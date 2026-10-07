from alembic import context
from sqlalchemy import create_engine

from duecare.config import settings
from duecare.models import Base

config = context.config
url = settings().migration_database_url
if not url:
    raise RuntimeError("MIGRATION_DATABASE_URL is required")
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, connect_args={"prepare_threshold": None}).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()
