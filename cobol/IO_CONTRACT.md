# payroll.cbl — I/O Contract

## Purpose
Weekly payroll tax calculator for one employee record.
Used as the **original COBOL implementation** in CBLDiff behavioral parity verification.

## Invocation
```bash
echo 'E001|40.00|20.00|N|0.00|0' | ./payroll
```
One pipe-delimited record per stdin line. One pipe-delimited record written to stdout.
The program reads exactly one line, computes, outputs one line, and exits.

## Input Format
```
EMPLOYEE_ID|HOURS|RATE|IS_SALARIED|SALARY|DEPENDENTS
```

| Field        | Type    | Description                                         |
|--------------|---------|-----------------------------------------------------|
| EMPLOYEE_ID  | string  | Up to 16 characters                                 |
| HOURS        | decimal | Worked hours this week (0.00–168.00 for hourly)     |
| RATE         | decimal | Hourly rate in USD/hr (ignored if salaried)         |
| IS_SALARIED  | char    | `Y` = salaried, `N` = hourly                        |
| SALARY       | decimal | Weekly salary in USD (0.00 if hourly)               |
| DEPENDENTS   | integer | Number of dependents (0–5; values > 5 capped at 5)  |

### Salaried employees
Set `IS_SALARIED=Y` and provide `SALARY` (weekly amount). `HOURS` and `RATE` are ignored.

### Hourly employees
Set `IS_SALARIED=N`. Provide `HOURS` and `RATE`. `SALARY` is ignored.

## Output Format
```
EMPLOYEE_ID|GROSS|FEDERAL_TAX|STATE_TAX|SS_TAX|MEDICARE_TAX|NET_PAY|STATUS
```

All monetary values have exactly 7 integer digits and 2 decimal places (zero-padded), e.g. `0000800.00`.

| Field        | Description                                          |
|--------------|------------------------------------------------------|
| EMPLOYEE_ID  | Echo of input ID                                     |
| GROSS        | Gross pay before taxes                               |
| FEDERAL_TAX  | Federal income tax withheld (after dependent credit) |
| STATE_TAX    | State income tax withheld                            |
| SS_TAX       | Social Security tax withheld                         |
| MEDICARE_TAX | Medicare tax withheld                                |
| NET_PAY      | Take-home pay (gross minus all taxes; floor = 0.00)  |
| STATUS       | `OK`, `ERR_HOURS`, or `ERR_MIN_WAGE`                 |

### Error outputs
On validation error, all monetary fields are `0.00` and STATUS contains the error code.

| STATUS        | Meaning                                         |
|---------------|-------------------------------------------------|
| `OK`          | Successful computation                          |
| `ERR_HOURS`   | hours < 0 or hours > 168 (RULE-14)             |
| `ERR_MIN_WAGE`| hourly rate < $7.25/hr (RULE-13)               |

## JSON Adapter
`payroll_io.py` provides JSON ↔ pipe conversion for the CBLDiff dual executor:
```python
# accepts JSON record, returns JSON record
result = run_cobol({"employee_id":"E001","hours":40,"rate":20,...})
```

## Business Rules

| Rule ID  | Description                                                   | Source Lines |
|----------|---------------------------------------------------------------|--------------|
| RULE-01  | Hourly gross = hours × rate                                   | ~168         |
| RULE-02  | Overtime: hours > 40 -> excess at 1.5× rate                   | ~162         |
| RULE-03  | Salaried gross = weekly salary (hours/rate ignored)           | ~155         |
| RULE-04  | Federal bracket 1: gross ≤ 500.00 -> 10% tax                  | ~180         |
| RULE-05  | Federal bracket 2: gross > 500 and ≤ 1500.00 -> 12% tax       | ~185         |
| RULE-06  | Federal bracket 3: gross > 1500.00 -> 22% tax                 | ~191         |
| RULE-07  | Dependent allowance: $80/dependent deducted from federal tax  | ~196         |
| RULE-08  | State tax: flat 3.07% of gross                                | ~213         |
| RULE-09  | Social Security: 6.20% of gross; weekly cap = $3,242.31       | ~219         |
| RULE-10  | Medicare: flat 1.45% of gross (no cap)                        | ~229         |
| RULE-11  | All monetary values rounded half-up to 2 decimal places       | (ROUNDED clauses) |
| RULE-12  | Net pay = gross − federal − state − ss − medicare; floor = 0  | ~235         |
| RULE-13  | Hourly rate < $7.25 -> ERR_MIN_WAGE                           | ~145         |
| RULE-14  | Hours < 0 or hours > 168 -> ERR_HOURS                         | ~140         |
| RULE-15  | Dependents > 5 capped at 5 (RULE-07 sub-rule)                | ~197         |

## Key Boundary Conditions for CBLDiff Testing

| Boundary                       | Value        | Rules Tested       |
|--------------------------------|--------------|--------------------|
| Federal bracket 1 top          | 500.00       | RULE-04, RULE-05   |
| **Federal bracket 2 top (KEY)**| **1500.00**  | **RULE-05, RULE-06** |
| Overtime threshold             | 40.00 hrs    | RULE-01, RULE-02   |
| SS weekly cap                  | 3242.31      | RULE-09            |
| Minimum wage floor             | 7.25         | RULE-13            |
| Maximum hours                  | 168.00       | RULE-14            |
| Dependent allowance wipes tax  | varies       | RULE-07            |
| Net pay floor                  | 0.00         | RULE-12            |

## Decimal Formatting
Output monetary values are zero-padded 9-character strings: `9999999.99`.
Python parsing: `float(field)`.

## Environment Requirements
```bash
export LC_ALL=C
export COB_DECIMAL_POINT=.
```
