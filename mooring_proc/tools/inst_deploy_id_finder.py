from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_inst_deploy_table(csv_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load the instrument-deployment lookup table.
    """
    if csv_path is None:
        csv_path = _repo_root() / "mooring_proc" / "db" / "inst_deploy.csv"
    df = pd.read_csv(csv_path)
    return df


def _norm_text(value) -> str:
    """Normalize text for robust matching."""
    if value is None:
        return ""
    return str(value).strip()


def preview_inst_deploy_ids(
    instrument: Optional[str] = None,
    year: Optional[int] = None,
    location: Optional[str] = None,
    mooring_channel: Optional[str] = None,
    deployment_id: Optional[str] = None,
    search_text: Optional[str] = None,
    max_rows: int = 25,
    csv_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Filter and preview candidate instrument deployment rows.

    Matching rules:
    - instrument/location/deployment_id: case-insensitive "contains" text match
    - mooring_channel: case-insensitive "contains" match within mooring_channels
    - year: exact match against parsed numeric deployment year (first 4 digits)
    - search_text: case-insensitive contains across all columns
    """
    df = load_inst_deploy_table(csv_path=csv_path).copy()

    # Normalize frequently-used string columns once
    for col in ["inst_type", "location", "deployment_id", "mooring_channels"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Instrument (case-insensitive partial match)
    instrument_s = _norm_text(instrument)
    if instrument_s:
        if "inst_type" not in df.columns:
            raise KeyError("Expected column 'inst_type' not found in inst_deploy table.")
        df = df[
            df["inst_type"].str.contains(instrument_s, case=False, na=False)
        ]

    # Year from deployment_id prefix (e.g., 2025f -> 2025)
    if year is not None:
        if "deployment_id" not in df.columns:
            raise KeyError("Expected column 'deployment_id' not found in inst_deploy table.")
        dep_year = pd.to_numeric(
            df["deployment_id"].astype(str).str.extract(r"^(\d{4})")[0],
            errors="coerce",
        )
        df = df[dep_year == int(year)]

    # Location (case-insensitive partial match)
    location_s = _norm_text(location)
    if location_s:
        if "location" not in df.columns:
            raise KeyError("Expected column 'location' not found in inst_deploy table.")
        df = df[
            df["location"].str.contains(location_s, case=False, na=False)
        ]

    # Mooring channel contained in mooring_channels (e.g. "U" matches "PTSUV")
    mooring_channel_s = _norm_text(mooring_channel)
    if mooring_channel_s:
        if "mooring_channels" not in df.columns:
            raise KeyError("Expected column 'mooring_channels' not found in inst_deploy table.")
        df = df[
            df["mooring_channels"].str.contains(mooring_channel_s, case=False, na=False)
        ]

    # deployment_id (case-insensitive partial match)
    deployment_id_s = _norm_text(deployment_id)
    if deployment_id_s:
        if "deployment_id" not in df.columns:
            raise KeyError("Expected column 'deployment_id' not found in inst_deploy table.")
        df = df[
            df["deployment_id"].str.contains(deployment_id_s, case=False, na=False)
        ]

    # Free-text search across all columns
    search_text_s = _norm_text(search_text)
    if search_text_s:
        row_match = pd.Series(False, index=df.index)
        for col in df.columns:
            row_match = row_match | df[col].astype(str).str.contains(
                search_text_s, case=False, na=False
            )
        df = df[row_match]

    # Friendly sort if key columns exist
    sort_cols = [c for c in ["inst_deploy_ID", "deployment_id", "location", "inst_type"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, kind="stable")

    # Limit rows
    max_rows = int(max_rows) if max_rows is not None else 25
    if max_rows > 0:
        preview_df = df.head(max_rows).copy()
    else:
        preview_df = df.copy()

    # Print compact preview
    print(f"Matched {len(df)} row(s).")
    if preview_df.empty:
        print("No matching rows.")
    else:
        compact_cols = [
            c for c in [
                "inst_deploy_ID",
                "deployment_id",
                "location",
                "inst_type",
                "inst_id",
                "mooring_channels",
                "time_coverage_start",
                "time_coverage_end",
            ]
            if c in preview_df.columns
        ]
        if compact_cols:
            print(preview_df[compact_cols].to_string(index=False))
        else:
            print(preview_df.to_string(index=False))

    return preview_df
