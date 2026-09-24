# case_ids: PR-021, PR-025, PR-007, PR-017, PR-005, PR-009, PR-010, OR-014
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
`assertion_taxonomy.is_write_case` 取"写期望"（读数：#5247 前 **49 条**、#5247 后 **15 条**
—— 数字是**当时的读数**、随用例面变，不是阈值），
其中绝大多数是 `order_create`（**下单**不改商品属性，它只是**引用**该商品）—— 对它们要求
"复位"是无对象的假红（R2：判据不得拦掉原本合法的输入）。故按**结构性**三层收窄，每层都可复算：

```
种子商品名（fixtures/*.sql 现算）
  ∩ user_inputs（点名了它）
  ∩ **活写方**的期望（tool ∈ 写工具扫描面；拆 ` or `，与 runner 同口径）
  → 属性（(tool, action) → 属性键，显式登记）
```
⇒ 收窄后的**命中数随写方面变**（这正是判据要的：写方回绑/退场都立刻反映到命中数上）：
#5247 后是 **0 条**（当时活写方 `order_create` / `aftersale_create` / `notification_manage` /
`settings_manage` 都不触达商品属性）；**#5303 起是 3 条**（`PR-009` / `PR-010` 的
`product_update` → `base_price`、`PR-021` 的 `sku_update` → `sku_price`）—— 三条各自声明了
对应复位，故判据 ② 判绿：**机制真的在被使用**，不是空转。
**不适用域负例**见 `test_order_only_cases_are_not_in_scope`
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

## #5303 改判（2026-09-24，承接 #5247、**不是推翻**）：两个 A 档可逆写工具**回绑** ⇒ 真值面又变了

**新事实**：`product_update` / `sku_update` 被**重新绑定**到 B 端 `product_skill`
（product_skill 也进了 `_CONFIRM_GATE_BINDING_SKILLS` 名册）。二者是 #5285 只读化后唯一回绑的
**A 档可逆写**：前者写**商品级** `products.base_price`（PATCH
`/api/admin/agent/products/{id}`，字段 `basePrice`），后者写 `product_skus.price`
（PATCH `…/skus/price`）；都带工具级预览闸（缺 `before_price` 的改价 fail-closed，
且 `before_price` 不进请求体）。⇒ **它们重新可达**。

**三处口径同步**（同一个理由：**判据面必须与真实可达面逐字一致** —— 多一个 = 按旧地图判，
少一个 = 静默漏判）：
① `.github/assertion_taxonomy.py` 的 `WRITE_TOOLS` **补回**这两个名字（见该文件的 #5303 注释）；
本文件的 `WRITE_TOOL_SURFACE` 从它**推导** ⇒ 扫描面自动跟着变（**没有第二份手抄清单**）；
② `PRODUCT_ATTR_WRITERS` 新增两行（`("product_update","")` → `base_price`、
`("sku_update","")` → `sku_price`），并从 `RETIRED_ATTR_WRITERS` **移出同两条 key**
（同一 key 同时留在留档表里 = 双源：留档表是**历史**，不得读成"仍活着"）；
③ runner 新增复位类型 `product_price_restore`（attr `base_price`），与既有的
`sku_price_restore`（attr `sku_price`）**正交** —— 商品级基准价与单规格价是两个属性，
只复位后者治不了前者（`product_skus.price` 的接地真值就是商品级价）。

**判据 ② 从"无对象"变回"有对象"（这是改判的目的，不是副作用）**：`PR-009` / `PR-010`
写商品级价、`PR-021` 写 SKU 价 ⇒ 三条都必须声明对应复位（`post_clean`），否则本文件判红。
`REGISTERED_RESTORE_GAPS` **仍为空**：判据 ③ 只收"写了**尚无复位类型**的属性"的用例，
而这两个属性**都已有复位类型** ⇒ 走判据 ② 的"必须声明"出口，不进台账（台账没有被挪用成白名单）。

**为什么不是放宽**：判据 ①②③ 的代码一字未改，扫描面/profile 一条没删 —— 变的是**被测对象**：
#5247 让它们消失（判据无对象 ⇒ 红证只能注入），#5303 让它们回来（判据重新有**真**对象）。
新增两条 key 让判据 ① **多**两个必须被回答的写方 ⇒ 更严，不是更松。

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


def _with_synthetic_action_writer(monkeypatch, tool: str = "zzz_partial_write",
                                  action: str = "write_x") -> tuple:
    """把**合成**「部分写」工具临时填进扫描面（返回 `(tool, action)`）。

    🔴 **为什么需要（#5302）**：settings 域收口让 taxonomy 的 `WRITE_TOOL_ACTIONS` **归零**
    （最后一个"部分写"工具也没了）⇒ 真实用例库里**再无 action 级写方** ⇒ 本文件那几条
    「action 级写方」红证若继续锚在真值上会**静默失去判别力**（夹具不再是写用例 = 恒真断言）。
    故按仓内既有做法改成**注入式自证**：合成一个 `zzz_partial_write(write_x)`，机制本身
    （保守判写 / 未归类即红 / 台账路径）仍逐条被覆盖。

    注入必须走**两份真值**（本文件的判据同时读它们）：
      · `WRITE_TOOL_SURFACE`（本模块的扫描面，模块级常量）—— 直接替换该全局；
      · `is_write_expectation`（taxonomy 的判定）—— 注意 `_taxonomy()` 每次调用都**重新载入
        模块实例**，所以"改返回值里的字典"是无效的（实测：`WRITE_TOOL_ACTIONS` 仍是 `{}`）⇒
        必须把 `_taxonomy` 本身替换成返回**已打好补丁的那一份实例**（`monkeypatch` 退出时自动还原）。
    """
    tax = _taxonomy()
    monkeypatch.setattr(tax, "WRITE_TOOL_ACTIONS", {tool: frozenset({action})})
    monkeypatch.setitem(globals(), "_taxonomy", lambda: tax)
    monkeypatch.setitem(globals(), "WRITE_TOOL_SURFACE", WRITE_TOOL_SURFACE | {tool})
    return tool, action

