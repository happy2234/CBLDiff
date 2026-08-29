#!/usr/bin/env bash
# =============================================================
# smoke_test.sh — Phase 1 verification for payroll.cbl
# Usage: bash smoke_test.sh
#
# Compiles payroll.cbl, runs sample inputs, and asserts:
#  1. Output is a pipe-delimited record with 8 fields
#  2. Key boundary cases produce expected values
#  3. Error cases produce correct error codes
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COBOL_SRC="$SCRIPT_DIR/payroll.cbl"
BINARY="$SCRIPT_DIR/payroll"
SAMPLES="$SCRIPT_DIR/sample_inputs.txt"
PYTHON="python3"

export LC_ALL=C
export COB_DECIMAL_POINT=.

PASS=0
FAIL=0
ERRORS=()

echo "============================================="
echo "  CBLDiff Phase 1 — payroll.cbl Smoke Test"
echo "============================================="
echo ""

# ----------------------------------------------------------
# Step 1: Compile
# ----------------------------------------------------------
echo "[COMPILE] cobc -x -free -o $BINARY $COBOL_SRC"
cobc -x -free -o "$BINARY" "$COBOL_SRC" 2>&1 | grep -v '_FORTIFY_SOURCE' || true
echo "[COMPILE] OK — binary: $BINARY"
echo ""

# ----------------------------------------------------------
# Step 2: Run sample inputs and validate pipe format
# ----------------------------------------------------------
echo "[RUN] Executing all sample inputs ..."
echo ""

run_case() {
    local input="$1"
    local output
    output=$(echo "$input" | "$BINARY" 2>/dev/null)
    local field_count
    field_count=$(echo "$output" | awk -F'|' '{print NF}')
    echo "  IN : $input"
    echo "  OUT: $output  (fields: $field_count)"

    if [ "$field_count" -eq 8 ]; then
        echo "  [FIELDS] OK"
        PASS=$((PASS + 1))
    else
        echo "  [FIELDS] FAIL — expected 8 pipe-delimited fields, got $field_count"
        FAIL=$((FAIL + 1))
        ERRORS+=("Field count failed: $input -> $output")
    fi
    echo ""
}

while IFS= read -r line; do
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    run_case "$line"
done < "$SAMPLES"

# ----------------------------------------------------------
# Step 3: Boundary and arithmetic assertions
# ----------------------------------------------------------
echo "[ASSERT] Key boundary and arithmetic assertions ..."
echo ""

assert_field() {
    local label="$1"
    local input="$2"
    local field_idx="$3"    # 1-based: 1=id 2=gross 3=fed 4=state 5=ss 6=med 7=net 8=status
    local expected="$4"

    local output
    output=$(echo "$input" | "$BINARY" 2>/dev/null)
    local actual
    actual=$(echo "$output" | cut -d'|' -f"$field_idx" | tr -d ' ')

    # For monetary fields, compare as floats (strip leading zeros)
    local match="false"
    if $PYTHON -c "
import sys
a = '$actual'.strip()
e = '$expected'.strip()
try:
    match = abs(float(a) - float(e)) < 0.005
    sys.exit(0 if match else 1)
except (ValueError, TypeError):
    sys.exit(0 if a == e else 1)
" 2>/dev/null; then
        echo "  [PASS] $label: field[$field_idx] = $actual (expected $expected)"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $label: field[$field_idx] expected=$expected actual=$actual"
        echo "         input:  $input"
        echo "         output: $output"
        FAIL=$((FAIL + 1))
        ERRORS+=("$label: expected field[$field_idx]=$expected got $actual")
    fi
}

# FIELD INDEX reference:
# 1=EMPLOYEE_ID 2=GROSS 3=FEDERAL_TAX 4=STATE_TAX 5=SS_TAX 6=MEDICARE_TAX 7=NET_PAY 8=STATUS

# RULE-01: 40h * 20/hr = 800 gross
assert_field "RULE-01 gross 40h@20" "E001|40.00|20.00|N|0.00|0" 2 "800.00"

