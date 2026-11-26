---
name: medikeep-lab-analysis
description: Read, trend, and interpret lab results in MediKeep, and enter new lab panels (including from PDF reports). Use for questions like "how is my cholesterol trending", "which labs were abnormal", "compare my last two blood panels", or "add these lab results".
---

# Lab results

## Data model

- A **lab result** (`/lab-results`) is one order/report: `test_name` (e.g. "Comprehensive
  Metabolic Panel"), `test_category`, `ordered_date`, `completed_date`, `facility`,
  `status` (ordered, in_progress, completed, cancelled), `labs_result`, `practitioner_id`, notes, tags.
- **Lab test components** (`/lab-test-components`) are the individual analytes inside it:
  `test_name` ("Glucose"), `abbreviation`, `test_code` (LOINC), `value`, `unit`,
  `ref_range_min`/`ref_range_max`/`ref_range_text`, `status`, `category`,
  `result_type` (quantitative | qualitative), `qualitative_value` (positive, negative, detected, undetected).
- Component `status` is computed by MediKeep: `low` / `high` / `normal` from the
  reference range, `abnormal` for positive/detected qualitative results.
- A single-value lab result can also hold `value`/`unit`/ref range directly (`is_panel: false`).

## Reading

| Need | Operation |
|---|---|
| Which tests exist for this patient, latest value + trend + count | `get_component_catalog` (filters: search, category, status) |
| Full history of one analyte | `medikeep_lab_trend test_name="LDL Cholesterol"` (exact name from the catalog; add `unit` if several units exist) |
| Everything outside range | `get_abnormal_lab_test_components` (`patient_id`, optional `lab_result_id`) |
| All panels | `get_lab_results_by_patient` (skip/limit) |
| Components of one panel | `get_lab_test_components_by_lab_result` |
| Panel summary stats | `get_lab_test_component_statistics` |
| Attached PDFs | `get_lab_result_files` → `download_file__lab-result-files_download` |
| Linked conditions/meds/encounters | `get_lab_result_conditions`, `get_lab_result_medications`, `get_lab_result_encounters` |

Trend names must match exactly - always look the name up in `get_component_catalog`
first instead of guessing ("Hemoglobin A1c" vs "HbA1c").

## Interpreting (explain, don't diagnose)

- Report value + unit + reference range + date for every number.
- For trends: first and latest values, min/max, direction, and how many readings.
  Note gaps in time and changes of unit/lab (reference ranges differ between labs).
- Distinguish "slightly outside range" from "far outside range"; mention that one
  out-of-range value is common and context matters.
- Connect to context the record already holds - e.g. a statin started (medication
  `effective_period_start`) before an LDL drop, or a condition linked to the lab result.
- End with questions the user could ask their clinician. Urge prompt medical contact
  for critical values (e.g. potassium, sodium, glucose far out of range).

## Entering a new panel

1. Confirm patient and get the report details from the user (or from a PDF they provide).
   - PDF already in MediKeep or local: `parse_lab_pdf_with_ocr` (multipart `file`, needs an
     existing `lab_result_id`) returns extracted text for *you* to parse; it saves nothing.
2. Look up the ordering practitioner: `search_practitioners_by_name`.
3. Check for duplicates: `get_lab_results_by_patient` around the same date.
4. `create_lab_result` with `test_name`, `completed_date`, `status: "completed"`,
   `facility`, `practitioner_id`, `patient_id`.
5. Normalize analyte names with `search_standardized_tests` / `batch_match_tests`
   (gives LOINC `test_code` and canonical names), and reuse names already in the
   patient's `get_component_catalog` so trends stay continuous.
6. `create_lab_test_components_bulk` with `{"lab_result_id": id, "components": [...]}`.
   Include `ref_range_min`/`ref_range_max` from the report so status is computed; for
   text ranges ("<200") use `ref_range_text` plus the numeric bound.
7. Optionally attach the PDF: `upload_lab_result_file` (`files: {"file": path}`) and link
   to conditions/encounters (`create_lab_result_condition`, `create_lab_result_encounter`).
8. Read back with `get_lab_test_components_by_lab_result` and show the user what was stored.
