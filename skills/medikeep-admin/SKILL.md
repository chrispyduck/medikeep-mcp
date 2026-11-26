---
name: medikeep-admin
description: Administer a MediKeep server (admin accounts only) - system health, users, backups and restore, trash recovery, activity/audit logs, settings, integrations (Paperless-ngx, Papra), notifications, and account security (2FA, sessions). Use for operational or account-management questions rather than medical data.
---

# MediKeep administration and account settings

Admin endpoints (tag `admin`, paths `/api/v1/admin/...`) need an admin account; other
users get 403. List them with `medikeep_list_operations tag="admin"`.

## Health and version

`system_health`, `get_version`, `get_releases` (is an update available?),
`check_storage_health`, admin dashboard operations (`medikeep_list_operations
search="dashboard"`) for counts and recent activity.

## Backups and restore

`medikeep_list_operations search="backup"` - create backups, list, download (file is
saved locally), upload, verify, schedule, and restore (`search="restore"`).
Restoring overwrites data: always confirm explicitly and suggest creating a fresh
backup first.

## Users

`search="user-management"` covers listing users, creating, activating/deactivating,
resetting passwords, and role changes. Prefer deactivation over deletion.

## Trash and recovery

`search="trash"` - deleted records can often be listed and restored before they are purged.
Check here first when a user says something disappeared.

## Activity / audit

`search="activity"` - who changed what and when; filter by user, entity, date.

## Integrations

- Paperless-ngx: `get_paperless_settings`, `update_paperless_settings`,
  `test_paperless_connection`, `check_paperless_health`, `search_paperless_documents`.
- Papra: `get_papra_settings`, `update_papra_settings`, `test_papra_connection`,
  `list_papra_organizations`, `search_papra_documents`.

## Notifications

Channels (Discord, email, ntfy, webhooks...): `list_channels`, `create_channel`,
`test_channel`. What triggers notifications: `get_event_types`, `get_preference_matrix`,
`set_preference`. Sent history: `get_history`.

## Account security (any user)

- Profile: `get_current_user`, `update_current_user`, `get_current_user_preferences`,
  `update_current_user_preferences` (units, date format, timezone, ...).
- Password: `change_password`.
- 2FA: `get_two_factor_status`, `start_totp_setup`, `confirm_totp_setup`,
  `regenerate_backup_codes`, `disable_two_factor`, trusted devices
  (`list_trusted_devices`, `forget_trusted_device`).
- Sessions: `revoke_other_sessions`.

Do not change passwords, 2FA, or other users' accounts unless the user explicitly asks.
Never display backup codes or TOTP secrets beyond what the user asked to see. Note that
enabling 2FA on the account this MCP uses requires setting `MEDIKEEP_TOTP_SECRET`.
