# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`.gitleaksignore` 指纹的**元守卫**（issue #6197 的承载体）。

## 治的形态（实测两次，手工动作）

验收承载体里的**测试夹具值**会被 gitleaks 默认规则的 `generic-api-key` 误报 ⇒ 按本仓既有形态
（`.gitleaksignore` 的 `<commit>:<file>:<rule>:<line>` 指纹）登记豁免。**但指纹绑定 commit SHA**：
任何 rebase / amend 都让它整体失效 ⇒ `Secret Scan (gitleaks)` 重新判红（2026-10-03 实测：
承载体 PR 两次 rebase ⇒ 两次**手工**重算 11 条指纹）。

⇒ 本文件 + `scripts/gitleaks-fingerprints.py` 把那次手工动作变成**一条命令**，并让「失效」在
CI 里**必然出声**：指纹必须①形态合法 ②指向**存在**的文件 ③不重复（否则下一次 rebase 后会
悄悄失效、只在 Secret Scan 上以「另一个 finding」的形态出现）。

⚠️ **本文件不跑真 gitleaks**（那要下载二进制、且扫全历史，属于重活）：真读数由
`Secret Scan (gitleaks)` 这条 required 腿负责；这里判的是**台账自身的卫生**（形态 / 路径 / 重复），
以及重算工具的**行为**（用 PATH 上的假 gitleaks 喂固定报告 ⇒ 纯函数级复算）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "scripts" / "gitleaks-fingerprints.py"
IGNORE = REPO_ROOT / ".gitleaksignore"
#: 与工具同口径（`<commit>:<file>:<rule>:<line>`）
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{7,64}:[^:]+:[^:]+:\d+$")
COMMENT_RE = re.compile(r"^\s*#")


def fingerprints() -> list[str]:
    out = []
    for ln in IGNORE.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s and not COMMENT_RE.match(s):
            out.append(s)
    return out


def test_ignore_entries_are_well_formed() -> None:
    """每条指纹必须是 `<commit>:<file>:<rule>:<line>` 形态（写歪了就永远匹配不上）。"""
    bad = [fp for fp in fingerprints() if not FINGERPRINT_RE.match(fp)]
    assert bad == [], f".gitleaksignore 有形态非法的条目（永远不会生效）：{bad}"


def test_tool_flags_missing_and_stale_symmetric(tmp_path) -> None:
    """🔴 工具必须**双向**判：命中里没登记的 ⇒ 应加（会判红）；登记了但没命中的 ⇒ 应删。

    ⚠️ 存量有一条历史悬空指纹（`acceptance/2026-09-25/login-rework/ua/journey2.cjs` 从未入仓，
    #5528 时代写下的）—— 本条**不判它**（那是另一条上下文），只钉「工具在**临时仓**里双向可读」。
    """
    tmp_repo = _tmp_repo(tmp_path)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True,
                          text=True, check=True).stdout.strip()
    (tmp_repo / ".gitleaksignore").write_text(
        "d" * 40 + ":acceptance/stale.json:generic-api-key:5\n", encoding="utf-8")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True,
                            text=True, check=True).stdout.strip()
    proc = _run_tool(tmp_path, [
        {"Commit": commit, "File": "acceptance/new.json", "RuleID": "generic-api-key",
         "StartLine": 7, "Secret": "x", "Match": "m"},
    ], repo=tmp_repo, base=base)
    assert proc.returncode == 1, proc.stdout
    assert "应加" in proc.stdout and "acceptance/new.json" in proc.stdout, proc.stdout
    assert "应删" in proc.stdout and "acceptance/stale.json" in proc.stdout, proc.stdout
    assert "1 处" in proc.stdout or "命中 1" in proc.stdout, proc.stdout


def test_ignore_entries_are_unique() -> None:
    """不许重复：重复条目说明有人在**追加**而不是**重算** ⇒ 下一次 rebase 后必然脏。"""
    fps = fingerprints()
    dupes = sorted({fp for fp in fps if fps.count(fp) > 1})
    assert dupes == [], f".gitleaksignore 有重复条目（该用 --apply 重算）：{dupes}"


def test_tool_is_executable() -> None:
    """重算工具必须可直接执行（它是「手工重算」的替代品）。"""
    assert TOOL.exists(), f"{TOOL} 不存在"
    assert os.access(TOOL, os.X_OK), f"{TOOL} 不可执行（chmod +x）"


def _fake_gitleaks(tmp_path: Path, findings: list[dict]) -> Path:
    """造一个假 gitleaks：把固定报告写到 `--report-path`（不下载真二进制）。"""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    exe = bin_dir / "gitleaks"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"FINDINGS = {json.dumps(findings)}\n"
        "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--report-path=')]\n"
        "assert out, 'fake gitleaks: 没收到 --report-path'\n"
        "open(out[0], 'w', encoding='utf-8').write(json.dumps(FINDINGS))\n"
        "raise SystemExit(0 if not FINDINGS else 2)\n",
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return bin_dir


