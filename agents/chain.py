"""
agents/chain.py
All Ethereum contract interactions for AgentMarket.
Wraps web3.py with typed helpers for every contract call.
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional, Tuple

from web3 import Web3
from eth_account import Account

try:
    from web3.middleware import geth_poa_middleware as POA_MIDDLEWARE
except ImportError:
    try:
        from web3.middleware import ExtraDataToPOAMiddleware as POA_MIDDLEWARE
    except ImportError:
        POA_MIDDLEWARE = None

from config import (
    EVM_RPC_URL, CHAIN_ID,
    PRED_TOKEN_ADDRESS, POSITION_TOKEN_ADDRESS,
    AGENT_REGISTRY_ADDRESS, MARKET_FACTORY_ADDRESS,
    COLLECTIVE_RESOLVER_ADDRESS,
    AGENT_PRIVATE_KEY, TX_CONFIRM_TIMEOUT_SEC
)

log = logging.getLogger("chain")

# ─── ABI fragments (minimal — only what agents call) ─────────────────────────

PRED_ABI = [
    {"name": "approve",     "type": "function", "inputs": [{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}], "outputs": [{"type":"bool"}]},
    {"name": "balanceOf",   "type": "function", "inputs": [{"name":"account","type":"address"}], "outputs": [{"type":"uint256"}]},
    {"name": "allowance",   "type": "function", "inputs": [{"name":"owner","type":"address"},{"name":"spender","type":"address"}], "outputs": [{"type":"uint256"}]},
]

REGISTRY_ABI = [
    {"name": "register",          "type": "function", "inputs": [{"name":"metadataURI","type":"string"},{"name":"stakeAmount","type":"uint256"},{"name":"kvStreamId","type":"string"}], "outputs": [{"name":"agentId","type":"uint256"}]},
    {"name": "isVerified",        "type": "function", "inputs": [{"name":"agent","type":"address"}], "outputs": [{"type":"bool"}], "stateMutability": "view"},
    {"name": "getAgent",          "type": "function", "inputs": [{"name":"agentAddr","type":"address"}], "outputs": [{"components": [{"name":"agentId","type":"uint256"},{"name":"agentAddress","type":"address"},{"name":"tier","type":"uint8"},{"name":"stakedAmount","type":"uint256"},{"name":"reputationScore","type":"uint256"},{"name":"totalResolutions","type":"uint256"},{"name":"correctResolutions","type":"uint256"},{"name":"registeredAt","type":"uint256"},{"name":"metadataURI","type":"string"},{"name":"slashed","type":"bool"},{"name":"storageLogRoot","type":"bytes32"},{"name":"kvStreamId","type":"string"},{"name":"inftTokenId","type":"uint256"},{"name":"researchReportsCount","type":"uint256"}], "type":"tuple"}], "stateMutability": "view"},
    {"name": "addressToAgentId",  "type": "function", "inputs": [{"name":"","type":"address"}], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
    {"name": "totalVerifiedAgents","type":"function","inputs":[],"outputs":[{"type":"uint256"}],"stateMutability":"view"},
    {"name": "recordResearchReport", "type": "function", "inputs": [{"name":"reportRoot","type":"bytes32"}], "outputs": []},
    {"name": "updateStorageRoot", "type": "function", "inputs": [{"name":"newStorageLogRoot","type":"bytes32"},{"name":"newKvStreamId","type":"string"}], "outputs": []},
    {"name": "linkInft",          "type": "function", "inputs": [{"name":"inftTokenId","type":"uint256"}], "outputs": []},
    {"name": "increaseStake",     "type": "function", "inputs": [{"name":"amount","type":"uint256"}], "outputs": []},
    {"name": "minStakeVerified",  "type": "function", "inputs": [], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
]

FACTORY_ABI = [
    {"name": "createMarket", "type": "function", "inputs": [{"name":"questionURI","type":"string"},{"name":"resolutionTime","type":"uint256"},{"name":"category","type":"string"},{"name":"minBet","type":"uint256"}], "outputs": [{"name":"market","type":"address"}]},
    {"name": "marketCount",  "type": "function", "inputs": [], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
    {"name": "markets",      "type": "function", "inputs": [{"name":"","type":"uint256"}], "outputs": [{"name":"market","type":"address"},{"name":"creator","type":"address"},{"name":"agentId","type":"uint256"},{"name":"createdAt","type":"uint256"},{"name":"resolutionTime","type":"uint256"},{"name":"questionURI","type":"string"},{"name":"category","type":"string"},{"name":"active","type":"bool"}], "stateMutability":"view"},
    {"name": "marketCreationStake","type":"function","inputs":[],"outputs":[{"type":"uint256"}],"stateMutability":"view"},
    {"name": "returnCreatorStake","type":"function","inputs":[{"name":"market","type":"address"}],"outputs":[]},
    {"anonymous": False, "type": "event", "name": "MarketCreated", "inputs": [
        {"indexed": True, "name": "marketId", "type": "uint256"},
        {"indexed": True, "name": "market", "type": "address"},
        {"indexed": True, "name": "creator", "type": "address"},
        {"indexed": False, "name": "agentId", "type": "uint256"},
        {"indexed": False, "name": "questionURI", "type": "string"},
        {"indexed": False, "name": "resolutionTime", "type": "uint256"},
        {"indexed": False, "name": "category", "type": "string"},
    ]},
]

MARKET_ABI = [
    {"name": "bet",               "type": "function", "inputs": [{"name":"outcomeIndex","type":"uint8"},{"name":"amount","type":"uint256"}], "outputs": []},
    {"name": "triggerResolution", "type": "function", "inputs": [], "outputs": []},
    {"name": "claimWinnings",     "type": "function", "inputs": [], "outputs": []},
    {"name": "claimRefund",       "type": "function", "inputs": [], "outputs": []},
    {"name": "state",             "type": "function", "inputs": [], "outputs": [{"type":"uint8"}], "stateMutability": "view"},
    {"name": "yesPool",           "type": "function", "inputs": [], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
    {"name": "noPool",            "type": "function", "inputs": [], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
    {"name": "totalCollateral",   "type": "function", "inputs": [], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
    {"name": "impliedProbabilityYes","type":"function","inputs":[],"outputs":[{"type":"uint256"}],"stateMutability":"view"},
    {"name": "config",            "type": "function", "inputs": [], "outputs": [{"components":[{"name":"questionHash","type":"bytes32"},{"name":"questionURI","type":"string"},{"name":"createdAt","type":"uint256"},{"name":"resolutionTime","type":"uint256"},{"name":"bettingCloseTime","type":"uint256"},{"name":"creatorAgentId","type":"uint256"},{"name":"creator","type":"address"},{"name":"minBet","type":"uint256"},{"name":"category","type":"string"}],"type":"tuple"}], "stateMutability":"view"},
    {"name": "yesBalances",       "type": "function", "inputs": [{"name":"","type":"address"}], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
    {"name": "noBalances",        "type": "function", "inputs": [{"name":"","type":"address"}], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
]

RESOLVER_ABI = [
    {"name": "castVerifiedVote",  "type": "function", "inputs": [{"name":"market","type":"address"},{"name":"choice","type":"uint8"},{"name":"storageLogRoot","type":"bytes32"},{"name":"teeSignature","type":"bytes"}], "outputs": []},
    {"name": "castVote",          "type": "function", "inputs": [{"name":"market","type":"address"},{"name":"choice","type":"uint8"}], "outputs": []},
    {"name": "finalizeResolution","type": "function", "inputs": [{"name":"market","type":"address"}], "outputs": []},
    {"name": "distributeRewards", "type": "function", "inputs": [{"name":"market","type":"address"}], "outputs": []},
    {"name": "isVotingOpen",      "type": "function", "inputs": [{"name":"market","type":"address"}], "outputs": [{"type":"bool"}], "stateMutability": "view"},
    {"name": "timeUntilDeadline", "type": "function", "inputs": [{"name":"market","type":"address"}], "outputs": [{"type":"uint256"}], "stateMutability": "view"},
    {"name": "getActiveSessions", "type": "function", "inputs": [], "outputs": [{"type":"address[]"}], "stateMutability": "view"},
    {"name": "getSession",        "type": "function", "inputs": [{"name":"market","type":"address"}], "outputs": [{"components":[{"name":"market","type":"address"},{"name":"marketResolutionTime","type":"uint256"},{"name":"votingDeadline","type":"uint256"},{"name":"extensions","type":"uint256"},{"name":"state","type":"uint8"},{"name":"weightedYes","type":"uint256"},{"name":"weightedNo","type":"uint256"},{"name":"weightedInvalid","type":"uint256"},{"name":"voterCount","type":"uint256"},{"name":"finalOutcome","type":"uint8"},{"name":"finalized","type":"bool"},{"name":"rewardPool","type":"uint256"},{"name":"rewardDistributed","type":"bool"}],"type":"tuple"}], "stateMutability":"view"},
    {"name": "getVote",           "type": "function", "inputs": [{"name":"market","type":"address"},{"name":"voter","type":"address"}], "outputs": [{"components":[{"name":"choice","type":"uint8"},{"name":"weight","type":"uint256"},{"name":"cast","type":"bool"},{"name":"rewarded","type":"bool"},{"name":"storageLogRoot","type":"bytes32"},{"name":"teeSignature","type":"bytes"},{"name":"hasPoIR","type":"bool"}],"type":"tuple"}], "stateMutability":"view"},
    {"name": "getVoteProbabilities","type":"function","inputs":[{"name":"market","type":"address"}],"outputs":[{"name":"yesBps","type":"uint256"},{"name":"noBps","type":"uint256"},{"name":"invalidBps","type":"uint256"}],"stateMutability":"view"},
]


class ChainClient:
    """Web3 wrapper for all AgentMarket contract interactions."""

    MARKET_STATE = {0: "OPEN", 1: "RESOLVING", 2: "RESOLVED", 3: "INVALID"}

    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(EVM_RPC_URL))
        if POA_MIDDLEWARE is not None:
            self.w3.middleware_onion.inject(POA_MIDDLEWARE, layer=0)
        assert self.w3.is_connected(), f"Cannot connect to {EVM_RPC_URL}"

        self.account  = Account.from_key(AGENT_PRIVATE_KEY)
        self.address  = self.account.address
        log.info(f"Chain client ready — wallet: {self.address}")

        # Contract instances
        self.pred     = self.w3.eth.contract(address=PRED_TOKEN_ADDRESS,            abi=PRED_ABI)
        self.registry = self.w3.eth.contract(address=AGENT_REGISTRY_ADDRESS,        abi=REGISTRY_ABI)
        self.factory  = self.w3.eth.contract(address=MARKET_FACTORY_ADDRESS,        abi=FACTORY_ABI)
        self.resolver = self.w3.eth.contract(address=COLLECTIVE_RESOLVER_ADDRESS,   abi=RESOLVER_ABI)

    def market_contract(self, address: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=MARKET_ABI)

    def native_balance_wei(self) -> int:
        return self.w3.eth.get_balance(self.address)

    def native_balance_og(self) -> float:
        return float(self.w3.from_wei(self.native_balance_wei(), "ether"))

    def pred_balance_wei(self) -> int:
        return self.pred.functions.balanceOf(self.address).call()

    def require_native_budget(self, min_og: float, context: str) -> None:
        balance = self.native_balance_og()
        if balance < min_og:
            raise RuntimeError(
                f"Insufficient native 0G for {context}. "
                f"Wallet={self.address} balance={balance:.6f} OG required>={min_og:.6f} OG. "
                "Fund this wallet from the 0G Galileo faucet before running the demo."
            )

    def estimate_tx_cost_wei(self, fn, fallback_gas: int = 300_000) -> int:
        try:
            gas_limit = int(fn.estimate_gas({"from": self.address}) * 1.25)
        except Exception:
            gas_limit = fallback_gas
        return gas_limit * int(self.w3.eth.gas_price * 1.2)

    # ─── TX helper ─────────────────────────────────────────────────────────────

    def _send(self, fn, gas: int = 300_000) -> str:
        """Build, sign, send, and wait for a transaction. Returns tx hash."""
        last_error = None
        for attempt in range(3):
            nonce = self.w3.eth.get_transaction_count(self.address, "pending")
            gas_price = int(self.w3.eth.gas_price * (1.15 + attempt * 0.15))
            try:
                estimated_gas = fn.estimate_gas({"from": self.address})
                gas_limit = int(estimated_gas * 1.25)
            except Exception as e:
                log.warning(f"Gas estimate failed, using fallback gas={gas}: {e}")
                gas_limit = gas
            native_balance = self.w3.eth.get_balance(self.address)
            max_cost = gas_limit * gas_price
            if native_balance < max_cost:
                raise RuntimeError(
                    f"Insufficient native 0G for tx gas. Wallet={self.address} "
                    f"balance={self.w3.from_wei(native_balance, 'ether')} "
                    f"required~={self.w3.from_wei(max_cost, 'ether')} "
                    f"gasLimit={gas_limit} gasPrice={gas_price}. Fund this wallet from the 0G faucet."
                )
            tx_params = {
                "from":     self.address,
                "nonce":    nonce,
                "gas":      gas_limit,
                "gasPrice": gas_price,
                "chainId":  CHAIN_ID,
            }
            try:
                fn.call({"from": self.address})
            except Exception as e:
                log.warning(f"Preflight call failed: {e}")
            tx = fn.build_transaction(tx_params)
            signed = self.account.sign_transaction(tx)
            raw_tx = getattr(signed, "rawTransaction", None) or signed.raw_transaction
            try:
                tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
                break
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                if "replacement transaction underpriced" not in msg and "nonce too low" not in msg:
                    raise
                time.sleep(2)
        else:
            raise last_error
        log.info(f"TX sent: {tx_hash.hex()}")
        receipt = self.w3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=TX_CONFIRM_TIMEOUT_SEC
        )
        if receipt.status == 0:
            raise Exception(f"TX reverted: {tx_hash.hex()}")
        log.info(f"TX confirmed in block {receipt.blockNumber}")
        return tx_hash.hex()

    # ─── Registration ──────────────────────────────────────────────────────────

    def register_agent(self, metadata_uri: str, stake_pred: float, kv_stream_id: str = "") -> str:
        stake_wei = int(stake_pred * 1e18)
        if self.pred_balance_wei() < stake_wei:
            raise RuntimeError(
                f"Insufficient PRED for agent registration. Wallet={self.address} "
                f"balance={self.pred_balance_wei() / 1e18:.2f} PRED required={stake_wei / 1e18:.2f} PRED."
            )
        approve_fn = self.pred.functions.approve(AGENT_REGISTRY_ADDRESS, stake_wei)
        register_fn = self.registry.functions.register(metadata_uri, stake_wei, kv_stream_id)
        estimated_cost = (
            self.estimate_tx_cost_wei(approve_fn)
            + self.estimate_tx_cost_wei(register_fn, fallback_gas=500_000)
        )
        if self.native_balance_wei() < estimated_cost:
            raise RuntimeError(
                f"Insufficient native 0G for agent registration. Wallet={self.address} "
                f"balance={self.w3.from_wei(self.native_balance_wei(), 'ether')} OG "
                f"required~={self.w3.from_wei(estimated_cost, 'ether')} OG."
            )
        # Approve registry to pull stake
        self._send(approve_fn)
        return self._send(
            register_fn,
            gas=500_000
        )

    def is_verified(self) -> bool:
        return self.registry.functions.isVerified(self.address).call()

    def get_agent_id(self) -> int:
        return self.registry.functions.addressToAgentId(self.address).call()

    def get_agent_info(self):
        return self.registry.functions.getAgent(self.address).call()

    def is_registered(self) -> bool:
        return self.get_agent_id() != 0

    def min_verified_stake(self) -> int:
        return self.registry.functions.minStakeVerified().call()

    def ensure_verified_agent(self, metadata_uri: str, stake_pred: float = 1_000.0, kv_stream_id: str = "") -> None:
        required = max(int(stake_pred * 1e18), self.min_verified_stake())
        if not self.is_registered():
            try:
                self.register_agent(metadata_uri, required / 1e18, kv_stream_id)
            except Exception:
                if not self.is_registered():
                    raise

        info = self.get_agent_info()
        current_stake = int(info[3])
        if current_stake < required:
            top_up = required - current_stake
            self._send(self.pred.functions.approve(AGENT_REGISTRY_ADDRESS, top_up))
            self._send(self.registry.functions.increaseStake(top_up), gas=300_000)

        if not self.is_verified():
            raise RuntimeError("Agent is registered but still not verified; check slash status or registry tier")

    def record_research_report(self, report_root_hex: str) -> str:
        root_bytes = bytes.fromhex(report_root_hex.removeprefix("0x"))
        return self._send(self.registry.functions.recordResearchReport(root_bytes))

    def update_storage_root(self, storage_root_hex: str, kv_stream_id: str = "") -> str:
        root_bytes = bytes.fromhex(storage_root_hex.removeprefix("0x"))
        return self._send(self.registry.functions.updateStorageRoot(root_bytes, kv_stream_id))

    def link_inft(self, inft_token_id: int) -> str:
        return self._send(self.registry.functions.linkInft(inft_token_id))

    # ─── Market creation ───────────────────────────────────────────────────────

    def create_market(self, question_uri: str, resolution_time: int,
                      category: str, min_bet_pred: float = 1.0) -> str:
        """Returns address of deployed market clone."""
        creation_stake = self.factory.functions.marketCreationStake().call()
        if self.pred_balance_wei() < creation_stake:
            raise RuntimeError(
                f"Insufficient PRED for market creation. Wallet={self.address} "
                f"balance={self.pred_balance_wei() / 1e18:.2f} PRED required={creation_stake / 1e18:.2f} PRED."
            )
        approve_fn = self.pred.functions.approve(MARKET_FACTORY_ADDRESS, creation_stake)
        create_fn = self.factory.functions.createMarket(
            question_uri, resolution_time, category, int(min_bet_pred * 1e18)
        )
        estimated_cost = (
            self.estimate_tx_cost_wei(approve_fn)
            + self.estimate_tx_cost_wei(create_fn, fallback_gas=800_000)
        )
        if self.native_balance_wei() < estimated_cost:
            raise RuntimeError(
                f"Insufficient native 0G for market creation. Wallet={self.address} "
                f"balance={self.w3.from_wei(self.native_balance_wei(), 'ether')} OG "
                f"required~={self.w3.from_wei(estimated_cost, 'ether')} OG."
            )
        self._send(approve_fn)
        tx = self._send(
            create_fn,
            gas=800_000
        )
        # Parse the exact MarketCreated event. Do not scan arbitrary topics:
        # ERC20 Approval and AccessControl RoleGranted logs also have indexed
        # addresses and can otherwise be mistaken for the market clone.
        receipt = self.w3.eth.get_transaction_receipt(tx)
        event_topic = self.w3.keccak(text="MarketCreated(uint256,address,address,uint256,string,uint256,string)").hex()
        factory_addr = Web3.to_checksum_address(MARKET_FACTORY_ADDRESS)
        for log_entry in receipt.logs:
            if Web3.to_checksum_address(log_entry.address) != factory_addr:
                continue
            if not log_entry.topics or log_entry.topics[0].hex() != event_topic:
                continue
            event = self.factory.events.MarketCreated().process_log(log_entry)
            return Web3.to_checksum_address(event["args"]["market"])
        raise Exception("Could not parse market address from logs")

    def get_all_markets(self) -> list:
        count = self.factory.functions.marketCount().call()
        return [self.factory.functions.markets(i).call() for i in range(1, count + 1)]

    # ─── Betting ───────────────────────────────────────────────────────────────

    def place_bet(self, market_addr: str, outcome: int, amount_pred: float) -> str:
        """outcome: 1=YES, 0=NO"""
        amount_wei = int(amount_pred * 1e18)
        mkt = self.market_contract(market_addr)
        self._send(self.pred.functions.approve(market_addr, amount_wei))
        return self._send(mkt.functions.bet(outcome, amount_wei), gas=200_000)

    def get_market_state(self, market_addr: str) -> str:
        mkt = self.market_contract(market_addr)
        state_int = mkt.functions.state().call()
        return self.MARKET_STATE.get(state_int, "UNKNOWN")

    def get_market_config(self, market_addr: str) -> dict:
        mkt = self.market_contract(market_addr)
        cfg = mkt.functions.config().call()
        return {
            "questionHash":    cfg[0].hex(),
            "questionURI":     cfg[1],
            "createdAt":       cfg[2],
            "resolutionTime":  cfg[3],
            "bettingCloseTime":cfg[4],
            "creatorAgentId":  cfg[5],
            "creator":         cfg[6],
            "minBet":          cfg[7] / 1e18,
            "category":        cfg[8],
        }

    def get_market_pools(self, market_addr: str) -> Tuple[float, float]:
        mkt = self.market_contract(market_addr)
        yes = mkt.functions.yesPool().call() / 1e18
        no  = mkt.functions.noPool().call()  / 1e18
        return yes, no

    def get_implied_yes_pct(self, market_addr: str) -> float:
        mkt = self.market_contract(market_addr)
        bps = mkt.functions.impliedProbabilityYes().call()
        return bps / 100  # 6732 → 67.32%

    def trigger_resolution(self, market_addr: str) -> str:
        mkt = self.market_contract(market_addr)
        return self._send(mkt.functions.triggerResolution(), gas=150_000)

    def claim_winnings(self, market_addr: str) -> str:
        mkt = self.market_contract(market_addr)
        return self._send(mkt.functions.claimWinnings(), gas=200_000)

    # ─── Resolution voting ─────────────────────────────────────────────────────

    def cast_verified_vote(
        self,
        market_addr: str,
        choice: int,
        storage_log_root: str = "",
        tee_signature: str = ""
    ) -> str:
        """choice: 0=NO 1=YES 2=INVALID"""
        root_bytes = bytes.fromhex(storage_log_root.removeprefix("0x")) if storage_log_root else bytes(32)
        sig_bytes  = bytes.fromhex(tee_signature.removeprefix("0x"))    if tee_signature    else b""
        return self._send(
            self.resolver.functions.castVerifiedVote(
                Web3.to_checksum_address(market_addr),
                choice,
                root_bytes,
                sig_bytes
            ),
            gas=200_000
        )

    def already_voted(self, market_addr: str) -> bool:
        v = self.resolver.functions.getVote(
            Web3.to_checksum_address(market_addr), self.address
        ).call()
        return v[2]  # cast field

    def finalize_resolution(self, market_addr: str) -> str:
        return self._send(
            self.resolver.functions.finalizeResolution(Web3.to_checksum_address(market_addr)),
            gas=400_000
        )

    def distribute_rewards(self, market_addr: str) -> str:
        return self._send(
            self.resolver.functions.distributeRewards(Web3.to_checksum_address(market_addr)),
            gas=400_000
        )

    def get_active_sessions(self) -> list:
        return self.resolver.functions.getActiveSessions().call()

    def is_voting_open(self, market_addr: str) -> bool:
        return self.resolver.functions.isVotingOpen(
            Web3.to_checksum_address(market_addr)
        ).call()

    def time_until_deadline(self, market_addr: str) -> int:
        return self.resolver.functions.timeUntilDeadline(
            Web3.to_checksum_address(market_addr)
        ).call()

    def get_vote_probabilities(self, market_addr: str) -> dict:
        yes_bps, no_bps, inv_bps = self.resolver.functions.getVoteProbabilities(
            Web3.to_checksum_address(market_addr)
        ).call()
        return {
            "yes":     yes_bps / 100,
            "no":      no_bps  / 100,
            "invalid": inv_bps / 100,
        }

    # ─── Balances ──────────────────────────────────────────────────────────────

    def pred_balance(self) -> float:
        return self.pred_balance_wei() / 1e18
