// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IAgentRegistry {
    enum VerificationTier { UNREGISTERED, REGISTERED, VERIFIED, TRUSTED }
    struct Agent {
        uint256 agentId; address agentAddress; VerificationTier tier;
        uint256 stakedAmount; uint256 reputationScore; uint256 totalResolutions;
        uint256 correctResolutions; uint256 registeredAt; string metadataURI;
        bool slashed; bytes32 storageLogRoot; string kvStreamId;
        uint256 inftTokenId; uint256 researchReportsCount;
    }
    function isVerified(address agent) external view returns (bool);
    function getAgent(address agentAddr) external view returns (Agent memory);
    function getVoteWeight(address agentAddr) external view returns (uint256);
    function addressToAgentId(address) external view returns (uint256);
    function totalVerifiedAgents() external view returns (uint256);
    function recordResolutionParticipation(uint256 agentId, bool correct, bool participated) external;
    function recordResearchReport(bytes32 reportRoot) external;
    function updateStorageRoot(bytes32 newStorageLogRoot, string calldata newKvStreamId) external;
    function linkInft(uint256 inftTokenId) external;
}

interface IPositionToken {
    function mint(address to, address market, uint8 outcomeIndex, uint256 amount) external;
    function burn(address from, address market, uint8 outcomeIndex, uint256 amount) external;
    function getPositionId(address market, uint8 outcomeIndex) external pure returns (uint256);
    function grantMinterRole(address market) external;
}

interface IPredictionMarket {
    enum MarketState { OPEN, RESOLVING, RESOLVED, INVALID }
    function initialize(
        address _registry, address _positionToken, address _resolver,
        address _collateralToken, address _treasury, address _factory,
        bytes32 _questionHash, string calldata _questionURI,
        uint256 _resolutionTime, uint256 _bettingCloseTime,
        uint256 _creatorAgentId, address _creator, uint256 _minBet, string calldata _category
    ) external;
    function state() external view returns (MarketState);
    function resolveMarket(uint8 outcome) external;
    function triggerResolution() external;
    function getMarketSummary() external view returns (
        MarketState, uint256, uint256, uint256, uint256, uint8
    );
}

interface ICollectiveResolver {
    function openVoting(address market, uint256 marketResolutionTime) external;
    function castVerifiedVote(address market, uint8 choice, bytes32 storageLogRoot, bytes calldata teeSignature) external;
    function castVote(address market, uint8 choice) external;
    function finalizeResolution(address market) external;
    function distributeRewards(address market) external;
    function isVotingOpen(address market) external view returns (bool);
    function timeUntilDeadline(address market) external view returns (uint256);
    function notifyRewardReceived(address market, uint256 amount) external;
}
