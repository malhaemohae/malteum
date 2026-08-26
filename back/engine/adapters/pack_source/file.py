"""디렉터리의 rulepack_<version>.json 을 읽는다. 개발·테스트용. 운영은 postgres.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.pack.source import PackNotFound


class FilePackSource:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def read(self, pack_version: str) -> dict[str, Any]:
        path = self.directory / f"rulepack_{pack_version}.json"
        if not path.exists():
            raise PackNotFound(pack_version)
        return json.loads(path.read_text(encoding="utf-8"))
