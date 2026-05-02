#!/usr/bin/env bash
set -euo pipefail

AXL_BIN="${AXL_BIN:-axl}"
AXL_CONFIG_FLAG="${AXL_CONFIG_FLAG:--config}"
PYTHON_BIN="${PYTHON_BIN:-}"
VENV_DIR="${VENV_DIR:-venv}"
KEEP_ALIVE="${KEEP_ALIVE:-1}"

if grep -qi microsoft /proc/version 2>/dev/null && [ "$VENV_DIR" = "venv" ]; then
  VENV_DIR=".venv-wsl"
fi
if [ "$AXL_BIN" = "axl" ] && [ -x "./bin/axl.exe" ]; then
  AXL_BIN="./bin/axl.exe"
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] $1${NC}"; }
fail() { echo -e "${RED}[$(date +%H:%M:%S)] $1${NC}"; exit 1; }
step() { echo -e "\n${BLUE}${BOLD}== $1 ==${NC}"; }

detect_python() {
  if [ -n "$PYTHON_BIN" ] && command -v "$PYTHON_BIN" >/dev/null 2>&1; then return 0; fi
  for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$candidate"; return 0; fi
  done
  return 1
}

load_addresses() {
  node -e "const fs=require('fs'); const a=JSON.parse(fs.readFileSync('deployments/addresses.json','utf8')); process.stdout.write(a['$1'] || '')"
}

cleanup() {
  echo ""
  log "Stopping test systems..."
  kill ${AXL_A_PID:-} ${AXL_B_PID:-} ${AXL_C_PID:-} 2>/dev/null || true
  kill ${AGENT_A_PID:-} ${AGENT_B_PID:-} ${AGENT_C_PID:-} 2>/dev/null || true
  kill ${DASH_PID:-} 2>/dev/null || true
  log "Stopped."
}
trap cleanup EXIT INT TERM

cat <<'EOF'
AgentMarket Test Systems Runner
No market creation. Uses existing deployed markets.
EOF

step "Prerequisites"
detect_python || fail "Python not found. Install Python 3.11+ or set PYTHON_BIN."
command -v node >/dev/null 2>&1 || fail "node not found"
command -v npm >/dev/null 2>&1 || fail "npm not found"
command -v npx >/dev/null 2>&1 || fail "npx not found"
command -v "$AXL_BIN" >/dev/null 2>&1 || fail "AXL binary not found: $AXL_BIN"
log "Python: $PYTHON_BIN"
log "AXL: $AXL_BIN"

step "Environment"
[ -f .env ] || fail ".env not found"
set -a; source .env; set +a
[ -f deployments/addresses.json ] || fail "deployments/addresses.json not found"
export PRED_TOKEN_ADDRESS="${PRED_TOKEN_ADDRESS:-$(load_addresses PredToken)}"
export POSITION_TOKEN_ADDRESS="${POSITION_TOKEN_ADDRESS:-$(load_addresses PositionToken)}"
export AGENT_REGISTRY_ADDRESS="${AGENT_REGISTRY_ADDRESS:-$(load_addresses AgentRegistry)}"
export MARKET_FACTORY_ADDRESS="${MARKET_FACTORY_ADDRESS:-$(load_addresses MarketFactory)}"
export COLLECTIVE_RESOLVER_ADDRESS="${COLLECTIVE_RESOLVER_ADDRESS:-$(load_addresses CollectiveResolver)}"
export INFT_CONTRACT="${INFT_CONTRACT:-$(load_addresses INFT)}"
for var in AGENT_A_PRIVATE_KEY AGENT_B_PRIVATE_KEY AGENT_C_PRIVATE_KEY EVM_RPC_URL MARKET_FACTORY_ADDRESS; do
  [ -n "${!var:-}" ] || fail "$var is missing"
done
log "Environment loaded"

