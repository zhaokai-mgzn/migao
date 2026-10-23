# case_ids: MC-021
"""**B 端黄金策能力边界**的机械判据（issue #7040 重锚；沿革 = issue #5247 / #5302 / #5303）。

## 🔴 本文件的第三次重锚：判据换了对象（2026-10-16 用户裁定「能力边界 终版」）

权威口径 = **issue #5247 的最新评论「能力边界 终版」**（用户三条追加裁定后闭合），逐字要点：

> 「对比商家后台观星台的功能，不支持创建商品和订单，**其他单据类的也不要支持创建**，
> **只允许变更和查下分析类**」· 非单据对象创建「**都支持（只要不是单据）**」·
> 删除/停用「**不包含（只能改，不能删）**」· 射程「**只在 B 端（黄金策）**」

| 类别 | 支持面 |
|---|---|
| 创建**商品** / **订单** / **其他单据类** | ❌ 不支持 |
| 创建**非单据对象**（员工/角色/客户/供应商/标签/分类/加工项/定时提醒） | ✅ 必须支持 |
| **变更**（改已存在对象/单据：标记已读、改状态、改价…） | ✅ 必须支持 |
| **删除 / 停用 / 作废**（不可逆） | ❌ 不支持 |
| 查询 / 分析 / 导航 | ✅ 支持 |

**旧判据为什么必须换**（不是"顺手刷新"，是**判据与被判对象脱节**）：
本文件第二版判「B 端可达工具并集里不得有白名单外的 `read_only != True` 工具」，其文档头
逐字配套 2026-09-23 的旧口径「写工具处置 = **收窄为只读工具**」⇒ **任何一次「把变更接回 B 端」
都会被它判红**，而接回变更正是新裁定**要求**的行为 ⇒ 判据会把正确实现判成回归（假红）。
第三版判据按新口径换成**对象**：

1. **零「单据类创建」** —— B 端可达工具一个都不许是「创建单据」的工具（具名禁绑 +
   结构面：向单据**集合**路径发 `POST` = 建单）；
2. **零「删除 / 停用 / 作废」action** —— 结构面：发 `DELETE`（`/revert` 类撤销除外）
   或 action 名命中不可逆闭词表 ⇒ 红；
3. **每个非只读工具必须有确认门禁** —— 非只读 action 必须走 `requires_confirmation`
   （**保留原确认门禁**：接回变更 ≠ 拆门禁）；
4. **变更工具必须真的可达** —— 正向判据（旧判据只能表达「不许有写工具」，于是「变更整体
   不可达」也全绿；那正是 issue #7040 的起点）；
5. **A 档可逆写**（改价 / 定时提醒）的补回域与门禁**逐条照旧钉住**。

## 判据清单（每条都有**注入式红证**，见文件末尾 `JUDGEMENTS` × `_injections()`）

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | 单据类创建工具禁绑（具名）+ A 档工具的门禁/补回域 | `order_create` 绑回 B 端 / A 档工具摘掉确认门禁 / 补回域漂移 / 悬空绑定 |
| 2 | 具名写能力工具零绑定（`WRITE_TOOLS_UNBOUND_FROM_B_END` 逐条） | 具名清单里的工具被重新绑定 |
| 3 | B 端可达工具的 action 面：零建单 / 零删除·停用·作废（结构面 + 闭词表） | 向单据集合 `POST` / 发 `DELETE` / 暴露 `delete`·`toggle_status` |
| 4 | 能力文案不谎报（闭词表 + 句级否定过滤） | `mibao.py` 的非否定句里承诺创建/删除类能力 |
| 5 | 共享工具与 C 端零改动 | 删掉共享工具类 / 摘掉它的 C 端绑定 |
| 6 | A 档 + **变更**能力「文案 ↔ 绑定」双向一致 | 文案承诺而工具未绑 / 工具已绑而文案不提 |
| 7 | 声明了 mibao persona 的每个 skill（含已解绑孤儿）的工具面受控 | 孤儿 skill 工具改回非只读 / 暴露不可逆动作 / 绑未登记的写工具 |
| 8 | **非只读 ⇒ 必须带确认门禁**（新口径核心：变更可达但不得无确认执行） | 非只读 action 却无 `requires_confirmation`·`destructive` |
| 9 | 可达面的汇总口径：零建单、零不可逆动作 | 见判据 3 的两条结构面（9 是**可达并集**口径，独立红证） |
| 12 | **用例面**：`expectations` 要求 persona **不可达**的工具（在飞的用例期望一个边界外的动作） | 用例声明 `expectations: [order_create]` / `[product_manage]` ⇒ 具名报出「文件::用例 id::工具::原句」 |
| ⊕ | `test_change_tools_actually_reachable`：变更工具**必须真的可达** | 把 `notification` 从 `skill_names` 解绑 ⇒ 红 |

> 判据 8 / 9 与判据 1 / 3 的差别是**射程**：1 / 3 判「工具本身是不是禁形态」，8 / 9 判
> 「**可达**工具面里的实际形态」—— 两者都要求「注入即红」，各自带独立红证。

## 本次重锚厂的**配套改动**（同一 PR，缺一不可）

- `WRITE_TOOLS_UNBOUND_FROM_B_END` **移出** `notification_manage`（它的 `delete` / `create`
  仍未接线，但 `mark_read` / `read_all` 属**变更** ⇒ 留在表里等于「变更永远回不来」）；
- 新增 `CHANGE_TOOLS_REQUIRED_ON_B_END`（正向表）+ `CHANGE_CLAIM_WORDS`（判据 6b 的文案面）；
- `FORBIDDEN_CAPABILITY_PHRASES` **不移入**「标记已读」类词（它们已是真实能力；
  说了做不到由判据 6b 反向钉住）。

## 明确的边界（**不要**把本判据读成覆盖面更大）

- 本判据**只读源码文本 / 工具对象**（零依赖：仅标准库 `ast` + `re`），不连库、不跑 LLM、
  不读端点。端点存在性与权限码一致性由 `tests/unit_ci_workflows/test_agent_permission_parity.py`
  （#5246）与各工具自己的单测负责。
- **不判提示词里的行为指令**（那些要靠真实 LLM 评测，按 `migao-dev-flow` §13 默认不派发）；
  只判「**工具面 + 绑定面 + 能力文案 + 确认门禁**」这些静态可判的事实。
- 「单据类创建」的分类口径是**启发式**（见 `_endpoint_calls`）：只覆盖代码里**字面出现**的
  HTTP 方法与路径（模块级常量 + 调用点两轮扫描）；动态拼接的路径不在射程内（如实登记）。
"""

from __future__ import annotations

import ast
import sys
import functools
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SERVICE = REPO_ROOT / "backend" / "ai-agent-service"
TOOLS_DIR = AI_SERVICE / "app" / "tools"
SKILLS_DIR = AI_SERVICE / "app" / "graph" / "skills"
AGENTS_DIR = AI_SERVICE / "app" / "agents" / "agents"
CASES_DIR = REPO_ROOT / ".github" / "cases"

#: 用例源的解析器 = 仓内 `yaml_light`（**纯标准库**，与本判据「零依赖」的口径一致；
#: 直接 import `.github/render_cases.py` 会连带拉进它的兄弟模块，故只取其解析器这一份实现）。
sys.path.insert(0, str(REPO_ROOT / ".github"))
from yaml_light import load as _yaml_load_text  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# 一、新口径的真值表（**显式登记**，未登记即红）
# ══════════════════════════════════════════════════════════════════════════════

#: **单据类创建工具禁绑**（新裁定：商品 / 订单 / 其他单据类都不得创建）。判据 1 的具名面。
#: ⚠️ 这是**活表**：谁要把某个单据类创建工具接回 B 端，必须先在用户裁定面上登记
#: （改本表 = 改产品能力边界，评审面必须看见）。
DOCUMENT_CREATION_TOOLS_DENIED: dict[str, str] = {
    "order_create": "创建订单（用户裁定逐字点名不支持）",
    "product_manage": "创建商品（`create` action；用户裁定逐字点名不支持）",
    "aftersale_create": "创建售后工单（单据类；用户裁定「其他单据类的也不要支持创建」）",
    "processing_order_generate": "生成加工单（单据类创建）",
    "processing_order_update": "加工单写面（创建 / 状态流转；B 端未接线）",
}

#: **单据类资源根**（结构面判据的路径口径）。向这些**集合路径**发 `POST` = 建一张单据。
#: 口径 = 用户裁定里逐字点到的单据族（加工单 / 发货单 / 入库单 / 采购单 / 售后工单 / 质检单）
#: + 商品与订单两个被点名者。**刻意收窄**：`/customers`（客户，非单据对象）等**不在**表里。
DOCUMENT_ROOT_PATTERNS: tuple[str, ...] = (
    "/orders",             # 订单（含 /agent/orders）
    "/products",           # 商品（含 /agent/products）
    "/processing-orders",  # 加工单
    "/shipments",          # 发货单
    "/inbound-orders",     # 入库单
    "/purchase-orders",    # 采购单
    "/after-sales",        # 售后工单
    "/quality-checks",     # 质检单
)

#: 「删除 / 停用 / 作废」（不可逆）—— **action 名闭词表**（结构面兜底）。
IRREVERSIBLE_ACTION_WORDS: frozenset = frozenset({
    "delete", "delete_item", "delete_category", "delete_task", "delete_notification",
    "delete_role", "delete_user", "delete_tag", "delete_product",
    "toggle_status", "toggle_item_status", "toggle_product_status",
    "void", "deactivate", "disable", "abolish", "purge", "remove",
})

#: `/revert` 类**撤销**端点：把批量写改回去的**可逆**动作，按裁定**不是**删除
#: （`product_batch_update(action=revert)` 的存在就是这条口径的实例）。
REVERT_PATH_MARKERS: tuple[str, ...] = ("/revert", "/rollback", "/undo")

#: 🔴 **「撤销」与「删除」的分界**（`DELETE` 方法的**唯一**例外面，逐条具名登记）。
#: 口径 = `DELETE` 把「**本次委托产生的、可重建的**对象」收回 —— 它不销毁既有业务数据：
#: `scheduled_task_manage(action=cancel)` 删的是**自己刚建的提醒待办**，商家再委托一次即恢复
#: ⇒ 按裁定属**变更**（用户 2026-10-07 已裁定入 A 档可逆写白名单，issue #6486 包 2）。
#: 反面形态（**必须红**）：`processing_item_manage` 的 `delete_item` 删的是**既有业务对象**
#: （加工项，软删 = 记录置 `deleted=1`）—— 那才是「不可逆删除」。
#: ⚠️ 这是**活表**：加一条 = 允许某把工具用 `DELETE` ⇒ 评审面必须看见（判据 3 的
#: 「DELETE 例外」子判据会核「该工具的 action 面里不得出现 `delete*`」）。
CANCEL_DELETE_ALLOWLIST: dict[str, str] = {
    "scheduled_task_manage": (
        "`cancel` = 收回**本次委托**产生的提醒待办（可重建 ⇒ 可逆），"
        "A 档可逆写白名单成员（issue #6486 包 2）"
    ),
}

