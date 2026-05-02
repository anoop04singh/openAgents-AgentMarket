// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/**
 * @title TEETransferOracle
 * @notice Verifies signed TEE attestations for ERC-7857 style INFT transfer proofs.
 *
 * Proof format (abi.encode):
 * (
 *   bytes32 newMetadataHash,
 *   string newEncryptedURI,
 *   uint256 deadline,
 *   uint256 nonce,
 *   bytes signature
 * )
 *
 * Signature payload binds to chainId, INFT contract, transfer parties, tokenId,
 * sealedKey hash and metadata fields, making proofs non-portable and context-safe.
 */
contract TEETransferOracle is Ownable {
    using ECDSA for bytes32;

    struct TransferProof {
        bytes32 newMetadataHash;
        string newEncryptedURI;
        uint256 deadline;
        uint256 nonce;
        bytes signature;
    }

    bytes32 private constant TRANSFER_PROOF_TYPEHASH =
        keccak256(
            "TransferProof(uint256 chainId,address inft,address from,address to,uint256 tokenId,bytes32 sealedKeyHash,bytes32 newMetadataHash,bytes32 newEncryptedURIHash,uint256 deadline,uint256 nonce)"
        );

    mapping(address => bool) public trustedAttestors;

    event AttestorUpdated(address indexed attestor, bool trusted);

    constructor(address initialOwner, address initialAttestor) Ownable(initialOwner) {
        require(initialAttestor != address(0), "TEEOracle: attestor required");
        trustedAttestors[initialAttestor] = true;
        emit AttestorUpdated(initialAttestor, true);
    }

    function setTrustedAttestor(address attestor, bool trusted) external onlyOwner {
        require(attestor != address(0), "TEEOracle: bad attestor");
        trustedAttestors[attestor] = trusted;
        emit AttestorUpdated(attestor, trusted);
    }

    function verifyTransferProof(
        address inft,
        address from,
        address to,
        uint256 tokenId,
        bytes calldata sealedKey,
        bytes calldata proof
    ) external view returns (bool) {
        TransferProof memory p = abi.decode(proof, (TransferProof));
        if (p.deadline < block.timestamp) {
            return false;
        }

        bytes32 payloadHash = keccak256(
            abi.encode(
                TRANSFER_PROOF_TYPEHASH,
                block.chainid,
                inft,
                from,
                to,
                tokenId,
                keccak256(sealedKey),
                p.newMetadataHash,
                keccak256(bytes(p.newEncryptedURI)),
                p.deadline,
                p.nonce
            )
        );

        address signer = MessageHashUtils.toEthSignedMessageHash(payloadHash).recover(p.signature);
        return trustedAttestors[signer];
    }
}
