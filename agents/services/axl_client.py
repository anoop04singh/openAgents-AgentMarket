"""
agents/services/axl_client.py
AXL (Agent Exchange Layer) client.
Handles:
  - Fire-and-forget broadcast (send/recv)
  - MCP service calls to peers (request/response)
  - Convergecast for quorum aggregation
  - A2A agent discovery
"""

import json
import time
import asyncio
import logging
import aiohttp
from dataclasses import dataclass
from typing import Optional, Callable, List
from flask import Flask, request, jsonify
from threading import Thread

from config import (
    AXL_API_URL, AXL_MCP_PORT, AXL_A2A_PORT,
    AGENT_NAME, AGENT_DESCRIPTION, AGENT_DOMAIN_FOCUS,
    MSG_MARKET_CREATED, MSG_RESOLUTION_OPEN, MSG_VOTE_INTENTION,
    MSG_QUORUM_REACHED, MSG_FINALIZED, MSG_BET_PLACED,
    MSG_PEER_SIGNAL_REQ, MSG_PEER_SIGNAL_RESP,
)

log = logging.getLogger("axl")


@dataclass
class AXLMessage:
    type: str
    market: str
    timestamp: int
    sender_pubkey: str
    sender_agent_id: int
    payload: dict

# ─── Message envelope ─────────────────────────────────────────────────────────

def make_envelope(msg_type: str, market: str, agent_id: int, payload: dict) -> dict:
    return {
        "axl_protocol":     "agentmarket/v1",
        "type":             msg_type,
        "market":           market,
        "timestamp":        int(time.time()),
        "sender_agent_id":  agent_id,
        "payload":          payload,
    }


