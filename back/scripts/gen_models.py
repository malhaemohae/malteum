#!/usr/bin/env python3
"""contracts/ 의 ws_protocol·events 스키마 → server/generated/{ws,events}.py

datamodel-code-generator 는 JSON Schema 의 if/then 분기를 모델로 펼치지 못한다.
두 스키마는 `t`(ws)·`kind`(events) 값에 따라 필드가 달라지는 분기형이라, 여기서 분기마다
pydantic 클래스를 하나씩 만들고 판별 유니온으로 묶는다.

축↔상태 같은 교차 필드 제약(allOf/if 안의 enum 축소)은 pydantic 필드로 표현하지 않는다.
경계(ws 수신·이벤트 저장)에서 원본 스키마를 jsonschema 로 한 번 더 검증한다.

사용:  uv run python scripts/gen_models.py [출력 디렉터리]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACK = HERE.parent
CONTRACTS = BACK / "contracts"

HEADER = '''"""{title}

scripts/gen_models.py 가 contracts/{src} 에서 생성. 수동 편집 금지.
"""

from __future__ import annotations

from datetime import datetime  # noqa: F401
from typing import Annotated, Any, Literal  # noqa: F401

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter  # noqa: F401


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

'''


def pascal(s: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in s.replace("-", "_").split("_"))


class Gen:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.defs = schema.get("$defs", {})
        self.classes: list[str] = []
        self.emitted: dict[str, str] = {}  # def name -> class name

    # --- $ref -------------------------------------------------------------
    def resolve(self, node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            merged = dict(self.defs[name])
            merged.update({k: v for k, v in node.items() if k != "$ref"})
            return merged
        return node

    # --- 타입 --------------------------------------------------------------
    def pytype(self, node: dict[str, Any], hint: str) -> str:
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            target = self.defs[name]
            if target.get("type") == "object":
                return self.ensure_class(pascal(name), target)
            return self.pytype(target, pascal(name))
        if "anyOf" in node:
            return " | ".join(self.pytype(n, hint) for n in node["anyOf"])
        if "const" in node:
            return f"Literal[{node['const']!r}]"
        if "enum" in node:
            return "Literal[" + ", ".join(repr(v) for v in node["enum"]) + "]"
        t = node.get("type")
        if t == "string":
            return "datetime" if node.get("format") == "date-time" else "str"
        if t == "integer":
            return "int"
        if t == "number":
            return "float"
        if t == "boolean":
            return "bool"
        if t == "null":
            return "None"
        if t == "array":
            return f"list[{self.pytype(node.get('items', {}), hint)}]"
        if t == "object":
            if "properties" in node:
                return self.ensure_class(hint, node)
            return "dict[str, Any]"
        return "Any"

    # --- 필드 --------------------------------------------------------------
    def field(self, name: str, node: dict[str, Any], required: bool, owner: str) -> str:
        raw = node
        node = self.resolve(node)
        ann = self.pytype(raw, owner + pascal(name))
        kw: list[str] = []
        for js, py in (
            ("minimum", "ge"),
            ("maximum", "le"),
            ("minLength", "min_length"),
            ("maxLength", "max_length"),
            ("pattern", "pattern"),
            ("minItems", "min_length"),
            ("maxItems", "max_length"),
        ):
            if js in node:
                kw.append(f"{py}={node[js]!r}")
        if "description" in node:
            kw.append(f"description={node['description']!r}")
        if required:
            default = ""
        elif "default" in node:
            default = f" = {node['default']!r}"
        else:
            ann = f"{ann} | None" if not ann.endswith("| None") else ann
            default = " = None"
        if kw:
            ann = f"Annotated[{ann}, Field({', '.join(kw)})]"
        return f"    {name}: {ann}{default}\n"

    def ensure_class(
        self,
        name: str,
        node: dict[str, Any],
        extra_fields: str = "",
        required: set[str] | None = None,
        doc: str | None = None,
    ) -> str:
        if name in self.emitted:
            return name
        self.emitted[name] = name
        req = set(node.get("required", [])) | (required or set())
        body = extra_fields
        for pname, pnode in node.get("properties", {}).items():
            body += self.field(pname, pnode, pname in req, name)
        docstr = doc or node.get("description")
        lines = [f"class {name}(_Base):\n"]
        if docstr:
            lines.append(f'    """{docstr}"""\n\n')
        lines.append(body or "    pass\n")
        self.classes.append("".join(lines))
        return name

    # --- 분기형 객체 -------------------------------------------------------
    def branches(self, node: dict[str, Any], disc: str, suffix: str = "") -> list[str]:
        """`disc` 값별 if/then 을 클래스 하나씩으로 펼친다."""
        base_props = {k: v for k, v in node.get("properties", {}).items() if k != disc}
        base_req = set(node.get("required", [])) - {disc}
        by_value: dict[str, dict[str, Any]] = {}
        for cond in node.get("allOf", []):
            value = cond["if"]["properties"][disc]["const"]
            by_value[value] = cond.get("then", {})
        names: list[str] = []
        for value in node["properties"][disc]["enum"]:
            then = by_value.get(value, {})
            cname = pascal(value) + suffix
            merged = {
                "properties": {**base_props, **then.get("properties", {})},
                "required": sorted(base_req | set(then.get("required", []))),
                "description": then.get("$comment") or then.get("description"),
            }
            self.ensure_class(cname, merged, extra_fields=f"    {disc}: Literal[{value!r}]\n")
            names.append(cname)
        return names


def gen_ws(out: Path) -> None:
    schema = json.loads((CONTRACTS / "ws_protocol.schema.json").read_text(encoding="utf-8"))
    g = Gen(schema)
    c2s = g.branches(g.defs["c2s"], "t")
    s2c = g.branches(g.defs["s2c"], "t")
    tail = (
        "\n\nC2s = Annotated[" + " | ".join(c2s) + ', Field(discriminator="t")]\n'
        "S2c = Annotated[" + " | ".join(s2c) + ', Field(discriminator="t")]\n'
        "WsMessage = C2s | S2c\n\n"
        f"C2S_TYPES: tuple[str, ...] = {tuple(g.defs['c2s']['properties']['t']['enum'])!r}\n"
        f"S2C_TYPES: tuple[str, ...] = {tuple(g.defs['s2c']['properties']['t']['enum'])!r}\n\n"
        "c2s_adapter: TypeAdapter[Any] = TypeAdapter(C2s)\n"
        "s2c_adapter: TypeAdapter[Any] = TypeAdapter(S2c)\n"
    )
    write(out / "ws.py", schema["title"], "ws_protocol.schema.json", g, tail)


def gen_events(out: Path) -> None:
    schema = json.loads((CONTRACTS / "events.schema.json").read_text(encoding="utf-8"))
    g = Gen(schema)
    kinds = g.branches(schema, "kind", suffix="Event")
    tail = (
        "\n\nEvent = Annotated[" + " | ".join(kinds) + ', Field(discriminator="kind")]\n\n'
        f"EVENT_KINDS: tuple[str, ...] = {tuple(schema['properties']['kind']['enum'])!r}\n\n"
        "event_adapter: TypeAdapter[Any] = TypeAdapter(Event)\n"
    )
    write(out / "events.py", schema["title"], "events.schema.json", g, tail)


def write(path: Path, title: str, src: str, g: Gen, tail: str) -> None:
    text = HEADER.format(title=title, src=src) + "\n\n".join(g.classes) + tail
    path.write_text(text, encoding="utf-8")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else BACK / "server" / "generated"
    out.mkdir(parents=True, exist_ok=True)
    gen_ws(out)
    gen_events(out)


if __name__ == "__main__":
    main()
