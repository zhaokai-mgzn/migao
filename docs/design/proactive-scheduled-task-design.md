# 米宝定时任务（用户「预约」）设计 —— 主动发现（族 1）的时间轴扩展

> issue [#6486](https://github.com/zhaokai-mgzn/migao/issues/6486) ｜ 2026-10-07 ｜ 状态：**设计待裁定**（阻塞点见 §七）
>
> 本文是「定时任务」能力的**判据源**：数据模型、触发口径、护栏、拆包顺序以本文为准；
> 与既有文档冲突时，以本文 + `docs/agent-feature-design.md` 族 1 的组合口径为准。

---

## 一、口径（先对齐，防混）

**「预约」在本设计中的含义 = 定时任务**：agent 在未来某时刻 / 某条件满足时，**主动产出一条提醒**。

⚠️ **不是**线下上门服务预约（量尺 / 安装 / 维修上门）—— 那是另一条业务线，与本设计无关，勿混。

**已定方向**（需求提出人 2026-10-07 逐轮选择，已固化进 issue #6486）：

| 维度 | 取值 | 含义 |
|---|---|---|
| 执行层次 | **L1 提醒型** | 到点只发提醒 / 通知；**不**重跑业务动作 |
| 落地端 | **B 端米宝** | 商家 / 员工侧；C 端后置（见 §九 包 3） |
| 架构定位 | **族 1 的时间轴扩展** | 扩展既有主动发现引擎，**不新建一套定时任务系统** |

---

## 二、现状盘点（真值均在 `origin/main`）

### 2.1 已经有的（**不重复造**）

| 能力 | 承载体（仓库相对全路径） | 本设计如何复用 |
|---|---|---|
| 主动发现规则引擎 | `backend/ai-agent-service/app/briefing/proactive.py` | 复用其**产出契约**与纪律，不复制扫描机制 |
| 分钟级调度范式 | `backend/admin-api/src/main/java/com/migao/admin/config/BriefingScheduler.java` | 照抄 `@Scheduled` + 幂等唯一键模式 |
| 同类扫描器先例 | `backend/admin-api/src/main/java/com/migao/admin/config/AutoCompleteShippedScanScheduler.java`、`backend/admin-api/src/main/java/com/migao/admin/config/AutoBatchDueScanScheduler.java` | 形态参照 |
| 通知投递表 | `backend/admin-api/src/main/resources/db/init/schema.sql` 的 `notifications` / `notification_rules` / `notification_templates` | **直接写入**，不建第二套投递 |
| 通知读端点 | `backend/admin-api/src/main/java/com/migao/admin/controller/NotificationController.java` | 复用，**不新增端点** |
| B 端通知面 | `frontend/admin-web/src/components/layout/NotificationBell.tsx`、`frontend/admin-web/src/app/(dashboard)/notifications/page.tsx` | 复用，**不改前端** |

**族 1 引擎已交付的规则**（`RULES`，6 条具名）：`below_cost_price` / `unshipped_overdue` / `low_stock` /
`repeat_returns` / `price_change_over` / `discount_over`。

**族 1 的三条铁约束**（本设计**逐条继承**，一条不破）：

1. **触发用规则，不用 LLM 自由发挥** —— 规则具名、阈值可配、判据可复算
2. **每条命中必带三件套** —— `criterion`（为什么给你看）/ `impact`（几条 / 多少钱）/ `action`（一键处置入口）
3. 🔴 **没有处置入口的不发** —— `action` 缺失的候选在装配期（`_assemble`）被丢弃，不靠调用方自觉

**族 1 已有的疲劳控制口径**（本设计同样继承）：未处置的不重推；每次扫描有条数上限并按紧急度排序。

> 📌 提出人已确认的关键判断：**「再补几个预置场景」价值不大** —— 因为「订单节点提醒」已被规则
> `unshipped_overdue` 覆盖、「定时摘要」已由每日简报交付。预置场景永远只有 6 条，而**用户委托是无限的**。

### 2.2 缺的（本设计要补的两个自由度）

| 维度 | 现状 | 目标 |
|---|---|---|
| **触发时刻** | 每日一次（`BriefingScheduler` 扫「到生成时刻且当日未生成」）；事件型规则按事件日期分组 | **任意时刻**（分钟级，`fire_at`） |
| **触发内容** | 6 条预置规则 | **用户委托的待办**（不限于预置规则） |

**这两格就是本设计的全部增量。**

---

## 三、定位：族 1 的时间轴扩展

`docs/agent-feature-design.md` §三 族 1 的定位原文（逐字）：

> 这是**唯一在结构上页面不可能有的能力**（页面只能等人来点），也是「智能」二字的唯一定义性来源。
> 且它是**只读的** —— 风险远低于批量写。

并已把「**跨域只读推理 + 对话外主动推送**」登记为补回顺序第 5 项（状态：待启动，**定性为非写操作**）。

**本设计 = 该第 5 项的落地形态**（第 4 项「草稿实体 + B 档」已由用户 2026-10-02 裁定不做）。

### 3.1 形态图

```
族 1 现有:   6 条具名规则 × 每日一次        → daily_findings() → 日报 / 通知
本设计扩展:  ├─ 时间轴:  fire_at 任意时刻
             └─ 内容轴:  用户委托的待办（结构化记录）
                        ↓
             同一个产出契约（三件套）+ 同一个投递面 + 同一套疲劳控制
```

### 3.2 与 `RuleSpec` 的关系：**共用产出契约，不共用扫描机制**

`RuleSpec` 是「给一份数据快照，产出确定性命中集合」的纯函数（协议见其 `detect` 签名与
`backend/ai-agent-service/app/briefing/proactive.py` 的模块 docstring）。**待办没有快照可扫**
（「3 天后提醒我跟进张先生」不是对 `orders` / `skus` 的扫描）。

⇒ **硬决策：待办不伪装成 `RuleSpec`。** 硬塞会把引擎的「可复算判据」语义搞脏。

⇒ 但**必须**逐条满足族 1 的产出契约（§2.1 三铁约束 + 疲劳控制），否则就是绕过既有纪律。

> 💡 时间轴的天然接缝：`RuleSpec.detect(snapshot, as_of, cfg)` **已有 `as_of` 时间基准** ——
> 现有 `as_of` = 扫描基准日；本设计的增量是让 `fire_at` 可以落在**任意时刻**，而非改变既有规则的判定。

---

## 四、设计原则（继承 + 一处加固）

| # | 原则 | 落点 |
|---|---|---|
| P1 | 触发确定性，**不靠 LLM 每次重新判断** | 待办是**结构化记录**（建单时定稿），到点只做投递，不再调 LLM 决策 |
| P2 | 每条提醒必带三件套 | 表结构强制 `criterion` + `action_label` + `action_url` |
| P3 | 🔴 **无处置入口的不发** | **加固：前移为「不建」** —— 三件套字段 `NOT NULL`，建不出来 |
| P4 | 疲劳控制 | 已投递不重推；每轮有条数上限 + 紧急度排序；可被用户 dismiss |
| P5 | 只读 | 到点**只**写 `notifications`；**不**执行任何业务写（见 §八） |
| P6 | 多租户隔离 | 每行带 `tenant_id`；扫描按租户 |
| P7 | 行业无关 | `task_type` 可配置，**不写死**窗帘语义（与「通用行业 SaaS」定位一致） |

> 🔴 **P3 是对族 1 的唯一加固建议**：族 1 在**运行期**丢弃无处置入口的候选（`_assemble`）；
> 本设计把这条约束**前移到建单期**（`NOT NULL`）。
> 理由：运行期丢弃会让「为什么这条没发」变成不可见的静默面；建单期拒绝则当场可归因。
> **这不是放松既有约束，是让同一条约束更早生效。**

---

## 五、数据模型

```sql
CREATE TABLE scheduled_tasks (
    id            VARCHAR(64) PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenants(id),
    task_type     VARCHAR(32) NOT NULL,   -- 可配置（P7）；不写死窗帘语义
    subject_type  VARCHAR(32),            -- employee / customer / order（可空 = 无主体）
    subject_id    VARCHAR(64),
    fire_at       TIMESTAMPTZ NOT NULL,   -- 触发时刻（时间轴自由度）
    -- 三件套（P2 / P3：NOT NULL ⇒ 无处置入口的待办建不出来）
    criterion     TEXT NOT NULL,          -- 为什么推给你（委托原话 / 规则判据）
    impact        JSONB NOT NULL DEFAULT '{}',  -- 影响面（几条 / 多少钱；待办类可为空对象）
    action_label  VARCHAR(64) NOT NULL,   -- 一键处置入口文案
    action_url    VARCHAR(255) NOT NULL,  -- 一键处置入口地址
    payload       JSONB DEFAULT '{}',
    source        VARCHAR(32) NOT NULL,   -- user(米宝委托) / system(规则派生)
    status        VARCHAR(32) NOT NULL DEFAULT 'pending',
                  -- pending / fired / cancelled / failed / dismissed
    dedup_key     VARCHAR(128),           -- 幂等键（见 §六.2）
    fired_at      TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    deleted       INTEGER DEFAULT 0,
    CONSTRAINT uq_scheduled_tasks_tenant_dedup UNIQUE (tenant_id, dedup_key)
);
```

**设计取舍（照实登记）**：

- **不塞进 `after_sales_tickets`**：那张表语义是售后工单（`ticket_type` = return / exchange / repair / complaint），
  且**无服务时段 / 无委托语义**；硬塞会污染工单统计口径。
- **不塞进 `daily_briefings`**：那张表的粒度是「租户 × 业务日」（唯一键 `(tenant_id, biz_date)`），
  与本设计的「任意时刻」正交。
- **新建一张轻量表**是本设计**唯一**的新增 schema 面；投递与前端**零新增**。

---

## 六、触发与投递

### 6.1 扫描器

```
ScheduledTaskScanner                     ← 形态照抄 BriefingScheduler
  @Scheduled(cron = "0 * * * * *")       每分钟
  → SELECT ... WHERE status='pending' AND fire_at <= now() AND deleted=0
  → 按租户分组 → 幂等判定（dedup_key）→ 条数上限 + 紧急度排序
  → 投递（写 notifications）
  → UPDATE status='fired', fired_at=now()
```

**继承族 1 的两条疲劳控制**（§2.1）：

- 已 `fired` / `cancelled` / `dismissed` ⇒ **不再投递**（`status` 过滤即落地）
- 每轮扫到 N 条以上 ⇒ 按紧急度排序取前 N；其余下轮再投（**不丢，只延后**）

### 6.2 幂等

`dedup_key` 形态：`<tenant_id>:<task_type>:<subject 标识>:<fire_at 归一化>`。

理由与 `daily_briefings` 的唯一键 `(tenant_id, biz_date)` 同族：**同一件事在同一个时间点只该提醒一次**。
扫描器可能因重启 / 重叠触发重跑 ⇒ 唯一键 + 幂等判定双保险（同 `BriefingScheduler` 的「生成前查重」口径）。

### 6.3 投递面（**复用，零新增**）

写入 `notifications`：`recipient_type='employee'`、`channel='internal'`、`status='sent'`。

⇒ 商家在 admin-web 的**未读铃铛**（`frontend/admin-web/src/components/layout/NotificationBell.tsx`）
与**通知中心**（`frontend/admin-web/src/app/(dashboard)/notifications/page.tsx`）看到 —— **前端零改动、端点零新增**。

> ⚠️ **诚实的取舍**：这样商家是在「通知中心」看到，**不是**米宝主动在对话里开口。
> 要真正「像人一样提起」，需往会话写 `sender_type='system'` 的消息 —— 那是**体验增强**，
> 归包 3（§九），**不塞进包 1**。

---

## 七、agent 入口与 A 档裁定（🔴 本设计的阻塞点）

### 7.1 需要什么

米宝要能听懂「3 天后提醒我跟进张先生」，就需要一个新工具（暂名 `scheduled_task_manage`，
actions = `create` / `list` / `cancel`）。

### 7.2 会撞哪一条门禁

`tests/unit_ci_workflows/test_mibao_b_end_readonly.py` **判据 1**：

> **B 端可达的工具并集里不得有白名单外的 `read_only != True` 工具**

而 `docs/wiki/agent-write-boundary.md` 的 A 档白名单 `A_TIER_REVERSIBLE_WRITES` **目前只有**
`product_update` / `sku_update`，且判据硬性要求它们「**绑在且仅绑在** `product` skill」+ 带
`requires_confirmation`。⇒ 新工具会**当场判红**。

### 7.3 AI 评估（供裁定参考，**非裁定本身**）

定时任务逐条对齐 A 档口径，且**比现有白名单里的「改价」更轻**（改价涉钱）：

| A 档要求 | 定时任务 | 依据 |
|---|---|---|
| 可逆 | ✅ | `cancel` 撤销；`dismissed` 不再投递 |
| 幂等 | ✅ | `dedup_key` 唯一键（§6.2） |
| 非对外承诺 | ✅ | 自己提醒自己，**不发给客户** |
| 不绕审核门禁 | ✅ | 不涉钱、不涉状态跃迁 |

### 7.4 为什么仍须人工裁定

扩白名单 = **权限边界放宽** ⇒ 命中铁律 12(c)① 与 §30.1 的「只把五类交人工」中的
**③ 权限 / 安全边界放宽**。⇒ **AI 不自行改判据**，必须人工裁定 + 留裁定留痕
（`docs/wiki/agent-write-boundary.md` §五「裁定记录」是留痕面）。

### 7.5 裁定请求（带选项与代价，按铁律 12 要求）

- **卡在哪一条**：A 档白名单 + 判据 1 的 skill 约束（§7.2）
- **要问的具体问题**：是否批准把「定时任务创建」纳入 A 档可逆写白名单，并把判据 1 的 skill 约束
  放宽到允许绑定在**提醒域**？
- **选项与代价**：
  - **批准** ⇒ 拿到「用户委托」这一真正的产品增量；代价 = 放开一处写面（合规成本），
    需同步改判据 + 留裁定留痕
  - **不批准** ⇒ 只能做系统派生提醒（价值有限，见 §2.1 的提出人判断）；米宝仍不能创建待办
- **不裁时的安全默认动作**：先落**包 1**（零裁定、零门禁冲突），包 2 待裁定

---

## 八、L1 / L2 分层与护栏

| | **L1 提醒型（本设计）** | L2 执行型（**本设计不做**） |
|---|---|---|
| 形态 | 到点发一条提醒 | 到点**唤起 agent 重新执行动作** |
| 实现 | 扫描 + 投递 | 还需重建会话上下文 + 跑工具链 |
| 风险 | 低 | **高** —— agent 在无人监督下执行，写操作谁负责？ |

🔴 **护栏（本设计硬约束）**：到点的动作**只读 + 通知**。任何写操作（下单 / 改价 / 发货 / 退款）
**必须回到会话里等人点确认**。

**理由**：与既有「门禁只证明确认过，不证明看过什么」（`docs/wiki/agent-write-boundary.md`
的涉钱面确认形态口径）同族 —— 无人监督的定时执行**结构上无法取得确认**。

**L2 的重启条件（本设计有意不做，登记在此防「被读成已解决」）**：需先有可复核的授权模型
（谁能预先授权 agent 在何时执行哪类写）+ 责任归属口径；在此之前 **L2 不开**。

---

## 九、拆包（按序交付；包 1 可立即开工）

| 包 | 内容 | 前置 | 文件面 |
|---|---|---|---|
| **包 1** | `scheduled_tasks` 表 + 迁移 + `ScheduledTaskScanner` + 投递到 `notifications` + 疲劳控制 + 定点判据 | **无裁定** | schema 迁移 + 一个新 Java 类族 + 判据 |
| **包 2** | `scheduled_task_manage` 工具 + skill 绑定 + A 档白名单裁定 + `test_mibao_b_end_readonly.py` 判据改造 | **§七 裁定** | ai-agent tools / skills + 判据 |
| **包 3** | 会话内主动消息（`sender_type='system'`）/ C 端微信订阅消息 | 依赖微信订阅消息集成 | 见下 |

**包 1 是包 2 的地基**（表与扫描器两条路共用），**不是二选一的替代方案**。

### 9.1 包 3 的硬约束（C 端）

🔴 **全仓目前无微信订阅消息（subscribeMessage）实现**（对 `backend/` / `frontend/` / `deploy/`
的零命中检索）。而微信小程序**不允许主动推送**，唯一合规通道是「订阅消息」，要求：

1. 用户在小程序内**亲手点授权按钮**（前端调 `wx.requestSubscribeMessage`，需模板 ID）
2. **一次性订阅 = 一次授权只能发一条**

⇒ **C 端「用户说'明天 9 点提醒我' → 到点主动推给他」这条链路，当前物理上走不通** ——
不是代码问题，是**平台规则**问题。这是包 3 的准入前置，**不是包 3 里的一个 TODO**。

---

## 十、边界与未决（照实登记）

**本设计明确接受 / 未决的缺口**：

1. **L1 天花板**：只提醒、不执行。想让 agent 真正「替你把事办了」需 L2（§八，重启条件已登记）。
2. **C 端缺口**：受微信订阅消息的平台规则约束（§9.1），本设计不承诺 C 端到点触达。
3. **「用户会不会真的在对话里设提醒」未经数据验证**：这是产品假设，**不是**已验证事实。
   建议的验证路径（零成本、零代码）：从既有会话面（`agent_sessions` / `agent_messages`）
   检索真实用户表达过的「提醒 / 到时候 / 记得 / 过几天」类诉求，统计分布与当前 AI 的失败回答 ——
   **该验证不在本设计的交付范围内**，登记为立项前置建议。
4. **投递形态的体感落差**：包 1 走通知中心（§6.3），不是米宝主动开口 —— 登记为包 3 的动机之一。
5. **本设计不碰**既有 6 条规则的判定逻辑（`proactive.py` 的 `RULES` 一字不改）。

**未决（需在包 1 开工前定）**：

- `impact` 字段对待办类（`source='user'`）的取值口径：空对象 `{}` 是否可接受，
  还是必须有「影响面 = 1 条待办」这类最小非空值？（倾向后者，与 P2「必带三件套」一致）
- 紧急度排序的判据：`fire_at` 升序？还是引入显式 `priority`？（倾向前者，**不新增字段** —— 最少代码阶梯）

---

## 十一、引用（仓库相对全路径；**不写行号**）

| 对象 | 路径 / 符号 |
|---|---|
| 主动发现引擎 | `backend/ai-agent-service/app/briefing/proactive.py`（`RULES` / `RuleSpec` / `_assemble` / `daily_findings` / `proactive_status`） |
| 调度范式 | `backend/admin-api/src/main/java/com/migao/admin/config/BriefingScheduler.java` |
| 通知只读工具 | `backend/ai-agent-service/app/tools/notification_manage.py`（`VALID_ACTIONS`） |
| 通知读端点 | `backend/admin-api/src/main/java/com/migao/admin/controller/NotificationController.java` |
| 通知表 | `backend/admin-api/src/main/resources/db/init/schema.sql`（`notifications` / `notification_rules` / `notification_templates` / `daily_briefings`） |
| 写边界（A 档白名单 + 裁定记录） | `docs/wiki/agent-write-boundary.md` |
| B 端只读判据 | `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` |
| 能力地图（族 1 / 负面清单） | `docs/agent-feature-design.md` |
| B 端通知面 | `frontend/admin-web/src/components/layout/NotificationBell.tsx`、`frontend/admin-web/src/app/(dashboard)/notifications/page.tsx` |
