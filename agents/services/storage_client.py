"""
agents/services/storage_client.py
0G Storage client â€” KV (live state) and Log (immutable research archive).
"""

import json
import os
import time
import hashlib
import logging
import asyncio
import aiohttp
import tempfile
from pathlib import Path
from typing import Optional, Any

from config import (
    ZG_INDEXER_RPC, ZG_STORAGE_RPC, ZG_KV_RPC,
    ZG_KV_STREAM_ID, EVM_RPC_URL, AGENT_PRIVATE_KEY,
    ZG_STORAGE_MODE, ZG_STORAGE_UPLOAD_SCRIPT
)

log = logging.getLogger("storage")

# â”€â”€â”€ Key schema â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# All keys are deterministic so any agent can locate any other's data

def agent_state_key(agent_id: int)  -> str: return f"agent:{agent_id}:state"
def agent_memory_key(agent_id: int) -> str: return f"agent:{agent_id}:memory"
def market_odds_key(market: str)    -> str: return f"market:{market.lower()}:odds"
def market_meta_key(market: str)    -> str: return f"market:{market.lower()}:meta"
def resolution_tally_key(market: str) -> str: return f"resolution:{market.lower()}:tally"
def peer_estimate_key(agent_id: int, market: str) -> str:
    return f"signal:{agent_id}:{market.lower()}"


