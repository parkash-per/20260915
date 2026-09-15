"""Interactive helper for finding inst_deploy_ID values from metadata.

Usage
-----
Terminal interactive mode:
    python tools/inst_deploy_id_finder.py

Notebook or Python usage:
    from tools.inst_deploy_id_finder import preview_inst_deploy_ids
    preview_inst_deploy_ids(instrument="SBE37", search_text="BASJAS", max_rows=25)

Main functions
--------------
- find_inst_deploy_ids: return a filtered DataFrame.
- preview_inst_deploy_ids: print a compact table and return the filtered DataFrame.
- interactive_lookup: prompt for inputs in terminal and print matches.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from tools.database_lookup import list_instruments


SEARCH_COLUMNS = [
    "inst_deploy_ID",
    "deployment_id",
    "location",
    "inst_type",
    "inst_id",
    "mooring_channels",
]

DISPLAY_COLUMNS = [
    "inst_deploy_ID",
    "deployment_id",
    "location",
    "inst_type",
    "inst_id",
    "mooring_channels",
    "time_coverage_start",
    "time_coverage_end",
]


USAGE_TEXT = """inst_deploy_ID finder

Leave fields blank to skip a filter.
Prompts:
- Instrument [SBE37]
- Year [optional]
- Location [optional]
- Mooring channel [optional]
- Deployment ID [optional]
- Search text [optional]
- Max rows [25]
"""


def _blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _filter_search_text(table: pd.DataFrame, search_text: str | None) -> pd.DataFrame:
    search_text = _blank_to_none(search_text)
    if search_text is None:
        return table

    available_search_cols = [name for name in SEARCH_COLUMNS if name in table.columns]
    if not available_search_cols:
        return table

    combined = table.loc[:, available_search_cols].fillna("").astype(str).agg(" | ".join, axis=1)
    return table.loc[combined.str.casefold().str.contains(search_text.casefold(), na=False)]


def find_inst_deploy_ids(
    instrument: str = "SBE37",
    year: int | None = None,
    location: str | None = None,
    mooring_channel: str | None = None,
    deployment_id: str | None = None,
    search_text: str | None = None,
) -> pd.DataFrame:
    """Return matching metadata rows for interactive ID discovery."""
    normalized_instrument = (_blank_to_none(instrument) or "SBE37").upper()
    normalized_year = int(year) if year not in (None, "") else None

    table = list_instruments(
        None,
        year=normalized_year,
        location=_blank_to_none(location),
        instrument=normalized_instrument,
        mooring_channel=_blank_to_none(mooring_channel),
        deployment_id=_blank_to_none(deployment_id),
        include_paths=False,
    )
    table = _filter_search_text(table, search_text)
    return table.reset_index(drop=True)


def preview_inst_deploy_ids(
    instrument: str = "SBE37",
    year: int | None = None,
    location: str | None = None,
    mooring_channel: str | None = None,
    deployment_id: str | None = None,
    search_text: str | None = None,
    max_rows: int = 25,
) -> pd.DataFrame:
    """Print a compact preview and return the full filtered table."""
    table = find_inst_deploy_ids(
        instrument=instrument,
        year=year,
        location=location,
        mooring_channel=mooring_channel,
        deployment_id=deployment_id,
        search_text=search_text,
    )

    max_rows = int(max_rows)
    if max_rows < 1:
        raise ValueError("max_rows must be >= 1")

    if table.empty:
        print("No matching deployments found.")
        print("Try clearing filters or changing search_text.")
        return table

    available_columns = [name for name in DISPLAY_COLUMNS if name in table.columns]
    print(f"Matched {len(table)} row(s).")
    if len(table) > max_rows:
        print(f"Showing first {max_rows} rows. Tighten filters to narrow results.")

    print(table.loc[:, available_columns].head(max_rows).to_string(index=False))
    return table


def interactive_lookup() -> pd.DataFrame:
    """Prompt for finder inputs and print matching deployment IDs."""
    print(USAGE_TEXT)

    instrument = input("Instrument [SBE37]: ").strip() or "SBE37"
    year_raw = input("Year [optional]: ").strip()
    year = int(year_raw) if year_raw else None
    location = input("Location [optional]: ").strip() or None
    mooring_channel = input("Mooring channel [optional]: ").strip() or None
    deployment_id = input("Deployment ID [optional]: ").strip() or None
    search_text = input("Search text [optional]: ").strip() or None
    max_rows_raw = input("Max rows [25]: ").strip()
    max_rows = int(max_rows_raw) if max_rows_raw else 25

    return preview_inst_deploy_ids(
        instrument=instrument,
        year=year,
        location=location,
        mooring_channel=mooring_channel,
        deployment_id=deployment_id,
        search_text=search_text,
        max_rows=max_rows,
    )


if __name__ == "__main__":
    interactive_lookup()
