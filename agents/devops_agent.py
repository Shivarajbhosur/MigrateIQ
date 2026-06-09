"""
DevOps Agent - Handles Git/Azure DevOps operations
Step 3a: Create Branch
Step 8: Finalize (Commit, Push, PR)
"""

from typing import Tuple, Dict, Any

from tools.devops_tools import (
    create_and_pull_branch,
    get_branch_name,
    push_branch,
    get_current_branch
)
from models.session import Session, StepStatus
from utils.logger import get_logger
import config

logger = get_logger("devops_agent")


class DevOpsAgent:
    """
    Agent for Git and Azure DevOps operations.
    """
    
    def __init__(self, session: Session):
        """Initialize with a session."""
        self.session = session
        self.baseline_name = session.baseline_name
    
    def run_step_3a_branch(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Step 3a: Create branch in Azure DevOps and pull to local.
        
        create_and_pull_branch() internally handles:
        - Create branch in Azure DevOps
        - Pull to local
        - Find ticket by baseline
        - Link branch to ticket
        - Set ticket to Active
        
        Returns:
            Tuple[bool, Dict]: (success, result)
        """
        logger.info(f"Step 3a: Create branch for {self.baseline_name}")
        
        result = {
            "baseline": self.baseline_name,
            "branch_name": None,
            "ticket_id": None,
            "branch_url": None,
            "ticket_url": None,
            "message": None
        }
        
        # Update session
        self.session.update_step("step_3a_branch", StepStatus.RUNNING)
        
        try:
            # Create and pull branch (does all: create, pull, find ticket, link, activate)
            success, message = create_and_pull_branch(self.baseline_name)
            
            result["message"] = message
            result["branch_name"] = get_branch_name(self.baseline_name)
            
            # Build URLs
            org = config.AZURE_DEVOPS_ORG
            project = config.AZURE_DEVOPS_PROJECT
            repo = config.AZURE_DEVOPS_REPO
            
            branch_name = result["branch_name"]
            result["branch_url"] = f"https://dev.azure.com/{org}/{project}/_git/{repo}?version=GB{branch_name.replace('/', '%2F')}"
            
            # Extract ticket info if available
            if "linked to ticket" in message:
                try:
                    ticket_id = int(message.split("ticket ")[-1].split()[0])
                    result["ticket_id"] = ticket_id
                    result["ticket_url"] = f"https://dev.azure.com/{org}/{project}/_workitems/edit/{ticket_id}"
                except:
                    pass
            
            if success:
                self.session.update_step("step_3a_branch", StepStatus.COMPLETED, data={
                    "branch_name": result["branch_name"],
                    "ticket_id": result["ticket_id"]
                })
                logger.info(f"Step 3a completed successfully for {self.baseline_name}")
            else:
                self.session.update_step("step_3a_branch", StepStatus.FAILED, error=message)
                logger.error(f"Step 3a failed for {self.baseline_name}: {message}")
            
            return success, result
            
        except Exception as e:
            error_msg = str(e)
            self.session.update_step("step_3a_branch", StepStatus.FAILED, error=error_msg)
            logger.error(f"Step 3a exception for {self.baseline_name}: {error_msg}")
            result["message"] = error_msg
            return False, result
    
    def run_step_8_finalize(self, commit_message: str = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Step 8: Commit, push changes.
        
        Args:
            commit_message: Optional commit message
        
        Returns:
            Tuple[bool, Dict]: (success, result)
        """
        import subprocess
        
        logger.info(f"Step 8: Finalize for {self.baseline_name}")
        
        result = {
            "baseline": self.baseline_name,
            "branch_name": None,
            "commit_success": False,
            "push_success": False,
            "message": None
        }
        
        # Update session
        self.session.update_step("step_8_finalize", StepStatus.RUNNING)
        
        try:
            repo_path = config.GIT_REPO_PATH
            
            # Get current branch
            current_branch = get_current_branch(repo_path)
            result["branch_name"] = current_branch
            
            # Default commit message
            if not commit_message:
                commit_message = f"Validation: {self.baseline_name}"
            
            # Git add
            add_result = subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            
            if add_result.returncode != 0:
                error_msg = f"Git add failed: {add_result.stderr}"
                self.session.update_step("step_8_finalize", StepStatus.FAILED, error=error_msg)
                result["message"] = error_msg
                return False, result
            
            # Git commit
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            
            # Check if nothing to commit (not an error)
            if "nothing to commit" in commit_result.stdout.lower() or "nothing to commit" in commit_result.stderr.lower():
                result["commit_success"] = True
                result["message"] = "Nothing to commit"
            elif commit_result.returncode != 0:
                error_msg = f"Git commit failed: {commit_result.stderr}"
                self.session.update_step("step_8_finalize", StepStatus.FAILED, error=error_msg)
                result["message"] = error_msg
                return False, result
            else:
                result["commit_success"] = True
            
            # Git push
            success, push_msg = push_branch(self.baseline_name)
            result["push_success"] = success
            
            if success:
                self.session.update_step("step_8_finalize", StepStatus.COMPLETED, data={
                    "branch_name": current_branch,
                    "commit_message": commit_message
                })
                result["message"] = f"Changes committed and pushed to {current_branch}"
                logger.info(f"Step 8 completed successfully for {self.baseline_name}")
                return True, result
            else:
                self.session.update_step("step_8_finalize", StepStatus.FAILED, error=push_msg)
                result["message"] = push_msg
                return False, result
            
        except Exception as e:
            error_msg = str(e)
            self.session.update_step("step_8_finalize", StepStatus.FAILED, error=error_msg)
            logger.error(f"Step 8 exception for {self.baseline_name}: {error_msg}")
            result["message"] = error_msg
            return False, result