#: B 端**不得绑定**的写能力工具（具名清单）。
#: ⚠️ 2026-09-24 改判（issue #5303）：`product_update` / `sku_update` 已移出（A 档白名单）。
#: ⚠️ 2026-10-16 改判（issue #7040）：**`notification_manage` 已移出** —— 它的
#: `mark_read` / `read_all` 属**变更**（裁定要求支持，#7040 接回）；留在表里的后果是
#: 「变更永远回不来」（判据把正确实现判成回归）。移出 ≠ 放宽：它的可达性 / 确认门禁 /
#: 文案一致性由判据 3、6b、8、9 与 `test_change_tools_actually_reachable` 逐条钉住，
#: 且**本表其余条目一条都不许动**（`problems_write_tools_bound` 的红证仍在跑）。
WRITE_TOOLS_UNBOUND_FROM_B_END: dict[str, str] = {
    "order_create": "建单（与 C 端共享：只解绑 B 端，文件与 C 端行为一字不动）",
    "order_manage": "改订单状态/发货/退款（单据写面；B 端未接线）",
    "product_manage": "建品/上下架（商品创建 = 严禁）",
    "processing_item_manage": "加工项增删改（含 `delete_item` = 不可逆 ⇒ 与「只能改不能删」冲突）",
    "processing_order_generate": "生成加工单（单据类创建）",
    "processing_order_update": "加工单状态流转（单据写面）",
    "settings_manage": "系统设置（用户裁定：不进 B 端对话面）",
    "validate_input": "写操作前置校验（B 端写面按新口径重构 ⇒ 绑它只会引入「校验自己执行不了的写工具」= A5 死角）",
}

#: 🔴 **变更工具必须接回 B 端**（新口径的**正向**要求：变更 ✅ 必须支持）。
#: 这是本判据从「白名单制」换成「**禁绑制 + 变更可达**」的关键一格：
#: 旧判据只能表达"不许有写工具"，新口径要求"变更类写工具**应当在**"。
CHANGE_TOOLS_REQUIRED_ON_B_END: dict[str, str] = {
    "notification_manage": (
        "通知标记已读（变更，issue #7040 接线）：`mark_read` / `read_all` —— 端点 "
        "`PUT /api/admin/notifications/{id}/read` · `PUT /api/admin/notifications/read-all` 已核存在"
    ),
}

#: **A 档可逆写白名单**（issue #5303 / #5314 / #6486）：B 端**允许**存在的 `read_only=False` 工具。
#: 入册判据（缺一不可）：`WRITE|IDEMPOTENT`（重放安全）+ 可逆 + 非对外承诺 + 不绕过审核门禁。
#: ⚠️ 新增成员 = 改产品能力边界，必须显式改判本常量（判据 1 会立刻红）。
A_TIER_REVERSIBLE_WRITES: frozenset = frozenset({
    "product_update",        # 商品级统一定价（PATCH /api/admin/agent/products/{id} → basePrice）
    "sku_update",            # 单规格调价（PATCH …/skus/price）
    "product_batch_update",  # 批量改价 / 批量库存调整 + revert 撤销（issue #5314）
    "scheduled_task_manage",  # 建 / 取消「到点提醒」待办（issue #6486 包 2）
    # 算料配置的**改单键/多键**（PUT /api/admin/production/craft-calc-config；只覆盖点名的键）
    # —— issue #7514，用户 2026-10-23 裁定「黄金策要能支持算料配置的创建和变更」，
    # 语义 = 改单键/多键 + 逐键前后对照（不做整份编辑、不做重置默认）。
    "craft_calc_config_update",
})

#: A 档工具 → **必须**绑在的 skill（补回域**逐条**钉住；漂移到别的域即红）。
A_TIER_SKILLS: dict[str, str] = {
    "product_update": "product",
    "sku_update": "product",
    "product_batch_update": "product",
    "scheduled_task_manage": "reminder",
    # issue #7514：「算料参数怎么设置」没有专属意图、低置信时落 general 兜底（会话
    # sess_5742c5b5c43a48b1 的实测路由）⇒ 补回域 = general，**不得**绑 knowledge / product。
    "craft_calc_config_update": "general",
}

#: 写 action **闭词表**（判据 3 / 7 的兜底）：action 名命中即视为写能力。
#: 口径 = 「动词表达**改数据**」，与 `read_only_actions` 的声明**无关** ——
#: 否则把写 action 挪进 `read_only_actions` 就能洗白（那正是本表要拦的形态）。
WRITE_ACTION_WORDS = frozenset({
    "create", "update", "delete", "adjust", "add_tag", "remove_tag", "create_tag",
    "update_tag", "delete_tag", "assign", "end", "toggle_status", "reset_password",
    "generate", "cancel", "refund", "confirm_payment", "update_status",
    "update_logistics", "create_transaction", "create_processing_item", "update_item",
    "delete_item", "create_role", "update_role", "delete_role", "create_user",
    "update_user", "delete_user", "create_category", "update_category", "delete_category",
    "create_ticket", "create_order", "mark_read", "create_notification",
    "update_settings", "update_ai_config", "change_password", "read_all",
})

#: 能力文案里的**写能力承诺词**（判据 4 闭词表）。命中即「AI 说得到、做不到」。
#: ⚠️ 2026-09-24 改判（#5303）：`改价` / `调价` 已移出（A 档白名单能力，真实具备）。
#: ⚠️ 2026-10-16 改判（#7040）：`标记已读` 类词**不得入表** —— 它们是 `notification_manage`
#: 的真实能力（变更），留着会把**正确的如实告知**判成谎报（假红）。它们**不是被豁免**：
#: 文案说了而工具没绑 = 谎报，由判据 6b 的 `CHANGE_CLAIM_WORDS` 反向钉住。
FORBIDDEN_CAPABILITY_PHRASES = (
    "创建商品", "创建订单", "创建工单", "创建员工", "创建角色", "创建分类", "创建加工项",
    "建单", "建品", "下单", "改状态", "修改订单", "取消订单", "退款",
    "调库存", "调整库存", "上下架", "删除商品", "删除员工", "删除角色", "重置密码",
    "商品管理", "订单处理", "库存管理", "通知管理", "修改配置", "系统配置",
    "图片识别", "创建商品记录",
)

#: A 档写能力在能力文案里的**承诺词**（判据 6 的扫描面）—— **按域**。
A_TIER_CLAIM_WORDS: dict[str, tuple[str, ...]] = {
    "product": ("改价", "调价"),
    "reminder": ("提醒",),
    # issue #7514：算料配置的变更是**本域唯一**的写能力 —— greeting / capabilities 必须
    # 明说能改（说了做不到由本条反向钉住；做不到却不说 = 能力接回了没人知道）。
    "general": ("算料配置",),
}

#: **变更**能力在能力文案里的**承诺词**（判据 6b 的扫描面）—— 按工具。
#: 与判据 4 的闭词表互补：判据 4 管"别承诺做不到的"，判据 6b 管"做到了别不吭声"
#: （接回了变更却在 greeting/capabilities 里一个字不提 ⇒ 商家不知道能找黄金策办 = 白接）。
CHANGE_CLAIM_WORDS: dict[str, tuple[str, ...]] = {
    "notification_manage": ("标记已读", "标为已读", "全部已读"),
}

#: 与 C 端共享的工具（判据 5）：必须仍存在、且仍被 C 端 skill 绑定。
SHARED_WITH_C_END = (
    "order_create", "validate_input", "interact", "knowledge_search",
    "processing_item_query", "product_search", "product_detail", "production_progress_query",
)

#: 🔴 判据 11 的**正向工具名单**（prompt 措辞与代码事实一致性）。
#: 口径 = 本单**接回**的能力所对应的工具（`CHANGE_TOOLS_REQUIRED_ON_B_END`）+ A 档可逆写。
#: 它们在 prompt 文本里**不得与否定句共现**（同句出现 = 提示词还在教 agent 拒绝一个已支持的能力）。
#: 为什么只列**接回的**：prompt 语料里存量否定句指向的都是**确实不支持**的能力（创建 / 删除），
#: 全量扫描会把那些**正确**的如实告知判成假红（§17.3「判据被自己的文案喂红」）。
PROMPT_COHERENCE_TOOLS: tuple[str, ...] = tuple(sorted(
    set(CHANGE_TOOLS_REQUIRED_ON_B_END) | A_TIER_REVERSIBLE_WRITES
))

#: 判据 11 扫描的 prompt 语料（模型可见的域提示词 + 共享规则 + 通用助手兜底）。
PROMPT_CORPUS_FILES: tuple[str, ...] = (
    "PROMPT-rules.md",
    # ⚠️ EXAMPLES-*（L5 few-shot）**同属注入面**：本仓实测「缝在示例里的旧口径」比 prompt 正文
    # 更容易漏改（`EXAMPLES-product.md` 曾写「建品/改价…都不在能力内」，与 `prompts/product.md`
    # 的「唯一可写的动作是改价」**直接矛盾**，而没有任何判据会红）⇒ 一并进扫描面。
    "EXAMPLES-general.md",
    "EXAMPLES-order.md",
    "EXAMPLES-product.md",
    "EXAMPLES-aftersales.md",
    "EXAMPLES-customer.md",
    "EXAMPLES-staff.md",
    "EXAMPLES-settings.md",
    "prompts/general.md",
    "prompts/order.md",
    "prompts/product.md",
    "prompts/aftersales.md",
    "prompts/customer.md",
    "prompts/staff.md",
    "prompts/data.md",
    "prompts/settings.md",
    "base/principles.md",
)


# ══════════════════════════════════════════════════════════════════════════════
# 二、读源（注入式红证 = 替换这里的某一项文本后重建 World）
# ══════════════════════════════════════════════════════════════════════════════


def _source_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(TOOLS_DIR.glob("*.py")):
        if p.name in ("__init__.py", "base.py", "registry.py", "langchain_adapter.py"):
            continue
        out[f"tool:{p.name}"] = p.read_text(encoding="utf8")
    for p in sorted(SKILLS_DIR.glob("*.py")):
        out[f"skill:{p.name}"] = p.read_text(encoding="utf8")
    for name in ("mibao", "xiaobu"):
        out[f"agent:{name}"] = (AGENTS_DIR / f"{name}.py").read_text(encoding="utf8")
    refs = SKILLS_DIR / "references"
    for rel in PROMPT_CORPUS_FILES:
        path = refs / rel
        if path.exists():
            out[f"prompt:{rel}"] = path.read_text(encoding="utf8")
    # 用例面（判据 12）：`.github/cases/*.yml` 的**原文**。用 `rglob`（不 import
    # `render_cases.load_case_dicts`）——后者会连带拉进 `cases_yaml` 等兄弟模块，
    # 与本判据「零依赖、只读文本」的口径不一致（真库漏加载会被判据 12 的 fail-closed 兜住）。
    if CASES_DIR.is_dir():
        for p in sorted(CASES_DIR.rglob("*.yml")):
            out[f"case:{p.relative_to(CASES_DIR)}"] = p.read_text(encoding="utf8")
    return out


