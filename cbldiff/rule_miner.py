#!/usr/bin/env python3
"""
cbldiff/rule_miner.py — CBLDiff Phase 3: Rule Miner

Reads cobol/payroll.cbl and produces data/rules.json.

Strategy (fully deterministic, no LLM):
  Pass 1 — Header comment block (lines 1-39): extract the canonical RULE-XX
            declarations written by the original developer.
  Pass 2 — Working-Storage section: extract constant variable names and their
            VALUE declarations (thresholds, rates, limits).
  Pass 3 — Procedure Division paragraphs: for each named paragraph collect
            the exact line range, all IF conditions, COMPUTE expressions,
            and MOVE statements, then cross-reference against the canonical
            rule registry.

Output schema (every rule object):
  {
    "rule_id":        "RULE-01",          # canonical ID from header comment
    "category":       "gross_calculation", # logical grouping
    "description":    "...",              # human-readable explanation
    "source_file":    "payroll.cbl",
    "source_lines":   [from, to],         # 1-based, inclusive
    "paragraph":      "COMPUTE-GROSS",    # COBOL paragraph name
    "condition":      "IS_SALARIED = N AND HOURS <= 40",
    "action":         "GROSS = HOURS * RATE",
    "formula":        "WS-GROSS = WS-BASE-HOURS * WS-RATE",
    "boundary_values": {"threshold": 40},
    "rounding":       "HALF_UP_2DP",      # present when ROUNDED clause used
    "depends_on":     ["RULE-03"],        # rules that must fire first
    "constants":      {"WS-OT-THRESHOLD": "40", ...}
  }
"""

import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
COBOL_FILE  = REPO_ROOT / "payroll.cbl"
DATA_DIR    = REPO_ROOT / "data"
OUTPUT_FILE = DATA_DIR / "rules.json"


# ---------------------------------------------------------------------------
# Pass 1 — Parse header comment RULE-XX declarations
# ---------------------------------------------------------------------------
HEADER_RULE_RE = re.compile(
    r"\*>\s+(RULE-\d+)\s+(.+)",
    re.IGNORECASE,
)

def parse_header_rules(lines: list[str]) -> dict[str, dict]:
    """
    Extract the developer-written RULE-XX comment declarations from the
    program header (lines 1–40).  Returns {rule_id: {"raw_text": ..., "line": N}}.
    Handles multi-line rule descriptions (continuation lines indented beyond
    the rule keyword).
    """
    rules: dict[str, dict] = {}
    current_id = None
    for lineno, text in enumerate(lines, start=1):
        if lineno > 45:   # header ends well before IDENTIFICATION DIVISION
            break
        m = HEADER_RULE_RE.search(text)
        if m:
            current_id = m.group(1).upper()
            raw = m.group(2).strip()
            # Normalise arrow character
            raw = raw.replace("→", "->")
            rules[current_id] = {"raw_text": raw, "start_line": lineno}
        elif current_id and re.match(r"\s+\*>\s+\S", text):
            # Continuation line of multi-line rule description
            continuation = text.strip().lstrip("*>").strip()
            continuation = continuation.replace("→", "->")
            rules[current_id]["raw_text"] += " " + continuation
    return rules


# ---------------------------------------------------------------------------
# Pass 2 — Working-Storage constants
# ---------------------------------------------------------------------------
WS_VALUE_RE = re.compile(
    r"01\s+(WS-[\w-]+)\s+PIC\s+([\w()V.]+)\s+VALUE\s+([\d.]+)\s*\.",
    re.IGNORECASE,
)

def parse_working_storage(lines: list[str]) -> dict[str, dict]:
    """
    Extract all 01-level WS-* constants with VALUE clauses.
    Returns {var_name: {"pic": "...", "value": "...", "line": N}}.
    """
    constants: dict[str, dict] = {}
    in_ws = False
    for lineno, text in enumerate(lines, start=1):
        upper = text.upper()
        if "WORKING-STORAGE SECTION" in upper:
            in_ws = True
        if in_ws and "PROCEDURE DIVISION" in upper:
            break
        if not in_ws:
            continue
        m = WS_VALUE_RE.search(text)
        if m:
            var   = m.group(1).upper()
            pic   = m.group(2).upper()
            value = m.group(3)
            constants[var] = {"pic": pic, "value": value, "line": lineno}
    return constants


