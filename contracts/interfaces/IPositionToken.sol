// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IPositionToken {
    function mint(address to, address market, uint8 outcomeIndex, uint256 amount) external;
    function burn(address from, address market, uint8 outcomeIndex, uint256 amount) external;
    function getPositionId(address market, uint8 outcomeIndex) external pure returns (uint256);
    function grantMinterRole(address market) external;
}

