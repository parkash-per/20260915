"""Writers for IMOS-style output products."""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from ..config_manager import load_global_attributes, load_instrument_schema


TIME_UNITS = "days since 1950-01-01T00:00:00 UTC"
_INTERNAL_METADATA_KEYS = {
    "proc_1_file",
    "proc_2_file",
    "proc_1_path",
    "proc_2_path",
    "input_file_path",
    "output_dir",
    "output_stage",
    "output_name_mode",
    "manual_qc_flags",
    "flag_windows",
    "range_tag",
}

# Canonical order for global attributes in IMOS files
_GLOBAL_ATTR_ORDER = [
    "project",
    "Conventions",
    "title",
    "institution",
    "date_created",
    "abstract",
    "keywords",
    "distribution_statement",
    "geospatial_lat_min",
    "geospatial_lat_max",
    "geospatial_lon_min",
    "geospatial_lon_max",
    "geospatial_vertical_min",
    "geospatial_vertical_max",
    "geospatial_vertical_positive",
    "time_coverage_start",
    "time_coverage_end",
    "data_centre_email",
    "processing_version",
    "author_email",
    "author",
    "principal_investigator",
    "naming_authority",
    "site_code",
    "site",
    "instrument",
    "instrument_serial_number",
    "serial",
    "location",
    "deployment_id",
    "mooring_channels",
    "acknowledgement",
    "citation",
    "data_centre",
    "history",
    "source",
    "references",
    "disclaimer",
    "license",
    "standard_name_vocabulary",
    "keywords_vocabulary",
]

GLOBAL_ATTR_TYPE_MAP: dict[str, str] = {
    "instrument": "str",
    "instrument_serial_number": "int",
    "processing_version": "str",
    "time_coverage_start": "str",
    "time_coverage_end": "str",
    "source_file": "str",
    "geospatial_lat_min": "f32",
    "geospatial_lat_max": "f32",
    "geospatial_lon_min": "f32",
    "geospatial_lon_max": "f32",
    "geospatial_vertical_min": "f32",
    "geospatial_vertical_max": "f32",
}

VAR_ATTR_TYPE_MAP: dict[str, str] = {
    "flag_values": "str",
    "flag_meanings": "str",
    "valid_min": "typed-token",
    "valid_max": "typed-token",
    "uncertainty": "typed-token",
    "time_uncertainty": "typed-token",
    "_FillValue": "typed-token",
    "missing_value": "typed-token",
    "applied_offset": "typed-token",
}

_TOKEN_PATTERN = re.compile(r"^\s*([+-]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][+-]?\d+)?)\s*([fFbB])?\s*$")


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none"}


def _normalize_processing_version(version: Any) -> str:
    if _is_blank(version):
        return ""
    text = str(version).strip()
    try:
        numeric = int(float(text))
        if 0 <= numeric < 100:
            return f"{numeric:02d}"
    except (TypeError, ValueError):
        pass
    return text


