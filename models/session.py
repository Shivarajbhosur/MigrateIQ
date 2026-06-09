"""
Session model for tracking validation workflow state.
Each baseline has its own session file.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from enum import Enum

import config
from utils.logger import get_logger

logger = get_logger("session")


class StepStatus(str, Enum):
    """Status of a workflow step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Session:
    """
    Manages session state for a baseline validation.
    Session data is saved to JSON file.
    """
    
    # Step definitions
    STEPS = [
        "step_1_copy",
        "step_2_load",
        "step_3a_branch",       # ← Changed
        "step_3b_run",          # ← Added
        "step_4_analyze_fix",
        "step_5_unload",
        "step_6_compare",
        "step_7_report",
        "step_8_finalize",
    ]

    STEP_NAMES = {
        "step_1_copy": "Copy Baseline",
        "step_2_load": "Load to DB",
        "step_3a_branch": "Create Branch",      # ← Changed
        "step_3b_run": "Run Code",              # ← Added
        "step_4_analyze_fix": "Error Analysis & Fix",
        "step_5_unload": "Unload from DB",
        "step_6_compare": "Compare Output",
        "step_7_report": "Generate Report",
        "step_8_finalize": "Finalize & Deliver",
    }
    
    def __init__(self, baseline_name: str):
        """Initialize session for a baseline."""
        self.baseline_name = baseline_name
        self.file_path = config.SESSIONS_PATH / f"{baseline_name}.json"
        self.data = self._load_or_create()
        self.run_result = None  # Step 3b result for Step 4 analysis
    
    def _load_or_create(self) -> Dict[str, Any]:
        """Load existing session or create new one."""
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    logger.info(f"Loaded session for {self.baseline_name}")
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Corrupted session file, creating new")
        
        logger.info(f"Creating new session for {self.baseline_name}")
        return self._create_new_session()
    
    def _create_new_session(self) -> Dict[str, Any]:
        """Create new session structure."""
        session = {
            "baseline_name": self.baseline_name,
            "group": config.get_baseline_group(self.baseline_name),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "steps": {}
        }
        
        for step in self.STEPS:
            session["steps"][step] = {
                "status": StepStatus.PENDING.value,
                "started_at": None,
                "completed_at": None,
                "data": {},
                "error": None,
            }
        
        return session
    
    def save(self) -> None:
        """Save session to disk."""
        self.data["updated_at"] = datetime.now().isoformat()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2)
        
        logger.debug(f"Session saved for {self.baseline_name}")
    
    def update_step(
        self,
        step_name: str,
        status: StepStatus,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> None:
        """Update status of a step."""
        if step_name not in self.data["steps"]:
            logger.error(f"Unknown step: {step_name}")
            return
        
        step = self.data["steps"][step_name]
        step["status"] = status.value
        
        if status == StepStatus.RUNNING:
            step["started_at"] = datetime.now().isoformat()
        elif status in [StepStatus.COMPLETED, StepStatus.FAILED]:
            step["completed_at"] = datetime.now().isoformat()
        
        if data:
            step["data"].update(data)
        
        if error:
            step["error"] = error
        
        self.save()
        logger.info(f"Step {step_name} → {status.value}")
    
    def get_step_status(self, step_name: str) -> StepStatus:
        """Get status of a step."""
        if step_name not in self.data["steps"]:
            return StepStatus.PENDING
        return StepStatus(self.data["steps"][step_name]["status"])
    
    def get_step_data(self, step_name: str) -> Dict[str, Any]:
        """Get data stored for a step."""
        if step_name not in self.data["steps"]:
            return {}
        return self.data["steps"][step_name].get("data", {})
    
    def get_all_step_statuses(self) -> Dict[str, str]:
        """Get status of all steps."""
        return {
            step: self.data["steps"][step]["status"]
            for step in self.STEPS
        }
    
    def get_next_pending_step(self) -> Optional[str]:
        """Get next step to run."""
        for step in self.STEPS:
            status = self.get_step_status(step)
            if status in [StepStatus.PENDING, StepStatus.FAILED]:
                return step
        return None
    
    def is_completed(self) -> bool:
        """Check if all steps completed."""
        for step in self.STEPS:
            status = self.get_step_status(step)
            if status not in [StepStatus.COMPLETED, StepStatus.SKIPPED]:
                return False
        return True
    
    def reset_step(self, step_name: str) -> None:
        """Reset a step to pending."""
        if step_name in self.data["steps"]:
            self.data["steps"][step_name] = {
                "status": StepStatus.PENDING.value,
                "started_at": None,
                "completed_at": None,
                "data": {},
                "error": None,
            }
            self.save()
            logger.info(f"Step {step_name} reset")
    
    def reset_all(self) -> None:
        """Reset all steps."""
        self.data = self._create_new_session()
        self.save()
        logger.info(f"All steps reset for {self.baseline_name}")