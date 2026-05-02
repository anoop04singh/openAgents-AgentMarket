// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../contracts/tokens/PredToken.sol";
import "../contracts/tokens/PositionToken.sol";
import "../contracts/core/AgentRegistry.sol";
import "../contracts/core/PredictionMarket.sol";
import "../contracts/core/MarketFactory.sol";
import "../contracts/resolution/CollectiveResolver.sol";

/**
 * @title Deploy
 * @notice One-command deploy for all AgentMarket contracts.
 *
 * Usage (Sepolia):
 *   forge script scripts/Deploy.s.sol:Deploy \
 *     --rpc-url $SEPOLIA_RPC --broadcast --verify --etherscan-api-key $ETHERSCAN_KEY
 *
 * Usage (0G Galileo testnet):
 *   forge script scripts/Deploy.s.sol:Deploy \
 *     --rpc-url https://evmrpc-testnet.0g.ai --broadcast
 *
 * Env vars:
 *   PRIVATE_KEY       — deployer hex key
 *   TREASURY_ADDRESS  — optional, defaults to deployer
 */
contract Deploy is Script {
    function run() external {
        uint256 pk       = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(pk);
        address treasury = vm.envOr("TREASURY_ADDRESS", deployer);

        vm.startBroadcast(pk);

        PredToken         pred      = new PredToken(deployer, deployer);
        PositionToken     posToken  = new PositionToken(deployer);
        AgentRegistry     registry  = new AgentRegistry(address(pred), deployer);
        PredictionMarket  marketImpl = new PredictionMarket();
        CollectiveResolver resolver  = new CollectiveResolver(address(registry), address(pred), deployer);
        MarketFactory     factory   = new MarketFactory(
            address(marketImpl), address(registry), address(posToken),
            address(resolver), address(pred), treasury, deployer
        );

        // Wire roles
        registry.grantRole(keccak256("MARKET_ROLE"), address(resolver));
        posToken.grantRole(bytes32(0), address(factory));
        resolver.grantRole(keccak256("MARKET_ROLE"), address(factory));

        // Initial faucet supply
        pred.mint(deployer, 10_000_000 * 1e18);

        vm.stopBroadcast();

        // Write addresses.json
        string memory json = string.concat(
            '{\n  "chainId": ', vm.toString(block.chainid), ',\n',
            '  "PredToken": "',          vm.toString(address(pred)),       '",\n',
            '  "PositionToken": "',      vm.toString(address(posToken)),   '",\n',
            '  "AgentRegistry": "',      vm.toString(address(registry)),   '",\n',
            '  "MarketImpl": "',         vm.toString(address(marketImpl)), '",\n',
            '  "CollectiveResolver": "', vm.toString(address(resolver)),   '",\n',
            '  "MarketFactory": "',      vm.toString(address(factory)),    '"\n}'
        );
        vm.writeFile("deployments/addresses.json", json);

        console.log("=== Deploy complete ===");
        console.log("PredToken          :", address(pred));
        console.log("PositionToken      :", address(posToken));
        console.log("AgentRegistry      :", address(registry));
        console.log("MarketImpl         :", address(marketImpl));
        console.log("CollectiveResolver :", address(resolver));
        console.log("MarketFactory      :", address(factory));
        console.log("Written: deployments/addresses.json");
    }
}
