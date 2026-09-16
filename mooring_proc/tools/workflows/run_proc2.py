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


def _reset_qc_variables_to_good(
    dataset: xr.Dataset,
    default_flag: int = 1,
) -> xr.Dataset:
    """Reset all QC variables to the default flag value (good data).
    
    For each *_quality_control variable in the dataset, set all values
    to the default flag (typically 1 = good data). This prepares the
    dataset for proc_2, where manual QC flags will override as needed.
    
    Parameters
    ----------
    dataset : xr.Dataset
        The dataset with QC variables
    default_flag : int, default 1
        Default QC flag value. 1 = Good_data in IMOS convention.
    
    Returns
    -------
    xr.Dataset
        Dataset with QC variables reset to default flag.
    """
    result = dataset.copy(deep=False)
    
    for var_name in result.data_vars:
        if not var_name.endswith("_quality_control"):
            continue
        
        qc_var = result[var_name]
        # Fill all QC values with default flag
        qc_data = np.full_like(qc_var.values, fill_value=default_flag, dtype=np.int8)
        result[var_name] = xr.DataArray(qc_data, dims=qc_var.dims, attrs=qc_var.attrs)
    
    return result


def run_proc2(config, instrument_id=None, input_dataset=None):
    """Run proc_2 workflow to produce final IMOS FV01 product with manual QC.
    
    proc_2 loads the proc_1 FV00 file from disk, resets QC variables to
    good data (flag=1), applies manual QC flags, and writes the final
    IMOS FV01 output with schema-driven attributes.
    
    Parameters
    ----------
    config : dict
        Configuration dict including manual_qc_flags or flag_windows
    instrument_id : str, optional
        Instrument deployment ID; resolved from config if not provided
    input_dataset : str or Path, optional
        Explicit path to proc_1 file; if not provided, resolves from metadata
    """
    metadata_source = _metadata_source(config)
    inst_deploy_id = _instrument_key(config, instrument_id)
    _, row, cfg, _ = get_instrument_context(
        metadata_source,
        inst_deploy_id,
        deployment_id=config.get("deployment_id"),
    )
    inst_type = _instrument_type(row)
    schema_dir = config.get("schema_dir")

    # Load proc_1 FV00 file
    if input_dataset is not None:
        candidate = Path(str(input_dataset)).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        if candidate.exists():
            proc_1_dataset = xr.open_dataset(candidate).load()
        else:
            raise FileNotFoundError(f"Input dataset not found: {candidate}")
    else:
        proc_1_dataset = _load_proc1_file(row)
    
    # Reset all QC variables to good data (flag=1) as baseline
    proc_1_with_reset_qc = _reset_qc_variables_to_good(proc_1_dataset, default_flag=1)
    
    # Apply manual QC flags (these will override the good-data defaults)
    manual_qc_flags = list(config.get("manual_qc_flags", config.get("flag_windows", [])) or [])
    proc_2_dataset = apply_qc_flag_windows(proc_1_with_reset_qc, manual_qc_flags)

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
            "depth": row.get("nominal_inst_depth", cfg.get("nominal_inst_depth", 0)),
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
