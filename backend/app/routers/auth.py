from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from jose import jwt
from datetime import datetime, timedelta
import uuid
import bcrypt
from app.schemas.auth import UserRegister, UserLogin, Token, UserMe
from common.auth.deps import get_current_user_id
from common.db.mysql import AsyncSessionLocal
from common.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserMe, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister):
    async with AsyncSessionLocal() as session:
        # Check duplicate
        result = await session.execute(
            text("SELECT id FROM users WHERE username = :un OR email = :em"),
            {"un": user_data.username, "em": user_data.email},
        )
        if result.fetchone():
            raise HTTPException(status_code=400, detail="Username or email already exists")

        uid = str(uuid.uuid4())[:12]
        password_hash = bcrypt.hashpw(
            user_data.password.encode(), bcrypt.gensalt()
        ).decode()

        await session.execute(
            text(
                "INSERT INTO users (id, username, email, password_hash, role, created_at) "
                "VALUES (:id, :un, :em, :pw, :role, :now)"
            ),
            {
                "id": uid,
                "un": user_data.username,
                "em": user_data.email,
                "pw": password_hash,
                "role": "user",
                "now": datetime.now(),
            },
        )
        await session.commit()

        result = await session.execute(
            text("SELECT id, username, email, role FROM users WHERE username = :un"),
            {"un": user_data.username},
        )
        row = result.fetchone()._mapping

    return UserMe(id=row["id"], username=row["username"], email=row["email"], role=row["role"], is_active=True)


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, username, password_hash FROM users WHERE username = :un"),
            {"un": credentials.username},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        user = row._mapping
        if not bcrypt.checkpw(
            credentials.password.encode(), user["password_hash"].encode()
        ):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        payload = {
            "sub": str(user["id"]),
            "username": user["username"],
            "exp": datetime.now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return Token(access_token=token, token_type="bearer")


@router.get("/me", response_model=UserMe)
async def get_me(user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, username, email, role FROM users WHERE id = :uid"),
            {"uid": user_id},
        )
        row = result.fetchone()._mapping

    return UserMe(
        id=row["id"], username=row["username"], email=row["email"], role=row["role"], is_active=True
    )
