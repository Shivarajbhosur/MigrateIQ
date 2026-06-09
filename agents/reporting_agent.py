"""
Reporting Agent - Orchestrates all 6 reporting steps.

Steps:
1. Copy baseline
2. Load to DB
3. Run program
4. Unload from DB
5. Compare output
6. Close ticket
"""

import asyncio
from typing import Tuple, Dict, Any
from models.session import Session, StepStatus
from agents.script_runner_agent import ScriptRunnerAgent
from agents.compare_agent import CompareAgent
from tools.devops_tools import find_reporting_ticket_by_baseline, close_ticket
from utils.logger import get_logger

logger = get_logger(__name__)


class ReportingAgent:
    """Agent for orchestrating reporting task (6 steps)."""
    
    def __init__(self, session: Session):
        self.session = session
        self.baseline_name = session.baseline_name
        self.script_agent = ScriptRunnerAgent(session)
        self.compare_agent = CompareAgent(session)
        self.ticket_id = None
    
    def run_step_1_copy(self) -> Tuple[bool, Dict[str, Any]]:
        """Step 1: Copy baseline."""
        logger.info(f"Reporting Step 1: Copy for {self.baseline_name}")
        # Run async method in sync context
        success, message = asyncio.run(self.script_agent.run_step_1_copy())
        return success, {"message": message}
    
    def run_step_2_load(self) -> Tuple[bool, Dict[str, Any]]:
        """Step 2: Load to DB."""
        logger.info(f"Reporting Step 2: Load for {self.baseline_name}")
        # Run async method in sync context
        success, message = asyncio.run(self.script_agent.run_step_2_load())
        return success, {"message": message}
    
    def run_step_3_run(self) -> Tuple[bool, Dict[str, Any]]:
        """Step 3: Run program."""
        logger.info(f"Reporting Step 3: Run for {self.baseline_name}")
        # run_step_3b_run is SYNC (not async)
        success, result = self.script_agent.run_step_3b_run()
        return success, result if isinstance(result, dict) else {"message": result}
    
    def run_step_4_unload(self) -> Tuple[bool, Dict[str, Any]]:
        """Step 4: Unload from DB."""
        logger.info(f"Reporting Step 4: Unload for {self.baseline_name}")
        # Run async method in sync context
        success, message = asyncio.run(self.script_agent.run_step_5_unload())
        return success, {"message": message}
    
    def run_step_5_compare(self) -> Tuple[bool, Dict[str, Any]]:
        """Step 5: Compare output."""
        logger.info(f"Reporting Step 5: Compare for {self.baseline_name}")
        # run_step_6_compare is SYNC (not async)
        success, result = self.compare_agent.run_step_6_compare()
        return success, result
    
    def run_step_6_close_ticket(self) -> Tuple[bool, Dict[str, Any]]:
        """Step 6: Find and close reporting ticket."""
        logger.info(f"Reporting Step 6: Close ticket for {self.baseline_name}")
        
        # Find reporting ticket
        found, ticket_id, msg = find_reporting_ticket_by_baseline(self.baseline_name)
        
        if not found:
            return False, {"message": msg, "ticket_id": None}
        
        self.ticket_id = ticket_id
        
        # Close the ticket
        success, close_msg = close_ticket(ticket_id)
        
        return success, {
            "message": close_msg,
            "ticket_id": ticket_id
        }
    
    def get_ticket_id(self) -> int:
        """Get the ticket ID (after step 6)."""
        return self.ticket_id