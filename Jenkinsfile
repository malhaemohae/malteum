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
                // 루트 .env 는 age 로 암호화된 .env.age 로 저장소에 있다(tools/envsecret.py).
                // 개인키만 Jenkins Secret text 자격증명 `malteum-age-key` 에 있다. 호스트에
                // pyrage·age 를 깔지 않으려고 파이썬 컨테이너에서 푼다(현재 사용자로 실행해
                // .env 소유자가 jenkins 가 되게 한다)
                withCredentials([string(credentialsId: 'malteum-age-key', variable: 'MALTEUM_AGE_KEY')]) {
                    sh '''
                      rm -f .env
                      docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e MALTEUM_AGE_KEY \
                        -v "$PWD:/w" -w /w python:3.12-slim \
                        sh -c "pip install -q --target /tmp/py pyrage && PYTHONPATH=/tmp/py python tools/envsecret.py decrypt"
                      test -s .env
                    '''
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