#: `(tool, action)` → **属性键**（`""` = 是写方但**不改共享夹具的属性** ⇒ 判据 ②③ 都不适用）。
#: `action` 取 `""` 表示期望里没声明 action（`is_write_expectation` 对 action 级写工具**保守判写**）。
#: ⚠️ 只登记**库里真实出现**的活写方 key —— 每个 key 都要有人回答「它改的是不是共享夹具」；
#: **未在此归类 ⇒ 判据 ① 直接红**。
#: 为什么不把这张表也整体推导：推导出来等于"永远已归类"= 判据 ① 变空壳 ——
#: "这个新写方改不改共享夹具"必须由人判定，只能显式登记。
PRODUCT_ATTR_WRITERS: dict = {
    # ── 整工具写方（taxonomy 的 `WRITE_TOOLS`）──────────────────────────────
    # 下单：**引用**商品，不改商品属性（不适用域负例见 test_order_only_cases_are_not_in_scope）。
    ("order_create", ""): "",
    # 建售后工单：写的是**工单实体**，不触达商品属性。
    ("aftersale_create", ""): "",
    # ── #5303 回绑的两个 A 档可逆写工具：**都是商品属性写方**（本次改判的核心）──────
    # 商品级统一定价（`products.base_price`；PATCH `/api/admin/agent/products/{id}`）。
    # 属性键是独立的 `base_price`：它与 `sku_price` **正交**（商品级 vs 单规格），
    # 共用一个键会让"声明了错误的那一个"也判绿（假绿）——红证见
    # test_price_restore_types_are_orthogonal。
    ("product_update", ""): "base_price",     # PR-009 / PR-010 的写方
    # 单规格调价（`product_skus.price`；PATCH `…/skus/price`）—— PR-021 的写方。
    ("sku_update", ""): "sku_price",
    # ── # [RETIRED #5302] action 级写方（`WRITE_TOOL_ACTIONS`）**整体退场**────────────
    # settings 域收口把该表**归零**（`notification_manage` / `settings_manage` 也收窄为只读）
    # ⇒ 下面三条不再是活写方（工具仍是活工具，但**没有**写 action 了），从表里删除
    # （留着 = 对不存在的能力做归类）：
    #   ("settings_manage", "change_password") → ""        （ST-003 已改判为能力下线的如实告知）
    #   ("settings_manage", "")               → "unknown"   （该工具不再有写 action）
    #   ("notification_manage", "")           → "unknown"   （同上）
    # action 级写的判别力**没有丢**：三条红证改用**合成「部分写」工具**注入（见
    # `_with_synthetic_action_writer`），机制仍逐条被覆盖。
    # ── 具名批量写方（issue #5314）：属性由**用例声明的 `batch_type`** 决定 ⇒ 3 元组键 ──
    # `preview` = 预演：只落一条 preview 批次，**不改商品属性**（判别维在场也只是把这条钉死）。
    ("product_batch_update", "preview", "product_price"): "",
    ("product_batch_update", "preview", "product_status"): "",
    # `execute` = 真的落库：改价批次写 `products.base_price`、上下架批次写 `products.status`
    # —— 两者都**已有**复位类型（`product_price_restore` / `product_status_restore`）
    # ⇒ 走判据 ② 的"必须声明复位"出口。PR-108 是改价批量的写方。
    ("product_batch_update", "execute", "product_price"): "base_price",
    ("product_batch_update", "execute", "product_status"): "status",
    # `revert` = 逐条还原为 `old_value`：还原的是**同一批**改过的属性 ⇒ 与 execute 同维。
    ("product_batch_update", "revert", "product_price"): "base_price",
    ("product_batch_update", "revert", "product_status"): "status",
    # 用例**未声明** `batch_type` ⇒ 改哪个属性**不可判定** ⇒ `unknown`（走台账可见路径，
    # 不静默当成"不改共享夹具"）；`preview` 不依赖判别维（它本就不改商品属性）。
    ("product_batch_update", "preview"): "",
    ("product_batch_update", "execute"): "unknown",
    ("product_batch_update", "revert"): "unknown",
    ("product_batch_update", ""): "unknown",
}

