"""Thin generic data-access layer.

Services should go through a Repository instance rather than calling
`session.query(...)` directly, so persistence details stay in one place and
are easy to swap/test. Keep this generic and small — model-specific query
logic (e.g. "find chunks by document_id") belongs in a dedicated repository
subclass or module added alongside that model, not bolted on here.
"""
from typing import Generic, TypeVar

from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


class Repository(Generic[ModelT]):
    def __init__(self, db: Session, model: type[ModelT]):
        self.db = db
        self.model = model

    def get(self, id_: int) -> ModelT | None:
        return self.db.get(self.model, id_)

    def list(self, *, offset: int = 0, limit: int = 100) -> list[ModelT]:
        return self.db.query(self.model).offset(offset).limit(limit).all()

    def create(self, **fields) -> ModelT:
        instance = self.model(**fields)
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def delete(self, instance: ModelT) -> None:
        self.db.delete(instance)
        self.db.commit()
