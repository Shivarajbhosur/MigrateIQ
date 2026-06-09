---
name: baseline-validation
description: "**WORKFLOW SKILL** — Guide COBOL-to-Java modernization baseline validation. Use when: validating converted Java programs against COBOL baselines; running the 10-step validation process; loading/unloading baseline data; comparing CSV outputs with Beyond Compare; debugging Java mismatches against COBOL source; generating validation reports; resolving runtime errors in STS; creating branches for validation; handling .env files and Application.prop mappings; closing validation tickets. DO NOT USE FOR: baseline creation on mainframe; non-validation Java development; general COBOL questions without a baseline context."
argument-hint: "Provide the Baseline_Name and optionally the SG group (e.g., SG02) and Program-Name"
---

# Baseline Validation — COBOL-to-Java Modernization

## Overview

This skill guides team members through the complete validation workflow for a mainframe modernization project. Validation ensures that converted Java programs produce **identical output** to the original COBOL programs by comparing BEFORE/AFTER data states captured in baselines.

**Goal:** Every output CSV and file from the Java execution must exactly match the corresponding baseline output from the COBOL execution.

---

## Configuration — Path Constants

Paths use placeholders. Set these for your environment before starting:

| Placeholder | Default Value | Description |
|---|---|---|
| `{BASE_DIR}` | `D:\Users\{username}\baseline` | Local baseline root |
| `{SDRIVE}` | `S:\Validation` | Shared S-drive validation root |
| `{FILES_DIR}` | `{BASE_DIR}\files` | Input/output flat files directory |
| `{AFTER_DIR}` | `{FILES_DIR}\AFTER` | AFTER CSV file output directory |

### Derived Paths (per baseline)

```
{BASE_DIR}\SG{XY}\{Baseline_Name}\           # Local baseline root
{BASE_DIR}\SG{XY}\{Baseline_Name}\LOAD\      # Load SQL scripts
{BASE_DIR}\SG{XY}\{Baseline_Name}\REPORT\    # HTML comparison reports
{BASE_DIR}\SG{XY}\{Baseline_Name}\RESULT\    # Final AFTER CSVs + output files
{SDRIVE}\SG{XY}\{Baseline_Folder}\           # S-drive source (read)
{SDRIVE}\SG{XY}\{Baseline_Folder}\REPORT\    # S-drive report destination (write)
{SDRIVE}\SG{XY}\{Baseline_Folder}\RESULT\    # S-drive result destination (write)
```

---

## Background — Five Baseline Jobs

Every baseline captures BEFORE and AFTER states through five sequential jobs:

| Seq | Code | Name | Purpose |
|---|---|---|---|
| A | DBB | Database Backup Before | Export input tables to CSV before execution |
| B | FCB | File Capture Before | Copy input files before execution |
| C | BXR | Baseline Execution Run | Execute the COBOL program |
| D | FCA | File Capture After | Copy output files after execution |
| E | DBA | Database Backup After | Export output tables to CSV after execution |

**File naming:** `P<PkgID>-<Ver>-<BF4/AFT>-<TableOrFileName>.<ext>`
- `BF4` = Before execution (from DBB/FCB)
- `AFT` = After execution (from DBA/FCA)
- Example: `P00117-1-BF4-CUSTOMER_MASTER.csv`, `P00117-1-AFT-ORDER_SUMMARY.csv`

---

## The 10-Step Validation Process

### Step 1: Copy Baseline from S-Drive

```powershell
s <Baseline_Name>
```

**What this does:** Copies the entire baseline folder from `{SDRIVE}\SG{XY}\{Baseline_Name}` to `{BASE_DIR}\SG{XY}\{Baseline_Name}`.

