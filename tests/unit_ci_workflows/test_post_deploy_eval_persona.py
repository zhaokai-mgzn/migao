# case_ids: MC-012
"""`post-deploy-eval` 的 persona 收窄面（#7340）。

用户 2026-10-19 明确「当前只需要处理 B 端黄金策 agent，不要连带跑 C 端评测」。
本文件把这条需求锁在 workflow 形态上：

① dispatch 必须有 `persona` 选择（both / mibao / xiaobu），默认 both；
② matrix 必须由该输入动态收窄（不是永远双端）；
③ 单腿只允许 `purpose=debug` —— 判定用途必须 both（单腿不能冒充全量判定）；
④ report 必须给单腿留档、且 debug 失败不当作「部署后回归失败」建 issue。

反向红证：把 matrix 改回固定 `[mibao, xiaobu]`、删 persona 输入、删单腿守卫或删
report 留档 ⇒ 本文件的 audit 必须报问题。
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "post-deploy-eval.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")) or {}


def _inputs(wf: dict) -> dict:
    return ((wf.get("on") or wf.get(True) or {}).get("workflow_dispatch") or {}).get("inputs") or {}


def _steps(wf: dict) -> list[dict]:
    return (wf.get("jobs") or {}).get("eval", {}).get("steps") or []


def _report_steps(wf: dict) -> list[dict]:
    return (wf.get("jobs") or {}).get("report", {}).get("steps") or []


def audit_persona_surface(wf: dict) -> list[str]:
    """纯函数：输入解析后的 workflow，返回「persona 面」问题列表（空 = 合规）。"""
    problems: list[str] = []
    persona = _inputs(wf).get("persona") or {}
    options = persona.get("options") or []
    if persona.get("default") != "both":
        problems.append("persona 默认值必须 both")
    if set(options) != {"both", "mibao", "xiaobu"}:
        problems.append(f"persona 选项必须 both/mibao/xiaobu，实测 {options!r}")
    if persona.get("type") != "choice":
        problems.append("persona 必须是 choice")

    matrix = ((wf.get("jobs") or {}).get("eval", {}).get("strategy") or {}).get("matrix") or {}
    expr = str(matrix.get("persona") or "")
    if "fromJSON" not in expr or "github.event.inputs.persona" not in expr:
        problems.append("matrix.persona 必须由 dispatch 输入动态收窄（fromJSON + github.event.inputs.persona）")
    if "[mibao, xiaobu]" in expr:
        problems.append("matrix.persona 仍是固定双端")

    guard = [s for s in _steps(wf) if "单腿仅允许 debug" in (s.get("name") or "")]
    if not guard:
        problems.append("缺「单腿仅允许 debug」守卫")
    else:
        run = str(guard[0].get("run") or "")
        if "determination" not in run or "exit 1" not in run:
            problems.append("单腿守卫必须在 purpose=determination 时 exit 1")

    notes = [s for s in _report_steps(wf) if "单腿/调试留档" in (s.get("name") or "")]
    if not notes:
        problems.append("report 缺单腿/调试留档步骤")

    issue = [s for s in _report_steps(wf) if "Create Issue on failure" in (s.get("name") or "")]
    if not issue or "purpose" not in str(issue[0].get("if") or ""):
        problems.append("debug 失败不得当作部署后回归失败建 issue（Create Issue 的 if 必须排除 debug）")
    return problems


def test_persona_surface_is_wired() -> None:
    problems = audit_persona_surface(_load())
    assert problems == [], "persona 面不合规：\n" + "\n".join(problems)


def test_red_proof_fixed_matrix_is_detected() -> None:
    """反向红证：把动态 matrix 改回固定双端 ⇒ audit 必须报问题。"""
    wf = _load()
    wf["jobs"]["eval"]["strategy"]["matrix"]["persona"] = "[mibao, xiaobu]"
    problems = audit_persona_surface(wf)
    assert any("固定双端" in p or "动态收窄" in p for p in problems), problems


def test_red_proof_missing_guard_is_detected() -> None:
    """反向红证：删掉单腿守卫 ⇒ audit 必须报问题。"""
    wf = _load()
    wf["jobs"]["eval"]["steps"] = [
        s for s in wf["jobs"]["eval"]["steps"]
        if "单腿仅允许 debug" not in (s.get("name") or "")
    ]
    problems = audit_persona_surface(wf)
    assert any("单腿仅允许 debug" in p for p in problems), problems
