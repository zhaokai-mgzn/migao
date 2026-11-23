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

## 应用时机（判据，不是建议，issue #9082）

用户裁定（2026-11-23，逐字）：

> 「我们是 ai native 公司，冒烟都需要 AI 跑」
> 「以后还是需要先在测试机器上做充分验证，只有要发布生产的时候才在发布前走一次生产环境的冒烟」

| 时机 | 跑哪个档 | 目标 | 内容 |
|---|---|---|---|
| **日常 / 每次合并后**（AI 常态） | `--env test`（默认） | 测试机 `api.migaozn.com` / `ai-api.migaozn.com` | **完整档**（含写类用例、AI 会话、建单、删会话 —— 测试机可以随便写） |
| **发版前**（一次，人工/发版流程显式触发） | `--env prod` | 生产 `api.cytda.com` / `ai-api.cytda.com` | `prod_readonly_profile.json` 的**只读子集** |

```bash
# 日常档（AI 天天跑；一起提交后就跑这个）
./scripts/smoke-prod-ai.sh                 # = --env test

# 发版闸门档（**只在「即将发生产」时跑一次**）
export MIGAO_SMOKE_IDENTIFIER='<用户名>@<企业编码>'   # secret / 本机 export，绝不写进文件
export MIGAO_SMOKE_PASSWORD='<密码>'
./scripts/smoke-prod-ai.sh --env prod
```

**不许**把 `--env prod` 当日常回归跑：生产不打白工（只读档不打写接口）、不写脏数据、不烧 LLM 成本。
脚本启动时会打印横幅 `⚠️ 本档只在「即将发生产」时跑一次；日常验证请在测试机跑 --env test`，
且**禁止**给它挂 cron / schedule / 部署腿自动触发（判据 =
`tests/unit_ci_workflows/test_smoke_prod_readonly_profile.py::test_prod_gate_is_not_on_any_schedule`）。

### 生产只读冒烟（仅发版前一次）

`--env prod` 的三件事：

1. **凭据**：员工账号密码登录 `POST /api/auth/employee/login`（`identifier = <用户名>@<企业编码>`）
   换 access token，注入 `SMOKE_ADMIN_TOKEN` ⇒ **不发短信、不用 bypass**。
   - 变量只从环境变量读：`MIGAO_SMOKE_IDENTIFIER` / `MIGAO_SMOKE_PASSWORD`；
   - 缺任一 ⇒ **`rc=3`**（判不了）并点名缺哪个 + 去哪儿配（GitHub secret 同名 / 本机 `export`）；
   - **仓库里没有任何默认值**（也确实不许加）——判据含「脚本里不许出现 `${MIGAO_SMOKE_PASSWORD:-…}`」。
2. **只跑只读子集**：`tests/smoke/prod_readonly_profile.json` 是**单一来源**（每条一句「为什么只读」），
   脚本按它组 pytest 参数。**不跑** `-m p0` 整档：`test_04_ai_chat` 会建会话（写）、
   `test_09_order_lifecycle` 会建单（写 + 涉钱面）、AI 面还会烧 LLM 成本。
   排除的写类用例逐条写在 profile 的 `excluded[*].why` 里（含「对生产账号发错误验证码会累计风控计数」这类判断）。
3. **判不了怎么办**：`rc=3` 表示**没有判定**，不是通过 —— 缺凭据 / 连不上目标 / 只读档解析不了 /
   pytest 收集不到用例 / `passed=0`。此时按输出里的出口走（配 secret、核对企业编码、跑元守卫查只读档），
   **不要**把 `3` 读成绿，也**不要**改用 bypass 绕开（生产禁止开 `SMS_BYPASS_CODE`，issue #8977 已否决）。

### 为什么不用 bypass

`SMS_BYPASS_CODE` 是**服务端**配置：生产开着它 = 任何人都能用固定码登录 = 弱化登录（#8977 已否决）。
⇒ 生产侧只能走「真凭据」：员工账号 + 密码换 token，再注入 `SMOKE_ADMIN_TOKEN` 跑只读档。
测试机则相反：`SMS_BYPASS_CODE=123456` 在**测试环境**是允许的（`--env test` 的默认凭据路径），
所以日常档零凭据也能跑。

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
