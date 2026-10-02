# case_ids: MC-012
"""`scripts/dev-worktree.sh` 的预设文案必须与脚本事实一致（issue #4350；S4 改判见 #6020）。

## 病灶（一类缺陷：**声明与实际不符，且没有任何东西会因此变红**）

v1.35 的技能改判（实测 `refresh_presets()` 在 `add` 路径被调用 ⇒ **add 已自动刷新**）只改了技能，
脚本侧的同款过期文案还在 ⇒ 读到它的人（含 agent）会**重复劳动或误判工作区状态**；
而事实是真正需要人工自愈的是**活锚**（`./scripts/preset-anchor-refresh.sh`）与 **`rm/prune` 半径**。
与 `migao-dev-flow` §19.1「基于错误真相模型写出的 claim」同族。

## 🔴 S4（issue #6020，2026-10-02）改判：那份「四个面」整体过期了

预设的权威源已迁到独立仓 `zhaokai-mgzn/migao-agent-presets`，本业务仓**不再承载** `.agent-presets/**`
⇒ 「worktree 的 `.agent-presets/**` 是创建时刻快照」「add 自动刷新快照」「快照挡住 rebase」这一整套
（原面①/面④）**随路径一起消失**。现在的**两个面**是：

| 面 | 事实 |
|---|---|
| ① 提交路径 `preset-guard` | 判**业务仓** `.agent-presets/**` 版本下降 / 同号撞车，命中即 fail-closed；**合法升级放行**。⚠️ S4 后业务仓无该路径 ⇒ **零动作放行**（内容侧判据由**预设仓 CI**承担）；本子命令同时判**加载点** |
| ② 加载点（活锚） | **必须自愈**：`./scripts/preset-anchor-refresh.sh`（把专职只读镜像刷到**预设仓** main；落后/悬空即非零退出） |

## 判据（各带注入式红证；注入 = 在内存 / `tmp_path` 副本上做，仓库文件零污染）

| # | 判据 | 红证 |
|---|---|---|
| 1 | 全脚本**不得**再出现「预设随业务仓」的动作（`refresh_presets` / `discard_preset_snapshot` / `checkout origin/main -- .agent-presets/`） | 把旧函数写回 ⇒ 必红 |
| 2 | **正向**：全脚本必须同时点名「活锚」与「预设仓」，`preset-guard` 分支必须点名「自愈」 | 删掉「预设仓」⇒ 必红 |
| 3 | `preset-guard` 的**判定逻辑与退出码一字不改**（`exec … --repo "$ROOT" check "$@"`，且分支里不得有 `exit 0`） | 分支里插入 `exit 0` / 把 `--repo` 改成 `$REPO_ROOT` ⇒ 必红 |

**为什么判据 2 是「正向」的**：只判「旧句不在」可以被「把整段说明删光」通过（那同样是
「声明与实际脱节」—— 只是从**错误**变成**缺失**）；要求新面都在，才叫「文案与事实一致」。
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev-worktree.sh"
BASH = "bash"

#: 旧口径的**动作 / 函数**（S4 起业务仓不该再有「预设随业务仓」的实现）。逐字。
OUTDATED_ACTIONS = (
    "refresh_presets",
    "discard_preset_snapshot",
    "checkout origin/main -- .agent-presets/",
)
#: 全脚本必须点名的面（正向，防「删光了事」）—— S4 的两个面 + 权威源。
SCRIPT_FACES = ("活锚", "预设仓")
#: `preset-guard` 分支提示必须点名的面。
GUARD_BLOCK_FACES = ("活锚", "自愈")
#: `preset-guard` 的判定本体（承重：本单只治文案，不许顺手动逻辑或退出码）。
PRESET_GUARD_EXEC = 'exec "${PY}" "${guard}" --repo "$ROOT" check "$@"'


def preset_guard_block(src: str) -> str:
    """`preset-guard)` 分支的正文（到该分支的 `;;` 为止）—— 结构化定位，不靠行号。"""
    start = src.find("\n  preset-guard)\n")
    if start < 0:
        raise AssertionError("定位 `preset-guard)` 分支失败（fail-closed，别静默跳过）")
    end = src.find("\n    ;;\n", start)
    if end < 0:
        raise AssertionError("定位 `preset-guard)` 分支结尾 `;;` 失败（fail-closed）")
    return src[start:end]


def code_lines(src: str) -> str:
    """剥掉**整行注释**后剩下的代码（判据 1 只看代码）。

    为什么剥离：脚本头部的「S4 删掉了 `refresh_presets()` / `discard_preset_snapshot()`」这类
    **沿革说明**必须能写（否则等于把「删了什么、为什么删」从脚本里抹掉）；而旧的**动作**
    （函数定义 / 调用 / `checkout origin/main -- .agent-presets/`）才是不许回来的东西。
    ⚠️ 剥离是**行首注释**（`^\s*#`）—— 行尾注释里藏动作仍会被判到（不给人留缝）。
    """
    return "\n".join(l for l in src.splitlines() if not re.match(r"^\s*#", l))


def wording_violations(src: str) -> list[str]:
    """→ 违规清单（空 = 文案与事实一致）。纯函数 ⇒ 真文件与变异副本走**同一条**判据。"""
    code = code_lines(src)
    bad = [
        f"仍带着「预设随业务仓」的动作（S4 / issue #6020 后业务仓已无 `.agent-presets/**`）：{action!r}"
        for action in OUTDATED_ACTIONS if action in code
    ]
    bad += [f"全脚本文案没点名「{face}」这个面（删说明 ≠ 一致）"
            for face in SCRIPT_FACES if face not in src]
    block = preset_guard_block(src)
    bad += [f"`preset-guard` 分支的提示没点名「{face}」这个面（删说明 ≠ 一致）"
            for face in GUARD_BLOCK_FACES if face not in block]
    if PRESET_GUARD_EXEC not in block:
        bad.append(f"`preset-guard` 的判定本体被改动（必须仍是：{PRESET_GUARD_EXEC}）")
    if re.search(r"^\s*exit 0\s*$", block, re.M):
        bad.append("`preset-guard` 分支里出现了 `exit 0`（把守卫改成恒通过 = 吞掉 fail-closed）")
    return bad


def test_dev_worktree_wording_matches_script_facts():
    """判据 1+2+3（真文件）：文件头 / echo / `preset-guard` 提示都必须与实际一致。

    红证（S4 实测）：`refresh_presets` 尚在时本判据必红（判据 1 逐字命中）；脚本改完后转绿。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert wording_violations(src) == [], (
        "预设文案与脚本事实不一致（issue #4350 / S4 #6020）：\n"
        + "\n".join(f"  · {v}" for v in wording_violations(src))
    )


