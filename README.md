# PulseWard — doctor teams and owner oversight

**Upgrading? Start with `UPDATE_ROLES.md`.** This update relies on your existing v2
project. It adds three roles and changes patient ownership to a doctor's team.

- **Owner/admin:** configured locally with `setup_admin.py`; read-only staff/team
  tables, patient statuses, event history and approval audit. No vital readings,
  patient actions, nurse approvals or acknowledgements.
- **Doctor:** signs up using identity/contact details, photo, ID-card image and
  password. Reviews nurses who requested their ID; monitors/adds team patients,
  acknowledges alerts and removes team patients with password confirmation.
- **Nurse:** signs up under a registered doctor ID and waits for approval. Approved
  nurses monitor the whole team, acknowledge alerts and add patients using their
  own password. Nurses cannot remove patients.

Everyone logs in with email/password. The backend derives role/team from the
session, not a user-provided role. Patients from another doctor team are blocked.
Pending credentials can be reviewed only by the doctor handling that request.
There is no public owner signup, medical-license verification, QR/face recognition,
self-service password recovery or team-transfer workflow.

## Run

Preserve `.env` and `data/`. Configure owner credentials once with:

```powershell
.\.venv\Scripts\python.exe setup_admin.py
```

Terminal one:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Terminal two:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open http://127.0.0.1:8501. Use a single backend worker without `--reload`.
The simulator continues while FastAPI runs, even with all browsers closed.

## Existing data

The first startup backs up and migrates the old database. Existing nurses become
unassigned until they request a doctor and receive approval. Their patients and
historical events are preserved and assigned to that team on approval. Old
acknowledgements retain their time but cannot retrospectively identify who clicked.
Full upgrade and rollback details are in `UPDATE_ROLES.md`.

## Monitoring and privacy

Synthetic adult-patient baselines, noise and smooth episodes remain automatic.
The local demo supports 12 active patients per doctor team, 48 overall, ages 18–100.
There is no manual input or global monitoring toggle; sensor controls demonstrate
unplugging/reconnection. Results update about every three seconds; readings older
than 15 seconds are marked stale and hidden. Model outages are distinct from unplugging.

The existing LSTM checkpoint, normalization and snapshot inference are unchanged.
Thresholds remain below 0.05 NORMAL, 0.05–below 0.2 ELEVATED, and 0.2 or above
CRITICAL. These are project labels, not clinically validated decisions.

Encrypted HTTP commands and predictions use the existing AES-GCM channel, fresh
nonces, timestamp checks, replay protection and response matching. Components
share the FastAPI process in this local prototype. Remote deployment requires
HTTPS for both API and browser transport; no deployment is included.

`data/hospital.sqlite3` stores staff, approvals, patient assignments, last status
categories, events and acknowledgement identities. The historical table name
`nurses` is retained internally but now holds all three account roles. Images are
encrypted blobs; passwords are salted scrypt hashes; sessions are stored as token
hashes. Contact details, patient metadata and events are ordinary SQLite values;
the complete database is not encrypted.

Only the latest reading per active patient is kept in RAM. Individual vital readings
and model scores are not saved. Same-status repetitions create no event, and initial
NORMAL creates no event. Improvements are logged but do not require acknowledgement.
An acknowledgement records the first staff member's name/ID and time; it does not
change patient status or erase earlier alerts. Doctor removal stops monitoring and
retains historical records, marked removed.

Keep `.env` with the matching database and protect both, including backups. The
image encryption key cannot be regenerated to recover existing images. The old
nurse-only application must not be run against the role-upgraded database.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use temporary data and secrets, not your accounts. They cover migration,
approvals, role boundaries, team sharing, encrypted inference, owner responses
without vital data, background monitoring and personal acknowledgement. See
`VERIFICATION.md` for results and testing limits.
