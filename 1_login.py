import streamlit as st
import hashlib
import time

st.set_page_config(page_title="Edge Node Login", page_icon="🔒")

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'failed_attempts' not in st.session_state:
    st.session_state['failed_attempts'] = 0
if 'lockout_time' not in st.session_state:
    st.session_state['lockout_time'] = 0.0

correct_hash = hashlib.sha256("hospital123random_salt_8923".encode()).hexdigest()
MOCK_DB = {"admin": {"salt": "random_salt_8923", "hash": correct_hash}}

def verify_password(username, provided_password):
    if username in MOCK_DB:
        salt = MOCK_DB[username]["salt"]
        stored_hash = MOCK_DB[username]["hash"]
        calculated_hash = hashlib.sha256((provided_password + salt).encode()).hexdigest()
        return calculated_hash == stored_hash
    return False

st.title("🏥 Hospital Manager - Edge Node")

if not st.session_state['logged_in']:
    
    # 1. Create the master empty block for the entire login UI
    login_ui_block = st.empty()
    
    # 2. Check the lockout state first
    if time.time() < st.session_state['lockout_time']:
        
        # Vaporize the inputs instantly
        login_ui_block.empty()
        
        countdown_placeholder = st.empty()
        while time.time() < st.session_state['lockout_time']:
            remaining = int(st.session_state['lockout_time'] - time.time())
            countdown_placeholder.error(f"🚨 Too many failed attempts. System locked for {remaining} seconds.")
            time.sleep(1)
            
        countdown_placeholder.empty()
        st.session_state['failed_attempts'] = 0
        st.rerun()
        
    else:
        # 3. If not locked out, build the UI inside the container
        with login_ui_block.container():
            st.markdown("### Secure Staff Authentication")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            
            if st.button("Authenticate"):
                if verify_password(username, password):
                    st.session_state['logged_in'] = True
                    st.session_state['failed_attempts'] = 0
                    st.switch_page("pages/2_Dashboard.py")
                else:
                    st.session_state['failed_attempts'] += 1
                    
                    if st.session_state['failed_attempts'] >= 3:
                        st.session_state['lockout_time'] = time.time() + 30
                        login_ui_block.empty() # Destroy the container
                        st.rerun() # Restart the script to trigger the timer loop
                    else:
                        st.error(f"Invalid credentials. Attempt {st.session_state['failed_attempts']}/3")
else:
    st.success("You are already authenticated.")
    if st.button("Go to Dashboard"):
        st.switch_page("pages/2_Dashboard.py")