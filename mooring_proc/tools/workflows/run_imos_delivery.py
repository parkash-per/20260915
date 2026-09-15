"""Shared IMOS delivery workflow (proc_1 -> FV00, proc_2 -> FV01)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import xarray as xr

from ..database_lookup import get_instrument_context, update_metadata_file_fields
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
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_stage_file(stage_dir: Path, configured_name: Any, *, required: bool = True) -> Path | None:
    if configured_name is not None and str(configured_name).strip():
        candidate = stage_dir / str(configured_name).strip()
        if candidate.exists():
            return candidate
    candidates = sorted(stage_dir.glob("*.nc"))
    if not candidates and required:
        raise FileNotFoundError(f"No NetCDF files found in {stage_dir}")
    if not candidates:
        return None
    return candidates[-1]


def _delivery_attr_overrides(config: dict[str, Any], inst_type: str) -> dict[str, Any]:
    overrides = dict(config.get("delivery_global_attrs", {}) or {})
    by_inst = config.get("delivery_global_attrs_by_instrument", {}) or {}
    inst_overrides = by_inst.get(inst_type, by_inst.get(inst_type.lower(), {}))
    if isinstance(inst_overrides, dict):
        overrides.update(inst_overrides)
    return overrides


_INTERMEDIATE_ONLY_ATTRS = {
    "proc_1_file",
    "proc_2_file",
    "proc_1_path",
    "proc_2_path",
    "input_file_path",
    "source_file",
    "output_dir",
    "manual_qc_flags",
    "flag_windows",
}


def _sanitise_delivery_dataset(dataset: xr.Dataset) -> xr.Dataset:
    cleaned = dataset.copy(deep=True)
    for key in sorted(_INTERMEDIATE_ONLY_ATTRS & set(cleaned.attrs.keys())):
        cleaned.attrs.pop(key, None)
    cleaned.attrs.setdefault("output_stage", "imos_delivery")
    cleaned.attrs.setdefault("output_name_mode", "imos")
    cleaned.attrs.setdefault("version", "01")
    return cleaned


def _delivery_metadata(row, cfg, version: str, input_path: Path) -> dict[str, Any]:
    with xr.open_dataset(input_path) as opened_dataset:
        dataset = opened_dataset.load()

    attrs = dict(dataset.attrs)
    for key in _INTERMEDIATE_ONLY_ATTRS:
        attrs.pop(key, None)

    depth_value = attrs.get("NOMINAL_DEPTH", row.get("nominal_depth", cfg.get("nominal_depth", 0)))
    if "NOMINAL_DEPTH" in dataset.variables:
        depth_value = float(dataset["NOMINAL_DEPTH"].values)
    return {
        **cfg,
        **row.to_dict(),
        **attrs,
        "output_name_mode": "imos",
        "output_stage": "imos_delivery",
        "version": version,
        "location": cfg.get("location", row.get("location", "")),
        "instrument": row.get("inst_type", "AQD"),
        "inst_type": row.get("inst_type", "AQD"),
        "inst_id": row.get("inst_id", ""),
        "depth": depth_value,
        "start_of_good_data": attrs.get("time_coverage_start", row.get("time_coverage_start", row.get("deploy_date"))),
        "time_coverage_start": attrs.get("time_coverage_start", row.get("time_coverage_start", row.get("deploy_date"))),
        "time_coverage_end": attrs.get("time_coverage_end", row.get("time_coverage_end", row.get("recovery_date"))),
        "inst_channels": attrs.get("mooring_channels", cfg.get("inst_channels", row.get("mooring_channels", ""))),
        "mooring_channels": attrs.get("mooring_channels", cfg.get("mooring_channels", row.get("mooring_channels", ""))),
    }


def run_imos_delivery(config, instrument_id=None, input_dataset=None):
    """Validate and publish only the final FV01 IMOS product."""
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
    attr_overrides = _delivery_attr_overrides(config, inst_type)
    schema_dir = config.get("schema_dir")

    with xr.open_dataset(final_dataset_path) as ds_final:
        proc_2_ds = apply_postprocess(ds_final.load(), global_attr_overrides=attr_overrides)

    final_dataset_for_validation = _sanitise_delivery_dataset(proc_2_ds)
    run_compliance_check(
        final_dataset_for_validation,
        schema={"instrument": inst_type, "schema_dir": schema_dir},
    )

    final_metadata = _delivery_metadata(row, cfg, "1", final_dataset_path) | attr_overrides
    final_metadata = {k: v for k, v in final_metadata.items() if k not in _INTERMEDIATE_ONLY_ATTRS}
    final_metadata["output_name_mode"] = "imos"
    final_metadata["output_stage"] = "imos_delivery"
    final_metadata["version"] = "01"

    for stale_file in delivery_dir.glob("*.nc"):
        if "FV00" in stale_file.name and stale_file.name != Path(final_metadata.get("source_file", "")).name:
            stale_file.unlink()

    fv01_output = publish_delivery(final_dataset_path, delivery_dir, metadata=final_metadata)

    for stale_file in delivery_dir.glob("*.nc"):
        if "FV00" in stale_file.name and stale_file.name != Path(fv01_output).name:
            stale_file.unlink()

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
