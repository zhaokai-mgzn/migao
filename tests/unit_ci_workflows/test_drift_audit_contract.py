# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI workflow 结构由 pytest 单测验证」是 misc.yml 里已登记的形态）
"""L0 红证：统一漂移审计（`scripts/drift_audit.py`）的**每条判据都有能红的夹具**。

为什么这个文件存在（本契约 §7「反退化规则」的落码）：
  ① 判据集合不得为空、每条判据必须写清判定方式与违反后的处置、判定面不得为 0；
  ② **每条护栏必须带"能红的夹具"，且夹具用真实历史缺陷**——没红证的断言是空断言
     （`migao-acceptance`「可执行断言 + 红证」）；
  ③ 新增判据而不补夹具 ⇒ **红**（`test_every_check_has_redproof` 遍历 `--list-checks`）。

夹具形态：**注入式红证**（在临时 git 仓库里**构造**漂移态 → 断言审计必报出），
而不是"断言仓库当下恰有该缺陷"（那是自毁式真值主张，修好即红且报错指向错误方向）。
所有夹具走 `--repo/--base/--live-anchor/--gh-fixture/--now/--offline`，**不依赖本机状态**。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIFT = REPO_ROOT / "scripts" / "drift_audit.py"

SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
COPY_REL = "docs/wiki/DEV-FLOW.md"

SKILL_TMPL = """---
name: migao-dev-flow
version: {version}
description: fixture skill
---

# fixture 技能

## 1. 三把工具

正文甲。

## 2. 提交流程

正文乙。
"""

COPY_TMPL = """# fixture 同步副本

> 本文档是 DSH 技能 `migao-dev-flow`（**权威源：`.agent-presets/migao/skills/migao-dev-flow/SKILL.md`**）的仓库同步副本。
> 当前版本：v{version}（2026-09-04）。

## 1. 三把工具

正文甲。

## 2. 提交流程

正文乙。
"""

CASE_TMPL = """schema: "1"
domain: order
cases:
  - id: FX-001
    title: fixture 用例
    tier: smoke
    domains: [order]
    user_inputs:
      - "看看订单"
    expectations:
      - tool: order_query
    {extra}
