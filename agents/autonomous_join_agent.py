"""
Autonomous join agent for AgentMarket.

This entrypoint is meant for external builders joining the network. It wraps the
same production clients as agent.py, but exposes a clear CLI:

  python agents/autonomous_join_agent.py doctor
  python agents/autonomous_join_agent.py discover
  python agents/autonomous_join_agent.py think --market 0x...
  python agents/autonomous_join_agent.py run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(__file__))

from agent import AgentMarketAgent
from chain import ChainClient
from services.axl_client import AXLClient
from services.compute_client import ZeroGComputeClient
from services.storage_client import ZeroGStorageClient


@dataclass
class MarketThought:
    market: str
    state: str
    question_uri: str
    category: str
    implied_yes_pct: float
    action: str
    reason: str


class AutonomousJoinAgent:
    """Small operator-friendly wrapper around the full autonomous agent stack."""

    def __init__(self):
        self.chain = ChainClient()
        self.axl = AXLClient()
        self.storage = ZeroGStorageClient()
        self.compute = ZeroGComputeClient()

    async def doctor(self) -> None:
        print("\n=== Agent Doctor ===")
        print(f"wallet              {self.chain.address}")
        print(f"native 0G           {self.chain.native_balance_og():.6f}")
        print(f"PRED                {self.chain.pred_balance():.4f}")
        print(f"verified            {self.chain.is_verified()}")
        if self.chain.is_registered():
            info = self.chain.get_agent_info()
            print(f"agent id            {info[0]}")
            print(f"tier                {info[2]}")
            print(f"reputation          {info[4]}")
            print(f"iNFT token          {info[12]}")
            print(f"research reports    {info[13]}")
        await self.axl.discover_peers()
        print(f"AXL API             {self.axl.api_url}")
        print(f"AXL peers           {len(self.axl.known_peers)}")

    async def discover(self) -> list:
        print("\n=== Market Discovery ===")
        markets = self.chain.get_all_markets()
        thoughts = []
        for idx, record in enumerate(markets, start=1):
            market = record[0]
            state = self.chain.get_market_state(market)
            cfg = self.chain.get_market_config(market)
            yes = self.chain.get_implied_yes_pct(market)
            thought = self._think_from_market(market, state, cfg, yes)
            thoughts.append(thought)
            print(
                f"#{idx} {market} {state} {cfg['category']} "
                f"yes={yes:.2f}% action={thought.action} uri={cfg['questionURI']}"
            )
        return thoughts

    async def think(self, market: str) -> MarketThought:
        print("\n=== Agent Thinking ===")
        state = self.chain.get_market_state(market)
        cfg = self.chain.get_market_config(market)
        yes = self.chain.get_implied_yes_pct(market)
        peers = await self.axl.get_known_peers()
        print(f"market              {market}")
        print(f"state               {state}")
        print(f"question URI        {cfg['questionURI']}")
        print(f"category            {cfg['category']}")
        print(f"implied YES         {yes:.2f}%")
        print(f"known AXL peers     {len(peers)}")
        thought = self._think_from_market(market, state, cfg, yes)
        print(f"decision            {thought.action}")
        print(f"reason              {thought.reason}")
        return thought

    async def run(self) -> None:
        print("\n=== Starting Full Autonomous Agent ===")
        print("This mode onboards, discovers peers, researches, bets, votes, resolves, and updates iNFT state.")
        agent = AgentMarketAgent()
        await agent.run()

    def _think_from_market(self, market: str, state: str, cfg: dict, implied_yes_pct: float) -> MarketThought:
        now = int(time.time())
        if state == "OPEN" and now < cfg["resolutionTime"]:
            if cfg["category"] in self._domain_focus():
                return MarketThought(
                    market, state, cfg["questionURI"], cfg["category"], implied_yes_pct,
                    "research_then_maybe_bet",
                    "Market is open and matches this agent's domain focus.",
                )
            return MarketThought(
                market, state, cfg["questionURI"], cfg["category"], implied_yes_pct,
                "watch",
                "Market is open but outside this agent's configured domain focus.",
            )
        if state == "OPEN" and now >= cfg["resolutionTime"]:
            return MarketThought(
                market, state, cfg["questionURI"], cfg["category"], implied_yes_pct,
                "trigger_resolution",
                "Resolution time has passed and market is still open.",
            )
        if state == "RESOLVING":
            return MarketThought(
                market, state, cfg["questionURI"], cfg["category"], implied_yes_pct,
                "research_then_vote",
                "Voting is open or pending; agent should produce PoIR and vote.",
            )
        if state in ("RESOLVED", "INVALID"):
            return MarketThought(
                market, state, cfg["questionURI"], cfg["category"], implied_yes_pct,
                "claim_if_position",
                "Market is final; agent should claim winnings or refund if eligible.",
            )
        return MarketThought(market, state, cfg["questionURI"], cfg["category"], implied_yes_pct, "watch", "Unknown state.")

    def _domain_focus(self) -> set[str]:
        focus = os.getenv("AGENT_DOMAIN_FOCUS", "crypto,defi,macro")
        return {item.strip() for item in focus.split(",") if item.strip()}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Join AgentMarket as an autonomous agent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("discover")
    think = sub.add_parser("think")
    think.add_argument("--market", required=True)
    sub.add_parser("run")
    args = parser.parse_args()

    agent = AutonomousJoinAgent()
    if args.cmd == "doctor":
        await agent.doctor()
    elif args.cmd == "discover":
        await agent.discover()
    elif args.cmd == "think":
        await agent.think(args.market)
    elif args.cmd == "run":
        await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
