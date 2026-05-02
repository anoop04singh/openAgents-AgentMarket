"""
agents/services/compute_client.py
0G Compute Network client — calls TeeML-verified LLM inference.
Returns structured research receipt with TEE signature.
"""

import json
import time
import logging
import hashlib
import aiohttp
import asyncio
from dataclasses import dataclass
from typing import Optional

from config import ZG_BROKER_URL, ZG_COMPUTE_MODEL, AGENT_PRIVATE_KEY

log = logging.getLogger("compute")

# ─── System prompt for market research ────────────────────────────────────────

RESEARCH_SYSTEM_PROMPT = """You are an autonomous AI prediction market research agent.
Your job is to research a specific yes/no question and provide a well-reasoned verdict.

You must:
1. Analyse the question carefully and identify what needs to be verified
2. Consider the resolution criteria and timeframe
3. Apply logical reasoning based on known facts and patterns
4. Return a structured JSON response ONLY — no prose outside the JSON

Your output must be valid JSON matching this exact schema:
{
  "verdict": "YES" | "NO" | "INVALID",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<2–3 sentence summary of reasoning>",
  "evidence_sources": ["<source1>", "<source2>"],
  "key_factors": ["<factor1>", "<factor2>"],
  "uncertainty_notes": "<anything that reduces your confidence>"
}

Only output INVALID if the question is unanswerable, ambiguous, or the resolution
criteria cannot be evaluated. Do not guess — if confidence < 0.5, say INVALID.
"""

PEER_SIGNAL_SYSTEM_PROMPT = """You are aggregating market intelligence signals from peer AI agents.
Given multiple probability estimates for a market question, synthesise a final estimate.
Return JSON only: {"consensus_yes": <float 0-1>, "agreement_level": <float 0-1>, "outliers": <int>}
"""


