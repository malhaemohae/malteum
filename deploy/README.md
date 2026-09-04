# deploy/ — 홈서버 배포

`main` 에 push(merge 포함)가 오면 홈서버 Jenkins 가 `Jenkinsfile` 을 돌린다. 경로는 하나다.

```
GitHub push(main) → webhook → https://jenkins.gjguswns.com/github-webhook/
  → job `malteum-deploy` (Pipeline from SCM, main, Jenkinsfile)
  → .env (Secret file 자격증명 `malteum-env`) → docker compose up --build --wait → seed → health
```

| 조각 | 어디 | 비고 |
| --- | --- | --- |
| 파이프라인 | `Jenkinsfile` | 저장소가 정본. Jenkins 화면에서 고치지 않는다 |
| 루트 `.env` | Jenkins 자격증명 `malteum-env` (Secret file) | 키·토큰이 들어 있어 저장소에 없다. 바꾸면 자격증명을 갱신하고 다시 빌드 |
| 리버스 프록시 | `deploy/nginx/malteum.conf` → `/etc/nginx/conf.d/` | `malteum.gjguswns.com` · `/api/`·`/ws` → 8000, `/` → 3000(프런트) |
| 컨테이너 | `compose.yaml` | 프로젝트명 `malteum` 고정이라 워크스페이스 경로가 바뀌어도 볼륨(pgdata·hfcache·uploads)은 그대로 |

## 배포용 .env 에서 로컬과 다른 것

- `SERVER_PORT=127.0.0.1:8000`, `POSTGRES_PORT=127.0.0.1:5432` — nginx 뒤에 있으니 밖으로 열지 않는다. compose 는 `호스트IP:포트` 꼴을 그대로 받는다
- `APP_EMBEDDING_MODEL=intfloat/multilingual-e5-small`, `APP_EMBEDDING_DIM=384` — 팩(`contracts/fixtures`)의 임베딩과 같아야 L2 가 돈다

## 호스트에서 한 번 (root 필요)

```bash
sudo usermod -aG docker jenkins && sudo systemctl restart jenkins   # Jenkins 가 docker 를 부른다
sudo install -m 644 deploy/nginx/malteum.conf /etc/nginx/conf.d/ && sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable docker                                         # 재부팅 뒤 자동 기동 (README 리스크 5)
```

## 손으로 다시 돌리기

Jenkins 에서 `malteum-deploy` ▶ Build Now. 워크스페이스는 `/var/lib/jenkins/workspace/malteum-deploy` 이고 거기서 `docker compose logs -f server` 가 된다.
