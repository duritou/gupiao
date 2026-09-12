"""Independent artifact location, outside market and learning databases."""
import os
from pathlib import Path


def lab_root() -> Path:
    # Releases and source launches must use the same workspace-owned directory,
    # independently of VS Code/service LOCALAPPDATA overrides.
    for parent in Path(__file__).resolve().parents:
        if (parent / 'config' / 'runtime.env').is_file():
            return parent / 'runtime' / 'adaptive-review-lab'
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AdaptiveInvestmentReviewLab'
