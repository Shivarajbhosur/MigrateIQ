"""
File tools for copying baseline folders.
"""

import shutil
from pathlib import Path
from typing import Tuple

import config
from utils.logger import get_logger

logger = get_logger("file_tools")


def copy_baseline(baseline_name: str) -> Tuple[bool, str]:
    """
    Copy baseline folder from source (G:) to destination (C:).
    """
    try:
        source = config.get_source_path(baseline_name)
        dest = config.get_baseline_path(baseline_name)
        
        logger.info(f"Copying baseline: {baseline_name}")
        logger.info(f"Source: {source}")
        logger.info(f"Dest: {dest}")
        
        # Check if source exists
        if not source.exists():
            msg = f"Source not found: {source}"
            logger.error(msg)
            return False, msg
        
        # If dest exists, delete it first (overwrite)
        if dest.exists():
            logger.info(f"Destination exists, removing: {dest}")
            shutil.rmtree(dest)
        
        # Create parent directory if not exists
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy folder
        shutil.copytree(source, dest)
        
        msg = f"Copied successfully: {baseline_name}"
        logger.info(msg)
        return True, msg
        
    except PermissionError as e:
        msg = f"Permission denied: {e}"
        logger.error(msg)
        return False, msg
        
    except Exception as e:
        msg = f"Copy failed: {e}"
        logger.error(msg)
        return False, msg


def baseline_exists_at_source(baseline_name: str) -> bool:
    """Check if baseline exists at source (G:)."""
    source = config.get_source_path(baseline_name)
    return source.exists()


def baseline_exists_at_dest(baseline_name: str) -> bool:
    """Check if baseline exists at destination (C:)."""
    dest = config.get_baseline_path(baseline_name)
    return dest.exists()