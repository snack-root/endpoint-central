"""
FastAPI dependency injectors.
"""
from typing import Annotated, Optional
from fastapi import Depends, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_session_token
from app.models.models import User
from app.services.auth_service import AuthService


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> User:
    """Require a valid session cookie. Raises 401 if missing/expired."""
    token = request.cookies.get("ec_session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id = decode_session_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    svc = AuthService(session)
    user = await svc.get_user_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    return user


async def get_optional_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Return user or None (for login page rendering)."""
    try:
        return await get_current_user(request, session)
    except HTTPException:
        return None


# Type aliases
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
