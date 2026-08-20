from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def create_schema() -> None:
    # Import models before create_all so SQLAlchemy knows which tables to create.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE places "
                "ADD COLUMN IF NOT EXISTS locality VARCHAR(200)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE places ADD COLUMN IF NOT EXISTS "
                "scope_class VARCHAR(20) NOT NULL DEFAULT 'OTHER'"
            )
        )
        for table_name in ("knock_messages", "digs", "forum_posts"):
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS origin_place_id INTEGER"
                )
            )
            connection.execute(
                text(
                    f"UPDATE {table_name} SET origin_place_id = place_id "
                    "WHERE origin_place_id IS NULL"
                )
            )
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ALTER COLUMN origin_place_id SET NOT NULL"
                )
            )
            connection.execute(
                text(
                    "DO $$ BEGIN "
                    f"ALTER TABLE {table_name} ADD CONSTRAINT "
                    f"{table_name}_origin_place_id_fkey "
                    "FOREIGN KEY (origin_place_id) REFERENCES places(id) "
                    "ON DELETE CASCADE; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; "
                    "END $$"
                )
            )
            connection.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table_name}_origin_place_id "
                    f"ON {table_name} (origin_place_id)"
                )
            )
        connection.execute(
            text(
                "ALTER TABLE knock_messages "
                "ADD COLUMN IF NOT EXISTS client_id VARCHAR(80)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE knock_messages "
                "ADD COLUMN IF NOT EXISTS deny_code VARCHAR(30)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE knock_messages "
                "ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE knock_messages "
                "ADD COLUMN IF NOT EXISTS broadcast_at TIMESTAMPTZ"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_knock_messages_broadcast_at "
                "ON knock_messages (broadcast_at)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE forum_posts "
                "ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE forum_comments "
                "ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE job_queue_state "
                "ADD COLUMN IF NOT EXISTS last_served JSON NOT NULL DEFAULT '{}'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE job_queue_state "
                "ADD COLUMN IF NOT EXISTS serve_counter INTEGER NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE job_queue_state "
                "DROP COLUMN IF EXISTS last_user_id"
            )
        )
