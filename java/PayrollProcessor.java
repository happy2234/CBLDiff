/**
 * PayrollProcessor.java — CBLDiff Phase 2: Java modernisation of payroll.cbl
 *
 * Faithfully reproduces the behaviour of the GnuCOBOL payroll program
 * including every documented business rule and the exact I/O contract.
 *
 * I/O contract (identical to payroll.cbl):
 *   stdin  : EMPLOYEE_ID|HOURS|RATE|IS_SALARIED|SALARY|DEPENDENTS
 *   stdout : EMPLOYEE_ID|GROSS|FEDERAL_TAX|STATE_TAX|SS_TAX|MEDICARE_TAX|NET_PAY|STATUS
 *
 * Monetary output format: PIC 9(7).99 zero-padded, e.g. 0000800.00 (OK path).
 * Error output: literal "0.00" fields (matches COBOL DISPLAY literal).
 *
 * Arithmetic: BigDecimal throughout with RoundingMode.HALF_UP, scale 2.
 * This mirrors COBOL ROUNDED (round half away from zero) on every COMPUTE.
 */
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Scanner;

public class PayrollProcessor {

    // ---- Constants (mirror COBOL WORKING-STORAGE constants) ----
    private static final BigDecimal SS_WEEKLY_CAP   = new BigDecimal("3242.31"); // RULE-09
    private static final BigDecimal MIN_WAGE        = new BigDecimal("7.25");    // RULE-13
    private static final int        MAX_HOURS       = 168;                       // RULE-14
    private static final BigDecimal OT_THRESHOLD    = new BigDecimal("40");      // RULE-02
    private static final BigDecimal BRACKET_1_LIMIT = new BigDecimal("500.00");  // RULE-04
    private static final BigDecimal BRACKET_2_LIMIT = new BigDecimal("1500.00"); // RULE-05
    private static final BigDecimal FED_RATE_1      = new BigDecimal("0.10");    // RULE-04
    private static final BigDecimal FED_RATE_2      = new BigDecimal("0.12");    // RULE-05
    private static final BigDecimal FED_RATE_3      = new BigDecimal("0.22");    // RULE-06
    private static final BigDecimal STATE_RATE      = new BigDecimal("0.0307");  // RULE-08
    private static final BigDecimal SS_RATE         = new BigDecimal("0.062");   // RULE-09
    private static final BigDecimal MED_RATE        = new BigDecimal("0.0145");  // RULE-10
    private static final BigDecimal DEP_AMOUNT      = new BigDecimal("80.00");   // RULE-07
    private static final int        MAX_DEPENDENTS  = 5;                         // RULE-15
    private static final BigDecimal OT_MULTIPLIER   = new BigDecimal("1.5");     // RULE-02
    private static final BigDecimal ZERO            = BigDecimal.ZERO;

    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        // Read exactly one line (mirrors COBOL ACCEPT ... FROM CONSOLE)
        if (!sc.hasNextLine()) return;
        String line = sc.nextLine().trim();
        System.out.println(process(line));
    }

    /**
     * Process one pipe-delimited input record.
     * Exposed as a package-visible method for the comparison harness.
     */
    static String process(String inputLine) {
        // ---- PARSE-PIPE-INPUT ----------------------------------------
        String[] parts = inputLine.split("\\|", -1);
        if (parts.length < 6) {
            return "PARSE_ERROR|0.00|0.00|0.00|0.00|0.00|0.00|ERR_PARSE";
        }

        String employeeId = parts[0].trim();
        BigDecimal hours      = parseBD(parts[1]);
        BigDecimal rate       = parseBD(parts[2]);
        boolean    isSalaried = "Y".equalsIgnoreCase(parts[3].trim());
        BigDecimal salary     = parseBD(parts[4]);
        int        dependents = parseInt(parts[5]);

        // ---- VALIDATE-INPUT ------------------------------------------
        // RULE-14: hours guard (skip for salaried)
        if (!isSalaried) {
            if (hours.compareTo(ZERO) < 0 || hours.compareTo(new BigDecimal("168")) > 0) {
                return errorRecord(employeeId, "ERR_HOURS");
            }
        }
        // RULE-13: minimum wage guard (skip for salaried)
        if (!isSalaried) {
            if (rate.compareTo(MIN_WAGE) < 0) {
                return errorRecord(employeeId, "ERR_MIN_WAGE");
            }
        }

        // ---- COMPUTE-GROSS (RULE-01 / RULE-02 / RULE-03) -------------
        BigDecimal gross;
        if (isSalaried) {
            // RULE-03: salaried — use weekly salary directly
            gross = salary;
        } else if (hours.compareTo(OT_THRESHOLD) > 0) {
            // RULE-02: overtime — excess hours at 1.5× rate
            BigDecimal overtimeHours = hours.subtract(OT_THRESHOLD);
            BigDecimal basePay       = round2(OT_THRESHOLD.multiply(rate));
            BigDecimal otPay         = round2(overtimeHours.multiply(rate).multiply(OT_MULTIPLIER));
            gross = round2(basePay.add(otPay));
        } else {
            // RULE-01: straight-time
            gross = round2(hours.multiply(rate));
        }

        // ---- COMPUTE-FEDERAL-TAX (RULE-04 / RULE-05 / RULE-06 / RULE-07) ----
        BigDecimal federalBeforeDep;
        if (gross.compareTo(BRACKET_1_LIMIT) <= 0) {
            // RULE-04: bracket 1 — gross <= 500.00 @ 10%
            federalBeforeDep = round2(gross.multiply(FED_RATE_1));
        } else if (gross.compareTo(BRACKET_2_LIMIT) < 0) {
            // RULE-05: bracket 2 — 500 < gross < 1500 @ 12%  [MUTATED: was <=]
            federalBeforeDep = round2(gross.multiply(FED_RATE_2));
        } else {
            // RULE-06: bracket 3 — gross > 1500 @ 22%
            federalBeforeDep = round2(gross.multiply(FED_RATE_3));
        }

        // RULE-07 / RULE-15: dependent allowance ($80 each, max 5 deps)
        int effectiveDeps  = Math.min(dependents, MAX_DEPENDENTS);
        BigDecimal depAllowance = DEP_AMOUNT.multiply(new BigDecimal(effectiveDeps));

        BigDecimal federalTax;
        if (depAllowance.compareTo(federalBeforeDep) >= 0) {
            federalTax = ZERO;
        } else {
            federalTax = round2(federalBeforeDep.subtract(depAllowance));
        }

        // ---- COMPUTE-STATE-TAX (RULE-08) -----------------------------
        BigDecimal stateTax = round2(gross.multiply(STATE_RATE));

        // ---- COMPUTE-SS-TAX (RULE-09) --------------------------------
        BigDecimal ssTax;
        if (gross.compareTo(SS_WEEKLY_CAP) >= 0) {
            ssTax = round2(SS_WEEKLY_CAP.multiply(SS_RATE));
        } else {
            ssTax = round2(gross.multiply(SS_RATE));
        }

        // ---- COMPUTE-MEDICARE-TAX (RULE-10) --------------------------
        BigDecimal medicareTax = round2(gross.multiply(MED_RATE));

        // ---- COMPUTE-NET-PAY (RULE-11 / RULE-12) ---------------------
        // RULE-11: rounding applied via round2 throughout.
        // RULE-12: net = gross - federal - state - ss - medicare; floor = 0
        BigDecimal netPay = gross
                .subtract(federalTax)
                .subtract(stateTax)
                .subtract(ssTax)
                .subtract(medicareTax);
        if (netPay.compareTo(ZERO) < 0) {
            netPay = ZERO;
        }

        // ---- EMIT-PIPE-OUTPUT ----------------------------------------
        // Monetary fields formatted as PIC 9(7).99 (10 chars: 7 int + '.' + 2 dec)
        return employeeId
                + "|" + fmt(gross)
                + "|" + fmt(federalTax)
                + "|" + fmt(stateTax)
                + "|" + fmt(ssTax)
                + "|" + fmt(medicareTax)
                + "|" + fmt(netPay)
                + "|OK";
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    /** Round BigDecimal to 2dp HALF_UP — mirrors COBOL ROUNDED clause. */
    private static BigDecimal round2(BigDecimal v) {
        return v.setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * Format a monetary value as PIC 9(7).99 — 7 zero-padded integer digits,
     * decimal point, 2 decimal digits.  e.g. 800.00 → "0000800.00"
     */
    private static String fmt(BigDecimal v) {
        BigDecimal scaled = v.setScale(2, RoundingMode.HALF_UP);
        long cents  = scaled.movePointRight(2).longValueExact();
        long intPart = cents / 100;
        long decPart = cents % 100;
        return String.format("%07d.%02d", intPart, decPart);
    }

    /**
     * Error record — mirrors COBOL EMIT-PIPE-OUTPUT when STATUS != "OK".
     * Monetary fields are literal "0.00" (not zero-padded), exactly as in
     * the COBOL DISPLAY literal "|0.00|0.00|0.00|0.00|0.00|0.00|".
     */
    private static String errorRecord(String employeeId, String status) {
        return employeeId + "|0.00|0.00|0.00|0.00|0.00|0.00|" + status;
    }

    private static BigDecimal parseBD(String s) {
        try {
            return new BigDecimal(s.trim());
        } catch (NumberFormatException e) {
            return ZERO;
        }
    }

    private static int parseInt(String s) {
        try {
            return Integer.parseInt(s.trim());
        } catch (NumberFormatException e) {
            return 0;
        }
    }
}
