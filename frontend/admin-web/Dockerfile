# admin-web Dockerfile
# Next.js 16 App Router 生产部署（运行时 node:20-alpine ⇒ @types/node 同步锁在 ^20）
FROM node:20-alpine

WORKDIR /app

# 统一时区 UTC+8（业务时间均为北京时间；alpine 需 tzdata 才能解析 Asia/Shanghai）
RUN apk add --no-cache tzdata && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone
ENV TZ=Asia/Shanghai

# 安装依赖
COPY package*.json ./
RUN npm ci

# 复制源码
# ⚠️ `public/version.json` **不在仓里**（见下面的构建身份 RUN 段生成它）⇒ 不会被本行覆盖，
#    也**不该**被提交进仓（提交一份假的身份面 = 第二份会漂的口径）。
COPY . .

# 构建时环境变量（NEXT_PUBLIC_* 在构建时 baked into JS）
ARG NEXT_PUBLIC_API_BASE_URL=https://api.migaozn.com
ARG NEXT_PUBLIC_AI_API_BASE_URL=https://ai-api.migaozn.com
ARG NEXT_PUBLIC_COOKIE_DOMAIN=.migaozn.com
# B 端 h5 手机端入口（issue #5668）：二维码的**唯一**地址来源（前端不硬编码域名）。
# 缺省即线上落位；置空 = 页面显示「移动端地址未配置」且不画码（不是画一个空码）。
ARG NEXT_PUBLIC_BMINI_H5_URL=https://app.migaozn.com/b/

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_AI_API_BASE_URL=${NEXT_PUBLIC_AI_API_BASE_URL}
ENV NEXT_PUBLIC_COOKIE_DOMAIN=${NEXT_PUBLIC_COOKIE_DOMAIN}
ENV NEXT_PUBLIC_BMINI_H5_URL=${NEXT_PUBLIC_BMINI_H5_URL}
ENV NODE_ENV=production

# ── 构建身份注入面（issue #6611）──────────────────────────────────────────────
# 「线上跑的是哪个 build」必须**可判读** —— 消费方 = `deploy/scripts/admin-web-verify-served.sh`
# （`GET /version.json`，与 admin-api 的 `GET /api/version` 同族形态）。
#
# 🔴 为什么**烘焙进镜像**（构建期）而不是运行时现算 / compose `environment:` 注入：
#    · 运行时现算不可能：C′ 的构建上下文是 codeload 归档树，**容器里没有 `.git`**；
#    · `environment:` 注入表达的是**部署意图**，与「容器里真的在跑哪份代码」可以脱钩
#      （拉了旧镜像 / 容器没被替换）⇒ 探针会在跑着旧代码时照样报出新 sha = **空断言**。
# 🔴 为什么是**独立小文件**而不是把 sha 塞进 `index.html`：
#    逐字（issue #6611 病灶）—— 「`index.html` 字节哈希**跨版本相同**（只证 chunk 图，
#    不证部署了哪份代码）」（实测应用代码变了、`index.html` 的 sha256 前后都是 `b1f3a2ef2929ec66`）
#    ⇒ 把它当身份面只会让哈希重新"看起来有判别力"，而那**不是**真身份。
# 🔴 默认值 = `unknown`（**不是**空串）：`--build-arg` 未送达时产物自报 `unknown` ⇒ 探针判
#    「探不到」（exit 3 fail-closed），**绝不**退化成「空 == 空 ⇒ 绿」。`unknown` 不是 hex
#    ⇒ 探针的形态前置判据当场判「探不到」。
# ⚠️ 值的安全面：`deploy/scripts/swas-deploy-ci.sh` 的 BOOTSTRAP 渲染是**有界安全值**
#    （sha = hex、builtAt = ISO8601，调用方 fail-closed 校验过形态）⇒ 不引入任意 shell 片段。
# ⚠️ `tag` 有意取 `${TAG}`（docker 构建期自动提供的**镜像 tag** 环境变量），**不**新开一个 ARG
#    ——「这次装进镜像的那个 ref」与 compose 的 `image:` 同源（少一条会漂的口径）。
# 判据 = tests/unit_ci_workflows/test_admin_web_served_version.py
ARG MIGAO_BUILD_SHA=unknown
ARG MIGAO_BUILD_TAG=unknown
ARG MIGAO_BUILT_AT=unknown
RUN set -eu; \
    : "${MIGAO_BUILD_SHA:=unknown}"; : "${MIGAO_BUILD_TAG:=unknown}"; : "${MIGAO_BUILT_AT:=unknown}"; \
    case "$MIGAO_BUILD_SHA" in *[!0-9a-f]*) MIGAO_BUILD_SHA=unknown ;; esac; \
    if [ "${#MIGAO_BUILD_SHA}" -lt 7 ]; then MIGAO_BUILD_SHA=unknown; fi; \
    mkdir -p public; \
    printf '{"app":"admin-web","sha":"%s","tag":"%s","builtAt":"%s"}\n' \
      "$MIGAO_BUILD_SHA" "$MIGAO_BUILD_TAG" "$MIGAO_BUILT_AT" > public/version.json; \
    echo "构建身份已烘焙：$(cat public/version.json)"

# 构建（不再需要 output:export）
RUN npm run build


EXPOSE 3001

CMD ["npx", "next", "start", "-p", "3001"]
