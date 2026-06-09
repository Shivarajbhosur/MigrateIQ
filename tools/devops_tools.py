"""
Azure DevOps tools for branch creation and PR management.

SAFETY RULES:
- ✅ Can checkout any branch (including master)
- ✅ Can pull any branch
- ✅ Can create new branches from master
- ❌ CANNOT push to master (blocked)
"""

import subprocess
import requests
import base64
from typing import Tuple
from pathlib import Path

import config
from utils.logger import get_logger

logger = get_logger("devops_tools")

# Protected branches - cannot push to these
PROTECTED_BRANCHES = ["master", "main", "develop"]


def get_auth_header() -> dict:
    """Get authorization header for Azure DevOps API."""
    pat = config.AZURE_DEVOPS_PAT
    encoded = base64.b64encode(f":{pat}".encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json"
    }


def get_api_url() -> str:
    """Get Azure DevOps API base URL."""
    org = config.AZURE_DEVOPS_ORG
    project = config.AZURE_DEVOPS_PROJECT
    repo = config.AZURE_DEVOPS_REPO
    return f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}"


def get_branch_name(baseline_name: str) -> str:
    """
    Get branch name for baseline.
    
    Example: P02001-HPPL042P → SG02/P02001-HPPL042P
    """
    group = config.get_baseline_group(baseline_name)
    return f"{group}/{baseline_name}"


