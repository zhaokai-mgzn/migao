# 用例库腐烂清单（第二版·只读审计 + 无争议重锚）—— issue #7035

> **本文件是什么**：issue #7035「用例库重锚」的**可复算审计结论**。第一版清单由 #7035 的
> 2026-10-16 评论给出（当时 **771 条**用例、四类腐烂）。**20 天后重算，结论已经变了**：
> 那批条目绝大多数已由 #7047 / #7048 / #7058 / #7060 / #7050 落地关闭，四类腐烂在**受管面**上
> 已由**常驻判据**守住。本文件因此不复述旧清单，只做两件事：
> ① **现取复核**（每条给可复制命令与今日读数）；② **登记仍然腐烂的那一小部分**并逐条说清
> 「为什么它是腐烂、不是产品缺陷」，以及「重锚后它仍会红的那条路径在哪」。
>
> **权威口径**（按 #5247 的三条评论，后者覆盖前者）：
>
> | 类别 | 支持面 | 出处 |
> |---|---|---|
> | 创建**商品 / 订单** | ❌ 不支持 | 2026-10-16T07:29Z |
> | 创建**其他单据类**（加工单 / 发货单 / 入库单 / 采购单 / 售后工单 / 质检单 …） | ❌ 不支持 | 2026-10-16T07:30Z |
> | 创建**非单据对象**（员工 / 角色 / 客户 / 供应商 / 标签 / 分类 / 加工项 / 定时提醒） | ✅ 支持 | 2026-10-16T07:42Z（终版） |
> | **变更**（改已存在对象 / 单据） | ✅ 支持 | 2026-10-16T07:30Z |
> | **删除 / 停用 / 作废** | ❌ 不支持（只能引导去后台） | 2026-10-16T07:42Z（终版） |
> | 查询 / 分析 / 导航 | ✅ 支持 | 2026-10-16T07:30Z |
> | **射程** | **仅 B 端（黄金策）**；C 端（米宝）维持现状 | 2026-10-16T07:42Z（终版） |
>
> ⚠️ 审「射程」这一条时最容易走错：2026-10-16T07:29Z 那一版说的是「仅商品/订单不支持、
> 其他操作都需要支持」，**它已被 07:30Z 与 07:42Z 两次收窄覆盖**。只读 07:29Z 那一版会把
> 17 条 C 端下单用例误判成 A 类（见 §2 的读数）。

## 0. 方法与复算（零 LLM、零写操作）

判据面全部**现取**，不抄任何手写清单（抄清单就是第二个会腐烂的台账）：

| 面 | 取法（单一实现，不另写一套） |
|---|---|
| 用例全集 | `.github/cases/*.yml` → `yaml.safe_load`；`cases` 键下的条目 |
| 人格 / 腿选择 | `tests/agent_eval/eval_case_filter.py` 的 `select_cases_for_persona` / `case_persona` / `case_skip_reason` |
| B 端可跑工具集 | `eval_case_filter.mibao_real_toolset()`（= `MIBAO_SKILL_FILES` 各 skill 源码 `*_TOOLS` 并集） |
| C 端可跑工具集 | `eval_case_filter.XIAOBU_TOOLS` |
| 工具读写面 / action 枚举 | `scripts/case_coverage.py` 的 `registered_tools` / `action_enum` / `tool_declared_actions` |
| 声明键白名单 | `scripts/case_coverage.py` 的 `assertion_key_violations`（#7026 的类级固化） |
| 已登记的端归属守卫 | `tests/unit_ci_workflows/test_mibao_case_invariants.py`（`TestBendCaseToolBoundary` / `TestBendWriteToolSuccessAssertions`） |
| 机器判红通道 | `tests/unit_ci_workflows/test_case_machine_fail_channel.py` |

**一条命令复算本文件 §1 的四个计数**（在仓库根目录跑；输出应与下表逐行吻合）：

