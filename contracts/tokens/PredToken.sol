// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";

/**
 * @title PredToken
 * @notice Native ERC-20 collateral token for the prediction market platform.
 *         Used as:
 *           - Stake to register/verify agents
 *           - Collateral for placing bets
 *           - Resolver reward currency
 *
 *         In production, this can be replaced by USDC or any ERC-20.
 *         The MINTER_ROLE is granted to an initial distributor / faucet.
 */
contract PredToken is ERC20, AccessControl {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    uint256 public constant MAX_SUPPLY = 1_000_000_000 * 1e18; // 1B PRED
    uint256 public totalMinted;

    event TokensMinted(address indexed to, uint256 amount);

    constructor(address admin, address initialHolder) ERC20("Prediction Token", "PRED") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(MINTER_ROLE, admin);
        // Initial liquidity / team allocation
        _mint(initialHolder, 100_000_000 * 1e18); // 100M to initial holder
        totalMinted = 100_000_000 * 1e18;
    }

    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        require(totalMinted + amount <= MAX_SUPPLY, "PredToken: exceeds max supply");
        totalMinted += amount;
        _mint(to, amount);
        emit TokensMinted(to, amount);
    }

    function supportsInterface(bytes4 interfaceId)
        public view override(AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}
