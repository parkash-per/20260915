"""IMOS global attributes management for delivery compliance.

Provides helpers to load mandatory IMOS attributes from schema and apply
them to datasets before compliance checking and delivery publishing.
"""

from __future__ import annotations

from typing import Any

import xarray as xr

from ..config_manager import load_global_attributes


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
    
    # Start with mandatory attributes from schema
    new_attrs = load_imos_mandatory_attributes(schema_dir=schema_dir)
    
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