def test_outdated_action_injection_reds(tmp_path):
    """判据 1 的**判别力自证**：把旧动作逐字写回（副本）⇒ 必须变红，且**指名**它。

    自证：`mutated != src`；且违规清单必须**指名**那条动作（不是笼统报错）。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    action = OUTDATED_ACTIONS[0]
    needle = "# ── 活锚镜像刷新"
    assert needle in src, f"定位文件头小标题失败（fail-closed）：找不到 {needle!r}"
    mutated = src.replace(needle, f"{action}() {{ :; }}\n{needle}", 1)
    assert mutated != src, "变异注入未生效（自证失败 ⇒ 本判据的红证是空断言）"
    p = tmp_path / "dev-worktree-mutated.sh"
    p.write_text(mutated, encoding="utf-8")
    violations = wording_violations(p.read_text(encoding="utf-8"))
    assert any(action in v for v in violations), f"注入旧动作后判据没指名它：{violations}"
    assert wording_violations(src) == [], "真文件本身必须仍然合规（否则本红证分不清对象）"


def test_comment_only_mention_is_not_red(tmp_path):
    """**假红对照**：把动作名只写进**注释**（沿革说明）⇒ 判据 1 必须**不**报 —— 否则等于禁止
    脚本解释「S4 删掉了什么」（判据 1 的射程是**代码**，不是散文）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    needle = "# ── 活锚镜像刷新"
    assert needle in src
    mutated = src.replace(needle, f"# 沿革：S4 删掉了 {OUTDATED_ACTIONS[0]}（对照）\n{needle}", 1)
    assert mutated != src, "变异注入未生效（自证失败）"
    assert wording_violations(mutated) == [], (
        "只写进注释也被判红 ⇒ 判据在误伤沿革说明：\n" + "\n".join(wording_violations(mutated))
    )


def test_missing_face_injection_reds(tmp_path):
    """判据 2 的**判别力自证**：把「预设仓」「自愈」两面分别删掉 ⇒ 必红（防「删光说明」式假修复）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    block = preset_guard_block(src)
    assert "自愈" in block, "真文件的分支提示必须已点名「自愈」（否则先修脚本再谈红证）"
    mutated = src.replace(block, block.replace("自愈", "同步"), 1)
    assert mutated != src, "变异注入未生效（自证失败）"
    assert any("自愈" in v for v in wording_violations(mutated)), "删掉「自愈」后判据没报出缺面"

    assert "预设仓" in src, "真文件必须已点名权威源（预设仓）"
    mutated2 = src.replace("预设仓", "某仓库")
    assert mutated2 != src, "变异注入未生效（自证失败）"
    assert any("预设仓" in v for v in wording_violations(mutated2)), "删掉「预设仓」后判据没报出缺面"


def test_logic_or_exit_code_change_in_guard_block_is_caught():
    """判据 3 的**判别力自证**：往 `preset-guard` 分支塞 `exit 0` ⇒ 必红（判据 3 不是纸面承诺）。

    另：判定本体的 exec 行必须逐字在位（`--repo "$ROOT"` 那条 —— 用错根会让判据「绿了但没跑」，
    见该行上方既有注释里登记的那次实测）。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    block = preset_guard_block(src)
    mutated = src.replace(block, block.replace("    shift\n", "    shift\n    exit 0\n", 1), 1)
    assert mutated != src, "变异注入未生效（自证失败）"
    assert any("exit 0" in v for v in wording_violations(mutated)), "插入 exit 0 没被判据抓到"
    mutated2 = src.replace(block, block.replace('--repo "$ROOT"', '--repo "$REPO_ROOT"'), 1)
    assert mutated2 != src, "变异注入未生效（自证失败）"
    assert any("判定本体" in v for v in wording_violations(mutated2)), "改掉 exec 目标（读错索引根）没被抓到"


def test_script_is_still_executable_bash(tmp_path):
    """反绕过锁：本单**只治文案** —— 脚本必须仍是可执行的 bash（`--help` 仍能跑出用法）。

    红证：把 shebang 改成非 bash / 去掉可执行位 ⇒ 必红。
    """
    assert SCRIPT.stat().st_mode & 0o111, f"{SCRIPT} 丢了可执行位"
    first = SCRIPT.read_text(encoding="utf-8").splitlines()[:1]
    assert first == ["#!/usr/bin/env bash"], f"shebang 变了：{first}"
    r = subprocess.run([BASH, str(SCRIPT), "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, cwd=str(REPO_ROOT))
    assert "preset-guard" in (r.stdout + r.stderr), "用法块里必须仍有 preset-guard 子命令"
