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
| `TENANT_ID` | 租户 ID（staging/production = `25`「米高测试环境」，2026-10-04 环境重建；local = `1`） | `25` / `1` |
| `SERVICE_TOKEN` | 服务间通信 Token | - |
| `ADMIN_PHONE` | 冒烟管理员手机号（staging/production = `13900001025`，租户 46） | 按 `SMOKE_ENV` 档 |
| `ADMIN_SMS_CODE` | 短信验证码（生产无 bypass ⇒ 用**刚收到**的那条码；**单次消费**） | `123456` |
| `SMOKE_ADMIN_TOKEN` | 注入 token：非空则**不登录、不发码**，直接用它跑（生产复跑用，见下节） | 空 |

## 生产复跑：一次登录 + 注入 token（issue #8977）

生产（cytda）**没有**配 `SMS_BYPASS_CODE` ⇒ 短信验证码**单次消费**。整套 P0 只允许**一次**登录：

```bash
cd tests/smoke

# ① 首次整跑（消耗一条短信码）：session 级 auth_token 登录一次，全档复用
SMOKE_ENV=production ADMIN_PHONE=13900001025 TENANT_ID=46 \
  ADMIN_SMS_CODE=<刚收到的短信码> \
  pytest -m "p0" --tb=short -q

# ② 复跑 / 补跑（不再发码）：把上一次登录响应里的 accessToken 注入
SMOKE_ADMIN_TOKEN=<accessToken> SMOKE_ENV=production \
  ADMIN_PHONE=13900001025 TENANT_ID=46 \
  ADMIN_API_URL=https://api.cytda.com AI_AGENT_URL=https://ai-api.cytda.com \
  pytest -m "p0" --tb=short -q
```

口径：

- **不再需要** `--deselect test_02_auth.py::TestAuthLogin::test_login_success` —— 该用例复用
  `auth_token` 的**同一次**登录结果（只做断言，不再单独消费第二个码）；
- `SMOKE_ADMIN_TOKEN` 存在时**不调用** `/api/auth/sms/login`（判据 =
  `tests/unit_ci_workflows/test_smoke_single_login.py`）；未设置时仍按原逻辑登录**一次**；
- 注入 token 模式下 `test_refresh_token` **显式 skip**：没有登录就没有 `refresh_token` cookie，
  该用例**不可判定**（不是通过）；覆盖 refresh 链路需按 ① 真登录跑一次；
- **禁止**用「给生产配 `SMS_BYPASS_CODE`」绕开（= 弱化登录，issue #8977 已否决）。

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
