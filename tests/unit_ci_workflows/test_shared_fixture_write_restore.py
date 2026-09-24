# case_ids: PR-021, PR-025, PR-007, PR-017, PR-005, PR-009, OR-014
"""**共享夹具的属性写方**必须声明复位手段（issue #4075 的机制半边：L0 判据 + 红证）。

## 病灶（run `35243351675` @`67db87ae`，两条腿同一条断言结论相反）

`PR-021`「把遮光窗帘的米白色散剪规格改成 150 元」改的是**共享夹具** `prod_eval_blackout`
的 SKU 价，**没有任何复位动作**；`PR-025`「把遮光窗帘下架」同理。后果：

| 腿 | `OR-014` | `amount_verify[order_create]` | 同栈是否跑过 `PR-021` |
|---|---|---|---|
| mibao | **红** | 「遮光窗帘」单价 150 ≠ 商品库 168 | 是 |
| xiaobu | 绿 | 同一断言通过 | 否 |

⇒ 差异**在夹具不在 agent**：写方跑完把世界改了，而读方（按名/按价取真值的用例）
看到的是被改过的世界。读方止血（`#4078`：断言真值改成 SKU 感知）只治了"读到什么算对"，
**"世界被改了"这一半必须有机制**。本文件锁的就是机制那一半的**可判定性**。

## 与既有守卫的分工（R1：不重复造门，也不留盲区）

| 守卫 | 管什么 |
|---|---|
| `test_eval_product_name_pollution.py`（#3835） | **商品名**：写方不得写种子名（造副本） |
| `test_eval_preclean_registry.py`（#3781/#3791） | `pre_clean`/`post_clean` 的**类型登记表**一致性 |
| `test_eval_write_site_dispositions.py`（#3807） | runner 里每一处**写调用**的处置（怎么算成功） |
| **本文件**（#4075） | **属性**：写共享夹具的属性 ⇒ 必须声明复位（且复位真的生效/失败可见） |

## 判据三条（各自都有红证）

1. **写面必须归类（fail-closed）**：写工具扫描面 = **当前可达**的写工具（从
   `.github/assertion_taxonomy.py` 推导，见 `WRITE_TOOL_SURFACE`），库里凡落在该面上的期望
   （`(tool, action)` 组合）都必须在 `PRODUCT_ATTR_WRITERS` 里显式归类 ——
   新增工具 / 新增写 action **未归类即红**。防的是"新写方悄悄出现、判据还是旧地图"
   （`migao-dev-flow` §19.1：基于错误真相模型写出的护栏 = 永远红 / 永远被豁免的空判据）。
2. **可复位属性必须声明复位**：用例 `user_inputs` 点名种子商品（名字**现读 fixtures**）
   且写了**已有复位类型**的属性（属性↔类型的关系**现读 runner**）⇒ 必须声明该复位
   （`post_clean`，或裁定允许的 `pre_clean` 等价复位）。
3. **尚无复位类型的属性必须登记为缺口（双向相等，只许缩短）**：写这些属性的用例必须出现在
   `REGISTERED_RESTORE_GAPS` 里，且每条带跟随 issue 号（R4 的两个出口：
   本次修掉 / 开独立 issue）——**不是白名单**：新增一条即红，修好一条未同步台账也红。

## 为什么口径是"属性写方"而不是"带写期望"

裁定的原文是「凡 `user_inputs` 点名种子商品且带写期望的用例」。直接按
`assertion_taxonomy.is_write_case` 取"写期望"（#5247 前 **49 条**、#5247 后 **15 条**），
其中绝大多数是 `order_create`（**下单**不改商品属性，它只是**引用**该商品）—— 对它们要求
"复位"是无对象的假红（R2：判据不得拦掉原本合法的输入）。故按**结构性**三层收窄，每层都可复算：

```
种子商品名（fixtures/*.sql 现算）
  ∩ user_inputs（点名了它）
  ∩ **活写方**的期望（tool ∈ 写工具扫描面；拆 ` or `，与 runner 同口径）
  → 属性（(tool, action) → 属性键，显式登记）
```
⇒ 收窄后**命中 0 条**（活写方 = `order_create` / `aftersale_create` / `notification_manage` /
`settings_manage`，都不触达商品属性）。**不适用域负例**见 `test_order_only_cases_are_not_in_scope`
（`order_create` 用例**不得**被判红 —— 库里 13 条点名种子商品的下单用例靠这条口径不被假红）。

## #5247 改判（2026-09-23 用户裁定「B 端米宝只读化」）：真值面为什么变了

**原口径**：第 3 层手抄「5 个商品写工具」（`product_manage` / `product_update` / `sku_update` /
`inventory_manage(adjust)` …），据此命中 **12 条**「写共享夹具属性」的用例。

**前提被证伪**：这几个工具在 #5247 里**全部退场** —— `product_manage` / `product_update` /
`sku_update` 从 B 端全部 skill 解绑（工具类与注册行仍在、C 端绑定未动，但两侧工具集都不可达
⇒ 幽灵写工具，**不再是写方**），`inventory_manage` 收窄为只读 `{query, low_stock_alert}`、
写 action `adjust` 已从源码删除。对应用例也已改判 / 退役：`PR-005` 改判为「只读库存台账 +
入库批次」（不再写 stock）；`PR-009` / `PR-010` / `PR-017` / `PR-026` / `PR-027` / `CH-006` 退役
（写商品属性的断言已删）⇒ 那 12 条的写方**在新事实下不存在**。

**新口径**：① 扫描面**不再手抄**，从 `assertion_taxonomy.WRITE_TOOLS` / `WRITE_TOOL_ACTIONS`
（本仓"写"判定的唯一源，且自身只列**当前可达**的工具）推导；② `PRODUCT_ATTR_WRITERS` 只登记
库里真实出现的活写方 key；③ 判据 ②③ 在真实库上命中 **0 条** ⇒ 台账置 `{}`
（7 条旧条目的逐条留档写在该常量的 docstring 里）。

**为什么不是放宽**：判据机制一条没删 —— 扫描面非空（防空转下界）、未归类的活写方即红、
触达可复位属性却未声明复位即红、无复位类型的属性未登记即红、台账有陈旧条目即红，
每条都有**能真的变红**的红证，且红证已重新锚定到当前可达的写方（整工具写 = `order_create`，
action 级写 = `notification_manage(mark_read)`）。消失的是"写方本身"这个被测对象，不是判别力。

## 为什么不能只靠"读方止血"（#4078 已做）

读方改真值口径治的是"读到 150 时怎么判"；写方不改世界，下一条读该商品的用例
（如 `PR-001` 的 `product_search` 非空断言、`OR-014` 的接地真值）照样看到脏值。
两侧都要有 —— 本文件锁写方那一侧，且**同时**锁"复位真的生效"（不止"声明了"）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
FIXTURES_DIR = REPO_ROOT / "tests" / "agent_eval" / "fixtures"


def _load_runner():
    """导入 `local_runner`（L0 job 只装 pytest+pyyaml → 缺 httpx 时注入最小替身）。"""
    sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件里的 HTTP 一律走 `_FakeHttpx`")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


def _taxonomy():
    """载入 `.github/assertion_taxonomy.py`（**种子真值解析**的既有实现，不复制第二套）。"""
    spec = importlib.util.spec_from_file_location(
        "assertion_taxonomy", REPO_ROOT / ".github" / "assertion_taxonomy.py")
    tax = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tax)
    return tax


def seed_product_names() -> set:
    """种子商品名的**现算真值**（`INSERT INTO products(...)` 的 `name` 列）。

    为什么不硬编码：硬编码清单会与种子漂移，而 `CU-003`（#3832）的形态正是
    「种子改了名、用例没跟上」—— 唯一能结构性发现它的办法是**每次从种子现算**
    （口径与 `assertion_taxonomy.extract_seed_catalog` 同一处，不另写解析器）。
    """
    sql = "".join(p.read_text(encoding="utf-8") for p in sorted(FIXTURES_DIR.glob("*.sql")))
    return set(_taxonomy().extract_seed_catalog(sql).get("products") or set())


def _all_cases() -> list:
    out = []
    for f in sorted(CASES_DIR.glob("*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for c in doc.get("cases") or []:
            c = dict(c)
            c["__file"] = f.name
            out.append(c)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 一、写面登记表（**扫描面从单一真相源推导**；分类表只登记库里出现的活写方）
# ══════════════════════════════════════════════════════════════════════════════

#: **写工具扫描面** = 当前**可达**的写工具集合。
#: 真值锚点 = `.github/assertion_taxonomy.py` 的 `WRITE_TOOLS`（整工具即写）∪
#: `WRITE_TOOL_ACTIONS`（工具级写、只有部分 action 是写）—— 该模块是**本仓"写"判定的唯一源**
#: （`is_write_expectation` 与它同源），且它自己只列当前可达的工具（幽灵写工具由
#: `test_case_trust_gate.py::test_write_tool_sets_only_name_reachable_tools` 兜底）。
#: ⚠️ 2026-09-24（issue #5247，用户裁定 2026-09-23「B 端米宝只读化」）：**原口径**是本地手抄
#: 一份「5 个商品写工具」（`product_manage` / `product_update` / `sku_update` /
#: `inventory_manage` / …）。那份清单已被 #5247 证伪：前三个从 B 端全部 skill 解绑
#: （两侧工具集都不可达 ⇒ 不是写方），`inventory_manage` 收窄为只读（写 action `adjust`
#: 从源码删除）⇒ 手抄清单**全部失真**（第二份地图必然漂移）。
#: **新口径**：一律从 taxonomy 推导。**判别力为什么还在**：扫描面**非空**（防空转下界见
#: `test_scan_surface_covers_the_known_writers`）+ "新写方出现 ⇒ 必须归类"这条闸仍由判据 ①
#: 把着（活写方的新 action 未归类即红，红证见 `TestWriteSurfaceIsClassified`）。
WRITE_TOOL_SURFACE: frozenset = (
    frozenset(_taxonomy().WRITE_TOOLS) | frozenset(_taxonomy().WRITE_TOOL_ACTIONS))

#: `(tool, action)` → **属性键**（`""` = 是写方但**不改共享夹具的属性** ⇒ 判据 ②③ 都不适用）。
#: `action` 取 `""` 表示期望里没声明 action（`is_write_expectation` 对 action 级写工具**保守判写**）。
#: ⚠️ 只登记**库里真实出现**的活写方 key（当前 3 条具体 action + 2 条"未声明 action"）——
#: 每个 key 都要有人回答"它改的是不是共享夹具"；**未在此归类 ⇒ 判据 ① 直接红**。
#: 为什么不把这张表也整体推导：推导出来等于"永远已归类"= 判据 ① 变空壳 ——
#: "这个新写方改不改共享夹具"必须由人判定，只能显式登记。
PRODUCT_ATTR_WRITERS: dict = {
    # ── 整工具写方（taxonomy 的 `WRITE_TOOLS`）──────────────────────────────
    # 下单：**引用**商品，不改商品属性（不适用域负例见 test_order_only_cases_are_not_in_scope）。
    ("order_create", ""): "",
    # 建售后工单：写的是**工单实体**，不触达商品属性。
    ("aftersale_create", ""): "",
    # ── action 级写方（taxonomy 的 `WRITE_TOOL_ACTIONS`）────────────────────
    # 改密码：写的是**账号设置**，不触达商品属性（库里唯一在册的 settings 写方 = ST-003）。
    ("settings_manage", "change_password"): "",
    # 未声明 action 的 action 级写工具：taxonomy **保守判写**，但"改的是哪个属性"**不可判定**
    # ⇒ 单列 `unknown`（走台账路径 = 可见），而不是被静默当成"不改共享夹具"。
    # 判别力自证见 test_unknown_action_attr_lands_in_the_ledger_path。
    ("settings_manage", ""): "unknown",
    ("notification_manage", ""): "unknown",
    # ⚠️ **故意**不登记 notification_manage 的**具体**写 action（`mark_read` / `create` /
    #    `delete` / `mark_all_read`）：它们一出现在用例里就是"新写方"⇒ 判据 ① 先红、逼人判定
    #    （红证 test_red_proof_unclassified_action_is_caught 用的就是 `mark_read`）。
}

#: **留档**（#4075 / #4128 时代的商品属性写方 → 属性键），**已不是活写方**。
#: 为什么留：runner 的 `RESTORE_TYPES_BY_ATTR`（`status` / `sku_price`）与用例库里仍在的
#: 3 条 `post_clean` 声明（PR-007 / PR-025 / PR-021）指向这些属性 —— 本表是
#: 「runner 新增复位类型 ⇒ 必须在写面词表里有出处」这条**反向判据**的锚点
#: （见 `test_runner_restore_attrs_have_a_known_writer_surface`）。
#: ⚠️ 它**不参与**判据 ① 的活写方归类（扫描面不看它），也**不得**再往里加东西 ——
#: 新增写方一律走「taxonomy → `WRITE_TOOL_SURFACE` → `PRODUCT_ATTR_WRITERS`」这条链。
RETIRED_ATTR_WRITERS: dict = {
    ("sku_update", ""): "sku_price",                  # 单独 SKU 调价（PR-021 的写方）
    ("product_manage", "toggle_status"): "status",    # 上下架（PR-007 / PR-025 的写方）
    ("product_update", ""): "product_attr",           # base_price / allow_return_restock / …
    ("product_manage", "update"): "product_attr",     # images / 字段级更新
    ("inventory_manage", "adjust"): "stock",          # 出库（PR-005 的写方）
    ("product_manage", "create"): "",     # 建品：写**新对象**，不触达共享夹具属性（#3835 守卫单独治）
    # ⚠️ 随 #4371（商品↔加工项解耦）退场的两条：`("product_processing_item_manage",
    #    "add"/"")` → `processing_items` —— 工具退场、该属性键也不再有写方，故不留条目。
}

#: **存量**「写共享夹具属性、但当前没有复位类型」的缺口台账（**双向相等**：新增即红、陈旧即红）。
#: 出口两个（`migao-dev-flow` §20 R4）：本次修掉 / 开独立 issue —— 台账条目必须带 issue 号。
#: ⚠️ 2026-09-24（#5247）：**本台账现为空**，这是真值面**复算**的结果（不是清空销账）。
#: 原 7 条逐条留档 —— 它们各自为什么不再在册：
#:   · `PR-005` —— 已改判为「只读库存台账 + 入库批次」（`stock_ledger_query` /
#:     `inbound_order_query(batches)`），**不再写 stock**（写 action `adjust` 已从源码删除）；
#:   · `PR-009` —— 已随 #5247 退役：`product_update`（改 base_price）从 B 端解绑，写商品属性的断言已删；
#:   · `PR-010` —— 已随 #5247 退役（同上，`product_update` 写面）；其 processing_items 一侧
#:     早在 #4371 就随「商品不再持有加工项」退场；
#:   · `PR-017` —— 已随 #5247 退役（`product_update` / `product_manage` 写 allow_return_restock
#:     的断言已删）；
#:   · `PR-026` / `PR-027` —— 已随 #5247 退役（`product_manage(action=update, images)` 写主图
#:     的断言已删）；
#:   · `CH-006` —— 已随 #5247 退役（改价 199 的断言改成 `product_search` / `product_detail` 只读核对）。
#: 证据链（不是"清空即销账"）：复算双向相等 + 新增缺口红证 + 陈旧条目红证 +
#: `test_retired_writers_are_no_longer_seen_as_writers`（留档的写方真的不再被判据看见）。
REGISTERED_RESTORE_GAPS: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# 二、纯函数判据（每条都能被合成用例直接喂 —— 红证不依赖真实用例库）
# ══════════════════════════════════════════════════════════════════════════════

def live_write_expectations(case: dict) -> list:
    """用例里**当前可达写方**的写期望 → `[(tool, action)]`（排序去重，纯函数）。

    扫描面 = `WRITE_TOOL_SURFACE`（从 `assertion_taxonomy` 推导，见其 docstring）。
    ⚠️ 拆 ` or `：字符串形态的期望（`["direct_reply or order_create or interact"]`，`CH-009`
    就是它）由 `expectation_tools` 拆过一次，而 dict 形态里的 ` or `（旧形态
    `{"tool": "product_update or product_manage"}`）由本函数拆 —— 与 runner 的
    `check_expectation` 同口径；不拆的话真实写方会从扫描面里消失（判据漏掉病灶 = 假绿）。
    """
    out = set()
    tax = _taxonomy()
    for tool, args in tax.expectation_tools(case):
        for part in str(tool).split(" or "):
            t = part.strip()
            # ① 只算**当前可达的写工具**（扫描面，见 WRITE_TOOL_SURFACE）；② 只算**写** ——
            #    `inventory_manage(query)` 这类只读 action 由 taxonomy 的
            #    `is_write_expectation` 判定，不自己再写一份"哪些 action 算写"（两份口径必然漂移）。
            if t in WRITE_TOOL_SURFACE and tax.is_write_expectation(t, args or {}):
                out.add((t, str(((args or {}).get("action")) or "")))
    return sorted(out)


def live_writer_keys(cases: list) -> set:
    """**防空转下界**：全库解析出的活写方 `(tool, action)` 集合（空 = 判据在静默空跑）。"""
    return {k for c in cases or [] for k in live_write_expectations(c)}


def unclassified_live_writes(cases: list) -> dict:
    """**判据 ①**：未归类的 `tool(action)` → 声明它的用例（fail-closed）。

    扫描面 = **全库**（不限点名种子商品的用例）：新工具/新写 action 一出现就得归类，
    否则"它改的是不是共享夹具"这件事无人回答，判据 ②/③ 也就无从适用。
    """
    out: dict = {}
    for c in cases or []:
        for key in live_write_expectations(c):
            if key not in PRODUCT_ATTR_WRITERS:
                label = f"{key[0]}({key[1] or '无 action'})"
                out.setdefault(label, []).append(str(c.get("id") or "?"))
    return out


def named_seed_products(case: dict, names=None) -> set:
    """用例 `user_inputs` 里**点名**的种子商品名集合（纯函数）。

    ⚠️ 只看 `user_inputs`（裁定的判据），**不看** `pre_clean` / `expectations` 的定位键 ——
    那些位置的"名字"属于 §18.3 的不可变引用判据，不是本判据的面。
    """
    names = seed_product_names() if names is None else names
    txt = json.dumps(case.get("user_inputs") or [], ensure_ascii=False)
    return {n for n in names if n in txt}


def touched_attrs(case: dict, names=None) -> set:
    """本用例在**共享夹具**上触达的属性集合（点名种子商品 ∧ 活写方）。

    `""`（不改共享夹具属性）与 `"unknown"`（action 未定型 ⇒ 改哪个属性不可判定）都**不是**
    "可复位属性"，但两者处置不同：前者无事可做，后者进台账（可见）—— 属性键的定义见
    `PRODUCT_ATTR_WRITERS`。
    """
    if not named_seed_products(case, names):
        return set()
    return {PRODUCT_ATTR_WRITERS[k] for k in live_write_expectations(case)} - {""}


def runner_restore_map() -> dict:
    """属性 → 复位类型（**现读 runner**；守卫不复制一份，见判据 ② 的 docstring）。"""
    return dict(getattr(lr, "RESTORE_TYPES_BY_ATTR", {}) or {})


def declared_restore_types(case: dict) -> set:
    """用例**声明**的复位类型集合 = `post_clean` ∪ `pre_clean` 里的复位族动作。

    裁定原文是「必须声明复位手段（`post_clean` 或 `pre_clean` 的等价复位）」⇒ 两者都收。
    差别（写在用例注释里、不假装本判据能判）：`post_clean` 把世界**归零**（治跨用例污染），
    `pre_clean` 只保证**自己**重试前置等价 —— 故修法一律推荐 `post_clean`。
    """
    out = set()
    for field in ("post_clean", "pre_clean"):
        for spec in (case.get(field) or []):
            if isinstance(spec, dict) and str(spec.get("type") or ""):
                out.add(str(spec["type"]))
    return out


def missing_restores(cases: list, names=None) -> dict:
    """**判据 ②**：写了可复位属性、却没声明对应复位类型的用例 → `{cid: [属性]}`。"""
    save_map = runner_restore_map()
    out: dict = {}
    for c in cases or []:
        need = {a for a in touched_attrs(c, names) if a in save_map}
        if not need:
            continue
        declared = {save_map[a] for a in need if save_map[a] in declared_restore_types(c)}
        miss = sorted(a for a in need if save_map[a] not in declared)
        if miss:
            out[str(c.get("id") or "?")] = miss
    return out


def unregistered_restore_gaps(cases: list, names=None) -> dict:
    """**判据 ③**：写"尚无复位类型"的属性、却没登记台账的用例（新缺口 ⇒ 红）。"""
    save_map = runner_restore_map()
    out: dict = {}
    for c in cases or []:
        gap_attrs = sorted(a for a in touched_attrs(c, names) if a not in save_map)
        if gap_attrs:
            out[str(c.get("id") or "?")] = gap_attrs
    return out


def _writer_attr_vocabulary() -> set:
    """写面**属性词表** = 活写方分类值 ∪ 留档词表（去掉 `""`）—— 反向判据的比对面。"""
    return {a for a in (*PRODUCT_ATTR_WRITERS.values(), *RETIRED_ATTR_WRITERS.values()) if a}


def orphan_restore_attrs() -> list:
    """runner 里**没有写面出处**的复位属性（反向漏判：要求声明会指向没人能声明的目标）。"""
    vocab = _writer_attr_vocabulary()
    return sorted(a for a in runner_restore_map() if a not in vocab)


def ledger_new_entries(cases: list, names=None) -> list:
    """台账的**新增方向**红名单：复算出的缺口没登记在册（fail-closed）。"""
    live = unregistered_restore_gaps(cases, names)
    return sorted(set(live) - set(REGISTERED_RESTORE_GAPS))


def ledger_stale_entries(cases: list, names=None) -> list:
    """台账的**陈旧方向**红名单：登记在册却已不复现（只许缩短，防债务僵化）。"""
    live = unregistered_restore_gaps(cases, names)
    return sorted(set(REGISTERED_RESTORE_GAPS) - set(live))


def entries_without_issue(ledger: dict) -> list:
    """没有跟随 issue 号的台账条目（R4：登记不得变成静默出口）。"""
    import re
    return sorted(cid for cid, why in (ledger or {}).items()
                  if not re.search(r"#\d{3,}", str(why)))


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据 ⓪：种子真值 + 扫描面自证（防"绿了但没跑"）
# ══════════════════════════════════════════════════════════════════════════════

class TestSeedTruthAndScanSurface:
    def test_seed_names_are_derived_and_non_empty(self):
        """前提：种子商品名**现算**得到（解析器失效 ⇒ 判据 ②③ 会静默空跑）。"""
        names = seed_product_names()
        assert names, "从 fixtures/*.sql 解析不到任何商品名 —— 判据会空跑（fail-closed）"
        assert {"遮光窗帘", "北欧风窗帘", "夏日清风窗帘"} <= names, (
            f"小布栈的三个种子商品名必须都在派生集合里（解析口径变了？）：{sorted(names)}")

    def test_two_independent_seed_sources_agree(self):
        """与 #3835 守卫的硬编码清单**互校**：两份真值集合必须相等。

        为什么值得锁：两处口径漂移会让"哪些名字算种子商品"变成两份地图
        （一处判红一处判绿），而这类漂移**不会让任何东西变红** —— 只能靠互校。
        """
        sibling = Path(__file__).parent / "test_eval_product_name_pollution.py"
        spec = importlib.util.spec_from_file_location("_sib_pollution", sibling)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert set(mod.SEED_PRODUCT_NAMES) == seed_product_names(), (
            "两处种子商品名真值集合不一致："
            f"本文件（现算 fixtures）={sorted(seed_product_names())} / "
            f"#3835 守卫（硬编码）={sorted(mod.SEED_PRODUCT_NAMES)}")

    def test_write_tool_surface_is_derived_from_the_taxonomy(self):
        """**扫描面必须来自单一真相源**（不是本地手抄的第二份清单）。

        原口径（#4075）：本地手抄「5 个商品写工具」。**#5247 证伪**：那 5 个里
        `product_manage` / `product_update` / `sku_update` 已从 B 端全部 skill 解绑、
        `inventory_manage` 收窄为只读 ⇒ 手抄清单与实际写方**全部脱节**。
        新口径：扫描面 == `assertion_taxonomy.WRITE_TOOLS ∪ WRITE_TOOL_ACTIONS`（唯一真相源）。
        判别力：谁把扫描面改回手抄清单（或往 taxonom 之外加料）⇒ 本条立刻红。
        """
        tax = _taxonomy()
        assert WRITE_TOOL_SURFACE == (
            frozenset(tax.WRITE_TOOLS) | frozenset(tax.WRITE_TOOL_ACTIONS)), (
            f"扫描面与 taxonomy 不一致：{sorted(WRITE_TOOL_SURFACE)}")
        assert {"order_create", "aftersale_create"} <= WRITE_TOOL_SURFACE, (
            "整工具写方（C 端下单 / 建工单）不在扫描面里 —— 判据 ① 会漏掉它们")
        assert not ({"product_manage", "product_update", "sku_update", "inventory_manage",
                     "order_manage", "processing_item_manage"} & WRITE_TOOL_SURFACE), (
            "#5247 已退场的写工具仍在扫描面里 ⇒ 判据会按**旧地图**判（幽灵写方）")

    def test_scan_surface_covers_the_known_writers(self):
        """**扫描面自证**：当前**存在**的写方必须被 `live_write_expectations` 认出来。

        否则判据恒绿（`migao-acceptance`「绿了但没跑」）。
        原口径：拿 PR-021 / PR-025 / PR-007 / PR-017 / PR-005 的写期望当"识别力证据"。
        **#5247 证伪**：那 5 条的写工具已全部退场（PR-017/PR-005 改判为只读、
        PR-021/PR-025/PR-007 的写 action 已从源码删除）⇒ 它们不再是写方证据。
        新口径（三类都钉住，取**真实用例库**）：
          ① 整工具写 —— `CH-009` 的 ` or ` 形态字符串期望里必须析出 `order_create`；
          ② 整工具写 —— `AS-003` 的 `after_sales_manage or aftersale_create` 里析出 `aftersale_create`；
          ③ action 级写 —— `ST-003` 的 `settings_manage(action=change_password)`；
          ④ action 级写（库内暂无该写法）—— 合成 `notification_manage(mark_read)` 必须被认出；
          ⑤ **防空转下界**：从真实库解析出的活写方集合必须非空（解析失效 ⇒ 红）。
        """
        by = {c["id"]: c for c in _all_cases()}
        assert ("order_create", "") in live_write_expectations(by["CH-009"]), (   # 字符串 ` or ` 必须拆开
            f"判据认不出 CH-009 的整工具写（` or ` 没拆？）：{live_write_expectations(by['CH-009'])}")
        assert ("aftersale_create", "") in live_write_expectations(by["AS-003"]), (
            f"判据认不出 AS-003 的整工具写：{live_write_expectations(by['AS-003'])}")
        assert ("settings_manage", "change_password") in live_write_expectations(by["ST-003"]), (
            "判据认不出 ST-003 的 action 级写"
            f"（写 action 集合没读对？）：{live_write_expectations(by['ST-003'])}")
        fake = {"id": "FAKE-SCAN", "user_inputs": ["遮光窗帘相关的通知都标成已读"],
                "expectations": [{"tool": "notification_manage", "args": {"action": "mark_read"}}]}
        assert ("notification_manage", "mark_read") in live_write_expectations(fake), (
            f"判据认不出 action 级写方：{live_write_expectations(fake)}")
        live = live_writer_keys(_all_cases())
        assert live, "从真实用例库解析不到任何活写方 —— 扫描面失效（判据会静默空跑）"
        assert {k[0] for k in live} >= {"order_create", "aftersale_create", "settings_manage"}, (
            f"真实库的活写方没被认全：{sorted(live)}")


# ══════════════════════════════════════════════════════════════════════════════
# 四、判据 ①：写面必须归类（fail-closed）
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteSurfaceIsClassified:
    def test_every_live_write_is_classified(self):
        """**核心**：活写方的每个 `tool(action)` 写期望都已归类（fail-closed）。

        #5247 后真实库里的活写方 key 只有 3 个具体写 + 2 个"未声明 action"的保守判写口子
        （见 `PRODUCT_ATTR_WRITERS`）—— 少，但**每一个都必须有人回答**"改不改共享夹具"。
        """
        bad = unclassified_live_writes(_all_cases())
        assert bad == {}, (
            "出现**未归类**的活写方 —— 它改的是不是共享夹具没人回答，"
            "判据 ②③（要不要复位）因此无从适用。请在 PRODUCT_ATTR_WRITERS 显式归类：\n  "
            + "\n  ".join(f"{k} ← {v}" for k, v in sorted(bad.items())))

    def test_red_proof_unclassified_action_is_caught(self, monkeypatch):
        """**红证 ①（action 级写方）**：没归类的写 action ⇒ 判据必红。

        原口径用 `product_manage(action=delete)`；**#5247 证伪**：该工具已不是写工具
        （扫描面看不见它）⇒ 换成当前可达的 action 级写方 `notification_manage(mark_read)`
        （taxonomy 认它是写 action，分类表**故意**不登记具体 action）。
        """
        fake = [{"id": "FAKE-1", "user_inputs": ["遮光窗帘相关的通知都标成已读"],
                 "expectations": [{"tool": "notification_manage", "args": {"action": "mark_read"}}]}]
        assert unclassified_live_writes(fake) == {"notification_manage(mark_read)": ["FAKE-1"]}, (
            "未归类的 action 被放过了 —— 新写方会悄悄出现（判据变空壳）")
        # 负例（证明上面那声红来自"未归类"，不是判据恒红）：登记后即绿
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, ("notification_manage", "mark_read"), "")
        assert unclassified_live_writes(fake) == {}, "已归类的写方仍被判红 ⇒ 判据恒红"

    def test_red_proof_unclassified_action_of_a_whole_tool_writer_is_caught(self):
        """**红证 ①（整工具写方）**：整工具写方带一个未归类的 action ⇒ 判据必红。

        原口径用 `sku_update(action=bulk)`；**#5247 证伪**：`sku_update` 已解绑、
        不在扫描面里 ⇒ 换成当前可达的整工具写方 `order_create`（同一缺陷形态：
        "已登记写工具出现新 action 必须被拦"）。
        """
        fake = [{"id": "FAKE-3", "user_inputs": ["把遮光窗帘下单"],
                 "expectations": [{"tool": "order_create", "args": {"action": "bulk"}}]}]
        assert unclassified_live_writes(fake) == {"order_create(bulk)": ["FAKE-3"]}, (
            "已登记写工具的新 action 没被拦（判据 ① 只对新工具生效？）")

    def test_red_proof_ghost_tool_is_invisible_by_design(self):
        """**留档 / 边界**：已退场的写工具**不被**扫描面看见 —— 这是有意的口径。

        扫描面 = **当前可达**的写方（见 `WRITE_TOOL_SURFACE` 的 docstring）。#5247 把
        `product_manage` / `product_update` / `sku_update` 从 B 端解绑（两侧工具集都不可达）
        ⇒ 它们不再是写方，本判据看不见它们（这就是本文件在真实库上"少了几条"的原因）。
        口径的另一半由 taxonomy 的 `test_write_tool_sets_only_name_reachable_tools` 兜底：
        新增写工具必须先在 taxonomy 里登记，否则它**不是**"可达写方"。
        判别力没有丢：**活**写方的新 action 仍会被判据 ① 拦住（见上面两条红证）。
        """
        fake = [{"id": "FAKE-2", "user_inputs": ["改价"],
                 "expectations": [{"tool": "product_price_bulk_update"}]}]
        assert live_write_expectations(fake[0]) == [], (
            "taxonomy 之外的未知工具被当成写方了（扫描面漂移？）")
        ghost = [{"id": "FAKE-2b", "user_inputs": ["把遮光窗帘删掉"],
                  "expectations": [{"tool": "product_manage", "args": {"action": "delete"}}]}]
        assert live_write_expectations(ghost[0]) == [], (
            "已解绑的工具仍被算成写方 ⇒ 判据按旧地图判（幽灵写方）")

    def test_red_proof_real_library_loses_a_row_and_goes_red(self, monkeypatch):
        """**红证 ①（真实用例库）**：把 `order_create` 那一行从分类表里删掉 ⇒ 真实库立刻红。

        证明分类表**确实**覆盖着库里的活写方（不是只在合成用例上有效）：库里有 13 条点名
        种子商品的下单用例 + CH-009/CH-012 等 —— 删一行就成串报红。
        """
        monkeypatch.delitem(PRODUCT_ATTR_WRITERS, ("order_create", ""))
        bad = unclassified_live_writes(_all_cases())
        assert "order_create(无 action)" in bad and len(bad["order_create(无 action)"]) >= 5, (
            f"分类表少一行，真实库却没红 ⇒ 扫描面没扫到真实库？{bad}")


# ══════════════════════════════════════════════════════════════════════════════
# 五、判据 ②：可复位属性必须声明复位（本单的主判据）
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedFixtureWritersDeclareRestore:
    """判据 ②：写共享夹具**可复位属性**的活写方必须声明复位。

    ⚠️ 2026-09-24（#5247）：本判据在**真实库上命中 0 条** —— 活写方（`order_create` /
    `aftersale_create` / `notification_manage` / `settings_manage`）都不触达商品属性
    ⇒ 没有"必须声明复位"的对象。**这不是放宽**：机制照旧可红，只是被测对象（商品属性写方）
    已被 #5247 删除。为了证明机制仍活着，下面的红证把"触达可复位属性"这一格**注入**到
    当前可达的写方上（原口径直接拿 PR-021 / PR-025 / PR-007 当写方，那三个写工具已解绑
    ⇒ 前提消失，红证会变成"永远不可能红"的假证）。
    """

    def test_no_shared_fixture_writer_lacks_a_restore(self):
        """**主判据**：写可复位属性的用例都声明了复位（#5247 前：PR-021/PR-025/PR-007 ⇒ 红）。"""
        assert live_writer_keys(_all_cases()), (
            "全库解析不到任何活写方 ⇒ 本判据与判据 ③ 会静默空跑（fail-closed 下界）")
        miss = missing_restores(_all_cases())
        assert miss == {}, (
            "这些用例写了**共享夹具**的可复位属性却没声明复位手段 ⇒ 跑完把世界留给"
            "同栈的下一条用例（#4075 的病灶）：\n  "
            + "\n  ".join(f"{cid}: 缺 {sorted(a)} 的复位" for cid, a in sorted(miss.items()))
            + "\n修法：加 `post_clean: [{type: product_status_restore|sku_price_restore, …}]`"
              "（类型↔属性的关系见 local_runner._CLEAN_TYPES[*].attr）")

    def test_red_proof_whole_tool_writer_without_post_clean_is_caught(self, monkeypatch):
        """**红证 ②（整工具写方）**：整工具写方触达可复位属性、用例又没声明复位 ⇒ 必红。

        原口径：`PR-021` 去掉 `post_clean` ⇒ 红（写方是 `sku_update`）。**#5247 证伪**：
        `sku_update` 已解绑、不再是写方 ⇒ 那声红不再可能出现。新口径：把同一**缺陷形态**
        （写方可复位属性 + 无复位声明）搬到当前可达的整工具写方 `order_create` 上。
        判别力自证：把同一 key 判回"不触达夹具"（= 新真值）⇒ 同一条用例**不红**
        （若这里也红，说明判据恒红 = 空壳）。
        """
        fake = [{"id": "FAKE-4", "user_inputs": ["把遮光窗帘的米白散剪改成 150 元"],
                 "expectations": [{"tool": "order_create"}]}]
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, ("order_create", ""), "sku_price")
        assert missing_restores(fake) == {"FAKE-4": ["sku_price"]}, missing_restores(fake)
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, ("order_create", ""), "")
        assert missing_restores(fake) == {}, (
            "同一用例在「不触达共享夹具」的新真值下也红 ⇒ 判据恒红（判别力失效）")

    def test_red_proof_action_level_writer_without_post_clean_is_caught(self, monkeypatch):
        """**红证 ②（action 级写方 / 状态侧）**：action 级写方触达 `status` 且无复位声明 ⇒ 必红。

        原口径：`PR-025` / `PR-007` 去掉 `post_clean` ⇒ 红（写方是
        `product_manage(toggle_status)`）。**#5247 证伪**：该工具已解绑 ⇒ 换成当前可达的
        action 级写方 `notification_manage(mark_read)`，缺陷形态原样保留。
        """
        fake = [{"id": "FAKE-11", "user_inputs": ["遮光窗帘相关的通知都标成已读"],
                 "expectations": [{"tool": "notification_manage", "args": {"action": "mark_read"}}]}]
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, ("notification_manage", "mark_read"), "status")
        assert missing_restores(fake) == {"FAKE-11": ["status"]}, (
            f"off_sale/状态污染形态未被判红（#4075 的另一半病灶）：{missing_restores(fake)}")

    def test_red_proof_real_library_is_scanned(self, monkeypatch):
        """**红证 ②（真实用例库）**：把整工具写方判成触达 `status` ⇒ 真实库里点名种子商品的
        下单用例**成串**进红名单 —— 扫描面确实扫着真实库，而不是只在合成用例上有效。

        判别力：扫描面若解析不到写方（判据空跑），这里会得到空集合 ⇒ 必红。
        """
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, ("order_create", ""), "status")
        miss = missing_restores(_all_cases())
        assert len(miss) >= 5 and "OR-014" in miss, (
            f"真实库里的活写方没被扫到（判据空跑？）：{sorted(miss)}")

    def test_retired_writers_are_no_longer_seen_as_writers(self):
        """**改判留档**：`REGISTERED_RESTORE_GAPS` 那 7 条的写方在新真值下**不存在**。

        逐条留档（为什么不再在册）见 `REGISTERED_RESTORE_GAPS` 的 docstring；
        这里把"它们真的不再被判据看见"变成机器可判：9 条改判/退役用例的期望里
        **不得**再有活写方。判别力：谁要是把写方加回这些用例（例如重新声明
        `product_manage` 之外的某个活写工具），判据 ①（未归类即红）/②（未声明复位即红）
        会立刻响 —— 台账的"留档"结论随之必须重算。
        """
        by = {c["id"]: c for c in _all_cases()}
        for cid in ("PR-005", "PR-009", "PR-010", "PR-017", "PR-021",
                    "PR-025", "PR-026", "PR-027", "CH-006"):
            got = live_write_expectations(by[cid])
            assert got == [], (
                f"{cid} 仍带着活写方期望 {got} —— 「已改判为只读/已退役」这条留档不再成立，"
                "台账（现为空）必须按新真值重算")

    # ── 不适用域负例（R2：判据不得拦掉原本合法的输入）────────────────────────
    def test_order_only_cases_are_not_in_scope(self):
        """**负例**：`order_create` 用例（点名了种子商品）**不得**被判红。

        #5247 后 `order_create` 是本判据面里唯一的"整工具写"活写方，也是**主要**的不适用域
        （下单只引用商品、不改属性）—— 库里 13 条点名种子商品的下单用例都靠这条口径不被假红。
        """
        fake = [{"id": "FAKE-5", "user_inputs": ["我想买一件遮光窗帘，下单"],
                 "expectations": [{"tool": "order_create"}], "must_succeed": [{"tool": "order_create"}]}]
        assert live_write_expectations(fake[0]) == [("order_create", "")], (
            "下单用例没被认成写方 ⇒ 本负例变成空断言（判据面漏了整工具写方）")
        assert touched_attrs(fake[0]) == set(), (
            "下单用例被算成「写共享夹具」了 —— 它会白要求一份无对象的复位（R2 假红）")
        assert missing_restores(fake) == {} and unregistered_restore_gaps(fake) == {}

    def test_create_own_name_case_is_not_in_scope(self):
        """**负例（改判）**：建**自有名**商品的用例不得被判红。

        原口径用 `product_manage(action=create)`；#5247 后该工具已从 B 端解绑（不可达）
        ⇒ 它在扫描面外，本判据看不见它 —— 同名污染由 #3835 的
        `test_eval_product_name_pollution.py` 单独治（两条判据的适用域不重叠）。
        保留的是这条**不适用域**本身：写自有名对象 ≠ 写共享夹具 ⇒ 判据 ②③ 都不适用。
        """
        fake = [{"id": "FAKE-6", "user_inputs": ["创建商品，名称E2E建品流程样品帘，价格 100"],
                 "namespaces": ["product_name:E2E建品流程样品帘"],
                 "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]}]
        assert live_write_expectations(fake[0]) == [], (
            "已解绑的建品工具被算成活写方了（扫描面漂移？）")
        assert missing_restores(fake) == {} and unregistered_restore_gaps(fake) == {}

    def test_case_not_naming_a_seed_product_is_not_in_scope(self, monkeypatch):
        """**负例**：写自有对象的用例（不点名种子商品）不在本判据的面内。

        原口径用已解绑的 `product_update`；新口径改用**活写方** `order_create`，
        并把"触达可复位属性"注入进去（`sku_price`）—— 这样这条负例只由**一层**决定
        （`user_inputs` 没点名种子商品），而不是"写方本来就不触达夹具"顺带通过（那会变空断言）。
        """
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, ("order_create", ""), "sku_price")
        fake = [{"id": "FAKE-7", "user_inputs": ["把 E2E建品流程样品帘 的价格改成 199"],
                 "expectations": [{"tool": "order_create"}]}]
        assert live_write_expectations(fake[0]) == [("order_create", "")], "写方没被认出来"
        assert touched_attrs(fake[0]) == set(), "不点名种子商品的用例竟被判成写共享夹具（层收窄失效）"
        assert missing_restores(fake) == {}

    def test_pre_clean_equivalent_restore_is_accepted(self, monkeypatch):
        """裁定允许的等价形态：复位声明在 `pre_clean` 里也算"有复位手段"。

        用当前可达的整工具写方 + 注入"触达 `status`"（原口径用已解绑的
        `product_manage(toggle_status)`）—— 缺陷形态与判决口径原样保留。
        """
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, ("order_create", ""), "status")
        fake = [{"id": "FAKE-8", "user_inputs": ["把遮光窗帘下架"],
                 "expectations": [{"tool": "order_create"}],
                 "pre_clean": [{"type": "product_status_restore", "product_keyword": "遮光窗帘"}]}]
        assert missing_restores(fake) == {}, (
            "裁定原文允许 `pre_clean` 的等价复位 —— 判据把它判红 = 与裁定不符")


