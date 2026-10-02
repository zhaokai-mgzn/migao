# case_ids: MC-061
"""`growth_gate` 的**射程提示接线**判据（issue #5970）—— 非阻塞段的实例面。

## 病灶（实证 2026-10-02）

四条并行 PR（#5961 / #5963 / #5965 / #5967）共 **17 条红**，形态完全相同：
**判据只存在于全量单测里，窄跑看不见** —— 而 `growth_gate` 与 cases 面门禁**都不提示**
「这次改动的射程命中了哪些 meta 面」。本文件锁的是**接线**（提示真的被打印、真的进了结果对象、
`--json` 的新字段真存在），以及**它绝不改 blocker 语义**。

> 🔴 **为什么另开一个文件而不是塞进 `test_growth_gate_fail_closed.py`**：
> 那条文件锁的是**失败关闭**语义（扫描失败 ≠ 无发现），本文件锁的是**展示面**语义
> （提示出现/消失、且不计入 blocker）。两者判定对象不同，混在一起会让「哪一条红了」不可归因。

## 判据（每条都能单独变红）

| # | 判据 | 坏形态 ⇒ 红 |
|---|---|---|
| 1 | 命中射程的变更 ⇒ stdout 出现提示段（逐字首行） | 接线被摘掉 ⇒ 提示静默消失（**问题原地复发**） |
| 2 | 未命中 ⇒ **不出现**提示段（反面锚） | 无脑打印 ⇒ 提示变噪音，人就不看了 |
| 3 | `--json` 的 `blast_radius.faces` == 提示里列出的面 | JSON 与 stdout 双源漂移 |
| 4 | **提示在场时 `blocker_count` 不变**（0 ⇒ 仍 0） | 有人把提示算成 blocker ⇒ 门禁语义被改 |
| 5 | 注入式反面：射程面清空 ⇒ 提示消失（判据 1 的对照臂） | 提示来自别处（如硬编码字符串）⇒ 判据 1 是假绿 |
| 6 | PR 评论文本**不含**提示段 | 非阻塞提示混进 PR 评论 ⇒ 实施者读成「评论说的就是阻塞项」 |

边界（照实登记）：本文件判**接线**，判不了「射程表本身选得对不对」（那是
`test_blast_radius_registry.py` 与文档的事）；也判不了「人有没有真去跑那些命令」。
"""
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"

HINT_HEADER = "## ⚠️ 变更射程提示（非阻塞，不计入 blocker）"

#: 命中 `tool` / `rbac` 两个面的**只读**变更（不引入任何真实 blocker：工具 `order_query.py`
#: 的配套测试 `tests/test_tools_registry.py` 在仓内存在 ⇒ `classify_file` 判 pass）。
HIT_FILES = [
    "backend/ai-agent-service/app/tools/order_query.py",
    "frontend/admin-web/src/config/menu.ts",
]

#: 无关文件（不命中任何射程面）。
COLD_FILES = ["README.md", "docs/wiki/INDEX.md", ".github/scripts/blast_radius.py"]


