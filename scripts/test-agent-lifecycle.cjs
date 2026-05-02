#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");
require("dotenv").config();

const ROOT = path.resolve(__dirname, "..");
const ADDR = JSON.parse(fs.readFileSync(path.join(ROOT, "deployments", "addresses.json"), "utf8"));

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
  "function bet(uint8 outcomeIndex,uint256 amount)",
  "function triggerResolution()",
];
const REGISTRY_ABI = [
  "function isVerified(address) view returns (bool)",
  "function getAgent(address) view returns ((uint256 agentId,address agentAddress,uint8 tier,uint256 stakedAmount,uint256 reputationScore,uint256 totalResolutions,uint256 correctResolutions,uint256 registeredAt,string metadataURI,bool slashed,bytes32 storageLogRoot,string kvStreamId,uint256 inftTokenId,uint256 researchReportsCount))",
  "function totalVerifiedAgents() view returns (uint256)",
];
const RESOLVER_ABI = [
  "function getActiveSessions() view returns (address[])",
  "function isVotingOpen(address market) view returns (bool)",
  "function getSession(address market) view returns (address market,uint256 marketResolutionTime,uint256 votingDeadline,uint256 extensions,uint8 state,uint256 weightedYes,uint256 weightedNo,uint256 weightedInvalid,uint256 voterCount,uint8 finalOutcome,bool finalized,uint256 rewardPool,bool rewardDistributed)",
  "function getVote(address market,address voter) view returns (uint8 choice,uint256 weight,bool cast,bool rewarded,bytes32 storageLogRoot,bytes teeSignature,bool hasPoIR)",
  "function castVerifiedVote(address market,uint8 choice,bytes32 storageLogRoot,bytes teeSignature)",
  "function finalizeResolution(address market)",
];
const ERC20_ABI = [
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address,address) view returns (uint256)",
  "function approve(address spender,uint256 amount) returns (bool)",
  "function symbol() view returns (string)",
  "function decimals() view returns (uint8)",
];

const STATE = ["OPEN", "RESOLVING", "RESOLVED", "INVALID"];
const SESSION = ["NONE", "VOTING", "EXTENDED", "FINALIZED", "FAILED"];
const args = new Set(process.argv.slice(2));
const execute = args.has("--execute");
const selectedMarket = process.argv.find((a) => a.startsWith("--market="))?.split("=")[1];
const betAmount = process.argv.find((a) => a.startsWith("--bet="))?.split("=")[1] || "1";

function step(name) {
  console.log(`\n=== ${name} ===`);
}