# ══════════════════════════════════════════════════════════════════════════════
# 六、判据 ③：尚无复位类型的属性必须登记缺口（只许缩短）
# ══════════════════════════════════════════════════════════════════════════════

class TestUnrestorableWritersAreRegisteredGaps:
    """判据 ③：写"尚无复位类型"的属性的用例必须登记台账（**双向相等**，只许缩短）。

    ⚠️ 2026-09-24（#5247）：台账**现为空**（真值面复算的结果，7 条旧条目的逐条留档见
    `REGISTERED_RESTORE_GAPS` 的 docstring）。空台账不等于判据空壳：下面两条红证分别证明
    "新增缺口即红"与"陈旧条目即红"仍能触发，且 `test_gap_ledger_matches_the_library_exactly`
    里还带一条"复算真的跑过"的防空转下界。
    """

    def test_gap_ledger_matches_the_library_exactly(self):
        """存量缺口必须与台账**逐条相等**：新增即红、修好未删也红（清单只许缩短）。"""
        new = ledger_new_entries(_all_cases())
        assert new == [], (
            "出现**未登记**的共享夹具属性缺口（无复位类型）—— 出口只有两个："
            "本次补复位类型并声明 / 开独立 issue 后登记进台账（R4）：\n  "
            + "\n  ".join(f"{cid}: {unregistered_restore_gaps(_all_cases())[cid]}" for cid in new))
        stale = ledger_stale_entries(_all_cases())
        assert stale == [], (
            "台账里的缺口已不复现 ⇒ 必须删除该条（清单只许缩短，防债务僵化）："
            f"{stale}")
        assert live_writer_keys(_all_cases()), (
            "全库解析不到活写方 ⇒ 上面两条断言是因为「什么都没扫到」而空绿（空跑，不是真值）")

    def test_every_gap_entry_names_a_follow_up_issue(self):
        """台账条目**必须带 issue 号** —— 否则"登记"就变成新的静默出口（R4）。

        台账现为空（#5247）⇒ 纯遍历会退化成空断言；故同时用一条合成条目自证判据仍可红
        （判别力：只要 `entries_without_issue` 失效，第二句立刻红）。
        """
        assert entries_without_issue(REGISTERED_RESTORE_GAPS) == []
        assert entries_without_issue({**REGISTERED_RESTORE_GAPS, "FAKE-CID": "没有 issue 号"}) == \
            ["FAKE-CID"], "无 issue 号的条目没被认出来 ⇒ 本判据在空台账下变空壳（假绿）"

    def test_red_proof_new_gap_is_caught(self, monkeypatch):
        """**红证 ③**：活写方触达"无复位类型"的属性、又未登记台账 ⇒ 判据必红。

        原口径用 `inventory_manage(adjust)`（写 `stock`）；**#5247 证伪**：该写 action 已从
        源码删除、工具收窄为只读 ⇒ 换成当前可达的整工具写方 `order_create` 承接同一缺陷形态
        （`stock` 这一属性键不在 runner 的复位族里 ⇒ 走台账路径）。
        """
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, ("order_create", ""), "stock")
        fake = [{"id": "FAKE-9", "user_inputs": ["调整遮光窗帘的库存，出库 3 件"],
                 "expectations": [{"tool": "order_create"}]}]
        assert unregistered_restore_gaps(fake) == {"FAKE-9": ["stock"]}, unregistered_restore_gaps(fake)
        assert ledger_new_entries(fake) == ["FAKE-9"], (
            "新缺口没进红名单 ⇒ 台账的 fail-closed 语义失效")

    def test_red_proof_stale_ledger_entry_is_caught(self, monkeypatch):
        """**红证 ③（反方向）**：台账里留着一条已不复现的条目 ⇒ 判据必红（双向相等）。

        台账现为空，若无这条红证，"陈旧条目即红"这半条语义就是没人跑过的死代码。
        """
        monkeypatch.setitem(REGISTERED_RESTORE_GAPS, "PR-005", "（红证用的合成留档条目 #4128）")
        assert ledger_stale_entries(_all_cases()) == ["PR-005"], (
            "陈旧条目没被认出来 ⇒ 台账会僵化（「只许缩短」这条语义失效）")

    def test_unknown_action_attr_lands_in_the_ledger_path(self):
        """`action` 未声明的 action 级写工具走台账路径（可见），不被当成"不改夹具"。

        taxonomy 对 action 级写工具**缺 action 时保守判写**（见 `is_write_expectation` 的
        docstring）⇒ 分类表把这种 key 记为 `unknown`（"改的是哪个属性"不可判定）。它必须进台账
        （可见、要跟随 issue），而不是被静默当成 `""` —— 否则"未定型写方"会从判据 ②③ 里同时消失。
        判别力：合成一条裸 `notification_manage` + 点名种子商品的用例 ⇒ touched = `{"unknown"}`。
        """
        fake = [{"id": "FAKE-10", "user_inputs": ["处理一下遮光窗帘的通知"],
                 "expectations": [{"tool": "notification_manage"}]}]
        assert live_write_expectations(fake[0]) == [("notification_manage", "")], (
            "缺 action 的 action 级写方没被保守判写（taxonomy 口径变了？）")
        assert touched_attrs(fake[0]) == {"unknown"}, (
            "未定型写方被当成「不改共享夹具」⇒ 它会从两个判据里同时消失（静默）")
        assert unregistered_restore_gaps(fake) == {"FAKE-10": ["unknown"]}, (
            "未定型写方没进台账路径（可见性失效）")


