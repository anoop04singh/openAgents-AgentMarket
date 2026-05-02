"""
agents/services/inft_client.py
ERC-7857 iNFT minting and management on 0G Chain.

Supports:
1) 0G iNFT Integration Guide style contract interface:
   mint(to, encryptedURI, metadataHash)
   transfer(from, to, tokenId, sealedKey, proof)
   authorizeUsage(tokenId, executor, permissions)
2) Legacy project ABI fallback (set INFT_INTEGRATION_MODE=legacy).
"""

import json
import time
import logging
import hashlib
from typing import Optional

from config import (
    AGENT_PRIVATE_KEY,
    CHAIN_ID,
    INFT_CONTRACT,
    INFT_INTEGRATION_MODE,
)

log = logging.getLogger("inft")

INFT_CONTRACT_ADDRESS = INFT_CONTRACT

INFT_ABI_OG_GUIDE = [
    {
        "name": "mint",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "encryptedURI", "type": "string"},
            {"name": "metadataHash", "type": "bytes32"},
        ],
        "outputs": [{"name": "tokenId", "type": "uint256"}],
    },
    {
        "name": "transfer",
        "type": "function",
        "inputs": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
            {"name": "sealedKey", "type": "bytes"},
            {"name": "proof", "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "authorizeUsage",
        "type": "function",
        "inputs": [
            {"name": "tokenId", "type": "uint256"},
            {"name": "executor", "type": "address"},
            {"name": "permissions", "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "ownerOf",
        "type": "function",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"type": "address"}],
        "stateMutability": "view",
    },
    {
        "name": "tokenURI",
        "type": "function",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"type": "string"}],
        "stateMutability": "view",
    },
]

INFT_ABI_LEGACY = [
    {
        "name": "mint",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "metadataHash", "type": "bytes32"},
            {"name": "storageRoot", "type": "bytes32"},
            {"name": "encryptedKey", "type": "bytes"},
        ],
        "outputs": [{"name": "tokenId", "type": "uint256"}],
    },
]


class INFTClient:
    def __init__(self, chain_client):
        self.chain = chain_client
        log.info("iNFT client ready (mode=%s)", INFT_INTEGRATION_MODE)

    def build_intelligence_payload(
        self,
        agent_id: int,
        agent_address: str,
        reputation_score: int,
        correct_verdicts: int,
        total_verdicts: int,
        domain_focus: list,
        memory: dict,
        storage_log_root: str,
        axl_pubkey: str,
    ) -> dict:
        accuracy = correct_verdicts / total_verdicts if total_verdicts > 0 else 0.5
        return {
            "agentId": agent_id,
            "agentAddress": agent_address,
            "mintedAt": int(time.time()),
            "version": "1.0",
            "publicStats": {
                "reputationScore": reputation_score,
                "accuracyRate": round(accuracy, 4),
                "totalResolutions": total_verdicts,
                "correctResolutions": correct_verdicts,
                "domainFocus": domain_focus,
            },
            "storageLogRoot": storage_log_root,
            "services": [
                {"name": "market_intel", "protocol": "axl-mcp", "pubkey": axl_pubkey},
                {"name": "vote_intention", "protocol": "axl-mcp", "pubkey": axl_pubkey},
            ],
            "strategy": {
                "minBetConfidence": 0.65,
                "minVoteConfidence": 0.60,
                "peerSignalWeight": 0.25,
                "preferredModel": "deepseek-chat-v3-0324",
                "researchDepth": "thorough",
                "abstainOnAmbiguity": True,
            },
            "memory": memory,
        }

    async def mint_agent(
        self,
        agent_id: int,
        storage_log_root: str,
        intelligence_payload: dict,
    ) -> Optional[int]:
        if INFT_CONTRACT_ADDRESS == "0x0000000000000000000000000000000000000000":
            log.warning("iNFT contract address not set; using mock mint")
            return agent_id * 1000 + int(time.time() % 1000)

        try:
            from web3 import Web3
            from eth_account import Account

            w3 = self.chain.w3
            meta_bytes = json.dumps(intelligence_payload, sort_keys=True).encode()
            meta_hash = hashlib.sha256(meta_bytes).digest()

            nonce = w3.eth.get_transaction_count(self.chain.address)
            if INFT_INTEGRATION_MODE == "legacy":
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(INFT_CONTRACT_ADDRESS),
                    abi=INFT_ABI_LEGACY,
                )
                storage_root = bytes.fromhex(storage_log_root.removeprefix("0x").ljust(64, "0")[:64])
                tx = contract.functions.mint(
                    self.chain.address,
                    meta_hash,
                    storage_root,
                    b"\x00" * 32,
                ).build_transaction({
                    "from": self.chain.address,
                    "nonce": nonce,
                    "gas": 350_000,
                    "gasPrice": w3.eth.gas_price,
                    "chainId": CHAIN_ID,
                })
            else:
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(INFT_CONTRACT_ADDRESS),
                    abi=INFT_ABI_OG_GUIDE,
                )
                encrypted_uri = f"0g://{storage_log_root.removeprefix('0x')}"
                tx = contract.functions.mint(
                    self.chain.address,
                    encrypted_uri,
                    meta_hash,
                ).build_transaction({
                    "from": self.chain.address,
                    "nonce": nonce,
                    "gas": 350_000,
                    "gasPrice": w3.eth.gas_price,
                    "chainId": CHAIN_ID,
                })

            signed = Account.from_key(AGENT_PRIVATE_KEY).sign_transaction(tx)
            raw_tx = getattr(signed, "rawTransaction", None) or signed.raw_transaction
            tx_hash = w3.eth.send_raw_transaction(raw_tx)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 0:
                log.error("iNFT mint tx reverted")
                return None

            for log_entry in receipt.logs:
                if len(log_entry.topics) >= 4:
                    token_id = int(log_entry.topics[3].hex(), 16)
                    if token_id > 0:
                        log.info("iNFT minted tokenId=%s", token_id)
                        return token_id
            return None
        except Exception as e:
            log.error("iNFT mint failed: %s", e)
            return None

    async def update_intelligence(
        self,
        token_id: int,
        new_storage_log_root: str,
        new_memory: dict,
    ) -> bool:
        try:
            self.chain.update_storage_root(new_storage_log_root, "")
            log.info("iNFT %s intelligence updated with new root %s", token_id, new_storage_log_root)
            return True
        except Exception as e:
            log.error("iNFT update failed: %s", e)
            return False

    def get_aiverse_listing_url(self, token_id: int) -> str:
        return f"https://aiverse.0g.ai/agent/{token_id}"