def _skill_source_keys() -> dict[str, str]:
    """`skill 名 → 源键`（`skill:<文件名>`）——**现取**，不按命名规律拼。

    为什么不能拼 `<skill>_skill.py`（issue #7514 实测）：兜底域的 skill 文件叫
    `general_agent.py`（历史命名），拼出来的键根本不存在 ⇒ 判据 6 的注入当场 KeyError、
    整条红证链断掉。文件名的命名规律**不是本判据要表达的事实**，判据要的是
    「把这个域绑定的 A 档工具解绑」⇒ 按源文本里的 `SkillConfig(name="<domain>")` 解析。
    """

    out: dict[str, str] = {}
    for key, text in _source_map().items():
        if not key.startswith("skill:"):
            continue
        for matched in re.finditer(r'SkillConfig\(\s*name="([a-z_]+)"', text):
            out.setdefault(matched.group(1), key)
    return out


def _skill_source_key(skill: str) -> str:
    """`domain` → 它的源键；解析不出来才回退旧口径（回退不静默：注入会因锚点失配而红）。"""
    return _skill_source_keys().get(skill, f"skill:{skill}_skill.py")


def _literal(node: ast.AST):
    """字面量取值；`frozenset({'a','b'})` / `set()` / `tuple()` 这类包装自动拆一层。"""
    if isinstance(node, ast.Call):
        fn = getattr(node.func, "id", None)
        if fn in ("frozenset", "set", "tuple", "list"):
            if not node.args:
                return []
            return _literal(node.args[0])
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _module_literal(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id == name:
                return _literal(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
                return _literal(node.value)
    return None


def _class_literal(node: ast.ClassDef, attr: str, module_consts: dict | None = None):
    """类属性取值；**名字引用会被解析**（`read_only_actions = READ_ONLY_ACTIONS`）。

    ⚠️ 仓内既有形态把只读 action 集写成**模块级常量**再在类里按名字引用
    （`app/tools/notification_manage.py` / `scheduled_task_manage.py`）——
    不解析这层引用会静默拿到 `None`，让依赖它的判据子面变成**空断言**（实测踩到）。
    """
    for st in node.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1:
            tgt = st.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id == attr:
                val = _literal(st.value)
                if val is None and isinstance(st.value, ast.Name) and module_consts:
                    return module_consts.get(st.value.id)
                return val
    return None


#: 源码里 admin-api 客户端的方法名 → HTTP 方法（`AdminApiClient` 的公开面）。
_CLIENT_METHODS = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "delete": "DELETE"}


def _endpoint_calls(text: str) -> list[tuple[str, str]]:
    """`(HTTP 方法, 路径字面量)` —— 从**模块级字符串常量**与**调用点**两处现算。

    ⚠️ **分类口径是启发式**（`/revert` 那类撤销端点按裁定不算删除、动态拼接路径不在射程内）：
    它要判的是「**这个工具会不会去建单据 / 删东西**」，判的是代码里**字面出现**的调用形态。

    两轮扫描缺一不可（实证踩过其一就漏）：路径多数写成模块级常量
    （`LIST_ENDPOINT = "..."`）再进 `client.get(LIST_ENDPOINT)` —— 只看调用点会拿到 `Name`
    节点、一个路径都取不到，判据就变成**空断言**（看着绿、注入也不红）。
    """
    tree = ast.parse(text)

    const_strs: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            val = _literal(node.value)
            if isinstance(tgt, ast.Name) and isinstance(val, str):
                const_strs[tgt.id] = val
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            val = _literal(node.value) if node.value is not None else None
            if isinstance(val, str):
                const_strs[node.target.id] = val

    def _path_of(arg: ast.AST) -> str | None:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.Name):
            return const_strs.get(arg.id)
        # f-string：取它的字面量前缀（`f"/api/admin/orders/{oid}"` ⇒ "/api/admin/orders/"）
        if isinstance(arg, ast.JoinedStr):
            head = arg.values[0] if arg.values else None
            if isinstance(head, ast.Constant) and isinstance(head.value, str):
                return head.value
        return None

    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # `client.post(...)` / `get_admin_api_client().post(...)` / `self.client.delete(...)`
        if isinstance(fn, ast.Attribute) and fn.attr in _CLIENT_METHODS and node.args:
            path = _path_of(node.args[0])
            if path is not None:
                out.append((_CLIENT_METHODS[fn.attr], path))
        # 关键字形态：`client._request("POST", path)` 之类
        elif isinstance(fn, ast.Attribute) and fn.attr == "_request" and node.args:
            m = _literal(node.args[0])
            path = _path_of(node.args[1]) if len(node.args) > 1 else None
            if isinstance(m, str) and path is not None:
                out.append((m.upper(), path))
    return out


def _matches_document_root(path: str) -> bool:
    """路径是否落在**单据类资源**上（`/api/admin/agent/orders` / `…/orders/{id}` 都算）。"""
    stripped = path.split("?")[0]
    for root in DOCUMENT_ROOT_PATTERNS:
        if stripped == root or stripped.endswith(root):
            return True
        if f"{root}/" in stripped:
            return True
    return False


def _is_revert(path: str) -> bool:
    return any(marker in path for marker in REVERT_PATH_MARKERS)


def parse_tools(sources: dict[str, str]) -> dict[str, dict]:
    """`app/tools/*.py` → {tool_name: {read_only, ..., calls, irreversible_actions, file}}。"""
    out: dict[str, dict] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("tool:"):
            continue
        tree = ast.parse(text)
        valid = _module_literal(tree, "VALID_ACTIONS")
        # 模块级 Name 常量（`READ_ONLY_ACTIONS = frozenset({...})`）—— 供类属性引用解析
        module_consts: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name):
                    v = _literal(node.value)
                    if v is not None:
                        module_consts[tgt.id] = v
        calls = _endpoint_calls(text)
        # 结构面：向单据集合发 POST / 对任何路径发 DELETE（撤销端点除外）
        doc_creates = sorted({
            path for method, path in calls
            if method == "POST" and _matches_document_root(path)
        })
        hard_deletes = sorted({
            path for method, path in calls
            if method == "DELETE" and not _is_revert(path)
        })
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = _class_literal(node, "name")
            if not isinstance(name, str):
                continue
            ro = _class_literal(node, "read_only", module_consts)
            roa = _class_literal(node, "read_only_actions", module_consts)
            rc = _class_literal(node, "requires_confirmation", module_consts)
            actions = None if valid is None else [str(a) for a in valid]
            # 「撤销」面：`DELETE` 的**唯一**例外 = `CANCEL_DELETE_ALLOWLIST` 里的工具，
            # 且它的 action 面**不得**出现 `delete*`（否则那是真删除，不是撤销）。
            irreversible_deletes = (
                [] if name in CANCEL_DELETE_ALLOWLIST else hard_deletes
            )
            out[name] = {
                "file": f"app/tools/{key.split(':', 1)[1]}",
                "read_only": True if ro is None else bool(ro),
                "declared_read_only": ro is not None,
                "requires_confirmation": bool(rc) if rc is not None else False,
                "valid_actions": actions,
                "read_only_actions": None if roa is None else [str(a) for a in roa],
                "doc_creates": doc_creates,
                "hard_deletes": hard_deletes,
                "irreversible_deletes": irreversible_deletes,
                "write_actions": sorted(set(actions or []) & WRITE_ACTION_WORDS),
                "irreversible_actions": sorted(set(actions or []) & IRREVERSIBLE_ACTION_WORDS),
            }
    assert out, "工具解析出 0 个声明 ⇒ 判据会空跑（fail-closed）"
    return out


def parse_skills(sources: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """skill 名 → 工具清单（`SkillConfig(name=...)` + 同模块的 `*_TOOLS`）。"""
    out: dict[str, tuple[str, ...]] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("skill:"):
            continue
        tree = ast.parse(text)
        name = None
        tools: tuple[str, ...] = ()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = getattr(node.func, "id", None)
                if fn in ("SkillConfig", "create_skill_config"):
                    for kw in node.keywords:
                        if kw.arg == "name":
                            v = _literal(kw.value)
                            if isinstance(v, str):
                                name = v
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name) and re.fullmatch(r"[A-Z_]+_TOOLS", tgt.id):
                    v = _literal(node.value)
                    if isinstance(v, list) and all(isinstance(x, str) for x in v):
                        tools = tuple(v)
                        break
        if name and tools:
            out[name] = tools
    assert len(out) >= 12, f"skill 绑定解析出 {len(out)} 个 ⇒ 判据会空跑（fail-closed）：{sorted(out)}"
    return out


def parse_skill_personas(sources: dict[str, str]) -> dict[str, frozenset[str]]:
    """skill 名 → 它声明的 persona 集（`SkillConfig.system_prompts` 的键）。

    判据 7 的射程来源：**persona 家族**（`system_prompts` 的键）—— 与运行期的只读共享
    （`tests/test_readonly_cross_domain_sharing.py`）同一口径。用「声明」而不是「可达」，
    是为了让「把 skill 从 `skill_names` 解绑」不能把它的工具移出写面判据（#5302）。
    """
    out: dict[str, frozenset[str]] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("skill:"):
            continue
        tree = ast.parse(text)
        name = None
        personas: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) not in ("SkillConfig", "create_skill_config"):
                continue
            for kw in node.keywords:
                if kw.arg == "name":
                    v = _literal(kw.value)
                    if isinstance(v, str):
                        name = v
                elif kw.arg == "system_prompts":
                    keys = getattr(kw.value, "keys", None) or []
                    for k in keys:
                        pk = _literal(k)
                        if isinstance(pk, str):
                            personas.add(pk)
        if name:
            out[name] = frozenset(personas)
    assert out, "skill persona 解析出 0 个 ⇒ 判据 7 会空跑（fail-closed）"
    return out


def parse_agent(sources: dict[str, str], agent: str) -> tuple[frozenset[str], str | None]:
    """某人格的 `skill_names` + `fallback_skill`（用 AST 读，避免注释里的引号被当成 skill 名）。"""
    tree = ast.parse(sources[f"agent:{agent}"])
    names: list[str] = []
    fallback: str | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "AgentConfig":
            continue
        for kw in node.keywords:
            if kw.arg == "skill_names":
                v = _literal(kw.value)
                if isinstance(v, list):
                    names = [str(x) for x in v]
            elif kw.arg == "fallback_skill":
                v = _literal(kw.value)
                if isinstance(v, str):
                    fallback = v
    assert names, f"`{agent}` 的 `skill_names` 解析为空 ⇒ 判据 fail-closed"
    return frozenset(names), fallback


