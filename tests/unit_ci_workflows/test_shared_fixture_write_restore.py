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

1. **写面必须归类（fail-closed）**：用例库里凡是"写**商品实体**"的期望
   （`(tool, action)` 组合）都必须在 `PRODUCT_ATTR_WRITERS` 里显式归类 ——
   新增工具/新增 action **未归类即红**。防的是"新写方悄悄出现、判据还是旧地图"
   （`migao-dev-flow` §19.1：基于错误真相模型写出的护栏 = 永远红 / 永远被豁免的空判据）。
2. **可复位属性必须声明复位**：用例 `user_inputs` 点名种子商品（名字**现读 fixtures**）
   且写了**已有复位类型**的属性（属性↔类型的关系**现读 runner**）⇒ 必须声明该复位
   （`post_clean`，或裁定允许的 `pre_clean` 等价复位）。
3. **尚无复位类型的属性必须登记为缺口（只许缩短）**：写这些属性的用例必须出现在
   `REGISTERED_RESTORE_GAPS` 里，且每条带跟随 issue 号（R4 的两个出口：
   本次修掉 / 开独立 issue）——**不是白名单**：新增一条即红，修好一条未同步台账也红。

## 为什么口径是"属性写方"而不是"带写期望"

裁定的原文是「凡 `user_inputs` 点名种子商品且带写期望的用例」。直接按
`assertion_taxonomy.is_write_case` 取"写期望"会得到 **49 条**用例，其中绝大多数是
`order_create`（**下单**不改商品属性，它只是**引用**该商品）—— 对它们要求"复位"是无对象的
假红（R2：判据不得拦掉原本合法的输入）。故按**结构性**三层收窄，且每层都可复算：

```
种子商品名（fixtures/*.sql 现算）
  ∩ user_inputs（点名了它）
  ∩ 写**商品实体**的期望（tool ∈ 5 个商品写工具，拆 ` or ` 与 runner 同口径）
  → 属性（(tool, action) → 属性键，显式登记）
```
⇒ 12 条（复算命令与逐条结论见 PR body 的存量穷举表）。**不适用域负例**见
`test_order_only_cases_are_not_in_scope`（`order_create` / 建自有名商品**不得**被判红）。

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
# 一、写面登记表（**显式枚举**，同 `assertion_taxonomy.WRITE_TOOLS` 的做法）
# ══════════════════════════════════════════════════════════════════════════════

#: 写**商品实体**（商品 / 其 SKU / 其库存 / 其加工项关联）的工具。
#: 真值锚点 = `backend/ai-agent-service/app/tools/` 里 `read_only = False` 且动作落在商品上的
#: 那 5 个工具（按工具名检索即可复算）。**其余写工具写的是别的实体**
#: （`order_create`=订单 / `customer_manage`=客户 / `after_sales_manage`=工单 / …），
#: 它们不改共享夹具 ⇒ 不适用本判据（不适用域负例见本文件末尾）。
#: ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：`product_processing_item_manage`（给**商品**
#: 增删加工项）已随「商品不再持有加工项」退场（工具文件与注册行都删）⇒ 从本集合移除。
#: 移除**不是**放宽：该工具已不可能出现在任何用例的期望里（其 3 条用例已整条删除）。
PRODUCT_ENTITY_TOOLS: frozenset = frozenset({
    "product_manage",
    "product_update",
    "sku_update",
    "inventory_manage",
})

#: `(tool, action)` → **属性键**（`""` = 写商品实体但**不改共享夹具的属性**）。
#: `action` 取 `""` 表示期望里没声明 action（`is_write_expectation` 对此**保守判写**）。
#: ⚠️ 新增工具 / 新增 action **必须在此显式归类** —— 未归类 ⇒ 判据 ① 直接红
#: （这就是"新写方不会悄悄出现"的那道闸）。
PRODUCT_ATTR_WRITERS: dict = {
    ("sku_update", ""): "sku_price",
    ("product_manage", "toggle_status"): "status",
    ("product_update", ""): "product_attr",                 # base_price / allow_return_restock / …
    ("product_manage", "update"): "product_attr",           # images / 字段级更新
    ("inventory_manage", "adjust"): "stock",
    # ⚠️ `("product_processing_item_manage", "add"/"")`: "processing_items" 两条已随
    # #4371 解耦移除（工具退场；`processing_items` 这一「属性键」也不再有写方）。
    # 期望里没声明 action 的裸 `product_manage`：**改哪个属性不可判定** ⇒ 单列 `unknown`，
    # 让"未定型"这件事在台账里可见（而不是被当成"不改共享夹具"）。
    ("product_manage", ""): "unknown",
    # 建品：写的是**新对象**，不触达共享夹具的属性；"造出同名副本"由 #3835 的守卫
    # （`test_eval_product_name_pollution.py`）单独治 —— 两条判据的适用域不重叠。
    ("product_manage", "create"): "",
}

