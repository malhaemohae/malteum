from __future__ import annotations

from typing import Any

from engine.pack.source import PackNotFound


class FakePackSource:
    def __init__(self, *packs: dict[str, Any]) -> None:
        self.packs = {p["pack_version"]: p for p in packs}

    def read(self, pack_version: str) -> dict[str, Any]:
        try:
            return self.packs[pack_version]
        except KeyError:
            raise PackNotFound(pack_version) from None
