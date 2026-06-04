"""JWT authentication dependencies.

All DB/Milvus queries MUST filter by user_id (multi-tenant isolation).
No user_id filter is a bug.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from common.config import settings

security = HTTPBearer()


def decode_token(token: str) -> dict:
    """Decode JWT token, return payload or raise."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Extract current user from JWT token."""
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity",
        )
    return {"user_id": user_id, "username": payload.get("username", "")}


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Extract user_id directly."""
    user = await get_current_user(credentials)
    return user["user_id"]