# ══════════════════════════════════════════════════════════════════════════════
# 七、runner 侧登记表与本判据**同一份真值**（防"守卫按旧地图判"）
# ══════════════════════════════════════════════════════════════════════════════

class TestRunnerRegistryIsTheSingleSource:
    def test_restore_types_are_declared_with_phases(self):
        """复位族必须**显式声明阶段**（`pre`/`post`）—— 不允许默认两边都能跑。"""
        assert lr.RESTORE_TYPES_BY_ATTR, ("runner 的 RESTORE_TYPES_BY_ATTR 为空 —— 复位族被删了？"
                                          "本判据会静默变成空壳（fail-closed）")
        for attr, t in lr.RESTORE_TYPES_BY_ATTR.items():
            meta = lr._CLEAN_TYPES.get(t)
            assert meta, f"复位类型 {t} 不在 _CLEAN_TYPES 里（属性 {attr} 无实现）"
            assert "post" in meta["phases"], (
                f"{t} 不能在 post 阶段执行 ⇒ 写方无从声明（#4075 的机制等于没落地）：{meta}")
        assert "product_status_restore" in lr._POSTCLEAN_TYPES
        assert "sku_price_restore" in lr._POSTCLEAN_TYPES
        # #4992 的复位族第二批（订单状态 / 客户档案）：同一条结论通道
        # （`restore_failures` → `completion_verdict`）—— 行为面守卫见
        # `tests/unit_ci_workflows/test_shared_fixture_restore_order_customer.py`。
        assert {"order_status_restore", "customer_profile_restore"} <= lr._POSTCLEAN_TYPES
        assert {"order_status_restore", "customer_profile_restore"} <= lr._PRECLEAN_TYPES

    def test_runner_restore_attrs_have_a_known_writer_surface(self):
        """runner 里的复位属性必须能在**写面词表**里找到出处（反向漏判的堵法）。

        **原口径**：值域取 `PRODUCT_ATTR_WRITERS`（活写方分类表）。**#5247 证伪**：活写方
        只剩订单 / 工单 / 通知 / 设置四类、**都不触达商品属性** ⇒ 活写方值域恒为 `""`，
        按原值域比对会把 runner 的 `status` / `sku_price` 全判成孤儿（满屏假红）。
        **新口径**：值域 = 活写方分类值 ∪ **退场写方留档词表**（`RETIRED_ATTR_WRITERS` ——
        它与仍在库里的 3 条 `post_clean` 声明（PR-007 / PR-025 / PR-021）、runner 的复位族同源）。
        **判别力为什么还在**：runner 新增一个复位类型（比如 `stock`）而词表里没有出处 ⇒ 依旧红
        （红证见 `test_red_proof_orphan_restore_attr_is_caught`）。
        """
        orphans = orphan_restore_attrs()
        assert orphans == [], (
            f"runner 的复位属性 {orphans} 在写面词表里没有对应写方 ⇒ 判据②无从适用"
            f"（词表见 PRODUCT_ATTR_WRITERS / RETIRED_ATTR_WRITERS）")

    def test_registry_is_one_table_shared_by_both_phases(self):
        """**不复制第二套**：`pre`/`post` 的合法类型集合都由 `_CLEAN_TYPES` 派生。"""
        assert isinstance(lr._CLEAN_TYPES, dict) and lr._CLEAN_TYPES
        assert lr._PRECLEAN_TYPES == frozenset(
            t for t, m in lr._CLEAN_TYPES.items() if "pre" in m["phases"])
        assert lr._POSTCLEAN_TYPES == frozenset(
            t for t, m in lr._CLEAN_TYPES.items() if "post" in m["phases"])
        assert isinstance(lr._POSTCLEAN_TYPES, frozenset) and lr._POSTCLEAN_TYPES
        # 动作实现也只有一份（两个阶段入口都调它 —— 见 test_eval_preclean_registry 的实现分支守卫）
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert src.count("async def _run_clean_action(") == 1, "动作实现被复制成两份了"
        assert "await _run_clean_action(token, spec, \"post\")" in src, (
            "post 阶段没有走共用的动作实现体（会漂移成第二套）")

    def test_declared_post_clean_types_exist_in_the_runner(self):
        """用例声明的 `post_clean` 类型必须已在 runner 登记（拼错 ⇒ 这里就红）。"""
        bad = {}
        for c in _all_cases():
            for spec in (c.get("post_clean") or []):
                t = str((spec or {}).get("type") or "")
                if t and t not in lr._POSTCLEAN_TYPES:
                    bad.setdefault(t, []).append(c.get("id"))
        assert bad == {}, f"用例声明了未登记的 post_clean 类型：{bad}"

    def test_red_proof_orphan_restore_attr_is_caught(self, monkeypatch):
        """**红证**：给 runner 加一个"没有写面出处"的复位属性 ⇒ 判据必红。

        （原口径只断言"该属性不在写面表里"，从不真的让判据红 —— 是空断言；本单补齐。）
        """
        monkeypatch.setitem(lr.RESTORE_TYPES_BY_ATTR, "ghost_attr", "ghost_restore")
        assert "ghost_attr" not in _writer_attr_vocabulary()
        assert orphan_restore_attrs() == ["ghost_attr"], (
            f"没有写面出处的复位属性没被认出来：{orphan_restore_attrs()}")


