#!/usr/bin/env python3
"""
cbldiff/dual_executor.py — CBLDiff Phase 5: Dual Executor

Runs every test case in data/test_inputs.json through both:
  1. Original COBOL executable   (./payroll via bash)
  2. Modernized Java implementation (java/PayrollBatchRunner in one JVM)

Outputs:
  data/cobol_outputs.json   — per-test COBOL results
  data/java_outputs.json    — per-test Java results
  data/execution_summary.json — aggregate statistics

Usage:
  python cbldiff/dual_executor.py

Requirements:
  - bash must be available (Git Bash / WSL) to run the COBOL ELF binary
  - java must be on PATH
  - java/PayrollProcessor.class and java/PayrollBatchRunner.class must exist
    (run: javac java/PayrollProcessor.java java/PayrollBatchRunner.java -d java)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parent.parent
DATA_DIR    = REPO_ROOT / "data"
JAVA_DIR    = REPO_ROOT / "java"
COBOL_BIN   = REPO_ROOT / "cobol" / "payroll"
INPUTS_FILE = DATA_DIR / "test_inputs.json"
COBOL_OUT   = DATA_DIR / "cobol_outputs.json"
JAVA_OUT    = DATA_DIR / "java_outputs.json"
SUMMARY_OUT = DATA_DIR / "execution_summary.json"

# ---------------------------------------------------------------------------
# Output field names (positional, 0-indexed from pipe-delimited output)
# ---------------------------------------------------------------------------
OUTPUT_FIELDS = [
    "employee_id",    # 0
    "gross",          # 1
    "federal_tax",    # 2
    "state_tax",      # 3
    "ss_tax",         # 4
    "medicare_tax",   # 5
    "net_pay",        # 6
    "status",         # 7
]

# Expected number of pipe-delimited fields in a valid output line
EXPECTED_FIELD_COUNT = len(OUTPUT_FIELDS)  # 8

# Error status values that represent expected validation failures
EXPECTED_ERROR_STATUSES = {"ERR_HOURS", "ERR_MIN_WAGE"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_output_line(raw: str, test_id: str, impl: str) -> dict[str, Any]:
    """
    Parse a single pipe-delimited output line into a structured record.

    Returns a dict with:
      - raw_output:   the original stdout string
      - fields:       list of raw field strings
      - parsed:       dict of field_name -> value
      - is_error:     True if STATUS is an error code
      - parse_ok:     True if the line could be parsed into EXPECTED_FIELD_COUNT fields
    """
    raw = raw.strip()
    parts = raw.split("|")

    if len(parts) != EXPECTED_FIELD_COUNT:
        return {
            "raw_output": raw,
            "fields": parts,
            "parsed": {},
            "is_error": False,
            "parse_ok": False,
            "parse_error": (
                f"Expected {EXPECTED_FIELD_COUNT} pipe-delimited fields, "
                f"got {len(parts)}: {raw!r}"
            ),
        }

    parsed: dict[str, Any] = {}
    for i, name in enumerate(OUTPUT_FIELDS):
        parsed[name] = parts[i].strip()

    # Convert monetary fields to float where possible (indices 1-6)
    for name in OUTPUT_FIELDS[1:7]:
        try:
            parsed[name + "_float"] = float(parsed[name])
        except ValueError:
            parsed[name + "_float"] = None

    status = parsed["status"]
    return {
        "raw_output": raw,
        "fields": parts,
        "parsed": parsed,
        "is_error": status in EXPECTED_ERROR_STATUSES,
        "parse_ok": True,
    }


def record_result(
    test_id: str,
    category: str,
    pipe_input: str,
    raw_stdout: str,
    raw_stderr: str,
    exit_code: int,
    impl: str,
) -> dict[str, Any]:
    """Build a full result record for one test case."""
    execution_ok = exit_code == 0
    stdout_clean = raw_stdout.strip()

    parsed = None
    if stdout_clean:
        parsed = parse_output_line(stdout_clean, test_id, impl)

    execution_error: str | None = None
    if not execution_ok:
        execution_error = (
            f"Process exited with code {exit_code}. stderr: {raw_stderr.strip()!r}"
        )

    return {
        "test_id":       test_id,
        "category":      category,
        "impl":          impl,
        "pipe_input":    pipe_input,
        "exit_code":     exit_code,
        "execution_ok":  execution_ok,
        "execution_error": execution_error,
        "raw_stdout":    raw_stdout,
        "raw_stderr":    raw_stderr,
        "output":        parsed,
    }


# ---------------------------------------------------------------------------
# COBOL Execution
# ---------------------------------------------------------------------------

def run_cobol_all(test_cases: list[dict]) -> list[dict[str, Any]]:
    """
    Execute every test case through the COBOL binary.

    Each invocation uses bash so the Linux ELF binary (./payroll) can run on
    Windows via Git Bash / WSL.  One process per test case — the COBOL program
    is single-record (reads exactly one line then exits), so batching is not
    possible without modifying the binary.

    Environment follows IO_CONTRACT.md:
      LC_ALL=C
      COB_DECIMAL_POINT=.

    IMPORTANT: bash is invoked with cwd=REPO_ROOT and the binary is referenced
    as "./payroll" (relative) so that bash sees the WSL/Unix path rather than
    the Windows absolute path.
    """
    results = []
    env = {**os.environ, "LC_ALL": "C", "COB_DECIMAL_POINT": "."}

    # Confirm the binary exists (Windows path check)
    if not COBOL_BIN.exists():
        _abort(f"COBOL binary not found: {COBOL_BIN}")

    print(f"[COBOL] Running {len(test_cases)} tests via bash -> {COBOL_BIN.name}")
    t0 = time.monotonic()

    for tc in test_cases:
        test_id    = tc["test_id"]
        category   = tc["category"]
        pipe_input = tc["pipe_input"]

        # Use bash with a relative path ("./payroll") and cwd set to the repo
        # root so that bash resolves the path via its WSL mount (e.g. /mnt/c/…)
        # rather than receiving the Windows-style absolute path which bash
        # cannot interpret as an executable path.
        safe_input = pipe_input.replace("'", "'\\''")
        cmd = ["bash", "-c", f"printf '%s\\n' '{safe_input}' | {COBOL_BIN}"]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(REPO_ROOT),
                timeout=10,
            )
            result = record_result(
                test_id=test_id,
                category=category,
                pipe_input=pipe_input,
                raw_stdout=proc.stdout,
                raw_stderr=proc.stderr,
                exit_code=proc.returncode,
                impl="cobol",
            )
        except subprocess.TimeoutExpired:
            result = record_result(
                test_id=test_id,
                category=category,
                pipe_input=pipe_input,
                raw_stdout="",
                raw_stderr="TIMEOUT",
                exit_code=-1,
                impl="cobol",
            )
        except Exception as exc:
            result = record_result(
                test_id=test_id,
                category=category,
                pipe_input=pipe_input,
                raw_stdout="",
                raw_stderr=str(exc),
                exit_code=-1,
                impl="cobol",
            )

        results.append(result)

    elapsed = time.monotonic() - t0
    print(f"[COBOL] Done in {elapsed:.2f}s")
    return results


# ---------------------------------------------------------------------------
# Java Execution (batched — single JVM startup)
# ---------------------------------------------------------------------------

def ensure_java_compiled() -> None:
    """Compile PayrollProcessor and PayrollBatchRunner if .class files are missing."""
    runner_class = JAVA_DIR / "PayrollBatchRunner.class"
    processor_class = JAVA_DIR / "PayrollProcessor.class"

    need_compile = not runner_class.exists() or not processor_class.exists()
    if need_compile:
        print("[JAVA]  Compiling PayrollProcessor.java + PayrollBatchRunner.java …")
        sources = [
            str(JAVA_DIR / "PayrollProcessor.java"),
            str(JAVA_DIR / "PayrollBatchRunner.java"),
        ]
        proc = subprocess.run(
            ["javac", "-cp", str(JAVA_DIR), "-d", str(JAVA_DIR)] + sources,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            _abort(
                f"Java compilation failed (exit {proc.returncode}):\n"
                f"  stdout: {proc.stdout.strip()}\n"
                f"  stderr: {proc.stderr.strip()}"
            )
        print("[JAVA]  Compilation OK")


def run_java_all(test_cases: list[dict]) -> list[dict[str, Any]]:
    """
    Execute every test case through PayrollBatchRunner in a single JVM.

    All 70 pipe_input lines are piped to stdin at once.  PayrollBatchRunner
    calls PayrollProcessor.process() for each line and emits one result per
    line to stdout.  This avoids 70 JVM startup costs.

    Output lines are matched back to test cases by position (guaranteed
    deterministic because PayrollBatchRunner processes lines in order).
    """
    ensure_java_compiled()

    batch_input = "\n".join(tc["pipe_input"] for tc in test_cases) + "\n"

    print(f"[JAVA]  Running {len(test_cases)} tests via single JVM (PayrollBatchRunner)")
    t0 = time.monotonic()

    try:
        proc = subprocess.run(
            ["java", "-cp", str(JAVA_DIR), "PayrollBatchRunner"],
            input=batch_input,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        _abort("Java batch runner timed out after 60s")
    except Exception as exc:
        _abort(f"Java batch runner failed to start: {exc}")

    elapsed = time.monotonic() - t0
    print(f"[JAVA]  Done in {elapsed:.2f}s")

    if proc.returncode != 0:
        _abort(
            f"Java batch runner exited with code {proc.returncode}.\n"
            f"  stderr: {proc.stderr.strip()!r}"
        )

    # Split output lines, ignoring blank lines
    output_lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]

    if len(output_lines) != len(test_cases):
        _abort(
            f"Java batch runner produced {len(output_lines)} output lines "
            f"but expected {len(test_cases)}.\n"
            f"  stdout: {proc.stdout!r}\n"
            f"  stderr: {proc.stderr!r}"
        )

    results = []
    for tc, raw_line in zip(test_cases, output_lines):
        result = record_result(
            test_id=tc["test_id"],
            category=tc["category"],
            pipe_input=tc["pipe_input"],
            raw_stdout=raw_line + "\n",
            raw_stderr="",
            exit_code=0,
            impl="java",
        )
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Parity / Baseline Comparison
# ---------------------------------------------------------------------------

def compare_outputs(
    cobol_results: list[dict[str, Any]],
    java_results:  list[dict[str, Any]],
) -> tuple[list[dict], list[dict]]:
    """
    Compare COBOL and Java outputs field-by-field.

    Returns (matches, mismatches).

    Comparison rules:
      - employee_id and status must match exactly (string equality).
      - Monetary fields are compared as floats with tolerance 0.005
        (i.e. they must be equal to the nearest cent).
      - A missing/unparseable output is always a mismatch.
    """
    # Index Java results by test_id for quick lookup
    java_by_id = {r["test_id"]: r for r in java_results}

    matches    = []
    mismatches = []

    for cr in cobol_results:
        tid = cr["test_id"]
        jr  = java_by_id.get(tid)

        if jr is None:
            mismatches.append({
                "test_id":  tid,
                "reason":   "Java result missing for this test_id",
                "cobol":    cr,
                "java":     None,
            })
            continue

        # Both must have executed successfully enough to produce parseable output
        if not cr.get("output") or not cr["output"].get("parse_ok"):
            mismatches.append({
                "test_id": tid,
                "reason":  "COBOL output could not be parsed",
                "cobol_raw": cr.get("raw_stdout", ""),
                "java_raw":  jr.get("raw_stdout", ""),
            })
            continue

        if not jr.get("output") or not jr["output"].get("parse_ok"):
            mismatches.append({
                "test_id": tid,
                "reason":  "Java output could not be parsed",
                "cobol_raw": cr.get("raw_stdout", ""),
                "java_raw":  jr.get("raw_stdout", ""),
            })
            continue

        cp = cr["output"]["parsed"]
        jp = jr["output"]["parsed"]

        field_diffs = []

        # Exact match: employee_id and status
        for fname in ("employee_id", "status"):
            cv = cp.get(fname, "")
            jv = jp.get(fname, "")
            if cv != jv:
                field_diffs.append({
                    "field":  fname,
                    "cobol":  cv,
                    "java":   jv,
                })

        # Numeric match (within 0.005 — must agree to the cent)
        for fname in ("gross", "federal_tax", "state_tax", "ss_tax",
                      "medicare_tax", "net_pay"):
            cf = cp.get(fname + "_float")
            jf = jp.get(fname + "_float")
            if cf is None or jf is None:
                field_diffs.append({
                    "field":  fname,
                    "cobol":  cp.get(fname),
                    "java":   jp.get(fname),
                    "reason": "non-numeric value",
                })
            elif abs(cf - jf) >= 0.005:
                field_diffs.append({
                    "field":  fname,
                    "cobol":  cp.get(fname),
                    "java":   jp.get(fname),
                    "delta":  round(cf - jf, 6),
                })

        record = {
            "test_id":   tid,
            "category":  cr["category"],
            "pipe_input": cr["pipe_input"],
            "cobol_raw": cr["raw_stdout"].strip(),
            "java_raw":  jr["raw_stdout"].strip(),
        }

        if field_diffs:
            record["field_diffs"] = field_diffs
            mismatches.append(record)
        else:
            matches.append(record)

    return matches, mismatches


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def build_summary(
    test_cases:     list[dict],
    cobol_results:  list[dict[str, Any]],
    java_results:   list[dict[str, Any]],
    matches:        list[dict],
    mismatches:     list[dict],
) -> dict[str, Any]:
    cobol_ok     = sum(1 for r in cobol_results if r["execution_ok"])
    cobol_err    = sum(1 for r in cobol_results if not r["execution_ok"])
    java_ok      = sum(1 for r in java_results  if r["execution_ok"])
    java_err     = sum(1 for r in java_results  if not r["execution_ok"])

    # Distinguish expected validation errors (ERR_HOURS / ERR_MIN_WAGE) vs
    # unexpected process failures
    cobol_validation_errors = sum(
        1 for r in cobol_results
        if r["execution_ok"]
        and r.get("output")
        and r["output"].get("parse_ok")
        and r["output"].get("is_error")
    )
    java_validation_errors = sum(
        1 for r in java_results
        if r["execution_ok"]
        and r.get("output")
        and r["output"].get("parse_ok")
        and r["output"].get("is_error")
    )

    return {
        "schema_version":          "1.0",
        "phase":                   5,
        "description":             "CBLDiff dual-executor baseline run",
        "total_tests":             len(test_cases),
        "cobol": {
            "successes":             cobol_ok,
            "process_failures":      cobol_err,
            "validation_errors":     cobol_validation_errors,
        },
        "java": {
            "successes":             java_ok,
            "process_failures":      java_err,
            "validation_errors":     java_validation_errors,
        },
        "parity": {
            "matches":               len(matches),
            "mismatches":            len(mismatches),
            "baseline_result":       "PASS" if len(mismatches) == 0 else "FAIL",
            "mismatches_detail":     mismatches,
        },
        "files_written": [
            str(COBOL_OUT),
            str(JAVA_OUT),
            str(SUMMARY_OUT),
        ],
    }


# ---------------------------------------------------------------------------
# Abort helper
# ---------------------------------------------------------------------------

def _abort(msg: str) -> None:
    print(f"\n[ABORT] {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 65)
    print("  CBLDiff Phase 5 — Dual Executor")
    print("=" * 65)
    print()

    # ── Load test cases ──────────────────────────────────────────────────
    if not INPUTS_FILE.exists():
        _abort(f"Test inputs not found: {INPUTS_FILE}")

    with INPUTS_FILE.open() as fh:
        spec = json.load(fh)

    test_cases = spec["test_cases"]
    print(f"[LOAD]  {len(test_cases)} test cases from {INPUTS_FILE.name}")

    # ── Execute COBOL ────────────────────────────────────────────────────
    cobol_results = run_cobol_all(test_cases)

    # Fail fast on COBOL process failures
    cobol_failures = [r for r in cobol_results if not r["execution_ok"]]
    if cobol_failures:
        for f in cobol_failures:
            print(
                f"  [COBOL FAIL] {f['test_id']}: "
                f"exit={f['exit_code']} err={f['raw_stderr'].strip()!r}",
                file=sys.stderr,
            )
        _abort(
            f"{len(cobol_failures)} COBOL execution(s) failed. "
            "Cannot proceed with parity analysis."
        )

    # ── Execute Java (batched) ───────────────────────────────────────────
    java_results = run_java_all(test_cases)

    # Fail fast on Java process failures
    java_failures = [r for r in java_results if not r["execution_ok"]]
    if java_failures:
        for f in java_failures:
            print(
                f"  [JAVA FAIL] {f['test_id']}: "
                f"exit={f['exit_code']} err={f['raw_stderr'].strip()!r}",
                file=sys.stderr,
            )
        _abort(
            f"{len(java_failures)} Java execution(s) failed. "
            "Cannot proceed with parity analysis."
        )

    # ── Parse-level sanity check ──────────────────────────────────────────
    cobol_parse_fails = [
        r for r in cobol_results
        if r.get("output") and not r["output"].get("parse_ok")
    ]
    java_parse_fails = [
        r for r in java_results
        if r.get("output") and not r["output"].get("parse_ok")
    ]
    if cobol_parse_fails:
        for f in cobol_parse_fails:
            print(
                f"  [COBOL PARSE FAIL] {f['test_id']}: "
                f"{f['output'].get('parse_error', '?')!r}",
                file=sys.stderr,
            )
        _abort(
            f"{len(cobol_parse_fails)} COBOL output(s) could not be parsed."
        )
    if java_parse_fails:
        for f in java_parse_fails:
            print(
                f"  [JAVA PARSE FAIL] {f['test_id']}: "
                f"{f['output'].get('parse_error', '?')!r}",
                file=sys.stderr,
            )
        _abort(
            f"{len(java_parse_fails)} Java output(s) could not be parsed."
        )

    # ── Parity comparison ────────────────────────────────────────────────
    print()
    print("[PARITY] Comparing COBOL vs Java outputs …")
    matches, mismatches = compare_outputs(cobol_results, java_results)

    # ── Write output files ────────────────────────────────────────────────
    DATA_DIR.mkdir(exist_ok=True)

    cobol_out_doc = {
        "schema_version": "1.0",
        "impl": "cobol",
        "binary": str(COBOL_BIN),
        "test_count": len(cobol_results),
        "results": cobol_results,
    }
    java_out_doc = {
        "schema_version": "1.0",
        "impl": "java",
        "class": "PayrollProcessor",
        "runner": "PayrollBatchRunner",
        "test_count": len(java_results),
        "results": java_results,
    }

    with COBOL_OUT.open("w") as fh:
        json.dump(cobol_out_doc, fh, indent=2)
    print(f"[WRITE]  {COBOL_OUT}")

    with JAVA_OUT.open("w") as fh:
        json.dump(java_out_doc, fh, indent=2)
    print(f"[WRITE]  {JAVA_OUT}")

    summary = build_summary(test_cases, cobol_results, java_results, matches, mismatches)
    with SUMMARY_OUT.open("w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"[WRITE]  {SUMMARY_OUT}")

    # ── Report ────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("  EXECUTION SUMMARY")
    print("=" * 65)
    print(f"  Total tests         : {len(test_cases)}")
    print(f"  COBOL  successes    : {summary['cobol']['successes']}")
    print(f"  COBOL  proc failures: {summary['cobol']['process_failures']}")
    print(f"  COBOL  val errors   : {summary['cobol']['validation_errors']}")
    print(f"  Java   successes    : {summary['java']['successes']}")
    print(f"  Java   proc failures: {summary['java']['process_failures']}")
    print(f"  Java   val errors   : {summary['java']['validation_errors']}")
    print()
    print(f"  Parity matches      : {len(matches)}")
    print(f"  Parity MISMATCHES   : {len(mismatches)}")
    print(f"  Baseline result     : {summary['parity']['baseline_result']}")
    print()

    if mismatches:
        print("  !! MISMATCHES DETECTED — details follow:")
        print()
        for mm in mismatches:
            print(f"    TEST: {mm['test_id']}  ({mm.get('category', '?')})")
            print(f"    INPUT:      {mm.get('pipe_input', '?')}")
            print(f"    COBOL:      {mm.get('cobol_raw', '?')}")
            print(f"    JAVA:       {mm.get('java_raw',  '?')}")
            if "field_diffs" in mm:
                for fd in mm["field_diffs"]:
                    delta = f"  delta={fd['delta']}" if "delta" in fd else ""
                    print(
                        f"    DIFF  [{fd['field']}]: "
                        f"COBOL={fd['cobol']!r}  JAVA={fd['java']!r}{delta}"
                    )
            elif "reason" in mm:
                print(f"    REASON: {mm['reason']}")
            print()

        _abort(
            "Baseline parity check FAILED — "
            f"{len(mismatches)} behavioral mismatch(es) detected. "
            "See details above."
        )

    print("  All outputs match. Baseline parity PASSED.")
    print()
    print("  Files created / modified:")
    for f in summary["files_written"]:
        print(f"    {f}")
    print()
    print("  Command used:")
    print("    python cbldiff/dual_executor.py")
    print()


if __name__ == "__main__":
    main()
