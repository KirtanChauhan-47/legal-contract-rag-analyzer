from app.db.base import Base, engine

# Import every model module so it registers on Base.metadata before create_all runs.
from app.models import document, chunk, chat  # noqa: F401


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