#: **留档**（#4075 / #4128 时代的商品属性写方 → 属性键），**已不是活写方**。
#: 为什么留：runner 的 `RESTORE_TYPES_BY_ATTR`（`status` / `sku_price` / `base_price`）与用例库里
#: 仍在的 `post_clean` 声明指向这些属性 —— 本表是
#: 「runner 新增复位类型 ⇒ 必须在写面词表里有出处」这条**反向判据**的锚点
#: （见 `test_runner_restore_attrs_have_a_known_writer_surface`）。
#: ⚠️ 它**不参与**判据 ① 的活写方归类（扫描面不看它），也**不得**再往里加东西 ——
#: 新增写方一律走「taxonomy → `WRITE_TOOL_SURFACE` → `PRODUCT_ATTR_WRITERS`」这条链。
#: ⚠️ 2026-09-24（issue #5303）：原留档条目 `("sku_update","") → sku_price` 与
#: `("product_update","") → product_attr` **已移出本表** —— 二者随 #5303 **回绑 B 端
#: product skill**（A 档可逆写）⇒ 重新成为**活写方**，已按新真值登记进 `PRODUCT_ATTR_WRITERS`
#: （`base_price` / `sku_price`）。**同一 key 不得同时留在两张表**：留档表是**历史**，
#: 留着它会读成"仍活着"，而判据 ① 用的是活写方表 ⇒ 两表打架时没人会红（双源形态）。
#: 判据 `test_no_writer_key_is_double_claimed` 把"不得两表重复"变成机器可判。
#: （`product_attr` 这个属性键仍有出处：`("product_manage","update")` —— 该工具**未**回绑。）
RETIRED_ATTR_WRITERS: dict = {
    ("product_manage", "toggle_status"): "status",    # 上下架（PR-007 / PR-025 的写方）
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
#:     ⚠️ **2026-09-24（#5303）改判**：`product_update` **回绑** B 端 product skill ⇒ 该条的写方
#:     **重新可达**；但 `base_price` 已有复位类型（`product_price_restore`）且用例声明了它
#:     ⇒ 走判据 ② 的"必须声明复位"出口，**不进本台账**（台账只收"尚无复位类型"的属性）。
#:   · `PR-010` —— 已随 #5247 退役（同上，`product_update` 写面）；其 processing_items 一侧
#:     早在 #4371 就随「商品不再持有加工项」退场；
#:   · `PR-017` —— 已随 #5247 退役（`product_update` / `product_manage` 写 allow_return_restock
#:     的断言已删）；
#:   · `PR-026` / `PR-027` —— 已随 #5247 退役（`product_manage(action=update, images)` 写主图
#:     的断言已删）；
#:   · `CH-006` —— 已随 #5247 退役（改价 199 的断言改成 `product_search` / `product_detail` 只读核对）。
#: 证据链（不是"清空即销账"）：复算双向相等 + 新增缺口红证 + 陈旧条目红证 +
#: `test_retired_writers_are_no_longer_seen_as_writers`（留档的写方真的不再被判据看见）。
#: ⚠️ 2026-09-24（#5303）：**台账仍为空**，同样不是销账 —— 回绑的两个写工具
#: （`product_update` / `sku_update`）触达的属性**都已有复位类型**（`base_price` /
#: `sku_price`）⇒ 它们由判据 ②（必须声明复位）管，而不是判据 ③（登记缺口）。
#: 若哪天只回绑了工具、没给属性配复位类型，`product_price_restore` 一撤 ⇒ 判据 ③ 立刻把
#: `PR-009` / `PR-010` 报成新缺口（红证 `test_red_proof_rebound_writer_without_a_restore_type_is_a_gap`）。
REGISTERED_RESTORE_GAPS: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# 二、纯函数判据（每条都能被合成用例直接喂 —— 红证不依赖真实用例库）
# ══════════════════════════════════════════════════════════════════════════════

#: **具名批量**工具（issue #5314）：它们的写 action 是 execute/revert，但**改的是哪个属性**
#: 由 `batch_type` **参数**决定（`product_price` → `base_price` / `product_status` → `status`）
#: ⇒ 归类键在 `(tool, action)` 之外**多带一维**。判别值取**用例级**（用例在任一期望里声明
#: `batch_type` 即可，不必每次调用都带 —— 生产里 `execute`/`revert` 只带 `batch_id`）：
#: 「这条用例驱动的是哪类批量」是用例的**意图**，逐调用去要参数会造出假红（模型合理地不重复传）。
NAMED_BATCH_TOOLS = frozenset({"product_batch_update"})

#: 具名批量的 `batch_type` **白名单**（与工具侧 `app/tools/product_batch_update.py` 同源口径）。
NAMED_BATCH_TYPES = ("product_price", "product_status")


def _case_batch_type(pairs) -> tuple:
    """用例声明的批量类型（任一期望的 `args.batch_type`）→ 判别维元组；未声明 ⇒ `()`。

    `pairs` = `taxonomy.expectation_tools(case)` 的结果（**由调用方传**：`_taxonomy()` 每次
    调用都要重新 exec 模块，本文件在 460+ 条用例上跑 ⇒ 重复加载会把判据拖到分钟级）。

    ⚠️ 多个**不同**取值 ⇒ 返回 `()`（不可判定 ⇒ 走 2 元组键的 `unknown` 口径，不猜）。
    """
    seen = set()
    for tool, args in pairs or ():
        for part in str(tool).split(" or "):
            if part.strip() not in NAMED_BATCH_TOOLS:
                continue
            bt = str((args or {}).get("batch_type") or "").strip()
            if bt:
                seen.add(bt)
    return (seen.pop(),) if len(seen) == 1 else ()


def live_write_expectations(case: dict) -> list:
    """用例里**当前可达写方**的写期望 → `[(tool, action[, batch_type])]`（排序去重，纯函数）。

    扫描面 = `WRITE_TOOL_SURFACE`（从 `assertion_taxonomy` 推导，见其 docstring）。
    ⚠️ 2026-09-24（#5303）：`product_update` / `sku_update` 回绑 B 端 product skill ⇒ 它们
    重新出现在本函数的扫描面里（此前是 #5247 口径下的幽灵写工具）⇒ 判据 ①/② 对
    `PR-009` / `PR-010` / `PR-021` **重新有对象**（不是新增判据，是判据重新有了被测对象）。
    ⚠️ 拆 ` or `：字符串形态的期望（`["direct_reply or order_create or interact"]`，`CH-009`
    就是它）由 `expectation_tools` 拆过一次，而 dict 形态里的 ` or `（旧形态
    `{"tool": "product_update or product_manage"}`）由本函数拆 —— 与 runner 的
    `check_expectation` 同口径；不拆的话真实写方会从扫描面里消失（判据漏掉病灶 = 假绿）。
    """
    out = set()
    tax = _taxonomy()
    pairs = list(tax.expectation_tools(case))
    batch_dim = _case_batch_type(pairs)
    for tool, args in pairs:
        for part in str(tool).split(" or "):
            t = part.strip()
            # ① 只算**当前可达的写工具**（扫描面，见 WRITE_TOOL_SURFACE）；② 只算**写** ——
            #    `inventory_manage(query)` 这类只读 action 由 taxonomy 的
            #    `is_write_expectation` 判定，不自己再写一份"哪些 action 算写"（两份口径必然漂移）。
            if t in WRITE_TOOL_SURFACE and tax.is_write_expectation(t, args or {}):
                key = (t, str(((args or {}).get("action")) or ""))
                if t in NAMED_BATCH_TOOLS:
                    key += batch_dim
                out.add(key)
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


def double_claimed_writer_keys() -> list:
    """**同时**出现在活写方表与留档表里的 `(tool, action)` key（issue #5303 落成的判据）。

    为什么必须可判：留档表的语义是**"已不是活写方"**（历史），活写方表是**判据 ① 的比对面**。
    同一个 key 两边都有 = 两份互相矛盾的声明共存，而**没有任何东西会因此变红**
    （判据 ① 只看活写方表）⇒ 读的人会按留档那句"已不是活写方"做判断。
    #5303 的 `product_update` / `sku_update` 回绑正是这个形态：它们必须**只在**活写方表里
    （留档条目已移出）。纯函数，零依赖。
    """
    return sorted(set(PRODUCT_ATTR_WRITERS) & set(RETIRED_ATTR_WRITERS))


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
        # ⚠️ 2026-09-24（#5303）：`product_update` / `sku_update` 回绑 B 端 product skill
        # ⇒ **必须回到扫描面**。原文把它们放在下面那条"已退场"负例断言里（那是 #5247 的真值）
        # —— 留着会与本条判据面打架：真值面少两个写方 = 判据**静默漏判**（#5247 的反面形态）。
        assert {"product_update", "sku_update"} <= WRITE_TOOL_SURFACE, (
            "#5303 回绑的两个 A 档可逆写工具不在扫描面里 ⇒ 含它们期望的用例不再被判成"
            "写用例（效果层 / 复位要求对它静默失效）")
        assert not ({"product_manage", "inventory_manage", "order_manage",
                     "processing_item_manage"} & WRITE_TOOL_SURFACE), (
            "#5247 已退场、且 #5303 **未**回绑的写工具仍在扫描面里 ⇒ 判据按旧地图判（幽灵写方）")

    def test_scan_surface_covers_the_known_writers(self, monkeypatch):
        """**扫描面自证**：当前**存在**的写方必须被 `live_write_expectations` 认出来。

        否则判据恒绿（`migao-acceptance`「绿了但没跑」）。
        原口径：拿 PR-021 / PR-025 / PR-007 / PR-017 / PR-005 的写期望当"识别力证据"。
        **#5247 证伪**：那 5 条的写工具已全部退场（PR-017/PR-005 改判为只读、
        PR-021/PR-025/PR-007 的写 action 已从源码删除）⇒ 它们不再是写方证据。
        新口径（三类都钉住，取**真实用例库**）：
          ① 整工具写 —— `CH-009` 的 ` or ` 形态字符串期望里必须析出 `order_create`；
          ② 整工具写 —— `AS-003` 的 `after_sales_manage or aftersale_create` 里析出 `aftersale_create`；
          ③ 🔴 **#5302 改判**：原第 ③ 条（`ST-003` 的 `settings_manage(action=change_password)`）随
             settings 域只读化**消失**（该用例已改判为「能力下线的如实告知」）⇒ 改成断言**新真值**：
             真实用例库里**不再有任何 action 级写方**（若又出现，说明有写 action 复活 —— 这里先红）；
          ④ action 级写的**识别力**由**合成注入**自证（见 `_with_synthetic_action_writer`）；
          ⑤ **防空转下界**：从真实库解析出的活写方集合必须非空（解析失效 ⇒ 红）。
        """
        by = {c["id"]: c for c in _all_cases()}
        assert ("order_create", "") in live_write_expectations(by["CH-009"]), (   # 字符串 ` or ` 必须拆开
            f"判据认不出 CH-009 的整工具写（` or ` 没拆？）：{live_write_expectations(by['CH-009'])}")
        assert ("aftersale_create", "") in live_write_expectations(by["AS-003"]), (
            f"判据认不出 AS-003 的整工具写：{live_write_expectations(by['AS-003'])}")
        corpus_action_level = sorted(k for k in live_writer_keys(_all_cases()) if k[1])
        assert corpus_action_level == [], (
            f"真实用例库里又出现了 action 级写方 {corpus_action_level} —— taxonomy 的 "
            "`WRITE_TOOL_ACTIONS` 现为空集（#5302 后无「部分写」工具）⇒ 要么有人把写 action "
            "加回了工具源码（那是能力复活，先改判 taxonomy 与判据），要么用例锚点已过期"
        )
        tool, action = _with_synthetic_action_writer(monkeypatch)
        fake = {"id": "FAKE-SCAN", "user_inputs": ["遮光窗帘相关的通知都标成已读"],
                "expectations": [{"tool": tool, "args": {"action": action}}]}
        assert (tool, action) in live_write_expectations(fake), (
            f"判据认不出 action 级写方（合成注入后仍不认）：{live_write_expectations(fake)}")
        live = live_writer_keys(_all_cases())
        assert live, "从真实用例库解析不到任何活写方 —— 扫描面失效（判据会静默空跑）"
        assert {k[0] for k in live} >= {"order_create", "aftersale_create", "product_update",
                                        "sku_update"}, (
            f"真实库的活写方没被认全：{sorted(live)}")

    def test_rebound_writers_are_seen_by_the_surface(self):
        """**#5303 判据（防空转）**：回绑的两个 A 档可逆写工具必须被 `live_write_expectations` 认出。

        为什么必须钉在**真实库**上（不只是钉 taxonomy）：扫描面漂移的形态正是"taxonomy 改了、
        库里那条期望却没被认出来" —— 此时判据 ② 对 `PR-009` / `PR-010` / `PR-021` **静默**失效
        （无对象 ⇒ 判绿，`migao-acceptance`「绿了但没跑」）。
        判别力（反方向）：**未**回绑的 `product_manage` 必须仍认不出（幽灵写方）。
        """
        by = {c["id"]: c for c in _all_cases()}
        assert ("product_update", "") in live_write_expectations(by["PR-009"]), (
            "#5303：PR-009 的 `product_update` 期望没被认成活写方 ⇒ 判据 ② 对它静默失效"
            f"（实际认到：{live_write_expectations(by['PR-009'])}）")
        assert ("product_update", "") in live_write_expectations(by["PR-010"]), (
            "#5303：PR-010（写链路已恢复）的 `product_update` 期望没被认成活写方 ⇒ 同上"
            f"（实际认到：{live_write_expectations(by['PR-010'])}）")
        assert ("sku_update", "") in live_write_expectations(by["PR-021"]), (
            "#5303：PR-021 的 `sku_update` 期望没被认成活写方 ⇒ 同上"
            f"（实际认到：{live_write_expectations(by['PR-021'])}）")
        ghost = {"id": "FAKE-12", "user_inputs": ["把遮光窗帘改成 199 元"],
                 "expectations": [{"tool": "product_manage", "args": {"action": "update"}}]}
        assert live_write_expectations(ghost) == [], (
            "未回绑的 `product_manage` 被算成活写方 ⇒ 扫描面漂移（判据按旧地图判）")


# ══════════════════════════════════════════════════════════════════════════════
# 四、判据 ①：写面必须归类（fail-closed）
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteSurfaceIsClassified:
    def test_every_live_write_is_classified(self):
        """**核心**：活写方的每个 `tool(action)` 写期望都已归类（fail-closed）。

        #5247 后真实库里的活写方只剩 5 个 key（3 类"不触达夹具" + 2 个"未声明 action"的保守
        判写口子，见 `PRODUCT_ATTR_WRITERS`）；**#5303 起多两个真·商品属性写方**
        （`product_update` / `sku_update` 回绑）—— 少，但**每一个都必须有人回答**"改不改共享夹具"。
        """
        bad = unclassified_live_writes(_all_cases())
        assert bad == {}, (
            "出现**未归类**的活写方 —— 它改的是不是共享夹具没人回答，"
            "判据 ②③（要不要复位）因此无从适用。请在 PRODUCT_ATTR_WRITERS 显式归类：\n  "
            + "\n  ".join(f"{k} ← {v}" for k, v in sorted(bad.items())))

    def test_no_writer_key_is_double_claimed(self, monkeypatch):
        """**#5303 新判据**：一个 `(tool, action)` key **不得同时**出现在活写方表与留档表里。

        留档表的语义是"**已不是**活写方"（历史），活写方表是判据 ① 的比对面 —— 两表同 key
        = 两份互相矛盾的声明共存，而判据 ① 只看活写方表 ⇒ **没有任何东西会因此变红**。
        #5303 回绑 `product_update` / `sku_update` 时正是这个形态（留档条目必须移出）。
        """
        assert double_claimed_writer_keys() == [], (
            "同一写方 key 同时被登记为「活写方」与「已退场留档」—— 留档会读成"
            f"「仍活着」，而判据 ① 只看活写方表（双源）：{double_claimed_writer_keys()}")
        # 注入式红证：把同一条 key 塞回留档表 ⇒ 判据必须报出来（否则它是空壳）
        monkeypatch.setitem(RETIRED_ATTR_WRITERS, ("product_update", ""), "product_attr")
        assert double_claimed_writer_keys() == [("product_update", "")], (
            "同一 key 在两表里都存在却认不出来 ⇒ 本判据空转（假绿）")

    def test_red_proof_unclassified_action_is_caught(self, monkeypatch):
        """**红证 ①（action 级写方）**：没归类的写 action ⇒ 判据必红。

        🔴 **#5302 改判**：原锚点（`notification_manage(mark_read)`）随 settings 域只读化失效
        （`WRITE_TOOL_ACTIONS` 归零 ⇒ 真实库里再无 action 级写方）⇒ 换成**合成注入**
        （`_with_synthetic_action_writer`），缺陷形态（"未归类的写 action"）逐字保留。
        """
        tool, action = _with_synthetic_action_writer(monkeypatch)
        fake = [{"id": "FAKE-1", "user_inputs": ["遮光窗帘相关的通知都标成已读"],
                 "expectations": [{"tool": tool, "args": {"action": action}}]}]
        assert unclassified_live_writes(fake) == {f"{tool}({action})": ["FAKE-1"]}, (
            "未归类的 action 被放过了 —— 新写方会悄悄出现（判据变空壳）")
        # 负例（证明上面那声红来自"未归类"，不是判据恒红）：登记后即绿
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, (tool, action), "")
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
        `product_manage` / `order_manage` / … 从 B 端解绑（两侧工具集都不可达）
        ⇒ 它们不再是写方，本判据看不见它们。
        ⚠️ 2026-09-24（#5303）：原本文用 `product_update` / `sku_update` 当"幽灵"的活例 ——
        **它们已回绑、重新可达** ⇒ 不再是本条的实例（继续拿它们当负控 = 用真写方证明
        "看不见写方"，红证会变成永远不可能红的假证）。现取的幽灵实例是 `product_manage`
        （#5247 解绑、#5303 **未**回绑）。口径的另一半由 taxonomy 的
        `test_write_tool_sets_only_name_reachable_tools` 兜底：新增写工具必须先在 taxonomy
        里登记，否则它**不是**"可达写方"。
        判别力没有丢：**活**写方的新 action 仍会被判据 ① 拦住（见上面两条红证），
        回绑的写方会被 `test_rebound_writers_are_seen_by_the_surface` 正面认出来。
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

    ⚠️ 2026-09-24（#5247）：本判据**一度**在真实库上命中 0 条 —— 当时的活写方（`order_create` /
    `aftersale_create` / `notification_manage` / `settings_manage`）都不触达商品属性
    ⇒ 没有"必须声明复位"的对象。**那不是放宽**：机制照旧可红，只是被测对象（商品属性写方）
    已被 #5247 删除，当时的红证只能把"触达可复位属性"这一格**注入**到可达写方上。
    ⚠️ 2026-09-24（#5303）**改判**：`product_update` / `sku_update` 回绑 ⇒ 真实库重新有
    **真·商品属性写方**（`PR-009` / `PR-010` → `base_price`、`PR-021` → `sku_price`）⇒ 本判据
    重新有**真对象**（`test_rebound_writers_declare_their_restore` + 不带注入的红证
    `test_red_proof_rebound_writer_without_post_clean_is_caught`）。上面那两条注入式红证
    **保留**：它们证的是机制本身，与对象是否存在无关（R1：不因为对象回来了就删证明）。
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

        🔴 **#5302 改判**：原锚点（`notification_manage(mark_read)`）随 settings 域只读化失效
        ⇒ 换成**合成注入**（`_with_synthetic_action_writer`），缺陷形态原样保留。
        """
        tool, action = _with_synthetic_action_writer(monkeypatch)
        fake = [{"id": "FAKE-11", "user_inputs": ["遮光窗帘相关的通知都标成已读"],
                 "expectations": [{"tool": tool, "args": {"action": action}}]}]
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, (tool, action), "status")
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
        """**改判留档**：被判"已改判为只读 / 已退役"的用例，其期望里**不得**再有活写方。

        逐条留档（为什么不再在册）见 `REGISTERED_RESTORE_GAPS` 的 docstring；
        这里把"它们真的不再被判据看见"变成机器可判。
        ⚠️ 2026-09-24（#5303）：原 9 条名单里的 `PR-009` / `PR-010` / `PR-021` **已移出** ——
        `product_update` / `sku_update` 回绑 ⇒ 这三条**重新是活写方**（把它们留在名单里 =
        用"已退役"的判据锁住三条已回归的用例：本条会恒红，随后多半被人删掉换成弱断言）。
        `PR-010` 是集成期**追加**恢复的一条（写链路「改价 + 确认闸」整条回来），
        与 PR-009 同写 `base_price`。
        它们的新真值由 `test_rebound_writers_are_seen_by_the_surface`（被认成活写方）与
        `test_rebound_writers_declare_their_restore`（**已声明**对应复位）正面钉住。
        判别力：谁要是把写方加回**其余 6 条**（例如重新声明某个活写工具），判据 ①（未归类即红）
        /②（未声明复位即红）会立刻响 —— 台账的"留档"结论随之必须重算。
        """
        by = {c["id"]: c for c in _all_cases()}
        for cid in ("PR-005", "PR-017", "PR-025", "PR-026", "PR-027", "CH-006"):
            got = live_write_expectations(by[cid])
            assert got == [], (
                f"{cid} 仍带着活写方期望 {got} —— 「已改判为只读/已退役」这条留档不再成立，"
                "台账（现为空）必须按新真值重算")

    # ── #5303：回绑写方的**正面**判据（真实库 + 无注入红证）─────────────────────
    def test_rebound_writers_declare_their_restore(self):
        """**#5303 主判据（真实库）**：回绑写方的三条用例（`PR-009` / `PR-010` / `PR-021`）
        都必须声明复位。

        这是本判据从"无对象"变回"有对象"的直接判据 —— 集成方只回绑工具、漏了 `post_clean`
        （或声明了**另一个**复位类型 / 属性键对不上）⇒ 本条先红。
        """
        by = {c["id"]: c for c in _all_cases()}
        rebound = ["PR-009", "PR-010", "PR-021"]
        miss = missing_restores([by[cid] for cid in rebound])
        assert miss == {}, (
            "#5303 回绑的写方缺复位声明 ⇒ 跑完把共享夹具留给同栈其它用例（#4075 的病灶）：\n  "
            + "\n  ".join(f"{cid}: 缺 {sorted(a)} 的复位" for cid, a in sorted(miss.items())))
        for cid in ("PR-009", "PR-010"):
            assert "product_price_restore" in declared_restore_types(by[cid]), (
                f"{cid} 写的是**商品级** `base_price` ⇒ 必须声明 `product_price_restore`："
                f"{sorted(declared_restore_types(by[cid]))}")
        assert "sku_price_restore" in declared_restore_types(by["PR-021"]), (
            "PR-021 写的是 **SKU 价** ⇒ 必须声明 `sku_price_restore`："
            f"{sorted(declared_restore_types(by['PR-021']))}")

    def test_red_proof_rebound_writer_without_post_clean_is_caught(self):
        """**红证 ②（#5303 真写方，**零注入**）**：回绑的两个工具触达可复位属性、用例却没声明
        复位 ⇒ 必红。

        与上面两条注入式红证的分工：它们证"（属性键 → 复位类型）这一格生效"，本条证
        "**真实的**回绑写方此刻正被判据看着" —— #5303 之后不再需要把属性键注入到
        `order_create` 上才能触发判据 ②（对象本身回来了）。
        """
        for cid, tool, attr, restore in (
                ("FAKE-13", "product_update", "base_price", "product_price_restore"),
                ("FAKE-14", "sku_update", "sku_price", "sku_price_restore")):
            fake = [{"id": cid, "user_inputs": ["把遮光窗帘改成 199 元"],
                     "expectations": [{"tool": tool}]}]
            assert touched_attrs(fake[0]) == {attr}, (
                f"{tool} 没被算成写 {attr} ⇒ 判据 ② 对它无对象：{touched_attrs(fake[0])}")
            assert missing_restores(fake) == {cid: [attr]}, (
                f"{tool} 无复位声明却没判红 ⇒ 判据 ② 在真实写方上失效：{missing_restores(fake)}")
            ok = [dict(fake[0], post_clean=[{"type": restore, "product_keyword": "遮光窗帘"}])]
            assert missing_restores(ok) == {}, (
                f"声明了 {restore} 仍判红 ⇒ 判据恒红（判别力失效）")

    def test_price_restore_types_are_orthogonal(self):
        """**#5303 正交性判据**：商品级 `base_price` 与单规格 `sku_price` 各绑各自的复位类型。

        为什么必须钉住：若两个属性共用一个键（或两个复位类型共用一个 attr），
        "写商品级价、却只声明了 SKU 价复位"会被判绿 —— 那是**假绿**（世界仍然是脏的），
        正是 #4075 病根在新写方上的重现：复位手段对不上被改的那个属性。
        """
        m = runner_restore_map()
        assert m.get("base_price") == "product_price_restore", (
            f"商品级基准价没绑定 `product_price_restore`：{m}")
        assert m.get("sku_price") == "sku_price_restore", f"SKU 价的复位类型被改了：{m}"
        fake = [{"id": "FAKE-15", "user_inputs": ["把遮光窗帘改成 199 元"],
                 "expectations": [{"tool": "product_update"}],
                 "post_clean": [{"type": "sku_price_restore", "product_keyword": "遮光窗帘",
                                 "color_name": "米白", "price": 168}]}]
        assert missing_restores(fake) == {"FAKE-15": ["base_price"]}, (
            "写商品级价、只声明 SKU 价复位竟判绿 ⇒ 两个属性不是正交的（假绿）")

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

    def test_red_proof_rebound_writer_without_a_restore_type_is_a_gap(self, monkeypatch):
        """**红证 ③（#5303 的反方向）**：撤掉 `base_price` 的复位类型绑定 ⇒ 回绑的写方**立刻**
        变成"无复位类型"的缺口（必须登记台账）。

        为什么值得单列：它证"台账仍为空"**不是销账** —— `PR-009` 不进台账，只因为 `base_price`
        已有复位类型；绑定一撤，同一条用例立刻走台账路径（fail-closed）。
        """
        monkeypatch.delitem(lr.RESTORE_TYPES_BY_ATTR, "base_price")
        fake = [{"id": "FAKE-16", "user_inputs": ["把遮光窗帘改成 199 元"],
                 "expectations": [{"tool": "product_update"}]}]
        assert unregistered_restore_gaps(fake) == {"FAKE-16": ["base_price"]}, (
            f"没有复位类型的属性没走台账路径（判据 ③ 失效）：{unregistered_restore_gaps(fake)}")
        assert ledger_new_entries(fake) == ["FAKE-16"], (
            "新缺口没进红名单 ⇒ 台账的 fail-closed 语义失效")

    def test_unknown_action_attr_lands_in_the_ledger_path(self, monkeypatch):
        """`action` 未声明的 action 级写工具走台账路径（可见），不被当成"不改夹具"。

        taxonomy 对 action 级写工具**缺 action 时保守判写**（见 `is_write_expectation` 的
        docstring）⇒ 分类表把这种 key 记为 `unknown`（"改的是哪个属性"不可判定）。它必须进台账
        （可见、要跟随 issue），而不是被静默当成 `""` —— 否则"未定型写方"会从判据 ②③ 里同时消失。
        🔴 **#5302 改判**：真实库里再无 action 级写方（`WRITE_TOOL_ACTIONS` 归零）⇒ 换成
        **合成注入**（`_with_synthetic_action_writer` 的裸工具名形态），判别力原样保留。
        """
        tool, _action = _with_synthetic_action_writer(monkeypatch)
        # 归类的**真值**：action 未声明的「部分写」写方 = 属性不可判定 ⇒ 必须记 `unknown`
        # （这正是本条要证的"走台账路径"，不是为了让断言变绿的补丁）。
        monkeypatch.setitem(PRODUCT_ATTR_WRITERS, (tool, ""), "unknown")
        fake = [{"id": "FAKE-10", "user_inputs": ["处理一下遮光窗帘的通知"],
                 "expectations": [{"tool": tool}]}]
        assert live_write_expectations(fake[0]) == [(tool, "")], (
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
        # #5303 的复位族第三批：商品级基准价（`product_update` 的写面）—— 属性键必须**独立**
        # 于 `sku_price`（正交性判据见 TestSharedFixtureWritersDeclareRestore
        # ::test_price_restore_types_are_orthogonal）。
        assert "product_price_restore" in lr._POSTCLEAN_TYPES
        assert lr.RESTORE_TYPES_BY_ATTR.get("base_price") == "product_price_restore", (
            "#5303 回绑的 `product_update` 写的是商品级 `base_price` —— 没有独立属性键 ⇒ "
            f"判据 ②/③ 对它对不上号：{lr.RESTORE_TYPES_BY_ATTR}")
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
        它与仍在库里的 `post_clean` 声明、runner 的复位族同源）。
        ⚠️ 2026-09-24（#5303）：`sku_price` / `base_price` 现在由**活写方表**提供
        （`sku_update` / `product_update` 回绑）—— 留档表少了两条 key，比对面照样闭合
        （这正是"两表不得重复声明同一个 key"的判据 `test_no_writer_key_is_double_claimed`
        要防的形态）。
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
    """内存商品库（形状照抄种子：`status` + `basePrice` + `skus[colorName/sellingMethod/doorWidth/price]`）。

    `basePrice`（商品级基准价）是 #5303 新增的那一面：`product_update` 写它
    （PATCH `/api/admin/agent/products/{id}`），而 `product_skus.price` 的接地真值就是它。

    `fail_keys` / `ignore_writes` 是两个**失败注入**口子：
      · `fail_keys`     —— 端点返回 500（写失败）；
      · `ignore_writes` —— 写返回 200 但**不落地**（#3807 的"静默空转"形态：
        "2xx ≠ 值已落地"，只有回读校验才抓得到 —— 本组专治这一格）。
    """

    def __init__(self, products=None):
        self.products = products if products is not None else [
            {"id": "prod_eval_blackout", "name": "遮光窗帘", "status": SEED_STATUS,
             "basePrice": SEED_PRICE,
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

    def base_price(self, pid="prod_eval_blackout"):
        """商品级基准价（`basePrice`；#5303 的写面真值）。"""
        p = self.by_id(pid) or {}
        return p.get("basePrice")

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

    def set_base_price(self, pid: str, body: dict) -> bool:
        """商品级基准价写面（#5303；合同同后端 DTO：**只认** `basePrice`）。

        ⚠️ 刻意**照抄后端契约**（未知字段被忽略）：这样"复位发错字段名"的形态
        （#3807 的静默空转）在假体上也会静默不落地 ⇒ 只有回读校验才抓得到（同真后端）。
        """
        p = self.by_id(pid)
        if not p:
            return False
        if self.ignore_writes:
            return True
        if "basePrice" in body:
            p["basePrice"] = body["basePrice"]
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
        if method == "PATCH" and "/agent/products/" in path:
            # #5303：商品级基准价写面（`product_update` 的端点）
            pid = path.rstrip("/").rsplit("/", 1)[-1]
            ok = self.shop.set_base_price(pid, kw.get("json") or {})
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
# #5303：**商品级**基准价复位（PR-009 的写方 `product_update` 改的那一面）
PRODUCT_PRICE_SPEC = {"type": "product_price_restore", "product_keyword": "遮光窗帘",
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


class TestProductPriceRestore:
    """#5303：`product_update` 回绑 B 端 ⇒ **商品级**基准价这一面重新需要复位。

    本组的四格与 `TestSkuPriceRestore` 同形（真实分支 / 幂等 / 配置错误 / 失败可见 + 静默
    空转），因为**复位族的口径必须逐条一致** —— 差异只有"被复位的是哪个属性"。
    """

    def test_restores_the_fixture(self, monkeypatch):
        """**走真实分支**：PR-009 的病灶面 —— 商品级价被改成 199 ⇒ 复位回 168。"""
        shop = _Shop()
        shop.set_base_price("prod_eval_blackout", {"basePrice": 199})
        assert shop.base_price() == 199, "夹具没被写脏（夹具写错了？）"
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRODUCT_PRICE_SPEC)
        assert shop.base_price() == SEED_PRICE, f"复位没生效：{shop.base_price()} / {msg!r}"
        assert ("PATCH", "/api/admin/agent/products/prod_eval_blackout") in shop.calls, shop.calls
        assert not msg.startswith(lr._POSTCLEAN_BAD_MARKERS), msg
        assert "回读一致" in msg or "已复位" in msg, msg

    def test_is_idempotent(self, monkeypatch):
        """**幂等**：本就在种子值 ⇒ 成功（且**不**发多余的写请求）。"""
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRODUCT_PRICE_SPEC)
        assert not msg.startswith(lr._POSTCLEAN_BAD_MARKERS), msg
        assert "本就" in msg, f"幂等路径的文案必须点明「本就等于种子值」：{msg!r}"
        assert not [c for c in shop.calls if c[0] == "PATCH"], "幂等时不该发写请求"

    def test_missing_price_is_a_config_error(self, monkeypatch):
        """配置错误（缺 `price`）**不是**静默跳过：走**阶段化**标记、折进结论。"""
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        spec = {"type": "product_price_restore", "product_keyword": "遮光窗帘"}
        post = _run(spec)
        assert post.startswith(lr._POSTCLEAN_NOT_APPLIED), post
        assert lr.check_postclean_not_applied([post]) == [post]
        pre = _run(spec, phase="pre")
        assert pre.startswith(lr._PRECONDITION_NOT_APPLIED), (
            f"同一缺口在 pre 阶段必须走 pre 的标记（归因不指错阶段）：{pre!r}")

    def test_missing_target_is_visible(self, monkeypatch):
        """**失败可见**：目标商品不在库里 ⇒ `PRECONDITION_NOT_RESTORED`（进结论）。"""
        shop = _Shop(products=[])
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRODUCT_PRICE_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert lr.check_postclean_not_applied([msg]) == [msg], "未复位没被折进结论"

    def test_write_failure_is_visible(self, monkeypatch):
        """**失败可见**：写端点 500 ⇒ 标记进结论（不是静默）。"""
        shop = _Shop()
        shop.set_base_price("prod_eval_blackout", {"basePrice": 199})
        shop.fail_keys.add(("PATCH", "/agent/products/"))
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRODUCT_PRICE_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "500" in msg, msg

    def test_silent_noop_is_caught_by_the_readback(self, monkeypatch):
        """**#3807 的形态**：写返回 2xx 但值没落地 ⇒ 必须被**回读**抓住（不是静默成功）。"""
        shop = _Shop()
        shop.set_base_price("prod_eval_blackout", {"basePrice": 199})
        shop.ignore_writes = True
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRODUCT_PRICE_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), (
            f"2xx 但值未落地被当成成功（静默空转复现）：{msg!r}")
        assert "未生效" in msg, msg

    def test_sku_restore_does_not_fix_the_product_price(self, monkeypatch):
        """**本类型存在的理由**（正交性红证）：只跑 `sku_price_restore` **治不了**商品级脏值。

        没有这条，本类型就有可能是"多写了一个没人需要的复位动作"—— 实测口径相反：
        SKU 价复位只改 `product_skus.price`，商品级 `basePrice` 仍是脏的
        （而按商品级真值判定的用例读的就是它）。
        """
        shop = _Shop()
        shop.set_base_price("prod_eval_blackout", {"basePrice": 199})
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        msg = _run(PRICE_SPEC)                       # 只跑 SKU 价复位
        assert not msg.startswith(lr._POSTCLEAN_BAD_MARKERS), msg
        assert shop.base_price() == 199, (
            "SKU 价复位竟然把商品级价也改了 —— 两个属性不是正交的（本类型的理由不成立）")
        # 再跑商品级复位 ⇒ 归零（两条各治一面）
        assert not _run(PRODUCT_PRICE_SPEC).startswith(lr._POSTCLEAN_BAD_MARKERS)
        assert shop.base_price() == SEED_PRICE


