# CBLDiff

## Behavioral Parity Verification for AI-Modernized COBOL

**"AI can modernize legacy code. CBLDiff verifies that the behavior survived."**

### The Problem

When AI modernizes legacy COBOL into modern languages like Java, textual code comparison is insufficient to prove behavioral equivalence. Two implementations may be structurally different but functionally identical—or worse, subtly different in ways that break critical business rules. Traditional diffs cannot detect these behavioral divergences.

### The Solution

CBLDiff executes the original COBOL and modernized Java against the **same deterministic test suite**, captures their outputs, and compares their behavior **execution-by-execution**. Any divergence is detected, analyzed by rule, and reported with full traceability.

### High-Level Workflow

```mermaid
flowchart TD
    A["Legacy COBOL<br/>(payroll.cbl)"]
    B["IBM Bob<br/>(Agent Mode)"]
    C["Modernized Java<br/>(Java 21)"]
    D["CBLDiff<br/>(Verification Engine)"]
    E1["Rule Miner"]
    E2["Test Synthesizer"]
    E3["Dual Executor"]
    E4["Behavioral<br/>Parity Analyzer"]
    E5["Critical-Rule<br/>Verification Gate"]
    F["VERIFIED/<br/>NOT_VERIFIED"]
    
    A -->|source code| B
    B -->|modernization| C
    C -->|Java implementation| D
    D -->|orchestrates| E1
    D -->|orchestrates| E2
    D -->|orchestrates| E3
    D -->|orchestrates| E4
    D -->|orchestrates| E5
    E5 -->|final verdict| F
    
    style A fill:#e1f5ff
    style B fill:#fff3e0
    style C fill:#e1f5ff
    style D fill:#f3e5f5
    style E1 fill:#f3e5f5
    style E2 fill:#f3e5f5
    style E3 fill:#f3e5f5
    style E4 fill:#f3e5f5
    style E5 fill:#f3e5f5
    style F fill:#c8e6c9
```

---

## Key Results

| Metric | Value |
|--------|-------|
| Business Rules Extracted | 15 |
| Deterministic Test Cases | 70 |
| Final Baseline: Matching Tests | 70/70 |
| Final Baseline: Divergent Tests | 0 |
| **Behavioral Parity** | **100% VERIFIED** |

### Verification Evidence

![CBLDiff Verification Result](bob_sessions/04-phase6-parity-verification.png)

**Figure 1:** Final verification result from IBM Bob integration showing 70/70 matching tests, 0 divergent tests, and [PASS] VERIFIED status.

---

## Controlled Regression Demonstration

CBLDiff demonstrates its detection capability through a controlled regression test:

### Baseline State
- **Condition:** `gross <= 1500.00`
- **Result:** 70/70 tests matching, 100% parity, VERIFIED

### Injected Regression

A controlled regression changed the Java federal-tax boundary from:

```diff
- gross <= 1500.00
+ gross < 1500.00
```

**Critical Boundary Tested:** `gross = 1500.00`

### Regression Detection Results

The mutation caused 3 divergent test cases:

| Test ID | Category | Details |
|---------|----------|---------|
| BND-006 | Boundary | gross exactly at 1500.00 |
| BND-007 | Boundary | gross at 1500.00 edge case |
| ITR-005 | Interaction | Rule-05 interaction with other tax rules |

**Verification Impact:**
- Matching Tests: 67/70
- Divergent Tests: 3
- Parity Score: 95.71%
- Affected Rule: RULE-05 (Federal tax bracket boundary)
- Affected Fields: federal_tax, net_pay
- **Final Status: NOT_VERIFIED**

### Post-Repair Verification
After correcting the Java implementation back to the original logic (`gross <= 1500.00`):
- **Matching Tests:** 70/70
- **Divergent Tests:** 0
- **Parity:** 100%
- **Status:** [PASS] **VERIFIED**

This demonstrates CBLDiff's ability to detect behavioral regressions and validate repairs.

### Regression Detection Workflow