def parse_agent_direct_replies(sources: dict[str, str], agent: str) -> dict[str, str]:
    """`AgentConfig.greeting` + `direct_replies` 的 键→文案（判据 4 / 6 / 6b 的扫描面）。

    ⚠️ 两处**分开存键**（`greeting` vs `direct_replies.greeting`）：同名键互相覆盖会让
    「只改了一处」的注入在读数上被另一处盖掉 ⇒ 判据看着绿、注入就成了空断言（实测踩到）。
    """
    tree = ast.parse(sources[f"agent:{agent}"])
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "direct_replies":
            for k, v in zip(node.value.keys, node.value.values):
                key = _literal(k)
                val = _literal(v)
                if isinstance(key, str) and isinstance(val, str):
                    out[f"direct_replies.{key}"] = val
        if isinstance(node, ast.keyword) and node.arg == "greeting":
            val = _literal(node.value)
            if isinstance(val, str):
                out["greeting"] = val
    return out


class World:
    """判据的全部输入（注入式红证 = 用改过的文本重建它）。"""

    def __init__(self, sources: dict[str, str]):
        self.sources = sources
        self.tools = parse_tools(sources)
        self.skills = parse_skills(sources)
        self.skill_personas = parse_skill_personas(sources)
        b_names, b_fallback = parse_agent(sources, "mibao")
        c_names, c_fallback = parse_agent(sources, "xiaobu")
        self.mibao_skills = b_names | ({b_fallback} if b_fallback else set())
        self.xiaobu_skills = c_names | ({c_fallback} if c_fallback else set())
        self.b_end_tools = frozenset(
            t for s in self.mibao_skills for t in self.skills.get(s, ())
        )
        self.c_end_tools = frozenset(
            t for s in self.xiaobu_skills for t in self.skills.get(s, ())
        )
        self.capability_text = parse_agent_direct_replies(sources, "mibao")
        # 判据 12 的输入面：用例源原文（键 `case:<相对 .github/cases 的路径>`，值 = 文本）
        self.case_docs = {k: v for k, v in sources.items() if k.startswith("case:")}
        assert "case:chat.yml" in self.case_docs or not self.sources.get("case:chat.yml"), (
            "用例源名录与 `case:` 源不一致（`case:chat.yml` 缺席）⇒ 判据 12 会空跑，fail-closed"
        )
        # 判据 7 的射程：**声明**了 mibao persona 的 skill（可达 + 已解绑的孤儿）。
        self.mibao_declared_skills = frozenset(
            n for n, p in self.skill_personas.items() if "mibao" in p
        )
        self.mibao_declared_tools = frozenset(
            t for s in self.mibao_declared_skills for t in self.skills.get(s, ())
        )
        # 确认门禁面（判据 8）：从工具类声明现算，不抄清单
        self.confirmed_write_tools = frozenset(
            n for n, d in self.tools.items() if d.get("requires_confirmation")
        )
        assert self.b_end_tools, "B 端工具并集为空 ⇒ 判据会空跑（fail-closed）"
        assert self.c_end_tools, "C 端工具并集为空 ⇒ 判据会空跑（fail-closed）"
        assert self.mibao_declared_tools >= self.b_end_tools, (
            "声明 persona 的 skill 工具集必须是**可达并集的超集**（判据 7 的射程前提；"
            f"差集={sorted(self.b_end_tools - self.mibao_declared_tools)}）—— "
            "否则判据 7 比判据 1 还窄，收口失效"
        )

    def write_bound_tools(self) -> list[str]:
        """B 端**可达**且 `read_only=False` 的工具（判据 8 的射程）。"""
        return sorted(
            t for t in self.b_end_tools
            if t in self.tools and not self.tools[t]["read_only"]
        )


def world() -> World:
    return World(_source_map())


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（纯函数：输入 World，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def problems_document_creation_tools_denied(w: World) -> list[str]:
    """判据 1：**单据类创建工具禁绑**（具名）+ A 档工具的门禁与补回域。

    新口径下「白名单制」换成「**禁绑制**」：禁的是**单据类创建**（商品 / 订单 / 其他单据类），
    而不是「一切写」。A 档可逆写的两道护栏（确认门禁 + 补回域逐条钉住）**照旧**。
    """
    out: list[str] = []
    for tool, why in sorted(DOCUMENT_CREATION_TOOLS_DENIED.items()):
        if tool in w.b_end_tools:
            out.append(
                f"`{tool}`（{why}）仍在 B 端工具并集里 ⇒ **单据类创建能力复活**"
                "（用户裁定：创建商品 / 订单 / 其他单据类一律不支持）"
            )
    for name in sorted(w.b_end_tools):
        decl = w.tools.get(name)
        if decl is None:
            out.append(
                f"`{name}` 被 B 端 skill 绑定，但**没有任何工具类声明该名字**"
                "（悬空绑定 ⇒ 模型必然撞 tool_not_found）"
            )
            continue
        if decl["read_only"] or name not in A_TIER_REVERSIBLE_WRITES:
            continue
        expected_skill = A_TIER_SKILLS.get(name)
        if expected_skill is None:
            out.append(
                f"`{name}` 在 `A_TIER_REVERSIBLE_WRITES` 里，但 `A_TIER_SKILLS` 没登记它该绑哪个域 ⇒ "
                "两份台账不同步（新增 A 档工具必须同时写明它的补回域）"
            )
        elif name not in w.skills.get(expected_skill, ()):
            out.append(
                f"`{name}` 属 A 档可逆写白名单，却不在 `{expected_skill}` skill 的工具集里 ⇒ "
                "补回域漂移（`A_TIER_SKILLS` 逐条钉住每把工具的域）"
            )
        else:
            strays = sorted(s for s in w.mibao_skills
                            if s != expected_skill and name in w.skills.get(s, ()))
            if strays:
                out.append(
                    f"`{name}` 属 A 档可逆写白名单，却还绑在其它 B 端 skill {strays} ⇒ "
                    f"补回范围超界（该类工具只在 `{expected_skill}` 域补回）"
                )
        if not decl.get("requires_confirmation"):
            out.append(
                f"`{name}` 属 A 档可逆写白名单，但未声明 `requires_confirmation` ⇒ "
                "写操作没有用户确认门禁（A 档入册判据：不绕过审核门禁）"
            )
    return out


def problems_write_tools_bound(w: World) -> list[str]:
    """判据 2：具名写能力工具一个都不得绑在 B 端（双向陈旧检查）。"""
    out: list[str] = []
    for tool, why in sorted(WRITE_TOOLS_UNBOUND_FROM_B_END.items()):
        if tool in w.b_end_tools:
            out.append(f"写能力工具 `{tool}`（{why}）仍绑在 B 端 skill 里 ⇒ 必须解绑")
    return out


def problems_action_sets(w: World) -> list[str]:
    """判据 3：B 端可达工具的 action 面 —— 零**单据类创建**、零**删除·停用·作废**。

    三个子面（各自可单独变红）：
    ① **结构面-创建**：向单据类**集合**路径发 `POST`（= 建一张单据）；
    ② **结构面-删除**：对任何路径发 `DELETE`（`/revert` 类**撤销**端点除外 —— 它是可逆的）；
    ③ **闭词表兜底**：action 名命中 `IRREVERSIBLE_ACTION_WORDS`（防「把 DELETE 挪成 action 名
       藏进 schema」）或把写 action 声明进 `read_only_actions` 洗白。

    ⚠️ A 档白名单成员**有意**拥有写 action（这正是它入册的原因）⇒ 对它们只跑 ③ 的**洗白**
    子判据（不得把写动作名声明成只读），①/② 仍照跑。
    """
    out: list[str] = []
    for name in sorted(w.b_end_tools):
        decl = w.tools.get(name)
        if decl is None:
            continue
        if decl["doc_creates"]:
            out.append(
                f"`{name}`（{decl['file']}）向单据类资源发 `POST {', '.join(decl['doc_creates'])}` "
                "⇒ 这是**创建单据**的动作（用户裁定：商品 / 订单 / 其他单据类都不得创建）"
            )
        # 🔴 `DELETE` 例外的**自我守卫**：登记在 `CANCEL_DELETE_ALLOWLIST` 里的工具，其 action 面
        # 必须**真的只是撤销**（不得同时暴露 `delete*`）—— 否则「撤销」这张表就成了
        # 「DELETE 免检通道」（登记一次，之后往该工具里塞 `delete` 也没人管）。
        if name in CANCEL_DELETE_ALLOWLIST:
            deletes = sorted(
                a for a in (decl["valid_actions"] or []) if a.startswith("delete")
            )
            if deletes:
                out.append(
                    f"`{name}` 在 `CANCEL_DELETE_ALLOWLIST` 里（声称 `DELETE` = 撤销），"
                    f"但 action 面暴露真删除动作 {deletes} ⇒ 例外被滥用"
                )
        if decl["irreversible_deletes"]:
            out.append(
                f"`{name}`（{decl['file']}）发 `DELETE {', '.join(decl['irreversible_deletes'])}` ⇒ "
                "不可逆删除动作（用户裁定：只能改，不能删）"
            )
        if decl["irreversible_actions"]:
            out.append(
                f"`{name}`：action 集合里出现不可逆动作名 {decl['irreversible_actions']} ⇒ "
                "删除 / 停用 / 作废不在支持面内"
            )
        roa = set(decl["read_only_actions"] or [])
        actions = set(decl["valid_actions"] or [])
        if name in A_TIER_REVERSIBLE_WRITES or name in CHANGE_TOOLS_REQUIRED_ON_B_END:
            # 🔴 已登记的写面（A 档可逆写 / 变更类）**有意**拥有写 action —— 这正是它们入册的原因。
            # 对它们只判**洗白**：写动作名不得被声明成只读（那会借只读豁免绕开确认门禁）。
            hidden = sorted(a for a in (actions & roa) if a in WRITE_ACTION_WORDS)
            if hidden:
                out.append(
                    f"`{name}`：把写动作名 {hidden} 声明进 `read_only_actions` ⇒ "
                    "借只读豁免绕开确认门禁（闭词表兜底）"
                )
            continue
        if decl["read_only"]:
            # 只读工具的 action 面必须**全是只读 action**（写 action 一个都不许露）
            if decl["read_only_actions"] is not None:
                extra = sorted(actions - roa)
                if extra:
                    out.append(
                        f"`{name}`：**只读工具**的 action {extra} 不在它声明的只读 action "
                        f"{sorted(roa)} 里 ⇒ 写 action 没删干净"
                    )
            hits = sorted(actions & WRITE_ACTION_WORDS)
            if hits:
                out.append(
                    f"`{name}`：**只读工具**的 action 集合里出现写动作名 {hits}（闭词表命中）—— "
                    "即把它写进 `read_only_actions` 也只是洗白"
                )
        # 非只读且**未登记**（既非 A 档也非变更白名单）⇒ 不在此判死：由判据 7
        # （problems_declared_persona_tools_are_controlled）报「未登记的写能力」并给出两个出口，
        # 避免同一条事实被两条判据双报。
    return out


#: 句级否定词（**与仓内同类守卫同口径**）：这些句子是「教用户别这么期待」，不是能力承诺。
CAPABILITY_NEGATIONS = (
    "不做", "不提供", "不在能力内", "不得", "不能", "无法", "禁止", "切勿", "只读", "不支持",
)


