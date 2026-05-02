#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { ethers } = require("ethers");
require("dotenv").config();

const ROOT = path.resolve(__dirname, "..");
const DEMO_DIR = path.join(ROOT, ".demo");
const LATEST_FILE = path.join(DEMO_DIR, "latest-market.json");
const META_FILE = path.join(ROOT, "public", "market-metadata.json");
const ADDR = JSON.parse(fs.readFileSync(path.join(ROOT, "deployments", "addresses.json"), "utf8"));

const FACTORY_ABI = [
  "function marketCount() view returns (uint256)",
  "function markets(uint256) view returns (address market,address creator,uint256 agentId,uint256 createdAt,uint256 resolutionTime,string questionURI,string category,bool active)",
  "function getMarket(uint256) view returns (address market,address creator,uint256 agentId,uint256 createdAt,uint256 resolutionTime,string questionURI,string category,bool active)",
  "function marketCreationStake() view returns (uint256)",
  "function minResolutionDelay() view returns (uint256)",
  "function createMarket(string questionURI,uint256 resolutionTime,string category,uint256 minBet) returns (address)",
];
const MARKET_ABI = [
  "function state() view returns (uint8)",
  "function config() view returns (bytes32 questionHash,string questionURI,uint256 createdAt,uint256 resolutionTime,uint256 bettingCloseTime,uint256 creatorAgentId,address creator,uint256 minBet,string category)",
  "function yesPool() view returns (uint256)",
  "function noPool() view returns (uint256)",
  "function totalCollateral() view returns (uint256)",
  "function impliedProbabilityYes() view returns (uint256)",
  "function outcome() view returns (uint8)",
  "function bet(uint8 outcomeIndex,uint256 amount)",
  "function triggerResolution()",
  "function claimWinnings()",
  "function claimRefund()",
];
const REGISTRY_ABI = [
  "function isVerified(address) view returns (bool)",
  "function getAgent(address) view returns (tuple(uint256 agentId,address agentAddress,uint8 tier,uint256 stakedAmount,uint256 reputationScore,uint256 totalResolutions,uint256 correctResolutions,uint256 registeredAt,string metadataURI,bool slashed,bytes32 storageLogRoot,string kvStreamId,uint256 inftTokenId,uint256 researchReportsCount))",
  "function register(string metadataURI,uint256 stakeAmount,string kvStreamId)",
];
const RESOLVER_ABI = [
  "function isVotingOpen(address market) view returns (bool)",
  "function getSession(address market) view returns (address market,uint256 marketResolutionTime,uint256 votingDeadline,uint256 extensions,uint8 state,uint256 weightedYes,uint256 weightedNo,uint256 weightedInvalid,uint256 voterCount,uint8 finalOutcome,bool finalized,uint256 rewardPool,bool rewardDistributed)",
  "function getVote(address market,address voter) view returns (uint8 choice,uint256 weight,bool cast,bool rewarded,bytes32 storageLogRoot,bytes teeSignature,bool hasPoIR)",
  "function castVerifiedVote(address market,uint8 choice,bytes32 storageLogRoot,bytes teeSignature)",
  "function finalizeResolution(address market)",
  "function distributeRewards(address market)",
];
const TOKEN_ABI = [
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address,address) view returns (uint256)",
  "function approve(address,uint256) returns (bool)",
];

const MARKET_STATES = ["OPEN", "RESOLVING", "RESOLVED", "INVALID"];
const SESSION_STATES = ["NONE", "VOTING", "EXTENDED", "FINALIZED", "FAILED"];
const OUTCOMES = { NO: 0, YES: 1, INVALID: 2 };
const OUTCOME_NAMES = ["NO", "YES", "INVALID"];

