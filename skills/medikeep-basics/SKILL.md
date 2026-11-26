---
name: medikeep-basics
description: Orientation for the MediKeep MCP server - data model, patient context, how to find and call any of the ~580 API operations, pagination, files, and safety rules. Read first whenever working with MediKeep health records.
---

# Working with MediKeep

MediKeep is a self-hosted personal health record system. Each **user** account can
own or be shared several **patients** (self, children, parents...). Almost every
medical record belongs to exactly one patient.

## 1. Orient yourself

1. `medikeep_whoami` → signed-in user, **active patient**, every accessible patient,
   server version. Do this once at the start of a session.
2. If the user is asking about someone else (e.g. "my daughter"), find them in
   `accessible_patients` and either pass `patient_id` explicitly or switch with
   `switch_active_patient` (`body: {"patient_id": N}`). Say which patient you are
   looking at whenever more than one exists.
3. `medikeep_patient_overview` returns a multi-section snapshot in one call - prefer it
   to many small calls when you need the big picture.

## 2. Find and call any operation

| Step | Tool |
|---|---|
| See categories | `medikeep_list_operations` (no args) |
| List a category | `medikeep_list_operations tag="lab-results"` |
| Keyword search | `medikeep_list_operations search="booster"` |
| Parameters & body schema | `medikeep_describe_operation operation="create_medication"` |
| Execute | `medikeep_call operation="create_medication" body={...}` |

`medikeep_call` arguments: `path_params`, `query`, `body` (JSON), `form` + `files`
(multipart uploads, local paths), `raw_file` (raw-body uploads such as DICOM/ZIP
imaging import), `save_to` (downloads), `confirm` (required for DELETE).
`operation` may also be `"GET /api/v1/medications/12"`.

If the server runs in `full` tool mode, every operation is also a direct tool with
the same name (e.g. `read_medications`); the arguments are the same parameters flattened.

**Always describe an operation before your first create/update call** - required
fields and enums differ per record type, and MediKeep validates strictly (422 errors
list the offending field).

## 3. Record types and their main operations

| Domain | List / read | Create | Notes |
|---|---|---|---|
| Medications | `read_medications`, `read_patient_medications` (active_only) | `create_medication` | status: active, stopped, on-hold, completed, cancelled |
| Conditions | `read_conditions`, `get_active_conditions` | `create_condition` | status: active, inactive, resolved, chronic, recurrence, relapse; `diagnosis` required |
| Allergies | `read_allergies`, `get_active_allergies`, `get_critical_allergies` | `create_allergy` | severity: mild, moderate, severe, life-threatening |
| Lab results | `get_lab_results`, `get_lab_results_by_patient` | `create_lab_result` | individual analytes are **lab test components** |
| Lab components | `get_lab_test_components_by_lab_result`, `get_component_catalog`, `get_lab_test_component_trends` | `create_lab_test_components_bulk` | status auto-computed: normal / high / low / abnormal |
| Vitals | `read_patient_vitals`, `read_patient_latest_vitals`, `read_patient_vitals_stats` | `create_vitals` | BP, HR, temp, weight, height, SpO2, glucose, A1c, pain |
| Encounters (visits) | `read_encounters`, `get_recent_encounters` | `create_encounter` | `reason` + `date` required |
| Procedures | `read_procedures`, `get_recent_procedures` | `create_procedure` | status: scheduled, in_progress, completed, cancelled, postponed |
| Treatments | `read_treatments`, `get_active_treatments` | `create_treatment` | status: planned, active, in_progress, completed, cancelled, on_hold |
| Immunizations | `read_immunizations`, `get_immunization_history` | `create_immunization` | `check_booster_due` |
| Symptoms | `read_symptoms`, `read_symptom_timeline`, `read_symptom_stats` | `create_symptom` + `log_symptom_occurrence` | a symptom is a parent; each episode is an occurrence |
| Injuries | `read_injuries`, `get_active_injuries` | `create_injury` | status: active, healing, resolved, chronic |
| Family history | `read_family_members`, `get_family_member_conditions` | `create_family_member`, `create_family_condition` | |
| Insurance | `get_insurances` | `create_insurance` | `set_primary_insurance` |
| Emergency contacts | `read_emergency_contacts` | `create_emergency_contact` | |
| Equipment | `read_medical_equipment`, `get_equipment_needing_service` | `create_medical_equipment` | |
| Imaging | `read_imaging_studies` | `import_imaging_files` (raw_file) | |
| Blood donations | `read_blood_donations`, `read_blood_donation_eligibility` | `create_blood_donation` | |
| Providers | `read_practitioners`, `read_practices`, `read_pharmacies`, `list_active_specialties` | `create_practitioner` etc. | shared reference data |

Records are linked to each other (condition ↔ medication, lab result ↔ condition,
encounter ↔ anything, treatment ↔ medication/equipment/lab). Link operations live
under the parent, e.g. `get_condition_medications_with_details`,
`list_links__encounters_conditions`, `get_treatment_medications`.

Cross-cutting: `medikeep_search_records` (full-text), `search_by_tags_across_entities`,
`get_popular_tags_across_entities`, files via `get_entity_files` / `upload_entity_file`
/ `download_file__entity-files_files_download`.

## 4. Practical rules

- **Pagination:** list endpoints take `skip`/`limit` (defaults are often 100). Page
  until fewer than `limit` items return when you need completeness.
- **Patient scoping:** list endpoints such as `read_medications` accept `patient_id`;
  without it they return the *active* patient's records. Path parameters named
  `patient_id` are auto-filled with the active patient if omitted.
- **Dates** are ISO `YYYY-MM-DD`; datetimes ISO 8601.
- **Null fields are stripped** from responses to save space; a missing field means "not recorded".
- **Files:** uploads take local paths; downloads are written to the download dir and
  the path is returned - open/read that file if you need its contents.
- **Large responses** are truncated - narrow with filters, dates or `limit`.

## 5. Safety and tone

- This is real, private health data. Never fabricate a value, date or record; if it
  isn't in MediKeep, say so.
- Cite where facts came from (record type + date, e.g. "LDL 142 mg/dL, lab 2026-03-04").
- **Ask before any create/update/delete**, show what you will write, and report the
  IDs afterwards. DELETEs need explicit user confirmation (`confirm: true`).
- You can explain and summarize, flag values outside reference ranges, and suggest
  questions for a clinician - but do not diagnose or tell the user to change
  treatment. Recommend contacting a clinician for anything urgent or worrying.