# ══════════════════════════════════════════════════════════════════════════════
# 八、复位动作的**真实分支**（零网络 / 零 LLM：内存商品库 + 罐装 HTTP）
#
# 为什么要有这一组：上面全是静态资产判据，它们不证明"复位真的把值改回去了"。
# 本组让动作走**真实代码路径**（`_run_post_clean` → `_run_clean_action` → `_restore_*`），
# 断言三件事：① 值真的回到种子；② 幂等（本就在种子值时不报错）；③ 失败**可见**。
# ══════════════════════════════════════════════════════════════════════════════

SEED_STATUS = "on_sale"
SEED_PRICE = 168.0


class _Resp:
    def __init__(self, payload=None, status_code: int = 200):
        # `_safe_json` 读 `.content`（不是 `.json()`），照它的口径造
        self.content = json.dumps(payload if payload is not None else {}).encode("utf-8")
        self.status_code = status_code


class _Shop:
    """内存商品库（形状照抄种子：`status` + `skus[colorName/sellingMethod/doorWidth/price]`）。

    `fail_keys` / `ignore_writes` 是两个**失败注入**口子：
      · `fail_keys`     —— 端点返回 500（写失败）；
      · `ignore_writes` —— 写返回 200 但**不落地**（#3807 的"静默空转"形态：
        "2xx ≠ 值已落地"，只有回读校验才抓得到 —— 本组专治这一格）。
    """

    def __init__(self, products=None):
        self.products = products if products is not None else [
            {"id": "prod_eval_blackout", "name": "遮光窗帘", "status": SEED_STATUS,
             "skus": [
                 {"colorName": "米白", "sellingMethod": "bulk_cut", "doorWidth": "2.8",
                  "price": SEED_PRICE},
                 {"colorName": "浅灰", "sellingMethod": "bulk_cut", "doorWidth": "2.8",
                  "price": SEED_PRICE},
             ]},
        ]
        self.calls: list = []
        self.fail_keys: set = set()
        self.ignore_writes = False

    # ── 读面（断言用）──
    def by_id(self, pid):
        return next((p for p in self.products if p["id"] == pid), None)

    def status(self, pid="prod_eval_blackout"):
        p = self.by_id(pid) or {}
        return p.get("status")

    def price(self, color, pid="prod_eval_blackout"):
        p = self.by_id(pid) or {}
        return next((s.get("price") for s in p.get("skus") or []
                     if s.get("colorName") == color), None)

    # ── 行为面（路由用）──
    def should_fail(self, method: str, path: str) -> bool:
        return any(m == method and sub in path for m, sub in self.fail_keys)

    def list_matching(self, keyword: str) -> list:
        return [p for p in self.products if keyword in str(p.get("name") or "")]

    def set_status(self, pid: str, status: str) -> bool:
        p = self.by_id(pid)
        if not p or self.ignore_writes:
            return bool(p)
        p["status"] = status
        return True

    def set_sku_price(self, pid: str, body: dict) -> bool:
        p = self.by_id(pid)
        if not p:
            return False
        if self.ignore_writes:
            return True
        color = str(body.get("color") or "")
        for s in p.get("skus") or []:
            if color and s.get("colorName") != color:
                continue
            s["price"] = body.get("price")
        return True


