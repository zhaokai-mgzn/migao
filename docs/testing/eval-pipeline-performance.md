# 评测流水线性能账（C 端 xiaobu-acceptance）

> 为什么单独记账：评测墙钟时间直接决定「一个回归要等多久」，而**优化方向很容易猜错**——
> 本项目就走过一次弯路：按直觉做"用例分片成 3 个 job"，结果**更慢**（19.8min vs 15.6min）。
> 本文记录实测数据、归因方法与有效/无效的手段，避免后人重走。
>
> 数据来源：GitHub Actions run 的**步骤级耗时** + runner 打印的 `⏱ <case> start=` 锚点 +
> 镜像构建日志逐行时间线。复现方法见文末。

## 1. 起点与结论（C 端 normal，18 条用例）

| 阶段 | 起点 | 现在（实测） | 手段 |
|---|---|---|---|
| 栈启动（构建镜像 + 起容器） | 3.4-13.1min（剧烈波动） | **2.9min**（4.5×，且稳定） | CI 镜像构建改用 PyPI（§2.1） |
| 评测执行 | 11.6-19.7min | **8.2min**（重试预算 3）／3.9min（预算 1） | 用例级并发 + 读写门 + 收窄独占（§2.2-2.4） |
| **整跑墙钟** | **15.6-25.7min** | **12.6min** | 上述合计 |

实测明细（run 34702337356，normal 18 条，预算 3）：栈 2.9min + 评测 8.2min = 12.6min，成绩 16/18。
评测的**下界 = 最慢单条用例耗时**（并发缩短队列但不缩短单条）：18 条用例在 170s 内全部开工，
但一条带重试的失败用例就独占 ~5-6min —— 再往下压只能靠 C 端行为本身（少轮次/少失败），
不是调度问题。故本轮到此为止，`--max-retries` 保持 3（压到 1 会让后几条失败用例拿不到
那唯一一次防抖重试：实测 13/18 vs 16/18，多出的红灯要人工/AI 逐条排查，得不偿失）。

## 2. 归因：钱花在哪

### 2.1 栈启动：不是"构建慢"，是**镜像内 pip 走了阿里云源**

逐行时间线（run 34696595424，栈步骤 13.1min）：

| 阶段 | 耗时 |
|---|---|
| admin-api 镜像（Maven 打包，GHA 层缓存命中） | 47s |
| ai-agent 镜像 apt 依赖 | 24s |
| **ai-agent 镜像 `pip install -r requirements.txt`** | **632s（10.5min）** |
| 导出镜像层 + `compose up --wait` | ~1min |

pip 阶段下载速率 **~160 kB/s**。对照证据：**同一台 runner** 用默认 PyPI 装**同一份 requirements**
只要 **23s**（"Install eval runner deps" 步骤）。原因是 `Dockerfile` 的
`ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/` —— 对国内开发是合理默认，
但 GitHub runner 在境外，**慢了 27 倍**。

**手段**：CI 构建时显式 `--build-arg PIP_INDEX_URL=https://pypi.org/simple`（Dockerfile 默认值不动）。
**守卫**：`tests/unit_ci_workflows/test_schema_integrity.py::test_stack_step_uses_layer_cache_with_fallback`
断言栈步骤必须含 `pypi.org/simple` 与 `type=gha` 缓存、并有失败回落路径。

> 附带结论：GHA 层缓存（buildx `--cache-from type=gha`）本身是有效的（Maven 层命中 47s），
> 但它救不了"每次都要真跑一遍 pip"的那种层。

### 2.2 评测执行：串行 → 用例级并发（**单栈**）

- 单条用例的耗时几乎全是**真实 LLM 往返**（每轮：意图分类 + skill 循环 1-3 次调用）；
  实测单条通过用例 ~20s，失败用例 200-400s（含整条重跑）。
- 因此理论上可线性并行。**但并行必须发生在单栈内的用例之间**：

| 方案 | 栈启动 | 评测 | 墙钟 |
|---|---|---|---|
| 单 job 串行（18 条） | 3.4min | 11.6min | 15.6min |
| **3 个 job 分片**（各 6 条） | **12.0/11.9/11.7min** | 5.3/7.2/1.7min | **19.8min（更慢）** |
| 单 job + 并发度 3 | 3.4min | — | 见 §2.3 |

分片确实让**评测**快 ~3 倍（单条吞吐不变），但**每片各自 `docker compose up --build`**
在并发下把栈启动从 3.4min 抬到 12min（并发构建/拉镜像被打爆）→ 整体更慢。

**手段**： runner 支持 `--concurrency N`（`EVAL_CONCURRENCY`），**单 job 内** `asyncio.Semaphore`
并行跑用例，栈只起一次。默认 1（串行，向后兼容），CI 用 3。
**分片能力保留**（`--shard I/N` + workflow matrix），但**默认 1 片**，输入说明里写明上述实测。

### 2.3 独占 = 加性：减少/缩短独占用例才是关键

