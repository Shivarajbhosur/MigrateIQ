"""
Configuration settings for Validation Agent.
Loads environment variables from .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ============================================
# PATH CONFIGURATION
# ============================================

# Base directory (project root)
BASE_DIR = Path(__file__).parent

# Workspace path (where baselines are copied TO - destination)
WORKSPACE_PATH = Path(os.getenv("WORKSPACE_PATH", "C:/Clients/SSAB.OX/baseline"))

# Source path (where baselines are copied FROM - G drive)
SOURCE_PATH = Path(os.getenv("SOURCE_PATH", "G:/Clients/SSAB-OX/Validation"))

# PowerShell library path
PS_LIBRARY_PATH = Path(os.getenv("PS_LIBRARY_PATH", ""))

# Compare script path
COMPARE_SCRIPT_PATH = os.getenv("COMPARE_SCRIPT_PATH", r"C:\Clients\SSAB.OX\baseline\CompareX.ps1")

# Sessions path (for tracking progress)
SESSIONS_PATH = Path(os.getenv("SESSIONS_PATH", "./data/sessions"))

# Logs path
LOGS_PATH = Path(os.getenv("LOGS_PATH", "./data/logs"))

# Codebase repo path
SSAB_OX_REPO_PATH = r"C:\Users\shosur\git\SSAB.OX"

# COBOL source path
COBOL_SOURCE_PATH = os.getenv("COBOL_SOURCE_PATH", "")

# Compare Command
COMPARE_COMMAND = os.getenv("COMPARE_COMMAND", 'compare-x -BaselineName "{baseline_name}" -PromptOnFail $false -GenerateReportOn All')

# ============================================
# AZURE DEVOPS CONFIGURATION
# ============================================

AZURE_DEVOPS_ORG = os.getenv("AZURE_DEVOPS_ORG", "")
AZURE_DEVOPS_PROJECT = os.getenv("AZURE_DEVOPS_PROJECT", "")
AZURE_DEVOPS_REPO = os.getenv("AZURE_DEVOPS_REPO", "")
AZURE_DEVOPS_PAT = os.getenv("AZURE_DEVOPS_PAT", "")

# Local Git Repo
GIT_REPO_PATH = Path(os.getenv("GIT_REPO_PATH", r"C:\Users\shosur\git\SSAB.OX"))
GIT_MAIN_BRANCH = os.getenv("GIT_MAIN_BRANCH", "develop")


# ============================================
# ENSO AI CONFIGURATION (Week 6+)
# ============================================

ENSO_AI_API_URL = os.getenv("ENSO_AI_API_URL", "")
ENSO_AI_API_KEY = os.getenv("ENSO_AI_API_KEY", "")


# ============================================
# LOGGING
# ============================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


# ============================================
# HELPER FUNCTIONS
# ============================================

def get_baseline_group(baseline_name: str) -> str:
    """
    Extract group (SG01, SG02, etc.) from baseline name.
    
    Logic: First 2 digits after "P" = Group number
    
    Example:
        P01001-HOTO311P → "01" → SG01
        P02003-HPPL043P → "02" → SG02
    """
	# Extract digits at position 1-2 (after "P")
    group_number = baseline_name[1:3]
    return f"SG{group_number}"


def get_source_path(baseline_name: str) -> Path:
    """
    Get source path for a baseline (G drive).
    
    Example: 
        Input: "P02003-HPPL043P"
        Output: G:/Clients/SSAB-OX/Validation/SG02/P02003-HPPL043P
    """
    group = get_baseline_group(baseline_name)
    return SOURCE_PATH / group / baseline_name


def get_baseline_path(baseline_name: str) -> Path:
    """
    Get destination path for a baseline (C drive).
    
    Example: 
        Input: "P02003-HPPL043P"
        Output: C:/Clients/SSAB.OX/baseline/SG02/P02003-HPPL043P
    """
    group = get_baseline_group(baseline_name)
    return WORKSPACE_PATH / group / baseline_name


def get_report_path(baseline_name: str) -> Path:
    """
    Get report folder path for a baseline.
    
    Example:
        Input: "P02003-HPPL043P"
        Output: C:/Clients/SSAB.OX/baseline/SG02/P02003-HPPL043P/REPORT
    """
    return get_baseline_path(baseline_name) / "REPORT"


# ============================================
# CREATE DIRECTORIES IF NOT EXIST
# ============================================

def init_directories():
    """Create required directories if they don't exist."""
    SESSIONS_PATH.mkdir(parents=True, exist_ok=True)
    LOGS_PATH.mkdir(parents=True, exist_ok=True)


# Initialize on import
init_directories()


# ============================================
# TEST CONFIG
# ============================================

if __name__ == "__main__":
    print("=== Configuration ===")
    print(f"BASE_DIR: {BASE_DIR}")
    print(f"SOURCE_PATH: {SOURCE_PATH}")
    print(f"WORKSPACE_PATH: {WORKSPACE_PATH}")
    print(f"PS_LIBRARY_PATH: {PS_LIBRARY_PATH}")
    print(f"SESSIONS_PATH: {SESSIONS_PATH}")
    print(f"LOGS_PATH: {LOGS_PATH}")
    print(f"LOG_LEVEL: {LOG_LEVEL}")
    
    print("\n=== Test Paths ===")
    print(f"P02003-HPPL043P SOURCE: {get_source_path('P02003-HPPL043P')}")
    print(f"P02003-HPPL043P DEST:   {get_baseline_path('P02003-HPPL043P')}")
    print(f"P01001-HOTO311P SOURCE: {get_source_path('P01001-HOTO311P')}")
    print(f"P01001-HOTO311P DEST:   {get_baseline_path('P01001-HOTO311P')}")
    print(f"\n=== Azure DevOps ===")
    print(f"AZURE_DEVOPS_ORG: {AZURE_DEVOPS_ORG}")
    print(f"AZURE_DEVOPS_REPO: {AZURE_DEVOPS_REPO}")
    print(f"GIT_REPO_PATH: {GIT_REPO_PATH}")
    print(f"GIT_MAIN_BRANCH: {GIT_MAIN_BRANCH}")