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
| 栈启动（构建镜像 + 起容器） | 3.4-13.1min（剧烈波动） | **2.9-3.4min**（4.5×，且稳定） | CI 镜像构建改用 PyPI（§2.1） |
| 评测执行 | 11.6-19.7min | **4.7-8.2min**（重试预算 3）／3.9min（预算 1） | 用例级并发 + 读写门 + 收窄独占（§2.2-2.4） |
| **整跑墙钟** | **15.6-25.7min** | **8.7-12.6min** | 上述合计 |

实测明细（run 34702337356，normal 18 条，预算 3）：栈 2.9min + 评测 8.2min = 12.6min，成绩 16/18。

第二轮明细（run 34716531345，同样的 18 条）：栈 **3.4min**（20:15:34→20:18:57）
+ 评测 **5.0min**（20:19:23→20:24:25）+ E2E 22s，job 总计 9min45s，成绩 17/18。
评测时间随「红了几条」浮动（失败用例才吃满重试预算），**栈 3.4min + 评分器 5min 是当前常态区间**。

最好的一次（run 34717401685，全绿）：栈 **2.9min** + 评测 **4.7min** + E2E 0.4min，
job 墙钟 **8.7min**，成绩 18/18（100%）。同为 18 条的同一档位，从起点 15.6-25.7min
压到 8.7min —— 省下的是**排队等红灯**的时间：红灯少了，重试预算不再被吃满。
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

### 2.6 三档分治：完整档 / 收窄档 / 快速档（issue #3417）

上面几轮把**整跑**从 15.6-25.7min 压到 8.7-12.6min，但没解决**迭代**：30 条 normal 用例的
评测档实测 **663s**（~250 次真实 LLM 往返，`EVAL_CONCURRENCY=3`），"改一行等一刻钟"。
且本机无 docker → 评测只能在 CI 跑，所以旋钮必须做进 workflow（而不是"本地跑快点"）。

| 旋钮 | 默认 | 作用 | 边界 |
|---|---|---|---|
| `concurrency` | 3 → **6** | 同 job 内用例级并发（栈只起一次） | **语义不变** → 任何档可用；但实测只省 ~6%（见下） |
| `case_ids` | 空 | 只跑指定用例（与 tier/shard 正交，逗号分隔） | 迭代复验用；**ID 解析不到即报错退出**（少跑 ≠ 通过） |
| `fast` | `false` | 不重试（`--max-retries 0`）+ 跳过取证（real E2E / 路由 dump / DB 审计） | **只用于迭代，下结论前必须跑完整档** |

**实测（run 34762648990，2026-09-13，30 条 normal，并发 6）——先验证再写结论，结论与预期相反**：

| 指标 | 实测 |
|---|---|
| 评测档耗时（含重试） | **621s**（并发 3 时基线 663s → 只快 **6%**） |
| 用例级墙钟（首个用例开始 → 末个结束） | 522s |
| 全部用例"总工作量"（各条首试→最终完成之和） | 1345s |
| 最慢单条 | **OR-018 = 418s**（次慢 OR-021 = 417s，两条都是**首试失败→整会话重试**） |
| 其余用例 | 47–121s（多数 ≈100s） |

**为什么并发没救回来**：评测墙钟 = **最慢单条链** + 重试尾巴，不是吞吐瓶颈。
两条重试用例各 ~418s，而 `sum(工作量)/并发6 = 224s` —— 用实测耗时做调度模拟（LPT 慢的优先、
并发 6 或 12）结果**都是 418s**：无论怎么排、加多少并发，这两条自身就是 7 分钟的临界路径。
故「调大并发 ≈ 线性提速」是**错的**（本轮实测推翻），本轮真正的提速手段是 `case_ids` + `fast`：
按用例收窄（2 条）实测评测档 **167s**（run 34762661698）。

