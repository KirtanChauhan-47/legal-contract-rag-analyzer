from fastapi import FastAPI

from app.core.config import get_settings
from app.core.error_handlers import register_error_handlers
from app.core.logging_config import configure_logging
from app.db.init_db import init_db
from app.routers import documents, health, qa

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)

register_error_handlers(app)
app.include_router(health.router)
app.include_router(documents.router)
app.include_router(qa.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
