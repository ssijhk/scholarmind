from pydantic import BaseModel
from typing import Optional

class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserMe(BaseModel):
    id: str
    username: str
    email: str
    role: str = "user"
    is_active: bool = True
