# front/ — M4 web (서재오)

Next.js 루트. 프레임워크·상태 관리·컴포넌트 구조는 담당자가 정한다.

## 계약

- 서버와의 접점은 WebSocket(`back/contracts/ws_protocol.schema.json`)과 REST(`back/contracts/api.openapi.yaml`)뿐이다.
- 서버 없이 화면을 그릴 때는 `back/contracts/fixtures/ws_messages.json`(c2s·s2c 25건)을 그대로 재생한다. 이 파일이 화면의 정답이다.
- `verdict`는 항목별 `ver`가 큰 것만 채택한다(L1이 ver 1, L3가 ver 2로 고친다). 순서 뒤바뀜을 프런트가 흡수한다.
- 상태 집계(`progress`)는 서버가 보낸다. 프런트는 이벤트를 접지 않는다.
- 오디오 업링크는 바이너리 프레임: 앞 4바이트 빅엔디언 seq + 16kHz mono PCM16 100ms(3,200바이트).

## 경계

- `back/` 파이썬 코드를 import하거나 읽어서 동작을 추측하지 않는다. 스키마와 fixtures만 본다.
- 하트비트: 서버 `ping`(s2c)에 `pong`(c2s)으로 답한다.