def _claimed_sentences(text: str):
    """切句（。；换行）后**丢掉否定句** —— 剩下的才是「能力承诺」。"""
    for seg in re.split(r"[。；\n]", text):
        if any(neg in seg for neg in CAPABILITY_NEGATIONS):
            continue
        yield seg


def problems_capability_claims(w: World) -> list[str]:
    """判据 4：`mibao.py` 的 greeting / capabilities 不得**承诺**清单外的能力（闭词表 + 句级否定过滤）。"""
    out: list[str] = []
    for key, text in sorted(w.capability_text.items()):
        for seg in _claimed_sentences(text):
            for phrase in FORBIDDEN_CAPABILITY_PHRASES:
                if phrase in seg:
                    out.append(
                        f"`mibao.py` 的 `{key}` 文案在**非否定句**里出现「{phrase}」⇒ **能力谎报**"
                        "（该能力不支持，承诺它就是 AI 说得到做不到）"
                        f"｜原句：{seg.strip()[:60]}"
                    )
    return out


def problems_a_tier_capability_parity(w: World) -> list[str]:
    """判据 6：A 档写能力 + **变更**能力的「文案 ↔ 绑定」双向一致（两侧都现算，不抄清单）。"""
    out: list[str] = []
    for skill, claim_words in sorted(A_TIER_CLAIM_WORDS.items()):
        tools_in_skill = sorted(t for t, s_ in A_TIER_SKILLS.items() if s_ == skill)
        bound = sorted(t for t in tools_in_skill if t in w.b_end_tools)
        claimed: list[str] = []
        for key, text in sorted(w.capability_text.items()):
            for seg in _claimed_sentences(text):
                hit = next((w_ for w_ in claim_words if w_ in seg), None)
                if hit:
                    claimed.append(f"{key}「{hit}」")
        words = "/".join(claim_words)
        if claimed and not bound:
            out.append(
                f"能力文案承诺了{words}（{', '.join(claimed)}），但 `{skill}` 域的 A 档工具"
                "一条都不在 B 端工具并集里 ⇒ **能力谎报**（说得到做不到）"
            )
        if bound and not claimed:
            out.append(
                f"A 档工具 `{'/'.join(bound)}` 已绑回 B 端，但 `mibao.py` 的 greeting / "
                f"capabilities 一个字都没提{words} ⇒ **反向能力谎报**"
                "（商家不知道能找黄金策用这个能力；补回了却不说 = 白补）"
            )
    # 判据 6b：**变更**能力的同一条双向一致（#7040 接线后新增的面）
    for tool, claim_words in sorted(CHANGE_CLAIM_WORDS.items()):
        bound = tool in w.b_end_tools
        claimed: list[str] = []
        for key, text in sorted(w.capability_text.items()):
            for seg in _claimed_sentences(text):
                hit = next((w_ for w_ in claim_words if w_ in seg), None)
                if hit:
                    claimed.append(f"{key}「{hit}」")
        words = "/".join(claim_words)
        if claimed and not bound:
            out.append(
                f"能力文案承诺了{words}（{', '.join(claimed)}），但变更工具 `{tool}` 不在 "
                "B 端工具并集里 ⇒ **能力谎报**（说得到做不到）"
            )
        if bound and not claimed:
            out.append(
                f"变更工具 `{tool}` 已绑回 B 端，但 `mibao.py` 的 greeting / capabilities "
                f"一个字都没提{words} ⇒ **反向能力谎报**（接回了却不说 = 白接）"
            )
    return out


def problems_shared_tools_intact(w: World) -> list[str]:
    """判据 5：与 C 端共享的工具必须仍存在、且仍被 C 端 skill 绑定（只解绑 B，绝不删）。"""
    out: list[str] = []
    for tool in SHARED_WITH_C_END:
        if tool not in w.tools:
            out.append(f"共享工具 `{tool}` 的**工具类已消失** ⇒ 违反「只解绑 B、绝不删除」（C 端会直接失效）")
            continue
        if tool not in w.c_end_tools:
            out.append(
                f"共享工具 `{tool}` 不再被任何 C 端 skill 绑定 ⇒ 这是**改 C 端行为**的动作"
                "（用户裁定：C 端零改动），不得在本单里发生"
            )
    return out


def problems_declared_persona_tools_are_controlled(w: World) -> list[str]:
    """判据 7：**声明了黄金策 persona 的每个 skill**（含已解绑的孤儿）绑的工具必须
    ∈ A 档白名单 ∪ 变更白名单 ∪ 只读，且 action 面不得含不可逆动作。

    与判据 1 的差别 = **射程**：判据 1 取「可达并集」（`skill_names` ∪ fallback），
    本判据取「声明了 persona 的 skill 并集」⇒ "把 skill 解绑" 不再是逃逸路径（#5302）。
    """
    out: list[str] = []
    for name in sorted(w.mibao_declared_tools):
        decl = w.tools.get(name)
        if decl is None:
            out.append(
                f"`{name}` 被**声明了 mibao persona 的 skill** 绑定，但没有任何工具类声明该名字 "
                "（悬空绑定 ⇒ 模型必然撞 tool_not_found）"
            )
            continue
        if decl["irreversible_actions"]:
            out.append(
                f"`{name}`：action 集合里出现不可逆动作名 {decl['irreversible_actions']} ⇒ "
                "声明 persona 的 skill 不得暴露删除 / 停用 / 作废动作"
            )
        if decl["doc_creates"]:
            out.append(
                f"`{name}`（{decl['file']}）向单据类资源发 "
                f"`POST {', '.join(decl['doc_creates'])}` ⇒ 声明 persona 的 skill 不得绑创建单据的工具"
            )
        # 非只读 + 不在任一登记表里 ⇒ 红（未登记的写能力不得经 persona 家族溜进 B 端）
        if (not decl["read_only"]
                and name not in A_TIER_REVERSIBLE_WRITES
                and name not in DOCUMENT_CREATION_TOOLS_DENIED
                and name not in CHANGE_TOOLS_REQUIRED_ON_B_END):
            out.append(
                f"`{name}`（{decl['file']}）`read_only=False`，却被声明 mibao persona 的 skill 绑定 "
                "⇒ **未登记的写能力**。处置（二选一，必须显式）：① 按新裁定它是**变更** ⇒ 登记进 "
                "`CHANGE_TOOLS_REQUIRED_ON_B_END` 并把它的变更用例与确认门禁写清；"
                "② 它属单据类创建 / 删除 / 停用 / 作废 ⇒ 登记进 "
                "`DOCUMENT_CREATION_TOOLS_DENIED` 并解绑"
            )
    return out


def problems_write_requires_confirmation(w: World) -> list[str]:
    """判据 8（新口径的核心）：**非只读 ⇒ 必须带确认门禁**。

    「接回变更」与「拆掉门禁」是两件事：本判据保证前者发生的同时后者不发生 ——
    任何 B 端可达的非只读工具，必须在类体声明 `requires_confirmation`（或 `destructive`）。
    门禁落点 = `backend/ai-agent-service/app/graph/skills/base_skill.py` 的
    `_requires_confirmation`：非只读且非只读 action ⇒ 要求用户确认，
    补救路径 = 同 skill 的 `interact(component=confirm)` 确认卡。
    """
    out: list[str] = []
    for name in w.write_bound_tools():
        decl = w.tools[name]
        if decl.get("requires_confirmation") or decl.get("destructive"):
            continue
        out.append(
            f"`{name}`（{decl['file']}）在 B 端**可达**且 `read_only=False`，但既没有 "
            "`requires_confirmation` 也没有 `destructive` ⇒ **变更没有确认门禁**"
            "（会绕过 `base_skill._requires_confirmation`，模型可直接改数据）"
        )
    return out


def problems_no_irreversible_or_document_creation_on_b_end(w: World) -> list[str]:
    """判据 9：**可达工具面**里的「单据类创建」与「删除 / 停用 / 作废」零出现（汇总口径）。

    与判据 3 同源但**射程不同**（3 判单个工具的动作与调用面，9 判可达并集的形态），
    两条各自带独立红证 —— 防止「一条判据同时承担两件事」后被人顺手删掉一格。
    """
    out: list[str] = []
    for name in sorted(w.b_end_tools):
        decl = w.tools.get(name)
        if decl is None:
            continue
        if name in DOCUMENT_CREATION_TOOLS_DENIED:
            out.append(f"`{name}` 是**单据类创建工具**且 B 端可达（`DOCUMENT_CREATION_TOOLS_DENIED`）")
        if decl["irreversible_actions"] or decl["irreversible_deletes"]:
            out.append(
                f"`{name}` B 端可达且暴露不可逆动作 "
                f"（action={decl['irreversible_actions']} · DELETE={decl['irreversible_deletes']}）"
            )
    return out


def problems_change_tools_reachable(w: World) -> list[str]:
    """判据 10（**正向**）：登记在 `CHANGE_TOOLS_REQUIRED_ON_B_END` 的变更工具必须真的可达。

    旧判据只能表达「不许有写工具」⇒ 把变更能力整体解绑也全绿（那正是 issue #7040 的起点：
    「变更」在 B 端物理不可达，而没有任何判据会因此变红）。本条把**正向可达**变成判据。
    """
    return [
        f"变更工具 `{t}` 不在 B 端可达并集里（{why}）⇒ 「变更必须支持」这条裁定在 B 端"
        "**物理上不可达**" for t, why in sorted(CHANGE_TOOLS_REQUIRED_ON_B_END.items())
        if t not in w.b_end_tools
    ]


#: 判据 12 的**伪工具名**：`expectations` 里用来表达「该轮不要工具调用」等的形态词，
#: 不是真工具（真值源 = `tests/agent_eval/local_runner.py::check_expectation` 的语义）。
PSEUDO_EXPECTATIONS: frozenset = frozenset({"direct_reply"})


def _expectation_branches(exp):
    """`expectations` 的一条声明 → `(工具名列表, 是否含伪工具分支)`。

    ⚠️ 两条形态都要吃：**字符串**（`tool: "direct_reply or nav_guide"`）与 **mapping**
    （`tool: order_create`）；只写 mapping 分支 = 判据在真语料上一路空转
    （本判据首版实测：`iter names: []` ⇒ 注入式红证当场抓出）。

    ⚠️ **伪工具分支也必须计数**（第二版踩到）：`direct_reply or validate_input` 里
    `validate_input` 不可达，但 `direct_reply` **可达**（= 该轮零工具调用即满足）
    ⇒ 只看真工具名会把这条误判成「整条都不可达」。返回的第二个值就是为它准备的。
    """
    text = exp.get("tool") if isinstance(exp, dict) else exp
    names: list[str] = []
    pseudo = False
    for part in re.split(r"\bor\b", str(text or "")):
        name = part.strip()
        if not name:
            continue
        if name in PSEUDO_EXPECTATIONS:
            pseudo = True
            continue
        # `product_search(k=v)` 形态 ⇒ 取括号前那段
        name = name.split("(", 1)[0].strip()
        if re.fullmatch(r"[a-z][a-z0-9_]*", name):
            names.append(name)
    return names, pseudo