def _run_tool(tmp_path: Path, findings: list[dict], *args: str,
              repo: Path | None = None, base: str = "origin/main") -> subprocess.CompletedProcess:
    """跑工具（假 gitleaks 喂固定报告）。`repo` 默认=本仓；传临时仓时必须给 `base`。"""
    repo = repo or REPO_ROOT
    bin_dir = _fake_gitleaks(tmp_path, findings)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["GITLEAKS_FP_ROOT"] = str(repo)
    return subprocess.run([sys.executable, str(TOOL), "--base", base, *args],
                          cwd=repo, env=env, capture_output=True, text=True)


def _tmp_repo(tmp_path: Path, name: str = "repo") -> Path:
    """临时 git 仓（带两次提交 ⇒ `base^..HEAD` 非空，工具能拿到真读数）。"""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for msg in ("base", "second"):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                        "-q", "--allow-empty", "-m", msg], cwd=repo, check=True)
    return repo


def test_tool_passes_when_ignore_matches_the_scan(tmp_path) -> None:
    """台账与命中一致 ⇒ exit 0，且打印闭集读数（**不是**「0 个文件」那种空集绿）。"""
    recorded = fingerprints()
    assert recorded, "台账为空 ⇒ 本判据无从谈起（本仓库现在至少有 2 条历史指纹）"
    findings = []
    for idx, fp in enumerate(recorded):
        commit, path, rule, line = fp.split(":", 3)
        findings.append({"Commit": commit, "File": path, "RuleID": rule,
                         "StartLine": int(line), "Secret": "x", "Match": f"m{idx}"})
    proc = _run_tool(tmp_path, findings)
    assert proc.returncode == 0, f"应一致（exit 0）→ rc={proc.returncode}\n{proc.stdout}{proc.stderr}"
    assert "✅ 指纹与实际命中一致" in proc.stdout, proc.stdout


def test_tool_reports_missing_fingerprints_as_red(tmp_path) -> None:
    """🔴 红证：命中里有、台账里没有（= rebase 后的形态）⇒ exit 1 **并点名那条指纹**。"""
    findings = [{"Commit": "a" * 40, "File": "acceptance/x.json", "RuleID": "generic-api-key",
                 "StartLine": 7, "Secret": "x", "Match": "m"}]
    proc = _run_tool(tmp_path, findings)
    assert proc.returncode == 1, f"应判红（exit 1）→ rc={proc.returncode}\n{proc.stdout}"
    assert ("a" * 40 + ":acceptance/x.json:generic-api-key:7") in proc.stdout, proc.stdout
    assert "--apply" in proc.stdout, "应给出可复制的重算出入口"


def test_tool_apply_rewrites_ignore_and_then_passes(tmp_path, monkeypatch) -> None:
    """`--apply` 重算并写回 ⇒ 再校验必须一致（**自愈闭环**，不是只报不修）。

    隔离说明：把仓库根的 `.gitleaksignore` 换成本测试自己的副本（`cwd` 指向临时仓），
    ⇒ **不碰仓内文件**（本文件其余判据只读）。
    """
    tmp_repo = _tmp_repo(tmp_path, "apply-repo")
    (tmp_repo / ".gitleaksignore").write_text("# 注释保留\n", encoding="utf-8")
    # `HEAD` 自己当 base（扫描范围 = `HEAD^..HEAD` = 第二次提交）—— 不能用 `HEAD~1`
    # 当 base：它在两提交的临时仓里是**根提交**，没有父提交 ⇒ 工具按设计返 3（无法判定）。
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True,
                          text=True, check=True).stdout.strip()
    base = head
    findings = [{"Commit": head, "File": "acceptance/y.json", "RuleID": "generic-api-key",
                 "StartLine": 9, "Secret": "x", "Match": "m"}]
    bin_dir = _fake_gitleaks(tmp_path, findings)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["GITLEAKS_FP_ROOT"] = str(tmp_repo)
    for args, want_rc in (([], 1), (["--apply"], 0), ([], 0)):
        proc = subprocess.run([sys.executable, str(TOOL), "--base", base, *args],
                              cwd=tmp_repo, env=env, capture_output=True, text=True)
        assert proc.returncode == want_rc, (
            f"args={args} 期望 rc={want_rc} 实得 {proc.returncode}\n{proc.stdout}{proc.stderr}"
        )
    body = (tmp_repo / ".gitleaksignore").read_text(encoding="utf-8")
    assert "# 注释保留" in body, "`--apply` 不该吃掉注释（豁免理由要留在台账里）"
    assert f"{head}:acceptance/y.json:generic-api-key:9" in body, body


def test_tool_is_tri_state_when_gitleaks_is_missing(tmp_path) -> None:
    """⛔ 无 gitleaks ⇒ **exit 3 无法判定**，绝不当 0 读（`3` 与「通过」必须分得开）。"""
    env = os.environ.copy()
    kept = []
    for d in env["PATH"].split(os.pathsep):
        if d and (Path(d) / "gitleaks").exists():
            continue                                # 摘掉带 gitleaks 的目录
        kept.append(d)
    env["PATH"] = os.pathsep.join(kept)
    assert shutil.which("git", path=env["PATH"]), "PATH 里必须仍有 git（否则报的是 git 崩溃）"
    proc = subprocess.run([sys.executable, str(TOOL)], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 3, f"应 exit 3（无法判定）→ rc={proc.returncode}\n{proc.stdout}"
    assert "无法判定" in proc.stderr, proc.stderr