```bash
python3 - <<'PY'
import sys, glob, yaml, importlib.util
sys.path.insert(0, '.')
s = importlib.util.spec_from_file_location('ecf', 'tests/agent_eval/eval_case_filter.py')
ecf = importlib.util.module_from_spec(s); s.loader.exec_module(ecf)
from scripts.case_coverage import assertion_key_violations
cases = []
for f in sorted(glob.glob('.github/cases/*.yml')):
    for c in (yaml.safe_load(open(f)).get('cases') or []):
        c['__file'] = f; cases.append(c)
B = ecf.mibao_real_toolset()
print('total', len(cases), '| b_end_tools', len(B),
      '| skipped', sum(1 for c in cases if ecf.case_skip_reason(c)))
FENCED = ('order_create', 'aftersale_create')          # 裁定禁止的「创建」工具
hits = [c for c in cases if not ecf.case_skip_reason(c)
        for e in (c.get('expectations') or [])
        for br in ecf.expectation_branches(e) if br in FENCED]
print('A raw:', len(hits), '=> C 端（射程外）', sum(1 for c in hits if ecf.case_persona(c) == 'xiaobu'))
print('  B 端射程内:', [(c['id'], [x.get('only_if_called') for x in (c.get('must_succeed') or [])])
                        for c in hits if ecf.case_persona(c) != 'xiaobu'])
C = [c for c in cases if not ecf.case_persona(c) and not ecf.case_skip_reason(c)
     and (lambda bs: bs and not (bs & B))({b for e in (c.get('expectations') or [])
                                           for b in ecf.expectation_branches(e)})]
print('C:', len(C), '| D(key-level):', len(assertion_key_violations(cases)))
PY
```

> 下表读数是**某一时点**的现取（用例数随 main 演进而增）⇒ **以 §0 的脚本现取为准**；
> 每次并入 main 后重跑一次即可，本文件不追着改数字。

**今日读数（2026-11-04，`origin/main` = 起始基线 `a6d271678` 的父提交链）**：

| 项 | 读数 |
|---|---|
| 用例总数 | **1016**（2026-11-04 现取；本包重锚前为 1014，第一版审计时 771） |
| `persona` 分布 | 缺省（双端）**895** / `mibao` **68** / `xiaobu` **53** |
| `skip_reason` 非空 | **861**（不进 runner 实跑面；本包重锚前为 861 —— 已 un-skip `HR-002` / `HR-010`，见 §3） |
| B 端（黄金策）可跑工具集 | **41** 个 |
| C 端专属（B 端无） | **8** 个：`aftersale_create` / `aftersale_query` / `curtain_calc` / `customer_address_query` / `customer_logistics_track` / `customer_order_query` / `order_create` / `payment_qrcode_query` |
| **A**（**射程内**：B 端用例的期望/效果层要求创建商品/订单/单据） | **0**（全库原始命中 **17** 条，**全部**是 `persona: xiaobu` ⇒ 射程外） |
| **C**（双端 + 无 skip + 全部期望分支都不在 B 端工具集） | **0** |
| **D**（`assertion_key_violations` 判据） | **0** |

## 1. 四类腐烂的现取判定

### 1.1 A 类（期望含创建商品 / 创建订单 ⇒ 与裁定冲突）：**0 条在射程内**

全库把**写类工具**（含裁定禁止的创建）写进**期望 / 效果层**的用例共 **24** 条候选，逐条判下来**没有一条落在射程内的腐烂**：

| 分组 | 条数 | 为什么不是腐烂 | 代表 |
|---|---|---|---|
| `persona: xiaobu`（C 端） | **17** | 终版裁定「射程 = 仅 B 端」，C 端下单能力**仍在**（`order_create` 仍在 `XIAOBU_TOOLS`）⇒ 期望成立 | `order.yml` 的 `OR-014` / `OR-017`~`OR-026` / `OR-037` / `OR-049` / `OR-050`、`chat.yml` 的 `CH-010` / `CH-012` / `CH-025`、`aftersales.yml` 的 `AS-010` |
| `product_update` / `sku_update` | **4** | 这两个是**变更**（改已存在商品 / 改某规格价），终版裁定 **✅ 支持**，且在 B 端工具集内 | `.github/cases/product.yml` 的 `PR-009` / `PR-010` / `PR-021` / `PR-133` |
| 双端 + **`only_if_called` 条件档** | **3** | `must_succeed` 声明了 `only_if_called: true` ⇒「从未调用」不算违规，只有「真去建了却没成」才红；C 端腿保留判别力、B 端腿不产生噪音（#3778 刻意设计） | `.github/cases/aftersales.yml` 的 `AS-003` / `AS-005`、`.github/cases/chat.yml` 的 `CH-009` |