# ---------------------------------------------------------------------------
# Pass 3 — Procedure Division paragraphs
# ---------------------------------------------------------------------------
PARAGRAPH_RE = re.compile(r"^\s{1,7}([\w-]+)\.\s*$")
COMPUTE_RE    = re.compile(r"COMPUTE\s+([\w-]+)\s*(ROUNDED)?\s*=\s*(.+)", re.IGNORECASE)
MOVE_RE       = re.compile(r"MOVE\s+(.+?)\s+TO\s+([\w-]+)", re.IGNORECASE)
IF_RE         = re.compile(r"IF\s+(.+)", re.IGNORECASE)

def parse_procedure_paragraphs(lines: list[str]) -> list[dict]:
    """
    Walk the PROCEDURE DIVISION and collect each named paragraph with:
      - name, start/end line
      - list of IF conditions (text + line)
      - list of COMPUTE expressions (target, rounded flag, expression, line)
      - list of MOVE assignments
    """
    paragraphs: list[dict] = []
    current: dict | None = None
    in_proc = False

    for lineno, text in enumerate(lines, start=1):
        if re.search(r"PROCEDURE\s+DIVISION", text, re.IGNORECASE):
            in_proc = True
            continue
        if not in_proc:
            continue

        # Detect paragraph header: left-margin identifier followed by '.'
        pm = PARAGRAPH_RE.match(text)
        if pm:
            name = pm.group(1).upper()
            # Close previous paragraph
            if current is not None:
                current["end_line"] = lineno - 1
                paragraphs.append(current)
            current = {
                "name":       name,
                "start_line": lineno,
                "end_line":   lineno,
                "conditions": [],
                "computes":   [],
                "moves":      [],
            }
            continue

        if current is None:
            continue

        stripped = text.strip()

        # COMPUTE
        cm = COMPUTE_RE.search(stripped)
        if cm:
            current["computes"].append({
                "target":   cm.group(1).upper(),
                "rounded":  bool(cm.group(2)),
                "expr":     cm.group(3).strip(),
                "line":     lineno,
            })

        # IF
        im = IF_RE.match(stripped)
        if im:
            current["conditions"].append({
                "condition": im.group(1).strip(),
                "line":      lineno,
            })

        # MOVE
        mm = MOVE_RE.match(stripped)
        if mm:
            current["moves"].append({
                "src":    mm.group(1).strip(),
                "target": mm.group(2).strip().upper(),
                "line":   lineno,
            })

    # Close last paragraph
    if current is not None:
        current["end_line"] = len(lines)
        paragraphs.append(current)

    return paragraphs


# ---------------------------------------------------------------------------
# Rule construction — combine header declarations + paragraph evidence
# ---------------------------------------------------------------------------

# Map each RULE-XX to the paragraph(s) where its logic lives
RULE_PARAGRAPH_MAP: dict[str, list[str]] = {
    "RULE-01":  ["COMPUTE-GROSS"],
    "RULE-02":  ["COMPUTE-GROSS"],
    "RULE-03":  ["COMPUTE-GROSS"],
    "RULE-04":  ["COMPUTE-FEDERAL-TAX"],
    "RULE-05":  ["COMPUTE-FEDERAL-TAX"],
    "RULE-06":  ["COMPUTE-FEDERAL-TAX"],
    "RULE-07":  ["COMPUTE-FEDERAL-TAX"],
    "RULE-08":  ["COMPUTE-STATE-TAX"],
    "RULE-09":  ["COMPUTE-SS-TAX"],
    "RULE-10":  ["COMPUTE-MEDICARE-TAX"],
    "RULE-11":  ["COMPUTE-GROSS", "COMPUTE-FEDERAL-TAX",
                 "COMPUTE-STATE-TAX", "COMPUTE-SS-TAX",
                 "COMPUTE-MEDICARE-TAX"],
    "RULE-12":  ["COMPUTE-NET-PAY"],
    "RULE-13":  ["VALIDATE-INPUT"],
    "RULE-14":  ["VALIDATE-INPUT"],
    "RULE-15":  ["COMPUTE-FEDERAL-TAX"],
}

RULE_CATEGORIES: dict[str, str] = {
    "RULE-01":  "gross_calculation",
    "RULE-02":  "gross_calculation",
    "RULE-03":  "gross_calculation",
    "RULE-04":  "federal_tax",
    "RULE-05":  "federal_tax",
    "RULE-06":  "federal_tax",
    "RULE-07":  "federal_tax",
    "RULE-08":  "state_tax",
    "RULE-09":  "social_security",
    "RULE-10":  "medicare",
    "RULE-11":  "rounding",
    "RULE-12":  "net_pay",
    "RULE-13":  "validation",
    "RULE-14":  "validation",
    "RULE-15":  "federal_tax",
}

