"""Publishing helpers for IMOS deliveries."""

from __future__ import annotations

from pathlib import Path

import xarray as xr

from .writer import build_output_filename, write_imos_file


def publish_delivery(delivery_path, destination, metadata=None, instrument: str | None = None, schema_dir: str | None = None):
    """Publish an existing NetCDF file with IMOS delivery naming."""
    metadata = dict(metadata or {})
    input_path: Path | None = None
    if isinstance(delivery_path, xr.Dataset):
        dataset = delivery_path.copy(deep=True)
    else:
        input_path = Path(str(delivery_path)).expanduser()
        if not input_path.is_absolute():
            input_path = (Path.cwd() / input_path).resolve()
        else:
            input_path = input_path.resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"Delivery input file not found: {input_path}")

        with xr.open_dataset(input_path) as opened_dataset:
            dataset = opened_dataset.load()

    destination_path = Path(str(destination)).expanduser()
    if destination_path.suffix.lower() != ".nc":
        destination_path = destination_path / build_output_filename({**metadata, "output_name_mode": "imos"})
    if not destination_path.is_absolute():
        destination_path = (Path.cwd() / destination_path).resolve()
    else:
        destination_path = destination_path.resolve()

    combined_metadata = dict(dataset.attrs)
    combined_metadata.update(metadata)
    combined_metadata["output_name_mode"] = "imos"
    if input_path is not None:
        combined_metadata.setdefault("source_file", input_path.name)
    source_file_value = combined_metadata.get("source_file", "")
    if str(source_file_value or "").strip():
        combined_metadata["source_file"] = Path(str(source_file_value)).name
    resolved_instrument = instrument or combined_metadata.get("inst_type") or combined_metadata.get("instrument")
    return write_imos_file(
        dataset,
        destination_path,
        metadata=combined_metadata,
        instrument=str(resolved_instrument) if resolved_instrument else None,
        schema_dir=schema_dir,
    )
