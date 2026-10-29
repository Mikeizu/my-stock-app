"""Spreadsheet-safe research exports without changing numeric calculations."""
from __future__ import annotations

import pandas as pd


def safe_csv(frame: pd.DataFrame) -> str:
    """Keep source text from becoming spreadsheet formulas on CSV open."""
    def cell(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
    return frame.map(cell).to_csv(index=False)