> 🔁 **复核命令**（任取一条看现取原文，`persona` 与 `only_if_called` 同屏可见）：
> ```bash
> python3 -c "import yaml;d=yaml.safe_load(open('.github/cases/chat.yml'));print([c for c in d['cases'] if c['id']=='CH-009'][0]['must_succeed'])"
> ```
> 判据（让 A 类进不来）：`tests/unit_ci_workflows/test_mibao_case_invariants.py` 的
> `TestBendWriteToolSuccessAssertions::test_must_succeed_tools_are_bend_capabilities`
> —— B 端用例的效果层一旦点名非 B 端能力（含 `order_create` / `aftersale_create`）即红。

⚠️ **与第一版审计的差异（照实登记）**：第一版把 17 条 C 端下单用例计入 A 类，**是错的** ——
它是按 07:29Z 那一版口径算的，而 07:42Z 终版已把射程限定在 B 端。本条不再计入。

### 1.2 B 类（期望 agent「拒绝 / 只读」而裁定要求支持）：**3 条仍腐烂 ⇒ 本包已重锚**

判法：非 skip 用例里，`expectations` 的**全部** OR 分支都只是「不发工具直接答」或「只读 action」，
而该用例的 `user_inputs` 诉求按终版裁定**必须被支持**。

现取命中 **7** 条「纯拒绝期望」（`CH-015` 转人工 / `CH-051` 能力问答 / `CH-052` 批量下架 /
`DF-001`·`DF-004` token 攻击 / `OR-074` 无焦点追问 / `ST-003` 改密码），逐条判：

| 用例 | 判定 | 依据 |
|---|---|---|
| `.github/cases/chat.yml` 的 `CH-015` | ✅ 不腐烂 | 「转人工」无人工通道 ⇒ 如实告知 + 继续服务 = 正确行为 |
| `.github/cases/chat.yml` 的 `CH-051` | ✅ 不腐烂 | 问的是**能力**（「能改商品名称吗」），不是让改；直接回答「能」正确 |
| `.github/cases/chat.yml` 的 `CH-052` | ✅ 不腐烂 | 「批量下架」= **停用**类 ⇒ 终版 ❌ ⇒ 如实说明 + 给落点正确 |
| `.github/cases/defense.yml` 的 `DF-001` / `DF-004` | ✅ 不腐烂 | 对抗档（超长回复 / 洪泛），预期就是克制 |
| `.github/cases/order.yml` 的 `OR-074` | ✅ 不腐烂 | 无会话焦点时**必须追问**是哪一单，猜单才是缺陷 |
| `.github/cases/settings.yml` 的 `ST-003`（改密码） | 🟡 **待裁定** | 「改密码」在商家后台是有的 ⇒ 按「对齐观星台」倾向 ✅；但它同时是**安全边界**（改密码 ≠ 一般业务变更）⇒ 属 §30.1 第 ③ 类（权限 / 安全边界），**本包不改** |

**真正腐烂的 3 条在 `hr.yml`**（它们不是「纯拒绝」，而是「期望只剩只读路径」——
请求是**写**，期望却只要求**读**，等于把「不执行」奖励成合格）：

| 用例 | 现取期望 | 为什么是腐烂 | 处置 |
|---|---|---|---|
| `.github/cases/hr.yml` 的 `HR-002`（创建员工 - 开账号） | `employee_manage(action=list)` | 终版：创建**非单据对象** ✅；且 `employee_manage` 的 `VALID_ACTIONS` 已含 `create`、`read_only=False`（#7050，2026-11-03 合入）⇒ skip 理由「工具已收窄为只读」**当场被源码证伪** | **改期望 = 应执行该操作** + 补效果层 |
| `.github/cases/hr.yml` 的 `HR-008`（更新员工手机号） | `employee_manage(action=detail)` | 同上：`VALID_ACTIONS` 含 `update` ⇒ 「变更」✅ 支持 | 同（**但仍须 skip**，理由见 §3） |
| `.github/cases/hr.yml` 的 `HR-010`（有能力时不得误拒·正向对照） | `role_manage(action=list)` | **期望与标题自相矛盾**：标题写「同一请求**必须真的执行**」，期望只要求列角色 | **改期望 = 应执行该操作** + 恢复落库断言 |

