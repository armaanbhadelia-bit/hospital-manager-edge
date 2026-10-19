"""Nurse-only Streamlit dashboard. Run with python -m streamlit run app.py."""
import base64
import html
from datetime import datetime, timezone

import streamlit as st
from client import APIError, call
from config import api_token, api_url, master_key
from alert_rules import needs_ack

st.set_page_config(page_title='PulseWard · Hospital centre', page_icon='🏥', layout='wide')
st.markdown('''<style>
.block-container {padding-top:4.5rem; max-width:1450px;}
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
.waiting {color:#475569;background:#e2e8f0;}
.vitals {display:flex;justify-content:space-between;gap:8px;margin-bottom:10px;}
.vital-value {font-size:26px;font-weight:700;color:#16324a;}
.vital-label {font-size:11px;color:#64748b;}
</style>''', unsafe_allow_html=True)


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%d %b · %H:%M:%S UTC') if value else '—'


def clear_login(message=None):
    st.session_state.clear()
    if message:
        st.session_state['flash'] = message
    st.rerun()


def api(action, data=None):
    try:
        return call(action, data, st.session_state.get('session'))
    except APIError as exc:
        if exc.code == 401:
            clear_login('Your session ended. Please log in again.')
        st.error(str(exc))
        return None


try:
    master_key(); api_token(); api_url()
except RuntimeError as exc:
    st.title('Welcome to PulseWard')
    st.info(str(exc))
    st.code('python setup_local.py', language='bash')
    st.stop()

if 'session' not in st.session_state:
    st.markdown('<div class="eyebrow">PULSEWARD / HOSPITAL CENTRE</div>', unsafe_allow_html=True)
    st.title('Your team. Your patients.')
    st.caption('Doctors and approved nurses monitor their team. The owner has a separate read-only view.')
    if 'flash' in st.session_state:
        st.success(st.session_state.pop('flash'))
    if st.session_state.pop('signup_done', False):
        st.session_state['auth_view'] = 'Log in'
    view = st.radio('Account', ['Log in', 'Create account'], horizontal=True, key='auth_view')
    if view == 'Log in':
        left, _ = st.columns([1, 1])
        with left, st.form('login', clear_on_submit=True):
            email = st.text_input('Email', max_chars=254)
            password = st.text_input('Password', type='password', max_chars=128)
            if st.form_submit_button('Log in', type='primary'):
                try:
                    result = call('login', {'email': email, 'password': password})
                    st.session_state['session'] = result['session']
                    st.session_state['profile'] = result['profile']
                    st.rerun()
                except APIError as exc:
                    st.error(str(exc))
    else:
        signup_role = st.radio('Sign up as', ['Doctor', 'Nurse'], horizontal=True)
        with st.form('signup'):
            st.subheader('Create your ' + signup_role.lower() + ' account')
            a, b = st.columns(2)
            name = a.text_input('Full name', max_chars=80)
            staff_id = b.text_input(signup_role + ' ID', max_chars=40, help='Letters, numbers, hyphens and underscores.')
            doctor_id = st.text_input('Your doctor’s registered ID', max_chars=40) if signup_role == 'Nurse' else None
            email = a.text_input('Email', max_chars=254)
            phone = b.text_input('Phone number', max_chars=24)
            photo = a.file_uploader('Profile photo', type=['png', 'jpg', 'jpeg'])
            id_card = b.file_uploader('ID-card image', type=['png', 'jpg', 'jpeg'])
            st.caption('PNG/JPEG, up to 2 MB each. The ID card is stored only; QR and identity verification are future features.')
            password = a.text_input('Choose password', type='password', max_chars=128, help='At least 10 characters.')
            confirm = b.text_input('Confirm password', type='password', max_chars=128)
            if st.form_submit_button('Create account', type='primary'):
                if password != confirm:
                    st.error('The passwords do not match.')
                elif len(password) < 10:
                    st.error('Choose a password with at least 10 characters.')
                elif photo is None or id_card is None:
                    st.error('Upload both your profile photo and ID-card image.')
                elif photo.size > 2_000_000 or id_card.size > 2_000_000:
                    st.error('Each image must be under 2 MB.')
                else:
                    try:
                        call('signup', {'role': signup_role.lower(), 'name': name, 'staff_id': staff_id,
                                        'doctor_id': doctor_id, 'email': email,
                                        'phone': phone, 'password': password,
                                        'photo': base64.b64encode(photo.getvalue()).decode(),
                                        'id_card': base64.b64encode(id_card.getvalue()).decode()})
                        st.session_state['signup_done'] = True
                        st.session_state['flash'] = ('Your account is ready. Log in with your email and password.' if signup_role == 'Doctor'
                                                     else 'Account created. Log in to see your doctor-approval status.')
                        st.rerun()
                    except APIError as exc:
                        st.error(str(exc))
    st.stop()

