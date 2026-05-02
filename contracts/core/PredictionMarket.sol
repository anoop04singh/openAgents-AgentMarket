// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "../interfaces/IAgentRegistry.sol";
import "../interfaces/IPositionToken.sol";
import "../interfaces/ICollectiveResolver.sol";

/**
 * @title PredictionMarket
 * @notice A single binary (YES/NO) prediction market.
 *         Deployed by MarketFactory via EIP-1167 minimal proxy (clone).
 *
 * ─── Lifecycle ───────────────────────────────────────────────────────────────
 *   OPEN       → Agents can place bets (YES or NO)
 *   RESOLVING  → resolutionTime has passed; CollectiveResolver accepts votes
 *   RESOLVED   → Majority vote has determined outcome; winners can claim
 *   INVALID    → Quorum never reached or market voided; all bets returned
 *   DISPUTED   → (v2) A resolution has been challenged; re-vote triggered
 *
 * ─── Pricing & Collateral ─────────────────────────────────────────────────────
 *   Parimutuel model:
 *   • 1 PRED bet → 1 position token minted (1:1)
 *   • At resolution: winnerPayout = totalCollateral * (100 - FEE_BPS) / 10_000
 *                                   / totalWinningTokens
 *   • 2% fee: 1.5% to treasury, 0.5% to resolver reward pool
 *
 * ─── Autonomy ─────────────────────────────────────────────────────────────────
 *   Any verified agent (or any address) can call triggerResolution() once
 *   block.timestamp >= resolutionTime, enabling fully autonomous operation.
 */