> 🔁 **复核命令（证伪 skip 理由——这是本包唯一「AI 可裁」的关键一手）**：
> ```bash
> grep -n "read_only = \|^VALID_ACTIONS\|^READ_ONLY_ACTIONS" backend/ai-agent-service/app/tools/employee_manage.py
> ```
> 今日读数：`VALID_ACTIONS = {list, detail, create, update}` / `READ_ONLY_ACTIONS = {list, detail}` /
> `read_only = False` ⇒ 写 action 存在且未绑定为只读。
>
> 且 `HR-010` 的 `skip_reason` **自己写着 un-skip 判据**（逐字）：「当 B 端重新获得创建员工能力
> （`employee_manage` 的 `action=create` 回到源码且重新绑定 B 端）时 —— 把 `expectations` 改回
> `employee_manage(action=create)`…、恢复 `must_succeed` 与 `db_verify`，并摘掉本 `skip_reason`」
> ⇒ 判据已满足，不需要人工再裁「该不该支持」。

### 1.3 C 类（双端用例里混 C 端专属期望）：**0 条**

第一版审计对 C 类已给过「证伪」（实数 0）。今日重算仍为 **0**，原因有两条，**都已机械化**：

1. `expectations` 面：`TestBendCaseToolBoundary::test_every_expectation_has_bend_runnable_branch`
   要求 B 端可跑用例的每条期望**至少有一个** B 端可跑的 OR 分支 ⇒ 全分支 C 端专属即红；
2. 端点选择面：`select_cases_for_persona(cases, 'xiaobu')` 会对双端用例施加
   「全部期望工具 ⊆ `XIAOBU_TOOLS` 且语义适配自助」的收口 ⇒ 反向（B 端管理用例）不会误进 C 端腿。

**受管面读数**：双端 + 无 skip + 全部期望分支不在 B 端工具集 = **0**。
另有 **3** 条双端用例的**效果层**点名了 C 端专属工具（`AS-003` / `AS-005` / `CH-009`），
但它们都带 `only_if_called: true` ⇒ 是 §1.1 表格里那一档**刻意设计**，不是腐烂。

> 🔁 复核：`python3 -m pytest tests/unit_ci_workflows/test_mibao_case_invariants.py -q`

### 1.4 D 类（runner 不支持的键 / 值 ⇒ 断言静默空转）：**0 条**

`assertion_key_violations`（单一实现点在 `scripts/case_coverage.py`，门禁与 L0 共用）今日读数 **0**；
第一版点名的 `PP-016`~`PP-021`（#7026）已由 #7047 修好（`must_succeed` 改用 `action:`，
`expectations` 保留 `args`——后者是**被 runner 识别并参与匹配**的，两侧白名单不同）。

**本包把「静默空转」面又往下挖了一层**（键 → 值），五个新面**全部为 0**（每个都附复算口径）：

| 面 | 判定 | 今日读数 | 为什么它会静默空转 |
|---|---|---|---|
| `precondition` 的 `type` | 现取 `local_runner` 的 `_PRECONDITION_TYPES` 键集比对 | 0 条未登记 | 未登记类型 ⇒ 前置不执行，用例带着假前置跑，红的表现像「agent 不干活」 |
| `pre_clean` / `post_clean` 的 `type` | 同上，比 `_CLEAN_TYPES` | 0 条未登记 | 未登记类型 ⇒ 夹具不复位 ⇒ **污染同栈其它用例** |
| `forbidden_text` / `want_text` 的 `round` 越界 | 比对 `user_inputs` 轮数 | 0 条 | runner 对越界**已 fail-closed 判红**（不再静默） |
| `db_verify` / `post_session` 的 `fetch` | 比对 runner 的 fetch 分派表 | 0 条未分派 | 未分派 ⇒ 落库断言不执行 |
| 用例在 B 端腿**无任何计分断言** | `expectations` + 机器判定的 `data_checks` | 0 条 | 空断言 ⇒ `score = 1.0` 恒绿 |

