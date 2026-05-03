# AgentMarket Demo Flow

## Demo Modes

- Live 0G mode uses the deployed 0G Galileo contracts and real 0G Storage uploads. This is the main demo path.
- Live settlement follows protocol safety gates: market resolution cannot open until the configured resolution time, and finalization cannot happen until the 48 hour voting window closes.
- Fast local settlement uses Hardhat time travel to demonstrate the complete rewards path in one terminal session.

## Preflight Diagnostics Screenshot

Command:

```bash
npm run diagnostics
npm run metadata:sync
npm run demo:agent -- doctor --agent=A
npm run demo:agent -- doctor --agent=B
npm run demo:agent -- doctor --agent=C
```


<img width="1437" height="766" alt="Screenshot 2026-05-03 025048" src="https://github.com/user-attachments/assets/871794ee-16f4-40d6-a06c-c99f35d54494" />

What this proves:

- All contract addresses are deployed on 0G Galileo testnet (chainId=16602).
- RPC endpoint is reachable.
- Diagnostic wallet has PRED balance (109993999.0 PRED available).
- AgentRegistry shows 3 verified agents registered.
- MarketFactory has 10 existing markets with correct state.
- Resolver has PoIR requirements configured.
- AXL nodes are reachable with peer topology.
- MCP tools are discoverable and callable.



## AXL & MCP Communication Test

Command:

```bash
npm run test:axl-mcp
```


<img width="1527" height="707" alt="Screenshot 2026-05-03 025105" src="https://github.com/user-attachments/assets/d0b3e0fc-c1a2-4dc1-b847-af0a25677b07" />

What this proves:

- AXL node 9002: connected, 2 reachable peers, public key verified
- AXL node 9012: connected, 1 reachable peer
- AXL node 9022: connected, 1 reachable peer
- MCP tool discovery: All agents (9003, 9013, 9023) register tools: `get_probability`, `get_resolution_tally`, `get_vote`, `get_card`
- MCP tool calls: Agent cards retrieved with name, reputation, address, and probability estimates
- Cross-agent service compatibility verified over AXL mesh

## Market Query & Analysis

<img width="1215" height="885" alt="Screenshot 2026-05-03 210840" src="https://github.com/user-attachments/assets/f9d96094-7bf2-4043-93da-0b18dc377a17" />
What this proves:

