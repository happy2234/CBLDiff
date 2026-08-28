#!/usr/bin/env bash
# =============================================================
# java/run.sh — CBLDiff Phase 2: build and run PayrollProcessor
#
# Usage:
#   cd java
#   bash run.sh                       # compile only
#   echo 'E001|40.00|20.00|N|0.00|0' | bash run.sh   # compile + run
#   bash run.sh < ../sample_inputs.txt                 # run all samples
# =============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[BUILD] javac PayrollProcessor.java"
javac "$SCRIPT_DIR/PayrollProcessor.java" -d "$SCRIPT_DIR"
echo "[BUILD] OK"

# If stdin has data (i.e. not a terminal), process each non-comment line
if [ ! -t 0 ]; then
    while IFS= read -r line; do
        [[ "$line" =~ ^#.*$ ]] && continue
        [[ -z "$line" ]] && continue
        echo "$line" | java -cp "$SCRIPT_DIR" PayrollProcessor
    done
fi
