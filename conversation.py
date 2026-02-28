import os
import datetime  # <-- Added for timestamp
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
import pyodbc
import random

print("Speech key loaded:", os.environ.get('SPEECH_KEY') is not None)
print("Speech Endpoint loaded:", os.environ.get('ENDPOINT') is not None)
print("OpenAI key loaded:", os.environ.get('SPEECH_KEY') is not None)  # Note: This should be AZURE_OPENAI_API_KEY, but kept as per your code
print("OpenAI Endpoint loaded:", os.environ.get('ENDPOINT') is not None)  # Same note

server = os.environ.get('SQL_SERVER')
database = os.environ.get('SQL_DATABASE')
username = os.environ.get('SQL_USERNAME')
password = os.environ.get('SQL_PASSWORD')
driver = '{ODBC Driver 18 for SQL Server}'
connection_string = f'DRIVER={driver};SERVER={server};PORT=1433;DATABASE={database};UID={username};PWD={password}'

# Set up the Azure OpenAI Client
client = AzureOpenAI(
    azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
    api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-01"
)
deployment_name = "gpt-4.1-mini"   # Your deployment name

def recognize_from_microphone():
    # ... (unchanged, your existing function)
    speech_config = speechsdk.SpeechConfig(
        subscription=os.environ.get('SPEECH_KEY'),
        endpoint=os.environ.get('ENDPOINT')
    )
    speech_config.speech_recognition_language = "en-US"
    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
    speech_recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config
    )
    print("Speak into your microphone.")
    speech_recognition_result = speech_recognizer.recognize_once_async().get()

    if speech_recognition_result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print("Recognized: {}".format(speech_recognition_result.text))
    elif speech_recognition_result.reason == speechsdk.ResultReason.NoMatch:
        print("No speech could be recognized: {}".format(speech_recognition_result.no_match_details))
    elif speech_recognition_result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = speech_recognition_result.cancellation_details
        print("Speech Recognition canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print("Error details: {}".format(cancellation_details.error_details))
            print("Did you set the speech resource key and endpoint values?")
    return speech_recognition_result

def save_conversation(history):
    """
    Save the conversation to a text file with a timestamp.
    Skips system messages and writes only patient and doctor turns.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"conversation_{timestamp}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        for message in history:
            role = message["role"]
            content = message["content"]
            # Skip system prompts
            if role == "system":
                continue
            # Write the content (already prefixed with [patient] or [doctor])
            f.write(content + "\n")
    print(f"\nConversation saved to {filename}")

def save_transcript_to_db(history, connection_string):
    """
    Extracts the dialogue from the conversation history and inserts 
    it into the dbo.transcripts table in Azure SQL.
    """
    print("\nPreparing to save transcript to the database...")

    # 1. Extract and format the dialogue text
    transcript_lines = []
    for message in history:
        if message["role"] != "system":
            # The messages already contain the [doctor] and [patient] prefixes
            transcript_lines.append(message["content"])
            
    full_transcript_text = "\n".join(transcript_lines)

    # 2. Prepare the required SQL columns
    # Your schema requires summary_uuid to be an INT. 
    # (If this is an IDENTITY column in SQL, you can remove this variable)
    summary_uuid = random.randint(100000, 9999999) 
    
    # Format date for SQL 'DATE' type (YYYY-MM-DD)
    transcript_date = datetime.datetime.now().strftime("%Y-%m-%d")
    paciens_taj=123456789
    # 3. Connect and insert into dbo.transcripts
    try:
        # Establish the connection
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        # Parameterized SQL query
        insert_query = """
        INSERT INTO dbo.transcripts (transcript_uuid, transcript_date, transcript_text, paciens_taj)
        VALUES (?, ?, ?, ?)
        """
        
        # Execute and commit
        cursor.execute(insert_query, (summary_uuid,  transcript_date, full_transcript_text, paciens_taj))
        conn.commit()
        
        print(f"Success: Transcript successfully saved to dbo.transcripts with UUID {summary_uuid}!")

    except pyodbc.Error as e:
        print(f"Database insertion failed. SQL Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        
    finally:
        # Ensure the connection is always closed to prevent memory leaks
        if 'conn' in locals():
            conn.close()
            print("Database connection closed.")

# System prompt (unchanged)
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

conversation_history = [{"role": "system", "content": system_prompt}]

print("Starting the triage session. Say 'stop' to end the conversation.\n")

initial_greeting = "[doctor] Hello, I am the triage assistant. Please state your name and what brings you in today."
print(initial_greeting)
conversation_history.append({"role": "assistant", "content": initial_greeting})

while True:
    print("\n[Listening...]")
    result = recognize_from_microphone()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        user_text = result.text

        if "stop" in user_text.lower():
            print("\nEnding session. Preparing data for the doctor's dashboard...")
            save_conversation(conversation_history)   # <-- Save before exiting
            save_transcript_to_db(conversation_history, connection_string)
            break

        formatted_user_input = f"[patient] {user_text.lower()}"
        print(formatted_user_input)
        conversation_history.append({"role": "user", "content": formatted_user_input})

        response = client.chat.completions.create(
            model=deployment_name,
            messages=conversation_history,
            max_tokens=200,
            temperature=0.7
        )

        ai_response = response.choices[0].message.content
        print(ai_response)
        conversation_history.append({"role": "assistant", "content": ai_response})
        
        if "[COMPLETE]" in ai_response:
            print("\nTriage complete. Preparing data for the database...")
            
            # Optional: Remove the [COMPLETE] tag from the final string so it doesn't appear in your database
            conversation_history[-1]["content"] = ai_response.replace("[COMPLETE]", "").strip()
            
            # Trigger the save function
            save_transcript_to_db(conversation_history, connection_string)
            
            # End the conversation loop
            break
    elif result.reason == speechsdk.ResultReason.NoMatch:
        print("No speech could be recognized. Please try speaking again.")
    elif result.reason == speechsdk.ResultReason.Canceled:
        print(f"Speech Recognition canceled: {result.cancellation_details.reason}")
        break