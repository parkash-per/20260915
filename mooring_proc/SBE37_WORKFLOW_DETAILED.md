# SBE37 Processing Workflow - Detailed Explanation

This document traces the complete SBE37 data processing pipeline from raw file through proc_1 → proc_2 → IMOS delivery, showing where code is called, what inputs are required, and how data flows between stages.

---

## Overview: Three Processing Stages

| Stage | Input | Output | Purpose |
|-------|-------|--------|---------|
| **Proc_1 (FV00)** | Raw SBE37 ASCII file | IMOS-formatted NetCDF | Parse, validate, trim to deployment window |
| **Proc_2 (FV01)** | Proc_1 FV00 file | IMOS FV01 with manual QC | Apply manual QC flags, refine product |
| **IMOS Delivery** | Proc_2 FV01 file | Final deliverable | Compliance check, archive staging |

---

# STAGE 1: PROC_1 (FV00) — Parse & Trim

## User Action: Setup in Notebook

**File:** `mooring_proc/sbe37_pipeline.ipynb`

### Cell 1: Imports
```python
from tools.workflows.run_proc1 import run_proc1
from tools.parsers.read_sbe37 import read_sbe37
from tools.database_lookup import get_instrument_context
```
**What it does:** Imports the workflow functions needed for SBE37 processing.

---

### Cell 2: Set Working Directory
```python
working_directory = "/datasets/work/oa-srsalt/work/preqa/SWOT/cal_val/jason_calval/all_mooring_data"
os.chdir(working_directory)
```
**What it does:** Sets the base path for relative file lookups.

---

### Cell 3: Set Permissions
```python
os.umask(0o002)  # Sets file permissions to 664 (-rw-rw-r--)
```
**What it does:** Ensures output files are group-writable for team access.

---

### Cell 4: Locate Instrument — REQUIRED INPUTS
```python
inst_deploy_id = "275"      # Required: deployment ID from metadata CSV
instrument = "SBE37"         # Required: instrument type (used to select parser)
proc1_source_path = None     # Optional: override raw file location
```

**Inputs required from user:**
- `inst_deploy_id` — unique deployment identifier (find via `inst_deploy_id_finder.ipynb`)
- `instrument` — must be "SBE37"
- `proc1_source_path` — path to raw SBE37 file (if None, auto-discovered from metadata)

---

### Cell 5: Build Workflow Config
```python
def build_workflow_config():
    metadata_csv = str(database_lookup.DEFAULT_METADATA_CSV_PATH)  # Usually: metadata.csv
    return {
        "metadata_csv": metadata_csv,
        "metadata_source": metadata_csv,
        "inst_deploy_ID": inst_deploy_id,
        "instrument": instrument,
        "manual_qc_flags": list(globals().get("manual_qc_flags", [])),  # Empty for proc_1
    }
```

**What it does:** Bundles configuration parameters for the workflow functions.

---

### Cell 6: ID Lookup — Validates Setup
```python
selected_metadata_row, selected_metadata_cfg, _ = database_lookup.get_instrument_context(
    metadata_csv,
    inst_deploy_id,
    deployment_id=None,
)
```

**Calls:** `tools/database_lookup.py → get_instrument_context()`

**What it does:**
- Queries metadata CSV for the deployment row matching `inst_deploy_id`
- Resolves:
  - `time_coverage_start` / `time_coverage_end` (deployment window)
  - `proc_1_path` (output directory)
  - `inst_type`, `inst_id`, `location`, `nominal_depth`, etc.

**Returns:** Row dict with all deployment metadata

**If lookup fails:** User is directed to `inst_deploy_id_finder.ipynb` to find the correct ID.

---

### Cell 7: Inspect Source File
```python
proc1_source_preview = read_sbe37(proc1_source_path, config={"metadata_row": selected_metadata_row.to_dict()})
proc1_source_path = proc1_source_preview["input_path"]
proc1_source_frame = proc1_source_preview["dataframe"]
```

**Calls:** `tools/parsers/read_sbe37.py → read_sbe37()`

**What it does:**
- Reads raw SBE37 ASCII file
- Parses columns, converts timestamps, applies calibration coefficients
- Returns dataframe preview so user can verify:
  - Resolved file path
  - Data start/end timestamps
  - Comparison with deployment window

**Returns:** Dict with:
- `input_path` — resolved full path to SBE37 file
- `dataframe` — pandas DataFrame with columns [TIME, TEMP, CNDC, PSAL, PRES_REL, DEPTH, etc.]
- `dataset` — xarray Dataset (used internally by parser)

**Example output:**
```
Resolved source path: /data/raw/SBE37/deploy275_2025-08-20.hex
Source start timestamp: 2025-08-20T10:30:45Z
Source end timestamp: 2026-05-30T14:15:20Z
Deployment window start: 2025-08-20T11:00:00Z
Deployment window end: 2026-05-30T12:00:00Z
```

---

## User Action: Trim Window (Optional Override)

### Cell 8: Set Time Bounds (Optional)
```python
proc1_time_start_override = None   # Leave as None to use deployment metadata
proc1_time_end_override = None     # Or set to custom ISO 8601 timestamp
```

**What it does:** Allows user to trim to a subset of the deployment window (e.g., if instrument failed early).

---

## The Main Workflow: run_proc1()

### Cell 9: Execute Proc_1
```python
workflow_config = build_workflow_config()
proc1_config = dict(workflow_config)

if proc1_time_start_override not in (None, ""):
    proc1_config["time_coverage_start"] = str(proc1_time_start_override)
if proc1_time_end_override not in (None, ""):
    proc1_config["time_coverage_end"] = str(proc1_time_end_override)

proc1_result = run_proc1(proc1_config, source_path=proc1_source_path)
```

**Calls:** `tools/workflows/run_proc1.py → run_proc1(config, source_path)`

---

## Inside run_proc1() — Step-by-Step

**File:** `mooring_proc/tools/workflows/run_proc1.py`

### Step 1: Resolve Metadata & Instrument
```python
metadata_source = config["metadata_source"]  # e.g., "metadata.csv"
inst_deploy_id = config["inst_deploy_ID"]

_, row, cfg, _ = get_instrument_context(
    metadata_source,
    inst_deploy_id,
    deployment_id=config.get("deployment_id"),
)

inst_type = row["inst_type"]  # "SBE37"
parser = _PARSERS[inst_type]  # read_sbe37 function
```

**What it does:**
- Fetches the metadata row again (validates it exists)
- Selects the appropriate parser (for SBE37: `read_sbe37`)

---

### Step 2: Parse Raw File
```python
parsed = parser(source_path, config={"metadata_row": row.to_dict()})
dataset = parsed["dataset"]  # xarray.Dataset
```

**Calls:** `read_sbe37(source_path, config=...)`

**What read_sbe37() does:**
1. Opens raw SBE37 ASCII file
2. Parses header (calibration coefficients, metadata)
3. Reads data rows
4. Converts columns to IMOS-standard names:
   - `t090C` → `TEMP`
   - `c0S0x2Fm` → `CNDC`
   - `sal00` → `PSAL`
   - `prdM` → `PRES_REL`
   - etc.
5. Converts time from SBE serial format to pandas datetime
6. Creates xarray Dataset with:
   - Coordinate: `TIME` (datetime64)
   - Data vars: `TEMP`, `CNDC`, `PSAL`, `PRES_REL`, `DEPTH`, etc.
   - Metadata: instrument serial, location, latitude, longitude

---

### Step 3: Resolve Time Bounds
```python
start_time, end_time = _resolve_time_bounds(row, config)
# Priority:
# 1. Override from config (if user set proc1_time_*_override)
# 2. Metadata row (deployment window)
# 3. raise error if missing
```

**What it does:**
- Determines which time window to trim to
- Validates both are datetime64

**Example:**
```python
start_time = 2025-08-20T11:00:00
end_time = 2026-05-30T12:00:00
```

---

### Step 4: Build Metadata Bundle
```python
stage_metadata = {
    **cfg,                           # Global config (location, author, etc.)
    **row.to_dict(),                 # Deployment row (inst_id, lat/lon, etc.)
    **config,                        # User config (manual_qc_flags, etc.)
    "output_stage": "proc_1",
    "output_name_mode": "imos",
    "version": "00",                 # FV00 version code
    "location": row.get("location"),
    "instrument": row.get("inst_type"),
    "inst_id": row.get("inst_id"),
    "depth": row.get("nominal_depth"),
    "start_of_good_data": start_time,
    "time_coverage_start": start_time.isoformat(),
    "time_coverage_end": end_time.isoformat(),
    "output_dir": row.get("proc_1_path"),  # e.g., "/output/proc_1"
}
```

**What it does:** Merges all metadata needed for:
- Generating the output filename
- Setting NetCDF global attributes
- Updating the metadata CSV later

---

### Step 5: Generate Output Filename
```python
output_name = build_output_filename(stage_metadata)
# Returns: IMOS_SRSALT_275_20250820T110000Z_BASSSTR_FV00_SBE37d25m.nc
```

**Calls:** `tools/imos/writer.py → build_output_filename(metadata)`

**Naming convention (IMOS):**
```
IMOS_SRSALT_{channel}_{timestamp}_{location}_FV{version}_{instrument}d{depth}m.nc
```

- `channel` — from `inst_channels` or `mooring_channels` (e.g., "275")
- `timestamp` — deployment start time (YYYYMMDDTHHMMSSZ)
- `location` — site name without spaces (e.g., "BASSSTR")
- `FV{version}` — "FV00" for proc_1 (FV01 for proc_2)
- `instrument` — uppercase, no spaces (e.g., "SBE37")
- `depth` — rounded nominal depth in meters (e.g., "25m")

---

### Step 6: Apply QC Flags for Deployment Window
```python
qc_vars = [name for name in dataset.data_vars if name.endswith("_quality_control")]
deployment_windows = build_qc_windows(
    dataset,
    {
        "row": row.to_dict(),
        "time_coverage_start": start_time,
        "time_coverage_end": end_time,
        "flag": 4,  # bad_data
        "qc_vars": qc_vars or None,
        "comment": "outside deployment window",
    },
)
dataset_with_qc = apply_qc_flag_windows(dataset, deployment_windows)
```

**What it does:**
- For any data OUTSIDE the deployment window, sets QC flags to 4 (bad_data)
- This marks pre-deployment and post-recovery data as invalid
- QC flag variables (e.g., `TEMP_quality_control`) are created if missing

---

### Step 7: Trim to Deployment Window
```python
trimmed_dataset = dataset_with_qc.sel(TIME=slice(start_time, end_time))
```

**What it does:** Keeps only data within the deployment window.

---

### Step 8: Ensure QC Variables Exist
```python
proc_1_dataset = _ensure_qc_variables(
    trimmed_dataset,
    inst_type,      # "SBE37"
    schema_dir=None,
    default_flag=0, # No QC applied yet in proc_1
)
```

**Calls:** `_ensure_qc_variables(dataset, instrument, default_flag=0)`

**What it does:**
1. Loads the SBE37 schema from `tools/schemas/sbe37_schema.yaml`
2. Iterates through `output_variables` in the schema
3. For each variable ending in `_quality_control` (e.g., `TEMP_quality_control`):
   - If the base variable exists (e.g., `TEMP`) but QC var doesn't, creates it
   - Fills with the default flag value (0 = no QC applied)
   - Applies QC variable attributes from schema (long_name, standard_name, etc.)

**Result:** Dataset now has:
- `TEMP`, `TEMP_quality_control`
- `CNDC`, `CNDC_quality_control`
- `PSAL`, `PSAL_quality_control`
- `PRES_REL`, `PRES_REL_quality_control`
- `DEPTH`, `DEPTH_quality_control`
- All initially flagged as 0 (no QC applied)

---

### Step 9: Write to NetCDF with Schema-Driven Attributes
```python
proc_1_output = write_imos_file(
    proc_1_dataset,
    output_path,          # e.g., /output/proc_1/IMOS_SRSALT_275_....nc
    metadata=stage_metadata,
    instrument=inst_type,  # "SBE37"
    schema_dir=None,
)
```

**Calls:** `tools/imos/writer.py → write_imos_file(dataset, path, metadata, instrument)`

---

## Inside write_imos_file() — NetCDF Writing

**File:** `mooring_proc/tools/imos/writer.py`

### Step 9a: Validate Inputs
```python
if "TIME" not in dataset:
    raise KeyError("TIME not found in dataset")

if not instrument:
    raise ValueError("Instrument type is required")
```

### Step 9b: Load Schema
```python
schema = load_instrument_schema("SBE37", schema_dir=None)
# Returns dict with:
# - instrument: "SBE37"
# - output_variables: {
#     "TIME": {"type": "f8", "attributes": {...}},
#     "TEMP": {"type": "f4", "attributes": {"units": "degrees_Celsius", ...}},
#     "CNDC": {"type": "f4", "attributes": {"units": "S m-1", ...}},
#     ...
#   }
```

**File location:** `mooring_proc/tools/schemas/sbe37_schema.yaml`

### Step 9c: Apply Variable Attributes from Schema
```python
for var_name, var_meta in schema["output_variables"].items():
    if var_name not in dataset.variables:
        continue
    
    for attr_name, attr_value in var_meta["attributes"].items():
        dataset[var_name].attrs[attr_name] = attr_value
```

**What it does:**
- For each variable in schema's `output_variables`:
  - If variable exists in dataset, apply all attributes from schema
  - Attributes include: `units`, `long_name`, `standard_name`, `valid_min`, `valid_max`, etc.

**Example for CNDC:**
```yaml
CNDC:
  type: "f4"
  dimensions: ["TIME"]
  attributes:
    units: "S m-1"
    long_name: "sea_water_electrical_conductivity"
    standard_name: "sea_water_electrical_conductivity"
    valid_min: 0.0
    valid_max: 50000.0
```

Result in NetCDF:
```
CNDC:
    long_name: sea_water_electrical_conductivity
    standard_name: sea_water_electrical_conductivity
    units: S m-1
    valid_min: 0.0
    valid_max: 50000.0
```

### Step 9d: Apply Global Attributes from Schema
```python
global_schema = load_global_attributes(schema_dir=None)
# Returns dict with:
# - mandatory_attributes: {project, Conventions, title, ...}
# - defaults: {author, institution, ...}
# - geospatial: {geospatial_vertical_positive, ...}

# Merge with runtime values
runtime_values = {
    "date_created": "2026-09-16T08:00:00Z",
    "history": "Created 2026-09-16T08:00:00Z",
    "geospatial_lat_min": -43.5,
    "geospatial_lat_max": -43.5,
    ...
}

# Final global attributes applied to dataset
```

**File location:** `mooring_proc/tools/schemas/global_attributes.yaml`

### Step 9e: Build Encoding from Schema
```python
encoding = _build_encoding_from_schema(dataset, "SBE37", schema_dir=None)
# Returns:
# {
#     "TIME": {"dtype": "float64"},
#     "TEMP": {"dtype": "float32"},
#     "CNDC": {"dtype": "float32"},
#     "PSAL": {"dtype": "float32"},
#     "PRES_REL": {"dtype": "float64"},
#     ...
# }
```

**What it does:**
- Reads `type` field from each variable in schema's `output_variables`
- Maps schema types (`f4`, `f8`, `i1`, etc.) to numpy dtypes
- Sets xarray encoding for each variable
- **Result:** All variables written with correct dtype (e.g., CNDC as float32, not float64)

### Step 9f: Write NetCDF File
```python
dataset.to_netcdf(
    output_path,  # e.g., /output/proc_1/IMOS_SRSALT_275_20250820T110000Z_....nc
    encoding=encoding
)
```

**What it does:**
- Writes xarray Dataset to NetCDF4 file
- Uses encoding dict to set variable dtypes
- Applies all attributes (variable and global)

---

### Step 10: Update Metadata CSV
```python
update_metadata_file_fields(
    metadata_source,          # metadata.csv path
    inst_deploy_id,           # "275"
    {"proc_1_file": Path(proc_1_output).name}  # "IMOS_SRSALT_275_....nc"
)
```

**Calls:** `tools/database_lookup.py → update_metadata_file_fields()`

**What it does:**
- Reads metadata CSV
- Finds row matching `inst_deploy_id`
- Updates `proc_1_file` column with the generated filename
- Writes CSV back to disk

**CSV before:**
```
inst_deploy_id,inst_type,location,proc_1_file
275,SBE37,BASSSTR,
```

