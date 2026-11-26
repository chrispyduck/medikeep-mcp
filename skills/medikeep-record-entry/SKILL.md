---
name: medikeep-record-entry
description: Accurately add or update MediKeep records from conversation, notes, visit summaries, discharge papers, or uploaded documents - with duplicate checks, provider lookups, standardized codes, linking related records, tags, and file attachments. Use whenever creating or editing medical records.
---

# Entering records correctly

## Workflow for every write

1. **Confirm the patient** (`medikeep_whoami`). Wrong-patient entries are the worst error.
2. **Describe the operation** (`medikeep_describe_operation`) to get required fields and enums.
3. **Check for duplicates** - list the same record type around the same date/name first.
4. **Resolve references** (practitioner, practice, pharmacy, condition IDs) - see below.
5. **Show the user exactly what you will create** (a compact table) and get a yes.
   Extract only what the source says; leave unknown fields out instead of guessing.
6. Create, then **link** related records and **attach** source files.
7. Read back and report the new IDs.

## Resolving references

| Reference | Look up | Create if missing |
|---|---|---|
| Practitioner | `search_practitioners_by_name` (min 2 chars), `read_practitioners` | `create_practitioner` (needs `specialty_id` from `list_active_specialties` / `create_or_get_specialty`) |
| Practice / clinic | `search_practices_by_name` | `create_practice` |
| Pharmacy | `read_pharmacies` | `create_pharmacy` |
| Condition for linking | `get_conditions_for_dropdown` | `create_condition` |
| Lab analyte names / LOINC | `search_standardized_tests`, `batch_match_tests`, patient's `get_component_catalog` | - |
| Vaccine names / WHO codes | `search_standardized_vaccines`, `get_vaccine_autocomplete` | - |
| Injury type | `get_injury_types_for_dropdown` | `create_injury_type` |
| Family relationship values | describe `create_family_member` | - |
| Tags | `autocomplete_tags`, `get_popular_tags_across_entities` | `create_tag` or just pass `tags: [...]` |

Reuse existing practitioners and names exactly - near-duplicates fragment the record.

## Mapping a visit summary

A typical after-visit summary becomes:

- `create_encounter` - `date`, `reason`, `visit_type`, `chief_complaint`, `diagnosis`,
  `treatment_plan`, `follow_up_instructions`, `practitioner_id`, `location`.
- New diagnoses → `create_condition` (`diagnosis`, `status`, `onset_date`, `icd10_code` if given),
  then link: `create_link__encounters_conditions`.
- New prescriptions → `create_medication`, then `create_condition_medication` and
  `create_link__encounters_medications`.
- Orders → `create_lab_result` with `status: "ordered"` or `create_procedure` with
  `status: "scheduled"`; link to the encounter.
- Vitals measured at the visit → `create_vitals` (`recorded_date`, values, `practitioner_id`).
- Vaccines given → `create_immunization` (`vaccine_name`, `date_administered`, `lot_number`,
  `manufacturer`, `site`, `standardized_vaccine_who_code` if found).
- Follow-up appointment → a future `create_encounter`; `reminder_enabled` + `reminder_offsets` if wanted.

Encounter link operations follow the pattern `create_link__encounters_<type>` with
`body: {"<type>_id": id}`; bulk variants (`bulk_create_links__encounters_<type>_bulk`)
take lists. Describe the link operation to get exact field names.

## Attaching documents

- Most record types accept files: `upload_entity_file` with `path_params:
  {"entity_type": "<type>", "entity_id": id}`, `files: {"file": "/path/to/doc.pdf"}`,
  optional `form: {"description": ..., "category": ...}`. Entity types: lab-result,
  insurance, encounter (visit), procedure, vitals, medication, immunization, allergy,
  condition, treatment, symptom, injury, medical-equipment.
- Lab result PDFs can also use `upload_lab_result_file`.
- Documents already in Paperless-ngx/Papra: `search_paperless_documents` /
  `search_papra_documents`, then `link_paperless_document` / `link_papra_document`.

## Bulk imports

- Vitals from devices/apps: `get_import_devices`, then
  `preview_import__vitals_patient_import_preview` → review → `execute_import__vitals_patient_import_execute`.
- Health record files (e.g. CCDA/FHIR exports): `get_import_formats`, then
  `preview_import__health-records_patient_import_preview` → `execute_import__health-records_patient_import_execute`.
- DICOM/ZIP imaging: `import_imaging_files` with `query: {"filename": ...}` and
  `raw_file: <path>`; poll `read_import_job`.

Always run the preview and show the user what will be created/skipped before executing.

## Updating and deleting

- Updates are partial (`update_*` with only the changed fields).
- Prefer status changes (resolved, stopped, completed) over deletion to keep history.
- Deletions require explicit user confirmation and `confirm: true`. Deleted items
  may be recoverable by an admin via trash management.
