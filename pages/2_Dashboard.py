import streamlit as st
import time
import uuid
import random
import json
from cryptography.fernet import Fernet
import hashlib

st.set_page_config(page_title="Active Ward", page_icon="🏥")

# INFOSEC BOUNCER
if 'logged_in' not in st.session_state or not st.session_state['logged_in']:
    st.error("🚨 Unauthorized Access. Please log in first.")
    st.stop() 

# --- CRYPTO & DATA LOGIC ---
if 'aes_key' not in st.session_state:
    st.session_state['aes_key'] = Fernet.generate_key()
cipher_suite = Fernet(st.session_state['aes_key'])

def generate_vitals(session_id):
    return {
        "timestamp": time.time(),
        "session_id": session_id,
        "vitals": {"bpm": random.randint(70, 85), "spo2": random.randint(96, 100), "resp_rate": random.randint(14, 18)}
    }

def encrypt_payload(vitals_dict):
    json_bytes = json.dumps(vitals_dict).encode('utf-8')
    return cipher_suite.encrypt(json_bytes)

# --- DASHBOARD UI ---
st.title("🏥 Active Ward Dashboard")
st.success("Secure Connection Established")

if 'active_patients' not in st.session_state:
    st.session_state['active_patients'] = {}

MAX_PATIENTS = 20
current_count = len(st.session_state['active_patients'])
st.markdown(f"### Active Telemetry Streams: {current_count} / {MAX_PATIENTS}")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Admit Patient")
    patient_name = st.text_input("Patient Identifier")
    if st.button("Add Patient Stream"):
        if current_count < MAX_PATIENTS and patient_name and patient_name not in st.session_state['active_patients']:
            st.session_state['active_patients'][patient_name] = {"session_id": str(uuid.uuid4())[:8]}
            st.rerun()

# ---------------------------------------------------------
# THE FIX: Isolate the loop using a Streamlit Fragment
# This replaces the need for st.empty() and time.sleep()
# ---------------------------------------------------------



@st.dialog("🔐 Authorization Required")
def secure_discharge_dialog(patient_name):
    st.warning(f"You are requesting to terminate the telemetry stream for **{patient_name}**.")
    password_attempt = st.text_input("Enter Admin Password to confirm", type="password")
    
    if st.button("Authorize Discharge"):
        # CRYPTOGRAPHY: Hash the input and check it against the known admin hash
        correct_hash = hashlib.sha256("hospital123random_salt_8923".encode()).hexdigest()
        calculated_hash = hashlib.sha256((password_attempt + "random_salt_8923").encode()).hexdigest()
        
        if calculated_hash == correct_hash:
            del st.session_state['active_patients'][patient_name]
            st.rerun() # This instantly closes the pop-up and updates the dashboard
        else:
            st.error("Invalid password. Security anomaly logged.")

@st.fragment(run_every=2)
def active_monitoring_panel():
    st.subheader("Active Monitoring")
    if not st.session_state['active_patients']:
        st.info("No active patient streams.")
        return

    for p_name, data in list(st.session_state['active_patients'].items()):
        with st.expander(f"🛏️ {p_name} (ID: {data['session_id']})", expanded=True):
            payload = generate_vitals(data['session_id'])
            v = payload["vitals"]
            
            m1, m2, m3 = st.columns(3)
            m1.metric("BPM", v['bpm'])
            m2.metric("SpO2", f"{v['spo2']}%")
            m3.metric("Resp", v['resp_rate'])
            
            encrypted_data = encrypt_payload(payload)
            st.caption("🔒 Encrypted Transmission Payload:")
            st.code(encrypted_data.decode('utf-8'), language="text")
            
            if st.button(f"Discharge {p_name}", key=f"del_{p_name}"):
                secure_discharge_dialog(p_name)

with col2:
    active_monitoring_panel()

st.divider()
if st.button("Log Out"):
    st.session_state['logged_in'] = False
    st.switch_page("1_Login.py")