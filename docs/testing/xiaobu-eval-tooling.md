# C 端（小布）评测体系

> 对齐 B 端（米宝）评测方法论的 C 端落地说明。**改动 C 端评测工具或用例前必读。**
> 单一事实源：`.github/cases/`（用例库）、`tests/agent_eval/local_runner.py`（runner）。
> 相关：`migao-dev-flow` §13/§14（行为体检与用例演进）、`acceptance-protocol`（验收协议）。

## 1. 为什么单独有一页

C 端小布与 B 端米宝是**两个 Agent、两套工具集**，但共用一套用例库与 runner（靠
`persona` 字段分流）。2026-09-11 查证发现 C 端评测长期处于「看起来有覆盖」状态
（issue #3266），本页固化正确的评测口径，防止再次退化。

## 2. 四层评测架构与外部依赖

| 层次 | 载体 | 依赖微信开发者工具 | 进 CI |
|---|---|---|---|
| ① 行为评测（**主力**） | `tests/agent_eval/local_runner.py` + `PERSONA=xiaobu` | ❌ 不需要（纯 HTTP/SSE） | ✅ `xiaobu-acceptance.yml` |
| ② H5 视觉回归 | `tests/playwright.xiaobu.config.ts` | ❌ 不需要（静态托管 Taro H5 产物 + 本地 Chrome） | ✅ `mini-app.yml::xiaobu-h5-visual` |
| ③ 组件单测 | `frontend/mini-app/tests/*.tsx` | ❌ 不需要（jest + jsdom，Taro 全 mock） | ✅ `mini-app.yml::typecheck-and-test` |
| ④ 真机小程序 E2E | `frontend/mini-app/e2e/run.js` | ✅ **唯一依赖** | ❌ 未接入 |

**④ 不作为评测骨架**：`miniprogram-automator` 需本机已登录的微信开发者工具
（`CLI_PATH` 硬编码 `/Applications/wechatwebdevtools.app/...`，还需在设置里开服务端口），
违背「零人工执行步骤」。定位为**可选补充证据层**，主力压在 ①②③。

## 3. ①行为评测的运行前提（关键约束）

`PERSONA=xiaobu` 的身份注入走 `X-Debug-Role: customer` 头，而该降级路径
**仅 `DEBUG=true` 时生效**（`app/utils/auth.py` fail-closed 加固）：

- ✅ **本地 DEBUG 栈**：`DEBUG=true` + 无 token + `X-Debug-Role: customer`
  → `UserIdentity(user_id="debug_customer_1", tenant_id=1, role=CUSTOMER)` → 路由小布
- ✅ **CI xiaobu-acceptance**：docker compose 起 DEBUG 栈
- ❌ **生产 `ai-api.migaozn.com`**：`DEBUG=false` → 该头被忽略 → 请求兜底路由到**米宝**，
  但 runner 仍按 xiaobu 语义打分（`order_query`→`customer_order_query` 映射照旧生效）
  → **结论不可信**。生产 C 端身份需微信 `wx.login()` 的 code 换 token
  （`POST /api/auth/mini/login`），评测无法直接复现。

> **铁律**：跑 C 端评测前先确认目标是 DEBUG 栈。打生产 URL 跑 `PERSONA=xiaobu`
> 得到的是米宝的结果，不要当成 C 端结论。

本地起 DEBUG 栈（无 docker 时）的最小做法：

