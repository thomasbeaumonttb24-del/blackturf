#!/bin/bash
# run_tests.sh — Exécute les tests ML + API dans le conteneur backend
set -e

echo "===================================================="
echo "  BlackTurf — Tests unitaires ML"
echo "===================================================="

# Tests ML purs (pas de DB)
echo ""
echo "→ Tests ML unitaires (ELO, Value bets, Kelly, Features, Recommandations)..."
pytest tests/test_ml_units.py -v --tb=short

echo ""
echo "→ Tests de santé..."
pytest tests/test_health.py -v --tb=short

echo ""
echo "===================================================="
echo "  ML Unit Tests DONE"
echo "===================================================="
