# AgentMarket Demo Screenshot Flow

Use this document as the screenshot storyboard for the hackathon demo. Add images under `docs/screenshots/` and replace each placeholder with the real screenshot path.

## Demo Modes

- Live 0G mode uses the deployed 0G Galileo contracts and real 0G Storage uploads. This is the main demo path.
- Live settlement follows protocol safety gates: market resolution cannot open until the configured resolution time, and finalization cannot happen until the 48 hour voting window closes.
- Fast local settlement uses Hardhat time travel to demonstrate the complete rewards path in one terminal session.

## Preflight Screenshot

Command:

```bash
npm run diagnostics
npm run metadata:sync
npm run demo:agent -- doctor --agent=A
npm run demo:agent -- doctor --agent=B
npm run demo:agent -- doctor --agent=C
```

Screenshot placeholder:

![Preflight checks](screenshots/01-preflight.png)

What this proves:

- The frontend has deployed contract addresses.
- The wallet has PRED and registry state.
- Agents A, B, and C are ready to act.

## Frontend Dashboard Screenshot

Command:

```bash
npm run metadata:sync
npm run dev
```

Open:

```text
http://localhost:5173
```

Screenshot placeholder:

![Dashboard landing](screenshots/02-dashboard-landing.png)

What this proves:

- Markets are visible from MarketFactory.
- Market details are loaded from the local 0G metadata cache.
- Agent registry and resolution sessions are visible.

## Creator Creates A Market

Terminal 1:

```bash
npm run demo:agent -- create --agent=A --question="Will AgentMarket complete the live three-agent demo?" --criteria="Resolve YES if one creator, two bettors, and three resolver votes are shown in terminal and on-chain." --category=demo --hours=1 --min-bet=1
```

Screenshot placeholder:

![Creator market creation](screenshots/03-create-market.png)

What this proves:

- Agent A uploads metadata to 0G Storage.
- Agent A approves the MarketFactory creation stake.
- MarketFactory deploys a new PredictionMarket clone.
- The latest market is saved to `.demo/latest-market.json` for the other terminals.

## Agents Discover The Market

Terminal 2:

```bash
npm run demo:agent -- discover --agent=B --limit=8
```

Terminal 3:

```bash
npm run demo:agent -- discover --agent=C --limit=8
```

Screenshot placeholder:

![Agents discover market](screenshots/04-discover.png)

What this proves:

- Agents can independently query MarketFactory.
- The market address, question, state, probability, and 0G URI are visible.

## Agents Bet

Terminal 2:

```bash
npm run demo:agent -- bet --agent=B --side=YES --amount=10 --market=latest
```

Terminal 3:

```bash
npm run demo:agent -- bet --agent=C --side=NO --amount=5 --market=latest
```

Screenshot placeholder:

![Agents bet](screenshots/05-betting.png)

What this proves:

- Each agent approves PRED to the market contract.
- Agent B receives YES exposure.
- Agent C receives NO exposure.
- Pool balances and implied probability update after each bet.

## Frontend Updates After Betting

Command:

```bash
npm run metadata:sync
```

Click Refresh on the frontend.

Screenshot placeholder:

![Frontend after betting](screenshots/06-frontend-after-bets.png)

What this proves:

- The frontend reflects chain state after betting.
- The selected market shows YES pool, NO pool, total pool, and probability.

## Open Resolution

Run this after the market resolution timestamp shown in the create command.

Terminal 4:

```bash
npm run demo:agent -- resolve --agent=C --market=latest
```

Screenshot placeholder:

![Resolution opened](screenshots/07-resolution-opened.png)

What this proves:

- The market moves from OPEN to RESOLVING.
- CollectiveResolver opens a voting session.
- A voting deadline is created.

## Multi-Agent Voting

Terminal 1:

```bash
npm run demo:agent -- vote --agent=A --choice=YES --market=latest
```

Terminal 2:

```bash
npm run demo:agent -- vote --agent=B --choice=YES --market=latest
```

Terminal 3:

```bash
npm run demo:agent -- vote --agent=C --choice=YES --market=latest
```

Screenshot placeholder:

![Resolver votes](screenshots/08-votes.png)

What this proves:

- Three verified agents vote.
- Votes include a PoIR-compatible storage root field.
- Quorum is reached.

## Finalize And Distribute Rewards

Run this after the 48 hour voting window closes on live 0G mode.

Terminal 4:

```bash
npm run demo:agent -- finalize --agent=A --market=latest
```

Screenshot placeholder:

![Finalize rewards](screenshots/09-finalize-rewards.png)

What this proves:

- CollectiveResolver finalizes the majority outcome.
- Resolver rewards are distributed when a reward pool exists.
- Winning bettors can claim market winnings.

## Fast Local Full Settlement

Use this when you need a complete create-discover-bet-resolve-vote-finalize-reward recording without waiting for live protocol windows.

Command:

```bash
npm run demo:flow:local
```

Screenshot placeholder:

![Fast local settlement](screenshots/10-local-fast-settlement.png)

What this proves:

- The full contract lifecycle works end-to-end.
- Hardhat advances time through the one hour market maturity gate and the 48 hour voting window.
- Rewards and winnings are distributed in the expected order.

## Suggested 3 Minute Video Structure

1. Show the sharp frontend landing page and live market table.
2. Show Terminal 1 creating a market with a real 0G Storage root.
3. Show Terminals 2 and 3 discovering and betting.
4. Show the frontend probability changing.
5. Show resolution and three votes.
6. Show the local-fast settlement proof for final rewards if the live 48 hour window has not elapsed.
7. End on docs for third-party agents joining the network.
