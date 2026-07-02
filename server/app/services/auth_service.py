from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password, create_session_token
from app.models.models import User
from app.repositories.repositories import UserRepository
from app.schemas.schemas import UserCreate


class AuthService:
    def __init__(self, session: AsyncSession):
        self.repo = UserRepository(session)
        self.session = session

    async def authenticate(self, username: str, password: str) -> Optional[User]:
        user = await self.repo.get_by_username(username)
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        # Update last_login
        await self.repo.update(user, last_login=datetime.now(timezone.utc))
        return user

    async def create_user(self, data: UserCreate) -> User:
        user = await self.repo.create(
            username=data.username,
            email=data.email,
            hashed_password=hash_password(data.password),
            role=data.role,
        )
        return user

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        return await self.repo.get(user_id)

    def make_session_token(self, user: User) -> str:
        return create_session_token(user.id)

    async def ensure_admin_exists(self) -> None:
        """Create default admin if no users exist."""
        count = await self.repo.count()
        if count == 0:
            await self.create_user(
                UserCreate(
                    username="admin",
                    email="admin@endpoint.local",
                    password="Admin@1234",
                    role="admin",
                )
            )
