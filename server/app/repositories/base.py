"""
Generic async repository base.
All specific repositories extend this.
"""
from typing import TypeVar, Generic, Type, Optional, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(self, model: Type[ModelT], session: AsyncSession):
        self.model = model
        self.session = session

    async def get(self, id: str) -> Optional[ModelT]:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        offset: int = 0,
        limit: int = 50,
        **filters: Any,
    ) -> list[ModelT]:
        stmt = select(self.model)
        for attr, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, attr) == value)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        for attr, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, attr) == value)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def create(self, **kwargs: Any) -> ModelT:
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, obj: ModelT, **kwargs: Any) -> ModelT:
        for key, value in kwargs.items():
            setattr(obj, key, value)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
