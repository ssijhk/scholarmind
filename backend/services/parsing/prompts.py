"""Prompt template loader for the entire project.

Loads prompt .md files, extracts the actual prompt body from fenced code blocks,
and fills variables. All services share this module via relative imports.

In Docker the prompts are mounted at /prompts via docker-compose volume.
"""
import os
from pathlib import Path

# Docker: prompts mounted at /prompts
# Local dev: prompts is 4 dirs up from backend/services/parsing/prompts.py
if os.path.isdir("/prompts"):
    _PROMPTS_DIR = Path("/prompts")
else:
    _PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"


def load_prompt(name: str) -> str:
    """Load raw .md prompt template from prompts/{name}.md."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt '{name}' not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_body(template: str) -> str:
    """Extract prompt body from markdown wrapper.

    Convention: the real prompt is inside the last ``` fenced code block.
    """
    blocks = template.split("```")
    candidates = [b.strip() for b in blocks[1:-1:2] if b.strip()]
    return candidates[-1] if candidates else template.strip()


def fill_prompt(template: str, **kwargs) -> str:
    """Fill {variable} placeholders in a prompt template."""
    body = _extract_body(template)
    for key, val in kwargs.items():
        body = body.replace(f"{{{key}}}", str(val))
    return body
