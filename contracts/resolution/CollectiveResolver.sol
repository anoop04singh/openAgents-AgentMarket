// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface IAgentRegistry {
    enum VerificationTier { UNREGISTERED, REGISTERED, VERIFIED, TRUSTED }
    struct Agent {
        uint256 agentId;
        address agentAddress;
        VerificationTier tier;
        uint256 stakedAmount;
        uint256 reputationScore;
        uint256 totalResolutions;
        uint256 correctResolutions;
        uint256 registeredAt;
        string  metadataURI;
        bool    slashed;
    }
    function isVerified(address agent) external view returns (bool);
    function getAgent(address agentAddr) external view returns (Agent memory);
    function getVoteWeight(address agentAddr) external view returns (uint256);
    function totalVerifiedAgents() external view returns (uint256);
    function recordResolutionParticipation(uint256 agentId, bool correct, bool participated) external;
}

interface IPredictionMarket {
    enum MarketState { OPEN, RESOLVING, RESOLVED, INVALID }
    function state() external view returns (MarketState);
    function resolveMarket(uint8 outcome) external;
}

/**
 * @title CollectiveResolver
 * @notice Schelling-point resolution engine with Proof-of-AI-Research (PoIR).
 *
 * PoIR fields on every vote:
 *   storageLogRoot  — 0G Storage Log merkle root of the agent's research report
 *   teeSignature    — 0G Compute TEE signature proving an LLM ran on the question
 *
 * Both fields are OPTIONAL during the hackathon demo (requirePoIR flag).
 * When enabled, votes without valid PoIR are rejected on-chain.
 *
 * Resolution flow:
 *   1. PredictionMarket.triggerResolution() → openVoting()
 *   2. 48h window: agents castVerifiedVote(market, choice, storageRoot, teeSig)
 *   3. finalizeResolution() — quorum check, majority wins, callback to market
 *   4. distributeRewards() — 0.5% pool to majority voters proportional to weight
 *   5. Reputation updated: +5 correct, -10 wrong, -1 abstain
 */