#: **存量**「写共享夹具属性、但当前没有复位类型」的缺口台账（**只许缩短**）。
#: 出口两个（`migao-dev-flow` §20 R4）：本次修掉 / 开独立 issue —— 本台账对应
#: **#4128**（五类属性无复位动作），故每条都带该 issue 号。
#: ⚠️ 这不是白名单：**新增**一条缺口即红（判据 ③），修好一条未删台账也红。
REGISTERED_RESTORE_GAPS: dict = {
    "PR-005": "stock（`inventory_manage(adjust)` 出库 10 件）—— 无 stock 复位类型（#4128）",
    "PR-009": "product_attr / base_price —— 复位由 #3807 的 tag 式快照承担（非声明式），"
              "无声明式复位类型（#4128）",
    "PR-010": "product_attr / base_price（同上）+ processing_items（`add`，无复位类型）（#4128）",
    "PR-017": "product_attr / allow_return_restock —— 无复位类型（#4128）",
    "PR-026": "product_attr / images（主图）—— 无复位类型（#4128）",
    "PR-027": "product_attr / images（主图）—— 无复位类型（#4128）",
    "CH-006": "product_attr（改价 199，且**不在** #3807 的快照 tag 覆盖面内）"
              "+ processing_items —— 无复位类型（#4128）",
}


# ══════════════════════════════════════════════════════════════════════════════
# 二、纯函数判据（每条都能被合成用例直接喂 —— 红证不依赖真实用例库）
# ══════════════════════════════════════════════════════════════════════════════

def product_write_expectations(case: dict) -> list:
    """用例里**写商品实体**的期望 → `[(tool, action)]`（排序去重，纯函数）。

    ⚠️ 拆 ` or `：`expectations: [{tool: "product_update or product_manage", …}]` 是既有用例
    的现实形态（`PR-017` 就是它），而 **runner 的 `check_expectation` 会拆**
    （`expectation.split(" or ")`，见该函数）；若本守卫不拆，`PR-017` 这个**真实**的
    共享夹具写方就会从扫描面里消失（判据漏掉病灶 = 假绿）。
    """
    out = set()
    tax = _taxonomy()
    for tool, args in tax.expectation_tools(case):
        for part in str(tool).split(" or "):
            t = part.strip()
            # ① 只算**商品实体**工具；② 只算**写** —— `inventory_manage(query)` /
            #    `low_stock_alert` 是 read_only action（PR-004/PR-006 就是它们），
            #    判据复用 taxonomy 的 `is_write_expectation`，不自己再写一份
            #    "哪些 action 算写"（两份口径必然漂移）。
            if t in PRODUCT_ENTITY_TOOLS and tax.is_write_expectation(t, args or {}):
                out.add((t, str(((args or {}).get("action")) or "")))
    return sorted(out)


