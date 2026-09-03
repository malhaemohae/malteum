#!/usr/bin/env python3
"""화자 추정 도구 실험. STT 가 화자 분리를 못 줄 때 LLM 이 맥락으로 `teller`·`customer` 를
붙일 수 있는지 잰다.

시연 대본(`assets/scenarios/*/script.json`)의 줄을 서버와 같은 문장 분리(`assembler.utterances`)로
나눠, 화자 라벨 없이 순서대로 한 덩어리씩 LLM 에 보낸다. LLM 은 `assign_speaker` 툴 하나로
답한다. 앞 덩어리의 라벨은 정답이 아니라 **LLM 이 스스로 붙인 것**을 문맥으로 준다 —
실제 스트림에서도 정답을 모르기 때문이다(`--truth-context` 로 정답을 주면 상한을 본다).

사용 (back/ 에서)
    uv run python scripts/speaker_infer_check.py                    # 두 시나리오, 1문장 단위
    uv run python scripts/speaker_infer_check.py --chunk 2          # 2문장씩 (STT final 이 길 때)
    uv run python scripts/speaker_infer_check.py --truth-context    # 앞 화자를 정답으로 준 상한
    APP_LLM_PROVIDER · APP_LLM_API_KEY · APP_LLM_MODEL 을 .env 에서 읽는다 (test_live_llm 과 같다).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import litellm

BACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACK))

from engine.adapters.llm.litellm import register  # noqa: E402
from server.bootstrap.settings import Settings  # noqa: E402
from server.services.stt.assembler import utterances  # noqa: E402

SCENARIOS = BACK.parent / "assets" / "scenarios"
CONTEXT_TURNS = 6

SYSTEM_PROMPT = """당신은 은행 창구 상담 녹취의 화자를 가려내는 역할이다.
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

TOOL = {
    "type": "function",
    "function": {
        "name": "assign_speaker",
        "description": "방금 온 문장의 화자를 정한다",
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


def stream_chunks(script: dict, chunk: int) -> list[tuple[str, str, str]]:
    """(줄 id, 정답 화자, 문장 덩어리). 서버의 문장 분리로 나눈 뒤 chunk 개씩 묶는다."""
    out = []
    for line in script["lines"]:
        sents = utterances(line["text"])
        for i in range(0, len(sents), chunk):
            out.append((line["id"], line["speaker"], " ".join(sents[i : i + chunk])))
    return out


def ask(
    model: str, settings: Settings, context: list[tuple[str, str]], text: str, title: str
) -> dict:
    body = {
        "consultation": title,
        "recent": [{"speaker": s, "text": t} for s, t in context],
        "current": text,
    }
    kwargs = {}
    if settings.llm_no_reasoning:
        kwargs["extra_body"] = {"reasoning": {"enabled": False}}
    resp = litellm.completion(
        model=model,
        api_key=settings.llm_api_key,
        temperature=0.0,
        timeout=30,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False, indent=1)},
        ],
        tools=[TOOL],
        tool_choice={"type": "function", "function": {"name": "assign_speaker"}},
        **kwargs,
    )
    call = resp.choices[0].message.tool_calls[0]
    args = json.loads(call.function.arguments)
    args["tokens"] = getattr(resp.usage, "total_tokens", None)
    return args


def ask_retry(*a, tries: int = 3) -> dict:
    """일시 오류(429·5xx·툴 호출 누락)는 잠깐 쉬고 다시 묻는다. 실험이 중간에 끊기지 않게."""
    for i in range(tries):
        try:
            return ask(*a)
        except Exception as e:  # noqa: BLE001 - 실험 스크립트. 종류를 가리지 않고 재시도
            if i == tries - 1:
                raise
            print(f"   (재시도 {i + 1}: {type(e).__name__}: {str(e)[:80]})")
            time.sleep(2 * (i + 1))
    raise AssertionError


def run(
    preset_dir: Path, model: str, settings: Settings, chunk: int, truth_context: bool
) -> tuple[int, int]:
    script = json.loads((preset_dir / "script.json").read_text(encoding="utf-8"))
    chunks = stream_chunks(script, chunk)
    context: list[tuple[str, str]] = []
    correct = 0
    print(
        f"\n== {preset_dir.name} · {script['title']} · {len(chunks)}덩어리 · {chunk}문장씩"
        + (" · 문맥=정답" if truth_context else " · 문맥=LLM 라벨")
    )
    for lid, truth, text in chunks:
        t0 = time.perf_counter()
        a = ask_retry(model, settings, context[-CONTEXT_TURNS:], text, script["title"])
        ms = (time.perf_counter() - t0) * 1000
        got = a["speaker"]
        ok = got == truth
        correct += ok
        mark = "  " if ok else "✗ "
        print(
            f"{mark}{lid} 정답 {truth:8s} 추정 {got:8s} {a.get('confidence', 0):.2f} "
            f"{ms:5.0f}ms  {text[:40]}" + ("" if ok else f"   ← {a.get('reason', '')[:60]}")
        )
        context.append((truth if truth_context else got, text))
    print(f"정확도 {correct}/{len(chunks)}")
    return correct, len(chunks)


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 화자 추정 실험")
    ap.add_argument("preset", nargs="*", help="preset_id. 없으면 전부")
    ap.add_argument("--chunk", type=int, default=1, help="한 번에 보내는 문장 수")
    ap.add_argument(
        "--truth-context", action="store_true", help="앞 문장 화자를 정답으로 준다(상한)"
    )
    args = ap.parse_args()
    settings = Settings()
    if not settings.llm_model:
        raise SystemExit("APP_LLM_MODEL 이 없습니다. .env 를 확인하세요.")
    model = register(settings.llm_model, settings.llm_provider, "chat")
    presets = [SCENARIOS / p for p in args.preset] or sorted(
        d for d in SCENARIOS.iterdir() if (d / "script.json").exists()
    )
    total = (0, 0)
    for d in presets:
        c, n = run(d, model, settings, args.chunk, args.truth_context)
        total = (total[0] + c, total[1] + n)
    print(f"\n전체 {total[0]}/{total[1]}  ({settings.llm_provider}/{settings.llm_model})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
