// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IPredictionMarket {
    enum MarketState { OPEN, RESOLVING, RESOLVED, INVALID }

    function initialize(
        address _registry,
        address _positionToken,
        address _resolver,
        address _collateralToken,
        address _treasury,
        address _factory,
        bytes32 _questionHash,
        string calldata _questionURI,
        uint256 _resolutionTime,
        uint256 _bettingCloseTime,
        uint256 _creatorAgentId,
        address _creator,
        uint256 _minBet,
        string calldata _category
    ) external;

    function state() external view returns (MarketState);
    function resolveMarket(uint8 outcome) external;
    function triggerResolution() external;
    function getMarketSummary() external view returns (
        MarketState,
        uint256,
        uint256,
        uint256,
        uint256,
        uint8
    );
}