**迭代档实测（run 34762661698：`case_ids=OR-019,OR-024` + `fast=true`）**：
栈 174s + 装依赖 20s + 评测 167s + 验收剧本 139s ≈ **9.5 分钟**（完整档 16–17 分钟）。
可见迭代档剩下的时间**几乎全是固定成本**（栈 + 验收剧本），不是评测本身 ——
下一个提速目标应当是"把栈启动 3 分钟压下去"，而不是继续调并发。

**快速档的红线**：只允许跳过**取证**，绝不允许跳过**判定**。验收剧本（点卡/打岔/换窗口）
是**独立判定源**，若被 `fast` 一起跳过，就会得到"跑得快且全绿"的假象 ——
评测缺陷与体验缺陷互相掩盖（同 #3364 对 E2E 的结论：只要评测红，E2E 红就永远看不见）。

这条红线由 `TestEvalSpeedKnobs` **双向**钉死：取证步骤必须挂 `fast` 跳过，非取证步骤
**一律不许**挂 `fast`（防止将来有人为了"更快"把栈健康检查/判定步骤也标上 `fast`）。

**迭代档不开验收 issue**：失败时自动开的「小布 C 端验收失败」issue 语义是**每日全量**结论，
而迭代档的红是预期中的工作状态；且 issue 标题不含分支 → 分支迭代失败会与主干验收失败
共用同一线程（去重按标题，直接往主干 issue 追加评论），拿 2 条用例的失败开全量 issue
也是过度断言。故 `fast=true` 或收窄档不建 issue，**完整档照旧建**（该被看见的红一条不少）。

> 为什么不做"自动降档"：档位是**结论强度**的选择，必须显式声明。
> 自动降档会让"没验收却报全绿"变得无法察觉 —— 本项目的假绿事故几乎都是"少做了一步但没报错"。

评测档耗时现在回显到日志（`⏱ 评测档耗时 ${SECONDS}s`），让基线持续可见：
没有可见基线，"提速"就只能靠感觉。

### 2.7 失败记录：层缓存路线**已废弃**（issue #3426，三次实验均无效）

栈启动 196s 里，**镜像构建占 128–172s**。直觉上"给 docker 层做缓存"就能省下来 ——
实测三次干预**全部无效**，记录在此以免后人重跑：

| 实验 | 结果 |
|---|---|
| 基线（层顺序优化：pom/requirements 与源码分层） | 栈 **193s**；`CACHED` 层数 **0** / 重建 **43** 层 |
| ＋`actions: write`（缓存写入权限） | 仓库 **仍 0 条** buildx/gha 缓存（173 条全是 setup-node/python/java） |
| ＋`ACTIONS_CACHE_SERVICE_V2=1`（上游 buildkit#5896 提到的开关）| **仍 0 条**、日志**无任何警告**、无 cache manifest 行 |

**共同形态**：构建成功 + 后端**完全没参与**（既无 `importing cache manifest`，也无 error/warning）。
说明在 `buildx v0.37.0 + moby/buildkit:buildx-stable-1` 组合下 `type=gha` 后端不可用，
且**没有可利用的错误信息**继续定位（上游：moby/buildkit#5896、#5754）。

**处置**：
- 层顺序优化已**回滚**（无缓存命中时它只是把一次 Maven 变成两次，净效应为负）；
- 无效的 v2 开关与 `actions: write` 只保留后者（无害的前置条件）+ 一组**可观测性**改进：
  buildx 输出留档、回落分支打印错误尾部（原来**静默吞掉失败**）、成功分支打印
  cache manifest 行与警告 —— 这条同样适用于其它 workflow；
- **下一步走 GHCR 预构建镜像**（admin-api 与分支无关 → 可长期复用；ai-agent 必须按分支重建）。

> 教训（与本文件其它反模式同族）：**优化前先确认"机制到底有没有生效"，并让失败可见**。
> 这次"每次 CI 全量重建"之所以长期无人察觉，是因为回落路径把构建输出丢掉了 ——
> 没有可观测性时，"没有收益"和"没有生效"长得一模一样。

