#!/bin/bash
# Quick Start: Plato Room Musician — Synthetic Scoring
set -e
pip install -e ".[dev]" --quiet 2>/dev/null || pip install -e . --quiet 2>/dev/null || true
python3 examples/synthetic_score.py
echo ""
echo "🎉 Synthetic scoring complete — see results above!"
