// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

interface IINFTOracle {
    function verifyTransferProof(
        address inft,
        address from,
        address to,
        uint256 tokenId,
        bytes calldata sealedKey,
        bytes calldata proof
    ) external view returns (bool);
}

/**
 * @title INFT
 * @notice ERC-7857 style intelligent NFT contract for 0G integration.
 */
contract INFT is ERC721, Ownable, ReentrancyGuard {
    struct TransferProof {
        bytes32 newMetadataHash;
        string newEncryptedURI;
        uint256 deadline;
        uint256 nonce;
        bytes signature;
    }

    mapping(uint256 => bytes32) private _metadataHashes;
    mapping(uint256 => string) private _encryptedURIs;
    mapping(uint256 => mapping(address => bytes)) private _authorizations;
    mapping(bytes32 => bool) public consumedProofs;

    address public oracle;
    uint256 private _nextTokenId = 1;

    event MetadataUpdated(uint256 indexed tokenId, bytes32 newHash);
    event UsageAuthorized(uint256 indexed tokenId, address indexed executor);

    constructor(
        string memory name_,
        string memory symbol_,
        address oracle_,
        address initialOwner
    ) ERC721(name_, symbol_) Ownable(initialOwner) {
        require(oracle_ != address(0), "INFT: oracle required");
        oracle = oracle_;
    }

    function mint(
        address to,
        string calldata encryptedURI,
        bytes32 metadataHash
    ) external onlyOwner returns (uint256) {
        uint256 tokenId = _nextTokenId++;
        _safeMint(to, tokenId);
        _encryptedURIs[tokenId] = encryptedURI;
        _metadataHashes[tokenId] = metadataHash;
        return tokenId;
    }

    function transfer(
        address from,
        address to,
        uint256 tokenId,
        bytes calldata sealedKey,
        bytes calldata proof
    ) external nonReentrant {
        require(ownerOf(tokenId) == from, "INFT: not owner");
        require(msg.sender == from || getApproved(tokenId) == msg.sender || isApprovedForAll(from, msg.sender), "INFT: not approved");
        require(to != address(0), "INFT: bad recipient");

        bytes32 proofHash = keccak256(proof);
        require(!consumedProofs[proofHash], "INFT: proof already used");

        bool valid;
        try IINFTOracle(oracle).verifyTransferProof(address(this), from, to, tokenId, sealedKey, proof) returns (bool ok) {
            valid = ok;
        } catch {
            valid = false;
        }
        require(valid, "INFT: invalid proof");

        _updateMetadataAccess(tokenId, sealedKey, proof);
        consumedProofs[proofHash] = true;
        _transfer(from, to, tokenId);
        emit MetadataUpdated(tokenId, keccak256(sealedKey));
    }

    function authorizeUsage(
        uint256 tokenId,
        address executor,
        bytes calldata permissions
    ) external {
        require(ownerOf(tokenId) == msg.sender, "INFT: not owner");
        _authorizations[tokenId][executor] = permissions;
        emit UsageAuthorized(tokenId, executor);
    }

    function setOracle(address newOracle) external onlyOwner {
        require(newOracle != address(0), "INFT: bad oracle");
        oracle = newOracle;
    }

    function getMetadataHash(uint256 tokenId) external view returns (bytes32) {
        _requireOwned(tokenId);
        return _metadataHashes[tokenId];
    }

    function getEncryptedURI(uint256 tokenId) external view returns (string memory) {
        _requireOwned(tokenId);
        return _encryptedURIs[tokenId];
    }

    function getAuthorization(uint256 tokenId, address executor) external view returns (bytes memory) {
        _requireOwned(tokenId);
        return _authorizations[tokenId][executor];
    }

    function _updateMetadataAccess(
        uint256 tokenId,
        bytes calldata sealedKey,
        bytes calldata proof
    ) internal {
        TransferProof memory decoded = abi.decode(proof, (TransferProof));
        _metadataHashes[tokenId] = decoded.newMetadataHash == bytes32(0) ? keccak256(sealedKey) : decoded.newMetadataHash;
        if (bytes(decoded.newEncryptedURI).length > 0) {
            _encryptedURIs[tokenId] = decoded.newEncryptedURI;
        }
    }
}
