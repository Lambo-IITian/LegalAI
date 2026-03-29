from typing import Optional
from pydantic import BaseModel


class UserDocument(BaseModel):
    id:                str
    created_at:        str
    updated_at:        Optional[str] = None
    email:             str
    display_name:      str
    phone:             Optional[str] = None
    city:              Optional[str] = None
    state:             Optional[str] = None
    total_cases_filed: int = 0
    consent_given:     bool = False
    consent_given_at:  Optional[str] = None


class UserCreate(BaseModel):
    email:        str
    display_name: str
    phone:        Optional[str] = None
    city:         Optional[str] = None
    state:        Optional[str] = None