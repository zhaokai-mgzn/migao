FROM maven:3-eclipse-temurin-21-alpine AS builder

WORKDIR /app
# ── 依赖层与源码层**分离**（issue #3426，评测栈提速）──
# 原写法是 `COPY pom.xml .` + `COPY src ./src` + 单个 `RUN mvn clean package` ——
# 源码改动会让这一层整体失效，于是**每次 CI 都重新下载全部 Maven 依赖**
# （run 34762648990 实测镜像构建里 1847 行 `Downloading from …`，约 50s；栈步骤共 196s）。
# 拆开后：pom 不变 → 依赖层命中缓存，只剩编译时间。
# 刻意**不用** `--mount=type=cache`：本地 `docker compose up --build` 若跑在未启用 BuildKit
# 的环境会直接构建失败，而这个 Dockerfile 是开发与 CI 共用的。
COPY pom.xml .
RUN mvn -B -q dependency:go-offline -DskipTests || true

COPY src ./src
RUN mvn clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine

WORKDIR /app

# 统一时区 UTC+8（业务时间均为北京时间；alpine 需 tzdata 才能解析 Asia/Shanghai）
RUN apk add --no-cache tzdata && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone
ENV TZ=Asia/Shanghai
ENV JAVA_TOOL_OPTIONS="-Duser.timezone=Asia/Shanghai"

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