```mermaid
flowchart TD
    A["Correct Implementation<br/>gross <code>&lt;=</code> 1500.00"]
    B["Intentional Mutation<br/>gross <code>&lt;</code> 1500.00"]
    C["70 Tests Executed"]
    D["3 Divergent Tests Found:<br/>BND-006<br/>BND-007<br/>ITR-005"]
    E["Parity Score<br/>95.71%"]
    F["RULE-05 Analysis<br/>Boundary: gross = 1500.00<br/>Affected:<br/>federal_tax, net_pay"]
    G["Critical-Rule Gate<br/>FAIL"]
    H["NOT_VERIFIED"]
    I["Java Repair<br/>gross <code>&lt;=</code> 1500.00"]
    J["70/70 Tests Matching<br/>100% Parity"]
    K["VERIFIED"]
    
    A -->|mutate| B
    B -->|execute| C
    C -->|analyze| D
    D -->|calculate| E
    E -->|trace| F
    F -->|evaluate| G
    G -->|verdict| H
    
    I -->|restore correct code| J
    J -->|verdict| K
    
    style A fill:#c8e6c9
    style B fill:#ffccbc
    style C fill:#fff9c4
    style D fill:#ffccbc
    style E fill:#ffccbc
    style F fill:#ffccbc
    style G fill:#ffccbc
    style H fill:#ffcdd2
    style I fill:#c8e6c9
    style J fill:#c8e6c9
    style K fill:#c8e6c9
```

---

## How CBLDiff Works

CBLDiff is a 5-stage verification pipeline:

1. **Rule Miner**  
   Analyzes COBOL source code to extract business rules and logical conditions.

2. **Test Synthesizer**  
   Generates deterministic test cases that exercise all extracted rules and boundary conditions.

3. **Dual Executor**  
   Executes both the original COBOL and modernized Java with identical inputs; captures and normalizes outputs.

4. **Behavioral Parity Analyzer**  
   Compares execution results test-by-test and rule-by-rule; identifies divergences and their root causes.

5. **Critical-Rule Verification Gate**  
   Applies pass/fail logic based on divergence threshold; outputs final verification status.

### Detailed Verification Pipeline

```mermaid
flowchart TD
    A["cobol/payroll.cbl<br/>(Source)"]
    B["Rule Miner"]
    C["data/rules.json<br/>(15 Rules)"]
    D["Test Synthesizer"]
    E["data/test_inputs.json<br/>(70 Tests)"]
    F["Dual Executor"]
    G["cobol/payroll.cbl<br/>Execution"]
    H["java/PayrollProcessor.java<br/>Execution"]
    I["data/cobol_outputs.json"]
    J["data/java_outputs.json"]
    K["Behavioral<br/>Parity Analyzer"]
    L["Field-by-field<br/>Comparison"]
    M["Divergence<br/>Analysis"]
    N["Rule/Provenance<br/>Mapping"]
    O["data/divergence_report.json"]
    P["Parity Gate<br/>score >= 0.95?"]
    Q["Critical-Rule Gate<br/>no divergence?"]
    R["data/verification_result.json"]
    S["VERIFIED/<br/>NOT_VERIFIED"]
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    F --> H
    G --> I
    H --> J
    I --> K
    J --> K
    K --> L
    L --> M
    M --> N
    N --> O
    O --> P
    P -->|yes| Q
    P -->|no| R
    Q -->|yes| R
    Q -->|no| R
    R --> S
    
    style A fill:#e1f5ff
    style C fill:#f3e5f5
    style E fill:#f3e5f5
    style G fill:#e1f5ff
    style H fill:#e1f5ff
    style I fill:#f3e5f5
    style J fill:#f3e5f5
    style O fill:#f3e5f5
    style R fill:#f3e5f5
    style S fill:#c8e6c9
```

---

## IBM Bob Integration

CBLDiff is integrated with **IBM Bob**, an AI agent platform for enterprise code transformation. Bob orchestrates the modernization and verification workflow:

