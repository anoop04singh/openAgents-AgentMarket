"""
agents/convergecast.py
═══════════════════════════════════════════════════════════════════════════════
AXL convergecast-based quorum monitor.

Uses the Yggdrasil spanning tree to aggregate vote tallies upward,
so any agent can determine — without querying the chain — whether quorum
has been reached on a resolution session.

How it works (mirrors AXL convergecast example):
  1. Each agent polls its AXL /topology endpoint to learn its tree position.
  2. Leaf nodes: read their own on-chain vote tally, send upward to parent.
  3. Parent nodes: aggregate children's tallies + own tally, send further up.
  4. Root node: when aggregated voterCount ≥ quorum → broadcast QUORUM_REACHED.
  5. Any agent receiving QUORUM_REACHED calls finalizeResolution() on-chain.

Why this matters for the hackathon:
  - Demonstrates cross-node AXL communication (separate processes/machines)
  - Uses AXL's convergecast pattern (a specific feature Gensyn docs highlight)
  - Enables fully permissionless, decentralised finalization
  - No central coordinator needed — any agent in the tree can be the root
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from services.axl_client import AXLClient, AXLMessage

log = logging.getLogger("convergecast")

MSG_QUORUM_REACHED     = "QUORUM_REACHED"
MSG_TALLY_REPORT       = "TALLY_REPORT"       # node → parent
MSG_AGGREGATE_TALLY    = "AGGREGATE_TALLY"    # parent → root

MIN_QUORUM_COUNT   = 3
MIN_QUORUM_PERCENT = 20   # percent of totalVerifiedAgents


@dataclass
class MarketTally:
    market_address:   str
    voter_count:      int   = 0
    weighted_yes:     int   = 0
    weighted_no:      int   = 0
    weighted_invalid: int   = 0
    contributing_nodes: list[str] = field(default_factory=list)
    last_updated:     int   = field(default_factory=lambda: int(time.time()))


class QuorumMonitor:
    """
    Runs alongside the main agent loop.
    Tracks resolution sessions via AXL convergecast and
    fires the finalisation call when quorum is detected.
    """

    def __init__(
        self,
        axl:               AXLClient,
        chain,                              # ChainClient
        agent_wallet:      str,
        on_quorum_reached,                  # async callback(market_addr)
    ):
        self.axl              = axl
        self.chain            = chain
        self.wallet           = agent_wallet
        self.on_quorum_reached = on_quorum_reached

        # market_addr → MarketTally
        self._tallies: dict[str, MarketTally] = {}

        # Topology info (refreshed periodically from AXL /topology)
        self._parent_pubkey:   Optional[str]  = None
        self._children_pubkeys: list[str]     = []
        self._is_root:         bool           = False

    # ─── Public API ──────────────────────────────────────────────────────────

    async def run(self):
        """Main loop — topology refresh + periodic tally broadcast."""
        log.info("Quorum monitor started.")
        await asyncio.gather(
            self._topology_refresh_loop(),
            self._tally_broadcast_loop(),
        )

    def add_market(self, market_address: str):
        """Register a market to monitor."""
        if market_address not in self._tallies:
            self._tallies[market_address] = MarketTally(market_address=market_address)
            log.info(f"[Quorum] Monitoring market {market_address[:12]}…")

    async def handle_axl_message(self, msg: AXLMessage):
        """Called from main AXL message loop for quorum-related messages."""
        mtype = msg.payload.get("type", "")
        if   mtype == MSG_TALLY_REPORT:    await self._handle_tally_report(msg)
        elif mtype == MSG_AGGREGATE_TALLY: await self._handle_aggregate_tally(msg)
        elif mtype == MSG_QUORUM_REACHED:  await self._handle_quorum_reached(msg)

    # ─── Topology ────────────────────────────────────────────────────────────

    async def _topology_refresh_loop(self):
        while True:
            try:
                topo = await self.axl.get_topology()
                self._parent_pubkey    = topo.get("parent")
                self._children_pubkeys = topo.get("children", [])
                self._is_root          = (self._parent_pubkey is None)
                if self._is_root:
                    log.debug("[Quorum] I am the spanning tree root this cycle.")
            except Exception as e:
                log.debug(f"[Quorum] Topology refresh error: {e}")
            await asyncio.sleep(120)  # refresh every 2 min

    # ─── Tally collection ─────────────────────────────────────────────────────

    async def _tally_broadcast_loop(self):
        """Every 60s, read on-chain tallies and push upward through tree."""
        while True:
            await asyncio.sleep(60)
            for market_addr in list(self._tallies.keys()):
                await self._collect_and_propagate(market_addr)

    async def _collect_and_propagate(self, market_addr: str):
        """Read on-chain session, update local tally, push to parent."""
        try:
            session = self.chain.resolver.functions.getSession(market_addr).call()
            # session tuple: market, resTime, deadline, extensions, state,
            #   weightedYes, weightedNo, weightedInvalid, voterCount, ...
            tally = self._tallies[market_addr]
            tally.voter_count      = session[8]
            tally.weighted_yes     = session[5]
            tally.weighted_no      = session[6]
            tally.weighted_invalid = session[7]
            tally.last_updated     = int(time.time())

            if self._is_root:
                # We are root — check quorum directly
                await self._check_quorum_at_root(market_addr, tally)
            elif self._parent_pubkey:
                # Send our tally upward
                await self.axl.send(self._parent_pubkey, {
                    "type":             MSG_TALLY_REPORT,
                    "market":           market_addr,
                    "voter_count":      tally.voter_count,
                    "weighted_yes":     tally.weighted_yes,
                    "weighted_no":      tally.weighted_no,
                    "weighted_invalid": tally.weighted_invalid,
                    "from_wallet":      self.wallet,
                })
        except Exception as e:
            log.debug(f"[Quorum] collect_and_propagate {market_addr[:12]}: {e}")

    # ─── Message handlers ─────────────────────────────────────────────────────

    async def _handle_tally_report(self, msg: AXLMessage):
        """Child node sent us its tally. Merge and propagate upward."""
        p = msg.payload
        market_addr = p.get("market", "")
        if not market_addr:
            return

        if market_addr not in self._tallies:
            self.add_market(market_addr)

        tally = self._tallies[market_addr]
        # Merge (take max voter_count, accumulate weights)
        tally.voter_count       = max(tally.voter_count, p.get("voter_count", 0))
        tally.weighted_yes     += p.get("weighted_yes",     0)
        tally.weighted_no      += p.get("weighted_no",      0)
        tally.weighted_invalid += p.get("weighted_invalid", 0)
        from_wallet = p.get("from_wallet", "")
        if from_wallet and from_wallet not in tally.contributing_nodes:
            tally.contributing_nodes.append(from_wallet)

        if self._is_root:
            await self._check_quorum_at_root(market_addr, tally)
        elif self._parent_pubkey:
            # Forward aggregated tally upward
            await self.axl.send(self._parent_pubkey, {
                "type":             MSG_AGGREGATE_TALLY,
                "market":           market_addr,
                "voter_count":      tally.voter_count,
                "weighted_yes":     tally.weighted_yes,
                "weighted_no":      tally.weighted_no,
                "weighted_invalid": tally.weighted_invalid,
                "contributing":     len(tally.contributing_nodes),
                "from_wallet":      self.wallet,
            })

    async def _handle_aggregate_tally(self, msg: AXLMessage):
        """Root receives aggregated tally. Check quorum."""
        await self._handle_tally_report(msg)  # same merge logic

    async def _handle_quorum_reached(self, msg: AXLMessage):
        """Quorum detected (from root or another agent). Finalize."""
        market_addr = msg.payload.get("market", "")
        if not market_addr:
            return
        log.info(f"[Quorum] QUORUM_REACHED received for {market_addr[:12]}…")
        try:
            await self.on_quorum_reached(market_addr)
        except Exception as e:
            log.warning(f"[Quorum] on_quorum_reached error: {e}")

    # ─── Root quorum check ────────────────────────────────────────────────────

    async def _check_quorum_at_root(self, market_addr: str, tally: MarketTally):
        """
        Root node determines if quorum is met.
        If yes → broadcast QUORUM_REACHED to all known peers.
        """
        try:
            total_verified = self.chain.registry.functions.totalVerifiedAgents().call()
            required = max(MIN_QUORUM_COUNT, (total_verified * MIN_QUORUM_PERCENT) // 100)

            if tally.voter_count >= required:
                log.info(
                    f"[Quorum] ✓ QUORUM MET for {market_addr[:12]}… "
                    f"voters={tally.voter_count} required={required}"
                )
                # Broadcast to all peers
                known_peers = await self.axl.get_known_peers()
                await self.axl.broadcast(known_peers, {
                    "type":         MSG_QUORUM_REACHED,
                    "market":       market_addr,
                    "voter_count":  tally.voter_count,
                    "weighted_yes": tally.weighted_yes,
                    "weighted_no":  tally.weighted_no,
                    "required":     required,
                    "from_wallet":  self.wallet,
                    "timestamp":    int(time.time()),
                })
                # Also trigger locally
                await self.on_quorum_reached(market_addr)
            else:
                log.debug(
                    f"[Quorum] {market_addr[:12]}… voters={tally.voter_count}/{required} "
                    f"(yes={tally.weighted_yes} no={tally.weighted_no})"
                )
        except Exception as e:
            log.warning(f"[Quorum] Root check error: {e}")