const argv = process.argv.slice(2);
const command = argv[0] || "help";
const flag = (name) => argv.includes(`--${name}`);
const option = (name, fallback = "") => {
  const prefix = `--${name}=`;
  const value = argv.find((item) => item.startsWith(prefix));
  return value ? value.slice(prefix.length) : fallback;
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const fmt = (value) => ethers.formatEther(value);
const short = (addr = "") => addr ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : "unknown";
const now = () => Math.floor(Date.now() / 1000);

function section(title) {
  console.log(`\n=== ${title} ===`);
}

function row(label, value) {
  console.log(`${label.padEnd(22)} ${value}`);
}

function rpcUrl() {
  return process.env.EVM_RPC_URL || process.env.OG_RPC_URL || "https://evmrpc-testnet.0g.ai";
}

function provider() {
  return new ethers.JsonRpcProvider(
    rpcUrl(),
    { chainId: 16602, name: "0g-galileo" },
    { staticNetwork: true, batchMaxCount: 1 }
  );
}

function keyFor(agentName) {
  const agent = String(agentName || option("agent", "A")).toUpperCase();
  const key =
    process.env[`AGENT_${agent}_PRIVATE_KEY`] ||
    (agent === "A" ? process.env.AGENT_PRIVATE_KEY || process.env.PRIVATE_KEY : "");
  if (!/^0x[0-9a-fA-F]{64}$/.test(key || "")) {
    throw new Error(`Missing valid private key for Agent ${agent}. Set AGENT_${agent}_PRIVATE_KEY in .env.`);
  }
  return { agent, key };
}

function signerFor(agentName) {
  const { agent, key } = keyFor(agentName);
  return { agent, wallet: new ethers.Wallet(key, provider()) };
}

function contracts(signerOrProvider) {
  return {
    pred: new ethers.Contract(process.env.PRED_TOKEN_ADDRESS || ADDR.PredToken, TOKEN_ABI, signerOrProvider),
    factory: new ethers.Contract(process.env.MARKET_FACTORY_ADDRESS || ADDR.MarketFactory, FACTORY_ABI, signerOrProvider),
    registry: new ethers.Contract(process.env.AGENT_REGISTRY_ADDRESS || ADDR.AgentRegistry, REGISTRY_ABI, signerOrProvider),
    resolver: new ethers.Contract(process.env.COLLECTIVE_RESOLVER_ADDRESS || ADDR.CollectiveResolver, RESOLVER_ABI, signerOrProvider),
  };
}

async function rpcCall(fn, label, attempts = 6) {
  let last;
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await fn();
    } catch (error) {
      last = error;
      const message = String(error?.message || error);
      const retry = message.includes("request rate exceeded") || message.includes("Too many requests") || message.includes("-32005") || message.includes("could not coalesce");
      if (!retry || i === attempts - 1) break;
      await sleep(300 * (i + 1));
    }
  }
  throw new Error(`${label}: ${last?.shortMessage || last?.message || last}`);
}

async function ensureAllowance(token, owner, spender, amount) {
  const allowance = await rpcCall(() => token.allowance(owner, spender), "token.allowance");
  if (allowance >= amount) return null;
  const tx = await token.approve(spender, amount);
  console.log(`[tx] approve ${spender}: ${tx.hash}`);
  await tx.wait();
  return tx.hash;
}

function readLatest() {
  if (!fs.existsSync(LATEST_FILE)) throw new Error("No latest market found. Run create first or pass --market=0x...");
  return JSON.parse(fs.readFileSync(LATEST_FILE, "utf8"));
}

function resolveMarketArg() {
  const market = option("market", "latest");
  if (market && market !== "latest") return market;
  return readLatest().market;
}

function readMetadataCache() {
  if (!fs.existsSync(META_FILE)) return {};
  try { return JSON.parse(fs.readFileSync(META_FILE, "utf8")); } catch { return {}; }
}

function writeMetadataCache(market, metadata) {
  fs.mkdirSync(path.dirname(META_FILE), { recursive: true });
  const cache = readMetadataCache();
  cache[market] = { ...(cache[market] || {}), ...metadata, market, syncedAt: new Date().toISOString() };
  fs.writeFileSync(META_FILE, `${JSON.stringify(cache, null, 2)}\n`, "utf8");
}

