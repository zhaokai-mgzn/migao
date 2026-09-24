# case_ids: MC-012
"""`scripts/dev-worktree.sh` 的预设快照文案必须与脚本事实一致（issue #4350）。

## 病灶（一类缺陷：**声明与实际不符，且没有任何东西会因此变红**）

v1.35 的技能改判（实测 `refresh_presets()` 在 `add` 路径被调用 ⇒ **add 已自动刷新**）只改了技能，
脚本侧的同款过期文案还在（文件头注释 + `refresh_presets` 的 echo + `preset-guard` 提示）：
读到它的人（含 agent）会以为「`add` 之后仍需人工刷新预设」，从而**重复劳动或误判工作区状态**；
而事实是真正需要人工自愈的是**活锚**（`./scripts/preset-anchor-refresh.sh`）与 **`rm/prune` 半径**。
与 `migao-dev-flow` §19.1「基于错误真相模型写出的 claim」同族。

## 四个面（照事实登记；本判据要求提示文本覆盖它们）

| 面 | 事实 |
|---|---|
| ① 创建路径 `add` | **已自动刷新**（`refresh_presets()`，v1.8 / issue #3851）⇒ **不需要**人工再刷一遍 |
| ② 提交路径 `preset-guard` | 判版本下降，命中即 fail-closed；**合法升级放行**（改研发模式不能被堵死） |
| ③ 加载点（活锚） | **必须自愈**：`./scripts/preset-anchor-refresh.sh`；同一守卫同时判活锚新鲜度 |
| ④ 清理半径 | `rm` / `prune` **会命中** worktree 的预设快照 ⇒ 清理前先 `readlink` 活锚目标 |

## 判据（各带注入式红证；注入 = 在 `tmp_path` 的副本上做，仓库文件零污染）

| # | 判据 | 红证 |
|---|---|---|
| 1 | 全脚本**不得**再出现旧口径（逐字两种形态，见 `OUTDATED_CLAIMS`） | 把旧句写回文件头 ⇒ 必红 |
| 2 | **正向**：`preset-guard` 分支的提示文本必须点名「活锚」+「自愈」+「自动刷新」三个面 | 删掉「自愈」⇒ 必红 |
| 3 | `preset-guard` 的**判定逻辑与退出码一字不改** | 分支里插入 `exit 0` ⇒ 必红 |

**为什么判据 2 是「正向」的**：只判「旧句不在」可以被「把整段说明删光」通过（那同样是
「声明与实际脱节」—— 只是从**错误**变成**缺失**）；要求四个面都在，才叫「文案与事实一致」。
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev-worktree.sh"
BASH = "bash"

#: 旧口径（v1.35 已在技能里改判；脚本侧残留 ⇒ 读到的人会白刷一遍预设）。逐字两种形态。
OUTDATED_CLAIMS = (
    "工作区不会自动跟上",
    "main 推进后不自动跟上",
)
#: `preset-guard` 分支提示必须点名的面（正向，防「删光了事」）。
GUARD_BLOCK_FACES = ("活锚", "自愈", "自动刷新")
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


def wording_violations(src: str) -> list[str]:
    """→ 违规清单（空 = 文案与四个面一致）。纯函数 ⇒ 真文件与变异副本走**同一条**判据。"""
    bad = [f"仍是旧口径（与 `add` 已自动刷新的事实不符）：{claim!r}" for claim in OUTDATED_CLAIMS if claim in src]
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

    红证（本 PR 实测）：本判据**先**写好再改脚本 ⇒ 改前必红（报出旧口径那句 + 缺「自愈」面），
    改后转绿 —— 见 `test_outdated_claim_injection_reds` 等的注入式复跑。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert wording_violations(src) == [], (
        "预设快照文案与脚本事实不一致（issue #4350）：\n"
        + "\n".join(f"  · {v}" for v in wording_violations(src))
    )


def test_outdated_claim_injection_reds(tmp_path):
    """判据 1 的**判别力自证**：把旧口径逐字写回（副本）⇒ 必须变红。

    自证：`mutated != src`；且违规清单必须**指名**那一句（不是笼统报错）。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    claim = OUTDATED_CLAIMS[0]
    needle = "#   worktree 的 `.agent-presets/**` 是**创建时刻快照**"
    assert needle in src, f"定位文件头小标题失败（fail-closed）：找不到 {needle!r}"
    mutated = src.replace(needle, f"# （旧口径回注）：{claim}\n{needle}", 1)
    assert mutated != src, "变异注入未生效（自证失败 ⇒ 本判据的红证是空断言）"
    p = tmp_path / "dev-worktree-mutated.sh"
    p.write_text(mutated, encoding="utf-8")
    violations = wording_violations(p.read_text(encoding="utf-8"))
    assert any(claim in v for v in violations), f"注入旧口径后判据没指名它：{violations}"
    assert wording_violations(src) == [], "真文件本身必须仍然合规（否则本红证分不清对象）"


def test_missing_face_injection_reds(tmp_path):
    """判据 2 的**判别力自证**：把「自愈」这一面删掉 ⇒ 必红（防「删光说明」式假修复）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    block = preset_guard_block(src)
    assert "自愈" in block, "真文件的分支提示必须已点名「自愈」（否则先修脚本再谈红证）"
    mutated = src.replace(block, block.replace("自愈", "同步"), 1)
    assert mutated != src, "变异注入未生效（自证失败）"
    violations = wording_violations(mutated)
    assert any("自愈" in v for v in violations), f"删掉「自愈」后判据没报出缺面：{violations}"


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
    first = SCRIPT.read_text(encoding="utf-8").splitlines()[:1]
    assert first == ["#!/usr/bin/env bash"], f"shebang 变了：{first}"
    r = subprocess.run([BASH, str(SCRIPT), "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, cwd=str(REPO_ROOT))
    assert "preset-guard" in (r.stdout + r.stderr), "用法块里必须仍有 preset-guard 子命令"