contract PredictionMarket is ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ─── Constants ────────────────────────────────────────────────────────────
    uint256 public constant FEE_BPS          = 200;   // 2% total fee
    uint256 public constant TREASURY_BPS     = 150;   // 1.5% to treasury
    uint256 public constant RESOLVER_BPS     = 50;    // 0.5% to resolver rewards
    uint256 public constant BPS_DENOMINATOR  = 10_000;
    uint8   public constant YES              = 1;
    uint8   public constant NO               = 0;

    // ─── Market State ─────────────────────────────────────────────────────────
    enum MarketState { OPEN, RESOLVING, RESOLVED, INVALID }

    struct MarketConfig {
        bytes32 questionHash;     // keccak256 of question string (stored off-chain / IPFS)
        string  questionURI;      // IPFS URI to question details + context
        uint256 createdAt;
        uint256 resolutionTime;   // earliest time resolution voting can begin
        uint256 bettingCloseTime; // when betting closes (usually == resolutionTime)
        uint256 creatorAgentId;
        address creator;
        uint256 minBet;
        string  category;
    }

    // ─── Storage ──────────────────────────────────────────────────────────────
    bool private _initialized;

    IAgentRegistry      public registry;
    IPositionToken      public positionToken;
    ICollectiveResolver public resolver;
    IERC20              public collateralToken;   // PRED
    address             public treasury;
    address             public factory;

    MarketConfig   public config;
    MarketState    public state;

    uint256 public yesPool;       // total PRED bet on YES
    uint256 public noPool;        // total PRED bet on NO
    uint256 public resolverPool;  // 0.5% fee reserved for resolvers
    uint8   public outcome;       // 1 = YES, 0 = NO (valid only when RESOLVED)

    mapping(address => uint256) public yesBalances;
    mapping(address => uint256) public noBalances;
    mapping(address => bool)    public hasClaimed;

    uint256 public totalCollateral;  // yesPool + noPool (after fee deductions)

    // ─── Events ───────────────────────────────────────────────────────────────
    event BetPlaced(
        address indexed agent,
        uint8   indexed outcomeIndex,
        uint256 amount,
        uint256 tokensReceived,
        uint256 yesPoolAfter,
        uint256 noPoolAfter
    );
    event ResolutionTriggered(uint256 timestamp);
    event MarketResolved(uint8 indexed outcome, uint256 totalPool, uint256 resolverPool);
    event MarketInvalidated(string reason);
    event WinningsClaimed(address indexed agent, uint256 amount);
    event InvalidBetReturned(address indexed agent, uint256 amount);

    // ─── Errors ───────────────────────────────────────────────────────────────
    error AlreadyInitialized();
    error NotOpen();
    error NotResolving();
    error BettingClosed();
    error BelowMinBet();
    error ResolutionTimeNotReached();
    error AlreadyClaimed();
    error NoWinnings();
    error OnlyResolver();
    error OnlyFactory();

    // ─── Initializer (called by Factory after clone) ──────────────────────────

    function initialize(
        address _registry,
        address _positionToken,
        address _resolver,
        address _collateralToken,
        address _treasury,
        address _factory,
        bytes32 _questionHash,
        string  calldata _questionURI,
        uint256 _resolutionTime,
        uint256 _bettingCloseTime,
        uint256 _creatorAgentId,
        address _creator,
        uint256 _minBet,
        string  calldata _category
    ) external {
        if (_initialized) revert AlreadyInitialized();
        _initialized = true;

        registry       = IAgentRegistry(_registry);
        positionToken  = IPositionToken(_positionToken);
        resolver       = ICollectiveResolver(_resolver);
        collateralToken = IERC20(_collateralToken);
        treasury       = _treasury;
        factory        = _factory;

        config = MarketConfig({
            questionHash:     _questionHash,
            questionURI:      _questionURI,
            createdAt:        block.timestamp,
            resolutionTime:   _resolutionTime,
            bettingCloseTime: _bettingCloseTime,
            creatorAgentId:   _creatorAgentId,
            creator:          _creator,
            minBet:           _minBet,
            category:         _category
        });

        state = MarketState.OPEN;
    }

    // ─── Betting ──────────────────────────────────────────────────────────────

    /**
     * @notice Place a bet. Only verified agents can bet.
     * @param outcomeIndex  1 = YES, 0 = NO
     * @param amount        PRED tokens to bet (>= minBet)
     *
     * Tokens minted = amount (1:1). Payout ratio determined at resolution.
     * A 2% fee is deducted from the collateral pool on claim.
     */
    function bet(uint8 outcomeIndex, uint256 amount)
        external
        nonReentrant
    {
        if (state != MarketState.OPEN) revert NotOpen();
        if (block.timestamp >= config.bettingCloseTime) revert BettingClosed();
        if (amount < config.minBet) revert BelowMinBet();
        require(outcomeIndex == YES || outcomeIndex == NO, "Invalid outcome");
        require(registry.isVerified(msg.sender), "Agent not verified");

        // Transfer collateral
        collateralToken.safeTransferFrom(msg.sender, address(this), amount);

        // Update pool
        if (outcomeIndex == YES) {
            yesPool += amount;
            yesBalances[msg.sender] += amount;
        } else {
            noPool += amount;
            noBalances[msg.sender] += amount;
        }
        totalCollateral += amount;

        // Mint 1:1 position tokens
        positionToken.mint(msg.sender, address(this), outcomeIndex, amount);

        emit BetPlaced(
            msg.sender,
            outcomeIndex,
            amount,
            amount,
            yesPool,
            noPool
        );
    }

    // ─── Resolution Trigger ───────────────────────────────────────────────────

    /**
     * @notice Anyone can call this once resolutionTime is passed.
     *         Transitions market to RESOLVING and opens resolver voting window.
     */
    function triggerResolution() external {
        if (state != MarketState.OPEN) revert NotOpen();
        if (block.timestamp < config.resolutionTime)
            revert ResolutionTimeNotReached();

        state = MarketState.RESOLVING;

        // Notify the CollectiveResolver to open voting for this market
        resolver.openVoting(address(this), config.resolutionTime);

        emit ResolutionTriggered(block.timestamp);
    }

    // ─── Resolution Callback (called by CollectiveResolver) ───────────────────

    /**
     * @notice Called by CollectiveResolver once voting concludes.
     * @param _outcome  1 = YES won, 0 = NO won, 2 = INVALID
     */
    function resolveMarket(uint8 _outcome) external nonReentrant {
        if (msg.sender != address(resolver)) revert OnlyResolver();
        if (state != MarketState.RESOLVING) revert NotResolving();

        if (_outcome == 2) {
            // INVALID: refund everyone
            state = MarketState.INVALID;
            emit MarketInvalidated("No quorum reached or voted INVALID");
            return;
        }

        outcome = _outcome;
        state   = MarketState.RESOLVED;

        // Carve out resolver reward from total collateral
        uint256 rPool = (totalCollateral * RESOLVER_BPS) / BPS_DENOMINATOR;
        resolverPool  = rPool;

        // Send resolver pool to CollectiveResolver for distribution
        collateralToken.safeTransfer(address(resolver), rPool);
        resolver.notifyRewardReceived(address(this), rPool);

        emit MarketResolved(_outcome, totalCollateral, rPool);
    }

    // ─── Claim Winnings ───────────────────────────────────────────────────────

    /**
     * @notice Winning agents call this to redeem position tokens for PRED.
     */
    function claimWinnings() external nonReentrant {
        if (state != MarketState.RESOLVED) revert NoWinnings();
        if (hasClaimed[msg.sender]) revert AlreadyClaimed();

        uint256 winningBalance = outcome == YES
            ? yesBalances[msg.sender]
            : noBalances[msg.sender];

        if (winningBalance == 0) revert NoWinnings();

        hasClaimed[msg.sender] = true;

        uint256 winningPool  = outcome == YES ? yesPool : noPool;
        uint256 netCollateral = totalCollateral - resolverPool;
        uint256 afterFees     = (netCollateral * (BPS_DENOMINATOR - TREASURY_BPS)) / BPS_DENOMINATOR;

        // Proportional payout
        uint256 payout = (winningBalance * afterFees) / winningPool;

        // Treasury fee
        uint256 treasuryFee = (payout * TREASURY_BPS) / BPS_DENOMINATOR;
        uint256 agentPayout = payout - treasuryFee;

        // Burn position tokens
        positionToken.burn(msg.sender, address(this), outcome, winningBalance);

        // Transfer
        collateralToken.safeTransfer(treasury, treasuryFee);
        collateralToken.safeTransfer(msg.sender, agentPayout);

        emit WinningsClaimed(msg.sender, agentPayout);
    }

    /**
     * @notice In INVALID markets, agents reclaim their original bets (no fee).
     */
    function claimRefund() external nonReentrant {
        if (state != MarketState.INVALID) revert NoWinnings();
        if (hasClaimed[msg.sender]) revert AlreadyClaimed();

        uint256 yesAmt = yesBalances[msg.sender];
        uint256 noAmt  = noBalances[msg.sender];
        uint256 total  = yesAmt + noAmt;
        if (total == 0) revert NoWinnings();

        hasClaimed[msg.sender] = true;

        if (yesAmt > 0) positionToken.burn(msg.sender, address(this), YES, yesAmt);
        if (noAmt > 0)  positionToken.burn(msg.sender, address(this), NO,  noAmt);

        collateralToken.safeTransfer(msg.sender, total);
        emit InvalidBetReturned(msg.sender, total);
    }

    // ─── View Helpers ─────────────────────────────────────────────────────────

    /**
     * @notice Real-time implied probability for YES (in basis points).
     *         impliedYes = yesPool * 10_000 / (yesPool + noPool)
     */
    function impliedProbabilityYes() external view returns (uint256) {
        if (totalCollateral == 0) return 5_000; // 50% default
        return (yesPool * BPS_DENOMINATOR) / totalCollateral;
    }

    function getMarketSummary() external view returns (
        MarketState _state,
        uint256 _yesPool,
        uint256 _noPool,
        uint256 _totalCollateral,
        uint256 _resolutionTime,
        uint8   _outcome
    ) {
        return (state, yesPool, noPool, totalCollateral, config.resolutionTime, outcome);
    }

    function getPositionIds() external view returns (uint256 yesId, uint256 noId) {
        yesId = positionToken.getPositionId(address(this), YES);
        noId  = positionToken.getPositionId(address(this), NO);
    }
}
