# case_ids: MC-134
"""**类级元守卫**：仓库级文本语料的读面必须登记，且**唯一实现** = 读 git 索引（issue #6594）。

## 为什么需要这一层（实例 → 类）

实例修复 = `frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts` 的 C2b 改成读
`tests/helpers/trackedCorpus.js`。但「只修这一处 = 没修」：**任何**读工作树做判决的语料都会在
本机被本地产物（`coverage.json` / 构建产物 / 临时文件）顶成假红，而 CI 永远绿 —— 那种红**没有人能
从读数里分辨出来**。故本判据把这件事变成台账与单实现约束：

| # | 判据 | 怎么红 |
|---|---|---|
| 1 | **单实现**：`frontend/**` 里**定义** `readCorpus` 的只许 `single_implementation.path` 一处 | 另写一份读面（第二份定义）⇒ 红 |
| 2 | 唯一实现的 `module.exports` 必须含 `readCorpus` | 台账挂一个不存在的实现名 ⇒ 红 |
| 3 | **未登记即红**：`frontend/**/tests/**` 里引用 `trackedCorpus` 的文件必须在 `consumers` | 新造消费者不登记 ⇒ 红 |
| 4 | **登记未兑现即红**：consumer 真实存在 + 仍引用 `trackedCorpus` + `roots` 逐字出现 | 台账给不存在的射程盖章 ⇒ 红 |
| 5 | **读面纯度**：已登记 consumer 里不许出现 `readdirSync`（自己走路工作树） | 把读面改回工作树 ⇒ 红 |
| 6 | **例外只许缩短**：`exceptions` ≤ `exceptions_frozen_max`，且冻结值 == 本文件常量（= 0） | 悄悄抬高例外数 ⇒ 红 |
| 7 | `consumers` 为空 ⇒ 红（fail-closed） | 清空台账「消红」⇒ 红 |
| 8 | **判别力自证**：六种坏形态（第二份实现 / 实现未导出 / 消费者未登记 / 登记未兑现 / 读面被改回 / 例外增长）**在内存里各自判红**；只改注释 ⇒ **不红**（对照） | 守卫退化成空跑 ⇒ 红 |

## 已知残余（照实登记，§19.1）

- 换了名字的第二份读面**判不了**（形态学判据不做语义一刀切）。
- `tests/unit_ci_workflows/**` 侧的 Python 语料读工作树**不在射程**：CI 上那一侧跑的就是同一份
  工作树，不存在「CI 干净检出」这第二个口径 ⇒ 那不属于本单的缺陷形态。
- 谓词判别力不归本判据（本单**一字未改**谓词）；读面的**行为**归
  `tests/unit_ci_workflows/test_bmini_corpus_read_face.py`。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SELF_REL = "tests/unit_ci_workflows/test_repo_corpus_read_face_ledger.py"
LEDGER_REL = "tests/unit_ci_workflows/repo_corpus_read_face_ledger.json"

#: 例外的**冻结上限**（本单 = 0）。要加例外必须同改这一行 ⇒ 强制一次显式评审（§23「只许缩短」）。
EXCEPTIONS_FROZEN_MAX = 0

#: 「**定义**」`readCorpus` 的两种形态（`function readCorpus(` / `readCorpus = function` / `readCorpus = (`）。
#: ⚠️ 刻意**不**匹配 `readCorpus: readCorpusAt`（别名解构）与 `{ readCorpus }`（导出引用）——
#: 那两处是**消费**共享实现，不是再造一份。
DEF_RE = re.compile(r"(?:\bfunction\s+readCorpus\s*\(|\breadCorpus\s*[:=]\s*(?:function\b|\())")

CORPUS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs")


def _frontend_units() -> dict[str, str]:
    """语料 = `git ls-files frontend` 里的代码文件正文（**索引面**，与守卫同口径）。"""
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "frontend"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180, check=True,
    )
    out: dict[str, str] = {}
    for rel in proc.stdout.split("\0"):
        if not rel or not rel.endswith(CORPUS_EXT):
            continue
        out[rel] = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    assert out, "语料为空（fail-closed）：`git ls-files frontend` 一个代码文件都没读到"
    return out


def _ledger() -> dict:
    return json.loads((REPO_ROOT / LEDGER_REL).read_text(encoding="utf-8"))


def _problems(units: dict[str, str], ledger: dict) -> list[str]:
    """纯判定（真判据与注入式红证**共用同一份**）。"""
    problems: list[str] = []
    impl = (ledger.get("single_implementation") or {})
    impl_path = impl.get("path")
    symbol = impl.get("symbol", "readCorpus")

    # ── 判据 1：单实现 ───────────────────────────────────────────────────
    definers = sorted(rel for rel, text in units.items() if DEF_RE.search(text))
    if impl_path not in definers:
        problems.append(
            f"唯一实现 `{impl_path}` 没有定义 `{symbol}`（台账挂了一个不存在的实现名；"
            f"实得定义处 = {definers}）"
        )
    extra = [rel for rel in definers if rel != impl_path]
    if extra:
        problems.append(
            f"`{symbol}` 出现**第二份定义**（读面分叉：任何一份都可能读工作树）：{extra}；"
            f"唯一允许的位置 = `{impl_path}`（issue #6594）"
        )

    # ── 判据 2：唯一实现必须真的导出 ─────────────────────────────────────
    impl_text = units.get(impl_path, "")
    tail = impl_text[impl_text.index("module.exports"):] if "module.exports" in impl_text else ""
    if symbol not in tail:
        problems.append(f"`{impl_path}` 的 `module.exports` 里没有 `{symbol}`（实现没被导出 ⇒ 台账失效）")

    # ── 判据 3/4/5：消费者登记、兑现、读面纯度 ────────────────────────────
    registered = {str(c.get("path")): c for c in (ledger.get("consumers") or [])}
    fixture_units = {
        rel: text
        for rel, text in units.items()
        if rel.startswith("frontend/") and "/tests/" in rel and rel != impl_path
    }
    for rel, text in sorted(fixture_units.items()):
        if "trackedCorpus" in text and rel not in registered:
            problems.append(
                f"{rel} 引用了共享读面 `trackedCorpus`，却没在台账 `consumers` 里登记"
                f"（未登记即红：新造的语料消费者必须写明射程与理由）"
            )

    for rel, entry in sorted(registered.items()):
        if rel not in units:
            problems.append(f"台账登记的 consumer `{rel}` 在仓内不存在（登记未兑现）")
            continue
        text = units[rel]
        if "trackedCorpus" not in text:
            problems.append(f"{rel} 已登记为读面消费者，但**没有**引用 `trackedCorpus`（登记未兑现）")
        if "readdirSync" in text:
            problems.append(
                f"{rel} 是已登记的读面消费者，却出现 `readdirSync`（自己遍历工作树）⇒ "
                f"读面被改回工作树（issue #6594 的缺陷形态）"
            )
        for root in entry.get("roots") or []:
            if root not in text:
                problems.append(f"{rel} 台账登记的射程 `{root}` 在该文件里**逐字找不到**（登记未兑现）")
        if not entry.get("why"):
            problems.append(f"{rel} 台账条目缺 `why`（不写清「为什么是仓库级语料」就不算登记）")

    # ── 判据 6：例外只许缩短 ─────────────────────────────────────────────
    exceptions = ledger.get("exceptions") or []
    frozen = ledger.get("exceptions_frozen_max")
    if frozen != EXCEPTIONS_FROZEN_MAX:
        problems.append(
            f"台账 `exceptions_frozen_max` = {frozen!r}，而判据里的冻结常量 = {EXCEPTIONS_FROZEN_MAX} ⇒ "
            f"例外上限被抬高（只许缩短；要加例外请同改判据常量并走评审）"
        )
    if len(exceptions) > EXCEPTIONS_FROZEN_MAX:
        problems.append(
            f"`exceptions` 有 {len(exceptions)} 条，超过冻结上限 {EXCEPTIONS_FROZEN_MAX}（只许缩短）"
        )
    for idx, entry in enumerate(exceptions):
        for field in ("reason", "restart"):
            if not (entry or {}).get(field):
                problems.append(f"`exceptions[{idx}]` 缺 `{field}`（例外必须写明理由与重启条件）")

    # ── 判据 7：不允许空台账 ─────────────────────────────────────────────
    if not registered:
        problems.append("台账 `consumers` 为空（fail-closed）：清空本表不得把守卫变成空跑")

    return problems


# ── 真语料：必须全绿 ─────────────────────────────────────────────────────
def test_real_repo_corpus_is_clean() -> None:
    problems = _problems(_frontend_units(), _ledger())
    assert problems == [], "类级元守卫判红：\n" + "\n".join(f"  - {p}" for p in problems)


def test_ledger_names_the_guard_that_judges_it() -> None:
    led = _ledger()
    assert led.get("_judged_by") == SELF_REL, (
        f"台账 `_judged_by` 必须逐字指向本判据 `{SELF_REL}`（实得 {led.get('_judged_by')!r}）"
    )
    assert (REPO_ROOT / SELF_REL).exists(), "判据自身不在仓内 ⇒ 台账指向一个不存在的承载体"


def test_real_ledger_is_not_empty() -> None:
    led = _ledger()
    assert led.get("consumers"), "台账 `consumers` 为空（fail-closed）"
    assert led["single_implementation"]["path"] in _frontend_units(), "唯一实现路径不在语料里"


# ── 判别力自证（内存注入；六种坏形态各自判红 + 一条对照）─────────────────
def _base() -> tuple[dict[str, str], dict]:
    units = _frontend_units()
    return dict(units), _ledger()


def test_injection_second_implementation_turns_red() -> None:
    units, led = _base()
    units["frontend/bmini-app/tests/helpers/zzz_injectedCorpus.ts"] = "export function readCorpus(xs: string[]) { return xs }\n"
    bad = _problems(units, led)
    assert any("第二份定义" in b and "zzz_injectedCorpus.ts" in b for b in bad), bad


def test_injection_missing_implementation_name_turns_red() -> None:
    units, led = _base()
    led["single_implementation"]["path"] = "frontend/bmini-app/tests/helpers/zzz_nonexistent.js"
    bad = _problems(units, led)
    assert any("唯一实现" in b and "zzz_nonexistent.js" in b for b in bad), bad


def test_injection_unregistered_consumer_turns_red() -> None:
    units, led = _base()
    units["frontend/bmini-app/tests/zzz_injected.test.ts"] = (
        "const { readCorpus } = require('./helpers/trackedCorpus.js')\n"
    )
    bad = _problems(units, led)
    assert any("未登记" in b and "zzz_injected.test.ts" in b for b in bad), bad


def test_injection_ledger_stamps_a_nonexistent_consumer_turns_red() -> None:
    units, led = _base()
    led["consumers"].append(
        {"path": "frontend/bmini-app/tests/zzz_ghost.test.ts", "roots": ["frontend"], "why": "x"}
    )
    bad = _problems(units, led)
    assert any("登记未兑现" in b and "zzz_ghost.test.ts" in b for b in bad), bad


def test_injection_worktree_read_face_returns_turns_red() -> None:
    """🔴 本单的缺陷形态：已登记的消费者里塞回工作树遍历 ⇒ 必红（这是「退回旧读面」的绊线）"""
    units, led = _base()
    rel = led["consumers"][0]["path"]
    units[rel] = units[rel] + "\nconst __probe = require('fs').readdirSync('.')\n"
    bad = _problems(units, led)
    assert any("readdirSync" in b and rel in b for b in bad), bad


def test_injection_raised_exception_cap_turns_red() -> None:
    units, led = _base()
    led["exceptions_frozen_max"] = 3
    led["exceptions"] = [
        {"path": "x", "reason": "r", "restart": "s"},
    ]
    bad = _problems(units, led)
    assert any("只许缩短" in b for b in bad), bad


def test_comment_only_change_keeps_it_green() -> None:
    """对照读数：只改注释 ⇒ 不红（守卫不会被自己的文案喂红）"""
    units, led = _base()
    rel = led["consumers"][0]["path"]
    units[rel] = units[rel] + "\n// 只加一行注释：读面没变（issue #6594）\n"
    assert _problems(units, led) == []
