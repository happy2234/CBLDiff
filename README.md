# CBLDiff

## Behavioral Parity Verification for AI-Modernized COBOL

CBLDiff is a verification workflow for AI-assisted legacy modernization.

The project addresses a key problem in COBOL modernization: after legacy code is translated into a modern language, how can a developer verify that the new implementation preserves the original business behavior?

CBLDiff compares the original COBOL implementation with its modernized Java implementation using the same generated test inputs and produces an explainable verification result.

## Core Workflow

```text
Legacy COBOL
     |
     v
IBM Bob Agent Mode
     |
     v
Modernized Java
     |
     v
CBLDiff
     |
     +--> Rule Miner
     |
     +--> Test Synthesizer
     |
     +--> Dual Executor
     |
     +--> Behavioral Parity Analyzer
     |
     +--> Verification Gate
     |
     v
VERIFIED / NOT VERIFIED
