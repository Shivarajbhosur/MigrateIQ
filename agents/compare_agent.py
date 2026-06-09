"""
Compare Agent - Handles Step 6: Compare output files.
"""

from typing import Tuple, Dict, Any
from tools.compare_tools import run_compare
from models.session import Session, StepStatus
from utils.logger import get_logger

logger = get_logger(__name__)


class CompareAgent:
    """Agent for handling compare operations (Step 6)."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def run_step_6_compare(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Run Step 6: Compare generated vs expected output.
        
        Returns:
            Tuple[bool, Dict]: (success, result_dict)
        """
        baseline_name = self.session.baseline_name
        logger.info(f"Step 6: Compare for {baseline_name}")
        
        # Mark step as running
        self.session.update_step("step_6_compare", StepStatus.RUNNING)
        
        # Run compare
        success, result = run_compare(baseline_name)
        
        if not success:
            logger.error(f"Compare failed: {result.get('message')}")
            self.session.update_step(
                "step_6_compare", 
                StepStatus.FAILED,
                error=result.get('message')
            )
            return False, result
        
        # Determine status based on result
        if result["all_pass"]:
            status = StepStatus.COMPLETED
        else:
            # Differences found - need review (keep as RUNNING until user decides)
            status = StepStatus.RUNNING
        
        # Update session with compare data
        compare_data = {
            "all_pass": result["all_pass"],
            "after_csv_pass": result["after_csv_pass"],
            "after_csv_fail": result["after_csv_fail"],
            "root_mixed_pass": result["root_mixed_pass"],
            "root_mixed_fail": result["root_mixed_fail"],
            "failed_files": result["failed_files"],
            "report_path": result["report_path"]
        }
        
        self.session.update_step("step_6_compare", status, data=compare_data)
        
        logger.info(f"Compare complete. All pass: {result['all_pass']}")
        return True, result
    
    def mark_acceptable(self) -> Tuple[bool, str]:
        """Mark differences as acceptable."""
        compare_data = self.session.get_step_data("step_6_compare")
        compare_data["user_decision"] = "acceptable"
        
        self.session.update_step(
            "step_6_compare", 
            StepStatus.COMPLETED,
            data=compare_data
        )
        
        logger.info("Differences marked as acceptable")
        return True, "Differences marked as acceptable. Ready for finalize."
    
    def mark_not_acceptable(self) -> Tuple[bool, str]:
        """Mark differences as not acceptable."""
        compare_data = self.session.get_step_data("step_6_compare")
        compare_data["user_decision"] = "not_acceptable"
        
        self.session.update_step(
            "step_6_compare", 
            StepStatus.FAILED,
            data=compare_data
        )
        
        logger.info("Differences marked as not acceptable")
        return True, "Differences marked as not acceptable. Fix code and re-run."