import streamlit as st
import ai_engine
import azure.cognitiveservices.speech as speechsdk

# --- UI Setup ---
st.set_page_config(page_title="MedSync AI", layout="wide")
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to:", [
    "Patient: Voice Triage", 
    "Doctor: Dictation (Mode A)", 
])

# ==========================================
# PAGE 1: PATIENT VOICE TRIAGE
# ==========================================
if page == "Patient: Voice Triage":
    st.title("🎙️ AI Triage Assistant")
    
    # 1. Initialize Triage Session State with EXACT conversation.py prompt
    if "triage_history" not in st.session_state:
        system_prompt = """
You are an AI triage assistant for a healthcare application. 
Your goal is to ask targeted questions one at a time to gather information about the patient's chief complaint.
DO NOT give medical advice, diagnoses, or treatment recommendations.
CRITICAL RULE: You must start every single response with the exact prefix '[doctor] '.

You must ask about:
1. Chief complaint (in the patient’s own words)
2. Onset, duration, and severity
3. Associated symptoms
4. Past medical history
5. Current medications and allergies
6. Any recent events (last 24 hours)
7. Any relevant social or family history

When you have gathered enough information to draft a SOAP note, end your last response with "[COMPLETE]".
"""
        st.session_state.triage_history = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": "[doctor] Hello, I am the triage assistant. Please state your name and what brings you in today."}
        ]
    
    if "triage_complete" not in st.session_state:
        st.session_state.triage_complete = False

    # 2. Display Chat History
    for msg in st.session_state.triage_history:
        if msg["role"] != "system":
            # Format nicely for the UI
            with st.chat_message(msg["role"]):
                st.write(msg["content"].replace("[doctor] ", "").replace("[patient] ", ""))

    # 3. Voice Interaction Logic
    if not st.session_state.triage_complete:
        st.write("---")
        if st.button("🎤 Click to Speak", use_container_width=True):
            result = ai_engine.recognize_from_microphone()

            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                user_text = result.text
                
                # Manual Stop Logic
                if "stop" in user_text.lower():
                    st.warning("Session ended by user. Saving data...")
                    success, db_msg = ai_engine.save_transcript_to_db(st.session_state.triage_history)
                    if success:
                        st.success(f"Manually saved to DB! (UUID: {db_msg})")
                    else:
                        st.error(f"Failed to save to DB: {db_msg}")
                    st.session_state.triage_complete = True
                    # st.rerun() # <-- Comment this out so the message doesn't disappear!

                # Add User Message to History
                formatted_user_input = f"[patient] {user_text.lower()}"
                st.session_state.triage_history.append({"role": "user", "content": formatted_user_input})

                # Call AI with full history
                with st.spinner("AI is thinking..."):
                    ai_response = ai_engine.call_azure_chat(st.session_state.triage_history)
                
                st.session_state.triage_history.append({"role": "assistant", "content": ai_response})

                # Check for Completion Tag
                if "[COMPLETE]" in ai_response:
                    st.session_state.triage_history[-1]["content"] = ai_response.replace("[COMPLETE]", "").strip()
                    success, db_msg = ai_engine.save_transcript_to_db(st.session_state.triage_history)
                    
                    if success:
                        st.success(f"Triage Complete! Saved to DB (UUID: {db_msg})")
                    else:
                        st.error(f"Failed to save to DB: {db_msg}")
                    
                    st.session_state.triage_complete = True
                
                st.rerun()
                
            elif result.reason == speechsdk.ResultReason.NoMatch:
                st.error("No speech could be recognized. Please try speaking again.")
            else:
                st.error(f"Speech Recognition canceled: {result.cancellation_details.reason}")

    else:
        st.success("The triage session is complete. The doctor will see you shortly.")
        if st.button("Start New Triage Session"):
            # Delete the current state completely to force a hard reset
            del st.session_state.triage_history
            del st.session_state.triage_complete
            st.rerun()

# ==========================================
# PAGE 2: DOCTOR DICTATION (Mode A)
# ==========================================
if page == "Doctor: Dictation (Mode A)":
    st.subheader("Generate Master SOAP from Patient History")
    patient_id = st.text_input("Enter Patient ID (TAJ):", value="123456789")

    if st.button("Synthesize Full Medical Record"):
        with st.spinner(f"Fetching history for patient {patient_id} and synthesizing..."):
            success, result = ai_engine.generate_master_soap_for_patient(patient_id)
            
            if success:
                st.success(f"Master Note Saved! (UUID: {result['uuid']})")
                st.metric(label="Calculated Urgency Score", value=f"{result['urgency']} / 10")
                st.write(result['soap'])
            else:
                st.error(f"Failed: {result}")
