#!/usr/bin/env node

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const { ethers } = require("ethers");
require("dotenv").config();

const ROOT = path.resolve(__dirname, "..");
const ADDRESSES_PATH = path.join(ROOT, "deployments", "addresses.json");

const FACTORY_ABI = [
  "function marketCount() view returns (uint256)",
  "function markets(uint256) view returns (address market,address creator,uint256 agentId,uint256 createdAt,uint256 resolutionTime,string questionURI,string category,bool active)",
  "function marketCreationStake() view returns (uint256)",
  "function minResolutionDelay() view returns (uint256)",
  "function maxResolutionDelay() view returns (uint256)",
  "function paused() view returns (bool)",
];

const MARKET_ABI = [
  "function state() view returns (uint8)",
  "function config() view returns (bytes32 questionHash,string questionURI,uint256 createdAt,uint256 resolutionTime,uint256 bettingCloseTime,uint256 creatorAgentId,address creator,uint256 minBet,string category)",
  "function yesPool() view returns (uint256)",
  "function noPool() view returns (uint256)",
  "function totalCollateral() view returns (uint256)",
  "function impliedProbabilityYes() view returns (uint256)",
];

const REGISTRY_ABI = [
  "function totalVerifiedAgents() view returns (uint256)",
  "function isVerified(address) view returns (bool)",
  "function getAgent(address) view returns ((uint256 agentId,address agentAddress,uint8 tier,uint256 stakedAmount,uint256 reputationScore,uint256 totalResolutions,uint256 correctResolutions,uint256 registeredAt,string metadataURI,bool slashed,bytes32 storageLogRoot,string kvStreamId,uint256 inftTokenId,uint256 researchReportsCount))",
];

const RESOLVER_ABI = [
  "function requirePoIR() view returns (bool)",
  "function getActiveSessions() view returns (address[])",
  "function getSession(address) view returns (address market,uint256 marketResolutionTime,uint256 votingDeadline,uint256 extensions,uint8 state,uint256 weightedYes,uint256 weightedNo,uint256 weightedInvalid,uint256 voterCount,uint8 finalOutcome,bool finalized,uint256 rewardPool,bool rewardDistributed)",
];

const ERC20_ABI = [
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address,address) view returns (uint256)",
  "function decimals() view returns (uint8)",
  "function symbol() view returns (string)",
];

const STATE = ["OPEN", "RESOLVING", "RESOLVED", "INVALID"];
const SESSION_STATE = ["NONE", "VOTING", "EXTENDED", "FINALIZED", "FAILED"];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function rpcCall(fn, label = "rpc", attempts = 5) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      const message = String(error?.message || error);
      const retryable =
        message.includes("request rate exceeded") ||
        message.includes("-32005") ||
        message.includes("Too many requests") ||
        message.includes("missing revert data") ||
        message.includes("could not coalesce error");
      if (!retryable || attempt === attempts - 1) break;
      await sleep(300 * (attempt + 1));
    }
  }
  throw new Error(`${label}: ${lastError?.message || lastError}`);
}

function readAddresses() {
  if (!fs.existsSync(ADDRESSES_PATH)) {
    throw new Error(`Missing deployments file: ${ADDRESSES_PATH}`);
  }
  return JSON.parse(fs.readFileSync(ADDRESSES_PATH, "utf8"));
}

function envAddress(name, fallback) {
  return process.env[name] || fallback;
}

function ok(label, detail = "") {
  console.log(`[ok] ${label}${detail ? `: ${detail}` : ""}`);
}

function warn(label, detail = "") {
  console.log(`[warn] ${label}${detail ? `: ${detail}` : ""}`);
}

function fail(label, detail = "") {
  console.log(`[fail] ${label}${detail ? `: ${detail}` : ""}`);
}

async function httpJson(url, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3500);
  try {
    const res = await fetch(url, {
      method: body ? "POST" : "GET",
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const text = await res.text();
    let parsed = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = text;
    }
    return { ok: res.ok, status: res.status, data: parsed };
  } finally {
    clearTimeout(timer);
  }
}

async function checkContractCode(provider, name, address) {
  if (!address || !ethers.isAddress(address)) {
    fail(`${name} address`, address || "missing");
    return false;
  }
  const code = await rpcCall(() => provider.getCode(address), `getCode(${name})`);
  if (code === "0x") {
    fail(`${name} bytecode`, `${address} has no code`);
    return false;
  }
  ok(`${name} bytecode`, `${address} (${(code.length - 2) / 2} bytes)`);
  return true;
}

