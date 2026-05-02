#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");
require("dotenv").config();

const ROOT = path.resolve(__dirname, "..");
const ADDR = JSON.parse(fs.readFileSync(path.join(ROOT, "deployments", "addresses.json"), "utf8"));
const METADATA_PATH = path.join(ROOT, "public", "market-metadata.json");

const FACTORY_ABI = [
  "function marketCount() view returns (uint256)",
  "function markets(uint256) view returns (address market,address creator,uint256 agentId,uint256 createdAt,uint256 resolutionTime,string questionURI,string category,bool active)",
];
const MARKET_ABI = [
  "function state() view returns (uint8)",
  "function config() view returns (bytes32 questionHash,string questionURI,uint256 createdAt,uint256 resolutionTime,uint256 bettingCloseTime,uint256 creatorAgentId,address creator,uint256 minBet,string category)",
  "function yesPool() view returns (uint256)",
  "function noPool() view returns (uint256)",
  "function totalCollateral() view returns (uint256)",
  "function impliedProbabilityYes() view returns (uint256)",
  "function triggerResolution()",
  "function outcome() view returns (uint8)",
];
const REGISTRY_ABI = [
  "function isVerified(address) view returns (bool)",
  "function totalVerifiedAgents() view returns (uint256)",
  "function getAgent(address) view returns ((uint256 agentId,address agentAddress,uint8 tier,uint256 stakedAmount,uint256 reputationScore,uint256 totalResolutions,uint256 correctResolutions,uint256 registeredAt,string metadataURI,bool slashed,bytes32 storageLogRoot,string kvStreamId,uint256 inftTokenId,uint256 researchReportsCount))",
];
const RESOLVER_ABI = [
  "function requirePoIR() view returns (bool)",
  "function getActiveSessions() view returns (address[])",
  "function isVotingOpen(address market) view returns (bool)",
  "function getSession(address market) view returns (address market,uint256 marketResolutionTime,uint256 votingDeadline,uint256 extensions,uint8 state,uint256 weightedYes,uint256 weightedNo,uint256 weightedInvalid,uint256 voterCount,uint8 finalOutcome,bool finalized,uint256 rewardPool,bool rewardDistributed)",
  "function getVote(address market,address voter) view returns (uint8 choice,uint256 weight,bool cast,bool rewarded,bytes32 storageLogRoot,bytes teeSignature,bool hasPoIR)",
  "function castVerifiedVote(address market,uint8 choice,bytes32 storageLogRoot,bytes teeSignature)",
  "function finalizeResolution(address market)",
  "function distributeRewards(address market)",
];

const MARKET_STATE = ["OPEN", "RESOLVING", "RESOLVED", "INVALID"];
const SESSION_STATE = ["NONE", "VOTING", "EXTENDED", "FINALIZED", "FAILED"];
const VOTE_NAME = ["NO", "YES", "INVALID"];
const MCP_PORTS = [9003, 9013, 9023];
const AXL_PORTS = [9002, 9012, 9022];

const argv = process.argv.slice(2);
const flags = new Set(argv.filter((a) => a.startsWith("--") && !a.includes("=")));
const option = (name, fallback = "") => {
  const item = argv.find((a) => a.startsWith(`--${name}=`));
  return item ? item.slice(name.length + 3) : fallback;
};

const execute = flags.has("--execute");
const finalize = flags.has("--finalize");
const distribute = flags.has("--distribute");
const requestedMarket = option("market");
const requestedChoice = option("choice", "INVALID").toUpperCase();
const choice = { NO: 0, YES: 1, INVALID: 2 }[requestedChoice] ?? 2;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function section(name) {
  console.log(`\n=== ${name} ===`);
}

function row(label, value) {
  console.log(`${label.padEnd(28)} ${value}`);
}

function fmtPct(bps) {
  return `${(Number(bps) / 100).toFixed(2)}%`;
}

function fmtToken(value) {
  return ethers.formatEther(value);
}

function readMetadata() {
  if (!fs.existsSync(METADATA_PATH)) return {};
  try {
    return JSON.parse(fs.readFileSync(METADATA_PATH, "utf8"));
  } catch {
    return {};
  }
}

async function rpcCall(fn, label, attempts = 6) {
  let last;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (error) {
      last = error;
      const msg = String(error?.message || error);
      const retryable =
        msg.includes("request rate exceeded") ||
        msg.includes("-32005") ||
        msg.includes("Too many requests") ||
        msg.includes("could not coalesce error");
      if (!retryable || i === attempts - 1) break;
      await sleep(350 * (i + 1));
    }
  }
  throw new Error(`${label}: ${last?.message || last}`);
}

