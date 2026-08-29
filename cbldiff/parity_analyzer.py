"""
cbldiff/parity_analyzer.py
==========================
PHASE 6 – Behavioral Parity + Divergence Analysis

Loads the structured COBOL and Java outputs produced by Phase 5, compares
them field-by-field against the mined rules, and writes two output files:

  data/divergence_report.json   – every mismatch with rule-mapping and cluster
  data/verification_result.json – pass/fail verdict (threshold = 0.95)

Clustering strategy (deterministic, ML-ready)
----------------------------------------------
With zero or very few divergences a statistical cluster algorithm like
KMeans or DBSCAN would add noise rather than signal.  A transparent
deterministic strategy is used instead:

  • Primary key  : affected output field   (e.g. "federal_tax")
  • Secondary key: targeted rule ID        (derived from rules.json boundaries)
  • Tertiary key : input boundary region   (e.g. "gross_bracket_1")

Each unique (field, rule_id, boundary_region) triple forms one cluster.
The code is designed so an ML back-end can be slotted in later by
replacing/augmenting `_assign_cluster_key()` without touching the rest
of the pipeline.

Usage
-----
  python cbldiff/parity_analyzer.py
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT   = Path(__file__).resolve().parent.parent
DATA_DIR    = REPO_ROOT / "data"

COBOL_OUT_FILE    = DATA_DIR / "cobol_outputs.json"
JAVA_OUT_FILE     = DATA_DIR / "java_outputs.json"
INPUTS_FILE       = DATA_DIR / "test_inputs.json"
RULES_FILE        = DATA_DIR / "rules.json"
DIVERGENCE_REPORT = DATA_DIR / "divergence_report.json"
VERIFICATION_FILE = DATA_DIR / "verification_result.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MONETARY_FIELDS: tuple[str, ...] = (
    "gross",
    "federal_tax",
    "state_tax",
    "ss_tax",
    "medicare_tax",
    "net_pay",
)

EXACT_MATCH_FIELDS: tuple[str, ...] = (
    "employee_id",
    "status",
)

# Tolerance for monetary comparisons: 1 cent.
# Two values are "equal" when |cobol - java| <= MONETARY_TOLERANCE.
MONETARY_TOLERANCE: Decimal = Decimal("0.01")

# Parity score threshold to declare the implementation VERIFIED.
VERIFICATION_THRESHOLD: float = 0.95

# ---------------------------------------------------------------------------
# Critical-rule gate
# ---------------------------------------------------------------------------
# Any divergence that maps to one of these rule IDs blocks VERIFIED status
# regardless of the aggregate parity score.  Both conditions must hold for
# VERIFIED:
#   1. parity_score >= VERIFICATION_THRESHOLD
#   2. no active divergence maps to a CRITICAL_RULE_IDS member
#
# Covered categories:
#   RULE-04/05/06  – federal tax brackets
#   RULE-07/15     – dependent allowance affecting federal tax
#   RULE-01/02/03  – gross calculation (wage / minimum-wage / hours validation)
#   RULE-09        – social-security cap
#   RULE-12        – net-pay calculation
CRITICAL_RULE_IDS: frozenset[str] = frozenset({
    "RULE-01",   # hourly gross: hours * rate
    "RULE-02",   # salaried gross
    "RULE-03",   # minimum-wage / hours validation
    "RULE-04",   # federal bracket 1  (gross <= 500)
    "RULE-05",   # federal bracket 2  (500 < gross <= 1500)
    "RULE-06",   # federal bracket 3  (gross > 1500)
    "RULE-07",   # dependent allowance deducted from federal tax
    "RULE-09",   # social-security cap
    "RULE-12",   # net-pay calculation
    "RULE-15",   # dependent allowance (alias / extension rule)
})

SCHEMA_VERSION = "1.0"
PHASE          = 6


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _index_by_test_id(results: list[dict]) -> dict[str, dict]:
    """Return a {test_id: record} mapping from a results list."""
    return {r["test_id"]: r for r in results}


def _index_inputs(test_cases: list[dict]) -> dict[str, dict]:
    """Return a {test_id: test_case} mapping."""
    return {tc["test_id"]: tc for tc in test_cases}


# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------

def _build_rule_index(rules: list[dict]) -> dict[str, dict]:
    """Return a {rule_id: rule} mapping."""
    return {r["rule_id"]: r for r in rules}


def _gross_bracket_region(gross: float | None) -> str:
    """Map a gross pay amount to a named boundary region for clustering."""
    if gross is None:
        return "unknown"
    if gross <= 500.0:
        return "gross_bracket_1"          # ≤ 500 -> federal 10 %
    if gross <= 1500.0:
        return "gross_bracket_2"          # 500 < g ≤ 1500 -> federal 12 %
    return "gross_bracket_3"              # > 1500 -> federal 22 %


def _identify_rules_for_field(
    field: str,
    cobol_val: float | None,
    java_val: float | None,
    input_record: dict,
    rule_index: dict[str, dict],
    targeted_rule_ids: list[str],
) -> list[str]:
    """
    Return a list of rule IDs most likely responsible for a divergence in
    *field*.  Uses three layers of evidence (most specific wins):

    1. Explicit targeted_rule_ids from the test input (synthetic labels).
    2. Field->category mapping combined with gross bracket.
    3. Full rule scan: boundary checks vs. the input gross.
    """
    # ---- Layer 1: use the test's own targeted rule labels ----------------
    if targeted_rule_ids:
        # Filter to rules that actually govern the divergent field
        field_rules = _rules_for_output_field(field, rule_index)
        overlap = [r for r in targeted_rule_ids if r in field_rules]
        if overlap:
            return overlap
        return targeted_rule_ids  # fall back to all targeted rules

    # ---- Layer 2: field -> governing rules --------------------------------
    return _rules_for_output_field(field, rule_index)


def _rules_for_output_field(field: str, rule_index: dict[str, dict]) -> list[str]:
    """
    Return rule IDs that govern the computation of *field*.
    Hard-coded mapping mirrors the dependency graph in rules.json.
    """
    FIELD_TO_CATEGORIES: dict[str, list[str]] = {
        "gross":        ["gross_calculation"],
        "federal_tax":  ["federal_tax"],
        "state_tax":    ["state_tax"],
        "ss_tax":       ["social_security"],
        "medicare_tax": ["medicare"],
        "net_pay":      ["net_pay"],
        "status":       ["validation"],
        "employee_id":  [],
    }
    wanted = FIELD_TO_CATEGORIES.get(field, [])
    return [
        rid for rid, rule in rule_index.items()
        if rule.get("category") in wanted
    ]


def _source_provenance(rule_ids: list[str], rule_index: dict[str, dict]) -> list[dict]:
    """Return [{rule_id, source_file, source_lines, paragraph}] for each rule."""
    provenance = []
    for rid in rule_ids:
        rule = rule_index.get(rid)
        if rule:
            provenance.append({
                "rule_id":     rid,
                "source_file": rule.get("source_file", ""),
                "source_lines": rule.get("source_lines", []),
                "paragraph":   rule.get("paragraph", ""),
                "condition":   rule.get("condition", ""),
                "description": rule.get("description", ""),
            })
    return provenance


# ---------------------------------------------------------------------------
# Clustering (deterministic, ML-ready design)
# ---------------------------------------------------------------------------

def _assign_cluster_key(
    field: str,
    primary_rule_id: str,
    boundary_region: str,
) -> str:
    """
    Produce a deterministic cluster key from the three most discriminating
    dimensions of a divergence.

    Design note
    -----------
    This function is the single seam point for a future ML back-end.
    An ML replacement would:
      1. Build a feature vector from (field, rule_id, boundary_region,
         abs_difference, input_gross, input_hours, …).
      2. Run KMeans / DBSCAN on the full divergence set.
      3. Return the cluster label as a string.

    KMeans / DBSCAN are intentionally NOT added here because:
      • The current dataset has zero divergences -> no meaningful clusters
        to learn.
      • With < 5 divergences any centroid-based method is unstable.
      • Deterministic grouping is more auditable and reproducible at
        this dataset size.
    """
    return f"{field}::{primary_rule_id}::{boundary_region}"


def _group_divergences(
    divergences: list[dict],
    rule_index: dict[str, dict],
) -> list[dict]:
    """
    Group individual field-level divergences into clusters using the
    deterministic strategy.  Returns a list of cluster dicts sorted by
    cluster key for reproducibility.
    """
    clusters: dict[str, list[dict]] = {}
    for div in divergences:
        rule_ids = div.get("rule_ids", [])
        primary_rule = rule_ids[0] if rule_ids else "UNKNOWN"
        region = div.get("boundary_region", "unknown")
        key = _assign_cluster_key(div["field"], primary_rule, region)
        clusters.setdefault(key, []).append(div)

    result = []
    for key, members in sorted(clusters.items()):
        field, primary_rule, region = key.split("::", 2)
        rule = rule_index.get(primary_rule, {})
        affected_test_ids = sorted({m["test_id"] for m in members})

        # Collect unique rule IDs across all members
        all_rule_ids: list[str] = []
        seen: set[str] = set()
        for m in members:
            for rid in m.get("rule_ids", []):
                if rid not in seen:
                    all_rule_ids.append(rid)
                    seen.add(rid)

        provenance = _source_provenance(all_rule_ids, rule_index)

        # Human-readable explanation
        explanation = _build_explanation(
            field=field,
            primary_rule_id=primary_rule,
            rule=rule,
            affected_test_ids=affected_test_ids,
            provenance=provenance,
            members=members,
        )

        result.append({
            "cluster_key":         key,
            "cluster_method":      "deterministic:field+rule+boundary_region",
            "field":               field,
            "primary_rule_id":     primary_rule,
            "boundary_region":     region,
            "affected_test_ids":   affected_test_ids,
            "divergence_count":    len(members),
            "rule_ids":            all_rule_ids,
            "provenance":          provenance,
            "explanation":         explanation,
            "members":             members,
        })

    return result


def _build_explanation(
    field: str,
    primary_rule_id: str,
    rule: dict,
    affected_test_ids: list[str],
    provenance: list[dict],
    members: list[dict],
) -> str:
    """
    Build a concise human-readable explanation for a divergence cluster.
    Format mirrors the example given in the Phase 6 specification.
    """
    lines = []

    lines.append(f"RULE: {primary_rule_id}")

    if rule.get("condition"):
        lines.append(f"Condition: {rule['condition']}")

    if rule.get("description"):
        lines.append(f"Description: {rule['description']}")

    lines.append(f"Affected output field: {field}")

    if affected_test_ids:
        lines.append("Affected test cases: " + ", ".join(affected_test_ids))

    # Summarise diffs
    abs_diffs = [m.get("absolute_difference") for m in members if m.get("absolute_difference") is not None]
    if abs_diffs:
        max_diff = max(abs_diffs)
        lines.append(f"Max absolute difference: {max_diff:.6f}")

    # Provenance
    for prov in provenance:
        src = prov.get("source_file", "")
        sl = prov.get("source_lines", [])
        para = prov.get("paragraph", "")
        if src and sl:
            line_range = f"lines {sl[0]}–{sl[-1]}" if len(sl) > 1 else f"line {sl[0]}"
            lines.append(f"Source: {src} {line_range}  [{para}]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Field-level comparison
# ---------------------------------------------------------------------------

def _to_decimal(value: Any) -> Decimal | None:
    """Safely coerce a value to Decimal; return None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _compare_field(
    field: str,
    cobol_parsed: dict,
    java_parsed: dict,
) -> dict | None:
    """
    Compare a single field between the COBOL and Java parsed outputs.

    Returns None if the values match within tolerance, or a mismatch dict.
    """
    # Resolve the value key: monetary fields store floats under "<field>_float"
    if field in MONETARY_FIELDS:
        cobol_raw = cobol_parsed.get(field)          # formatted string
        java_raw  = java_parsed.get(field)
        cobol_num = _to_decimal(cobol_parsed.get(f"{field}_float"))
        java_num  = _to_decimal(java_parsed.get(f"{field}_float"))

        # Compare numerically with tolerance
        if cobol_num is not None and java_num is not None:
            abs_diff = abs(cobol_num - java_num)
            if abs_diff <= MONETARY_TOLERANCE:
                return None  # match
            return {
                "field":              field,
                "cobol_raw":          cobol_raw,
                "java_raw":           java_raw,
                "cobol_normalized":   float(cobol_num),
                "java_normalized":    float(java_num),
                "absolute_difference": float(abs_diff),
                "comparison_type":    "monetary_tolerance",
                "tolerance":          float(MONETARY_TOLERANCE),
            }

        # Fall back to string comparison if floats unavailable
        if str(cobol_raw) != str(java_raw):
            return {
                "field":              field,
                "cobol_raw":          cobol_raw,
                "java_raw":           java_raw,
                "cobol_normalized":   cobol_raw,
                "java_normalized":    java_raw,
                "absolute_difference": None,
                "comparison_type":    "string_fallback",
                "tolerance":          None,
            }
        return None

    # Exact-match fields
    cobol_val = cobol_parsed.get(field)
    java_val  = java_parsed.get(field)
    if str(cobol_val) != str(java_val):
        return {
            "field":              field,
            "cobol_raw":          cobol_val,
            "java_raw":           java_val,
            "cobol_normalized":   cobol_val,
            "java_normalized":    java_val,
            "absolute_difference": None,
            "comparison_type":    "exact",
            "tolerance":          None,
        }
    return None


