# L1 판정 생존율 — 실제 STT 가설 14벌 × 대본의 L1 기대 판정 11건 (2026-09-04)

이 폴더의 다른 실험이 저장해 둔 줄 단위 전사(`qwen_asr/eval_*.json`, `nemotron/*_eval.json`,
`elevenlabs/*_eval.json` 의 `lines[].hyp`)를 엔진(LLM 없음)에 넣고, 대본 `script.json` 의 `expect` 가
`… L1` 로 끝나는 판정 11건(dep-a 4, loan-b 7)이 L1 에서 그대로 나오는지 센다. 연속 스트리밍 "full" 3벌은
줄 정렬이 없어 제외(154 = 11 × 14).

```bash
cd back && .venv/bin/python scripts/experiments/stt/l1_survival/l1_survival.py <레포 루트>   # MISS 를 뒤에 붙이면 놓친 줄을 찍는다
```

| STT 가설 | dev(#20 까지) | #21 (L0 영문 교정 · L1 띄어쓰기 · 되물음 · B09 패턴) |
|---|---|---|
| ElevenLabs Scribe v1 | 10 | 11 |
| ElevenLabs Scribe v2 | 10 | 11 |
| Nemotron 오프라인 | 8 | 8 |
| Nemotron 스트리밍 1.12s | 6 | 6 |
| Nemotron 스트리밍 0.32s | 3 | 4 |
| Qwen 0.6B clips (CPU) | 7 | 10 |
| Qwen 0.6B clips (GPU) | 7 | 10 |
| Qwen 0.6B seg (GPU) | 8 | 11 |
| Qwen 0.6B seg (CPU) | 8 | 11 |
| Qwen 1.7B clips (GPU) | 8 | 10 |
| Qwen 1.7B seg (GPU) | 10 | 11 |
| Qwen 0.6B 스트리밍 (CPU) | 7 | 10 |
| Qwen 0.6B 스트리밍 (GPU) | 8 | 11 |
| Qwen 1.7B 스트리밍 (GPU) | 9 | 11 |
| **합계** | **109 / 154 (71%)** | **135 / 154 (88%)** |

- 가장 많이 오른 곳: Qwen 0.6B(복합어를 자주 띄움 → L1 keyword 띄어쓰기 둔감 매칭)와 B09 위험 신호(전 엔진이
  "다른 상환 방식은" 으로 띄어 냈는데 패턴이 붙여쓰기만 허용했던 것).
- Nemotron 스트리밍이 그대로인 이유: "약 전 기율", "차갑률" 처럼 음절이 갈라지고 글자가 바뀐다. L1 범위 밖이고 L2 후보 → L3 몫.
- 표본이 대본 두 편 × 11건이라 방향은 분명하지만 절대 수치는 크게 보지 말 것.
