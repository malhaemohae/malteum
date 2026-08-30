"""engine 의 `PackSource` 를 만족하는 server 쪽 구현.

발행된 팩은 DB(`rule_packs`)에 있고 개발용 팩은 파일(`settings.pack_dir`)에 있다. 둘을
따로 보면 `/packs` 는 DB 를, 세션은 파일을 보게 되어 같은 서버가 서로 다른 팩을 말한다.
DB 를 먼저 보고 없으면 파일로 내려간다.

engine 이 이 객체의 타입을 모른다. `read(pack_version) -> dict` 만 맞으면 된다
(engine/pack/source.py). `engine/adapters/pack_source/postgres.py` 가 생기면 그것으로
갈아끼우고 이 파일은 지운다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.adapters.pack_source.file import FilePackSource
from server.services.pack_store import PackStore


class DbThenFilePackSource:
    def __init__(self, store: PackStore, directory: Path) -> None:
        self.store = store
        self.files = FilePackSource(directory)

    def read(self, pack_version: str) -> dict[str, Any]:
        doc = self.store.get(pack_version)
        if doc is not None:
            return doc
        return self.files.read(pack_version)  # 없으면 PackNotFound 가 그대로 올라간다
