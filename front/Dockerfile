# Next.js standalone 이미지. `next.config.mjs` 가 이미 output: 'standalone' 이라
# 빌드가 필요한 것만 추린 서버를 내놓고, 마지막 단계는 그것만 담는다.
#
# **두 값은 빌드 시점에 박힌다.** 실행할 때 넣어도 안 먹으므로 build arg 로 받는다.
#   NEXT_PUBLIC_*        클라이언트 번들에 인라인된다. 브라우저가 읽을 값이라 서버
#                        환경변수로는 전달될 자리가 없다
#   MALTEUM_BACKEND_URL  next.config.mjs 의 rewrites() 결과가 빌드 때
#                        routes-manifest.json 으로 굳는다
FROM node:20-alpine AS deps
WORKDIR /app
# 락파일만 먼저 넣어 의존성 층을 캐시한다. 소스가 바뀌어도 재설치가 안 일어난다
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
ARG MALTEUM_BACKEND_URL=http://server:8000
# **기본은 빈 값이다.** 비어 있으면 `lib/api.ts` 의 `wsUrl` 이 브라우저 주소에서
# `wss://<호스트>/ws` 를 스스로 만든다 — nginx 뒤에서는 그게 맞고, 도메인이 바뀌어도
# 다시 안 구워도 된다. 값을 주면 그 분기가 막히는데, 상대 경로를 주면
# `new WebSocket('/ws')` 가 던진다. 백엔드를 다른 호스트에 둘 때만 절대 URL 로 채운다
ARG NEXT_PUBLIC_MALTEUM_WS_URL=
ARG NEXT_PUBLIC_MALTEUM_API_BASE_URL=/api
ENV MALTEUM_BACKEND_URL=$MALTEUM_BACKEND_URL \
    NEXT_PUBLIC_MALTEUM_WS_URL=$NEXT_PUBLIC_MALTEUM_WS_URL \
    NEXT_PUBLIC_MALTEUM_API_BASE_URL=$NEXT_PUBLIC_MALTEUM_API_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
# standalone 은 필요한 node_modules 를 스스로 안고 나온다. static·public 은 그 밖이라 따로
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
# 루트로 두면 컨테이너가 침해됐을 때 이미지 안을 마음대로 쓴다. node 이미지의 비루트 계정
USER node
EXPOSE 3000
CMD ["node", "server.js"]
