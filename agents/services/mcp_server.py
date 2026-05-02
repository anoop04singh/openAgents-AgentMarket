"""
agents/services/mcp_server.py
═══════════════════════════════════════════════════════════════════════════════
Flask-based MCP server that AXL routes inbound requests to.
Runs on :9003 (configured in axl-configs/node.json as router_port).

Exposes three MCP tools that other agents call via AXL:

  1. market_intel / get_probability
       → Returns this agent's probability estimate for a market
         (from 0G Storage KV live state or fresh research)

  2. vote_intention / get_vote_intention
       → Returns this agent's current research verdict for a resolving market
         (includes 0G Storage Log root so caller can verify the report)

  3. agent_info / get_agent_card
       → Returns ERC-8004 agent card + on-chain stats

All responses follow JSON-RPC 2.0 + MCP content format so AXL's
built-in MCP router can parse and forward them correctly.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from flask import Flask, jsonify, request

log = logging.getLogger("mcp_server")

app = Flask(__name__)

# ─── Shared state injected by agent.py on startup ─────────────────────────────
# These are set by calling mcp_server.set_state() before app.run()
_agent_state: dict = {
    "agent_id":      None,
    "wallet":        "",
    "agent_name":    "AgentMarket-Bot",
    "reputation":    50,
    "open_markets":  {},   # addr → market info + our estimate
    "voted_markets": {},   # addr → {verdict, confidence, storage_root}
    "inft_token_id": None,
    "chain":         None,  # ChainClient
    "storage":       None,  # ZgStorageClient
}


def set_state(state: dict):
    """Called by agent.py to inject live state into this server."""
    global _agent_state
    _agent_state.update(state)


# ─── MCP dispatch ─────────────────────────────────────────────────────────────

@app.route("/mcp", methods=["POST"])
def mcp_handler():
    """
    Single entry point. AXL MCP router sends all inbound calls here.
    Dispatches based on method + tool name.
    """
    req: dict = request.get_json(force=True, silent=True) or {}
    req_id  = req.get("id", 0)
    method  = req.get("method", "")
    params  = req.get("params", {})

    try:
        if method == "tools/list":
            return _tools_list(req_id)

        if method == "tools/call":
            tool_name = params.get("name", "")
            args      = params.get("arguments", {})
            return _tool_call(req_id, tool_name, args)

        return _error(req_id, -32601, f"Method not found: {method}")

    except Exception as e:
        log.exception(f"MCP error: {e}")
        return _error(req_id, -32603, str(e))


def _tools_list(req_id: Any):
    tools = [
        {
            "name":        "get_probability",
            "description": "Returns this agent's probability estimate for a binary prediction market.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "market_address": {"type": "string", "description": "Ethereum address of the PredictionMarket contract"}
                },
                "required": ["market_address"]
            }
        },
        {
            "name":        "get_vote_intention",
            "description": "Returns this agent's current resolution vote intention and supporting PoIR data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "market_address": {"type": "string", "description": "Ethereum address of the resolving market"}
                },
                "required": ["market_address"]
            }
        },
        {
            "name":        "get_agent_card",
            "description": "Returns ERC-8004 agent card and on-chain stats for this agent.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name":        "list_positions",
            "description": "Lists all open positions this agent holds across markets.",
            "inputSchema": {"type": "object", "properties": {}}
        },
    ]
    return jsonify({
        "jsonrpc": "2.0", "id": req_id,
        "result": {"tools": tools}
    })


def _tool_call(req_id: Any, tool_name: str, args: dict):
    if tool_name == "get_probability":
        return _get_probability(req_id, args.get("market_address", ""))

    if tool_name == "get_vote_intention":
        return _get_vote_intention(req_id, args.get("market_address", ""))

    if tool_name == "get_agent_card":
        return _get_agent_card(req_id)

    if tool_name == "list_positions":
        return _list_positions(req_id)

    return _error(req_id, -32601, f"Unknown tool: {tool_name}")


# ─── Tool implementations ─────────────────────────────────────────────────────

def _get_probability(req_id: Any, market_address: str):
    """
    Returns our probability estimate for a market.
    Pulled from 0G Storage KV live state if available.
    Falls back to on-chain implied probability.
    """
    if not market_address:
        return _error(req_id, -32602, "market_address required")

    market_info = _agent_state["open_markets"].get(market_address, {})
    estimate    = market_info.get("our_estimate", {})

    # Try live KV state first
    yes_prob   = estimate.get("yes_probability", None)
    confidence = estimate.get("confidence",     0.0)
    reasoning  = estimate.get("reasoning_summary", "No estimate available yet.")

    # Fallback: on-chain implied probability
    if yes_prob is None:
        try:
            chain = _agent_state.get("chain")
            if chain:
                yes_prob = chain.get_implied_yes_pct(market_address) / 100.0
            else:
                yes_prob = 0.5
        except Exception:
            yes_prob = 0.5

    result = {
        "market_address":     market_address,
        "yes_probability":    round(yes_prob, 4),
        "no_probability":     round(1.0 - yes_prob, 4),
        "confidence":         round(confidence, 4),
        "reasoning_summary":  reasoning[:200],
        "agent_id":           _agent_state.get("agent_id"),
        "agent_reputation":   _agent_state.get("reputation", 50),
        "model":              market_info.get("model_used", "unknown"),
        "storage_log_root":   estimate.get("storage_log_root", ""),
        "has_poir":           bool(estimate.get("tee_signature")),
        "timestamp":          int(time.time()),
    }

    return _ok(req_id, result)


def _get_vote_intention(req_id: Any, market_address: str):
    """
    Returns our current vote intention for a resolving market.
    Includes PoIR fields so the caller can independently verify the research.
    """
    if not market_address:
        return _error(req_id, -32602, "market_address required")

    voted = _agent_state.get("voted_markets", {}).get(market_address, {})

    if not voted:
        return _ok(req_id, {
            "market_address": market_address,
            "status":         "not_researched",
            "verdict":        None,
            "message":        "This agent has not yet researched this market.",
        })

    result = {
        "market_address":   market_address,
        "status":           "researched",
        "verdict":          voted.get("verdict"),           # "YES"/"NO"/"INVALID"
        "confidence":       voted.get("confidence", 0.0),
        "yes_probability":  voted.get("yes_probability", 0.5),
        "reasoning_summary":voted.get("reasoning_chain", "")[:300],
        "evidence_count":   len(voted.get("evidence_sources", [])),
        # PoIR
        "storage_log_root": voted.get("storage_log_root", ""),
        "tee_signature":    voted.get("tee_signature_hex", ""),
        "model_used":       voted.get("model_used", ""),
        "has_poir":         bool(voted.get("storage_log_root")),
        "agent_id":         _agent_state.get("agent_id"),
        "agent_reputation": _agent_state.get("reputation", 50),
        "researched_at":    voted.get("archived_at", 0),
    }

    return _ok(req_id, result)


def _get_agent_card(req_id: Any):
    """ERC-8004 compatible agent card."""
    chain = _agent_state.get("chain")
    agent_info = {}
    try:
        if chain:
            raw = chain.get_agent_info()
            agent_info = {
                "agentId":           raw[0],
                "tier":              raw[2],
                "reputationScore":   raw[4],
                "totalResolutions":  raw[5],
                "correctResolutions":raw[6],
                "researchReports":   raw[13],
                "inftTokenId":       raw[12],
            }
    except Exception:
        pass

    result = {
        "schema":       "erc8004/v1",
        "name":         _agent_state.get("agent_name", "AgentMarket-Bot"),
        "wallet":       _agent_state.get("wallet", ""),
        "agent_id":     _agent_state.get("agent_id"),
        "inft_token_id":_agent_state.get("inft_token_id"),
        "on_chain":     agent_info,
        "services": [
            {"name": "market_intel",   "tools": ["get_probability", "list_positions"]},
            {"name": "vote_intention", "tools": ["get_vote_intention"]},
        ],
        "trust_models": ["teeml-0g-compute", "on-chain-reputation"],
        "timestamp":    int(time.time()),
    }
    return _ok(req_id, result)


def _list_positions(req_id: Any):
    """List open positions from agent state."""
    chain = _agent_state.get("chain")
    positions = []

    try:
        if chain:
            for market_addr, info in _agent_state.get("open_markets", {}).items():
                yes_bal = 0
                no_bal  = 0
                try:
                    yes_bal = chain.market_contract(market_addr).functions.yesBalances(
                        chain.address
                    ).call() / 1e18
                    no_bal  = chain.market_contract(market_addr).functions.noBalances(
                        chain.address
                    ).call() / 1e18
                except Exception:
                    pass

                if yes_bal > 0 or no_bal > 0:
                    positions.append({
                        "market":       market_addr,
                        "yes_balance":  yes_bal,
                        "no_balance":   no_bal,
                        "category":     info.get("category", ""),
                        "questionURI":  info.get("questionURI", ""),
                    })
    except Exception as e:
        log.warning(f"list_positions error: {e}")

    return _ok(req_id, {"positions": positions, "count": len(positions)})


# ─── JSON-RPC helpers ─────────────────────────────────────────────────────────

def _ok(req_id: Any, data: dict):
    return jsonify({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(data)}]
        }
    })


def _error(req_id: Any, code: int, message: str):
    return jsonify({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message}
    }), 400


# ─── A2A endpoint (/.well-known/agent.json) ───────────────────────────────────

@app.route("/.well-known/agent.json")
def a2a_agent_json():
    """
    AXL A2A server auto-serves this endpoint.
    Exposes tool list so peers can auto-discover services.
    """
    return jsonify({
        "name":     _agent_state.get("agent_name", "AgentMarket-Bot"),
        "version":  "1.0.0",
        "services": [
            {
                "name":     "market_intel",
                "endpoint": "/mcp",
                "tools":    ["get_probability", "list_positions"],
            },
            {
                "name":     "vote_intention",
                "endpoint": "/mcp",
                "tools":    ["get_vote_intention"],
            },
        ],
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "agent_id": _agent_state.get("agent_id"), "ts": int(time.time())})


def run(port: int = 9003):
    log.info(f"MCP server starting on :{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    run()
