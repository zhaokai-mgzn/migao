# case_ids: HR-009, DF-003
"""Agent 能力研发范式的**元守卫**（issue #7291）。

范式（`docs/wiki/agent-capability-paradigm.md`）的三条不变式：
1. **声明 = 投影**：对模型可见的能力 / 权限 / 意图声明，必须由代码从真值源投影生成，
   prompt 文件只放领域知识 —— 不得手写能力矩阵。
2. **每个投影都有判据**：真值源 → 渲染缝 → 判据，三件套登记在
   `tests/agent_projection_ledger.json`；未登记 / 判据文件不存在 / 渲染缝不可解析 ⇒ 红。
3. **真值变化必须红**：投影的判据里要有现实快照（工具 / 权限一变就红）。

本文件只判「有没有按范式接」，**不判**「这条能力该不该有」（那是业务裁定）。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[2]
_REFERENCES = _TESTS_DIR.parent / "app" / "graph" / "skills" / "references"
_LEDGER = _TESTS_DIR / "agent_projection_ledger.json"

#: 投影清单快照：新增/删除投影必须显式改这里（配合 `agent_projection_ledger.json`）。
PROJECTION_KEYS = [
    "capability_boundary",
    "capability_index",
    "intent_ownership",
    "permission_scope",
]

#: 手写能力矩阵的形态（#7291 的病灶）。prompt 文件里出现即红 ——
#: 能力断言只能由投影产出（`capability_boundary` / `capability_index`）。
BANNED_CLAIM_FORMS = ("✅ 支持", "❌ 不支持", "✅ 不支持")


def _load_ledger() -> dict:
    return json.loads(_LEDGER.read_text(encoding="utf-8"))


def test_ledger_shape():
    ledger = _load_ledger()
    assert ledger["version"] == 1
    assert ledger["projections"], "投影片账不得为空"
    for entry in ledger["projections"]:
        assert set(entry) == {"key", "truth", "render", "guard"}, entry
        for field in ("key", "truth", "render", "guard"):
            assert entry[field].strip(), f"{entry.get('key')}: {field} 为空"


def test_projection_keys_are_frozen():
    """只许显式改判：新增投影要同时改台账与本快照（防「偷偷加一个没人守的投影」）。"""
    assert sorted(p["key"] for p in _load_ledger()["projections"]) == PROJECTION_KEYS


def test_every_projection_has_resolvable_render_and_guard():
    """渲染缝必须可解析、判据文件必须存在（否则台账只是自我安慰）。"""
    for entry in _load_ledger()["projections"]:
        render = entry["render"]
        if "::" in render:
            module_name, symbol = render.split("::", 1)
            module = importlib.import_module(module_name)
            assert callable(getattr(module, symbol, None)), (
                f"{entry['key']}: 渲染缝 {render} 不可调用"
            )
        else:
            assert (_REPO_ROOT / render).is_file(), (
                f"{entry['key']}: 渲染缝文件不存在 {render}"
            )
        assert (_REPO_ROOT / entry["guard"]).is_file(), (
            f"{entry['key']}: 判据文件不存在 {entry['guard']}"
        )


def test_no_handwritten_capability_matrix_in_prompts():
    """类级守卫：prompt 里不得再出现手写能力矩阵（#7291 的 9 处形态）。"""
    offenders = []
    for path in _REFERENCES.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        hits = [form for form in BANNED_CLAIM_FORMS if form in text]
        if hits:
            offenders.append(f"{path.relative_to(_REFERENCES)}: {hits}")
    assert not offenders, (
        "以下 prompt 仍在手写能力声明（应改为投影渲染，见 agent-capability-paradigm.md）：\n"
        + "\n".join(offenders)
    )


def test_paradigm_doc_exists_and_is_indexed():
    """范式页必须在，且从 Wiki 索引可达（否则下一个会话读不到）。"""
    doc = _REPO_ROOT / "docs" / "wiki" / "agent-capability-paradigm.md"
    assert doc.is_file(), "缺少范式页 docs/wiki/agent-capability-paradigm.md"
    index = (_REPO_ROOT / "docs" / "wiki" / "INDEX.md").read_text(encoding="utf-8")
    assert "agent-capability-paradigm" in index, "范式页未接入 Wiki 索引"
