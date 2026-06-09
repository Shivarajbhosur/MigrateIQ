"""
Script Runner Agent - Handles Step 1, 2, 3b, 5
Step 1: Copy baseline
Step 2: Load to DB
Step 3b: Run Code
Step 5: Unload from DB
"""

from typing import Tuple, Dict, Any

from tools.file_tools import copy_baseline, baseline_exists_at_source
from tools.powershell_tools import new_sysout, new_env, copy_input, load_baseline_data, unload_baseline_data
from tools.dotnet_tools import run_program, extract_program_name
from models.session import Session, StepStatus
from utils.logger import get_logger

logger = get_logger("script_runner_agent")


class ScriptRunnerAgent:
    """
    Agent for running copy, load, run, unload operations.
    """
    
    def __init__(self, session: Session):
        """Initialize with a session."""
        self.session = session
        self.baseline_name = session.baseline_name
    
    async def run_step_1_copy(self) -> Tuple[bool, str]:
        """
        Step 1: Copy baseline from G: to C: and setup files.
        
        1. Copy folder (Python)
        2. New-Sysout (PowerShell)
        3. New-Env (PowerShell)
        4. Copy-Input (PowerShell)
        """
        logger.info(f"Step 1: Copy baseline - {self.baseline_name}")
        
        # Update session status to running
        self.session.update_step("step_1_copy", StepStatus.RUNNING)
        
        # Check if source exists
        if not baseline_exists_at_source(self.baseline_name):
            msg = f"Baseline not found at source: {self.baseline_name}"
            self.session.update_step("step_1_copy", StepStatus.FAILED, error=msg)
            return False, msg
        
        # Step 1a: Copy folder (Python)
        logger.info(f"Step 1a: Copying folder...")
        success, msg = copy_baseline(self.baseline_name)
        if not success:
            self.session.update_step("step_1_copy", StepStatus.FAILED, error=msg)
            return False, f"Copy folder failed: {msg}"
        
        # Step 1b: New-Sysout (PowerShell)
        logger.info(f"Step 1b: Creating SYSOUT...")
        success, output = new_sysout(self.baseline_name)
        if not success:
            self.session.update_step("step_1_copy", StepStatus.FAILED, error=output)
            return False, f"New-Sysout failed: {output}"
        
        # Step 1c: New-Env (PowerShell)
        logger.info(f"Step 1c: Creating .env...")
        success, output = new_env(self.baseline_name)
        if not success:
            self.session.update_step("step_1_copy", StepStatus.FAILED, error=output)
            return False, f"New-Env failed: {output}"
        
        # Step 1d: Copy-Input (PowerShell)
        logger.info(f"Step 1d: Copying input files...")
        success, output = copy_input(self.baseline_name)
        if not success:
            self.session.update_step("step_1_copy", StepStatus.FAILED, error=output)
            return False, f"Copy-Input failed: {output}"
        
        # All done!
        # All done!
        self.session.update_step("step_1_copy", StepStatus.COMPLETED)
        
        # Build detailed message
        details = [f"**Step 1 Completed:** `{self.baseline_name}`"]
        details.append("• ✅ Folder copied")
        details.append("• ✅ SYSOUT created")
        details.append("• ✅ .env file placed")
        details.append("• ✅ Input files copied")
        
        return True, "\n".join(details)
    
    async def run_step_2_load(self) -> Tuple[bool, str]:
        """
        Step 2: Load data to DB
        """
        logger.info(f"Step 2: Load to DB - {self.baseline_name}")
        
        self.session.update_step("step_2_load", StepStatus.RUNNING)
        
        success, output = load_baseline_data(self.baseline_name)
        
        if success:
            self.session.update_step("step_2_load", StepStatus.COMPLETED)
            return True, f"Step 2 completed: {self.baseline_name}\n\n{output}"
        else:
            self.session.update_step("step_2_load", StepStatus.FAILED, error=output)
            return False, f"Step 2 failed: {output}"
    
    def run_step_3b_run(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Step 3b: Run C# program.
        
        Returns:
            Tuple[bool, Dict]: (success, result)
        """
        program_name = extract_program_name(self.baseline_name)
        logger.info(f"Step 3b: Running program {program_name} for {self.baseline_name}")
        
        # Update session
        self.session.update_step("step_3b_run", StepStatus.RUNNING)
        
        try:
            # Run program
            success, result = run_program(self.baseline_name)
            
            # Store result in session for Step 4
            self.session.run_result = result
            
            if success:
                self.session.update_step("step_3b_run", StepStatus.COMPLETED, data={
                    "program": program_name,
                    "exit_code": result.get("exit_code", 0)
                })
                logger.info(f"Step 3b completed successfully for {self.baseline_name}")
            else:
                error_info = result.get("error_info") or {}
                error_msg = error_info.get("error_message", "Unknown error")
                self.session.update_step("step_3b_run", StepStatus.FAILED, error=error_msg)
                logger.error(f"Step 3b failed for {self.baseline_name}: {error_msg}")
            
            return success, result
            
        except Exception as e:
            error_msg = str(e)
            self.session.update_step("step_3b_run", StepStatus.FAILED, error=error_msg)
            logger.error(f"Step 3b exception for {self.baseline_name}: {error_msg}")
            return False, {
                "success": False,
                "error_info": {"error_type": "exception", "error_message": error_msg}
            }
    
    async def run_step_5_unload(self) -> Tuple[bool, str]:
        """
        Step 5: Unload from DB
        """
        logger.info(f"Step 5: Unload from DB - {self.baseline_name}")
        
        self.session.update_step("step_5_unload", StepStatus.RUNNING)
        
        success, output = unload_baseline_data(self.baseline_name)
        
        if success:
            self.session.update_step("step_5_unload", StepStatus.COMPLETED)
            return True, f"Step 5 completed: {self.baseline_name}\n\n{output}"
        else:
            self.session.update_step("step_5_unload", StepStatus.FAILED, error=output)
            return False, f"Step 5 failed: {output}"