**CSV after:**
```
inst_deploy_id,inst_type,location,proc_1_file
275,SBE37,BASSSTR,IMOS_SRSALT_275_20250820T110000Z_BASSSTR_FV00_SBE37d25m.nc
```

---

### Step 11: Return Results
```python
return {
    "metadata_row": row,
    "dataset": trimmed_dataset,
    "output_path": proc_1_output,  # Full path to written file
}
```

---

## Back in Notebook: Review Proc_1

### Cell 10: Inspect Source Data
```python
proc1_source_preview = read_sbe37(proc1_source_path, config={...})
```
(Already explained above; allows user to verify raw data before trim)

---

### Cell 11: Visualize Data by QC Flag
```python
review_figure = plot_data_by_qc(
    proc1_result["dataset"],
    title=f"proc_1 review: SBE37 {selected_metadata_row.get('inst_id')}",
)
```

**Calls:** `tools/helpers.py → plot_data_by_qc(dataset)`

**What it does:**
- Creates 4-panel plot of TEMP, DEPTH, UCUR, VCUR
- Colors points by QC flag value:
  - Green = good_data (1)
  - Yellow = probably_good (2)
  - Red = bad_data (4)
  - Gray = missing_data (5)
- User can identify any pre/post-deployment flagging

---

### Cell 12: Save Proc_1 & Update Permissions
```python
proc1_output_path = Path(proc1_result["output_path"])
proc1_output_path.parent.chmod(0o2775)  # Make parent directory group-writable
subprocess.run(["chgrp", "1054842", str(proc1_output_path)], check=True)

print(f"proc_1 saved file: {proc1_output_path}")
```

**What it does:**
- Confirms the file was written
- Sets group ownership so teammates can access/modify it
- Validates FV00 in filename

---

# STAGE 2: PROC_2 (FV01) — Apply Manual QC

The proc_2 stage does NOT re-parse or re-trim. It:
1. Loads the proc_1 FV00 NetCDF file
2. Applies manual QC flags (user-defined time windows where data is marked bad)
3. Writes the final FV01 product

---

### Cell 13: Load Proc_1 for Proc_2
```python
proc2_input = proc1_output_path  # Use output from proc_1
print(f"Using proc_1 output: {proc2_input}")
```

---

### Cell 14: Define Manual QC Flags (Optional)
```python
manual_qc_flags = [
    {
        "qc_vars": ["PSAL_quality_control"],
        "flag": 4,  # bad_data
        "start": "2025-08-23T06:00:00",
        "end": "2025-08-23T12:00:00",
        "comment": "Sensor error - delay in calibration.",
    },
    {
        "qc_vars": ["PSAL_quality_control"],
        "flag": 4,
        "start": "2026-01-02T08:49:00",
        "end": "2026-01-02T08:51:00",
        "comment": "Spike - single point.",
    },
]
```

**What it does:**
- User specifies time windows and which QC variables to flag
- Each entry marks data as bad (flag=4) or other QC state
- Comments document WHY each window was flagged

---

### Cell 15: Execute Proc_2
```python
proc2_result = run_proc2(workflow_config, input_dataset=proc2_input)
```

**Calls:** `tools/workflows/run_proc2.py → run_proc2(config, input_dataset)`

---

## Inside run_proc2()

**File:** `mooring_proc/tools/workflows/run_proc2.py`

### Step 1: Load Proc_1 File
```python
proc_2_dataset = xr.open_dataset(input_dataset)
```

**What it does:** Reads the FV00 NetCDF file written by proc_1.

### Step 2: Apply Manual QC Flags
```python
qc_windows = build_qc_windows(proc_2_dataset, manual_qc_flags)
proc_2_dataset = apply_qc_flag_windows(proc_2_dataset, qc_windows)
```

**What it does:**
- For each manual flag entry, creates a time window
- Updates the corresponding QC variable to the specified flag value
- Logs all changes to a manual QC log file

### Step 3: Reconstruct QC Variables
```python
proc_2_dataset = _ensure_qc_variables(
    proc_2_dataset,
    inst_type,
    schema_dir=config.get("schema_dir"),
    default_flag=1,  # good_data (different from proc_1's 0)
)
```

