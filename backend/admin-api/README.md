# Admin API

米高 AI 智能客服 — Java 管理后端

## 技术栈

- Java 21 + Spring Boot 3.3 + MyBatis-Plus
- PostgreSQL 15 + Redis 7
- JWT RS256 认证 + 多租户数据隔离

## 快速开始

```bash
# 1. 配置环境变量（复制模板并填入实际值）
cp .env.example .env

# 2. 启动（连接云 dev 数据库）
./mvnw spring-boot:run
# 启动后访问: http://localhost:8080
# Swagger UI: http://localhost:8080/swagger-ui.html
```

## 测试

```bash
./mvnw test                          # 全量单测
./mvnw test -Dtest=XxxTest           # 指定测试类
```

## 关键配置

| 变量 | 说明 |
|------|------|
| `RDS_HOST/PORT/DB/USER/PASSWORD` | 数据库连接 |
| `REDIS_HOST/PORT/PASSWORD` | Redis 连接 |
| `JWT_PRIVATE_KEY_PEM` | JWT 签名私钥（PEM 字符串，优先级高于文件） |
| `SERVICE_TOKEN_SECRET` | AI 服务间认证 Token |
| `CORS_ALLOWED_ORIGINS` | 允许的前端域名 |
