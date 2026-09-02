// 홈서버 Jenkins 가 main 을 감시해 배포한다. GitHub webhook(push) → 이 파이프라인.
// 배포 = compose 재빌드·기동 → 팩·시연 이벤트 적재 → 헬스 확인. 자세한 것은 deploy/README.md
pipeline {
    agent any
    options {
        disableConcurrentBuilds()   // 배포 둘이 겹치면 compose 가 서로 밟는다
        timestamps()
    }
    triggers { githubPush() }

    stages {
        stage('env') {
            steps {
                // 루트 .env 는 저장소에 없다(.gitignore). Jenkins Secret file 자격증명에서 꺼낸다
                withCredentials([file(credentialsId: 'malteum-env', variable: 'ENV_FILE')]) {
                    sh 'install -m 600 "$ENV_FILE" .env'
                }
            }
        }
        stage('up') {
            steps {
                // --wait: compose 의 healthcheck(db pg_isready · server /api/health status=ok)가
                // 전부 통과할 때까지 기다리고, 못 하면 실패로 끝난다. 죽은 줄 모르는 배포가 없게
                sh 'docker compose up --build -d --remove-orphans --wait --wait-timeout 600'
            }
        }
        stage('seed') {
            steps {
                // Makefile `make seed` 와 같다. --replace 라 다시 돌려도 같은 결과
                sh 'docker compose exec -T server python scripts/load_pack.py --replace --unsigned'
                sh 'docker compose exec -T server python scripts/seed_session.py --replace'
            }
        }
        stage('health') {
            steps {
                sh 'docker compose exec -T server python scripts/watch_health.py http://localhost:8000 --once'
            }
        }
    }
    post {
        failure {
            sh 'docker compose ps || true; docker compose logs --tail 100 server || true'
        }
    }
}