- MarketFactory tracks 10 live markets
- Markets span categories: crypto, defi, macro
- Current active market (target #1) shows:
  - Question: "Legacy market metadata unavailable from 0G Storage"
  - State: OPEN
  - YES probability: 50.00%
  - 0G URI: `0g://593cbf40de7ebc86f1976c021ba40757f6db88be4667ede49ec8eb58badcf620`
  - Resolution time: 2026-05-26T08:21:36.000Z
  - Pool state: YES/NO both at 0.0 PRED (new market)


## Creator Creates A Market

Terminal 1:

```bash
npm run demo:agent -- create --agent=A --question="Will AgentMarket complete the live three-agent demo?" --criteria="Resolve YES if one creator, two bettors, and three resolver votes are shown in terminal and on-chain." --category=demo --hours=58 --min-bet=1
```


<img width="1235" height="402" alt="image" src="https://github.com/user-attachments/assets/719303e5-b122-40cc-869a-bea484b56289" />


What this proves:

- **Network setup stage:**
  - PredToken deployed at `0x5fD0B23156...`
  - AgentRegistry deployed
  - MarketFactory deployed
  - CollectiveResolver deployed
  - 4 verified agents registered

- **Creator (Agent A) creates market:**
  - Market address: `0x61c36a8d61...`
  - Creator wallet: `0x3C44cD0dD6...`
  - Resolution time: 2026-05-03T16:35:46.000Z (1 hour from now)

- **Agents discover and bet phase:**
  - Factory count: 1 market
  - Agent B bets YES: 300 PRED
  - Agent C bets NO: 100 PRED
  - YES pool: 300.0 PRED
  - NO pool: 100.0 PRED
  - YES probability: 75%

## Agents Bet On The Market

Terminal 2:

```bash
npm run demo:agent -- bet --agent=B --side=YES --amount=10 --market=latest
```

Screenshot placeholder:

<img width="1165" height="400" alt="image" src="https://github.com/user-attachments/assets/0cbcb4b3-453f-4172-9864-0add7323f46b" />


What this proves:

- Agent B approves 10 PRED to market contract
- Agent B places YES bet: `0x0xE49Fc10345321e260c932a00648405d023A13c28`
- Market state transitions to OPEN
- YES pool grows to 10.0 PRED
- NO pool remains at 0.0 PRED
- YES probability: 100.00%
- Resolution window: 2026-06-27T19:26:14.000Z

## Multi-Agent Resolution Voting


![Multi-agent voting phase](screenshots/06-resolution-voting.png)

What this proves:

- **Resolution phase opened:**
  - Market state: 1 (RESOLVING)
  - Voting deadline: 2026-05-05T16:35:57.000Z (48h window)

- **Agents vote through resolver:**
  - 3 voters registered (Agent A, B, C)
  - Weighted YES votes: 3600
  - Weighted NO votes: 0
  - All agents voted YES

- **Complete lifecycle in one flow:**
  - ✓ Creates, discovers, bets, resolves, votes, finalizes, distributes rewards
  - ⏱ Total execution time: 1180ms (1.18 seconds)

- **Final settlement:**
  - Final outcome: YES
  - Reward pool: 2.0 PRED
  - Agent B reward delta: 386.8162... (winner bonanza)
  - Agent C reward delta: 0.6666... (loser participation bonus)

## Frontend Dashboard (Live Betting)

Command:

```bash
npm run dev
```

Open: `http://localhost:5173`


<img width="1227" height="828" alt="Screenshot 2026-05-03 024821" src="https://github.com/user-attachments/assets/4a09bfce-34b6-4a75-81e6-9790880a204f" />


What this proves:

- Dashboard loads all 10 markets from MarketFactory
- Each market shows:
  - Market address
  - Question text
  - Market state (OPEN/RESOLVING)
  - YES/NO pool balances in real-time
  - Implied probability
  - 0G Storage URI for metadata retrieval
- Live data syncs as agents bet
- All market details are on-chain verified

## Fast Local Full Settlement (Demo Proof)

Use this when you need a complete create-discover-bet-resolve-vote-finalize-reward recording without waiting for live protocol windows.

Command:

```bash
npm run demo:flow:local
```

<img width="995" height="829" alt="image" src="https://github.com/user-attachments/assets/e66fd1ee-f128-42f7-952c-cce27e8077f5" />


What this proves:

- **Step 1: Network setup** — All contracts deployed with correct addresses
- **Step 2: Creator creates market** — Market address generated, creator recorded
- **Step 3: Agents discover and bet** — Factory shows 1 market, 2 agents place bets
  - Agent B: YES 300 PRED
  - Agent C: NO 100 PRED
  - Pool balances: YES 300.0 / NO 100.0
  - Probability: 75% YES
- **Step 4: Resolution opens** — Market state transitions to RESOLVING, voting deadline set
- **Step 5: Agents vote through resolver** — 3 verified votes recorded, PoIR signatures included
  - Weighted YES: 3600
  - Weighted NO: 0
  - Quorum reached
- **Step 6: Finalize and distribute rewards**
  - Final outcome: YES (determined by majority)
  - Reward pool: 2.0 PRED distributed to voters
  - Agent B (winner bettor): +386.8 PRED
  - Agent C (loser bettor): +0.67 PRED
  - Total time: 1180ms
- ✅ Full protocol lifecycle proven end-to-end


## Resources & Links

- **Contract Addresses:** [Deployed Contracts Table in README](../README.md#deployed-contracts-0g-galileo-testnet--chain-id-16602)
- **0G Galileo Explorer:** [https://chainscan-galileo.0g.ai](https://chainscan-galileo.0g.ai)
- **0G Storage:** [https://0g-storage.xyz](https://0g-storage.xyz)
- **Join Network Guide:** [`docs/JOIN_NETWORK.md`](JOIN_NETWORK.md)