async function checkMarkets(provider, addresses) {
  const factory = new ethers.Contract(addresses.MarketFactory, FACTORY_ABI, provider);
  const count = Number(await rpcCall(() => factory.marketCount(), "factory.marketCount"));
  const paused = await rpcCall(() => factory.paused(), "factory.paused");
  const creationStake = ethers.formatUnits(await rpcCall(() => factory.marketCreationStake(), "factory.marketCreationStake"), 18);
  ok("MarketFactory", `marketCount=${count}, paused=${paused}, creationStake=${creationStake} PRED`);

  if (count === 0) {
    warn("Listed markets", "none found yet");
    return [];
  }

  const markets = [];
  for (let id = 1; id <= count; id++) {
    const rec = await rpcCall(() => factory.markets(id), `factory.markets(${id})`);
    const market = new ethers.Contract(rec.market, MARKET_ABI, provider);
    const state = await rpcCall(() => market.state(), `market(${id}).state`);
    const yesPool = await rpcCall(() => market.yesPool(), `market(${id}).yesPool`);
    const noPool = await rpcCall(() => market.noPool(), `market(${id}).noPool`);
    const totalCollateral = await rpcCall(() => market.totalCollateral(), `market(${id}).totalCollateral`);
    const implied = await rpcCall(() => market.impliedProbabilityYes(), `market(${id}).impliedProbabilityYes`);
    const config = await rpcCall(() => market.config(), `market(${id}).config`);
    const item = {
      id,
      market: rec.market,
      questionURI: rec.questionURI,
      category: rec.category,
      active: rec.active,
      state: STATE[Number(state)] || String(state),
      resolutionTime: Number(rec.resolutionTime),
      yesPool: ethers.formatUnits(yesPool, 18),
      noPool: ethers.formatUnits(noPool, 18),
      totalCollateral: ethers.formatUnits(totalCollateral, 18),
      impliedYesPct: (Number(implied) / 100).toFixed(2),
    };
    markets.push(item);
    ok(
      `Market #${id}`,
      `${item.market} ${item.state} ${item.category} yes=${item.impliedYesPct}% uri=${item.questionURI}`
    );
    if (config.questionURI !== rec.questionURI) {
      warn(`Market #${id} config mismatch`, "factory URI differs from market config URI");
    }
    await sleep(100);
  }
  return markets;
}

async function checkRegistry(provider, addresses, wallet) {
  const registry = new ethers.Contract(addresses.AgentRegistry, REGISTRY_ABI, provider);
  const verifiedCount = Number(await rpcCall(() => registry.totalVerifiedAgents(), "registry.totalVerifiedAgents"));
  ok("Registry", `totalVerifiedAgents=${verifiedCount}`);
  if (!wallet) return;

  const verified = await rpcCall(() => registry.isVerified(wallet), "registry.isVerified");
  const agent = await rpcCall(() => registry.getAgent(wallet), "registry.getAgent");
  ok(
    "Current wallet agent",
    `agentId=${agent.agentId} tier=${agent.tier} verified=${verified} stake=${ethers.formatUnits(agent.stakedAmount, 18)} slashed=${agent.slashed}`
  );
}

async function checkResolver(provider, addresses) {
  const resolver = new ethers.Contract(addresses.CollectiveResolver, RESOLVER_ABI, provider);
  const requirePoIR = await rpcCall(() => resolver.requirePoIR(), "resolver.requirePoIR");
  const active = await rpcCall(() => resolver.getActiveSessions(), "resolver.getActiveSessions");
  ok("Resolver", `requirePoIR=${requirePoIR}, activeSessions=${active.length}`);
  for (const market of active) {
    const s = await rpcCall(() => resolver.getSession(market), `resolver.getSession(${market})`);
    ok(
      `Resolution session ${market}`,
      `state=${SESSION_STATE[Number(s.state)] || s.state} voters=${s.voterCount} deadline=${new Date(Number(s.votingDeadline) * 1000).toISOString()}`
    );
  }
}

async function checkBalances(provider, addresses, wallet) {
  if (!wallet) return;
  const token = new ethers.Contract(addresses.PredToken, ERC20_ABI, provider);
  const symbol = await rpcCall(() => token.symbol(), "pred.symbol");
  const decimals = await rpcCall(() => token.decimals(), "pred.decimals");
  const balance = await rpcCall(() => token.balanceOf(wallet), "pred.balanceOf");
  let allowance = 0n;
  try {
    allowance = await rpcCall(() => token.allowance(wallet, addresses.MarketFactory), "pred.allowance");
  } catch (error) {
    warn("PRED allowance", error.message);
  }
  ok(
    `${symbol} balance`,
    `wallet=${ethers.formatUnits(balance, decimals)}, factoryAllowance=${ethers.formatUnits(allowance, decimals)}`
  );
}