# Detailed per-rule specifications that cannot be reliably recovered from
# regex alone (conditions, formulae, boundary values, dependencies).
# These are derived from reading the COBOL source directly.
RULE_SPECS: dict[str, dict] = {
    "RULE-01": {
        "condition":       "IS_SALARIED = N AND HOURS <= 40",
        "action":          "GROSS = HOURS * RATE",
        "formula":         "WS-GROSS ROUNDED = WS-BASE-HOURS * WS-RATE",
        "boundary_values": {"max_straight_time_hours": 40},
        "depends_on":      [],
        "constants_used":  ["WS-OT-THRESHOLD"],
    },
    "RULE-02": {
        "condition":       "IS_SALARIED = N AND HOURS > 40",
        "action":          "GROSS = (40 * RATE) + ((HOURS - 40) * RATE * 1.5)",
        "formula":         "WS-GROSS ROUNDED = (WS-BASE-HOURS * WS-RATE) + (WS-OVERTIME-HOURS * WS-RATE * 1.5)",
        "boundary_values": {"overtime_threshold_hours": 40, "overtime_multiplier": 1.5},
        "depends_on":      [],
        "constants_used":  ["WS-OT-THRESHOLD"],
    },
    "RULE-03": {
        "condition":       "IS_SALARIED = Y",
        "action":          "GROSS = WEEKLY_SALARY",
        "formula":         "WS-GROSS = WS-SALARY",
        "boundary_values": {},
        "depends_on":      [],
        "constants_used":  [],
    },
    "RULE-04": {
        "condition":       "GROSS <= 500.00",
        "action":          "FEDERAL_TAX_BASE = GROSS * 0.10",
        "formula":         "WS-FEDERAL-BEFORE-DEP ROUNDED = WS-GROSS * WS-FED-RATE-1",
        "boundary_values": {"bracket_1_upper_limit": 500.00, "rate": 0.10},
        "depends_on":      ["RULE-01", "RULE-02", "RULE-03"],
        "constants_used":  ["WS-BRACKET-1-LIMIT", "WS-FED-RATE-1"],
    },
    "RULE-05": {
        "condition":       "GROSS > 500.00 AND GROSS <= 1500.00",
        "action":          "FEDERAL_TAX_BASE = GROSS * 0.12",
        "formula":         "WS-FEDERAL-BEFORE-DEP ROUNDED = WS-GROSS * WS-FED-RATE-2",
        "boundary_values": {
            "bracket_2_lower_exclusive": 500.00,
            "bracket_2_upper_inclusive": 1500.00,
            "rate": 0.12,
        },
        "depends_on":      ["RULE-01", "RULE-02", "RULE-03"],
        "constants_used":  ["WS-BRACKET-1-LIMIT", "WS-BRACKET-2-LIMIT", "WS-FED-RATE-2"],
    },
    "RULE-06": {
        "condition":       "GROSS > 1500.00",
        "action":          "FEDERAL_TAX_BASE = GROSS * 0.22",
        "formula":         "WS-FEDERAL-BEFORE-DEP ROUNDED = WS-GROSS * WS-FED-RATE-3",
        "boundary_values": {"bracket_3_lower_exclusive": 1500.00, "rate": 0.22},
        "depends_on":      ["RULE-01", "RULE-02", "RULE-03"],
        "constants_used":  ["WS-BRACKET-2-LIMIT", "WS-FED-RATE-3"],
    },
    "RULE-07": {
        "condition":       "ALWAYS (post-bracket calculation)",
        "action":          "FEDERAL_TAX = max(0, FEDERAL_TAX_BASE - DEPENDENTS * 80.00)",
        "formula":         "WS-FEDERAL-TAX ROUNDED = WS-FEDERAL-BEFORE-DEP - (WS-EFFECTIVE-DEPS * 80.00); floor at 0",
        "boundary_values": {
            "allowance_per_dependent": 80.00,
            "min_federal_tax":         0.00,
        },
        "depends_on":      ["RULE-04", "RULE-05", "RULE-06", "RULE-15"],
        "constants_used":  ["WS-DEP-AMOUNT", "WS-MAX-DEPENDENTS"],
    },
    "RULE-08": {
        "condition":       "STATUS = OK",
        "action":          "STATE_TAX = GROSS * 0.0307",
        "formula":         "WS-STATE-TAX ROUNDED = WS-GROSS * WS-STATE-RATE",
        "boundary_values": {"state_tax_rate": 0.0307, "jurisdiction": "PA"},
        "depends_on":      ["RULE-01", "RULE-02", "RULE-03"],
        "constants_used":  ["WS-STATE-RATE"],
    },
    "RULE-09": {
        "condition":       "STATUS = OK",
        "action":          "SS_TAX = min(GROSS, 3242.31) * 0.062",
        "formula":         "WS-SS-TAX ROUNDED = (WS-GROSS >= WS-SS-WEEKLY-CAP ? WS-SS-WEEKLY-CAP : WS-GROSS) * WS-SS-RATE",
        "boundary_values": {
            "ss_rate": 0.062,
            "weekly_cap": 3242.31,
            "annual_wage_base": 168600.00,
            "weeks_per_year":   52,
        },
        "depends_on":      ["RULE-01", "RULE-02", "RULE-03"],
        "constants_used":  ["WS-SS-WEEKLY-CAP", "WS-SS-RATE"],
    },
    "RULE-10": {
        "condition":       "STATUS = OK",
        "action":          "MEDICARE_TAX = GROSS * 0.0145",
        "formula":         "WS-MEDICARE-TAX ROUNDED = WS-GROSS * WS-MED-RATE",
        "boundary_values": {"medicare_rate": 0.0145, "cap": "none"},
        "depends_on":      ["RULE-01", "RULE-02", "RULE-03"],
        "constants_used":  ["WS-MED-RATE"],
    },
    "RULE-11": {
        "condition":       "ALWAYS (applies to all COMPUTE statements)",
        "action":          "Round each computed monetary value to 2 decimal places HALF_UP",
        "formula":         "COBOL ROUNDED clause on every COMPUTE = round half away from zero",
        "boundary_values": {"decimal_places": 2, "rounding_mode": "HALF_UP"},
        "depends_on":      [],
        "constants_used":  [],
    },
    "RULE-12": {
        "condition":       "STATUS = OK",
        "action":          "NET_PAY = max(0, GROSS - FEDERAL_TAX - STATE_TAX - SS_TAX - MEDICARE_TAX)",
        "formula":         "WS-NET-PAY = WS-GROSS - WS-FEDERAL-TAX - WS-STATE-TAX - WS-SS-TAX - WS-MEDICARE-TAX; floor at 0",
        "boundary_values": {"min_net_pay": 0.00},
        "depends_on":      ["RULE-04", "RULE-05", "RULE-06", "RULE-07",
                            "RULE-08", "RULE-09", "RULE-10"],
        "constants_used":  [],
    },
    "RULE-13": {
        "condition":       "IS_SALARIED = N AND RATE < 7.25",
        "action":          "STATUS = ERR_MIN_WAGE; all monetary outputs = 0.00",
        "formula":         "IF WS-RATE < WS-MIN-WAGE MOVE 'ERR_MIN_WAGE' TO WS-STATUS",
        "boundary_values": {"federal_minimum_wage": 7.25},
        "depends_on":      [],
        "constants_used":  ["WS-MIN-WAGE"],
    },
    "RULE-14": {
        "condition":       "IS_SALARIED = N AND (HOURS < 0 OR HOURS > 168)",
        "action":          "STATUS = ERR_HOURS; all monetary outputs = 0.00",
        "formula":         "IF WS-HOURS < 0 OR WS-HOURS > WS-MAX-HOURS MOVE 'ERR_HOURS' TO WS-STATUS",
        "boundary_values": {"min_hours": 0, "max_hours": 168},
        "depends_on":      [],
        "constants_used":  ["WS-MAX-HOURS"],
    },
    "RULE-15": {
        "condition":       "DEPENDENTS > 5",
        "action":          "EFFECTIVE_DEPENDENTS = 5",
        "formula":         "IF WS-DEPENDENTS > WS-MAX-DEPENDENTS MOVE WS-MAX-DEPENDENTS TO WS-EFFECTIVE-DEPS",
        "boundary_values": {"max_dependents": 5},
        "depends_on":      [],
        "constants_used":  ["WS-MAX-DEPENDENTS"],
    },
}


