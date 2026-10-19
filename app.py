"""Streamlit hospital-centre dashboard. No login in this first rebuild."""
import html
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from config import api_token, api_url, master_key
from gateway import send_reading

st.set_page_config(page_title='PulseWard · Hospital Centre', page_icon='🏥', layout='wide')
st.markdown('''<style>
.block-container {padding-top:2rem; max-width:1500px;}
[data-testid="stSidebar"] {border-right:1px solid #dce6eb;}
h1,h2,h3 {letter-spacing:-.035em;}
.eyebrow {color:#0d9488;font-size:12px;font-weight:700;letter-spacing:2px;}
.patient-top {display:flex;justify-content:space-between;align-items:center;gap:8px;}
.patient-name {font-size:19px;font-weight:650;color:#16324a;}
.patient-sub {font-size:13px;color:#64748b;margin:5px 0 20px;}
.badge {font-size:10px;font-weight:750;border-radius:20px;padding:6px 10px;white-space:nowrap;}
.normal {color:#047857;background:#d1fae5;}
.elevated {color:#92400e;background:#fef3c7;}
.critical {color:#b91c1c;background:#fee2e2;}
.waiting,.offline {color:#475569;background:#e2e8f0;}
.vitals {display:flex;justify-content:space-between;gap:8px;margin-bottom:10px;}
.vital-value {font-size:26px;font-weight:700;color:#16324a;}
.vital-label {font-size:11px;color:#64748b;}
</style>''', unsafe_allow_html=True)

defaults = {'patients': {}, 'history': {}, 'latest': {}, 'alerts': [],
            'monitoring': False, 'last_cycle': 0.0}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


def add_patient(name, age, bed, scenario):
    pid = 'P-' + uuid.uuid4().hex[:8].upper()
    st.session_state.patients[pid] = dict(name=name, age=age, bed=bed, scenario=scenario)
    st.session_state.history[pid] = []


def sample(patient):
    # Synthetic examples for exercising the pipeline, not physiological models.
    shifted = patient['scenario'] == 'Shifted readings'
    return {'heart_rate': round(random.uniform(150, 180) if shifted else random.uniform(65, 85), 1),
            'oxygen_saturation': round(random.uniform(80, 88) if shifted else random.uniform(96, 99), 1),
            'respiratory_rate': round(random.uniform(27, 35) if shifted else random.uniform(12, 18), 1),
            'age': patient['age']}


def exchange(item):
    pid, vitals = item
    measured_at = time.time()
    try:
        result = send_reading(pid, vitals, measured_at)
        return pid, {'vitals': vitals, 'measured_at': measured_at, 'received_at': time.time(),
                     'result': result, 'error': False}
    except Exception:
        # Do not show raw requests, tokens, or backend tracebacks in the UI.
        return pid, {'vitals': vitals, 'measured_at': measured_at,
                     'received_at': time.time(), 'result': None, 'error': True}


def record(pid, entry):
    previous = st.session_state.latest.get(pid, {}).get('result') or {}
    st.session_state.latest[pid] = entry
    history = st.session_state.history[pid]
    history.append({'time': datetime.fromtimestamp(entry['measured_at'], timezone.utc),
                    **entry['vitals']})
    del history[:-120]
    result = entry['result']
    if result and result['status'] in {'ELEVATED', 'CRITICAL'} and previous.get('status') != result['status']:
        st.session_state.alerts.insert(0, {'id': uuid.uuid4().hex, 'patient_id': pid,
                                         'time': entry['received_at'], 'status': result['status'],
                                         'acknowledged': False})
        del st.session_state.alerts[100:]


def displayed_status(entry):
    if not entry:
        return 'WAITING'
    if entry['error']:
        return 'OFFLINE'
    if time.time() - entry['measured_at'] > 15:
        return 'STALE'
    return entry['result']['status']