> 🔁 复核（一条命令，五个面一起算）：把本文件 §0 的复算块最后一段替换成扫 `precondition` /
> `pre_clean` 的 `type` 与 `local_runner` 的 `_PRECONDITION_TYPES` / `_CLEAN_TYPES` 键集求差即可；
> 键集必须**现取**（写死清单会随 runner 演进腐烂，正是本文件的主题）。
>
> **为什么这层没被 #7026 的判据挡住**：`assertion_key_violations` 判的是**键**（`must_succeed[*]`
> 的允许键），**值域分派**在 runner 侧；runner 目前对上面每一面都在**运行期** fail-closed 或
> 有分派表兜底 ⇒ 属「运行期能自证」而非「静态缺口」，故本包**不新增平行判据**（避免第二份口径）。

**D 面的一个残留（有意保留，不是腐烂）**：全库 **21** 处 `forbidden_tools` 点名了**已不在注册表**
的工具名（`product_manage` / `order_manage` / `processing_order_generate` / `processing_order_update`）。
它们**今天确实永不触发**（工具都解绑了），但那是 #7048 的**刻意设计**：把「不得真去建品 / 下单」写成
**重绑定绊线** —— 若哪天有人把写工具接回 B 端，这 21 条会立刻判红。
⇒ **保留并登记**（本文件即登记处）。若要把它变成可判的静态面，正确做法是给
`case_coverage` 加「值必须是在册工具 **或** 已登记绊线」两分支 —— 本包**有意不做**：
它会逼出一次 21 条的台账维护，而当前形态没有任何真实损失（判据不因它假绿）。

## 2. 与第一版清单的差异（逐条闭合证据）

第一版（#7035 的 2026-10-16 评论）列了 **A 41 / B 21 / C 0 / D 11 / 灰 8**。今日复核：
**受管面上 0 条残留**，闭合承载体逐条如下：

| 第一版条目 | 今日判定 | 闭合于 |
|---|---|---|
| `CH-009` 的 `order_create` 分支 | ✅ 已重锚（`data_checks` 明写「B 端射程内创建订单 ❌」，`must_succeed` 收成条件档） | #7047 |
| `CH-019` / `CH-044`（建商品） | ✅ 已重锚（`forbidden_tools[product_manage(action=create)]` + `interact` 期望退役） | #7047 / #7058 |
| `OR-030`（下单） | ✅ 已重锚（`expectations` 收成 `validate_input` + `forbidden_tools[order_create]`） | #7047 / #7058 |
| `AS-003` / `AS-005` / `AS-010`（`aftersale_create`） | ✅ 已重锚（期望收成 `after_sales_manage`；写分支只留条件档） | #7047 / #7058 |
| `HR-009`（开客服账号） | ✅ 已重锚（#7050 接回后改为「能开、但该身份缺权限 ⇒ 如实说明 + 后台路径」） | #7050 / #8561 |
| `ST-005`（标记已读） | ✅ 已重锚（期望改为 **真做**：`notification_manage(action=mark_read) or interact` + 假承诺禁词） | #7058 |
| `DF-006` / `DF-007`（安全语义写成「必须调工具」） | ✅ 已重锚（期望 `direct_reply or product_search` = 拒绝也算合格） | #7060 |
| `PP-016`~`PP-021`（`must_succeed.args`，D 类） | ✅ 已修（改用 `action:`）+ **类级守卫** | #7047（#7026） |
| `HR-005`（`role_manage` 过度指定 `action`） | ✅ **不是腐烂**（见下） | — |
| `CH-001`（两条期望跨两次运行才可能满足） | ✅ 已重锚成 `product_detail or product_search` | #7047 |
| `FN-001`（资金流水夹具缺表） | 🧰 夹具面（不是用例腐烂） | #7043 |
| `HR-002` / `HR-008` / `HR-010`（员工写能力） | 🔴 **本包发现的残留 rotting**（第一版把它们归入已对齐/灰色，实为「只读口径」的遗留） | 本包 |

**两条必须照实登记的更正**：