### IBM Bob Integration Architecture

```mermaid
flowchart TD
    A["Developer"]
    B["IBM Bob<br/>(Agent Mode)"]
    C["parity-check<br/>Skill"]
    D["Local MCP Server"]
    E["verify_parity<br/>MCP Tool"]
    F["cbldiff/<br/>parity_analyzer.py"]
    G["Verification Result"]
    H["Structured Result<br/>to Bob UI"]
    
    A -->|modernize COBOL| B
    B -->|invoke| C
    C -->|call| D
    D -->|execute| E
    E -->|run engine| F
    F -->|generate| G
    G -->|return| H
    H -->|display| B
    
    style A fill:#fff9c4
    style B fill:#fff3e0
    style C fill:#f3e5f5
    style D fill:#f3e5f5
    style E fill:#f3e5f5
    style F fill:#e8f5e9
    style G fill:#f3e5f5
    style H fill:#fff3e0
```

**Integration Components:**
- **Bob Mode:** Plan & Agent modes
- **Skill:** `parity-check` (embedded in workspace)
- **Server:** Local Model Context Protocol (MCP) server
- **Tool:** `verify_parity` MCP tool
- **Custom Mode:** `CBLDiff Verify`

### Integration Files
- [.bob/mcp.json](.bob/mcp.json) — MCP server configuration
- [.bob/custom_modes.yaml](.bob/custom_modes.yaml) — Custom verification mode
- [.bob/skills/parity-check/SKILL.md](.bob/skills/parity-check/SKILL.md) — Parity check skill definition

---

## Verification Data & Artifacts

| Artifact | Purpose |
|----------|---------|
| [data/rules.json](data/rules.json) | Extracted business rules (15 rules) |
| [data/test_inputs.json](data/test_inputs.json) | Synthesized test cases (70 tests) |
| [data/execution_summary.json](data/execution_summary.json) | Execution results summary |
| [data/divergence_report.json](data/divergence_report.json) | Divergence analysis by rule |
| [data/verification_result.json](data/verification_result.json) | Final verification verdict |

### Verification Decision Logic

```mermaid
flowchart TD
    A["Parity Score<br/>vs Threshold"]
    B{"Parity Score<br/>>= 0.95?"}
    C{"Critical-Rule<br/>Divergence?"}
    D["[PASS]<br/>VERIFIED"]
    E["[FAIL]<br/>NOT_VERIFIED"]
    F["[FAIL]<br/>NOT_VERIFIED"]
    
    A --> B
    B -->|YES| C
    B -->|NO| E
    C -->|NO| D
    C -->|YES| F
    
    style A fill:#fff9c4
    style B fill:#ffe0b2
    style C fill:#ffe0b2
    style D fill:#c8e6c9
    style E fill:#ffcdd2
    style F fill:#ffcdd2
```

**Verification Decision:**
- **VERIFIED:** Parity score >= 0.95 AND no critical-rule divergence
- **NOT_VERIFIED:** Parity score < 0.95 OR critical-rule divergence detected

---

## Bob Development Evidence

The repository contains comprehensive session records and evidence from IBM Bob integration development:

- [bob_sessions/bob-task-history-2026-08-28.md](bob_sessions/bob-task-history-2026-08-28.md) — Detailed task history
- [bob_sessions/phase8-bob-skill-mcp.md](bob_sessions/phase8-bob-skill-mcp.md) — Skill & MCP integration documentation
- [bob_sessions/phase8-integration-notes.md](bob_sessions/phase8-integration-notes.md) — Integration notes and learnings
- [bob_sessions/phase9-repair-final-reverification.md](bob_sessions/phase9-repair-final-reverification.md) — Regression repair and re-verification
- [bob_sessions/01-bob-skill-mcp.png](bob_sessions/01-bob-skill-mcp.png) — Skill execution screenshot
- [bob_sessions/02-phase9-repair-progress.png](bob_sessions/02-phase9-repair-progress.png) — Repair progress screenshot
- [bob_sessions/03-phase9-boundary-checks.png](bob_sessions/03-phase9-boundary-checks.png) — Boundary validation screenshot
- [bob_sessions/04-phase6-parity-verification.png](bob_sessions/04-phase6-parity-verification.png) — Parity verification screenshot

