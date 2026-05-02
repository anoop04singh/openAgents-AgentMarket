"""
agents/config.py
Centralised configuration for all AgentMarket agents.
Loaded from environment variables + agents/config.yaml.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ─── Contract addresses (set after deployment) ────────────────────────────────
PRED_TOKEN_ADDRESS        = os.getenv("PRED_TOKEN_ADDRESS",        "0x0")
POSITION_TOKEN_ADDRESS    = os.getenv("POSITION_TOKEN_ADDRESS",    "0x0")
AGENT_REGISTRY_ADDRESS    = os.getenv("AGENT_REGISTRY_ADDRESS",    "0x0")
MARKET_FACTORY_ADDRESS    = os.getenv("MARKET_FACTORY_ADDRESS",    "0x0")
COLLECTIVE_RESOLVER_ADDRESS = os.getenv("COLLECTIVE_RESOLVER_ADDRESS", "0x0")

# ─── Chain ────────────────────────────────────────────────────────────────────
EVM_RPC_URL   = os.getenv("EVM_RPC_URL",   "https://evmrpc-testnet.0g.ai")  # 0G Galileo testnet
CHAIN_ID      = int(os.getenv("CHAIN_ID",  "16602"))                          # 0G Galileo chain ID

# ─── 0G Storage ───────────────────────────────────────────────────────────────
ZG_INDEXER_RPC    = os.getenv("ZG_INDEXER_RPC",    "https://indexer-storage-testnet-turbo.0g.ai")
ZG_STORAGE_RPC    = os.getenv("ZG_STORAGE_RPC",    "https://indexer-storage-testnet-turbo.0g.ai")
ZG_KV_RPC         = os.getenv("ZG_KV_RPC",         "https://rpc-kv-testnet.0g.ai")
ZG_KV_STREAM_ID   = os.getenv("ZG_KV_STREAM_ID",   "")  # agent creates on first run
ZG_STORAGE_MODE   = os.getenv("ZG_STORAGE_MODE",   "sdk")  # sdk | local
ZG_STORAGE_UPLOAD_SCRIPT = os.getenv("ZG_STORAGE_UPLOAD_SCRIPT", "")
ZG_CHAIN_RPC      = os.getenv("ZG_CHAIN_RPC", EVM_RPC_URL)
INFT_CONTRACT     = os.getenv("INFT_CONTRACT", "0x0000000000000000000000000000000000000000")
INFT_INTEGRATION_MODE = os.getenv("INFT_INTEGRATION_MODE", "og_guide")

# ─── 0G Compute ───────────────────────────────────────────────────────────────
ZG_BROKER_URL     = os.getenv("ZG_BROKER_URL", os.getenv("ZG_COMPUTE_BROKER", "https://api.inference.0g.ai"))
ZG_COMPUTE_MODEL  = os.getenv("ZG_COMPUTE_MODEL", os.getenv("ZG_INFERENCE_MODEL", "deepseek-chat-v3-0324"))  # TeeML verified
ZG_COMPUTE_BROKER = os.getenv("ZG_COMPUTE_BROKER", ZG_BROKER_URL)
ZG_INFERENCE_MODEL = os.getenv("ZG_INFERENCE_MODEL", ZG_COMPUTE_MODEL)

# ─── AXL ──────────────────────────────────────────────────────────────────────
AXL_API_URL       = os.getenv("AXL_API_URL", os.getenv("AXL_API_BASE", "http://127.0.0.1:9002"))
AXL_API_BASE      = os.getenv("AXL_API_BASE", AXL_API_URL)
AXL_MCP_PORT      = int(os.getenv("AXL_MCP_PORT",  "9003"))
AXL_A2A_PORT      = int(os.getenv("AXL_A2A_PORT",  "9004"))
AXL_BOOTSTRAP_PEER = os.getenv("AXL_BOOTSTRAP_PEER", "")   # base58 pubkey of bootstrap node

# ─── Agent identity ───────────────────────────────────────────────────────────
AGENT_PRIVATE_KEY    = os.getenv("AGENT_PRIVATE_KEY",    "")
AGENT_NAME           = os.getenv("AGENT_NAME",           "AgentMarket-Agent")
AGENT_DESCRIPTION    = os.getenv("AGENT_DESCRIPTION",    "Autonomous AI prediction market agent")
AGENT_DOMAIN_FOCUS   = os.getenv("AGENT_DOMAIN_FOCUS",   "crypto,defi,macro")  # comma-separated
PRIVATE_KEY          = os.getenv("PRIVATE_KEY", AGENT_PRIVATE_KEY)

# ─── Betting strategy ─────────────────────────────────────────────────────────
MIN_BET_AMOUNT_PRED  = float(os.getenv("MIN_BET_AMOUNT",   "1.0"))
MAX_BET_AMOUNT_PRED  = float(os.getenv("MAX_BET_AMOUNT",   "100.0"))
MIN_BET_CONFIDENCE   = float(os.getenv("MIN_BET_CONFIDENCE","0.65"))  # skip bet below this
MIN_VOTE_CONFIDENCE  = float(os.getenv("MIN_VOTE_CONFIDENCE","0.60"))  # skip vote below this
MIN_CONFIDENCE       = float(os.getenv("MIN_CONFIDENCE", str(MIN_BET_CONFIDENCE)))
MAX_STAKE_PCT        = float(os.getenv("MAX_STAKE_PCT",    "0.10"))   # max 10% of balance per bet
PEER_SIGNAL_WEIGHT   = float(os.getenv("PEER_SIGNAL_WEIGHT","0.25"))  # weight of AXL peer signals
REQUIRE_POIR         = os.getenv("REQUIRE_POIR", "false").lower() in ("1", "true", "yes")

ADDRESSES = {
    "PRED_TOKEN_ADDRESS": PRED_TOKEN_ADDRESS,
    "POSITION_TOKEN_ADDRESS": POSITION_TOKEN_ADDRESS,
    "AGENT_REGISTRY_ADDRESS": AGENT_REGISTRY_ADDRESS,
    "MARKET_FACTORY_ADDRESS": MARKET_FACTORY_ADDRESS,
    "COLLECTIVE_RESOLVER_ADDRESS": COLLECTIVE_RESOLVER_ADDRESS,
}

# ─── Timing ───────────────────────────────────────────────────────────────────
POLL_INTERVAL_SEC       = int(os.getenv("POLL_INTERVAL",        "30"))
RESOLUTION_POLL_SEC     = int(os.getenv("RESOLUTION_POLL",      "60"))
AXL_RECV_POLL_SEC       = int(os.getenv("AXL_RECV_POLL",        "5"))
TX_CONFIRM_TIMEOUT_SEC  = int(os.getenv("TX_CONFIRM_TIMEOUT",   "120"))
DEMO_MIN_NATIVE_OG      = float(os.getenv("DEMO_MIN_NATIVE_OG",  "0.01"))


@dataclass
class ResearchReceipt:
    market_address:    str
    question_uri:      str
    question_text:     str
    verdict:           str          # "YES" | "NO" | "INVALID"
    confidence:        float        # 0.0 – 1.0
    evidence_sources:  list
    reasoning:         str
    tee_signature:     str          # hex — from 0G Compute
    model_used:        str
    timestamp:         int
    agent_id:          int
    storage_log_root:  str = ""     # set after archiving to 0G Storage Log
    axl_peer_signals:  list = field(default_factory=list)


@dataclass
class AXLMessage:
    type:          str           # MARKET_CREATED | RESOLUTION_OPEN | VOTE_INTENTION | QUORUM_REACHED | FINALIZED
    market:        str
    timestamp:     int
    sender_pubkey: str
    sender_agent_id: int
    payload:       dict


# AXL message type constants
MSG_MARKET_CREATED   = "MARKET_CREATED"
MSG_RESOLUTION_OPEN  = "RESOLUTION_OPEN"
MSG_VOTE_INTENTION   = "VOTE_INTENTION"
MSG_QUORUM_REACHED   = "QUORUM_REACHED"
MSG_FINALIZED        = "FINALIZED"
MSG_BET_PLACED       = "BET_PLACED"
MSG_PEER_SIGNAL_REQ  = "PEER_SIGNAL_REQUEST"
MSG_PEER_SIGNAL_RESP = "PEER_SIGNAL_RESPONSE"
