#!/usr/bin/env bash
# =============================================================
# java/compare.sh — CBLDiff Phase 2 parity check
# Runs each sample input through both COBOL and Java and
# reports MATCH / DIFF for every case.
# =============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
COBOL_BIN="$ROOT/payroll"
JAVA_CP="$SCRIPT_DIR"
SAMPLES="$ROOT/sample_inputs.txt"
PYTHON=python3

export LC_ALL=C
export COB_DECIMAL_POINT=.

PASS=0
FAIL=0
ERRORS=()

echo "============================================================="
echo "  CBLDiff Phase 2 — COBOL vs Java Parity Check"
echo "============================================================="
echo ""

# Rebuild COBOL binary freshly
cobc -x -free -o "$COBOL_BIN" "$ROOT/payroll.cbl" 2>&1 | grep -v '_FORTIFY_SOURCE' || true

compare_case() {
    local input="$1"
    local cobol_out java_out

    cobol_out=$(printf '%s' "$input" | "$COBOL_BIN" 2>/dev/null)
    java_out=$(printf '%s' "$input"  | java -cp "$JAVA_CP" PayrollProcessor 2>/dev/null)

    # Compare field-by-field.  Monetary fields (2–7) allow float tolerance;
    # STATUS field (8) and EMPLOYEE_ID (1) are exact.
    local cobol_fields java_fields
    IFS='|' read -ra cobol_fields <<< "$cobol_out"
    IFS='|' read -ra java_fields  <<< "$java_out"

    local match=true
    local diff_detail=""

    # Field count
    if [ "${#cobol_fields[@]}" -ne "${#java_fields[@]}" ]; then
        match=false
        diff_detail="field count mismatch: cobol=${#cobol_fields[@]} java=${#java_fields[@]}"
    else
        for i in "${!cobol_fields[@]}"; do
            local cf="${cobol_fields[$i]}"
            local jf="${java_fields[$i]}"
            if [ "$cf" = "$jf" ]; then
                continue
            fi
            # For monetary fields (indices 1–6) try float comparison
            if [ "$i" -ge 1 ] && [ "$i" -le 6 ]; then
                ok=$($PYTHON -c "
import sys
try:
    sys.exit(0 if abs(float('$cf') - float('$jf')) < 0.005 else 1)
except (ValueError, TypeError):
    sys.exit(1)
" 2>/dev/null && echo yes || echo no)
                if [ "$ok" != "yes" ]; then
                    match=false
                    diff_detail="${diff_detail} field[$((i+1))]: cobol='$cf' java='$jf'"
                fi
            else
                match=false
                diff_detail="${diff_detail} field[$((i+1))]: cobol='$cf' java='$jf'"
            fi
        done
    fi

    if $match; then
        echo "  [MATCH] $input"
        echo "          COBOL: $cobol_out"
        echo "          Java : $java_out"
        PASS=$((PASS + 1))
    else
        echo "  [DIFF]  $input"
        echo "          COBOL: $cobol_out"
        echo "          Java : $java_out"
        echo "          DELTA:$diff_detail"
        FAIL=$((FAIL + 1))
        ERRORS+=("$input → $diff_detail")
    fi
    echo ""
}

while IFS= read -r line; do
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    compare_case "$line"
done < "$SAMPLES"

echo "============================================================="
echo "  PARITY RESULTS: $PASS matched, $FAIL differed"
echo "============================================================="

if [ "${#ERRORS[@]}" -gt 0 ]; then
    echo ""
    echo "DIFFERENCES:"
    for e in "${ERRORS[@]}"; do
        echo "  - $e"
    done
    echo ""
fi

if [ "$FAIL" -eq 0 ]; then
    echo "  FULL PARITY — Java reproduces COBOL output for all sample inputs."
    exit 0
else
    echo "  PARITY FAILURES — review differences above."
    exit 1
fi
