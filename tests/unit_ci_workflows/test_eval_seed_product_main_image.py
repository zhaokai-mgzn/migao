# case_ids: PR-135, PR-074
"""评测种子的「商品主图」接地判据（PR-135；2026-11-27 run 45979067843 逐字归因）。

## 病灶 = 夹具缺陷（不是能力缺陷）

PR-135（persona=mibao）R1 唯一一次 `product_image_generate` 调用**无一成功**：

    ❌ must_succeed: product_image_generate 共 1 次调用无一成功（R1:IMAGE_SOURCE_MISSING）
       callargs=product_image_generate{"kind":"main","product_id":"prod_eval_summer"}

而用例的 `data_checks` 写的是「图 URL 取自商品档案主图」—— 用例**默认档案里有主图**，
种子给的却是 `'[]'::jsonb` ⇒ 「档案有主图 ⇒ 能生成」这条链路从来没有被真正测过。

同一 run 的 **PR-074 通过**：它的取样对象 `prod_eval_blackout` 早在 issue #7541 就补了样图
（`tests/agent_eval/fixtures/xiaobu_eval_seed.sql` 的 products 段）⇒ 同一工具、同一取样口径，
差别只在种子。这就是「夹具缺陷」的判据面：**能力同源、数据不同**。

## 判据（每条都吃**磁盘上的真 seed**，改法即红）

| # | 判据 | 回归时会怎么红 |
|---|---|---|
| ① | `prod_eval_summer` 的 `images` 是**非空**数组，且首元素是**绝对 http(s)** URL | 改回 `'[]'::jsonb` ⇒ 具名红；改成相对路径 ⇒ 也红 |
| ② | 同一范式对 `prod_eval_blackout`（#7541 先例 / PR-074 取样对象）成立 | 删掉它的样图 ⇒ 具名红（一条判据管两个取样对象） |
| ③ | `scripts/eval_stack_seed.sh --persona mibao --dry-run` **真的**把 xiaobu seed 列进来 | 只改 mibao seed（或摘掉叠加）⇒ 红 —— PR-135 是 persona=mibao，而商品在 C 端种子里 |

**为什么 ① 要判「绝对 http(s)」**：`backend/ai-agent-service/app/tools/product_image_generate.py`
的 `_sample_image` 取 `mainImage`、缺失时回退 `images[0]`；**相对路径会被如实拒绝**
（同码 `IMAGE_SOURCE_MISSING`）⇒ 「有值」不等于「取得到样图」。

**为什么 ③ 也要判**：`prod_eval_summer` 只存在于 C 端种子里，而 PR-135 的 persona 是 mibao。
装配面（`bash scripts/eval_stack_seed.sh --persona mibao --dry-run` 的实际输出）是唯一能
证明「B 端腿也拿到这张样图」的地方 —— 只改 mibao seed 会绿得毫无作用。

## 红证（注入式）

把 `prod_eval_summer` 的 images 改回 `'[]'::jsonb` ⇒ ① 具名红；改成 `/uploads/main.jpg`
⇒ ① 也红（两种形态各一条断言）。判据吃纯文本，注入即红。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "agent_eval" / "fixtures"
C_END_SEED = FIXTURES / "xiaobu_eval_seed.sql"
SEED_SH = REPO / "scripts" / "eval_stack_seed.sh"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unit_ci_workflows._seed_sql import (  # noqa: E402
    _parse_tuples,
    _split_top_level,
    literal,
)
from unit_ci_workflows._sql_schema import strip_sql_comments  # noqa: E402


def _product_rows(seed: Path) -> dict[str, dict[str, str]]:
    """种子 `INSERT INTO products (列…) VALUES (…), (…)` → `{商品 id: {列: 原文}}`。

    只认**本仓种子实际在写**的形态（字面量元组，列清单显式）；行/列数不齐或读不到
    VALUES 段 ⇒ **fail-closed** 抛错（「判不了」不许静默跳过 —— 那正是假绿）。
    """
    text = strip_sql_comments(seed.read_text(encoding="utf-8"))
    m = re.search(
        r"INSERT\s+INTO\s+products\s*\(([^)]*)\)\s*VALUES\b(.*?)(?:\bON\s+CONFLICT\b|;)",
        text, re.I | re.S,
    )
    assert m, f"fail-closed：{seed.name} 里读不到 `products` 的 VALUES 段 —— 判据会空转成假绿"
    columns = _split_top_level(m.group(1))
    rows: dict[str, dict[str, str]] = {}
    for tup in _parse_tuples(m.group(2)):
        assert len(tup) == len(columns), (
            f"fail-closed：{seed.name} 的 products 行有 {len(tup)} 个值、列清单 {len(columns)} 列 —— "
            f"判不了。行原文：{tup[:3]}…"
        )
        row = dict(zip(columns, tup))
        rows[str(literal(row["id"]))] = row
    return rows


def _sample_images(row: dict[str, str]) -> list[str]:
    """`images` 列（jsonb 数组字面量）→ Python 列表；不是数组字面量 ⇒ fail-closed。"""
    body = re.sub(r"::\s*\w+$", "", row["images"].strip())
    value = literal(body)
    assert isinstance(value, str), f"fail-closed：images 不是字符串字面量（读到 `{row['images']}`）"
    parsed = json.loads(value)
    assert isinstance(parsed, list), f"fail-closed：images 解析成 {type(parsed).__name__}，不是数组"
    return parsed


@pytest.mark.parametrize(
    "product_id, product_name",
    [
        # PR-135 的取样对象（本判据补的那个）
        ("prod_eval_summer", "夏日清风窗帘"),
        # PR-074 的取样对象（issue #7541 的先例 = 本判据照抄的范式）
        ("prod_eval_blackout", "遮光窗帘"),
    ],
)
def test_eval_seed_product_has_a_usable_sample_image(product_id, product_name):
    """取样商品在种子里必须有**一张可用作样图的图**（非空 + 绝对 http(s) URL）。"""
    rows = _product_rows(C_END_SEED)
    assert product_id in rows, (
        f"fail-closed：C 端种子（persona=mibao 也叠加它）里没有取样商品 `{product_id}`（{product_name}）"
    )
    images = _sample_images(rows[product_id])
    assert images, (
        f"`{product_id}`（{product_name}）的 `images` 是空数组 ⇒ "
        f"`product_image_generate` 必然 `IMAGE_SOURCE_MISSING`（PR-135 的根因就是它）"
    )
    first = images[0].strip()
    assert first.startswith(("https://", "http://")), (
        f"`{product_id}`（{product_name}）的首图不是绝对 http(s) 地址（读到 `{first}`）⇒ "
        f"`_sample_image` 取得到的样图不合法，生图内核会如实拒绝（同码 IMAGE_SOURCE_MISSING）；"
        f"要一张**可抓取**的静态图，不是相对路径"
    )


def test_mibao_stack_really_loads_the_c_end_seed():
    """装配面：persona=mibao 的种子清单里**先**是 C 端种子（`prod_eval_summer` 在那里）。"""
    out = subprocess.run(
        ["bash", str(SEED_SH), "--persona", "mibao", "--dry-run"],
        cwd=str(REPO), capture_output=True, text=True, timeout=180,
    )
    assert out.returncode == 0, f"种子装配自检失败（exit {out.returncode}）：{out.stderr[-800:]}"
    applied = [ln.split(":", 1)[1].strip() for ln in out.stdout.splitlines()
               if ln.startswith("seed:")]
    assert "tests/agent_eval/fixtures/xiaobu_eval_seed.sql" in applied, (
        f"persona=mibao 的种子清单里没有 C 端种子（实得 {applied}）—— PR-135 的取样商品在它里面"
    )
    assert applied.index("tests/agent_eval/fixtures/xiaobu_eval_seed.sql") < applied.index(
        "tests/agent_eval/fixtures/mibao_eval_seed.sql"
    ), f"C 端种子必须**先**跑（否则叠加会改 products 的 created_at 排序）：实得 {applied}"