def _load_gate():
    spec = importlib.util.spec_from_file_location("growth_gate_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_gate(files, json_file, capsys):
    gate = _load_gate()
    rc = gate.main(["--files", *files,
                    "--tech-stack", ".github/tech-stack.yml",
                    "--exemptions", ".github/qa-exemptions.yml",
                    "--check-cases", ".github/cases",
                    "--json", "--json-file", str(json_file)])
    out = capsys.readouterr().out
    payload = json.loads(Path(json_file).read_text(encoding="utf8"))
    return rc, out, payload


# ── 判据 1 + 3 + 4：命中的变更 ⇒ 提示出现，JSON 同源，blocker 语义不变 ──

def test_hint_appears_and_json_matches(tmp_path, capsys):
    rc, out, payload = _run_gate(HIT_FILES, tmp_path / "r.json", capsys)
    assert rc == 0, f"本组文件不应产生任何崩溃/阻塞，rc={rc}"
    assert HINT_HEADER in out, (
        f"命中射程的变更**没有打印射程提示**（接线被摘掉？）\n--- stdout ---\n{out}")
    assert payload["blast_radius"]["faces"] == ["tool", "rbac"], (
        f"JSON 的面清单与预期不符：{payload['blast_radius']['faces']}")
    for face in payload["blast_radius"]["faces"]:
        assert f"`{face}`" in out, f"面 {face} 在 JSON 里但没出现在提示正文里（双源漂移）"
    assert payload["blocker_count"] == 0 == len(payload["blockers"]), (
        "🔴 提示不得改变 blocker 语义：这几个文件本就零 blocker")


def test_hint_does_not_count_as_blocker_or_warning(tmp_path, capsys):
    _, out, payload = _run_gate(HIT_FILES, tmp_path / "r.json", capsys)
    assert HINT_HEADER in out
    assert payload["warning_count"] == len(payload["warnings"]) == 0, (
        "射程提示**不是 warning**（它是独立段，只在 stdout + step summary）")
    assert payload["blocker_count"] == 0, "射程提示**不是 blocker**"


# ── 判据 2：未命中 ⇒ 不出现（反面锚，防「无脑打印」）──

def test_no_hint_for_unrelated_files(tmp_path, capsys):
    _, out, payload = _run_gate(COLD_FILES, tmp_path / "r.json", capsys)
    assert HINT_HEADER not in out, (
        "无关文件不该打印射程提示（提示变噪音 = 没有人会读）")
    assert payload["blast_radius"]["faces"] == [], "无关文件的 JSON 面清单必须为空"
    assert payload["blocker_count"] == 0, "反面锚同样不得引入 blocker"


# ── 判据 5：注入式反面 —— 射程面清空 ⇒ 提示消失（判据 1 的对照臂）──

def test_hint_disappears_when_face_table_is_emptied(tmp_path, capsys, monkeypatch):
    """把射程表清空（**注入**）⇒ 同一组文件下提示必须消失、`blocker_count` 仍为 0。

    为什么这条不可省：判据 1 只证明「出现」，不排除提示来自别处（硬编码文案）；
    清空数据源后仍出现 ⇒ 判据 1 是**假绿**。
    """
    gate = _load_gate()
    real = gate._load_blast_radius()
    assert hasattr(real, "FACES"), "射程模块加载失败 ⇒ 本判据无法自证（先修加载）"
    monkeypatch.setattr(real, "FACES", [])
    monkeypatch.setattr(gate, "_load_blast_radius", lambda: real)
    rc = gate.main(["--files", *HIT_FILES,
                    "--tech-stack", ".github/tech-stack.yml",
                    "--exemptions", ".github/qa-exemptions.yml",
                    "--check-cases", ".github/cases",
                    "--json", "--json-file", str(tmp_path / "r.json")])
    out = capsys.readouterr().out
    payload = json.loads((tmp_path / "r.json").read_text(encoding="utf8"))
    assert rc == 0 and payload["blocker_count"] == 0, "注入不得改变本组文件的判定"
    assert HINT_HEADER not in out, (
        "🔴 射程表已清空，提示却仍在打印 ⇒ 提示不是从**同一份数据源**来的（判据 1 假绿）")
    assert payload["blast_radius"]["faces"] == [], "JSON 面清单必须随数据源一起清空"


# ── 判据 6：PR 评论不含提示（非阻塞段只在控制台/step summary）──

def test_pr_comment_does_not_carry_the_hint(tmp_path, capsys):
    _, _, payload = _run_gate(HIT_FILES, tmp_path / "r.json", capsys)
    gate = _load_gate()
    comment = gate.render_pr_comment(payload)
    assert HINT_HEADER not in comment, (
        "PR 评论只该说「阻塞/不阻塞」的结论；把射程提示混进去会被读成阻塞项")
    assert "射程" not in comment, "评论文本里连措辞都不该出现（同上理由）"


def test_gate_module_stays_importable_without_the_scripts_package():
    """接线面：`growth_gate.py` 由**文件路径**加载射程模块（`.github` 不在 sys.path 上）。"""
    gate = _load_gate()
    mod = gate._load_blast_radius()
    assert hasattr(mod, "render_hint"), "射程模块加载失败（路径写错？）⇒ 提示会静默消失且不阻塞"
    assert "blast_radius.py" in (mod.__file__ or ""), f"加载到了别的对象：{mod.__file__}"
    # 现取坐标自证（铁律 11(a)）：目录形态随 `--files` 走，这里只钉住它在仓内
    assert str(REPO_ROOT) in (mod.__file__ or ""), f"射程模块不在本仓内：{mod.__file__}"
    assert sys.version_info.major == 3
