"""
Fix Suggestion Models

Data classes for AI analysis and fix suggestion workflow.
Tracks errors, fixes, attempts, and results.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


# ============================================================================
# ENUMS
# ============================================================================

class ErrorType(Enum):
    """Type of error that triggered analysis."""
    RUN_FAILED = "run_failed"           # Program execution failed
    COMPARE_DIFF = "compare_diff"       # Output comparison found differences


class FixStatus(Enum):
    """Status of fix attempt."""
    PENDING = "pending"                 # Not yet applied
    APPLIED = "applied"                 # Fix was applied
    SUCCESS = "success"                 # Fix worked - run successful
    FAILED = "failed"                   # Fix didn't work - still failing


class AnalysisStatus(Enum):
    """Overall analysis status."""
    IN_PROGRESS = "in_progress"         # Analysis ongoing
    FIX_SUGGESTED = "fix_suggested"     # AI suggested a fix
    SUCCESS = "success"                 # Problem resolved
    MAX_ATTEMPTS = "max_attempts"       # Reached 5 attempts, escalate
    CANCELLED = "cancelled"             # User cancelled


# ============================================================================
# ERROR CONTEXT
# ============================================================================

@dataclass
class ErrorContext:
    """
    Information about the error that occurred.
    
    Captures all details needed for AI to understand the problem.
    """
    program_name: str                           # e.g., "HPPL494P"
    baseline_name: str                          # e.g., "P02070-HPPL494P"
    error_type: ErrorType                       # RUN_FAILED or COMPARE_DIFF
    error_message: str                          # Full error message
    file_path: Optional[str] = None             # e.g., "Hppl494p.cs"
    line_number: Optional[int] = None           # Line where error occurred
    stack_trace: Optional[str] = None           # Full stack trace if available
    exit_code: Optional[int] = None             # Program exit code
    diff_details: Optional[str] = None          # For COMPARE_DIFF: what differs
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_prompt_text(self) -> str:
        """Format error context for AI prompt."""
        text = f"""
ERROR TYPE: {self.error_type.value}
PROGRAM: {self.program_name}
BASELINE: {self.baseline_name}
ERROR MESSAGE: {self.error_message}
"""
        if self.file_path:
            text += f"FILE: {self.file_path}\n"
        if self.line_number:
            text += f"LINE: {self.line_number}\n"
        if self.stack_trace:
            text += f"STACK TRACE:\n{self.stack_trace}\n"
        if self.diff_details:
            text += f"DIFF DETAILS:\n{self.diff_details}\n"
        
        return text.strip()


# ============================================================================
# CODE CONTEXT
# ============================================================================

@dataclass
class CodeContext:
    """
    COBOL and C# code for the program.
    
    COBOL = Source of truth
    C# = Code to fix
    """
    program_name: str                           # e.g., "HPPL494P"
    
    # COBOL (Source of Truth)
    cobol_code: Optional[str] = None            # Full COBOL source
    cobol_file_path: Optional[str] = None       # e.g., "HPPL494P.COB"
    
    # C# (Code to Fix)
    csharp_code: Optional[str] = None           # Full C# source
    csharp_file_path: Optional[str] = None      # e.g., "Hppl494p.cs"
    csharp_record_code: Optional[str] = None    # Record/model file if exists
    csharp_record_path: Optional[str] = None    # e.g., "Hppl494p.record.cs"
    
    def has_cobol(self) -> bool:
        """Check if COBOL code is available."""
        return self.cobol_code is not None and len(self.cobol_code) > 0
    
    def has_csharp(self) -> bool:
        """Check if C# code is available."""
        return self.csharp_code is not None and len(self.csharp_code) > 0


# ============================================================================
# SIMILAR FIX (From KB)
# ============================================================================