async function checkAxlAndMcp() {
  const axlPorts = [9002, 9012, 9022];
  const mcpPorts = [9003, 9013, 9023];

  for (const port of axlPorts) {
    try {
      const topology = await httpJson(`http://127.0.0.1:${port}/topology`);
      if (topology.ok) {
        const peers = Array.isArray(topology.data?.peers) ? topology.data.peers.length : "unknown";
        ok(`AXL node ${port}`, `topology reachable, peers=${peers}`);
      } else {
        warn(`AXL node ${port}`, `topology status ${topology.status}`);
      }
    } catch (e) {
      warn(`AXL node ${port}`, e.message);
    }
  }

  for (const port of mcpPorts) {
    try {
      const tools = await httpJson(`http://127.0.0.1:${port}/mcp`, {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/list",
        params: {},
      });
      if (tools.ok) {
        const names = tools.data?.result?.tools?.map((t) => t.name).join(", ") || "none";
        ok(`MCP tools ${port}`, names);
      } else {
        warn(`MCP tools ${port}`, `status ${tools.status}`);
      }
    } catch (e) {
      warn(`MCP ${port}`, e.message);
    }
  }
}

function runUploadDiagnostic() {
  const tmp = path.join(os.tmpdir(), `agentmarket-0g-diag-${Date.now()}.json`);
  fs.writeFileSync(
    tmp,
    JSON.stringify({ type: "agentmarket-diagnostic", createdAt: new Date().toISOString() }, null, 2)
  );
  try {
    const result = spawnSync(process.execPath, [path.join(ROOT, "scripts", "zg-upload.mjs"), tmp], {
      cwd: ROOT,
      env: {
        ...process.env,
        PRIVATE_KEY: process.env.PRIVATE_KEY || process.env.AGENT_A_PRIVATE_KEY || process.env.AGENT_PRIVATE_KEY,
      },
      encoding: "utf8",
      timeout: 120000,
    });
    if (result.status !== 0) {
      fail("0G upload", (result.stderr || result.stdout || "unknown error").trim());
      process.exitCode = 1;
      return;
    }
    const line = result.stdout.trim().split(/\r?\n/).reverse().find((value) => value.trim().startsWith("{"));
    const parsed = JSON.parse(line);
    ok("0G upload", `root=${parsed.rootHash} tx=${parsed.txHash || "n/a"}`);
  } finally {
    fs.rmSync(tmp, { force: true });
  }
}

async function main() {
  const args = new Set(process.argv.slice(2));
  if (args.has("--checkAxlAndMcp")) {
    await checkAxlAndMcp();
    return;
  }

  const deployments = readAddresses();
  const addresses = {
    PredToken: envAddress("PRED_TOKEN_ADDRESS", deployments.PredToken),
    PositionToken: envAddress("POSITION_TOKEN_ADDRESS", deployments.PositionToken),
    AgentRegistry: envAddress("AGENT_REGISTRY_ADDRESS", deployments.AgentRegistry),
    MarketFactory: envAddress("MARKET_FACTORY_ADDRESS", deployments.MarketFactory),
    CollectiveResolver: envAddress("COLLECTIVE_RESOLVER_ADDRESS", deployments.CollectiveResolver),
    INFTOracle: envAddress("INFT_ORACLE_ADDRESS", deployments.INFTOracle),
    INFT: envAddress("INFT_CONTRACT", deployments.INFT),
  };
  const rpcUrl = process.env.EVM_RPC_URL || process.env.OG_RPC_URL || "https://evmrpc-testnet.0g.ai";
  const provider = new ethers.JsonRpcProvider(
    rpcUrl,
    { chainId: 16602, name: "0g-galileo" },
    { staticNetwork: true, batchMaxCount: 1 }
  );
  const network = await rpcCall(() => provider.getNetwork(), "provider.getNetwork");
  ok("RPC", `${rpcUrl} chainId=${network.chainId}`);

  for (const [name, address] of Object.entries(addresses)) {
    await checkContractCode(provider, name, address);
  }

  let wallet = "";
  const pk = process.env.PRIVATE_KEY || process.env.AGENT_A_PRIVATE_KEY || process.env.AGENT_PRIVATE_KEY;
  if (pk) {
    wallet = new ethers.Wallet(pk).address;
    ok("Diagnostic wallet", wallet);
  } else {
    warn("Diagnostic wallet", "no PRIVATE_KEY/AGENT_A_PRIVATE_KEY found");
  }

  await checkRegistry(provider, addresses, wallet);
  await checkBalances(provider, addresses, wallet);
  await checkMarkets(provider, addresses);
  await checkResolver(provider, addresses);
  await checkAxlAndMcp();

  if (args.has("--upload")) {
    runUploadDiagnostic();
  } else {
    warn("0G upload", "skipped; run `npm run diagnostics:upload` to perform a real paid SDK upload");
  }
}

main().catch((error) => {
  fail("Diagnostics crashed", error.stack || error.message);
  process.exit(1);
});
