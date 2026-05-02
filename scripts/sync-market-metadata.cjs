#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { ethers } = require("ethers");
require("dotenv").config();

const ROOT = path.resolve(__dirname, "..");
const ADDRESSES = JSON.parse(fs.readFileSync(path.join(ROOT, "deployments", "addresses.json"), "utf8"));
const OUT_DIR = path.join(ROOT, "public");
const OUT_FILE = path.join(OUT_DIR, "market-metadata.json");

const FACTORY_ABI = [
  "function marketCount() view returns (uint256)",
  "function markets(uint256) view returns (address market,address creator,uint256 agentId,uint256 createdAt,uint256 resolutionTime,string questionURI,string category,bool active)",
];

const RPC_URL = process.env.EVM_RPC_URL || "https://evmrpc-testnet.0g.ai";
const FACTORY_ADDR = process.env.MARKET_FACTORY_ADDRESS || ADDRESSES.MarketFactory;
const provider = new ethers.JsonRpcProvider(
  RPC_URL,
  { chainId: 16602, name: "0g-galileo" },
  { staticNetwork: true, batchMaxCount: 1 }
);
const factory = new ethers.Contract(FACTORY_ADDR, FACTORY_ABI, provider);

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
      const retry = msg.includes("request rate exceeded") || msg.includes("-32005") || msg.includes("Too many requests");
      if (!retry || i === attempts - 1) break;
      await sleep(300 * (i + 1));
    }
  }
  throw new Error(`${label}: ${last?.message || last}`);
}

function loadExisting() {
  if (!fs.existsSync(OUT_FILE)) return {};
  try {
    return JSON.parse(fs.readFileSync(OUT_FILE, "utf8"));
  } catch {
    return {};
  }
}

function downloadMetadata(questionURI) {
  const rootHash = questionURI.replace(/^0g:\/\//, "");
  const proc = spawnSync(process.execPath, [path.join(ROOT, "scripts", "zg-download.mjs"), rootHash], {
    cwd: ROOT,
    env: process.env,
    encoding: "utf8",
    timeout: 120000,
  });
  if (proc.status !== 0) {
    throw new Error((proc.stderr || proc.stdout || "0G download failed").trim());
  }
  return JSON.parse(proc.stdout);
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const existing = loadExisting();
  const count = Number(await rpcCall(() => factory.marketCount(), "factory.marketCount"));
  const cache = { ...existing };

  console.log(`[sync] Factory ${FACTORY_ADDR} has ${count} markets`);
  for (let id = 1; id <= count; id++) {
    const rec = await rpcCall(() => factory.markets(id), `factory.markets(${id})`);
    const market = rec.market;
    const questionURI = rec.questionURI;
    if (cache[market]?.question && cache[market]?.questionURI === questionURI) {
      console.log(`[skip] #${id} ${market} already cached`);
      continue;
    }

    console.log(`[0g]   #${id} ${market} ${questionURI}`);
    try {
      const metadata = downloadMetadata(questionURI);
      cache[market] = {
        ...metadata,
        market,
        marketId: id,
        questionURI,
        category: rec.category,
        creator: rec.creator,
        creatorAgentId: Number(rec.agentId),
        active: rec.active,
        syncedAt: new Date().toISOString(),
      };
    } catch (error) {
      console.log(`[warn] #${id} metadata unavailable from 0G: ${error.message.split("\n")[0]}`);
      cache[market] = cache[market] || {
        market,
        marketId: id,
        questionURI,
        category: rec.category,
        creator: rec.creator,
        creatorAgentId: Number(rec.agentId),
        active: rec.active,
        question: "Legacy market metadata unavailable from 0G Storage",
        resolutionCriteria: "This market was created before the real 0G upload path was enabled.",
        syncedAt: new Date().toISOString(),
      };
    }
    await sleep(250);
  }

  fs.writeFileSync(OUT_FILE, JSON.stringify(cache, null, 2));
  console.log(`[ok] Wrote ${Object.keys(cache).length} market metadata records to ${OUT_FILE}`);
}

main().catch((error) => {
  console.error(`[fail] ${error.stack || error.message}`);
  process.exit(1);
});