class _FakeClient:
    def __init__(self, shop: _Shop):
        self.shop = shop

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @staticmethod
    def _path(url) -> str:
        return urlparse(str(url)).path

    async def _handle(self, method: str, url, kw: dict):
        path = self._path(url)
        self.shop.calls.append((method, path))
        if self.shop.should_fail(method, path):
            return _Resp({}, 500)
        if method == "GET" and path == "/api/admin/products":
            kwd = str((kw.get("params") or {}).get("keyword") or "")
            return _Resp({"data": {"items": self.shop.list_matching(kwd)}})
        if method == "GET" and path.startswith("/api/admin/products/"):
            pid = path.rstrip("/").rsplit("/", 1)[-1]
            p = self.shop.by_id(pid)
            return _Resp({"data": p}, 200 if p else 404)
        if method == "PUT" and path.endswith("/status"):
            pid = path.rstrip("/").rsplit("/", 2)[-2]
            ok = self.shop.set_status(pid, str((kw.get("json") or {}).get("status") or ""))
            return _Resp({"data": {}}, 200 if ok else 404)
        if method == "PATCH" and path.endswith("/skus/price"):
            pid = path.rstrip("/").rsplit("/", 3)[-3]
            ok = self.shop.set_sku_price(pid, kw.get("json") or {})
            return _Resp({"data": {}}, 200 if ok else 404)
        return _Resp({}, 404)

    async def get(self, url, **kw):
        return await self._handle("GET", url, kw)

    async def put(self, url, **kw):
        return await self._handle("PUT", url, kw)

    async def patch(self, url, **kw):
        return await self._handle("PATCH", url, kw)

    async def post(self, url, **kw):
        return await self._handle("POST", url, kw)

    async def delete(self, url, **kw):
        return await self._handle("DELETE", url, kw)