profile = st.session_state['profile']
state = api('account_state')
if state is None:
    st.stop()
profile.update(state)
role = profile['role']
with st.sidebar:
    st.markdown('## 🏥 PulseWard')
    if profile.get('photo'):
        st.image(base64.b64decode(profile['photo']), width=80)
    st.write(profile['name'])
    st.caption(f"{role.title()} · {profile['staff_id']}")
    st.caption(profile['email'])
    st.divider()
    st.markdown('**Owner overview**' if role == 'admin' else '**Your doctor team**')
    st.caption('Automatic simulated readings. Monitoring continues while the backend is running—even when this page is closed.')
    st.divider()
    if st.button('Log out', width='stretch'):
        try:
            call('logout', session=st.session_state['session'])
        except APIError:
            pass
        clear_login()
    st.caption('Project prototype · fake patients · model-generated status labels')

st.markdown('<div class="eyebrow">HOSPITAL CENTRE / LIVE OBSERVATION</div>', unsafe_allow_html=True)
st.title('Hospital overview' if role == 'admin' else 'Our patients')
st.caption('Read-only oversight · status only' if role == 'admin' else 'Live readings and shared alerts for your doctor’s team.')
if 'flash' in st.session_state:
    st.success(st.session_state.pop('flash'))

if role == 'nurse' and profile['approval_status'] != 'approved':
    status = profile['approval_status']
    if status == 'pending':
        st.warning('Awaiting doctor approval. Patient access will open after approval.')
        st.write('Requested doctor: ' + str(profile.get('doctor_name') or profile.get('doctor_staff_id') or 'Assigned doctor'))
    else:
        st.info('Choose your doctor to request team access.' if status == 'unassigned' else 'Your request was rejected. You may submit another request.')
        if status == 'unassigned':
            st.caption('Your earlier account and patient records are preserved. Approval assigns your previous patients to the doctor’s team.')
        with st.form('request_team'):
            doctor_id = st.text_input('Doctor’s registered ID')
            if st.form_submit_button('Request team access', type='primary'):
                if api('request_team', {'doctor_id': doctor_id}) is not None:
                    st.session_state['profile'] = api('profile')
                    st.rerun()
    @st.fragment(run_every='3s')
    def approval_watch():
        latest = api('account_state')
        if latest and latest['approval_status'] != status:
            st.session_state['profile'] = api('profile')
            st.rerun()
        st.caption('Approval status updates automatically.')
    approval_watch()
    st.stop()


