# deploy/ — 홈서버 배포

`main` 에 push(merge 포함)가 오면 홈서버 Jenkins 가 `Jenkinsfile` 을 돌린다. 경로는 하나다.

```
GitHub push(main) → webhook → https://jenkins.gjguswns.com/github-webhook/
  → job `malteum-deploy` (Pipeline from SCM, main, Jenkinsfile)
  → .env (저장소의 .env.age 를 age 개인키 자격증명 `malteum-age-key` 로 복호화) → docker compose up --build --wait → seed → health
```

| 조각 | 어디 | 비고 |
| --- | --- | --- |
| 파이프라인 | `Jenkinsfile` | 저장소가 정본. Jenkins 화면에서 고치지 않는다 |
| 루트 `.env` | 저장소의 `.env.age` (age 암호문) + Jenkins 자격증명 `malteum-age-key` (Secret text, 개인키) | 평문은 저장소에 없다. 값을 바꾸면 `tools/envsecret.py encrypt` 로 다시 암호화해 커밋한다 — 배포가 자동으로 새 값을 쓴다 |
| 화자 분리 사이드카 | `compose.yaml` 의 `diarization` (`back/sidecar/diarization`) | CPU Sortformer. STT 가 화자 번호를 안 줄 때(OpenAI) 화자 단계가 이것으로 접착한다 |
| 리버스 프록시 | `deploy/nginx/malteum.conf` → `/etc/nginx/conf.d/` | `malteum.gjguswns.com` · `/api/`·`/ws` → 8000, `/` → 3000(프런트) |
| 컨테이너 | `compose.yaml` | 프로젝트명 `malteum` 고정이라 워크스페이스 경로가 바뀌어도 볼륨(pgdata·hfcache·uploads)은 그대로 |

## .env 다루기 (팀원용)

`.env` 는 `age` 로 암호화해 `.env.age` 로 커밋한다. 개인키(`.secret`)는 Bitwarden 으로 공유하고 저장소에는 없다.
파이썬만 있으면 되고(윈도우 포함), age 구현(pyrage)은 스크립트가 알아서 설치한다.

```bash
# 처음 받을 때: 공유받은 개인키를 레포 루트에 .secret 으로 두고
python tools/envsecret.py decrypt              # .env.age → .env

# 값을 바꿨을 때
python tools/envsecret.py encrypt              # .env → .env.age  (커밋)

# 풀 수 있는 사람을 늘릴 때 (그 사람이 keygen 으로 만든 공개키를 받아서)
python tools/envsecret.py add-key age1...  --label 이름   # deploy/env.recipients 에 추가 + 다시 암호화
python tools/envsecret.py keys                 # 수신자 목록
```

개인키가 새면 `python tools/envsecret.py keygen --force` 로 새로 발급하고, `deploy/env.recipients` 에서 옛 키를
지운 뒤 `encrypt` 하고, Jenkins 자격증명 `malteum-age-key` 의 값을 새 개인키로 바꾼다.

## 배포용 .env 에서 로컬과 다른 것

- `SERVER_PORT=127.0.0.1:8000`, `POSTGRES_PORT=127.0.0.1:5432` — nginx 뒤에 있으니 밖으로 열지 않는다. compose 는 `호스트IP:포트` 꼴을 그대로 받는다
- `APP_EMBEDDING_MODEL=intfloat/multilingual-e5-small`, `APP_EMBEDDING_DIM=384` — 팩(`contracts/fixtures`)의 임베딩과 같아야 L2 가 돈다
- STT: `APP_STT_PROVIDER=openai_file`, `APP_STT_BASE_URL=https://api.openai.com`, `APP_STT_MODEL=gpt-4o-transcribe`, `APP_STT_API_KEY=<OpenAI 키>` — 화자 구간마다 배치 전사. Realtime 어댑터가 오면 `openai_realtime` 로 바꾼다(`back/server/services/stt/README.md`). 화자 분리 주소는 compose 기본값 `ws://diarization:8300/ws`
- `APP_L3_BUDGET_MS` 는 compose 기본값 3000. OpenRouter 왕복 1.2~2.4초 실측(2026-09-04). 느린 시간대에 L3 판정이 빠지면 여기를 올린다

## 호스트에서 한 번 (root 필요)

```bash
sudo usermod -aG docker jenkins && sudo systemctl restart jenkins   # Jenkins 가 docker 를 부른다
sudo install -m 644 deploy/nginx/malteum.conf /etc/nginx/conf.d/ && sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable docker                                         # 재부팅 뒤 자동 기동 (README 리스크 5)
```

## 손으로 다시 돌리기

Jenkins 에서 `malteum-deploy` ▶ Build Now. 워크스페이스는 `/var/lib/jenkins/workspace/malteum-deploy` 이고 거기서 `docker compose logs -f server` 가 된다.
