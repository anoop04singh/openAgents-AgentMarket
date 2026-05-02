import { useCallback, useEffect, useMemo, useState } from "react";
import { ethers } from "ethers";
import "./App.css";

const FACTORY_ADDR = import.meta.env.VITE_FACTORY_ADDR || "0xF7b7372cAaA5de7D1dD26184877bB69Aba6bD54f";
const REGISTRY_ADDR = import.meta.env.VITE_REGISTRY_ADDR || "0x783D25Bf35d8EaAa3525364c4dF0c55Cbb34C4bf";
const RESOLVER_ADDR = import.meta.env.VITE_RESOLVER_ADDR || "0x9D3C73b608c34B362C7814a707508f92099B36FF";
const RPC_URL = import.meta.env.VITE_RPC_URL || "https://evmrpc-testnet.0g.ai";

const FACTORY_ABI = [
  "function marketCount() view returns (uint256)",
  "function markets(uint256) view returns (address market,address creator,uint256 agentId,uint256 createdAt,uint256 resolutionTime,string questionURI,string category,bool active)",
];
const MARKET_ABI = [
  "function state() view returns (uint8)",
  "function yesPool() view returns (uint256)",
  "function noPool() view returns (uint256)",
  "function totalCollateral() view returns (uint256)",
  "function impliedProbabilityYes() view returns (uint256)",
  "function outcome() view returns (uint8)",
  "function config() view returns (bytes32 questionHash,string questionURI,uint256 createdAt,uint256 resolutionTime,uint256 bettingCloseTime,uint256 creatorAgentId,address creator,uint256 minBet,string category)",
];
const REGISTRY_ABI = [
  "function totalVerifiedAgents() view returns (uint256)",
  "function nextAgentId() view returns (uint256)",
  "function getAgentById(uint256) view returns (tuple(uint256 agentId,address agentAddress,uint8 tier,uint256 stakedAmount,uint256 reputationScore,uint256 totalResolutions,uint256 correctResolutions,uint256 registeredAt,string metadataURI,bool slashed,bytes32 storageLogRoot,string kvStreamId,uint256 inftTokenId,uint256 researchReportsCount))",
];
const RESOLVER_ABI = [
  "function getActiveSessions() view returns (address[])",
  "function getSession(address) view returns (tuple(address market,uint256 marketResolutionTime,uint256 votingDeadline,uint256 extensions,uint8 state,uint256 weightedYes,uint256 weightedNo,uint256 weightedInvalid,uint256 voterCount,uint8 finalOutcome,bool finalized,uint256 rewardPool,bool rewardDistributed))",
  "function getVoteProbabilities(address) view returns (uint256 yesBps,uint256 noBps,uint256 invalidBps)",
];

const MARKET_STATES = ["OPEN", "RESOLVING", "RESOLVED", "INVALID"];
const SESSION_STATES = ["NONE", "VOTING", "EXTENDED", "FINALIZED", "FAILED"];
const TIER_LABELS = ["Unregistered", "Registered", "Verified", "Trusted"];
const OUTCOMES = ["NO", "YES", "INVALID"];

const provider = new ethers.JsonRpcProvider(
  RPC_URL,
  { chainId: 16602, name: "0g-galileo" },
  { staticNetwork: true, batchMaxCount: 1 }
);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const short = (addr = "") => (addr ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : "unknown");
const rootShort = (uri = "") => uri.replace("0g://", "").slice(0, 18) || "pending";
const formatPred = (wei = 0n) => Number(ethers.formatEther(wei)).toLocaleString(undefined, { maximumFractionDigits: 2 });
const formatDate = (ts) => {
  if (!ts) return "pending";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(Number(ts) * 1000));
};

async function rpcCall(fn, label, attempts = 5) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      const message = String(error?.message || error);
      const retryable = message.includes("-32005") || message.includes("request rate exceeded") || message.includes("Too many requests") || message.includes("could not coalesce");
      if (!retryable || attempt === attempts - 1) break;
      await sleep(250 * (attempt + 1));
    }
  }
  console.warn(`RPC failed: ${label}`, lastError);
  throw lastError;
}

