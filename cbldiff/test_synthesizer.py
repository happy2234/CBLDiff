#!/usr/bin/env python3
"""
cbldiff/test_synthesizer.py — CBLDiff Phase 4: Test Synthesizer

Reads  data/rules.json
Writes data/test_inputs.json

Deterministic generation (fixed seed = 42).  Five categories:

  boundary     — exact thresholds and ±epsilon neighbours from rules.json
  normal       — representative valid inputs across all rule branches
  error        — ERR_HOURS and ERR_MIN_WAGE validation paths
  interaction  — multi-rule combinations (bracket+deps, SS-cap+OT, net floor)
  adversarial  — rounding-sensitive values where intermediate tax * rate ≈ *.005
                 (targets RULE-11 half-up boundary without any ML model)

Schema for each test case:
  {
    "test_id":           "BND-001",
    "category":          "boundary",
    "input": {
      "employee_id":     "BND001",
      "hours":           "40.00",
      "rate":            "12.50",
      "is_salaried":     "N",
      "salary":          "0.00",
      "dependents":      0
    },
    "pipe_input":        "BND001|40.00|12.50|N|0.00|0",
    "targeted_rule_ids": ["RULE-01"],
    "rationale":         "Straight-time hourly at exactly 40h."
  }
"""

from __future__ import annotations

import json
import random
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR  = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
RULES_FILE  = REPO_ROOT / "data" / "rules.json"
OUTPUT_FILE = REPO_ROOT / "data" / "test_inputs.json"

