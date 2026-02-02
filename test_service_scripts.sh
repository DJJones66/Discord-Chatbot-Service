#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="BrainDriveDev"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run_step() {
  local label="$1"
  shift
  echo "\n==> ${label}"
  "$@"
}

run_step "Create venv" conda run -n "$ENV_NAME" python "$ROOT_DIR/service_scripts/create_venv.py"
run_step "Install deps" conda run -n "$ENV_NAME" python "$ROOT_DIR/service_scripts/install_with_venv.py"
run_step "Start service" conda run -n "$ENV_NAME" python "$ROOT_DIR/service_scripts/start_with_venv.py"

# Give the service a moment to start
sleep 2

run_step "Restart service" conda run -n "$ENV_NAME" python "$ROOT_DIR/service_scripts/restart_with_venv.py"

# Give the service a moment to restart
sleep 2

run_step "Shutdown service" conda run -n "$ENV_NAME" python "$ROOT_DIR/service_scripts/shutdown_with_venv.py"

echo "\nAll service script steps completed."