---

## Demo: Baseline -> Regression -> Detection -> Repair -> Verification

1. **Baseline Verification**  
   Execute original COBOL and Java; confirm 100% behavioral parity across 70 tests.

2. **Controlled Regression**  
   Inject a boundary condition error in Java (`gross < 1500.00` instead of `gross <= 1500.00`).

3. **Divergence Detection**  
   CBLDiff identifies 3 failing tests (BND-006, BND-007, ITR-005) affecting RULE-05; parity drops to 95.71%.

4. **Repair**  
   Correct the Java condition back to the original logic.

5. **Re-Verification**  
   Re-run CBLDiff; confirm 70/70 tests passing, 100% parity restored, status: VERIFIED.

This end-to-end cycle demonstrates CBLDiff's ability to catch behavioral regressions and validate corrections.

---

## Why CBLDiff is Different

| Approach | Limitation |
|----------|-----------|
| **Textual Code Diff** | Cannot detect behavioral equivalence; may miss subtle semantic differences |
| **Unit Testing** | Depends on test coverage; does not guarantee rule preservation across all inputs |
| **Abstract Interpretation** | Computationally expensive; difficult to trace to business rules |
| **CBLDiff (Behavioral Parity)** | **Deterministic test execution** + **rule-level traceability** = provable behavioral equivalence over test suite |

---

## AI/ML Relevance

CBLDiff employs deterministic, rule-based verification with full explainability:

- **Rule Mining:** Deterministic static analysis of COBOL source code.
- **Test Synthesis:** Deterministic generation of test cases using boundary value analysis.
- **Parity Analysis:** Deterministic comparison of execution results.
- **Explainability & Provenance:** Every divergence is traced to a specific rule and test case; results are fully auditable.

**Note on ML:** CBLDiff's core verification engine is rule-based and deterministic. ML/clustering techniques were intentionally deferred as future work when the baseline achieved 100% parity with zero divergences. ML could support advanced anomaly detection or pattern discovery but is not currently the primary verification mechanism.

---

## Repository Structure

```
cbldiff/
├── README.md                          # This file
├── cbldiff/                           # Core verification engine
│   ├── __init__.py
│   ├── dual_executor.py               # COBOL + Java dual execution
│   ├── parity_analyzer.py             # Behavioral comparison logic
│   ├── rule_miner.py                  # Business rule extraction
│   └── test_synthesizer.py            # Deterministic test generation
├── cobol/
│   ├── payroll.cbl                    # Original COBOL payroll processor
│   ├── IO_CONTRACT.md                 # Input/output contract specification
│   ├── sample_inputs.txt              # Sample test inputs
│   ├── smoke_test.sh                  # Quick smoke test
│   └── quicktest.sh                   # Minimal test script
├── java/
│   ├── PayrollProcessor.java          # Modernized Java implementation
│   ├── PayrollBatchRunner.java        # Batch test runner
│   ├── run.sh                         # Execution script
│   └── compare.sh                     # Comparison script
├── data/                              # Verification artifacts
│   ├── rules.json                     # Extracted business rules
│   ├── test_inputs.json               # Test case definitions
│   ├── java_outputs.json              # Java execution results
│   ├── cobol_outputs.json             # COBOL execution results
│   ├── execution_summary.json         # Summary statistics
│   ├── divergence_report.json         # Detailed divergence analysis
│   └── verification_result.json       # Final verification verdict
├── .bob/                              # IBM Bob integration
│   ├── mcp.json                       # MCP server configuration
│   ├── custom_modes.yaml              # Custom CBLDiff verification mode
│   └── skills/parity-check/SKILL.md   # Parity check skill
├── bob_sessions/                      # Development evidence & session logs
│   ├── bob-task-history-2026-08-28.md
│   ├── phase8-bob-skill-mcp.md
│   ├── phase8-integration-notes.md
│   ├── phase9-repair-final-reverification.md
│   └── *.png                          # Session screenshots
└── reports/                           # Generated reports
```