def problems_cases_expect_unreachable_tools(w: World) -> list[str]:
    """判据 12（**用例面**）：声明了 persona 的用例，其 `expectations` 要求的工具必须**可达**。

    ## 立案理由（issue #7048 P4，2026-10-16）

    判据 1 / 3 / 7 / 9 判的是**工具面与绑定面** —— 它们看不见「**在飞的用例**还在期望一个
    边界外的动作」。`CH-019` 就是这一格：2026-10-16 能力边界终版之后，它四轮诉求（建品／下单／
    客户写／工单改状态）在 B 端全部禁止或已下线，而 `expectations` 仍是 `tool: interact`
    ⇒ 把 agent 判成绿的唯一办法 = 它去发一张**被裁定禁止的写确认卡**。判据 1 全绿、CI 全绿，
    只有真跑 LLM 评测才会红（而评测按 #4262 由用户**集中手动**跑）⇒ **零常驻信号**。

    ## 判据形态

    逐用例取 persona 决定**该端的可达工具集**（`mibao` → B 端 / `xiaobu` → C 端 / 未声明 →
    两端并集；与 `tests/agent_eval/eval_case_filter.py::select_cases_for_persona` 同一口径），
    再逐条 `expectations` 取工具名：**不在该集合里 ⇒ 红**（默认拒绝，不猜、不近似匹配）。

    ## 边界（照实登记，§19.1）

    - **只扫 `expectations`**（不是 `data_checks`：后者多为自然语义散文，`acceptance-protocol` §1.3
      铁律明确它**不计分**）；`must_succeed` / `required_args` 的具名工具由判据 1/7 的绑定面兜住。
    - **判不了行为**（同判据 11 的自述）：它只保证「用例不会**要求**一个边界外的工具」，
      「模型是否照做」只能靠真实 LLM 评测。
    - **判不了「期望过严」**（漏报方向）：`HR-009` 的裸 `direct_reply` 是**另一个形态**的腐烂
      （该调 `nav_guide` 却被要求零工具）—— 那需要读产品语义，本判据不假装能判。
    - 🔴 **双端用例整条排除**（防假红，**主会话插单提醒核过**）：`persona` 缺省 ⇒ 两端都跑，
      而 `expectations` 是「任一轮满足即过」⇒ 某个工具在**本腿**不可达是**合法**形态
      （实例：`CH-009` 的 `order_create` = C 端主流程）。故本判据只判**单端**用例
      （`persona` ∈ {mibao, xiaobu}）—— 反向对照见 `test_dual_leg_cases_are_not_false_red`。
    - **零台账 / 零豁免**：真语料上当前命中 **0** 条（2026-10-16 现取）⇒ 本判据**不留**
      「登记后放行」的出口（边界外期望一出现即红）。
    - **整条 vs 死分支**：只判「`expectations` **整条**都指向不可达工具」那一格（判别力被掏空）；
      `or` 形态里**仍有可达分支**的（死分支）不判红、也不登记（漏报方向，如实登记）。
    """
    out: list[str] = []
    seen_blockers: dict[str, str] = {}
    if not w.case_docs:
        out.append(
            "用例源一个都没加载到（`.github/cases/**` 为空或 `CASES_DIR` 漂移）⇒ 本判据会空跑，"
            "fail-closed 判红"
        )
        return out
    for key, text in sorted(w.case_docs.items()):
        rel = key.split(":", 1)[1]
        # ⚠️ 从 **World 的源文本**解析（`w.case_docs[key]`），**不是**从磁盘重读文件 ——
        # 判据的输入面就是 `sources`；重读磁盘会让注入式红证**恒绿**（注入改了内存、
        # 磁盘没变 ⇒ 判据读不到注入，实测踩到：⑫ 首版写成 `_yaml_load_file(str(CASES_DIR/rel))`
        # ⇒ 「判据没有变红 ⇒ 它是空断言」当场红）。
        try:
            data = _yaml_load_text(text)
        except Exception as e:  # noqa: BLE001 —— 解析不了 = 判不了 ⇒ 报出，不静默跳过
            out.append(f"`{rel}` 解析失败（{type(e).__name__}: {e}）⇒ 判据 12 判不了该文件")
            continue
        for c in (data or {}).get("cases") or []:
            if not isinstance(c, dict):
                continue
            persona = str(c.get("persona") or "").strip().lower()
            if persona == "mibao":
                reachable = w.b_end_tools
            elif persona == "xiaobu":
                reachable = w.c_end_tools
            else:
                # 🔴 **双端用例（`persona` 缺省）整条排除** —— 本判据只对**单端**用例生效。
                # 依据（与运行期选择口径**同一份**，不另立第二份判别）：
                # `tests/agent_eval/eval_case_filter.py::select_cases_for_persona` 的语义 ——
                # `persona` 为空/其它 ⇒ 该用例**两端都跑**（`filter_by_persona` 只在
                # `persona == 另一端的专属值` 时才丢），且 runner 的 `expectations` 是
                # **任一轮满足即过**（`tests/agent_eval/local_runner.py` 的计分循环）⇒
                # 「本腿不可达的那个工具」在另一条腿上可能是主流程 ⇒ 在这里判红 = **假红**。
                # 实例（主会话插单提醒核过，2026-10-16）：`CH-009` 是双端用例，其
                # `expectations` 含 `order_create`（**C 端元元的主流程**，在
                # `eval_case_filter.XIAOBU_TOOLS` 在册）；`order_create` 在 B 端已解绑 ⇒
                # 若把双端用例一起判，`CH-009` 会被假红。**故必须排除**（不是"漏判"：
                # 双端用例的"本腿不可达"是**合法**形态）。
                continue
            for exp in c.get("expectations") or []:
                text = str((exp.get("tool") if isinstance(exp, dict) else exp) or "")
                names, has_pseudo = _expectation_branches(exp)
                if not names:
                    continue
                dead = [n for n in names if n not in reachable]
                if not dead:
                    continue
                has_reachable = has_pseudo or any(n in reachable for n in names)
                cid, who = c.get("id"), (persona or "双端")
                if not has_reachable:
                    # 🔴 **判别力被掏空的那一格**（本判据的靶心）：这一条**没有任何**可达分支
                    # ⇒ 用例的通过条件只能是「做到一个边界外的动作」（绿 = 奖励被禁止的行为），
                    # 或者永远红（agent 正确地不做）。`CH-019`（改判前）就是这一格。
                    seen_blockers[str(cid)] = (
                        f"`{rel}` 的用例 `{cid}`（persona={who}）`expectations` **整条**都指向"
                        f"不可达工具 {dead}（B 端可达 {len(w.b_end_tools)} 个）⇒ 该用例要么奖励"
                        f"一个边界外的动作、要么永远红（无第三个出口）｜原句：{text}"
                    )
                # else：**死分支不判红**（漏报方向，如实登记）—— `or` 形态里至少还有一条
                # 可达分支 ⇒ 用例**仍然可满足**，那个不可达分支**不影响判定**。
                # 真语料上这类形态当前 0 条（双端用例已在上面整条排除；三条例 `persona: mibao`
                # 的 `direct_reply or validate_input` 是**伪分支 + 真分支**，不属于本判据射程）。
    # 无台账、无豁免：**默认拒绝**。真语料上当前命中 0 条（2026-10-16 现取）——
    # 本判据是**零存量**的（把边界外的期望留在用例里 ⇒ 当场红，没有"登记后放行"的出口）。
    return out + [f"{detail}" for _cid, detail in sorted(seen_blockers.items())]


def problems_prompt_boundary_coherence(w: World) -> list[str]:
    """判据 11：**prompt 措辞**不得把已接回的能力说成「不在能力内」。

    ## 立案理由（主会话插单发现，2026-10-16）

    prompt 是 B 端行为的**主要载体**（比工具面更直接）：工具接回了、prompt 仍写「这些操作
    全部不在能力内」⇒ agent 会**继续拒绝**，接回的能力**不会被用**（#7040 形同空转），
    且评测里那批「期望 = agent 拒绝」的用例会继续红。

    ## 判据形态（**共现**扫描，不是"全文禁词"）

    对每个 prompt 语料文件，按**句**（`。；\n` 切）扫描：**同一句**里既出现
    `PROMPT_COHERENCE_TOOLS` 里的工具名、又出现**否定词** ⇒ 红。
    逐句而不是逐文件是**判别力的来源**：本仓 prompt 文风是「一条规则 + 一条 ❌ 反例」，
    正确的写法（如「创建商品 ❌ 不支持；**标记已读** ✅ 要办」）会让否定句与工具名**不同句**
    ⇒ 不误红；而「`notification_manage` 已下线 / 不在能力内」这类**同句**写法必红。

    ## 边界（照实登记，§19.1）

    - **只扫 `PROMPT_COHERENCE_TOOLS`**（本单接回的工具 + A 档工具）：全量禁词扫描会把 prompt 里
      指向**确实不支持**能力（创建 / 删除）的**正确**否定句整片喂红（§17.3）。
    - **判的是文本一致性，不是 LLM 行为**：prompt 改对了不等于模型照做 —— 行为面只能靠真实
      LLM 评测（按 #4262 由用户集中跑）。本判据只保证「提示词不会**主动教 agent 拒绝**已支持的能力」。
    """
    out: list[str] = []
    for key, text in sorted(w.sources.items()):
        if not key.startswith("prompt:"):
            continue
        rel = key.split(":", 1)[1]
        for seg in re.split(r"[。；\n]", text):
            neg = next((n for n in CAPABILITY_NEGATIONS if n in seg), None)
            if neg is None:
                continue
            hits = sorted(t for t in PROMPT_COHERENCE_TOOLS if t in seg)
            if hits:
                out.append(
                    f"`{rel}` 同一句里既点名已接回的工具 {hits}、又出现否定词「{neg}」⇒ "
                    "提示词仍在教 agent 拒绝一个**已支持**的能力（#7040 接线会被 prompt 抵消）"
                    f"｜原句：{seg.strip()[:80]}"
                )
    return out


JUDGEMENTS = {
    "1 · 单据类创建工具禁绑 + A 档门禁/补回域": problems_document_creation_tools_denied,
    "2 · 具名写工具零绑定": problems_write_tools_bound,
    "3 · action 面零建单零删除": problems_action_sets,
    "4 · 能力文案不谎报": problems_capability_claims,
    "5 · 共享工具与 C 端零改动": problems_shared_tools_intact,
    "6 · A 档/变更能力文案↔绑定双向一致": problems_a_tier_capability_parity,
    "7 · 声明 persona 的 skill 工具面受控": problems_declared_persona_tools_are_controlled,
    "8 · 非只读 ⇒ 必须带确认门禁": problems_write_requires_confirmation,
    "9 · 可达面零建单零删除": problems_no_irreversible_or_document_creation_on_b_end,
    "10 · 变更工具必须真的可达": problems_change_tools_reachable,
    "11 · prompt 措辞与边界一致（不教 agent 拒绝已支持能力）": problems_prompt_boundary_coherence,
    "12 · 用例 expectations 要求 persona 可达的工具": problems_cases_expect_unreachable_tools,
}