"""


# ─────────────────────────────────────────────────────────────────────────────
# 夹具基础设施
# ─────────────────────────────────────────────────────────────────────────────
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def mk_repo(tmp: Path, files: dict[str, str], *, commit: bool = True) -> Path:
    """临时 git 仓库（分支 `main`，一次 base 提交）——夹具的**注入面**。"""
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    for rel, content in files.items():
        _write(repo, rel, content)
    if commit:
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
    return repo


# ⚠️ 夹具里**不能出现字面量 `路径.ext:数字`**：dev-flow §18.1 说明这种写法会被
# **模式扫描**误判成「残留引用」——本文件自己就是被扫的面（`tests/unit_ci_workflows/**`）。
# 故把夹具里的文件名拼出来：源码不含该模式，语义不变。
_PY = "order_query" + ".py"
_NOWHERE = "nowhere" + ".py"


def run(repo: Path, *args: str, base: str = "main") -> tuple[int, str, dict]:
    """跑审计；返回 (exit, stdout, json 报告)。报告写到仓库**外**，避免污染被测树。

    `base` 必须与被测仓库的分支名对齐：夹具仓库是 `main`，真仓库是 `origin/main`
    （用错基准会让"行越界"之类的判定整体偏移 —— 本测试自己踩过一次）。
    """
    out_json = Path(tempfile.mkdtemp()) / "drift.json"
    p = subprocess.run(
        [sys.executable, str(DRIFT), "--repo", str(repo), "--base", base,
         "--json", str(out_json), "--offline"] + list(args),
        capture_output=True, text=True, timeout=300)
    rep = json.loads(out_json.read_text(encoding="utf-8")) if out_json.is_file() else {}
    return p.returncode, p.stdout + p.stderr, rep


def check_of(rep: dict, cid: str) -> dict:
    for c in rep.get("checks", []):
        if c["id"] == cid:
            return c
    raise AssertionError(f"报告里没有判据 {cid}")


# ─────────────────────────────────────────────────────────────────────────────
# 退化守卫：判据集合与契约完整性
# ─────────────────────────────────────────────────────────────────────────────
def list_checks() -> dict:
    p = subprocess.run([sys.executable, str(DRIFT), "--list-checks"],
                       capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def test_judgment_set_not_empty_and_wellformed():
    """判据集合不得为空；每条必须写清判定方式与违反后的处置（契约 §1 第 4 列不许留空）。"""
    data = list_checks()
    checks = data["checks"]
    assert checks, "判据集合为空 —— 审计退化成了空跑"
    for c in checks:
        assert c["judgment"].strip(), f"{c['id']} 缺『判定方式』"
        assert c["remedy"].strip(), f"{c['id']} 缺『违反后的处置』"
        assert c["min_evaluated"] >= 1, f"{c['id']} 允许判定面为 0（空集恒真）"


def test_unimplemented_registry_is_explicit():
    """未实装项必须**如实登记**（写明缺什么），不得用恒真判断凑数。"""
    data = list_checks()
    ids = {u["id"] for u in data["unimplemented"]}
    assert {"ref-semantic-hit", "runtime-fencing", "sync-copy-landing"} <= ids
    for u in data["unimplemented"]:
        assert u["why"].strip() and u["missing"].strip(), f"{u['id']} 未写清为什么/缺什么"


# 每条判据的**红证**：夹具名 -> 判据 id。新增判据不补夹具 ⇒ 本表对不上 ⇒ 红。
REDPROOF: dict[str, str] = {
    "skill-anchor": "test_skill_anchor_red_when_live_anchor_behind",
    "preset-monotonic": "test_preset_version_downgrade_red_upgrade_green",
    "sync-copy": "test_sync_copy_version_stamp_mismatch_red",
    "generated-freshness": "test_generated_view_dropping_preclean_red",
    "ref-freshness": "test_stale_and_bare_line_refs_red",
    "mutable-locator": "test_mutable_locator_red_immutable_green",
    "heartbeat": "test_heartbeat_red_when_last_success_nine_days_ago",
    "regression-guard": "test_empty_cases_surface_red",
}


def test_every_check_has_redproof():
    """护栏失效 ⇒ 红：每个判据都必须有一个实测会变红的夹具。"""
    declared = {c["id"] for c in list_checks()["checks"]}
    missing = declared - set(REDPROOF)
    assert not missing, (
        f"判据 {sorted(missing)} 没有红证夹具 —— 没有红证的判据是空断言。"
        f"请在 REDPROOF 表里补上（夹具必须是注入式，不能是『断言仓库当下有该缺陷』）。")
    stale = set(REDPROOF) - declared
    assert not stale, f"REDPROOF 表里有已不存在的判据：{sorted(stale)}（销账后要删条目）"
    for cid, name in REDPROOF.items():
        assert name in globals(), f"{cid} 的红证函数 {name} 不存在"


# ─────────────────────────────────────────────────────────────────────────────
# ① 技能活锚新鲜度（I1/I4）
# ─────────────────────────────────────────────────────────────────────────────
def _anchor(tmp: Path, version: str, body: str | None = None) -> Path:
    a = tmp / "fake-anchor"
    _write(a, "skills/migao-dev-flow/SKILL.md",
           body if body is not None else SKILL_TMPL.format(version=version))
    return a


def _anchor_repo(tmp: Path, skill_version: str = "1.28.0"):
    return mk_repo(tmp, {SKILL_REL: SKILL_TMPL.format(version=skill_version)})


def test_skill_anchor_red_when_live_anchor_behind(tmp_path):
    """红证：活锚停在旧版本（实证形态 v1.23 vs 仓库 v1.27）⇒ 必红，且不可被基线放行。"""
    repo = _anchor_repo(tmp_path, "1.28.0")
    anchor = _anchor(tmp_path, "1.23.0")
    rc, out, rep = run(repo, "--live-anchor", str(anchor), "--check")
    chk = check_of(rep, "skill-anchor")
    assert chk["status"] == "new-drift", out
    assert rc == 1
    assert any("1.23.0" in f["detail"] and "落后" in f["detail"] for f in chk["env_findings"]), out
    # 环境漂移永不进基线 ⇒ 即使重生成基线，仍必红（不是"豁免表"能吃掉的东西）
    run(repo, "--live-anchor", str(anchor), "--regen-baseline", "--reason", "x")
    rc2, out2, rep2 = run(repo, "--live-anchor", str(anchor), "--check", "--only", "skill-anchor")
    assert rc2 == 1 and check_of(rep2, "skill-anchor")["status"] == "new-drift", out2


def test_skill_anchor_green_when_in_sync(tmp_path):
    """修后绿：活锚与仓库同版本同内容 ⇒ 不报。"""
    repo = _anchor_repo(tmp_path, "1.28.0")
    anchor = _anchor(tmp_path, "1.28.0")
    rc, out, rep = run(repo, "--live-anchor", str(anchor), "--check", "--only", "skill-anchor")
    assert rc == 0 and check_of(rep, "skill-anchor")["status"] == "ok", out


def test_skill_anchor_same_version_but_content_forked_red(tmp_path):
    """同版本号不同内容也是漂移（只看版本号会漏 —— §18.2 的"内容级比对"）。"""
    repo = _anchor_repo(tmp_path, "1.28.0")
    anchor = _anchor(tmp_path, "1.28.0", body=SKILL_TMPL.format(version="1.28.0") + "\n额外一行\n")
    rc, out, rep = run(repo, "--live-anchor", str(anchor), "--check", "--only", "skill-anchor")
    assert rc == 1, out
    assert any("逐字节不同" in f["detail"]
               for f in check_of(rep, "skill-anchor")["env_findings"]), out


def _clone(repo: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone", "-q", str(repo), str(dest)], check=True,
                   capture_output=True, text=True)
    return dest


def test_skill_anchor_commit_lag_judged_by_content_not_count(tmp_path):
    """红证：活锚落后且**落后区间动过 `.agent-presets/migao/**`** ⇒ 红。

    反面（同样落后 1 个提交，但落后区间只动 `docs/`）⇒ **绿** ——
    判据是**内容级**的，不是提交数（否则每次主干合并都会把活锚判红 = 噪音红）。
    """
    repo = mk_repo(tmp_path, {
        SKILL_REL: SKILL_TMPL.format(version="1.28.0"),
        ".agent-presets/migao/README.md": "r1\n",
        "docs/other.md": "d1\n",
    })
    anchor_old = _clone(repo, tmp_path / "anchor-old")          # HEAD = 提交 A
    _write(repo, ".agent-presets/migao/README.md", "r2\n")      # 提交 B：动了预设
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "B: preset 改动")

    rc, out, rep = run(repo, "--check", "--only", "skill-anchor",
                       "--live-anchor", str(anchor_old / ".agent-presets" / "migao"))
    chk = check_of(rep, "skill-anchor")
    assert rc == 1, out
    assert any("落后区间**动过**" in f["detail"] for f in chk["env_findings"]), out

    anchor_new = _clone(repo, tmp_path / "anchor-new")          # HEAD = 提交 B
    _write(repo, "docs/other.md", "d2\n")                      # 提交 C：只动 docs
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "C: 只动 docs")
    rc2, out2, rep2 = run(repo, "--check", "--only", "skill-anchor",
                          "--live-anchor", str(anchor_new / ".agent-presets" / "migao"))
    chk2 = check_of(rep2, "skill-anchor")
    assert rc2 == 0 and chk2["status"] == "ok", out2
    assert any("未改" in n and "仍是最新" in n for n in chk2["notes"]), out2


def test_skill_anchor_missing_is_unknown_not_pass(tmp_path):
    """活锚未安装 ⇒ 显式『未知』，**不得**当成通过（"未安装"与"没漂移"是两件事）。"""
    repo = _anchor_repo(tmp_path)
    rc, out, rep = run(repo, "--live-anchor", str(tmp_path / "nope"), "--check",
                       "--only", "skill-anchor")
    chk = check_of(rep, "skill-anchor")
    assert chk["status"] == "unknown", out
    assert any("未安装" in n for n in chk["notes"]), out


# ─────────────────────────────────────────────────────────────────────────────
# ② 预设版本单调性（I1）—— 不得把技能版本降级
# ─────────────────────────────────────────────────────────────────────────────
def test_preset_version_downgrade_red_upgrade_green(tmp_path):
    """红证：`1.28.0 → 1.27.0` 必红；**正常升级 `1.28.0 → 1.29.0` 必须绿**（不许误伤升级）。"""
    repo = _anchor_repo(tmp_path, "1.28.0")
    _write(repo, SKILL_REL, SKILL_TMPL.format(version="1.27.0"))       # worktree 降到旧值
    rc, out, rep = run(repo, "--check", "--only", "preset-monotonic")
    chk = check_of(rep, "preset-monotonic")
    assert chk["status"] == "new-drift" and rc == 1, out
    assert any("1.28.0" in f["detail"] and "1.27.0" in f["detail"] for f in chk["env_findings"]), out
    # 重生成基线也不能放行（硬漂移）
    run(repo, "--regen-baseline", "--reason", "x")
    rc2, out2, _ = run(repo, "--check", "--only", "preset-monotonic")
    assert rc2 == 1, out2

    _write(repo, SKILL_REL, SKILL_TMPL.format(version="1.29.0"))       # 正常升级
    rc3, out3, rep3 = run(repo, "--check", "--only", "preset-monotonic")
    assert rc3 == 0 and check_of(rep3, "preset-monotonic")["status"] == "ok", out3


def test_preset_same_version_different_content_is_fork_red(tmp_path):
    """同版本不同内容 = 分叉（不是升级），必须报。"""
    repo = _anchor_repo(tmp_path, "1.28.0")
    _write(repo, SKILL_REL, SKILL_TMPL.format(version="1.28.0") + "\n分叉出去的一行\n")
    rc, out, rep = run(repo, "--check", "--only", "preset-monotonic")
    assert rc == 1, out
    assert any("内容已分叉" in f["detail"]
               for f in check_of(rep, "preset-monotonic")["env_findings"]), out


# ─────────────────────────────────────────────────────────────────────────────
# ③ 同步副本 diff（I1）
# ─────────────────────────────────────────────────────────────────────────────
def test_sync_copy_version_stamp_mismatch_red(tmp_path):
    """红证：副本自报 v1.3 / 权威源 1.28.0（**真实红例**，锚定 origin/main@d0724892）⇒ 必红。"""
    repo = mk_repo(tmp_path, {
        SKILL_REL: SKILL_TMPL.format(version="1.28.0"),
        COPY_REL: COPY_TMPL.format(version="1.3"),
    })
    rc, out, rep = run(repo, "--check", "--only", "sync-copy")
    chk = check_of(rep, "sync-copy")
    assert chk["status"] == "new-drift" and rc == 1, out
    assert any("v1.3" in f["detail"] and "1.28.0" in f["detail"] for f in chk["findings"]), out


def test_sync_copy_green_when_stamp_matches(tmp_path):
    """修后绿：版本戳一致 ⇒ 不报。"""
    repo = mk_repo(tmp_path, {
        SKILL_REL: SKILL_TMPL.format(version="1.28.0"),
        COPY_REL: COPY_TMPL.format(version="1.28"),
    })
    rc, out, rep = run(repo, "--check", "--only", "sync-copy")
    assert rc == 0 and check_of(rep, "sync-copy")["status"] == "ok", out


def test_sync_copy_dangling_declared_source_red(tmp_path):
    """副本自称的权威源不存在 ⇒ 悬空（"同步副本"这个 claim 本身要能被证伪）。"""
    copy = COPY_TMPL.format(version="1.28").replace(
        ".agent-presets/migao/skills/migao-dev-flow/SKILL.md", "docs/nowhere.md")
    repo = mk_repo(tmp_path, {SKILL_REL: SKILL_TMPL.format(version="1.28.0"),
                              COPY_REL: copy})
    rc, out, rep = run(repo, "--check", "--only", "sync-copy")
    assert rc == 1 and any("权威源不存在" in f["detail"]
                           for f in check_of(rep, "sync-copy")["findings"]), out


# ─────────────────────────────────────────────────────────────────────────────
# ④ 生成物新鲜度（I1）
# ─────────────────────────────────────────────────────────────────────────────
def test_generated_view_dropping_preclean_red(tmp_path):
    """红证：**渲染器静默丢字段**（`pre_clean` 曾不被 `render_cases.py` 渲染 ⇒ 账本盲区）。

    夹具：渲染器被换成"只写一行、不含 pre_clean"的桩，而用例库里有 `pre_clean` ⇒ 必红。
    """
    stub = "import sys,pathlib\np=pathlib.Path(sys.argv[sys.argv.index('--out-eval')+1]);p.write_text('X=1\\n')\n" \
           "m=pathlib.Path(sys.argv[sys.argv.index('--out-md')+1]);m.write_text('M\\n')\n"
    repo = mk_repo(tmp_path, {
        ".github/render_cases.py": stub,
        ".github/cases/order.yml": CASE_TMPL.format(extra='pre_clean:\n      - type: product_dedupe\n        product_keyword: "遮光窗帘"'),
        "tests/agent_eval/eval_cases.py": "X=1\n",
        "docs/testing/mibao-verification-cases.md": "M\n",
    })
    rc, out, rep = run(repo, "--check", "--only", "generated-freshness")
    assert rc == 1, out
    assert any("pre_clean" in f["detail"]
               for f in check_of(rep, "generated-freshness")["findings"]), out


def test_generated_view_diverged_red(tmp_path):
    """红证：改了 `.github/cases/` 却没提交生成物 ⇒ 重渲染 diff ≠ 0 ⇒ 必红。"""
    stub = "import sys,pathlib\np=pathlib.Path(sys.argv[sys.argv.index('--out-eval')+1]);p.write_text('X=1\\n')\n" \
           "m=pathlib.Path(sys.argv[sys.argv.index('--out-md')+1]);m.write_text('M\\n')\n"
    repo = mk_repo(tmp_path, {
        ".github/render_cases.py": stub,
        ".github/cases/order.yml": CASE_TMPL.format(extra=""),
        "tests/agent_eval/eval_cases.py": "X=1\n",
        "docs/testing/mibao-verification-cases.md": "M\n",
    })
    rc, out, rep = run(repo, "--check", "--only", "generated-freshness")
    assert rc == 0, out  # 与桩输出一致 ⇒ 新鲜
    _write(repo, "tests/agent_eval/eval_cases.py", "X=2\n")   # 手改了生成物
    rc2, out2, rep2 = run(repo, "--check", "--only", "generated-freshness")
    assert rc2 == 1, out2
    assert any("重渲染结果不一致" in f["detail"]
               for f in check_of(rep2, "generated-freshness")["findings"]), out2


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ 引用新鲜度（I1）
# ─────────────────────────────────────────────────────────────────────────────
def test_stale_and_bare_line_refs_red(tmp_path):
    """红证三族：**越界**（`path:NNN` 超行数）/ **悬空**（路径不存在）/ **裸行号**。

    越界 = 可证伪的失效引用（`#3787` 第 5 条的形态）；裸行号 = dev-flow §18.1 明令禁止的写法。
    """
    repo = mk_repo(tmp_path, {
        "docs/wiki/note.md": (
            f"引用甲：`{_PY}:9999`（越界）\n"
            f"引用乙：`{_NOWHERE}:3`（悬空）\n"
            f"引用丙：`{_PY}:2`（行内、无 @sha 限定）\n"
            f"引用丁：`{_PY}` **第 1 行**（带文件的裸行号，无 @sha）\n"
            f"引用戊：`{_PY}` **第 1 行**，`@d0724892`（限定值 ⇒ 合规）\n"
        ),
        "order_query.py": "l1\nl2\nl3\n",
    })
    rc, out, rep = run(repo, "--check", "--only", "ref-freshness", "--stale-scope", "none")
    chk = check_of(rep, "ref-freshness")
    details = " || ".join(f["detail"] for f in chk["findings"])
    assert rc == 1, out
    assert "行越界" in details, details
    assert "没有这个文件" in details, details
    assert "无 `@<sha>` 限定" in details, details
    assert "裸行号" in details, details
    # 带 @sha 限定的那条**不得**被判违规（否则是误红）
    assert "引用戊" not in details, details


def test_ref_freshness_allows_sha_qualified(tmp_path):
    """修后绿：`第 N 行` + `@<sha>` 是契约允许的写法。"""
    repo = mk_repo(tmp_path, {
        "docs/wiki/note.md": f"引用：`{_PY}` **第 2 行**，`@d0724892`。\n",
        "order_query.py": "l1\nl2\n",
    })
    rc, out, rep = run(repo, "--check", "--only", "ref-freshness", "--stale-scope", "none")
    assert rc == 0 and check_of(rep, "ref-freshness")["status"] == "ok", out


# ─────────────────────────────────────────────────────────────────────────────
# ⑥ 可变引用计数（I2）
# ─────────────────────────────────────────────────────────────────────────────
def test_mutable_locator_red_immutable_green(tmp_path):
    """红证：`customer_index: 0`（位置类定位，实证 CU-003）/ `product_keyword`（名字类）。

    **反面**：用 `order_no` 定位 ⇒ 绿（不可变标识）；用户输入里的名字/序号 ⇒ **不计**。
    """
    bad = mk_repo(tmp_path / "bad", {
        ".github/cases/order.yml": CASE_TMPL.format(
            extra='pre_clean:\n      - type: customer_tag_remove\n        customer_index: 0'),
    })
    rc, out, rep = run(bad, "--check", "--only", "mutable-locator")
    chk = check_of(rep, "mutable-locator")
    assert rc == 1 and any("customer_index" in f["detail"] for f in chk["findings"]), out

    good = mk_repo(tmp_path / "good", {
        ".github/cases/order.yml": CASE_TMPL.format(
            extra='pre_clean:\n      - type: order_reset\n        order_no: "EVAL-MB-ORD-0002"'),
    })
    rc2, out2, rep2 = run(good, "--check", "--only", "mutable-locator")
    assert rc2 == 0 and check_of(rep2, "mutable-locator")["status"] == "ok", out2


def test_user_input_names_are_not_counted(tmp_path):
    """口径不写清就会大面积误伤：`user_inputs` 的**字符串**名字/序号是合理表达，不计。"""
    repo = mk_repo(tmp_path, {
        ".github/cases/order.yml": CASE_TMPL.format(extra="").replace(
            '- "看看订单"', '- "把第一个订单的遮光窗帘改成 2 件"'),
    })
    rc, out, rep = run(repo, "--check", "--only", "mutable-locator")
    assert rc == 0, out
    assert check_of(rep, "mutable-locator")["findings"] == [], out


def test_auto_select_turn_directive_is_counted(tmp_path):
    """`user_inputs` 里的 **dict 项** `auto_select: true` 是结构化选择器 ⇒ 计（序数类定位）。"""
    repo = mk_repo(tmp_path, {
        ".github/cases/order.yml": CASE_TMPL.format(extra="").replace(
            '- "看看订单"', '- "看看订单"\n      - auto_select: true'),
    })
    rc, out, rep = run(repo, "--check", "--only", "mutable-locator")
    assert rc == 1, out
    assert any("auto_select" in f["detail"]
               for f in check_of(rep, "mutable-locator")["findings"]), out


# ─────────────────────────────────────────────────────────────────────────────
# ⑦ 无心跳的调度任务（I4）
# ─────────────────────────────────────────────────────────────────────────────
def _wf(name: str, cron: str | None, paused: bool = False) -> str:
    if paused:
        on = "on:\n  # schedule:\n  #   - cron: '0 18 * * *'\n  workflow_dispatch:\n"
    else:
        on = f"on:\n  schedule:\n    - cron: '{cron}'\n"
    return f"name: {name}\n{on}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n"


NOW = "2026-09-15T06:00:00Z"  # 距 09-06T02:00 的成功恰 9 天


def test_heartbeat_red_when_last_success_nine_days_ago(tmp_path):
    """红证：假 workflow 记录里"最后成功在 9 天前"（周期 1 天）⇒ 必红；被注释停用也必红。"""
    repo = mk_repo(tmp_path, {
        ".github/workflows/ghost.yml": _wf("Ghost", "0 2 * * *"),
        ".github/workflows/paused.yml": _wf("Paused", None, paused=True),
    })
    fixture = tmp_path / "gh.json"
    fixture.write_text(json.dumps({
        # 每天 02:00 跑，最后成功却在 9 天前 ⇒ 超 3 天阈值
        "ghost.yml": [{"status": "completed", "conclusion": "failure",
                       "createdAt": "2026-09-14T02:00:00Z"},
                      {"status": "completed", "conclusion": "success",
                       "createdAt": "2026-09-06T02:00:00Z"}],
    }), encoding="utf-8")
    rc, out, rep = run(repo, "--check", "--only", "heartbeat", "--stale-scope", "none",
                       "--gh-fixture", str(fixture), "--now", NOW)
    chk = check_of(rep, "heartbeat")
    details = " || ".join(f["detail"] for f in chk["findings"])
    assert rc == 1, out
    assert "ghost.yml" in details and "最近成功在 9 天前" in details, details
    assert "paused.yml" in details and "注释停用" in details, details


def test_heartbeat_never_succeeded_is_red(tmp_path):
    """红证：**历史 0 条成功**（实证 fixture-record.yml）⇒ 必红，不是"它一直红所以忽略"。"""
    repo = mk_repo(tmp_path, {".github/workflows/monthly.yml": _wf("Monthly", "0 19 1 * *")})
    fixture = tmp_path / "gh.json"
    fixture.write_text(json.dumps({"monthly.yml": [
        {"status": "completed", "conclusion": "failure", "createdAt": "2026-09-01T21:40:35Z"}]}),
        encoding="utf-8")
    rc, out, rep = run(repo, "--check", "--only", "heartbeat", "--stale-scope", "none",
                       "--gh-fixture", str(fixture), "--now", NOW)
    details = " ".join(f["detail"] for f in check_of(rep, "heartbeat")["findings"])
    assert rc == 1 and "零成功" in details, out


def test_heartbeat_new_workflow_is_pending_not_never_succeeded(tmp_path):
    """红证反面：本 PR **新增**的 workflow 在合并前不纳入心跳判定。

    实测形态（本 PR 自己的第一次 CI run，#3858 run 34913526579）：新 workflow 的**自己的
    in_progress run** 会被 `gh run list --workflow=<file>` 看到 ⇒ 若照常判定就会报
    "近 1 次运行零成功" = **自指假红**，把自己挡在门外。
    """
    repo = mk_repo(tmp_path, {".github/workflows/old.yml": _wf("Old", "0 2 * * *")})
    _write(repo, ".github/workflows/brand-new.yml", _wf("BrandNew", "0 3 * * *"))
    fixture = tmp_path / "gh.json"
    fixture.write_text(json.dumps({
        "old.yml": [{"status": "completed", "conclusion": "success",
                     "createdAt": "2026-09-15T02:00:00Z"}],
        "brand-new.yml": [{"status": "in_progress", "conclusion": "",
                           "createdAt": "2026-09-15T03:00:00Z"}],
    }), encoding="utf-8")
    rc, out, rep = run(repo, "--check", "--only", "heartbeat",
                       "--gh-fixture", str(fixture), "--now", NOW)
    chk = check_of(rep, "heartbeat")
    assert rc == 0, out
    assert any("pending-merge" in n for n in chk["notes"]), out
    assert not any("brand-new.yml" in f["detail"] for f in chk["findings"]), out


def test_heartbeat_offline_is_unknown_not_pass(tmp_path):
    """离线 ⇒ **未知**，不假装通过（"没网"与"没漂移"是两件事）。"""
    repo = mk_repo(tmp_path, {".github/workflows/daily.yml": _wf("Daily", "0 2 * * *")})
    rc, out, rep = run(repo, "--check", "--only", "heartbeat")
    chk = check_of(rep, "heartbeat")
    assert chk["status"] == "unknown", out
    assert any("未知" in n for n in chk["notes"]), out
    assert rc == 0, out
    # 定时审计用 --fail-on-unknown ⇒ 未知要红（防"网络静默"变成假绿）
    rc2, out2, _ = run(repo, "--check", "--only", "heartbeat", "--fail-on-unknown")
    assert rc2 == 1, out2


# ─────────────────────────────────────────────────────────────────────────────
# ⑧ 退化守卫 + 基线策略（meta）
# ─────────────────────────────────────────────────────────────────────────────
def test_empty_cases_surface_red(tmp_path):
    """红证：判据面为 0（用例库空）⇒ 红 —— 空集会让护栏恒真（空断言）。"""
    repo = mk_repo(tmp_path, {".github/cases/keep.yml": "schema: '1'\ndomain: x\ncases: []\n"})
    rc, out, rep = run(repo, "--check", "--only", "mutable-locator")
    chk = check_of(rep, "mutable-locator")
    assert chk["status"] == "error", out
    assert "判据面为空" in chk["error"], out
    assert rc == 1, out


def test_baseline_only_shrinks_new_drift_blocks(tmp_path):
    """基线只许缩短：新增漂移 ⇒ 非零退出（fail-closed）；重生成后放行。"""
    repo = mk_repo(tmp_path, {
        SKILL_REL: SKILL_TMPL.format(version="1.28.0"),
        COPY_REL: COPY_TMPL.format(version="1.3"),
    })
    only = ("--only", "sync-copy,ref-freshness")
    rc1, out1, _ = run(repo, "--check", *only)
    assert rc1 == 1, out1
    run(repo, "--regen-baseline", "--reason", "首跑基线", *only)
    rc2, out2, rep2 = run(repo, "--check", *only)
    assert rc2 == 0 and rep2["summary"]["known_drift"] > 0, out2
    # 新增一条漂移 ⇒ 又红
    _write(repo, COPY_REL, COPY_TMPL.format(version="1.3") + f"\n引用：`{_NOWHERE}:3`\n")
    rc3, out3, _ = run(repo, "--check", *only)
    assert rc3 == 1, out3


def test_new_drift_out_of_pr_scope_warns_not_blocks(tmp_path):
    """面外新增漂移**不阻塞本 PR**（假红），但 `--strict-stale`（定时腿）下红。

    实证形态：本 PR 的 CI 被**并行包刚合并进 main** 的 `docs/testing/demo-readiness.md`
    里 3 处裸行号判红（run 34914147884）—— 报错指向错误的对象，且挡住了无关的 PR。
    """
    repo = mk_repo(tmp_path, {
        SKILL_REL: SKILL_TMPL.format(version="1.28.0"),
        COPY_REL: COPY_TMPL.format(version="1.3"),
    })
    run(repo, "--regen-baseline", "--reason", "首跑基线", "--only", "ref-freshness")
    # 面外：漂移来自**基线生成之后**才落到 main 的另一个文件（并行包合并的形态）
    _write(repo, "docs/testing/other.md", f"引用：`{_NOWHERE}:3`\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "另一包合并：带来一处漂移")
    rc, out, rep = run(repo, "--check", "--only", "ref-freshness")
    assert rc == 0, out
    assert rep["summary"]["new_drift_out_of_scope"] >= 1, out
    rc2, out2, _ = run(repo, "--check", "--only", "ref-freshness", "--strict-stale")
    assert rc2 == 1, out2
    # 面内：同一个漂移若出在本 PR 改动的文件里 ⇒ 必红
    _write(repo, COPY_REL, COPY_TMPL.format(version="1.3") + f"\n引用：`{_NOWHERE}:4`\n")
    rc3, out3, rep3 = run(repo, "--check", "--only", "ref-freshness")
    assert rc3 == 1, out3
    assert rep3["summary"]["new_drift"] >= 1, out3


def test_regen_baseline_requires_reason(tmp_path):
    """重生成基线必须写理由（PR 里要说明为什么）—— 防"基线当成豁免表随手刷"。"""
    repo = _anchor_repo(tmp_path)
    p = subprocess.run([sys.executable, str(DRIFT), "--repo", str(repo), "--base", "main",
                        "--offline", "--regen-baseline"], capture_output=True, text=True)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "必须带 --reason" in p.stdout + p.stderr


def test_stale_baseline_entry_warn_then_strict_red(tmp_path):
    """基线陈旧项：PR 门禁**只告警**（#3846 裁定：硬阻塞会把修好的人卡在别人的文件上），
    定时审计（`--strict-stale`）下**红**。"""
    repo = mk_repo(tmp_path, {
        SKILL_REL: SKILL_TMPL.format(version="1.28.0"),
        COPY_REL: COPY_TMPL.format(version="1.3"),
        ".github/cases/order.yml": CASE_TMPL.format(
            extra='pre_clean:\n      - type: customer_tag_remove\n        customer_index: 0'),
    })
    run(repo, "--regen-baseline", "--reason", "首跑基线", "--only", "mutable-locator")
    # 修好那条可变定位（改文件 = 本次 diff 命中该文件的形态）
    _write(repo, ".github/cases/order.yml", CASE_TMPL.format(extra=""))
    rc, out, rep = run(repo, "--check", "--only", "mutable-locator")
    assert rc == 0, out
    assert check_of(rep, "mutable-locator")["stale_baseline_entry"], out
    assert rep["summary"]["stale_baseline_entry"] >= 1
    rc2, out2, _ = run(repo, "--check", "--only", "mutable-locator", "--strict-stale")
    assert rc2 == 1, out2


def test_baseline_entry_keys_have_no_line_numbers(tmp_path):
    """基线 key **不含行号**：否则改一行就换 key，"只许缩短"会退化成随机红。"""
    import re
    p = REPO_ROOT / "scripts" / "drift_audit_baseline.json"
    if not p.is_file():
        pytest.skip("本分支尚未提交基线（首次落地时由 --regen-baseline 生成）")
    data = json.loads(p.read_text(encoding="utf-8"))
    import re as _re
    bad = [k for entries in data["entries"].values() for k in entries
           if _re.search(r"\.(py|sh|yml|yaml|md|js|ts|tsx|java):\d+", k)]
    assert not bad, (
        f"基线条目 key 含 `路径:行号` 字面量：{bad[:3]} —— 两个问题："
        f"① 会被别的 `path:NNN` 模式扫描误判成悬空引用（实证：case-trust 门禁的规则 G）；"
        f"② 改一行就换 key，『只许缩短』会退化成随机红")


def test_real_repo_audit_is_green_on_current_tree():
    """本 PR 自身的自证：在当前树上 `--check` 必须绿（存量放行、无新增漂移）。

    这条同时是"审计没被自己写坏"的兜底 —— 判据崩溃（`status=error`）会让它红。
    """
    # 活锚新鲜度依赖**本机状态**（会持续漂移）⇒ 用"不存在的活锚"把它降级为『未知』，
    # 本测试只断言**仓库内**没新增漂移、判据没崩。
    # ⚠️ CI 的 `ci workflow helper unit tests` job 是**浅检出**，`origin/main` 可能不可解析
    #    ⇒ 那时"哪些 workflow 是本 PR 新增"无法判定，本测试无意义（判据自己会标注）。
    probe = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--verify",
                            "origin/main^{commit}"], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("当前检出没有 origin/main（浅检出）⇒ 本自证无判定基准，跳过")
    # 默认 `--stale-scope diff`：**本 PR 改动面**的新增漂移才阻塞 —— 这样并行包刚合并进
    # main 的漂移不会把本测试（以及任何无关 PR）判红。
    rc, out, rep = run(REPO_ROOT, "--check",
                       "--live-anchor", str(REPO_ROOT.parent / "no-such-anchor"),
                       base="origin/main")
    errs = [c["id"] for c in rep["checks"] if c["status"] == "error"]
    assert not errs, f"判据崩溃：{errs}\n{out}"
    assert rc == 0, out
