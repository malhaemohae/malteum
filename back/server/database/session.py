"""SQLAlchemy 엔진과 세션 팩토리.

접속 주소의 정본은 `settings` 한 곳이다. 여기서 URL 을 만들지 않고 받기만 한다.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_sessions(url: str) -> sessionmaker[Session]:
    # pool_pre_ping: 컨테이너 재기동 등으로 끊긴 연결을 조용히 되살린다
    return sessionmaker(create_engine(url, pool_pre_ping=True), expire_on_commit=False)