### 2.7.1 第四次实测复核（#3587，2026-09-14）：缓存**确实**一条都没有

#3426 的三次实验是在 `xiaobu-acceptance.yml` 上做的。本轮在 **`post-deploy-eval.yml`**
上复核，结论一致，且这次拿到了**仓库级的硬证据**：

| 证据 | 实测值 | 出处 / 复现命令 |
|---|---|---|
| 仓库 Actions 缓存条目（总数） | **232 条** | `gh api "repos/<owner>/<repo>/actions/caches?per_page=100" --jq .total_count` |
| 其中 buildx / docker / gha 相关 | **0 条**（前 100 条全是 `gitleaks-cache`(94) / `setup-python`(2) / `setup-java`(2) / `node-cache`(2)） | `gh api ... --jq '.actions_caches[].key' \| grep -icE "gha\|buildx\|docker"` → **0** |
| 仓库可见性（影响 gha 缓存可用性） | **public** | `gh api repos/<owner>/<repo> --jq .visibility` ⇒ 排除"私有仓库 gha 缓存受限"这一常见嫌疑 |
| 最近一次 post-deploy run 的构建路径 | **回落**（`docker compose up --build`，无缓存） | run 34806843585 日志只有 `── 已清空旧卷（fresh DB）──` → `Container aikf-* Waiting`；**既无** `✅ 镜像构建完成（buildx + GHA cache，未回落）`，**也无** `::warning:: 回落` |
| 该 run 的栈步骤耗时 | **210s / 209s**（双 persona 各自独立栈，并行） | `gh api .../runs/34806843585/jobs`：`Start local stack` 04:39:32→04:43:02、04:39:37→04:43:06 |
| 同一 run 的评测步骤耗时 | xiaobu 408s / mibao 505s | 同上（`Run <persona> normal`） |

**两个新增结论**（超出 #3426）：

1. **不只是"缓存没命中"，而是"分支本身没留下任何痕迹"**：该 run 的 `Start local stack`
   步骤从头到尾**没有打印任何一条**判定信息 —— 既没有成功分支的 CACHED 层数/cache manifest，
   也没有失败分支的 `::warning::`/错误尾部。也就是说"到底走了哪条路"在日志里**无法判定**
   （只能靠"日志里没有成功标记"反推）。这与 #3426 的教训同族但更严重：
   那次是"失败可见性不足"，这次是**两条分支都没有留下可判定的痕迹**。
   ⇒ 本轮已修：构建前打印预期路径，构建后打印**判定行**（路径/是否回落/失败腿/耗时），
   两条腿分开判定（`admin-api` 挂了与 `ai-agent` 挂了不再长得一样）。
2. **失败腿可归因**：原实现用 `A && B` 嵌套，admin-api 失败时 ai-agent **根本不执行**，
   日志上看不出是哪条腿的锅；现在分开判，判定行直接写出 `失败腿=admin-api,ai-agent`。

**这些证据下的结论与建议**（#3587 ③）：

| 方案 | 预期收益（基于上表） | 代价 / 风险 | 建议 |
|---|---|---|---|
| 继续修 `type=gha` 层缓存 | **≈0**（三次实验 + 本轮复核共四次无效；后端"完全没参与"，无可利用错误；仓库是 public ⇒ 已排除"私有仓库 gha 缓存受限"这一嫌疑） | 继续投入排查上游 buildkit 缺陷，收益不确定 | ❌ 停止投入（#3426 已判定） |
| **GHCR 预构建镜像** | admin-api **与分支无关** → 可长期复用，省掉每次 Maven 打包；ai-agent 依赖源码 → 只省基础层/系统依赖层。栈步骤实测 **210s**，其中构建占大头 ⇒ **乐观估计每次评测省 2-3min（栈 3.5min → ~1min）** | ① 需 `packages: write` + GHCR 登录；② 镜像发布/清理策略（配额、过期）；③ 与"标准考场必须评**被部署的那份代码**"冲突 —— ai-agent 镜像必须按 SHA 构建，不能直接复用（否则评的不是这份代码）；④ 双 persona 矩阵 ×2 份拉取流量 | ⏸ **本包不实现**（改动不小且需要新权限；见下方拆分建议） |
| **修正 `--cache-from` 指向** | ≈0（当前写法本身没错：scope 已带 workflow 名、`mode=max` 已是最大导出） | —— | ❌ 无修正空间（不是"指错了"，是后端不工作） |

