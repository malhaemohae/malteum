"""L3 의미 귀속 실험 하네스. 변형을 monkeypatch 로 바꿔 병렬 호출하고 원시 응답까지 찍는다.

사용: uv run --no-sync python <this> --variant base|stated|hints|both [--sets dev,holdout,unseen] [--repeats 1] [--workers 6]
"""
from __future__ import annotations

import argparse, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import contextvars
CUR_PV = contextvars.ContextVar("pv", default="")
from pathlib import Path

os.environ.setdefault("MALTEUM_LIVE_REGRESSION", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
ROOT = Path("/home/me/projects/malteum/back")
sys.path.insert(0, str(ROOT))

from contracts.engine_contract import ItemState, Utterance, VerdictPayload, JudgeDecision
from engine.adapters.llm.litellm import LiteLlmJudge
from engine.pack.loader import load_pack
from engine.tiers.l3 import decision_parser, prompt_builder, tools
from engine.types import SessionState
from server.bootstrap.settings import Settings
from tests.engine.conftest import FIX
from tests.engine.fakes import FakePackSource

TESTS = ROOT / "tests" / "engine"
RAW = {}
def raw_pack(pv):
    if pv not in RAW:
        RAW[pv] = json.loads((FIX / f"rulepack_{pv}.json").read_text(encoding="utf-8"))
    return RAW[pv]

# ---- 변형 ------------------------------------------------------------------
_orig_tool, _orig_messages, _orig_to_decision = tools.judge_tool, tools.messages, tools.to_decision

def _humanize(rx: str) -> str:
    s = rx.replace("\\s*", "").replace("\\s+", " ").replace("[을를]?", "").replace("(?:", "(")
    s = re.sub(r"\.\{0,\d+\}", "…", s)
    s = re.sub(r"\[([^\]]+)\]", lambda m: m.group(1)[0], s)
    s = s.replace("\\.", ".")
    return s

def hints_for(pv: str, code: str) -> dict[str, list[str]]:
    it = next(i for i in raw_pack(pv)["items"] if i["code"] == code)
    out: dict[str, list[str]] = {}
    for p in it.get("l1_patterns", []):
        out.setdefault(p["element"], []).append(_humanize(p["value"]) if p["kind"] == "regex" else p["value"])
    return out

FEATURES: set[str] = set()

def feat_tool(prompt):
    t = _orig_tool(prompt)
    params = t["function"]["parameters"]
    v = params["properties"]["verdicts"]["items"]
    props = v["properties"]
    new_props = {"item_code": props["item_code"]}
    req = ["item_code"]
    if "relation" in FEATURES:
        names = " / ".join(f"{it.code}={it.name}" for it in prompt.candidate_items)
        new_props["relation"] = {"type": "string", "enum": ["explains_item", "other_topic", "unrelated"],
            "description": ("utterance_topic 과 항목 이름(" + names + ")의 관계. explains_item: 발화가 그 항목의 사안 "
                            "자체를 설명한다. other_topic: 연관되거나 요소가 겹치지만 실제 주제는 다른 사안이다. "
                            "unrelated: 무관하다")}
        req.append("relation")
    elif "topic" in FEATURES or "stated" in FEATURES:
        new_props["explains_item"] = {"type": "boolean",
            "description": "발화가 이 항목 이름의 사안 자체를 설명하는가. 요소 하나가 겹치는 것만으로는 false"}
        req.append("explains_item")
    if "stated" in FEATURES:
        new_props["stated_elements"] = {"type": "array", "items": props["missing_elements"]["items"],
                                        "description": "이 발화가 실제로 말한 요건 요소만"}
        req.append("stated_elements")
    new_props["axis"] = props["axis"]; new_props["state"] = props["state"]; req += ["axis", "state"]
    if "stated" not in FEATURES:
        new_props["missing_elements"] = props["missing_elements"]
    new_props["confidence"] = props["confidence"]
    v["properties"] = new_props; v["required"] = req
    if "topic" in FEATURES:
        params["properties"] = {"utterance_topic": {"type": "string",
            "description": "이 발화가 무엇을 설명하는지 한 구절로. 후보 항목 이름과 같지 않아도 된다"},
            **params["properties"]}
        params["required"] = ["utterance_topic", *params["required"]]
    if "rel2" in FEATURES:
        names = " / ".join(f"{it.code}={it.name}" for it in prompt.candidate_items)
        rel = {"type": "array", "description": "후보 항목마다 하나씩. utterance_topic 과 항목 이름(" + names + ")의 관계",
               "items": {"type": "object", "properties": {
                   "item_code": props["item_code"],
                   "relation": {"type": "string", "enum": ["explains_item", "other_topic", "unrelated"],
                       "description": ("explains_item: 발화가 그 항목 이름의 사안 자체(그 사안이 생기는 경우나 그 사안의 내용)를 "
                                       "설명한다. other_topic: 조건·결과·금액이 겹치더라도 실제 주제는 다른 사안이다"
                                       + ("(other_items 에 있는 사안이면 other_topic)" if "catalog" in FEATURES else "") + ". "
                                       "unrelated: 무관하다")}},
                   "required": ["item_code", "relation"], "additionalProperties": False}}
        newp = {}
        for k, val in params["properties"].items():
            if k == "verdicts":
                newp["topic_relations"] = rel
            newp[k] = val
        params["properties"] = newp
        params["required"] = [r for r in params["required"] if r != "verdicts"] + ["topic_relations", "verdicts"]
    return t

LAST_ARGS = contextvars.ContextVar("args", default=None) if False else None

def feat_to_decision(args, tokens):
    verdicts = []
    for v in args.get("verdicts", ()):
        if "rel2" in FEATURES:
            rels = {r["item_code"]: r["relation"] for r in args.get("topic_relations", ())}
            if rels.get(v["item_code"]) != "explains_item":
                continue
        if "relation" in FEATURES:
            if v.get("relation") != "explains_item":
                continue
        elif ("topic" in FEATURES or "stated" in FEATURES) and not v.get("explains_item", True):
            continue
        elems = v.get("stated_elements", ()) if "stated" in FEATURES else v.get("missing_elements", ())
        verdicts.append(VerdictPayload(item_code=v["item_code"], axis=v["axis"], state=v["state"],
                        decided_by="L3", confidence=v.get("confidence"), missing_elements=tuple(elems)))
    d = JudgeDecision(verdicts=tuple(verdicts), tokens=tokens)
    TOPICS.value = (args.get("utterance_topic"), [(r["item_code"], r["relation"]) for r in args.get("topic_relations", ())] or [(v["item_code"], v.get("relation", v.get("explains_item"))) for v in args.get("verdicts", ())])
    return d

import threading
TOPICS = threading.local()

def apply_variant(name: str):
    global VARIANT
    VARIANT = name
    FEATURES.clear(); FEATURES.update(f for f in name.split("+") if f != "base")
    tools.judge_tool = feat_tool if FEATURES & {"topic", "stated", "relation", "rel2"} else _orig_tool
    tools.to_decision = feat_to_decision if FEATURES & {"topic", "stated", "relation", "rel2"} else _orig_to_decision
    if FEATURES & {"hints", "noplain", "catalog", "uttlast"}:
        def messages(prompt):
            msgs = _orig_messages(prompt)
            body = json.loads(msgs[1]["content"])
            pv = CUR_PV.get()
            for it in body["candidate_items"]:
                if "hints" in FEATURES:
                    it["element_examples"] = hints_for(pv, it["code"])
                if "noplain" in FEATURES:
                    it.pop("plain_language", None)
            if "catalog" in FEATURES:
                cands = {it["code"] for it in body["candidate_items"]}
                body["other_items"] = [it["name"] for it in raw_pack(pv)["items"]
                                       if it["type"] in ("required", "forbidden") and it["code"] not in cands]
            if "uttlast" in FEATURES:
                utt = body.pop("utterance"); body["utterance"] = utt
            msgs[1]["content"] = json.dumps(body, ensure_ascii=False, indent=1)
            return msgs
        tools.messages = messages
    else:
        tools.messages = _orig_messages

VARIANT = "base"

# ---- 사례 ------------------------------------------------------------------
def load_cases(sets):
    import tests.engine.test_live_scope_regression as T
    cases = []
    if "dev" in sets:
        for name, text, expected, missing in T.CASES:
            cases.append({"name": name, "pack": "LOAN-2026.08-v7", "text": text, "target": "LOAN-EXP-001",
                          "expected": expected, "missing": list(missing), "set": "dev"})
    for fname, tag in (("scope_holdout.json", "holdout"), ("scope_holdout2.json", "unseen")):
        if tag in sets:
            for c in json.loads((TESTS / fname).read_text(encoding="utf-8"))["cases"]:
                cases.append({**c, "set": tag})
    return cases

def run_case(case, judge):
    pv = case["pack"]; CUR_PV.set(pv)
    raw = raw_pack(pv)
    pack = load_pack(FakePackSource(raw), pv)
    target = case["target"]
    context = (Utterance("prior", case["context_speaker"], case["context"], 0),) if "context" in case else ()
    state = SessionState("S", pv, "text", items=(ItemState(target, "omission",
            "partial" if "before_missing" in case else "unmet", "L3" if "before_missing" in case else "L1", 0,
            missing_elements=tuple(case.get("before_missing", ()))),), recent_utterances=context)
    utt = Utterance("current", case.get("speaker", "teller"), case["text"], 1)
    cands = [target, *([case["additional_target"]] if "additional_target" in case else [])]
    prompt = prompt_builder.build(utt.text, pack, state, cands, "qwen/qwen3-8b", utt.speaker)
    t0 = time.perf_counter()
    try:
        decision = judge.decide(prompt)
        err = None
    except Exception as e:
        decision, err = JudgeDecision(), f"{type(e).__name__}: {str(e)[:120]}"
    ms = round((time.perf_counter() - t0) * 1000)
    raw_v = [(v.item_code, v.axis, v.state, list(v.missing_elements)) for v in decision.verdicts]
    topic = getattr(TOPICS, "value", None); TOPICS.value = None
    if "stated" in FEATURES:
        # stated_elements → missing_elements 변환 (required/omission)
        conv = []
        for v in decision.verdicts:
            item = pack.item(v.item_code)
            if v.axis == "omission" and item is not None:
                stated = set(v.missing_elements)
                missing = tuple(e for e in item.requirement_elements if e not in stated)
                conv.append(VerdictPayload(v.item_code, "omission", "met" if not missing else "partial", "L3",
                                           confidence=v.confidence, missing_elements=missing))
            else:
                conv.append(VerdictPayload(v.item_code, v.axis, v.state, "L3", confidence=v.confidence))
        decision = JudgeDecision(verdicts=tuple(conv), tokens=decision.tokens)
    verdicts, alerts, assists, rejected = decision_parser.parse(decision, pack, state, utt)
    actual = [{"state": v.state, "missing": sorted(v.missing_elements)} for v in verdicts if v.item_code == target]
    expected = [{"state": case["expected"], "missing": sorted(case.get("missing", []))}] if case["expected"] else []
    return {"set": case["set"], "name": case["name"], "ms": ms, "tokens": decision.tokens, "err": err,
            "raw": raw_v, "topic": topic, "rejected": rejected, "expected": expected, "actual": actual,
            "passed": err is None and actual == expected}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="base"); ap.add_argument("--sets", default="dev,holdout")
    ap.add_argument("--repeats", type=int, default=1); ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", default=""); ap.add_argument("--out", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    apply_variant(a.variant)
    if a.dry:
        for pv, code in (("LOAN-2026.08-v7", "LOAN-EXP-001"), ("DEP-2026.08-v6", "DEP-INT-002")):
            print(code, hints_for(pv, code))
        pack = load_pack(FakePackSource(raw_pack("LOAN-2026.08-v7")), "LOAN-2026.08-v7")
        pr = prompt_builder.build("t", pack, SessionState("S", "LOAN-2026.08-v7", "text"), ["LOAN-EXP-001"], "m", "teller")
        CUR_PV.set("LOAN-2026.08-v7")
        print(json.dumps(tools.judge_tool(pr)["function"]["parameters"]["properties"]["verdicts"]["items"], ensure_ascii=False)[:600])
        print(tools.messages(pr)[1]["content"][:900])
        return
    cases = load_cases(a.sets.split(","))
    if a.only:
        cases = [c for c in cases if c["name"] in a.only.split(",")]
    settings = Settings(); assert settings.llm_api_key
    judge = LiteLlmJudge("qwen/qwen3-8b", provider="openrouter", api_key=settings.llm_api_key,
                         extra_body={"reasoning": {"enabled": False}})
    jobs = [(c, r) for r in range(1, a.repeats + 1) for c in cases]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(lambda cr: {**run_case(cr[0], judge), "repeat": cr[1]}, jobs))
    passed = sum(r["passed"] for r in results)
    for r in results:
        flag = "ok  " if r["passed"] else "FAIL"
        print(f"{flag} [{r['set']}] {r['name']} r{r['repeat']} {r['ms']}ms tok={r['tokens']} raw={r['raw']} topic={r.get('topic')!r} "
              f"rej={r['rejected']} exp={r['expected']} act={r['actual']}" + (f" ERR={r['err']}" if r["err"] else ""))
    by = {}
    for r in results:
        by.setdefault(r["set"], [0, 0]); by[r["set"]][1] += 1; by[r["set"]][0] += r["passed"]
    print(f"== variant={a.variant} total {passed}/{len(results)} " + " ".join(f"{k}={v[0]}/{v[1]}" for k, v in by.items())
          + f" wall={time.perf_counter()-t0:.1f}s")
    if a.out:
        Path(a.out).write_text(json.dumps({"variant": a.variant, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")

if __name__ == "__main__":
    main()
