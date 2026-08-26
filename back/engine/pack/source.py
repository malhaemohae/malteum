"""PackSource — 팩 JSON 을 어디서 읽는지 (계약 변경 요청 3번, DESIGN 3절).

engine 은 파일·postgres 를 모르고 이 Protocol 만 안다. 실물은 adapters/pack_source/.
"""

from __future__ import annotations

from typing import Any, Protocol


class PackNotFound(LookupError):
    pass


class PackSource(Protocol):
    def read(self, pack_version: str) -> dict[str, Any]:
        """rulepack.schema.json 을 만족하는 dict. 없으면 PackNotFound."""
        ...
