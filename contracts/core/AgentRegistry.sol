// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/**
 * @title AgentRegistry
 * @notice On-chain identity registry for AI agents.
 *
 *   Each agent mints an ERC-721 AgentID NFT whose tokenURI points to:
 *     - An ERC-8004 agent card (A2A service discovery, AXL endpoints)
 *     - 0G Storage Log root of the agent's intelligence package (iNFT compatible)
 *     - 0G Storage KV stream ID for the agent's live state
 *
 *   The metadataURI is structured JSON stored on 0G Storage and referenced here.
 *   When a 0G iNFT (ERC-7857) is minted for this agent, the iNFT token ID
 *   is recorded in agentInftId[agentId] for cross-contract lookups.
 *
 * Verification Tiers:
 *   UNREGISTERED (0) — not registered
 *   REGISTERED   (1) — 100 PRED stake; can bet
 *   VERIFIED     (2) — 1,000 PRED stake; can create markets + vote
 *   TRUSTED      (3) — governance elevated; 2x reputation multiplier
 */
contract AgentRegistry is ERC721URIStorage, AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ─── Roles ────────────────────────────────────────────────────────────────
    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER_ROLE");
    bytes32 public constant SLASHER_ROLE  = keccak256("SLASHER_ROLE");
    bytes32 public constant MARKET_ROLE   = keccak256("MARKET_ROLE");

    // ─── Tiers ────────────────────────────────────────────────────────────────
    enum VerificationTier { UNREGISTERED, REGISTERED, VERIFIED, TRUSTED }

    // ─── Agent ────────────────────────────────────────────────────────────────
    struct Agent {
        uint256 agentId;
        address agentAddress;
        VerificationTier tier;
        uint256 stakedAmount;
        uint256 reputationScore;     // 0–100
        uint256 totalResolutions;
        uint256 correctResolutions;
        uint256 registeredAt;
        string  metadataURI;         // 0G Storage URI: ERC-8004 card + intelligence root
        bool    slashed;
        // ── 0G Storage integration ────────────────────────────────────────────
        bytes32 storageLogRoot;      // 0G Storage Log root of intelligence package
        string  kvStreamId;          // 0G Storage KV stream ID for live state
        // ── iNFT integration (ERC-7857 on 0G Chain) ──────────────────────────
        uint256 inftTokenId;         // ERC-7857 iNFT token ID (0 = not minted)
        uint256 researchReportsCount;// number of 0G-archived research reports
    }

    // ─── Storage ──────────────────────────────────────────────────────────────
    IERC20  public immutable predToken;
    uint256 public nextAgentId;
    uint256 public totalVerifiedAgents;

    uint256 public minStakeRegistered = 100   * 1e18;
    uint256 public minStakeVerified   = 1_000 * 1e18;
    uint256 public maxReputationScore = 100;

    uint256 public slashPercentage        = 20;
    uint256 public reputationSlashAmount  = 10;
    uint256 public reputationRewardAmount = 5;
    uint256 public reputationAbstainPenalty = 1;

    mapping(address => uint256) public addressToAgentId;
    mapping(uint256 => Agent)   public agents;
    mapping(address => bool)    public isRegistered;

    // ─── Events ───────────────────────────────────────────────────────────────
    event AgentRegistered(uint256 indexed agentId, address indexed agentAddress, string metadataURI);
    event AgentVerified(uint256 indexed agentId, VerificationTier tier);
    event AgentSlashed(uint256 indexed agentId, uint256 slashAmount, string reason);
    event ReputationUpdated(uint256 indexed agentId, uint256 oldScore, uint256 newScore);
    event StakeChanged(uint256 indexed agentId, uint256 newAmount);
    event StorageRootUpdated(uint256 indexed agentId, bytes32 storageLogRoot, string kvStreamId);
    event InftLinked(uint256 indexed agentId, uint256 inftTokenId);
    event ResearchReportRecorded(uint256 indexed agentId, bytes32 reportRoot, uint256 totalReports);

    // ─── Errors ───────────────────────────────────────────────────────────────
    error AlreadyRegistered();
    error InsufficientStake(uint256 provided, uint256 required);
    error AgentNotFound();
    error AgentSlashedError();

    constructor(address _predToken, address _admin)
        ERC721("AgentID", "AGID")
    {
        predToken = IERC20(_predToken);
        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(VERIFIER_ROLE, _admin);
        _grantRole(SLASHER_ROLE, _admin);
        nextAgentId = 1;
    }

    // ─── Registration ─────────────────────────────────────────────────────────

    /**
     * @notice Register an AI agent.
     * @param metadataURI   0G Storage URI of ERC-8004 agent card JSON
     * @param stakeAmount   PRED tokens to stake
     * @param kvStreamId    0G Storage KV stream ID for live agent state
     */
    function register(
        string  calldata metadataURI,
        uint256 stakeAmount,
        string  calldata kvStreamId
    ) external nonReentrant returns (uint256 agentId) {
        if (isRegistered[msg.sender]) revert AlreadyRegistered();
        if (stakeAmount < minStakeRegistered)
            revert InsufficientStake(stakeAmount, minStakeRegistered);

        predToken.safeTransferFrom(msg.sender, address(this), stakeAmount);

        agentId = nextAgentId++;
        isRegistered[msg.sender] = true;
        addressToAgentId[msg.sender] = agentId;

        VerificationTier tier = stakeAmount >= minStakeVerified
            ? VerificationTier.VERIFIED
            : VerificationTier.REGISTERED;

        if (tier == VerificationTier.VERIFIED) totalVerifiedAgents++;

        agents[agentId] = Agent({
            agentId:              agentId,
            agentAddress:         msg.sender,
            tier:                 tier,
            stakedAmount:         stakeAmount,
            reputationScore:      50,
            totalResolutions:     0,
            correctResolutions:   0,
            registeredAt:         block.timestamp,
            metadataURI:          metadataURI,
            slashed:              false,
            storageLogRoot:       bytes32(0),
            kvStreamId:           kvStreamId,
            inftTokenId:          0,
            researchReportsCount: 0
        });

        _mint(msg.sender, agentId);
        _setTokenURI(agentId, metadataURI);

        emit AgentRegistered(agentId, msg.sender, metadataURI);
        if (tier == VerificationTier.VERIFIED) emit AgentVerified(agentId, tier);
    }

    // ─── 0G Storage updates ───────────────────────────────────────────────────

    /**
     * @notice Update the agent's 0G Storage Log root (called after archiving research or updating intelligence).
     */
    function updateStorageRoot(bytes32 newStorageLogRoot, string calldata newKvStreamId)
        external
    {
        require(isRegistered[msg.sender], "Not registered");
        uint256 agentId = addressToAgentId[msg.sender];
        Agent storage agent = agents[agentId];
        agent.storageLogRoot = newStorageLogRoot;
        if (bytes(newKvStreamId).length > 0) agent.kvStreamId = newKvStreamId;
        emit StorageRootUpdated(agentId, newStorageLogRoot, newKvStreamId);
    }

    /**
     * @notice Record a new research report (increments counter, updates Log root).
     *         Called by the agent after archiving a research report to 0G Storage Log.
     */
    function recordResearchReport(bytes32 reportRoot) external {
        require(isRegistered[msg.sender], "Not registered");
        uint256 agentId = addressToAgentId[msg.sender];
        Agent storage agent = agents[agentId];
        agent.storageLogRoot        = reportRoot;
        agent.researchReportsCount += 1;
        emit ResearchReportRecorded(agentId, reportRoot, agent.researchReportsCount);
    }

    /**
     * @notice Link a minted ERC-7857 iNFT token to this agent.
     *         Called by the agent after minting on 0G Chain.
     */
    function linkInft(uint256 inftTokenId) external {
        require(isRegistered[msg.sender], "Not registered");
        uint256 agentId = addressToAgentId[msg.sender];
        agents[agentId].inftTokenId = inftTokenId;
        emit InftLinked(agentId, inftTokenId);
    }

    // ─── Stake management ─────────────────────────────────────────────────────

    function increaseStake(uint256 amount) external nonReentrant {
        if (!isRegistered[msg.sender]) revert AgentNotFound();
        uint256 agentId = addressToAgentId[msg.sender];
        Agent storage agent = agents[agentId];
        if (agent.slashed) revert AgentSlashedError();

        predToken.safeTransferFrom(msg.sender, address(this), amount);
        agent.stakedAmount += amount;

        if (agent.tier == VerificationTier.REGISTERED && agent.stakedAmount >= minStakeVerified) {
            agent.tier = VerificationTier.VERIFIED;
            totalVerifiedAgents++;
            emit AgentVerified(agentId, VerificationTier.VERIFIED);
        }
        emit StakeChanged(agentId, agent.stakedAmount);
    }

    function withdrawStake(uint256 amount) external nonReentrant {
        if (!isRegistered[msg.sender]) revert AgentNotFound();
        uint256 agentId = addressToAgentId[msg.sender];
        Agent storage agent = agents[agentId];
        if (agent.slashed) revert AgentSlashedError();

        uint256 minRequired = agent.tier >= VerificationTier.VERIFIED
            ? minStakeVerified : minStakeRegistered;
        require(agent.stakedAmount - amount >= minRequired, "Below minimum stake");

        agent.stakedAmount -= amount;
        if (agent.tier == VerificationTier.VERIFIED && agent.stakedAmount < minStakeVerified) {
            agent.tier = VerificationTier.REGISTERED;
            totalVerifiedAgents--;
            emit AgentVerified(agentId, VerificationTier.REGISTERED);
        }
        predToken.safeTransfer(msg.sender, amount);
        emit StakeChanged(agentId, agent.stakedAmount);
    }

    // ─── Reputation (called by CollectiveResolver via MARKET_ROLE) ────────────

    function recordResolutionParticipation(uint256 agentId, bool correct, bool participated)
        external onlyRole(MARKET_ROLE)
    {
        Agent storage agent = agents[agentId];
        uint256 old = agent.reputationScore;
        agent.totalResolutions++;
        if (!participated) {
            agent.reputationScore = old > reputationAbstainPenalty ? old - reputationAbstainPenalty : 0;
        } else if (correct) {
            agent.correctResolutions++;
            uint256 newScore = old + reputationRewardAmount;
            agent.reputationScore = newScore > maxReputationScore ? maxReputationScore : newScore;
        } else {
            agent.reputationScore = old > reputationSlashAmount ? old - reputationSlashAmount : 0;
        }
        emit ReputationUpdated(agentId, old, agent.reputationScore);
    }

    // ─── Slashing ─────────────────────────────────────────────────────────────

    function slash(uint256 agentId, string calldata reason) external onlyRole(SLASHER_ROLE) {
        Agent storage agent = agents[agentId];
        require(agent.agentId != 0, "Agent not found");
        uint256 slashAmount = (agent.stakedAmount * slashPercentage) / 100;
        agent.stakedAmount  -= slashAmount;
        agent.reputationScore = 0;
        agent.slashed         = true;
        if (agent.tier >= VerificationTier.VERIFIED) totalVerifiedAgents--;
        agent.tier = VerificationTier.REGISTERED;
        predToken.safeTransfer(msg.sender, slashAmount); // to treasury / caller
        emit AgentSlashed(agentId, slashAmount, reason);
    }

    // ─── Admin ────────────────────────────────────────────────────────────────

    function elevateToTrusted(uint256 agentId) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(agents[agentId].tier == VerificationTier.VERIFIED, "Must be VERIFIED");
        agents[agentId].tier = VerificationTier.TRUSTED;
        emit AgentVerified(agentId, VerificationTier.TRUSTED);
    }

    function setMinStake(uint256 _registered, uint256 _verified)
        external onlyRole(DEFAULT_ADMIN_ROLE)
    {
        require(_verified > _registered, "Verified must exceed registered");
        minStakeRegistered = _registered;
        minStakeVerified   = _verified;
    }

    // ─── View ─────────────────────────────────────────────────────────────────

    function isVerified(address agentAddr) external view returns (bool) {
        if (!isRegistered[agentAddr]) return false;
        uint256 id = addressToAgentId[agentAddr];
        return agents[id].tier >= VerificationTier.VERIFIED && !agents[id].slashed;
    }

    function getAgent(address agentAddr) external view returns (Agent memory) {
        return agents[addressToAgentId[agentAddr]];
    }

    function getAgentById(uint256 agentId) external view returns (Agent memory) {
        return agents[agentId];
    }

    /**
     * @notice Vote weight formula:
     *   weight = (stakedAmount / 1e18) × (reputationScore / 50)
     *   Neutral rep → 1x. Max rep → 2x. Zero rep → cannot vote.
     */
    function getVoteWeight(address agentAddr) external view returns (uint256) {
        if (!isRegistered[agentAddr]) return 0;
        Agent storage a = agents[addressToAgentId[agentAddr]];
        if (a.slashed || a.tier < VerificationTier.VERIFIED) return 0;
        return (a.stakedAmount / 1e18) * a.reputationScore / 50;
    }

    function supportsInterface(bytes4 interfaceId)
        public view override(ERC721URIStorage, AccessControl)
        returns (bool)
    { return super.supportsInterface(interfaceId); }
}
