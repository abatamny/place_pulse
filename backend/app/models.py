from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FoundationRecord(Base):
    """A minimal persistent table used to verify the Step 1 foundation."""

    __tablename__ = "foundation_records"

    record_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    record_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