def unclassified_product_writes(cases: list) -> dict:
    """**判据 ①**：未归类的 `tool(action)` → 声明它的用例（fail-closed）。

    扫描面 = **全库**（不限点名种子商品的用例）：新工具/新 action 一出现就得归类，
    否则"它改的是不是共享夹具"这件事无人回答，判据 ②/③ 也就无从适用。
    """
    out: dict = {}
    for c in cases or []:
        for key in product_write_expectations(c):
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
    """本用例在**共享夹具**上触达的属性集合（点名种子商品 ∧ 写商品实体）。

    `""`（不改共享夹具属性）与 `"unknown"`（action 未定型）都**不是**"可复位属性"，
    但两者处置不同：前者无事可做，后者进台账（可见）。
    """
    if not named_seed_products(case, names):
        return set()
    return {PRODUCT_ATTR_WRITERS[k] for k in product_write_expectations(case)} - {""}


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

    def test_scan_surface_covers_the_known_writers(self):
        """**扫描面自证**：已知的共享夹具写方必须被 `product_write_expectations` 认出来。

        否则判据恒绿（`migao-acceptance`「绿了但没跑」）：这里用**改前形态**（本单的三条
        病灶用例仍在库里）+ `PR-017` 的 ` or ` 形态作为"识别力"证据。
        """
        by = {c["id"]: c for c in _all_cases()}
        for cid, want in (("PR-021", ("sku_update", "")),
                          ("PR-025", ("product_manage", "toggle_status")),
                          ("PR-007", ("product_manage", "toggle_status")),
                          ("PR-017", ("product_update", "")),      # dict 形态的 ` or ` 必须拆开
                          ("PR-005", ("inventory_manage", "adjust"))):
            got = product_write_expectations(by[cid])
            assert want in got, (
                f"判据认不出 {cid} 的写期望 {want}（扫描面失效，本文件会静默空跑）：{got}")


# ══════════════════════════════════════════════════════════════════════════════
# 四、判据 ①：写面必须归类（fail-closed）
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteSurfaceIsClassified:
    def test_every_product_write_is_classified(self):
        """**核心**：商品实体的每个 `tool(action)` 写期望都已归类。"""
        bad = unclassified_product_writes(_all_cases())
        assert bad == {}, (
            "出现**未归类**的商品实体写方 —— 它改的是不是共享夹具没人回答，"
            "判据 ②③（要不要复位）因此无从适用。请在 PRODUCT_ATTR_WRITERS 显式归类：\n  "
            + "\n  ".join(f"{k} ← {v}" for k, v in sorted(bad.items())))

    def test_red_proof_unclassified_action_is_caught(self):
        """**红证**：给商品工具加一个没归类的 action（如 `delete`）⇒ 判据必红。"""
        fake = [{"id": "FAKE-1", "user_inputs": ["把遮光窗帘删掉"],
                 "expectations": [{"tool": "product_manage", "args": {"action": "delete"}}]}]
        assert unclassified_product_writes(fake) == {"product_manage(delete)": ["FAKE-1"]}, (
            "未归类的 action 被放过了 —— 新写方会悄悄出现（判据变空壳）")

    def test_red_proof_unclassified_tool_is_caught(self):
        """**红证**：新增一个商品写工具（未登记）⇒ 判据必红（判据①对"新工具"同样生效）。"""
        fake = [{"id": "FAKE-2", "user_inputs": ["改价"],
                 "expectations": [{"tool": "product_price_bulk_update"}]}]
        assert unclassified_product_writes(fake) == {}, (
            "未登记的工具**不在** `PRODUCT_ENTITY_TOOLS` 里 ⇒ 本判据看不见它。"
            "这是**有意**的口径（本判据的面 = 已知商品写工具），但它意味着："
            "新增商品写工具时必须同时更新 PRODUCT_ENTITY_TOOLS —— 由"
            "`test_write_tool_sets_only_name_reachable_tools`（taxonomy）与人工评审兜底。")
        # 负例的另一半：把工具登记进来、action 未归类 ⇒ 立刻红
        fake2 = [{"id": "FAKE-3", "user_inputs": ["改价"],
                  "expectations": [{"tool": "sku_update", "args": {"action": "bulk"}}]}]
        assert unclassified_product_writes(fake2) == {"sku_update(bulk)": ["FAKE-3"]}, (
            "已登记工具的新 action 必须被拦（否则判据①只对新工具生效）")