第二轮的实测（run 34697877406）：并发 3 已生效（16 条并行），但评测仍 10.2min ——
用例开工时间线里出现 **333s 空档**：串行道的 OR-014（因 `pre_clean` 被判独占）一个人跑 ~5.5min，
把并行读者全挡住。即 **墙钟 = 并行段 + 独占段**，独占段无法被并行掩盖。

**手段（第三轮）**：
- **收窄独占范围**：`pre_clean`（"评测前把共享数据清干净"的**短写动作**）改为在 gate 的
  **独占窗口**内执行，用例主体回到并行道。仍整体独占的只剩：
  `id_reuse/update/full_lifecycle` 标签（商品改价类，全程持有共享商品状态）与
  `post_session`（用户级长期状态，写 `user_memories`）。
  C 端 normal 的独占用例因此从 2 条降到 1 条（CH-024，~16s）。
- **读写门（`ConcurrencyGate`）**：并行用例持"读"位（上限 = 并发度），独占用例持"写"位，
  **读者排空即进入**（不是"等整批跑完"）；写者优先避免被源源不断的读者饿死。

### 2.4 重试预算：失败用例整条重跑是尾巴主因

`local_runner` 的防抖机制会**整条重跑**失败用例（200-400s/次）以分类 `llm-noise`。
CI 原先允许 3 次 → 失败多的跑把分钟数全花在重试上。

**手段**：`--max-retries`（CI 设 1，保留"单次重试"这一分类语义）；超预算的失败
**照样记为失败**，只把标签标成 `no-retry-budget`（不掩盖红灯）。

### 2.5 其它已落地的小项

- 固定节流可配：`EVAL_ROUND_SLEEP` / `EVAL_CASE_SLEEP`（默认 0.5/1.0，CI 0.2/0.3；
  非法值回落默认）。C 端 18 条约省 60s。
- E2E 步骤 `always()`：此前"评测失败 → E2E 被 skip → E2E 的红灯永远看不见"
  （main run 34684474262 评测 17/17、E2E 已 failure）。现在两条腿各自亮灯。
- 结果按**原始用例顺序**回填（并发不改变报告顺序，便于与历史 run 逐条对比）。

## 3. 诊断基建（没有它，上面的归因都做不出来）

| 证据 | 出处 |
|---|---|
| 每条用例起止 | runner 打印 `⏱ <case_id> start=<UTC ISO>` |
| 逐轮工具/结果/卡片/**本轮实际发出的消息** | `round_trace`（`AGENT_EVAL_TRACE_ALL=1` 全量打印） |
| 为什么走这个 Skill | workflow「Dump C 端逐轮路由轨迹」步骤 grep `route_by_intent/continuity/escape hatch` |
| 写工具为什么失败 | 同步骤 grep `[order-create] Failed` / `[tool-exec] <tool> ERROR` / `Tool not found` / 门禁拦截 / `pending-validated` |
| 数据真的落库了吗 | workflow「Eval 产物 DB 审计」：会话（含残留）、订单**金额**、工单、长期记忆 + 假绿告警 |
| 本片/本次跑了什么 | `AGENT_EVAL_SUMMARY_JSON`（机器可读：total/passed/order_write_cases/cases[]） |

## 4. 反模式（踩过的坑）

1. **按直觉做多 job 分片** → 并发建栈把栈启动放大 3 倍，整体更慢（§2.2）。
2. **凭"构建慢"猜优化** → 真凶是 pip 源（§2.1）；不逐行计时就会去做无效的层缓存调参。
   附带一问：GHA 层缓存并非万能（Maven 层命中 47s，但"每次都要真跑一遍"的 pip 层仍慢），
   要区分"层没命中"和"层命中了但那一层本身慢"。
3. **让独占用例排队到整批之后** → 慢用例变成整跑尾巴（§2.3）。
4. **把"隔离"理解成"必须最后跑"** → 隔离语义是**不与其他用例重叠**，可以插空跑。
5. **用 `tail -N` 截断诊断日志** → 关键异常可能被挤掉；现在 dump 前会先报匹配条数。

## 5. 复现与验证

```bash
# 1) 单跑（本地或 CI）——看每条用例的起止与并发调度
EVAL_CONCURRENCY=3 EVAL_ROUND_SLEEP=0.2 EVAL_CASE_SLEEP=0.3 \
AGENT_EVAL_SUMMARY_JSON=/tmp/summary.json \
python tests/agent_eval/local_runner.py normal --cases .github/cases --max-retries 1

# 2) 步骤级耗时（CI）
gh api repos/<owner>/<repo>/actions/runs/<id>/jobs \
  --jq '.jobs[].steps[] | "\(.name)\t\(.started_at)\t\(.completed_at)"'

# 3) 栈步骤逐行时间线（定位是 pip / maven / pull / healthcheck）
gh run view <id> --log | grep "Start local stack" | ...
```

守卫（改动若让优化退化会变红）：
`tests/unit_ci_workflows/test_schema_integrity.py`（栈缓存 + PyPI 源 + 审计口径）、
`backend/ai-agent-service/tests/test_acceptance_case_checks.py`（并发有界、读写门独占、
报告顺序、预算不被并发突破、pre_clean 只独占清理动作）。
