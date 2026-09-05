# speaker_infer — LLM 문장 단위 화자 추정(qwen3-8b/32b, 슬라이딩 윈도우, 프롬프트 보강)

원본: `speaker/` (스크래치, 2026-09-03/04) + 워크트리 `scratchpad/wt/back/scripts/speaker_infer_check.py`(미커밋 수정본). 수치·판단은 `RESULT.md` 참고.

## 실행 환경

- `speaker_infer_check.py` 는 openrouter 경유로 LLM 을 호출한다(`.env` 의 `APP_LLM_PROVIDER`·`APP_LLM_API_KEY`·`APP_LLM_MODEL`). 로컬 모델·GPU 불필요.
- **이 파일은 레포 `back/scripts/speaker_infer_check.py`(브랜치 `feat/speaker-infer-check`)의 수정본이다.** 모드·윈도우·프롬프트 옵션이 추가되어 있으며, 원본 레포 파일은 건드리지 않았다. 실험을 재현하려면 이 옵션들을 원본 레포 파일에 반영하거나, 이 파일을 그대로 가져다 쓴다.
- `m8b.*.json`, `m32b.*.json` 은 각 조건(문맥 방식·윈도우·프롬프트)의 원본 실행 결과다.

## 재현 명령

```bash
# 기존 방식(라벨 문맥 6문장) · 기존 프롬프트
python speaker_infer_check.py --mode labeled --window 6 --prompt base --json m8b.labeled6_base.json

# 슬라이딩 (b): 앞 3 + 현재 1 = 4문장을 한 번에 판정 · 보강 프롬프트 (8b 기본값)
python speaker_infer_check.py --mode joint --window 3 --prompt plus --json m8b.joint3_plus.json
```

`preset` 인자를 생략하면 `preset-dep-a`·`preset-loan-b` 두 시나리오를 모두 돈다. `--mode`/`--window`/`--prompt` 조합은 `RESULT.md` 의 표를 참고.
