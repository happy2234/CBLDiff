      *> ============================================================
      *> payroll.cbl — CBLDiff Demo: Weekly Payroll Tax Calculator
      *> GnuCOBOL 3.2.0
      *>
      *> INPUT  (stdin): pipe-delimited record, one per invocation
      *>   EMPLOYEE_ID|HOURS|RATE|IS_SALARIED|SALARY|DEPENDENTS
      *>   E001|40.00|20.00|N|0.00|0
      *>
      *> OUTPUT (stdout): pipe-delimited result
      *>   EMPLOYEE_ID|GROSS|FEDERAL_TAX|STATE_TAX|SS_TAX|MEDICARE_TAX|NET_PAY|STATUS
      *>   E001|800.00|96.00|24.56|49.60|11.60|618.24|OK
      *>
      *> Note: a thin Python wrapper (payroll_io.py) converts JSON <-> pipe
      *>       format for the CBLDiff dual executor pipeline.
      *>
      *> BUSINESS RULES (source of truth for CBLDiff Rule Miner):
      *>
      *>  RULE-01  Hourly gross = hours * rate
      *>  RULE-02  Overtime: hours > 40 → excess hours at 1.5x rate
      *>  RULE-03  Salaried: IS_SALARIED=Y → gross = weekly salary
      *>  RULE-04  Fed bracket 1: gross <= 500.00        → rate 10%
      *>  RULE-05  Fed bracket 2: 500.00 < gross
      *>                      and gross <= 1500.00        → rate 12%
      *>  RULE-06  Fed bracket 3: gross > 1500.00         → rate 22%
      *>  RULE-07  Dependent allowance: $80 deducted from federal tax
      *>           per dependent (max 5); minimum federal tax = 0
      *>  RULE-08  State tax: flat 3.07% of gross (PA rate)
      *>  RULE-09  Social Security: 6.20% of gross;
      *>           weekly SS cap = 3242.31 (annual $168,600 / 52)
      *>  RULE-10  Medicare: flat 1.45% of gross (no cap)
      *>  RULE-11  All monetary amounts rounded HALF-UP to 2 decimal
      *>           places (COBOL ROUNDED clause = round half away from 0)
      *>  RULE-12  Net pay = gross - federal - state - ss - medicare;
      *>           net pay floor = 0.00
      *>  RULE-13  Minimum wage guard: rate < 7.25 → status = ERR_MIN_WAGE
      *>  RULE-14  Hours guard: hours < 0 or hours > 168
      *>                        → status = ERR_HOURS
      *>  RULE-15  Dependents cap: dependents > 5 capped at 5 (RULE-07)
      *>
      *> ============================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       AUTHOR. CBLDiff-Demo.

       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.

       INPUT-OUTPUT SECTION.
       FILE-CONTROL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.

      *> ---- Raw input buffer ----
       01 WS-INPUT-LINE             PIC X(200).
       01 WS-INPUT-LEN              PIC 9(3).

      *> ---- Parsed input fields (from pipe-delimited string) ----
       01 WS-EMPLOYEE-ID            PIC X(16).
       01 WS-HOURS-STR              PIC X(10).
       01 WS-RATE-STR               PIC X(10).
       01 WS-SALARIED-FLAG          PIC X(1).
       01 WS-SALARY-STR             PIC X(12).
       01 WS-DEPS-STR               PIC X(2).

      *> ---- Numeric parsed values ----
       01 WS-HOURS                  PIC 9(3)V99.
       01 WS-RATE                   PIC 9(5)V99.
       01 WS-SALARY                 PIC 9(7)V99.
       01 WS-DEPENDENTS             PIC 9(1).

      *> ---- Computed values ----
       01 WS-BASE-HOURS             PIC 9(3)V99.
       01 WS-OVERTIME-HOURS         PIC 9(3)V99.
       01 WS-GROSS                  PIC 9(7)V99.
       01 WS-FEDERAL-BEFORE-DEP     PIC 9(7)V99.
       01 WS-DEP-ALLOWANCE          PIC 9(5)V99.
       01 WS-FEDERAL-TAX            PIC 9(7)V99.
       01 WS-STATE-TAX              PIC 9(7)V99.
       01 WS-SS-TAX                 PIC 9(7)V99.
       01 WS-MEDICARE-TAX           PIC 9(7)V99.
       01 WS-NET-PAY                PIC 9(7)V99.
       01 WS-STATUS                 PIC X(20).
       01 WS-EFFECTIVE-DEPS         PIC 9(1).

      *> ---- Formatting for pipe-delimited output ----
       01 WS-GROSS-OUT              PIC 9(7).99.
       01 WS-FED-OUT                PIC 9(7).99.
       01 WS-STATE-OUT              PIC 9(7).99.
       01 WS-SS-OUT                 PIC 9(7).99.
       01 WS-MED-OUT                PIC 9(7).99.
       01 WS-NET-OUT                PIC 9(7).99.

      *> ---- Constants ----
       01 WS-SS-WEEKLY-CAP          PIC 9(5)V99  VALUE 3242.31.
       01 WS-MIN-WAGE               PIC 9(3)V99  VALUE 7.25.
       01 WS-MAX-HOURS              PIC 9(3)     VALUE 168.
       01 WS-OT-THRESHOLD           PIC 9(3)     VALUE 40.
       01 WS-BRACKET-1-LIMIT        PIC 9(5)V99  VALUE 500.00.
       01 WS-BRACKET-2-LIMIT        PIC 9(5)V99  VALUE 1500.00.
       01 WS-FED-RATE-1             PIC V99      VALUE .10.
       01 WS-FED-RATE-2             PIC V99      VALUE .12.
       01 WS-FED-RATE-3             PIC V99      VALUE .22.
       01 WS-STATE-RATE             PIC V9999    VALUE .0307.
       01 WS-SS-RATE                PIC V999     VALUE .062.
       01 WS-MED-RATE               PIC V9999    VALUE .0145.
       01 WS-DEP-AMOUNT             PIC 9(3)V99  VALUE 80.00.
       01 WS-MAX-DEPENDENTS         PIC 9(1)     VALUE 5.

       PROCEDURE DIVISION.

       MAIN-PARA.
           ACCEPT WS-INPUT-LINE FROM CONSOLE
           PERFORM PARSE-PIPE-INPUT
           PERFORM VALIDATE-INPUT
           IF WS-STATUS = "OK"
               PERFORM COMPUTE-GROSS
               PERFORM COMPUTE-FEDERAL-TAX
               PERFORM COMPUTE-STATE-TAX
               PERFORM COMPUTE-SS-TAX
               PERFORM COMPUTE-MEDICARE-TAX
               PERFORM COMPUTE-NET-PAY
           END-IF
           PERFORM EMIT-PIPE-OUTPUT
           STOP RUN.

      *> ============================================================
      *>  INPUT PARSING — pipe-delimited: ID|HOURS|RATE|S|SALARY|DEPS
      *> ============================================================
       PARSE-PIPE-INPUT.
           MOVE "OK" TO WS-STATUS
           UNSTRING WS-INPUT-LINE DELIMITED BY "|"
               INTO WS-EMPLOYEE-ID
                    WS-HOURS-STR
                    WS-RATE-STR
                    WS-SALARIED-FLAG
                    WS-SALARY-STR
                    WS-DEPS-STR
           END-UNSTRING
           MOVE FUNCTION NUMVAL(WS-HOURS-STR)   TO WS-HOURS
           MOVE FUNCTION NUMVAL(WS-RATE-STR)    TO WS-RATE
           MOVE FUNCTION NUMVAL(WS-SALARY-STR)  TO WS-SALARY
           MOVE FUNCTION NUMVAL(WS-DEPS-STR)    TO WS-DEPENDENTS.

      *> ============================================================
      *>  VALIDATION — RULE-13, RULE-14
      *> ============================================================
       VALIDATE-INPUT.
      *>  RULE-14: hours guard (skip for salaried)
           IF WS-SALARIED-FLAG NOT = "Y"
               IF WS-HOURS < 0 OR WS-HOURS > WS-MAX-HOURS
                   MOVE "ERR_HOURS" TO WS-STATUS
               END-IF
           END-IF
      *>  RULE-13: minimum wage guard (skip for salaried)
           IF WS-STATUS = "OK"
               IF WS-SALARIED-FLAG NOT = "Y"
                   IF WS-RATE < WS-MIN-WAGE
                       MOVE "ERR_MIN_WAGE" TO WS-STATUS
                   END-IF
               END-IF
           END-IF.

      *> ============================================================
      *>  RULE-01 / RULE-02 / RULE-03: GROSS PAY
      *> ============================================================
       COMPUTE-GROSS.
      *>  RULE-03: salaried employees use weekly salary directly
           IF WS-SALARIED-FLAG = "Y"
               MOVE WS-SALARY TO WS-GROSS
           ELSE
      *>      RULE-02: overtime
               IF WS-HOURS > WS-OT-THRESHOLD
                   SUBTRACT WS-OT-THRESHOLD FROM WS-HOURS
                       GIVING WS-OVERTIME-HOURS
                   MOVE WS-OT-THRESHOLD TO WS-BASE-HOURS
      *>          RULE-02: excess hours at 1.5x rate
                   COMPUTE WS-GROSS ROUNDED =
                       (WS-BASE-HOURS * WS-RATE) +
                       (WS-OVERTIME-HOURS * WS-RATE * 1.5)
               ELSE
      *>          RULE-01: straight-time gross
                   MOVE WS-HOURS TO WS-BASE-HOURS
                   COMPUTE WS-GROSS ROUNDED =
                       WS-BASE-HOURS * WS-RATE
               END-IF
           END-IF.

      *> ============================================================
      *>  RULE-04 / RULE-05 / RULE-06 / RULE-07: FEDERAL TAX
      *> ============================================================
       COMPUTE-FEDERAL-TAX.
      *>  RULE-04: bracket 1 — gross <= 500.00 taxed at 10%
           IF WS-GROSS <= WS-BRACKET-1-LIMIT
               COMPUTE WS-FEDERAL-BEFORE-DEP ROUNDED =
                   WS-GROSS * WS-FED-RATE-1

      *>  RULE-05: bracket 2 — 500 < gross <= 1500 taxed at 12%
           ELSE IF WS-GROSS > WS-BRACKET-1-LIMIT AND
                   WS-GROSS <= WS-BRACKET-2-LIMIT
               COMPUTE WS-FEDERAL-BEFORE-DEP ROUNDED =
                   WS-GROSS * WS-FED-RATE-2

      *>  RULE-06: bracket 3 — gross > 1500 taxed at 22%
           ELSE
               COMPUTE WS-FEDERAL-BEFORE-DEP ROUNDED =
                   WS-GROSS * WS-FED-RATE-3
           END-IF

      *>  RULE-07: dependent allowance — $80 per dependent, max 5
      *>  RULE-15: cap dependents at 5
           IF WS-DEPENDENTS > WS-MAX-DEPENDENTS
               MOVE WS-MAX-DEPENDENTS TO WS-EFFECTIVE-DEPS
           ELSE
               MOVE WS-DEPENDENTS TO WS-EFFECTIVE-DEPS
           END-IF

           COMPUTE WS-DEP-ALLOWANCE =
               WS-EFFECTIVE-DEPS * WS-DEP-AMOUNT

           IF WS-DEP-ALLOWANCE >= WS-FEDERAL-BEFORE-DEP
               MOVE 0 TO WS-FEDERAL-TAX
           ELSE
               COMPUTE WS-FEDERAL-TAX ROUNDED =
                   WS-FEDERAL-BEFORE-DEP - WS-DEP-ALLOWANCE
           END-IF.

      *> ============================================================
      *>  RULE-08: STATE TAX — flat 3.07% of gross
      *> ============================================================
       COMPUTE-STATE-TAX.
           COMPUTE WS-STATE-TAX ROUNDED =
               WS-GROSS * WS-STATE-RATE.

      *> ============================================================
      *>  RULE-09: SOCIAL SECURITY — 6.20% up to weekly cap $3,242.31
      *> ============================================================
       COMPUTE-SS-TAX.
           IF WS-GROSS >= WS-SS-WEEKLY-CAP
               COMPUTE WS-SS-TAX ROUNDED =
                   WS-SS-WEEKLY-CAP * WS-SS-RATE
           ELSE
               COMPUTE WS-SS-TAX ROUNDED =
                   WS-GROSS * WS-SS-RATE
           END-IF.

      *> ============================================================
      *>  RULE-10: MEDICARE — flat 1.45% of gross
      *> ============================================================
       COMPUTE-MEDICARE-TAX.
           COMPUTE WS-MEDICARE-TAX ROUNDED =
               WS-GROSS * WS-MED-RATE.

      *> ============================================================
      *>  RULE-11 (applied via ROUNDED clauses throughout)
      *>  RULE-12: NET PAY = gross - all taxes; floor at 0.00
      *> ============================================================
       COMPUTE-NET-PAY.
           COMPUTE WS-NET-PAY =
               WS-GROSS - WS-FEDERAL-TAX - WS-STATE-TAX
               - WS-SS-TAX - WS-MEDICARE-TAX
           IF WS-NET-PAY < 0
               MOVE 0 TO WS-NET-PAY
           END-IF.

      *> ============================================================
      *>  OUTPUT EMISSION — pipe-delimited
      *>  FORMAT: ID|GROSS|FEDERAL|STATE|SS|MEDICARE|NET|STATUS
      *> ============================================================
       EMIT-PIPE-OUTPUT.
           IF WS-STATUS NOT = "OK"
               DISPLAY FUNCTION TRIM(WS-EMPLOYEE-ID)
                   "|0.00|0.00|0.00|0.00|0.00|0.00|"
                   FUNCTION TRIM(WS-STATUS)
           ELSE
               MOVE WS-GROSS        TO WS-GROSS-OUT
               MOVE WS-FEDERAL-TAX  TO WS-FED-OUT
               MOVE WS-STATE-TAX    TO WS-STATE-OUT
               MOVE WS-SS-TAX       TO WS-SS-OUT
               MOVE WS-MEDICARE-TAX TO WS-MED-OUT
               MOVE WS-NET-PAY      TO WS-NET-OUT
               DISPLAY FUNCTION TRIM(WS-EMPLOYEE-ID)
                   "|" WS-GROSS-OUT
                   "|" WS-FED-OUT
                   "|" WS-STATE-OUT
                   "|" WS-SS-OUT
                   "|" WS-MED-OUT
                   "|" WS-NET-OUT
                   "|OK"
           END-IF.
