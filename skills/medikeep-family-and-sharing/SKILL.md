---
name: medikeep-family-and-sharing
description: Manage family medical history, multiple patients (dependents, parents), and sharing records with other MediKeep users - invitations, permissions, revocation. Use for "add my father's heart disease", "what runs in my family", "switch to my son's record", or "share my records with my spouse".
---

# Family history, multiple patients, and sharing

## Multiple patients

- `get_accessible_patients` lists every patient the user can see (owned + shared);
  `get_owned_patients` only owned; `get_self_record` the user's own record.
- `get_active_patient` / `switch_active_patient` (`body: {"patient_id": N}`) controls
  which patient un-scoped calls use. Tell the user when you switch, and switch back
  afterwards if the change was only for your query (or pass `patient_id` instead).
- `create_patient` adds a dependent (child, parent you care for); `update_patient` edits demographics.
- Never mix data across patients in one answer without labeling whose it is.

## Family medical history

- **Family members** belong to a patient: `create_family_member` - `name`,
  `relationship` (describe the operation for allowed values, e.g. father, mother,
  sibling, grandparent...), `gender`, `birth_year`, `is_deceased`, `death_year`, notes.
- **Family conditions** belong to a family member: `create_family_condition` (path
  `family_member_id`) - `condition_name`, `diagnosis_age`, `severity`, `status`,
  `condition_type`, `icd10_code`, notes.
- Read: `read_family_members` (filter `relationship`), `get_family_member_conditions`,
  `get_organized_family_history` (everything grouped, including history shared with you).

**Summarizing family history:** group by condition, list affected relatives with
relationship, side of family if known, and age at diagnosis. Highlight first-degree
relatives and early onset (e.g. heart disease before 55 in men / 65 in women, cancers
diagnosed young) as things worth mentioning to a clinician - not as risk predictions.

## Sharing a patient record

- Sharing creates an **invitation**: `send_patient_share_invitation` - `patient_id`,
  `shared_with_user_identifier` (username or email), `permission_level` (view, edit, full),
  optional `expires_at`, message. Bulk: `bulk_send_patient_share_invitations`.
- See shares: `get_patient_shares` (path `patient_id`), `get_shares_created`,
  `get_shares_received`, `get_user_sharing_stats`.
- Change/revoke: `update_patient_share`, `revoke_patient_share`; a recipient can leave
  with `remove_my_access`.
- Family history can be shared separately per relative: `send_family_history_share_invitation`,
  `get_family_member_shares`, `revoke_family_member_share`, `get_shared_family_history`.

## Invitations

`get_pending_invitations` (received), `get_sent_invitations`, `get_invitation_summary`,
`respond_to_invitation` (accept/decline - describe for the body), `cancel_invitation`,
`revoke_invitation`.

Sharing exposes private health data to another person: always confirm the recipient,
the patient, the permission level and expiry with the user before sending, and prefer
the least permission that meets their need (`view`).