**GHCR 拆分建议（后续包）**：① 先做 admin-api（分支无关，收益确定、风险低）——
`docker buildx build --cache-to type=registry,ref=ghcr.io/<owner>/migao-eval-cache:admin-api,mode=max`
+ `--cache-from` 同 ref + `docker/login-action` 登录 GHCR，**保留现有回落路径**；
② 跑 3 次对比栈步骤耗时（本轮新增的判定行已提供现成的对照基线）；
③ 只有 ① 的收益被实测证实，再评估 ai-agent（它必须按 SHA 构建，收益只可能来自基础层）。
**不满足这两条前置条件就不要上镜像化** —— 本项目在层缓存上已经付过四次学费。

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

# 1b) 迭代档（issue #3417）：只复验几条 + 不重试 + 不取证 —— 把"改一行看一眼"压到分钟级
EVAL_CONCURRENCY=6 python tests/agent_eval/local_runner.py normal --cases .github/cases \
  --case-ids OR-019,OR-024 --max-retries 0
#   ⚠️ 收窄/快速档只用于迭代复验；**下结论前必须跑完整档**（见 §2.6 的红线）

# 2) 步骤级耗时（CI）
gh api repos/<owner>/<repo>/actions/runs/<id>/jobs \
  --jq '.jobs[].steps[] | "\(.name)\t\(.started_at)\t\(.completed_at)"'