class ZeroGStorageClient:
    """
    Wraps 0G Storage SDK for:
      - KV Layer: mutable agent/market state (read/write)
      - Log Layer: append-only research archive (write-once, returns merkle root)

    Uses the 0g-ts-sdk compatible REST endpoints via aiohttp.
    For production: use the official Python SDK when released.
    """

    def __init__(self, stream_id: str = ""):
        self.indexer_rpc  = ZG_INDEXER_RPC
        self.storage_rpc  = ZG_STORAGE_RPC
        self.kv_rpc       = ZG_KV_RPC
        self.stream_id    = stream_id or ZG_KV_STREAM_ID
        self._api_key     = self._derive_api_key()
        log.info(f"0G Storage client ready â€” stream: {self.stream_id or 'not set'}")

    def _derive_api_key(self) -> str:
        h = hashlib.sha256(bytes.fromhex(AGENT_PRIVATE_KEY.removeprefix("0x")) + b"0g-storage-v1")
        return h.hexdigest()

    def _headers(self) -> dict:
        return {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    async def _upload_with_official_sdk(self, data: bytes) -> Optional[str]:
        """
        Upload through the official TypeScript SDK wrapper when Node can run it.
        0G's current public indexer upload path is SDK Indexer.upload(), not a
        simple /upload REST endpoint.
        """
        if ZG_STORAGE_MODE.lower() == "local":
            return None

        repo_root = Path(__file__).resolve().parents[2]
        script = Path(ZG_STORAGE_UPLOAD_SCRIPT) if ZG_STORAGE_UPLOAD_SCRIPT else repo_root / "scripts" / "zg-upload.mjs"
        sdk_dir = repo_root / "node_modules" / "@0gfoundation" / "0g-ts-sdk"
        if not script.exists():
            raise RuntimeError(f"0G SDK upload script is missing: {script}")
        if not sdk_dir.exists():
            raise RuntimeError("0G SDK package is missing. Run npm install before uploading to 0G Storage.")

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            env = os.environ.copy()
            env.update({
                "ZG_INDEXER_RPC": self.indexer_rpc,
                "EVM_RPC_URL": EVM_RPC_URL,
                "PRIVATE_KEY": AGENT_PRIVATE_KEY,
            })
            proc = await asyncio.create_subprocess_exec(
                "node",
                str(script),
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(repo_root),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
            if proc.returncode != 0:
                msg = stderr.decode(errors="ignore").strip() or stdout.decode(errors="ignore").strip()
                raise RuntimeError(f"0G SDK upload failed: {msg}")

            stdout_text = stdout.decode(errors="ignore").strip()
            json_line = next((line for line in reversed(stdout_text.splitlines()) if line.strip().startswith("{")), "")
            if not json_line:
                stderr_text = stderr.decode(errors="ignore").strip()
                raise RuntimeError(
                    "0G SDK upload did not return JSON"
                    + (f": {stderr_text}" if stderr_text else "")
                )
            result = json.loads(json_line)
            root = result.get("rootHash") or result.get("root")
            if root:
                log.info(f"Archived to 0G Storage SDK - root: {root}")
                return root
            raise RuntimeError(f"0G SDK upload returned no root hash: {json_line}")
        except asyncio.TimeoutError as e:
            raise RuntimeError("0G SDK upload timed out after 90 seconds") from e
        except Exception as e:
            raise RuntimeError(str(e)) from e
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # â”€â”€â”€ KV Layer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def kv_set(self, key: str, value: Any) -> bool:
        """Write a value to the 0G Storage KV layer."""
        data_bytes = json.dumps(value, default=str).encode()
        payload = {
            "stream_id": self.stream_id,
            "key":       key,
            "data":      data_bytes.hex(),
        }
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{self.kv_rpc}/kv/set",
                    json=payload, headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    ok = resp.status == 200
                    if not ok:
                        log.warning(f"KV set failed [{resp.status}] key={key}")
                    return ok
        except Exception as e:
            log.error(f"KV set error: {e}")
            return False

    async def kv_get(self, key: str) -> Optional[Any]:
        """Read a value from the 0G Storage KV layer."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{self.kv_rpc}/kv/get",
                    params={"stream_id": self.stream_id, "key": key},
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 404:
                        return None
                    data = await resp.json()
                    raw = bytes.fromhex(data.get("data", ""))
                    return json.loads(raw.decode())
        except Exception as e:
            log.error(f"KV get error key={key}: {e}")
            return None

    # â”€â”€â”€ Convenience KV wrappers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def update_agent_state(self, agent_id: int, state: dict) -> bool:
        state["_updatedAt"] = int(time.time())
        return await self.kv_set(agent_state_key(agent_id), state)

    async def get_agent_state(self, agent_id: int) -> Optional[dict]:
        return await self.kv_get(agent_state_key(agent_id))

    async def update_agent_memory(self, agent_id: int, memory: dict) -> bool:
        """Persistent agent memory â€” accumulated over all markets."""
        memory["_updatedAt"] = int(time.time())
        return await self.kv_set(agent_memory_key(agent_id), memory)

    async def get_agent_memory(self, agent_id: int) -> dict:
        mem = await self.kv_get(agent_memory_key(agent_id))
        return mem or {
            "markets_researched": 0,
            "correct_verdicts":   0,
            "total_verdicts":     0,
            "domain_performance": {},
            "trusted_sources":    [],
            "strategy_notes":     [],
        }

    async def update_market_odds(self, market: str, yes_pool: float, no_pool: float) -> bool:
        total = yes_pool + no_pool
        return await self.kv_set(market_odds_key(market), {
            "impliedYesPct": round(yes_pool / total * 100, 2) if total > 0 else 50.0,
            "yesPool":       yes_pool,
            "noPool":        no_pool,
            "totalPool":     total,
            "updatedAt":     int(time.time()),
        })

    async def get_market_odds(self, market: str) -> Optional[dict]:
        return await self.kv_get(market_odds_key(market))

    async def publish_peer_estimate(
        self, agent_id: int, market: str,
        yes_probability: float, confidence: float
    ) -> bool:
        """Publish this agent's probability estimate so peers can query it."""
        return await self.kv_set(peer_estimate_key(agent_id, market), {
            "agentId":        agent_id,
            "market":         market,
            "yesProbability": yes_probability,
            "confidence":     confidence,
            "publishedAt":    int(time.time()),
        })

    async def get_peer_estimate(self, peer_agent_id: int, market: str) -> Optional[dict]:
        return await self.kv_get(peer_estimate_key(peer_agent_id, market))

    async def update_resolution_tally(self, market: str, tally: dict) -> bool:
        return await self.kv_set(resolution_tally_key(market), {
            **tally, "updatedAt": int(time.time())
        })

    # â”€â”€â”€ Log Layer (immutable research archive) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def archive_research_report(self, report: dict) -> str:
        """
        Upload a research report to 0G Storage Log layer.
        Returns merkle root hash (used as on-chain PoIR commitment).
        This is append-only â€” once written, cannot be modified.
        """
        report_json  = json.dumps(report, indent=2, default=str).encode()
        if ZG_STORAGE_MODE.lower() == "local":
            root = self._local_merkle_root(report_json)
            log.info(f"Using explicit local 0G commitment mode - root: {root}")
            return root

        sdk_root = await self._upload_with_official_sdk(report_json)
        if not sdk_root:
            raise RuntimeError(
                "0G Storage SDK upload failed. This project requires real 0G Storage upload; "
                "set ZG_STORAGE_MODE=local only for offline unit tests."
            )
        return sdk_root

    async def retrieve_research_report(self, merkle_root: str) -> Optional[dict]:
        """Retrieve a research report from 0G Storage Log by merkle root."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{self.indexer_rpc}/retrieve",
                    params={"root": merkle_root},
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        raw  = bytes.fromhex(data.get("data", ""))
                        return json.loads(raw.decode())
                    return None
        except Exception as e:
            log.error(f"0G Log retrieve error: {e}")
            return None

    async def archive_agent_intelligence(self, agent_id: int, intelligence: dict) -> str:
        """
        Archive full agent intelligence package (for iNFT minting).
        Returns merkle root used as iNFT storage reference.
        """
        intelligence["agentId"]    = agent_id
        intelligence["archivedAt"] = int(time.time())
        return await self.archive_research_report(intelligence)

    def _local_merkle_root(self, data: bytes) -> str:
        """Offline test mode: SHA-256 commitment with the same hex shape as a root."""
        return "0x" + hashlib.sha256(data).hexdigest()

    # Compatibility methods used by older modules/tests
    async def upload_log(self, data: bytes, tags: Optional[dict] = None) -> str:
        try:
            payload = json.loads(data.decode())
        except Exception:
            payload = {"raw": data.hex(), "tags": tags or {}}
        root = await self.archive_research_report(payload)
        return root.removeprefix("0x")

    async def download(self, merkle_root: str) -> bytes:
        report = await self.retrieve_research_report(merkle_root)
        if report is None:
            return b"{}"
        return json.dumps(report).encode()

    async def create_kv_stream(self) -> str:
        if self.stream_id:
            return self.stream_id
        self.stream_id = f"stream-{int(time.time())}"
        return self.stream_id


class ZgStorageClient(ZeroGStorageClient):
    pass
