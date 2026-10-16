FROM maven:3-eclipse-temurin-21-alpine AS builder

WORKDIR /app
COPY pom.xml .
COPY src ./src

# 构建身份（issue #6951）：**只有构建期能知道**「这个产物是按哪个 commit 造的」——
# 部署形态下容器里没有 `.git`（C′ 的构建上下文是 codeload 归档树）⇒ 运行时现算必然是错的。
# ⚠️ 这三个值**不是给 builder 用的**（源码编译不读它们；留在这里是为了让构建身份在**同一份**
#    构建输入里可见，且让「忘了传 build-arg」这件事在 builder 阶段就有名字，而不是静默空串）。
ARG MIGAO_BUILD_SHA=""
ARG MIGAO_BUILD_TAG=""
ARG MIGAO_BUILT_AT=""

RUN mvn clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine

WORKDIR /app

# 统一时区 UTC+8（业务时间均为北京时间；alpine 需 tzdata 才能解析 Asia/Shanghai）
RUN apk add --no-cache tzdata && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone
ENV TZ=Asia/Shanghai
ENV JAVA_TOOL_OPTIONS="-Duser.timezone=Asia/Shanghai"

# ── 版本探针的注入面（issue #6951）────────────────────────────────────────────
# 三个值由部署腿经 `docker build --build-arg` 注入（deploy/swas/deploy.sh 的 C′ 构建段），
# 烘焙进**镜像本身** ⇒ 它表达的是「**这份镜像**是按哪个 commit 造的」。
# 🔴 为什么必须烘焙进镜像、不许在 `docker compose up` 时用 `environment:` 注入：
#    `environment:` 表达的是「**这次部署想让线上跑什么**」—— 它与「容器里真的在跑哪份代码」
#    可以脱钩（拉了旧镜像 / 容器没被替换）⇒ 用运行时注入，探针会在**跑着旧代码**时照样报出新 sha，
#    变成**空断言**（正是 issue #6951 要治的形态）。
#    烘焙进镜像后，探针的读数是**产物身份**：它错，只可能是镜像本身错。
# ⚠️ ARG 的作用域是**每个 stage 各自**的 ⇒ 必须在**运行时 stage** 重新声明，否则 ENV 取不到 builder 的值。
ARG MIGAO_BUILD_SHA=""
ARG MIGAO_BUILD_TAG=""
ARG MIGAO_BUILT_AT=""
ENV MIGAO_BUILD_SHA=$MIGAO_BUILD_SHA
ENV MIGAO_BUILD_TAG=$MIGAO_BUILD_TAG
ENV MIGAO_BUILT_AT=$MIGAO_BUILT_AT
# 消费点 = `com.migao.admin.controller.VersionController`（`GET /api/version`）；
# 判据 = tests/unit_ci_workflows/test_served_version_verify.py。

RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring

COPY --from=builder /app/target/*.jar app.jar

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/actuator/health || exit 1

ENTRYPOINT ["java", \
    "-XX:+UseZGC", \
    "-XX:+ZGenerational", \
    "-XX:MaxRAMPercentage=75.0", \
    "-jar", "app.jar"]
