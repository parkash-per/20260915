import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from mooring_proc.tools.imos.attributes import apply_imos_mandatory_attributes
from mooring_proc.tools.imos.publisher import publish_delivery
from mooring_proc.tools.imos.writer import build_output_filename, write_imos_file
from mooring_proc.tools.workflows.run_imos_delivery import _delivery_metadata


def _sample_dataset() -> xr.Dataset:
    time = np.array(["2025-08-23T06:00:00", "2025-08-23T07:00:00"], dtype="datetime64[ns]")
    return xr.Dataset(
        data_vars={
            "TEMP": ("TIME", np.array([10.2, 10.4], dtype=np.float32)),
            "TEMP_quality_control": ("TIME", np.array([0, 0], dtype=np.int8)),
            "LATITUDE": xr.DataArray(-40.5),
            "LONGITUDE": xr.DataArray(145.25),
            "NOMINAL_DEPTH": xr.DataArray(52.0),
        },
        coords={"TIME": time},
        attrs={
            "source_file": "/tmp/input/raw/input_file.cnv",
            "output_stage": "proc_1",
        },
    )


class ImosMetadataTests(unittest.TestCase):
    def test_build_output_filename_prefers_mooring_channels(self):
        output_name = build_output_filename(
            {
                "output_name_mode": "imos",
                "output_stage": "proc_1",
                "version": "00",
                "start_of_good_data": "2025-08-23T06:00:00Z",
                "location": "BASJAS",
                "instrument": "SBE37",
                "depth": 52,
                "inst_channels": "TCS",
                "mooring_channels": "PTSUV",
            }
        )

        self.assertIn("_PTSUV_", output_name)
        self.assertNotIn("_TCS_", output_name)
        self.assertIn("_FV00_", output_name)

    def test_build_output_filename_falls_back_when_mooring_channels_is_blank(self):
        output_name = build_output_filename(
            {
                "output_name_mode": "imos",
                "version": "01",
                "start_of_good_data": "2025-08-23T06:00:00Z",
                "location": "BASJAS",
                "instrument": "SBE37",
                "depth": 52,
                "inst_channels": "TCS",
                "mooring_channels": "",
            }
        )

        self.assertIn("_TCS_", output_name)

    def test_write_imos_file_filters_internal_attrs_and_applies_schema_defaults(self):
        dataset = _sample_dataset()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "proc1.nc"
            written = write_imos_file(
                dataset,
                output_path,
                metadata={
                    "inst_type": "SBE37",
                    "instrument": "SBE37",
                    "version": "00",
                    "location": "BASJAS",
                    "deployment_id": "DEP001",
                    "mooring_channels": "PTSUV",
                    "inst_channels": "TCS",
                    "latitude": -40.5,
                    "longitude": 145.25,
                    "depth": 52,
                    "source_file": "/data/in/raw/input_file.cnv",
                    "output_stage": "proc_1",
                    "output_name_mode": "imos",
                    "output_dir": tmpdir,
                },
                instrument="SBE37",
            )
            self.assertEqual(Path(written).parent, Path(tmpdir))

            with xr.open_dataset(written) as opened:
                attrs = dict(opened.attrs)

        self.assertEqual(attrs["source_file"], "input_file.cnv")
        self.assertEqual(attrs["processing_version"], "00")
        self.assertEqual(attrs["mooring_channels"], "PTSUV")
        self.assertEqual(attrs["project"], "Integrated Marine Observing System (IMOS)")
        self.assertEqual(attrs["institution"], "SRS")
        self.assertIn("CF-1.6", attrs["Conventions"])
        self.assertIn("distribution_statement", attrs)
        self.assertIn("keywords", attrs)
        self.assertEqual(attrs["geospatial_lat_max"], -40.5)
        self.assertEqual(attrs["geospatial_lon_max"], 145.25)
        self.assertEqual(attrs["geospatial_vertical_max"], 52)
        self.assertNotIn("output_stage", attrs)
        self.assertNotIn("output_name_mode", attrs)
        self.assertNotIn("output_dir", attrs)

    def test_publish_delivery_uses_clean_dataset_and_consistent_filename(self):
        dataset = _sample_dataset()
        dataset.attrs["output_stage"] = "imos_delivery"
        written_path = None

        with tempfile.TemporaryDirectory() as tmpdir:
            written = publish_delivery(
                dataset,
                tmpdir,
                metadata={
                    "inst_type": "SBE37",
                    "instrument": "SBE37",
                    "version": "01",
                    "location": "BASJAS",
                    "deployment_id": "DEP001",
                    "mooring_channels": "PTSUV",
                    "inst_channels": "TCS",
                    "depth": 52,
                    "start_of_good_data": "2025-08-23T06:00:00Z",
                    "source_file": "/full/path/input_file.cnv",
                    "output_name_mode": "imos",
                    "output_stage": "imos_delivery",
                },
                instrument="SBE37",
            )
            written_path = Path(written)
            self.assertEqual(written_path.parent, Path(tmpdir))

            output_name = written_path.name
            with xr.open_dataset(written) as opened:
                attrs = dict(opened.attrs)

        self.assertIsNotNone(written_path)
        self.assertFalse(written_path.exists())

        self.assertIn("_PTSUV_", output_name)
        self.assertNotIn("_TCS_", output_name)
        self.assertEqual(attrs["source_file"], "input_file.cnv")
        self.assertEqual(attrs["processing_version"], "01")
        self.assertNotIn("output_stage", attrs)

    def test_apply_imos_mandatory_attributes_ignores_blank_coordinate_overrides(self):
        dataset = _sample_dataset()

        updated = apply_imos_mandatory_attributes(
            dataset,
            overrides={"latitude": "", "longitude": None},
        )

        self.assertEqual(updated.attrs["geospatial_lat_max"], -40.5)
        self.assertEqual(updated.attrs["geospatial_lon_max"], 145.25)
        self.assertEqual(updated.attrs["project"], "Integrated Marine Observing System (IMOS)")
        self.assertEqual(updated.attrs["institution"], "SRS")
        self.assertEqual(updated.attrs["geospatial_vertical_positive"], "down")

    def test_delivery_metadata_falls_back_to_inst_channels_when_mooring_channels_blank(self):
        dataset = _sample_dataset()
        dataset.attrs["mooring_channels"] = ""
        dataset.attrs["inst_channels"] = ""

        metadata = _delivery_metadata(
            pd.Series({"inst_type": "SBE37", "inst_id": "123", "location": "BASJAS", "mooring_channels": ""}),
            {"inst_channels": "TCS", "mooring_channels": "", "nominal_depth": 52, "location": "BASJAS"},
            "01",
            dataset,
        )

        self.assertEqual(metadata["inst_channels"], "TCS")
        self.assertEqual(metadata["mooring_channels"], "TCS")


if __name__ == "__main__":
    unittest.main()
