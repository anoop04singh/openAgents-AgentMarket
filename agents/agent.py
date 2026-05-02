"""
agents/agent.py
Main autonomous agent process.
Orchestrates: onboarding → market discovery → betting → resolution voting → claiming.
Integrates: 0G Compute (research) · 0G Storage KV+Log · AXL (P2P) · iNFT (identity).
"""

import asyncio
import logging
import time
import json
import sys
import os
from typing import Optional

# Add parent dir to path
sys.path.insert(0, os.path.dirname(__file__))

from config import (
    AGENT_NAME, AGENT_PRIVATE_KEY, AGENT_DOMAIN_FOCUS,
    MIN_BET_CONFIDENCE, MIN_VOTE_CONFIDENCE,
    MIN_BET_AMOUNT_PRED, MAX_BET_AMOUNT_PRED, MAX_STAKE_PCT,
    PEER_SIGNAL_WEIGHT, POLL_INTERVAL_SEC,
    MSG_MARKET_CREATED, MSG_RESOLUTION_OPEN, MSG_VOTE_INTENTION,
    MSG_QUORUM_REACHED, MSG_FINALIZED,
)
from chain import ChainClient
from services.compute_client  import ZeroGComputeClient
from services.storage_client  import ZeroGStorageClient
from services.axl_client      import AXLClient, MCPServiceServer
from services.inft_client     import INFTClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-14s] %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("agent.log")]
)
log = logging.getLogger("agent")


