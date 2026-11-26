---
name: medikeep-reports-and-export
description: Produce PDF reports, data exports (JSON/CSV/PDF/ZIP), and downloads of attached files from MediKeep. Use when the user wants a printable report for a doctor, a backup/export of their data, specific documents, or trend charts.
---

# Reports, exports and files

All of these return files; the MCP server saves them locally (default
`~/Downloads/medikeep-mcp`, or `save_to`) and returns the path. Tell the user where
the file is. Read the file yourself only if you need its contents.

## Quick export

`export_patient_data` (GET) - query:
- `format`: json | csv | pdf
- `scope`: all, medications, lab_results, ... (describe the operation for the full enum)
- `start_date` / `end_date`
- `include_files`: true → ZIP containing the export plus attached files
- `include_patient_info`, `unit_system` (imperial | metric)

`get_export_summary` shows record counts per scope first; `get_supported_formats` lists options.
Several scopes in one ZIP: `create_bulk_export` (`body: {"scopes": [...], "format": ...}`).

JSON exports are the best input if *you* need to analyze lots of data at once.

## Custom PDF report (for a clinician)

1. `get_custom_report_data_summary` - categories and records available for selection.
2. Choose records with the user (e.g. active meds, relevant conditions, last 3 lipid panels).
3. Optional trend charts: `get_available_trend_data`, then `trend_charts` with
   `vital_charts` / lab test charts (describe `generate_custom_report` for the shape).
4. `preview_report_record_count` to sanity-check the selection.
5. `generate_custom_report` with `selected_records: [{"category": "medications",
   "record_ids": [..]}, ...]`, `report_title`, `include_patient_info`, `include_summary`,
   `date_range`, optional `tags`.
6. Save reusable selections: `save_report_template`, `get_saved_templates`, `get_template`.

## Attached files

- List files on a record: `get_entity_files` (path `entity_type`, `entity_id`);
  counts for many records: `get_batch_file_counts__entity-files_files_batch-counts`.
- Download: `download_file__entity-files_files_download` (path `file_id`).
- Lab PDFs: `get_lab_result_files` / `read_files_by_patient` →
  `download_file__lab-result-files_download`.
- Imaging: `read_imaging_studies` → `read_imaging_study_series` →
  `read_imaging_instance_file`.
- Patient photo: `get_patient_photo`.

## Privacy

Exports contain the full health record. Save only where the user asks, don't upload
them anywhere else, and mention that the file contains sensitive data.
