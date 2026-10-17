"""Regenerate data/synthetic/ from src/studyspace/synthetic/generator.py (deterministic)."""

from studyspace.config import load_settings
from studyspace.synthetic import write

if __name__ == "__main__":
    print(f"wrote {write(load_settings().synthetic_dir)}")
