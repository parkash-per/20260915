# Instrument workflows

## Overview

Each instrument has a dedicated Jupyter notebook pipeline that implements a three-stage workflow:
1. **proc_1**: Parse raw data and apply deployment trim window
2. **proc_2**: Apply manual QC flags and adjustments
3. **imos_delivery**: Run compliance gate and stage final deliverable

The notebooks are designed for **cell-by-cell execution** rather than "Run All". This allows operators to inspect, review, and validate data at each stage before proceeding.

## Pipeline Structure

### Stage 1: proc_1
- Resolves the raw source file and deployment trim window
- Builds proc_1 metadata and generates IMOS FV00 filename
- Writes the proc_1 NetCDF to the proc_1 directory
- Updates metadata CSV with saved proc_1 filename
- **Output**: FV00 intermediate product

### Stage 2: proc_2
- Applies manual QC flags to the already-trimmed FV00 proc_1 output
- Creates the final IMOS FV01 product candidate
- Does not re-trim source data, only applies QC adjustments
- Writes QC log documenting operator edits
- **Output**: FV01 final product

### Stage 3: imos_delivery
- Runs final compliance gate for IMOS workflow
- Only the FV01 proc_2 product is treated as the final deliverable
- FV00 files remain in proc_1 directory as intermediate products
- **Output**: Staged delivery file with compliance metadata

## Usage Example

Each instrument notebook follows the same structure. Example using SBE37:

```python
# 1. Set instrument deployment identifier
inst_deploy_id = "275"
instrument = "SBE37"

# 2. Build workflow configuration
config = build_workflow_config()

# 3. Run proc_1: parse and trim
proc1_result = run_proc1(config, source_path=proc1_source_path)

# 4. Review proc_1 output
review_figure = plot_data_by_qc(proc1_result["dataset"])

# 5. Define manual QC flags if needed
manual_qc_flags = [
    {
        "qc_vars": ["PSAL_quality_control"],
        "flag": 4,
        "start": "2025-08-23T06:00:00",
        "end": "2025-08-23T12:00:00",
        "comment": "Sensor error - delay in calibration.",
    }
]

# 6. Run proc_2: apply QC
proc2_result = run_proc2(config, input_dataset=proc1_output_path)

# 7. Review and save proc_2 output
review_figure = plot_data_by_qc(proc2_result["dataset"])

# 8. Run imos_delivery: compliance gate
delivery_result = run_imos_delivery(config)
print(delivery_result['imos_deliverables_file'])
```

## Supported Instruments

### SBE37
- Status: **Operational**
- Pipeline: `sbe37_pipeline.ipynb`
- Three-stage workflow fully implemented and validated

### AQD (Aquadopp)
- Status: **In development** ⚠️
- Pipeline: `aqd_pipeline.ipynb`
- Caveat: Implementation ongoing to match SBE37 structure

### SBE26 (Pressure)
- Status: **Needs testing** ⚠️
- Pipeline: `sbe26_pipeline.ipynb`
- Caveat: Pipeline implementation complete but requires validation testing

### RBRQ (RBRconcerto³)
- Status: **Needs testing** ⚠️
- Pipeline: `rbrq_pipeline.ipynb`
- Caveat: Pipeline implementation complete but requires validation testing

### SIG500 (Signature 500)
- Status: **Under refinement** ⚠️
- Pipeline: `sig500_pipeline.ipynb`
- Caveat: Pipeline needs refinement and optimization before operational use

## Notebook Navigation Guide

**Suggested run order for operators:**
1. Run "Imports" cell
2. Run "Setup" cells (working directory, permissions)
3. Run "ID lookup" to validate inputs and confirm metadata
4. If you need to discover an ID first, use `inst_deploy_id_finder.ipynb`
5. Run only the stage cells you need (proc_1, proc_2, imos_delivery)

**Do not use "Run All"** — execute cells individually to allow for review and validation at each processing stage.

## Key Workflow Configuration

Each pipeline requires:
- `metadata_csv`: Path to metadata CSV file
- `inst_deploy_ID`: Deployment identifier (validated via ID lookup)
- `instrument`: Instrument type (e.g., "SBE37", "AQD")
- `manual_qc_flags`: Optional list of QC windows to apply in proc_2

Manual QC flag structure:
```python
{
    "qc_vars": ["variable_quality_control"],  # Variable to flag
    "flag": 4,                                # IMOS QC flag value
    "start": "yyyy-mm-ddThh:mm:ss",         # UTC timestamp
    "end": "yyyy-mm-ddThh:mm:ss",           # UTC timestamp
    "comment": "Reason for flag"             # Documentation
}
```

## Output Files

- **proc_1 output**: IMOS FV00 file in `proc_1/` directory (intermediate)
- **proc_2 output**: IMOS FV01 file in `proc_2/` directory (final product)
- **QC log**: Operator edit documentation for proc_2
- **Delivery file**: Compliance-checked deliverable staged for publication
