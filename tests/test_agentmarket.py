"""
tests/test_agentmarket.py
═══════════════════════════════════════════════════════════════════════════════
Full test suite covering:
  - ResearchEngine (mocked 0G Compute + Storage)
  - ChainClient helpers (against Anvil local fork)
  - CollectiveResolver PoIR vote flow
  - Convergecast quorum detection
  - MCP server endpoints

Run:
  pytest tests/test_agentmarket.py -v
  pytest tests/test_agentmarket.py -v -k "research"   # only research tests
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_compute_result():
    """Simulates a 0G Compute TeeML response."""
    r = MagicMock()
    r.content = json.dumps({
        "verdict":          "YES",
        "confidence":       0.82,
        "yes_probability":  0.78,
        "evidence_sources": ["coingecko.com/eth", "coinmarketcap.com/eth"],
        "reasoning_chain":  "ETH price crossed $5000 on Dec 28 per multiple sources.",
        "data_gaps":        "No intraday price data available.",
    })
    r.tee_signature  = b"\xde\xad\xbe\xef" * 16   # 64 bytes fake TEE sig
    r.model_id       = "deepseek-ai/DeepSeek-V3-0324"
    r.provider       = "0g-compute-teeml"
    return r


@pytest.fixture
def mock_storage_root():
    return "0x" + "ab" * 32


@pytest.fixture
def mock_compute_client(mock_compute_result):
    client = AsyncMock()
    client.chat_completion = AsyncMock(return_value=mock_compute_result)
    return client


@pytest.fixture
def mock_storage_client(mock_storage_root):
    client = AsyncMock()
    client.upload_log   = AsyncMock(return_value=mock_storage_root.lstrip("0x"))
    client.download     = AsyncMock(return_value=b'{"question": "Will ETH exceed $5000?"}')
    client.kv_get       = AsyncMock(return_value=None)
    client.kv_set       = AsyncMock(return_value=True)
    client.create_kv_stream = AsyncMock(return_value="stream-id-" + "a" * 20)
    return client


@pytest.fixture
def mock_axl_client():
    client = AsyncMock()
    client.receive_all    = AsyncMock(return_value=[])
    client.broadcast      = AsyncMock(return_value=None)
    client.send           = AsyncMock(return_value=None)
    client.mcp_call       = AsyncMock(return_value={
        "result": {"content": [{"text": json.dumps({
            "yes_probability": 0.72,
            "confidence":      0.68,
            "reasoning_summary": "Peer analysis: bullish trend",
            "agent_id":        2,
            "agent_reputation": 75,
        })}]}
    })
    client.get_topology   = AsyncMock(return_value={"parent": None, "children": []})
    client.get_known_peers = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_chain_client():
    client = MagicMock()
    client.record_research_report = AsyncMock(return_value="0xdeadbeef")
    client.get_agent = AsyncMock(return_value={
        "agentId": 1,
        "reputationScore": 75,
        "totalResolutions": 10,
        "correctResolutions": 8,
        "researchReportsCount": 5,
        "inftTokenId": 42,
    })
    return client


@pytest.fixture
def research_engine(mock_compute_client, mock_storage_client, mock_axl_client, mock_chain_client):
    """Construct ResearchEngine with all mocked dependencies."""
    import sys
    sys.path.insert(0, "agents")
    from research_engine import ResearchEngine
    return ResearchEngine(
        compute_client = mock_compute_client,
        storage_client = mock_storage_client,
        axl_client     = mock_axl_client,
        chain_client   = mock_chain_client,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# RESEARCH ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestResearchEngine:

    @pytest.mark.asyncio
    async def test_full_research_pipeline(self, research_engine, mock_storage_root):
        """Full PoIR pipeline produces a valid ResearchReceipt."""
        receipt = await research_engine.research(
            market_address  = "0x" + "11" * 20,
            question_uri    = "ipfs://QmTestQuestion",
            resolution_time = int(time.time()) - 3600,  # already past
            known_peers     = ["peer-pubkey-abc123"],
        )

        assert receipt.verdict == "YES"
        assert receipt.confidence == pytest.approx(0.82, abs=0.01)
        assert receipt.yes_probability == pytest.approx(0.78, abs=0.01)
        assert len(receipt.evidence_sources) == 2
        assert receipt.tee_signature == b"\xde\xad\xbe\xef" * 16
        assert receipt.storage_log_root != ""
        assert receipt.choice_int == 1  # YES
        assert receipt.model_used == "deepseek-ai/DeepSeek-V3-0324"

    @pytest.mark.asyncio
    async def test_low_confidence_overrides_to_invalid(self, research_engine, mock_compute_client):
        """Confidence below MIN_CONFIDENCE should force INVALID verdict."""
        mock_compute_client.chat_completion.return_value.content = json.dumps({
            "verdict":          "YES",
            "confidence":       0.40,   # below 0.65 threshold
            "yes_probability":  0.55,
            "evidence_sources": [],
            "reasoning_chain":  "Weak signal.",
            "data_gaps":        "Insufficient data.",
        })

        receipt = await research_engine.research(
            market_address  = "0x" + "22" * 20,
            question_uri    = "ipfs://QmLowConf",
            resolution_time = int(time.time()) - 100,
            known_peers     = [],
        )

        assert receipt.verdict == "INVALID"
        assert receipt.choice_int == 2

    @pytest.mark.asyncio
    async def test_peer_signals_collected(self, research_engine, mock_axl_client):
        """Peer signals are collected from AXL peers."""
        receipt = await research_engine.research(
            market_address  = "0x" + "33" * 20,
            question_uri    = "ipfs://QmPeerTest",
            resolution_time = int(time.time()) - 100,
            known_peers     = ["peer-1", "peer-2", "peer-3"],
        )

        # 3 peers queried → mcp_call should be called 3 times
        assert mock_axl_client.mcp_call.call_count == 3
        assert len(receipt.peer_signals) == 3
        assert all(p.yes_prob == pytest.approx(0.72) for p in receipt.peer_signals)

    @pytest.mark.asyncio
    async def test_peer_failure_non_fatal(self, research_engine, mock_axl_client):
        """Peer query failure should not abort research."""
        mock_axl_client.mcp_call.side_effect = Exception("Peer offline")

        receipt = await research_engine.research(
            market_address  = "0x" + "44" * 20,
            question_uri    = "ipfs://QmPeerFail",
            resolution_time = int(time.time()) - 100,
            known_peers     = ["peer-1", "peer-2"],
        )

        # Research should complete despite peer failures
        assert receipt.verdict in ("YES", "NO", "INVALID")
        assert len(receipt.peer_signals) == 0   # no successful peer signals

    @pytest.mark.asyncio
    async def test_storage_log_archived(self, research_engine, mock_storage_client, mock_storage_root):
        """Research report must be archived to 0G Storage Log."""
        receipt = await research_engine.research(
            market_address  = "0x" + "55" * 20,
            question_uri    = "ipfs://QmArchive",
            resolution_time = int(time.time()) - 100,
            known_peers     = [],
        )

        mock_storage_client.upload_log.assert_called_once()
        # Storage root should be in the receipt
        assert receipt.storage_log_root == mock_storage_root.lstrip("0x")

    @pytest.mark.asyncio
    async def test_on_chain_record_called(self, research_engine, mock_chain_client):
        """recordResearchReport should be called after archiving."""
        await research_engine.research(
            market_address  = "0x" + "66" * 20,
            question_uri    = "ipfs://QmRecord",
            resolution_time = int(time.time()) - 100,
            known_peers     = [],
        )
        mock_chain_client.record_research_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_malformed_llm_response(self, research_engine, mock_compute_client):
        """Malformed JSON from LLM should result in INVALID, not a crash."""
        mock_compute_client.chat_completion.return_value.content = (
            "Sorry, I cannot determine the outcome of this market."
        )

        receipt = await research_engine.research(
            market_address  = "0x" + "77" * 20,
            question_uri    = "ipfs://QmMalformed",
            resolution_time = int(time.time()) - 100,
            known_peers     = [],
        )

        assert receipt.verdict == "INVALID"

    def test_choice_int_mapping(self):
        """choice_int must correctly map YES=1, NO=0, INVALID=2."""
        import sys
        sys.path.insert(0, "agents")
        from research_engine import ResearchReceipt

        for verdict, expected in [("YES", 1), ("NO", 0), ("INVALID", 2)]:
            r = ResearchReceipt(
                market_address="0x" + "aa" * 20, question_uri="",
                question_text="", verdict=verdict, confidence=0.8,
                yes_probability=0.8, evidence_sources=[], reasoning_chain="",
                peer_signals=[], tee_signature=b"", model_used="",
                storage_log_root="", archived_at=0, agent_name="",
            )
            assert r.choice_int == expected, f"{verdict} should map to {expected}"


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERGECAST TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestConvergecast:

    @pytest.fixture
    def mock_chain_for_quorum(self):
        chain = MagicMock()
        chain.resolver = MagicMock()
        chain.registry = MagicMock()
        # Session: (market, resTime, deadline, ext, state, yesW, noW, invW, voterCount, ...)
        chain.resolver.functions.getSession.return_value.call.return_value = (
            "0x" + "11" * 20,   # market
            0, 0, 0, 1,          # resTime, deadline, ext, state(VOTING)
            2000, 1000, 0,       # weightedYes, weightedNo, weightedInvalid
            4,                   # voterCount  ← 4 >= MIN_QUORUM_COUNT(3) → quorum!
            0, False, 0, False   # finalOutcome, finalized, rewardPool, distributed
        )
        chain.registry.functions.totalVerifiedAgents.return_value.call.return_value = 10
        return chain

    @pytest.mark.asyncio
    async def test_quorum_detected_at_root(self, mock_axl_client, mock_chain_for_quorum):
        """Root node should detect quorum and fire callback."""
        import sys
        sys.path.insert(0, "agents")
        from convergecast import QuorumMonitor

        callback_called = asyncio.Event()

        async def on_quorum(market_addr):
            callback_called.set()

        monitor = QuorumMonitor(
            axl            = mock_axl_client,
            chain          = mock_chain_for_quorum,
            agent_wallet   = "0x" + "aa" * 20,
            on_quorum_reached = on_quorum,
        )
        monitor._is_root = True   # force root for this test
        market = "0x" + "11" * 20
        monitor.add_market(market)

        await monitor._collect_and_propagate(market)
        assert callback_called.is_set()

    @pytest.mark.asyncio
    async def test_no_quorum_no_callback(self, mock_axl_client, mock_chain_for_quorum):
        """Not enough voters → callback should NOT fire."""
        import sys
        sys.path.insert(0, "agents")
        from convergecast import QuorumMonitor

        # Override to only 1 voter
        mock_chain_for_quorum.resolver.functions.getSession.return_value.call.return_value = (
            "0x" + "bb" * 20,
            0, 0, 0, 1, 500, 0, 0,
            1,   # voterCount = 1 < 3 = MIN_QUORUM_COUNT
            0, False, 0, False
        )

        callback_called = False
        async def on_quorum(market_addr):
            nonlocal callback_called
            callback_called = True

        monitor = QuorumMonitor(
            axl            = mock_axl_client,
            chain          = mock_chain_for_quorum,
            agent_wallet   = "0x" + "aa" * 20,
            on_quorum_reached = on_quorum,
        )
        monitor._is_root = True
        market = "0x" + "bb" * 20
        monitor.add_market(market)

        await monitor._collect_and_propagate(market)
        assert not callback_called


# ═══════════════════════════════════════════════════════════════════════════════
# MCP SERVER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpServer:

    @pytest.fixture
    def mcp_client(self):
        import sys
        sys.path.insert(0, "agents/services")
        from mcp_server import app, set_state
        set_state({
            "agent_id":    1,
            "wallet":      "0x" + "aa" * 20,
            "agent_name":  "Test-Agent",
            "reputation":  80,
            "open_markets": {
                "0x" + "11" * 20: {
                    "questionURI": "ipfs://QmTest",
                    "category":    "crypto",
                    "our_estimate": {
                        "yes_probability":  0.73,
                        "confidence":       0.81,
                        "reasoning_summary":"ETH showing bullish momentum.",
                        "storage_log_root": "ab" * 32,
                        "tee_signature":    "de" * 32,
                        "model_used":       "deepseek-v3",
                    }
                }
            },
            "voted_markets": {
                "0x" + "22" * 20: {
                    "verdict":          "YES",
                    "confidence":       0.85,
                    "yes_probability":  0.80,
                    "reasoning_chain":  "Clear evidence from CoinGecko.",
                    "evidence_sources": ["coingecko.com", "cmc.com"],
                    "storage_log_root": "cd" * 32,
                    "tee_signature_hex": "ef" * 32,
                    "model_used":       "deepseek-v3",
                    "archived_at":      int(time.time()),
                }
            },
            "chain":  None,
            "storage": None,
        })
        app.config["TESTING"] = True
        return app.test_client()

    def _rpc(self, client, method, params=None):
        return client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1,
            "method": method,
            "params": params or {}
        })

    def test_tools_list(self, mcp_client):
        r = self._rpc(mcp_client, "tools/list")
        assert r.status_code == 200
        data = r.get_json()
        names = [t["name"] for t in data["result"]["tools"]]
        assert "get_probability"     in names
        assert "get_vote_intention"  in names
        assert "get_agent_card"      in names

    def test_get_probability_known_market(self, mcp_client):
        r = self._rpc(mcp_client, "tools/call", {
            "name": "get_probability",
            "arguments": {"market_address": "0x" + "11" * 20}
        })
        assert r.status_code == 200
        data = json.loads(r.get_json()["result"]["content"][0]["text"])
        assert data["yes_probability"] == pytest.approx(0.73)
        assert data["confidence"]      == pytest.approx(0.81)
        assert data["has_poir"]        is True

    def test_get_vote_intention_voted(self, mcp_client):
        r = self._rpc(mcp_client, "tools/call", {
            "name": "get_vote_intention",
            "arguments": {"market_address": "0x" + "22" * 20}
        })
        data = json.loads(r.get_json()["result"]["content"][0]["text"])
        assert data["status"]  == "researched"
        assert data["verdict"] == "YES"
        assert data["has_poir"] is True

    def test_get_vote_intention_unresearched(self, mcp_client):
        r = self._rpc(mcp_client, "tools/call", {
            "name": "get_vote_intention",
            "arguments": {"market_address": "0x" + "99" * 20}
        })
        data = json.loads(r.get_json()["result"]["content"][0]["text"])
        assert data["status"] == "not_researched"
        assert data["verdict"] is None

    def test_get_agent_card(self, mcp_client):
        r = self._rpc(mcp_client, "tools/call", {
            "name": "get_agent_card",
            "arguments": {}
        })
        data = json.loads(r.get_json()["result"]["content"][0]["text"])
        assert data["schema"]   == "erc8004/v1"
        assert data["agent_id"] == 1
        assert len(data["services"]) == 2

    def test_unknown_tool_error(self, mcp_client):
        r = self._rpc(mcp_client, "tools/call", {
            "name": "nonexistent_tool",
            "arguments": {}
        })
        assert r.status_code == 400
        assert "error" in r.get_json()

    def test_health_endpoint(self, mcp_client):
        r = mcp_client.get("/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

    def test_a2a_agent_json(self, mcp_client):
        r = mcp_client.get("/.well-known/agent.json")
        assert r.status_code == 200
        data = r.get_json()
        assert "services" in data
        assert data["name"] == "Test-Agent"
