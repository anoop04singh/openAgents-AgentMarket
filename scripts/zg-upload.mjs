import { Indexer, ZgFile } from "@0gfoundation/0g-ts-sdk";
import { ethers } from "ethers";

console.log = (...args) => console.error(...args);

const filePath = process.argv[2];
if (!filePath) {
  console.error("Usage: node scripts/zg-upload.mjs <file>");
  process.exit(2);
}

const rpcUrl = process.env.EVM_RPC_URL || "https://evmrpc-testnet.0g.ai";
const indexerRpc = process.env.ZG_INDEXER_RPC || "https://indexer-storage-testnet-turbo.0g.ai";
const privateKey = process.env.PRIVATE_KEY || process.env.AGENT_PRIVATE_KEY;

if (!privateKey) {
  console.error("PRIVATE_KEY or AGENT_PRIVATE_KEY is required");
  process.exit(2);
}

const provider = new ethers.JsonRpcProvider(rpcUrl);
const signer = new ethers.Wallet(privateKey, provider);
const indexer = new Indexer(indexerRpc);
const file = await ZgFile.fromFilePath(filePath);

try {
  const [, treeErr] = await file.merkleTree();
  if (treeErr !== null) {
    throw new Error(`Merkle tree error: ${treeErr}`);
  }

  const [tx, uploadErr] = await indexer.upload(file, rpcUrl, signer);
  if (uploadErr !== null) {
    throw new Error(`Upload error: ${uploadErr}`);
  }

  const rootHash = tx.rootHash || (tx.rootHashes && tx.rootHashes[0]);
  const txHash = tx.txHash || (tx.txHashes && tx.txHashes[0]);
  process.stdout.write(JSON.stringify({ rootHash, txHash }));
} finally {
  await file.close();
}
