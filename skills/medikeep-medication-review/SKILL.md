---
name: medikeep-medication-review
description: Review, reconcile, and maintain a patient's medication list in MediKeep - current meds, why each is taken, allergy cross-checks, start/stop history, reminders, pharmacies and prescribers. Use for "what am I taking", medication reconciliation, adding/stopping a medication, or checking a new drug against allergies.
---

# Medication review

## Data model

`/medications` fields: `medication_name` (required), `alternative_name`, `medication_type`,
`dosage`, `frequency`, `route`, `indication`, `effective_period_start`,
`effective_period_end`, `status` (active, stopped, on-hold, completed, cancelled),
`practitioner_id` (prescriber), `pharmacy_id`, `side_effects`, `notes`, `tags`, and
reminder settings (`reminder_enabled`, `reminder_times` ["08:00"], `reminder_days`
[0-6], `reminder_message`).

Medications link to conditions (`get_medication_conditions`,
`create_condition_medication`), treatments (`get_medication_treatments`), symptoms
(`link_symptom_to_medication`), injuries, encounters and lab results. Allergies can
reference a `medication_id`.

## Current medication list

1. `read_patient_medications` with `active_only: true` (path `patient_id` auto-filled).
2. For each, the reason: `get_medication_conditions` (path `medication_id`); fall back
   to the `indication` field.
3. Resolve prescriber/pharmacy names with `read_practitioner` / `read_pharmacy` when only IDs are present.
4. Present as a table: name (alt name), dose, frequency, route, for what, since, prescriber.

## Reconciliation checks (report findings, ask before fixing)

- `status: active` but `effective_period_end` in the past → probably stopped.
- Same drug entered twice (compare `medication_name` / `alternative_name`, brand vs generic).
- Active medication with no linked condition and no `indication`.
- Allergy conflicts: for each active med and any new drug, call `check_allergen_conflict`
  (path `allergen` = drug name / class) and also compare against `get_active_allergies`
  (look at allergens like "penicillin" vs "amoxicillin" - same class).
- Side effects recorded in `side_effects` that match active symptoms (`read_symptoms`).
- Labs commonly monitored for a drug class (e.g. statins → lipid panel/ALT, metformin →
  A1c/eGFR, levothyroxine → TSH): check `get_component_catalog` for recency and offer
  to show trends. Present these as "commonly monitored", not as instructions.

You are not a pharmacist: do not assert drug-drug interactions as fact from memory.
You may mention well-known interaction concerns as questions for the prescriber or pharmacist.

## Changes

- **Add:** describe `create_medication`; look up prescriber (`search_practitioners_by_name`)
  and pharmacy (`read_pharmacies`); check allergies first; then create with
  `patient_id`, `status: "active"`, `effective_period_start`. Offer to link it to its
  condition with `create_condition_medication` (`body: {"medication_id": id}`).
- **Stop:** prefer `update_medication` with `status: "stopped"` and
  `effective_period_end` over deleting - history matters. Delete only if entered in error.
- **Dose change:** update `dosage`/`frequency` and add a dated note, or stop the old entry
  and create a new one if the user wants history preserved.
- **Reminders:** set `reminder_enabled`, `reminder_times`, `reminder_days`; reminders are
  delivered through notification channels (`list_channels`) - `send_test_reminder` verifies setup.
