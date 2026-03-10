#!/bin/bash
cd /home/kavia/workspace/code-generation/game-price-comparison-hub-330667-330682/compare_prices_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

