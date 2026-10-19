# Apply the doctor / nurse / owner update

This is an **update pack for your existing v2 project**, not a standalone project.

## Install

1. Stop both FastAPI and Streamlit with **Ctrl+C**.
2. Back up your current project folder, including its `.env` and `data/` folder.
3. Extract this ZIP and open its `hospital_roles_update` folder.
4. Copy everything **inside** that folder into your current project folder. Replace
   matching files and merge the `tests/` folder.
5. Keep your existing `.env`, `data/`, `.venv`, checkpoint and other files. They
   are not in this pack. Do not delete the database or generate a replacement key.
6. In a terminal in your project folder, configure the owner account:

```powershell
.\.venv\Scripts\python.exe setup_admin.py
```

Choose an owner email not already used by a nurse/doctor, then enter and confirm
its password. The script adds the owner settings and preserves encryption keys.
It stores a password hash, not the plaintext password. Run it again to change the
owner credentials; restart FastAPI afterward. Changed credentials revoke existing
owner sessions.

7. Start FastAPI in terminal one:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
```

8. Start Streamlit in terminal two:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open **http://127.0.0.1:8501**. No additional dependencies are needed beyond the
existing v2 requirements. Use one FastAPI worker without `--reload`.

## First test

1. Sign up as **Doctor**, using a new email/ID, such as `D-001`. Log in.
2. Sign up as **Nurse**, with another email and that doctor's registered ID.
3. The nurse sees **Awaiting doctor approval** and cannot access patients.
4. The doctor sees a warning about pending requests. Open **My nursing team →
   Review credentials**. Review the nurse's details, photo and ID-card image, then
   approve or reject. Passwords are never shown to the doctor.
5. Approval opens the nurse's team view automatically. The nurse can add patients
   with their own password. The doctor and approved teammates see the same patients.
6. Only the doctor can remove a patient, using their own password.
7. Log in with your owner email/password to view the read-only staff, patient-status,
   event and approval-audit tables. No vital readings or editing controls are provided.

Use separate browser profiles/private windows for simultaneous users, or log out
between accounts. Each staff member has their own login; it is not a shared account.

## Existing accounts and patients

Before changing a v2 database, the backend makes a consistent SQLite backup:

`data/hospital.before_roles_<timestamp>.sqlite3`

The transactional migration preserves accounts, password hashes, encrypted images,
patient records, statuses and events. Old sessions are invalidated, so log in again.

Existing accounts remain **nurses**, initially **Unassigned**. We do not guess their
doctor. Create a doctor account with a different email/ID. Log in as an existing
nurse, enter that doctor's ID, then approve the request from the doctor account.
Approval assigns the nurse's legacy patients and historical events to that team.
Active patients resume simulation; until approval, the records are preserved and
shown as UNASSIGNED to the owner, without active simulation.

Old acknowledgement times remain intact. Their actor displays **Legacy record**,
because the previous version did not record who clicked. New acknowledgements
record the person's name, staff ID, role and time; a second click does not replace
the first person's identity.

Rejected nurses may request another doctor. Approved nurses cannot switch teams
through this interface; transfers and revocation are outside this update.

## Permissions

| Action | Owner | Doctor | Approved nurse | Pending/rejected nurse |
| --- | --- | --- | --- | --- |
| All teams' patient statuses | Yes | No | No | No |
| Own-team vital readings | No | Yes | Yes | No |
| Add patient with own password | No | Yes | Yes | No |
| Remove patient with own password | No | Own team only | No | No |
| Acknowledge team alerts | No | Yes | Yes | No |
| Review/approve nurse requests | No | Requested doctor only | No | No |
| Own profile | Yes | Yes | Yes | Yes |
| Request a doctor | No | No | No | If not already pending |

Doctor signup does not perform medical-license verification. ID uploads are
stored for manual review; no QR, face recognition or automatic verification is added.
There is no public owner signup.

## Acknowledgement rule included

State changes are still logged. Entering ELEVATED/CRITICAL or worsening from
ELEVATED to CRITICAL requests acknowledgement. CRITICAL → ELEVATED and return to
NORMAL do not request another acknowledgement. Existing improvement events stop
counting as pending automatically. Earlier worsening alerts remain pending until
reviewed. No event history is deleted.

## Rollback

Stop both services and restore the pre-update source, `.env` and `data/` together.
Do not run the old nurse-only backend against the new role database: its permission
rules do not understand doctor teams. Protect backup files like the live database.
Keep the original encryption key; generating a new key cannot decrypt old images.

## Files included

Replace: `app.py`, `accounts.py`, `schemas.py`, `storage.py`, `service.py`,
`server.py`, `README.md`, `VERIFICATION.md`, `tests/test_system.py`,
`tests/test_dashboard.py`.

New: `alert_rules.py`, `setup_admin.py`, `tests/test_roles.py`, `UPDATE_ROLES.md`.

Model, simulator, encryption, configuration and other unchanged files are omitted.
