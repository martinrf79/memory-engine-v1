#!/usr/bin/env bash
set -euo pipefail
export USE_FAKE_FIRESTORE=true
export PYTHONPATH=.
pytest
python tests/run_memory_regression.py
python app/smoke_test.py
python -m compileall -q app tests
