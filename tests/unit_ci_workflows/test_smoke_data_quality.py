# case_ids: MC-012, MC-190
"""冒烟数据质量判据的守卫（SDQS，issue #7580 现场；规范 = `docs/testing/smoke-data-quality.md`）。

> **case 声明口径**：`.github/cases/` 目前**没有**「冒烟数据质量」域的条目；本文件与同族守卫
> （`tests/unit_ci_workflows/test_ui_smoke_*.py` 四份）一致声明 **MC-012**（研发工具/基建判据的登记号）。
> 若将来为该域立真实用例，应由用例库所有权包登记后改写本行（不自己编 ID）。

## 病灶（2026-10-23 现取读数）

商家端 UI 冒烟 **33/33 全绿**，而同轮自造的「冒烟SKU商品…」**没有一条 SKU**；
`08-products-list` 的截图停在「加载中…」、`09-products-new` 只存草稿（不填颜色/价格/库存）、
`21-customer-detail` 在「无客户可进详情」时也记通过 —— 绿证明的是**页面渲染**，不是**数据可用**。

## 判据（每条都单独变红；`3` 不得当 `0` 读）

| # | 判什么 | 回归时会怎么红 |
|---|---|---|
| A | `smoke_data_quality.evaluate()` 的六条规则 | 好快照通过；`with_skus=0` / 夹具无 SKU / 门幅带单位 / 面 0 行 / 残留 / 采集失败 ⇒ **各自具名**红 |
| B | **判别力自证（注入式）** | 从「好快照」里逐个删/改关键读数 ⇒ 对应 `DQ-*` 必须红；未注入 ⇒ 不红（反向对照） |
| C | spec **真的会采数据** | `spec.mjs` 不含 `collectDataSnapshot` / 不写 `smoke-data.json` / 商品夹具不含 `skus` ⇒ 红 |
| D | 壳脚本 **真的会判** | `ui_smoke_merchant.sh` 不调 `smoke_data_quality.py` 或不把非零折进退出码 ⇒ 红 |
| E | 种子门幅口径一致 | `demo-seed.sql` 的 `product_skus.door_width` 出现带单位写法（如 `2.8米`）⇒ 红 |
| F | 规范正文存在且被研发模式索引 | 正文缺失 / `AGENTS.md` 无引用 ⇒ 红 |
| G | **P1 冒烟不许把 5xx 当通过**（issue #7583 缺陷 4） | `tests/smoke/` 的 `status_code in (…, 5xx)` 回归 ⇒ 红 |
| H | **失败旅程必须留现场图**（issue #7583 缺陷 8） | `jrun` 的 catch 不再拍截图 ⇒ 红 |
| I | **自造订单的清理要自证**（issue #7583 缺陷 6） | `cleanupOrder` 不核 `GET 404` / 不核加工单残留 / 四条旅程重新变成「只造不清」 ⇒ 红 |
| J | **空态/缺控件不许记通过**（issue #7583 缺陷 5） | 旅程把「无数据 / 未见控件」写回 `done(true)`，或只判 `bodyLen` ⇒ 红 |
| K | **P1 写用例必须 `finally` 清理并自证**（issue #7583 缺陷 4） | 造单用例不删 / 删了不核 404 / 把 5xx 当业务拒绝 ⇒ 红 |
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unit_ci_workflows._seed_sql import literal, rows as seed_rows  # noqa: E402
SCRIPTS = REPO_ROOT / "scripts"
SPEC = SCRIPTS / "ui-smoke-merchant" / "spec.mjs"
SHELL = SCRIPTS / "ui_smoke_merchant.sh"
DOC = REPO_ROOT / "docs" / "testing" / "smoke-data-quality.md"
AGENTS = REPO_ROOT / "AGENTS.md"
DEMO_SEED = REPO_ROOT / "docs" / "deployment" / "demo-seed.sql"


def _load_checker():
    path = SCRIPTS / "smoke_data_quality.py"
    assert path.exists(), "scripts/smoke_data_quality.py 不存在 —— 数据质量没有判据"
    spec = importlib.util.spec_from_file_location("smoke_data_quality", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_data_quality"] = module
    spec.loader.exec_module(module)
    return module


GOOD = {
    "schema_version": 1,
    "collected_at": "2026-10-24T07:00:00Z",
    "ran_journeys": ["01-login", "08-products-list", "09-products-new", "14-orders-list",
                     "18-after-sales-list", "20-customers-list"],
    "run": {"journeys_total": 33, "journeys_pass": 33},
    "entities": {
        "products": {"collected": True, "total": 12, "sampled": 12, "with_skus": 5},
        "skus": {"collected": True, "total": 41, "door_width_noncanonical": 0,
                 "door_width_noncanonical_samples": []},
        "orders": {"collected": True, "total": 20, "with_items": 20},
        "customers": {"collected": True, "total": 7},
        "after_sales": {"collected": True, "total": 14},
    },
    "fixtures": {"products_created": 2, "products_with_skus": 2, "products_residue": 0},
    "collection_errors": [],
}


def _bad(**kwargs):
    snap = json.loads(json.dumps(GOOD))
    for path, value in kwargs.items():
        node = snap
        keys = path.split("__")
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value
    return snap


def _codes(violations):
    return {v["code"] for v in violations}


# ── A：六条规则的判别力 ─────────────────────────────────────────────
def test_good_snapshot_passes():
    checker = _load_checker()
    violations, undecidable = checker.evaluate(GOOD)
    assert violations == []
    assert undecidable == []


def test_no_sku_at_all_is_red():
    """用户投诉的那一条：33/33 绿也不许掩盖「一件商品都没有 SKU」。"""
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(entities__products={"collected": True, "total": 12,
                                                              "sampled": 12, "with_skus": 0}))
    assert "DQ-1" in _codes(violations)
    assert "SKU" in violations[0]["why"]


def test_empty_product_face_is_red():
    """空商品面也是「空态冒充绿」（Q1）：0 件商品 ⇒ `DQ-1` 判红，不是通过。"""
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(entities__products={"collected": True, "total": 0,
                                                              "sampled": 0, "with_skus": 0}))
    assert "DQ-1" in _codes(violations)
    assert "0 行" in violations[0]["why"]


def test_fixture_product_without_sku_is_red():
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(fixtures={"products_created": 2, "products_with_skus": 0,
                                                    "products_residue": 0}))
    assert "DQ-2" in _codes(violations)


def test_noncanonical_door_width_is_red():
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(entities__skus={
        "collected": True, "total": 41, "door_width_noncanonical": 2,
        "door_width_noncanonical_samples": ["2.8米"]}))
    assert "DQ-3" in _codes(violations)


def test_empty_entity_faces_are_red():
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(
        entities__orders={"collected": True, "total": 0, "with_items": 0},
        entities__customers={"collected": True, "total": 0},
        entities__after_sales={"collected": True, "total": 0},
    ))
    assert {"DQ-4"} <= _codes(violations)
    assert len([v for v in violations if v["code"] == "DQ-4"]) == 3


def test_residue_is_red():
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(fixtures={"products_created": 2, "products_with_skus": 2,
                                                    "products_residue": 1,
                                                    "residue_samples": ["冒烟SKU商品1"]}))
    assert "DQ-5" in _codes(violations)


def test_collection_failure_is_undecidable_not_pass():
    checker = _load_checker()
    violations, undecidable = checker.evaluate(_bad(
        entities__skus={"collected": False, "why": "GET /api/admin/products → 401"},
        entities__products={"collected": False, "why": "GET /api/admin/products → 401"},
    ))
    assert violations == []
    assert {u["code"] for u in undecidable} == {"DQ-U"}


def test_partial_run_does_not_judge_unrelated_faces():
    """`--group 09-` 只跑建品：不因「没跑订单」误红（无假红才有可信度）。"""
    checker = _load_checker()
    snap = _bad(ran_journeys=["09-products-new"])
    snap["entities"]["orders"] = {"collected": True, "total": 0, "with_items": 0}
    snap["entities"]["customers"] = {"collected": True, "total": 0}
    snap["entities"]["after_sales"] = {"collected": True, "total": 0}
    violations, undecidable = checker.evaluate(snap)
    assert violations == []
    assert undecidable == []


def test_bad_schema_is_undecidable():
    checker = _load_checker()
    violations, undecidable = checker.evaluate(_bad(schema_version=99))
    assert violations == []
    assert undecidable and undecidable[0]["code"] == "DQ-U"


def test_cli_exit_codes(tmp_path):
    checker = _load_checker()
    good = tmp_path / "good.json"
    good.write_text(json.dumps(GOOD, ensure_ascii=False), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_bad(entities__products={"collected": True, "total": 12,
                                                       "sampled": 12, "with_skus": 0}),
                              ensure_ascii=False), encoding="utf-8")
    assert checker.main(["--snapshot", str(good)]) == 0
    assert checker.main(["--snapshot", str(bad)]) == 1
    assert checker.main(["--snapshot", str(tmp_path / "missing.json")]) == 3


# ── B：判别力自证（注入式；反向对照见 A 的 good 用例）──────────────
@pytest.mark.parametrize("inject, expected", [
    ({"entities__products": {"collected": True, "total": 3, "sampled": 3, "with_skus": 0}}, "DQ-1"),
    ({"fixtures": {"products_created": 3, "products_with_skus": 1, "products_residue": 0}}, "DQ-2"),
    ({"entities__skus": {"collected": True, "total": 10, "door_width_noncanonical": 1}}, "DQ-3"),
    ({"entities__customers": {"collected": True, "total": 0}}, "DQ-4"),
    ({"fixtures": {"products_created": 3, "products_with_skus": 3, "products_residue": 2}}, "DQ-5"),
])
def test_each_injection_turns_its_rule_red(inject, expected):
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(**inject))
    assert expected in _codes(violations), f"注入 {inject} 后未命中 {expected}：{violations}"


# ── C/D：入口真的调用（否则规范只是文档）───────────────────────────
def test_spec_collects_and_writes_data_snapshot():
    source = SPEC.read_text(encoding="utf-8")
    assert "collectDataSnapshot" in source, "spec.mjs 没有采集数据快照 ⇒ 数据质量不可判"
    assert "smoke-data.json" in source, "spec.mjs 没有写 smoke-data.json"


def test_product_fixture_declares_sku_matrix():
    source = SPEC.read_text(encoding="utf-8")
    match = re.search(r"async function createProductFixture[\s\S]*?\n}\n", source)
    assert match, "spec.mjs 里找不到 createProductFixture"
    body = match.group(0)
    # 允许 `skus,`（对象简写）与 `skus:` 两种写法；四个字段必须都在（矩阵不是空壳）
    assert "skus:" in body or "skus," in body, "商品夹具没有 skus ⇒ 造出来的商品没有 SKU（用户投诉的形态）"
    for field in ("colorName", "doorWidth", "price", "stock"):
        assert field in body, f"商品夹具的 skus 缺 `{field}`"


def test_shell_runs_data_quality_check_and_folds_exit_code():
    source = SHELL.read_text(encoding="utf-8")
    assert "smoke_data_quality.py" in source, "冒烟壳脚本没有调用数据质量体检"
    assert "smoke-data-quality.md" in source, "体检报告没有落到输出目录（人看不到）"
    assert re.search(r"DQ_EXIT", source), "体检退出码没有变量承接 ⇒ 无法折进整体退出码"


# ── E：种子门幅口径一致 ──────────────────────────────────────────
def test_demo_seed_door_width_is_canonical():
    """门幅口径一致（Q3）：落库 = **裸数值**，带单位只出现在显示层。

    ⚠️ 取数方式（issue #7583）：矩阵写成逐行显式后，旧形态「`door_width` 之后第一个引号串」
    会把**商品 id** 读成门幅（矩阵行以 product_id 开头）；这里改成按列取值（真值 = 列清单）。
    """
    skus = seed_rows(DEMO_SEED.read_text(encoding="utf-8"), "product_skus")
    assert skus, "fail-closed：demo-seed 解析不到 product_skus 行 —— 判不了，不得当通过"
    bad = sorted({str(literal(s["door_width"])) for s in skus
                  if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(literal(s["door_width"])))})
    assert not bad, f"demo-seed 的 product_skus.door_width 出现非 canonical 值：{bad}"


# ── F：规范正文与研发模式索引 ────────────────────────────────────
def test_spec_document_exists_and_is_indexed():
    assert DOC.exists(), "docs/testing/smoke-data-quality.md 不存在"
    body = DOC.read_text(encoding="utf-8")
    for token in ("DQ-1", "DQ-2", "DQ-3", "DQ-4", "DQ-5", "DQ-U"):
        assert token in body, f"规范正文缺判据 {token}"
    assert "smoke-data-quality.md" in AGENTS.read_text(encoding="utf-8"), \
        "AGENTS.md 没有把规范挂进研发模式（后续执行无入口）"


# ── G：P1 冒烟不许把 5xx 当通过（issue #7583 缺陷 4）────────────────────────
def test_smoke_assertions_must_not_accept_5xx():
    """`tests/smoke/` 的任何「状态码集合」都不得包含 5xx。

    病灶（issue #7583）：`smoke-p1` 跑的是**生产**栈，而
    `tests/smoke/test_10_aftersales_notifications.py` 的
    `assert resp.status_code in (200, 201, 400, 422, 500)` 让**后端 500 也能绿**；
    同族还有 `test_11` 的 `in (200, 202, 500)`（拿 500 当「RAG 未配置」的合法形态）。

    口径：**4xx 可以是有效结论**（前置/校验被拒，写清理由即可）；**5xx 一律是坏** ——
    未配置的环境应 `pytest.skip`（skip ≠ pass），真坏了应判红。两类都不许混进通过集合。
    """
    offenders = []
    for path in sorted((REPO_ROOT / "tests" / "smoke").glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"status_code\s+in\s*[\(\{]([\s\S]{0,240}?)[\)\}]", source):
            statuses = [int(n) for n in re.findall(r"(?<![\d.])(\d{3})(?![\d.])", match.group(1))]
            bad = sorted({s for s in statuses if s >= 500})
            if bad:
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)} 第 {line} 行接受 {bad}")
    assert not offenders, (
        "以下 P1 冒烟断言把 5xx 当通过了（后端 500 也能绿）：\n  " + "\n  ".join(offenders)
        + "\n修法：未配置/未实现 ⇒ pytest.skip（skip ≠ pass）；真坏了 ⇒ 判红。")


# ── H：失败旅程必须留现场图（issue #7583 缺陷 8）──────────────────────────
def test_failed_journey_leaves_screenshot():
    """截图此前只在 `journey().done` 里拍，而**抛错旅程走不到 done** ⇒ 零证据。

    判据：`jrun` 的 catch 必须**先尝试截图**再落结果，且用**独立文件名**（`-failed.png`）
    —— 与正常路径同名会覆盖掉「本旅程正常时」的截图，两种证据互相抹掉。
    """
    source = SPEC.read_text(encoding="utf-8")
    match = re.search(r"async function jrun\([\s\S]*?\n}\n", source)
    assert match, "spec.mjs 里找不到 jrun（判据锚点失效 ⇒ 判不了，不得当通过）"
    body = match.group(0)
    assert "screenshot" in body, (
        "jrun 的失败路径不拍截图 ⇒ 抛错/超时旅程零证据（issue #7583 缺陷 8）")
    assert "-failed.png" in body, (
        "失败截图没有独立文件名（会覆盖同名旅程的正常截图）")
    assert "evidence" in body, "失败截图没有进 evidence ⇒ 汇总里看不到它"


# ══════════════════════════════════════════════════════════════════════════════
# 商家后台演示/冒烟凭据的**同一口径**（issue #7479）
#
# 病根（2026-10-22 实测）：商家后台登录页用 `13800138000` 被服务端拒绝
# 「该账号非管理员，请使用员工登录入口」—— 库里该手机号是 **C 端顾客**（role=customer）。
# 而冒烟 spec / 冒烟脚本 / 三份演示文档**默认**都写着这个号 ⇒ 谁照文档做谁撞墙，
# 且冒烟默认值本身就是「一定登不上」。
#
# 判据（同一口径 = 单一真值，不许三处各写各的）：
# ① spec.mjs 的默认 PHONE、ui_smoke_merchant.sh 的默认 PHONE、demo-readiness.md 的「演示前用 <号>」三者必须相等；
# ② 三份商家侧文档里凡出现 C 端顾客号，同一行必须写明「C 端 / 顾客」，避免被当成管理员凭据。
# ══════════════════════════════════════════════════════════════════════════════

MERCHANT_ADMIN_PHONE = "13600136000"
CUSTOMER_PHONE = "13800138000"
MERCHANT_FACING_DOCS = (
    REPO_ROOT / "docs" / "testing" / "demo-readiness.md",
    REPO_ROOT / "docs" / "deployment" / "poc-rehearsal-checklist.md",
    REPO_ROOT / "docs" / "testing" / "frontend-acceptance-checklist.md",
)


def _spec_default_phone() -> str:
    source = SPEC.read_text(encoding="utf-8")
    match = re.search(r"const PHONE = process\.env\.PHONE \|\| '(\d{11})'", source)
    assert match, "spec.mjs 的默认 PHONE 取不到（判据锚点失效 ⇒ 判不了，不得当通过）"
    return match.group(1)


def _shell_default_phone() -> str:
    source = SHELL.read_text(encoding="utf-8")
    match = re.search(r'PHONE="\$\{PHONE:-(\d{11})\}"', source)
    assert match, "ui_smoke_merchant.sh 的默认 PHONE 取不到（判据锚点失效）"
    return match.group(1)


def _documented_merchant_phone() -> str:
    source = MERCHANT_FACING_DOCS[0].read_text(encoding="utf-8")
    match = re.search(r"演示前用 (\d{11}) / 万能码", source)
    assert match, "demo-readiness.md 里找不到「演示前用 <手机号> / 万能码」这句（判据锚点失效）"
    return match.group(1)


class TestMerchantDemoCredentials:
    def test_smoke_defaults_are_the_merchant_admin(self):
        spec_phone = _spec_default_phone()
        shell_phone = _shell_default_phone()
        doc_phone = _documented_merchant_phone()
        assert spec_phone == shell_phone == doc_phone == MERCHANT_ADMIN_PHONE, (
            "商家侧登录号三处不一致（或又写回 C 端顾客号）—— issue #7479："
            f"spec={spec_phone} shell={shell_phone} doc={doc_phone} 期望={MERCHANT_ADMIN_PHONE}")

    def test_customer_phone_is_always_qualified_as_customer(self):
        offenders = []
        for doc in MERCHANT_FACING_DOCS:
            for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                if CUSTOMER_PHONE not in line:
                    continue
                if "C 端" in line or "顾客" in line:
                    continue
                offenders.append(f"{doc.relative_to(REPO_ROOT)}:{lineno}")
        assert not offenders, (
            "这些商家侧文档行把 C 端顾客号当成登录凭据写（没写清它是 C 端/顾客）—— issue #7479："
            + ", ".join(offenders))

    def test_sms_rate_limit_cleanup_uses_the_login_phone(self):
        """登录前清 SMS 限流键时，必须清**当前登录号**——写死号码 ⇒ 换号后一个都没清到。"""
        source = SHELL.read_text(encoding="utf-8")
        block = re.search(r"for phone in \[(.+?)\]:", source)
        assert block, "找不到 SMS 限流清理的号码列表（判据锚点失效）"
        assert "sys.argv" in block.group(1), (
            "SMS 限流清理写死了手机号（issue #7479 现场：写死 C 端顾客号 ⇒ 换号后限流键没清、登录旅程会 400）")


# ══════════════════════════════════════════════════════════════════════════════
# DQ-5（续）：自造**订单**的清理自证（issue #7583 缺陷 6）
#
# 旧形态 `cleanupOrder` 只 `return res.ok`（删不掉静默留下），且 16-/17-/17b-/19- **一条都没清**
# ⇒ 共享云库越跑越脏。订单「能不能删」是业务事实（只允许 `pending`、已生成活跃作业单会被拒），
# 所以判据不是「必须删掉」，而是**两态都必须可自证**：删掉 ⇒ `GET 404`；删不掉 ⇒ 服务端原话
# + 仍可读（可枚举）。三种失败形态各自具名：`order_cleanup_proven` / `order_processing_residue`
# / `DQ-U`。
# ══════════════════════════════════════════════════════════════════════════════

ORDER_FIXTURES_GOOD = {
    "orders_created": 3,
    "orders_gone_404": 1,
    "orders_kept": 2,
    "orders_cleanup_failed": 0,
    "orders_residue_samples": ["冒烟详情#a1：DELETE 422：仅允许删除待确认状态的订单"],
    "orders_processing_residue": 0,
    "orders_processing_unreadable": 0,
}


def test_order_fixtures_kept_with_reason_pass():
    """`kept`（业务规则拒绝删除 + 原话 + 仍可读）是**自证过的终态**，不是失败。"""
    checker = _load_checker()
    violations, undecidable = checker.evaluate(_bad(fixtures={
        "products_created": 0, "products_with_skus": 0, "products_residue": 0,
        **ORDER_FIXTURES_GOOD}))
    assert violations == []
    assert undecidable == []


def test_order_cleanup_not_proven_is_red():
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(fixtures={
        "products_created": 0, "products_with_skus": 0, "products_residue": 0,
        **{**ORDER_FIXTURES_GOOD, "orders_cleanup_failed": 1, "orders_kept": 1}}))
    assert "DQ-5" in _codes(violations)
    assert any(v["rule"] == "order_cleanup_proven" for v in violations), violations


def test_order_processing_residue_is_red():
    """删掉订单却留下**活跃**加工单 ⇒ 作业看板会对已删父订单扇出 404。"""
    checker = _load_checker()
    violations, _ = checker.evaluate(_bad(fixtures={
        "products_created": 0, "products_with_skus": 0, "products_residue": 0,
        **{**ORDER_FIXTURES_GOOD, "orders_processing_residue": 2}}))
    assert any(v["rule"] == "order_processing_residue" for v in violations), violations


def test_order_cleanup_counts_must_add_up():
    """读数不自洽（gone + kept + failed ≠ created）⇒ 判不了，不许当通过。"""
    checker = _load_checker()
    _, undecidable = checker.evaluate(_bad(fixtures={
        "products_created": 0, "products_with_skus": 0, "products_residue": 0,
        **{**ORDER_FIXTURES_GOOD, "orders_kept": 0}}))
    assert any(u["code"] == "DQ-U" and u["rule"] == "DQ-5:orders" for u in undecidable), undecidable


def test_order_processing_unreadable_is_undecidable():
    """加工单残留读不到 ⇒ 不可判定（读不到 ≠ 没有残留）。"""
    checker = _load_checker()
    violations, undecidable = checker.evaluate(_bad(fixtures={
        "products_created": 0, "products_with_skus": 0, "products_residue": 0,
        **{**ORDER_FIXTURES_GOOD, "orders_processing_unreadable": 1}}))
    assert violations == []
    assert any(u["code"] == "DQ-U" and u["rule"] == "DQ-5:orders" for u in undecidable), undecidable


# ══════════════════════════════════════════════════════════════════════════════
# I / J / K：缺陷 4 / 5 / 6 的**类级**收口（不是逐行字面量）
#
# 为什么必须落成「类」：缺陷 5 是**一族**（13/21/22/26/27~30 各自 `done(true)` 或只判 `bodyLen`），
# 缺陷 6 是**四条旅程共用**一份 `cleanupOrder`。逐处修完一处、下一处照旧 —— 判据必须落在
# 「函数族 / 调用点族」上，新旅程/新写用例才进不来。
# ══════════════════════════════════════════════════════════════════════════════

def _function_body(source: str, name: str) -> str:
    """取 `async function <name>(` 到下一个顶层 `}`（fail-closed：取不到即判不了）。"""
    match = re.search(rf"async function {re.escape(name)}\([\s\S]*?\n\}}\n", source)
    assert match, f"spec.mjs 里找不到 {name}（判据锚点失效 ⇒ 判不了，不得当通过）"
    return match.group(0)


def _order_cleanup_defects(source: str) -> list[str]:
    """判据 I 的纯函数核心（便于注入式红证）：返回具名缺陷，空 = 通过。"""
    bad: list[str] = []
    body = _function_body(source, "cleanupOrder")
    if not re.search(r"del\.ok\s*&&\s*rec\.gone404", body):
        bad.append("cleanupOrder 的「删除成功」分支不要求 `GET 404` 自证 ⇒ 假清理也能过")
    if "processingResidue(" not in body:
        bad.append("cleanupOrder 不核加工单残留 ⇒ 已删订单的作业单会悬挂")
    if "'kept'" not in body:
        bad.append("cleanupOrder 没有 `kept` 态 ⇒ 业务规则拒绝删除时会被静默吞掉")
    for name in ("createOrderFixture", "createPlainOrderFixture"):
        if "recordFixture('orders'" not in _function_body(source, name):
            bad.append(f"{name} 不登记自造台账 ⇒ 跑完不知道该清哪些（漏清无读数）")
    if "async function sweepOrderFixtures" not in source:
        bad.append("没有统一扫尾入口 sweepOrderFixtures")
    if "await sweepOrderFixtures(page)" not in source:
        bad.append("扫尾入口定义了却没被调用 ⇒ 旅程跑完不会清")
    return bad


def test_order_fixture_cleanup_is_self_proving():
    """I：自造订单跑完必须**自证**清理（两态都可枚举），且**统一扫尾**覆盖全部造单入口。"""
    source = SPEC.read_text(encoding="utf-8")
    defects = _order_cleanup_defects(source)
    assert defects == [], "自造订单的清理自证缺口（issue #7583 缺陷 6）：\n  " + "\n  ".join(defects)
    # 注入式红证（内存变异，不写盘）：把「删除成功」分支的 404 自证拿掉 ⇒ 必须判红
    mutated = source.replace("if (del.ok && rec.gone404) {", "if (del.ok) {", 1)
    assert mutated != source, "变异注入未生效（锚点漂移）—— 判据没牙"
    assert _order_cleanup_defects(mutated), "去掉 `GET 404` 自证后判据仍然绿 ⇒ 判据没牙"


WEAK_PAGE_FUNCTIONS = {
    "categoriesJourney": ("未见「新增分类」按钮", "throw new Error"),
    "financeJourney": ('tbody tr', 'role="row"'),
    # 空态字面量**现取**自 notifications/page.tsx（#8040）—— 判据 A 只认源码里真有的候选
    "notificationsJourney": ("还没有通知", 'tbody tr'),
    # role 选择器（判据 R 的现取口径）—— 不写裸标签 CSS（族外形态要进只许缩短的台账）
    "corporatePage": ("getByRole('heading')", "getByRole('link')"),
    "customerDetailJourney": ("缺数据不是有效结论", "throw new Error"),
}

#: 把「空态 / 缺控件 / 没数据」写成**通过**的两句原始形态（2026-10-23 用户投诉的根）。
#: 匹配的是**记通过的那一句**（`done(true, '<说明>'`），不是提及它的注释 —— 判据不许因为
#: 「解释这条禁忌」而变红（`migao-dev-flow` 的「引用即实例」同族坑）。
FORBIDDEN_EMPTY_PASS = ("done(true, '无客户可进详情'",
                        "done(true, '未见新增按钮（可能入口不同）'")


def _weak_page_defects(source: str) -> list[str]:
    """判据 J 的纯函数核心：返回具名缺陷，空 = 通过。"""
    bad: list[str] = []
    for name, markers in WEAK_PAGE_FUNCTIONS.items():
        body = _function_body(source, name)
        missing = [m for m in markers if m not in body]
        if missing:
            bad.append(f"{name} 缺内容面判据 {missing} ⇒ 只判 bodyLen / 缺控件也能记通过")
    for phrase in FORBIDDEN_EMPTY_PASS:
        if phrase in source:
            bad.append(f"spec.mjs 仍把空态写成通过：{phrase}")
    return bad


def test_no_journey_reports_empty_state_as_pass():
    """J：空态/加载态/缺控件**不得冒充通过**（SDQS Q1；issue #7583 缺陷 5）。"""
    source = SPEC.read_text(encoding="utf-8")
    defects = _weak_page_defects(source)
    assert defects == [], "空态冒充通过的旅程（issue #7583 缺陷 5）：\n  " + "\n  ".join(defects)
    # 注入式红证：把分类旅程的「未见按钮」判据换回旧的「仅验证渲染」⇒ 必须判红
    mutated = source.replace("未见「新增分类」按钮", "仅验证渲染", 1)
    assert mutated != source, "变异注入未生效（锚点漂移）—— 判据没牙"
    assert _weak_page_defects(mutated), "缺控件记通过后判据仍然绿 ⇒ 判据没牙"