async function httpJson(url, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(url, {
      method: body ? "POST" : "GET",
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const text = await res.text();
    let data = text;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {}
    return { ok: res.ok, status: res.status, data };
  } finally {
    clearTimeout(timer);
  }
}

async function mcpCall(port, name, args) {
  return httpJson(`http://127.0.0.1:${port}/mcp`, {
    jsonrpc: "2.0",
    id: Date.now(),
    method: "tools/call",
    params: { name, arguments: args },
  });
}

async function mcpTools(port) {
  const response = await httpJson(`http://127.0.0.1:${port}/mcp`, {
    jsonrpc: "2.0",
    id: Date.now(),
    method: "tools/list",
    params: {},
  });
  if (!response.ok) return [];
  return response.data?.result?.tools?.map((tool) => tool.name) || [];
}

function pickTool(tools, preferred, fallback) {
  if (tools.includes(preferred)) return preferred;
  if (tools.includes(fallback)) return fallback;
  return preferred;
}

function makeProvider() {
  const rpcUrl = process.env.EVM_RPC_URL || process.env.OG_RPC_URL || "https://evmrpc-testnet.0g.ai";
  return new ethers.JsonRpcProvider(
    rpcUrl,
    { chainId: 16602, name: "0g-galileo" },
    { staticNetwork: true, batchMaxCount: 1 }
  );
}

function wallets(provider) {
  const keys = [
    ["Agent A", process.env.AGENT_A_PRIVATE_KEY || process.env.AGENT_PRIVATE_KEY || process.env.PRIVATE_KEY],
    ["Agent B", process.env.AGENT_B_PRIVATE_KEY],
    ["Agent C", process.env.AGENT_C_PRIVATE_KEY],
  ];
  const seen = new Set();
  return keys
    .filter(([, key]) => key && /^0x[0-9a-fA-F]{64}$/.test(key))
    .map(([name, key]) => [name, new ethers.Wallet(key, provider)])
    .filter(([, wallet]) => {
      const lower = wallet.address.toLowerCase();
      if (seen.has(lower)) return false;
      seen.add(lower);
      return true;
    });
}

async function discoverMarkets(factory, provider) {
  const count = Number(await rpcCall(() => factory.marketCount(), "factory.marketCount"));
  const markets = [];
  for (let id = 1; id <= count; id++) {
    const rec = await rpcCall(() => factory.markets(id), `factory.markets(${id})`);
    const market = new ethers.Contract(rec.market, MARKET_ABI, provider);
    const [state, cfg, implied, yesPool, noPool, total] = await Promise.all([
      rpcCall(() => market.state(), `market(${id}).state`),
      rpcCall(() => market.config(), `market(${id}).config`),
      rpcCall(() => market.impliedProbabilityYes(), `market(${id}).impliedProbabilityYes`),
      rpcCall(() => market.yesPool(), `market(${id}).yesPool`),
      rpcCall(() => market.noPool(), `market(${id}).noPool`),
      rpcCall(() => market.totalCollateral(), `market(${id}).totalCollateral`),
    ]);
    markets.push({
      id,
      address: rec.market,
      creator: rec.creator,
      category: rec.category,
      active: rec.active,
      questionURI: rec.questionURI,
      stateId: Number(state),
      state: MARKET_STATE[Number(state)] || String(state),
      createdAt: Number(cfg.createdAt),
      resolutionTime: Number(cfg.resolutionTime),
      minBet: cfg.minBet,
      implied,
      yesPool,
      noPool,
      total,
    });
    await sleep(80);
  }
  return markets;
}

function chooseMarket(markets, activeSessions) {
  if (requestedMarket) {
    const found = markets.find((m) => m.address.toLowerCase() === requestedMarket.toLowerCase());
    if (!found) throw new Error(`Requested market not found in factory: ${requestedMarket}`);
    return found;
  }
  const activeSet = new Set(activeSessions.map((a) => a.toLowerCase()));
  return (
    markets.find((m) => activeSet.has(m.address.toLowerCase())) ||
    markets.find((m) => m.state === "OPEN" && Math.floor(Date.now() / 1000) >= m.resolutionTime) ||
    markets.find((m) => m.state === "OPEN") ||
    markets[0]
  );
}

async function printAxlAndMcp(target) {
  section("3. Multi-Agent Communication");
  for (const port of AXL_PORTS) {
    try {
      const topology = await httpJson(`http://127.0.0.1:${port}/topology`);
      if (!topology.ok) {
        console.log(`[warn] AXL ${port}: topology status=${topology.status}`);
        continue;
      }
      const peers = Array.isArray(topology.data?.peers) ? topology.data.peers.length : "unknown";
      console.log(`[ok] AXL ${port}: reachable peers=${peers}`);
    } catch (error) {
      console.log(`[warn] AXL ${port}: ${error.message}`);
    }
  }

  for (const port of MCP_PORTS) {
    try {
      const tools = await mcpTools(port);
      const cardTool = pickTool(tools, "get_agent_card", "get_card");
      const voteTool = pickTool(tools, "get_vote_intention", "get_vote");
      console.log(`[ok] MCP ${port}.tools: ${tools.join(", ") || "unknown"}`);
      const card = await mcpCall(port, cardTool, {});
      const probability = await mcpCall(port, "get_probability", { market_address: target.address });
      const vote = await mcpCall(port, voteTool, { market_address: target.address });
      const cardText = card.data?.result?.content?.[0]?.text || "{}";
      const probabilityText = probability.data?.result?.content?.[0]?.text || "{}";
      const voteText = vote.data?.result?.content?.[0]?.text || "{}";
      console.log(`[ok] MCP ${port}.${cardTool}: ${cardText.slice(0, 140)}`);
      console.log(`[ok] MCP ${port}.get_probability: ${probabilityText.slice(0, 180)}`);
      console.log(`[ok] MCP ${port}.${voteTool}: ${voteText.slice(0, 180)}`);
    } catch (error) {
      console.log(`[warn] MCP ${port}: ${error.message}`);
    }
  }
}

async function printAgents(registry, provider) {
  section("4. Verified Agent Readiness");
  const all = wallets(provider);
  row("configured wallets", all.length);
  row("network verified total", (await rpcCall(() => registry.totalVerifiedAgents(), "registry.totalVerifiedAgents")).toString());
  for (const [name, wallet] of all) {
    const verified = await rpcCall(() => registry.isVerified(wallet.address), `registry.isVerified(${name})`);
    let details = "";
    try {
      const agent = await rpcCall(() => registry.getAgent(wallet.address), `registry.getAgent(${name})`);
      details = ` agentId=${agent.agentId} tier=${agent.tier} stake=${fmtToken(agent.stakedAmount)}`;
    } catch {}
    console.log(`${name.padEnd(8)} ${wallet.address} verified=${verified}${details}`);
    await sleep(80);
  }
}

async function executeVoteFlow(resolver, registry, provider, target) {
  const all = wallets(provider);
  if (!execute) {
    row("vote mode", `dry-run, planned choice=${VOTE_NAME[choice]}`);
    return;
  }
  for (const [name, wallet] of all) {
    const verified = await rpcCall(() => registry.isVerified(wallet.address), `registry.isVerified(${name})`);
    if (!verified) {
      console.log(`[skip] ${name}: not verified`);
      continue;
    }
    const vote = await rpcCall(() => resolver.getVote(target.address, wallet.address), `resolver.getVote(${name})`);
    if (vote.cast) {
      console.log(`[skip] ${name}: already voted ${VOTE_NAME[Number(vote.choice)]}`);
      continue;
    }
    const writeResolver = resolver.connect(wallet);
    const tx = await writeResolver.castVerifiedVote(target.address, choice, ethers.ZeroHash, "0x");
    console.log(`[tx] ${name} cast ${VOTE_NAME[choice]}: ${tx.hash}`);
    await tx.wait();
    await sleep(500);
  }
}

async function main() {
  const provider = makeProvider();
  const primaryWallets = wallets(provider);
  const signer = primaryWallets[0]?.[1] || provider;
  const factory = new ethers.Contract(process.env.MARKET_FACTORY_ADDRESS || ADDR.MarketFactory, FACTORY_ABI, signer);
  const registry = new ethers.Contract(process.env.AGENT_REGISTRY_ADDRESS || ADDR.AgentRegistry, REGISTRY_ABI, signer);
  const resolver = new ethers.Contract(process.env.COLLECTIVE_RESOLVER_ADDRESS || ADDR.CollectiveResolver, RESOLVER_ABI, signer);
  const metadata = readMetadata();

  section("1. Resolution Test Configuration");
  const network = await rpcCall(() => provider.getNetwork(), "provider.getNetwork");
  row("network", `${network.name} chainId=${network.chainId}`);
  row("execute writes", execute);
  row("finalize", finalize);
  row("vote choice", VOTE_NAME[choice]);
  row("resolver requirePoIR", await rpcCall(() => resolver.requirePoIR(), "resolver.requirePoIR"));

  section("2. Market Selection");
  const [markets, activeSessions] = await Promise.all([
    discoverMarkets(factory, provider),
    rpcCall(() => resolver.getActiveSessions(), "resolver.getActiveSessions"),
  ]);
  row("factory markets", markets.length);
  row("active sessions", activeSessions.length);
  const target = chooseMarket(markets, activeSessions);
  const meta = metadata[target.address] || {};
  row("target id", `#${target.id}`);
  row("target market", target.address);
  row("state", target.state);
  row("category", target.category);
  row("question", meta.question || "metadata not synced");
  row("criteria", meta.resolutionCriteria || "metadata not synced");
  row("question URI", target.questionURI);
  row("resolution time", new Date(target.resolutionTime * 1000).toISOString());
  row("yes/no pools", `${fmtToken(target.yesPool)} / ${fmtToken(target.noPool)} PRED`);
  row("implied YES", fmtPct(target.implied));

  await printAxlAndMcp(target);
  await printAgents(registry, provider);

  section("5. Resolution Gate");
  const now = Math.floor(Date.now() / 1000);
  const market = new ethers.Contract(target.address, MARKET_ABI, signer);
  const isMature = now >= target.resolutionTime;
  row("now", new Date(now * 1000).toISOString());
  row("mature", isMature);
  if (target.state === "OPEN" && isMature) {
    if (!execute) {
      row("triggerResolution", "ready; rerun with --execute to open voting");
    } else {
      const tx = await market.triggerResolution();
      row("trigger tx", tx.hash);
      await tx.wait();
    }
  } else if (target.state === "OPEN") {
    const remaining = target.resolutionTime - now;
    row("triggerResolution", `blocked until ${new Date(target.resolutionTime * 1000).toISOString()} (${remaining}s)`);
  } else {
    row("triggerResolution", "not needed; market already resolving/final");
  }

  section("6. Voting And Quorum");
  const votingOpen = await rpcCall(() => resolver.isVotingOpen(target.address), "resolver.isVotingOpen");
  row("voting open", votingOpen);
  if (votingOpen) {
    await executeVoteFlow(resolver, registry, provider, target);
  } else {
    row("vote action", "blocked until market enters RESOLVING");
  }
  const session = await rpcCall(() => resolver.getSession(target.address), "resolver.getSession").catch(() => null);
  if (session && session.market !== ethers.ZeroAddress) {
    row("session state", SESSION_STATE[Number(session.state)] || String(session.state));
    row("voters", session.voterCount.toString());
    row("weighted YES", session.weightedYes.toString());
    row("weighted NO", session.weightedNo.toString());
    row("weighted INVALID", session.weightedInvalid.toString());
    row("deadline", new Date(Number(session.votingDeadline) * 1000).toISOString());
  } else {
    row("session", "none");
  }

  section("7. Finalization And Settlement");
  const refreshedState = Number(await rpcCall(() => market.state(), "market.state"));
  row("market state", MARKET_STATE[refreshedState] || refreshedState);
  if (!session || session.market === ethers.ZeroAddress) {
    row("settlement", "no session yet; trigger resolution first when mature");
  } else {
    const deadline = Number(session.votingDeadline);
    const canFinalize = Math.floor(Date.now() / 1000) > deadline && !session.finalized;
    row("can finalize", canFinalize);
    if (canFinalize && execute && finalize) {
      const tx = await resolver.finalizeResolution(target.address);
      row("finalize tx", tx.hash);
      await tx.wait();
    } else if (canFinalize) {
      row("finalize action", "ready; rerun with --execute --finalize");
    } else if (session.finalized) {
      row("finalize action", "already finalized");
    } else {
      row("finalize action", `blocked until voting deadline ${new Date(deadline * 1000).toISOString()}`);
    }
    if (execute && distribute && session.finalized && session.rewardPool > 0n && !session.rewardDistributed) {
      const tx = await resolver.distributeRewards(target.address);
      row("reward tx", tx.hash);
      await tx.wait();
    }
  }

  section("8. Test Outcome");
  console.log("Market discovery: ok");
  console.log("AXL node communication: checked");
  console.log("MCP agent calls: checked");
  console.log("Resolution trigger gate: checked");
  console.log("Multi-agent voting gate: checked");
  console.log(execute ? "Write mode: executed every eligible action" : "Write mode: dry-run only; no chain state changed");
}

main().catch((error) => {
  console.error(`\n[fail] ${error.stack || error.message}`);
  process.exit(1);
});