def render_events(owner=False):
    st.subheader('Changes only')
    st.caption('State changes are logged. Improvements do not request a new acknowledgement.')
    before = st.session_state.get('events_before')
    result = api('admin_events' if owner else 'events', {'before_id': before})
    if result is None:
        return
    events = result['events']
    names = {'DEVICE_CONNECTED': 'Sensor connected', 'DEVICE_DISCONNECTED': 'Sensor disconnected',
             'ELEVATED': 'Changed to elevated', 'CRITICAL': 'Changed to critical',
             'RETURNED_NORMAL': 'Returned to normal', 'INFERENCE_UNAVAILABLE': 'Model connection unavailable',
             'INFERENCE_RESTORED': 'Model connection restored'}
    rows = []
    for e in events:
        row = {'Time (UTC)': timestamp(e['occurred_at']), 'Patient': e['patient_name'], 'Bed': e['bed'],
               'Event': names.get(e['kind'], e['kind']),
               'Review': 'Acknowledged' if e['acknowledged_at'] else 'Pending' if needs_ack(e) else '—',
               'Acknowledged by': ((e['acknowledged_by'] + ' · ' + e['acknowledged_by_id']) if e['acknowledged_by']
                                   else 'Legacy record' if e['acknowledged_at'] else '—'),
               'Acknowledged at': timestamp(e['acknowledged_at']),
               'Patient record': 'Removed' if e['removed_at'] else 'Active'}
        if owner:
            row['Doctor'] = e['doctor_name'] or 'Unassigned'
        rows.append(row)
    if rows:
        st.dataframe(rows, hide_index=True, width='stretch')
    else:
        st.info('No events yet.')
    pending = {e['id']: f"{e['patient_name']} · {names.get(e['kind'])} · {timestamp(e['occurred_at'])}"
               for e in events if needs_ack(e) and not e['acknowledged_at']}
    if pending and not owner:
        event_id = st.selectbox('Alert to acknowledge', list(pending), format_func=pending.get)
        if st.button('Acknowledge alert'):
            if api('acknowledge', {'event_id': event_id}) is not None:
                st.rerun()
    a, b = st.columns(2)
    if a.button('Latest events', disabled=before is None):
        st.session_state.pop('events_before', None); st.rerun()
    if b.button('Older events', disabled=not result['has_more']):
        st.session_state['events_before'] = events[-1]['id']; st.rerun()


if role == 'admin':
    st.info('Spectator access. This account cannot add/remove patients, approve nurses, or acknowledge alerts.')
    owners, logs, approvals = st.tabs(['Staff & patients', 'Event log', 'Approval audit'])
    with owners:
        @st.fragment(run_every='3s')
        def owner_overview():
            data = api('admin_overview')
            if data is None:
                return
            a, b, c = st.columns(3)
            a.metric('Doctors', sum(s['role'] == 'doctor' for s in data['staff']))
            b.metric('Nurses', sum(s['role'] == 'nurse' for s in data['staff']))
            c.metric('Active patients', len(data['patients']))
            st.subheader('Doctors and nurses')
            staff_rows = [{'Name': s['name'], 'Staff ID': s['staff_id'], 'Role': s['role'].title(),
                           'Email': s['email'], 'Doctor': s['doctor_name'] or '—',
                           'Doctor ID': s['doctor_staff_id'] or '—', 'Approval': s['approval_status'].title()}
                          for s in data['staff']]
            st.dataframe(staff_rows, hide_index=True, width='stretch')
            st.subheader('Patients · status only')
            patient_rows = [{'Patient': p['name'], 'Patient ID': p['id'], 'Bed': p['bed'],
                             'Doctor': p['doctor_name'] or 'Unassigned', 'Doctor ID': p['doctor_staff_id'] or '—',
                             'Added by': p['added_by'], 'Status': p['status']} for p in data['patients']]
            st.dataframe(patient_rows, hide_index=True, width='stretch')
            st.caption('Updated · ' + timestamp(data['updated_at']))
        owner_overview()
    with logs:
        @st.fragment(run_every='3s')
        def owner_events():
            render_events(owner=True)
        owner_events()
    with approvals:
        @st.fragment(run_every='3s')
        def owner_approvals():
            before = st.session_state.get('audit_before')
            result = api('admin_audit', {'before_id': before})
            if result:
                labels = {'TEAM_REQUESTED': 'Team requested', 'NURSE_APPROVED': 'Nurse approved', 'NURSE_REJECTED': 'Nurse rejected'}
                rows = [{'Time (UTC)': timestamp(e['occurred_at']), 'Action': labels.get(e['action'], e['action']),
                         'Nurse': e['nurse_name'], 'Nurse ID': e['nurse_id'],
                         'Performed by': e['decision_by'], 'Staff ID': e['decision_by_id']} for e in result['audit']]
                st.dataframe(rows, hide_index=True, width='stretch')
                if st.button('Latest decisions', disabled=before is None):
                    st.session_state.pop('audit_before', None); st.rerun()
                if st.button('Older decisions', disabled=not result['has_more']):
                    st.session_state['audit_before'] = result['audit'][-1]['id']; st.rerun()
        owner_approvals()
    st.stop()

if role == 'doctor':
    overview, manage, log, team_tab, account = st.tabs(['Live ward', 'Patient management', 'Event log', 'My nursing team', 'My profile'])
else:
    overview, manage, log, account = st.tabs(['Live ward', 'Patient management', 'Event log', 'My profile'])