class AgentMarketAgent:
    """
    Fully autonomous AI prediction market agent.

    Lifecycle per market:
      OPEN      → research + bet
      RESOLVING → research + cast_verified_vote (with PoIR)
      RESOLVED  → claim winnings + update iNFT intelligence
    """

    def __init__(self):
        self.chain   = ChainClient()
        self.compute = ZeroGComputeClient()
        self.storage = ZeroGStorageClient()
        self.axl     = AXLClient()
        self.inft    = INFTClient(self.chain)

        # Runtime state (also persisted in 0G KV)
        self.agent_id:    int  = 0
        self.inft_id:     int  = 0
        self.rep_score:   int  = 50
        self.balance:     float = 0.0
        self.axl_pubkey:  str  = ""
        self.research_count: int = 0

        # Per-market tracking
        self.probability_estimates: dict = {}   # market → {yes_probability, confidence}
        self.pending_votes:         dict = {}   # market → {choice, confidence}
        self.resolution_tallies:    dict = {}   # market → tally dict
        self.processed_bets:        set  = set()
        self.processed_votes:       set  = set()

        # Register MCP service — exposes this agent's data to AXL peers
        self._mcp = MCPServiceServer(self._get_state_snapshot)
        self._mcp.start_background()

    # ─── State snapshot (fed to MCP server) ──────────────────────────────────

    def _get_state_snapshot(self) -> dict:
        return {
            "agent_id":              self.agent_id,
            "address":               self.chain.address,
            "axl_pubkey":            self.axl_pubkey,
            "reputation_score":      self.rep_score,
            "research_reports_count":self.research_count,
            "probability_estimates": self.probability_estimates,
            "pending_votes":         self.pending_votes,
            "resolution_tallies":    self.resolution_tallies,
        }

    # ─── Onboarding ───────────────────────────────────────────────────────────

    async def onboard(self):
        """Register on-chain if not yet verified. Mint iNFT. Connect AXL."""
        log.info(f"=== Onboarding {AGENT_NAME} ===")

        self.balance    = self.chain.pred_balance()
        self.axl_pubkey = await self.axl.get_own_pubkey()
        log.info(f"Wallet: {self.chain.address} | Balance: {self.balance:.2f} PRED")

        if not self.chain.is_verified():
            log.info("Agent not registered — registering now...")

            # Build ERC-8004 agent card
            agent_card = {
                "name":        AGENT_NAME,
                "description": "Autonomous AI prediction market agent using 0G Compute + AXL",
                "version":     "1.0",
                "wallet":      self.chain.address,
                "domains":     AGENT_DOMAIN_FOCUS.split(","),
                "services": [
                    {
                        "name":     "market_intel",
                        "protocol": "axl-mcp",
                        "endpoint": f"mcp://axl/{self.axl_pubkey}",
                        "tools":    ["get_probability", "get_resolution_tally"]
                    },
                    {
                        "name":     "vote_intention",
                        "protocol": "axl-mcp",
                        "endpoint": f"mcp://axl/{self.axl_pubkey}",
                        "tools":    ["get_vote"]
                    }
                ],
                "trustModels": ["teeml", "0g-storage-log"],
            }

            # Upload agent card to 0G Storage Log (immutable identity record)
            card_root = await self.storage.archive_research_report(agent_card)
            log.info(f"Agent card archived to 0G Storage — root: {card_root}")

            # Create 0G KV stream for live state
            kv_stream_id = f"agentmarket-{self.chain.address.lower()}"
            await self.storage.update_agent_state(0, {"bootstrap": True})

            # Register on-chain (stake 1000 PRED for VERIFIED tier)
            stake = 1_000.0
            if self.balance < stake + 10:
                log.error(f"Insufficient PRED: need {stake}, have {self.balance:.2f}")
                raise RuntimeError("Insufficient PRED balance for registration")

            self.chain.register_agent(card_root, stake, kv_stream_id)
            log.info("On-chain registration confirmed ✓")

        self.agent_id  = self.chain.get_agent_id()
        agent_info     = self.chain.get_agent_info()
        self.rep_score = agent_info[4]   # reputationScore field
        self.research_count = agent_info[13]  # researchReportsCount
        self.inft_id   = agent_info[12]  # inftTokenId

        log.info(f"Agent ID: {self.agent_id} | Rep: {self.rep_score} | iNFT: {self.inft_id}")

        # Mint iNFT if not done yet
        if self.inft_id == 0:
            await self._mint_inft()

        # Connect AXL and discover peers
        await self.axl.discover_peers()
        self._register_axl_handlers()
        log.info(f"AXL connected — {len(self.axl.known_peers)} peers")

        # Persist initial state to 0G KV
        await self.storage.update_agent_state(self.agent_id, {
            "agentId":    self.agent_id,
            "address":    self.chain.address,
            "repScore":   self.rep_score,
            "inftId":     self.inft_id,
            "status":     "ACTIVE",
        })

        log.info(f"=== {AGENT_NAME} ready ===\n")

    async def _mint_inft(self):
        """Mint initial iNFT on 0G Chain."""
        log.info("Minting iNFT...")
        memory    = await self.storage.get_agent_memory(self.agent_id)
        intel     = self.inft.build_intelligence_payload(
            agent_id=self.agent_id,
            agent_address=self.chain.address,
            reputation_score=self.rep_score,
            correct_verdicts=0,
            total_verdicts=0,
            domain_focus=AGENT_DOMAIN_FOCUS.split(","),
            memory=memory,
            storage_log_root="0x" + "00" * 32,
            axl_pubkey=self.axl_pubkey,
        )
        intel_root = await self.storage.archive_agent_intelligence(self.agent_id, intel)
        token_id   = await self.inft.mint_agent(self.agent_id, intel_root, intel)

        if token_id:
            self.inft_id = token_id
            self.chain.link_inft(token_id)
            log.info(f"iNFT minted — token ID: {token_id}")
            log.info(f"View on AIverse: {self.inft.get_aiverse_listing_url(token_id)}")

    # ─── AXL message handlers ─────────────────────────────────────────────────

    def _register_axl_handlers(self):

        @self.axl.on_message(MSG_MARKET_CREATED)
        async def on_market_created(msg: dict):
            market  = msg["market"]
            payload = msg.get("payload", {})
            log.info(f"[AXL] New market: {market[:12]}... category={payload.get('category')}")
            # Queue for research + bet on next poll cycle
            # (avoids re-processing markets we already know about)

        @self.axl.on_message(MSG_RESOLUTION_OPEN)
        async def on_resolution_open(msg: dict):
            market   = msg["market"]
            deadline = msg.get("payload", {}).get("votingDeadline", 0)
            log.info(f"[AXL] Resolution open: {market[:12]}... deadline={deadline}")
            # Immediately begin research
            asyncio.create_task(self._handle_resolution(market))

        @self.axl.on_message(MSG_QUORUM_REACHED)
        async def on_quorum_reached(msg: dict):
            market = msg["market"]
            log.info(f"[AXL] Quorum reached for {market[:12]}... — attempting finalize")
            asyncio.create_task(self._try_finalize(market))

        @self.axl.on_message(MSG_FINALIZED)
        async def on_finalized(msg: dict):
            market  = msg["market"]
            outcome = msg.get("payload", {}).get("outcome", "?")
            log.info(f"[AXL] Market finalized: {market[:12]}... outcome={outcome}")
            asyncio.create_task(self._try_claim(market))

    # ─── Main loop ────────────────────────────────────────────────────────────

    async def run(self):
        """Main event loop. Runs indefinitely."""
        await self.onboard()

        # Start AXL recv polling in background
        axl_task = asyncio.create_task(self.axl.poll_recv())

        log.info("Agent running — polling every %ds", POLL_INTERVAL_SEC)

        try:
            while True:
                try:
                    await self._poll_cycle()
                except Exception as e:
                    log.error(f"Poll cycle error: {e}", exc_info=True)
                await asyncio.sleep(POLL_INTERVAL_SEC)
        finally:
            axl_task.cancel()

    async def _poll_cycle(self):
        """One full poll cycle: check all markets and act appropriately."""
        self.balance = self.chain.pred_balance()
        markets      = self.chain.get_all_markets()

        for record in markets:
            market_addr = record[0]
            if not market_addr or market_addr == "0x" + "0" * 40:
                continue
            state = self.chain.get_market_state(market_addr)
            await self._handle_market(market_addr, state)

    # ─── Market handling ──────────────────────────────────────────────────────

    async def _handle_market(self, market_addr: str, state: str):
        if state == "OPEN":
            await self._maybe_bet(market_addr)
            await self._maybe_trigger_resolution(market_addr)

        elif state == "RESOLVING":
            await self._handle_resolution(market_addr)

        elif state == "RESOLVED":
            await self._try_claim(market_addr)
            await self._try_distribute_rewards(market_addr)
            await self._try_return_stake(market_addr)

    # ─── Betting ──────────────────────────────────────────────────────────────

    async def _maybe_bet(self, market_addr: str):
        if market_addr in self.processed_bets:
            return

        cfg       = self.chain.get_market_config(market_addr)
        yes_pct   = self.chain.get_implied_yes_pct(market_addr)
        resolution_time = cfg["resolutionTime"]

        # Skip if betting window is closed
        if time.time() >= resolution_time:
            return

        log.info(f"Researching market {market_addr[:12]}... (implied YES: {yes_pct:.1f}%)")

        # 1. Gather peer signals via AXL MCP
        peer_signals = await self.axl.gather_peer_market_signals(
            market_addr, cfg.get("questionURI", "")
        )

        # 2. Run 0G Compute inference
        research = await self.compute.research_market(
            question_text        = cfg.get("questionURI", "Unknown question"),
            resolution_criteria  = "See questionURI",
            resolution_time      = resolution_time,
            category             = cfg.get("category", "general"),
            market_address       = market_addr,
            peer_signals         = peer_signals,
        )

        verdict    = research["verdict"]
        confidence = research["confidence"]

        log.info(f"Research complete: {verdict} (conf={confidence:.2f})")

        # Publish estimate to 0G KV for peers
        yes_prob = confidence if verdict == "YES" else (1 - confidence if verdict == "NO" else 0.5)
        await self.storage.publish_peer_estimate(self.agent_id, market_addr, yes_prob, confidence)
        self.probability_estimates[market_addr] = {
            "yes_probability": yes_prob, "confidence": confidence
        }

        if verdict == "INVALID" or confidence < MIN_BET_CONFIDENCE:
            log.info(f"Skipping bet — confidence too low ({confidence:.2f})")
            self.processed_bets.add(market_addr)
            return

        # 3. Blend with peer consensus
        if peer_signals:
            consensus = await self.compute.get_peer_consensus(peer_signals)
            peer_yes  = consensus.get("consensus_yes", 0.5)
            agreement = consensus.get("agreement_level", 0.0)
            blended   = (1 - PEER_SIGNAL_WEIGHT) * yes_prob + PEER_SIGNAL_WEIGHT * peer_yes
            log.info(f"Peer consensus: {peer_yes:.2f} (agreement={agreement:.2f}) → blended: {blended:.2f}")
            yes_prob = blended

        # 4. Size bet (Kelly-ish: proportional to edge and balance)
        outcome  = 1 if yes_prob > 0.5 else 0
        edge     = abs(yes_prob - 0.5) * 2     # 0 → no edge, 1 → maximum edge
        bet_size = min(
            self.balance * MAX_STAKE_PCT * edge,
            MAX_BET_AMOUNT_PRED
        )
        bet_size = max(bet_size, MIN_BET_AMOUNT_PRED)

        if bet_size > self.balance * 0.8:
            log.warning("Bet size would exceed 80% of balance — capping")
            bet_size = self.balance * 0.1

        log.info(f"Placing bet: {'YES' if outcome==1 else 'NO'} {bet_size:.2f} PRED on {market_addr[:12]}...")

        try:
            tx = self.chain.place_bet(market_addr, outcome, bet_size)
            log.info(f"Bet placed ✓ tx={tx[:16]}...")
            self.processed_bets.add(market_addr)

            # Broadcast to AXL peers
            await self.axl.broadcast(
                "BET_PLACED", market_addr,
                {"outcome": outcome, "amount": bet_size, "agentId": self.agent_id}
            )

            # Update 0G KV with new market odds
            yes_pool, no_pool = self.chain.get_market_pools(market_addr)
            await self.storage.update_market_odds(market_addr, yes_pool, no_pool)

        except Exception as e:
            log.error(f"Bet failed: {e}")

    # ─── Resolution trigger ───────────────────────────────────────────────────

    async def _maybe_trigger_resolution(self, market_addr: str):
        cfg = self.chain.get_market_config(market_addr)
        if time.time() < cfg["resolutionTime"]:
            return
        try:
            log.info(f"Triggering resolution for {market_addr[:12]}...")
            self.chain.trigger_resolution(market_addr)
            await self.axl.announce_resolution_open(
                market_addr,
                int(time.time()) + 48 * 3600,
                self.chain.get_market_pools(market_addr)[0] + self.chain.get_market_pools(market_addr)[1]
            )
        except Exception as e:
            # Likely already triggered — not an error
            log.debug(f"trigger_resolution: {e}")

    # ─── Resolution voting ────────────────────────────────────────────────────

    async def _handle_resolution(self, market_addr: str):
        if market_addr in self.processed_votes:
            return
        if not self.chain.is_voting_open(market_addr):
            return
        if self.chain.already_voted(market_addr):
            self.processed_votes.add(market_addr)
            return

        log.info(f"=== Resolution research: {market_addr[:12]}... ===")

        # Gather peer vote intentions via AXL
        peer_intentions = []
        for peer_pk in self.axl.known_peers[:5]:  # query up to 5 peers
            intention = await self.axl.query_peer_vote_intention(peer_pk, market_addr)
            if intention and intention.get("choice"):
                peer_intentions.append(intention)

        cfg = self.chain.get_market_config(market_addr)

        # 0G Compute — run fresh inference for resolution
        research = await self.compute.research_market(
            question_text        = cfg.get("questionURI", ""),
            resolution_criteria  = "Evaluate if the event occurred as stated",
            resolution_time      = cfg.get("resolutionTime", 0),
            category             = cfg.get("category", "general"),
            market_address       = market_addr,
        )

        verdict    = research["verdict"]
        confidence = research["confidence"]
        tee_sig    = research["tee_signature"]

        log.info(f"Resolution verdict: {verdict} (conf={confidence:.2f}, teePoIR={'yes' if tee_sig else 'no'})")

        if confidence < MIN_VOTE_CONFIDENCE:
            log.info(f"Confidence too low ({confidence:.2f}) — voting INVALID")
            verdict = "INVALID"

        # ── PoIR: archive research to 0G Storage Log ──────────────────────────
        report = {
            "market_address":    market_addr,
            "question_uri":      cfg.get("questionURI", ""),
            "verdict":           verdict,
            "confidence":        confidence,
            "reasoning":         research["reasoning"],
            "evidence_sources":  research["evidence_sources"],
            "tee_signature":     tee_sig,
            "model_used":        research["model_used"],
            "timestamp":         int(time.time()),
            "agent_id":          self.agent_id,
            "peer_intentions_considered": peer_intentions,
        }
        storage_root = await self.storage.archive_research_report(report)
        log.info(f"Research archived → 0G Storage Log root: {storage_root}")

        # Record on-chain (AgentRegistry)
        try:
            self.chain.record_research_report(storage_root)
        except Exception as e:
            log.warning(f"recordResearchReport chain call failed: {e}")

        # ── Cast verified vote ─────────────────────────────────────────────────
        choice_map = {"YES": 1, "NO": 0, "INVALID": 2}
        choice     = choice_map.get(verdict, 2)

        # Broadcast intention before voting (AXL deliberation)
        await self.axl.broadcast_vote_intention(market_addr, verdict, confidence)
        self.pending_votes[market_addr] = {"choice": verdict, "confidence": confidence}

        # Small delay — give peers time to deliberate
        await asyncio.sleep(5)

        try:
            tx = self.chain.cast_verified_vote(market_addr, choice, storage_root, tee_sig)
            log.info(f"Vote cast ✓ tx={tx[:16]}... (PoIR attached: {bool(storage_root)})")
            self.processed_votes.add(market_addr)
            self.research_count += 1
        except Exception as e:
            log.error(f"Vote cast failed: {e}")
            return

        # ── Check if we should finalize ────────────────────────────────────────
        await asyncio.sleep(3)
        tally = await self.axl.convergecast_tally(market_addr)
        await self.storage.update_resolution_tally(market_addr, tally)
        self.resolution_tallies[market_addr] = tally

        total_verified = self.chain.resolver.functions.getActiveSessions().call()
        await self._try_finalize(market_addr)

    # ─── Finalization ─────────────────────────────────────────────────────────

    async def _try_finalize(self, market_addr: str):
        if self.chain.is_voting_open(market_addr):
            return   # still open
        try:
            tx = self.chain.finalize_resolution(market_addr)
            log.info(f"Resolution finalized ✓ tx={tx[:16]}...")
            probs = self.chain.get_vote_probabilities(market_addr)
            outcome = "YES" if probs["yes"] > probs["no"] else "NO"
            await self.axl.announce_finalized(market_addr, outcome)
        except Exception as e:
            log.debug(f"finalize not ready: {e}")

    async def _try_distribute_rewards(self, market_addr: str):
        try:
            session = self.chain.resolver.functions.getSession(
                self.chain.w3.to_checksum_address(market_addr)
            ).call()
            if session[10] and not session[12] and session[11] > 0:  # finalized, not distributed, has rewards
                self.chain.distribute_rewards(market_addr)
                log.info(f"Rewards distributed for {market_addr[:12]}...")
        except Exception as e:
            log.debug(f"distribute_rewards: {e}")

    async def _try_claim(self, market_addr: str):
        try:
            state = self.chain.get_market_state(market_addr)
            mkt   = self.chain.market_contract(market_addr)

            if state == "RESOLVED":
                yes_bal = mkt.functions.yesBalances(self.chain.address).call()
                no_bal  = mkt.functions.noBalances(self.chain.address).call()
                if yes_bal > 0 or no_bal > 0:
                    tx = self.chain.claim_winnings(market_addr)
                    log.info(f"Winnings claimed ✓ tx={tx[:16]}...")
                    await self._update_inft_after_resolution(market_addr)

            elif state == "INVALID":
                tx = mkt.functions.claimRefund()
                log.info(f"Refund claimed for invalid market {market_addr[:12]}...")

        except Exception as e:
            log.debug(f"claim: {e}")

    async def _try_return_stake(self, market_addr: str):
        try:
            cfg = self.chain.get_market_config(market_addr)
            if cfg.get("creator", "").lower() == self.chain.address.lower():
                self.chain.factory.functions.returnCreatorStake(market_addr)
                log.info(f"Creator stake returned for {market_addr[:12]}...")
        except:
            pass

    # ─── iNFT intelligence update ─────────────────────────────────────────────

    async def _update_inft_after_resolution(self, market_addr: str):
        """Update agent's iNFT with new research data after each resolution."""
        if self.inft_id == 0:
            return
        try:
            memory = await self.storage.get_agent_memory(self.agent_id)
            memory["markets_researched"] = memory.get("markets_researched", 0) + 1

            agent_info = self.chain.get_agent_info()
            correct    = agent_info[6]   # correctResolutions
            total      = agent_info[5]   # totalResolutions
            new_root   = agent_info[10]  # storageLogRoot as bytes32 → hex

            memory["correct_verdicts"] = correct
            memory["total_verdicts"]   = total
            memory["accuracy_rate"]    = round(correct / total, 4) if total > 0 else 0.5

            await self.storage.update_agent_memory(self.agent_id, memory)
            storage_root = new_root.hex() if isinstance(new_root, bytes) else str(new_root)
            await self.inft.update_intelligence(self.inft_id, storage_root, memory)

            log.info(f"iNFT intelligence updated — accuracy: {memory['accuracy_rate']:.1%}")
        except Exception as e:
            log.warning(f"iNFT update failed: {e}")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv()

    agent = AgentMarketAgent()

    log.info(f"Starting {AGENT_NAME}")
    log.info(f"Wallet: {agent.chain.address}")
    asyncio.run(agent.run())
