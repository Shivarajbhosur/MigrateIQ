"""
Analysis Agent

AI-powered analysis agent for COBOL-to-C# migration issues.
Analyzes runtime errors and output differences, suggests fixes.
"""

import re
import os
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from loguru import logger

from models.fix_suggestion import (
    ErrorType,
    ErrorContext,
    CodeContext,
    SimilarFix,
    FixSuggestion,
    FixAttempt,
    AnalysisSession,
    AnalysisStatus,
    create_analysis_session,
    create_error_context
)

from services.cobol_service import CobolService
from services.codebase_service import CodebaseService
from services.knowledge_base_service import KnowledgeBaseService
from services.llm_service import LLMService


class AnalysisAgent:
    """AI Analysis Agent for COBOL-to-C# migration issues."""
    
    def __init__(self):
        """Initialize the Analysis Agent."""
        self.base_path = Path(__file__).parent.parent
        self.prompts_config = self._load_prompts_config()
        self.skill_content = self._load_skill_file()
        
        self.cobol_service = CobolService()
        self.codebase_service = CodebaseService()
        self.kb_service = KnowledgeBaseService()
        self.llm_service = LLMService()
        
        self._sessions: Dict[str, AnalysisSession] = {}
        logger.info("AnalysisAgent initialized")
    
    def _load_prompts_config(self) -> Dict[str, Any]:
        """Load prompt templates from YAML."""
        yaml_path = self.base_path / "prompts" / "fix_suggestion.yaml"
        if not yaml_path.exists():
            logger.error(f"Prompts config not found: {yaml_path}")
            raise FileNotFoundError(f"Prompts config not found: {yaml_path}")
        with open(yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        logger.debug(f"Loaded prompts config from {yaml_path}")
        return config
    
    def _load_skill_file(self) -> str:
        """Load SKILL.md as system prompt."""
        skill_path = self.base_path / "prompts" / "COBOL_TO_CSHARP_SKILL.md"
        if not skill_path.exists():
            logger.error(f"Skill file not found: {skill_path}")
            raise FileNotFoundError(f"Skill file not found: {skill_path}")
        with open(skill_path, 'r', encoding='utf-8') as f:
            content = f.read()
        logger.debug(f"Loaded skill file from {skill_path}")
        return content
    
    def get_session(self, baseline_name: str) -> Optional[AnalysisSession]:
        """Get active session for a baseline."""
        return self._sessions.get(baseline_name)
    
    def create_session(
        self,
        baseline_name: str,
        program_name: str,
        error_context: ErrorContext
    ) -> AnalysisSession:
        """Create a new analysis session."""
        session = create_analysis_session(
            baseline_name=baseline_name,
            program_name=program_name,
            error_context=error_context
        )
        self._sessions[baseline_name] = session
        logger.info(f"Created analysis session: {session.session_id} for {baseline_name}")
        return session
    
    def clear_session(self, baseline_name: str) -> None:
        """Clear/remove a session."""
        if baseline_name in self._sessions:
            del self._sessions[baseline_name]
            logger.info(f"Cleared session for {baseline_name}")
    
    async def gather_code_context(self, program_name: str) -> CodeContext:
        """Gather COBOL and C# code for a program."""
        logger.info(f"Gathering code context for {program_name}")
        context = CodeContext(program_name=program_name)
        
        try:
            cobol_results = self.cobol_service.search_hybrid(
                query=program_name,
                n_results=1
            )
            if cobol_results:
                best_match = cobol_results[0]
                metadata = best_match.get('metadata', {})
                context.cobol_file_path = metadata.get('full_path', '') or metadata.get('relative_path', f"{program_name}.COB")
                context.cobol_code = best_match.get('content', '')
                logger.debug(f"Found COBOL code: {context.cobol_file_path}")
        except Exception as e:
            logger.warning(f"Failed to fetch COBOL code: {e}")
        
        try:
            csharp_results = self.codebase_service.search_hybrid(
                query=program_name,
                n_results=3
            )
            for result in csharp_results:
                metadata = result.get('metadata', {})
                file_path = metadata.get('full_path', '') or metadata.get('relative_path', '')
                
                # Read LIVE file content (not KB copy) to get current code
                content = ''
                if file_path and os.path.exists(file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        logger.debug(f"Read live file: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to read live file {file_path}: {e}")
                        content = result.get('content', '')  # Fallback to KB
                else:
                    content = result.get('content', '')  # Fallback to KB
                
                if file_path.lower().endswith('.cs') and 'record' not in file_path.lower():
                    if not context.csharp_code:
                        context.csharp_file_path = file_path
                        context.csharp_code = content
                        logger.debug(f"Found C# code: {context.csharp_file_path}")
                elif 'record' in file_path.lower():
                    context.csharp_record_path = file_path
                    context.csharp_record_code = content
                    logger.debug(f"Found C# record: {context.csharp_record_path}")
        except Exception as e:
            logger.warning(f"Failed to fetch C# code: {e}")
        
        return context
    
    async def search_similar_fixes(
        self,
        program_name: str,
        error_message: str,
        n_results: int = 5
    ) -> List[SimilarFix]:
        """Search KB for similar past fixes."""
        logger.info(f"Searching KB for similar fixes: {program_name}")
        similar_fixes = []
        
        try:
            query = f"{program_name} {error_message[:200]}"
            results = self.kb_service.search_hybrid(
                query=query,
                n_results=n_results
            )
            for result in results:
                metadata = result.get('metadata', {})
                files_str = metadata.get('files_changed', '')
                files_list = files_str.split(',') if files_str else []

                fix = SimilarFix(
                    pr_id=metadata.get('pr_id', 0),
                    baseline=metadata.get('baseline', ''),
                    ticket_id=metadata.get('ticket_id'),
                    files_changed=files_list,
                    commit_message=metadata.get('title', ''),
                    fix_description=metadata.get('title', ''),
                    code_diff=result.get('document', ''),  #NEW: Include code diff!
                    relevance_score=result.get('score', 0)
                )
                similar_fixes.append(fix)
            logger.debug(f"Found {len(similar_fixes)} similar fixes")
        except Exception as e:
            logger.warning(f"Failed to search KB: {e}")
        
        return similar_fixes
    
    def _build_prompt(
        self,
        prompt_type: str,
        error_context: ErrorContext,
        code_context: CodeContext,
        similar_fixes: List[SimilarFix],
        session: Optional[AnalysisSession] = None
    ) -> str:
        """Build the user prompt from template."""
        prompt_config = self.prompts_config.get(prompt_type, {})
        template = prompt_config.get('template', '')
        
        if not template:
            logger.error(f"No template found for prompt type: {prompt_type}")
            return ""
        
        stack_trace_section = ""
        if error_context.stack_trace:
            stack_trace_section = f"**Stack Trace:**\n```\n{error_context.stack_trace}\n```"
        
        csharp_record_section = ""
        if code_context.csharp_record_code:
            csharp_record_section = f"## C# Record/Model File\n**File:** {code_context.csharp_record_path}\n```csharp\n{code_context.csharp_record_code}\n```"
        
        similar_fixes_section = ""
        if similar_fixes:
            fixes_list = "\n\n".join([fix.to_prompt_text() for fix in similar_fixes[:3]])
            similar_fixes_section = f"## Similar Past Fixes (From Knowledge Base)\n\n{fixes_list}"
        
        previous_attempts_section = ""
        if session and session.current_attempt > 0:
            previous_attempts_section = f"## Previous Fix Attempts (Did Not Work)\n{session.get_failed_fixes_summary()}"
        
        try:
            prompt = template.format(
                program_name=error_context.program_name,
                baseline_name=error_context.baseline_name,
                exit_code=error_context.exit_code or "N/A",
                error_message=error_context.error_message,
                stack_trace_section=stack_trace_section,
                cobol_file_path=code_context.cobol_file_path or "N/A",
                cobol_code=code_context.cobol_code or "COBOL source not available",
                csharp_file_path=code_context.csharp_file_path or "N/A",
                csharp_code=code_context.csharp_code or "C# source not available",
                csharp_record_section=csharp_record_section,
                similar_fixes_section=similar_fixes_section,
                previous_attempts_section=previous_attempts_section,
                diff_details=error_context.diff_details or "N/A",
                failed_files=error_context.diff_details or "N/A",
                attempt_number=session.current_attempt + 1 if session else 1,
                max_attempts=session.max_attempts if session else 5,
                previous_attempts_details=session.get_failed_fixes_summary() if session else ""
            )
        except KeyError as e:
            logger.warning(f"Missing template variable: {e}")
            prompt = template
        
        return prompt
    
    def _parse_ai_response(self, response: str) -> FixSuggestion:
        """Parse AI response into FixSuggestion object."""
        logger.debug("Parsing AI response")
        
        root_cause = "Unable to determine root cause"
        explanation = ""
        file_to_fix = ""
        line_number = None
        original_code = ""
        suggested_code = ""
        confidence = 50
        fix_type = "other"
        additional_notes = ""
        
        match = re.search(r'### Root Cause\n(.+?)(?=\n\n|\n###)', response, re.DOTALL)
        if match:
            root_cause = match.group(1).strip()
        
        match = re.search(r'### Analysis\n(.+?)(?=\n### File)', response, re.DOTALL)
        if match:
            explanation = match.group(1).strip()
        
        match = re.search(r'### File to Fix\n(.+?)(?=\n)', response)
        if match:
            file_to_fix = match.group(1).strip()
        
        match = re.search(r'### Line Number\n(\d+|N/A)', response)
        if match:
            line_str = match.group(1).strip()
            if line_str != "N/A":
                try:
                    line_number = int(line_str)
                except ValueError:
                    pass
        
        match = re.search(r'### Original Code\n```(?:csharp)?\n(.+?)```', response, re.DOTALL)
        if match:
            original_code = match.group(1).strip()
        
        match = re.search(r'### Suggested Fix\n```(?:csharp)?\n(.+?)```', response, re.DOTALL)
        if match:
            suggested_code = match.group(1).strip()
        
        match = re.search(r'### Confidence\n(\d+)%?', response)
        if match:
            try:
                confidence = int(match.group(1))
            except ValueError:
                confidence = 50
        
        match = re.search(r'### Fix Type\n(.+?)(?=\n)', response)
        if match:
            fix_type = match.group(1).strip()
        
        match = re.search(r'### Notes\n(.+?)(?=\n###|$)', response, re.DOTALL)
        if match:
            additional_notes = match.group(1).strip()
        
        suggestion = FixSuggestion(
            root_cause=root_cause,
            explanation=explanation,
            file_to_fix=file_to_fix,
            line_number=line_number,
            original_code=original_code,
            suggested_code=suggested_code,
            confidence=confidence,
            fix_type=fix_type,
            additional_notes=additional_notes,
            requires_manual_review=(confidence < 70)
        )
        
        logger.debug(f"Parsed suggestion: confidence={confidence}%, file={file_to_fix}")
        return suggestion
    
    async def analyze_runtime_error(
        self,
        baseline_name: str,
        program_name: str,
        error_message: str,
        exit_code: int = 1,
        stack_trace: Optional[str] = None
    ) -> FixSuggestion:
        """Analyze a runtime error and suggest a fix."""
        logger.info(f"Analyzing runtime error for {program_name}")
        
        error_context = create_error_context(
            program_name=program_name,
            baseline_name=baseline_name,
            error_type=ErrorType.RUN_FAILED,
            error_message=error_message,
            exit_code=exit_code,
            stack_trace=stack_trace
        )
        
        session = self.get_session(baseline_name)
        if not session:
            session = self.create_session(baseline_name, program_name, error_context)
        
        if not session.can_retry:
            session.mark_max_attempts()
            logger.warning(f"Max attempts reached for {baseline_name}")
            return FixSuggestion(
                root_cause="Maximum analysis attempts reached",
                explanation=f"After {session.max_attempts} attempts, the issue could not be automatically resolved.",
                file_to_fix="",
                confidence=0,
                requires_manual_review=True,
                additional_notes="Please review manually or create a bug ticket."
            )
        
        code_context = await self.gather_code_context(program_name)
        session.code_context = code_context
        
        similar_fixes = await self.search_similar_fixes(program_name, error_message)
        session.similar_fixes = similar_fixes
        
        prompt_type = "retry_analysis" if session.current_attempt > 0 else "analyze_runtime_error"
        
        user_prompt = self._build_prompt(
            prompt_type=prompt_type,
            error_context=error_context,
            code_context=code_context,
            similar_fixes=similar_fixes,
            session=session
        )
        
        logger.debug("Calling LLM for analysis")
        response = await self.llm_service.chat(
            system_prompt=self.skill_content,
            user_prompt=user_prompt,
            max_tokens=self.prompts_config.get('max_tokens', 4096),
            temperature=self.prompts_config.get('temperature', 0.2)
        )
        
        suggestion = self._parse_ai_response(response)
        suggestion.similar_fixes_used = similar_fixes[:3] if similar_fixes else []
        
        session.add_attempt(error_context, suggestion)
        session.status = AnalysisStatus.FIX_SUGGESTED
        
        logger.info(f"Analysis complete: confidence={suggestion.confidence}%, attempt={session.current_attempt}/{session.max_attempts}")
        return suggestion
    
    async def analyze_output_diff(
        self,
        baseline_name: str,
        program_name: str,
        diff_details: str,
        failed_files: Optional[List[str]] = None
    ) -> FixSuggestion:
        """Analyze output differences and suggest a fix."""
        logger.info(f"Analyzing output diff for {program_name}")
        
        error_context = create_error_context(
            program_name=program_name,
            baseline_name=baseline_name,
            error_type=ErrorType.COMPARE_DIFF,
            error_message="Output comparison failed - differences found",
            diff_details=diff_details
        )
        
        session = self.get_session(baseline_name)
        if not session:
            session = self.create_session(baseline_name, program_name, error_context)
        
        if not session.can_retry:
            session.mark_max_attempts()
            logger.warning(f"Max attempts reached for {baseline_name}")
            return FixSuggestion(
                root_cause="Maximum analysis attempts reached",
                explanation=f"After {session.max_attempts} attempts, the issue could not be automatically resolved.",
                file_to_fix="",
                confidence=0,
                requires_manual_review=True,
                additional_notes="Please review manually or create a bug ticket."
            )
        
        code_context = await self.gather_code_context(program_name)
        session.code_context = code_context
        
        similar_fixes = await self.search_similar_fixes(program_name, diff_details[:200])
        session.similar_fixes = similar_fixes
        
        prompt_type = "retry_analysis" if session.current_attempt > 0 else "analyze_output_diff"
        
        user_prompt = self._build_prompt(
            prompt_type=prompt_type,
            error_context=error_context,
            code_context=code_context,
            similar_fixes=similar_fixes,
            session=session
        )
        
        logger.debug("Calling LLM for analysis")
        response = await self.llm_service.chat(
            system_prompt=self.skill_content,
            user_prompt=user_prompt,
            max_tokens=self.prompts_config.get('max_tokens', 4096),
            temperature=self.prompts_config.get('temperature', 0.2)
        )
        
        suggestion = self._parse_ai_response(response)
        suggestion.similar_fixes_used = similar_fixes[:3] if similar_fixes else []
        
        session.add_attempt(error_context, suggestion)
        session.status = AnalysisStatus.FIX_SUGGESTED
        
        logger.info(f"Analysis complete: confidence={suggestion.confidence}%, attempt={session.current_attempt}/{session.max_attempts}")
        return suggestion
    
    async def retry_analysis(
        self,
        baseline_name: str,
        new_error_message: str,
        stack_trace: Optional[str] = None
    ) -> FixSuggestion:
        """Retry analysis after a failed fix attempt."""
        session = self.get_session(baseline_name)
        
        if not session:
            logger.error(f"No session found for {baseline_name}")
            raise ValueError(f"No active session for {baseline_name}. Start with analyze_runtime_error() first.")
        
        latest_attempt = session.get_latest_attempt()
        if latest_attempt:
            latest_attempt.mark_failed(new_error_message)
        
        return await self.analyze_runtime_error(
            baseline_name=session.baseline_name,
            program_name=session.program_name,
            error_message=new_error_message,
            stack_trace=stack_trace
        )
    
    def mark_fix_success(self, baseline_name: str) -> None:
        """Mark the current fix as successful."""
        session = self.get_session(baseline_name)
        if session:
            latest_attempt = session.get_latest_attempt()
            if latest_attempt:
                latest_attempt.mark_success()
            session.mark_success()
            logger.info(f"Fix successful for {baseline_name}")
    
    def get_session_summary(self, baseline_name: str) -> Optional[Dict[str, Any]]:
        """Get summary of analysis session."""
        session = self.get_session(baseline_name)
        if session:
            return session.to_summary()
        return None


_analysis_agent: Optional[AnalysisAgent] = None


def get_analysis_agent() -> AnalysisAgent:
    """Get singleton instance of AnalysisAgent."""
    global _analysis_agent
    if _analysis_agent is None:
        _analysis_agent = AnalysisAgent()
    return _analysis_agent