function uploadQuestion(metadata, privateKey) {
  fs.mkdirSync(DEMO_DIR, { recursive: true });
  const file = path.join(DEMO_DIR, `question-${Date.now()}.json`);
  fs.writeFileSync(file, `${JSON.stringify(metadata, null, 2)}\n`, "utf8");
  const result = spawnSync(process.execPath, [path.join(ROOT, "scripts", "zg-upload.mjs"), file], {
    cwd: ROOT,
    env: { ...process.env, PRIVATE_KEY: privateKey, AGENT_PRIVATE_KEY: privateKey },
    encoding: "utf8",
    timeout: 180000,
  });
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || "0G upload failed").trim());
  }
  const parsed = JSON.parse(result.stdout);
  if (!parsed.rootHash) throw new Error(`0G upload did not return rootHash: ${result.stdout}`);
  return { rootHash: parsed.rootHash, txHash: parsed.txHash, file };
}

async function listMarkets(limit = 8) {
  const p = provider();
  const { factory } = contracts(p);
  const count = Number(await rpcCall(() => factory.marketCount(), "factory.marketCount"));
  const cache = readMetadataCache();
  const start = Math.max(1, count - limit + 1);
  const rows = [];
  for (let id = start; id <= count; id += 1) {
    const rec = await rpcCall(() => factory.markets(id), `factory.markets(${id})`);
    const market = new ethers.Contract(rec.market, MARKET_ABI, p);
    const [state, cfg, implied, total] = await Promise.all([
      rpcCall(() => market.state(), `market.state(${id})`),
      rpcCall(() => market.config(), `market.config(${id})`),
      rpcCall(() => market.impliedProbabilityYes(), `market.implied(${id})`),
      rpcCall(() => market.totalCollateral(), `market.total(${id})`),
    ]);
    const meta = cache[rec.market] || cache[String(rec.market).toLowerCase()] || {};
    rows.push({ id, rec, state: Number(state), cfg, implied, total, meta });
    await sleep(80);
  }
  return { count, rows };
}

async function commandDoctor() {
  const { agent, wallet } = signerFor(option("agent", "A"));
  const c = contracts(wallet);
  section(`Agent ${agent} readiness`);
  row("wallet", wallet.address);
  row("chain", `${(await wallet.provider.getNetwork()).chainId}`);
  row("verified", await rpcCall(() => c.registry.isVerified(wallet.address), "registry.isVerified"));
  row("PRED balance", fmt(await rpcCall(() => c.pred.balanceOf(wallet.address), "pred.balanceOf")));
  try {
    const info = await rpcCall(() => c.registry.getAgent(wallet.address), "registry.getAgent");
    row("agent id", info.agentId.toString());
    row("tier", info.tier.toString());
    row("stake", `${fmt(info.stakedAmount)} PRED`);
    row("reputation", info.reputationScore.toString());
  } catch (error) {
    row("registry", error.message);
  }
}

async function commandRegister() {
  const { agent, wallet } = signerFor(option("agent", "A"));
  const c = contracts(wallet);
  const stake = ethers.parseEther(option("stake", "1000"));
  section(`Register Agent ${agent}`);
  const verified = await rpcCall(() => c.registry.isVerified(wallet.address), "registry.isVerified");
  if (verified) {
    console.log(`Agent ${agent} is already verified: ${wallet.address}`);
    return;
  }
  await ensureAllowance(c.pred, wallet.address, await c.registry.getAddress(), stake);
  const metadata = option("metadata", `0g://agent-${agent.toLowerCase()}-card`);
  const kv = option("kv", `agent-${agent.toLowerCase()}-kv`);
  const tx = await c.registry.register(metadata, stake, kv);
  console.log(`[tx] register: ${tx.hash}`);
  await tx.wait();
  console.log(`[ok] Agent ${agent} registered and verified`);
}

