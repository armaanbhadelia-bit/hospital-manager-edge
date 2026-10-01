import streamlit as st
import hashlib
import time

st.set_page_config(page_title="Edge Node Login", page_icon="🔒")

# Initialize security state
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

# The UI
st.title("🏥 Hospital Manager - Edge Node")

if not st.session_state['logged_in']:
    st.markdown("### Secure Staff Authentication")
    
    # Check if we are currently in a lockout period BEFORE drawing inputs
    current_time = time.time()
    if current_time < st.session_state['lockout_time']:
        remaining = int(st.session_state['lockout_time'] - current_time)
        st.error(f"🚨 Too many failed attempts. System locked for {remaining} seconds.")
        # Create a live countdown effect
        time.sleep(1)
        st.rerun()
    else:
        # Reset attempts if the lockout just expired
        if st.session_state['failed_attempts'] >= 3:
            st.session_state['failed_attempts'] = 0

        # Draw the inputs only if not locked out
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
                    # Set the lockout timestamp 30 seconds into the future
                    st.session_state['lockout_time'] = time.time() + 30
                    st.rerun() # Instantly wipe the screen
                else:
                    st.error(f"Invalid credentials. Attempt {st.session_state['failed_attempts']}/3")
else:
    st.success("You are already authenticated.")
    if st.button("Go to Dashboard"):
        st.switch_page("pages/2_Dashboard.py")