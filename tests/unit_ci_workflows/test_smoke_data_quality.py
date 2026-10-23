# case_ids: MC-012
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
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
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
    source = DEMO_SEED.read_text(encoding="utf-8")
    literals = re.findall(r"door_width[^;]{0,200}?'([^']+)'", source)
    bad = [v for v in literals if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", v)]
    assert not bad, f"demo-seed 的 product_skus.door_width 出现非 canonical 值：{sorted(set(bad))}"


# ── F：规范正文与研发模式索引 ────────────────────────────────────
def test_spec_document_exists_and_is_indexed():
    assert DOC.exists(), "docs/testing/smoke-data-quality.md 不存在"
    body = DOC.read_text(encoding="utf-8")
    for token in ("DQ-1", "DQ-2", "DQ-3", "DQ-4", "DQ-5", "DQ-U"):
        assert token in body, f"规范正文缺判据 {token}"
    assert "smoke-data-quality.md" in AGENTS.read_text(encoding="utf-8"), \
        "AGENTS.md 没有把规范挂进研发模式（后续执行无入口）"
