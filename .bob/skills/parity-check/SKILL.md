---
name: parity-check
description: >-
  Use when the user wants to verify behavioral parity between a COBOL source and
  its modernized Java counterpart, run a CBLDiff parity check, check for
  regressions, invoke CBLDiff verification, or determine whether a Java
  modernization is VERIFIED or NOT_VERIFIED against the COBOL reference.
---

# CBLDiff Parity-Check Skill

This skill orchestrates CBLDiff behavioral parity verification through the
local MCP server and reports the result back to the developer.

## Purpose

Invoke the full CBLDiff verification pipeline — dual execution, parity scoring,
critical-rule gate — and surface the structured verdict to the developer without
modifying any source files.

## When to Use

- Developer asks: "run parity check", "verify the Java", "check for regressions",
  "is the Java modernization correct?", "run CBLDiff"
- After a Java change that may affect payroll computation
- As a pre-merge verification gate in a modernization workflow

## Required Inputs

| Input | Description | Required |
|---|---|---|
| workspace root | The repo root containing `cbldiff/` and `data/` directories | Yes (assumed to be current workspace) |
| pre-run artifacts | `data/cobol_outputs.json` and `data/java_outputs.json` must exist | Yes |

If the execution artifacts do not exist, instruct the developer to run the
Dual Executor first:
```
python cbldiff/dual_executor.py
```

## Workflow

1. **Check artifacts** — verify `data/cobol_outputs.json` and `data/java_outputs.json`
   exist using `read_file` or `glob`. If missing, stop and ask the developer to run the
   Dual Executor.

2. **Invoke CBLDiff via MCP** — call the `verify_parity` tool exposed by the
   `cbldiff-mcp` MCP server. The tool runs the full parity analysis pipeline and
   returns a structured JSON result.

3. **Interpret the result** — map `final_status` to one of:
   - `VERIFIED` — parity score meets threshold AND no critical-rule divergences
   - `NOT_VERIFIED` — either gate failed; regression likely present

4. **Surface critical findings** — if `critical_rule_gate` triggered, always report:
   - The failing rule IDs (e.g. `RULE-05`)
   - The affected test IDs (e.g. `BND-006`, `BND-007`)
   - The affected output fields (e.g. `federal_tax`, `net_pay`)
   - The COBOL source provenance (paragraph name, condition, line numbers)

5. **Recommend action** — based on the verdict, advise the developer:
   - `VERIFIED`: modernization is behaviorally equivalent; safe to proceed
   - `NOT_VERIFIED`: describe the regression location precisely so a developer
     can fix the Java without guessing

## Commands

Run the Dual Executor (if artifacts are stale or missing):
```
python cbldiff/dual_executor.py
```

Run the parity analyzer directly (bypassing MCP, for debugging):
```
python cbldiff/parity_analyzer.py
```

Invoke via MCP (preferred path when Bob is the orchestrator):
Use the `verify_parity` tool on the `cbldiff-mcp` MCP server.

## Expected Outputs

| Artifact | Description |
|---|---|
| `data/verification_result.json` | Final verdict, parity score, gate outcomes |
| `data/divergence_report.json` | Full cluster-level divergence detail |
| MCP tool response | Concise structured summary returned to Bob |

## MCP Tool Response Schema

```json
{
  "parity_score": 0.957143,
  "parity_gate": { "passes": true, "score": 0.957143, "threshold": 0.95 },
  "critical_rule_gate": { "passes": false, "triggered": true, ... },
  "final_status": "NOT_VERIFIED",
  "divergent_test_ids": ["BND-006", "BND-007", "ITR-005"],
  "affected_rules": ["RULE-05", "RULE-06", "RULE-07"],
  "affected_fields": ["federal_tax", "net_pay"],
  "provenance": [ { "rule_id": "RULE-05", "condition": "GROSS > 500.00 AND GROSS <= 1500.00", ... } ],
  "verdict_explanation": "..."
}
```

## Failure Conditions

| Condition | Action |
|---|---|
| `data/cobol_outputs.json` or `data/java_outputs.json` missing | Stop; ask developer to run Dual Executor |
| MCP server not running / not registered | Tell developer to register `cbldiff/mcp_server.py` in `.bob/mcp.json` and restart Bob |
| `final_status = NOT_VERIFIED` | Surface rule IDs, affected tests, provenance; do NOT silently fix source files |
| `parity_score < 0.95` | Report score and list all divergent test IDs |

## Important Constraints

- **Never edit `cobol/payroll.cbl`** — it is the reference implementation
- **Never edit `data/rules.json`** or `data/test_inputs.json` — these are the source of truth
- **Never silently fix Java regressions** — surface them and let the developer decide
- Treat `NOT_VERIFIED` as a blocking signal, not a warning
