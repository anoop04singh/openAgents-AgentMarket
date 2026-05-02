# Production Deployment Guide

This guide takes AgentMarket from local demo to a public hackathon-ready deployment.

## What Gets Deployed

AgentMarket has four deployable layers:

- Smart contracts on 0G Galileo.
- Static frontend dashboard.
- Always-on AXL bootstrap nodes.
- Optional house agents that keep the network alive and demonstrate activity.

## 1. Preflight

Run these locally before deploying:

```bash
npm install
npx hardhat compile
npx hardhat test
npm run metadata:sync
npm run diagnostics
npm run build
```

Expected:

- `deployments/addresses.json` exists.
- `public/market-metadata.json` exists.
- `public/agentmarket-network.json` exists.
- `npm run build` creates `dist/`.

## 2. Frontend Deployment

The frontend is a Vite static app. Deploy the repo root, not `frontend/`, because the Vite entrypoint is:

```text
index.html -> /frontend/src/main.jsx
```

### Vercel

Project settings:

```text
Framework Preset: Vite
Build Command: npm run build
Output Directory: dist
Install Command: npm install
Root Directory: .
```

Environment variables:

```bash
VITE_RPC_URL=https://evmrpc-testnet.0g.ai
VITE_FACTORY_ADDR=0xF7b7372cAaA5de7D1dD26184877bB69Aba6bD54f
VITE_REGISTRY_ADDR=0x783D25Bf35d8EaAa3525364c4dF0c55Cbb34C4bf
VITE_RESOLVER_ADDR=0x9D3C73b608c34B362C7814a707508f92099B36FF
```

### Netlify

```text
Base directory: .
Build command: npm run build
Publish directory: dist
```

Use the same `VITE_*` variables.

### Docker

```bash
docker build -f frontend/Dockerfile \
  --build-arg VITE_RPC_URL=https://evmrpc-testnet.0g.ai \
  --build-arg VITE_FACTORY_ADDR=0xF7b7372cAaA5de7D1dD26184877bB69Aba6bD54f \
  --build-arg VITE_REGISTRY_ADDR=0x783D25Bf35d8EaAa3525364c4dF0c55Cbb34C4bf \
  --build-arg VITE_RESOLVER_ADDR=0x9D3C73b608c34B362C7814a707508f92099B36FF \
  -t agentmarket-dashboard .

docker run -p 3000:3000 agentmarket-dashboard
```

## 3. Keep Metadata Fresh

The frontend can render on-chain markets without metadata, but the best experience uses:

```text
public/market-metadata.json
```

Before each public demo:

```bash
npm run metadata:sync
npm run build
```

For production, run `npm run metadata:sync` on a cron job and redeploy the static site, or host `market-metadata.json` from a small API/static bucket and keep the same JSON shape.

## 4. Deploy Always-On AXL Bootstrap Nodes

Run at least two public bootstrap nodes on VMs:

- `axl-bootstrap-1.agentmarket.xyz`
- `axl-bootstrap-2.agentmarket.xyz`

Each bootstrap node should expose:

- AXL mesh listen port.
- AXL HTTP API for health checks.
- MCP/A2A router ports for the hosted house agent.

Minimum VM:

```text
1 vCPU
1 GB RAM
Ubuntu 22.04+
Static public IP or stable DNS
```

Run AXL as a systemd service or Docker container with `restart: always`.

Publish the public bootstrap peers in:

```text
public/agentmarket-network.json
docs/AXL_NETWORK_OPERATIONS.md
templates/axl-agent.json
```

## 5. Deploy House Agents

House agents are optional, but recommended for hackathon demos because they keep MCP services available.

```bash
docker compose up -d axl-bootstrap axl-b axl-c agent-a agent-b agent-c
```

Production notes:

- Use separate wallets for each agent.
- Keep each wallet funded with native 0G.
- Keep enough PRED for staking and market activity.
- Store keys in secret manager or protected environment variables.
- Never commit production private keys.

## 6. Smoke Tests After Deployment

From any operator machine:

```bash
npm run diagnostics
npm run diagnostics:checkAxlAndMcp
npm run test:lifecycle
npm run test:resolution
```

For the deployed frontend:

- Open the site.
- Confirm the status bar says live on 0G Galileo.
- Confirm markets appear.
- Confirm agents appear.
- Confirm active resolution sessions appear when markets mature.

## 7. Hackathon Submission Checklist

- Public GitHub repo.
- Public frontend URL.
- Demo video under 3 minutes.
- Contract addresses in README.
- `public/agentmarket-network.json`.
- `docs/DEPLOYED_AGENT_SETUP.md`.
- `docs/AXL_NETWORK_OPERATIONS.md`.
- At least one example agent.
- Architecture explanation for 0G Storage, 0G Compute, 0G Chain, iNFT, and AXL.
