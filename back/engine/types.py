"""contracts.engine_contract 의 dataclass 는 메서드 본문이 `...` 이다. 본문은 여기서 채운다.

M1 은 계약 타입으로 받고 isinstance 가 성립한다. 필드는 추가하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import engine_contract as c


@dataclass(frozen=True, slots=True)
class RulePack(c.RulePack):
    def item(self, code: str) -> c.PackItem | None:
        return next((it for it in self.items if it.code == code), None)

    def required_items(self) -> tuple[c.PackItem, ...]:
        return tuple(it for it in self.items if it.type == "required")

    def forbidden_items(self) -> tuple[c.PackItem, ...]:
        return tuple(it for it in self.items if it.type == "forbidden")


@dataclass(frozen=True, slots=True)
class SessionState(c.SessionState):
    def state_of(self, item_code: str, axis: c.Axis = "omission") -> c.ItemState | None:
        return next((s for s in self.items if s.item_code == item_code and s.axis == axis), None)

    def unmet_codes(self) -> tuple[str, ...]:
        return tuple(s.item_code for s in self.items if s.state == "unmet")