@dataclass
class SimilarFix:
    """
    A similar fix found in the Knowledge Base.
    
    Past fixes help AI understand how similar problems were solved.
    """
    pr_id: int                                  # PR number
    baseline: str                               # e.g., "P01068-HPPR028P"
    ticket_id: Optional[str] = None             # e.g., "78561"
    files_changed: List[str] = field(default_factory=list)  # Files modified
    commit_message: Optional[str] = None        # What was fixed
    fix_description: Optional[str] = None       # Detailed description
    code_diff: Optional[str] = None             # ✅ NEW: Actual code changes!
    relevance_score: float = 0.0                # How relevant (0-100)
    
    def to_prompt_text(self) -> str:
        """Format similar fix for AI prompt."""
        files = ", ".join(self.files_changed) if self.files_changed else "N/A"
        
        # Include code diff if available (truncate if too long)
        diff_section = ""
        if self.code_diff:
            diff_text = self.code_diff[:2000] if len(self.code_diff) > 2000 else self.code_diff
            diff_section = f"\nCode Changes:\n```\n{diff_text}\n```"
        
        return f"""
PR #{self.pr_id}
Baseline: {self.baseline}
Ticket: {self.ticket_id or 'N/A'}
Files Changed: {files}
Fix: {self.commit_message or self.fix_description or 'N/A'}{diff_section}
Relevance: {self.relevance_score:.1f}%
""".strip()


# ============================================================================
# FIX SUGGESTION (AI Output)
# ============================================================================

@dataclass
class FixSuggestion:
    """
    AI's suggested fix for the problem.
    
    Contains root cause analysis and code changes.
    """
    # Analysis
    root_cause: str                             # Why the error occurred
    explanation: str                            # Detailed explanation
    
    # Code Fix
    file_to_fix: str                            # Which file to modify
    line_number: Optional[int] = None           # Where to make change
    original_code: Optional[str] = None         # Current code (to replace)
    suggested_code: Optional[str] = None        # New code (replacement)
    
    # Metadata
    confidence: int = 0                         # 0-100 confidence level
    fix_type: str = ""                          # e.g., "null_check", "format_fix"
    similar_fixes_used: List[SimilarFix] = field(default_factory=list)
    
    # Additional suggestions
    additional_notes: Optional[str] = None      # Any extra advice
    requires_manual_review: bool = False        # If AI is unsure
    
    def to_display_text(self) -> str:
        """Format fix suggestion for display to user."""
        text = f"""
📋 ROOT CAUSE:
{self.root_cause}

💡 EXPLANATION:
{self.explanation}

📁 FILE TO FIX: {self.file_to_fix}
"""
        if self.line_number:
            text += f"📍 LINE: {self.line_number}\n"
        
        if self.original_code and self.suggested_code:
            text += f"""
🔴 ORIGINAL CODE:
{self.original_code}

🟢 SUGGESTED FIX:
{self.suggested_code}
"""
        
        text += f"\n🎯 CONFIDENCE: {self.confidence}%"
        
        if self.similar_fixes_used:
            text += f"\n📚 BASED ON: PR #{self.similar_fixes_used[0].pr_id}"
        
        if self.additional_notes:
            text += f"\n\n📝 NOTES: {self.additional_notes}"
        
        if self.requires_manual_review:
            text += "\n\n⚠️ MANUAL REVIEW RECOMMENDED"
        
        return text.strip()


# ============================================================================
# FIX ATTEMPT
# ============================================================================

@dataclass
class FixAttempt:
    """
    Record of a single fix attempt.
    
    Tracks what was tried and what happened.
    """
    attempt_number: int                         # 1, 2, 3, 4, or 5
    error_context: ErrorContext                 # Error at this attempt
    fix_suggestion: Optional[FixSuggestion] = None  # AI's suggestion
    status: FixStatus = FixStatus.PENDING       # Current status
    
    # After applying
    applied_at: Optional[datetime] = None       # When fix was applied
    result_error: Optional[str] = None          # New error if failed
    result_message: Optional[str] = None        # Success/failure message
    
    # User action
    user_action: Optional[str] = None           # "applied", "skipped", "modified"
    
    def mark_applied(self):
        """Mark fix as applied."""
        self.status = FixStatus.APPLIED
        self.applied_at = datetime.now()
        self.user_action = "applied"
    
    def mark_success(self, message: str = ""):
        """Mark fix as successful."""
        self.status = FixStatus.SUCCESS
        self.result_message = message
    
    def mark_failed(self, new_error: str):
        """Mark fix as failed with new error."""
        self.status = FixStatus.FAILED
        self.result_error = new_error


# ============================================================================
# ANALYSIS SESSION
# ============================================================================