class AXLClient:
    """
    Thin wrapper around the AXL node HTTP API.
    AXL node must be running locally on AXL_API_URL (default :9002).
    """

    def __init__(self, agent_id: int = 0, agent_address: str = ""):
        self.api_url      = AXL_API_URL
        self.agent_id     = agent_id
        self.agent_address = agent_address
        self.known_peers: List[str] = []   # AXL public keys of known peers
        self._handlers: dict = {}          # msg_type → async callable
        self._running = False
        log.info(f"AXL client ready — API: {self.api_url}")

    # ─── Peer management ─────────────────────────────────────────────────────

    def add_peer(self, peer_pubkey: str):
        if peer_pubkey not in self.known_peers:
            self.known_peers.append(peer_pubkey)
            log.info(f"Peer registered: {peer_pubkey[:16]}...")

    async def discover_peers(self):
        """Query AXL topology endpoint for connected peers."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.api_url}/topology",
                                 timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        peers = data.get("peers", [])
                        for p in peers:
                            if isinstance(p, dict):
                                pk = p.get("public_key") or p.get("peer_id") or p.get("id")
                            else:
                                pk = str(p)
                            if pk:
                                self.add_peer(pk)
                        log.info(f"Discovered {len(peers)} peers via topology")
        except Exception as e:
            log.warning(f"Peer discovery failed: {e}")

    async def get_topology(self) -> dict:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.api_url}/topology",
                                 timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        return {"parent": None, "children": []}
                    data = await resp.json()
                    if "parent" in data or "children" in data:
                        children = []
                        for c in data.get("children", []):
                            if isinstance(c, dict):
                                pk = c.get("public_key") or c.get("peer_id") or c.get("id")
                            else:
                                pk = str(c)
                            if pk:
                                children.append(pk)
                        parent = data.get("parent")
                        if isinstance(parent, dict):
                            parent = parent.get("public_key") or parent.get("peer_id") or parent.get("id")
                        return {"parent": parent, "children": children}
                    peers = data.get("peers", [])
                    children = []
                    for p in peers:
                        if isinstance(p, dict):
                            pk = p.get("public_key") or p.get("peer_id") or p.get("id")
                        else:
                            pk = str(p)
                        if pk:
                            children.append(pk)
                    return {"parent": None, "children": children}
        except Exception:
            return {"parent": None, "children": []}

    async def get_known_peers(self) -> list[str]:
        if not self.known_peers:
            await self.discover_peers()
        return list(self.known_peers)

    async def get_own_pubkey(self) -> str:
        """Get this node's AXL public key."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.api_url}/topology") as resp:
                    data = await resp.json()
                    return data.get("our_public_key", "") or data.get("public_key", "")
        except:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(f"{self.api_url}/identity") as resp:
                        data = await resp.json()
                        return data.get("public_key", "")
            except:
                return ""

    # ─── Send ─────────────────────────────────────────────────────────────────

    async def send(self, peer_pubkey: str, msg_type, market: str = "", payload: dict | None = None):
        """Send a fire-and-forget message to a specific peer."""
        if isinstance(msg_type, dict):
            envelope = msg_type
        else:
            envelope = make_envelope(msg_type, market, self.agent_id, payload or {})
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{self.api_url}/send",
                    data=json.dumps(envelope),
                    headers={
                        "Content-Type":          "application/json",
                        "X-Destination-Peer-Id": peer_pubkey,
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        log.warning(f"AXL send failed → {peer_pubkey[:12]} [{resp.status}]")
        except Exception as e:
            log.error(f"AXL send error: {e}")

    async def broadcast(self, msg_type: str, market: str, payload: dict):
        """Broadcast a message to all known peers."""
        if not self.known_peers:
            await self.discover_peers()
        tasks = [self.send(pk, msg_type, market, payload) for pk in self.known_peers]
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info(f"Broadcast {msg_type} to {len(self.known_peers)} peers (market {market[:10]}...)")

    # ─── Receive ──────────────────────────────────────────────────────────────

    def on_message(self, msg_type: str):
        """Decorator to register a handler for a message type."""
        def decorator(fn):
            self._handlers[msg_type] = fn
            return fn
        return decorator

    async def poll_recv(self):
        """Poll AXL /recv endpoint and dispatch to handlers. Run in background."""
        self._running = True
        log.info("AXL recv loop started")
        while self._running:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        f"{self.api_url}/recv",
                        timeout=aiohttp.ClientTimeout(total=6)
                    ) as resp:
                        if resp.status == 200:
                            content_type = resp.headers.get("Content-Type", "")
                            if "application/json" in content_type:
                                payload = await resp.json()
                                messages = payload if isinstance(payload, list) else [payload]
                            else:
                                body = await resp.text()
                                if not body.strip():
                                    messages = []
                                else:
                                    try:
                                        parsed = json.loads(body)
                                        messages = parsed if isinstance(parsed, list) else [parsed]
                                    except Exception:
                                        messages = [{"type": "RAW", "payload": {"text": body}}]
                            for raw in messages:
                                if isinstance(raw, dict):
                                    await self._dispatch(raw)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                log.error(f"AXL recv error: {e}")
            await asyncio.sleep(5)

    async def _dispatch(self, raw: dict):
        msg_type = raw.get("type", "")
        handler  = self._handlers.get(msg_type)
        if handler:
            try:
                await handler(raw)
            except Exception as e:
                log.error(f"Handler error for {msg_type}: {e}")
        else:
            log.debug(f"No handler for message type: {msg_type}")

    async def mcp_call(
        self,
        peer_pubkey: str,
        service: str,
        tool: str,
        args: dict,
        timeout: float = 15.0,
    ) -> Optional[dict]:
        return await self.call_peer_mcp(
            peer_pubkey=peer_pubkey,
            service_name=service,
            tool_name=tool,
            arguments=args,
            timeout=int(timeout),
        )

    def stop(self):
        self._running = False

    # ─── MCP calls to peers ───────────────────────────────────────────────────

    async def call_peer_mcp(
        self,
        peer_pubkey: str,
        service_name: str,
        tool_name: str,
        arguments: dict,
        timeout: int = 15
    ) -> Optional[dict]:
        """
        Call an MCP tool on a peer agent.
        AXL routes this through the multiplexer to the peer's MCP router.
        """
        payload = {
            "jsonrpc": "2.0",
            "id":      int(time.time() * 1000),
            "method":  "tools/call",
            "params": {
                "name":      tool_name,
                "arguments": arguments,
            }
        }
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{self.api_url}/mcp/{peer_pubkey}/{service_name}",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data.get("result", {}).get("content", [])
                        if content:
                            return json.loads(content[0].get("text", "{}"))
            return None
        except Exception as e:
            log.warning(f"MCP call to {peer_pubkey[:12]} failed: {e}")
            return None

    async def gather_peer_market_signals(
        self, market_address: str, question_text: str
    ) -> list:
        """
        Query all peers for their probability estimate on a market.
        Returns list of peer signal dicts.
        """
        tasks = [
            self.call_peer_mcp(
                peer_pk, "market_intel", "get_probability",
                {"market_address": market_address, "question": question_text}
            )
            for peer_pk in self.known_peers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        signals = []
        for r in results:
            if isinstance(r, dict) and "yes_probability" in r:
                signals.append(r)
        log.info(f"Collected {len(signals)}/{len(self.known_peers)} peer signals")
        return signals

    async def query_peer_vote_intention(
        self, peer_pk: str, market_address: str
    ) -> Optional[dict]:
        """Ask a specific peer for their current vote intention."""
        return await self.call_peer_mcp(
            peer_pk, "vote_intention", "get_vote",
            {"market_address": market_address}
        )

    # ─── Convergecast (quorum monitoring) ─────────────────────────────────────

    async def convergecast_tally(self, market_address: str) -> dict:
        """
        Aggregate vote tallies from peers using AXL spanning tree.
        Returns combined tally across all reachable nodes.
        """
        tasks = [
            self.call_peer_mcp(
                peer_pk, "market_intel", "get_resolution_tally",
                {"market_address": market_address}
            )
            for peer_pk in self.known_peers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        combined = {"voter_count": 0, "weighted_yes": 0, "weighted_no": 0, "weighted_invalid": 0}
        for r in results:
            if isinstance(r, dict):
                combined["voter_count"]     = max(combined["voter_count"],     r.get("voter_count", 0))
                combined["weighted_yes"]    = max(combined["weighted_yes"],    r.get("weighted_yes", 0))
                combined["weighted_no"]     = max(combined["weighted_no"],     r.get("weighted_no", 0))
                combined["weighted_invalid"]= max(combined["weighted_invalid"],r.get("weighted_invalid", 0))

        return combined

    # ─── Typed broadcast helpers ──────────────────────────────────────────────

    async def announce_market(self, market_addr: str, question_uri: str,
                               resolution_time: int, category: str):
        await self.broadcast(MSG_MARKET_CREATED, market_addr, {
            "questionURI":    question_uri,
            "resolutionTime": resolution_time,
            "category":       category,
        })

    async def announce_resolution_open(self, market_addr: str, voting_deadline: int, total_pool: float):
        await self.broadcast(MSG_RESOLUTION_OPEN, market_addr, {
            "votingDeadline": voting_deadline,
            "totalPool":      total_pool,
        })

    async def broadcast_vote_intention(self, market_addr: str, choice: str, confidence: float):
        await self.broadcast(MSG_VOTE_INTENTION, market_addr, {
            "choice":     choice,
            "confidence": confidence,
        })

    async def announce_quorum_reached(self, market_addr: str):
        await self.broadcast(MSG_QUORUM_REACHED, market_addr, {})

    async def announce_finalized(self, market_addr: str, outcome: str):
        await self.broadcast(MSG_FINALIZED, market_addr, {"outcome": outcome})


# ─── MCP service app (Flask, runs in background thread) ───────────────────────

class MCPServiceServer:
    """
    Exposes three MCP tools over AXL:
      - market_intel  → get_probability, get_resolution_tally
      - vote_intention → get_vote
      - agent_info    → get_card (ERC-8004)
    """

    def __init__(self, agent_state_provider: Callable, port: int = None):
        self.app      = Flask("mcp_server")
        self.port     = port or AXL_MCP_PORT
        self.provider = agent_state_provider
        self._register_routes()

    def _register_routes(self):

        @self.app.post("/mcp")
        def mcp_handler():
            req  = request.get_json()
            if not req:
                return jsonify({"error": "no body"}), 400

            method    = req.get("method", "")
            req_id    = req.get("id", 1)
            tool_name = req.get("params", {}).get("name", "")
            args      = req.get("params", {}).get("arguments", {})

            if method == "tools/list":
                return jsonify(self._tools_list(req_id))

            if method == "tools/call":
                result = self._dispatch_tool(tool_name, args)
                return jsonify({
                    "jsonrpc": "2.0",
                    "id":      req_id,
                    "result":  {
                        "content": [{"type": "text", "text": json.dumps(result)}]
                    }
                })

            return jsonify({"error": "unknown method"}), 400

    def _tools_list(self, req_id: int) -> dict:
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": [
                {"name": "get_probability",      "description": "Get this agent's probability estimate for a market", "inputSchema": {"type":"object","properties":{"market_address":{"type":"string"},"question":{"type":"string"}}}},
                {"name": "get_resolution_tally", "description": "Get live resolution vote tally for a market",       "inputSchema": {"type":"object","properties":{"market_address":{"type":"string"}}}},
                {"name": "get_vote",             "description": "Get this agent's current vote intention",           "inputSchema": {"type":"object","properties":{"market_address":{"type":"string"}}}},
                {"name": "get_card",             "description": "Get this agent's ERC-8004 identity card",           "inputSchema": {"type":"object","properties":{}}},
            ]}
        }

    def _dispatch_tool(self, name: str, args: dict) -> dict:
        state = self.provider()
        market = args.get("market_address", "")

        if name == "get_probability":
            est = state.get("probability_estimates", {}).get(market)
            if est:
                return {
                    "yes_probability":   est.get("yes_probability", 0.5),
                    "confidence":        est.get("confidence", 0.0),
                    "agent_id":          state.get("agent_id", 0),
                    "agent_reputation":  state.get("reputation_score", 50),
                    "research_count":    state.get("research_reports_count", 0),
                }
            return {"yes_probability": 0.5, "confidence": 0.0, "note": "no estimate available"}

        if name == "get_resolution_tally":
            tally = state.get("resolution_tallies", {}).get(market, {})
            return tally or {"voter_count": 0, "weighted_yes": 0, "weighted_no": 0, "weighted_invalid": 0}

        if name == "get_vote":
            vote = state.get("pending_votes", {}).get(market)
            if vote:
                return {"choice": vote.get("choice"), "confidence": vote.get("confidence")}
            return {"choice": None, "note": "not voted yet"}

        if name == "get_card":
            return {
                "name":          AGENT_NAME,
                "description":   AGENT_DESCRIPTION,
                "agent_id":      state.get("agent_id", 0),
                "address":       state.get("address", ""),
                "reputation":    state.get("reputation_score", 50),
                "domains":       AGENT_DOMAIN_FOCUS.split(","),
                "services":      [
                    {"name": "market_intel",  "endpoint": f"mcp://axl/{state.get('axl_pubkey','')}"},
                    {"name": "vote_intention","endpoint": f"mcp://axl/{state.get('axl_pubkey','')}"},
                ],
            }

        return {"error": f"unknown tool: {name}"}

    def start_background(self):
        t = Thread(target=lambda: self.app.run(port=self.port, debug=False, use_reloader=False), daemon=True)
        t.start()
        log.info(f"MCP server started on port {self.port}")
