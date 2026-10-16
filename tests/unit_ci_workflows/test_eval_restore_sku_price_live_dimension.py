# case_ids: PR-021, PR-006, PR-018, PR-014
"""`sku_price_restore` 的回读匹配只能按**活着的** SKU 维度（色名 + 门幅）—— #7048 P9。

## 症状（逐字读数：PR-021 连续 5 个 run 恒红，而 DB 真值早已复位成功）

`local_runner.py::_restore_sku_price` 的复位链路是「找商品 → 回读 `skus[]` 匹配目标规格 →
比对现值 → 不等才 PATCH → **再回读证实**」。最后一步（以及幂等预判那一步）走
`_match_sku_price(skus, color, method, width)`，而它按 **色名 + `selling_method` + 门幅**
三个维度过滤：

    症状（`/tmp/eval-rerun-1016-2131.log`，`PR-021` 段）：
    ⛔ post_clean: PRECONDITION_NOT_RESTORED: post_clean: 商品「遮光窗帘」/米白/bulk_cut/门幅2.8
       的 SKU 价复位**未证实** —— 回读里找不到该规格的 SKU
    ⇒ 该条被折叠成「通过但被 fail-closed 阻塞（跨 run 复发，score=1）」。

同一个 run 里 DB 真值是**已复位**的（直连夹具库实测）：

    → prod_eval_blackout / 米白 / 2.8 / price = 168.00 / stock = 500.0

⇒ 红的是**回读判据**，不是世界，也不是 agent（该 run `score=100%`）。

## 根因：`selling_method` 在 SKU 面已被迁移删除（读侧却在过滤它）

| 面 | 事实 | durable 锚 |
|---|---|---|
| schema | `product_skus.selling_method` **列已删**；售卖方式上移为 `products.selling_methods`；唯一键 = `(product_id, color_id, door_width)` | `mibao_eval_seed.sql` 的「V111：`product_skus.selling_method` 列已删除…本 INSERT 不得再写该列」；DB 约束 `uq_product_skus_combination` |
| 回读 DTO | `ProductSkuResponse` **不再有** `sellingMethod` | `backend/admin-api/src/main/java/com/migao/admin/dto/ProductSkuResponse.java` 的类注释：「本 DTO **不再有** `sellingMethod`…（V113 迁移删列，issue #5245 C2）」 |
| 写侧匹配 | 只按 color + door_width | `AgentProductController.updateSkuPrice` 的注释：「V108：售卖方式不再是 SKU 维度 ⇒ 不参与定位」 |
| 线上实测 | 回读里每个 SKU 的 `sellingMethod` 都是 `null` | `GET /api/admin/products/prod_eval_blackout`（带 `X-Tenant-Id`）⇒ `{'colorName': '米白', 'sellingMethod': None, 'doorWidth': '2.8', 'price': 168.0}` |

⇒ 读侧按 `sellingMethod` 过滤时，"键存在且相等"**恒不成立**（键根本不在 payload 里）
⇒ `_match_sku_price` 恒返回 `None` ⇒ 复位族**恒判"未证实"** ⇒ 假红阻塞。
按色名 + 门幅取值是**确定**的（DB 唯一键保证组合唯一）。

## 判据（每条都有会红的注入点）

| # | 判据 | 怎么红 |
|---|---|---|
| 1 | 回读 payload 无 `sellingMethod` 键时，仍能按 color+width 取到价 | 把 `selling_method` 过滤加回 ⇒ 本格红（= PR-021 病灶本身） |
| 2 | 回读 payload **带** `sellingMethod` 且与声明**不等**时，仍取到该 SKU（该维不参与筛选） | 同上 |
| 3 | 未命中组合仍返回 `None`（不放宽成"随便取第一条"） | 删掉 `color`/`width` 过滤 ⇒ 本格红 |
| 4 | 纯函数**零网络**：即使被调用也不得发 HTTP | 改成本文件的替身被触发 ⇒ 红（`RuntimeError`） |

## 为什么用单测（不是评测）

`_match_sku_price` 是**纯函数**（吃 `skus[]`、吐价），零 LLM / 零网络
（`migao-dev-flow` §16.1：能下层不上层）；评测层只证明"改后读数转绿"，机器判据放这里。
⚠️ 本目录在 CI 只 `pip install pytest pytest-xdist pyyaml`，而 `local_runner` 有模块级
`import httpx` ⇒ 用下方最小替身（与 `test_eval_must_succeed_or_group.py` 同形）。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

#: 线上回读的真实形态（`GET /api/admin/products/prod_eval_blackout`，tenant 1）：
#: V113 之后 DTO 里**没有** `sellingMethod` 键 —— 两个 SKU 都只带 colorName/doorWidth/price。
LIVE_READBACK = [
    {"id": "2", "colorName": "浅灰", "doorWidth": "2.8", "price": 168.0, "stock": 500.0},
    {"id": "5", "colorName": "米白", "doorWidth": "2.8", "price": 168.0, "stock": 500.0},
]

#: 万一将来 DTO 把该键以 `null` / 其它值带回（本次实测 = `None`）—— 同样不得参与筛选。
NULL_DIM_READBACK = [
    {"id": "5", "colorName": "米白", "sellingMethod": None, "doorWidth": "2.8", "price": 150.0},
]

#: 反例：该键回来了、且与用例声明（`bulk_cut`）**不等** ⇒ 旧实现会把这条 SKU 跳过。
WRONG_DIM_READBACK = [
    {"id": "5", "colorName": "米白", "sellingMethod": "whole_roll", "doorWidth": "2.8",
     "price": 150.0},
]


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身；一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)

    import local_runner
    return local_runner


lr = _load_runner()


def test_match_sku_price_ignores_removed_selling_method_dimension():
    """判据 1：线上形态（payload 无该键）必须能取到价 —— PR-021 的病灶面。

    注入式红证：在 `_match_sku_price` 里把
    `if method and str(s.get("sellingMethod") or s.get("selling_method") or "") != method: continue`
    加回去 ⇒ 本格当场红（返回 None，而 `_restore_sku_price` 会据此报
    「回读里找不到该规格的 SKU」⇒ fail-closed 阻塞 PR-021）。
    """
    got = lr._match_sku_price(LIVE_READBACK, "米白", "bulk_cut", "2.8")
    assert got == 168.0, (
        "回读 payload 按 V113 之后的 DTO 形态（无 sellingMethod 键）必须能取到价；"
        f"实际 {got!r} —— 该维一旦参与过滤 ⇒ 恒 None ⇒ PR-021 假红阻塞")


def test_match_sku_price_dimension_neutral_when_key_present_but_null():
    """判据 2a：键以 `null` 回来（本次线上实测就是 None）⇒ 同样不得参与筛选。"""
    got = lr._match_sku_price(NULL_DIM_READBACK, "米白", "bulk_cut", "2.8")
    assert got == 150.0, f"该维已从 SKU 面删除 ⇒ 不允许用它的值判定；实际 {got!r}"


def test_match_sku_price_dimension_neutral_when_key_present_with_other_value():
    """判据 2b：键回来了且值**不等** ⇒ 那一维不参与筛选（防"换个值又变回筛选维"）。"""
    got = lr._match_sku_price(WRONG_DIM_READBACK, "米白", "bulk_cut", "2.8")
    assert got == 150.0, (
        "SKU 组合唯一性由 DB 约束 (product_id, color_id, door_width) 保证 ⇒ "
        f"色名 + 门幅已足够定位；实际 {got!r}")


def test_match_sku_price_still_misses_when_color_or_width_do_not_match():
    """判据 3（不降判别力的对照格）：未命中组合仍返回 None —— 不是"随便取第一条"。"""
    assert lr._match_sku_price(LIVE_READBACK, "雾霾蓝", "bulk_cut", "2.8") is None
    assert lr._match_sku_price(LIVE_READBACK, "米白", "bulk_cut", "3.0") is None


def test_match_sku_price_is_pure_no_network():
    """判据 4：纯函数 —— 空/畸形输入不得抛错，也不得触到 httpx 替身。"""
    assert lr._match_sku_price([], "米白", "bulk_cut", "2.8") is None
    assert lr._match_sku_price(None, "米白", "bulk_cut", "2.8") is None
    assert lr._match_sku_price(["not-a-dict"], "米白", "bulk_cut", "2.8") is None


# ── 用例面：等价路径的 OR 必须**两侧对称**（#7048 P9；PR-018 与 PR-006 同形态）──────────
_CASES_YML = (REPO_ROOT / ".github" / "cases" / "product.yml").read_text(encoding="utf-8")
_OR_TOOLS = ("inventory_manage", "product_search")


def _case_block(case_id: str) -> str:
    """取某用例的 yaml 片段（从 `- id: X` 到下一个 `- id:`），**剔除注释行**。

    ⚠️ 必须剔注释：本仓用例的注释里大量**引用**别的用例的声明原文（例如 PR-018 的注释就逐字
    引了 PR-006 的 `must_succeed` OR 与 expectations OR）—— 不剔注释时判据会被**注释里的
    ` or `** 喂成假绿（本包实测：把 PR-018 的 `must_succeed` 改回单工具，旧版判据仍判绿）。
    这正是「引用即实例」的同族坑（`migao-dev-flow` §2.2）。
    """
    start = _CASES_YML.index(f"  - id: {case_id}\n")
    nxt = _CASES_YML.find("\n  - id: ", start + 1)
    block = _CASES_YML[start:nxt if nxt != -1 else len(_CASES_YML)]
    return "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))


def test_low_stock_cases_have_symmetric_or_paths():
    """PR-006 + PR-018：期望面 OR ⇄ 效果层 OR 成功组（两侧对称）。

    注入式红证：把任一用例的 `must_succeed` 改回单工具（`tool: product_search`）⇒ 本格当场红，
    并具名报出是哪条用例 —— 那正是「按 agent 选哪条等价路径在 0%/100% 之间跳」的病灶。
    """
    for case_id in ("PR-006", "PR-018"):
        block = _case_block(case_id)
        assert " or " in block, f"{case_id}: 期望面丢了等价路径 OR（本用例的存在理由）"
        # 只取 `must_succeed:` 到下一个**声明键**（顶格 4 空格的 yaml 键）之间的真声明。
        after = block.split("must_succeed:", 1)[1]
        decl = [ln for ln in after.splitlines() if ln.startswith("      - ") or not ln.strip()]
        decl_txt = "\n".join(decl)
        assert decl_txt.strip(), f"{case_id}: must_succeed 声明为空（fail-closed 断言被清空）"
        assert " or " in decl_txt, (
            f"{case_id}: 期望面是 OR 而 must_succeed 是**合取**单工具 ⇒ 走另一条等价路径的运行恒判 0%"
            f"（PR-006 的 P5 病灶面）；当前声明：{decl_txt.strip()!r}")
        for tool in _OR_TOOLS:
            assert tool in decl_txt, f"{case_id}: OR 成功组必须覆盖两条等价路径，缺 {tool}"


def test_pr014_first_segment_accepts_both_card_forms():
    """PR-014：第一段（改哪些经商家过目）两条等价载体任一成立，且第二段卡**仍在**。

    注入式红证：把第一条 expectations 改回只认 `interact(component=choice, multiSelect=true)`
    ⇒ 本格红（` or ` 消失）；把 `multiSelect=true` 从第一条删掉 ⇒ 本格红（判别力被吞）。
    反向对照：第二段卡（`- tool: interact` + `component: confirm`）与执行断言不得被删
    —— 删掉就把 OR 洗成"随便一张卡"。

    ⚠️ **本格的边界（如实登记）**：runner 的 `check_expectation` 是**跨轮**「任一调用命中即过」，
    且第二段卡的期望渲染成 `- tool: interact` / `args.component: confirm`（**两行**，与第一条的
    内联文本形态不同）⇒ 本格只能钉住"那段声明**在**"，钉不住"它被**另一次**调用满足"
    （choice 路径下 R1 的那张卡可能同时充当第一段与第二段）。这条**不是本包引入**：
    原用例的 `interact(component=confirm)` 一直是跨轮判据 ⇒ 属**既有覆盖缺口**，已登记进 PR body
    未固化项（不在本包射程内改 runner 的逐轮语义）。
    """
    exp = _case_block("PR-014").split("expectations:", 1)[1].split("must_succeed:", 1)[0]
    assert "interact(component=choice, multiSelect=true) or interact(component=confirm)" in exp, (
        "PR-014 第一段应接受两条等价载体（choice 勾选卡 / confirm 明细卡）；"
        f"当前声明：{exp.strip()[:200]!r}")
    # 第二段卡结构不得被删：`- tool: interact` + `component: confirm`（两行形态）
    assert "- tool: interact\n        args:\n          component: confirm" in exp, (
        "第二段卡（逐条预览展示 + 等点卡）不得被删 —— 删掉即把 OR 洗成'随便一张卡'")
    # 执行断言不得被删
    assert "action: execute" in exp, "执行断言（带 preview 的 batch_id）不得被删"

