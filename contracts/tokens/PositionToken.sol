// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";

/**
 * @title PositionToken
 * @notice ERC-1155 multi-token representing YES / NO outcome positions.
 *         Inspired by the Gnosis Conditional Tokens Framework (CTF).
 *
 *         Token ID derivation (deterministic & gas-efficient):
 *           positionId = keccak256(abi.encodePacked(marketAddress, outcomeIndex))
 *           where outcomeIndex: 1 = YES, 0 = NO
 *
 *         This means any contract can derive the token ID offline without
 *         querying state, enabling efficient off-chain indexing by AI agents.
 *
 *         Only MINTER_ROLE (granted to PredictionMarket contracts by the Factory)
 *         can mint or burn position tokens.
 */
contract PositionToken is ERC1155, AccessControl {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    // Human-readable outcome labels for UIs
    mapping(uint256 => string) public positionLabel;

    event PositionMinted(
        address indexed market,
        address indexed to,
        uint256 indexed positionId,
        uint256 amount,
        uint8   outcomeIndex
    );
    event PositionBurned(
        address indexed market,
        address indexed from,
        uint256 indexed positionId,
        uint256 amount
    );

    constructor(address admin)
        ERC1155("https://pred.market/api/position/{id}.json")
    {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    // ─── Position ID Derivation ───────────────────────────────────────────────

    /**
     * @notice Compute the ERC-1155 token ID for a given market outcome.
     * @param market       Address of the PredictionMarket contract
     * @param outcomeIndex 1 = YES, 0 = NO
     */
    function getPositionId(address market, uint8 outcomeIndex)
        public pure returns (uint256)
    {
        return uint256(keccak256(abi.encodePacked(market, outcomeIndex)));
    }

    // ─── Mint / Burn ──────────────────────────────────────────────────────────

    function mint(
        address to,
        address market,
        uint8   outcomeIndex,
        uint256 amount
    ) external onlyRole(MINTER_ROLE) {
        uint256 positionId = getPositionId(market, outcomeIndex);
        _mint(to, positionId, amount, "");

        emit PositionMinted(market, to, positionId, amount, outcomeIndex);
    }

    function burn(
        address from,
        address market,
        uint8   outcomeIndex,
        uint256 amount
    ) external onlyRole(MINTER_ROLE) {
        uint256 positionId = getPositionId(market, outcomeIndex);
        _burn(from, positionId, amount);

        emit PositionBurned(market, from, positionId, amount);
    }

    // ─── Batch mint for gas efficiency ───────────────────────────────────────

    function mintBatch(
        address   to,
        address   market,
        uint256[] calldata amounts // [noAmount, yesAmount] → indices [0, 1]
    ) external onlyRole(MINTER_ROLE) {
        require(amounts.length == 2, "PositionToken: must provide exactly 2 outcomes");
        uint256[] memory ids = new uint256[](2);
        ids[0] = getPositionId(market, 0); // NO
        ids[1] = getPositionId(market, 1); // YES
        _mintBatch(to, ids, amounts, "");
    }

    // ─── Role grant helper (called by Factory when deploying markets) ─────────

    function grantMinterRole(address market) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _grantRole(MINTER_ROLE, market);
    }

    function revokeMinterRole(address market) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _revokeRole(MINTER_ROLE, market);
    }

    function supportsInterface(bytes4 interfaceId)
        public view override(ERC1155, AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}