# RULE-02: 45h * 20/hr OT: 40*20 + 5*30 = 800+150 = 950
assert_field "RULE-02 OT gross 45h@20" "E002|45.00|20.00|N|0.00|0" 2 "950.00"

# RULE-04: bracket1, gross=400 -> federal = 400*0.10 = 40.00
assert_field "RULE-04 bracket1 gross=400 federal" "T03|40.00|10.00|N|0.00|0" 3 "40.00"

# RULE-05: bracket2, gross=800 -> federal = 800*0.12 = 96.00
assert_field "RULE-05 bracket2 gross=800 federal" "E001|40.00|20.00|N|0.00|0" 3 "96.00"

# RULE-05/06 KEY BOUNDARY: gross EXACTLY 1500.00 must use bracket2 (12%)
# 1500 * 0.12 = 180.00  NOT 22%
assert_field "KEY-BOUNDARY gross=1500.00 uses bracket2 (12%)" "E005|40.00|37.50|N|0.00|0" 3 "180.00"

# RULE-06: bracket3, gross=2000 -> 2000*0.22 = 440; dep=1: 440-80=360
assert_field "RULE-06 bracket3 gross=2000 dep=1 federal" "E006|40.00|50.00|N|0.00|1" 3 "360.00"

# RULE-07: gross=950 bracket2=114; dep=2: 114-160<0 -> 0
assert_field "RULE-07 dep allowance eliminates federal" "E002|45.00|20.00|N|0.00|2" 3 "0.00"

# RULE-03: salaried 2000/wk
assert_field "RULE-03 salaried gross=2000" "E007|0.00|0.00|Y|2000.00|3" 2 "2000.00"

# RULE-08: state = 3.07% of 800 = 24.56
assert_field "RULE-08 state tax gross=800" "E001|40.00|20.00|N|0.00|0" 4 "24.56"

# RULE-09: SS = 6.2% of 800 = 49.60
assert_field "RULE-09 ss_tax gross=800" "E001|40.00|20.00|N|0.00|0" 5 "49.60"

# RULE-10: medicare = 1.45% of 800 = 11.60
assert_field "RULE-10 medicare gross=800" "E001|40.00|20.00|N|0.00|0" 6 "11.60"

# RULE-09 cap: gross=4000 > 3242.31 -> SS = 3242.31 * 0.062 = 201.02
assert_field "RULE-09 SS cap gross=4000" "E009|40.00|100.00|N|0.00|0" 5 "201.02"

# RULE-12: net = 800 - 96 - 24.56 - 49.60 - 11.60 = 618.24
assert_field "RULE-12 net pay" "E001|40.00|20.00|N|0.00|0" 7 "618.24"

# RULE-13: below minimum wage -> ERR_MIN_WAGE
assert_field "RULE-13 ERR_MIN_WAGE" "E010|40.00|5.00|N|0.00|0" 8 "ERR_MIN_WAGE"

# RULE-14: hours exceeded -> ERR_HOURS
assert_field "RULE-14 ERR_HOURS" "E011|200.00|20.00|N|0.00|0" 8 "ERR_HOURS"

# RULE-04 exact: gross=500.00 is bracket1 -> 500*0.10=50
assert_field "RULE-04 exact boundary gross=500" "E004|25.00|20.00|N|0.00|0" 3 "50.00"

# RULE-06: gross JUST ABOVE 1500 -> bracket3
# 40 * 37.51 = 1500.40 -> 1500.40 * 0.22 = 330.09
assert_field "RULE-06 gross=1500.40 bracket3 (just above boundary)" "E005B|40.00|37.51|N|0.00|0" 3 "330.09"

# ----------------------------------------------------------
# Summary
# ----------------------------------------------------------
echo ""
echo "============================================="
echo "  RESULTS: $PASS passed, $FAIL failed"
echo "============================================="

if [ "${#ERRORS[@]}" -gt 0 ]; then
    echo ""
    echo "FAILURES:"
    for e in "${ERRORS[@]}"; do
        echo "  - $e"
    done
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "  ALL TESTS PASSED — payroll.cbl Phase 1 verified."
    exit 0
else
    echo "  TESTS FAILED — review output above."
    exit 1
fi
