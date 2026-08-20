import os
import shutil
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import delete


def ensure_test_database(database_name: str) -> None:
    connection_settings = {
        "host": os.getenv("DB_HOST", "db"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", "placepulse"),
        "password": os.getenv("POSTGRES_PASSWORD", "placepulse"),
    }
    with psycopg.connect(
        **connection_settings,
        dbname="postgres",
        autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
        ).fetchone()
        if exists is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )

    with psycopg.connect(
        **connection_settings,
        dbname=database_name,
        autocommit=True,
    ) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def clean_test_data(media_root: Path) -> None:
    from app.database import SessionLocal
    from app.models import (
        AIJob,
        AuthSession,
        Dig,
        DirectMessage,
        ExploreComment,
        ExploreLike,
        ExploreMemory,
        ExploreMemoryDig,
        ExploreParticipant,
        ForumComment,
        ForumPost,
        ForumVote,
        JobQueueState,
        KnockMessage,
        MediaAttachment,
        Place,
        PlaceMembership,
        Presence,
        User,
        Visit,
    )

    with SessionLocal() as db:
        for model in (
            AIJob,
            JobQueueState,
            ExploreComment,
            ExploreLike,
            ExploreParticipant,
            ExploreMemoryDig,
            ExploreMemory,
            MediaAttachment,
            ForumComment,
            ForumVote,
            ForumPost,
            DirectMessage,
            Dig,
            KnockMessage,
            Visit,
            Presence,
            PlaceMembership,
            Place,
            AuthSession,
            User,
        ):
            db.execute(delete(model))
        db.commit()
    shutil.rmtree(media_root / "digs", ignore_errors=True)
    shutil.rmtree(media_root / "attachments", ignore_errors=True)
