#!/usr/bin/env bash
# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â
# AgentMarket Ã¢â‚¬â€ Hackathon Demo Runner
# Starts 3 agents on separate AXL nodes and seeds demo markets.
# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â
set -e
AXL_BIN="${AXL_BIN:-axl}"
AXL_CONFIG_FLAG="${AXL_CONFIG_FLAG:--config}"
PYTHON_BIN="${PYTHON_BIN:-}"
VENV_DIR="${VENV_DIR:-venv}"
if grep -qi microsoft /proc/version 2>/dev/null && [ "$VENV_DIR" = "venv" ]; then
  VENV_DIR=".venv-wsl"
fi
if [ "$AXL_BIN" = "axl" ] && [ -x "./bin/axl.exe" ]; then
  AXL_BIN="./bin/axl.exe"
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

print_banner() {
cat << 'EOF'
   _                    _   __  __            _        _
  / \   __ _  ___ _ __ | |_|  \/  | __ _ _ __| | _____| |_
 / _ \ / _` |/ _ \ '_ \| __| |\/| |/ _` | '__| |/ / _ \ __|
/ ___ \ (_| |  __/ | | | |_| |  | | (_| | |  |   <  __/ |_
/_/   \_\__, |\___|_| |_|\__|_|  |_|\__,_|_|  |_|\_\___|\__|
        |___/
         0G Ãƒâ€” AXL Autonomous Prediction Markets
         Gensyn + 0G Hackathon Demo
EOF
}

log()    { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn()   { echo -e "${YELLOW}[$(date +%H:%M:%S)] Ã¢Å¡Â Ã¯Â¸Â  $1${NC}"; }
error()  { echo -e "${RED}[$(date +%H:%M:%S)] Ã¢Å“â€” $1${NC}"; }
step()   { echo -e "\n${BLUE}${BOLD}Ã¢â€¢ÂÃ¢â€¢Â $1 Ã¢â€¢ÂÃ¢â€¢Â${NC}"; }

print_banner
echo ""

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Check prerequisites Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Checking prerequisites"

check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    error "$1 not found. Please install it."
    exit 1
  fi
  log "$1 Ã¢Å“â€œ"
}

detect_python() {
  if [ -n "$PYTHON_BIN" ] && command -v "$PYTHON_BIN" &>/dev/null; then
    return 0
  fi
  for candidate in python3 python py; do
    if command -v "$candidate" &>/dev/null; then
      PYTHON_BIN="$candidate"
      return 0
    fi
  done
  return 1
}

if ! detect_python; then
  error "Python not found. Install Python 3.11+ or set PYTHON_BIN=/path/to/python."
  exit 1
fi
log "Python Ã¢Å“â€œ ($PYTHON_BIN)"
check_cmd npx
check_cmd node

if ! command -v "$AXL_BIN" &>/dev/null; then
  error "AXL binary not found: $AXL_BIN"
  echo -e "${YELLOW}Install AXL from:${NC} https://github.com/gensyn-ai/axl/releases"
  echo -e "${YELLOW}Then rerun with:${NC} AXL_BIN=./bin/axl.exe bash run_demo.sh"
  exit 1
fi
log "AXL binary Ã¢Å“â€œ ($AXL_BIN)"

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Load env Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Loading environment"
if [ ! -f .env ]; then
  error ".env not found. Copy .env.example to .env and fill in values."
  exit 1
fi
set -a; source .env; set +a
log "Environment loaded"

# Validate required vars
for var in AGENT_A_PRIVATE_KEY AGENT_B_PRIVATE_KEY AGENT_C_PRIVATE_KEY EVM_RPC_URL; do
  if [ -z "${!var}" ]; then
    error "$var not set in .env"
    exit 1
  fi
done
log "All required env vars present"

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Generate AXL keys if needed Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Preparing AXL keys"
mkdir -p keys
for agent in a b c; do
  if [ ! -f "keys/agent-${agent}-private.pem" ]; then
    log "Generating key for agent-${agent}Ã¢â‚¬Â¦"
    openssl genpkey -algorithm ed25519 -out "keys/agent-${agent}-private.pem" 2>/dev/null
  else
    log "Key for agent-${agent} already exists Ã¢Å“â€œ"
  fi
done

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Deploy contracts (if not already deployed) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Smart contracts"
if [ ! -f deployments/addresses.json ]; then
  log "Deploying contracts to $EVM_RPC_URL (chain $CHAIN_ID)Ã¢â‚¬Â¦"
  mkdir -p deployments
  npx hardhat run scripts/deploy.cjs --network zg_galileo 2>&1 | tee deployments/deploy.log
  log "Contracts deployed Ã¢Å“â€œ"
  cat deployments/addresses.json
else
  log "Contracts already deployed (deployments/addresses.json exists)"
  cat deployments/addresses.json
fi
addr_from_deployments() {
  node -e "const fs=require('fs'); const a=JSON.parse(fs.readFileSync('deployments/addresses.json','utf8')); process.stdout.write(a['$1'] || '')"
}
export PRED_TOKEN_ADDRESS="${PRED_TOKEN_ADDRESS:-$(addr_from_deployments PredToken)}"
export POSITION_TOKEN_ADDRESS="${POSITION_TOKEN_ADDRESS:-$(addr_from_deployments PositionToken)}"
export AGENT_REGISTRY_ADDRESS="${AGENT_REGISTRY_ADDRESS:-$(addr_from_deployments AgentRegistry)}"
export MARKET_FACTORY_ADDRESS="${MARKET_FACTORY_ADDRESS:-$(addr_from_deployments MarketFactory)}"
export COLLECTIVE_RESOLVER_ADDRESS="${COLLECTIVE_RESOLVER_ADDRESS:-$(addr_from_deployments CollectiveResolver)}"
export INFT_CONTRACT="${INFT_CONTRACT:-$(addr_from_deployments INFT)}"

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Install Python deps Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Python dependencies"
USE_VENV="${USE_VENV:-1}"
if [ "$USE_VENV" = "1" ] && [ ! -f "$VENV_DIR/Scripts/activate" ] && [ ! -f "$VENV_DIR/bin/activate" ]; then
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    warn "Python venv is unavailable; falling back to the current Python environment."
    USE_VENV=0
  fi
fi
if [ "$USE_VENV" = "1" ]; then
  if [ -f "$VENV_DIR/Scripts/activate" ]; then
    source "$VENV_DIR/Scripts/activate"
    PYTHON_BIN="python"
  elif [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
    PYTHON_BIN="python"
  else
    warn "Virtual environment activation script not found; using current Python."
    USE_VENV=0
  fi
fi

if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
  error "pip is not available for $PYTHON_BIN. Install python3-pip or set PYTHON_BIN to a Python that has pip."
  exit 1
fi
if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import importlib.util
mods = ["web3", "eth_account", "aiohttp", "requests", "flask", "dotenv", "pydantic", "click"]
raise SystemExit(0 if all(importlib.util.find_spec(m) for m in mods) else 1)
PY
then
  log "Python deps already available"
else
  log "Installing Python deps (first run can take a few minutes)..."
  "$PYTHON_BIN" -m pip install --disable-pip-version-check -r requirements.txt
fi
log "Python deps installed Ã¢Å“â€œ"

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Start AXL nodes Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Starting AXL nodes (separate processes)"
mkdir -p logs

log "Starting AXL bootstrap node (Agent A)Ã¢â‚¬Â¦"
"$AXL_BIN" "$AXL_CONFIG_FLAG" axl-configs/agent-a.json > logs/axl-a.log 2>&1 &
AXL_A_PID=$!
sleep 2

log "Starting AXL node BÃ¢â‚¬Â¦"
"$AXL_BIN" "$AXL_CONFIG_FLAG" axl-configs/agent-b.json > logs/axl-b.log 2>&1 &
AXL_B_PID=$!
sleep 1

log "Starting AXL node CÃ¢â‚¬Â¦"
"$AXL_BIN" "$AXL_CONFIG_FLAG" axl-configs/agent-c.json > logs/axl-c.log 2>&1 &
AXL_C_PID=$!
sleep 1

log "AXL nodes running: A(pid=$AXL_A_PID) B(pid=$AXL_B_PID) C(pid=$AXL_C_PID)"

step "Seeding demo markets"
cd agents
AGENT_PRIVATE_KEY=$AGENT_A_PRIVATE_KEY "$PYTHON_BIN" market_creator.py seed
cd ..
log "Demo markets seeded ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“"

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Start agents Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Starting AI agents"
cd agents

log "Starting Agent A (creator)Ã¢â‚¬Â¦"
AGENT_PRIVATE_KEY=$AGENT_A_PRIVATE_KEY \
AGENT_NAME="AgentMarket-Creator" \
AXL_API_BASE="http://127.0.0.1:9002" \
AXL_MCP_PORT=9003 AXL_A2A_PORT=9004 \
"$PYTHON_BIN" agent.py > ../logs/agent-a.log 2>&1 &
AGENT_A_PID=$!

sleep 3

log "Starting Agent B (bettor)Ã¢â‚¬Â¦"
AGENT_PRIVATE_KEY=$AGENT_B_PRIVATE_KEY \
AGENT_NAME="AgentMarket-Bettor" \
AXL_API_BASE="http://127.0.0.1:9012" \
AXL_MCP_PORT=9013 AXL_A2A_PORT=9014 \
"$PYTHON_BIN" agent.py > ../logs/agent-b.log 2>&1 &
AGENT_B_PID=$!

sleep 3

log "Starting Agent C (resolver)Ã¢â‚¬Â¦"
AGENT_PRIVATE_KEY=$AGENT_C_PRIVATE_KEY \
AGENT_NAME="AgentMarket-Resolver" \
AXL_API_BASE="http://127.0.0.1:9022" \
AXL_MCP_PORT=9023 AXL_A2A_PORT=9024 \
"$PYTHON_BIN" agent.py > ../logs/agent-c.log 2>&1 &
AGENT_C_PID=$!

cd ..

sleep 5
log "Agents running: A(pid=$AGENT_A_PID) B(pid=$AGENT_B_PID) C(pid=$AGENT_C_PID)"


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Start dashboard Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Starting dashboard"
if [ ! -d node_modules ]; then
  npm install -q
fi
VITE_RPC_URL="$EVM_RPC_URL" \
VITE_FACTORY_ADDR="$MARKET_FACTORY_ADDRESS" \
VITE_REGISTRY_ADDR="$AGENT_REGISTRY_ADDRESS" \
VITE_RESOLVER_ADDR="$COLLECTIVE_RESOLVER_ADDRESS" \
npm run dev > logs/dashboard.log 2>&1 &
DASH_PID=$!

sleep 2
log "Dashboard running at http://localhost:5173"

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Summary Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
step "Demo is live!"
echo ""
echo -e "${CYAN}${BOLD}  SERVICES${NC}"
echo -e "  Dashboard     : ${GREEN}http://localhost:5173${NC}"
echo -e "  AXL Node A    : http://127.0.0.1:9002  (bootstrap)"
echo -e "  AXL Node B    : http://127.0.0.1:9012"
echo -e "  AXL Node C    : http://127.0.0.1:9022"
echo -e "  MCP Server A  : http://127.0.0.1:9003/mcp"
echo -e "  MCP Server B  : http://127.0.0.1:9013/mcp"
echo -e "  MCP Server C  : http://127.0.0.1:9023/mcp"
echo ""
echo -e "${CYAN}${BOLD}  LOGS${NC}"
echo -e "  tail -f logs/agent-a.log"
echo -e "  tail -f logs/agent-b.log"
echo -e "  tail -f logs/agent-c.log"
echo -e "  tail -f logs/axl-a.log"
echo ""
echo -e "${YELLOW}  Press Ctrl+C to stop all services${NC}"
echo ""

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Cleanup on exit Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
cleanup() {
  echo ""
  log "Shutting down all servicesÃ¢â‚¬Â¦"
  kill $AXL_A_PID $AXL_B_PID $AXL_C_PID 2>/dev/null || true
  kill $AGENT_A_PID $AGENT_B_PID $AGENT_C_PID 2>/dev/null || true
  kill $DASH_PID 2>/dev/null || true
  log "Done. Goodbye."
}
trap cleanup EXIT INT TERM

# Wait forever
wait
