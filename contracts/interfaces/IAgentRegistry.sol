// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

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
        string metadataURI;
        bool slashed;
        bytes32 storageLogRoot;
        string kvStreamId;
        uint256 inftTokenId;
        uint256 researchReportsCount;
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

