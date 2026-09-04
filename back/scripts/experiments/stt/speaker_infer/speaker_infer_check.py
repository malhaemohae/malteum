#!/usr/bin/env python3
"""화자 추정 도구 실험. STT 가 화자 분리를 못 줄 때 LLM 이 맥락으로 `teller`·`customer` 를
붙일 수 있는지 잰다.

시연 대본(`assets/scenarios/*/script.json`)의 줄을 서버와 같은 문장 분리(`assembler.utterances`)로
나눠, 화자 라벨 없이 순서대로 한 덩어리씩 LLM 에 보낸다. 문맥은 슬라이딩 윈도우(바로 앞
`--window` 문장)이고 두 방식이 있다.

- `labeled`: 앞 문장에 **LLM 이 스스로 붙인** 라벨을 달아 주고 현재 문장 하나를 `assign_speaker`
  로 정한다. 정답을 주지 않는 것이 실제 스트림 조건이다(`--truth-context` 로 정답을 주면 상한).
- `joint`(기본): 앞 문장과 현재 문장을 라벨 없이 순서대로 보여 주고 `assign_speakers` 로 전부의
  화자를 한 번에 정한 뒤 마지막 문장의 라벨만 쓴다. 같은 문장이 여러 윈도우에서 판정되므로
  다수결로 확정한 결과(`vote`)도 함께 낸다 — 다만 다수결은 뒤 문장이 `window` 개 더 와야
  확정되므로 스트림에서는 라벨이 나중에 바뀌는 셈이다.

사용 (back/ 에서)
    uv run python scripts/speaker_infer_check.py                    # 두 시나리오, 기본 조합
    uv run python scripts/speaker_infer_check.py --mode labeled --window 6 --prompt base  # 기준선
    uv run python scripts/speaker_infer_check.py --chunk 2          # 2문장씩 (STT final 이 길 때)
    uv run python scripts/speaker_infer_check.py --json out.json    # 문장별 결과 저장
    APP_LLM_PROVIDER · APP_LLM_API_KEY · APP_LLM_MODEL 을 .env 에서 읽는다 (test_live_llm 과 같다).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import litellm

BACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACK))

from engine.adapters.llm.litellm import register  # noqa: E402
from server.bootstrap.settings import Settings  # noqa: E402
from server.services.stt.assembler import utterances  # noqa: E402

SCENARIOS = BACK.parent / "assets" / "scenarios"

PROMPT_BASE = """당신은 은행 창구 상담 녹취의 화자를 가려내는 역할이다.
음성 인식이 화자를 구분하지 못해, 문장이 순서대로 하나씩 온다. 방금 온 문장이 은행원(teller)의
말인지
고객(customer)의 말인지 정하고 반드시 `assign_speaker` 툴로 답한다.

단서
- 은행원: 상품 조건·이율·세금·수수료·권리를 설명하고 안내한다. "안내드리겠습니다",
  "적용됩니다",
  "고객님", "준비해 주세요", "죄송합니다, 정정하겠습니다" 처럼 설명·안내·정정·요청하는 말.
- 고객: 자기 상황을 말하고, 묻고, 되묻고, 이해했다고 되짚고, 결정을 말한다. "제 조건이면",
  "그게 뭐예요?", "그렇다는 거네요", "그냥 해지할게요", "걱정되네요" 처럼 사정·질문·확인·결정하는
  말.
- 상담은 보통 번갈아 말하지만 은행원이 여러 문장을 이어 설명하는 구간이 길다. 앞 문장이
  은행원이라고
  다음이 꼭 고객인 것은 아니다. 문장의 내용과 말투를 우선하고, 순서는 보조로만 쓴다.
- 짧은 맞장구("네", "아, 그래요")는 앞뒤 흐름으로 정한다. 질문에 대한 대답이면 대답하는 쪽이다."""

# 보강 단서. "~해 주세요" 를 은행원 말로 단정하던 것을 풀고, 돈의 주인과 일을 시키는 방향으로 가른다
PROMPT_PLUS = (
    PROMPT_BASE
    + """
- 단, "~해 주세요", "~해 주시겠어요" 는 부탁하는 말투일 뿐 화자를 정하지 않는다. 고객도 은행원에게
  일을 시킨다. **누가 누구에게 무슨 일을 시키는지**로 가른다. 창구에서 돈을 움직이고 서류를
  처리하는 쪽은 은행원이므로, 해지·송금·이체·입금 같은 **처리를 해 달라**는 말은 고객이고,
  신분증·서류·도장을 **준비해 달라**, 확인해 보라는 말은 은행원이다.
