#!/bin/bash
# Docker entrypoint for pystata-x development container.
# Handles both pystata-x (SFI bridge) AND pystata-analyzer (standalone
# Stata binary analysis framework).
#
# Environment:
#   REINSTALL=yes        Reinstall packages from mounted source on start
#   STATA_LIB_PATH       Path to libstata*.so
#
# Usage:
#   docker start pystata-x-persist
#   docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh unit
#   docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh e2e
#   docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh framework
#   docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh all
#   docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh analyze _bist_data
#   docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh catalog
#   docker exec -it pystata-x-persist /pystata-x/docker-entrypoint.sh shell

REINSTALL="${REINSTALL:-yes}"
export PYTHONDONTWRITEBYTECODE=1
export STATAPATH="${STATAPATH:-/usr/local/stata19}"
export STATA_LIB_PATH="${STATA_LIB_PATH:-/usr/local/stata19/libstata-se.so}"
export PATH="$STATAPATH:/venv/bin:$PATH"

if [ "$REINSTALL" = "yes" ]; then
    echo "[entrypoint] Installing packages from /pystata-x (editable)..." >&2
    pip install -q -e /pystata-x/src/pystata-analyzer
    pip install -q -e /pystata-x
    echo "[entrypoint] Done." >&2
fi

case "${1:-shell}" in
    unit)
        shift 1
        exec python -m pytest /pystata-x/tests/unit/ -v --tb=short "$@"
        ;;
    e2e)
        shift 1
        exec python -m pytest /pystata-x/tests/e2e/ -m requires_stata -v --tb=short "$@"
        ;;
    framework)
        shift 1
        python -m pytest /pystata-x/src/pystata-analyzer/tests/test_analyzer.py -v --tb=short "$@"
        exec python -m pytest /pystata-x/src/pystata-analyzer/tests/test_integration.py -v --tb=short "$@"
        ;;
    all-tests|all)
        shift 1
        python -m pytest /pystata-x/tests/unit/ -v --tb=short "$@"
        python -m pytest /pystata-x/src/pystata-analyzer/tests/test_analyzer.py -v --tb=short "$@"
        python -m pytest /pystata-x/tests/e2e/ -m requires_stata -v --tb=short "$@"
        exec python -m pytest /pystata-x/src/pystata-analyzer/tests/test_integration.py -v --tb=short "$@"
        ;;
    analyze)
        shift 1
        FUNC="${1:-_bist_data}"
        exec python -c "
from pystata_analyzer import StataBinary
b = StataBinary('$STATA_LIB_PATH')
b.analyze()
import json, sys
proto = b.analyze_full_protocol('$FUNC')
print(json.dumps(proto, indent=2, default=str))
"
        ;;
    catalog)
        shift 1
        exec python -c "
from pystata_analyzer import StataBinary
b = StataBinary('$STATA_LIB_PATH')
b.analyze()
print(f'{\"Function\":30s} {\"Idx\":5s} {\"Type\":18s} {\"Stack\":6s} {\"EDI\":10s}')
print('=' * 70)
for name in sorted(b.symbols):
    if name.startswith('_bist_') and name != '_bist_store':
        p = b.analyze_full_protocol(name)
        di = str(p.get('dispatch_index', '?'))
        pt = p.get('protocol_type', '?')
        us = 'YES' if p.get('uses_push_stack') else 'no'
        ec = ','.join(str(e['checks']) for e in p.get('edi_checks', [])[:3])
        print(f'{name:30s} {di:5s} {pt:18s} {us:6s} {ec:10s}')
" 2>&1 | head -50
        ;;
    shell)
        exec bash
        ;;
    *)
        if [ -n "$1" ]; then
            exec "$@"
        else
            exec bash
        fi
        ;;
esac