# Fixed seed — must never change; same rules.json -> same test_inputs.json
RANDOM_SEED = 42

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def d2(v: str | float | Decimal) -> str:
    """Format a number as a 2-decimal-place string."""
    return str(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def make_case(
    seq: int,
    prefix: str,
    category: str,
    hours: str | float,
    rate: str | float,
    is_salaried: str,
    salary: str | float,
    dependents: int,
    targeted: list[str],
    rationale: str,
) -> dict[str, Any]:
    """Build one fully-populated test case dict."""
    emp_id = f"{prefix}{seq:03d}"
    h  = d2(hours)
    r  = d2(rate)
    s  = d2(salary)
    is_sal = is_salaried.upper()
    pipe   = f"{emp_id}|{h}|{r}|{is_sal}|{s}|{dependents}"
    return {
        "test_id":           f"{prefix}-{seq:03d}",
        "category":          category,
        "input": {
            "employee_id": emp_id,
            "hours":       h,
            "rate":        r,
            "is_salaried": is_sal,
            "salary":      s,
            "dependents":  dependents,
        },
        "pipe_input":        pipe,
        "targeted_rule_ids": targeted,
        "rationale":         rationale,
    }


# Shorthand builders by category prefix
def bnd(seq, hours, rate, is_salaried, salary, deps, rules, rationale):
    return make_case(seq, "BND", "boundary", hours, rate, is_salaried, salary, deps, rules, rationale)

def nrm(seq, hours, rate, is_salaried, salary, deps, rules, rationale):
    return make_case(seq, "NRM", "normal", hours, rate, is_salaried, salary, deps, rules, rationale)

def err(seq, hours, rate, is_salaried, salary, deps, rules, rationale):
    return make_case(seq, "ERR", "error", hours, rate, is_salaried, salary, deps, rules, rationale)

def itr(seq, hours, rate, is_salaried, salary, deps, rules, rationale):
    return make_case(seq, "ITR", "interaction", hours, rate, is_salaried, salary, deps, rules, rationale)

def adv(seq, hours, rate, is_salaried, salary, deps, rules, rationale):
    return make_case(seq, "ADV", "adversarial", hours, rate, is_salaried, salary, deps, rules, rationale)


# ---------------------------------------------------------------------------
# Category 1: BOUNDARY cases (20 cases)
# Tests every documented threshold at its exact value and at ±1 cent / ±0.01h
# ---------------------------------------------------------------------------
def generate_boundary_cases() -> list[dict]:
    cases = []

    # ── Federal bracket 1 / 2 boundary: gross = 500.00 ─────────────────────
    # gross = hours * rate; to get gross=500 use rate=12.50 h=40
    cases.append(bnd(1, 40.00, 12.50, "N", 0, 0,
        ["RULE-04", "RULE-05"],
        "gross = 500.00 exactly — upper limit of bracket 1 (must use 10% rate, NOT 12%)"))

    # gross = 500.40 (40 * 12.51) — cleanly above 500 in bracket 2
    cases.append(bnd(2, 40.00, 12.51, "N", 0, 0,
        ["RULE-05"],
        "gross = 500.40 (40*12.51) — just above bracket 1 top; bracket 2 at 12%"))

    # gross = 499.60 (40 * 12.49) — cleanly below 500 in bracket 1
    cases.append(bnd(3, 40.00, 12.49, "N", 0, 0,
        ["RULE-04"],
        "gross = 499.60 (40*12.49) — just below bracket 1 top; solidly bracket 1 at 10%"))

    # Use salaried to get exact boundary values without rounding ambiguity
    cases.append(bnd(4, 0, 0, "Y", 500.00, 0,
        ["RULE-04"],
        "salaried gross = 500.00 exactly — bracket 1 upper limit, 10% rate"))

    cases.append(bnd(5, 0, 0, "Y", 500.01, 0,
        ["RULE-05"],
        "salaried gross = 500.01 — crosses into bracket 2 at 12%"))

    # ── Federal bracket 2 / 3 KEY boundary: gross = 1500.00 ─────────────────
    cases.append(bnd(6, 40.00, 37.50, "N", 0, 0,
        ["RULE-05", "RULE-06"],
        "gross = 1500.00 exactly (40*37.50) — upper limit of bracket 2 (must use 12%, NOT 22%)"))

    cases.append(bnd(7, 0, 0, "Y", 1500.00, 0,
        ["RULE-05"],
        "salaried gross = 1500.00 exactly — bracket 2 upper boundary, must use 12%"))

    cases.append(bnd(8, 0, 0, "Y", 1499.99, 0,
        ["RULE-05"],
        "salaried gross = 1499.99 — just below bracket 2 top, still 12%"))

    cases.append(bnd(9, 0, 0, "Y", 1500.01, 0,
        ["RULE-06"],
        "salaried gross = 1500.01 — first cent into bracket 3 at 22%"))

    cases.append(bnd(10, 40.00, 37.51, "N", 0, 0,
        ["RULE-06"],
        "gross = 1500.40 (40*37.51) — just above bracket 2/3 boundary, must use 22%"))

    # ── Overtime threshold: hours = 40 ──────────────────────────────────────
    cases.append(bnd(11, 40.00, 20.00, "N", 0, 0,
        ["RULE-01"],
        "hours = 40.00 exactly — OT threshold; straight-time only (not OT)"))

    cases.append(bnd(12, 40.01, 20.00, "N", 0, 0,
        ["RULE-02"],
        "hours = 40.01 — one hundredth of an hour into OT; triggers 1.5x rate"))

    cases.append(bnd(13, 39.99, 20.00, "N", 0, 0,
        ["RULE-01"],
        "hours = 39.99 — just below OT threshold; pure straight-time"))

    # ── Maximum hours boundary: 168 ─────────────────────────────────────────
    cases.append(bnd(14, 168.00, 10.00, "N", 0, 0,
        ["RULE-14", "RULE-02"],
        "hours = 168.00 exactly — max allowed hours; valid, all OT above 40"))

    # ── Minimum wage boundary: 7.25 ─────────────────────────────────────────
    cases.append(bnd(15, 40.00, 7.25, "N", 0, 0,
        ["RULE-13"],
        "rate = 7.25 exactly — minimum wage floor; valid (not below threshold)"))

    cases.append(bnd(16, 40.00, 7.24, "N", 0, 0,
        ["RULE-13"],
        "rate = 7.24 — one cent below minimum wage; must trigger ERR_MIN_WAGE"))

    cases.append(bnd(17, 40.00, 7.26, "N", 0, 0,
        ["RULE-13", "RULE-01"],
        "rate = 7.26 — one cent above minimum wage; valid"))

    # ── Social Security weekly cap: 3242.31 ─────────────────────────────────
    # gross = 3242.31 exactly: use salaried salary = 3242.31
    cases.append(bnd(18, 0, 0, "Y", 3242.31, 0,
        ["RULE-09"],
        "salaried gross = 3242.31 exactly — SS cap boundary; SS = 3242.31 * 0.062"))

    cases.append(bnd(19, 0, 0, "Y", 3242.32, 0,
        ["RULE-09"],
        "salaried gross = 3242.32 — one cent above SS cap; SS still capped at 3242.31 * 0.062"))

    cases.append(bnd(20, 0, 0, "Y", 3242.30, 0,
        ["RULE-09"],
        "salaried gross = 3242.30 — one cent below SS cap; SS = 3242.30 * 0.062"))

    return cases


# ---------------------------------------------------------------------------
# Category 2: NORMAL cases (16 cases)
# Representative valid inputs covering all major code paths
# ---------------------------------------------------------------------------
def generate_normal_cases() -> list[dict]:
    cases = []

    # Hourly straight-time, different brackets
    cases.append(nrm(1, 40.00, 10.00, "N", 0, 0,
        ["RULE-01", "RULE-04"],
        "40h @ $10/h = gross 400; bracket 1 (10%)"))

    cases.append(nrm(2, 35.00, 10.00, "N", 0, 0,
        ["RULE-01", "RULE-04"],
        "35h @ $10 = gross 350; well inside bracket 1"))

    cases.append(nrm(3, 40.00, 20.00, "N", 0, 0,
        ["RULE-01", "RULE-05"],
        "40h @ $20 = gross 800; bracket 2 (12%)"))

    cases.append(nrm(4, 40.00, 30.00, "N", 0, 0,
        ["RULE-01", "RULE-05"],
        "40h @ $30 = gross 1200; mid-range bracket 2"))

    cases.append(nrm(5, 40.00, 50.00, "N", 0, 0,
        ["RULE-01", "RULE-06"],
        "40h @ $50 = gross 2000; bracket 3 (22%)"))

    cases.append(nrm(6, 40.00, 100.00, "N", 0, 0,
        ["RULE-01", "RULE-06", "RULE-09"],
        "40h @ $100 = gross 4000; bracket 3 + SS cap triggered"))

    # Overtime cases
    cases.append(nrm(7, 45.00, 20.00, "N", 0, 0,
        ["RULE-02", "RULE-05"],
        "45h OT @ $20: 40*20 + 5*30 = 950; bracket 2"))

    cases.append(nrm(8, 50.00, 20.00, "N", 0, 0,
        ["RULE-02", "RULE-05"],
        "50h OT @ $20: 40*20 + 10*30 = 1100; bracket 2"))

    cases.append(nrm(9, 60.00, 30.00, "N", 0, 0,
        ["RULE-02", "RULE-06"],
        "60h OT @ $30: 40*30 + 20*45 = 2100; bracket 3"))

    # Salaried cases
    cases.append(nrm(10, 0, 0, "Y", 500.00, 0,
        ["RULE-03", "RULE-04"],
        "salaried $500/wk; bracket 1 (10%)"))

    cases.append(nrm(11, 0, 0, "Y", 1000.00, 2,
        ["RULE-03", "RULE-05", "RULE-07"],
        "salaried $1000/wk, 2 deps; bracket 2, dep allowance = 160"))

    cases.append(nrm(12, 0, 0, "Y", 2000.00, 3,
        ["RULE-03", "RULE-06", "RULE-07"],
        "salaried $2000/wk, 3 deps; bracket 3; dep allowance = 240"))

    cases.append(nrm(13, 0, 0, "Y", 5000.00, 0,
        ["RULE-03", "RULE-06", "RULE-09"],
        "high salaried $5000/wk; bracket 3 + SS capped"))

    # Dependent variations on same gross
    cases.append(nrm(14, 40.00, 20.00, "N", 0, 1,
        ["RULE-05", "RULE-07"],
        "gross 800, 1 dep; federal = 800*0.12 - 80 = 16.00"))

    cases.append(nrm(15, 40.00, 20.00, "N", 0, 3,
        ["RULE-05", "RULE-07"],
        "gross 800, 3 deps; federal = 96 - 240 < 0 -> 0"))

    cases.append(nrm(16, 40.00, 20.00, "N", 0, 5,
        ["RULE-05", "RULE-07", "RULE-15"],
        "gross 800, 5 deps (max); federal = 96 - 400 < 0 -> 0"))

    return cases


# ---------------------------------------------------------------------------
# Category 3: ERROR cases (8 cases)
# ---------------------------------------------------------------------------
def generate_error_cases() -> list[dict]:
    cases = []

    # ERR_HOURS — above max
    cases.append(err(1, 168.01, 10.00, "N", 0, 0,
        ["RULE-14"],
        "hours = 168.01 — one hundredth over max; must produce ERR_HOURS"))

    cases.append(err(2, 200.00, 20.00, "N", 0, 0,
        ["RULE-14"],
        "hours = 200 — clearly over 168; ERR_HOURS"))

    cases.append(err(3, 999.99, 10.00, "N", 0, 0,
        ["RULE-14"],
        "hours = 999.99 — extreme over-hours; ERR_HOURS"))

    # ERR_HOURS — negative (COBOL unsigned, so 0 is the effective floor but
    # a negative string value is worth testing the parser path)
    cases.append(err(4, 169.00, 15.00, "N", 0, 2,
        ["RULE-14"],
        "hours = 169 with dependents; ERR_HOURS regardless of deps"))

    # ERR_MIN_WAGE — below threshold
    cases.append(err(5, 40.00, 7.24, "N", 0, 0,
        ["RULE-13"],
        "rate = 7.24 — below $7.25 min wage; ERR_MIN_WAGE"))

    cases.append(err(6, 40.00, 5.00, "N", 0, 0,
        ["RULE-13"],
        "rate = 5.00 — well below min wage; ERR_MIN_WAGE"))

    cases.append(err(7, 40.00, 0.01, "N", 0, 0,
        ["RULE-13"],
        "rate = 0.01 — near-zero rate; ERR_MIN_WAGE"))

    # Hours valid but rate bad
    cases.append(err(8, 40.00, 7.00, "N", 0, 3,
        ["RULE-13"],
        "rate = 7.00 < 7.25 with dependents; ERR_MIN_WAGE (deps irrelevant for errors)"))

    return cases


# ---------------------------------------------------------------------------
# Category 4: INTERACTION cases (16 cases)
# Test combinations where multiple rules interact
# ---------------------------------------------------------------------------
def generate_interaction_cases() -> list[dict]:
    cases = []

    # Bracket 1 + dep allowance wipes federal tax
    cases.append(itr(1, 10.00, 10.00, "N", 0, 1,
        ["RULE-04", "RULE-07"],
        "gross=100 (bracket1), 1 dep: 100*0.10=10, 10-80<0 -> federal=0"))

    cases.append(itr(2, 40.00, 12.50, "N", 0, 1,
        ["RULE-04", "RULE-07"],
        "gross=500 (bracket1 top), 1 dep: 50-80<0 -> federal=0"))

    # Bracket 2 + varying deps
    cases.append(itr(3, 40.00, 20.00, "N", 0, 1,
        ["RULE-05", "RULE-07"],
        "gross=800 (bracket2), 1 dep: 96-80=16 federal"))

    cases.append(itr(4, 40.00, 20.00, "N", 0, 2,
        ["RULE-05", "RULE-07"],
        "gross=800 (bracket2), 2 deps: 96-160<0 -> federal=0"))

    # Bracket 2 top + 0 deps (key boundary)
    cases.append(itr(5, 40.00, 37.50, "N", 0, 1,
        ["RULE-05", "RULE-07"],
        "gross=1500 (bracket2 top), 1 dep: 1500*0.12=180, 180-80=100 federal"))

    cases.append(itr(6, 40.00, 37.50, "N", 0, 5,
        ["RULE-05", "RULE-07", "RULE-15"],
        "gross=1500 (bracket2 top), 5 deps (cap): 180-400<0 -> federal=0"))

    # Bracket 3 + deps
    cases.append(itr(7, 40.00, 50.00, "N", 0, 1,
        ["RULE-06", "RULE-07"],
        "gross=2000 (bracket3), 1 dep: 2000*0.22=440, 440-80=360 federal"))

    cases.append(itr(8, 40.00, 50.00, "N", 0, 5,
        ["RULE-06", "RULE-07", "RULE-15"],
        "gross=2000 (bracket3), 5 deps (cap): 440-400=40 federal"))

    # OT + bracket transition
    cases.append(itr(9, 44.00, 33.00, "N", 0, 0,
        ["RULE-02", "RULE-05", "RULE-06"],
        "OT 44h @ $33: 40*33 + 4*49.50 = 1320+198 = 1518; bracket 3"))

    cases.append(itr(10, 41.00, 36.00, "N", 0, 0,
        ["RULE-02", "RULE-05"],
        "OT 41h @ $36: 40*36 + 1*54 = 1440+54 = 1494; stays bracket 2"))

    # SS cap + bracket 3
    cases.append(itr(11, 40.00, 90.00, "N", 0, 0,
        ["RULE-06", "RULE-09"],
        "gross=3600 (bracket3 + SS capped): SS = 3242.31 * 0.062"))

    cases.append(itr(12, 168.00, 25.00, "N", 0, 0,
        ["RULE-02", "RULE-06", "RULE-09"],
        "max hours 168h @ $25: 40*25 + 128*37.50 = 1000+4800=5800; bracket3 + SS cap"))

    # Dependents cap: exactly 5 vs 6 (capped to 5)
    cases.append(itr(13, 40.00, 50.00, "N", 0, 5,
        ["RULE-06", "RULE-07", "RULE-15"],
        "gross=2000, dependents=5 (at cap): effective=5, allowance=400"))

    cases.append(itr(14, 40.00, 50.00, "N", 0, 6,
        ["RULE-06", "RULE-07", "RULE-15"],
        "gross=2000, dependents=6 (over cap): capped at 5, same result as 5 deps"))

    # Net pay floor
    cases.append(itr(15, 0, 0, "Y", 10.00, 0,
        ["RULE-03", "RULE-04", "RULE-12"],
        "salaried $10/wk (tiny salary): all taxes may consume all net pay; test floor=0"))

    # Salaried + dep cap
    cases.append(itr(16, 0, 0, "Y", 2000.00, 6,
        ["RULE-03", "RULE-06", "RULE-07", "RULE-15"],
        "salaried $2000 + 6 deps (capped to 5): bracket3, allowance=400, federal=40"))

    return cases


# ---------------------------------------------------------------------------
# Category 5: ADVERSARIAL cases (10 cases)
# Deterministic rounding-boundary inputs: values where gross * rate ≈ N.005
# (the exact half-up trigger), forcing correct HALF_UP rounding behaviour.
# No ML — pure arithmetic adversarial targeting of RULE-11.
# ---------------------------------------------------------------------------
def generate_adversarial_cases(rng: random.Random) -> list[dict]:  # noqa: ARG001
    """
    Adversarial strategy: identify gross values where an intermediate
    computation lands exactly on a half-cent boundary (N.005), which is the
    point where ROUND_HALF_UP differs from ROUND_HALF_EVEN (banker's rounding).
    This catches implementations that use Python's built-in round() instead of
    Decimal(ROUND_HALF_UP) or COBOL ROUNDED.

    For each tax rate R, we want gross * R = N.005 for some integer N.
    -> gross = (N + 0.005) / R

    We generate one adversarial case per tax rate.
    We also include cases around the OT boundary where the OT gross itself
    rounds to a half-cent.
    """
    cases = []

    # State tax: rate = 0.0307
    # gross * 0.0307 = N.005 -> gross = N.005 / 0.0307
    # N=24: 24.005 / 0.0307 = 781.9... -> gross ≈ 781.92
    gross_state = Decimal("24.005") / Decimal("0.0307")
    gross_state = float(gross_state.quantize(Decimal("0.01"), ROUND_HALF_UP))
    # Use salaried to avoid further rounding from hourly computation
    cases.append(adv(1, 0, 0, "Y", gross_state, 0,
        ["RULE-08", "RULE-11"],
        f"state-tax rounding: gross={gross_state} -> gross*0.0307 ≈ N.005 (half-up trigger)"))

    # Federal bracket 2: rate = 0.12
    # gross * 0.12 = N.005 -> gross = N.005 / 0.12
    # N=96: 96.005/0.12 = 800.042 -> gross=800.04
    gross_fed2 = Decimal("96.005") / Decimal("0.12")
    gross_fed2 = float(gross_fed2.quantize(Decimal("0.01"), ROUND_HALF_UP))
    cases.append(adv(2, 0, 0, "Y", gross_fed2, 0,
        ["RULE-05", "RULE-11"],
        f"bracket-2 federal rounding: gross={gross_fed2} -> gross*0.12 ≈ N.005"))

    # Federal bracket 1: rate = 0.10
    # gross * 0.10 = N.005 -> gross = N.005 / 0.10
    # N=40: 40.005/0.10 = 400.05
    gross_fed1 = Decimal("40.005") / Decimal("0.10")
    gross_fed1 = float(gross_fed1.quantize(Decimal("0.01"), ROUND_HALF_UP))
    cases.append(adv(3, 0, 0, "Y", gross_fed1, 0,
        ["RULE-04", "RULE-11"],
        f"bracket-1 federal rounding: gross={gross_fed1} -> gross*0.10 ≈ N.005"))

    # Federal bracket 3: rate = 0.22
    # gross * 0.22 = N.005 -> gross = N.005 / 0.22
    # N=330: 330.005/0.22 = 1500.022... — too close to bracket boundary, use N=362:
    # 362.005/0.22 = 1645.48
    gross_fed3 = Decimal("362.005") / Decimal("0.22")
    gross_fed3 = float(gross_fed3.quantize(Decimal("0.01"), ROUND_HALF_UP))
    cases.append(adv(4, 0, 0, "Y", gross_fed3, 0,
        ["RULE-06", "RULE-11"],
        f"bracket-3 federal rounding: gross={gross_fed3} -> gross*0.22 ≈ N.005"))

    # SS tax: rate = 0.062
    # gross * 0.062 = N.005 -> gross = N.005/0.062
    # N=49: 49.005/0.062 = 790.40
    gross_ss = Decimal("49.005") / Decimal("0.062")
    gross_ss = float(gross_ss.quantize(Decimal("0.01"), ROUND_HALF_UP))
    cases.append(adv(5, 0, 0, "Y", gross_ss, 0,
        ["RULE-09", "RULE-11"],
        f"SS-tax rounding: gross={gross_ss} -> gross*0.062 ≈ N.005"))

    # Medicare: rate = 0.0145
    # gross * 0.0145 = N.005 -> gross = N.005/0.0145
    # N=11: 11.005/0.0145 = 758.97
    gross_med = Decimal("11.005") / Decimal("0.0145")
    gross_med = float(gross_med.quantize(Decimal("0.01"), ROUND_HALF_UP))
    cases.append(adv(6, 0, 0, "Y", gross_med, 0,
        ["RULE-10", "RULE-11"],
        f"medicare rounding: gross={gross_med} -> gross*0.0145 ≈ N.005"))

    # OT gross rounding: choose hours and rate so that the OT pay
    # component itself rounds half-up
    # OT gross = 40*rate + ot_hours * rate * 1.5
    # Choose rate=13.33, ot_hours=1: OT component = 1 * 13.33 * 1.5 = 19.995
    # -> rounds to 20.00 (HALF_UP) vs 19.99 (truncate)
    cases.append(adv(7, 41.00, 13.33, "N", 0, 0,
        ["RULE-02", "RULE-11"],
        "OT rounding: 1 OT hour @ $13.33 -> OT pay = 13.33*1.5 = 19.995, half-up -> 20.00"))

    # Another OT case: rate=6.67/h — below min wage BUT want to test OT calc
    # Use rate = 15.00, ot_hours = 2.5: OT = 2.5*15*1.5 = 56.25 (clean, not interesting)
    # rate = 11.11, ot_hours = 3: OT = 3 * 11.11 * 1.5 = 49.995 -> 50.00 HALF_UP
    cases.append(adv(8, 43.00, 11.11, "N", 0, 0,
        ["RULE-02", "RULE-11"],
        "OT rounding: 3 OT hours @ $11.11 -> OT pay = 49.995, half-up -> 50.00"))

    # Dep allowance near zero: federal ≈ 0.005 (dep allowance within a
    # penny of wiping all federal tax)
    # bracket2, 1 dep: federal_base - 80 ≈ 0.005
    # gross*0.12 = 80.005 -> gross = 80.005/0.12 = 666.71
    gross_dep_edge = Decimal("80.005") / Decimal("0.12")
    gross_dep_edge = float(gross_dep_edge.quantize(Decimal("0.01"), ROUND_HALF_UP))
    cases.append(adv(9, 0, 0, "Y", gross_dep_edge, 1,
        ["RULE-05", "RULE-07", "RULE-11"],
        f"dep allowance edge: gross={gross_dep_edge}, 1 dep -> "
        f"federal_base={gross_dep_edge}*0.12≈80.005, "
        f"after dep: ≈0.005 -> rounds to 0.01 or 0.00"))

    # Gross exactly at SS cap with rounding-sensitive OT
    # To get gross = 3242.31 via hourly OT:
    # 40*rate + ot_hours*rate*1.5 = 3242.31
    # rate*(40 + 1.5*ot_hours) = 3242.31
    # ot_hours=1: rate * 41.5 = 3242.31 -> rate = 78.13
    # Check: 40*78.13 + 1*78.13*1.5 = 3125.20 + 117.195 = 3242.395 ≈ 3242.40 (not exact)
    # Use salaried for exact SS cap test with non-trivial net
    cases.append(adv(10, 0, 0, "Y", 3242.31, 2,
        ["RULE-07", "RULE-09", "RULE-11"],
        "gross = SS cap exactly, 2 deps: SS = 3242.31*0.062=201.02; bracket 3 federal with dep reduction"))

    return cases


# ---------------------------------------------------------------------------
# Schema validator
# ---------------------------------------------------------------------------
REQUIRED_KEYS = {"test_id", "category", "input", "pipe_input",
                 "targeted_rule_ids", "rationale"}
INPUT_KEYS    = {"employee_id", "hours", "rate", "is_salaried",
                 "salary", "dependents"}
VALID_CATS    = {"boundary", "normal", "error", "interaction", "adversarial"}

def validate_test_cases(cases: list[dict]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for c in cases:
        tid = c.get("test_id", "<missing>")
        if tid in seen_ids:
            errors.append(f"{tid}: duplicate test_id")
        seen_ids.add(tid)
        missing = REQUIRED_KEYS - set(c.keys())
        if missing:
            errors.append(f"{tid}: missing keys {sorted(missing)}")
        if c.get("category") not in VALID_CATS:
            errors.append(f"{tid}: invalid category '{c.get('category')}'")
        inp = c.get("input", {})
        missing_inp = INPUT_KEYS - set(inp.keys())
        if missing_inp:
            errors.append(f"{tid}: missing input fields {sorted(missing_inp)}")
        if not isinstance(c.get("targeted_rule_ids"), list):
            errors.append(f"{tid}: targeted_rule_ids must be a list")
        # Verify pipe_input reconstructs correctly
        expected_pipe = (f"{inp.get('employee_id', '')}|"
                         f"{inp.get('hours', '')}|{inp.get('rate', '')}|"
                         f"{inp.get('is_salaried', '')}|{inp.get('salary', '')}|"
                         f"{inp.get('dependents', '')}")
        if c.get("pipe_input") != expected_pipe:
            errors.append(f"{tid}: pipe_input mismatch (expected '{expected_pipe}' "
                          f"got '{c.get('pipe_input')}')")
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("  CBLDiff Phase 4 — Test Synthesizer")
    print("=" * 60)

    if not RULES_FILE.exists():
        sys.exit(f"ERROR: rules.json not found: {RULES_FILE}")

    rules_doc = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    rule_ids  = {r["rule_id"] for r in rules_doc["rules"]}
    print(f"\n[INPUT]  {RULES_FILE.name}  ({rules_doc['rule_count']} rules)")

    # Seed RNG — must be fixed for determinism
    rng = random.Random(RANDOM_SEED)
    print(f"[SEED]   random seed = {RANDOM_SEED} (fixed for determinism)")

    # Generate all categories
    print("\n[GEN]    Generating test cases ...")
    boundary    = generate_boundary_cases()
    normal      = generate_normal_cases()
    error       = generate_error_cases()
    interaction = generate_interaction_cases()
    adversarial = generate_adversarial_cases(rng)

    all_cases = boundary + normal + error + interaction + adversarial
    print(f"         boundary    : {len(boundary):>3}")
    print(f"         normal      : {len(normal):>3}")
    print(f"         error       : {len(error):>3}")
    print(f"         interaction : {len(interaction):>3}")
    print(f"         adversarial : {len(adversarial):>3}")
    print(f"         TOTAL       : {len(all_cases):>3}")

    # Validate
    print("\n[VALIDATE] Checking schema ...")
    # Warn if any targeted_rule_id is not in the rules registry
    rule_ref_warnings = []
    for c in all_cases:
        for rid in c["targeted_rule_ids"]:
            if rid not in rule_ids:
                rule_ref_warnings.append(f"{c['test_id']}: unknown rule ref '{rid}'")
    for w in rule_ref_warnings:
        print(f"  WARN: {w}")

    schema_errors = validate_test_cases(all_cases)
    if schema_errors:
        for e in schema_errors:
            print(f"  ERROR: {e}")
        sys.exit(1)
    print(f"  Schema OK — {len(all_cases)} cases, all required keys present")

    # Write output
    output = {
        "schema_version":  "1.0",
        "generated_by":    "cbldiff/test_synthesizer.py",
        "random_seed":     RANDOM_SEED,
        "rules_source":    RULES_FILE.name,
        "test_count":      len(all_cases),
        "counts_by_category": {
            "boundary":    len(boundary),
            "normal":      len(normal),
            "error":       len(error),
            "interaction": len(interaction),
            "adversarial": len(adversarial),
        },
        "test_cases": all_cases,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\n[WRITE]  {OUTPUT_FILE}  ({OUTPUT_FILE.stat().st_size:,} bytes)")

    # Print critical boundary cases (500 and 1500)
    print("\n" + "=" * 60)
    print("  CRITICAL FEDERAL BRACKET BOUNDARY CASES")
    print("=" * 60)
    for c in all_cases:
        # Check pipe_input or salary for 500/1500 proximity
        pipe = c["pipe_input"]
        inp  = c["input"]
        gross_hint = ""
        # For salaried we know gross = salary
        if inp["is_salaried"] == "Y":
            try:
                sal = float(inp["salary"])
                if 498 <= sal <= 502 or 1498 <= sal <= 1502 or 3240 <= sal <= 3245:
                    gross_hint = f" [salary={sal}]"
            except ValueError:
                pass
        # Flag by targeted rule IDs
        targets = c["targeted_rule_ids"]
        if any(r in targets for r in ("RULE-04", "RULE-05", "RULE-06")):
            if gross_hint or any(x in pipe for x in ("500", "37.50", "37.51", "12.50")):
                print(f"  {c['test_id']:<10} [{c['category']:<12}] {pipe}")
                print(f"             Rules: {targets}")
                print(f"             {c['rationale']}")
                print()

    print("=" * 60)
    print("  FULL TEST COUNTS BY CATEGORY")
    print("=" * 60)
    for cat in ("boundary", "normal", "error", "interaction", "adversarial"):
        count = sum(1 for c in all_cases if c["category"] == cat)
        print(f"  {cat:<15} {count:>3}")
    print(f"  {'TOTAL':<15} {len(all_cases):>3}")


if __name__ == "__main__":
    main()
