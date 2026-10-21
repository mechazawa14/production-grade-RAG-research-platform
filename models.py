from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


# Base.metadata.create_all(bind=engine)