**Verify after running:**
- [ ] Baseline folder exists locally at `{BASE_DIR}\SG{XY}\{Baseline_Name}\`
- [ ] BF4 (BEFORE) CSV files are present
- [ ] AFT (AFTER) CSV files are present (these are the comparison targets)
- [ ] Any input flat files are present

**If the command fails:**
- Check S-drive network connectivity
- Verify the baseline name spelling (case-sensitive)
- Confirm you have read access to the S-drive path
- Check if the SG group folder exists

---

### Step 2: Generate Load/Unload Scripts

```powershell
new-loadUnloadScripts <Baseline_Name>
```

**What this does:** Auto-generates SQL scripts in `{BASE_DIR}\SG{XY}\{Baseline_Name}\LOAD\` that will load BF4 CSV data into the local database and unload AFT data after Java execution.

**Verify after running:**
- [ ] LOAD folder created with SQL scripts
- [ ] Each BF4 CSV has a corresponding load script
- [ ] Unload scripts reference the correct tables

**If scripts look wrong:**
- Check CSV file naming follows the `P<PkgID>-<Ver>-BF4-<Name>.csv` convention
- Ensure CSV headers match expected table schemas

---

### Step 3: Load BEFORE Data into Database

```powershell
l <Baseline_Name>
```

**What this does:** Executes the load scripts to populate the local database with the BEFORE-state data (BF4 CSVs). This sets up the starting state that the Java program will read from.

**Verify after running:**
- [ ] No SQL errors in output
- [ ] Row counts match the CSV file row counts
- [ ] Spot-check a few records in the database

**Common errors:**
| Error | Cause | Fix |
|---|---|---|
| Table not found | Schema mismatch | Verify table names in load scripts match DB schema |
| Data truncation | Column size too small | Check VARCHAR lengths vs actual data |
| Constraint violation | FK/PK issues | Load parent tables before child tables |
| Duplicate key | Data already loaded | Truncate tables and retry |

---

### Step 4: Handle Input Files and Configuration

This step has three sub-tasks:

#### 4a: Copy Input Files
Copy any flat input files from the baseline to `{FILES_DIR}`. These are files the program reads during execution (not database tables).

#### 4b: Create/Update `.env` File
Map environment-specific parameters. The `.env` file tells the Java program where to find input files and where to write output files.

**Typical `.env` entries:**
```properties
INPUT_FILE_PATH={FILES_DIR}
OUTPUT_FILE_PATH={FILES_DIR}\AFTER
# Additional parameters from Application.prop
```

#### 4c: Map Parameters from `Application.prop`
Review the program's `Application.prop` (or `application.properties`) file and ensure all file path parameters, DB connection strings, and runtime flags are correctly set for the local environment.

**Checklist:**
- [ ] Input flat files copied to `{FILES_DIR}`
- [ ] `.env` file created/updated with correct paths
- [ ] `Application.prop` parameters mapped
- [ ] Output directory `{AFTER_DIR}` exists and is empty

---

### Step 5: Create Branch and Run Program in STS

#### 5a: Create a Git Branch

**Branch naming convention:** `SG<XY>/<Program-Name>`

Example: `SG02/P02045-GCRS1910`

```bash
git checkout -b SG02/P02045-GCRS1910
```

#### 5b: Run the Java Program in Spring Tool Suite (STS)

1. Open the project in STS
2. Locate the main class for the program
3. Set the run configuration (ensure `.env` and `Application.prop` are loaded)
4. Run the program

**Expected outcome:** Program completes without exceptions and produces output files.

---

### Step 6: Resolve Runtime Errors

If the program fails or throws exceptions, debug and fix iteratively.

**Debug Decision Tree:**

```
Program threw an exception?
├── YES → Is this a known/common error?
│   ├── YES → Check previous fixes and PRs for established solutions
│   │         Apply the known fix, re-run (go to Step 5b)
│   └── NO  → Is it a data-related error (NPE, bad format, missing record)?
│       ├── YES → Check input data matches what COBOL program expected
│       │         Verify .env / Application.prop mappings
│       │         Fix data handling in Java code
│       └── NO  → Is it a logic error (wrong calculation, missing branch)?
│           ├── YES → Compare Java logic against source COBOL program
│           │         Fix the Java implementation
│           └── NO  → Escalate to team lead with:
│                     - Exception stack trace
│                     - Input data sample
│                     - Steps to reproduce
└── NO → Program completed → Proceed to Step 7
```

**Common runtime errors:**

| Error Type | Symptom | Resolution |
|---|---|---|
| NullPointerException | Unexpected null value | Check COBOL source for default handling; add null checks |
| FileNotFoundException | Input file not found | Verify `.env` path; check file name case sensitivity |
| SQLException | DB query fails | Verify table/column names; check data types |
| NumberFormatException | Bad numeric data | Check COBOL COMP-3/PACKED handling in conversion |
| ArrayIndexOutOfBounds | Array sizing wrong | Compare OCCURS clause in COBOL vs Java array size |
| DateTimeParseException | Date format mismatch | Check COBOL date format (YYYYMMDD vs Java pattern) |

**Key principle:** Keep fixing and re-running until the program executes successfully with no errors.

---

### Step 7: Unload Data and Compare

#### 7a: Unload AFTER Data

```powershell
u <Baseline_Name>
```

**What this does:** Exports the database tables post-Java-execution to CSV files in `{AFTER_DIR}`. These are the Java program's AFTER state.

#### 7b: Compare with Beyond Compare

Open Beyond Compare and compare:
- **Left side (Baseline):** `{BASE_DIR}\SG{XY}\{Baseline_Name}\` — the original COBOL AFT files
- **Right side (Actual):** `{AFTER_DIR}` — the Java-produced AFTER files

**For each file pair, check:**
- [ ] Row counts match exactly
- [ ] All column values match
- [ ] No missing or extra rows
- [ ] No column ordering differences

**Comparison result categories:**

| Result | Meaning | Action |
|---|---|---|
| Files identical | Perfect match | Mark as PASS, proceed to Step 9 |
| Minor differences | Timestamps, system IDs | Document as acceptable if justified |
| Data mismatches | Values differ | Proceed to Step 8 |
| Missing file | Java didn't produce output | Debug — go back to Step 6 |
| Extra file | Java produced unexpected output | Investigate — may indicate logic error |

---

### Step 8: Fix Mismatches

When data mismatches are found:

1. **Identify the mismatched fields** — Note table name, column, row key, baseline value, actual value
2. **Locate the logic in COBOL source** — Find the paragraph/section that computes this value
3. **Compare with Java implementation** — Find the corresponding Java method
4. **Identify the discrepancy** — Common causes:
   - Rounding differences (COBOL COMP-3 vs Java BigDecimal)
   - String padding (COBOL PIC X(n) is space-padded)
   - Sign handling (COBOL signed fields)
   - Date arithmetic differences
   - Conditional logic missing a branch
   - REDEFINES/UNION handling differences
5. **Fix the Java code**
6. **Re-run from Step 3** (reload data → re-execute → re-compare)

**Repeat Steps 3-8 until ALL files match.**

---

### Step 9: Generate HTML Reports

For each file pair that matches (or has only acceptable differences):

1. In Beyond Compare, generate an HTML comparison report
2. Save to `{BASE_DIR}\SG{XY}\{Baseline_Name}\REPORT\`
3. Name format: `<TableOrFileName>_comparison.html`

**Checklist:**
- [ ] One HTML report per compared file
- [ ] Reports show "files are identical" or only acceptable variances
- [ ] All reports saved in REPORT folder

---

### Step 10: Generate Final Word Document

```powershell
New-ReportDraft <BaselineName>
```

**What this does:** Generates a Word document summarizing the validation results, including pass/fail status for each file, any accepted differences with justifications, and execution details.

**Verify the report contains:**
- [ ] Baseline name and program identifier
- [ ] Validation date
- [ ] Summary: total files compared, passed, failed
- [ ] Per-file details with pass/fail status
- [ ] Any accepted differences documented with reasons
- [ ] Validator name

---

## Post-Validation Closure

After all 10 steps complete with all files matching:

### 1. Create RESULT Folder
```
{BASE_DIR}\SG{XY}\{Baseline_Name}\RESULT\
```
Copy into it:
- All AFTER CSV files produced by the Java program
- Any output flat files produced by the Java program

### 2. Copy to S-Drive
Copy these folders to the S-drive:
```
{BASE_DIR}\SG{XY}\{Baseline_Name}\REPORT\  →  {SDRIVE}\SG{XY}\{Baseline_Name}\REPORT\
{BASE_DIR}\SG{XY}\{Baseline_Name}\RESULT\  →  {SDRIVE}\SG{XY}\{Baseline_Name}\RESULT\
```

### 3. Push Code Changes
```bash
git add .
git commit -m "Validation: <Baseline_Name> - all outputs match"
git push origin SG<XY>/<Program-Name>
```

### 4. Raise Pull Request
- Title: `SG<XY>/<Program-Name> - Validation Complete`
- Link to the Azure DevOps validation work item
- Include validation summary in PR description
- Attach or reference the Word report

### 5. Close Validation Ticket
Update the Azure DevOps work item:
- Status: Resolved/Closed
- Attach the generated Word document
- Note any accepted differences

---

## PowerShell Commands Reference

| Command | Syntax | Purpose |
|---|---|---|
| Copy baseline | `s <Baseline_Name>` | Copy baseline from S-drive to local |
| Generate scripts | `new-loadUnloadScripts <Baseline_Name>` | Create load/unload SQL scripts |
| Load data | `l <Baseline_Name>` | Load BF4 CSVs into database |
| Unload data | `u <Baseline_Name>` | Export AFTER tables to CSV |
| Generate report | `New-ReportDraft <BaselineName>` | Create final Word document |

---

## Quality Assurance Checklist

Use this checklist to verify completion before closing a validation:

### Pre-Validation
- [ ] Baseline copied from S-drive successfully
- [ ] Load/unload scripts generated
- [ ] Database loaded with BF4 data (row counts verified)
- [ ] Input files copied to `{FILES_DIR}`
- [ ] `.env` and `Application.prop` configured
- [ ] Git branch created (format: `SG<XY>/<Program-Name>`)

### Execution
- [ ] Java program runs without errors in STS
- [ ] Program produces expected output files
- [ ] AFTER data unloaded from database

### Comparison
- [ ] All AFTER CSVs compared in Beyond Compare
- [ ] All output files compared in Beyond Compare
- [ ] ALL files match (or differences documented as acceptable)
- [ ] HTML reports generated for each comparison

### Closure
- [ ] Word report generated via `New-ReportDraft`
- [ ] RESULT folder created with all AFTER outputs
- [ ] REPORT and RESULT copied to S-drive
- [ ] Code committed and pushed to branch
- [ ] PR raised and linked to work item
- [ ] Validation ticket closed in Azure DevOps

---

## Troubleshooting Guide

### Scenario: Load command fails with SQL errors
1. Check LOAD folder for the failing script
2. Open the script and verify table/column names
3. Verify CSV headers match the schema
4. Check for encoding issues (UTF-8 vs ANSI)
5. Try loading one table at a time to isolate the failure

### Scenario: Program runs but produces empty output
1. Verify input data was loaded correctly (Step 3)
2. Check `.env` file paths are correct
3. Review program logs for skipped processing conditions
4. Compare COBOL JCL PARM values with Java run configuration
5. Check if program has conditional logic that filters all records

### Scenario: Many columns mismatch across all rows
This usually indicates a systematic issue, not individual bugs:
1. **Shifted columns** — Check if column order differs between COBOL and Java output
2. **Different delimiter** — Verify CSV uses the same delimiter
3. **Header row difference** — One file has headers, the other doesn't
4. **Encoding** — EBCDIC vs UTF-8 conversion issue
5. **Trailing spaces** — COBOL PIC X fields are space-padded

### Scenario: Row counts differ
1. Check if the Java program has different filtering logic
2. Verify WHERE clauses in unload scripts match the baseline
3. Look for COBOL PERFORM UNTIL vs Java loop termination differences
4. Check for off-by-one errors in iteration logic

### Scenario: Numeric precision differences
1. Identify the COBOL PIC clause (e.g., `PIC S9(7)V99 COMP-3`)
2. Verify the Java uses `BigDecimal` with matching scale
3. Check rounding mode (`HALF_UP` matches COBOL default)
4. Look for intermediate calculation precision loss

---

## Common Pitfalls

1. **Forgetting to reload data between re-runs** — Always re-execute Step 3 (`l <Baseline_Name>`) before re-running the program, or the database will contain AFTER-state data from the previous run.

2. **Wrong SG group** — Double-check the SG number matches the baseline. Using SG02 paths with an SG04 baseline will load wrong data.

3. **Stale `.env` file** — If switching between baselines, always update the `.env` file for the new baseline mapping.

4. **Not emptying the AFTER directory** — Clear `{AFTER_DIR}` before each run to avoid mixing output from previous executions.

5. **Comparing wrong files** — Always compare the COBOL AFT files (from baseline) with the Java AFTER outputs (from unload). Don't compare BF4 with AFT.

6. **Skipping the Word report** — Even if all files match, the Word document is required for the audit trail.

7. **Not checking previous PRs** — Before debugging a new error, search Azure DevOps for similar program names. The fix may already exist in a merged PR.
