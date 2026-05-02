// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

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