### Step 4: Write Proc_2 FV01 File
```python
proc_2_output = write_imos_file(
    proc_2_dataset,
    output_path,       # /output/proc_2/IMOS_SRSALT_275_20250820T110000Z_....nc (FV01)
    metadata=stage_metadata,
    instrument=inst_type,
    schema_dir=schema_dir,
)
```

**Same as proc_1**, but:
- Output directory is `proc_2_path`
- Version changes from FV00 to FV01 in filename
- QC flags now reflect manual edits

### Step 5: Write QC Log
```python
manual_qc_log = write_manual_qc_flags_txt(manual_qc_flags, proc_2_output)
# Returns: /output/proc_2/IMOS_SRSALT_275_....FV01_SBE37d25m_qc.txt
```

**What it does:**
- Documents each QC flag applied (time window, variable, reason)
- Provides audit trail for reviewers

### Step 6: Update Metadata CSV
```python
update_metadata_file_fields(
    metadata_source,
    inst_deploy_id,
    {"proc_2_file": Path(proc_2_output).name}
)
```

---

### Cell 16: Visualize Proc_2 with QC Applied
```python
review_figure = plot_data_by_qc(proc2_result["dataset"])
```

**User inspects:** Are the manual QC flags in the right places?

---

### Cell 17: Save Proc_2
```python
proc2_output_path = Path(proc2_result["output_path"])
proc2_output_path.parent.chmod(0o2775)
subprocess.run(["chgrp", "1054842", str(proc2_output_path)], check=True)

print(f"proc_2 saved file: {proc2_output_path}")
print(f"QC log: {proc2_result['manual_qc_log']}")
```

---

# STAGE 3: IMOS Delivery — Compliance & Archive

---

### Cell 18: Run IMOS Delivery
```python
delivery_result = run_imos_delivery(workflow_config)
```

**Calls:** `tools/workflows/run_imos_delivery.py → run_imos_delivery(config)`

---

## Inside run_imos_delivery()

**File:** `mooring_proc/tools/workflows/run_imos_delivery.py`

### Step 1: Load Proc_2 File
```python
proc_2_path = get_proc_2_path(row)  # From metadata
proc_2_dataset = xr.open_dataset(proc_2_path)
```

### Step 2: Run Compliance Check
```python
run_compliance_check(proc_2_dataset, schema={"instrument": inst_type})
```

**Calls:** `tools/validation/compliance_check.py → run_compliance_check()`

**What it does:**
- Verifies all required variables are present
- Checks all required global attributes
- Validates QC flag values
- Raises `ValueError` if non-compliant

### Step 3: Copy to Delivery Directory
```python
delivery_path = build_output_filename(delivery_metadata)
shutil.copy(proc_2_path, delivery_path)
```

**What it does:**
- Copies FV01 from proc_2 directory to delivery staging area
- **FV00 files (proc_1) are NOT copied** — they're intermediate products

### Step 4: Update Metadata CSV
```python
update_metadata_file_fields(
    metadata_source,
    inst_deploy_id,
    {
        "imos_delivery_file": Path(delivery_path).name,
        "delivery_status": "ready",
    }
)
```

---

### Cell 19: Confirm Delivery
```python
print(f"FV01 path: {delivery_result['proc_2_delivery']}")
print(f"Delivery file: {delivery_result['imos_deliverables_file']}")
```

**Output:**
```
FV01 path: /output/delivery/IMOS_SRSALT_275_20250820T110000Z_BASSSTR_FV01_SBE37d25m.nc
Delivery file: IMOS_SRSALT_275_20250820T110000Z_BASSSTR_FV01_SBE37d25m.nc
```

---

# Data Flow Diagram