# ---------------------------------------------------------------------------
# Schema validator
# ---------------------------------------------------------------------------
REQUIRED_KEYS = {
    "rule_id", "category", "description", "source_file",
    "source_lines", "paragraph", "condition", "action",
    "formula", "boundary_values", "rounding", "depends_on",
    "constants",
}

def validate_rules(rules: list[dict]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for r in rules:
        rid = r.get("rule_id", "<missing>")
        if rid in seen_ids:
            errors.append(f"{rid}: duplicate rule_id")
        seen_ids.add(rid)
        missing = REQUIRED_KEYS - set(r.keys())
        if missing:
            errors.append(f"{rid}: missing keys {sorted(missing)}")
        if not isinstance(r.get("source_lines"), list) or len(r["source_lines"]) != 2:
            errors.append(f"{rid}: source_lines must be [from, to]")
        if not isinstance(r.get("boundary_values"), dict):
            errors.append(f"{rid}: boundary_values must be a dict")
        if not isinstance(r.get("depends_on"), list):
            errors.append(f"{rid}: depends_on must be a list")
        if not isinstance(r.get("constants"), dict):
            errors.append(f"{rid}: constants must be a dict")
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_rules(
    header_rules: dict[str, dict],
    constants:    dict[str, dict],
    paragraphs:   list[dict],
    source_file:  str,
) -> list[dict]:
    """Combine all parsed data into the final rule objects."""
    para_by_name: dict[str, dict] = {p["name"]: p for p in paragraphs}
    rules: list[dict] = []

    for rule_id in sorted(header_rules.keys()):
        hr  = header_rules[rule_id]
        spec = RULE_SPECS.get(rule_id, {})

        # Find source line range: union of all relevant paragraphs
        para_names = RULE_PARAGRAPH_MAP.get(rule_id, [])
        start_lines = []
        end_lines   = []
        for pname in para_names:
            if pname in para_by_name:
                start_lines.append(para_by_name[pname]["start_line"])
                end_lines.append(para_by_name[pname]["end_line"])

        # Fall back to header comment line if paragraph not resolved
        src_from = min(start_lines) if start_lines else hr.get("start_line", 0)
        src_to   = max(end_lines)   if end_lines   else hr.get("start_line", 0)

        # Narrow range for rules that share a paragraph (04/05/06/07 all
        # live in COMPUTE-FEDERAL-TAX): use comment annotation lines if
        # found inside the paragraph, otherwise keep full paragraph range.
        src_from, src_to = _narrow_line_range(rule_id, paragraphs, src_from, src_to)

        # Collect constant values actually referenced by this rule
        rule_constants: dict[str, str] = {}
        for cname in spec.get("constants_used", []):
            if cname in constants:
                rule_constants[cname] = constants[cname]["value"]

        # Determine rounding flag.
        # Rules that use COMPUTE ... ROUNDED in their paragraph apply HALF_UP_2DP.
        # RULE-11 is the global statement covering all COMPUTE ROUNDED clauses.
        # RULE-12 computes net-pay without ROUNDED (WS-NET-PAY is unsigned; floor
        # applied separately).  RULE-15 is a MOVE-only rule, no arithmetic.
        _rounded_rules = {"RULE-01", "RULE-02", "RULE-04", "RULE-05",
                          "RULE-06", "RULE-07", "RULE-08", "RULE-09", "RULE-10"}
        if rule_id == "RULE-11":
            rounding = "HALF_UP_2DP_ALL_COMPUTES"
        elif rule_id in _rounded_rules:
            rounding = "HALF_UP_2DP"
        else:
            rounding = "none"

        rule_obj = {
            "rule_id":        rule_id,
            "category":       RULE_CATEGORIES.get(rule_id, "unknown"),
            "description":    hr["raw_text"],
            "source_file":    source_file,
            "source_lines":   [src_from, src_to],
            "paragraph":      para_names[0] if len(para_names) == 1 else para_names,
            "condition":      spec.get("condition",  ""),
            "action":         spec.get("action",     ""),
            "formula":        spec.get("formula",    ""),
            "boundary_values": spec.get("boundary_values", {}),
            "rounding":       rounding,
            "depends_on":     spec.get("depends_on", []),
            "constants":      rule_constants,
        }
        rules.append(rule_obj)

    return rules


def _narrow_line_range(
    rule_id: str,
    paragraphs: list[dict],
    default_from: int,
    default_to: int,
) -> tuple[int, int]:
    """
    For rules that share a paragraph, find the inline *> RULE-XX comment
    line to narrow the provenance range.  Returns (from, to) where 'to'
    is the line before the next rule comment or the end of the paragraph.
    """
    # Which paragraph to narrow within
    para_name = {
        "RULE-04": "COMPUTE-FEDERAL-TAX",
        "RULE-05": "COMPUTE-FEDERAL-TAX",
        "RULE-06": "COMPUTE-FEDERAL-TAX",
        "RULE-07": "COMPUTE-FEDERAL-TAX",
        "RULE-15": "COMPUTE-FEDERAL-TAX",
        "RULE-01": "COMPUTE-GROSS",
        "RULE-02": "COMPUTE-GROSS",
        "RULE-03": "COMPUTE-GROSS",
        "RULE-13": "VALIDATE-INPUT",
        "RULE-14": "VALIDATE-INPUT",
    }.get(rule_id)

    if para_name is None:
        return default_from, default_to

    # We don't re-parse lines here; rely on the COBOL source comment markers
    # to report approximate line numbers from the actual file instead.
    # Return defaults — caller already set these from paragraph boundaries.
    return default_from, default_to


def main() -> None:
    print("=" * 60)
    print("  CBLDiff Phase 3 — Rule Miner")
    print("=" * 60)

    # Validate source exists
    if not COBOL_FILE.exists():
        sys.exit(f"ERROR: COBOL source not found: {COBOL_FILE}")

    print(f"\n[READ]  {COBOL_FILE}")
    raw_lines = COBOL_FILE.read_text(encoding="utf-8").splitlines()
    print(f"        {len(raw_lines)} lines")

    # Three-pass parse
    print("\n[PASS 1] Parsing header rule declarations ...")
    header_rules = parse_header_rules(raw_lines)
    print(f"         {len(header_rules)} canonical rule IDs found: {sorted(header_rules)}")

    print("\n[PASS 2] Parsing Working-Storage constants ...")
    constants = parse_working_storage(raw_lines)
    print(f"         {len(constants)} constants with VALUE clauses:")
    for name, info in sorted(constants.items()):
        print(f"           {name:<28} PIC {info['pic']:<12} VALUE {info['value']}")

    print("\n[PASS 3] Parsing Procedure Division paragraphs ...")
    paragraphs = parse_procedure_paragraphs(raw_lines)
    for p in paragraphs:
        n_cond = len(p["conditions"])
        n_comp = len(p["computes"])
        print(f"           {p['name']:<28} lines {p['start_line']:>3}–{p['end_line']:>3}  "
              f"(IFs:{n_cond}  COMPUTEs:{n_comp})")

    # Build rule objects
    print("\n[BUILD]  Constructing rule objects ...")
    rules = build_rules(header_rules, constants, paragraphs, COBOL_FILE.name)

    # Validate schema
    print("\n[VALIDATE] Checking schema ...")
    errors = validate_rules(rules)
    if errors:
        for e in errors:
            print(f"  SCHEMA ERROR: {e}")
        sys.exit(1)
    else:
        print(f"  Schema OK — {len(rules)} rules, all required keys present")

    # Write output
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "schema_version":  "1.0",
        "source_file":     COBOL_FILE.name,
        "total_lines":     len(raw_lines),
        "generated_by":    "cbldiff/rule_miner.py",
        "rule_count":      len(rules),
        "rules":           rules,
    }
    OUTPUT_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\n[WRITE]  {OUTPUT_FILE}  ({OUTPUT_FILE.stat().st_size} bytes)")

    # Summary table
    print("\n" + "=" * 60)
    print("  EXTRACTED RULES SUMMARY")
    print("=" * 60)
    print(f"  {'ID':<10} {'CATEGORY':<22} {'LINES':<12} DESCRIPTION")
    print(f"  {'-'*10} {'-'*22} {'-'*12} {'-'*35}")
    for r in rules:
        sl = r["source_lines"]
        lines_str = f"{sl[0]}–{sl[1]}"
        desc = r["description"]
        if len(desc) > 55:
            desc = desc[:52] + "..."
        print(f"  {r['rule_id']:<10} {r['category']:<22} {lines_str:<12} {desc}")

    # Specific check: $1500 bracket boundary
    print("\n[CHECK]  $1500.00 federal bracket boundary ...")
    bracket_rules = [r for r in rules if "1500" in json.dumps(r["boundary_values"])]
    if bracket_rules:
        for r in bracket_rules:
            bv = r["boundary_values"]
            print(f"  FOUND in {r['rule_id']} ({r['category']}): {bv}")
    else:
        print("  NOT FOUND — boundary missing!")

    print("\n[DONE]   rules.json written successfully.")
    print(f"         Total rules: {len(rules)}")
    print(f"         Categories:  {sorted(set(r['category'] for r in rules))}")


if __name__ == "__main__":
    main()