# ══════════════════════════════════════════════════════════════════════════════
# 四、断言
# ══════════════════════════════════════════════════════════════════════════════


def test_every_judgement_is_green() -> None:
    """全部判据在**当前仓库**上全绿（红 = B 端能力边界已漂移，逐条问题见断言文案）。"""
    w = world()
    problems = {label: fn(w) for label, fn in JUDGEMENTS.items()}
    bad = {label: p for label, p in problems.items() if p}
    assert bad == {}, "B 端能力边界判据未通过：\n" + "\n".join(
        f"  【{label}】\n    - " + "\n    - ".join(items[:12]) for label, items in bad.items()
    )


DUAL_LEG_CASE_ID = "ZZ-INJ-DUAL-LEG"
SINGLE_LEG_CASE_ID = "ZZ-INJ-SINGLE-LEG"


def test_dual_leg_cases_are_not_false_red() -> None:
    """判据 12 的**反向对照**：双端用例里出现"本腿不可达的工具"**不得**判红。

    为什么必须单列这条（主会话插单提醒，2026-10-16）：
      `persona` 缺省的用例**两端都跑**，而 `expectations` 的计分语义是「任一轮满足即过」
      ⇒ 它在 B 端腿不可达的那个工具，在 C 端腿可能正是主流程（实例：`CH-009` 的
      `order_create`，见 `tests/agent_eval/eval_case_filter.py::XIAOBU_TOOLS`）——
      若不排除双端用例，本判据会把 `CH-009` 这类**合法**用例判红。

    两段读数（**同一判定函数**）：
      ① 真语料（含 `CH-009`）⇒ 判据 12 输出不含任何 `CH-009` 相关的阻塞项（现取，不写死）；
      ② 合成对照：同一个"不可达工具"声明，放在**双端**用例里 ⇒ 不红；放在**单端**用例里 ⇒ 红
         （这半段同时证明「⑫d 不是空断言」）。
    """
    w = world()
    problems = problems_cases_expect_unreachable_tools(w)
    c009 = [p for p in problems if "`CH-009`" in p]
    assert c009 == [], (
        "双端用例 `CH-009` 被判据 12 判红 ⇒ 本判据误伤了双端用例"
        "（`order_create` 是 C 端主流程，B 端不可达是**合法**形态）：\n  " + "\n  ".join(c009)
    )
    # ② 合成对照：同一段声明，persona 取/不取
    def _with(extra: str) -> list[str]:
        src = dict(_source_map())
        src["case:chat.yml"] = src["case:chat.yml"] + extra
        return problems_cases_expect_unreachable_tools(World(src))

    dual = _with(
        f"\n  - id: {DUAL_LEG_CASE_ID}\n    user_inputs:\n      - \"双端对照\"\n"
        "    expectations:\n      - tool: order_create\n    skip_reason: \"\"\n"
    )
    assert [p for p in dual if DUAL_LEG_CASE_ID in p] == [], (
        "双端用例（persona 缺省）被判定为「期望边界外动作」⇒ 判据 12 的双端排除失效"
    )
    single = _with(
        f"\n  - id: {SINGLE_LEG_CASE_ID}\n    persona: mibao\n    user_inputs:\n"
        "      - \"单端对照\"\n    expectations:\n      - tool: order_create\n"
        "    skip_reason: \"\"\n"
    )
    hits = [p for p in single if SINGLE_LEG_CASE_ID in p]
    assert hits, (
        "单端用例声明一个不可达工具却**没有**被判红 ⇒ 判据 12 的判别力退化成空断言"
        "（双端排除把单端也一起放过了）"
    )


def test_change_tools_actually_reachable() -> None:
    """**正向要求**（新口径 vs 旧判据的分水岭）：变更工具必须真的在 B 端可达并集里。

    红证 = 注入 ⑪（把 `notification` 从 `mibao.py` 的 `skill_names` 解绑）。
    """
    w = world()
    assert problems_change_tools_reachable(w) == [], "\n".join(problems_change_tools_reachable(w))
    assert w.write_bound_tools(), (
        "B 端可达并集里一个非只读工具都没有 ⇒ 「变更可达」这条正向判据退化成空断言"
        "（fail-closed：接回变更才是本单的目的）"
    )


def test_union_print_is_informative() -> None:
    """读数（供 PR/汇报引用）：B 端工具并集与它们的 `read_only` / 门禁声明。"""
    w = world()
    print("\n[B 端工具并集] " + str(sorted(w.b_end_tools)))
    print("[其中 read_only=False] " + str(sorted(
        n for n in w.b_end_tools if w.tools.get(n, {}).get("read_only") is not True
    )))
    print("[其中带确认门禁] " + str(sorted(
        n for n in w.b_end_tools
        if w.tools.get(n, {}).get("requires_confirmation") or w.tools.get(n, {}).get("destructive")
    )))
    print("[B 端 skill] " + str(sorted(w.mibao_skills)))
    print("[声明 mibao persona 的 skill（判据 7 射程）] " + str(sorted(w.mibao_declared_skills)))
    print("[该射程的工具并集] " + str(sorted(w.mibao_declared_tools)))


# ══════════════════════════════════════════════════════════════════════════════
# 五、注入式红证：**每一条**判据都要有能单独变红的负向夹具（否则它只是空断言）
# ══════════════════════════════════════════════════════════════════════════════


def _bind_into_b_skill(text: str, tool: str) -> str:
    """往某个 B 端 skill 的 `*_TOOLS` 列表里插一个工具名（模拟「工具被重新绑回」）。"""
    m = re.search(r"^[A-Z_]+_TOOLS\s*=\s*\[", text, re.M)
    assert m, "注入锚点失配：该 skill 里没有 `*_TOOLS = [`（同步本判据）"
    return text[: m.end()] + f'\n    "{tool}",' + text[m.end():]


def _unbind_from_c_skill(text: str, tool: str) -> str:
    new, n = re.subn(rf'\n\s*"{re.escape(tool)}",', "", text, count=1)
    assert n == 1, f"注入锚点失配：该 skill 里没有 `{tool}`（同步本判据）"
    return new


