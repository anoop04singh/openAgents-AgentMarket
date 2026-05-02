"""
agents/market_creator.py
═══════════════════════════════════════════════════════════════════════════════
Standalone market-creator agent.
Demonstrates the full market creation flow:
  1. Builds a structured question JSON
  2. Uploads it to 0G Storage Log → gets content-addressed URI
  3. Calls MarketFactory.createMarket() on-chain
  4. Broadcasts MARKET_CREATED over AXL to all peers

Run with:
  python market_creator.py --question "Will ETH exceed $5000 by Dec 31 2025?" \
                           --category crypto \
                           --days 30

Or import and call create_market() programmatically from the main agent loop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from config import (
    EVM_RPC_URL, PRIVATE_KEY, ADDRESSES,
    ZG_STORAGE_RPC, ZG_INDEXER_RPC, ZG_KV_RPC,
    AXL_API_BASE, DEMO_MIN_NATIVE_OG,
)
from chain import ChainClient
from services.storage_client import ZgStorageClient
from services.axl_client     import AXLClient

log = logging.getLogger("market_creator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")


def update_dashboard_metadata_cache(market_addr: str, question_uri: str, question_data: dict) -> None:
    """Keep the local dashboard cache in sync with the real 0G-uploaded question JSON."""
    try:
        root = Path(__file__).resolve().parents[1]
        public_dir = root / "public"
        public_dir.mkdir(exist_ok=True)
        cache_path = public_dir / "market-metadata.json"
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        else:
            cache = {}
        cache[market_addr] = {
            **question_data,
            "market": market_addr,
            "questionURI": question_uri,
            "syncedAt": int(time.time()),
        }
        cache_path.write_text(json.dumps(cache, indent=2, default=str), encoding="utf-8")
        log.info(f"Dashboard metadata cache updated: {cache_path}")
    except Exception as e:
        log.warning(f"Could not update dashboard metadata cache: {e}")


async def ensure_creator_registered(chain: ChainClient, storage: ZgStorageClient) -> None:
    try:
        agent_id = chain.get_agent_id()
        if agent_id:
            info = chain.get_agent_info()
            log.info(
                "Creator registry state: agentId=%s tier=%s stake=%.2f slashed=%s verified=%s",
                agent_id,
                info[2],
                info[3] / 1e18,
                info[9],
                chain.is_verified(),
            )
    except Exception as e:
        log.warning(f"Could not read creator registry state: {e}")

    if chain.is_verified():
        log.info("Creator agent already verified on-chain")
        return

    log.info("Creator agent not verified; registering before seeding markets...")
    agent_card = {
        "schema": "agentmarket/agent-card/v1",
        "name": "AgentMarket-Creator",
        "description": "Demo creator agent for 0G x AXL autonomous prediction markets",
        "wallet": chain.address,
        "services": ["market_intel", "vote_intention"],
        "createdAt": int(time.time()),
    }
    card_root = await storage.archive_research_report(agent_card)
    kv_stream_id = f"agentmarket-{chain.address.lower()}"
    chain.ensure_verified_agent(card_root, 1_000.0, kv_stream_id)
    log.info("Creator agent registration confirmed")


async def create_market(
    question:         str,
    resolution_criteria: str,
    category:         str,
    resolution_days:  int,
    min_bet_pred:     float = 1.0,
    peers:            list[str] | None = None,
    chain:            ChainClient | None = None,
    storage:          ZgStorageClient | None = None,
    axl:              AXLClient | None = None,
    ensure_registered: bool = True,
) -> str:
    """
    Full market creation pipeline.
    Returns the deployed market contract address.
    """
    chain = chain or ChainClient()
    wallet = chain.account
    storage = storage or ZgStorageClient()
    axl = axl or AXLClient()
    if ensure_registered:
        await ensure_creator_registered(chain, storage)

    resolution_time = int(time.time()) + resolution_days * 86400

    # ── Step 1: Build structured question JSON ────────────────────────────────
    question_data = {
        "schema":              "agentmarket/question/v1",
        "question":            question,
        "resolutionCriteria":  resolution_criteria or _default_criteria(question),
        "category":            category,
        "resolutionTime":      resolution_time,
        "resolutionDate":      _fmt_ts(resolution_time),
        "outcomes":            ["NO", "YES"],
        "minBet":              min_bet_pred,
        "creator":             wallet.address,
        "createdAt":           int(time.time()),
        "version":             "1.0.0",
    }

    log.info(f"Question: {question}")
    log.info(f"Resolves: {_fmt_ts(resolution_time)} ({resolution_days} days)")

    # ── Step 2: Upload question to 0G Storage Log ─────────────────────────────
    q_bytes = json.dumps(question_data, indent=2).encode()
    log.info("Uploading question to 0G Storage Log…")
    question_root = await storage.upload_log(
        data=q_bytes,
        tags={"type": "question", "category": category}
    )
    question_uri = f"0g://{question_root}"
    log.info(f"Question URI: {question_uri[:40]}…")

    # ── Step 3: Create market on-chain ────────────────────────────────────────
    log.info("Creating market on-chain via MarketFactory…")
    market_addr = chain.create_market(
        question_uri    = question_uri,
        resolution_time = resolution_time,
        category        = category,
        min_bet_pred    = min_bet_pred,
    )
    log.info(f"✓ Market deployed: {market_addr}")
    update_dashboard_metadata_cache(market_addr, question_uri, question_data)

    # ── Step 4: Broadcast via AXL ─────────────────────────────────────────────
    if peers:
        announcement = {
            "type":           "MARKET_CREATED",
            "market":         market_addr,
            "questionURI":    question_uri,
            "question":       question[:120],
            "category":       category,
            "resolutionTime": resolution_time,
            "minBet":         min_bet_pred,
            "creator":        wallet.address,
            "timestamp":      int(time.time()),
        }
        await axl.broadcast("MARKET_CREATED", market_addr, announcement)
        log.info(f"Broadcast MARKET_CREATED to {len(peers)} peers via AXL")

    return market_addr


def _default_criteria(question: str) -> str:
    return (
        f"This market resolves YES if the following statement is true as of "
        f"the resolution date: '{question}'. "
        f"It resolves NO otherwise. INVALID if the outcome cannot be determined."
    )


def _fmt_ts(ts: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")


# ─── Demo market catalogue ────────────────────────────────────────────────────

DEMO_MARKETS = [
    {
        "question":            "Will ETH price exceed $5,000 USD by end of this month?",
        "resolution_criteria": "Resolves YES if ETH/USD closing price on any major CEX (Binance, Coinbase, Kraken) exceeds $5,000 before the resolution timestamp.",
        "category":            "crypto",
        "resolution_days":     30,
    },
    {
        "question":            "Will Bitcoin dominance stay above 55% for the next 14 days?",
        "resolution_criteria": "Resolves YES if CoinMarketCap Bitcoin dominance index remains above 55% continuously for 14 days from market creation.",
        "category":            "crypto",
        "resolution_days":     14,
    },
    {
        "question":            "Will total DeFi TVL exceed $150 billion within 7 days?",
        "resolution_criteria": "Resolves YES if DefiLlama total TVL (all chains) crosses $150B USD at any point within 7 days of market creation.",
        "category":            "defi",
        "resolution_days":     7,
    },
    {
        "question":            "Will the Federal Reserve cut interest rates at its next meeting?",
        "resolution_criteria": "Resolves YES if the FOMC announces a federal funds rate reduction at its next scheduled meeting after market creation.",
        "category":            "macro",
        "resolution_days":     60,
    },
]


async def seed_demo_markets(peers: list[str] | None = None):
    """Create the full set of demo markets for the hackathon showcase."""
    log.info(f"Seeding {len(DEMO_MARKETS)} demo markets…")
    chain = ChainClient()
    storage = ZgStorageClient()
    axl = AXLClient()
    chain.require_native_budget(DEMO_MIN_NATIVE_OG, "demo market seeding")
    await ensure_creator_registered(chain, storage)

    addresses = []
    for m in DEMO_MARKETS:
        try:
            addr = await create_market(
                question            = m["question"],
                resolution_criteria = m["resolution_criteria"],
                category            = m["category"],
                resolution_days     = m["resolution_days"],
                peers               = peers,
                chain               = chain,
                storage             = storage,
                axl                 = axl,
                ensure_registered   = False,
            )
            addresses.append({"market": addr, "question": m["question"]})
            await asyncio.sleep(5)  # avoid nonce collisions
        except Exception as e:
            log.error(f"Failed to create market: {e}")

    log.info("=== Demo Markets ===")
    for a in addresses:
        log.info(f"  {a['market']} — {a['question'][:60]}")
    if not addresses:
        raise RuntimeError("No demo markets were created")
    return addresses


# ─── CLI ─────────────────────────────────────────────────────────────────────

async def _cli():
    parser = argparse.ArgumentParser(description="AgentMarket — create a prediction market")
    sub = parser.add_subparsers(dest="cmd")

    # create subcommand
    create = sub.add_parser("create", help="Create a single market")
    create.add_argument("--question",   required=True)
    create.add_argument("--criteria",   default="")
    create.add_argument("--category",   default="general")
    create.add_argument("--days",       type=int, default=30)
    create.add_argument("--min-bet",    type=float, default=1.0)

    # seed subcommand
    sub.add_parser("seed", help="Seed all demo markets")

    args = parser.parse_args()

    if args.cmd == "create":
        addr = await create_market(
            question            = args.question,
            resolution_criteria = args.criteria,
            category            = args.category,
            resolution_days     = args.days,
            min_bet_pred        = args.min_bet,
        )
        print(f"\nMarket deployed: {addr}")

    elif args.cmd == "seed":
        await seed_demo_markets()

    else:
        parser.print_help()


if __name__ == "__main__":
    if not PRIVATE_KEY:
        print("ERROR: AGENT_PRIVATE_KEY not set")
        sys.exit(1)
    asyncio.run(_cli())
