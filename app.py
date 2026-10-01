import streamlit as st
import hashlib
import time
import uuid
import random
# --- CRYPTOGRAPHY: Secure Password Hashing ---
# In a real app, this comes from a database. For the prototype, we hardcode a hashed password.
# The password for "admin" is "hospital123"

# We calculate the real hash dynamically here so it perfectly matches the math
correct_hash = hashlib.sha256("hospital123random_salt_8923".encode()).hexdigest()

MOCK_DB = {
    "admin": {
        "salt": "random_salt_8923",
        "hash": correct_hash 
    }
}

def generate_vitals(session_id):
    # Simulating a healthy patient with slight random fluctuations
    return {
        "timestamp": time.time(),
        "session_id": session_id,
        "vitals": {
            "bpm": random.randint(70, 85),
            "spo2": random.randint(96, 100),
            "resp_rate": random.randint(14, 18)
        }
    }

def verify_password(username, provided_password):
    if username in MOCK_DB:
        salt = MOCK_DB[username]["salt"]
        stored_hash = MOCK_DB[username]["hash"]
        
        # Combine password and salt, then hash it to check against the database
        password_salt_combo = provided_password + salt
        calculated_hash = hashlib.sha256(password_salt_combo.encode()).hexdigest()
        
        return calculated_hash == stored_hash
    return False

# --- INFOSEC: Brute-Force Protection & State Management ---
# Initialize session states to track logins and security lockouts

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'just_logged_in' not in st.session_state:
    st.session_state['just_logged_in'] = False
if 'failed_attempts' not in st.session_state:
    st.session_state['failed_attempts'] = 0
if 'lockout_time' not in st.session_state:
    st.session_state['lockout_time'] = 0


def login_screen():
    # ALL your login UI (Username, Password, Authenticate button) MUST be indented inside here
    st.title("🏥 Hospital Manager - Edge Node")
    st.markdown("### Secure Staff Authentication")
        
        # InfoSec: Check if the system is currently locked down due to brute-force attempts
    if time.time() < st.session_state['lockout_time']:
        remaining = int(st.session_state['lockout_time'] - time.time())
        st.error(f"🚨 SYSTEM LOCKED. Too many failed attempts. Try again in {remaining} seconds.")
        return
    
    # UI Inputs
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
        
    if st.button("Authenticate"):
        if verify_password(username, password):
            st.session_state['logged_in'] = True
            st.session_state['failed_attempts'] = 0 # Reset attempts on success
            st.session_state['just_logged_in'] = True # Trigger the notification
            if st.session_state['just_logged_in']:
                st.toast("Authentication Successful! Generating secure session keys...")
                st.session_state['just_logged_in'] = False
            time.sleep(1) # Fake loading for effect
            st.rerun()
        else:
            st.session_state['failed_attempts'] += 1
            st.error(f"Invalid credentials. Attempt {st.session_state['failed_attempts']}/3")
            
        # InfoSec: Trigger a 30-second lockout on 3 failed attempts
            if st.session_state['failed_attempts'] >= 3:
                st.session_state['lockout_time'] = time.time() + 30
                st.session_state['failed_attempts'] = 0
                st.rerun()
    
    # ... [rest of login code] ...

    
def main_dashboard():
    # ALL your monitoring UI (Active streams, Admit Patient, Vitals) MUST be indented inside here
    st.title("🏥 Active Ward Dashboard")
    st.success("Secure Connection Established")
        
    # Initialize the patient dictionary in session state if it doesn't exist
    if 'active_patients' not in st.session_state:
        st.session_state['active_patients'] = {}
    
    # INFOSEC: Enforce the 10 patient limit to prevent node overload/DDoS
    MAX_PATIENTS = 10
    current_count = len(st.session_state['active_patients'])
        
    st.markdown(f"### Active Telemetry Streams: {current_count} / {MAX_PATIENTS}")
        
    col1, col2 = st.columns(2)
        
    with col1:
        st.subheader("Admit Patient")
        patient_name = st.text_input("Patient Identifier (e.g., Bed 4, John Doe)")
            
        if st.button("Add Patient Stream"):
            if current_count >= MAX_PATIENTS:
                st.error("Maximum ward capacity reached. Cannot add more telemetry streams.")                
            elif not patient_name:
                st.warning("Please enter a patient identifier.")
            elif patient_name in st.session_state['active_patients']:
                st.warning("Patient identifier already exists.")
            else:
                # CRYPTOGRAPHY: Generate a unique secure sub-session ID for multiplexing
                session_id = str(uuid.uuid4())[:8]
                st.session_state['active_patients'][patient_name] = {
                    "session_id": session_id,
                    "status": "Connecting..."
                }
                st.rerun()
    
    with col2:
        # Display each patient and a button to discharge them
            for p_name, data in list(st.session_state['active_patients'].items()):
                with st.expander(f"🛏️ {p_name} (ID: {data['session_id']})", expanded=True):
                        
                    # 1. Fetch the generated JSON payload
                    payload = generate_vitals(data['session_id'])
                    v = payload["vitals"]
                        
                    # 2. Display it cleanly
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Heart Rate", f"{v['bpm']} BPM")
                    m2.metric("SpO2", f"{v['spo2']} %")
                    m3.metric("Resp Rate", f"{v['resp_rate']} /min")
                        
                    if st.button(f"Discharge {p_name}", key=f"del_{p_name}"):
                        del st.session_state['active_patients'][p_name]
                        st.rerun()
    
        # The continuous event loop (updates the UI every 2 seconds)
    time.sleep(2)
    st.rerun()
    
    st.divider()
    if st.button("Log Out"):
        st.session_state['logged_in'] = False
        st.rerun()
    # ... [rest of dashboard code] ...
    



# ==========================================
# MAIN APP ROUTING (The if/else flag!)
# ==========================================

# 1. Initialize the authentication flag if it doesn't exist yet
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

# 2. The Strict If/Else Routing
if st.session_state['logged_in'] == False:
    # If the flag is False, ONLY run the login screen
    login_screen()
else:
    # If the flag is True, ONLY run the main dashboard
    main_dashboard()