#!/bin/bash
# Quick run of 10 pipe-delimited test cases
cd /home/gaurav/cbldiff/cobol
export LC_ALL=C
export COB_DECIMAL_POINT=.

run() {
    local label="$1"
    local input="$2"
    echo "--- $label ---"
    echo "IN : $input"
    echo "OUT: $(echo "$input" | ./payroll)"
    echo ""
}

run "RULE-01: 40h at rate 20 (gross=800, bracket2)" "E001|40.00|20.00|N|0.00|0"
run "RULE-02: 45h OT, 2 deps (gross=950, dep elim)" "E002|45.00|20.00|N|0.00|2"
run "RULE-04: gross=400 bracket1 (10%)" "T03|40.00|10.00|N|0.00|0"
run "KEY BOUNDARY: gross=1500.00 exactly (bracket2 top, must be 12%)" "E005|40.00|37.50|N|0.00|0"
run "RULE-06: gross=1500.40 just above boundary (bracket3 22%)" "E005B|40.00|37.51|N|0.00|0"
run "RULE-06: gross=2000 bracket3 dep=1" "E006|40.00|50.00|N|0.00|1"
run "RULE-03: salaried 2000/wk, 3 deps" "E007|0.00|0.00|Y|2000.00|3"
run "RULE-09: SS cap gross=4000" "E009|40.00|100.00|N|0.00|0"
run "RULE-13: ERR_MIN_WAGE rate=5.00" "E010|40.00|5.00|N|0.00|0"
run "RULE-14: ERR_HOURS hours=200" "E011|200.00|20.00|N|0.00|0"
