#!/usr/bin/env python3
"""contracts 자체 검증. 커밋 전에 돌린다.

세 층으로 검사한다. 뒤로 갈수록 스키마가 잡아주지 못하는 것을 잡는다.

  1. 스키마 검증      fixtures 가 JSON Schema 를 만족하는가
  2. 교차 검증        fixture 끼리 앞뒤가 맞는가 (팩에 없는 item_code, 요약과 실제 판정의 불일치, supersedes 끊김)
  3. 근거 실재 검증   evidence.span 이 실제 PDF 에 그 페이지에 있는가  (P4 의 기계적 관문)

3층이 이 프로젝트에서 가장 중요하다. 스키마는 '문자열이 있다' 까지만 보장하고
'그 문자열이 원문에 실재한다' 는 보장하지 못한다. 근거 없는 항목이 팩에 들어가면
화면에 그럴듯한 인용이 뜨지만 원문에는 없다. 그것이 이 제품에서 가장 나쁜 실패다.

사용
    python contracts/validate.py
    python contracts/validate.py --skip-pdf     문서 없이 스키마·교차만

의존
    pip install jsonschema pypdfium2
    둘 다 선택이지만 pypdfium2 가 없으면 3층이 빠진다. 그 상태의 통과는 근거를 검사하지 않은 통과다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
DOCS = os.path.join(ROOT, "03_규정문서")

PACK_FIXTURE = "rulepack_DEP-2026.08-v3.json"

# 축별 허용 상태. events.schema.json 의 allOf 제약과 같은 표를 여기에도 둔다.
# 두 곳에 두는 이유는 스키마가 없을 때도 이 검사가 돌아야 하기 때문이다.
AXIS_STATES = {
    "omission": {"unmet", "partial", "met", "waived"},
    "commission": {"clean", "suspected", "violated"},
    "comprehension": {"explained", "confirmed"},
}

errors: list[str] = []
warns: list[str] = []
notes: list[str] = []


def load(name: str):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1층  스키마
# ---------------------------------------------------------------------------

def layer_schema(pack, events, ws):
    try:
        import jsonschema
    except ImportError:
        notes.append("jsonschema 없음 → 1층(스키마) 건너뜀.  pip install jsonschema")
        return

    def check(schema_file, instance, label):
        with open(os.path.join(HERE, schema_file), encoding="utf-8") as f:
            schema = json.load(f)
        v = jsonschema.Draft202012Validator(schema)
        for e in sorted(v.iter_errors(instance), key=lambda e: list(e.path)):
            path = "/".join(str(p) for p in e.path) or "(root)"
            errors.append(f"[스키마] {label} @ {path}: {e.message}")

    check("rulepack.schema.json", pack, PACK_FIXTURE)
    for i, ev in enumerate(events):
        check("events.schema.json", ev, f"events[{i}] {ev.get('event_id')}")
    for i, m in enumerate(ws):
        check("ws_protocol.schema.json", m, f"ws[{i}] t={m.get('t')}")


# ---------------------------------------------------------------------------
# 2층  교차
# ---------------------------------------------------------------------------

def layer_cross(pack, events, ws, cases):
    codes = {it["code"]: it for it in pack["items"]}
    pack_version = pack["pack_version"]

    # 항목 코드가 팩에 실재하는가
    def known(code, where):
        if code and code not in codes:
            errors.append(f"[교차] {where}: 팩에 없는 item_code {code}")

    # 이벤트
    seqs = [e["seq_in_session"] for e in events]
    if seqs != sorted(seqs):
        errors.append("[교차] events: seq_in_session 이 오름차순이 아니다")
    if len(set(seqs)) != len(seqs):
        errors.append("[교차] events: seq_in_session 중복")

    ids = set()
    for e in events:
        eid = e["event_id"]
        if eid in ids:
            errors.append(f"[교차] events: event_id 중복 {eid}")
        ids.add(eid)
        if e["pack_version"] != pack_version:
            errors.append(f"[교차] {eid}: pack_version 이 팩과 다르다")

    for e in events:
        sup = e.get("supersedes")
        if sup and sup not in ids:
            errors.append(f"[교차] {e['event_id']}: supersedes 대상 {sup} 이 없다")
        if sup:
            prev = next(x for x in events if x["event_id"] == sup)
            if prev["kind"] != e["kind"]:
                errors.append(f"[교차] {e['event_id']}: supersedes 가 다른 kind 를 가리킨다")
            if prev["seq_in_session"] >= e["seq_in_session"]:
                errors.append(f"[교차] {e['event_id']}: supersedes 가 뒤 이벤트를 가리킨다")

        if e["kind"] == "verdict":
            v = e["verdict"]
            known(v["item_code"], e["event_id"])
            if v["state"] not in AXIS_STATES[v["axis"]]:
                errors.append(f"[교차] {e['event_id']}: {v['axis']} 축에 {v['state']} 는 없는 상태")
            if v["state"] == "waived" and v.get("decided_by") != "human":
                errors.append(f"[교차] {e['event_id']}: waived 는 human 만 낼 수 있다")
            it = codes.get(v["item_code"])
            if it and v["axis"] != "comprehension" and it.get("axis") != v["axis"]:
                errors.append(f"[교차] {e['event_id']}: 팩의 축({it.get('axis')})과 판정 축({v['axis']}) 불일치")
            for m in v.get("missing_elements", []):
                if it and m not in it["requirement_elements"]:
                    errors.append(f"[교차] {e['event_id']}: 요건 요소에 없는 '{m}'")
        elif e["kind"] == "alert":
            known(e["alert"].get("item_code"), e["event_id"])
        elif e["kind"] == "assist":
            a = e["assist"]
            known(a.get("item_code"), e["event_id"])
            if a["assist_type"] == "rephrase":
                ref = a.get("source_utterance_ref")
                if ref not in ids:
                    errors.append(f"[교차] {e['event_id']}: rephrase 의 source_utterance_ref 가 없다")
                else:
                    src = next(x for x in events if x["event_id"] == ref)
                    if src["kind"] != "utterance":
                        errors.append(f"[교차] {e['event_id']}: source_utterance_ref 가 발화가 아니다")

    # 종료 요약이 이벤트를 접은 결과와 맞는가.
    # 요약은 파생물이므로 여기서 다시 계산해서 대조한다. 어긋나면 리포트가 거짓말을 한다.
    ended = [e for e in events if e["kind"] == "session_ended"]
    if len(ended) != 1:
        errors.append(f"[교차] session_ended 가 {len(ended)}개")
    else:
        superseded = {e["supersedes"] for e in events if e.get("supersedes")}
        final: dict[tuple[str, str], str] = {}
        for e in events:
            if e["kind"] == "verdict" and e["event_id"] not in superseded:
                v = e["verdict"]
                final[(v["item_code"], v["axis"])] = v["state"]

        required = [c for c, it in codes.items() if it["type"] == "required"]
        counted = {"met": 0, "partial": 0, "unmet": 0, "waived": 0}
        for c in required:
            counted[final.get((c, "omission"), "unmet")] += 1
        violations = sum(1 for (c, ax), s in final.items() if ax == "commission" and s == "violated")

        s = ended[0]["session_ended"]["summary"]
        if s["items_total"] != len(required):
            errors.append(f"[교차] 요약 items_total={s['items_total']} 인데 필수 항목은 {len(required)}개")
        for k, got in counted.items():
            if s.get(k, 0) != got:
                errors.append(f"[교차] 요약 {k}={s.get(k)} 인데 접어 보면 {got}")
        if s.get("violations", 0) != violations:
            errors.append(f"[교차] 요약 violations={s.get('violations')} 인데 접어 보면 {violations}")

        alerts = sum(1 for e in events if e["kind"] == "alert")
        if s.get("alerts", 0) != alerts:
            errors.append(f"[교차] 요약 alerts={s.get('alerts')} 인데 실제 {alerts}")
        adopted = sum(
            1 for e in events
            if e["kind"] == "assist" and e["event_id"] not in superseded
            and e["assist"].get("outcome") == "adopted"
        )
        if s.get("assists_adopted", 0) != adopted:
            errors.append(f"[교차] 요약 assists_adopted={s.get('assists_adopted')} 인데 실제 {adopted}")

    # ws 메시지
    for i, m in enumerate(ws):
        for key in ("item_code",):
            if key in m:
                known(m[key], f"ws[{i}] t={m['t']}")
        if m["t"] == "ready":
            for it in m["items"]:
                known(it["item_code"], f"ws[{i}] ready")
                if it["state"] not in AXIS_STATES[it["axis"]]:
                    errors.append(f"[교차] ws[{i}] ready: {it['axis']} 축에 {it['state']} 없음")
        if m["t"] == "verdict" and m["state"] not in AXIS_STATES[m["axis"]]:
            errors.append(f"[교차] ws[{i}] verdict: {m['axis']} 축에 {m['state']} 없음")

    # ws ready 의 항목 집합이 팩의 판정 대상과 같은가.
    # reference 항목은 판정 대상이 아니므로 빠져 있어야 한다.
    ready = next((m for m in ws if m["t"] == "ready"), None)
    if ready:
        got = {it["item_code"] for it in ready["items"]}
        want = {c for c, it in codes.items() if it["type"] != "reference"}
        if got != want:
            errors.append(f"[교차] ws ready 항목 집합 불일치. 빠짐 {sorted(want - got)} 여분 {sorted(got - want)}")

    # 판정 테스트 케이스
    for c in cases["cases"]:
        for v in c["expect"].get("verdicts", []):
            known(v["item_code"], f"case '{c['name']}'")
            if v.get("state") and v["state"] not in AXIS_STATES[v["axis"]]:
                errors.append(f"[교차] case '{c['name']}': {v['axis']} 축에 {v['state']} 없음")
            it = codes.get(v["item_code"])
            for m in v.get("missing_elements", []):
                if it and m not in it["requirement_elements"]:
                    errors.append(f"[교차] case '{c['name']}': 요건 요소에 없는 '{m}'")
        for a in c["expect"].get("alerts", []):
            known(a.get("item_code"), f"case '{c['name']}'")
        for st in c.get("state_before", {}).values():
            if st not in set().union(*AXIS_STATES.values()):
                errors.append(f"[교차] case '{c['name']}': 알 수 없는 상태 {st}")


# ---------------------------------------------------------------------------
# 3층  근거 실재
# ---------------------------------------------------------------------------

def collect_evidence(pack, events):
    """검사 대상 근거를 (출처 표시, evidence) 로 모은다."""
    out = []
    for it in pack["items"]:
        out.append((f"팩 {it['code']}", it["evidence"]))
        for nf in it.get("numeric_facts", []):
            if "evidence" in nf:
                out.append((f"팩 {it['code']} 숫자 '{nf['label']}'", nf["evidence"]))
    for e in events:
        body = e.get(e["kind"]) or {}
        if isinstance(body, dict) and "evidence" in body:
            out.append((f"이벤트 {e['event_id']}", body["evidence"]))
    return out


def layer_pdf(pack, events):
    try:
        sys.path.insert(0, HERE)
        from find_span import find_span
    except ImportError:
        # 조용히 넘기지 않는다. 3층이 빠진 통과는 통과가 아니다.
        warns.append("pypdfium2 없음 → 3층(근거 실재) 건너뜀. 이 상태의 '통과' 는 근거를 검사하지 않은 것이다."
                     "  pip install pypdfium2")
        return

    by_doc = {s["doc_id"]: s for s in pack["sources"]}
    files = {}
    for name in (os.listdir(DOCS) if os.path.isdir(DOCS) else []):
        if name.lower().endswith(".pdf"):
            files[os.path.splitext(name)[0]] = os.path.join(DOCS, name)

    checked = 0
    for where, ev in collect_evidence(pack, events):
        doc_id = ev["doc_id"]
        if doc_id not in by_doc:
            errors.append(f"[근거] {where}: sources 에 없는 doc_id {doc_id}")
            continue
        path = files.get(doc_id)
        if not path:
            warns.append(f"[근거] {where}: 문서 파일 없음 {doc_id}.pdf")
            continue

        hit = find_span(path, ev["span"], ev["page"])
        if hit is None:
            errors.append(f"[근거] {where}: p{ev['page']} 에 인용이 없다 → {ev['span'][:40]!r}")
            continue
        checked += 1
        if "bbox" in ev:
            got, want = hit["bbox"], ev["bbox"]
            if max(abs(a - b) for a, b in zip(got, want)) > 1.0:
                errors.append(f"[근거] {where}: bbox 불일치. 파일 {got} vs 기록 {want}")

    notes.append(f"근거 {checked}건 원문 대조 통과")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-pdf", action="store_true")
    a = ap.parse_args()

    pack = load(PACK_FIXTURE)
    events = load("events_scenario_a.json")
    ws = load("ws_messages.json")
    cases = load("judge_cases.json")

    print("=== contracts 검증 ===")
    print(f"  팩 {pack['pack_version']}  항목 {len(pack['items'])}")
    print(f"  이벤트 {len(events)}  ws 메시지 {len(ws)}  판정 케이스 {len(cases['cases'])}")
    print()

    layer_schema(pack, events, ws)
    layer_cross(pack, events, ws, cases)
    if not a.skip_pdf:
        layer_pdf(pack, events)

    for n in notes:
        print(f"  · {n}")
    for w in warns:
        print(f"  ! {w}")
    if errors:
        print()
        for e in errors:
            print(f"  X {e}")
        print(f"\n실패 {len(errors)}건")
        return 1
    print("\n통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