- 돈의 주인은 고객이다. 자기 돈을 어디로 보낼지, 해지할지 말지, 얼마를 빌릴지 정하는 말은
  고객이다. 은행원은 고객 돈의 송금처를 먼저 정하거나 제안하지 않는다 — 고객이 말한 송금처를
  되묻고 확인할 뿐이다("따님과 직접 통화는 해 보셨어요?").
- "아뇨", "그냥 할게요", "그렇게 해 주세요" 처럼 안내를 듣고 결정을 말하는 쪽은 고객이다.
  결정 뒤에 이어지는 "그 돈은 ~로 보내 주세요" 도 같은 사람(고객)의 말이다."""
)

PROMPTS = {"base": PROMPT_BASE, "plus": PROMPT_PLUS}

TOOL_ONE = {
    "type": "function",
    "function": {
        "name": "assign_speaker",
        "description": "방금 온 문장(current)의 화자를 정한다",
        "parameters": {
            "type": "object",
            "properties": {
                "speaker": {"type": "string", "enum": ["teller", "customer"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string", "description": "근거 한 문장"},
            },
            "required": ["speaker", "confidence"],
            "additionalProperties": False,
        },
    },
}

TOOL_MANY = {
    "type": "function",
    "function": {
        "name": "assign_speakers",
        "description": "보여 준 문장(sentences) 전부의 화자를 순서대로 정한다. 개수가 같아야 한다",
        "parameters": {
            "type": "object",
            "properties": {
                "speakers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["teller", "customer"]},
                    "description": "sentences 와 같은 순서·같은 개수",
                },
                "reason": {"type": "string", "description": "마지막 문장의 화자 근거 한 문장"},
            },
            "required": ["speakers"],
            "additionalProperties": False,
        },
    },
}


def stream_chunks(script: dict, chunk: int) -> list[tuple[str, str, str]]:
    """(줄 id, 정답 화자, 문장 덩어리). 서버의 문장 분리로 나눈 뒤 chunk 개씩 묶는다."""
    out = []
    for line in script["lines"]:
        sents = utterances(line["text"])
        for i in range(0, len(sents), chunk):
            out.append((line["id"], line["speaker"], " ".join(sents[i : i + chunk])))
    return out


def complete(model: str, settings: Settings, prompt: str, body: dict, tool: dict) -> dict:
    kwargs = {}
    if settings.llm_no_reasoning:
        kwargs["extra_body"] = {"reasoning": {"enabled": False}}
    t0 = time.perf_counter()
    resp = litellm.completion(
        model=model,
        api_key=settings.llm_api_key,
        temperature=0.0,
        timeout=60,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False, indent=1)},
        ],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": tool["function"]["name"]}},
        **kwargs,
    )
    call = resp.choices[0].message.tool_calls[0]
    args = json.loads(call.function.arguments)
    args["tokens"] = getattr(resp.usage, "total_tokens", None)
    args["ms"] = round((time.perf_counter() - t0) * 1000)  # 재시도 대기는 빼고 마지막 호출만
    return args


def ask_labeled(
    model: str,
    settings: Settings,
    prompt: str,
    title: str,
    context: list[tuple[str, str]],
    text: str,
) -> dict:
    body = {
        "consultation": title,
        "recent": [{"speaker": s, "text": t} for s, t in context],
        "current": text,
    }
    return complete(model, settings, prompt, body, TOOL_ONE)


def ask_joint(model: str, settings: Settings, prompt: str, title: str, texts: list[str]) -> dict:
    body = {
        "consultation": title,
        "sentences": [{"n": i + 1, "text": t} for i, t in enumerate(texts)],
        "note": f"{len(texts)}개 문장 전부의 화자를 순서대로 정한다. "
        f"마지막(n={len(texts)})이 방금 온 문장이다",
    }
    args = complete(model, settings, prompt, body, TOOL_MANY)
    if len(args.get("speakers", [])) != len(texts):
        raise ValueError(f"speakers 개수 불일치 {len(args.get('speakers', []))}≠{len(texts)}")
    return args


def with_retry(fn, *a, tries: int = 3) -> dict:
    """일시 오류(429·5xx·툴 호출 누락·개수 불일치)는 잠깐 쉬고 다시 묻는다. 실험이 끊기지 않게."""
    for i in range(tries):
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 - 실험 스크립트. 종류를 가리지 않고 재시도
            if i == tries - 1:
                raise
            print(f"   (재시도 {i + 1}: {type(e).__name__}: {str(e)[:80]})")
            time.sleep(2 * (i + 1))
    raise AssertionError


def run(preset_dir: Path, model: str, settings: Settings, args: argparse.Namespace) -> list[dict]:
    """문장별 결과. got 은 스트림에서 즉시 낸 라벨, vote 는 joint 의 다수결 확정 라벨."""
    script = json.loads((preset_dir / "script.json").read_text(encoding="utf-8"))
    chunks = stream_chunks(script, args.chunk)
    prompt = PROMPTS[args.prompt]
    title = script["title"]
    rows: list[dict] = []
    votes: list[Counter] = [Counter() for _ in chunks]
    print(
        f"\n== {preset_dir.name} · {title} · {len(chunks)}덩어리 · {args.chunk}문장씩 · "
        f"{args.mode} · 윈도우 {args.window} · 프롬프트 {args.prompt}"
        + (" · 문맥=정답" if args.truth_context else "")
    )
    for i, (lid, truth, text) in enumerate(chunks):
        lo = max(0, i - args.window)
        if args.mode == "labeled":
            ctx = [(r["truth"] if args.truth_context else r["got"], r["text"]) for r in rows[lo:i]]
            a = with_retry(ask_labeled, model, settings, prompt, title, ctx, text)
            got = a["speaker"]
        else:
            a = with_retry(
                ask_joint, model, settings, prompt, title, [c[2] for c in chunks[lo : i + 1]]
            )
            for j, s in zip(range(lo, i + 1), a["speakers"], strict=True):
                votes[j][s] += 1
            got = a["speakers"][-1]
        ms = a["ms"]
        ok = got == truth
        mark = "  " if ok else "✗ "
        print(
            f"{mark}{lid} 정답 {truth:8s} 추정 {got:8s} {ms:5.0f}ms  {text[:40]}"
            + ("" if ok else f"   ← {a.get('reason', '')[:70]}")
        )
        rows.append(
            {
                "preset": preset_dir.name,
                "id": lid,
                "text": text,
                "truth": truth,
                "got": got,
                "reason": a.get("reason", ""),
                "ms": ms,
                "tokens": a.get("tokens"),
            }
        )
    for r, v in zip(rows, votes, strict=True):
        # 동률이면 즉시 라벨을 지킨다
        r["vote"] = max(v, key=lambda s: (v[s], s == r["got"])) if v else r["got"]
    n = len(rows)
    got_ok = sum(r["got"] == r["truth"] for r in rows)
    line = f"정확도 {got_ok}/{n}"
    if args.mode == "joint":
        line += f" · 다수결 {sum(r['vote'] == r['truth'] for r in rows)}/{n}"
    print(line)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 화자 추정 실험")
    ap.add_argument("preset", nargs="*", help="preset_id. 없으면 전부")
    ap.add_argument("--mode", choices=["labeled", "joint"], default="joint")
    ap.add_argument("--window", type=int, default=3, help="문맥으로 보여 주는 앞 문장 수")
    ap.add_argument("--prompt", choices=sorted(PROMPTS), default="plus")
    ap.add_argument("--chunk", type=int, default=1, help="한 번에 보내는 문장 수")
    ap.add_argument(
        "--truth-context",
        action="store_true",
        help="labeled 에서 앞 문장 화자를 정답으로 준다(상한)",
    )
    ap.add_argument("--json", type=Path, help="문장별 결과를 JSON 으로 저장")
    args = ap.parse_args()
    settings = Settings()
    if not settings.llm_model:
        raise SystemExit("APP_LLM_MODEL 이 없습니다. .env 를 확인하세요.")
    model = register(settings.llm_model, settings.llm_provider, "chat")
    presets = [SCENARIOS / p for p in args.preset] or sorted(
        d for d in SCENARIOS.iterdir() if (d / "script.json").exists()
    )
    rows: list[dict] = []
    for d in presets:
        rows += run(d, model, settings, args)
    n = len(rows)
    ms = sum(r["ms"] for r in rows) / max(n, 1)
    line = f"\n전체 {sum(r['got'] == r['truth'] for r in rows)}/{n}"
    if args.mode == "joint":
        line += f" · 다수결 {sum(r['vote'] == r['truth'] for r in rows)}/{n}"
    print(f"{line} · 평균 {ms:.0f}ms  ({settings.llm_provider}/{settings.llm_model})")
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
