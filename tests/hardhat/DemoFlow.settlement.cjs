const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

const STAKE = ethers.parseEther("1000");
const CREATION_STAKE = ethers.parseEther("500");

function log(label, value) {
  console.log(`${label.padEnd(26)} ${value}`);
}

describe("AgentMarket Terminal Demo Flow", function () {
  it("creates, discovers, bets, resolves, votes, finalizes, distributes rewards", async function () {
    const [admin, treasury, creator, agentB, agentC, agentD] = await ethers.getSigners();

    const PredToken = await ethers.getContractFactory("PredToken");
    const pred = await PredToken.connect(admin).deploy(admin.address, admin.address);
    await pred.waitForDeployment();

    const PositionToken = await ethers.getContractFactory("PositionToken");
    const posToken = await PositionToken.connect(admin).deploy(admin.address);
    await posToken.waitForDeployment();

    const AgentRegistry = await ethers.getContractFactory("AgentRegistry");
    const registry = await AgentRegistry.connect(admin).deploy(await pred.getAddress(), admin.address);
    await registry.waitForDeployment();

    const PredictionMarket = await ethers.getContractFactory("PredictionMarket");
    const marketImpl = await PredictionMarket.connect(admin).deploy();
    await marketImpl.waitForDeployment();

    const CollectiveResolver = await ethers.getContractFactory("CollectiveResolver");
    const resolver = await CollectiveResolver.connect(admin).deploy(await registry.getAddress(), await pred.getAddress(), admin.address);
    await resolver.waitForDeployment();

    const MarketFactory = await ethers.getContractFactory("MarketFactory");
    const factory = await MarketFactory.connect(admin).deploy(
      await marketImpl.getAddress(),
      await registry.getAddress(),
      await posToken.getAddress(),
      await resolver.getAddress(),
      await pred.getAddress(),
      treasury.address,
      admin.address
    );
    await factory.waitForDeployment();

    const marketRole = ethers.keccak256(ethers.toUtf8Bytes("MARKET_ROLE"));
    await (await registry.connect(admin).grantRole(marketRole, await resolver.getAddress())).wait();
    await (await posToken.connect(admin).grantRole(ethers.ZeroHash, await factory.getAddress())).wait();
    await (await resolver.connect(admin).grantRole(marketRole, await factory.getAddress())).wait();

    console.log("\n=== 1. Network setup ===");
    log("PredToken", await pred.getAddress());
    log("AgentRegistry", await registry.getAddress());
    log("MarketFactory", await factory.getAddress());
    log("Resolver", await resolver.getAddress());

    for (const signer of [creator, agentB, agentC, agentD]) {
      await (await pred.connect(admin).mint(signer.address, ethers.parseEther("10000"))).wait();
      await (await pred.connect(signer).approve(await registry.getAddress(), STAKE)).wait();
      await (await registry.connect(signer).register(`0g://agent-card-${signer.address}`, STAKE, `kv-${signer.address}`)).wait();
    }
    log("Verified agents", await registry.totalVerifiedAgents());

    console.log("\n=== 2. Creator creates market ===");
    const resolutionTime = BigInt((await time.latest()) + 3700);
    await (await pred.connect(creator).approve(await factory.getAddress(), CREATION_STAKE)).wait();
    await (await factory.connect(creator).createMarket("0g://demo-question-root", resolutionTime, "demo", ethers.parseEther("1"))).wait();
    const rec = await factory.getMarket(await factory.marketCount());
    const market = await ethers.getContractAt("PredictionMarket", rec.market);
    log("Market", rec.market);
    log("Creator", creator.address);
    log("Resolution time", new Date(Number(resolutionTime) * 1000).toISOString());

    console.log("\n=== 3. Agents discover and bet ===");
    log("Factory count", await factory.marketCount());
    await (await pred.connect(agentB).approve(rec.market, ethers.parseEther("300"))).wait();
    await (await market.connect(agentB).bet(1, ethers.parseEther("300"))).wait();
    log("Agent B bet", "YES 300 PRED");
    await (await pred.connect(agentC).approve(rec.market, ethers.parseEther("100"))).wait();
    await (await market.connect(agentC).bet(0, ethers.parseEther("100"))).wait();
    log("Agent C bet", "NO 100 PRED");
    log("YES pool", ethers.formatEther(await market.yesPool()));
    log("NO pool", ethers.formatEther(await market.noPool()));
    log("YES probability", `${Number(await market.impliedProbabilityYes()) / 100}%`);

    console.log("\n=== 4. Resolution opens ===");
    await time.increaseTo(Number(resolutionTime + 10n));
    await (await market.connect(agentD).triggerResolution()).wait();
    log("Market state", await market.state());
    let session = await resolver.getSession(rec.market);
    log("Voting deadline", new Date(Number(session.votingDeadline) * 1000).toISOString());

    console.log("\n=== 5. Agents vote through resolver ===");
    const root = ethers.keccak256(ethers.toUtf8Bytes("demo-research-root"));
    await (await resolver.connect(agentB).castVerifiedVote(rec.market, 1, root, "0x1234")).wait();
    await (await resolver.connect(agentC).castVerifiedVote(rec.market, 1, root, "0x1234")).wait();
    await (await resolver.connect(agentD).castVerifiedVote(rec.market, 1, root, "0x1234")).wait();
    session = await resolver.getSession(rec.market);
    log("Voters", session.voterCount);
    log("Weighted YES", session.weightedYes);
    log("Weighted NO", session.weightedNo);

    console.log("\n=== 6. Finalize and distribute rewards ===");
    await time.increase(49 * 60 * 60);
    await (await resolver.connect(creator).finalizeResolution(rec.market)).wait();
    session = await resolver.getSession(rec.market);
    log("Final outcome", "YES");
    log("Reward pool", ethers.formatEther(session.rewardPool));
    const beforeB = await pred.balanceOf(agentB.address);
    const beforeC = await pred.balanceOf(agentC.address);
    if (session.rewardPool > 0n) {
      await (await resolver.connect(creator).distributeRewards(rec.market)).wait();
    }
    await (await market.connect(agentB).claimWinnings()).wait();
    log("Agent B reward delta", ethers.formatEther((await pred.balanceOf(agentB.address)) - beforeB));
    log("Agent C reward delta", ethers.formatEther((await pred.balanceOf(agentC.address)) - beforeC));

    expect(await market.state()).to.equal(2n);
    expect(await market.outcome()).to.equal(1n);
  });
});

