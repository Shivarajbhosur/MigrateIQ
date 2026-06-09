"""
PowerShell tools for running baseline commands.

The cmdlet catalog (names, argument templates, step numbers, purposes) lives
in ``prompts/WORKFLOW_ORCHESTRATION_SKILL.md`` under the
``powershell_commands:`` key. This module is a thin executor: it looks up
the spec by id and shells out via ``pwsh -Command``. Switching projects /
clients = edit the skill file (no Python changes here).
"""

import subprocess
from typing import Tuple

from utils.logger import get_logger

logger = get_logger("powershell_tools")


def _resolve_command(cmd_id: str, baseline_name: str) -> str:
    """Build the PowerShell command string from the skill catalog.

    Imported lazily to avoid a circular import at module load time
    (orchestrator imports from tools.workflow_tools).
    """
    from services.orchestrator import get_orchestrator

    spec = get_orchestrator().get_powershell_command(cmd_id)
    cmdlet = spec["cmdlet"]
    args = spec["args_template"].format(baseline=baseline_name)
    return f"{cmdlet} {args}".strip()


def run_powershell_command(command: str) -> Tuple[bool, str]:
    """
    Run a PowerShell command and return result.
    
    Args:
        command: PowerShell command to run
    
    Returns:
        Tuple[bool, str]: (success, output)
    """
    try:
        logger.info(f"Running PowerShell: {command}")
        
        result = subprocess.run(
            ["pwsh", "-Command", command],
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout
        )
        
        output = result.stdout + result.stderr
        
        if result.returncode == 0:
            logger.info(f"Command successful")
            return True, output
        else:
            logger.error(f"Command failed: {output}")
            return False, output
            
    except subprocess.TimeoutExpired:
        msg = "Command timed out (5 minutes)"
        logger.error(msg)
        return False, msg
        
    except Exception as e:
        msg = f"Command error: {e}"
        logger.error(msg)
        return False, msg


def new_sysout(baseline_name: str) -> Tuple[bool, str]:
    """Step 1b: Create SYSOUT file"""
    return run_powershell_command(_resolve_command("new_sysout", baseline_name))


def new_env(baseline_name: str) -> Tuple[bool, str]:
    """Step 1c: Create .env file"""
    return run_powershell_command(_resolve_command("new_env", baseline_name))


def copy_input(baseline_name: str) -> Tuple[bool, str]:
    """Step 1d: Copy input files to working folder"""
    return run_powershell_command(_resolve_command("copy_input", baseline_name))


def load_baseline_data(baseline_name: str) -> Tuple[bool, str]:
    """Step 2: Load data to DB"""
    return run_powershell_command(_resolve_command("load_baseline_data", baseline_name))


def unload_baseline_data(baseline_name: str) -> Tuple[bool, str]:
    """Step 5: Unload data from DB"""
    return run_powershell_command(_resolve_command("unload_baseline_data", baseline_name))