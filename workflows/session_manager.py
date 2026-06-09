"""
Session Manager for handling multiple baseline sessions.
"""

from typing import Dict, List

import config
from models.session import Session, StepStatus
from utils.logger import get_logger

logger = get_logger("session_manager")


class SessionManager:
    """
    Manages sessions for multiple baselines.
    """
    
    def __init__(self):
        """Initialize session manager."""
        self._sessions: Dict[str, Session] = {}
        logger.info("SessionManager initialized")
    
    def get_session(self, baseline_name: str) -> Session:
        """
        Get or create a session for a baseline.
        """
        if baseline_name not in self._sessions:
            self._sessions[baseline_name] = Session(baseline_name)
        return self._sessions[baseline_name]
    
    def list_sessions(self) -> List[str]:
        """
        List all existing sessions (from disk).
        """
        sessions = []
        
        if config.SESSIONS_PATH.exists():
            for file in config.SESSIONS_PATH.glob("*.json"):
                sessions.append(file.stem)
        
        return sorted(sessions)
    
    def get_session_summary(self, baseline_name: str) -> Dict:
        """
        Get summary of session status.
        """
        session = self.get_session(baseline_name)
        statuses = session.get_all_step_statuses()
        
        completed = sum(1 for s in statuses.values() if s == StepStatus.COMPLETED.value)
        failed = sum(1 for s in statuses.values() if s == StepStatus.FAILED.value)
        pending = sum(1 for s in statuses.values() if s == StepStatus.PENDING.value)
        
        return {
            "baseline_name": baseline_name,
            "group": session.data.get("group", ""),
            "total_steps": len(statuses),
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "is_done": session.is_completed(),
            "next_step": session.get_next_pending_step(),
            "steps": statuses,
        }
    
    def delete_session(self, baseline_name: str) -> bool:
        """
        Delete a session file.
        """
        file_path = config.SESSIONS_PATH / f"{baseline_name}.json"
        
        if file_path.exists():
            file_path.unlink()
            if baseline_name in self._sessions:
                del self._sessions[baseline_name]
            logger.info(f"Session deleted for {baseline_name}")
            return True
        
        return False
    
    def format_status_display(self, baseline_name: str) -> str:
        """
        Format session status for chat display.
        """
        session = self.get_session(baseline_name)
        statuses = session.get_all_step_statuses()
        
        status_icons = {
            "pending": "⏳",
            "running": "🔄",
            "completed": "✅",
            "failed": "❌",
            "skipped": "⏭️",
        }
        
        lines = [f"📊 **Status: {baseline_name}** (Group: {session.data.get('group', '')})\n"]
        
        for step in Session.STEPS:
            status = statuses.get(step, "pending")
            icon = status_icons.get(status, "❓")
            step_name = Session.STEP_NAMES.get(step, step)
            lines.append(f"{icon} {step_name}")
        
        # Summary
        summary = self.get_session_summary(baseline_name)
        lines.append(f"\n**Progress:** {summary['completed']}/{summary['total_steps']} completed")
        
        if summary['next_step']:
            next_name = Session.STEP_NAMES.get(summary['next_step'], summary['next_step'])
            lines.append(f"**Next:** {next_name}")
        
        return "\n".join(lines)


# Global session manager instance
session_manager = SessionManager()


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    return session_manager