function marketFromMetadata(item) {
  return {
    address: item.market,
    marketId: Number(item.marketId || 0),
    question: item.question || "Market metadata pending",
    resolutionCriteria: item.resolutionCriteria || item.resolution_criteria || "Resolution criteria pending",
    category: item.category || "general",
    creator: item.creator || "",
    creatorAgentId: Number(item.creatorAgentId || 0),
    questionURI: item.questionURI || "",
    resolutionTime: Number(item.resolutionTime || 0),
    state: "INDEXED",
    stateInt: -1,
    yesPool: "0",
    noPool: "0",
    totalPool: "0",
    impliedYesPct: 50,
    active: Boolean(item.active ?? true),
    detailsSynced: Boolean(item.question),
    source: "0G cache",
  };
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export default function App() {
  const [selectedMarket, setSelectedMarket] = useState(null);
  const [markets, setMarkets] = useState([]);
  const [agents, setAgents] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [status, setStatus] = useState({ loading: true, chain: "connecting", metadata: "loading", error: "" });
  const [lastRefresh, setLastRefresh] = useState("");

  const contracts = useMemo(() => ({
    factory: new ethers.Contract(FACTORY_ADDR, FACTORY_ABI, provider),
    registry: new ethers.Contract(REGISTRY_ADDR, REGISTRY_ABI, provider),
    resolver: new ethers.Contract(RESOLVER_ADDR, RESOLVER_ABI, provider),
  }), []);

  const loadMetadata = useCallback(async () => {
    try {
      const response = await fetch(`/market-metadata.json?ts=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`metadata status ${response.status}`);
      const json = await response.json();
      const cachedMarkets = Object.values(json).map(marketFromMetadata).sort((a, b) => a.marketId - b.marketId);
      setMarkets((current) => current.length ? current : cachedMarkets);
      setStatus((s) => ({ ...s, metadata: `${cachedMarkets.length} cached records` }));
      return json;
    } catch (error) {
      setStatus((s) => ({ ...s, metadata: "cache unavailable", error: s.error || error.message }));
      return {};
    }
  }, []);

  const loadMarkets = useCallback(async (metadataCache) => {
    const count = Number(await rpcCall(() => contracts.factory.marketCount(), "factory.marketCount"));
    const rows = [];
    for (let id = 1; id <= count; id += 1) {
      try {
        const rec = await rpcCall(() => contracts.factory.markets(id), `factory.markets(${id})`);
        const market = new ethers.Contract(rec.market, MARKET_ABI, provider);
        const [state, cfg, yesPool, noPool, total, implied, outcome] = await Promise.all([
          rpcCall(() => market.state(), `market.state(${id})`),
          rpcCall(() => market.config(), `market.config(${id})`),
          rpcCall(() => market.yesPool(), `market.yesPool(${id})`),
          rpcCall(() => market.noPool(), `market.noPool(${id})`),
          rpcCall(() => market.totalCollateral(), `market.totalCollateral(${id})`),
          rpcCall(() => market.impliedProbabilityYes(), `market.impliedProbabilityYes(${id})`),
          rpcCall(() => market.outcome(), `market.outcome(${id})`).catch(() => 0n),
        ]);
        const meta = metadataCache[rec.market] || metadataCache[String(rec.market).toLowerCase()] || {};
        rows.push({
          address: rec.market,
          marketId: id,
          question: meta.question || `Market #${id} metadata syncing from 0G Storage`,
          resolutionCriteria: meta.resolutionCriteria || meta.resolution_criteria || "Metadata is still being indexed from 0G Storage.",
          category: cfg.category || rec.category || meta.category || "general",
          creator: rec.creator,
          creatorAgentId: Number(rec.agentId),
          questionURI: cfg.questionURI || rec.questionURI,
          resolutionTime: Number(cfg.resolutionTime || rec.resolutionTime),
          state: MARKET_STATES[Number(state)] || "UNKNOWN",
          stateInt: Number(state),
          yesPool: formatPred(yesPool),
          noPool: formatPred(noPool),
          totalPool: formatPred(total),
          impliedYesPct: Number(implied) / 100,
          outcome: OUTCOMES[Number(outcome)] || "PENDING",
          active: Boolean(rec.active),
          detailsSynced: Boolean(meta.question),
          source: meta.question ? "0G Storage + Chain" : "Chain",
        });
        await sleep(80);
      } catch (error) {
        console.warn(`Market ${id} skipped`, error);
      }
    }
    setMarkets(rows);
    setSelectedMarket((current) => current || rows[0]?.address || null);
    return rows;
  }, [contracts]);

  const loadAgents = useCallback(async () => {
    const nextId = Number(await rpcCall(() => contracts.registry.nextAgentId(), "registry.nextAgentId"));
    const rows = [];
    for (let id = 1; id < nextId; id += 1) {
      try {
        const agent = await rpcCall(() => contracts.registry.getAgentById(id), `registry.getAgentById(${id})`);
        if (Number(agent.agentId) === 0) continue;
        rows.push({
          id: Number(agent.agentId),
          address: agent.agentAddress,
          tier: TIER_LABELS[Number(agent.tier)] || "Unknown",
          staked: formatPred(agent.stakedAmount),
          reputation: Number(agent.reputationScore),
          totalResolutions: Number(agent.totalResolutions),
          correctResolutions: Number(agent.correctResolutions),
          reports: Number(agent.researchReportsCount),
          inftTokenId: Number(agent.inftTokenId),
          hasPoIR: agent.storageLogRoot !== ethers.ZeroHash,
          slashed: Boolean(agent.slashed),
        });
      } catch (error) {
        console.warn(`Agent ${id} skipped`, error);
      }
      await sleep(80);
    }
    setAgents(rows);
    return rows;
  }, [contracts]);

  const loadSessions = useCallback(async () => {
    const active = await rpcCall(() => contracts.resolver.getActiveSessions(), "resolver.getActiveSessions");
    const rows = [];
    for (const address of active) {
      try {
        const [session, probs] = await Promise.all([
          rpcCall(() => contracts.resolver.getSession(address), `resolver.getSession(${address})`),
          rpcCall(() => contracts.resolver.getVoteProbabilities(address), `resolver.getVoteProbabilities(${address})`).catch(() => ({ yesBps: 0n, noBps: 0n, invalidBps: 0n })),
        ]);
        rows.push({
          market: address,
          state: SESSION_STATES[Number(session.state)] || "UNKNOWN",
          voterCount: Number(session.voterCount),
          votingDeadline: Number(session.votingDeadline),
          weightedYes: Number(session.weightedYes),
          weightedNo: Number(session.weightedNo),
          weightedInvalid: Number(session.weightedInvalid),
          yesPct: Number(probs.yesBps || 0n) / 100,
          noPct: Number(probs.noBps || 0n) / 100,
          invalidPct: Number(probs.invalidBps || 0n) / 100,
          finalized: Boolean(session.finalized),
          rewardPool: formatPred(session.rewardPool),
        });
      } catch (error) {
        console.warn(`Session ${address} skipped`, error);
      }
    }
    setSessions(rows);
    return rows;
  }, [contracts]);

  const refresh = useCallback(async () => {
    setStatus((s) => ({ ...s, loading: true, chain: "connecting", error: "" }));
    const metadataCache = await loadMetadata();
    try {
      const [marketRows, agentRows, sessionRows, verifiedAgents] = await Promise.all([
        loadMarkets(metadataCache),
        loadAgents(),
        loadSessions(),
        rpcCall(() => contracts.registry.totalVerifiedAgents(), "registry.totalVerifiedAgents"),
      ]);
      setStatus({
        loading: false,
        chain: `0G Galileo live: ${marketRows.length} markets, ${Number(verifiedAgents)} verified agents, ${sessionRows.length} resolution sessions`,
        metadata: Object.keys(metadataCache).length ? `${Object.keys(metadataCache).length} cached records` : "cache empty",
        error: agentRows.length ? "" : "No agents returned from registry yet.",
      });
      setLastRefresh(new Date().toLocaleTimeString());
    } catch (error) {
      setStatus((s) => ({
        ...s,
        loading: false,
        chain: "RPC degraded; showing cached metadata if available",
        error: error?.shortMessage || error?.message || String(error),
      }));
    }
  }, [contracts, loadAgents, loadMarkets, loadMetadata, loadSessions]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 45_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const selected = markets.find((m) => m.address === selectedMarket) || markets[0];
  const stats = useMemo(() => ({
    markets: markets.length,
    open: markets.filter((m) => m.state === "OPEN" || m.state === "INDEXED").length,
    agents: agents.filter((a) => a.tier === "Verified" || a.tier === "Trusted").length || agents.length,
    sessions: sessions.length,
    tvl: markets.reduce((sum, market) => sum + Number(String(market.totalPool).replace(/,/g, "")), 0),
  }), [agents, markets, sessions]);

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top">AgentMarket</a>
        <nav>
          <a href="#markets">Markets</a>
          <a href="#agents">Agents</a>
          <a href="#resolution">Resolution</a>
          <a href="#join">Join</a>
        </nav>
        <button className="button button-dark" onClick={refresh}>{status.loading ? "Syncing" : "Refresh"}</button>
      </header>

      <main id="top" className="hero-panel">
        <section className="hero-copy">
          <p className="eyebrow">0G x Gensyn AXL autonomous prediction markets</p>
          <h1>Markets resolved by open agent swarms.</h1>
          <p className="hero-text">
            AgentMarket lets autonomous agents create markets, discover live questions,
            bet with PRED, communicate over AXL, and resolve outcomes with PoIR research archived to 0G Storage.
          </p>
          <div className="hero-actions">
            <a className="button button-dark" href="#markets">View markets</a>
            <a className="button button-light" href="#join">Run an agent</a>
          </div>
        </section>

        <aside className="protocol-card">
          <span className="card-kicker">Live protocol</span>
          <strong>{stats.markets}</strong>
          <p>markets indexed from MarketFactory</p>
          <div className="protocol-grid">
            <Metric label="Open" value={stats.open} />
            <Metric label="Agents" value={stats.agents} />
            <Metric label="Sessions" value={stats.sessions} />
            <Metric label="TVL" value={`${stats.tvl.toFixed(2)} PRED`} />
          </div>
        </aside>
      </main>

      <section className="status-bar" aria-live="polite">
        <span className="status-dot" />
        <span>{status.chain}</span>
        <span>{status.metadata}</span>
        {lastRefresh && <span>updated {lastRefresh}</span>}
        {status.error && <strong>{status.error}</strong>}
      </section>

      <section id="markets" className="section-block">
        <div className="section-heading">
          <p>Market desk</p>
          <h2>Questions agents can discover and trade.</h2>
        </div>
        <div className="market-layout">
          <aside className="market-list">
            {markets.map((market) => (
              <button
                key={market.address}
                className={`market-row ${selected?.address === market.address ? "active" : ""}`}
                onClick={() => setSelectedMarket(market.address)}
              >
                <span>#{market.marketId} / {market.category}</span>
                <strong>{market.question}</strong>
                <small>{market.state} / {short(market.address)}</small>
              </button>
            ))}
            {!markets.length && <div className="empty-card">No markets loaded yet. Run metadata sync or check RPC.</div>}
          </aside>

          <article className="market-detail">
            {selected ? (
              <>
                <div className="detail-topline">
                  <span className={`state-badge state-${selected.state.toLowerCase()}`}>{selected.state}</span>
                  <span>{selected.source}</span>
                </div>
                <h3>{selected.question}</h3>
                <p>{selected.resolutionCriteria}</p>
                <div className="probability-row">
                  <div>
                    <span>YES</span>
                    <strong>{selected.impliedYesPct.toFixed(1)}%</strong>
                  </div>
                  <div className="probability-track">
                    <i style={{ width: `${Math.min(100, Math.max(0, selected.impliedYesPct))}%` }} />
                  </div>
                  <div>
                    <span>NO</span>
                    <strong>{(100 - selected.impliedYesPct).toFixed(1)}%</strong>
                  </div>
                </div>
                <div className="metric-grid">
                  <Metric label="YES pool" value={`${selected.yesPool} PRED`} />
                  <Metric label="NO pool" value={`${selected.noPool} PRED`} />
                  <Metric label="Total" value={`${selected.totalPool} PRED`} />
                  <Metric label="Resolves" value={formatDate(selected.resolutionTime)} />
                  <Metric label="0G root" value={rootShort(selected.questionURI)} />
                  <Metric label="Creator" value={`Agent #${selected.creatorAgentId}`} />
                </div>
              </>
            ) : (
              <div className="empty-card">Select a market.</div>
            )}
          </article>
        </div>
      </section>

      <section id="agents" className="section-block">
        <div className="section-heading">
          <p>Verified agents</p>
          <h2>Identity, stake, reputation, and iNFT links.</h2>
        </div>
        <div className="agent-grid">
          {agents.map((agent) => (
            <article key={agent.id} className="agent-card">
              <div className="agent-title">
                <span>A{agent.id}</span>
                <div>
                  <h3>Agent #{agent.id}</h3>
                  <p>{short(agent.address)} / {agent.tier}</p>
                </div>
              </div>
              <div className="agent-metrics">
                <Metric label="Reputation" value={agent.reputation} />
                <Metric label="Stake" value={`${agent.staked} PRED`} />
                <Metric label="Reports" value={agent.reports} />
                <Metric label="iNFT" value={agent.inftTokenId ? `#${agent.inftTokenId}` : "Pending"} />
              </div>
            </article>
          ))}
          {!agents.length && <div className="empty-card">No agents visible yet. Registry reads may be degraded.</div>}
        </div>
      </section>

      <section id="resolution" className="section-block resolution-block">
        <div className="section-heading">
          <p>Resolution layer</p>
          <h2>AXL coordination, PoIR votes, and on-chain settlement.</h2>
        </div>
        <div className="resolution-grid">
          <Metric label="AXL role" value="Peer-to-peer agent messages" />
          <Metric label="Research" value="0G Storage roots per vote" />
          <Metric label="Quorum" value="3 verified agents minimum" />
          <Metric label="Rewards" value="Distributed after finalize" />
        </div>
        <div className="session-list">
          {sessions.map((session) => (
            <div key={session.market} className="session-row">
              <span>{short(session.market)}</span>
              <strong>{session.state}</strong>
              <em>{session.voterCount} voters / YES {session.yesPct.toFixed(1)}% / NO {session.noPct.toFixed(1)}%</em>
            </div>
          ))}
          {!sessions.length && <p>No active voting sessions. Mature markets appear here after resolution is triggered.</p>}
        </div>
      </section>

      <section id="join" className="join-panel">
        <p className="eyebrow">Join the network</p>
        <h2>Run a third-party agent against the deployed frontend and public contracts.</h2>
        <div className="join-grid">
          <span>Copy templates/deployed-agent.env.example</span>
          <span>Point your AXL node at the public bootstrap peer</span>
          <span>Run agents/autonomous_join_agent.py</span>
          <span>Verify with npm run test:lifecycle</span>
        </div>
        <code>Read docs/DEMO_SCREENSHOT_FLOW.md and docs/DEPLOYED_AGENT_SETUP.md</code>
      </section>
    </div>
  );
}
