---
name: medikeep-health-summary
description: Build a health summary, pre-appointment brief, or "what's going on with my health" overview from MediKeep records. Use when the user wants a summary of a patient's current health, a doctor-visit prep sheet, a handoff to a new provider, or a recap of a time period.
---

# Health summaries and visit prep

## Gather (in this order)

1. `medikeep_whoami` - confirm which patient. If several exist and the request is
   ambiguous, ask.
2. `medikeep_patient_overview sections=["all"] days=<window>` - one call returns
   demographics, active medications/conditions/allergies/treatments/injuries, latest
   vitals + stats, recent encounters/procedures/immunizations, recent labs, abnormal lab
   components, symptoms, family members, insurance, emergency contact, equipment.
   Use `days=90` for "lately", `365` (default) for a yearly review, larger for history.
3. Fill gaps only as needed:
   - Lab detail: `get_lab_test_components_by_lab_result` for the most recent panels;
     `medikeep_lab_trend` for anything abnormal or clinically central (A1c, LDL, eGFR, TSH...).
   - Why each medication is taken: `get_medication_conditions` (path `medication_id`)
     or `get_condition_medications_with_details`.
   - Symptom activity: `read_symptom_timeline` with start/end dates.
   - Family history: `get_family_member_conditions` per relevant relative.
   - Visit for a specific specialist: filter `read_encounters` / `read_practitioners`.

## Write the summary

Use this structure; omit empty sections rather than writing "none recorded" for each.

1. **Patient** - name, age (from birth date), sex, blood type, primary care provider.
2. **Allergies** - allergen, reaction, severity. Put life-threatening first. Never omit this section; say "No allergies recorded" if empty.
3. **Active problems** - condition, since (onset), severity, ICD-10 if present.
4. **Current medications** - name, dose, frequency, route, indication / linked condition, prescriber.
5. **Recent results** - most recent vitals (with date) and notable labs: value, unit,
   reference range, status, and trend direction vs. prior values.
6. **Recent care** - encounters, procedures, treatments in the window (date, provider, reason, outcome).
7. **Immunizations** - recent and any `check_booster_due` results the user cares about.
8. **Symptoms / open issues** - active symptoms with frequency & severity from occurrences.
9. **Family history** - first-degree relatives' significant conditions with age at diagnosis.
10. **Questions to ask** (visit prep) - derived from abnormal results, unresolved
    symptoms, medications without a linked condition, overdue boosters, equipment needing service.

## Rules

- Every number carries its unit and date. Prefer tables for meds and labs.
- Flag data-quality issues you notice (active medication with an end date in the past,
  duplicate entries, conditions with no status) - offer to fix them, don't silently do it.
- Status words like "high"/"low" come from MediKeep reference ranges; describe them as
  "outside the lab's reference range", not as diagnoses.
- For a provider handoff, offer a PDF instead: see the `medikeep-reports-and-export` guide.
