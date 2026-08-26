# back/engine — M2 engine (허현준)

`contracts/engine_contract.py`의 `Engine` Protocol 구현. 판정 L1(규칙) → L2(의미 검색) → L3(LLM 심판), assist(answer·rephrase·briefing·documents), 상태 접기(fold).

## 허용 import

`contracts`만. `server`·`rulepack`은 금지.

## 규칙

- **WebSocket·DB를 모른다.** 입력·출력은 dataclass. 봉투(`event_id` 등)는 만들지 않는다.
- **상태를 들고 있지 않다.** 상태는 인자로 받고 새 객체를 돌려준다. 같은 (발화, 팩, 상태)면 같은 결과. 유일한 비결정 지점은 L3이고 어댑터 뒤에 있다.
- 외부 의존(`Embedder`·`VectorIndex`·`LlmJudge`·`DecisionCache`·`PackSource`)은 전부 Protocol + `adapters/`의 실물·fake 쌍. 테스트는 fake로 돈다.
- `judge()`는 동기: l0 사전 치환(숫자 제외) → L1 → L2, 잠정 판정 즉시 반환. `refine()`은 비동기: 후보 id 열거 → LLM 교정(tool_choice 강제, 후보 중 선택만) → L3 심판. 예산 L1 5ms · L1+L2 20ms · L3 1500ms.
- **숫자는 어느 단계에서도 교정하지 않고 경보로 넘긴다.**
- 근거 없는 문장을 만들지 않는다(P4). `answer`·`rephrase`는 근거가 없으면 `None`.
- 노드는 얇게, 로직은 `tiers/` 순수 함수에. 그래프 없이 단위 테스트가 돌아야 한다.
- `fold`는 실시간 화면과 리포트가 같은 함수를 쓴다. supersede된 이벤트는 건너뛴다.

## 목표 구조

`DESIGN.md`(워크벤치) 3절. 파일이 생길 때 그 자리에 만든다.