1. **`HR-005` 不是腐烂** —— 它表面上写了两条**合取**期望（`role_manage(action=list)` 与
   `action=all`），而 `expectations` 逐条都要过 ⇒ 看着像「一次运行永远凑不齐」。但 runner 有
   **只读查询动作等价组**（`local_runner` 的 `_QUERY_ACTION_SYNONYMS` + `_is_query_action_equal`，
   经 `check_expectation` 的 `action` 比较调用）⇒ 一次 `action=all` 调用**同时满足**两条。
   ⚠️ 这是「读码才否掉」的一个假说：**只看 yaml 会把它误判成 D 类**。
2. **17 条 C 端下单用例不在 A 类射程内**（见 §1.1 的差异说明）—— 只读 07:29Z 版裁定得出的
   「其他操作都需要支持」会把它们全部算成腐烂。

## 3. 本包改了什么（只有无争议项）

| 用例 | 改动 | 为什么不算「放宽门禁」 |
|---|---|---|
| `.github/cases/hr.yml` `HR-002` | `expectations` 由只读 `list` 改为 **`employee_manage(action=create) or interact`**；补 `must_succeed[employee_manage(action=create)]`；`data_checks` 与 `skip_reason` 按新事实重写 | 只读路径是**过期的低标准**（「不执行也算过」）。改后要求**真执行**（或走确认卡），并要求工具**真的成功** ⇒ 判别力**只增不减** |
| `.github/cases/hr.yml` `HR-010` | `expectations` 由 `role_manage(action=list)` 改为 **`employee_manage(action=create) or role_manage(action=create) or interact`**；补 `must_succeed[employee_manage(action=create)]`；保留 `db_verify[employee]`（李四落库）；`skip_reason` 重写 | 该用例**标题**本来就要求「必须真的执行」，原期望与标题矛盾。改后与 `db_verify` 落库断言**同向**，是**恢复**而非放宽 |
| `.github/cases/hr.yml` `HR-008` | `expectations` 由 `employee_manage(action=detail)` 改为 **`employee_manage(action=update) or interact`**；补 `must_succeed[employee_manage(action=update)]`；`skip_reason` 重写为**真实原因**（见下） | 同族；改后要求 update 真的成功 |

**处置（集成侧 2026-11-04 裁定后落定）**：`HR-002` / `HR-010` **已 un-skip**；`HR-008` **仍 skip**（夹具缺口）。

- `HR-002` / `HR-010`：**已 un-skip**（`skip_reason` 清空、`merge_log` 记明「un-skip 于 2026-11-04；
  红了按产品缺陷开单，不重新 skip」）。裁定理由（逐条）：能力已接回源码、期望已重锚 + 有 `must_succeed`
  效果层 ⇒ **再保持 skip = 让刚接回的能力零断言覆盖**；un-skip 本身**不触发评测跑**（只是把用例放进
  可跑集），**keep-skip 才是永久静默**；fail-closed 的方向是放进集里，红了说明产品真有问题 ⇒ 开产品单。
  与 #4262 不冲突：那条禁的是「自动派发评测 workflow 烧钱」，不是「不许把用例放进集里」。
  **读数**：B 端（`mibao`）可跑集 **111 → 113**；`skipped` 总数 **861 → 859**（并入 main 的 MC-190 后为 **860**）。
- `HR-008`：**夹具缺口，不是用例腐烂** —— 它把种子员工的手机号从 `13700137000` 改成
  `13900139111`，而 runner 的复位族里**没有**「把手机号改回去」的类型
  （`_CLEAN_TYPES` 只有 `employee_reactivate` / `employee_remove`）⇒ 一旦 un-skip，
  **第二次跑的前置必然不成立**（自污染），且会连带污染同租户其它读员工的用例。
  **重启条件**：`_CLEAN_TYPES` 增加手机号复位类型后，按 `HR-002` 同口径 un-skip。
  ⚠️ 这条是**有意不做 + 登记的缺口**，不是「已解决」。

