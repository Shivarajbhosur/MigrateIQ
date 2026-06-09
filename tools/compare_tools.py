"""
Compare Tools - Runs CompareX.ps1 for output comparison.
"""
# & "C:\Clients\SSAB.OX\baseline\CompareX.ps1" SG02\P02040-HPPL166P -PromptOnFail:$false

import subprocess
import re
import os
from pathlib import Path
from typing import Tuple, Dict, Any
from utils.logger import get_logger
import config

logger = get_logger(__name__)


def run_compare(baseline_name: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Run CompareX.ps1 to compare generated vs expected output.
    
    Args:
        baseline_name: e.g., "P02070-HPPL486P"
    
    Returns:
        Tuple[bool, Dict]: (success, result_dict)
    """
    # Build path: SG02\P02070-HPPL486P (extract group from baseline)
    group = config.get_baseline_group(baseline_name)
    program_rel_path = f"{group}\\{baseline_name}"
    
    #script_path = config.COMPARE_SCRIPT_PATH
    report_path = str(config.get_report_path(baseline_name))
    
    logger.info(f"Running compare for {baseline_name}")
    #logger.info(f"Script: {script_path}")
    logger.info(f"Path: {program_rel_path}")
    
    try:
        # Run compare-x command from PowerShell library
        command = config.COMPARE_COMMAND.format(baseline_name=baseline_name)
        logger.info(f"Command: {command}")
        
        # Close stdin (DEVNULL) so any interactive Read-Host / "press enter option dont through code"
        # prompt added inside the compare-x PowerShell module returns
        # immediately on EOF instead of blocking the agent indefinitely.
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            #cwd=str(config.WORKSPACE_PATH)
        )
        
        output = result.stdout + result.stderr
        exit_code = result.returncode
        
        logger.info(f"Compare exit code: {exit_code}")
        
        # Parse output
        parsed = parse_compare_output(output)
        
        # Build result
        all_pass = (exit_code == 0 and parsed["after_csv_fail"] == 0 and parsed["root_mixed_fail"] == 0)
        
        result_dict = {
            "exit_code": exit_code,
            "after_csv_pass": parsed["after_csv_pass"],
            "after_csv_fail": parsed["after_csv_fail"],
            "root_mixed_pass": parsed["root_mixed_pass"],
            "root_mixed_fail": parsed["root_mixed_fail"],
            "all_pass": all_pass,
            "failed_files": parsed["failed_files"],
            "report_path": report_path,
            "output": output,
            "message": "All files match!" if all_pass else "Differences found - review needed"
        }
        
        return True, result_dict
        
    except Exception as e:
        msg = f"Error running compare: {e}"
        logger.error(msg)
        return False, {
            "exit_code": -1,
            "message": msg,
            "output": str(e)
        }


def parse_compare_output(output: str) -> Dict[str, Any]:
    """
    Parse CompareX.ps1 console output to extract pass/fail counts.
    """
    result = {
        "after_csv_pass": 0,
        "after_csv_fail": 0,
        "root_mixed_pass": 0,
        "root_mixed_fail": 0,
        "failed_files": []
    }
    
    # Parse AFTER CSV summary
    after_csv_match = re.search(r"Summary \(AFTER CSV\):\s*(\d+)\s*pass,\s*(\d+)\s*fail", output)
    if after_csv_match:
        result["after_csv_pass"] = int(after_csv_match.group(1))
        result["after_csv_fail"] = int(after_csv_match.group(2))
    
    # Parse Root Mixed summary
    root_mixed_match = re.search(r"Summary \(Root Mixed\):\s*(\d+)\s*pass,\s*(\d+)\s*fail", output)
    if root_mixed_match:
        result["root_mixed_pass"] = int(root_mixed_match.group(1))
        result["root_mixed_fail"] = int(root_mixed_match.group(2))
    
    # Parse failed files
    fail_matches = re.findall(r"FAIL \(data differs.*?\):\s*(.+?)(?:\n|$)", output)
    result["failed_files"] = [f.strip() for f in fail_matches]
    
    return result