# case_ids: MC-230
"""类级元守卫（issue #8175 P2）：**把口径卡置 active 的全部写路径必须登记**。

## 这条判据治什么

「同一条口径出现两条 active」不是某一行代码的缺陷，而是一**类**：只要将来有人新增一条
「把卡改成 active」的写路径（新的 sweep / 新的审批入口 / 新的运营脚本），而它没有走
冲突守卫，P2 的写面护栏就**当场失效** —— 而所有功能测试照样绿（那条新路径根本没被测到）。

所以这里不测「某条路径的行为」，而是测**路径集合本身**：

1. 全仓扫描（Java main + Python app）里所有 `SET state = 'active'` 形态的写语句；
2. 命中文件必须逐条登记在 `REGISTRY`（登记值 = 该文件里承担激活的那条语句/符号）；
3. **未登记 ⇒ 红**（新增路径进不来）；**登记了但已扫不到 ⇒ 也红**（台账过期，必须销账）；
4. 扫描自身有牙齿：合成一段未登记的写路径 ⇒ 必须被标红（不是「看起来在扫」）。

## 判红时的可行动出口

红文案会打印「扫到的文件 + 登记表 + 可复制命令」。修法二选一：
① 让新路径复用已登记的 CAS（推荐：`PlaybookMapper.activateIfDraft` /
`lifecycle._PROMOTE_SQL`，两者都内建冲突/前态检查）；② 若确实是另一条独立路径，
把它登记进 `REGISTRY` **并在 PR 里说明它如何走冲突守卫**（登记不是豁免）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 登记表：路径（仓库相对）→ 该文件里承担「置 active」的语句/符号
REGISTRY = {
    "backend/admin-api/src/main/java/com/migao/admin/mapper/PlaybookMapper.java": "activateIfDraft",
    "backend/ai-agent-service/app/playbook/lifecycle.py": "_PROMOTE_SQL",
}

#: 写面语句的形态：**对 `playbooks` 的 UPDATE ... SET state='active'**。
#: 只认这张表 —— 否则别的域（如 agent_batches）将来新增一个同名状态迁移会把本守卫打成假红，
#: 而「假红」会诱导下一个人去登记无关文件、把登记表变成垃圾场。
_ACTIVATE_PATTERN = re.compile(
    r"UPDATE\s+playbooks\b[\s\S]{0,300}?SET\s+state\s*=\s*'active'",
    re.IGNORECASE,
)

_SCAN_ROOTS = (
    "backend/admin-api/src/main",
    "backend/ai-agent-service/app",
)


def _iter_source_files():
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix not in (".java", ".py"):
                continue
            yield path


def scan_activation_paths(files) -> dict:
    """→ `{相对路径: [命中行号...]}`（只扫**可执行**语句，不看注释里的举例）。"""
    hits: dict = {}
    for path, text in files:
        matched = [
            text.count("\n", 0, match.start()) + 1 for match in _ACTIVATE_PATTERN.finditer(text)
        ]
        if matched:
            hits[str(path)] = matched
    return hits


def _files():
    for path in _iter_source_files():
        yield path.relative_to(REPO_ROOT), path.read_text(encoding="utf-8")


def compare(seen: dict) -> list:
    """→ 具名差异清单（空 = 登记表与代码一致）。"""
    problems: list = []
    unregistered = sorted(set(seen) - set(REGISTRY))
    if unregistered:
        problems.append(
            "未登记的激活写路径（新增路径必须走冲突守卫，或登记并说明它如何走）："
            + "；".join(f"{path}（行 {seen[path]}）" for path in unregistered)
        )
    stale = sorted(set(REGISTRY) - set(seen))
    if stale:
        problems.append(
            "登记表里已扫不到对应写路径（台账过期，请销账）：" + "；".join(stale)
        )
    if not seen:
        problems.append("扫描面为空（扫描器没工作 ≠ 没有写路径）")
    return problems


def test_every_activation_write_path_is_registered():
    seen = scan_activation_paths(_files())
    problems = compare(seen)
    assert not problems, (
        "\n".join(problems)
        + "\n复现：python3 -m pytest tests/unit_ci_workflows/test_playbook_active_write_registry.py -q"
        + "\n登记表：tests/unit_ci_workflows/test_playbook_active_write_registry.py::REGISTRY"
    )


def test_registry_entries_name_a_real_symbol():
    """登记值必须是文件里真实存在的符号（写错名字 = 台账看起来有、实际指不到东西）。"""
    for path, symbol in REGISTRY.items():
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert symbol in text, f"{path} 里找不到登记的符号 {symbol!r}"


def test_scanner_ignores_unrelated_tables():
    """别的域的 `SET state='active'` 不许被本守卫误红（否则登记表会变成垃圾场）。"""
    assert scan_activation_paths(
        [(Path("rogue.py"), "UPDATE agent_batches SET state = 'active' WHERE id = :id")]
    ) == {}


def test_scanner_matches_multiline_python_sql():
    """Python 侧的 SQL 是跨行的（`UPDATE playbooks` 换行后才是 `SET`）⇒ 必须按全文匹配。"""
    assert scan_activation_paths([(Path("x.py"), "UPDATE playbooks\nSET state = 'active', activated_at = NOW()")]) != {}


def test_scanner_has_teeth_on_unregistered_path():
    """合成一条未登记的激活写路径 ⇒ 必须被标红（证明扫描器真的在看，不是空转）。"""
    synthetic = {
        "backend/ai-agent-service/app/playbook/rogue.py": 42,
    }
    problems = compare(synthetic)
    assert any("未登记" in problem for problem in problems)
    assert any("rogue.py" in problem for problem in problems)


def test_scanner_has_teeth_on_stale_registry_entry():
    """登记了、但代码里已经没有这条写路径 ⇒ 也必须红（否则登记表会烂成垃圾场）。"""
    problems = compare({})
    assert any("扫描面为空" in problem for problem in problems)
    missing = compare({"backend/ai-agent-service/app/playbook/lifecycle.py": 1})
    assert any("台账过期" in problem for problem in missing)