**为什么不改其它看起来像腐烂的**：
- `ST-003`（改密码）⇒ **已裁定「不纳入支持面」**（集成侧 2026-11-04）：① **不可逆**（改后旧密码即刻失效）
  ② **凭据面**（改密前提是能证明持有旧密码，agent 代操作天然无法证明；替人静默改密 = **账号接管面**）
  ⇒ 期望维持 `direct_reply`（如实告知 + 引导自助改），**语义未改**；依据已写进该用例的 `data_checks`，
  标题也从「能力已下线 / 本域只读」改成「凭据面 / 不可逆：黄金策**不代改**」（防止被当成待补能力再重开）；
- `CU-004`（更新客户资料）/ `PP-006`·`PP-007`·`PP-008`（加工项增改停）/ `CT-002`（建分类）：
  终版裁定这些**应当支持**，但今天的工具**仍是只读或未绑定**
  （`customer_manage` 只有 `{list, detail, list_tags, profile_view, value_view}`、
  `processing_item_manage` 不在 B 端工具集、`category_manage` 只有 `{tree}`）
  ⇒ 这是**产品侧能力缺口**，不是用例腐烂；按 #7035 边界「须改实现才能过的 ⇒ 另开单」。
  本包**不改用例**把它们洗绿，也不在用例里写「应支持」的期望（那会让用例恒红）。

### 3.1 OR 面的两条硬形态（本包**踩过一次**，CI 抓到的，照实登记）

`expectations` 的 OR 一旦写成 `dict` 形态（`- tool: "A(action=x) or B"`）就会被
`tests/unit_ci_workflows/test_eval_expectation_or_group.py` 判红 ——
**args 必须写进 `args` 字段，或整条改用字符串形态**（否则写身份 / args 值级校验会被扫描面漏掉）。
本包第一版正是写成 `dict` 形态 ⇒ CI 的 `ci workflow helper unit tests` 判红，已改成字符串形态。

另：OR 里的**裸分支**（后面不带 `(...)`）必须在同一判据的 `BARE_BRANCH_LEDGER` 里登记
（`interact` 已登记；`role_manage` **未**登记 ⇒ `HR-010` 必须写成 `role_manage(action=list)`）。
⇒ **动手前跑一次**：`python3 -m pytest tests/unit_ci_workflows/test_eval_expectation_or_group.py -q`。

## 4. 待裁定 —— **已由集成侧裁定（2026-11-04），逐条结论如下**

| # | 事项 | 裁定结论 | 落地 |
|---|---|---|---|
| 1 | `HR-002` / `HR-010` 的 un-skip | **现在就 un-skip**（keep-skip = 让刚接回的能力零断言覆盖；红了按产品缺陷开单，不重新 skip） | ✅ 已 un-skip |
| 2 | `ST-003` 改密码是否纳入支持面 | **不纳入**（不可逆 + 凭据面，§30.1 第 ③ 类） | ✅ 语义未改；依据写进 `data_checks` + 标题改准 |
| 3 | `CU-004` / `PP-006`~`PP-008` / `CT-002` 的产品侧缺口 | **由集成侧另开产品单承接**（工具没接，不是用例腐烂） | ✅ 本包**未改**这些用例、**未改**工具（射程外） |
| 4 | 21 处 `forbidden_tools` 绊线是否升格静态判据 | 未裁定 | ⏸ 保留并登记（§1.4 末） |

## 5. 边界（照实登记）

- 本文件**只判「期望是否可满足 / 是否与裁定冲突」**，不判「期望措辞是否优雅」，也不判
  「agent 现在的行为对不对」—— 后者要真实 LLM 评测，本包**未跑**（按 #4262「不自动验证」）。
- **没有重放过任何用例**：本包改的是**声明层**，不是行为层。`HR-002` / `HR-010` un-skip 后会在
  **下一次 B 端评测自然被跑到**（不是由本包触发）；若红了，按裁定**开产品单，不重新 skip**。
- 「0 条」全部是**现取读数**，不是「没人报过」。四个 A/C/D 面各自的**常驻判据**在 §1 里逐条点名；
  其中 §1.4 的五个**值域**面**只有 runner 运行期兜底、没有 L0 静态判据** —— 这是本文件
  **有意接受**的边界（新增平行判据会与 `scripts/case_coverage.py` 的单一实现点冲突）。
- 本文件不新增门禁、不改任何通过条件、不新增豁免。