def _injections() -> dict[str, tuple[str, "callable", "callable"]]:
    """`label` → (被判据读取的源键, 文本变异, 目标判据)。"""
    return {
        # ── 判据 1：单据类创建工具禁绑 ────────────────────────────────────────────
        "① 把 `order_create` 重新绑回 order skill ⇒ 判据 1 红（单据类创建）": (
            "skill:order_skill.py",
            lambda s: _bind_into_b_skill(s, "order_create"),
            problems_document_creation_tools_denied,
        ),
        "①b A 档工具摘掉确认门禁（product_update）⇒ 判据 1 红": (
            "tool:product_update.py",
            lambda s: s.replace("requires_confirmation = True", "requires_confirmation = False", 1),
            problems_document_creation_tools_denied,
        ),
        "①c A 档工具被绑到别的 B 端域（product_update 进 order skill）⇒ 判据 1 红（补回域漂移）": (
            "skill:order_skill.py",
            lambda s: _bind_into_b_skill(s, "product_update"),
            problems_document_creation_tools_denied,
        ),
        "①d 绑一个不存在的工具名（悬空绑定）⇒ 判据 1 红": (
            "skill:data_skill.py",
            lambda s: _bind_into_b_skill(s, "ghost_tool_never_declared"),
            problems_document_creation_tools_denied,
        ),
        # ── 判据 2：具名写工具零绑定 ─────────────────────────────────────────────
        "② 把 `settings_manage` 重新绑回 product skill ⇒ 判据 2 红": (
            "skill:product_skill.py",
            lambda s: _bind_into_b_skill(s, "settings_manage"),
            problems_write_tools_bound,
        ),
        "②b 把 `order_manage` 重新绑回 order skill ⇒ 判据 2 红": (
            "skill:order_skill.py",
            lambda s: _bind_into_b_skill(s, "order_manage"),
            problems_write_tools_bound,
        ),
        # ── 判据 3：action 面零建单零删除（三条子面各自独立红证）────────────────────
        "③ 让 B 端可达工具向单据集合发 POST（category_manage 加建单调用）⇒ 判据 3 红": (
            "tool:category_manage.py",
            lambda s: s.replace(
                'VALID_ACTIONS = {"tree"}',
                'VALID_ACTIONS = {"tree"}\n\n\nasync def _planted_create(client):\n'
                '    return await client.post("/api/admin/agent/orders", json_data={})',
                1,
            ),
            problems_action_sets,
        ),
        "③b 让 B 端可达工具发 DELETE（category_manage 加删分类调用）⇒ 判据 3 红": (
            "tool:category_manage.py",
            lambda s: s.replace(
                'VALID_ACTIONS = {"tree"}',
                'VALID_ACTIONS = {"tree"}\n\n\nasync def _planted_delete(client):\n'
                '    return await client.delete("/api/admin/categories/1")',
                1,
            ),
            problems_action_sets,
        ),
        "③c 往 B 端只读工具的 action 集塞不可逆动作名（category_manage += delete）⇒ 判据 3 红": (
            "tool:category_manage.py",
            lambda s: s.replace('VALID_ACTIONS = {"tree"}', 'VALID_ACTIONS = {"tree", "delete"}', 1),
            problems_action_sets,
        ),
        "③d 把写 action 挪进 `read_only_actions` 洗白（notification_manage += mark_read）⇒ 判据 3 红": (
            "tool:notification_manage.py",
            lambda s: s.replace('READ_ONLY_ACTIONS = frozenset({"list", "unread_count"})',
                                'READ_ONLY_ACTIONS = frozenset({"list", "unread_count", "mark_read"})', 1),
            problems_action_sets,
        ),
        "③e `DELETE` 例外被滥用（允许撤销的工具同时暴露 delete action）⇒ 判据 3 红": (
            "tool:scheduled_task_manage.py",
            lambda s: s.replace('VALID_ACTIONS = {"create", "list", "cancel"}',
                                'VALID_ACTIONS = {"create", "list", "cancel", "delete"}', 1),
            problems_action_sets,
        ),
        # ── 判据 4：能力文案不谎报 ───────────────────────────────────────────────
        "④ 能力文案注入「我可以帮您创建商品」⇒ 判据 4 红": (
            "agent:mibao",
            lambda s: s.replace("我可以帮您**查数据、做分析**", "我可以帮您创建商品、", 1),
            problems_capability_claims,
        ),
        "④b greeting 单独注入写能力承诺 ⇒ 判据 4 红": (
            "agent:mibao",
            lambda s: s.replace(
                "我可以帮您**查数据、做分析**：订单与物流、生产进度与报工、",
                "我可以帮您处理商品管理、订单处理，",
                1,
            ),
            problems_capability_claims,
        ),
        # ── 判据 5：共享工具与 C 端零改动 ────────────────────────────────────────
        "⑤ 共享工具的 C 端绑定被摘掉（customer_order 去 order_create）⇒ 判据 5 红": (
            "skill:customer_order_skill.py",
            lambda s: _unbind_from_c_skill(s, "order_create"),
            problems_shared_tools_intact,
        ),
        # ── 判据 6：A 档 / 变更能力「文案 ↔ 绑定」双向 ───────────────────────────
        **{
            f"⑥ 解绑 {_sk} 域**全部** A 档工具（文案仍承诺）⇒ 判据 6 红（谎报方向）": (
                _skill_source_key(_sk),
                (lambda _tools: (
                    lambda s: functools.reduce(
                        lambda acc, t: _unbind_from_c_skill(acc, t), _tools, s)
                ))(sorted(_t for _t, _s in A_TIER_SKILLS.items() if _s == _sk)),
                problems_a_tier_capability_parity,
            )
            for _sk in sorted(set(A_TIER_SKILLS.values()))
        },
        "⑥b 文案抹掉改价承诺、工具仍绑在 B 端 ⇒ 判据 6 红（漏报方向）": (
            "agent:mibao",
            lambda s: re.sub(r"改价|调价", "改款", s),
            problems_a_tier_capability_parity,
        ),
        "⑥c 文案承诺标记已读、但变更工具被解绑 ⇒ 判据 6 红（谎报方向）": (
            "skill:notification_skill.py",
            lambda s: _unbind_from_c_skill(s, "notification_manage"),
            problems_a_tier_capability_parity,
        ),
        "⑥d 文案抹掉标记已读承诺、工具仍绑在 B 端 ⇒ 判据 6 红（漏报方向）": (
            "agent:mibao",
            lambda s: re.sub(r"标记已读|标为已读|全部已读", "看看通知", s),
            problems_a_tier_capability_parity,
        ),
        # ── 判据 7：声明 persona 的 skill 工具面受控 ──────────────────────────────
        "⑦ 已解绑 skill 的工具改回 `read_only = False`（settings_manage）⇒ 判据 7 红": (
            "tool:settings_manage.py",
            lambda s: s.replace("read_only = True", "read_only = False", 1),
            problems_declared_persona_tools_are_controlled,
        ),
        "⑦b 已解绑 skill 的工具塞回不可逆 action（settings_manage += delete）⇒ 判据 7 红": (
            "tool:settings_manage.py",
            lambda s: s.replace(
                'VALID_ACTIONS = {"get_settings", "get_ai_config", "login_logs"}',
                'VALID_ACTIONS = {"get_settings", "get_ai_config", "login_logs", "delete"}',
                1,
            ),
            problems_declared_persona_tools_are_controlled,
        ),
        "⑦c 已解绑 skill 绑定一个不存在的工具（settings_skill 悬空绑定）⇒ 判据 7 红": (
            "skill:settings_skill.py",
            lambda s: _bind_into_b_skill(s, "ghost_tool_never_declared"),
            problems_declared_persona_tools_are_controlled,
        ),
        "⑦d 声明 persona 的 skill 绑一个未登记的写工具（settings_skill 绑 order_manage）⇒ 判据 7 红": (
            "skill:settings_skill.py",
            lambda s: _bind_into_b_skill(s, "order_manage"),
            problems_declared_persona_tools_are_controlled,
        ),
        # ── 判据 8：非只读 ⇒ 必须带确认门禁 ─────────────────────────────────────
        "⑧ 变更工具摘掉确认门禁（notification_manage）⇒ 判据 8 红": (
            "tool:notification_manage.py",
            lambda s: s.replace("requires_confirmation = True", "requires_confirmation = False", 1),
            problems_write_requires_confirmation,
        ),
        # ⑧b 用的是**合成工具**（真仓里没有「非只读且无门禁」的工具 —— 那正是本判据要防的形态）
        # ⇒ 注入点 = 新增一个工具文件 + 把它绑进 B 端 skill（见 _inject_unconfirmed_write_tool）。
        "⑧b 往 B 端接一个**非只读且无确认门禁**的工具 ⇒ 判据 8 红": (
            "skill:staff_skill.py",
            lambda s: _bind_into_b_skill(s, "zzz_planted_write_tool"),
            problems_write_requires_confirmation,
        ),
        # ── 判据 9：可达面零建单零删除 ───────────────────────────────────────────
        "⑨ 单据类创建工具进 B 端可达面（order_create → order skill）⇒ 判据 9 红": (
            "skill:order_skill.py",
            lambda s: _bind_into_b_skill(s, "order_create"),
            problems_no_irreversible_or_document_creation_on_b_end,
        ),
        "⑨b 可达工具暴露不可逆动作（notification_manage += delete）⇒ 判据 9 红": (
            "tool:notification_manage.py",
            lambda s: s.replace(
                'VALID_ACTIONS = {"list", "unread_count", "mark_read", "read_all"}',
                'VALID_ACTIONS = {"list", "unread_count", "mark_read", "read_all", "delete"}',
                1,
            ),
            problems_no_irreversible_or_document_creation_on_b_end,
        ),
        # ── 判据 10（正向）：变更工具必须真的可达 ────────────────────────────────
        "⑩ 把 `notification` skill 从 mibao 解绑 ⇒ 判据 10 红（变更不可达）": (
            "agent:mibao",
            lambda s: re.sub(r'\n\s*"notification",', "", s, count=1),
            problems_change_tools_reachable,
        ),
        # ── 判据 11：prompt 措辞与边界一致 ───────────────────────────────────────
        "⑪ prompt 同句把已接回的工具说成「不在能力内」（settings.md 写回旧口径）⇒ 判据 11 红": (
            "prompt:prompts/settings.md",
            lambda s: s + (
                "\n## 旧口径残留（注入）\n"
                "`notification_manage` 的标记已读**不在能力内**，如实说明并引导到后台。\n"
            ),
            problems_prompt_boundary_coherence,
        ),
        "⑪b prompt 同句说 A 档改价工具「不做」（general.md 写回旧口径）⇒ 判据 11 红": (
            "prompt:prompts/general.md",
            lambda s: s + "\n改价（product_update / sku_update）本域**不做**，请到后台自行调整。\n",
            problems_prompt_boundary_coherence,
        ),
        # ── 判据 12：用例面（expectations 要求不可达工具）────────────────────────
        # 三个注入各打一个**不同**的坏形态：① 边界外工具（B 端解绑的写工具）
        # ② C 端专属工具（B 端从来没有）③ 用例源整个没加载（fail-closed，防"空跑恒绿"）。
        "⑫ 用例 expectations 要求 B 端**已解绑**的写工具（order_create）⇒ 判据 12 红": (
            "case:chat.yml",
            lambda s: s + _INJECTED_CASE_ORPHAN_WRITE,
            problems_cases_expect_unreachable_tools,
        ),
        "⑫b 用例 expectations 要求 **C 端专属**工具（aftersale_create 跑在 mibao 腿上）⇒ 判据 12 红": (
            "case:chat.yml",
            lambda s: s + _INJECTED_CASE_C_END_TOOL,
            problems_cases_expect_unreachable_tools,
        ),
        # ⚠️ ⑫d 是**反向对照**（不是红证）：本判据的注入表要求「判据必须变红」，
        # 故它用**同一判定函数**在 `_injections` 之外的独立断言里跑 —— 见
        # `test_dual_leg_cases_are_not_false_red`（它证明**不红**，方向与注入表相反）。
        "⑫c 用例源一个都没加载（`CASES_DIR` 漂移）⇒ 判据 12 红（fail-closed，不空跑恒绿）": (
            "case:chat.yml",
            lambda s: s + "\n# 注入（判据 12 ⑫c 的锚点，见下方 sources 抹除）\n",
            problems_cases_expect_unreachable_tools,
        ),
    }


#: 判据 12 的注入语料（合成用例：**只在内存里**进 World —— ⑫c 用 `[]` 把 `case:` 源整片抹掉）。
_INJECTED_CASE_ORPHAN_WRITE = '''
  - id: ZZ-INJ-WRITE
    persona: mibao
    user_inputs:
      - "注入：下单"
    expectations:
      - tool: order_create
    skip_reason: ""
'''
_INJECTED_CASE_C_END_TOOL = '''
  - id: ZZ-INJ-CEND
    persona: mibao
    user_inputs:
      - "注入：C 端专属工具"
    expectations:
      - tool: aftersale_create
    skip_reason: ""
'''


def test_every_judgement_can_go_red() -> None:
    """**每条**判据都要有能单独变红的注入（改坏必红、还原必绿）。"""
    _covered = {fn for _key, _mutate, fn in _injections().values()}
    _missing = sorted(label for label, fn in JUDGEMENTS.items() if fn not in _covered)
    _orphan = sorted(
        label for label, (_k, _m, fn) in _injections().items() if fn not in JUDGEMENTS.values()
    )
    assert not _missing and not _orphan, (
        "判据表与注入表必须**互相覆盖**：缺注入 ⇒ 该判据永远不会红（空断言）；"
        f"\n  仅有判据、无注入：{_missing}\n  注入指向未登记的判据：{_orphan}"
    )
    base_sources = _source_map()
    base_world = World(base_sources)
    green = {label: fn(base_world) for label, fn in JUDGEMENTS.items()}
    assert all(not v for v in green.values()), (
        "对照组：未注入时全部判据必须全绿（否则红证无从归因）：\n"
        + "\n".join(f"  【{k}】{v[:2]}" for k, v in green.items() if v)
    )
    for label, (key, mutate, judgement) in _injections().items():
        sources = dict(base_sources)
        sources[key] = mutate(sources[key])
        assert sources[key] != base_sources[key], (
            f"{label}：注入没生效（锚点失配）—— 同步本判据"
        )
        if label.startswith("⑫c"):
            # ⑫c 的语义 = 「用例源整片没加载」⇒ 抹掉全部 `case:` 源（注入语料本身不改）
            sources = {k: v for k, v in sources.items() if not k.startswith("case:")}
        sources.update(_synthetic_tools(label))
        mutated = World(sources)
        assert judgement(mutated), f"{label}：判据没有变红 ⇒ 它是空断言"


#: 注入用**合成工具**（只在内存里存在，不落盘）：真仓里不存在「非只读且无确认门禁」的 B 端工具
#: —— 那正是判据 8 要防的形态 ⇒ 只能靠合成对象证明判据**真的会红**（否则判据 8 是空断言）。
_SYNTHETIC_WRITE_TOOL = """\
from app.tools.base import BaseTool, ToolResult


VALID_ACTIONS = {"list", "mark_all"}


class ZzzPlantedWriteTool(BaseTool):
    name = "zzz_planted_write_tool"
    description = "注入用合成工具（非只读、无确认门禁）"
    read_only = False

    async def execute(self, context, action="list", **kwargs) -> ToolResult:
        return ToolResult(success=True, message="noop")
"""


def _synthetic_tools(label: str) -> dict[str, str]:
    """按注入标签补上合成源：只有 ⑧b 需要（其余注入都打真文件）。"""
    if label.startswith("⑧b"):
        return {"tool:zzz_planted_write_tool.py": _SYNTHETIC_WRITE_TOOL}
    return {}
