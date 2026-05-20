import requests
import json

BASE_URL = "http://localhost:5000"

def test_query(query, description):
    print(f"\n--- {description} ---")
    print(f"Query: {query}")
    try:
        response = requests.post(f"{BASE_URL}/route_query", json={"query": query}, timeout=10)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Intent: {data.get('intent')}")
            print(f"Response: {data.get('response')[:100]}...")  # Truncate for brevity
            actions = data.get('actions', {})
            if 'extracted' in actions:
                extracted = actions['extracted']
                print(f"Extracted - Doctor: {extracted.get('doctor_name')}, Date: {extracted.get('appointment_date')}, Time: {extracted.get('appointment_time')}, Phone: {extracted.get('patient_phone')}, Name: {extracted.get('patient_name')}")
            if 'booked' in actions:
                print(f"Booked: {actions['booked']}")
            if 'missing_fields' in actions:
                print(f"Missing: {actions['missing_fields']}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

# Test cases
test_cases = [
    ("Book an appointment with Dr. Smith tomorrow at 10am, my phone is 123-456-7890", "Basic booking with phone"),
    ("I need to see Dr. Johnson on Friday at 2pm, name is John Doe, phone (987) 654-3210", "Booking with name and phone in parens"),
    ("Appointment for Dr. Patel next week, 11am, phone 555.123.4567", "Phone with dots"),
    ("Book with Dr. Lee today at 9am", "Missing phone"),
    ("Book appointment tomorrow", "Missing everything"),
    ("Book with Dr. Smith at 10am", "Missing date"),
    ("Book tomorrow at 10am with phone 1234567890", "Missing doctor"),
    ("Book with Dr. Smith tomorrow at 3pm, phone +1 234 567 8901", "International phone"),
    ("I want to book an appointment", "Vague query"),
    ("Book with Dr. Smith tomorrow at 10am, phone 123-456-7890, name Jane", "With name"),
    ("Book with Dr. Smith on 2026-03-15 at 14:00, phone 1234567890", "Specific date and time"),
]

for query, desc in test_cases:
    test_query(query, desc)