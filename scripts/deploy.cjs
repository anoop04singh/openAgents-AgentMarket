/* eslint-disable no-console */
const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  const treasury = process.env.TREASURY_ADDRESS || deployer.address;
  const oracleAttestor = process.env.INFT_ORACLE_ATTESTOR || deployer.address;

  console.log("Deploying with:", deployer.address);
  console.log("Treasury:", treasury);
  console.log("Chain ID:", (await ethers.provider.getNetwork()).chainId.toString());

  const PredToken = await ethers.getContractFactory("PredToken");
  const pred = await PredToken.deploy(deployer.address, deployer.address);
  await pred.waitForDeployment();

  const PositionToken = await ethers.getContractFactory("PositionToken");
  const posToken = await PositionToken.deploy(deployer.address);
  await posToken.waitForDeployment();

  const AgentRegistry = await ethers.getContractFactory("AgentRegistry");
  const registry = await AgentRegistry.deploy(await pred.getAddress(), deployer.address);
  await registry.waitForDeployment();

  const PredictionMarket = await ethers.getContractFactory("PredictionMarket");
  const marketImpl = await PredictionMarket.deploy();
  await marketImpl.waitForDeployment();

  const CollectiveResolver = await ethers.getContractFactory("CollectiveResolver");
  const resolver = await CollectiveResolver.deploy(
    await registry.getAddress(),
    await pred.getAddress(),
    deployer.address
  );
  await resolver.waitForDeployment();

  const MarketFactory = await ethers.getContractFactory("MarketFactory");
  const factory = await MarketFactory.deploy(
    await marketImpl.getAddress(),
    await registry.getAddress(),
    await posToken.getAddress(),
    await resolver.getAddress(),
    await pred.getAddress(),
    treasury,
    deployer.address
  );
  await factory.waitForDeployment();

  const TEETransferOracle = await ethers.getContractFactory("TEETransferOracle");
  const oracle = await TEETransferOracle.deploy(deployer.address, oracleAttestor);
  await oracle.waitForDeployment();

  const INFT = await ethers.getContractFactory("INFT");
  const inft = await INFT.deploy(
    "AI Agent NFTs",
    "AINFT",
    await oracle.getAddress(),
    deployer.address
  );
  await inft.waitForDeployment();

  const marketRole = ethers.keccak256(ethers.toUtf8Bytes("MARKET_ROLE"));
  await (await registry.grantRole(marketRole, await resolver.getAddress())).wait();
  await (await posToken.grantRole(ethers.ZeroHash, await factory.getAddress())).wait();
  await (await resolver.grantRole(marketRole, await factory.getAddress())).wait();

  await (await pred.mint(deployer.address, ethers.parseEther("10000000"))).wait();

  const chainId = Number((await ethers.provider.getNetwork()).chainId);
  const addresses = {
    chainId,
    PredToken: await pred.getAddress(),
    PositionToken: await posToken.getAddress(),
    AgentRegistry: await registry.getAddress(),
    MarketImpl: await marketImpl.getAddress(),
    CollectiveResolver: await resolver.getAddress(),
    MarketFactory: await factory.getAddress(),
    INFTOracle: await oracle.getAddress(),
    INFT: await inft.getAddress(),
  };

  const outDir = path.join(process.cwd(), "deployments");
  const outFile = path.join(outDir, "addresses.json");
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(outFile, `${JSON.stringify(addresses, null, 2)}\n`, "utf8");

  console.log("=== Deploy complete ===");
  for (const [k, v] of Object.entries(addresses)) {
    console.log(`${k}: ${v}`);
  }
  console.log("Written:", outFile);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