```bash
cd backend/ai-agent-service
cp <主仓库>/.env .env                      # 含 DEBUG=true / PRIMARY_API_KEY / SERVICE_TOKEN
# ADMIN_API_BASE_URL 指向可用的 admin-api（云 dev 或本地 8080）
sed -i '' 's|^ADMIN_API_BASE_URL=.*|ADMIN_API_BASE_URL=https://api.migaozn.com|' .env
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

云端 RDS 需把当前公网 IP 加入白名单（`aliyun rds ModifySecurityIps`，
**必须查旧列表原样保留 + 追加，禁止清空他人 IP**，见 `migao-dev-flow` §10）。

## 4. 用例选择口径（`select_cases_for_persona`）

**单一权威 = `persona` 字段 + 工具集兼容性**，不按 tag 猜（tag 是通用词，会误捞）：

| 步骤 | 规则 |
|---|---|
| 1 | `filter_by_persona(cases, "xiaobu")`：排除 `persona: mibao`（另一端专属）；`""`=双端保留 |
| 2 | 丢弃 `skip_reason` 非空的用例（纯前端 jest 用例，非 LLM 行为） |
| 3 | `persona: xiaobu` 的用例**无条件保留**（显式声明优先） |
| 4 | 双端用例：其**全部**期望工具须 ⊆ `XIAOBU_TOOLS` 才保留 |

实现落在 `tests/agent_eval/eval_case_filter.py::select_cases_for_persona`
（`local_runner` 与覆盖脚本共用，避免三处口径漂移）。

`XIAOBU_TOOLS` = 各 `customer_*_skill.py` 的 `CUSTOMER_*_TOOLS` 并集，共 13 个工具
（单一真值来源 `tests/agent_eval/eval_case_filter.py`；与源码一致性由
`tests/unit_ci_workflows/test_xiaobu_case_set.py::TestXiaobuToolsetTruth` 锁定）。

### 为什么废弃旧实现

旧 `local_runner` 在 persona 过滤后**又加了一层宽 tag 过滤**：

```python
XIAOBU_ONLY_TAGS = {"order_query", "order_create", "aftersale", "query", "product", "knowledge", "wiki"}
```

`query`/`product` 几乎每个域都有 → 实测选中 33 条，其中**仅 4 条**真属 C 端，其余是
B 端管理用例（DA-001 经营概览 / FN-001 资金流水 / HR-001 员工列表 / CT-001 分类树 /
CU-001 客户 / AS-001 售后工单 / ST-001 设置）——小布工具集里根本没有
`dashboard_stats`/`finance_api`/`employee_manage` 等，这些用例在小布上要么被合理拒绝
后判失败，要么根本没验证到任何东西，却计入「C 端评测通过率」。

## 5. 覆盖体检（`scripts/xiaobu_coverage.py`）

回答「哪个 C 端能力没被测」——B 端的 `mibao-verification-cases.md` 是用例清单生成物，
不回答这个问题。

```bash
# 人读报告
backend/ai-agent-service/.venv/bin/python scripts/xiaobu_coverage.py
# CI 门禁（孤儿用例/空用例集 → exit 1）；已接入 verify-all.sh gate/quick/full
backend/ai-agent-service/.venv/bin/python scripts/xiaobu_coverage.py --check
# Markdown（供文档引用）
backend/ai-agent-service/.venv/bin/python scripts/xiaobu_coverage.py --md
```

输出三部分：① 工具覆盖矩阵（缺口标 ⚠️）② 用例归属（按 tier）③ 孤儿用例
（声明 `persona: xiaobu` 却断言非小布工具 = 配置错误，门禁拦截）。
另有**显式豁免**区：有用例但声明了 `skip_reason` 的工具（如 `customer_address_query`
由 CH-025 覆盖但 skip，改由 pytest 验证）——豁免必须显式声明理由，不得靠「看起来有覆盖」。

> 脚本零第三方依赖（纯逻辑在 `tests/agent_eval/eval_case_filter.py`），
> `python3` 直接可跑。**为什么拆模块**：`local_runner` 有模块级 `import httpx`，
> 而 CI 的 `ci workflow helper unit tests` job 只装 `pytest pyyaml` →
> 测试一 import runner 就 ImportError（本地必装 httpx 故全绿，CI 红）。
> 拆出零依赖纯函数后，runner / 契约测试 / 覆盖体检三处共用同一实现且都能跑。

## 6. 当前基线（2026-09-11，issue #3266）

本地 DEBUG 栈实测（`deepseek-v4-pro`）：

| tier | 用例 | 覆盖能力 | 实测 |
|---|---|---|---|
| smoke | AS-008 | 售后进度查询（本人工单隔离） | ✅ 100% |
| smoke | KN-001 | 本店知识库检索 | ✅ 100% |
| smoke | OR-012 | 物流查询（仅本人已发货） | ✅ 100% |
| smoke | PR-001 | 商品搜索 | ✅ 100% |
| smoke | PR-003 | 商品详情（ID 解析） | ✅ 100%（偶发噪声重试放行） |

工具覆盖 **12/13**（唯一未覆盖 `customer_address_query` 已显式豁免）。

### 已实测发现的 C 端行为问题（待收敛）

| 用例 | 现象 | 性质 |
|---|---|---|
| OR-016 | 下单 confirm 前**未主动询问加工项**（商品绑定加工项时）；`interact[choice:processing_items] before interact[confirm]` 时序断言全程未命中 | 复现型（两次不同指纹，待多次采样定性） |
| OR-009 | 下单全流程 6 轮跑偏：首轮 `human_handoff`，无 `order_create`，末轮工具调用超时 180s | 待定性（含 infra 超时因素） |

> 这两条是「提高 C 端能力上下限」的直接输入，需按 `migao-dev-flow` §13.3 收敛为
> 可执行断言（`order_before` 时序 / `required_args` 参数完整性）并做 case 有效性验证。

## 7. 新增 C 端用例的检查单

1. 在对应域 `.github/cases/*.yml` 新增，**必写** `persona: xiaobu`（C 端专属）；
2. `tier`：稳定单/双轮且是核心能力 → `smoke`；多轮/复杂流转 → `normal`；
3. 断言优先用**可执行形态**（`order_before` / `required_args` / `forbidden_text` /
   `db_verify`），自然语义 `data_checks` 不算覆盖（`acceptance-protocol` §1.3）；
4. 涉及数据隔离的能力（订单/物流/售后/地址）必须断言「仅本人」+「无 B 端越权工具」；
5. 跑 `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases.py --out-md docs/testing/mibao-verification-cases.md` 提交生成物；
6. 跑覆盖体检 `--check` 确认无孤儿用例；
7. 用本地 DEBUG 栈实测该用例 ≥1 次（真实 LLM），确认断言与行为一致（先例：行为合理但
   断言过严的，按 §14.2 校准而非删用例）。