def get_current_branch(repo_path: Path) -> str:
    """Get current branch name in local repo."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        return result.stdout.strip()
    except:
        return ""


def is_protected_branch(branch_name: str) -> bool:
    """Check if branch is protected (master/main)."""
    return branch_name.lower() in PROTECTED_BRANCHES


def branch_exists_remote(branch_name: str) -> bool:
    """Check if branch exists in Azure DevOps."""
    try:
        url = f"{get_api_url()}/refs?filter=heads/{branch_name}&api-version=7.0"
        response = requests.get(url, headers=get_auth_header())
        
        if response.status_code == 200:
            data = response.json()
            return len(data.get("value", [])) > 0
        return False
    except Exception as e:
        logger.error(f"Error checking branch: {e}")
        return False


def create_branch_remote(baseline_name: str) -> Tuple[bool, str]:
    """
    Create branch in Azure DevOps from develop.
    
    SAFETY: This only CREATES a new branch. Does NOT modify develop.
    
    Args:
        baseline_name: e.g., "P02001-HPPL042P"
    
    Returns:
        Tuple[bool, str]: (success, message)
    """
    branch_name = get_branch_name(baseline_name)
    logger.info(f"Creating branch: {branch_name}")
    
    # Safety check: Never create a branch named master/main/develop
    if is_protected_branch(branch_name):
        msg = "SAFETY: Cannot create branch named master/main/develop"
        logger.error(msg)
        return False, msg
    
    # Check if branch already exists
    if branch_exists_remote(branch_name):
        msg = f"Branch {branch_name} already exists"
        logger.info(msg)
        return True, msg
    
    try:
        # Get develop branch ref (READ-ONLY operation)
        main_branch = config.GIT_MAIN_BRANCH
        url = f"{get_api_url()}/refs?filter=heads/{main_branch}&api-version=7.0"
        response = requests.get(url, headers=get_auth_header())
        
        if response.status_code != 200:
            msg = f"Failed to get {main_branch} branch: {response.text}"
            logger.error(msg)
            return False, msg
        
        data = response.json()
        if not data.get("value"):
            msg = f"Branch {main_branch} not found"
            logger.error(msg)
            return False, msg
        
        develop_commit = data["value"][0]["objectId"]
        logger.info(f"Develop commit: {develop_commit}")
        
        # Create NEW branch (does NOT modify develop)
        url = f"{get_api_url()}/refs?api-version=7.0"
        payload = [
            {
                "name": f"refs/heads/{branch_name}",
                "oldObjectId": "0000000000000000000000000000000000000000",
                "newObjectId": develop_commit
            }
        ]
        
        response = requests.post(url, headers=get_auth_header(), json=payload)
        
        if response.status_code in [200, 201]:
            msg = f"Branch {branch_name} created successfully"
            logger.info(msg)
            return True, msg
        else:
            msg = f"Failed to create branch: {response.text}"
            logger.error(msg)
            return False, msg
            
    except Exception as e:
        msg = f"Error creating branch: {e}"
        logger.error(msg)
        return False, msg

def pull_branch_local(baseline_name: str) -> Tuple[bool, str]:
    """
    Pull/checkout branch to local repo.
    
    Args:
        baseline_name: e.g., "P02001-HPPL042P"
    
    Returns:
        Tuple[bool, str]: (success, message)
    """
    branch_name = get_branch_name(baseline_name)
    repo_path = config.GIT_REPO_PATH
    
    logger.info(f"Pulling branch {branch_name} to {repo_path}")
    
    try:
        # Fetch all branches (READ-ONLY, safe)
        result = subprocess.run(
            ["git", "fetch", "--all"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            msg = f"Git fetch failed: {result.stderr}"
            logger.error(msg)
            return False, msg
        
        # Check if branch exists locally
        check_local = subprocess.run(
            ["git", "branch", "--list", branch_name],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        branch_exists_locally = bool(check_local.stdout.strip())
        
        if branch_exists_locally:
            # Branch exists locally - just checkout
            logger.info(f"Branch {branch_name} exists locally, checking out...")
            result = subprocess.run(
                ["git", "checkout", branch_name],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                msg = f"Git checkout failed: {result.stderr}"
                logger.error(msg)
                return False, msg
        else:
            # Branch does NOT exist locally - create tracking branch
            logger.info(f"Branch {branch_name} not found locally, creating tracking branch...")
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                msg = f"Git checkout failed: {result.stderr}"
                logger.error(msg)
                return False, msg
        
        # Pull latest
        result = subprocess.run(
            ["git", "pull"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        msg = f"Branch {branch_name} checked out and pulled"
        logger.info(msg)
        return True, msg
        
    except Exception as e:
        msg = f"Error pulling branch: {e}"
        logger.error(msg)
        return False, msg


def push_branch(baseline_name: str) -> Tuple[bool, str]:
    """
    Push current branch to remote.
    
    SAFETY: Will NOT push to master/main.
    
    Args:
        baseline_name: e.g., "P02001-HPPL042P"
    
    Returns:
        Tuple[bool, str]: (success, message)
    """
    repo_path = config.GIT_REPO_PATH
    
    # Get current branch
    current_branch = get_current_branch(repo_path)
    
    # SAFETY: Block push to protected branches
    if is_protected_branch(current_branch):
        msg = f"🛑 SAFETY BLOCK: Cannot push to protected branch '{current_branch}'"
        logger.error(msg)
        return False, msg
    
    logger.info(f"Pushing branch: {current_branch}")
    
    try:
        result = subprocess.run(
            ["git", "push", "-u", "origin", current_branch],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            msg = f"Branch {current_branch} pushed successfully"
            logger.info(msg)
            return True, msg
        else:
            msg = f"Git push failed: {result.stderr}"
            logger.error(msg)
            return False, msg
            
    except Exception as e:
        msg = f"Error pushing branch: {e}"
        logger.error(msg)
        return False, msg

def find_ticket_by_baseline(baseline_name: str) -> Tuple[bool, int, str]:
    """
    Search for ticket by baseline name in title.
    
    Args:
        baseline_name: e.g., "P03024-HMAB067P"
    
    Returns:
        Tuple[bool, int, str]: (success, ticket_id, message)
    """
    logger.info(f"Searching for ticket with baseline: {baseline_name}")
    
    try:
        org = config.AZURE_DEVOPS_ORG
        project = config.AZURE_DEVOPS_PROJECT
        
        # WIQL query to find work item by title
        url = f"https://dev.azure.com/{org}/{project}/_apis/wit/wiql?api-version=7.0"
        
        query = {
            "query": f"SELECT [System.Id], [System.Title] FROM WorkItems WHERE [System.Title] CONTAINS '{baseline_name}' AND [System.Title] CONTAINS '03-Validation'"
        }
        
        response = requests.post(url, headers=get_auth_header(), json=query)
        
        if response.status_code != 200:
            msg = f"Failed to search tickets: {response.text}"
            logger.error(msg)
            return False, 0, msg
        
        data = response.json()
        work_items = data.get("workItems", [])
        
        if not work_items:
            msg = f"No ticket found for baseline: {baseline_name}"
            logger.warning(msg)
            return False, 0, msg
        
        # Get first matching ticket
        ticket_id = work_items[0]["id"]
        logger.info(f"Found ticket ID: {ticket_id}")
        return True, ticket_id, f"Found ticket {ticket_id}"
        
    except Exception as e:
        msg = f"Error searching ticket: {e}"
        logger.error(msg)
        return False, 0, msg
def get_repo_id() -> str:
    """Get repository ID for linking."""
    try:
        url = f"{get_api_url()}?api-version=7.0"
        response = requests.get(url, headers=get_auth_header())
        
        if response.status_code == 200:
            data = response.json()
            return data.get("id", "")
        return ""
    except:
        return ""


def get_project_id() -> str:
    """Get project ID for linking."""
    try:
        org = config.AZURE_DEVOPS_ORG
        project = config.AZURE_DEVOPS_PROJECT
        
        url = f"https://dev.azure.com/{org}/_apis/projects/{project}?api-version=7.0"
        response = requests.get(url, headers=get_auth_header())
        
        if response.status_code == 200:
            data = response.json()
            return data.get("id", "")
        return ""
    except:
        return ""


def link_branch_to_ticket(baseline_name: str, ticket_id: int) -> Tuple[bool, str]:
    """
    Link branch to work item/ticket.
    
    Args:
        baseline_name: e.g., "P03024-HMAB067P"
        ticket_id: e.g., 88004
    
    Returns:
        Tuple[bool, str]: (success, message)
    """
    branch_name = get_branch_name(baseline_name)
    logger.info(f"Linking branch {branch_name} to ticket {ticket_id}")
    
    try:
        org = config.AZURE_DEVOPS_ORG
        project = config.AZURE_DEVOPS_PROJECT
        
        # Get repo and project IDs
        repo_id = get_repo_id()
        project_id = get_project_id()
        
        if not repo_id or not project_id:
            msg = "Failed to get repo/project ID"
            logger.error(msg)
            return False, msg
        
        # Create artifact URI for branch link
        artifact_uri = f"vstfs:///Git/Ref/{project_id}%2F{repo_id}%2FGB{branch_name.replace('/', '%2F')}"
        
        # Update work item with branch link
        url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{ticket_id}?api-version=7.0"
        
        headers = get_auth_header()
        headers["Content-Type"] = "application/json-patch+json"
        
        payload = [
            {
                "op": "add",
                "path": "/relations/-",
                "value": {
                    "rel": "ArtifactLink",
                    "url": artifact_uri,
                    "attributes": {
                        "name": "Branch"
                    }
                }
            }
        ]
        
        response = requests.patch(url, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            msg = f"Branch {branch_name} linked to ticket {ticket_id}"
            logger.info(msg)
            return True, msg
        elif "RelationAlreadyExistsException" in response.text:
            # Already linked = SUCCESS
            msg = f"Branch {branch_name} already linked to ticket {ticket_id}"
            logger.info(msg)
            return True, msg
        else:
            msg = f"Failed to link branch: {response.text}"
            logger.error(msg)
            return False, msg
            
    except Exception as e:
        msg = f"Error linking branch: {e}"
        logger.error(msg)
        return False, msg



def set_ticket_active(ticket_id: int) -> Tuple[bool, str]:
    """
    Set ticket state to Active.
    
    Args:
        ticket_id: e.g., 88004
    
    Returns:
        Tuple[bool, str]: (success, message)
    """
    logger.info(f"Setting ticket {ticket_id} to Active")
    
    try:
        org = config.AZURE_DEVOPS_ORG
        project = config.AZURE_DEVOPS_PROJECT
        
        url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{ticket_id}?api-version=7.0"
        
        headers = get_auth_header()
        headers["Content-Type"] = "application/json-patch+json"
        
        payload = [
            {
                "op": "add",
                "path": "/fields/System.State",
                "value": "Active"
            }
        ]
        
        response = requests.patch(url, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            msg = f"Ticket {ticket_id} set to Active"
            logger.info(msg)
            return True, msg
        elif "already" in response.text.lower() or response.status_code == 200:
            msg = f"Ticket {ticket_id} already Active"
            logger.info(msg)
            return True, msg
        else:
            msg = f"Failed to update ticket state: {response.text}"
            logger.error(msg)
            return False, msg
            
    except Exception as e:
        msg = f"Error updating ticket state: {e}"
        logger.error(msg)
        return False, msg
        
        

def create_and_pull_branch(baseline_name: str) -> Tuple[bool, str]:
    """
    Step 3a: Create branch in Azure DevOps, pull to local, link to ticket, and activate.
    
    SAFETY:
    - Creates NEW branch from master (does not modify master)
    - Checks out the new feature branch
    - Links branch to ticket (optional - won't fail if linking fails)
    - Sets ticket to Active state
    
    Args:
        baseline_name: e.g., "P02001-HPPL042P"
    
    Returns:
        Tuple[bool, str]: (success, message)
    """
    # Step 1: Create branch in Azure DevOps (CRITICAL)
    success, msg = create_branch_remote(baseline_name)
    if not success:
        return False, msg
    
    # Step 2: Pull to local (CRITICAL)
    success, msg = pull_branch_local(baseline_name)
    if not success:
        return False, msg
    
    # Git operations SUCCESS ✅
    branch_name = get_branch_name(baseline_name)
    
    # Step 3: Find and link to ticket (OPTIONAL)
    ticket_success, ticket_id, ticket_msg = find_ticket_by_baseline(baseline_name)
    
    if ticket_success:
        # Link branch to ticket
        link_success, link_msg = link_branch_to_ticket(baseline_name, ticket_id)
        
        # Set ticket to Active
        active_success, active_msg = set_ticket_active(ticket_id)
        
        if link_success:
            return True, f"Branch {branch_name} created, pulled, and linked to ticket {ticket_id}"
        else:
            logger.warning(f"Branch created but linking failed: {link_msg}")
            return True, f"Branch {branch_name} created and pulled. (Linking failed: {link_msg})"
    else:
        logger.warning(f"Branch created but no ticket found: {ticket_msg}")
        return True, f"Branch {branch_name} created and pulled. (No ticket found)"
        
 ##for reporting task for below      
def find_reporting_ticket_by_baseline(baseline_name: str) -> Tuple[bool, int, str]:
    """
    Search for REPORTING ticket by baseline name in title.
    
    Args:
        baseline_name: e.g., "P02070-HPPL486P"
    
    Returns:
        Tuple[bool, int, str]: (success, ticket_id, message)
    """
    logger.info(f"Searching for reporting ticket with baseline: {baseline_name}")
    
    try:
        org = config.AZURE_DEVOPS_ORG
        project = config.AZURE_DEVOPS_PROJECT
        
        # WIQL query to find reporting work item by title
        url = f"https://dev.azure.com/{org}/{project}/_apis/wit/wiql?api-version=7.0"
        
        query = {
            "query": f"SELECT [System.Id], [System.Title] FROM WorkItems WHERE [System.Title] CONTAINS '{baseline_name}' AND [System.Title] CONTAINS '05-Reporting'"
        }
        
        response = requests.post(url, headers=get_auth_header(), json=query)
        
        if response.status_code != 200:
            msg = f"Failed to search tickets: {response.text}"
            logger.error(msg)
            return False, 0, msg
        
        data = response.json()
        work_items = data.get("workItems", [])
        
        if not work_items:
            msg = f"No reporting ticket found for baseline: {baseline_name}"
            logger.warning(msg)
            return False, 0, msg
        
        # Get first matching ticket
        ticket_id = work_items[0]["id"]
        logger.info(f"Found reporting ticket ID: {ticket_id}")
        return True, ticket_id, f"Found reporting ticket {ticket_id}"
        
    except Exception as e:
        msg = f"Error searching reporting ticket: {e}"
        logger.error(msg)
        return False, 0, msg


def close_ticket(ticket_id: int, reason: str = "Completed") -> Tuple[bool, str]:
    """
    Close a ticket (set state to Closed).
    
    Reusable for both Reporting and Validation finalize.
    
    Args:
        ticket_id: e.g., 82244
        reason: Close reason (default: "Completed")
    
    Returns:
        Tuple[bool, str]: (success, message)
    """
    logger.info(f"Closing ticket {ticket_id} with reason: {reason}")
    
    try:
        org = config.AZURE_DEVOPS_ORG
        project = config.AZURE_DEVOPS_PROJECT
        
        url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{ticket_id}?api-version=7.0"
        
        headers = get_auth_header()
        headers["Content-Type"] = "application/json-patch+json"
        
        payload = [
            {
                "op": "add",
                "path": "/fields/System.State",
                "value": "Closed"
            },
            {
                "op": "add",
                "path": "/fields/System.Reason",
                "value": reason
            }
        ]
        
        response = requests.patch(url, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            msg = f"Ticket {ticket_id} closed successfully"
            logger.info(msg)
            return True, msg
        elif "already" in response.text.lower():
            msg = f"Ticket {ticket_id} already closed"
            logger.info(msg)
            return True, msg
        else:
            msg = f"Failed to close ticket: {response.text}"
            logger.error(msg)
            return False, msg
            
    except Exception as e:
        msg = f"Error closing ticket: {e}"
        logger.error(msg)
        return False, msg  