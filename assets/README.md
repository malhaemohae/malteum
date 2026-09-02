# assets/

- `03_규정문서/` — 규정 PDF 7종. 전부 공개 자료이고 레포에 포함한다(rulepack 테스트가 원문을 직접 열어 근거 스팬을 대조하므로 원문이 있어야 CI 가 돈다). 출처·발행 기관·스냅샷 일자는 `MANIFEST.md`. 주담대 시연은 `06_상품설명서_가계대출`, 위험 신호 근거는 `07_제2차_금융분야_보이스피싱_대책` 을 쓴다.
- `scenarios/<id>/`: 시연 시나리오. `script.json`(대사·화자·시각·기대 판정, TTS 제작과 클라이언트 재생의 입력) · `manifest.json`(pack_version · customer_type · mode) · `audio.wav`(git 제외) · `trace.json`. 사람이 읽는 대본과 제작·검증 지침은 `scenarios/SCRIPT.md`.