class _FakeHttpx:
    """`httpx` 模块替身（零网络）：只提供 runner 用到的 `AsyncClient`。"""

    def __init__(self, shop: _Shop):
        self.shop = shop

    def AsyncClient(self, *a, **k):          # noqa: N802 —— 与 httpx 同名
        return _FakeClient(self.shop)


STATUS_SPEC = {"type": "product_status_restore", "product_keyword": "遮光窗帘"}
PRICE_SPEC = {"type": "sku_price_restore", "product_keyword": "遮光窗帘",
              "color_name": "米白", "selling_method": "bulk_cut", "door_width": "2.8",
              "price": SEED_PRICE}


def _run(spec, phase="post"):
    return asyncio.run(lr._run_post_clean("tok", spec) if phase == "post"
                       else lr._run_pre_clean("tok", spec))


class TestStatusRestore:
    def test_restores_the_fixture(self, monkeypatch):
        """**走真实分支**：被下架（off_sale）⇒ 复位回 on_sale（含回读校验）。"""
        shop = _Shop()
        shop.products[0]["status"] = "off_sale"
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(STATUS_SPEC)
        assert shop.status() == SEED_STATUS, f"复位没生效：{shop.status()} / msg={msg!r}"
        assert ("PUT", "/api/admin/products/prod_eval_blackout/status") in shop.calls, shop.calls
        assert not msg.startswith(lr._POSTCLEAN_BAD_MARKERS), msg
        assert "回读一致" in msg or "已复位" in msg, msg

    def test_is_idempotent(self, monkeypatch):
        """**幂等**：本就在种子值 ⇒ 成功（且**不**发多余的写请求）。"""
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(STATUS_SPEC)
        assert not msg.startswith(lr._POSTCLEAN_BAD_MARKERS), msg
        assert "本就" in msg, f"幂等路径的文案必须点明「本就等于种子值」：{msg!r}"
        assert not [c for c in shop.calls if c[0] == "PUT"], "幂等时不该发写请求"

    def test_missing_target_is_visible(self, monkeypatch):
        """**失败可见**：目标商品不在库里 ⇒ `PRECONDITION_NOT_RESTORED`（进结论）。"""
        shop = _Shop(products=[])
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(STATUS_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert lr.check_postclean_not_applied([msg]) == [msg], "未复位没被折进结论"

    def test_ambiguous_target_is_visible(self, monkeypatch):
        """**失败可见**：命中多件同名 ⇒ 不瞎改（fail-closed，且消息里给出修法）。"""
        shop = _Shop(products=[
            {"id": "p1", "name": "遮光窗帘", "status": "off_sale", "skus": []},
            {"id": "p2", "name": "遮光窗帘", "status": "off_sale", "skus": []},
        ])
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(STATUS_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "不唯一" in msg, msg
        assert not [c for c in shop.calls if c[0] == "PUT"], "目标不唯一时不该写"

    def test_write_failure_is_visible(self, monkeypatch):
        """**失败可见**：写端点 500 ⇒ 标记进结论（不是静默）。"""
        shop = _Shop()
        shop.products[0]["status"] = "off_sale"
        shop.fail_keys.add(("PUT", "/status"))
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(STATUS_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "500" in msg, msg

    def test_silent_noop_is_caught_by_the_readback(self, monkeypatch):
        """**本仓库踩过的形态**（#3807）：写返回 2xx 但**值没落地** ⇒ 必须被回读抓住。

        没有回读校验时这一格是"复位永远空转、日志一片安静"，而后续用例读到脏值。
        """
        shop = _Shop()
        shop.products[0]["status"] = "off_sale"
        shop.ignore_writes = True
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(STATUS_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), (
            f"2xx 但值未落地被当成成功（静默空转复现）：{msg!r}")
        assert "未生效" in msg, msg


class TestSkuPriceRestore:
    def test_restores_the_fixture(self, monkeypatch):
        """**走真实分支**：PR-021 的病灶面 —— 米白/散剪 SKU 被改成 150 ⇒ 复位回 168。"""
        shop = _Shop()
        shop.set_sku_price("prod_eval_blackout", {"color": "米白", "price": 150})
        assert shop.price("米白") == 150
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRICE_SPEC)
        assert shop.price("米白") == SEED_PRICE, f"复位没生效：{shop.price('米白')} / {msg!r}"
        assert shop.price("浅灰") == SEED_PRICE, "同商品其它规格被误改"
        assert ("PATCH", "/skus/price") in [(m, p.rsplit("/", 2)[-1]) for m, p in shop.calls] or \
            any("skus/price" in p for _m, p in shop.calls), shop.calls
        assert not msg.startswith(lr._POSTCLEAN_BAD_MARKERS), msg

    def test_is_idempotent(self, monkeypatch):
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRICE_SPEC)
        assert not msg.startswith(lr._POSTCLEAN_BAD_MARKERS), msg
        assert "本就" in msg, msg
        assert not [c for c in shop.calls if c[0] == "PATCH"], "幂等时不该发写请求"

    def test_missing_price_is_a_config_error(self, monkeypatch):
        """配置错误（缺 `price`）**不是**静默跳过：带阶段化前缀、折进结论。"""
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run({"type": "sku_price_restore", "product_keyword": "遮光窗帘"})
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert lr.check_postclean_not_applied([msg]) == [msg]

    def test_missing_target_is_visible(self, monkeypatch):
        shop = _Shop(products=[])
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRICE_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg

    def test_readback_mismatch_is_visible(self, monkeypatch):
        """写 2xx 但不落地 ⇒ 回读不符 ⇒ 可见（同状态侧的静默空转形态）。"""
        shop = _Shop()
        shop.set_sku_price("prod_eval_blackout", {"color": "米白", "price": 150})
        shop.ignore_writes = True
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRICE_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "未生效" in msg, msg


class TestTwoConsecutiveRuns:
    """**红证 ③**：连续两次运行同一用例，第二次**开始时**夹具是种子原值。

    用假体证明（不必真跑 LLM）：第一次运行里"写方"把夹具改脏（走与 runner 相同的端点），
    用例结束时 `post_clean` 复位 ⇒ 第二次运行的起点 = 种子。
    """

    @staticmethod
    def _pollute(shop: _Shop):
        """模拟**写方**（agent 的工具调用）：PR-021 改 SKU 价 + PR-025 下架。"""
        async def _do():
            async with _FakeClient(shop) as c:
                await c.patch(f"{lr.ADMIN_API}/api/admin/agent/products/prod_eval_blackout/skus/price",
                              headers={}, json={"price": 150, "color": "米白"}, timeout=15)
                await c.put(f"{lr.ADMIN_API}/api/admin/products/prod_eval_blackout/status",
                            headers={}, json={"status": "off_sale"}, timeout=15)
        asyncio.run(_do())

    def test_second_run_starts_from_the_seed_value(self, monkeypatch):
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        # ── 第 1 次运行 ──
        self._pollute(shop)
        assert (shop.status(), shop.price("米白")) == ("off_sale", 150), "夹具没被写脏（夹具写错了？）"
        msgs = asyncio.run(lr._run_clean_specs("tok", [STATUS_SPEC, PRICE_SPEC], "post"))
        assert lr.check_postclean_not_applied(msgs) == [], msgs
        # ── 第 2 次运行的**起点** ──
        assert (shop.status(), shop.price("米白")) == (SEED_STATUS, SEED_PRICE), (
            f"第二次运行看到的不是种子原值：{shop.status()} / {shop.price('米白')}")

    def test_without_post_clean_the_second_run_starts_dirty(self, monkeypatch):
        """**负例**（证明上面的绿不是恒真）：不复位 ⇒ 第二次运行起点就是脏值。"""
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        self._pollute(shop)
        # 不执行 post_clean（模拟"去掉某写方的 post_clean"）
        assert (shop.status(), shop.price("米白")) == ("off_sale", 150), (
            "不复位时夹具竟然自己回到种子值 —— 本组红证失去判别力")


# ══════════════════════════════════════════════════════════════════════════════
# 九、结论层：复位失败**进用例结论**（不是一行日志）
# ══════════════════════════════════════════════════════════════════════════════

class TestPostCleanFailureReachesTheVerdict:
    def test_marker_is_classified_by_failure_atom(self):
        """失败身份必须与 #3807 的价格复位**分属不同原子**（归因不混层）。"""
        msg = f"{lr._POSTCLEAN_NOT_APPLIED}: 商品「遮光窗帘」在售状态复位为 on_sale 失败（HTTP 500）"
        assert lr._failure_atom(msg, lr._CASE_LEVEL_DETAIL) == \
            "precondition_not_restored(post_clean)", lr._failure_atom(msg, lr._CASE_LEVEL_DETAIL)
        legacy = "PRECONDITION_NOT_RESTORED: 价格复位未生效 —— 商品 prod_eva 回读 198.0"
        assert lr._failure_atom(legacy, lr._CASE_LEVEL_DETAIL) == \
            "precondition_not_restored(pre_clean)", "既有 #3807 的身份被改动了（回归）"

    def test_config_error_has_a_phase_specific_prefix(self):
        """`post_clean` 的配置错误前缀必须与 `pre_clean` 分开（归因不指错阶段）。"""
        assert lr._POSTCLEAN_CONFIG_ERR.startswith("post_clean:")
        assert lr._POSTCLEAN_CONFIG_ERR != lr._PRECLEAN_CONFIG_ERR
        assert lr.check_postclean_not_applied([f"{lr._POSTCLEAN_CONFIG_ERR}: 'typo'"])
        assert lr.check_preclean_not_applied([f"{lr._POSTCLEAN_CONFIG_ERR}: 'typo'"]) == [], (
            "post 的配置错误被 pre 的折叠器捞走了 —— 两个阶段会互相误判")

    def test_completion_verdict_blocks_on_restore_failure(self):
        """**红证 ②**：复位失败 ⇒ 结论阻塞（`restore_failures`），**即使用例本身满分**。"""
        msg = f"{lr._POSTCLEAN_NOT_APPLIED}: 商品「遮光窗帘」在售状态复位为 on_sale 失败（HTTP 500）"
        results = [{"case_id": "PR-025", "score": 1.0, "classification": "pass",
                    "restore": [msg]}]
        v = lr.completion_verdict(results, ())
        assert v["ok"] is False, f"复位失败没让结论失败（静默）：{v}"
        assert v["restore_failures"] == ["PR-025"], v
        # 负例：复位成功（无标记）⇒ 不得阻塞（否则判据变成恒红）
        ok = lr.completion_verdict([{"case_id": "PR-025", "score": 1.0,
                                     "classification": "pass",
                                     "restore": ["已复位商品「遮光窗帘」在售状态 → on_sale（回读一致）"]}], ())
        assert ok["ok"] is True and ok["restore_failures"] == [], ok


# ══════════════════════════════════════════════════════════════════════════════
# 十、端到端接线（`run_suite` 真的会跑 post_clean，且**在断言之后**）
#
# 为什么必须端到端：动作单测证明"复位动作对"，静态判据证明"声明齐"，
# 但**没人证明调度器真的调了它** —— 缺这一格，"声明了却没执行"就是下一个静默失效
# （`migao-dev-flow` §20 R5 第 1 条形态：声明无消费）。
# 脚手架口径照 `backend/ai-agent-service/tests/test_eval_preclean_attempt_reset.py`
# （零 LLM / 零网络：`login`/`run_case`/`_close_and_verify_session` 全部替身）。
# ══════════════════════════════════════════════════════════════════════════════

def _attempt_result(score: float, sid: str = "s1") -> dict:
    return {"case_id": "PC-001", "score": score, "rounds": 1, "tool_calls": [],
            "round_trace": [], "passed": 0, "total": 1, "failed": [],
            "final_session_id": sid, "last_error": None, "final_text": ""}


class _SuiteHarness:
    """跑 `run_suite` 的零 LLM 脚手架；`events` 记录 尝试/断言/复位的**发生顺序**。

    `pollute=True`（默认）：替身 `run_case` 里模拟**写方**（agent 的工具调用，走与 runner
    相同的端点）把共享夹具改脏 —— 这正是 #4075 的病灶形态。
    需要注入"复位动作失败"的用例把它设为 False 并自己先把库改脏（否则失败注入会连
    写方的写一起挡掉，测的就不再是复位那一步了）。
    """

    def __init__(self, shop: _Shop, scores=(1.0,), pollute: bool = True):
        self.shop = shop
        self.scores = list(scores)
        self.pollute = pollute
        self.events: list = []

    def install(self, monkeypatch, tmp_path):
        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True, **kw):
            return "sess"

        async def fake_run_case(case, token, session_id):
            self.events.append("attempt")
            if self.pollute:
                # 写方：agent 的工具调用把共享夹具改脏（真实端点 → 假后端）
                await _FakeClient(self.shop).patch(
                    f"{lr.ADMIN_API}/api/admin/agent/products/prod_eval_blackout/skus/price",
                    headers={}, json={"price": 150, "color": "米白"}, timeout=15)
            return _attempt_result(self.scores.pop(0) if self.scores else 1.0)

        async def fake_close_and_verify(case, token, r, session_id):
            self.events.append("verify")     # 断言（含 db_verify/post_session）在此发生

        async def fake_end_session(*a, **k):
            return None

        _real_post_clean = lr._run_post_clean

        async def recording_post_clean(token, spec):
            """记录"复位真的被执行了"这件事 —— 事件序列是接线判据的全部信息量。"""
            self.events.append("post_clean")
            return await _real_post_clean(token, spec)

        monkeypatch.setattr(lr, "httpx", _FakeHttpx(self.shop))
        monkeypatch.setattr(lr, "login", fake_login)
        monkeypatch.setattr(lr, "get_or_create_session", fake_sess)
        monkeypatch.setattr(lr, "run_case", fake_run_case)
        monkeypatch.setattr(lr, "_run_post_clean", recording_post_clean)
        monkeypatch.setattr(lr, "_close_and_verify_session", fake_close_and_verify)
        monkeypatch.setattr(lr, "_end_session", fake_end_session)
        monkeypatch.setenv("AGENT_EVAL_FLAKE_LOG", str(tmp_path / "flakes.json"))