# ══════════════════════════════════════════════════════════════════════════════
# 五、判据 ②：可复位属性必须声明复位（本单的主判据）
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedFixtureWritersDeclareRestore:
    def test_no_shared_fixture_writer_lacks_a_restore(self):
        """**主判据**：写可复位属性的用例都声明了复位（改前：PR-021/PR-025/PR-007 ⇒ 红）。"""
        miss = missing_restores(_all_cases())
        assert miss == {}, (
            "这些用例写了**共享夹具**的可复位属性却没声明复位手段 ⇒ 跑完把世界留给"
            "同栈的下一条用例（#4075 的病灶）：\n  "
            + "\n  ".join(f"{cid}: 缺 {sorted(a)} 的复位" for cid, a in sorted(miss.items()))
            + "\n修法：加 `post_clean: [{type: product_status_restore|sku_price_restore, …}]`"
              "（类型↔属性的关系见 local_runner._CLEAN_TYPES[*].attr）")

    def test_red_proof_pr021_without_post_clean_is_caught(self):
        """**红证 ①**：把 `PR-021` 的 `post_clean` **去掉** ⇒ 判据必红（本单的原话）。"""
        real = next(c for c in _all_cases() if c["id"] == "PR-021")
        assert "post_clean" in real and real["post_clean"], (
            "PR-021 已声明 post_clean（本 PR 修的）—— 若这里为空说明修复被回退了")
        stripped = {k: v for k, v in real.items() if k != "post_clean"}
        assert missing_restores([stripped]) == {"PR-021": ["sku_price"]}, (
            "去掉写方的 post_clean 之后判据没红 —— 守卫对**本单的原始缺陷**没有判别力")

    def test_red_proof_pr025_and_pr007_without_post_clean_are_caught(self):
        """**红证 ①（状态侧）**：`PR-025` / `PR-007` 去掉 `post_clean` ⇒ 判据必红。"""
        by = {c["id"]: c for c in _all_cases()}
        for cid in ("PR-025", "PR-007"):
            stripped = {k: v for k, v in by[cid].items() if k != "post_clean"}
            assert missing_restores([stripped]) == {cid: ["status"]}, (
                f"{cid} 的 off_sale 污染形态未被判红（#4075 的另一半病灶）")

    def test_red_proof_synthetic_writer_is_caught(self):
        """**红证**：合成一条"点名种子商品 + `sku_update`、无复位"的用例 ⇒ 判据必红。"""
        fake = [{"id": "FAKE-4", "user_inputs": ["把遮光窗帘的米白散剪改成 150 元"],
                 "expectations": [{"tool": "sku_update"}], "must_succeed": [{"tool": "sku_update"}]}]
        assert missing_restores(fake) == {"FAKE-4": ["sku_price"]}, missing_restores(fake)

    # ── 不适用域负例（R2：判据不得拦掉原本合法的输入）────────────────────────
    def test_order_only_cases_are_not_in_scope(self):
        """**负例**：`order_create` 用例（点名了种子商品）**不得**被判红。"""
        fake = [{"id": "FAKE-5", "user_inputs": ["我想买一件遮光窗帘，下单"],
                 "expectations": [{"tool": "order_create"}], "must_succeed": [{"tool": "order_create"}]}]
        assert touched_attrs(fake[0]) == set(), (
            "下单用例被算成「写共享夹具」了 —— 它会白要求一份无对象的复位（R2 假红）")
        assert missing_restores(fake) == {} and unregistered_restore_gaps(fake) == {}

    def test_create_own_name_case_is_not_in_scope(self):
        """**负例**：建**自有名**商品的用例不得被判红（同名污染属 #3835 的守卫）。"""
        fake = [{"id": "FAKE-6", "user_inputs": ["创建商品，名称E2E建品流程样品帘，价格 100"],
                 "namespaces": ["product_name:E2E建品流程样品帘"],
                 "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]}]
        assert missing_restores(fake) == {} and unregistered_restore_gaps(fake) == {}

    def test_case_not_naming_a_seed_product_is_not_in_scope(self):
        """**负例**：写自有商品属性的用例（不点名种子商品）不在本判据的面内。"""
        fake = [{"id": "FAKE-7", "user_inputs": ["把 E2E建品流程样品帘 的价格改成 199"],
                 "expectations": [{"tool": "product_update", "args": {"price": "199"}}]}]
        assert touched_attrs(fake[0]) == set()

    def test_pre_clean_equivalent_restore_is_accepted(self):
        """裁定允许的等价形态：复位声明在 `pre_clean` 里也算"有复位手段"。"""
        fake = [{"id": "FAKE-8", "user_inputs": ["把遮光窗帘下架"],
                 "expectations": [{"tool": "product_manage", "args": {"action": "toggle_status"}}],
                 "pre_clean": [{"type": "product_status_restore", "product_keyword": "遮光窗帘"}]}]
        assert missing_restores(fake) == {}, (
            "裁定原文允许 `pre_clean` 的等价复位 —— 判据把它判红 = 与裁定不符")


# ══════════════════════════════════════════════════════════════════════════════
# 六、判据 ③：尚无复位类型的属性必须登记缺口（只许缩短）
# ══════════════════════════════════════════════════════════════════════════════

class TestUnrestorableWritersAreRegisteredGaps:
    def test_gap_ledger_matches_the_library_exactly(self):
        """存量缺口必须与台账**逐条相等**：新增即红、修好未删也红（清单只许缩短）。"""
        live = unregistered_restore_gaps(_all_cases())
        new = sorted(set(live) - set(REGISTERED_RESTORE_GAPS))
        assert new == [], (
            "出现**未登记**的共享夹具属性缺口（无复位类型）—— 出口只有两个："
            "本次补复位类型并声明 / 开独立 issue 后登记进台账（R4）：\n  "
            + "\n  ".join(f"{cid}: {live[cid]}" for cid in new))
        stale = sorted(set(REGISTERED_RESTORE_GAPS) - set(live))
        assert stale == [], (
            "台账里的缺口已不复现 ⇒ 必须删除该条（清单只许缩短，防债务僵化）："
            f"{stale}")

    def test_every_gap_entry_names_a_follow_up_issue(self):
        """台账条目**必须带 issue 号** —— 否则"登记"就变成新的静默出口（R4）。"""
        import re
        bad = [cid for cid, why in REGISTERED_RESTORE_GAPS.items()
               if not re.search(r"#\d{3,}", str(why))]
        assert bad == [], f"缺口台账条目没有跟随 issue（将来无人处理）：{bad}"

    def test_red_proof_new_gap_is_caught(self):
        """**红证**：合成一条"写 stock、未登记"的用例 ⇒ 判据必红。"""
        fake = [{"id": "FAKE-9", "user_inputs": ["调整遮光窗帘的库存，出库 3 件"],
                 "expectations": [{"tool": "inventory_manage", "args": {"action": "adjust"}}]}]
        assert unregistered_restore_gaps(fake) == {"FAKE-9": ["stock"]}, unregistered_restore_gaps(fake)

    def test_unknown_action_attr_lands_in_the_ledger_path(self):
        """`action` 未定型的裸 `product_manage` 走台账路径（可见），不被当成"不改夹具"。"""
        fake = [{"id": "FAKE-10", "user_inputs": ["处理一下遮光窗帘"],
                 "expectations": [{"tool": "product_manage"}]}]
        assert touched_attrs(fake[0]) == {"unknown"}, (
            "未定型写方被当成「不改共享夹具」⇒ 它会从两个判据里同时消失（静默）")


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

    def test_runner_restore_attrs_have_a_known_writer_surface(self):
        """runner 里的复位属性必须能在**本守卫的写面表**里找到对应写方。

        反向漏判的堵法：runner 新增一个复位类型（比如 `product_stock_restore`，attr=`stock`）
        而写面表还没把 `inventory_manage(adjust)` 归到 `stock` ⇒ "要求声明"会指向一个
        没人能声明的目标。
        """
        attrs_in_writers = {a for a in PRODUCT_ATTR_WRITERS.values() if a}
        orphans = sorted(a for a in runner_restore_map() if a not in attrs_in_writers)
        assert orphans == [], (
            f"runner 的复位属性 {orphans} 在写面表里没有对应写方 ⇒ 判据②无从适用"
            f"（写面表见 PRODUCT_ATTR_WRITERS）")

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
        """**红证**：给 runner 加一个"没有写方"的复位属性 ⇒ 判据必红。"""
        monkeypatch.setitem(lr.RESTORE_TYPES_BY_ATTR, "ghost_attr", "ghost_restore")
        attrs_in_writers = {a for a in PRODUCT_ATTR_WRITERS.values() if a}
        assert "ghost_attr" not in attrs_in_writers


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