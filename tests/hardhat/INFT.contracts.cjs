const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

describe("INFT Contract", function () {
  async function deployFixture() {
    const [owner, alice, bob, executor] = await ethers.getSigners();

    const TEETransferOracle = await ethers.getContractFactory("TEETransferOracle");
    const oracle = await TEETransferOracle.deploy(owner.address, owner.address);
    await oracle.waitForDeployment();

    const INFT = await ethers.getContractFactory("INFT");
    const inft = await INFT.deploy(
      "AI Agent NFTs",
      "AINFT",
      await oracle.getAddress(),
      owner.address
    );
    await inft.waitForDeployment();

    return { owner, alice, bob, executor, oracle, inft };
  }

  async function buildProof({ signer, inft, from, to, tokenId, sealedKey, newMetadataHash, newEncryptedURI, deadline, nonce }) {
    const chainId = (await ethers.provider.getNetwork()).chainId;
    const typeHash = ethers.keccak256(
      ethers.toUtf8Bytes(
        "TransferProof(uint256 chainId,address inft,address from,address to,uint256 tokenId,bytes32 sealedKeyHash,bytes32 newMetadataHash,bytes32 newEncryptedURIHash,uint256 deadline,uint256 nonce)"
      )
    );
    const payloadHash = ethers.keccak256(
      ethers.AbiCoder.defaultAbiCoder().encode(
        ["bytes32", "uint256", "address", "address", "address", "uint256", "bytes32", "bytes32", "bytes32", "uint256", "uint256"],
        [
          typeHash,
          chainId,
          await inft.getAddress(),
          from.address,
          to.address,
          tokenId,
          ethers.keccak256(sealedKey),
          newMetadataHash,
          ethers.keccak256(ethers.toUtf8Bytes(newEncryptedURI)),
          deadline,
          nonce,
        ]
      )
    );
    const signature = await signer.signMessage(ethers.getBytes(payloadHash));
    return ethers.AbiCoder.defaultAbiCoder().encode(
      ["tuple(bytes32 newMetadataHash,string newEncryptedURI,uint256 deadline,uint256 nonce,bytes signature)"],
      [[newMetadataHash, newEncryptedURI, deadline, nonce, signature]]
    );
  }

  it("mints INFT with encrypted metadata", async function () {
    const { owner, alice, inft } = await loadFixture(deployFixture);
    const hash = ethers.keccak256(ethers.toUtf8Bytes("metadata-v1"));
    await (await inft.connect(owner).mint(alice.address, "0g://encrypted-uri", hash)).wait();
    expect(await inft.ownerOf(1)).to.equal(alice.address);
    expect(await inft.getMetadataHash(1)).to.equal(hash);
    expect(await inft.getEncryptedURI(1)).to.equal("0g://encrypted-uri");
  });

  it("transfers with signed TEE attestation proof", async function () {
    const { owner, alice, bob, oracle, inft } = await loadFixture(deployFixture);
    await (await inft.connect(owner).mint(alice.address, "0g://enc", ethers.keccak256(ethers.toUtf8Bytes("m1")))).wait();

    const newHash = ethers.keccak256(ethers.toUtf8Bytes("new-hash"));
    const sealedKey = ethers.hexlify(ethers.randomBytes(32));
    const deadline = (await ethers.provider.getBlock("latest")).timestamp + 3600;
    const proof = await buildProof({
      signer: owner,
      inft,
      from: alice,
      to: bob,
      tokenId: 1,
      sealedKey,
      newMetadataHash: newHash,
      newEncryptedURI: "0g://enc-v2",
      deadline,
      nonce: 1n,
    });

    await (await inft.connect(alice).transfer(alice.address, bob.address, 1, sealedKey, proof)).wait();

    expect(await inft.ownerOf(1)).to.equal(bob.address);
    expect(await inft.getMetadataHash(1)).to.equal(newHash);
    expect(await inft.getEncryptedURI(1)).to.equal("0g://enc-v2");

    await (await oracle.setTrustedAttestor(owner.address, false)).wait();
    const invalidProof = await buildProof({
      signer: owner,
      inft,
      from: bob,
      to: alice,
      tokenId: 1,
      sealedKey,
      newMetadataHash: ethers.keccak256(ethers.toUtf8Bytes("new-hash-2")),
      newEncryptedURI: "0g://enc-v3",
      deadline: deadline + 10,
      nonce: 2n,
    });
    await expect(
      inft.connect(bob).transfer(bob.address, alice.address, 1, sealedKey, invalidProof)
    ).to.be.revertedWith("INFT: invalid proof");
  });

  it("rejects expired or replayed transfer proof", async function () {
    const { owner, alice, bob, inft } = await loadFixture(deployFixture);
    await (await inft.connect(owner).mint(alice.address, "0g://enc", ethers.keccak256(ethers.toUtf8Bytes("m1")))).wait();

    const sealedKey = ethers.hexlify(ethers.randomBytes(32));
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    const expiredProof = await buildProof({
      signer: owner,
      inft,
      from: alice,
      to: bob,
      tokenId: 1,
      sealedKey,
      newMetadataHash: ethers.keccak256(ethers.toUtf8Bytes("v2")),
      newEncryptedURI: "0g://enc-v2",
      deadline: now - 1,
      nonce: 10n,
    });

    await expect(
      inft.connect(alice).transfer(alice.address, bob.address, 1, sealedKey, expiredProof)
    ).to.be.revertedWith("INFT: invalid proof");

    const validProof = await buildProof({
      signer: owner,
      inft,
      from: alice,
      to: bob,
      tokenId: 1,
      sealedKey,
      newMetadataHash: ethers.keccak256(ethers.toUtf8Bytes("v3")),
      newEncryptedURI: "0g://enc-v3",
      deadline: now + 3600,
      nonce: 11n,
    });
    await (await inft.connect(alice).transfer(alice.address, bob.address, 1, sealedKey, validProof)).wait();

    await expect(
      inft.connect(bob).transfer(bob.address, alice.address, 1, sealedKey, validProof)
    ).to.be.revertedWith("INFT: proof already used");
  });

  it("authorizes usage without ownership transfer", async function () {
    const { owner, alice, executor, inft } = await loadFixture(deployFixture);
    await (await inft.connect(owner).mint(alice.address, "0g://enc", ethers.keccak256(ethers.toUtf8Bytes("meta")))).wait();

    const perms = ethers.toUtf8Bytes(JSON.stringify({ maxRequests: 100, rateLimit: 10 }));
    await (await inft.connect(alice).authorizeUsage(1, executor.address, perms)).wait();
    const stored = await inft.getAuthorization(1, executor.address);
    expect(stored).to.equal(ethers.hexlify(perms));
    expect(await inft.ownerOf(1)).to.equal(alice.address);
  });
});