class TestTwoConsecutiveRuns:
    """**红证 ③**：连续两次运行同一用例，第二次**开始时**夹具是种子原值。

    用假体证明（不必真跑 LLM）：第一次运行里"写方"把夹具改脏（走与 runner 相同的端点），
    用例结束时 `post_clean` 复位 ⇒ 第二次运行的起点 = 种子。
    """

    @staticmethod
    def _pollute(shop: _Shop):
        """模拟**写方**（agent 的工具调用）：PR-021 改 SKU 价 + PR-025 下架 + PR-009 改商品价。

        ⚠️ 2026-09-24（#5303）：补第三个写面（商品级 `basePrice`，`product_update` 的端点）——
        端到端红证必须覆盖**每一个回绑的写方**，否则"复位接好了"这句话只对其中一面成立。
        """
        async def _do():
            async with _FakeClient(shop) as c:
                await c.patch(f"{lr.ADMIN_API}/api/admin/agent/products/prod_eval_blackout/skus/price",
                              headers={}, json={"price": 150, "color": "米白"}, timeout=15)
                await c.patch(f"{lr.ADMIN_API}/api/admin/agent/products/prod_eval_blackout",
                              headers={}, json={lr.PRODUCT_PRICE_FIELD: 199}, timeout=15)
                await c.put(f"{lr.ADMIN_API}/api/admin/products/prod_eval_blackout/status",
                            headers={}, json={"status": "off_sale"}, timeout=15)
        asyncio.run(_do())

    def test_second_run_starts_from_the_seed_value(self, monkeypatch):
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        # ── 第 1 次运行 ──
        self._pollute(shop)
        assert (shop.status(), shop.price("米白"), shop.base_price()) == \
            ("off_sale", 150, 199), "夹具没被写脏（夹具写错了？）"
        msgs = asyncio.run(lr._run_clean_specs(
            "tok", [STATUS_SPEC, PRICE_SPEC, PRODUCT_PRICE_SPEC], "post"))
        assert lr.check_postclean_not_applied(msgs) == [], msgs
        # ── 第 2 次运行的**起点** ──
        assert (shop.status(), shop.price("米白"), shop.base_price()) == \
            (SEED_STATUS, SEED_PRICE, SEED_PRICE), (
            f"第二次运行看到的不是种子原值：{shop.status()} / {shop.price('米白')} / "
            f"{shop.base_price()}")

    def test_without_post_clean_the_second_run_starts_dirty(self, monkeypatch):
        """**负例**（证明上面的绿不是恒真）：不复位 ⇒ 第二次运行起点就是脏值。"""
        shop = _Shop()
        monkeypatch.setattr(lr, "httpx", _FakeHttpx(shop))
        self._pollute(shop)
        # 不执行 post_clean（模拟"去掉某写方的 post_clean"）
        assert (shop.status(), shop.price("米白"), shop.base_price()) == \
            ("off_sale", 150, 199), (
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