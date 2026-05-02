require("@nomicfoundation/hardhat-toolbox");
const path = require("path");
require("dotenv").config({ path: path.resolve(__dirname, ".env"), override: true });

function normalizePrivateKey(value) {
  const raw = (value || "").trim().replace(/^"+|"+$/g, "");
  if (!raw) return "";
  const prefixed = raw.startsWith("0x") ? raw : `0x${raw}`;
  return /^0x[0-9a-fA-F]{64}$/.test(prefixed) ? prefixed : "";
}

const PRIVATE_KEY = normalizePrivateKey(process.env.PRIVATE_KEY);
const SEPOLIA_RPC_URL = process.env.SEPOLIA_RPC_URL || "";
const EVM_RPC_URL = process.env.EVM_RPC_URL || "https://evmrpc-testnet.0g.ai";
const ZG_GALILEO_CHAIN_ID = Number(process.env.ZG_GALILEO_CHAIN_ID || process.env.CHAIN_ID || "16602");
const ZG_MAIN_CHAIN_ID = Number(process.env.ZG_MAIN_CHAIN_ID || "16661");
const ETHERSCAN_KEY = process.env.ETHERSCAN_KEY || process.env.OGSCAN_API_KEY || "DUMMY";
const ACCOUNTS = PRIVATE_KEY ? [PRIVATE_KEY] : [];

module.exports = {
  solidity: {
    version: "0.8.26",
    settings: {
      optimizer: { enabled: true, runs: 200 },
      viaIR: true,
      evmVersion: "cancun",
    },
  },
  paths: {
    sources: "./contracts",
    tests: "./tests/hardhat",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  networks: {
    hardhat: {},
    sepolia: {
      url: SEPOLIA_RPC_URL,
      accounts: ACCOUNTS,
      chainId: 11155111,
    },
    zg_galileo: {
      url: EVM_RPC_URL,
      accounts: ACCOUNTS,
      chainId: ZG_GALILEO_CHAIN_ID,
    },
    zg_main: {
      url: "https://evmrpc.0g.ai",
      accounts: ACCOUNTS,
      chainId: ZG_MAIN_CHAIN_ID,
    },
    testnet: {
      url: EVM_RPC_URL,
      accounts: ACCOUNTS,
      chainId: ZG_GALILEO_CHAIN_ID,
    },
    mainnet: {
      url: "https://evmrpc.0g.ai",
      accounts: ACCOUNTS,
      chainId: ZG_MAIN_CHAIN_ID,
    },
  },
  etherscan: {
    apiKey: {
      sepolia: ETHERSCAN_KEY,
      testnet: ETHERSCAN_KEY,
      mainnet: ETHERSCAN_KEY,
      zg_galileo: ETHERSCAN_KEY,
      zg_main: ETHERSCAN_KEY,
    },
    customChains: [
      {
        network: "testnet",
        chainId: 16602,
        urls: {
          apiURL: "https://chainscan-galileo.0g.ai/open/api",
          browserURL: "https://chainscan-galileo.0g.ai",
        },
      },
      {
        network: "mainnet",
        chainId: 16661,
        urls: {
          apiURL: "https://chainscan.0g.ai/open/api",
          browserURL: "https://chainscan.0g.ai",
        },
      },
      {
        network: "zg_galileo",
        chainId: 16602,
        urls: {
          apiURL: "https://chainscan-galileo.0g.ai/open/api",
          browserURL: "https://chainscan-galileo.0g.ai",
        },
      },
      {
        network: "zg_main",
        chainId: 16661,
        urls: {
          apiURL: "https://chainscan.0g.ai/open/api",
          browserURL: "https://chainscan.0g.ai",
        },
      },
    ],
  },
};
