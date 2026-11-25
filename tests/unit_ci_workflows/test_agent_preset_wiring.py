# case_ids: MC-012, MC-013
"""预设**技能接线**守卫（2026-11-25 实测故障）—— 含**红证**。

守的是这颗地雷（本单的主因）：本机生效的 `migao` preset 是 `~/.dsh/profiles/web/cordis.patch.yml`
里的**声明行**（dsh 0.2.2 升级时从目录 preset 迁移过去的），它的 `skill-filesystem` 行写着
`customSkillDirs: [ <anchor>/skills ]` —— 而 2026-11-21 预设仓改成 `presets/<name>/` 布局后
该路径已不存在。插件对不存在的技能根**静默跳过** ⇒ preset 自带的两个技能从未加载，
真正让 catalog「看起来有技能」的是 `~/.dsh/skills` 里的两条**临时软链**（宿主默认根兜底）。

⇒ 本守卫四类判据（每条都要能单独变红）：

① **缺根**：技能根不存在 ⇒ 红（今晚的故障形态）；
② **指错副本**：根存在、但不是活锚的技能目录（旧布局 / 改错副本）⇒ 红；
③ **覆盖不全**：活锚里有、接线根里没有 ⇒ 红（预设加了技能却看不到）；
④ **兜底遮蔽**：`$DSH_HOME/skills` 下出现同名技能 ⇒ 红（断线仍假绿）；
⑤ **无法判定**：没有 profile patch / 没有该 preset 声明行 ⇒ **3**（不得当 0 读）。

夹具全部建在 `tmp_path` 的**真目录**里（不是 mock）——判据本体是路径解析与 `!!js` 求值，
mock 掉它们等于把被测对象换成替身（`migao-acceptance` 的「空跑」同族）。
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "agent-preset-wiring-guard.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("agent_preset_wiring_guard", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def env(tmp_path: Path):
    """dsh home + 活锚 preset（两个技能）。"""
    dsh = tmp_path / "dsh"
    anchor = tmp_path / "anchor"
    (dsh / "profiles" / "web").mkdir(parents=True)
    for name in ("migao-dev-flow", "migao-acceptance"):
        skill = anchor / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}\n---\n", encoding="utf-8")
    return dsh, anchor


def write_patch(dsh: Path, roots: list[str], *, with_skill_row: bool = True) -> Path:
    """写一份最小 profile patch：`- insert:` 里一个 `@deepseek-ai/dsh-agent-preset` 声明行。"""
    lines = [
        "- insert:",
        "    - id: preset-migao",
        "      name: '@deepseek-ai/dsh-agent-preset'",
        "      config:",
        "        id: migao",
        "        plugins:",
    ]
    if with_skill_row:
        lines.extend([
            "          - id: skill-filesystem",
            "            name: '@deepseek-ai/dsh-skill-filesystem'",
            "            config:",
            "              customSkillDirs:",
        ])
        for root in roots:
            lines.append(f"                - {root}")
    patch = dsh / "profiles" / "web" / "cordis.patch.yml"
    patch.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return patch


def judge(guard, dsh: Path, anchor: Path, **kwargs) -> tuple[int, str]:
    out = io.StringIO()
    patch = kwargs.pop("patch", dsh / "profiles" / "web" / "cordis.patch.yml")
    code = guard.judge(patch, anchor, "migao", dsh, out=out, **kwargs)
    return code, out.getvalue()


def test_green_when_root_is_anchor_skills(guard, env):
    dsh, anchor = env
    write_patch(dsh, [str(anchor / "skills")])
    code, out = judge(guard, dsh, anchor)
    assert code == 0, out
    assert "✅" in out


def test_missing_root_is_red(guard, env):
    """红证 ①：根不存在（今晚的故障形态）⇒ 红，且报错点出「静默跳过」。"""
    dsh, anchor = env
    write_patch(dsh, [str(anchor / "skills" / "gone")])
    code, out = judge(guard, dsh, anchor)
    assert code == 1, out
    assert "不存在" in out and "静默跳过" in out


def test_wrong_copy_is_red(guard, env, tmp_path: Path):
    """红证 ②：根存在但 realpath 不是活锚的技能目录（改错副本 / 旧布局）。"""
    dsh, anchor = env
    copy = tmp_path / "copy" / "skills"
    for name in ("migao-dev-flow", "migao-acceptance"):
        (copy / name).mkdir(parents=True)
        (copy / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    write_patch(dsh, [str(copy)])
    code, out = judge(guard, dsh, anchor)
    assert code == 1, out
    assert "改错副本" in out


def test_uncovered_skill_is_red(guard, env, tmp_path: Path):
    """红证 ③：活锚里有两个技能，接线根只覆盖一个 ⇒ 红（预设加了技能却看不到）。"""
    dsh, anchor = env
    partial = tmp_path / "partial"
    (partial / "migao-dev-flow").mkdir(parents=True)
    (partial / "migao-dev-flow" / "SKILL.md").write_text("---\nname: migao-dev-flow\n---\n", encoding="utf-8")
    write_patch(dsh, [str(partial)])
    code, out = judge(guard, dsh, anchor)
    assert code == 1, out
    assert "覆盖不到" in out and "migao-acceptance" in out


def test_host_stopgap_masking_is_red(guard, env):
    """红证 ④：$DSH_HOME/skills 下有同名软链 ⇒ 红（断线仍会“看起来有技能”）。"""
    dsh, anchor = env
    write_patch(dsh, [str(anchor / "skills")])
    stopgap = dsh / "skills" / "migao-dev-flow"
    stopgap.parent.mkdir(parents=True)
    stopgap.symlink_to(anchor / "skills" / "migao-dev-flow")
    code, out = judge(guard, dsh, anchor)
    assert code == 1, out
    assert "兜底遮蔽" in out


def test_js_expression_root_is_evaluated(guard, env):
    """`!!js` 表达式（`dshHomePath`）能求值 ⇒ 绿：证明判据读的是**求值后的路径**。"""
    dsh, anchor = env
    patch = write_patch(dsh, [])
    patch.write_text(
        patch.read_text(encoding="utf-8").replace(
            "              customSkillDirs:\n",
            "              customSkillDirs:\n                - !!js \"dshHomePath('..', 'anchor', 'skills')\"\n",
        ),
        encoding="utf-8",
    )
    code, out = judge(guard, dsh, anchor)
    assert code == 0, out


def test_broken_expression_is_red(guard, env):
    """表达式求值失败 ⇒ 红（fail-closed，不许当成「没有这个根」静默通过）。"""
    dsh, anchor = env
    patch = write_patch(dsh, [])
    patch.write_text(
        patch.read_text(encoding="utf-8").replace(
            "              customSkillDirs:\n",
            "              customSkillDirs:\n                - !!js \"process.nope.boom\"\n",
        ),
        encoding="utf-8",
    )
    code, out = judge(guard, dsh, anchor)
    assert code == 1, out
    assert "求值失败" in out


def test_no_skill_row_is_red(guard, env):
    """声明行没有 skill 行、但活锚有技能 ⇒ 红（技能无处加载）。"""
    dsh, anchor = env
    patch = write_patch(dsh, [], with_skill_row=False)
    code, out = judge(guard, dsh, anchor)
    assert code == 1, out
    assert "没有任何" in out


def test_absent_patch_is_three(guard, env):
    """三态：没有 profile patch ⇒ 3（不得当 0 读）。"""
    dsh, anchor = env
    code, out = judge(guard, dsh, anchor, patch=dsh / "profiles" / "web" / "absent.yml")
    assert code == 3, out
    assert "未跑判定" in out


def test_other_preset_only_is_three(guard, env):
    """三态：patch 里没有该 preset 的声明行 ⇒ 3（不得当 0 读）。"""
    dsh, anchor = env
    patch = write_patch(dsh, [str(anchor / "skills")])
    patch.write_text(patch.read_text(encoding="utf-8").replace("id: migao", "id: someone-else"), encoding="utf-8")
    code, out = judge(guard, dsh, anchor)
    assert code == 3, out