function line(label, value) {
  console.log(`${label.padEnd(26)} ${value}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function rpcCall(fn, label, attempts = 5) {
  let last;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (error) {
      last = error;
      const msg = String(error?.message || error);
      if (!(msg.includes("-32005") || msg.includes("request rate exceeded")) || i === attempts - 1) break;
      await sleep(300 * (i + 1));
    }
  }
  throw new Error(`${label}: ${last?.message || last}`);
}

async function main() {
  const rpc = process.env.EVM_RPC_URL || "https://evmrpc-testnet.0g.ai";
  const provider = new ethers.JsonRpcProvider(rpc, { chainId: 16602, name: "0g-galileo" }, { staticNetwork: true, batchMaxCount: 1 });
  const pk = process.env.AGENT_PRIVATE_KEY || process.env.PRIVATE_KEY || process.env.AGENT_A_PRIVATE_KEY;
  const signer = pk ? new ethers.Wallet(pk, provider) : null;
  const reader = signer || provider;

  const factory = new ethers.Contract(process.env.MARKET_FACTORY_ADDRESS || ADDR.MarketFactory, FACTORY_ABI, reader);
  const registry = new ethers.Contract(process.env.AGENT_REGISTRY_ADDRESS || ADDR.AgentRegistry, REGISTRY_ABI, reader);
  const resolver = new ethers.Contract(process.env.COLLECTIVE_RESOLVER_ADDRESS || ADDR.CollectiveResolver, RESOLVER_ABI, reader);
  const pred = new ethers.Contract(process.env.PRED_TOKEN_ADDRESS || ADDR.PredToken, ERC20_ABI, reader);

  step("1. Agent Identity");
  line("RPC", rpc);
  if (!signer) {
    line("wallet", "read-only; set AGENT_PRIVATE_KEY or PRIVATE_KEY for write tests");
  } else {
    const wallet = signer.address;
    const [verified, agent, verifiedCount, nativeBal, predBal] = await Promise.all([
      rpcCall(() => registry.isVerified(wallet), "registry.isVerified"),
      rpcCall(() => registry.getAgent(wallet), "registry.getAgent"),
      rpcCall(() => registry.totalVerifiedAgents(), "registry.totalVerifiedAgents"),
      rpcCall(() => provider.getBalance(wallet), "provider.getBalance"),
      rpcCall(() => pred.balanceOf(wallet), "pred.balanceOf"),
    ]);
    line("wallet", wallet);
    line("verified", verified);
    line("agent id", agent.agentId.toString());
    line("tier / reputation", `${agent.tier} / ${agent.reputationScore}`);
    line("verified agents", verifiedCount.toString());
    line("native 0G", ethers.formatEther(nativeBal));
    line("PRED", ethers.formatEther(predBal));
  }

  step("2. Market Discovery");
  const count = Number(await rpcCall(() => factory.marketCount(), "factory.marketCount"));
  line("market count", count);
  const markets = [];
  for (let i = 1; i <= count; i++) {
    const rec = await rpcCall(() => factory.markets(i), `factory.markets(${i})`);
    const mkt = new ethers.Contract(rec.market, MARKET_ABI, reader);
    const [state, cfg, implied, yes, no] = await Promise.all([
      rpcCall(() => mkt.state(), `market(${i}).state`),
      rpcCall(() => mkt.config(), `market(${i}).config`),
      rpcCall(() => mkt.impliedProbabilityYes(), `market(${i}).implied`),
      rpcCall(() => mkt.yesPool(), `market(${i}).yesPool`),
      rpcCall(() => mkt.noPool(), `market(${i}).noPool`),
    ]);
    const row = {
      id: i,
      address: rec.market,
      state: STATE[Number(state)] || state.toString(),
      category: rec.category,
      questionURI: rec.questionURI,
      resolutionTime: Number(cfg.resolutionTime),
      minBet: cfg.minBet,
      impliedYes: Number(implied) / 100,
      yes,
      no,
    };
    markets.push(row);
    console.log(`#${i} ${row.address} ${row.state} ${row.category} yes=${row.impliedYes.toFixed(2)}% resolves=${new Date(row.resolutionTime * 1000).toISOString()}`);
  }

  const target = selectedMarket
    ? markets.find((m) => m.address.toLowerCase() === selectedMarket.toLowerCase())
    : markets.find((m) => m.state === "OPEN") || markets[0];
  if (!target) throw new Error("No markets found");

  step("3. Betting Readiness");
  line("target market", target.address);
  line("state", target.state);
  line("question URI", target.questionURI);
  line("min bet", `${ethers.formatEther(target.minBet)} PRED`);
  if (signer) {
    const amountWei = ethers.parseEther(betAmount);
    const allowance = await rpcCall(() => pred.allowance(signer.address, target.address), "pred.allowance(market)");
    line("planned bet", `${betAmount} PRED on YES`);
    line("market allowance", ethers.formatEther(allowance));
    if (target.state !== "OPEN") {
      line("bet action", "skipped; market is not OPEN");
    } else if (!execute) {
      line("bet action", "dry-run ok; rerun with --execute to approve + bet");
    } else {
      if (allowance < amountWei) {
        const tx = await pred.approve(target.address, amountWei);
        line("approve tx", tx.hash);
        await tx.wait();
      }
      const mkt = new ethers.Contract(target.address, MARKET_ABI, signer);
      const tx = await mkt.bet(1, amountWei);
      line("bet tx", tx.hash);
      await tx.wait();
    }
  }

  step("4. Resolution Readiness");
  const now = Math.floor(Date.now() / 1000);
  line("now", new Date(now * 1000).toISOString());
  line("resolution time", new Date(target.resolutionTime * 1000).toISOString());
  if (target.state === "OPEN" && now >= target.resolutionTime) {
    if (!execute || !signer) {
      line("trigger action", "ready; rerun with --execute to call triggerResolution()");
    } else {
      const mkt = new ethers.Contract(target.address, MARKET_ABI, signer);
      const tx = await mkt.triggerResolution();
      line("trigger tx", tx.hash);
      await tx.wait();
    }
  } else {
    line("trigger action", "not ready or already triggered");
  }

  step("5. Voting Readiness");
  const activeSessions = await rpcCall(() => resolver.getActiveSessions(), "resolver.getActiveSessions");
  line("active sessions", activeSessions.length);
  for (const addr of activeSessions) {
    const session = await rpcCall(() => resolver.getSession(addr), `resolver.getSession(${addr})`);
    console.log(`${addr} state=${SESSION[Number(session.state)]} voters=${session.voterCount} deadline=${new Date(Number(session.votingDeadline) * 1000).toISOString()}`);
  }
  if (signer) {
    const votingOpen = await rpcCall(() => resolver.isVotingOpen(target.address), "resolver.isVotingOpen");
    const vote = await rpcCall(() => resolver.getVote(target.address, signer.address), "resolver.getVote");
    line("target voting open", votingOpen);
    line("already voted", vote.cast);
    if (votingOpen && !vote.cast) {
      if (!execute) {
        line("vote action", "dry-run ok; rerun with --execute to cast INVALID demo vote");
      } else {
        const tx = await resolver.castVerifiedVote(target.address, 2, ethers.ZeroHash, "0x");
        line("vote tx", tx.hash);
        await tx.wait();
      }
    }
  }

  step("6. Agent Lifecycle Summary");
  line("discover markets", "ok");
  line("bet", execute ? "executed when eligible" : "dry-run verified");
  line("resolve trigger", "checked");
  line("vote", execute ? "executed when eligible" : "dry-run verified");
}

main().catch((error) => {
  console.error(`\n[fail] ${error.stack || error.message}`);
  process.exit(1);
});
