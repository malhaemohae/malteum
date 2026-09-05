# 로컬 통합 실행

저장소 루트에서 실행합니다. 백엔드 소스와 계약은 바꾸지 않으며 로컬 설정·스크립트는 `front/`에 둡니다.

현재 실제 연동은 가능하지만 서비스 최종 승인은 보류입니다. [백엔드 통합 검수 결과](BACKEND_INTEGRATION_FINDINGS_20260905.md)의 숫자 경보/종료 처리 두 건이 수정돼야 합니다.

## 실행

Docker Desktop이 켜진 상태에서 터미널 두 개를 사용합니다.

```powershell
# 터미널 1: PostgreSQL + 화자 분리 Docker, 마이그레이션, 실제 백엔드
.\back\.venv\Scripts\python.exe front/scripts/local-backend.py

# 최초 DB에 공식 개발 팩을 넣을 때만 --seed 추가. 기존 팩은 덮어쓰지 않음.
# .\back\.venv\Scripts\python.exe front/scripts/local-backend.py --seed

# 터미널 2: 프론트
cd front
npm run dev -- --hostname 127.0.0.1
```

- 프론트: `http://127.0.0.1:3000`
- 백엔드: `http://127.0.0.1:8000/api/health`
- 로컬 DB: `127.0.0.1:15432`, 기존 `malteum_pgdata` 볼륨 유지. 이 PC의 Windows 예약 포트 범위에 5432가 포함돼 15432를 사용합니다.
- 화자 분리: `127.0.0.1:8300`. 공식 `compose.yaml`에 `front/compose.local.yaml`을 추가 적용해 Windows 백엔드에서 접속합니다.
- API 호출은 프론트의 `/api` 프록시, WebSocket은 `.env.local`의 로컬 8000 주소를 사용합니다.
- 첫 화자 분리 이미지 빌드와 모델 다운로드에는 시간이 걸립니다. `/health`가 정상이어도 실제 음성 테스트 결과를 별도로 확인해야 합니다.

## 키와 관리자 인증

팀 `.env.age`는 기존 `tools/envsecret.py`를 재사용해 복호화합니다. 공유받은 개인키가 있어야 하며 새 키를 생성하지 않습니다.

```powershell
# front/.env.backend.local이 아직 없을 때만. 기존 파일은 덮어쓰지 않습니다.
.\back\.venv\Scripts\python.exe front/scripts/local-backend.py --secret-file "개인키 파일의 실제 경로"
```

복호화 결과는 Git에서 제외된 `front/.env.backend.local`에 저장됩니다. 외부 API 키는 백엔드 프로세스에만 전달됩니다. 이 실행기는 팀 환경 파일의 DB 주소 대신 로컬 DB 주소를 강제해 운영 DB를 마이그레이션하지 않습니다.

팀 환경에 `APP_ADMIN_TOKEN`이 없으면 최초 실행에서 암호학적 난수로 로컬 토큰을 만들어 Git 제외 파일 `front/.admin-token`에 보관합니다. 기준 관리의 **관리자 인증**에서 이 토큰을 입력합니다. 토큰은 브라우저 메모리에만 유지되고 새로고침 시 해제되며, `NEXT_PUBLIC_*` 환경변수에 넣지 않습니다. 관리자 토큰은 문서 추출 조회·업로드·후보 승인·팩 발행 요청에만 전달됩니다.

로컬 업로드는 Git 제외 경로 `front/.local/uploads`에 저장됩니다. `.env.backend.local`, `.admin-token`, `.local`을 커밋하거나 공유하지 마세요. 원래 전달받은 개인키 파일은 수정하지 않습니다.

## 검증

배포용 `front/Dockerfile`은 `front/`만 빌드 컨텍스트로 사용합니다. 랜딩 예시 데이터는 `lib/landing-preview-data.json`에 필요한 값만 포함하며, `node scripts/landing-qa.cjs`로 계약 fixture와의 일치를 검사합니다. `.dockerignore`는 환경 파일·개인키·관리자 토큰·로컬 업로드·검수 결과를 이미지에서 제외합니다.

```powershell
cd front
node scripts/contract-qa.cjs
node scripts/workspace-qa.cjs
node scripts/admin-qa.cjs
node scripts/candidate-qa.cjs
node scripts/voice-qa.cjs
node scripts/integration-findings.cjs

# 실제 종료 세션을 저장한 뒤 DB와 백엔드를 재시작하고 비교
node scripts/persistence-qa.cjs snapshot
# 로컬 DB/백엔드 재시작
node scripts/persistence-qa.cjs verify

# 실행 중인 dev 번들과 충돌하지 않는 프로덕션 빌드
$env:MALTEUM_NEXT_DIST_DIR='.next-verify'
npm run build
```

`voice-qa`는 저장소의 합성 상담 음원을 Chromium의 마이크 입력으로 사용합니다. 전사·판정·저장은 실제 서비스이며 사람의 마이크나 주변 대화는 녹음하지 않습니다. 외부 전사·LLM 호출 비용이 발생할 수 있습니다. 검사 결과와 스크린샷은 Git 제외 경로 `front/qa-output/`에 저장됩니다.

`admin-qa`는 인증·추출 조회·잘못된 요청 거부·불변 팩 중복 발행 거부를 검증합니다. 실제 규정 후보를 임의 승인하거나 새 운영 팩을 발행하지 않습니다.
