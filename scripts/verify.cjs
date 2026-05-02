/* eslint-disable no-console */
const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

async function verifyOne(label, address, args = [], contract) {
  if (!address) {
    console.log(`Skipping ${label}: missing address`);
    return;
  }
  try {
    console.log(`Verifying ${label} at ${address} ...`);
    await hre.run("verify:verify", {
      address,
      constructorArguments: args,
      contract,
    });
    console.log(`Verified ${label}`);
  } catch (err) {
    const msg = String(err && err.message ? err.message : err);
    if (msg.includes("Already Verified") || msg.includes("already verified")) {
      console.log(`${label} already verified`);
      return;
    }
    throw err;
  }
}

async function main() {
  const addressesPath = path.join(process.cwd(), "deployments", "addresses.json");
  if (!fs.existsSync(addressesPath)) {
    throw new Error(`Missing deployments file: ${addressesPath}`);
  }
  const addresses = JSON.parse(fs.readFileSync(addressesPath, "utf8"));
  const [deployer] = await hre.ethers.getSigners();
  const treasury = process.env.TREASURY_ADDRESS || deployer.address;
  const oracleAttestor = process.env.INFT_ORACLE_ATTESTOR || deployer.address;

  await verifyOne(
    "PredToken",
    addresses.PredToken,
    [deployer.address, deployer.address],
    "contracts/tokens/PredToken.sol:PredToken"
  );

  await verifyOne(
    "PositionToken",
    addresses.PositionToken,
    [deployer.address],
    "contracts/tokens/PositionToken.sol:PositionToken"
  );

  await verifyOne(
    "AgentRegistry",
    addresses.AgentRegistry,
    [addresses.PredToken, deployer.address],
    "contracts/core/AgentRegistry.sol:AgentRegistry"
  );

  await verifyOne(
    "MarketImpl (PredictionMarket)",
    addresses.MarketImpl,
    [],
    "contracts/core/PredictionMarket.sol:PredictionMarket"
  );

  await verifyOne(
    "CollectiveResolver",
    addresses.CollectiveResolver,
    [addresses.AgentRegistry, addresses.PredToken, deployer.address],
    "contracts/resolution/CollectiveResolver.sol:CollectiveResolver"
  );

  await verifyOne(
    "MarketFactory",
    addresses.MarketFactory,
    [
      addresses.MarketImpl,
      addresses.AgentRegistry,
      addresses.PositionToken,
      addresses.CollectiveResolver,
      addresses.PredToken,
      treasury,
      deployer.address,
    ],
    "contracts/core/MarketFactory.sol:MarketFactory"
  );

  await verifyOne(
    "INFTOracle (TEETransferOracle)",
    addresses.INFTOracle,
    [deployer.address, oracleAttestor],
    "contracts/inft/TEETransferOracle.sol:TEETransferOracle"
  );

  await verifyOne(
    "INFT",
    addresses.INFT,
    ["AI Agent NFTs", "AINFT", addresses.INFTOracle, deployer.address],
    "contracts/inft/INFT.sol:INFT"
  );

  console.log("All verification attempts completed.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

