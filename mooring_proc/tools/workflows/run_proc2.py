"""Instrument proc_2 workflow (manual QC on proc_1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ..config_manager import load_instrument_schema
from ..database_lookup import get_instrument_context, update_metadata_file_fields
from ..imos.writer import build_output_filename, write_imos_file
from ..qc.manual_flags import apply_qc_flag_windows, write_manual_qc_flags_txt


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
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_stage_file(stage_dir: Path, configured_name: Any) -> Path:
    if configured_name is not None and str(configured_name).strip():
        candidate = stage_dir / str(configured_name).strip()
        if candidate.exists():
            return candidate
    candidates = sorted(stage_dir.glob("*.nc"))
    if not candidates:
        raise FileNotFoundError(f"No NetCDF files found in {stage_dir}")
    return candidates[-1]


def _load_proc1_file(row) -> xr.Dataset:
    """Load the proc_1 FV00 file from disk.
    
    The proc_1 file is always read from the proc_1_path directory,
    either using the configured proc_1_file name or the latest *.nc file.
    """
    stage_dir = _stage_dir(row.get("proc_1_path"))
    dataset_path = _resolve_stage_file(stage_dir, row.get("proc_1_file"))
    with xr.open_dataset(dataset_path) as opened_dataset:
        return opened_dataset.load()


def _reconstruct_missing_qc_variables(
    dataset: xr.Dataset,
    instrument: str,
    schema_dir: str | None = None,
    default_flag: int = 1,
) -> xr.Dataset:
    """Reconstruct missing *_quality_control variables in a dataset.
    
    For each variable in the dataset, if the corresponding *_quality_control
    variable is missing, create it with the given default flag value.
    
    Parameters
    ----------
    dataset : xr.Dataset
        The dataset to augment (typically a loaded proc_1 FV00 file)
    instrument : str
        Instrument type (e.g. "SBE37") to look up schema
    schema_dir : str, optional
        Path to schemas directory; defaults to tools/schemas
    default_flag : int, default 1
        Default QC flag value to use when creating new QC variables.
        1 = Good_data in IMOS convention.
    
    Returns
    -------
    xr.Dataset
        New dataset with missing QC variables added.
    """
    schema = load_instrument_schema(instrument, schema_dir=schema_dir)
    output_vars = schema.get("output_variables", {}) or {}
    
    result = dataset.copy(deep=True)
    
    for var_name, var_meta in output_vars.items():
        if not var_name.endswith("_quality_control") or not isinstance(var_meta, dict):
            continue
        
        if var_name in result.variables:
            continue
        
        # Extract the base variable name (e.g. TEMP from TEMP_quality_control)
        base_var_name = var_name.removesuffix("_quality_control")
        
        # Only create QC variable if the base variable exists
        if base_var_name not in result.variables:
            continue
        
        # Get dimensions from the base variable
        base_var = result[base_var_name]
        dims = list(base_var.dims)
        
        # Create the QC variable filled with the default flag value
        qc_data = np.full(base_var.shape, fill_value=default_flag, dtype=np.int8)
        result[var_name] = xr.DataArray(qc_data, dims=dims)
        
        # Apply schema attributes if available
        if "attributes" in var_meta and isinstance(var_meta["attributes"], dict):
            result[var_name].attrs.update(var_meta["attributes"])
    
    return result


def run_proc2(config, instrument_id=None, schema_dir=None):
    """Run proc_2 workflow to produce final IMOS FV01 product with QC variables.
    
    proc_2 loads the proc_1 FV00 file from disk, reconstructs any missing
    *_quality_control variables, applies manual QC flags, and writes the final
    IMOS FV01 output with schema-driven attributes. This is the only product
    that will be compliance-checked and published as a deliverable.
    
    Parameters
    ----------
    config : dict
        Configuration dict including manual_qc_flags or flag_windows
    instrument_id : str, optional
        Instrument deployment ID; resolved from config if not provided
    schema_dir : str, optional
        Path to schemas directory; resolved from config if not provided
    """
    metadata_source = _metadata_source(config)
    inst_deploy_id = _instrument_key(config, instrument_id)
    _, row, cfg, _ = get_instrument_context(
        metadata_source,
        inst_deploy_id,
        deployment_id=config.get("deployment_id"),
    )
    inst_type = _instrument_type(row)
    schema_dir = schema_dir or config.get("schema_dir")

    # Load proc_1 FV00 file from disk
    proc_1_dataset = _load_proc1_file(row)
    
    # Reconstruct any missing QC variables from schema
    proc_1_with_qc = _reconstruct_missing_qc_variables(
        proc_1_dataset,
        inst_type,
        schema_dir=schema_dir,
        default_flag=1,
    )
    
    # Apply manual QC flags
    manual_qc_flags = list(config.get("manual_qc_flags", config.get("flag_windows", [])) or [])
    proc_2_dataset = apply_qc_flag_windows(proc_1_with_qc, manual_qc_flags)

    stage_metadata = {**cfg, **row.to_dict(), **config, **proc_2_dataset.attrs}
    stage_metadata.update(
        {
            "output_stage": "proc_2",
            "output_name_mode": "imos",
            "version": "01",
            "location": cfg.get("location", row.get("location", "")),
            "instrument": row.get("inst_type", inst_type),
            "inst_type": row.get("inst_type", inst_type),
            "inst_id": row.get("inst_id", ""),
            "depth": row.get("nominal_depth", cfg.get("nominal_depth", 0)),
            "start_of_good_data": proc_2_dataset.attrs.get(
                "time_coverage_start",
                row.get("time_coverage_start", row.get("deploy_date")),
            ),
            "output_dir": row.get("proc_2_path"),
        }
    )

    proc_2_dir = _stage_dir(row.get("proc_2_path"))
    output_path = proc_2_dir / build_output_filename(stage_metadata)
    
    # Write proc_2 FV01 file with schema-driven attributes
    proc_2_output = write_imos_file(
        proc_2_dataset,
        output_path,
        metadata=stage_metadata,
        instrument=inst_type,
        schema_dir=schema_dir,
    )
    manual_qc_log = write_manual_qc_flags_txt(manual_qc_flags, proc_2_output)
    update_metadata_file_fields(metadata_source, inst_deploy_id, {"proc_2_file": Path(proc_2_output).name})
    return {
        "metadata_row": row,
        "dataset": proc_2_dataset,
        "output_path": proc_2_output,
        "manual_qc_log": str(manual_qc_log),
    }
