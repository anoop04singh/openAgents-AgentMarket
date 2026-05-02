const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture, time } = require("@nomicfoundation/hardhat-network-helpers");

const STAKE = ethers.parseEther("1000");
const BET_SIZE = ethers.parseEther("100");
const CREATION_STAKE = ethers.parseEther("500");

describe("AgentMarket Contracts (Hardhat)", function () {
  async function deployFixture() {
    const [admin, treasury, agentA, agentB, agentC, agentD] = await ethers.getSigners();

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
    const resolver = await CollectiveResolver.connect(admin).deploy(
      await registry.getAddress(),
      await pred.getAddress(),
      admin.address
    );
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

    const funding = ethers.parseEther("10000");
    await (await pred.connect(admin).mint(agentA.address, funding)).wait();
    await (await pred.connect(admin).mint(agentB.address, funding)).wait();
    await (await pred.connect(admin).mint(agentC.address, funding)).wait();
    await (await pred.connect(admin).mint(agentD.address, funding)).wait();

    async function registerAgent(agentSigner) {
      await (await pred.connect(agentSigner).approve(await registry.getAddress(), STAKE)).wait();
      await (await registry.connect(agentSigner).register("0g://agent-card-root", STAKE, "kv-stream-id")).wait();
      return registry.addressToAgentId(agentSigner.address);
    }

    async function createMarket(creatorSigner, secondsFromNow = 86400) {
      const now = await time.latest();
      const resolutionTime = BigInt(now + secondsFromNow);
      await (await pred.connect(creatorSigner).approve(await factory.getAddress(), CREATION_STAKE)).wait();
      await (await factory.connect(creatorSigner).createMarket("0g://question-root", resolutionTime, "crypto", ethers.parseEther("1"))).wait();
      const count = await factory.marketCount();
      const rec = await factory.getMarket(count);
      const market = await ethers.getContractAt("PredictionMarket", rec.market);
      return { market, address: rec.market, resolutionTime };
    }

    async function bet(bettorSigner, market, outcome, amount) {
      await (await pred.connect(bettorSigner).approve(await market.getAddress(), amount)).wait();
      await (await market.connect(bettorSigner).bet(outcome, amount)).wait();
    }

    return {
      admin, treasury, agentA, agentB, agentC, agentD,
      pred, posToken, registry, marketImpl, resolver, factory,
      registerAgent, createMarket, bet,
    };
  }

  it("registers verified agent", async function () {
    const { agentA, registry, registerAgent } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    expect(await registry.isVerified(agentA.address)).to.equal(true);
    const agent = await registry.getAgent(agentA.address);
    expect(agent.tier).to.equal(2n);
    expect(agent.reputationScore).to.equal(50n);
  });

  it("rejects duplicate registration", async function () {
    const { agentA, pred, registry, registerAgent } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await (await pred.connect(agentA).approve(await registry.getAddress(), STAKE)).wait();
    await expect(
      registry.connect(agentA).register("0g://card2", STAKE, "kv2")
    ).to.be.reverted;
  });

  it("creates market only for verified agents", async function () {
    const { agentA, factory, createMarket, registerAgent } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    const { market } = await createMarket(agentA);
    expect(await market.state()).to.equal(0n);

    const now = await time.latest();
    await expect(
      factory.connect(agentA).createMarket("0g://q2", BigInt(now + 1800), "crypto", ethers.parseEther("1"))
    ).to.be.reverted;
  });

  it("rejects unverified market creation", async function () {
    const { agentA, factory, pred } = await loadFixture(deployFixture);
    await (await pred.connect(agentA).approve(await factory.getAddress(), CREATION_STAKE)).wait();
    const now = await time.latest();
    await expect(
      factory.connect(agentA).createMarket("0g://question", BigInt(now + 86400), "crypto", ethers.parseEther("1"))
    ).to.be.reverted;
  });

  it("places YES/NO bets and computes implied probability", async function () {
    const { agentA, agentB, agentC, registerAgent, createMarket, bet } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await registerAgent(agentB);
    await registerAgent(agentC);
    const { market } = await createMarket(agentA);

    await bet(agentB, market, 1, ethers.parseEther("300"));
    await bet(agentC, market, 0, ethers.parseEther("100"));

    expect(await market.yesPool()).to.equal(ethers.parseEther("300"));
    expect(await market.noPool()).to.equal(ethers.parseEther("100"));
    expect(await market.impliedProbabilityYes()).to.be.closeTo(7500n, 10n);
  });

  it("rejects unverified betting", async function () {
    const { agentA, agentB, registerAgent, createMarket, pred } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    const { market } = await createMarket(agentA);
    await (await pred.connect(agentB).approve(await market.getAddress(), BET_SIZE)).wait();
    await expect(market.connect(agentB).bet(1, BET_SIZE)).to.be.revertedWith("Agent not verified");
  });

  it("triggers resolution and records verified vote with PoIR", async function () {
    const { agentA, agentB, registerAgent, createMarket, resolver } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await registerAgent(agentB);
    const { market, address, resolutionTime } = await createMarket(agentA);
    await time.increaseTo(Number(resolutionTime + 10n));
    await (await market.triggerResolution()).wait();

    const baseWeight = await resolver.registry().then(async (addr) => {
      const registry = await ethers.getContractAt("AgentRegistry", addr);
      return registry.getVoteWeight(agentB.address);
    });

    const root = ethers.keccak256(ethers.toUtf8Bytes("research-report"));
    await (await resolver.connect(agentB).castVerifiedVote(address, 1, root, "0xdeadbeef")).wait();
    const vote = await resolver.getVote(address, agentB.address);
    expect(vote.cast).to.equal(true);
    expect(vote.hasPoIR).to.equal(true);
    expect(vote.weight).to.equal((baseWeight * 120n) / 100n);
  });

  it("prevents double voting", async function () {
    const { agentA, agentB, registerAgent, createMarket, resolver } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await registerAgent(agentB);
    const { market, address, resolutionTime } = await createMarket(agentA);
    await time.increaseTo(Number(resolutionTime + 10n));
    await (await market.triggerResolution()).wait();
    await (await resolver.connect(agentB).castVerifiedVote(address, 1, ethers.ZeroHash, "0x")).wait();
    await expect(
      resolver.connect(agentB).castVerifiedVote(address, 0, ethers.ZeroHash, "0x")
    ).to.be.reverted;
  });

  it("runs full flow YES wins and claims winnings", async function () {
    const { agentA, agentB, agentC, agentD, registerAgent, createMarket, bet, resolver, pred } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await registerAgent(agentB);
    await registerAgent(agentC);
    await registerAgent(agentD);
    const { market, address, resolutionTime } = await createMarket(agentA);

    await bet(agentB, market, 1, ethers.parseEther("300"));
    await bet(agentC, market, 0, ethers.parseEther("100"));
    await time.increaseTo(Number(resolutionTime + 10n));
    await (await market.triggerResolution()).wait();

    const root = ethers.keccak256(ethers.toUtf8Bytes("proof-yes"));
    await (await resolver.connect(agentB).castVerifiedVote(address, 1, root, "0x1234")).wait();
    await (await resolver.connect(agentC).castVerifiedVote(address, 1, root, "0x1234")).wait();
    await (await resolver.connect(agentD).castVerifiedVote(address, 1, root, "0x1234")).wait();

    await time.increase(3 * 24 * 60 * 60);
    await (await resolver.finalizeResolution(address)).wait();
    expect(await market.state()).to.equal(2n);
    expect(await market.outcome()).to.equal(1n);

    const balBefore = await pred.balanceOf(agentB.address);
    await (await market.connect(agentB).claimWinnings()).wait();
    const balAfter = await pred.balanceOf(agentB.address);
    expect(balAfter).to.be.greaterThan(balBefore);
  });

  it("extends session when quorum not met", async function () {
    const { agentA, agentB, registerAgent, createMarket, bet, resolver } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await registerAgent(agentB);
    const { market, address, resolutionTime } = await createMarket(agentA);
    await bet(agentB, market, 1, BET_SIZE);
    await time.increaseTo(Number(resolutionTime + 10n));
    await (await market.triggerResolution()).wait();

    await (await resolver.connect(agentB).castVerifiedVote(address, 1, ethers.ZeroHash, "0x")).wait();
    await time.increase(3 * 24 * 60 * 60);
    await (await resolver.finalizeResolution(address)).wait();
    const sess = await resolver.getSession(address);
    expect(sess.extensions).to.equal(1n);
    expect(sess.state).to.equal(2n);
  });

  it("invalidates after max extensions and refunds", async function () {
    const { agentA, agentB, registerAgent, createMarket, bet, resolver, pred } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await registerAgent(agentB);
    const { market, address, resolutionTime } = await createMarket(agentA);
    await bet(agentB, market, 1, BET_SIZE);
    await time.increaseTo(Number(resolutionTime + 10n));
    await (await market.triggerResolution()).wait();

    for (let i = 0; i < 4; i++) {
      await time.increase(2 * 24 * 60 * 60);
      await resolver.finalizeResolution(address);
    }
    expect(await market.state()).to.equal(3n);

    const before = await pred.balanceOf(agentB.address);
    await (await market.connect(agentB).claimRefund()).wait();
    const after = await pred.balanceOf(agentB.address);
    expect(after - before).to.equal(BET_SIZE);
  });

  it("updates reputation and supports slashing", async function () {
    const { admin, agentA, agentB, agentC, agentD, registerAgent, createMarket, resolver, registry } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await registerAgent(agentB);
    await registerAgent(agentC);
    await registerAgent(agentD);
    const { market, address, resolutionTime } = await createMarket(agentA);

    await time.increaseTo(Number(resolutionTime + 10n));
    await (await market.triggerResolution()).wait();
    const root = ethers.keccak256(ethers.toUtf8Bytes("proof"));

    await (await resolver.connect(agentB).castVerifiedVote(address, 0, root, "0xff")).wait(); // minority
    await (await resolver.connect(agentC).castVerifiedVote(address, 1, root, "0xff")).wait(); // majority
    await (await resolver.connect(agentD).castVerifiedVote(address, 1, root, "0xff")).wait();
    await time.increase(3 * 24 * 60 * 60);
    await (await resolver.finalizeResolution(address)).wait();

    const agentBInfo = await registry.getAgent(agentB.address);
    const agentCInfo = await registry.getAgent(agentC.address);
    expect(agentBInfo.reputationScore).to.be.lessThan(50n);
    expect(agentCInfo.reputationScore).to.be.greaterThan(50n);

    const initialStake = (await registry.getAgent(agentB.address)).stakedAmount;
    await (await registry.connect(admin).slash(await registry.addressToAgentId(agentB.address), "Malicious")).wait();
    const slashed = await registry.getAgent(agentB.address);
    expect(slashed.stakedAmount).to.be.lessThan(initialStake);
    expect(slashed.reputationScore).to.equal(0n);
    expect(slashed.slashed).to.equal(true);
  });

  it("returns creator stake after resolution", async function () {
    const { agentA, agentB, agentC, agentD, registerAgent, createMarket, resolver, factory, pred } = await loadFixture(deployFixture);
    await registerAgent(agentA);
    await registerAgent(agentB);
    await registerAgent(agentC);
    await registerAgent(agentD);

    const balBefore = await pred.balanceOf(agentA.address);
    const { market, address, resolutionTime } = await createMarket(agentA);
    const balAfterCreate = await pred.balanceOf(agentA.address);
    expect(balBefore - balAfterCreate).to.equal(CREATION_STAKE);

    await time.increaseTo(Number(resolutionTime + 10n));
    await (await market.triggerResolution()).wait();
    const root = ethers.keccak256(ethers.toUtf8Bytes("proof"));
    await (await resolver.connect(agentB).castVerifiedVote(address, 1, root, "0xaa")).wait();
    await (await resolver.connect(agentC).castVerifiedVote(address, 1, root, "0xaa")).wait();
    await (await resolver.connect(agentD).castVerifiedVote(address, 1, root, "0xaa")).wait();
    await time.increase(3 * 24 * 60 * 60);
    await (await resolver.finalizeResolution(address)).wait();

    await (await factory.returnCreatorStake(address)).wait();
    const balAfterReturn = await pred.balanceOf(agentA.address);
    expect(balAfterReturn - balAfterCreate).to.equal(CREATION_STAKE);
  });
});

