---
description: "Guide COBOL-to-Java baseline validation through the 10-step process: copy baseline, generate scripts, load data, configure environment, run program, debug, compare outputs, fix mismatches, generate reports, and close validation."
mode: agent
---

# COBOL-to-Java Baseline Validation

You are guiding a developer through validating a converted Java program against its original COBOL baseline. The goal is to ensure the Java output **exactly matches** the COBOL output.

## Arguments

- `{Baseline_Name}` — The baseline identifier (e.g., `P02045-HPPL486P`)
- `{SG_Group}` — The SG group folder (e.g., `SG02`). Ask if not provided.
- `{Program_Name}` — The program name for branch naming. Derive from Baseline_Name if not given.

## Path Configuration

Use these defaults unless the user overrides them:

| Placeholder | Default |
|---|---|
| `{BASE_DIR}` | `D:\Users\$env:USERNAME\baseline` |
| `{SDRIVE}` | `S:\Validation` |
| `{FILES_DIR}` | `{BASE_DIR}\files` |
| `{AFTER_DIR}` | `{FILES_DIR}\AFTER` |

Derived per baseline:
- Local root: `{BASE_DIR}\{SG_Group}\{Baseline_Name}\`
- LOAD scripts: `{BASE_DIR}\{SG_Group}\{Baseline_Name}\LOAD\`
- REPORT output: `{BASE_DIR}\{SG_Group}\{Baseline_Name}\REPORT\`
- RESULT output: `{BASE_DIR}\{SG_Group}\{Baseline_Name}\RESULT\`

## The 10-Step Validation Process

Walk the user through each step sequentially. **Do not skip steps.** Confirm completion before proceeding.

### Step 1: Copy Baseline from S-Drive
Run: `s {Baseline_Name}`
Verify: BF4 and AFT CSV files present locally, plus any input flat files.

### Step 2: Generate Load/Unload Scripts
Run: `new-loadUnloadScripts {Baseline_Name}`
Verify: LOAD folder has SQL scripts matching each BF4 CSV.

### Step 3: Load BEFORE Data
Run: `l {Baseline_Name}`
Verify: No SQL errors, row counts match CSV files.

**Common errors:** Table not found → check schema; Data truncation → check VARCHAR lengths; Constraint violation → load parent tables first; Duplicate key → truncate and retry.

### Step 4: Configure Environment
4a. Copy input flat files to `{FILES_DIR}`.
4b. Create/update `.env` with correct `INPUT_FILE_PATH` and `OUTPUT_FILE_PATH`.
4c. Verify `Application.prop` parameters (file paths, DB connections, runtime flags).
4d. Ensure `{AFTER_DIR}` exists and is **empty**.

### Step 5: Create Branch and Run
5a. Create branch: `git checkout -b {SG_Group}/{Program_Name}`
5b. Run the Java program in STS. Expect clean completion with output files produced.

### Step 6: Resolve Runtime Errors
If the program fails, debug using this decision tree:
- **Known error?** → Check previous PRs in Azure DevOps for established fixes.
- **Data error** (NPE, bad format)? → Verify input data, `.env`, `Application.prop`.
- **Logic error** (wrong calculation)? → Compare Java logic against COBOL source.
- **Unknown** → Escalate with stack trace, input sample, and repro steps.

Common issues: NullPointerException (check COBOL defaults), FileNotFoundException (verify `.env` paths), NumberFormatException (check COMP-3/PACKED handling), DateTimeParseException (YYYYMMDD vs Java pattern).

**Keep fixing and re-running until the program succeeds.**

### Step 7: Unload and Compare
7a. Run: `u {Baseline_Name}` to export AFTER tables to CSV.
7b. Compare in Beyond Compare: baseline AFT files (left) vs Java AFTER outputs (right).
- Files identical → PASS
- Minor diffs (timestamps, system IDs) → Document as acceptable
- Data mismatches → Proceed to Step 8
- Missing/extra files → Debug (back to Step 6)

### Step 8: Fix Mismatches
1. Identify mismatched fields (table, column, row key, expected vs actual).
2. Locate the logic in COBOL source.
3. Compare with Java implementation.
4. Fix the Java code.
5. **Re-run from Step 3** (reload data → re-execute → re-compare).

Common causes: rounding (COMP-3 vs BigDecimal), string padding (PIC X space-padded), sign handling, date arithmetic, missing conditional branches, REDEFINES handling.

**Repeat Steps 3–8 until ALL files match.**

### Step 9: Generate HTML Reports
In Beyond Compare, generate HTML comparison reports for each file pair. Save to `{BASE_DIR}\{SG_Group}\{Baseline_Name}\REPORT\`.

### Step 10: Generate Word Report
Run: `New-ReportDraft {Baseline_Name}`
Verify report contains: baseline name, date, file-by-file pass/fail, accepted differences, validator name.

## Post-Validation Closure

After all steps pass:
1. Create RESULT folder with all AFTER CSVs and output files.
2. Copy REPORT and RESULT to S-drive.
3. Commit and push: `git push origin {SG_Group}/{Program_Name}`
4. Raise PR titled `{SG_Group}/{Program_Name} - Validation Complete`, link to Azure DevOps work item.
5. Close validation ticket in Azure DevOps, attach Word report.

## Critical Reminders

- **Always reload data (Step 3) before re-running** — otherwise DB has stale AFTER-state data.
- **Clear `{AFTER_DIR}` before each run** — avoid mixing outputs from previous executions.
- **Compare AFT (baseline) vs AFTER (Java)** — never compare BF4 with AFT.
- **Check previous PRs before debugging** — the fix may already exist.
- **Word report is mandatory** — even if all files match, it's needed for audit trail.