contract CollectiveResolver is ReentrancyGuard, AccessControl {
    using SafeERC20 for IERC20;

    // ─── Constants ────────────────────────────────────────────────────────────
    uint256 public constant VOTING_WINDOW      = 48 hours;
    uint256 public constant EXTENSION_PERIOD   = 24 hours;
    uint256 public constant MAX_EXTENSIONS     = 3;
    uint256 public constant MIN_QUORUM_COUNT   = 3;
    uint256 public constant MIN_QUORUM_PERCENT = 20;

    uint8 public constant VOTE_NO      = 0;
    uint8 public constant VOTE_YES     = 1;
    uint8 public constant VOTE_INVALID = 2;

    // ─── Roles ────────────────────────────────────────────────────────────────
    bytes32 public constant MARKET_ROLE = keccak256("MARKET_ROLE");

    // ─── PoIR config ──────────────────────────────────────────────────────────
    bool public requirePoIR = false; // toggled true for full verification

    // ─── State ────────────────────────────────────────────────────────────────
    enum ResolutionState { NONE, VOTING, EXTENDED, FINALIZED, FAILED }

    struct ResolutionSession {
        address market;
        uint256 marketResolutionTime;
        uint256 votingDeadline;
        uint256 extensions;
        ResolutionState state;
        uint256 weightedYes;
        uint256 weightedNo;
        uint256 weightedInvalid;
        uint256 voterCount;
        uint8   finalOutcome;
        bool    finalized;
        uint256 rewardPool;
        bool    rewardDistributed;
    }

    /// @dev Core vote struct — PoIR fields included.
    struct Vote {
        uint8   choice;
        uint256 weight;
        bool    cast;
        bool    rewarded;
        // ── Proof-of-AI-Research ──────────────────────────────────
        bytes32 storageLogRoot;  // 0G Storage Log merkle root (research report)
        bytes   teeSignature;    // 0G Compute TEE signature (LLM ran on this question)
        bool    hasPoIR;         // true when both fields are non-empty
    }

    IAgentRegistry public registry;
    IERC20          public rewardToken;

    mapping(address => ResolutionSession) public sessions;
    mapping(address => mapping(address => Vote)) public votes;
    mapping(address => address[]) public sessionVoters;

    address[] public activeSessions;
    mapping(address => uint256) public activeSessionIndex;

    // ─── Events ───────────────────────────────────────────────────────────────
    event VotingOpened(address indexed market, uint256 deadline, uint256 totalVerifiedAgents);
    event VoteCast(
        address indexed market,
        address indexed voter,
        uint8   choice,
        uint256 weight,
        bool    hasPoIR,
        bytes32 storageLogRoot
    );
    event VotingExtended(address indexed market, uint256 newDeadline, uint256 extensionNum);
    event ResolutionFinalized(address indexed market, uint8 outcome, uint256 yesWeight, uint256 noWeight);
    event ResolutionFailed(address indexed market, string reason);
    event RewardDistributed(address indexed market, address indexed voter, uint256 amount);
    event PoIRToggled(bool required);

    // ─── Errors ───────────────────────────────────────────────────────────────
    error SessionNotOpen();
    error AlreadyVoted();
    error VotingWindowNotClosed();
    error NotVerifiedAgent();
    error SessionNotFound();
    error ZeroWeight();
    error AlreadyFinalized();
    error PoIRRequired();

    constructor(address _registry, address _rewardToken, address _admin) {
        registry    = IAgentRegistry(_registry);
        rewardToken = IERC20(_rewardToken);
        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(MARKET_ROLE, _admin);
    }

    // ─── Called by PredictionMarket ───────────────────────────────────────────

    function openVoting(address market, uint256 marketResolutionTime) external {
        require(
            msg.sender == market || hasRole(MARKET_ROLE, msg.sender),
            "CollectiveResolver: unauthorized"
        );
        ResolutionSession storage session = sessions[market];
        require(session.state == ResolutionState.NONE, "Session exists");

        uint256 deadline = block.timestamp + VOTING_WINDOW;
        sessions[market] = ResolutionSession({
            market:               market,
            marketResolutionTime: marketResolutionTime,
            votingDeadline:       deadline,
            extensions:           0,
            state:                ResolutionState.VOTING,
            weightedYes:          0,
            weightedNo:           0,
            weightedInvalid:      0,
            voterCount:           0,
            finalOutcome:         0,
            finalized:            false,
            rewardPool:           0,
            rewardDistributed:    false
        });

        activeSessionIndex[market] = activeSessions.length;
        activeSessions.push(market);

        emit VotingOpened(market, deadline, registry.totalVerifiedAgents());
    }

    // ─── Voting ───────────────────────────────────────────────────────────────

    /**
     * @notice Cast a resolution vote with optional Proof-of-AI-Research.
     * @param market         PredictionMarket address
     * @param choice         0=NO, 1=YES, 2=INVALID
     * @param storageLogRoot 0G Storage Log merkle root of research report
     * @param teeSignature   0G Compute TEE signature (bytes(0) if not using PoIR)
     */
    function castVerifiedVote(
        address market,
        uint8   choice,
        bytes32 storageLogRoot,
        bytes   calldata teeSignature
    ) external nonReentrant {
        if (!registry.isVerified(msg.sender)) revert NotVerifiedAgent();

        ResolutionSession storage session = sessions[market];
        if (session.state != ResolutionState.VOTING &&
            session.state != ResolutionState.EXTENDED)
            revert SessionNotOpen();

        require(block.timestamp <= session.votingDeadline, "Voting closed");
        if (votes[market][msg.sender].cast) revert AlreadyVoted();
        require(choice <= 2, "Invalid choice");

        bool hasPoIR = storageLogRoot != bytes32(0) && teeSignature.length > 0;

        // Reject votes without PoIR if enforcement is enabled
        if (requirePoIR && !hasPoIR) revert PoIRRequired();

        uint256 weight = registry.getVoteWeight(msg.sender);
        if (weight == 0) revert ZeroWeight();

        // Votes WITH PoIR get a 20% weight bonus (incentivises proper research)
        uint256 effectiveWeight = hasPoIR ? (weight * 120) / 100 : weight;

        votes[market][msg.sender] = Vote({
            choice:         choice,
            weight:         effectiveWeight,
            cast:           true,
            rewarded:       false,
            storageLogRoot: storageLogRoot,
            teeSignature:   teeSignature,
            hasPoIR:        hasPoIR
        });

        session.voterCount++;
        sessionVoters[market].push(msg.sender);

        if (choice == VOTE_YES)     session.weightedYes     += effectiveWeight;
        else if (choice == VOTE_NO) session.weightedNo      += effectiveWeight;
        else                        session.weightedInvalid += effectiveWeight;

        emit VoteCast(market, msg.sender, choice, effectiveWeight, hasPoIR, storageLogRoot);
    }

    /// @notice Legacy alias — votes without PoIR. Works unless requirePoIR=true.
    function castVote(address market, uint8 choice) external {
        this.castVerifiedVote(market, choice, bytes32(0), "");
    }

    // ─── Finalization ─────────────────────────────────────────────────────────

    function finalizeResolution(address market) external nonReentrant {
        ResolutionSession storage session = sessions[market];
        if (session.market == address(0)) revert SessionNotFound();
        if (session.finalized) revert AlreadyFinalized();
        require(block.timestamp > session.votingDeadline, "Voting still open");

        bool quorumMet = _checkQuorum(session);

        if (!quorumMet) {
            if (session.extensions < MAX_EXTENSIONS) {
                session.extensions++;
                session.votingDeadline = block.timestamp + EXTENSION_PERIOD;
                session.state = ResolutionState.EXTENDED;
                emit VotingExtended(market, session.votingDeadline, session.extensions);
                return;
            } else {
                session.state     = ResolutionState.FAILED;
                session.finalized = true;
                _updateReputationAll(market, VOTE_INVALID, false);
                IPredictionMarket(market).resolveMarket(VOTE_INVALID);
                emit ResolutionFailed(market, "No quorum after max extensions");
                _removeActiveSession(market);
                return;
            }
        }

        uint8 winningOutcome = _determineOutcome(session);
        session.finalOutcome = winningOutcome;
        session.finalized    = true;
        session.state        = ResolutionState.FINALIZED;

        _updateReputationAll(market, winningOutcome, true);
        IPredictionMarket(market).resolveMarket(winningOutcome);

        emit ResolutionFinalized(market, winningOutcome, session.weightedYes, session.weightedNo);
        _removeActiveSession(market);
    }

    function distributeRewards(address market) external nonReentrant {
        ResolutionSession storage session = sessions[market];
        require(session.finalized, "Not finalized");
        require(session.rewardPool > 0, "No rewards");
        require(!session.rewardDistributed, "Already distributed");

        session.rewardDistributed = true;
        uint8    winner      = session.finalOutcome;
        uint256  totalWeight = _getMajorityWeight(session, winner);
        uint256  pool        = session.rewardPool;
        address[] memory voters = sessionVoters[market];

        for (uint256 i = 0; i < voters.length; i++) {
            address voter = voters[i];
            Vote storage v = votes[market][voter];
            if (!v.cast || v.rewarded || v.choice != winner) continue;
            uint256 share = (v.weight * pool) / totalWeight;
            if (share == 0) continue;
            v.rewarded = true;
            rewardToken.safeTransfer(voter, share);
            emit RewardDistributed(market, voter, share);
        }
    }

    /// @notice Receive reward pool from resolved market (called by market after safeTransfer)
    function notifyRewardReceived(address market, uint256 amount) external {
        require(msg.sender == market, "Only market");
        sessions[market].rewardPool += amount;
    }

    // ─── Admin ────────────────────────────────────────────────────────────────

    function setRequirePoIR(bool _require) external onlyRole(DEFAULT_ADMIN_ROLE) {
        requirePoIR = _require;
        emit PoIRToggled(_require);
    }

    // ─── Internal ─────────────────────────────────────────────────────────────

    function _checkQuorum(ResolutionSession storage session) internal view returns (bool) {
        uint256 totalVerified = registry.totalVerifiedAgents();
        uint256 required      = (totalVerified * MIN_QUORUM_PERCENT) / 100;
        if (required < MIN_QUORUM_COUNT) required = MIN_QUORUM_COUNT;
        return session.voterCount >= required;
    }

    function _determineOutcome(ResolutionSession storage session) internal view returns (uint8) {
        uint256 maxW    = session.weightedYes;
        uint8   outcome = VOTE_YES;
        if (session.weightedNo      > maxW) { maxW = session.weightedNo;      outcome = VOTE_NO;      }
        if (session.weightedInvalid > maxW) {                                  outcome = VOTE_INVALID; }
        return outcome;
    }

    function _getMajorityWeight(ResolutionSession storage session, uint8 winner)
        internal view returns (uint256)
    {
        if (winner == VOTE_YES) return session.weightedYes;
        if (winner == VOTE_NO)  return session.weightedNo;
        return session.weightedInvalid;
    }

    function _updateReputationAll(address market, uint8 winningOutcome, bool hasMajority) internal {
        address[] memory voters = sessionVoters[market];
        for (uint256 i = 0; i < voters.length; i++) {
            Vote storage v = votes[market][voters[i]];
            if (!v.cast) continue;
            IAgentRegistry.Agent memory agent = registry.getAgent(voters[i]);
            bool correct = hasMajority && v.choice == winningOutcome;
            registry.recordResolutionParticipation(agent.agentId, correct, true);
        }
    }

    function _removeActiveSession(address market) internal {
        uint256 idx  = activeSessionIndex[market];
        uint256 last = activeSessions.length - 1;
        if (idx < last) {
            address lastM              = activeSessions[last];
            activeSessions[idx]        = lastM;
            activeSessionIndex[lastM]  = idx;
        }
        activeSessions.pop();
        delete activeSessionIndex[market];
    }

    // ─── View ─────────────────────────────────────────────────────────────────

    function getSession(address market) external view returns (ResolutionSession memory) { return sessions[market]; }
    function getVote(address market, address voter) external view returns (Vote memory) { return votes[market][voter]; }
    function getActiveSessions() external view returns (address[] memory) { return activeSessions; }
    function isVotingOpen(address market) external view returns (bool) {
        ResolutionSession storage s = sessions[market];
        return (s.state == ResolutionState.VOTING || s.state == ResolutionState.EXTENDED)
            && block.timestamp <= s.votingDeadline;
    }
    function timeUntilDeadline(address market) external view returns (uint256) {
        ResolutionSession storage s = sessions[market];
        if (block.timestamp >= s.votingDeadline) return 0;
        return s.votingDeadline - block.timestamp;
    }
    function getVoteProbabilities(address market)
        external view returns (uint256 yesBps, uint256 noBps, uint256 invalidBps)
    {
        ResolutionSession storage s = sessions[market];
        uint256 total = s.weightedYes + s.weightedNo + s.weightedInvalid;
        if (total == 0) return (3333, 3333, 3334);
        yesBps     = (s.weightedYes     * 10_000) / total;
        noBps      = (s.weightedNo      * 10_000) / total;
        invalidBps = (s.weightedInvalid * 10_000) / total;
    }
}
