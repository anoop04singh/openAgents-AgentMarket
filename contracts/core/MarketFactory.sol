// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/proxy/Clones.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "../interfaces/IAgentRegistry.sol";
import "../interfaces/IPositionToken.sol";
import "../interfaces/IPredictionMarket.sol";

/**
 * @title MarketFactory
 * @notice Master factory contract that deploys PredictionMarket clones
 *         using EIP-1167 minimal proxy pattern for maximum gas efficiency.
 *
 *         Only VERIFIED or TRUSTED agents (per AgentRegistry) can create markets.
 *         A market creation stake is required, returned on resolution.
 *
 * ─── Gas Optimization ─────────────────────────────────────────────────────────
 *   Each market is deployed as a ~45-byte proxy pointing to a shared
 *   PredictionMarket implementation. Cost: ~50k gas vs ~1.5M for full deploy.
 *
 * ─── Market Registry ──────────────────────────────────────────────────────────
 *   All deployed markets are tracked for off-chain indexing by AI agents.
 */
contract MarketFactory is AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using Clones for address;

    // ─── Roles ────────────────────────────────────────────────────────────────
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");

    // ─── Config ───────────────────────────────────────────────────────────────
    address public immutable marketImplementation; // PredictionMarket logic contract
    IAgentRegistry public  registry;
    IPositionToken  public positionToken;
    address         public resolver;
    address         public collateralToken;
    address         public treasury;

    uint256 public marketCreationStake = 500 * 1e18;  // 500 PRED to create market
    uint256 public minResolutionDelay  = 1 hours;
    uint256 public maxResolutionDelay  = 365 days;
    uint256 public defaultMinBet       = 1 * 1e18;     // 1 PRED

    bool    public paused;

    // ─── Market Registry ──────────────────────────────────────────────────────
    struct MarketRecord {
        address market;
        address creator;
        uint256 agentId;
        uint256 createdAt;
        uint256 resolutionTime;
        string  questionURI;
        string  category;
        bool    active;
    }

    uint256 public marketCount;
    mapping(uint256 => MarketRecord)  public markets;         // index → record
    mapping(address  => uint256)      public marketIndex;     // market addr → index
    mapping(address  => uint256[])    public agentMarkets;    // creator → market indices
    mapping(string   => uint256[])    public categoryMarkets; // category → market indices

    // Creator stakes (returned on resolution)
    mapping(address => uint256) public creatorStakes;

    // ─── Events ───────────────────────────────────────────────────────────────
    event MarketCreated(
        uint256 indexed marketId,
        address indexed market,
        address indexed creator,
        uint256 agentId,
        string  questionURI,
        uint256 resolutionTime,
        string  category
    );
    event MarketStakeReturned(address indexed market, address indexed creator, uint256 amount);
    event FactoryConfigUpdated(uint256 creationStake, uint256 minDelay, uint256 maxDelay);
    event FactoryPaused(bool paused);

    // ─── Errors ───────────────────────────────────────────────────────────────
    error FactoryPausedError();
    error NotVerifiedAgent();
    error InvalidResolutionTime();
    error InvalidQuestion();
    error MarketNotFound();

    constructor(
        address _implementation,
        address _registry,
        address _positionToken,
        address _resolver,
        address _collateralToken,
        address _treasury,
        address _admin
    ) {
        marketImplementation = _implementation;
        registry       = IAgentRegistry(_registry);
        positionToken  = IPositionToken(_positionToken);
        resolver       = _resolver;
        collateralToken = _collateralToken;
        treasury       = _treasury;

        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(PAUSER_ROLE, _admin);
    }

    // ─── Market Creation ──────────────────────────────────────────────────────

    /**
     * @notice Deploy a new PredictionMarket.
     *         Caller must be a VERIFIED agent.
     *
     * @param questionURI      IPFS URI to structured question JSON
     * @param resolutionTime   Unix timestamp when voting can begin
     * @param category         Category string for indexing (e.g. "crypto", "science")
     * @param minBet           Minimum bet amount in PRED (0 = default)
     *
     * @return market  Address of deployed PredictionMarket clone
     */
    function createMarket(
        string  calldata questionURI,
        uint256 resolutionTime,
        string  calldata category,
        uint256 minBet
    )
        external
        nonReentrant
        returns (address market)
    {
        if (paused) revert FactoryPausedError();
        if (!registry.isVerified(msg.sender)) revert NotVerifiedAgent();
        if (bytes(questionURI).length == 0) revert InvalidQuestion();

        uint256 rTime = resolutionTime;
        if (rTime < block.timestamp + minResolutionDelay
            || rTime > block.timestamp + maxResolutionDelay)
            revert InvalidResolutionTime();

        // Collect creation stake
        IERC20(collateralToken).safeTransferFrom(
            msg.sender, address(this), marketCreationStake
        );

        // Get creator's agentId
        IAgentRegistry.Agent memory agent = registry.getAgent(msg.sender);
        uint256 agentId = agent.agentId;

        // Deploy EIP-1167 clone
        market = marketImplementation.clone();

        // Derive question hash for on-chain reference
        bytes32 questionHash = keccak256(bytes(questionURI));

        // Initialize clone
        IPredictionMarket(market).initialize(
            address(registry),
            address(positionToken),
            resolver,
            collateralToken,
            treasury,
            address(this),
            questionHash,
            questionURI,
            rTime,
            rTime, // bettingCloseTime == resolutionTime
            agentId,
            msg.sender,
            minBet == 0 ? defaultMinBet : minBet,
            category
        );

        // Grant market MINTER_ROLE on PositionToken
        positionToken.grantMinterRole(market);

        // Track creator stake
        creatorStakes[market] = marketCreationStake;

        // Register market
        uint256 marketId = ++marketCount;
        markets[marketId] = MarketRecord({
            market:         market,
            creator:        msg.sender,
            agentId:        agentId,
            createdAt:      block.timestamp,
            resolutionTime: rTime,
            questionURI:    questionURI,
            category:       category,
            active:         true
        });
        marketIndex[market]     = marketId;
        agentMarkets[msg.sender].push(marketId);
        categoryMarkets[category].push(marketId);

        emit MarketCreated(marketId, market, msg.sender, agentId, questionURI, rTime, category);
    }

    /**
     * @notice Return creation stake after a market resolves.
     *         Called by the resolver or automatically claimable by creator.
     */
    function returnCreatorStake(address market) external nonReentrant {
        uint256 idx = marketIndex[market];
        if (idx == 0) revert MarketNotFound();

        MarketRecord storage record = markets[idx];
        uint256 stake = creatorStakes[market];
        if (stake == 0) return;

        // Market must be resolved or invalid
        (IPredictionMarket.MarketState mState,,,,, ) =
            IPredictionMarket(market).getMarketSummary();

        require(
            mState == IPredictionMarket.MarketState.RESOLVED
            || mState == IPredictionMarket.MarketState.INVALID,
            "MarketFactory: market not yet resolved"
        );

        creatorStakes[market] = 0;
        record.active         = false;

        IERC20(collateralToken).safeTransfer(record.creator, stake);
        emit MarketStakeReturned(market, record.creator, stake);
    }

    // ─── Admin ────────────────────────────────────────────────────────────────

    function setConfig(
        uint256 _creationStake,
        uint256 _minDelay,
        uint256 _maxDelay,
        uint256 _defaultMinBet
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        marketCreationStake = _creationStake;
        minResolutionDelay  = _minDelay;
        maxResolutionDelay  = _maxDelay;
        defaultMinBet       = _defaultMinBet;
        emit FactoryConfigUpdated(_creationStake, _minDelay, _maxDelay);
    }

    function setPaused(bool _paused) external onlyRole(PAUSER_ROLE) {
        paused = _paused;
        emit FactoryPaused(_paused);
    }

    // ─── View ──────────────────────────────────────────────────────────────────

    function getMarketsByCategory(string calldata category)
        external view returns (uint256[] memory)
    {
        return categoryMarkets[category];
    }

    function getMarketsByAgent(address agent)
        external view returns (uint256[] memory)
    {
        return agentMarkets[agent];
    }

    function getMarket(uint256 marketId)
        external view returns (MarketRecord memory)
    {
        return markets[marketId];
    }
}
