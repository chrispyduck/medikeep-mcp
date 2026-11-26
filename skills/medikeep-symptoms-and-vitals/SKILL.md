---
name: medikeep-symptoms-and-vitals
description: Log and analyze symptoms, symptom episodes, vitals (blood pressure, weight, glucose, heart rate, SpO2...) and injuries in MediKeep. Use for "log a migraine", "how often have my headaches happened", "what's my blood pressure trend", "record today's weight", or correlating symptoms with medications and conditions.
---

# Symptoms, vitals and injuries

## Symptoms: two levels

- **Symptom** (parent) - `symptom_name`, `category`, `status` (active, resolved,
  recurring), `is_chronic`, `first_occurrence_date`, `typical_triggers`, `general_notes`, tags.
- **Occurrence** (each episode) - `occurrence_date` (required), `severity` (required: none,
  mild, moderate, severe, critical), `pain_scale` 0-10, `duration`, `time_of_day`,
  `occurrence_time`, `location`, `triggers`, `relief_methods`, `associated_symptoms`,
  `impact_level`, `resolved_date`/`resolved_time`, `resolution_notes`, `notes`.

**Logging an episode:** find the parent first (`read_symptoms` with `search`). If it
exists, `log_symptom_occurrence` (path `symptom_id`). If not, `create_symptom`
(`first_occurrence_date` = today/the episode date), then log the occurrence. Don't
create a new parent per episode.

**Analysis:**
- `read_symptom_stats` - counts by status/severity.
- `read_symptom_timeline` (`start_date`, `end_date`) - episodes over time.
- `read_symptom_occurrences` (path `symptom_id`) - full episode list for one symptom.
  Summarize frequency (per week/month), severity distribution, common triggers and
  relief methods, time-of-day pattern, and change over time.
- Context: `get_symptom_conditions`, `get_symptom_medications`, `get_symptom_treatments`;
  link with `link_symptom_to_condition` / `link_symptom_to_medication` /
  `link_symptom_to_treatment`. Compare episode dates with medication start/stop dates
  (`effective_period_start/end`) - present correlation as an observation, not causation.

## Vitals

Fields: `recorded_date` (required), `systolic_bp`, `diastolic_bp`, `heart_rate`,
`temperature`, `weight`, `height`, `oxygen_saturation`, `respiratory_rate`,
`blood_glucose` + `glucose_context`, `a1c`, `bmi`, `pain_scale`, `location`,
`device_used`, `notes`. Units follow the user's preference (`get_current_user_preferences`
→ unit system); confirm units when the user gives a number without one.

| Need | Operation |
|---|---|
| Most recent reading | `read_patient_latest_vitals` |
| Averages/min/max/trend | `read_patient_vitals_stats` |
| History in a window | `read_patient_vitals_date_range` (start_date, end_date) |
| Paged history | `read_patient_vitals_paginated` |
| Record | `create_vitals` (or `create_patient_vitals`) |
| Device/app import | `get_import_devices` → `preview_import__vitals_patient_import_preview` → `execute_import__vitals_patient_import_execute` |

When analyzing blood pressure, report averages and the share of readings above common
thresholds (e.g. ≥130/80, ≥140/90) and note time-of-day/measurement context if present.
For weight, report change over the window and per month. Avoid single-reading conclusions.

## Injuries

`create_injury` - `injury_name`, `body_part` (required), `laterality` (left, right,
bilateral, not_applicable), `injury_type_id` (`get_injury_types_for_dropdown`),
`date_of_injury`, `mechanism`, `severity`, `status` (active, healing, resolved, chronic),
`treatment_received`, `recovery_notes`. Link care with `create_injury_medication`,
`create_injury_treatment`, `create_injury_procedure`, `create_injury_condition`, and
encounters (`create_link__injuries_encounters`). `get_active_injuries` for current ones.

## Safety

If a logged symptom or vital suggests an emergency (e.g. chest pain, SpO2 < 90%, BP ≥
180/120, stroke signs, severe allergic reaction), tell the user to seek urgent care
before continuing with record-keeping.
