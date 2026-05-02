"""
agents/research_engine.py
═══════════════════════════════════════════════════════════════════════════════
Full Proof-of-AI-Research (PoIR) pipeline:

  1. Fetch market question from 0G Storage (or IPFS fallback)
  2. Query 0G Compute (TeeML) → get LLM verdict + TEE signature
  3. Consult AXL peer signals (MCP market_intel service on each peer)
  4. Synthesise final verdict weighting own research + peer signals
  5. Archive full report to 0G Storage Log → get merkle root
  6. Record root on-chain via AgentRegistry.recordResearchReport()
  7. Return ResearchReceipt ready for castVerifiedVote()
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
from dataclasses import dataclass, asdict, field
from typing import Optional, Any

import aiohttp

from config import ZG_INFERENCE_MODEL, MIN_CONFIDENCE, AGENT_NAME
from services.axl_client      import AXLClient

log = logging.getLogger(__name__)

# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PeerSignal:
    peer_pubkey:   str
    agent_id:      int
    yes_prob:      float      # 0–1
    confidence:    float      # 0–1
    reasoning:     str
    reputation:    int        # on-chain rep score 0-100
    received_at:   int        # unix ts

@dataclass
class ResearchReceipt:
    market_address:    str
    question_uri:      str
    question_text:     str
    verdict:           str            # "YES" | "NO" | "INVALID"
    confidence:        float          # 0–1
    yes_probability:   float          # 0–1
    evidence_sources:  list[str]
    reasoning_chain:   str
    peer_signals:      list[PeerSignal]
    # PoIR fields
    tee_signature:     bytes          # 0G Compute TEE sig (empty if unavailable)
    model_used:        str
    storage_log_root:  str            # 0G Storage Log merkle root (hex)
    archived_at:       int            # unix ts
    agent_name:        str
    # Convenience
    choice_int:        int = 0        # 0=NO 1=YES 2=INVALID

    def __post_init__(self):
        self.choice_int = {"YES": 1, "NO": 0, "INVALID": 2}.get(self.verdict, 2)

# ─── System prompt ────────────────────────────────────────────────────────────

RESEARCH_SYSTEM_PROMPT = """\
You are an AI forecasting agent participating in a decentralised prediction market.
Your job is to determine whether a prediction market question resolved YES or NO.

You MUST respond with a single valid JSON object and nothing else. No preamble, no markdown.
Schema:
{
  "verdict":          "YES" | "NO" | "INVALID",
  "confidence":       <float 0.0–1.0>,
  "yes_probability":  <float 0.0–1.0>,
  "evidence_sources": [<url or description>, ...],
  "reasoning_chain":  "<step-by-step reasoning>",
  "data_gaps":        "<what information was missing or uncertain>"
}

