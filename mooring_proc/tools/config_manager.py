"""Configuration helpers for mooring_proc."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _schema_dir(schema_dir: str | None = None) -> Path:
    """Resolve the schema directory without depending on the notebook CWD.

    If an explicit schema_dir is provided, resolve it directly. Otherwise,
    default to the package-local schemas directory next to this module.
    """
    if schema_dir:
        return Path(schema_dir).expanduser().resolve()
    return (Path(__file__).resolve().parent / "schemas").resolve()


def load_schema_config(schema_path, overrides=None):
    """Load a YAML schema file (or pass through dict config)."""
    if isinstance(schema_path, dict):
        config = dict(schema_path)
    else:
        path = Path(str(schema_path)).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        else:
            path = path.resolve()
        if not path.exists():
            raise FileNotFoundError(f"Schema config not found: {path}")
        with open(path, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}

    merged = dict(config)
    if isinstance(overrides, dict):
        merged.update(overrides)
    return merged


def load_instrument_schema(instrument: str, schema_dir: str | None = None) -> dict[str, Any]:
    path = _schema_dir(schema_dir) / f"{instrument.lower()}_schema.yaml"
    return load_schema_config(path)


def load_global_attributes(schema_dir: str | None = None) -> dict[str, Any]:
    path = _schema_dir(schema_dir) / "global_attributes.yaml"
    return load_schema_config(path)
