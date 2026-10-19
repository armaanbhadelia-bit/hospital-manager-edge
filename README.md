# PulseWard — hospital-centre monitoring prototype

A fresh Streamlit dashboard with an encrypted FastAPI/LSTM round trip.
The old login and dashboard are not used in this project. It opens directly
to the ward view. No hardcoded staff credentials or staff database are included.

## 1. Install (Windows / VS Code)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_local.py
```

If your installed version is Python 3.12, replace `py -3.11` with `py -3.12`.
The commands use the virtual environment's Python directly, so PowerShell
activation permissions do not need changing. PyTorch may take time to download.
Hadoop is not required by this prototype.

## 2. Start FastAPI

Keep this terminal running:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
```

If the old FastAPI process is already using port 8000, stop it with Ctrl+C first.
This project runs `server:app`, not the original `API_of_LSTM:app`.

## 3. Start the dashboard

Open a second terminal in the same folder:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open http://127.0.0.1:8501. Click **Load demo ward**, then enable **Run monitoring**
in the sidebar. Start with these fictional patients. Add/remove patients in
**Patient management**. Switch the sidebar source to **Manual readings** to send
a single set of values for a selected patient.

For macOS/Linux, create the environment with `python3 -m venv .venv` and use
`.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

## What is included

- Patient cards: heart rate, SpO2, respiratory rate, age, bed and model result.
- Up to 12 patients per browser session; synthetic updates every 3 seconds while
  the page is active. This is not a background monitoring daemon.
- Per-patient input history, last-sample times, stale and connection-error states.
- Alert events when a model result changes into ELEVATED or CRITICAL. Acknowledging
  an event does not change the current patient status. The log retains 100 events
  and displays the latest 10.
- AES-256-GCM request and response encryption with independently derived direction
  keys, random 96-bit nonces, integrity verification, a bearer API token, message
  freshness checks, and a persistent SQLite request-ID replay cache.
- Your supplied `telemetry_autoencoder.pth`, the same model architecture, feature
  order, normalization, repeated-snapshot input and score thresholds.
- No silently substituted model or fake fallback predictions. Service failures
  display OFFLINE; readings older than 15 seconds display STALE.

## Data flow and encryption boundary

```text
IoMT adapter (future) / simulator / manual values
    -> hospital-centre gateway (inside the Streamlit server for this prototype)
    -> encrypt request
    -> FastAPI: authenticate, decrypt, validate, run LSTM
    -> encrypt response
    -> centre gateway: decrypt, match patient/request, display in Streamlit
```

`gateway.send_reading(patient_id, vitals, measured_at)` is the reusable sender for
your future hospital-centre/IoMT adapter. `measured_at` is Unix time in seconds.
The actual IoMT protocol, device authentication and continuously running ingestion
service are not implemented. The simulator runs from an active browser session.

Encryption starts in the centre's Python process, not in the nurse's browser.
Streamlit must decrypt data to display it, and FastAPI must decrypt it to run the
model. For separate machines, configure HTTPS for both services; the browser-to-
Streamlit and IoMT-to-centre paths are separate transport boundaries. Only local
loopback HTTP is accepted by the gateway. No remote deployment has been performed.

`setup_local.py` creates a local `.env` containing the master key and bearer token
once; it will not overwrite an existing file. No secrets are included in this ZIP.
For a separate inference machine, securely provision the same two secrets there
and set `HOSPITAL_API_URL` on the centre to your HTTPS API URL. The FastAPI machine
needs the checkpoint and server-side source files. Never commit `.env` or copy
secrets into frontend JavaScript. This starter uses one centre identity; separate
centre keys, authorization and key rotation are future deployment work.

SQLite here stores only request IDs and arrival times for rejecting replays. It
is not a patient database. Patient metadata, readings and acknowledgements stay
in Streamlit session memory; closing/reloading a session or restarting the app can
lose them. Separate nurses' browser sessions are not synchronized.

## Model compatibility

The input order is `[heart_rate, oxygen_saturation, respiratory_rate, age]`.
As in your existing API, the normalized snapshot is repeated ten times before
inference. The model classifies reconstruction error as:

| Score | Existing label |
| --- | --- |
| `< 0.05` | NORMAL |
| `>= 0.05` and `< 0.2` | ELEVATED |
| `>= 0.2` | CRITICAL |

These thresholds are preserved for project compatibility; this rebuild does not
establish their clinical validity. It does not retrain the model or use a true
temporal window. The checkpoint is loaded on CPU with PyTorch's restricted
weights loader and a narrow allowlist for its NumPy normalization arrays.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

During preparation, all 14 tests passed: eight cryptography tests and six API
integration tests using the actual uploaded checkpoint. Every Python file also
passed syntax compilation. Missing integration-test dependencies produce explicit
skips, not passing API checks.

Streamlit AppTest also passed against a running local FastAPI service: demo ward
loading, encrypted monitoring with actual model results, alert acknowledgement,
manual submission, patient removal and patient addition. An unavailable API was
checked separately and produced OFFLINE states. These are functional checks;
no browser screenshot or deployment test was performed.

Test environment: Python 3.12, Streamlit 1.65.0, FastAPI 0.142.2, PyTorch 2.14.1,
NumPy 2.3.5 and cryptography 46.0.0. Compatible dependency ranges are supplied;
future versions within those ranges have not been separately tested.

Tests cover tampering, wrong keys, direction separation, freshness, random nonces,
and non-finite payloads; API tests cover the real-model encrypted round trip,
replays, expiry, invalid values, token checks and absence of a plaintext route.

## File guide

| File | Purpose |
| --- | --- |
| `app.py` | Replacement Streamlit dashboard, patient management and simulator |
| `server.py` | Encrypted FastAPI prediction endpoint |
| `inference.py` | Existing model architecture and inference behaviour |
| `gateway.py` | Hospital-centre sender and response matching |
| `secure_channel.py` | Authenticated request/response encryption |
| `config.py` | Local configuration and remote HTTPS restriction |
| `setup_local.py` | One-time local secret generation |
| `telemetry_autoencoder.pth` | Your uploaded checkpoint, copied unchanged |

Official references used: [Streamlit fragments](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment),
[Streamlit session state](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state),
and [cryptography AES-GCM](https://cryptography.io/en/45.0.4/hazmat/primitives/aead/).

This is a local project prototype, not a deployed or clinically validated hospital
monitoring system. Staff authentication, a shared patient database, real IoMT
ingestion, background monitoring and deployment controls are next-stage work.
