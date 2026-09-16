"""IMOS global attributes management for delivery compliance.

Provides helpers to load mandatory IMOS attributes from schema and apply
them to datasets before compliance checking and delivery publishing.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from ..config_manager import load_global_attributes


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none"}


def load_imos_mandatory_attributes(schema_dir: str | None = None) -> dict[str, str]:
    """Load mandatory IMOS global attributes from schema.
    
    Returns all attributes that MUST be present in delivery files
    according to global_attributes.yaml.
    
    Parameters
    ----------
    schema_dir : str, optional
        Path to schemas directory. If not provided, uses default location.
    
    Returns
    -------
    dict[str, str]
        Mapping of attribute name → default value from schema.
    """
    global_schema = load_global_attributes(schema_dir=schema_dir)
    mandatory = global_schema.get("mandatory_attributes", {}) or {}
    return dict(mandatory)


def load_imos_default_attributes(schema_dir: str | None = None) -> dict[str, str]:
    """Load default IMOS global attributes from schema.
    
    These are recommended defaults that may be overridden by deployment-specific
    values or config.
    
    Parameters
    ----------
    schema_dir : str, optional
        Path to schemas directory. If not provided, uses default location.
    
    Returns
    -------
    dict[str, str]
        Mapping of attribute name → default value from schema.
    """
    global_schema = load_global_attributes(schema_dir=schema_dir)
    defaults = global_schema.get("defaults", {}) or {}
    return dict(defaults)


def _dataset_scalar(dataset: xr.Dataset, variable_name: str) -> Any:
    if variable_name not in dataset.variables:
        return None
    value = np.asarray(dataset[variable_name].values).squeeze()
    if np.size(value) != 1:
        return None
    return value.item()


def load_imos_geospatial_attributes(
    dataset: xr.Dataset,
    *,
    overrides: dict[str, Any] | None = None,
    schema_dir: str | None = None,
) -> dict[str, Any]:
    """Load IMOS geospatial global attributes with dataset-derived values."""
    global_schema = load_global_attributes(schema_dir=schema_dir)
    geospatial = dict(global_schema.get("geospatial", {}) or {})
    aliases = {
        "positive": "geospatial_vertical_positive",
        "lat_max": "geospatial_lat_max",
        "lat_min": "geospatial_lat_min",
        "lon_max": "geospatial_lon_max",
        "lon_min": "geospatial_lon_min",
        "vertical_max": "geospatial_vertical_max",
        "vertical_min": "geospatial_vertical_min",
    }
    override_values = dict(overrides or {})
    latitude = None
    for value in (
        override_values.get("latitude"),
        dataset.attrs.get("latitude"),
        _dataset_scalar(dataset, "LATITUDE"),
    ):
        if not _is_blank(value):
            latitude = value
            break
    longitude = None
    for value in (
        override_values.get("longitude"),
        dataset.attrs.get("longitude"),
        _dataset_scalar(dataset, "LONGITUDE"),
    ):
        if not _is_blank(value):
            longitude = value
            break
    depth = None
    for value in (
        override_values.get("depth"),
        override_values.get("nominal_depth"),
        dataset.attrs.get("depth"),
        dataset.attrs.get("nominal_depth"),
        _dataset_scalar(dataset, "NOMINAL_DEPTH"),
    ):
        if not _is_blank(value):
            depth = value
            break
    derived_values = {
        "geospatial_lat_max": latitude,
        "geospatial_lat_min": latitude,
        "geospatial_lon_max": longitude,
        "geospatial_lon_min": longitude,
        "geospatial_vertical_max": depth,
        "geospatial_vertical_min": depth,
    }

    resolved = {}
    for key, value in geospatial.items():
        attr_key = aliases.get(key, key)
        resolved_value = derived_values.get(attr_key) if value is None else value
        if not _is_blank(resolved_value):
            resolved[attr_key] = resolved_value
    return resolved


def apply_imos_mandatory_attributes(
    dataset: xr.Dataset,
    *,
    overrides: dict[str, Any] | None = None,
    schema_dir: str | None = None,
) -> xr.Dataset:
    """Apply mandatory IMOS global attributes to a dataset.
    
    Loads all mandatory attributes from schema and applies them to the
    dataset. Existing dataset attributes are preserved unless explicitly
    overridden. Ensures delivery files have all required global attributes
    before compliance checking.
    
    Parameters
    ----------
    dataset : xr.Dataset
        The dataset to update with mandatory attributes.
    overrides : dict, optional
        Mapping of attribute name → value to override schema defaults.
        These take precedence over mandatory attributes from the schema.
    schema_dir : str, optional
        Path to schemas directory. If not provided, uses default location.
    
    Returns
    -------
    xr.Dataset
        Updated dataset with mandatory IMOS attributes applied.
        The original dataset is not mutated.
    
    Examples
    --------
    >>> ds = apply_imos_mandatory_attributes(
    ...     proc_2_dataset,
    ...     overrides={
    ...         "author": "Dr Jane Smith",
    ...         "institution": "CSIRO",
    ...     }
    ... )
    """
    prepared = dataset.copy(deep=True)
    
    # Start with schema-driven attributes from schema
    new_attrs = load_imos_mandatory_attributes(schema_dir=schema_dir)
    new_attrs.update(load_imos_default_attributes(schema_dir=schema_dir))
    new_attrs.update(load_imos_geospatial_attributes(prepared, overrides=overrides, schema_dir=schema_dir))
    
    # Merge in dataset's existing attributes (preserve non-mandatory values)
    existing = dict(prepared.attrs)
    for key, value in existing.items():
        if key not in new_attrs:  # Only preserve non-mandatory attributes
            new_attrs[key] = value
    
    # Apply overrides last (highest priority)
    if overrides:
        new_attrs.update(overrides)
    
    prepared.attrs = new_attrs
    return prepared


def get_attribute_overrides(
    config: dict[str, Any],
    inst_type: str = "",
    schema_dir: str | None = None,
) -> dict[str, str]:
    """Build deployment/instrument-specific attribute overrides.
    
    Combines deployment metadata and instrument-specific overrides
    with defaults from schema to create the final attribute mapping
    for delivery files.
    
    Parameters
    ----------
    config : dict
        Configuration dict containing optional keys:
        - delivery_global_attrs: dict of attribute overrides
        - delivery_global_attrs_by_instrument: dict of {instrument: overrides}
    inst_type : str, optional
        Instrument type (e.g. "SBE37") to look up instrument-specific overrides.
    schema_dir : str, optional
        Path to schemas directory. If not provided, uses default location.
    
    Returns
    -------
    dict[str, str]
        Mapping of attribute name → value with all overrides applied.
    """
    # Start with schema defaults
    overrides = load_imos_default_attributes(schema_dir=schema_dir)
    
    # Apply global delivery overrides from config
    global_overrides = config.get("delivery_global_attrs", {}) or {}
    if isinstance(global_overrides, dict):
        overrides.update(global_overrides)
    
    # Apply instrument-specific overrides
    if inst_type:
        by_inst = config.get("delivery_global_attrs_by_instrument", {}) or {}
        inst_overrides = by_inst.get(inst_type, by_inst.get(inst_type.lower(), {}))
        if isinstance(inst_overrides, dict):
            overrides.update(inst_overrides)
    
    return overrides
