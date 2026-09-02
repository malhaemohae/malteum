# back/regwatch — 규정 개정 일일 감시 (임한빈)

공개 규정 원천 7종의 개정을 매일 확인해 팩 재발행 필요를 알린다. 감시 대상 정의는 `config/sources.json`, 실행은 `scripts/`(Windows 작업 스케줄러).

## 허용 import

표준 라이브러리만. `server`·`engine`·`rulepack`·`contracts` 전부 금지 — 완전 독립 모듈이며, 다른 모듈도 regwatch 를 import 하지 않는다 (import-linter 가 강제).

## 규칙

- 원천 응답은 결정적 지문(fingerprint)으로 비교한다. 시계·세션 토큰 같은 잡음은 지문 계산 전에 제거한다.
- 한 원천의 실패가 다른 원천 감시를 막지 않는다 (장애 격리). 실패는 exit code 2 로 드러낸다.
- 감시가 볼 수 있는 것은 공개 원천까지다. 은행 내부 법규집 연동은 도입 기관 몫.
- 개정 감지 결과는 보고서 파일로만 남긴다. 팩 재발행 여부 판단과 실행은 사람(M3 담당)이 한다.