Rules:
- Use "INVALID" only if the question is unanswerable or the resolution criteria are ambiguous.
- confidence = how certain you are of your verdict.
- yes_probability = estimated probability that the true answer is YES (regardless of your verdict).
- Be conservative. If confidence < 0.55, use INVALID.
- Cite at least 2 evidence sources if possible.
"""

# ─── ResearchEngine ───────────────────────────────────────────────────────────

class ResearchEngine:
    """
    Orchestrates the full PoIR research pipeline for a single market question.
    """

    def __init__(
        self,
        compute_client: Any,
        storage_client: Any,
        axl_client:     AXLClient,
        chain_client,                   # agents/chain.py ChainClient
    ):
        self.compute = compute_client
        self.storage = storage_client
        self.axl     = axl_client
        self.chain   = chain_client

    async def research(
        self,
        market_address: str,
        question_uri:   str,
        resolution_time: int,
        known_peers:    list[str] | None = None,
    ) -> ResearchReceipt:
        """
        Full pipeline. Returns a ResearchReceipt with PoIR fields populated.
        """
        log.info(f"[Research] Starting research for market {market_address[:10]}…")

        # ── Step 1: Fetch question ──────────────────────────────────────────
        question_data = await self._fetch_question(question_uri)
        question_text = question_data.get("question", question_uri)
        resolution_criteria = question_data.get("resolutionCriteria", "")
        category = question_data.get("category", "general")

        log.info(f"[Research] Question: {question_text[:80]}")

        # ── Step 2: Collect AXL peer signals ───────────────────────────────
        peer_signals: list[PeerSignal] = []
        if known_peers:
            peer_signals = await self._collect_peer_signals(
                market_address, known_peers
            )
            log.info(f"[Research] Received {len(peer_signals)} peer signals")

        # ── Step 3: 0G Compute inference (TeeML) ───────────────────────────
        prompt = self._build_prompt(
            question_text, resolution_criteria,
            resolution_time, category, peer_signals
        )

        compute_result = await self.compute.chat_completion(
            model=ZG_INFERENCE_MODEL,
            messages=[
                {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ]
        )

        # ── Step 4: Parse LLM response ─────────────────────────────────────
        parsed = self._parse_response(compute_result.content)
        verdict     = parsed.get("verdict", "INVALID")
        confidence  = float(parsed.get("confidence", 0.0))
        yes_prob    = float(parsed.get("yes_probability", 0.5))
        evidence    = parsed.get("evidence_sources", [])
        reasoning   = parsed.get("reasoning_chain", "")

        # Override to INVALID if confidence below threshold
        if confidence < MIN_CONFIDENCE:
            log.warning(f"[Research] Confidence {confidence:.2f} < {MIN_CONFIDENCE}, overriding to INVALID")
            verdict = "INVALID"

        log.info(f"[Research] Verdict={verdict} conf={confidence:.2f} yes_prob={yes_prob:.2f}")

        # ── Step 5: Build full report ──────────────────────────────────────
        report = {
            "schema_version":   "agentmarket/research/v1",
            "market_address":   market_address,
            "question_uri":     question_uri,
            "question_text":    question_text,
            "verdict":          verdict,
            "confidence":       confidence,
            "yes_probability":  yes_prob,
            "evidence_sources": evidence,
            "reasoning_chain":  reasoning,
            "data_gaps":        parsed.get("data_gaps", ""),
            "peer_signals":     [asdict(p) for p in peer_signals],
            "model":            compute_result.model_id,
            "tee_signature":    compute_result.tee_signature.hex() if compute_result.tee_signature else "",
            "tee_provider":     compute_result.provider,
            "agent":            AGENT_NAME,
            "timestamp":        int(time.time()),
            "resolution_time":  resolution_time,
        }

        # ── Step 6: Archive to 0G Storage Log ─────────────────────────────
        report_bytes    = json.dumps(report, indent=2).encode()
        storage_root    = await self.storage.upload_log(
            data=report_bytes,
            tags={"market": market_address, "type": "research_report", "verdict": verdict}
        )
        report["storage_log_root"] = storage_root
        archived_at = int(time.time())

        log.info(f"[Research] Archived to 0G Storage. Root: {storage_root[:20]}…")

        # ── Step 7: Record on-chain ────────────────────────────────────────
        try:
            await self.chain.record_research_report(storage_root)
            log.info(f"[Research] On-chain report root recorded")
        except Exception as e:
            log.warning(f"[Research] On-chain record failed (non-fatal): {e}")

        return ResearchReceipt(
            market_address   = market_address,
            question_uri     = question_uri,
            question_text    = question_text,
            verdict          = verdict,
            confidence       = confidence,
            yes_probability  = yes_prob,
            evidence_sources = evidence,
            reasoning_chain  = reasoning,
            peer_signals     = peer_signals,
            tee_signature    = compute_result.tee_signature or b"",
            model_used       = compute_result.model_id,
            storage_log_root = storage_root,
            archived_at      = archived_at,
            agent_name       = AGENT_NAME,
        )

    # ─── Private helpers ──────────────────────────────────────────────────────

    async def _fetch_question(self, uri: str) -> dict:
        """Fetch question JSON from 0G Storage or IPFS."""
        try:
            # Try 0G Storage first (preferred)
            if uri.startswith("0g://"):
                data = await self.storage.download(uri[5:])
                return json.loads(data)
            # IPFS gateway fallback
            gateway = f"https://ipfs.io/ipfs/{uri.replace('ipfs://', '')}"
            async with aiohttp.ClientSession() as session:
                async with session.get(gateway, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    return await r.json(content_type=None)
        except Exception as e:
            log.warning(f"[Research] Question fetch failed: {e}, using URI as text")
            return {"question": uri, "resolutionCriteria": "", "category": "general"}

    async def _collect_peer_signals(
        self, market_address: str, peers: list[str]
    ) -> list[PeerSignal]:
        """Query market_intel MCP service on each AXL peer in parallel."""
        tasks = [self._query_peer(market_address, p) for p in peers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, PeerSignal)]

    async def _query_peer(self, market_address: str, peer_pubkey: str) -> PeerSignal | None:
        """Query a single peer's market_intel MCP tool."""
        try:
            resp = await self.axl.mcp_call(
                peer_pubkey=peer_pubkey,
                service="market_intel",
                tool="get_probability",
                args={"market_address": market_address},
                timeout=8.0
            )
            d = json.loads(resp["result"]["content"][0]["text"])
            return PeerSignal(
                peer_pubkey  = peer_pubkey,
                agent_id     = d.get("agent_id", 0),
                yes_prob     = float(d.get("yes_probability", 0.5)),
                confidence   = float(d.get("confidence", 0.0)),
                reasoning    = d.get("reasoning_summary", ""),
                reputation   = int(d.get("agent_reputation", 50)),
                received_at  = int(time.time()),
            )
        except Exception as e:
            log.debug(f"[Research] Peer {peer_pubkey[:12]}… signal failed: {e}")
            return None

    def _build_prompt(
        self,
        question: str,
        resolution_criteria: str,
        resolution_time: int,
        category: str,
        peer_signals: list[PeerSignal],
    ) -> str:
        import datetime
        res_date = datetime.datetime.fromtimestamp(resolution_time).strftime("%Y-%m-%d %H:%M UTC")

        peer_section = ""
        if peer_signals:
            lines = []
            for p in peer_signals:
                lines.append(
                    f"  - Agent {p.agent_id} (rep={p.reputation}): "
                    f"P(YES)={p.yes_prob:.2f} conf={p.confidence:.2f} — {p.reasoning[:100]}"
                )
            peer_section = "\n\nPeer Agent Signals (from AXL network — treat as context, not authority):\n" + "\n".join(lines)

        return f"""\
Market question: {question}
Category: {category}
Resolution criteria: {resolution_criteria or "Standard market resolution as stated in the question."}
Resolution date/time: {res_date}
Current date: {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
{peer_section}

Research this question and return your verdict as JSON per the system instructions.
Focus on verifiable facts available up to the resolution date.
"""

    def _parse_response(self, content: str) -> dict:
        """Parse LLM JSON response with fallback."""
        try:
            # Strip any accidental markdown fences
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            return json.loads(clean.strip())
        except json.JSONDecodeError as e:
            log.warning(f"[Research] JSON parse failed: {e}. Raw: {content[:200]}")
            return {
                "verdict": "INVALID", "confidence": 0.0,
                "yes_probability": 0.5, "evidence_sources": [],
                "reasoning_chain": f"Parse error: {e}", "data_gaps": content[:200]
            }
