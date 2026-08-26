"""SQLAlchemy 선언 베이스. entities/ 의 테이블이 여기에 붙고 alembic 이 이 메타데이터를 본다."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