def _pc_case(cid="PC-001", post_clean=None, pre_clean=None):
    return lr.EvalCase(id=cid, title="（夹具）共享夹具写方 + 复位", skill=lr.Skill.PRODUCT,
                       difficulty=lr.Difficulty.NORMAL,
                       user_inputs=["把遮光窗帘的米白色散剪规格改成 150 元"],
                       expectations=[], data_checks=[],
                       pre_clean=pre_clean or [], post_clean=post_clean or [])


class TestRunSuiteWiring:
    def test_post_clean_runs_after_the_assertions(self, monkeypatch, tmp_path):
        """**接线**：`post_clean` 在该用例的断言**之后**执行，并把夹具复位。"""
        shop = _Shop()
        h = _SuiteHarness(shop)
        h.install(monkeypatch, tmp_path)
        case = _pc_case(post_clean=[PRICE_SPEC])
        results = asyncio.run(lr.run_suite([case], "t", classify=False, concurrency=1))
        r = results[0]
        assert shop.price("米白") == SEED_PRICE, (
            f"用例跑完后夹具没复位（调度器没接 post_clean？）：{shop.price('米白')} / {r.get('restore')}")
        assert r.get("restore") and not lr.check_postclean_not_applied(r["restore"]), r.get("restore")
        # **顺序判据**（本仓库的红线）：尝试 → 断言 → 复位。复位提前 = 把本次尝试的证据洗掉。
        assert h.events == ["attempt", "verify", "post_clean"], (
            f"事件序列不对（复位必须在该用例的断言之后、且只跑一次）：{h.events}")

    def test_post_clean_failure_lands_in_the_result(self, monkeypatch, tmp_path):
        """**红证 ②（端到端）**：复位失败 ⇒ 结果里带标记 + `precondition` + 结论阻塞。"""
        shop = _Shop()
        # 先把共享夹具改脏（模拟"写方已经写过了"），再让**复位**那一步失败
        shop.set_sku_price("prod_eval_blackout", {"color": "米白", "price": 150})
        shop.fail_keys.add(("PATCH", "/skus/price"))
        h = _SuiteHarness(shop, pollute=False)
        h.install(monkeypatch, tmp_path)
        case = _pc_case(post_clean=[PRICE_SPEC])
        results = asyncio.run(lr.run_suite([case], "t", classify=False, concurrency=1))
        r = results[0]
        assert r.get("restore"), f"复位失败没有落盘（静默）：{r}"
        assert lr.check_postclean_not_applied(r["restore"]), r["restore"]
        assert str(r.get("precondition") or "").startswith("PRECONDITION_NOT_RESTORED"), r
        v = lr.completion_verdict([{"case_id": r["case_id"], "score": r["score"],
                                    "classification": r.get("classification") or "pass",
                                    "restore": r["restore"]}], ())
        assert v["ok"] is False and v["restore_failures"] == [r["case_id"]], v

    def test_case_without_post_clean_does_not_run_any_restore(self, monkeypatch, tmp_path):
        """**按用例 opt-in**：没声明 `post_clean` 的用例整跑零复位（不误伤别人的前置）。"""
        shop = _Shop()
        h = _SuiteHarness(shop)
        h.install(monkeypatch, tmp_path)
        results = asyncio.run(lr.run_suite([_pc_case()], "t", classify=False, concurrency=1))
        assert shop.price("米白") == 150, "没声明的用例竟然被复位了（全局复位会伤到别人的前置）"
        assert not results[0].get("restore"), results[0].get("restore")

    def test_two_consecutive_suite_runs_see_the_seed_value(self, monkeypatch, tmp_path):
        """**红证 ③（端到端）**：连跑两次同一用例 ⇒ 第二次开始时夹具 = 种子原值。"""
        shop = _Shop()
        h = _SuiteHarness(shop)
        h.install(monkeypatch, tmp_path)
        case = _pc_case(post_clean=[PRICE_SPEC])
        asyncio.run(lr.run_suite([case], "t", classify=False, concurrency=1))
        second_run_start = shop.price("米白")
        assert second_run_start == SEED_PRICE, (
            f"第二次运行的起点不是种子值（第一次跑完把世界留脏了）：{second_run_start}")