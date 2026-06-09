# Reporting Workflow Skill

Defines the 6-step reporting workflow executed by `handle_reporting` in
`app.py`.  Step definitions, progress-card settings, and user-facing
messages live here so they can be edited without touching Python code.

Actual execution stays in `agents/reporting_agent.py` — the skill file
is configuration only.

```yaml
reporting_workflow:
  total_steps: 6

  start_message: |
    🧪 **Reporting Task Started**

    **Baseline:** `{baseline_name}`

    Running 6 steps automatically...

  steps:
    - id: copy
      number: 1
      title: Copy Baseline
      function: run_step_1_copy
      progress_interval: 10
      progress_eta: 120
      progress_status: "Copying input files..."
      progress_complete: "Copy complete"
      progress_fail_default: "Copy failed"
      success: "✅ **Step 1: Copy complete!**\n\n    {message}"
      fail: "❌ **Step 1 Failed: Copy**\n\n{error}\n\n**Action:** Notify validator and try again."

    - id: load
      number: 2
      title: Load to DB
      function: run_step_2_load
      progress_interval: 10
      progress_eta: 90
      progress_status: "Loading baseline data..."
      progress_complete: "Load complete"
      progress_fail_default: "Load failed"
      success: "✅ Step 2: Load complete!"
      fail: "❌ **Step 2 Failed: Load**\n\n{error}\n\n**Action:** Notify validator and try again."

    - id: run
      number: 3
      title: Run Program
      function: run_step_3_run
      progress_interval: 15
      progress_eta: 180
      progress_status: "Executing program..."
      progress_complete: "Run complete"
      progress_fail_default: "Run failed"
      pre_message: "🔄 **Step 3/6: Run Program...**"
      error_path: "error_info.error_message"
      success: "✅ Step 3: Run complete!"
      fail: "❌ **Step 3 Failed: Run**\n\n**Error:** {error}\n\n**Action:** Notify validator about runtime error and try again after fix."

    - id: unload
      number: 4
      title: Unload from DB
      function: run_step_4_unload
      progress_interval: 10
      progress_eta: 90
      progress_status: "Unloading baseline data..."
      progress_complete: "Unload complete"
      progress_fail_default: "Unload failed"
      pre_message: "🔄 **Step 4/6: Unload from DB...**"
      success: "✅ Step 4: Unload complete!"
      fail: "❌ **Step 4 Failed: Unload**\n\n{error}\n\n**Action:** Notify validator and try again."

  compare:
    pre_message: "🔄 **Step 5/6: Compare Output...**\n\n📄 **Note:** A Word document popup may appear. If it does, please set the security label and save it manually."
    progress_interval: 15
    progress_eta: 180
    progress_status: "Comparing output & generating report..."
    progress_complete: "Compare complete"
    progress_fail_default: "Compare failed"
    fail: "❌ **Step 5 Failed: Compare**\n\n{error}\n\n**Action:** Notify validator and try again."
    all_pass: |
      ✅ **Step 5: Compare - All Pass!**

      **Results:**
      ├── AFTER CSV: {csv_pass} pass, {csv_fail} fail ✅
      └── Root Mixed: {root_pass} pass, {root_fail} fail ✅
    differences_found: |
      ⚠️ **Step 5: Differences Found**

      **Results:**
      ├── AFTER CSV: {csv_pass} pass, {csv_fail} fail {csv_icon}
      └── Root Mixed: {root_pass} pass, {root_fail} fail {root_icon}

      **Differences in:**
      {failed_list}

      **Report:** `{report_path}`

      Please review and confirm:
    acceptable_label: "✅ Acceptable"
    not_acceptable_label: "❌ Not Acceptable - Report to Validator"
    acceptable_ack: "✅ Differences marked as acceptable."
    not_acceptable: |
      ❌ **Reporting Stopped - Issue Found**

      **Baseline:** `{baseline_name}`

      **Differences not acceptable - Report to Validator:**
      • Review differences in report
      • Notify validator to fix the code

      **Action Required:**
      1. Review report at: `{report_path}`
      2. Notify validator about the differences
      3. After fix, run `reporting {baseline_name}` again

      {ticket_info}

  close_ticket:
    pre_message: "🔄 **Step 6/6: Closing Ticket...**"
    success: |
      ✅ Ticket {ticket_id} closed!

      ─────────────────────────────────────────

      🎉 **Reporting Task Complete!**

      **Baseline:** `{baseline_name}`
      **Ticket:** [{ticket_id}]({ticket_url}) (Closed)
      **Report:** `{report_path}`

      All 6 steps completed successfully!
    fail: |
      ⚠️ **Step 6: Close Ticket**

      {error}

      **Note:** All other steps completed. Please close ticket manually.

      ─────────────────────────────────────────

      🎉 **Reporting Task Complete!**

      **Baseline:** `{baseline_name}`
      **Report:** `{report_path}`
```
