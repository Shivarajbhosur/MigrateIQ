"""
Dotnet Tools - Run C# programs
Step 3b: Run Code
"""

import subprocess
import os
import re
from typing import Tuple, Dict, Any
from utils.logger import get_logger

logger = get_logger("dotnet_tools")

# Project paths
SSAB_PROJECT_PATH = r"C:\Users\shosur\git\SSAB.OX\SSAB.OX"
SSAB_REPO_PATH = r"C:\Users\shosur\git\SSAB.OX"


def extract_program_name(baseline_name: str) -> str:
    """
    Extract program name from baseline.
    P02003-HPPL043P → HPPL043P
    """
    if "-" in baseline_name:
        return baseline_name.split("-", 1)[1]
    return baseline_name


def find_program_file(program_name: str) -> Tuple[bool, str]:
    """
    Find program .cs file in the SSAB.OX repo.
    """
    logger.info(f"Searching for program: {program_name}.cs")
    
    # Search entire repo
    for root, dirs, files in os.walk(SSAB_REPO_PATH):
        # Skip bin, obj, .git folders
        dirs[:] = [d for d in dirs if d not in ['bin', 'obj', '.git', 'node_modules']]
        for file in files:
            if file.lower() == f"{program_name.lower()}.cs":
                full_path = os.path.join(root, file)
                logger.info(f"Found program: {full_path}")
                return True, full_path
    
    msg = f"Program {program_name}.cs not found in repository"
    logger.warning(msg)
    return False, msg


def parse_error_output(stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
    """
    Parse program output to extract error information.
    """
    error_info = {
        "has_error": exit_code != 0,
        "exit_code": exit_code,
        "error_type": None,
        "error_message": None,
        "stack_trace": None,
        "sql_error": None,
        "sql_error_number": None,
        "warnings": []
    }
    
    combined_output = (stdout or "") + "\n" + (stderr or "")
    
    # Check for SQL errors
    sql_error_match = re.search(r'\[Error\].*SQL Exception: "(.*?)"', combined_output, re.DOTALL)
    if sql_error_match:
        error_info["error_type"] = "sql_error"
        error_info["sql_error"] = sql_error_match.group(1)
    
    sql_error_num_match = re.search(r'SQL Error Number: (\d+)', combined_output)
    if sql_error_num_match:
        error_info["sql_error_number"] = int(sql_error_num_match.group(1))
    
    # Check for build errors
    if "error CS" in combined_output:
        error_info["error_type"] = "build_error"
        build_errors = re.findall(r'error CS\d+: .*', combined_output)
        error_info["error_message"] = "\n".join(build_errors)
    
    # Check for runtime exceptions
    exception_match = re.search(r'(System\.\w+Exception|Microsoft\.\w+Exception): (.*?)(?=\n   at|\Z)', combined_output, re.DOTALL)
    if exception_match:
        error_info["error_type"] = error_info["error_type"] or "runtime_error"
        error_info["error_message"] = f"{exception_match.group(1)}: {exception_match.group(2).strip()}"
    
    # Extract stack trace
    # Extract stack trace - find LAST exception block (actual error, not warnings)
    # Look for exception followed by stack trace containing the program name
    all_exceptions = re.findall(
        r'((?:System\.|Microsoft\.)\w*Exception.*?)\n((?:   at .*\n?)+)',
        combined_output,
        re.DOTALL
    )
    
    if all_exceptions:
        # Use the LAST exception (actual crash, not early warnings)
        last_exception = all_exceptions[-1]
        error_info["error_message"] = last_exception[0].strip()
        stack_lines = last_exception[1].strip().split('\n')[:15]
        error_info["stack_trace"] = "\n".join(stack_lines)
        error_info["error_type"] = "runtime_error"
    else:
        # Fallback to old method
        stack_match = re.search(r'(   at .*)', combined_output, re.DOTALL)
        if stack_match:
            stack_lines = stack_match.group(1).split('\n')[:10]
            error_info["stack_trace"] = "\n".join(stack_lines)
    
    # Extract warnings
    warnings = re.findall(r'warning CS\d+: .*', combined_output)
    error_info["warnings"] = warnings
    
    # If error but couldn't categorize
    if error_info["has_error"] and not error_info["error_type"]:
        error_info["error_type"] = "unknown_error"
        error_lines = [l for l in combined_output.split('\n') if 'error' in l.lower() or 'exception' in l.lower()]
        if error_lines:
            error_info["error_message"] = error_lines[-1]
    
    return error_info


def run_program(baseline_name: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Run C# program using dotnet run.
    """
    program_name = extract_program_name(baseline_name)
    logger.info(f"Running program: {program_name} for baseline: {baseline_name}")
    
    result = {
        "baseline": baseline_name,
        "program": program_name,
        "success": False,
        "exit_code": -1,
        "error_info": {},
        "output": "",
        "program_path": None
    }
    
    try:
        command = f'dotnet run -- {program_name}'
        logger.info(f"Command: {command}")
        logger.info(f"Working directory: {SSAB_PROJECT_PATH}")
        
        process_result = subprocess.run(
            command,
            shell=True,
            cwd=SSAB_PROJECT_PATH,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        result["exit_code"] = process_result.returncode
        result["output"] = process_result.stdout or ""
        result["error_info"] = parse_error_output(
            process_result.stdout,
            process_result.stderr,
            process_result.returncode
        )
        
        if process_result.returncode == 0:
            logger.info(f"Program {program_name} completed successfully")
            result["success"] = True
            return True, result
        else:
            logger.error(f"Program {program_name} failed with exit code: {process_result.returncode}")
            return False, result
            
    except subprocess.TimeoutExpired:
        msg = f"Program {program_name} timed out after 5 minutes"
        logger.error(msg)
        result["error_info"] = {"error_type": "timeout", "error_message": msg}
        return False, result
        
    except Exception as e:
        msg = f"Error running program: {e}"
        logger.error(msg)
        result["error_info"] = {"error_type": "execution_error", "error_message": str(e)}
        return False, result