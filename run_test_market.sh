#!/usr/bin/env bash
set -e

echo "🚀 Creating Prediction Market (1-hour resolution)"

# Load env
if [ ! -f .env ]; then
  echo "❌ .env not found"
  exit 1
fi

set -a
source .env
set +a

# Validate
if [ -z "$AGENT_A_PRIVATE_KEY" ] || [ -z "$EVM_RPC_URL" ]; then
  echo "❌ Missing required env vars"
  exit 1
fi

echo "✅ Environment loaded"

# Get contract addresses (if deployed already)
if [ -f deployments/addresses.json ]; then
  export MARKET_FACTORY_ADDRESS=$(node -e "console.log(require('./deployments/addresses.json').MarketFactory)")
else
  echo "❌ deployments/addresses.json not found"
  exit 1
fi

echo "✅ Using MarketFactory: $MARKET_FACTORY_ADDRESS"

# Move to agents folder
cd agents

# Create market with 1-hour expiry
END_TIME=$(($(date +%s) + 3600))

echo "🧠 Creating market (resolves in 1 hour)..."

AGENT_PRIVATE_KEY=$AGENT_A_PRIVATE_KEY \
python3 market_creator.py create \
  --question "Will BTC be above 70k in 1 hour?" \
  --end-time $END_TIME \
  --initial-liquidity 100

echo "✅ Market created successfully!"