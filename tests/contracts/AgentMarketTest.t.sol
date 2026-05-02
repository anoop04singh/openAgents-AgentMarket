// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "forge-std/console.sol";
import "@openzeppelin/contracts/proxy/Clones.sol";

import "../../contracts/tokens/PredToken.sol";
import "../../contracts/tokens/PositionToken.sol";
import "../../contracts/core/AgentRegistry.sol";
import "../../contracts/core/PredictionMarket.sol";
import "../../contracts/core/MarketFactory.sol";
import "../../contracts/resolution/CollectiveResolver.sol";

/**
 * @title AgentMarketTest
 * @notice Full foundry test suite.
 *
 * Run:
 *   forge test -vv                          (all tests)
 *   forge test --match-test testFullFlow -vvv (single test verbose)
 *   forge test --gas-report                  (gas usage)
 */
contract AgentMarketTest is Test {

    // ─── Contracts ────────────────────────────────────────────────────────────
    PredToken         pred;
    PositionToken     posToken;
    AgentRegistry     registry;
    PredictionMarket  marketImpl;
    CollectiveResolver resolver;
    MarketFactory     factory;

    // ─── Actors ───────────────────────────────────────────────────────────────
    address admin    = address(0xA0);
    address treasury = address(0xA1);
    address agentA   = address(0xB1);   // market creator
    address agentB   = address(0xB2);   // bettor YES
    address agentC   = address(0xB3);   // bettor NO + resolver
    address agentD   = address(0xB4);   // resolver

    uint256 constant STAKE    = 1_000 * 1e18;
    uint256 constant BET_SIZE =   100 * 1e18;
    uint256 constant CREATION_STAKE = 500 * 1e18;

    // ─── Setup ────────────────────────────────────────────────────────────────

    function setUp() public {
        vm.startPrank(admin);

        pred      = new PredToken(admin, admin);
        posToken  = new PositionToken(admin);
        registry  = new AgentRegistry(address(pred), admin);
        marketImpl = new PredictionMarket();
        resolver  = new CollectiveResolver(address(registry), address(pred), admin);
        factory   = new MarketFactory(
            address(marketImpl), address(registry), address(posToken),
            address(resolver), address(pred), treasury, admin
        );

        // Wire roles
        registry.grantRole(keccak256("MARKET_ROLE"), address(resolver));
        posToken.grantRole(bytes32(0), address(factory));
        resolver.grantRole(keccak256("MARKET_ROLE"), address(factory));

        // Fund agents
        uint256 agentFunding = 10_000 * 1e18;
        pred.mint(agentA, agentFunding);
        pred.mint(agentB, agentFunding);
        pred.mint(agentC, agentFunding);
        pred.mint(agentD, agentFunding);

        vm.stopPrank();
    }

    // ─── Helpers ──────────────────────────────────────────────────────────────

    function _registerAgent(address agent) internal returns (uint256 agentId) {
        vm.startPrank(agent);
        pred.approve(address(registry), STAKE);
        registry.register("0g://agent-card-root", STAKE, "kv-stream-id");
        agentId = registry.addressToAgentId(agent);
        vm.stopPrank();
    }

    function _createMarket(address creator) internal returns (address market) {
        vm.startPrank(creator);
        pred.approve(address(factory), CREATION_STAKE);
        market = factory.createMarket(
            "0g://question-root",
            block.timestamp + 1 days,
            "crypto",
            1e18
        );
        vm.stopPrank();
    }

    function _bet(address bettor, address market, uint8 outcome, uint256 amount) internal {
        vm.startPrank(bettor);
        pred.approve(market, amount);
        PredictionMarket(market).bet(outcome, amount);
        vm.stopPrank();
    }

    // ─── Tests ────────────────────────────────────────────────────────────────

    // ── Registration ──────────────────────────────────────────────────────────

    function testRegisterAgent_Success() public {
        _registerAgent(agentA);

        assertTrue(registry.isVerified(agentA));
        IAgentRegistry.Agent memory agent = registry.getAgent(agentA);
        assertEq(agent.tier, uint8(IAgentRegistry.VerificationTier.VERIFIED));
        assertEq(agent.reputationScore, 50);
        assertEq(agent.stakedAmount, STAKE);
    }

    function testRegisterAgent_InsufficientStake() public {
        vm.startPrank(agentA);
        pred.approve(address(registry), 50e18);
        vm.expectRevert();
        registry.register("0g://card", 50e18, "kv-id");
        vm.stopPrank();
    }

    function testRegisterAgent_CannotRegisterTwice() public {
        _registerAgent(agentA);
        vm.startPrank(agentA);
        pred.approve(address(registry), STAKE);
        vm.expectRevert();
        registry.register("0g://card2", STAKE, "kv-id2");
        vm.stopPrank();
    }

    function testRegisterAgent_ERC721Minted() public {
        _registerAgent(agentA);
        uint256 id = registry.addressToAgentId(agentA);
        assertEq(registry.ownerOf(id), agentA);
    }

    function test0GStorageRootUpdate() public {
        _registerAgent(agentA);
        bytes32 newRoot = keccak256("research-report");
        vm.prank(agentA);
        registry.updateStorageRoot(newRoot, "new-kv-stream");
        IAgentRegistry.Agent memory agent = registry.getAgent(agentA);
        assertEq(agent.storageLogRoot, newRoot);
    }

    function testLinkInft() public {
        _registerAgent(agentA);
        vm.prank(agentA);
        registry.linkInft(42);
        IAgentRegistry.Agent memory agent = registry.getAgent(agentA);
        assertEq(agent.inftTokenId, 42);
    }

    function testRecordResearchReport() public {
        _registerAgent(agentA);
        bytes32 root = keccak256("report-1");
        vm.prank(agentA);
        registry.recordResearchReport(root);
        IAgentRegistry.Agent memory agent = registry.getAgent(agentA);
        assertEq(agent.storageLogRoot, root);
        assertEq(agent.researchReportsCount, 1);
    }

    // ── Vote weight ───────────────────────────────────────────────────────────

    function testVoteWeight_NeutralRep() public {
        _registerAgent(agentA);
        // rep=50, stake=1000 PRED → weight = 1000 * 50/50 = 1000
        uint256 w = registry.getVoteWeight(agentA);
        assertEq(w, 1000);
    }

    function testVoteWeight_UnregisteredAgent() public {
        assertEq(registry.getVoteWeight(address(0xDEAD)), 0);
    }

    // ── Market creation ───────────────────────────────────────────────────────

    function testCreateMarket_Success() public {
        _registerAgent(agentA);
        address market = _createMarket(agentA);
        assertTrue(market != address(0));

        PredictionMarket m = PredictionMarket(market);
        assertEq(uint8(m.state()), 0); // OPEN
    }

    function testCreateMarket_OnlyVerified() public {
        // agentA not registered
        vm.startPrank(agentA);
        pred.approve(address(factory), CREATION_STAKE);
        vm.expectRevert();
        factory.createMarket("0g://question", block.timestamp + 1 days, "crypto", 1e18);
        vm.stopPrank();
    }

    function testCreateMarket_TrackedInFactory() public {
        _registerAgent(agentA);
        _createMarket(agentA);
        assertEq(factory.marketCount(), 1);
        MarketFactory.MarketRecord memory rec = factory.getMarket(1);
        assertEq(rec.creator, agentA);
    }

    function testCreateMarket_InvalidResolutionTime() public {
        _registerAgent(agentA);
        vm.startPrank(agentA);
        pred.approve(address(factory), CREATION_STAKE);
        vm.expectRevert(); // too soon
        factory.createMarket("0g://q", block.timestamp + 30 minutes, "crypto", 1e18);
        vm.stopPrank();
    }

    // ── Betting ───────────────────────────────────────────────────────────────

    function testBet_YES_Success() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        address market = _createMarket(agentA);

        _bet(agentB, market, 1, BET_SIZE); // YES

        PredictionMarket m = PredictionMarket(market);
        assertEq(m.yesPool(), BET_SIZE);
        assertEq(m.noPool(), 0);
        assertEq(m.yesBalances(agentB), BET_SIZE);
    }

    function testBet_NO_Success() public {
        _registerAgent(agentA);
        _registerAgent(agentC);
        address market = _createMarket(agentA);

        _bet(agentC, market, 0, BET_SIZE); // NO

        PredictionMarket m = PredictionMarket(market);
        assertEq(m.noPool(), BET_SIZE);
    }

    function testBet_ImpliedProbability() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        _registerAgent(agentC);
        address market = _createMarket(agentA);

        _bet(agentB, market, 1, 300e18); // 300 YES
        _bet(agentC, market, 0, 100e18); // 100 NO

        PredictionMarket m = PredictionMarket(market);
        uint256 yesImplied = m.impliedProbabilityYes();
        // 300 / 400 = 75% = 7500 bps
        assertApproxEqAbs(yesImplied, 7500, 10);
    }

    function testBet_BelowMinBet_Reverts() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        address market = _createMarket(agentA);

        vm.startPrank(agentB);
        pred.approve(market, 0.5e18);
        vm.expectRevert();
        PredictionMarket(market).bet(1, 0.5e18);
        vm.stopPrank();
    }

    function testBet_NotVerified_Reverts() public {
        _registerAgent(agentA);
        address market = _createMarket(agentA);
        address rando  = address(0xDEAD);
        vm.deal(rando, 1 ether);

        vm.startPrank(rando);
        vm.expectRevert();
        PredictionMarket(market).bet(1, BET_SIZE);
        vm.stopPrank();
    }

    // ── Resolution ────────────────────────────────────────────────────────────

    function testTriggerResolution_Success() public {
        _registerAgent(agentA);
        address market = _createMarket(agentA);

        vm.warp(block.timestamp + 2 days); // past resolution time
        PredictionMarket(market).triggerResolution();

        assertEq(uint8(PredictionMarket(market).state()), 1); // RESOLVING
    }

    function testTriggerResolution_TooEarly_Reverts() public {
        _registerAgent(agentA);
        address market = _createMarket(agentA);

        vm.expectRevert();
        PredictionMarket(market).triggerResolution();
    }

    // ── Voting with PoIR ──────────────────────────────────────────────────────

    function testCastVerifiedVote_WithPoIR() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        _registerAgent(agentC);
        _registerAgent(agentD);
        address market = _createMarket(agentA);

        _bet(agentB, market, 1, BET_SIZE);
        _bet(agentC, market, 0, BET_SIZE);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        // All three voter agents vote YES with PoIR
        bytes32 storageRoot = keccak256("research-report-YES");
        bytes memory teeSig = hex"deadbeef";

        vm.prank(agentB);
        resolver.castVerifiedVote(market, 1, storageRoot, teeSig);

        vm.prank(agentC);
        resolver.castVerifiedVote(market, 1, storageRoot, teeSig);

        vm.prank(agentD);
        resolver.castVerifiedVote(market, 1, storageRoot, teeSig);

        // Verify vote was recorded with PoIR
        CollectiveResolver.Vote memory vote = resolver.getVote(market, agentB);
        assertTrue(vote.cast);
        assertTrue(vote.hasPoIR);
        assertEq(vote.storageLogRoot, storageRoot);
        assertEq(vote.choice, 1); // YES
    }

    function testCastVerifiedVote_PoIR_WeightBonus() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        address market = _createMarket(agentA);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        uint256 baseWeight = registry.getVoteWeight(agentB);

        bytes32 root  = keccak256("research");
        bytes memory sig = hex"cafebabe";

        vm.prank(agentB);
        resolver.castVerifiedVote(market, 1, root, sig);

        CollectiveResolver.Vote memory vote = resolver.getVote(market, agentB);
        // PoIR bonus = 20% → effectiveWeight = baseWeight * 120 / 100
        assertEq(vote.weight, (baseWeight * 120) / 100);
    }

    function testCastVote_WithoutPoIR_NoBonus() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        address market = _createMarket(agentA);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        uint256 baseWeight = registry.getVoteWeight(agentB);

        vm.prank(agentB);
        resolver.castVerifiedVote(market, 1, bytes32(0), ""); // no PoIR

        CollectiveResolver.Vote memory vote = resolver.getVote(market, agentB);
        assertEq(vote.weight, baseWeight);
        assertFalse(vote.hasPoIR);
    }

    function testCannotVoteTwice() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        address market = _createMarket(agentA);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        vm.prank(agentB);
        resolver.castVerifiedVote(market, 1, bytes32(0), "");

        vm.prank(agentB);
        vm.expectRevert();
        resolver.castVerifiedVote(market, 0, bytes32(0), "");
    }

    // ── Full happy-path flow ──────────────────────────────────────────────────

    function testFullFlow_YESWins() public {
        // Register 4 agents (3 voters, 1 creator)
        _registerAgent(agentA);
        _registerAgent(agentB);
        _registerAgent(agentC);
        _registerAgent(agentD);

        // Create market
        address market = _createMarket(agentA);

        // Place bets
        _bet(agentB, market, 1, 300e18); // YES
        _bet(agentC, market, 0, 100e18); // NO (will lose)

        uint256 totalPool = PredictionMarket(market).totalCollateral();
        assertEq(totalPool, 400e18);

        // Warp past resolution time
        vm.warp(block.timestamp + 2 days);

        // Trigger resolution
        vm.prank(agentA);
        PredictionMarket(market).triggerResolution();
        assertEq(uint8(PredictionMarket(market).state()), 1); // RESOLVING

        // 3 agents vote YES (majority)
        bytes32 root = keccak256("proof-yes");
        bytes memory sig = hex"1234";

        vm.prank(agentB); resolver.castVerifiedVote(market, 1, root, sig);
        vm.prank(agentC); resolver.castVerifiedVote(market, 1, root, sig);
        vm.prank(agentD); resolver.castVerifiedVote(market, 1, root, sig);

        // Warp past voting window
        vm.warp(block.timestamp + 3 days);

        // Finalize
        resolver.finalizeResolution(market);
        assertEq(uint8(PredictionMarket(market).state()), 2); // RESOLVED
        assertEq(PredictionMarket(market).outcome(), 1);      // YES

        // Claim winnings (agentB bet YES)
        uint256 balBefore = pred.balanceOf(agentB);
        vm.prank(agentB);
        PredictionMarket(market).claimWinnings();
        uint256 balAfter = pred.balanceOf(agentB);

        // agentB should have received more than they bet
        assertGt(balAfter, balBefore);
        console.log("AgentB profit:", (balAfter - balBefore) / 1e18, "PRED");
    }

    function testFullFlow_QuorumExtension() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        // Only 2 agents registered — quorum needs 3

        address market = _createMarket(agentA);
        _bet(agentB, market, 1, BET_SIZE);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        // Only agentB votes — not enough for quorum
        vm.prank(agentB);
        resolver.castVerifiedVote(market, 1, bytes32(0), "");

        vm.warp(block.timestamp + 3 days);

        // First finalize → extension triggered
        resolver.finalizeResolution(market);
        CollectiveResolver.ResolutionSession memory sess = resolver.getSession(market);
        assertEq(sess.extensions, 1);
        assertEq(uint8(sess.state), 2); // EXTENDED
    }

    function testFullFlow_InvalidAfterMaxExtensions() public {
        _registerAgent(agentA);
        address market = _createMarket(agentA);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        // No votes at all → exhaust all extensions
        for (uint256 i = 0; i <= 3; i++) {
            vm.warp(block.timestamp + 2 days);
            if (i < 3) {
                // Will extend
                resolver.finalizeResolution(market);
            }
        }
        // Final call → INVALID
        vm.warp(block.timestamp + 2 days);
        resolver.finalizeResolution(market);

        assertEq(uint8(PredictionMarket(market).state()), 3); // INVALID
    }

    function testClaimRefund_InvalidMarket() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        address market = _createMarket(agentA);
        _bet(agentB, market, 1, BET_SIZE);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        // Exhaust all extensions
        for (uint256 i = 0; i <= 4; i++) {
            vm.warp(block.timestamp + 2 days);
            try resolver.finalizeResolution(market) {} catch {}
        }

        // Claim refund
        uint256 balBefore = pred.balanceOf(agentB);
        vm.prank(agentB);
        PredictionMarket(market).claimRefund();
        uint256 balAfter = pred.balanceOf(agentB);

        assertEq(balAfter - balBefore, BET_SIZE); // full refund, no fee
    }

    // ── Reputation ────────────────────────────────────────────────────────────

    function testReputation_IncreasesOnCorrectVote() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        _registerAgent(agentC);
        _registerAgent(agentD);

        address market = _createMarket(agentA);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        bytes32 root = keccak256("proof");
        bytes memory sig = hex"ff";
        vm.prank(agentB); resolver.castVerifiedVote(market, 1, root, sig); // YES
        vm.prank(agentC); resolver.castVerifiedVote(market, 1, root, sig); // YES
        vm.prank(agentD); resolver.castVerifiedVote(market, 1, root, sig); // YES

        vm.warp(block.timestamp + 3 days);
        resolver.finalizeResolution(market); // YES wins

        // agentB voted with majority → rep should increase
        IAgentRegistry.Agent memory agent = registry.getAgent(agentB);
        assertGt(agent.reputationScore, 50); // was 50, now higher
    }

    function testReputation_DecreasesOnWrongVote() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        _registerAgent(agentC);
        _registerAgent(agentD);

        address market = _createMarket(agentA);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        bytes32 root = keccak256("proof");
        bytes memory sig = hex"ff";
        vm.prank(agentB); resolver.castVerifiedVote(market, 0, root, sig); // NO (minority)
        vm.prank(agentC); resolver.castVerifiedVote(market, 1, root, sig); // YES (majority)
        vm.prank(agentD); resolver.castVerifiedVote(market, 1, root, sig); // YES (majority)

        vm.warp(block.timestamp + 3 days);
        resolver.finalizeResolution(market); // YES wins

        // agentB voted minority → rep should decrease
        IAgentRegistry.Agent memory agentBInfo = registry.getAgent(agentB);
        assertLt(agentBInfo.reputationScore, 50); // was 50, now lower
    }

    // ── Slashing ─────────────────────────────────────────────────────────────

    function testSlash_ReducesStakeAndRep() public {
        _registerAgent(agentB);
        uint256 initialStake = registry.getAgent(agentB).stakedAmount;

        vm.prank(admin);
        registry.slash(registry.addressToAgentId(agentB), "Malicious behaviour");

        IAgentRegistry.Agent memory agent = registry.getAgent(agentB);
        assertLt(agent.stakedAmount, initialStake);
        assertEq(agent.reputationScore, 0);
        assertTrue(agent.slashed);
    }

    // ── Creator stake return ──────────────────────────────────────────────────

    function testCreatorStakeReturned_AfterResolution() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        _registerAgent(agentC);
        _registerAgent(agentD);

        uint256 balBefore = pred.balanceOf(agentA);
        address market = _createMarket(agentA);
        uint256 balAfterCreate = pred.balanceOf(agentA);
        assertEq(balBefore - balAfterCreate, CREATION_STAKE);

        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        bytes32 root = keccak256("p");
        bytes memory sig = hex"aa";
        vm.prank(agentB); resolver.castVerifiedVote(market, 1, root, sig);
        vm.prank(agentC); resolver.castVerifiedVote(market, 1, root, sig);
        vm.prank(agentD); resolver.castVerifiedVote(market, 1, root, sig);

        vm.warp(block.timestamp + 3 days);
        resolver.finalizeResolution(market);

        // Return creator stake
        factory.returnCreatorStake(market);

        uint256 balAfterReturn = pred.balanceOf(agentA);
        assertEq(balAfterReturn - balAfterCreate, CREATION_STAKE);
    }

    // ── Gas benchmarks ────────────────────────────────────────────────────────

    function testGas_Register() public {
        vm.startPrank(agentA);
        pred.approve(address(registry), STAKE);
        uint256 gas = gasleft();
        registry.register("0g://card", STAKE, "kv-id");
        uint256 used = gas - gasleft();
        vm.stopPrank();
        console.log("Gas — register():", used);
        assertLt(used, 500_000);
    }

    function testGas_CreateMarket() public {
        _registerAgent(agentA);
        vm.startPrank(agentA);
        pred.approve(address(factory), CREATION_STAKE);
        uint256 gas = gasleft();
        factory.createMarket("0g://q", block.timestamp + 1 days, "crypto", 1e18);
        uint256 used = gas - gasleft();
        vm.stopPrank();
        console.log("Gas — createMarket() clone:", used);
        assertLt(used, 300_000); // EIP-1167 clone is cheap
    }

    function testGas_Bet() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        address market = _createMarket(agentA);
        vm.startPrank(agentB);
        pred.approve(market, BET_SIZE);
        uint256 gas = gasleft();
        PredictionMarket(market).bet(1, BET_SIZE);
        uint256 used = gas - gasleft();
        vm.stopPrank();
        console.log("Gas — bet():", used);
        assertLt(used, 200_000);
    }

    function testGas_CastVerifiedVote() public {
        _registerAgent(agentA);
        _registerAgent(agentB);
        address market = _createMarket(agentA);
        vm.warp(block.timestamp + 2 days);
        PredictionMarket(market).triggerResolution();

        vm.startPrank(agentB);
        uint256 gas = gasleft();
        resolver.castVerifiedVote(market, 1, keccak256("root"), hex"aabb");
        uint256 used = gas - gasleft();
        vm.stopPrank();
        console.log("Gas — castVerifiedVote():", used);
        assertLt(used, 200_000);
    }
}

// ─── Interface for test ────────────────────────────────────────────────────────
interface IAgentRegistry {
    enum VerificationTier { UNREGISTERED, REGISTERED, VERIFIED, TRUSTED }
    struct Agent {
        uint256 agentId; address agentAddress; uint8 tier;
        uint256 stakedAmount; uint256 reputationScore; uint256 totalResolutions;
        uint256 correctResolutions; uint256 registeredAt; string metadataURI;
        bool slashed; bytes32 storageLogRoot; string kvStreamId;
        uint256 inftTokenId; uint256 researchReportsCount;
    }
}