# 3) 栈步骤逐行时间线（定位是 pip / maven / pull / healthcheck）
gh run view <id> --log | grep "Start local stack" | ...
```

守卫（改动若让退化会变红）：
`tests/unit_ci_workflows/test_schema_integrity.py`（栈缓存 + PyPI 源 + 审计口径 +
`TestEvalSpeedKnobs`：三旋钮接线与快速档边界，含"非取证步骤不许挂 fast"的反向守卫）、
`backend/ai-agent-service/tests/test_acceptance_case_checks.py`（并发有界、读写门独占、
报告顺序、预算不被并发突破、pre_clean 只独占清理动作）、
`tests/unit_ci_workflows/test_post_deploy_eval_supersede.py`（#3587：抑制判定口径 + 全局槽位 +
"抑制不得计失败"反向守卫）。

## 6. 结论：为什么**不该**在 PR 层做全量 LLM 评测（#3587）

> 本节是一次性结论，供后人决策时引用。**只给结论与建议，不改任何既有门禁属性**
> （required 名单与各 workflow 的 blocking 语义保持原样）。
>
> ⚠️ **下游已落地，本节表格是 2026-09-14 的快照（别再当现状读）**：
> 下面「事实 1」的四层 PR 真实 LLM，经 #3653（2026-09-15，降到一层）之后，
> 已由 **2026-09-17 用户裁定 2′/4′（承载 issue #4034）** 进一步**归零** ——
> PR 层真实 LLM **停跑**，`agent-behavior-eval.yml` 只留**零 LLM 的映射信号**；
> 判定用途收敛到单一入口 `post-deploy-eval.yml`（每 3 天 normal 全量 + 手动 dispatch），
> 既有定时档全部保留。现状口径见 `docs/testing/eval-environments.md` §3.1/§3.7。

### 6.1 三条实测事实

**事实 1：PR 层的真实 LLM 评测不拦门 —— 它是"信号"，不是"门禁"。**
分支保护 required_status_checks 只有确定性层那 9 项（`.env`/三模块单测/QA Growth Gate/
ci-helper/gitleaks/Danger Scan）；LLM 行为层**有意不进 required**
（`eval-environments.md` §3.1/§3.2 决策记录：真实 LLM 方差会卡死**无关** PR 的合并流水线；
job 名随 persona 参数化也不适合做 required 名）。
⇒ 一个改 AI 行为的 PR 目前要付**四层真实 LLM** 的成本：

| # | 层 | 触发 | 环境 | 拦不拦合并 |
|---|---|---|---|---|
| 1 | C 端 smoke（persona=xiaobu） | PR（AI 行为文件） | CI 独立栈 | ❌ 信息性 |
| 2 | 映射用例迭代档（#3502） | PR（AI 行为文件） | CI 独立栈 | 规则命中桶阻塞 / 兜底网只报告 |
| 3 | xiaobu Acceptance（PR 触发） | PR | CI 独立栈 | ❌ 信息性 |
| 4 | B 端云冒烟（pr-check） | PR | 云测试环境 | ❌ 信息性 |

**事实 2：并发不只是慢，它让结论变不准（本文件自己就记过两次）。**
① §2.2：3 job 分片把栈启动从 3.4min 抬到 **12min**，整跑 **19.8min > 串行 15.6min**；
② 用户侧实测：并发把评测轮次从 8min 抬到 **12min**、**确定性失败从 9 条涨到 13 条**。
⇒ "并发评测"制造的红灯里，有相当一部分**不是代码的问题**（是环境互抢），
而假失败会诱发"重跑—再假失败"的二次浪费（§2.4 重试预算正是被这么吃满的）。

**事实 3：栈成本在固定成本里占大头，而 PR 层把它乘了很多倍。**
栈步骤实测 **210s/腿**（run 34806843585；其中镜像构建占大头且缓存四次实测均未生效，§2.7/§2.7.1）
+ 依赖安装 ~20s。**PR 层每起一次栈就是 3.5 分钟**，而 PR 层的结论**不拦门**（事实 1）。
本会话实测窗口（2026-09-14 05:18~05:25 UTC）：

| run | workflow | 建 run → 首个 job 起跑 | 结果 |
|---|---|---|---|
| 34809133992 | xiaobu-acceptance | **231s（排队）** | 栈 3min → 装依赖 19s → 评测**跑 0 秒即 failure** |
| 34809196579 / 34809398757 | xiaobu-acceptance | 79s / 48s（排队） | 与 4 个 PR 的其余 workflow run 同时 pending |
| 34809476067 / 34809506509 | xiaobu-acceptance | 144s / 1s | 同一时刻 **6+ 个 run 排队** |

### 6.2 结论

**PR 层只保留「定向映射用例」（窄、报告制）；完整覆盖交给定期/手动批次轮（部署后回归，#3503/#3925）。**

理由（按重要性）：
1. **信号价值与成本错配**：不拦门的信号不该按拦门的价格买。PR 层要回答的是
   "这次改动**碰到的**能力有没有坏"（几十条映射用例足够），不是"整个 agent 还行不行"；
2. **并发制造假失败**：PR 层是并发最密集的地方（多 PR 同时触发），也是最不该承担
   "不能有假失败"要求的地方 —— 而全量/结论档恰恰需要确定性（事实 2）；
3. **完整覆盖有更合适的时机**：部署后 / 批次轮（#3503）在**同一份 main 状态**上跑全量，
   没有"评到一半代码又变了"的问题（#3587 的抑制正是为此），且频率低、可串行（§3.3 全局槽位）；
4. **栈成本可预测**：PR 层少起一次栈 = 少 3.5min 固定成本 × 每个 PR（事实 3）。

### 6.3 建议的分层清单（现状 → 建议，**含"要不要改门禁属性"**）

| 层 | 档位 | 环境 | 触发 | 建议 | 需要改门禁属性吗 |
|---|---|---|---|---|---|
| PR · 确定性 | 三模块单测 / QA Gate / ci-helper / gitleaks / Danger Scan | CI | PR | **保持 required**（本来就快、无方差） | 否 |
| PR · 行为窄档 | **只跑映射用例（#3502 的规则命中桶）**，兜底网可保留但**显式标注不阻塞** | CI 独立栈 | PR（AI 行为文件） | **收窄**：默认不跑 smoke/Acceptance/云冒烟（或仅在**规则未命中**时才跑其中一层做兜底） | 否（三者本就是信息性） |
| PR · 冒烟档 | C 端 smoke（7 条） | CI 独立栈 | PR（AI 行为文件） | 降为**按需**（`workflow_dispatch` 或"映射用例全绿但仍想抽检"）；**不**与映射用例并行起两个栈 | 否 |
| 部署后 | 双 persona **全量** + `completion_verdict` | CI 独立栈 | **手动 `workflow_dispatch`**（#3925：部署后自动触发已移除，改手动/定期） | **按需手动执行**（人显式要求时才跑，省真实 LLM 成本）；全局串行（§3.3） | 否 |
| 批次/夜间 | normal 全量（降频） + adversarial（每周六） | CI 独立栈 | schedule | **保持**（只追踪不阻塞） | 否 |
| 里程碑/下结论 | 结论档：全量 + 验收剧本 + 双裁判 + `completion_verdict` | CI 独立栈 | 人工/里程碑 | **保持必过** | 否 |

> **本节的边界**：以上是**建议**，落地需要单独的任务包（改 workflow 的触发/档位 =
> 改门禁矩阵的"自动动作"列，须同步改 `eval-environments.md` §3.1 与 `migao-dev-flow` §16.5）。
> #3587 只交付了本条结论 + ①②（抑制 + 全局槽位）+ ③（缓存实测结论），
> **没有**动任何既有门禁的 blocking 属性。

## 7. 思考开关的实测账（issue #3573）：**参数生效**，且默认是「开」

> 为什么记在这里：思考预算是**评测/线上共同的主要成本与延迟杠杆**（一条最简 prompt 的
> 一次调用就能烧掉 100+ reasoning token / 多 0.5-1s）。此前这条杠杆建立在**一个从未实测过
> 的假设**上，故单独立账。

### 7.1 待验证的问题（不是"优化"，是"证实/证伪"）

`LLMFactory.create_skill_llm` 的思考开关写法来自 MiniMax-M3 时代
（`app/llm/factory.py:63-69`）：`enable_thinking=True` 发
`extra_body={"thinking": {"type": "enabled"}}`，`force_no_think=True` 发
`{"thinking": {"type": "disabled"}}`；**两个都不传 → 不传 `extra_body`**（`tests/test_llm_factory.py:41` 钉死）。

矛盾证据（仓库内已确证，这是本账的起点）：

- 同一 provider（`api.deepseek.com` / `deepseek-flash`）的**视觉路径**在
  `tests/test_llm_factory.py:81-82` 明确断言
  「DeepSeek vision（OpenAI 兼容）不传 MiniMax 专属 thinking extra_body」+
  `assert "extra_body" not in kwargs`（PR #2547 / commit `f7cd3ba9` 引入）；
- 而 **skill 路径仍在传**（`factory.py:64/67`）；
- `factory.py:51` 的注释「不传参时 M3 默认仍开思考」是 MiniMax-M3 时代产物，当前模型是
  `deepseek-flash`（`app/config.py:41,111-112`）。

`_THINKING_INTENTS` / `_MULTI_TURN_THINKING_INTENTS`（`app/graph/skills/base_skill.py:198-224`）
与 issue #3153（把 5 个写意图纳入 thinking）的全部收益，都以「该开关真的生效」为前提；
若为静默 no-op，则 #3153 的收益必须重新归因。

### 7.2 实测结论：**参数生效（不是 no-op，也不是被拒）**

- **run id**：`34809425971`（job `thinking-probe-bootstrap`，2026-09-14 05:30Z，
  `workflow_dispatch` 触发的 `test/3573-thinking-probe`）
- **专属入口自证**：`34810173534`（`LLM Thinking Probe` workflow 文件自己跑通，39s，
  结论同上 `VERDICT=参数生效`）—— 证明该 workflow 合入 main 后 `gh workflow run` 可用
- **探针**：`backend/ai-agent-service/scripts/probe_thinking_effect.py`
  （3 次真实调用、prompt 极短、不跑评测用例）
- **CI 入口**：`.github/workflows/llm-thinking-probe.yml`（仅 `workflow_dispatch`，零常态成本）
- **机器判定**：`VERDICT=参数生效`（两次独立 run 一致 → 非偶然）

出网请求体（拦 httpx 传输层取得，证明 `extra_body` 未被 langchain 静默丢弃）：

| 变体 | 出网 `thinking` | `max_completion_tokens` |
|---|---|---|
| A `enable_thinking=True` | `{"type": "enabled"}` | 384000 |
| B `force_no_think=True` | `{"type": "disabled"}` | 2048 |
| C 两者都不传（基线） | **不存在该 key** | 2048 |

响应侧证据（同一 prompt「只回答两个字：好的。不要任何解释。」）：

| 变体 | `reasoning_content` | reasoning tokens | output tokens | 耗时 | content |
|---|---|---|---|---|---|
| A enabled | **len=164** | 100 | 102 | 1.33s | `好的` |
| B disabled | **absent** | （无该字段） | **1** | 0.91s | `好的` |
| C 基线（不传） | **len=537** | 122 | 124 | 1.55s | `好的` |

三条可判定结论：

1. **参数生效**：A 与 B 在 `reasoning_content` 有无、reasoning token 数、output token 数上
   全面可分（A 102 输出 token vs B **1** 个）。
   第二次独立 run（`34810173534`）同样形态（A 44 / reasoning 42 vs B **1**，
   基线 52 / reasoning 50）—— **`disabled` 侧的 output token 稳定为 1 且 `reasoning_content`
   恒 absent**，`enabled`/基线侧稳定为「有 reasoning + 数十 output token」，非单次偶然。
2. **DeepSeek 认这个字段，且不校验**：`thinking` 作为顶层 body key 出网、返回 200、无 400；
   但响应 `response_metadata` 里**不回显**该字段（`model_name/finish_reason/model_provider` +
   `system_fingerprint`，无 `thinking`/`reasoning` 回显）→ 判定只能靠**行为差异**，不能靠回显。
3. **provider 默认是「开」**：C（不传 `extra_body`）照样产出 reasoning_content（len=537，
   122 reasoning tokens），与 A 同级。
   ⇒ `factory.py:51` 那句「不传参时默认仍开思考」在当前 provider 上**结论仍然成立**
   （虽然它是 M3 时代的注释）；但**语义已变**：不是「M3 特有的默认」，而是
   「DeepSeek 的默认思考行为」。`enable_thinking=False` 才是「什么都不说、放任默认」，
   `force_no_think=True` 才是**真正关闭**。

对既有结论的影响（明确写清，防误读）：

- ✅ **`_THINKING_INTENTS` / `_MULTI_TURN_THINKING_INTENTS` 的调参在当前 provider 上有效**；
  #3153 的收益**不需要重新归因**（不是「参数没生效所以收益来自别处」）。
- ⚠️ 但反过来的推论同样重要：因为**默认就是开**，真正省钱的开关是
  `force_no_think=True`（关思考），而不是 `enable_thinking=True`（那是显式回到默认）。
  单条最简 prompt 实测，关思考把 output token 从 102 → **1**（-99%）、耗时 1.33s → 0.91s。

一个**未解释的观察**（诚实标注，不编因果）：`input_tokens` 在开思考时稳定为 40、
关思考时稳定为 14（两次 run 一致），而探针三次用的是**同一个 prompt**。
看到的最接近的解释是基线那次 `reasoning_content` 里出现「there's a system instruction
that says I should think before answering」—— 疑似 provider 在思考模式下会附加思考指令，
但**本次探针没有取证请求侧 messages，无法证实**。若后续要靠 input token 做成本核算，
需要单独取证（属独立小包，不影响本账三条结论）。

### 7.3 探针顺带发现的能力缺口（属于后续包，本账只记录）

1. **视觉路径缺该开关**：`factory.py:82-105`（`create_vision_llm`）**不传任何 thinking 参数**
   → 按 §7.2 结论 3，**每次图片识别都在默认开思考**（拍照找同款/识别面料这类任务，
   推理 token 纯属浪费）。与 skill 路径一致化的做法：显式传
   `extra_body={"thinking": {"type": "disabled"}}`（或按任务分级）。
2. **轻量文本路径的 `disabled` 是有效省钱**：`create_intent_llm` / `create_summary_llm` /
   `create_suggestion_llm` / `create_registration_review_llm` / `create_briefing_llm`
   （`factory.py:114/137/206/223/240`）都传 `disabled` —— 实测该参数确实生效，这些路径的
   省 token 设计**成立**（此前无法证实）。
3. **写法用的是「未文档化的兼容形态」**：`{"thinking": {"type": ...}}` 是 MiniMax 形态，
   DeepSeek 官方 Thinking Mode 文档（https://api-docs.deepseek.com/guides/thinking_mode/）
   记的是 `reasoning_effort`。当前实测**能用**（§7.2），但属于依赖兼容行为；
   是否迁移到官方文档形态是**独立决策**（涉及全部 5 个轻量路径 + 视觉路径），不在本账范围。

### 7.4 复现方法

```bash
# CI（唯一能拿到真实凭据的路径）：workflow_dispatch 专用入口，3 次真实调用
gh workflow run llm-thinking-probe.yml
gh run watch <run-id>
gh run view <run-id> --log   # 检索 VERDICT= 与 wire#0 thinking
```

> **入口已常驻 main**（workflow id `357556316`，PR #3579 合入）——`gh workflow run` 随时可复跑；
> 结论有变（provider 升级 / 换模型）时**先重跑探针再改行为**，别凭记忆推断。
>
> ⚠️ 一个 CI 事实（本次取证踩过）：**新增的 workflow 文件在合入默认分支之前无法
> `workflow_dispatch`** —— GitHub 只在默认分支索引 workflow，`gh workflow run <新文件>`
> 会报 `HTTP 404: not found on the default branch`。要「先拿结论再合入」时，只能借既有
> dispatch 入口（或用一次性 `push` 触发）取证；反之若必须先合入，就把「取证」与
> 「行为改动」拆成两个 PR（本账正是这么做的）。

本地无 `.env`（无 LLM 凭据）时脚本**优雅退出**并打印 `SKIPPED: 本次未发送任何 LLM 调用，
**不构成任何结论**` —— 不会静默假成功（这是刻意设计：探针最危险的失败模式是"看起来跑过了"）。
退出码语义：结论（no-op / 生效 / 被拒）**不影响**退出码；只有探针自身没跑成
（凭据 401/403、网络不可达、服务端 5xx）才非零退出。

### 7.5 后续动作建议（基于本结论）

1. **`_MULTI_TURN_THINKING_INTENTS` 该补齐 5 个写意图** —— 因为参数**确实生效**，
   多轮写流程（建品/角色/客户/分类/加工项）的迭代 2+ 轮保留思考是**真实可得的收益**，
   不存在「补了也白补」的情形。
2. **优先级更高的反而是「关」的一侧**：视觉路径（`create_vision_llm`）缺 `disabled`
   → 每次识图默认开思考；补上与 skill 路径一致的显式关闭，是**纯赚**的延迟/成本优化。
3. **不要顺手改 `factory.py` 的行为**：本账是「证实/证伪 + 记录」，行为改动（视觉路径补
   `disabled`、是否迁移到 `reasoning_effort`）各自独立开包，避免把「实测结论」和
   「行为变更」混在一个 PR 里（结论可复现，行为变更需要自己的回归）。
