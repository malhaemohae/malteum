# assets/

- `03_규정문서/` — 규정 PDF 7종. 전부 공개 자료이고 레포에 포함한다(rulepack 테스트가 원문을 직접 열어 근거 스팬을 대조하므로 원문이 있어야 CI 가 돈다). 출처·발행 기관·스냅샷 일자는 `MANIFEST.md`. 주담대 시연은 `06_상품설명서_가계대출`, 위험 신호 근거는 `07_제2차_금융분야_보이스피싱_대책` 을 쓴다.
- `extraction/`: 규정 PDF 7종의 구조 추출 덤프(JSON). `back/scripts/dump_extraction.py` 가 오프라인에서 떠서 커밋하고, 서버의 원문 추출·업로드 경로가 자바 없이 이걸 읽는다(M1).
- `scenarios/<id>/`: 시연 시나리오. `script.json`(대사·화자·시각·TTS 발음·기대 판정과 pack_version·customer_type·mode 메타. TTS 제작·조립과 서버 재생의 입력) · `audio.wav`(TTS 클립을 조립해 사람이 듣고 확정한 단일 음원. 커밋한다. 줄별 클립 캐시 `clips/` 는 제외). 시나리오 A 의 이벤트 trace 는 여기 두지 않고 `back/contracts/fixtures/events_scenario_a.json` 을 `back/scripts/gen_scenario_trace.py` 로 대본에서 생성한다. 사람이 읽는 대본과 제작·검증 지침은 `scenarios/SCRIPT.md`.
