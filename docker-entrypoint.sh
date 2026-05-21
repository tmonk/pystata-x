#!/bin/bash
"""Docker entrypoint for pystata-x development container.

Handles:
  - Package reinstall from the mounted source on every start
  - PYTHONDONTWRITEBYTECODE to avoid stale .pyc caches
  - Graceful container health check
  - Drop into a working shell

Usage:
    docker start pystata-x-persist                    # start daemonized
    docker exec pystata-x-persist ./entrypoint.sh test # run tests
    docker exec -it pystata-x-persist ./entrypoint.sh shell  # interactive
"""

set -euo pipefail

REINSTALL="${REINSTALL:-yes}"
TEST_TARGET="${TEST_TARGET:-/pystata-x/tests/unit/}"

export PYTHONDONTWRITEBYTECODE=1
export STATAPATH="${STATAPATH:-/usr/local/stata19}"
export PATH="$STATAPATH:/venv/bin:$PATH"

if [ "$REINSTALL" = "yes" ]; then
    echo "[entrypoint] Reinstalling pystata-x (editable) from mounted source..." >&2
    pip install -q -e /pystata-x
    pip install -q -e /pystata-x/src/pystata-analyzer
    echo "[entrypoint] Done." >&2
fi

case "${1:-shell}" in
    test)
        shift 1
        exec python -m pytest /pystata-x/tests/"${@:-unit/ -v --tb=short}"
        ;;
    e2e)
        shift 1
        exec python -m pytest /pystata-x/tests/e2e/ -m requires_stata -v --tb=short "$@"
        ;;
    all)
        shift 1
        python -m pytest /pystata-x/tests/unit/ -v --tb=short "$@"
        python -m pytest /pystata-x/tests/e2e/ -m requires_stata -v --tb=short "$@"
        python -m pytest /pystata-x/src/pystata-analyzer/tests/ -v --tb=short "$@"
        ;;
    shell)
        exec bash
        ;;
    *)
        exec "$@"
        ;;
esac