```
Raw SBE37 File
    |
    v
read_sbe37() ─────────────────────────────┐
    |                                      |
    | Dataset with                         |
    | TEMP, CNDC, PSAL,                   |
    | PRES_REL, DEPTH, etc.               |
    |                                      |
    v                                      |
run_proc1()                                |
    |                                      |
    | Step 1: Parse & load                |
    |         (calls read_sbe37 again)    |────► (uses output)
    | Step 2: Apply deployment QC flags  |
    | Step 3: Trim to window              |
    | Step 4: Ensure QC variables         |
    | Step 5: Apply schema attributes    |
    | Step 6: Write IMOS FV00             |
    | Step 7: Update metadata CSV         |
    |                                      |
    v                                      |
PROC_1 OUTPUT ◄──────────────────────────┤
(IMOS FV00 NetCDF)                       |
proc_1_file: IMOS_SRSALT_275_..._FV00..  |
    |                                      |
    +──────────────────────────────────────┘
    |
    v
run_proc2()
    |
    | Step 1: Load FV00 file
    | Step 2: Apply manual QC flags
    | Step 3: Write QC log
    | Step 4: Write IMOS FV01
    | Step 5: Update metadata CSV
    |
    v
PROC_2 OUTPUT
(IMOS FV01 NetCDF)
proc_2_file: IMOS_SRSALT_275_..._FV01..
manual_qc_log: IMOS_SRSALT_275_..._qc.txt
    |
    v
run_imos_delivery()
    |
    | Step 1: Load FV01 file
    | Step 2: Run compliance check
    | Step 3: Copy to delivery directory
    | Step 4: Update metadata CSV
    |
    v
DELIVERY OUTPUT
(Same FV01, now in archive staging)
imos_delivery_file: IMOS_SRSALT_275_..._FV01..
delivery_status: "ready"
```

---

# Key Schema Files

All attributes and encodings are defined in YAML schemas:

## 1. Global Attributes
**File:** `mooring_proc/tools/schemas/global_attributes.yaml`

Defines:
- `mandatory_attributes` — required for all IMOS files (project, Conventions, etc.)
- `defaults` — defaults for author, institution, etc.
- `geospatial` — template for lat/lon/depth min/max

## 2. Instrument Schema (SBE37)
**File:** `mooring_proc/tools/schemas/sbe37_schema.yaml`

Defines:
- `input_variables` — what SBE37 parser outputs (TEMP, CNDC, PSAL, etc.)
- `output_variables` — what variables appear in NetCDF output with:
  - `type` — data type for encoding (f8, f4, i1, etc.)
  - `attributes` — variable-level attributes (units, long_name, valid_min/max, etc.)

## 3. Writer (No Hardcoded Attributes!)
**File:** `mooring_proc/tools/imos/writer.py`

**Previously:** Had hardcoded `VARIABLE_ATTRS` dict

**Now:** Reads ALL attributes from schema — 100% schema-driven

---

# Required Inputs Summary

| Input | Required | Source | Example |
|-------|----------|--------|---------|
| `inst_deploy_id` | YES | User (or find via finder) | "275" |
| `instrument` | YES | User (hardcoded) | "SBE37" |
| `metadata_csv` | YES | System default or user override | "metadata.csv" |
| `proc1_source_path` | NO | User override; auto-discovered if None | "/data/raw/sbe37_275.hex" |
| `proc1_time_start_override` | NO | User override; uses deployment window if None | "2025-08-20T15:00:00" |
| `proc1_time_end_override` | NO | User override; uses deployment window if None | "2026-05-30T10:00:00" |
| `manual_qc_flags` | NO | User list (empty list = no manual QC) | List of dicts with time windows |
| `schema_dir` | NO | System default | "tools/schemas" |

---

# Error Handling

| Error | Cause | Resolution |
|-------|-------|-----------|
| `inst_deploy_id` not found | Wrong ID, typo | Use `inst_deploy_id_finder.ipynb` |
| `TIME` variable missing | Parser failed | Check raw file format |
| Instrument schema not found | Unsupported instrument | Only SBE37, SBE26, RBRQ, AQD, SIG500 |
| Compliance check failed | Missing required variables/attributes | Check schema is correct |
| Proc_1 file not written | Encoding error | Check dtypes from schema |

---

# Summary

The SBE37 workflow is **three-stage, schema-driven**:

1. **Proc_1 (FV00)**: Parse raw → trim to window → add QC variables → write NetCDF with schema attributes
2. **Proc_2 (FV01)**: Load FV00 → apply manual QC flags → write FV01 with refined QC flags
3. **Delivery**: Load FV01 → run compliance check → copy to archive → update metadata CSV

All **variable attributes, encodings, and global attributes are defined in YAML schemas**, not hardcoded in Python. This makes the pipeline:
- **Scalable** — add new instruments by adding a schema
- **Maintainable** — change attributes by editing YAML, not code
- **Verifiable** — compliance checks are schema-aware