async function commandCreate() {
  const { agent, wallet, key } = (() => {
    const picked = keyFor(option("agent", "A"));
    return { ...picked, wallet: new ethers.Wallet(picked.key, provider()) };
  })();
  const c = contracts(wallet);
  section(`Agent ${agent} creates market`);
  const verified = await rpcCall(() => c.registry.isVerified(wallet.address), "registry.isVerified");
  if (!verified) throw new Error(`Agent ${agent} is not verified. Run: npm run demo:agent -- register --agent=${agent}`);

  const minDelay = Number(await rpcCall(() => c.factory.minResolutionDelay(), "factory.minResolutionDelay"));
  const requestedHours = Math.max(Number(option("hours", "1")), Math.ceil(minDelay / 3600));
  const resolutionTime = now() + Math.max(minDelay, Math.floor(requestedHours * 3600));
  const question = option("question", "Will the AgentMarket demo complete with three agent votes?");
  const resolutionCriteria = option("criteria", "Resolve YES if the live terminal demo shows one creator, two bettors, and three resolver votes recorded on-chain.");
  const category = option("category", "demo");
  const minBet = ethers.parseEther(option("min-bet", "1"));
  const creationStake = await rpcCall(() => c.factory.marketCreationStake(), "factory.marketCreationStake");
  const metadata = {
    question,
    resolutionCriteria,
    category,
    createdBy: wallet.address,
    createdByAgent: agent,
    demoFlow: true,
    createdAt: new Date().toISOString(),
    resolutionTime,
  };
  row("question", question);
  row("resolution", new Date(resolutionTime * 1000).toISOString());
  row("upload", "0G Storage SDK");
  const upload = uploadQuestion(metadata, key);
  const questionURI = `0g://${upload.rootHash}`;
  row("0G root", upload.rootHash);
  await ensureAllowance(c.pred, wallet.address, await c.factory.getAddress(), creationStake);
  const countBefore = Number(await rpcCall(() => c.factory.marketCount(), "factory.marketCount(before)"));
  const tx = await c.factory.createMarket(questionURI, resolutionTime, category, minBet);
  console.log(`[tx] createMarket: ${tx.hash}`);
  await tx.wait();
  const countAfter = Number(await rpcCall(() => c.factory.marketCount(), "factory.marketCount(after)"));
  const rec = await rpcCall(() => c.factory.markets(countAfter), "factory.markets(latest)");
  fs.mkdirSync(DEMO_DIR, { recursive: true });
  const latest = { market: rec.market, marketId: countAfter, question, category, questionURI, resolutionTime, creator: wallet.address, txHash: tx.hash };
  fs.writeFileSync(LATEST_FILE, `${JSON.stringify(latest, null, 2)}\n`, "utf8");
  writeMetadataCache(rec.market, { ...metadata, marketId: countAfter, market: rec.market, questionURI, active: true, creator: wallet.address, creatorAgentId: Number(rec.agentId) });
  row("market count", `${countBefore} -> ${countAfter}`);
  row("market", rec.market);
  console.log("[ok] Latest market saved to .demo/latest-market.json");
}

async function commandDiscover() {
  const agent = option("agent", "B").toUpperCase();
  section(`Agent ${agent} discovers markets`);
  const { count, rows } = await listMarkets(Number(option("limit", "8")));
  row("factory count", count);
  rows.forEach(({ id, rec, state, cfg, implied, total, meta }) => {
    console.log(`#${String(id).padStart(3)} ${rec.market} ${MARKET_STATES[state]} YES=${(Number(implied) / 100).toFixed(1)}% total=${fmt(total)} PRED`);
    console.log(`      ${meta.question || "metadata syncing"}`);
    console.log(`      resolves ${new Date(Number(cfg.resolutionTime) * 1000).toISOString()} uri=${cfg.questionURI}`);
  });
}

async function commandBet() {
  const { agent, wallet } = signerFor(option("agent", "B"));
  const marketAddress = resolveMarketArg();
  const side = option("side", "YES").toUpperCase();
  const outcome = OUTCOMES[side];
  if (outcome === undefined || outcome === 2) throw new Error("Bet side must be YES or NO");
  const amount = ethers.parseEther(option("amount", "10"));
  const c = contracts(wallet);
  const market = new ethers.Contract(marketAddress, MARKET_ABI, wallet);
  section(`Agent ${agent} bets ${side}`);
  row("wallet", wallet.address);
  row("market", marketAddress);
  row("amount", `${fmt(amount)} PRED`);
  if (!(await rpcCall(() => c.registry.isVerified(wallet.address), "registry.isVerified"))) {
    throw new Error(`Agent ${agent} is not verified. Run register first.`);
  }
  await ensureAllowance(c.pred, wallet.address, marketAddress, amount);
  const tx = await market.bet(outcome, amount);
  console.log(`[tx] bet ${side}: ${tx.hash}`);
  await tx.wait();
  await printMarketStatus(marketAddress);
}

