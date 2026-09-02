#!/bin/sh
# 세션 이벤트 백업·복구. 레포 루트에서 돌린다.
#
# 왜 필요한가
#     `session_events` 가 증빙의 정본이고 append-only 라, 날아가면 복원할 원본이 없다.
#     세션 이력(S5)·리포트(C축 DoD)·trace 재생이 통째로 사라진다. 지금 그 전부가
#     `pgdata` 볼륨 하나에 들어 있다.
#
# 왜 컨테이너 안에서 뜨나
#     pg_dump 는 db 이미지에 이미 있다. 호스트에 postgres 클라이언트를 따로 깔면
#     서버 버전과 어긋날 때 조용히 실패한다.
#
# 사용
#     scripts/backup.sh dump [출력경로]         기본: backups/malteum-<날짜시각>.sql
#     scripts/backup.sh restore <파일> --yes    지우고 덮어쓴다. --yes 없으면 거절
#     scripts/backup.sh verify                  행 수만 세어 본다
#
# restore 가 묻지 않고 플래그를 받는 이유
#     되묻는 프롬프트는 stdin 을 읽는다. 그러면 파이프·비대화 셸에서 조용히 깨지고,
#     정작 복구가 급한 새벽에 터진다. 위험한 명령일수록 손이 아니라 플래그로 막는다.
set -eu

DB_SERVICE=db
DB_USER="${POSTGRES_USER:-app}"
DB_NAME="${POSTGRES_DB:-app}"
ROOT="$(cd "$(dirname "$0")/.." && cd .. && pwd)"
cd "$ROOT"

counts() {
    docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -tA -c \
        "SELECT 'sessions='||(SELECT count(*) FROM sessions)
             ||' events='||(SELECT count(*) FROM session_events)
             ||' packs='||(SELECT count(*) FROM rule_packs)
             ||' embeddings='||(SELECT count(*) FROM pack_embeddings)"
}

case "${1:-}" in
dump)
    out="${2:-backups/malteum-$(date +%Y%m%d-%H%M%S).sql}"
    mkdir -p "$(dirname "$out")"
    # --clean --if-exists: 복구가 기존 것을 지우고 다시 만든다. 반쯤 겹친 상태를 안 만든다
    docker compose exec -T "$DB_SERVICE" \
        pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists > "$out"
    printf '백업: %s (%s)\n  %s\n' "$out" "$(wc -c < "$out" | tr -d ' ') bytes" "$(counts)"
    ;;
restore)
    file="${2:?복구할 파일을 지정하세요}"
    [ -f "$file" ] || { echo "파일이 없습니다: $file" >&2; exit 1; }
    if [ "${3:-}" != "--yes" ]; then
        printf '지금 상태: %s\n' "$(counts)" >&2
        printf '이 명령은 위 내용을 지우고 %s 로 덮어씁니다.\n실행하려면 --yes 를 붙이세요.\n' "$file" >&2
        exit 1
    fi
    printf '복구 전: %s\n' "$(counts)"
    docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -q < "$file"
    printf '복구 후: %s\n' "$(counts)"
    ;;
verify)
    printf '%s\n' "$(counts)"
    ;;
*)
    sed -n '2,20p' "$0"
    exit 1
    ;;
esac