---

## Test Coverage

CBLDiff synthesizes 70 deterministic test cases across five categories to achieve comprehensive rule coverage:

| Test Category | Count | Purpose |
|---------------|-------|---------|
| **Boundary** | 20 | Test rule boundary conditions (e.g., gross = 1500.00) |
| **Normal** | 16 | Exercise standard business logic paths |
| **Error** | 8 | Validate error handling and edge cases |
| **Interaction** | 16 | Test rule combinations and dependencies |
| **Adversarial** | 10 | Challenge edge cases with extreme values |
| **TOTAL** | **70** | **Full rule coverage** |

Each test case exercises one or more of the 15 extracted business rules and generates structured provenance data to trace divergences back to specific rules.

---

## Running the Project

### Developer Workflow

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Bob as IBM Bob
    participant CBL as COBOL
    participant Java as Java
    participant CBLDiff as CBLDiff
    
    Dev->>Bob: Modernize legacy COBOL
    Bob->>Java: Generate Java modernization
    Dev->>CBLDiff: Verify parity
    CBLDiff->>CBL: Execute test suite
    CBLDiff->>Java: Execute same test suite
    CBLDiff->>CBLDiff: Compare outputs field-by-field
    CBLDiff->>Bob: Return structured result
    Bob->>Dev: Display VERIFIED / NOT_VERIFIED
```

This workflow ensures developers can validate behavioral equivalence after AI-driven modernization before deploying to production.

### Environment
- **OS:** Ubuntu 20.04+ (WSL2 on Windows)
- **GnuCOBOL:** 3.2.0
- **Java:** 21+
- **Python:** 3.14+
- **Git**

### Prerequisites
```bash
# Install GnuCOBOL
sudo apt-get install gnucobol

# Install Java 21
sudo apt-get install openjdk-21-jdk

# Install Python dependencies
pip install -r requirements.txt  # (if present in repo)
```

### Verify Behavioral Parity
```bash
cd /home/gaurav/cbldiff

# Run COBOL execution
cd cobol && ./quicktest.sh
cd ..

# Run Java execution
cd java && ./run.sh
cd ..

# Run parity analysis
python3 -m cbldiff.parity_analyzer
```

### Expected Output
```
Execution Summary:
  Total Tests: 70
  Matching: 70
  Divergent: 0
  Parity: 100.00%
Status: VERIFIED
```

### With IBM Bob
CBLDiff can also be invoked through IBM Bob using the embedded `parity-check` skill:
1. Open the project in IBM Bob (Agent Mode)
2. Run the `CBLDiff Verify` custom mode
3. Bob will execute the verification and report the result

---

## Limitations

CBLDiff provides **behavioral equivalence verification over the generated test suite**. It does **not**:

- Mathematically prove complete program equivalence for every possible input
- Replace formal methods or theorem provers
- Handle non-deterministic or stateful operations (I/O, system time, randomness)
- Verify performance characteristics or resource consumption

Verification is limited to the coverage of the test suite. Additional rules, boundary conditions, or edge cases may require synthetic test expansion.

---

## Project Goal

**CBLDiff demonstrates that behavioral verification through deterministic dual execution is a practical, explainable, and auditable method for validating AI-modernized legacy code.**

By combining rule extraction, test synthesis, dual execution, and behavioral comparison, CBLDiff provides confidence that modernized code preserves the original business behavior—essential for enterprise COBOL-to-Java transformations where correctness is non-negotiable.

---

## Repository

**GitHub:** [happy2234/CBLDiff](https://github.com/happy2234/CBLDiff)

---

*CBLDiff was developed as a submission for the IBM TechXchange 2026 Hackathon.*
