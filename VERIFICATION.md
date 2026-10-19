# Verification — role/team update

Tested on 8 October 2026 in the build environment.

| Group | Result |
| --- | --- |
| Monitoring, security, privacy and persistence tests adapted to teams | 22 passed |
| Role, approval, migration and acknowledgement-attribution tests | 7 passed |
| Real HTTP + Streamlit three-role workflow | 1 passed |
| Total | 30 passed |

The UI workflow exercises doctor and nurse signup with both image uploads; pending
nurse access; doctor review/approval; nurse patient creation; shared visibility;
real encrypted inference with the original model; personal acknowledgement;
status-only owner view; doctor removal; and monitoring after all users log out.

Backend tests cover rejection/reapplication, wrong-doctor approval, admin mutation
attempts, forbidden raw-data access by admin, password checks, first-acknowledger
preservation and event counts excluding improvements.

Migration tests build a real v2-schema database with an account, encrypted images,
patient, event and session. They verify a readable pre-migration backup, preserved
values, invalidated old sessions, doctor assignment on approval, preserved legacy
acknowledgement and idempotent restart without another migration backup.

All Python files pass compilation. The checkpoint and inference file are unchanged.
The ZIP contains only changed/new files, with no .env, database, model, virtual
environment, bytecode or test data.

Limits: functional tests ran on Linux with Streamlit AppTest. Windows commands and
the Windows file-lock branch have not been run on the user's PC. No manual-browser
screenshot, production-load test or clinical validation is claimed.
