"""Shared IMOS delivery workflow (FV01-only compliance gate)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import xarray as xr

from ..config_manager import load_global_attributes
from ..database_lookup import get_instrument_context, update_metadata_file_fields
from ..imos.attributes import apply_imos_mandatory_attributes, get_attribute_overrides
from ..imos.postprocess import apply_postprocess
from ..imos.publisher import publish_delivery
from ..validation.compliance_check import run_compliance_check


def _metadata_source(config: dict[str, Any]):
    for key in ("metadata_table", "metadata_csv", "metadata_source"):
        if config.get(key) is not None:
            return config[key]
    raise ValueError("config must provide metadata_table, metadata_csv, or metadata_source.")


def _instrument_key(config: dict[str, Any], instrument_id: Any):
    if instrument_id is not None:
        return instrument_id
    for key in ("inst_deploy_ID", "instrument_id"):
        if config.get(key) is not None:
            return config[key]
    raise ValueError("An inst_deploy_ID or instrument_id is required.")


_SUPPORTED = {"AQD", "SBE26", "SBE37", "RBRQ", "SIG500"}


def _instrument_type(row: Any) -> str:
    inst = str(row.get("inst_type", "")).strip().upper()
    if inst not in _SUPPORTED:
        raise NotImplementedError(f"Unsupported instrument '{inst}'.")
    return inst


def _stage_dir(path_value: Any) -> Path:
    return Path(str(path_value or "")).expanduser().resolve()


def _resolve_stage_file(stage_dir: Path, configured_name: Any, *, required: bool = True) -> Path | None:
    """Resolve a stage file (proc_1, proc_2, etc.) from a directory.
    
    Parameters
    ----------
    stage_dir : Path
        The directory to search
    configured_name : Any
        The configured filename (or None)
    required : bool
        If True, raise error if file not found. If False, return None.
    
    Returns
    -------
    Path | None
        Path to the file if found, or None if not required and not found.
    """
    if configured_name is None:
        candidate = None
    else:
        candidate = stage_dir / str(configured_name)
    
    if candidate and candidate.exists():
        return candidate
    
    if required:
        raise FileNotFoundError(f"Stage file not found in {stage_dir}: {configured_name}")
    return None


# Attributes that are workflow-internal and must be removed before delivery
_INTERMEDIATE_ONLY_ATTRS = {
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


def _get_imos_compliant_attributes(schema_dir: str | None = None) -> set[str]:
    """Load the set of IMOS-compliant global attributes from schema.
    
    This defines which attributes are allowed in the final delivery file.
    """
    global_schema = load_global_attributes(schema_dir=schema_dir)
    allowed = set()
    
    # Mandatory attributes are always allowed
    if "mandatory_attributes" in global_schema:
        allowed.update(global_schema["mandatory_attributes"].keys())
    
    # Default attributes are allowed
    if "defaults" in global_schema:
        allowed.update(global_schema["defaults"].keys())
    
    # Geospatial attributes are allowed
    if "geospatial" in global_schema:
        allowed.update(global_schema["geospatial"].keys())
    
    # Standard deployment/instrument attributes
    allowed.update({
        "instrument",
        "serial",
        "deployment_id",
        "location",
        "mooring_channels",
        "time_coverage_start",
        "time_coverage_end",
        "processing_version",
        "Conventions",
        "title",
        "abstract",
        "keywords",
        "standard_name_vocabulary",
    })
    
    return allowed


def _sanitise_delivery_dataset(dataset: xr.Dataset, schema_dir: str | None = None) -> xr.Dataset:
    """Remove intermediate-only attributes and normalize for IMOS compliance.
    
    This strips all workflow-internal attributes, ensuring only IMOS-compliant
    attributes remain before compliance checking and publication.
    
    Parameters
    ----------
    dataset : xr.Dataset
        The proc_2 FV01 dataset to sanitize
    schema_dir : str, optional
        Path to schemas directory for loading compliance rules
    
    Returns
    -------
    xr.Dataset
        Cleaned dataset with only IMOS-compliant attributes.
    """
    cleaned = dataset.copy(deep=True)
    
    # Remove all intermediate-only attributes
    for key in list(cleaned.attrs.keys()):
        if key in _INTERMEDIATE_ONLY_ATTRS:
            cleaned.attrs.pop(key, None)
    
    # Optionally validate against allowed attributes (currently permissive)
    # In the future, this could enforce a strict whitelist
    
    source_file_value = cleaned.attrs.get("source_file", "")
    if isinstance(source_file_value, str) and source_file_value:
        cleaned.attrs["source_file"] = Path(source_file_value).name
    
    return cleaned


def _delivery_metadata(row, cfg, version: str, dataset: xr.Dataset, schema_dir: str | None = None) -> dict[str, Any]:
    """Build metadata dict for the final delivery file.
    
    Uses the sanitized proc_2 dataset, removes intermediate attributes, and constructs
    the metadata needed for the delivery output filename and attributes.
    """
    attrs = dict(dataset.attrs)
    
    # Remove intermediate-only attributes
    for key in _INTERMEDIATE_ONLY_ATTRS:
        attrs.pop(key, None)
    
    # Normalize source_file to just the filename (not full path)
    source_file_value = attrs.get("source_file", "")
    if isinstance(source_file_value, str) and source_file_value:
        attrs["source_file"] = Path(source_file_value).name

    depth_value = attrs.get("NOMINAL_DEPTH", row.get("nominal_depth", cfg.get("nominal_depth", 0)))
    if "NOMINAL_DEPTH" in dataset.variables:
        depth_value = float(dataset["NOMINAL_DEPTH"].values)
    
    return {
        **cfg,
        **row.to_dict(),
        **attrs,
        "output_name_mode": "imos",
        "version": version,
        "location": cfg.get("location", row.get("location", "")),
        "instrument": row.get("inst_type", "AQD"),
        "inst_type": row.get("inst_type", "AQD"),
        "inst_id": row.get("inst_id", ""),
        "depth": depth_value,
        "start_of_good_data": attrs.get("time_coverage_start", row.get("time_coverage_start", row.get("deploy_date"))),
        "time_coverage_start": attrs.get("time_coverage_start", row.get("time_coverage_start", row.get("deploy_date"))),
        "time_coverage_end": attrs.get("time_coverage_end", row.get("time_coverage_end", row.get("recovery_date"))),
        "inst_channels": attrs.get("inst_channels", cfg.get("inst_channels", row.get("inst_channels", row.get("mooring_channels", "")))),
        "mooring_channels": attrs.get("mooring_channels", cfg.get("mooring_channels", row.get("mooring_channels", ""))),
    }


def run_imos_delivery(config, instrument_id=None, input_dataset=None):
    """Compliance gate for FV01 delivery.
    
    This is the final step before publication. It:
    1. Loads the proc_2 FV01 file
    2. Applies mandatory IMOS global attributes from schema
    3. Removes all intermediate-only attributes
    4. Runs compliance checks
    5. If valid, publishes to the IMOS deliverables directory
    6. Updates metadata tracking
    
    Only the final FV01 product is published; proc_1 FV00 is not delivered.
    
    Parameters
    ----------
    config : dict
        Configuration including schema_dir and delivery paths
    instrument_id : str, optional
        Instrument deployment ID; resolved from config if not provided
    input_dataset : str or Path, optional
        Explicit path to proc_2 file; if not provided, resolves from metadata
    """
    metadata_source = _metadata_source(config)
    inst_deploy_id = _instrument_key(config, instrument_id)
    _, row, cfg, _ = get_instrument_context(
        metadata_source,
        inst_deploy_id,
        deployment_id=config.get("deployment_id"),
    )
    inst_type = _instrument_type(row)

    final_dataset_path = None
    if input_dataset is not None:
        candidate = Path(str(input_dataset)).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if candidate.exists():
            final_dataset_path = candidate

    if final_dataset_path is None:
        proc_2_path = _resolve_stage_file(_stage_dir(row.get("proc_2_path")), row.get("proc_2_file"), required=False)
        if proc_2_path is None:
            raise ValueError(
                "Final delivery requires a valid proc_2 FV01 file. Run proc_2 first and confirm the metadata row points to a proc_2 output."
            )
        final_dataset_path = proc_2_path

    delivery_dir = _stage_dir(row.get("imos_deliverables_path", row.get("imos_path", "")))
    attr_overrides = get_attribute_overrides(config, inst_type=inst_type, schema_dir=config.get("schema_dir"))
    schema_dir = config.get("schema_dir")

    # Load proc_2 FV01 file and apply delivery-specific overrides
    with xr.open_dataset(final_dataset_path) as ds_final:
        proc_2_ds = apply_postprocess(ds_final.load(), global_attr_overrides=attr_overrides)

    # Apply mandatory IMOS global attributes from schema
    proc_2_ds = apply_imos_mandatory_attributes(
        proc_2_ds,
        overrides=attr_overrides,
        schema_dir=schema_dir,
    )

    # Sanitize: remove all intermediate-only attributes before validation
    final_dataset_for_validation = _sanitise_delivery_dataset(proc_2_ds, schema_dir=schema_dir)
    
    # Run compliance check on the cleaned dataset
    run_compliance_check(
        final_dataset_for_validation,
        schema={"instrument": inst_type, "schema_dir": schema_dir},
    )

    # Build final metadata for the output filename and attributes
    final_metadata = _delivery_metadata(row, cfg, "01", final_dataset_for_validation, schema_dir=schema_dir) | attr_overrides
    
    # Final cleanup: ensure no intermediate attributes in the metadata dict itself
    final_metadata = {k: v for k, v in final_metadata.items() if k not in _INTERMEDIATE_ONLY_ATTRS}
    final_metadata["output_name_mode"] = "imos"
    final_metadata["version"] = "01"

    # Publish the FV01 output to delivery directory
    fv01_output = publish_delivery(
        final_dataset_for_validation,
        delivery_dir,
        metadata=final_metadata,
        instrument=inst_type,
        schema_dir=schema_dir,
    )

    # Update metadata tracking
    update_metadata_file_fields(
        metadata_source,
        inst_deploy_id,
        {"imos_deliverables_file": Path(fv01_output).name},
    )
    
    return {
        "metadata_row": row,
        "proc_1_delivery": None,
        "proc_2_delivery": fv01_output,
        "imos_deliverables_file": Path(fv01_output).name,
    }