with overview:
    @st.fragment(run_every='3s')
    def live_ward():
        snapshot = api('dashboard')
        if snapshot is None:
            st.warning('Live view unavailable. No previous readings are being presented as current.')
            return
        patients = snapshot['patients']
        if role == 'doctor' and snapshot['pending_requests']:
            st.warning(f"{snapshot['pending_requests']} nurse request(s) pending. Open My nursing team to review credentials.")
        stats = st.columns(4)
        stats[0].metric('Team patients', len(patients))
        stats[1].metric('Normal · model', sum(p['status'] == 'NORMAL' for p in patients))
        stats[2].metric('Needs review · model', sum(p['status'] in {'ELEVATED', 'CRITICAL'} for p in patients))
        stats[3].metric('Unacknowledged alerts', snapshot['pending_alerts'])
        st.caption('Automatic updates · ' + timestamp(snapshot['updated_at']))
        if not patients:
            st.info('Your ward is empty. Add a patient in Patient management; their readings start automatically.')
            return
        filter_by = st.selectbox('Show', ['All my patients', 'Needs review', 'Connection issues'])
        visible = [p for p in patients if filter_by == 'All my patients'
                   or (filter_by == 'Needs review' and p['status'] in {'ELEVATED', 'CRITICAL'})
                   or (filter_by == 'Connection issues' and p['status'] not in {'NORMAL', 'ELEVATED', 'CRITICAL'})]
        columns = st.columns(3)
        for i, p in enumerate(visible):
            status = p['status']
            css = status.lower() if status in {'NORMAL', 'ELEVATED', 'CRITICAL'} else 'waiting'
            with columns[i % 3].container(border=True):
                st.markdown(f'<div class="patient-top"><div class="patient-name">{html.escape(p["name"])}</div>'
                            f'<span class="badge {css}">{status}</span></div>'
                            f'<div class="patient-sub">Bed {html.escape(p["bed"])} · Age {p["age"]} · {p["id"]}</div>', unsafe_allow_html=True)
                if p['vitals']:
                    v = p['vitals']
                    st.markdown('<div class="vitals">' + ''.join(
                        f'<div><div class="vital-value">{v[key]:g}</div><div class="vital-label">{label}</div></div>'
                        for key, label in [('heart_rate', 'HEART RATE · bpm'), ('oxygen_saturation', 'SpO₂ · %'),
                                           ('respiratory_rate', 'RESP · /min')]) + '</div>', unsafe_allow_html=True)
                    st.caption('Last sample · ' + timestamp(p['measured_at']))
                else:
                    descriptions = {'DISCONNECTED': 'The simulated sensor is unplugged.',
                                    'WAITING': 'Waiting for the next automatic reading…',
                                    'OFFLINE': 'The model service did not return a valid result.',
                                    'STALE': 'No fresh result. Check the backend connection.'}
                    st.caption(descriptions.get(status, status))
                with st.expander('Simulated sensor'):
                    st.caption('Use this to demonstrate a sensor being unplugged or reconnected.')
                    label = 'Disconnect sensor' if p['connected'] else 'Reconnect sensor'
                    if st.button(label, key='device_' + p['id']):
                        if api('device', {'patient_id': p['id'], 'connected': not bool(p['connected'])}) is not None:
                            st.rerun()
        if not visible:
            st.info('No patients match this filter.')
    live_ward()