async function printMarketStatus(marketAddress) {
  const p = provider();
  const market = new ethers.Contract(marketAddress, MARKET_ABI, p);
  const [state, cfg, yes, no, total, implied] = await Promise.all([
    rpcCall(() => market.state(), "market.state"),
    rpcCall(() => market.config(), "market.config"),
    rpcCall(() => market.yesPool(), "market.yesPool"),
    rpcCall(() => market.noPool(), "market.noPool"),
    rpcCall(() => market.totalCollateral(), "market.totalCollateral"),
    rpcCall(() => market.impliedProbabilityYes(), "market.impliedProbabilityYes"),
  ]);
  row("state", MARKET_STATES[Number(state)]);
  row("YES pool", `${fmt(yes)} PRED`);
  row("NO pool", `${fmt(no)} PRED`);
  row("total", `${fmt(total)} PRED`);
  row("YES probability", `${(Number(implied) / 100).toFixed(2)}%`);
  row("resolution", new Date(Number(cfg.resolutionTime) * 1000).toISOString());
}

async function commandStatus() {
  const marketAddress = resolveMarketArg();
  section(`Market status ${marketAddress}`);
  await printMarketStatus(marketAddress);
  const { resolver } = contracts(provider());
  try {
    const session = await rpcCall(() => resolver.getSession(marketAddress), "resolver.getSession");
    if (session.market === ethers.ZeroAddress) {
      row("session", "none");
    } else {
      row("session", SESSION_STATES[Number(session.state)]);
      row("voters", session.voterCount.toString());
      row("weights", `YES=${session.weightedYes} NO=${session.weightedNo} INVALID=${session.weightedInvalid}`);
      row("deadline", new Date(Number(session.votingDeadline) * 1000).toISOString());
      row("reward pool", `${fmt(session.rewardPool)} PRED`);
      row("rewards sent", session.rewardDistributed);
    }
  } catch (error) {
    row("session", error.message);
  }
}

async function commandResolve() {
  const { agent, wallet } = signerFor(option("agent", "C"));
  const marketAddress = resolveMarketArg();
  const market = new ethers.Contract(marketAddress, MARKET_ABI, wallet);
  section(`Agent ${agent} opens resolution`);
  const cfg = await rpcCall(() => market.config(), "market.config");
  const state = Number(await rpcCall(() => market.state(), "market.state"));
  row("market", marketAddress);
  row("state", MARKET_STATES[state]);
  row("resolution", new Date(Number(cfg.resolutionTime) * 1000).toISOString());
  if (state !== 0) {
    console.log("[ok] Market is already past OPEN state.");
    return;
  }
  if (now() < Number(cfg.resolutionTime)) {
    throw new Error(`Resolution is blocked until ${new Date(Number(cfg.resolutionTime) * 1000).toISOString()}. This is an on-chain safety gate.`);
  }
  const tx = await market.triggerResolution();
  console.log(`[tx] triggerResolution: ${tx.hash}`);
  await tx.wait();
  console.log("[ok] Voting session opened.");
}

async function commandVote() {
  const { agent, wallet } = signerFor(option("agent", "A"));
  const marketAddress = resolveMarketArg();
  const choiceName = option("choice", "YES").toUpperCase();
  const choice = OUTCOMES[choiceName];
  if (choice === undefined) throw new Error("Vote choice must be YES, NO, or INVALID");
  const c = contracts(wallet);
  section(`Agent ${agent} votes ${choiceName}`);
  if (!(await rpcCall(() => c.resolver.isVotingOpen(marketAddress), "resolver.isVotingOpen"))) {
    throw new Error("Voting is not open. Run resolve after the market resolution time.");
  }
  const current = await rpcCall(() => c.resolver.getVote(marketAddress, wallet.address), "resolver.getVote");
  if (current.cast) {
    console.log(`[skip] Agent ${agent} already voted ${OUTCOME_NAMES[Number(current.choice)]}`);
    return;
  }
  const root = ethers.keccak256(ethers.toUtf8Bytes(`${marketAddress}:${wallet.address}:${choiceName}:${Date.now()}`));
  const tx = await c.resolver.castVerifiedVote(marketAddress, choice, root, "0x");
  console.log(`[tx] castVerifiedVote: ${tx.hash}`);
  await tx.wait();
  await commandStatus();
}