class ZeroGComputeClient:
    """
    Client for 0G Compute Network (TeeML verified inference).

    In production: uses 0G's on-chain payment settlement + TEE attestation.
    For hackathon demo: authenticates with API key derived from wallet private key.
    """

    def __init__(self):
        self.broker_url = ZG_BROKER_URL
        self.model      = ZG_COMPUTE_MODEL
        # Derive API credentials from wallet (no separate key needed)
        self._api_key   = self._derive_api_key()
        log.info(f"0G Compute client ready — model: {self.model}")

    def _derive_api_key(self) -> str:
        """Derive a deterministic API key from the agent's private key."""
        h = hashlib.sha256(bytes.fromhex(AGENT_PRIVATE_KEY.removeprefix("0x")) + b"0g-compute-v1")
        return h.hexdigest()

    async def research_market(
        self,
        question_text: str,
        resolution_criteria: str,
        resolution_time: int,
        category: str,
        market_address: str,
        peer_signals: Optional[list] = None
    ) -> dict:
        """
        Call 0G Compute TeeML model to research a market question.
        Returns dict with verdict, confidence, reasoning, tee_signature.
        """
        peer_context = ""
        if peer_signals:
            avg_yes = sum(s.get("yes_probability", 0.5) for s in peer_signals) / len(peer_signals)
            peer_context = f"\n\nPeer AI agent signals (for awareness only, not for copying): average YES probability from {len(peer_signals)} peers = {avg_yes:.2f}"

        user_prompt = f"""Market Question: {question_text}

Resolution Criteria: {resolution_criteria}
Resolution Timestamp: {resolution_time} (Unix)
Category: {category}
Market Address: {market_address}
{peer_context}

Research this question and provide your independent verdict as JSON."""

        payload = {
            "model":    self.model,
            "messages": [
                {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt}
            ],
            "temperature": 0.1,    # low temperature for factual research
            "max_tokens":  800,
            "stream":      False,
        }

        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-Model-Attestation": "teeml",   # request TEE-attested response
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.broker_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        log.error(f"0G Compute error {resp.status}: {text}")
                        return self._fallback_research(question_text)

                    data = await resp.json()

            content   = data["choices"][0]["message"]["content"]
            # Strip any markdown fencing
            content   = content.strip().removeprefix("```json").removesuffix("```").strip()
            result    = json.loads(content)

            # Extract TEE signature from response headers / attestation field
            tee_sig = data.get("attestation", {}).get("tee_signature", "")
            if not tee_sig:
                # Fallback: compute a deterministic mock signature for demo
                tee_sig = self._mock_tee_signature(content, market_address)

            return {
                "verdict":          result.get("verdict", "INVALID"),
                "confidence":       float(result.get("confidence", 0.5)),
                "reasoning":        result.get("reasoning", ""),
                "evidence_sources": result.get("evidence_sources", []),
                "key_factors":      result.get("key_factors", []),
                "uncertainty_notes":result.get("uncertainty_notes", ""),
                "tee_signature":    tee_sig,
                "model_used":       self.model,
                "raw_response":     content,
            }

        except json.JSONDecodeError as e:
            log.warning(f"Failed to parse model response as JSON: {e}")
            return self._fallback_research(question_text)
        except Exception as e:
            log.error(f"0G Compute call failed: {e}")
            return self._fallback_research(question_text)

    async def get_peer_consensus(self, peer_signals: list) -> dict:
        """Synthesise multiple peer signals into a consensus estimate."""
        if not peer_signals:
            return {"consensus_yes": 0.5, "agreement_level": 0.0, "outliers": 0}

        payload = {
            "model":    self.model,
            "messages": [
                {"role": "system", "content": PEER_SIGNAL_SYSTEM_PROMPT},
                {"role": "user",   "content": json.dumps(peer_signals)}
            ],
            "temperature": 0.0,
            "max_tokens":  100,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.broker_url}/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    data = await resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            content = content.removeprefix("```json").removesuffix("```").strip()
            return json.loads(content)
        except Exception as e:
            log.warning(f"Peer consensus call failed: {e}")
            # Manual calculation fallback
            yes_vals = [s.get("yes_probability", 0.5) for s in peer_signals]
            avg = sum(yes_vals) / len(yes_vals)
            std = (sum((v - avg) ** 2 for v in yes_vals) / len(yes_vals)) ** 0.5
            return {
                "consensus_yes":   round(avg, 3),
                "agreement_level": round(max(0, 1 - std * 2), 3),
                "outliers":        sum(1 for v in yes_vals if abs(v - avg) > 0.25)
            }

    def _mock_tee_signature(self, content: str, market_addr: str) -> str:
        """
        For demo purposes: HMAC-SHA256 of content keyed by private key.
        In production: real TEE attestation from 0G Compute node.
        """
        import hmac
        key = bytes.fromhex(AGENT_PRIVATE_KEY.removeprefix("0x"))
        msg = (content + market_addr).encode()
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    def _fallback_research(self, question_text: str) -> dict:
        """Called when 0G Compute is unreachable — returns INVALID so agent abstains."""
        log.warning("Using fallback research — INVALID verdict")
        return {
            "verdict":          "INVALID",
            "confidence":       0.0,
            "reasoning":        "Could not reach 0G Compute inference node",
            "evidence_sources": [],
            "key_factors":      [],
            "uncertainty_notes":"Compute node unavailable",
            "tee_signature":    "",
            "model_used":       "fallback",
            "raw_response":     "",
        }


@dataclass
class ComputeResult:
    content: str
    tee_signature: bytes
    model_id: str
    provider: str


class ZgComputeClient(ZeroGComputeClient):
    async def chat_completion(self, model: str, messages: list[dict]) -> ComputeResult:
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = msg.get("content", "")
                break
        result = await self.research_market(
            question_text=user_text,
            resolution_criteria="",
            resolution_time=int(time.time()) + 3600,
            category="general",
            market_address="0x" + "00" * 20,
            peer_signals=[],
        )
        tee = bytes.fromhex(result.get("tee_signature", "")) if result.get("tee_signature") else b""
        content = json.dumps({
            "verdict": result.get("verdict", "INVALID"),
            "confidence": result.get("confidence", 0.0),
            "yes_probability": 0.5 if result.get("verdict") == "INVALID" else (result.get("confidence", 0.5) if result.get("verdict") == "YES" else 1 - result.get("confidence", 0.5)),
            "evidence_sources": result.get("evidence_sources", []),
            "reasoning_chain": result.get("reasoning", ""),
            "data_gaps": result.get("uncertainty_notes", ""),
        })
        return ComputeResult(
            content=content,
            tee_signature=tee,
            model_id=result.get("model_used", model),
            provider="0g-compute-teeml",
        )
