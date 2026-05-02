import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Indexer } from "@0gfoundation/0g-ts-sdk";

console.log = (...args) => console.error(...args);

const rootHash = process.argv[2];
if (!rootHash) {
  console.error("Usage: node scripts/zg-download.mjs <rootHash>");
  process.exit(2);
}

const indexerRpc = process.env.ZG_INDEXER_RPC || "https://indexer-storage-testnet-turbo.0g.ai";
const indexer = new Indexer(indexerRpc);
const dir = await mkdtemp(join(tmpdir(), "agentmarket-0g-download-"));
const outputFile = join(dir, "payload.json");

try {
  const err = await indexer.download(rootHash, outputFile, false);
  if (err !== null) {
    throw new Error(`Download error: ${err}`);
  }

  const content = await readFile(outputFile, "utf8");
  process.stdout.write(content);
} finally {
  await rm(dir, { recursive: true, force: true });
}