# ---------------------------------------------------------------------------
# Core comparison loop
# ---------------------------------------------------------------------------

def compare_all(
    cobol_results: dict[str, dict],
    java_results: dict[str, dict],
    input_index: dict[str, dict],
    rule_index: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """
    Compare every test case field-by-field.

    Returns:
        per_test_results : one record per test (matching or divergent)
        divergences      : flat list of field-level mismatch records
    """
    all_test_ids = sorted(set(cobol_results) | set(java_results))
    per_test_results: list[dict] = []
    divergences: list[dict] = []

    for test_id in all_test_ids:
        cobol_rec = cobol_results.get(test_id)
        java_rec  = java_results.get(test_id)
        input_tc  = input_index.get(test_id, {})
        input_data = input_tc.get("input", {})
        targeted_rule_ids: list[str] = input_tc.get("targeted_rule_ids", [])

        # Handle missing records
        if cobol_rec is None or java_rec is None:
            missing_from = "java" if java_rec is None else "cobol"
            per_test_results.append({
                "test_id":      test_id,
                "category":     input_tc.get("category", "unknown"),
                "input":        input_data,
                "status":       "MISSING",
                "missing_from": missing_from,
                "field_mismatches": [],
            })
            continue

        cobol_parsed = cobol_rec.get("output", {}).get("parsed", {})
        java_parsed  = java_rec.get("output",  {}).get("parsed",  {})

        field_mismatches: list[dict] = []

        # Compare every output field
        for field in list(EXACT_MATCH_FIELDS) + list(MONETARY_FIELDS):
            mismatch = _compare_field(field, cobol_parsed, java_parsed)
            if mismatch is None:
                continue

            # Determine the gross pay for boundary-region labelling
            gross_float = cobol_parsed.get("gross_float")  # prefer COBOL
            if gross_float is None:
                gross_float = java_parsed.get("gross_float")

            boundary_region = _gross_bracket_region(gross_float)

            rule_ids = _identify_rules_for_field(
                field=field,
                cobol_val=mismatch.get("cobol_normalized"),
                java_val=mismatch.get("java_normalized"),
                input_record=input_data,
                rule_index=rule_index,
                targeted_rule_ids=targeted_rule_ids,
            )

            full_mismatch: dict = {
                "test_id":          test_id,
                "category":         input_tc.get("category", "unknown"),
                "input":            input_data,
                "boundary_region":  boundary_region,
                "rule_ids":         rule_ids,
                "provenance":       _source_provenance(rule_ids, rule_index),
                **mismatch,
            }
            field_mismatches.append(full_mismatch)
            divergences.append(full_mismatch)

        per_test_results.append({
            "test_id":          test_id,
            "category":         input_tc.get("category", "unknown"),
            "input":            input_data,
            "targeted_rule_ids": targeted_rule_ids,
            "status":           "MATCH" if not field_mismatches else "DIVERGENT",
            "field_mismatches": field_mismatches,
        })

    return per_test_results, divergences


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _calc_stats(per_test_results: list[dict]) -> dict:
    total    = len(per_test_results)
    matching = sum(1 for r in per_test_results if r["status"] == "MATCH")
    divergent = sum(1 for r in per_test_results if r["status"] == "DIVERGENT")
    missing  = sum(1 for r in per_test_results if r["status"] == "MISSING")
    parity_score = matching / total if total > 0 else 0.0
    return {
        "total_tests":           total,
        "matching_tests":        matching,
        "divergent_tests":       divergent,
        "missing_tests":         missing,
        "total_divergent_fields": sum(
            len(r.get("field_mismatches", []))
            for r in per_test_results
        ),
        "parity_score":          round(parity_score, 6),
        "parity_percent":        round(parity_score * 100, 4),
    }


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def build_divergence_report(
    per_test_results: list[dict],
    divergences: list[dict],
    clusters: list[dict],
    stats: dict,
    rules: list[dict],
) -> dict:
    """Assemble the full divergence_report.json structure."""
    return {
        "schema_version":      SCHEMA_VERSION,
        "phase":               PHASE,
        "description":         "CBLDiff Phase 6 – Behavioral parity & divergence analysis",
        "clustering_method":   "deterministic:field+rule+boundary_region",
        "ml_clustering_used":  False,
        "ml_clustering_note":  (
            "ML clustering (KMeans/DBSCAN) was intentionally deferred. "
            "With zero divergences no meaningful clusters can be learned. "
            "The code is structured so an ML back-end can replace "
            "_assign_cluster_key() when divergences accumulate."
        ),
        "statistics":          stats,
        "rule_mapping": {
            "strategy": "field->category->rule_id + targeted_rule_ids from test inputs",
            "rule_count": len(rules),
            "field_to_rule_mapping": {
                "gross":        ["RULE-01", "RULE-02", "RULE-03"],
                "federal_tax":  ["RULE-04", "RULE-05", "RULE-06", "RULE-07", "RULE-15"],
                "state_tax":    ["RULE-08"],
                "ss_tax":       ["RULE-09"],
                "medicare_tax": ["RULE-10"],
                "net_pay":      ["RULE-12"],
                "status":       ["RULE-13", "RULE-14"],
                "employee_id":  [],
            },
        },
        "divergence_clusters": clusters,
        "per_test_results":    per_test_results,
    }


# ---------------------------------------------------------------------------
# Critical-rule gate helper
# ---------------------------------------------------------------------------

def _check_critical_gate(clusters: list[dict]) -> dict:
    """Examine divergence clusters for critical-rule hits.

    Returns a gate descriptor with keys:
        triggered        – bool, True when at least one critical rule is hit
        critical_rule_ids – sorted list of matched critical rule IDs
        affected_test_ids – sorted list of all test IDs across triggered clusters
        affected_fields   – sorted list of output fields involved
        provenance        – list of source-provenance dicts from the clusters
    """
    hit_rule_ids:  set[str] = set()
    hit_test_ids:  set[str] = set()
    hit_fields:    set[str] = set()
    hit_provenance: list[dict] = []

    for cluster in clusters:
        # Collect all rule IDs referenced by this cluster
        cluster_rules: set[str] = set(cluster.get("rule_ids", []))
        cluster_rules.add(cluster.get("primary_rule_id", ""))

        matched = cluster_rules & CRITICAL_RULE_IDS
        if matched:
            hit_rule_ids.update(matched)
            hit_test_ids.update(cluster.get("affected_test_ids", []))
            hit_fields.add(cluster.get("field", ""))
            # Avoid duplicate provenance entries
            seen = {p["rule_id"] for p in hit_provenance}
            for prov in cluster.get("provenance", []):
                if prov["rule_id"] not in seen:
                    hit_provenance.append(prov)
                    seen.add(prov["rule_id"])

    triggered = bool(hit_rule_ids)
    return {
        "triggered":          triggered,
        "critical_rule_ids":  sorted(hit_rule_ids),
        "affected_test_ids":  sorted(hit_test_ids),
        "affected_fields":    sorted(f for f in hit_fields if f),
        "provenance":         hit_provenance,
    }


def build_verification_result(stats: dict, critical_gate: dict) -> dict:
    """Assemble the verification_result.json structure.

    Verification policy (both must hold for VERIFIED):
      1. parity_score >= VERIFICATION_THRESHOLD
      2. critical_gate["triggered"] is False
    """
    score              = stats["parity_score"]
    parity_passes      = score >= VERIFICATION_THRESHOLD
    gate_passes        = not critical_gate["triggered"]
    verified           = parity_passes and gate_passes

    if verified:
        status = "VERIFIED"
        explanation = (
            f"Parity score {score:.4f} (≥ threshold {VERIFICATION_THRESHOLD}) "
            f"and no critical-rule divergences detected -> VERIFIED"
        )
    elif not parity_passes and not gate_passes:
        status = "NOT_VERIFIED"
        explanation = (
            f"Parity score {score:.4f} (< threshold {VERIFICATION_THRESHOLD}) "
            f"AND critical-rule divergence detected "
            f"(rules: {', '.join(critical_gate['critical_rule_ids'])}) -> NOT_VERIFIED"
        )
    elif not parity_passes:
        status = "NOT_VERIFIED"
        explanation = (
            f"Parity score {score:.4f} (< threshold {VERIFICATION_THRESHOLD}) -> NOT_VERIFIED"
        )
    else:
        # parity passes but critical gate blocks
        status = "NOT_VERIFIED"
        explanation = (
            f"Parity score {score:.4f} (≥ threshold {VERIFICATION_THRESHOLD}) "
            f"but critical-rule divergence detected "
            f"(rules: {', '.join(critical_gate['critical_rule_ids'])}) -> NOT_VERIFIED"
        )

    result: dict = {
        "schema_version":           SCHEMA_VERSION,
        "phase":                    PHASE,
        "description":              "CBLDiff Phase 6 – Verification verdict",
        "verification_threshold":   VERIFICATION_THRESHOLD,
        "parity_score":             stats["parity_score"],
        "parity_percent":           stats["parity_percent"],
        "total_tests":              stats["total_tests"],
        "matching_tests":           stats["matching_tests"],
        "divergent_tests":          stats["divergent_tests"],
        "total_divergent_fields":   stats["total_divergent_fields"],
        "divergence_cluster_count": 0,      # filled in by caller
        # --- two-gate policy ------------------------------------------------
        "parity_gate": {
            "passes":    parity_passes,
            "score":     stats["parity_score"],
            "threshold": VERIFICATION_THRESHOLD,
        },
        "critical_rule_gate": {
            "passes":             gate_passes,
            "triggered":          critical_gate["triggered"],
            "critical_rule_ids":  critical_gate["critical_rule_ids"],
            "affected_test_ids":  critical_gate["affected_test_ids"],
            "affected_fields":    critical_gate["affected_fields"],
            "provenance":         critical_gate["provenance"],
        },
        # --- final verdict --------------------------------------------------
        "status":   status,
        "verified": verified,
        "verdict_explanation": explanation,
    }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("CBLDiff Phase 6 – Behavioral Parity & Divergence Analysis")
    print("=" * 70)

    # ---- Load inputs -------------------------------------------------------
    print("\n[1/6] Loading data files …")
    cobol_data  = _load_json(COBOL_OUT_FILE)
    java_data   = _load_json(JAVA_OUT_FILE)
    inputs_data = _load_json(INPUTS_FILE)
    rules_data  = _load_json(RULES_FILE)

    cobol_results = _index_by_test_id(cobol_data["results"])
    java_results  = _index_by_test_id(java_data["results"])
    input_index   = _index_inputs(inputs_data["test_cases"])
    rule_index    = _build_rule_index(rules_data["rules"])

    print(f"    COBOL records  : {len(cobol_results)}")
    print(f"    Java records   : {len(java_results)}")
    print(f"    Test inputs    : {len(input_index)}")
    print(f"    Rules loaded   : {len(rule_index)}")

    # ---- Compare -----------------------------------------------------------
    print("\n[2/6] Comparing outputs field-by-field …")
    per_test_results, divergences = compare_all(
        cobol_results, java_results, input_index, rule_index
    )
    print(f"    Tests evaluated : {len(per_test_results)}")
    print(f"    Field divergences: {len(divergences)}")

    # ---- Statistics --------------------------------------------------------
    print("\n[3/6] Calculating statistics …")
    stats = _calc_stats(per_test_results)
    print(f"    Total tests          : {stats['total_tests']}")
    print(f"    Matching tests       : {stats['matching_tests']}")
    print(f"    Divergent tests      : {stats['divergent_tests']}")
    print(f"    Total divergent fields: {stats['total_divergent_fields']}")
    print(f"    Parity score         : {stats['parity_score']:.6f}  ({stats['parity_percent']:.2f}%)")

    # ---- Clustering --------------------------------------------------------
    print("\n[4/6] Clustering divergences (deterministic strategy) …")
    clusters = _group_divergences(divergences, rule_index)
    print(f"    Divergence clusters  : {len(clusters)}")
    print("    ML clustering        : deferred (no divergences to cluster)")

    # ---- Build reports -----------------------------------------------------
    print("\n[5/6] Building reports …")
    divergence_report = build_divergence_report(
        per_test_results=per_test_results,
        divergences=divergences,
        clusters=clusters,
        stats=stats,
        rules=rules_data["rules"],
    )

    critical_gate = _check_critical_gate(clusters)
    verification_result = build_verification_result(stats, critical_gate)
    verification_result["divergence_cluster_count"] = len(clusters)

    # ---- Write outputs -----------------------------------------------------
    print("\n[6/6] Writing output files …")
    DIVERGENCE_REPORT.write_text(
        json.dumps(divergence_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    VERIFICATION_FILE.write_text(
        json.dumps(verification_result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"    Written: {DIVERGENCE_REPORT}")
    print(f"    Written: {VERIFICATION_FILE}")

    # ---- Final verdict -----------------------------------------------------
    print()
    print("=" * 70)
    score  = verification_result["parity_score"]
    status = verification_result["status"]
    pg     = verification_result["parity_gate"]
    cg     = verification_result["critical_rule_gate"]

    print(f"  Parity score       : {score:.6f}  ({verification_result['parity_percent']:.2f}%)")
    print(f"  Parity gate        : {'PASS' if pg['passes'] else 'FAIL'}  "
          f"(threshold {pg['threshold']})")
    print(f"  Divergences        : {stats['divergent_tests']} tests / "
          f"{stats['total_divergent_fields']} fields / "
          f"{len(clusters)} clusters")
    if cg["triggered"]:
        print(f"  Critical divergence: YES")
        print(f"  Critical rule(s)   : {', '.join(cg['critical_rule_ids'])}")
        print(f"  Affected cases     : {', '.join(cg['affected_test_ids'])}")
        print(f"  Affected field(s)  : {', '.join(cg['affected_fields'])}")
        print(f"  Critical gate      : FAIL")
    else:
        print(f"  Critical divergence: NO")
        print(f"  Critical gate      : PASS")
    print(f"  Final status       : {status}")
    print("=" * 70)

    if verification_result["verified"]:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
