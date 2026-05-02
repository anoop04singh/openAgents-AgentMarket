const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("Hardhat Migration Smoke", function () {
  it("deploys PredToken", async function () {
    const [deployer] = await ethers.getSigners();
    const PredToken = await ethers.getContractFactory("PredToken");
    const pred = await PredToken.deploy(deployer.address, deployer.address);
    await pred.waitForDeployment();

    expect(await pred.name()).to.equal("Prediction Token");
    expect(await pred.symbol()).to.equal("PRED");
  });
});