async function commandFinalize() {
  const { agent, wallet } = signerFor(option("agent", "A"));
  const marketAddress = resolveMarketArg();
  const c = contracts(wallet);
  section(`Agent ${agent} finalizes settlement`);
  const session = await rpcCall(() => c.resolver.getSession(marketAddress), "resolver.getSession");
  if (session.market === ethers.ZeroAddress) throw new Error("No resolution session exists yet.");
  row("session", SESSION_STATES[Number(session.state)]);
  row("deadline", new Date(Number(session.votingDeadline) * 1000).toISOString());
  if (!session.finalized) {
    if (now() <= Number(session.votingDeadline)) {
      throw new Error(`Finalize blocked until voting deadline ${new Date(Number(session.votingDeadline) * 1000).toISOString()}.`);
    }
    const tx = await c.resolver.finalizeResolution(marketAddress);
    console.log(`[tx] finalizeResolution: ${tx.hash}`);
    await tx.wait();
  } else {
    console.log("[skip] Already finalized.");
  }
  const refreshed = await rpcCall(() => c.resolver.getSession(marketAddress), "resolver.getSession(after)");
  if (!refreshed.rewardDistributed && refreshed.rewardPool > 0n) {
    const tx = await c.resolver.distributeRewards(marketAddress);
    console.log(`[tx] distributeRewards: ${tx.hash}`);
    await tx.wait();
  } else {
    console.log("[skip] No resolver rewards to distribute or already distributed.");
  }
  await commandStatus();
}

function printCommands() {
  section("Terminal demo commands");
  console.log("Terminal 1 - creator creates a market:");
  console.log("  npm run demo:agent -- create --agent=A --question=\"Will AgentMarket complete the live demo?\" --hours=1 --category=demo");
  console.log("Terminal 2 - Agent B discovers and bets YES:");
  console.log("  npm run demo:agent -- discover --agent=B");
  console.log("  npm run demo:agent -- bet --agent=B --side=YES --amount=10 --market=latest");
  console.log("Terminal 3 - Agent C discovers and bets NO:");
  console.log("  npm run demo:agent -- discover --agent=C");
  console.log("  npm run demo:agent -- bet --agent=C --side=NO --amount=5 --market=latest");
  console.log("Terminal 4 - after the market resolution time, open voting and cast votes:");
  console.log("  npm run demo:agent -- resolve --agent=C --market=latest");
  console.log("  npm run demo:agent -- vote --agent=A --choice=YES --market=latest");
  console.log("  npm run demo:agent -- vote --agent=B --choice=YES --market=latest");
  console.log("  npm run demo:agent -- vote --agent=C --choice=YES --market=latest");
  console.log("Terminal 5 - after the 48h voting window, finalize and distribute rewards:");
  console.log("  npm run demo:agent -- finalize --agent=A --market=latest");
  console.log("Fast local settlement proof for screenshots:");
  console.log("  npm run demo:flow:local");
}

async function main() {
  switch (command) {
    case "doctor": return commandDoctor();
    case "register": return commandRegister();
    case "create": return commandCreate();
    case "discover": return commandDiscover();
    case "bet": return commandBet();
    case "status": return commandStatus();
    case "resolve": return commandResolve();
    case "vote": return commandVote();
    case "finalize": return commandFinalize();
    case "commands": return printCommands();
    case "help":
    default:
      printCommands();
  }
}

main().catch((error) => {
  console.error(`\n[fail] ${error.stack || error.message}`);
  process.exit(1);
});