with manage:
    st.subheader('Add a patient')
    st.caption('The patient is assigned to your doctor’s team. Their fake sensor starts automatically. Adult simulation: ages 18–100.')
    with st.form('add_patient', clear_on_submit=True):
        a, b, c = st.columns([2, 1, 1])
        name = a.text_input('Patient name / label', max_chars=80)
        age = b.number_input('Age', min_value=18, max_value=100, value=35)
        bed = c.text_input('Bed / room', max_chars=20)
        confirmation = st.text_input('Your password to add this patient', type='password', max_chars=128)
        if st.form_submit_button('Add patient', type='primary'):
            if api('add_patient', {'name': name, 'age': int(age), 'bed': bed, 'password': confirmation}) is not None:
                st.session_state['flash'] = 'Patient added. Automatic readings will appear in Live ward.'
                st.rerun()
    if role == 'doctor':
        st.divider()
        st.subheader('Remove a patient')
        current = api('dashboard')
        if current and current['patients']:
            labels = {p['id']: f"{p['bed']} · {p['name']}" for p in current['patients']}
            with st.form('remove_patient', clear_on_submit=True):
                pid = st.selectbox('Patient to remove', list(labels), format_func=labels.get)
                password = st.text_input('Your password to remove this patient', type='password', max_chars=128)
                agreed = st.checkbox('Remove from active monitoring and stop their simulated readings')
                st.caption('Past change events remain in your event log. Raw reading history is never stored.')
                if st.form_submit_button('Remove patient'):
                    if not agreed:
                        st.error('Confirm removal using the checkbox.')
                    elif api('remove_patient', {'patient_id': pid, 'password': password}) is not None:
                        st.session_state['flash'] = 'Patient removed from active monitoring.'
                        st.rerun()
        else:
            st.caption('No active patients to remove.')
    else:
        st.caption('Only your doctor can remove a patient. You can add patients and monitor the team here.')

with log:
    @st.fragment(run_every='3s')
    def event_log():
        render_events()
    event_log()

if role == 'doctor':
    with team_tab:
        @st.fragment(run_every='3s')
        def nursing_team():
            data = api('team')
            if data is None:
                return
            pending = [n for n in data['nurses'] if n['approval_status'] == 'pending']
            st.subheader('Nursing team')
            st.caption('Your doctor ID: ' + profile['staff_id'] + ' · Give this ID to nurses who request to join.')
            if pending:
                st.warning(f'{len(pending)} nurse request(s) awaiting your decision.')
                choices = {n['account_id']: n['name'] + ' · ' + n['staff_id'] for n in pending}
                selected = st.selectbox('Pending nurse request', list(choices), format_func=choices.get)
                if st.button('Review credentials'):
                    st.session_state['review_nurse_id'] = selected
                review_id = st.session_state.get('review_nurse_id')
                if review_id in choices:
                    credentials = api('nurse_request', {'account_id': review_id})
                    if credentials:
                        with st.container(border=True):
                            st.subheader(credentials['name'])
                            st.write('Nurse ID: ' + credentials['staff_id'])
                            st.write('Email: ' + credentials['email'])
                            st.write('Phone: ' + credentials['phone'])
                            left, right = st.columns(2)
                            left.image(base64.b64decode(credentials['photo']), caption='Profile photo', width=180)
                            right.image(base64.b64decode(credentials['id_card']), caption='Uploaded ID card', width=400)
                            st.caption('Review these uploaded details yourself. There is no automatic ID, QR or face verification.')
                            approve, reject = st.columns(2)
                            decision = None
                            if approve.button('Approve nurse', type='primary'):
                                decision = 'approve'
                            if reject.button('Reject nurse'):
                                decision = 'reject'
                            if decision:
                                result = api('review_nurse', {'account_id': review_id, 'decision': decision})
                                if result is not None:
                                    st.session_state.pop('review_nurse_id', None)
                                    st.session_state['flash'] = 'Nurse approved.' if decision == 'approve' else 'Nurse request rejected.'
                                    st.rerun()
            else:
                st.success('No pending nurse requests.')
            if data['nurses']:
                rows = [{'Name': n['name'], 'Nurse ID': n['staff_id'], 'Email': n['email'], 'Phone': n['phone'],
                         'Approval': n['approval_status'].title(), 'Reviewed at': timestamp(n['reviewed_at'])}
                        for n in data['nurses']]
                st.dataframe(rows, hide_index=True, width='stretch')
            else:
                st.info('No nurses have requested to join yet.')
        nursing_team()

with account:
    st.subheader('My staff profile')
    a, b = st.columns([1, 3])
    a.image(base64.b64decode(profile['photo']), width=150)
    b.write('**' + profile['name'].replace('*', '') + '**')
    b.write(role.title() + ' ID: ' + profile['staff_id'])
    b.write('Email: ' + profile['email'])
    b.write('Phone: ' + profile['phone'])
    st.caption('Your ID-card image is stored for future project features. It is not used for verification or login.')
    if st.button('View my saved ID card'):
        result = api('profile')
        if result:
            st.image(base64.b64decode(result['id_card']), width=500)
