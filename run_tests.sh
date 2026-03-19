#!/usr/bin/env bash
# Esegue l'intera suite di test con coverage report.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Attiva virtualenv se presente
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

echo "========================================"
echo "  Trading Assistant — Test Suite"
echo "========================================"
echo ""

# Esegui pytest con coverage
if python -m pytest tests/ -v --tb=short --cov=modules --cov-report=term-missing "$@"; then
    echo ""
    echo "========================================"
    echo "  ✅ Suite completata — tutti i test passati"
    echo "========================================"
    exit 0
else
    FAILURES=$?
    echo ""
    echo "========================================"
    echo "  ❌ Test falliti: exit code $FAILURES"
    echo "========================================"
    exit 1
fi