def clock(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime('%H:%M:%S UTC')


try:
    master_key()
    api_token()
    endpoint = api_url()
except RuntimeError as exc:
    st.title('Welcome to PulseWard')
    st.info(str(exc))
    st.code('python setup_local.py', language='bash')
    st.stop()

with st.sidebar:
    st.markdown('## 🏥 PulseWard')
    st.caption('HOSPITAL CENTRE · NURSE STATION')
    st.divider()
    st.markdown('**Reading source**')
    mode = st.radio('Choose a source', ['Simulator', 'Manual readings'], label_visibility='collapsed')
    st.caption('Synthetic readings only. No IoMT device is connected yet.')
    if mode == 'Simulator':
        st.toggle('Run monitoring', key='monitoring')
    else:
        st.session_state.monitoring = False
        st.caption('Use the manual reading form in Patient management.')
    st.divider()
    st.markdown('**Hospital-centre connection**')
    st.caption('AES-256-GCM encrypted requests and responses')
    st.caption('Polling every 3 seconds while this page is active.')
    st.divider()
    st.caption('Prototype · No staff login yet.\n\nPatients and readings belong to this browser session and reset when it ends.')

st.markdown('<div class="eyebrow">HOSPITAL CENTRE / LIVE OBSERVATION</div>', unsafe_allow_html=True)
st.title('Patient monitoring')
st.caption('One view of your ward. Follow readings, review model alerts, and keep patients in sight.')
st.info('Project prototype: NORMAL / ELEVATED / CRITICAL are your existing model labels; they are not validated clinical decisions.')

monitor_tab, patients_tab, connection_tab = st.tabs(['Ward overview', 'Patient management', 'Connection & setup'])

with patients_tab:
    st.subheader('Add a patient')
    with st.form('add_patient', clear_on_submit=True):
        a, b, c = st.columns([2, 1, 1])
        name = a.text_input('Patient label', placeholder='Use a fictional name or demo ID', max_chars=60)
        age = b.number_input('Age (years)', min_value=0, max_value=130, value=35)
        bed = c.text_input('Bed / room', placeholder='A-01', max_chars=20)
        scenario = st.selectbox('Simulator scenario', ['Typical readings', 'Shifted readings'])
        submitted = st.form_submit_button('Add patient', type='primary')
        if submitted:
            if not name.strip() or not bed.strip():
                st.error('Enter a patient label and bed / room.')
            elif len(st.session_state.patients) >= 12:
                st.error('This demo supports up to 12 patients per session.')
            elif any(p['bed'].casefold() == bed.strip().casefold() for p in st.session_state.patients.values()):
                st.error('That bed is already assigned.')
            else:
                add_patient(name.strip(), int(age), bed.strip(), scenario)
                st.rerun()
    if st.session_state.patients:
        labels = {pid: f"{p['bed']} · {p['name']} · {pid}" for pid, p in st.session_state.patients.items()}
        st.subheader('Manage an existing patient')
        selected = st.selectbox('Patient', list(labels), format_func=labels.get)
        patient = st.session_state.patients[selected]
        new_scenario = st.selectbox('Change simulator scenario', ['Typical readings', 'Shifted readings'],
                                    index=int(patient['scenario'] == 'Shifted readings'), key=f'scenario_{selected}')
        if new_scenario != patient['scenario']:
            patient['scenario'] = new_scenario
            st.rerun()
        if mode == 'Manual readings':
            with st.form('manual_reading'):
                x, y, z = st.columns(3)
                hr = x.number_input('Heart rate · bpm', 0.0, 350.0, 72.0)
                spo2 = y.number_input('SpO₂ · %', 0.0, 100.0, 98.0)
                resp = z.number_input('Respiratory rate · /min', 0.0, 150.0, 15.0)
                if st.form_submit_button('Encrypt and analyse', type='primary'):
                    with st.spinner('Waiting for the encrypted result…'):
                        pid, entry = exchange((selected, {'heart_rate': hr, 'oxygen_saturation': spo2,
                                                          'respiratory_rate': resp, 'age': patient['age']}))
                    record(pid, entry)
                    if entry['error']:
                        st.error('No result received. Check that FastAPI is running and both sides use the same configuration.')
                    else:
                        st.success(f"Model result: {entry['result']['status']}")
        with st.expander('Remove patient'):
            confirmed = st.checkbox('Remove this patient and their session history', key=f'remove_confirm_{selected}')
            if st.button('Remove patient', disabled=not confirmed):
                for collection in ['patients', 'history', 'latest']:
                    st.session_state[collection].pop(selected, None)
                st.session_state.alerts = [a for a in st.session_state.alerts if a['patient_id'] != selected]
                st.rerun()

with connection_tab:
    st.subheader('Your encrypted round trip')
    st.markdown('1. Hospital centre collects a reading.\n2. The gateway encrypts it.\n'
                '3. FastAPI authenticates and decrypts it, then runs your LSTM.\n'
                '4. FastAPI encrypts the result.\n5. The centre decrypts and displays it.')
    st.code(endpoint, language=None)
    st.caption('The encryption boundary starts at the Streamlit server / hospital-centre gateway. '
               'The browser and any future IoMT-to-centre connection need their own protected transport.')
    st.markdown('**Start the inference service in a separate terminal**')
    st.code('python -m uvicorn server:app --host 127.0.0.1 --port 8000', language='bash')
    st.caption('Configuration: .env. Never publish that file. The README explains remote connections and limitations.')

with monitor_tab:
    if not st.session_state.patients:
        st.subheader('Your ward is ready')
        st.write('Add your first patient in Patient management, or load three fictional patients to explore the dashboard.')
        if st.button('Load demo ward', type='primary'):
            for args in [('Demo patient 01', 30, 'A-01', 'Typical readings'),
                         ('Demo patient 02', 55, 'A-02', 'Typical readings'),
                         ('Demo patient 03', 78, 'A-03', 'Shifted readings')]:
                add_patient(*args)
            st.rerun()
    else:
        @st.fragment(run_every='3s')
        def ward():
            now = time.time()
            if mode == 'Simulator' and st.session_state.monitoring and now - st.session_state.last_cycle >= 2.8:
                st.session_state.last_cycle = now
                work = [(pid, sample(p)) for pid, p in st.session_state.patients.items()]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for pid, entry in pool.map(exchange, work):
                        record(pid, entry)
            statuses = {pid: displayed_status(st.session_state.latest.get(pid)) for pid in st.session_state.patients}
            metrics = st.columns(4)
            metrics[0].metric('Patients in ward', len(statuses))
            metrics[1].metric('Normal · model', sum(s == 'NORMAL' for s in statuses.values()))
            metrics[2].metric('Needs review · model', sum(s in {'ELEVATED', 'CRITICAL'} for s in statuses.values()))
            metrics[3].metric('Awaiting fresh result', sum(s in {'WAITING', 'OFFLINE', 'STALE'} for s in statuses.values()))
            if mode == 'Simulator' and not st.session_state.monitoring:
                st.warning('Monitoring paused. Turn on Run monitoring in the sidebar to send simulated readings.')
            if any(s == 'OFFLINE' for s in statuses.values()):
                st.error('Some readings have no result. Check FastAPI and the shared configuration; previous results are not shown as current.')
            st.caption('Latest model results · readings older than 15 seconds are marked STALE')
            status_filter = st.selectbox('Show patients', ['All patients', 'Needs review', 'Awaiting fresh result'])
            visible = [(pid, p) for pid, p in st.session_state.patients.items()
                       if status_filter == 'All patients'
                       or (status_filter == 'Needs review' and statuses[pid] in {'ELEVATED', 'CRITICAL'})
                       or (status_filter == 'Awaiting fresh result' and statuses[pid] in {'WAITING', 'OFFLINE', 'STALE'})]
            columns = st.columns(3)
            for i, (pid, p) in enumerate(visible):
                entry = st.session_state.latest.get(pid)
                status = statuses[pid]
                style = status.lower() if status in {'NORMAL', 'ELEVATED', 'CRITICAL'} else 'waiting'
                with columns[i % 3].container(border=True):
                    st.markdown(f'<div class="patient-top"><div class="patient-name">{html.escape(p["name"])}</div>'
                                f'<span class="badge {style}">{status}</span></div>'
                                f'<div class="patient-sub">Bed {html.escape(p["bed"])} · Age {p["age"]} · {pid}</div>',
                                unsafe_allow_html=True)
                    if entry:
                        v = entry['vitals']
                        st.markdown('<div class="vitals">' + ''.join(
                            f'<div><div class="vital-value">{v[key]:g}</div><div class="vital-label">{label}</div></div>'
                            for key, label in [('heart_rate', 'HEART RATE · bpm'), ('oxygen_saturation', 'SpO₂ · %'),
                                               ('respiratory_rate', 'RESP · /min')]) + '</div>', unsafe_allow_html=True)
                        st.caption(f"Last sample · {clock(entry['measured_at'])}")
                        if entry['result']:
                            st.caption(f"Last model score · {entry['result']['mse_loss']:.5f}")
                    else:
                        st.caption('Waiting for the first reading…')
            if not visible:
                st.info('No patients match this filter.')
            st.divider()
            chart_col, alerts_col = st.columns([1.7, 1])
            with chart_col:
                st.subheader('Reading history')
                ids = list(st.session_state.patients)
                chart_labels = {pid: st.session_state.patients[pid]['name'] for pid in ids}
                selected_chart = st.selectbox('Inspect a patient', ids, format_func=chart_labels.get)
                rows = st.session_state.history[selected_chart]
                if rows:
                    df = pd.DataFrame(rows).set_index('time')
                    feature = st.selectbox('Measurement', ['heart_rate', 'oxygen_saturation', 'respiratory_rate'],
                                          format_func={'heart_rate': 'Heart rate · bpm', 'oxygen_saturation': 'SpO₂ · %',
                                                       'respiratory_rate': 'Respiratory rate · /min'}.get)
                    st.line_chart(df[[feature]], color='#0D9488', height=240)
                    st.caption('Last 120 input readings · UTC. A plotted reading may still have failed inference.')
                else:
                    st.info('History will appear after the first reading.')
            with alerts_col:
                st.subheader('Model alert log')
                if not st.session_state.alerts:
                    st.caption('No model alerts recorded yet.')
                for alert in st.session_state.alerts[:10]:
                    p = st.session_state.patients.get(alert['patient_id'])
                    if not p:
                        continue
                    with st.container(border=True):
                        st.write(f"{alert['status']} · {p['name']}")
                        st.caption(clock(alert['time']))
                        if alert['acknowledged']:
                            st.caption('✓ Acknowledged · does not change patient status')
                        elif st.button('Acknowledge', key=alert['id']):
                            alert['acknowledged'] = True
                            st.rerun()
                if len(st.session_state.alerts) > 10:
                    st.caption(f'Showing the latest 10 of {len(st.session_state.alerts)} session alerts.')
        ward()