def _parse_datetime(value: Any) -> pd.Timestamp:
    parsed = pd.to_datetime(value, format="mixed", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, dayfirst=True, format="mixed", errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Unable to parse datetime value: {value}")
    return parsed


def _time_values_to_datetime(time_values) -> pd.DatetimeIndex:
    values = np.asarray(time_values)
    if np.issubdtype(values.dtype, np.datetime64):
        return pd.to_datetime(values)
    return pd.to_datetime("1950-01-01") + pd.to_timedelta(values, unit="D")


def _to_days_since_1950(time_values) -> np.ndarray:
    timestamps = pd.to_datetime(time_values)
    reference = pd.Timestamp("1950-01-01")
    return ((timestamps - reference) / pd.Timedelta(days=1)).to_numpy(dtype=np.float64)


def _site_token(value: Any) -> str:
    return str(value or "").strip().replace(" ", "")


def _instrument_token(value: Any) -> str:
    return str(value or "").strip().upper().replace("_", "").replace(" ", "")


def _depth_token(value: Any) -> str:
    try:
        return f"{int(round(float(value)))}m"
    except (TypeError, ValueError):
        return f"{str(value).strip()}m"


def _normalize_source_file(value: Any) -> str:
    if _is_blank(value):
        return ""
    return Path(str(value)).name


def _normalize_metadata_for_netcdf(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in metadata.items() if key not in _INTERNAL_METADATA_KEYS}
    if "source_file" in cleaned:
        cleaned["source_file"] = _normalize_source_file(cleaned.get("source_file"))
    return cleaned


def _normalize_dataset_attrs_for_netcdf(dataset: xr.Dataset) -> xr.Dataset:
    prepared = dataset.copy(deep=True)
    attrs = {key: value for key, value in dict(prepared.attrs).items() if key not in _INTERNAL_METADATA_KEYS}
    if "source_file" in attrs:
        attrs["source_file"] = _normalize_source_file(attrs.get("source_file"))
    prepared.attrs = attrs
    return prepared


def _channel_token(metadata: dict[str, Any]) -> str:
    """Get channel token for filename, prioritizing inst_channels over mooring_channels.
    
    Returns the first non-blank value from:
    1. inst_channels
    2. mooring_channels
    3. "missing" as fallback when both are blank
    """
    for key in ("inst_channels", "mooring_channels"):
        value = metadata.get(key)
        if not _is_blank(value):
            return str(value)
    return "missing"


def _scalar_metadata_value(prepared: xr.Dataset, metadata: dict[str, Any], attrs: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key, attrs.get(key))
        if not _is_blank(value):
            return value
    for variable_name in {key.upper() for key in keys}:
        if variable_name not in prepared.variables:
            continue
        raw_value = np.asarray(prepared[variable_name].values).squeeze()
        if np.size(raw_value) == 1:
            scalar = raw_value.item()
            if not _is_blank(scalar):
                return scalar
    return None


def _cast_global_attr_value(key: str, value: Any) -> Any:
    if _is_blank(value):
        return None

    cast_type = GLOBAL_ATTR_TYPE_MAP.get(key, "str")
    if cast_type == "int":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return str(value)

    if cast_type == "f32":
        try:
            return np.float32(float(value))
        except (TypeError, ValueError):
            return value

    return str(value)


def _parse_typed_token(value: Any) -> Any:
    if isinstance(value, (int, float, np.integer, np.floating)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    match = _TOKEN_PATTERN.match(text)
    if not match:
        return value
    number_text, suffix = match.groups()
    suffix = (suffix or "").lower()
    try:
        if suffix == "b":
            return np.int8(int(float(number_text)))
        if suffix == "f":
            return np.float32(float(number_text))
        if "." in number_text or "e" in number_text.lower():
            return float(number_text)
        return int(number_text)
    except (TypeError, ValueError):
        return value


def _coerce_var_attr_value(attr_name: str, value: Any) -> Any:
    cast_type = VAR_ATTR_TYPE_MAP.get(attr_name)
    if cast_type == "str":
        if isinstance(value, (list, tuple, np.ndarray)):
            return ", ".join(str(v) for v in value)
        return str(value)

    if cast_type == "typed-token":
        if isinstance(value, (list, tuple, np.ndarray)):
            return np.asarray([_parse_typed_token(v) for v in value])
        return _parse_typed_token(value)

    return value


def _runtime_global_attr_values(
    prepared: xr.Dataset,
    metadata: dict[str, Any],
    attrs: dict[str, Any],
    derived_start_text: str,
    derived_end_text: str,
) -> dict[str, Any]:
    latitude = _scalar_metadata_value(prepared, metadata, attrs, "latitude")
    longitude = _scalar_metadata_value(prepared, metadata, attrs, "longitude")
    nominal_depth = _scalar_metadata_value(prepared, metadata, attrs, "nominal_inst_depth", "depth", "nominal_depth")
    
    # Generate timestamp for file creation
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "instrument": metadata.get("inst_type", metadata.get("instrument", attrs.get("instrument", ""))),
        "instrument_serial_number": metadata.get(
            "instrument_serial_number",
            metadata.get("inst_id", attrs.get("instrument_serial_number", attrs.get("serial", ""))),
        ),
        "processing_version": _normalize_processing_version(metadata.get("version", attrs.get("processing_version", ""))),
        "time_coverage_start": metadata.get("time_coverage_start") or derived_start_text,
        "time_coverage_end": metadata.get("time_coverage_end") or derived_end_text,
        "source_file": _normalize_source_file(metadata.get("source_file", attrs.get("source_file", ""))),
        "date_created": now_iso,
        "history": f"Created {now_iso}",
        "geospatial_lat_min": latitude,
        "geospatial_lat_max": latitude,
        "geospatial_lon_min": longitude,
        "geospatial_lon_max": longitude,
        "geospatial_vertical_min": nominal_depth,
        "geospatial_vertical_max": nominal_depth,
    }


def _schema_global_attrs(
    prepared: xr.Dataset,
    metadata: dict[str, Any],
    attrs: dict[str, Any],
    schema_dir: str | None,
    derived_start_text: str,
    derived_end_text: str,
) -> dict[str, Any]:
    global_schema = load_global_attributes(schema_dir=schema_dir)
    resolved: dict[str, Any] = {}

    for section_name in ("mandatory_attributes", "defaults"):
        section = global_schema.get(section_name, {}) or {}
        if isinstance(section, dict):
            for key, value in section.items():
                resolved[key] = value

    geospatial = global_schema.get("geospatial", {}) or {}
    geospatial_aliases = {
        "positive": "geospatial_vertical_positive",
        "lat_max": "geospatial_lat_max",
        "lat_min": "geospatial_lat_min",
        "lon_max": "geospatial_lon_max",
        "lon_min": "geospatial_lon_min",
        "vertical_max": "geospatial_vertical_max",
        "vertical_min": "geospatial_vertical_min",
    }

    runtime_values = _runtime_global_attr_values(prepared, metadata, attrs, derived_start_text, derived_end_text)

    if isinstance(geospatial, dict):
        for key, value in geospatial.items():
            attr_key = geospatial_aliases.get(key, key)
            resolved[attr_key] = value

    final_attrs: dict[str, Any] = {}
    for key, yaml_value in resolved.items():
        value = yaml_value
        if value is None or _is_blank(value):
            value = runtime_values.get(key)
        casted = _cast_global_attr_value(key, value)
        if casted is not None:
            final_attrs[key] = casted

    return final_attrs


def _order_global_attrs(attrs: dict[str, Any]) -> OrderedDict[str, Any]:
    """Order global attributes according to IMOS canonical order."""
    ordered = OrderedDict()

    # Add attributes in canonical order
    for key in _GLOBAL_ATTR_ORDER:
        if key in attrs:
            ordered[key] = attrs[key]

    # Add any remaining attributes not in canonical order
    for key, value in attrs.items():
        if key not in ordered:
            ordered[key] = value

    return ordered


def _resolve_output_name_mode(metadata: dict[str, Any]) -> str:
    mode = str(metadata.get("output_name_mode", "")).strip().lower()
    if mode:
        return mode
    stage = str(metadata.get("output_stage", "")).strip().lower()
    if stage in {"proc_1", "proc_2", "imos_delivery"}:
        return "imos"
    return "internal"


def _resolve_version(metadata: dict[str, Any]) -> str:
    version = metadata.get("version")
    if not _is_blank(version):
        return _normalize_processing_version(version)

    stage = str(metadata.get("output_stage", "")).strip().lower()
    if stage == "proc_1":
        return "00"
    if stage == "proc_2":
        return "01"
    if stage == "imos_delivery":
        return "01"
    return "01"


def build_output_filename(metadata=None):
    """Build an internal or delivery filename from metadata."""
    metadata = metadata or {}
    output_name_mode = _resolve_output_name_mode(metadata)
    start_time = _parse_datetime(
        metadata.get("start_of_good_data")
        or metadata.get("time_coverage_start")
        or metadata.get("deploy_date")
    )
    if output_name_mode == "imos":
        version = _resolve_version(metadata)
        nominal_depth = metadata.get('nominal_inst_depth', metadata.get('depth', metadata.get('nominal_depth', 0)))
        return (
            f"IMOS_SRSALT_{_channel_token(metadata)}_"
            f"{start_time.strftime('%Y%m%dT%H%M%SZ')}_{_site_token(metadata.get('location'))}_"
            f"FV{version}_{_instrument_token(metadata.get('instrument', metadata.get('inst_type', 'AQD')))}"
            f"d{int(round(float(nominal_depth)))}m.nc"
        )

    return (
        f"{_site_token(metadata.get('location'))}_{start_time.strftime('%Y%m')}_"
        f"{_instrument_token(metadata.get('instrument', metadata.get('inst_type', 'AQD')))}_"
        f"{str(metadata.get('inst_id', metadata.get('serial', ''))).strip()}_"
        f"{_depth_token(metadata.get('depth', metadata.get('nominal_depth', '')))}.nc"
    )


def _resolve_output_path(output_path, metadata=None) -> Path:
    metadata = metadata or {}
    if _is_blank(output_path):
        directory = metadata.get("output_dir")
        if _is_blank(directory):
            raise ValueError("An output path or output_dir metadata value is required.")
        base_path = Path(str(directory)).expanduser()
    else:
        base_path = Path(str(output_path)).expanduser()

    if base_path.suffix.lower() == ".nc":
        resolved_path = base_path
    else:
        resolved_path = base_path / build_output_filename(metadata)

    if not resolved_path.is_absolute():
        resolved_path = (Path.cwd() / resolved_path).resolve()
    else:
        resolved_path = resolved_path.resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    return resolved_path


def _apply_variable_attrs_from_schema(
    dataset: xr.Dataset,
    instrument: str,
    schema_dir: str | None = None,
) -> xr.Dataset:
    """Apply variable attributes from instrument schema.

    For each variable in the dataset, look up its definition in the schema
    and apply the canonical attributes (units, long_name, standard_name, etc).
    
    Raises
    ------
    ValueError
        If instrument schema cannot be found or does not contain output_variables.
    """
    prepared = dataset.copy(deep=True)

    schema = load_instrument_schema(instrument, schema_dir=schema_dir)
    output_vars = schema.get("output_variables", {}) or {}
    
    if not output_vars:
        raise ValueError(f"Schema for {instrument} has no output_variables defined")

    for var_name, var_meta in output_vars.items():
        if var_name not in prepared.variables or not isinstance(var_meta, dict):
            continue

        # Apply attributes from schema with explicit coercion rules
        if "attributes" in var_meta and isinstance(var_meta["attributes"], dict):
            normalized_attrs: dict[str, Any] = {}
            for attr_name, attr_value in var_meta["attributes"].items():
                normalized_attrs[attr_name] = _coerce_var_attr_value(attr_name, attr_value)
            prepared[var_name].attrs.update(normalized_attrs)

    return prepared


def _apply_global_attrs_from_schema(
    dataset: xr.Dataset,
    metadata: dict[str, Any],
    instrument: str,
    schema_dir: str | None = None,
) -> xr.Dataset:
    """Apply global attributes from schema, merged with provided metadata.

    YAML is treated as the source of truth for the global attribute key set.
    Runtime values from metadata/dataset only fill blank (null/empty) YAML values.
    """
    prepared = dataset.copy(deep=True)
    time_values = _time_values_to_datetime(prepared["TIME"].values)
    if len(time_values) == 0:
        raise ValueError("Cannot write an empty dataset.")
    derived_start = pd.to_datetime(time_values.min())
    derived_end = pd.to_datetime(time_values.max())
    derived_start_text = "" if pd.isna(derived_start) else derived_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    derived_end_text = "" if pd.isna(derived_end) else derived_end.strftime("%Y-%m-%dT%H:%M:%SZ")

    attrs = dict(prepared.attrs)
    resolved = _schema_global_attrs(
        prepared,
        metadata,
        attrs,
        schema_dir,
        derived_start_text,
        derived_end_text,
    )

    prepared.attrs = _order_global_attrs(resolved)
    return prepared


def _build_encoding_from_schema(
    dataset: xr.Dataset,
    instrument: str,
    schema_dir: str | None = None,
) -> dict[str, Any]:
    """Build xarray encoding dict from instrument schema.
    
    For each variable in the dataset, look up its type in the schema and set
    the encoding dtype. This is robust and works for any instrument/schema.
    
    Parameters
    ----------
    dataset : xr.Dataset
        The dataset to encode
    instrument : str
        Instrument type for schema lookup
    schema_dir : str, optional
        Path to schemas directory
    
    Returns
    -------
    dict[str, Any]
        Encoding dict mapping variable names to dtype specifications
        
    Raises
    ------
    ValueError
        If instrument schema cannot be found or does not contain output_variables.
    """
    schema = load_instrument_schema(instrument, schema_dir=schema_dir)
    output_vars = schema.get("output_variables", {}) or {}
    
    if not output_vars:
        raise ValueError(f"Schema for {instrument} has no output_variables defined")
    
    encoding = {"TIME": {"dtype": "float64"}}
    
    # Map schema types to numpy dtype strings
    type_map = {
        "f8": "float64",
        "f4": "float32",
        "i4": "int32",
        "i2": "int16",
        "i1": "int8",
    }
    
    for var_name in dataset.data_vars:
        if var_name == "TIME":
            continue
        
        if var_name not in output_vars:
            continue
        
        var_meta = output_vars[var_name]
        if not isinstance(var_meta, dict):
            continue
        
        schema_type = var_meta.get("type", "")
        numpy_dtype = type_map.get(schema_type, schema_type)
        
        if numpy_dtype:
            encoding[var_name] = {"dtype": numpy_dtype}
    
    return encoding


def _prepare_dataset_for_write(
    dataset: xr.Dataset,
    metadata: dict[str, Any],
    instrument: str | None = None,
    schema_dir: str | None = None,
) -> tuple[xr.Dataset, dict[str, Any]]:
    """Prepare a dataset for writing to NetCDF.

    This applies variable attributes from schema, global attributes from schema 
    and metadata, normalizes time encoding, and sets data types based on schema.

    Parameters
    ----------
    dataset : xr.Dataset
        The dataset to prepare
    metadata : dict
        Metadata for global attributes and filename
    instrument : str
        Instrument type for schema lookup (required)
    schema_dir : str, optional
        Path to schemas directory
        
    Raises
    ------
    ValueError
        If instrument is missing or schema cannot be found.
    """
    if not instrument:
        raise ValueError("Instrument type is required for schema-driven writing")
    
    sanitized_dataset = _normalize_dataset_attrs_for_netcdf(dataset)

    # Apply variable attributes from schema
    prepared = _apply_variable_attrs_from_schema(sanitized_dataset, instrument, schema_dir=schema_dir)

    # Apply global attributes from schema
    prepared = _apply_global_attrs_from_schema(prepared, metadata, instrument, schema_dir=schema_dir)

    prepared = prepared.copy(deep=True)

    time_values = _time_values_to_datetime(prepared["TIME"].values)
    prepared = prepared.assign_coords(TIME=_to_days_since_1950(time_values))
    prepared["TIME"].attrs.update({"units": TIME_UNITS, "calendar": "gregorian"})

    # Build encoding from schema for all variables
    encoding = _build_encoding_from_schema(prepared, instrument, schema_dir)

    # CRITICAL FIX: Remove 'coordinates' from variable attributes to avoid xarray encoding conflict
    # The 'coordinates' attribute is handled by xarray's dimension coordinates system, not variable attrs
    for var_name in prepared.data_vars:
        if "coordinates" in prepared[var_name].attrs:
            del prepared[var_name].attrs["coordinates"]

    return prepared, encoding


def write_imos_file(dataset, output_path, metadata=None, instrument=None, schema_dir=None):
    """Write an IMOS-compliant NetCDF file.

    Applies schema-driven attributes to variables and global metadata before
    writing to disk.

    Parameters
    ----------
    dataset : xr.Dataset
        The dataset to write
    output_path : str or Path
        Destination path (file or directory)
    metadata : dict, optional
        Metadata for naming and attributes
    instrument : str
        Instrument type (e.g. "SBE37") for schema lookup (required)
    schema_dir : str, optional
        Path to schemas directory
        
    Raises
    ------
    KeyError
        If TIME variable is missing from dataset.
    ValueError
        If instrument is missing or schema cannot be found.
    """
    if "TIME" not in dataset:
        raise KeyError("TIME not found in dataset")

    metadata = dict(metadata or {})
    metadata = _normalize_metadata_for_netcdf(metadata)

    # Infer instrument from metadata if not explicitly provided
    if not instrument:
        instrument = metadata.get("inst_type", metadata.get("instrument", ""))
    
    if not instrument:
        raise ValueError("Instrument type is required (provide as parameter or in metadata)")

    resolved_output_path = _resolve_output_path(output_path, metadata)
    prepared_dataset, encoding = _prepare_dataset_for_write(
        dataset,
        metadata,
        instrument=instrument,
        schema_dir=schema_dir,
    )
    if resolved_output_path.exists():
        resolved_output_path.unlink()
    prepared_dataset.to_netcdf(resolved_output_path, encoding=encoding)
    return str(resolved_output_path)