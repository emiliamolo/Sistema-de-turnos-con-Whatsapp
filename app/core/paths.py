"""
Path utilities for templates and static files.
Handles different execution contexts (local, Docker, tests).
"""

from pathlib import Path

def get_template_dir() -> str:
    """
    Get the absolute path to the templates directory.
    Works from any execution context.
    """
    # Get the directory where this file is located (src/app/core/)
    current_dir = Path(__file__).parent.parent
    templates_dir = current_dir / "templates"
    return str(templates_dir)

def get_static_dir() -> str:
    """
    Get the absolute path to the static files directory.
    Works from any execution context.
    """
    current_dir = Path(__file__).parent.parent
    static_dir = current_dir / "static"
    return str(static_dir)
