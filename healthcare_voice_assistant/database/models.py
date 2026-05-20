from dataclasses import dataclass
from typing import Optional


@dataclass
class Appointment:
    id: Optional[int]
    patient_name: str
    doctor_name: str
    appointment_date: str
    appointment_time: str
    patient_phone: str
    status: str
    created_at: str


@dataclass
class Patient:
    id: Optional[int]
    patient_name: str
    phone: str
    created_at: str
