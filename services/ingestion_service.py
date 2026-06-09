"""
Ingestion Service - Fetches PRs from Azure DevOps and stores in KB.
"""

import requests
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import config
from services.knowledge_base_service import get_kb_service
from utils.logger import get_logger

logger = get_logger("ingestion_service")


class IngestionService:
    """Service for ingesting PRs from Azure DevOps into KB."""
    
    # Azure DevOps API max per page
    PAGE_SIZE = 100
    
    def __init__(self):
        """Initialize with Azure DevOps config."""
        self.org = config.AZURE_DEVOPS_ORG
        self.project = config.AZURE_DEVOPS_PROJECT
        self.repo = config.AZURE_DEVOPS_REPO
        self.pat = config.AZURE_DEVOPS_PAT
        
        self.base_url = f"https://dev.azure.com/{self.org}/{self.project}/_apis"
        self.headers = {
            "Authorization": f"Basic {self._encode_pat()}",
            "Content-Type": "application/json"
        }
    
    def _encode_pat(self) -> str:
        """Encode PAT for Basic auth."""
        import base64
        token = f":{self.pat}"
        return base64.b64encode(token.encode()).decode()
    
    def fetch_completed_prs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetch completed PRs from Azure DevOps with pagination.
        
        Args:
            limit: Maximum number of PRs to fetch (None = ALL)
        
        Returns:
            List of PR data
        """
        all_prs = []
        skip = 0
        
        try:
            while True:
                url = f"{self.base_url}/git/repositories/{self.repo}/pullrequests"
                params = {
                    "searchCriteria.status": "completed",
                    "$top": self.PAGE_SIZE,
                    "$skip": skip,
                    "api-version": "7.0"
                }
                
                response = requests.get(url, headers=self.headers, params=params)
                
                if response.status_code != 200:
                    logger.error(f"Failed to fetch PRs: {response.status_code} - {response.text}")
                    break
                
                data = response.json()
                prs = data.get("value", [])
                
                if not prs:
                    # No more PRs
                    break
                
                all_prs.extend(prs)
                logger.info(f"Fetched {len(all_prs)} PRs so far...")
                
                # Check if we've reached the limit
                if limit and len(all_prs) >= limit:
                    all_prs = all_prs[:limit]
                    break
                
                # Check if we got less than page size (last page)
                if len(prs) < self.PAGE_SIZE:
                    break
                
                # Next page
                skip += self.PAGE_SIZE
            
            logger.info(f"Total fetched: {len(all_prs)} completed PRs")
            return all_prs
                
        except Exception as e:
            logger.error(f"Error fetching PRs: {e}")
            return all_prs
    
    def fetch_pr_details(self, pr_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch detailed PR info including files changed.
        
        Args:
            pr_id: Pull Request ID
        
        Returns:
            PR details with files changed
        """
        try:
            # Get PR details
            url = f"{self.base_url}/git/repositories/{self.repo}/pullrequests/{pr_id}"
            params = {"api-version": "7.0"}
            
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch PR {pr_id}: {response.status_code}")
                return None
            
            pr_data = response.json()
            
            # Get iterations (commits/changes)
            iterations_url = f"{url}/iterations"
            iterations_response = requests.get(iterations_url, headers=self.headers, params=params)
            
            files_changed = []
            code_diff = ""
            
            if iterations_response.status_code == 200:
                iterations = iterations_response.json().get("value", [])
                if iterations:
                    # Get changes from last iteration
                    last_iteration = iterations[-1]
                    iteration_id = last_iteration.get("id")
                    
                    changes_url = f"{url}/iterations/{iteration_id}/changes"
                    changes_response = requests.get(changes_url, headers=self.headers, params=params)
                    
                    if changes_response.status_code == 200:
                        changes = changes_response.json().get("changeEntries", [])
                        for change in changes:
                            item = change.get("item", {})
                            path = item.get("path", "")
                            # Only add .cs files
                            if path and path.endswith('.cs'):
                                files_changed.append(path)
            
            # Fetch code diff (commit changes)
            code_diff = self.fetch_pr_diff(pr_id)
            
            return {
                "pr_id": pr_id,
                "title": pr_data.get("title", ""),
                "description": pr_data.get("description", ""),
                "source_branch": pr_data.get("sourceRefName", ""),
                "target_branch": pr_data.get("targetRefName", ""),
                "created_by": pr_data.get("createdBy", {}).get("displayName", ""),
                "created_date": pr_data.get("creationDate", ""),
                "closed_date": pr_data.get("closedDate", ""),
                "files_changed": files_changed,
                "code_diff": code_diff
            }
            
        except Exception as e:
            logger.error(f"Error fetching PR {pr_id} details: {e}")
            return None
    
    def fetch_pr_diff(self, pr_id: int) -> str:
        """
        Fetch the code diff for a PR (committed changes).
        
        Args:
            pr_id: Pull Request ID
        
        Returns:
            Code diff as string
        """
        try:
            # Get commits for PR
            url = f"{self.base_url}/git/repositories/{self.repo}/pullrequests/{pr_id}/commits"
            params = {"api-version": "7.0"}
            
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code != 200:
                return ""
            
            commits = response.json().get("value", [])
            
            if not commits:
                return ""
            
            # Get diff for each commit (limit to avoid too large)
            diffs = []
            for commit in commits[:5]:  # Max 5 commits
                commit_id = commit.get("commitId", "")
                
                if commit_id:
                    diff = self.fetch_commit_diff(commit_id)
                    if diff:
                        diffs.append(diff)
            
            return "\n---\n".join(diffs)
            
        except Exception as e:
            logger.error(f"Error fetching PR {pr_id} diff: {e}")
            return ""
    
    def fetch_commit_diff(self, commit_id: str) -> str:
        """
        Fetch diff for a specific commit - including actual code changes.
        
        Args:
            commit_id: Commit SHA
        
        Returns:
            Diff as string with actual code changes
        """
        try:
            # Get commit details including parent
            commit_url = f"{self.base_url}/git/repositories/{self.repo}/commits/{commit_id}"
            params = {"api-version": "7.0"}
            
            commit_response = requests.get(commit_url, headers=self.headers, params=params)
            if commit_response.status_code != 200:
                return ""
            
            commit_data = commit_response.json()
            parent_ids = commit_data.get("parents", [])
            parent_commit_id = parent_ids[0] if parent_ids else None
            
            # Get changes for this commit
            changes_url = f"{self.base_url}/git/repositories/{self.repo}/commits/{commit_id}/changes"
            changes_response = requests.get(changes_url, headers=self.headers, params=params)
            
            if changes_response.status_code != 200:
                return ""
            
            changes = changes_response.json().get("changes", [])
            
            diff_parts = []
            for change in changes:
                item = change.get("item", {})
                path = item.get("path", "")
                change_type = change.get("changeType", "")
                is_folder = item.get("isFolder", False)
                
                # Only include .cs files, not folders
                if is_folder or not path or not path.endswith(".cs"):
                    continue
                
                diff_parts.append(f"[{change_type}] {path}")
                
                # Fetch actual file content diff for edits
                if change_type == "edit" and parent_commit_id:
                    try:
                        # Get new content (at this commit)
                        new_content = self._fetch_file_at_commit(path, commit_id)
                        # Get old content (at parent commit)
                        old_content = self._fetch_file_at_commit(path, parent_commit_id)
                        
                        if new_content and old_content:
                            # Generate diff
                            diff_text = self._generate_simple_diff(old_content, new_content, path)
                            if diff_text:
                                diff_parts.append(diff_text)
                    except Exception as e:
                        logger.debug(f"Could not fetch content diff for {path}: {e}")
                
                # For adds, get the new content
                elif change_type == "add":
                    try:
                        new_content = self._fetch_file_at_commit(path, commit_id)
                        if new_content:
                            # Show first 50 lines of new file
                            lines = new_content.split('\n')[:50]
                            diff_parts.append("+ " + "\n+ ".join(lines))
                    except Exception as e:
                        logger.debug(f"Could not fetch new file content for {path}: {e}")
            
            return "\n".join(diff_parts)
            
        except Exception as e:
            logger.error(f"Error fetching commit {commit_id} diff: {e}")
            return ""
   
   
    def _fetch_file_at_commit(self, file_path: str, commit_id: str) -> str:
        """Fetch file content at a specific commit."""
        try:
            url = f"{self.base_url}/git/repositories/{self.repo}/items"
            params = {
                "path": file_path,
                "versionType": "Commit",
                "version": commit_id,
                "api-version": "7.0"
            }
            
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code == 200:
                return response.text
            return ""
        except Exception as e:
            logger.debug(f"Error fetching file {file_path} at {commit_id}: {e}")
            return ""


    def _generate_simple_diff(self, old_content: str, new_content: str, file_path: str) -> str:
        """Generate a simple diff showing changed lines."""
        try:
            import difflib
            
            old_lines = old_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            
            diff = list(difflib.unified_diff(
                old_lines, 
                new_lines, 
                fromfile=f"a{file_path}",
                tofile=f"b{file_path}",
                lineterm=''
            ))
            
            # Limit diff size
            if len(diff) > 100:
                diff = diff[:100] + ["\n... (truncated)"]
            
            return "".join(diff)
        except Exception as e:
            logger.debug(f"Error generating diff: {e}")
            return ""
    
    def extract_baseline_and_ticket(self, title: str) -> Tuple[str, int]:
        """
        Extract baseline name and ticket ID from PR title.
        
        Expected format: "P02020-HPPL070P | 03-Validation #81794"
        
        Returns:
            Tuple of (baseline_name, ticket_id)
        """
        baseline = ""
        ticket_id = 0
        
        try:
            # Extract baseline (before |)
            if "|" in title:
                baseline = title.split("|")[0].strip()
            else:
                baseline = title.strip()
            
            # Extract ticket ID (after #)
            if "#" in title:
                ticket_part = title.split("#")[-1].strip()
                # Get just the number
                ticket_str = ""
                for char in ticket_part:
                    if char.isdigit():
                        ticket_str += char
                    else:
                        break
                if ticket_str:
                    ticket_id = int(ticket_str)
                    
        except Exception as e:
            logger.error(f"Error parsing title '{title}': {e}")
        
        return baseline, ticket_id
    
    def ingest_prs(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Fetch and ingest PRs into Knowledge Base.
        
        Args:
            limit: Maximum PRs to ingest (None = ALL)
        
        Returns:
            Summary of ingestion
        """
        logger.info(f"Starting PR ingestion (limit: {limit or 'ALL'})")
        
        kb = get_kb_service()
        
        # Fetch PRs (with pagination)
        prs = self.fetch_completed_prs(limit=limit)
        
        if not prs:
            return {"success": False, "message": "No PRs found", "ingested": 0}
        
        ingested = 0
        skipped = 0
        errors = 0
        
        total = len(prs)
        for i, pr in enumerate(prs):
            pr_id = pr.get("pullRequestId")
            title = pr.get("title", "")
            
            # Progress log
            if (i + 1) % 10 == 0:
                logger.info(f"Progress: {i + 1}/{total}")
            
            # Skip if already exists
            if kb.pr_exists(pr_id):
                continue
            
            # Extract baseline and ticket
            baseline, ticket_id = self.extract_baseline_and_ticket(title)
            
            if not baseline:
                logger.warning(f"Skipping PR {pr_id}: Could not extract baseline from '{title}'")
                skipped += 1
                continue
            
            # Fetch detailed info
            details = self.fetch_pr_details(pr_id)
            
            if not details:
                errors += 1
                continue
            
            # Add to KB
            success = kb.add_pr_fix(
                pr_id=pr_id,
                baseline=baseline,
                ticket_id=ticket_id,
                title=title,
                description=details.get("description", ""),
                files_changed=details.get("files_changed", []),
                code_diff=details.get("code_diff", ""),
                metadata={
                    "source_branch": details.get("source_branch", ""),
                    "created_by": details.get("created_by", ""),
                    "created_date": details.get("created_date", ""),
                    "closed_date": details.get("closed_date", "")
                }
            )
            
            if success:
                ingested += 1
            else:
                errors += 1
        
        summary = {
            "success": True,
            "total_prs": len(prs),
            "ingested": ingested,
            "skipped": skipped,
            "errors": errors,
            "kb_total": kb.get_stats()["total_entries"]
        }
        
        logger.info(f"Ingestion complete: {summary}")
        return summary


# Singleton instance
_ingestion_service: Optional[IngestionService] = None


def get_ingestion_service() -> IngestionService:
    """Get singleton ingestion service instance."""
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = IngestionService()
    return _ingestion_service