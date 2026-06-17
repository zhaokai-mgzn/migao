# MVP 全链路冒烟测试

面向生产环境的冒烟测试脚本，覆盖认证、核心业务 API、AI 对话、多租户隔离、健康检查和性能基线。

## 快速开始

```bash
# 安装依赖
pip install -r tests/smoke/requirements.txt

# 运行全部冒烟测试（默认 local 环境）
pytest tests/smoke/ -v

# 指定环境
SMOKE_ENV=local pytest tests/smoke/ -v
SMOKE_ENV=staging pytest tests/smoke/ -v
SMOKE_ENV=production pytest tests/smoke/ -v

# 只运行 P0 测试
pytest tests/smoke/ -v -m "p0"

# 只运行性能基线测试
pytest tests/smoke/ -v -m "performance"

# 生成 HTML 报告
pytest tests/smoke/ -v --html=reports/smoke_report.html --self-contained-html
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SMOKE_ENV` | 测试环境 (local/staging/production) | `local` |
| `ADMIN_API_URL` | admin-api 地址 | `http://localhost:8080` |
| `AI_AGENT_URL` | ai-agent-service 地址 | `http://localhost:8001` |
| `ADMIN_USERNAME` | 管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理员密码 | `admin123` |
| `TENANT_ID` | 租户 ID | `1` |
| `SERVICE_TOKEN` | 服务间通信 Token | - |

## 测试分类

- **P0 (冒烟)**：认证链路 + 核心 API + 健康检查 - 上线必须通过
- **P1 (回归)**：AI 对话 + 多租户隔离 + 性能基线
- **performance**：性能基线测试

## 目录结构

```
tests/smoke/
├── conftest.py           # 共享 fixtures
├── config.py             # 环境配置
├── helpers.py            # 工具函数
├── requirements.txt      # 测试依赖
├── test_01_health.py     # 健康检查
├── test_02_auth.py       # 认证链路
├── test_03_business.py   # 核心业务 API
├── test_04_ai_chat.py    # AI 对话链路
├── test_05_tenant.py     # 多租户隔离
└── test_06_perf.py       # 性能基线
```