def _test_blocks(source: str) -> list[tuple[str, str]]:
    """按 `    def test_*` 切片（含多行签名的用例；只用行首缩进，不做引号解析）。"""
    matches = list(re.finditer(r"^    def (test_\w+)\(", source, re.M))
    return [(m.group(1), source[m.end(): (matches[i + 1].start() if i + 1 < len(matches)
                                          else len(source))])
            for i, m in enumerate(matches)]


def _p1_write_defects(source: str, label: str) -> list[str]:
    """判据 K 的纯函数核心：造单的用例必须 `finally` + 清理自证（空清单 = 通过）。"""
    bad: list[str] = []
    for name, body in _test_blocks(source):
        if "_create_order(" not in body:
            continue  # 负控用例（直接 POST 且断言 4xx）不落库，不需要清理
        missing = [t for t in ("_cleanup_order(", "finally") if t not in body]
        if missing:
            bad.append(f"{label}::{name} 造了订单却没有 {'/'.join(missing)}")
    return bad


def _p1_cleanup_defects(source: str) -> list[str]:
    """判据 K：写用例的清理入口本身也要**自证**（404 + 区分业务拒绝与 5xx）。"""
    match = re.search(r"\ndef _cleanup_order\([\s\S]*?(?=\n\n# |\n\n@|\n\ndef |\n\nclass )", source)
    if not match:
        return ["tests/smoke/test_09_order_lifecycle.py 没有 `_cleanup_order` —— 写用例建单后无人清理"]
    helper = match.group(0)
    bad: list[str] = []
    if "404" not in helper:
        bad.append("_cleanup_order 的删除成功分支不核 `GET 404` ⇒ 假清理也能过")
    if "400 <= deleted.status_code < 500" not in helper:
        bad.append("_cleanup_order 不区分「业务规则拒绝（4xx）」与「真坏了（5xx）」")
    bad.extend(_p1_write_defects(source, "tests/smoke/test_09_order_lifecycle.py"))
    return bad


def test_p1_write_cases_clean_up_with_proof():
    """K：`tests/smoke/` 造单的 P1 用例必须 `finally` 清理并**自证**（issue #7583 缺陷 4）。"""
    defects: list[str] = []
    for path in sorted((REPO_ROOT / "tests" / "smoke").glob("test_*.py")):
        defects.extend(_p1_write_defects(path.read_text(encoding="utf-8"),
                                         path.relative_to(REPO_ROOT).as_posix()))
    order_file = REPO_ROOT / "tests" / "smoke" / "test_09_order_lifecycle.py"
    source = order_file.read_text(encoding="utf-8")
    defects.extend(_p1_cleanup_defects(source))
    assert defects == [], ("P1 写用例的清理缺口（issue #7583 缺陷 4）：\n  " + "\n  ".join(defects))
    # 注入式红证：拿掉一处 `finally` 里的清理调用 ⇒ 必须判红
    mutated = source.replace("_cleanup_order(authed_admin_client, order_id)", "", 1)
    assert mutated != source, "变异注入未生效（锚点漂移）—— 判据没牙"
    assert _p1_cleanup_defects(mutated), "拿掉清理调用后判据仍然绿 ⇒ 判据没牙"
