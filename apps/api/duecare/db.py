from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config import settings
from .errors import ApiError


@lru_cache
def engine():
    if not settings().database_url:
        raise ApiError(503, "DATABASE_CONFIGURATION", "Database setup is not complete")
    return create_engine(
        settings().database_url,
        pool_size=3,
        max_overflow=2,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None},
    )


def transaction(user_id=None):
    session = sessionmaker(bind=engine(), expire_on_commit=False)()
    if user_id:
        session.execute(text("select set_config('app.user_id', :id, true)"), {"id": str(user_id)})
    return session