step "Dependencies"
if [ ! -d node_modules ]; then npm install; fi
USE_VENV="${USE_VENV:-1}"
if [ "$USE_VENV" = "1" ] && [ ! -f "$VENV_DIR/Scripts/activate" ] && [ ! -f "$VENV_DIR/bin/activate" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR" || USE_VENV=0
fi
if [ "$USE_VENV" = "1" ]; then
  if [ -f "$VENV_DIR/Scripts/activate" ]; then source "$VENV_DIR/Scripts/activate"; PYTHON_BIN="python"; fi
  if [ -f "$VENV_DIR/bin/activate" ]; then source "$VENV_DIR/bin/activate"; PYTHON_BIN="python"; fi
fi
"$PYTHON_BIN" -m pip --version >/dev/null 2>&1 || fail "pip unavailable"
if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import importlib.util
mods = ["web3", "eth_account", "aiohttp", "requests", "flask", "dotenv", "pydantic", "click"]
raise SystemExit(0 if all(importlib.util.find_spec(m) for m in mods) else 1)
PY
then
  "$PYTHON_BIN" -m pip install --disable-pip-version-check -r requirements.txt
fi
log "Dependencies ready"

step "Prepare AXL Keys"
mkdir -p keys logs
for agent in a b c; do
  if [ ! -f "keys/agent-${agent}-private.pem" ]; then
    openssl genpkey -algorithm ed25519 -out "keys/agent-${agent}-private.pem" 2>/dev/null
  fi
done

step "Start AXL Nodes"
"$AXL_BIN" "$AXL_CONFIG_FLAG" axl-configs/agent-a.json > logs/axl-a.log 2>&1 &
AXL_A_PID=$!
sleep 2
"$AXL_BIN" "$AXL_CONFIG_FLAG" axl-configs/agent-b.json > logs/axl-b.log 2>&1 &
AXL_B_PID=$!
sleep 1
"$AXL_BIN" "$AXL_CONFIG_FLAG" axl-configs/agent-c.json > logs/axl-c.log 2>&1 &
AXL_C_PID=$!
sleep 2
log "AXL nodes running: A=$AXL_A_PID B=$AXL_B_PID C=$AXL_C_PID"

step "Sync Existing Market Metadata"
npm run metadata:sync || warn "Metadata sync had warnings; continuing"

step "Start Agents"
cd agents
AGENT_PRIVATE_KEY="$AGENT_A_PRIVATE_KEY" AGENT_NAME="AgentMarket-Creator" AXL_API_BASE="http://127.0.0.1:9002" AXL_MCP_PORT=9003 AXL_A2A_PORT=9004 "$PYTHON_BIN" agent.py > ../logs/agent-a.log 2>&1 &
AGENT_A_PID=$!
sleep 3
AGENT_PRIVATE_KEY="$AGENT_B_PRIVATE_KEY" AGENT_NAME="AgentMarket-Bettor" AXL_API_BASE="http://127.0.0.1:9012" AXL_MCP_PORT=9013 AXL_A2A_PORT=9014 "$PYTHON_BIN" agent.py > ../logs/agent-b.log 2>&1 &
AGENT_B_PID=$!
sleep 3
AGENT_PRIVATE_KEY="$AGENT_C_PRIVATE_KEY" AGENT_NAME="AgentMarket-Resolver" AXL_API_BASE="http://127.0.0.1:9022" AXL_MCP_PORT=9023 AXL_A2A_PORT=9024 "$PYTHON_BIN" agent.py > ../logs/agent-c.log 2>&1 &
AGENT_C_PID=$!
cd ..
sleep 6
log "Agents running: A=$AGENT_A_PID B=$AGENT_B_PID C=$AGENT_C_PID"

step "Start Dashboard"
VITE_RPC_URL="$EVM_RPC_URL" \
VITE_FACTORY_ADDR="$MARKET_FACTORY_ADDRESS" \
VITE_REGISTRY_ADDR="$AGENT_REGISTRY_ADDRESS" \
VITE_RESOLVER_ADDR="$COLLECTIVE_RESOLVER_ADDRESS" \
npm run dev > logs/dashboard.log 2>&1 &
DASH_PID=$!
sleep 3
log "Dashboard: http://localhost:5173"

step "Run Test Systems"
npm run diagnostics
npm run test:axl-mcp
npm run test:lifecycle
npm run test:resolution

step "Summary"
echo "Dashboard     : http://localhost:5173"
echo "AXL Node A    : http://127.0.0.1:9002"
echo "AXL Node B    : http://127.0.0.1:9012"
echo "AXL Node C    : http://127.0.0.1:9022"
echo "MCP Server A  : http://127.0.0.1:9003/mcp"
echo "MCP Server B  : http://127.0.0.1:9013/mcp"
echo "MCP Server C  : http://127.0.0.1:9023/mcp"
echo "Logs          : logs/agent-a.log logs/agent-b.log logs/agent-c.log logs/axl-a.log"

if [ "$KEEP_ALIVE" = "1" ]; then
  echo ""
  echo "Keeping services alive. Press Ctrl+C to stop."
  while true; do sleep 3600; done
fi