@dataclass
class AnalysisSession:
    """
    Complete analysis session for a problem.
    
    Tracks all attempts (up to 5) and final outcome.
    """
    # Identifiers
    session_id: str                             # Unique session ID
    baseline_name: str                          # e.g., "P02070-HPPL494P"
    program_name: str                           # e.g., "HPPL494P"
    
    # Context
    initial_error: ErrorContext                 # First error that triggered analysis
    code_context: Optional[CodeContext] = None  # COBOL + C# code
    similar_fixes: List[SimilarFix] = field(default_factory=list)  # From KB
    
    # Attempts (max 5)
    attempts: List[FixAttempt] = field(default_factory=list)
    max_attempts: int = 5                       # Maximum allowed attempts
    
    # Status
    status: AnalysisStatus = AnalysisStatus.IN_PROGRESS
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    # Final outcome
    final_message: Optional[str] = None
    
    @property
    def current_attempt(self) -> int:
        """Get current attempt number."""
        return len(self.attempts)
    
    @property
    def attempts_remaining(self) -> int:
        """Get remaining attempts."""
        return self.max_attempts - len(self.attempts)
    
    @property
    def can_retry(self) -> bool:
        """Check if more attempts are allowed."""
        return len(self.attempts) < self.max_attempts
    
    def add_attempt(self, error_context: ErrorContext, fix_suggestion: FixSuggestion) -> FixAttempt:
        """Add a new fix attempt."""
        attempt = FixAttempt(
            attempt_number=len(self.attempts) + 1,
            error_context=error_context,
            fix_suggestion=fix_suggestion
        )
        self.attempts.append(attempt)
        return attempt
    
    def get_latest_attempt(self) -> Optional[FixAttempt]:
        """Get the most recent attempt."""
        return self.attempts[-1] if self.attempts else None
    
    def get_failed_fixes_summary(self) -> str:
        """Get summary of all failed fixes for AI context."""
        if not self.attempts:
            return "No previous attempts."
        
        summary = "PREVIOUS FAILED ATTEMPTS:\n"
        for attempt in self.attempts:
            if attempt.status == FixStatus.FAILED and attempt.fix_suggestion:
                summary += f"""
Attempt #{attempt.attempt_number}:
- Fix Applied: {attempt.fix_suggestion.root_cause}
- Result: FAILED
- New Error: {attempt.result_error or 'Unknown'}
"""
        return summary.strip()
    
    def mark_success(self, message: str = "Problem resolved!"):
        """Mark session as successful."""
        self.status = AnalysisStatus.SUCCESS
        self.completed_at = datetime.now()
        self.final_message = message
    
    def mark_max_attempts(self):
        """Mark session as reached max attempts."""
        self.status = AnalysisStatus.MAX_ATTEMPTS
        self.completed_at = datetime.now()
        self.final_message = f"Reached maximum {self.max_attempts} attempts. Manual intervention required."
    
    def mark_cancelled(self):
        """Mark session as cancelled by user."""
        self.status = AnalysisStatus.CANCELLED
        self.completed_at = datetime.now()
        self.final_message = "Analysis cancelled by user."
    
    def to_summary(self) -> Dict[str, Any]:
        """Get session summary for logging/display."""
        return {
            "session_id": self.session_id,
            "baseline": self.baseline_name,
            "program": self.program_name,
            "status": self.status.value,
            "total_attempts": len(self.attempts),
            "max_attempts": self.max_attempts,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "final_message": self.final_message
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_analysis_session(
    baseline_name: str,
    program_name: str,
    error_context: ErrorContext
) -> AnalysisSession:
    """
    Create a new analysis session.
    
    Args:
        baseline_name: Baseline identifier
        program_name: Program name
        error_context: Initial error that triggered analysis
    
    Returns:
        New AnalysisSession instance
    """
    import uuid
    
    return AnalysisSession(
        session_id=str(uuid.uuid4())[:8],
        baseline_name=baseline_name,
        program_name=program_name,
        initial_error=error_context
    )


def create_error_context(
    program_name: str,
    baseline_name: str,
    error_type: ErrorType,
    error_message: str,
    **kwargs
) -> ErrorContext:
    """
    Create error context with common defaults.
    
    Args:
        program_name: Program name
        baseline_name: Baseline identifier
        error_type: Type of error
        error_message: Error message
        **kwargs: Additional optional fields
    
    Returns:
        New ErrorContext instance
    """
    return ErrorContext(
        program_name=program_name,
        baseline_name=baseline_name,
        error_type=error_type,
        error_message=error_message,
        **kwargs
    )