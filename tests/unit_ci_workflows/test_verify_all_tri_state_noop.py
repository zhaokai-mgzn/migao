# case_ids: MC-012
"""`verify-all.sh` 的三态判定 + 禁空跑 + 汇总口径守卫。

## 为什么需要（2026-09-15 实测，日志原文为证）

在**干净 worktree + detached HEAD == origin/main（零 diff）**上跑 `./verify-all.sh quick`：

```
✅ admin-api 单测
❌ ai-agent 单测 (exit 127)   ← 日志原文：bash: .venv/bin/python: No such file or directory
❌ admin-web vitest (exit 1)  ← 日志原文：Error: Cannot find module 'vitest/config'
✅ admin-web tsc              ← **假的**：npx 从 npm 拉了同名的错误包 `tsc`（打印
                                 "This is not the tsc command you are looking for" 后 exit 0）
✅ QA Growth Gate 预检         ← 日志原文：⚠️ 无变更或无法对比 origin/main，跳过
========== 结果: 5 通过, 2 失败 ==========
```

三重问题（本守卫逐条锁死）：

1. **零 diff 的树上跑 = 空跑**：gate 预检必然走「无变更…跳过」，其余检查对一棵与 main 完全一致的
   树没有边际信息。把它那排 ✅ 读成「验证通过」= migao-acceptance v1.3 的「空跑」（绿了但没跑）。
2. **exit 127 / MODULE_NOT_FOUND 是「环境未就绪」，不是「失败」** ⇒ 旧版记 ❌ = **假红**，
   逼人翻日志才能确认是环境问题。反向的假绿更隐蔽：`npx tsc` 在无 node_modules 时**exit 0**。
3. 结果里**看不出本次真跑了几项** ⇒ 「空跑」与「真验证」无法区分。

## 四类判定（边界必须清晰，不许混）

| 判定 | 含义 | 触发 |
|---|---|---|
| `✅ 通过` | **真跑了**且退出 0 | — |
| `⏭️ 未就绪（跳过）` | 运行环境没准备好 ⇒ **根本没跑**；附「缺什么 + 准备命令」 | `probe_ready()` 返回 1 |
| `❌ 失败` | **真跑了**且退出非 0 | — |
| `❌ 假绿（检查未生效）` | **跑了**却什么都没检查还退出 0（如 npx 拉到占位包） | 日志命中 `FAKE_PASS_SIGNATURE` |

⏭️ **绝不**表示失败；❌ 假绿**绝不**归 ✅ 或 ⏭️（它确实跑了）。

## 本守卫锁什么

- **禁空跑**：零变更集 ⇒ 不跑任何检查 + 非零退出（行为验证：真起一个零 diff 的 git 沙盒跑一遍）；
- **三态**：⏭️ 只在 `report_env()` 里、只由 `probe_ready()` 的返回 1 产生；❌ **只**留给真跑且失败；
- **`report()` 的签名是契约**：新增包装 `report_env()`，**不改** `report()` 的调用形态
  （`test_gate_uncommitted_noop.py` 场景 ⑧ 与 `test_step_exit_code_propagation.py` 都按旧形态抽它）；
- **`probe_ready` 单一实现** + 探**真正被调用的可执行文件** + 每个 key 都有声明；
- **汇总口径**：`真跑 N+M 项 / 共 R 项`；零项真跑 ⇒ `❌ 无有效检查（纯空跑）` + 非零退出。
"""
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "verify-all.sh"
_SCRIPT = SCRIPT.read_text(encoding="utf-8")

# 期望的返回码（verify-all.sh 文件头已声明为契约）
RC_OK = 0
RC_FAIL = 1
RC_USAGE = 2
RC_NO_CHANGE = 3
RC_PURE_NOOP = 4

# 需要运行环境的 env key（其余检查项不依赖运行环境，走 report() 原形态）
_ENV_KEYS = ("ai-agent", "admin-web-vitest", "admin-web-tsc", "admin-api")


def _extract(name: str) -> str:
    """从脚本里抽出 `name() { ... }` 的函数体（结束于第 0 列的 `}`）。"""
    m = re.search(rf"^{name}\(\) \{{[\s\S]*?^\}}", _SCRIPT, re.M)
    assert m, f"未能从 verify-all.sh 抽出 {name}() —— 结构变了就同步更新本守卫"
    return m.group(0)


def _summary_tail() -> str:
    """抽出脚本末尾的**汇总块**（从「汇总」标记到 EOF）—— 它含 `exit`，可直接跑。"""
    m = re.search(r"^# ── 汇总.*$", _SCRIPT, re.M)
    assert m, "verify-all.sh 里找不到汇总块标记（`# ── 汇总`）"
    return _SCRIPT[m.start():]


def _run_sh(code: str, env: dict = None):
    import os

    e = dict(os.environ)
    e.update(env or {})
    # 不启用 `set -u`：harness 里会展开可能的空数组（bash 3.2 + `-u` 对空数组报 unbound）。
    # 被测脚本自身在 `set -u` 下的安全性，由真沙盒端到端运行负责。
    return subprocess.run(["bash", "-c", code], capture_output=True, text=True, env=e)


def _fake_pass_signature() -> str:
    """脚本里声明的「假绿签名」（单一来源：harness 与断言都从这里取）。"""
    m = re.search(r'^FAKE_PASS_SIGNATURE="([^"]*)"', _SCRIPT, re.M)
    assert m, "verify-all.sh 里找不到 FAKE_PASS_SIGNATURE 声明"
    return m.group(1)


def _report_harness(root: Path, calls: str) -> str:
    """把 probe_ready()+report()+report_env() 装进最小 harness：可注入 ROOT（伪造依赖有无）。"""
    return (
        "set -uo pipefail\n"
        f"ROOT={shlex.quote(str(root))}\n"
        f"FAKE_PASS_SIGNATURE={shlex.quote(_fake_pass_signature())}\n"
        "PASS=0; FAIL=0; READY=0; declare -a FAILED; declare -a NOT_READY\n"
        + _extract("probe_ready") + "\n" + _extract("report") + "\n" + _extract("report_env") + "\n"
        + calls + "\n"
        + 'echo "COUNTERS PASS=$PASS FAIL=$FAIL READY=$READY"\n'
        + 'echo "FAILED=[${FAILED[*]:-}]"\n'
        + 'echo "NOT_READY=[${NOT_READY[*]:-}]"\n'
        + "rm -f /tmp/verify-all-*-*.log\n"
    )


def _fake_deps(root: Path, *, venv: bool, node_modules: bool, mvnw: bool = True) -> None:
    """在临时 ROOT 下伪造/隐藏各检查项依赖，用于确定性地演练两种环境。

    ⚠️ 探测的是**真正被调用的可执行文件**（`node_modules/.bin/<tool>`），故这里也照此伪造。
    """
    if venv:
        f = root / "backend" / "ai-agent-service" / ".venv" / "bin" / "python"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)
    if node_modules:
        for tool in ("vitest", "tsc"):
            f = root / "frontend" / "admin-web" / "node_modules" / ".bin" / tool
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("#!/bin/sh\nexit 0\n")
            f.chmod(0o755)
    if mvnw:
        f = root / "backend" / "admin-api" / "mvnw"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)


class TestNoopGuard:
    """零变更集 ⇒ 不跑任何检查 + 非零退出。"""

    @staticmethod
    def _sandbox(tmp_path: Path, *, change: bool) -> Path:
        """造一个真 git 沙盒：`origin/main` == 某个提交；`change=True` 时再提交一个改动。"""
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "verify-all.sh").write_text(_SCRIPT, encoding="utf-8")
        subprocess.run(["git", "init", "-q", "."], cwd=sb, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=sb, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=sb, check=True)
        subprocess.run(["git", "add", "-A"], cwd=sb, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=sb, check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=sb, check=True)
        if change:
            (sb / "changed.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=sb, check=True)
            subprocess.run(["git", "commit", "-qm", "change"], cwd=sb, check=True)
        return sb

    def test_zero_diff_tree_runs_no_check_and_exits_nonzero(self, tmp_path):
        """零 diff（干净树，HEAD == origin/main）⇒ 不执行任何检查，**不许出现 ✅**，且非零退出。"""
        sb = self._sandbox(tmp_path, change=False)
        r = subprocess.run(["bash", "verify-all.sh", "quick"], cwd=sb,
                           capture_output=True, text=True)
        assert r.returncode == RC_NO_CHANGE, (
            f"零变更集应当以 {RC_NO_CHANGE}（未执行任何检查）退出，实得 {r.returncode}：\n{r.stdout}"
        )
        assert "无变更 ⇒ 未执行任何检查" in r.stdout, (
            f"零变更集必须显式声明「未执行任何检查（这不是通过）」，实得：\n{r.stdout}"
        )
        assert "✅" not in r.stdout, (
            "零 diff 的树上**不许**出现任何 ✅ —— 那是把空跑说成通过：\n" + r.stdout
        )
        assert "❌" not in r.stdout, (
            "零 diff 也不该报 ❌（没有任何检查失败）—— 它是「未执行」不是「失败」：\n" + r.stdout
        )

    def test_noop_exit_code_distinguishes_from_failure_and_usage(self):
        """空跑的返回码必须**区别于**「有检查失败」(1) 与「用法错误」(2)。"""
        assert RC_NO_CHANGE not in (RC_OK, RC_FAIL, RC_USAGE), (
            "空跑的返回码与通过/失败/用法错误撞号 —— 调用方无法区分「没跑」与「跑了但红」"
        )

    def test_noop_guard_runs_before_any_check_is_dispatched(self):
        """静态不变式：禁空跑判定必须在**任何** `report`/`report_env` 调用之前。"""
        # 只看**调用点**（4 空格缩进）——`report_env` 内部也有 `report "$name" "$@"`，
        # 用 `^\s*` 会先命中它，断言就恒真了。
        first = re.search(r"^\s{4}report(_env)?\s+\S+\s+\"", _SCRIPT, re.M)
        assert first, "verify-all.sh 里找不到 report/report_env 调用"
        guard = _SCRIPT.index("无变更 ⇒ 未执行任何检查")
        assert guard < first.start(), (
            "禁空跑判定出现在第一个检查项调用之后 —— 空跑时检查已经被执行了"
        )

    def test_usage_error_still_exits_2(self, tmp_path):
        """行为验证：非法子命令仍是用法错误（返回码 2），没被禁空跑判定吞掉。"""
        sb = self._sandbox(tmp_path, change=True)
        r = subprocess.run(["bash", "verify-all.sh", "bogus"], cwd=sb,
                           capture_output=True, text=True)
        assert r.returncode == RC_USAGE, f"用法错误应当退出 {RC_USAGE}，实得 {r.returncode}"


class TestTriState:
    """✅ / ⏭️ / ❌ / ❌假绿 四类判定：❌ 只留给「真跑了且失败」。"""

    def test_probe_ready_is_a_single_definition(self):
        """探测必须是**单一实现**（散落各处就会出现「有的探有的不探」的漂移）。"""
        assert len(re.findall(r"^probe_ready\(\) \{", _SCRIPT, re.M)) == 1, (
            "probe_ready() 未定义或定义了多份 —— 就绪探测必须是单一实现"
        )

    def test_report_signature_is_unchanged_contract(self):
        """`report()` 的签名是契约：仍只吃 `"名字" 命令...`，env key 由 `report_env()` 承担。

        三处既有契约依赖该形态：`test_step_exit_code_propagation.py` 的静态断言、
        `test_gate_uncommitted_noop.py` 场景 ⑧ 的 `report "%s" false` harness、以及全部调用点。
        """
        body = _extract("report")
        assert 'local name="$1"; shift' in body, (
            "report() 的首个位置参数不再是 name —— 签名被改了（会白撞三处既有契约）"
        )
        assert 'local env_key="$1"' not in body, "report() 不应接收 env key（那是 report_env 的职责）"
        assert "probe_ready" not in body, "report() 里不应再探测运行环境（探测只属于 report_env）"
        assert 'report "$name" "$@"' in _extract("report_env"), (
            "report_env() 的形态变了 —— 它应当是 report() 的薄包装"
        )

    def test_only_report_env_prints_the_per_check_skipped_marker(self):
        """**逐检查项**的 ⏭️ 标记只能由 `report_env()` 打印（散落到调用点 = 可绕过探测直接标跳过）。

        脚本里另有一处 ⏭️ 属**禁空跑**的结构性提示（「无变更 ⇒ 未执行任何检查」），
        它不针对任何单个检查项，故先把它剔除再判。
        ⚠️ 只扫**代码行**（剥掉注释）—— 注释里会引用 ⏭️ 说明三态语义，那不是行为。
        """
        body = _extract("report_env")
        assert "⏭️" in body, "report_env() 里没有「未就绪」分支 —— 三态没落地"
        noop_guard = re.search(r"^# ── 禁空跑.*?(?=\ncase \"\$MODE\" in)", _SCRIPT, re.M | re.S)
        assert noop_guard, "找不到禁空跑块 —— 结构变了就同步更新本守卫"
        stripped = _SCRIPT.replace(body, "").replace(noop_guard.group(0), "")
        code_only = "\n".join(ln.split("#", 1)[0] for ln in stripped.splitlines())
        assert "⏭️" not in code_only, (
            "⏭️ 标记出现在 report_env() 与禁空跑块之外的**代码**里 —— "
            "未就绪判定被散落到调用点，会绕过 probe_ready()"
        )

    def test_every_env_key_is_declared_in_probe_ready(self):
        """每个 `report_env <key>` 的 key 必须在 `probe_ready()` 里有分支。

        未声明的 key → `probe_ready` 返回 2 → 记 ❌（脚本配置错误）。这条静态断言让该错误在
        **合并前**就暴露，而不是等到某次运行才发现某项悄悄变红。
        """
        declared = set(re.findall(r"^\s{4}([A-Za-z0-9_-]+)\)", _extract("probe_ready"), re.M))
        assert declared >= set(_ENV_KEYS), f"probe_ready() 声明的 key 缺项：{sorted(declared)}"
        used = set(re.findall(r"^\s*report_env\s+(\S+)\s+\"", _SCRIPT, re.M))
        assert used, "解析不到任何 report_env 调用 —— 守卫的解析逻辑需要同步更新"
        undeclared = used - declared
        assert not undeclared, (
            f"这些 report_env 的 env key 未在 probe_ready() 里声明：{sorted(undeclared)}"
            "（会在运行时被记为「脚本配置错误」）"
        )

    def test_probe_checks_the_real_executables(self):
        """探测项必须覆盖**实测踩到**的缺项，且 admin-web 探**真正被调用的可执行文件**。

        只探 `node_modules` 目录不够：目录在、工具不在时 `npx` 会去 npm 拉**同名包**，
        `npx tsc` 尤其会拉到占位包 `tsc` 并 **exit 0** ⇒ 假绿。探 `.bin/<tool>` 才能结构上杜绝。
        """
        probe = _extract("probe_ready")
        for needle in ("backend/ai-agent-service/.venv/bin/python",
                       "frontend/admin-web/node_modules/.bin/vitest",
                       "frontend/admin-web/node_modules/.bin/tsc"):
            assert needle in probe, f"probe_ready() 未探测实测缺项 / 真实可执行文件：{needle}"

    @pytest.mark.parametrize("key", _ENV_KEYS)
    def test_missing_dependency_is_skipped_not_failed(self, tmp_path, key):
        """依赖缺失 ⇒ ⏭️（既不是通过也不是失败），**不能**记 ❌。"""
        root = tmp_path / "root"
        # 三类依赖全部隐藏（含 mvnw）：否则 admin-api 会因为本机有 java 而被判为就绪
        _fake_deps(root, venv=False, node_modules=False, mvnw=False)
        r = _run_sh(_report_harness(root, f'report_env {key} "某检查" true'))
        assert "⏭️" in r.stdout, f"{key} 缺依赖时未标记为未就绪：\n{r.stdout}"
        assert "❌" not in r.stdout, f"{key} 缺依赖时被记成 ❌（假红）：\n{r.stdout}"
        assert "✅" not in r.stdout, f"{key} 缺依赖时被记成 ✅（假绿）：\n{r.stdout}"
        assert "COUNTERS PASS=0 FAIL=0 READY=1" in r.stdout, (
            f"未就绪没有计入 READY（会污染「真跑了几项」的口径）：\n{r.stdout}"
        )

    def test_node_modules_without_tsc_is_still_not_ready(self, tmp_path):
        """node_modules 在、但 `.bin/tsc` 不在 ⇒ 仍是 ⏭️。

        这是「只看目录不够」的形态：目录存在时**旧探测**会放行 → `npx tsc` 拉到占位包 → **假绿 ✅**。
        """
        root = tmp_path / "root"
        _fake_deps(root, venv=False, node_modules=False)
        (root / "frontend" / "admin-web" / "node_modules").mkdir(parents=True, exist_ok=True)
        r = _run_sh(_report_harness(root, 'report_env admin-web-tsc "admin-web tsc" true'))
        assert "⏭️" in r.stdout and "✅" not in r.stdout, (
            "只有 node_modules 目录（无 .bin/tsc）时被放行 —— 会退化成 npx 拉占位包的真假绿：\n"
            + r.stdout
        )

    def test_missing_tsc_prevents_the_fake_green(self, tmp_path):
        """回归锁定：工具缺失时 `admin-web tsc` **必须**是 ⏭️ 而非 ✅。

        实测（2026-09-14，日志原文）：无 node_modules 时 `npx tsc --noEmit` 会从 npm 拉**同名占位包**
        `tsc`，打印 "This is not the tsc command you are looking for" 后 **exit 0** ⇒ 旧版打 ✅ 而
        **什么都没检查**。红证要求「能证明：若不探测就会 ✅」—— 下一条用同一签名直接证明。
        """
        root = tmp_path / "root"
        _fake_deps(root, venv=False, node_modules=False)
        r = _run_sh(_report_harness(root, 'report_env admin-web-tsc "admin-web tsc" true'))
        assert "✅" not in r.stdout, (
            "无 node_modules 时 admin-web tsc 被记为 ✅ —— 这就是那条假绿（npx 拉到错误包 exit 0）：\n"
            + r.stdout
        )
        assert "⏭️" in r.stdout, r.stdout

    def test_fake_green_signature_is_failure_not_pass(self, tmp_path):
        """**第三类失败形态**：跑了（exit 0）但工具没生效 ⇒ `❌ 假绿（检查未生效）`。

        红证（即「若不探测/不判据就会 ✅」的证明）：同一个命令**退出 0**、日志里带占位包签名 ——
        没有这条判据时它会被记 ✅；有了判据必须记 ❌，且**绝不**能落进 ✅ 或 ⏭️。
        """
        root = tmp_path / "root"
        _fake_deps(root, venv=True, node_modules=True)
        sig = _fake_pass_signature()
        assert "'" not in sig, f"签名含单引号，harness 需换引法：{sig!r}"
        calls = (
            'report_env admin-web-tsc "admin-web tsc" '
            f'bash -c "echo {sig}; exit 0"'
        )
        r = _run_sh(_report_harness(root, calls))
        assert "❌" in r.stdout and "假绿（检查未生效）" in r.stdout, (
            f"退出 0 的假绿未被归入 ❌：\n{r.stdout}"
        )
        assert "✅" not in r.stdout, f"假绿被记成 ✅：\n{r.stdout}"
        assert "⏭️" not in r.stdout, f"假绿被记成 ⏭️（它**跑了**，不是「未就绪」）：\n{r.stdout}"
        assert "COUNTERS PASS=0 FAIL=1 READY=0" in r.stdout, r.stdout

    def test_ready_environment_reruns_and_can_pass(self, tmp_path):
        """反向验证：依赖齐全时，同一项必须**真的跑**并给出 ✅（探测没把一切都吞掉）。"""
        root = tmp_path / "root"
        _fake_deps(root, venv=True, node_modules=True)
        r = _run_sh(_report_harness(root, 'report_env admin-web-tsc "某检查" true'))
        assert "✅" in r.stdout, f"依赖齐全却未被判定为就绪：\n{r.stdout}"
        assert "COUNTERS PASS=1 FAIL=0 READY=0" in r.stdout, r.stdout

    def test_real_failure_is_still_a_failure(self, tmp_path):
        """**红线**：依赖齐全 + 命令返回非 0 ⇒ 必须 ❌（不许被改成 ⏭️ 来变绿）。"""
        root = tmp_path / "root"
        _fake_deps(root, venv=True, node_modules=True)
        r = _run_sh(_report_harness(root, 'report_env admin-web-tsc "某检查" false'))
        assert "❌" in r.stdout, f"真跑的失败被吞掉了（把红说成灰）：\n{r.stdout}"
        assert "⏭️" not in r.stdout, f"真跑的失败被标成「未就绪」：\n{r.stdout}"
        assert "COUNTERS PASS=0 FAIL=1 READY=0" in r.stdout, r.stdout

    def test_env_free_check_failure_is_a_failure(self, tmp_path):
        """不依赖运行环境的检查（`report` 原形态）失败同样必须是 ❌。"""
        root = tmp_path / "root"
        _fake_deps(root, venv=False, node_modules=False)
        r = _run_sh(_report_harness(root, 'report "环境无关检查" false'))
        assert "❌" in r.stdout and "COUNTERS PASS=0 FAIL=1 READY=0" in r.stdout, r.stdout

    def test_undeclared_env_key_is_not_silently_skipped(self, tmp_path):
        """未声明的 key = 脚本配置错误 ⇒ ❌（**不能**静默变成 ⏭️ 跳过）。"""
        root = tmp_path / "root"
        _fake_deps(root, venv=False, node_modules=False)
        r = _run_sh(_report_harness(root, 'report_env bogus-key "某检查" true'))
        assert "❌" in r.stdout, f"未声明的 env key 被静默放行了：\n{r.stdout}"
        assert "⏭️" not in r.stdout, r.stdout

    def test_no_bare_var_immediately_followed_by_non_ascii(self):
        r"""bash 3.2 陷阱：`$VAR` 后**紧跟非 ASCII 字节**会被并进变量名 → 运行时崩溃。

        macOS 自带 `/bin/bash` 是 **3.2**（本仓库开发机就是），而 verify-all.sh 里满是中文输出：
            echo "… $READY_MISSING（…"   →  变量名被解析成 `READY_MISSING\xef` → `unbound variable`
        实测（2026-09-14）：本文件兄弟用例执行 `report_env <未声明 key>` 时正是被这一行打崩
        （`bash: line 61: READY_MISSING\xef: unbound variable`）—— 静态看不出来，得真跑才炸。
        修法：后跟非 ASCII 的变量一律写 `${VAR}`。
        """
        offenders = []
        for i, line in enumerate(_SCRIPT.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            # 只匹配**裸** `$VAR`（`$(...)` 与 `${VAR}` 都安全；`${VAR}` 正是修法）
            for m in re.finditer(r"\$(?!\{|\()([A-Za-z_][A-Za-z0-9_]*)(?=[^\x00-\x7f])", line):
                offenders.append(f"  L{i}: {m.group(0)}  ←  {line.strip()[:90]}")
        assert not offenders, (
            "以下位置 `$VAR` 后紧跟非 ASCII 字节 —— bash 3.2 会把它并进变量名并报 unbound variable：\n"
            + "\n".join(offenders)
        )


class TestSummary:
    """汇总必须把「真跑了几项」摆到台面上，且零项真跑 = 纯空跑。"""

    @staticmethod
    def _run_summary(pass_n: int, fail_n: int, ready_n: int):
        code = (
            "set -uo pipefail\n"
            f"PASS={pass_n}; FAIL={fail_n}; READY={ready_n}\n"
            f"declare -a FAILED=({' '.join(f'f{i}' for i in range(fail_n))})\n"
            f"declare -a NOT_READY=({' '.join(f'r{i}' for i in range(ready_n))})\n"
            + _summary_tail()
        )
        return _run_sh(code)

    def test_summary_shows_really_executed_counts(self):
        """`真跑 N+M 项 / 共 R 项` 必须与三态计数一致（否则「空跑 vs 真验证」仍无法区分）。"""
        r = self._run_summary(pass_n=2, fail_n=1, ready_n=1)
        assert "真跑 3 项 / 共 4 项" in r.stdout, f"汇总未暴露「真跑了几项」：\n{r.stdout}"
        assert "2 通过, 1 失败, 1 未就绪" in r.stdout, r.stdout
        assert r.returncode == RC_FAIL, f"有真跑失败应当退出 {RC_FAIL}，实得 {r.returncode}"

    def test_zero_really_executed_is_pure_noop_and_nonzero(self):
        """有变更但零项真跑 ⇒ `❌ 无有效检查（纯空跑）` + 非零退出（不许当通过）。"""
        r = self._run_summary(pass_n=0, fail_n=0, ready_n=3)
        assert "无有效检查（纯空跑）" in r.stdout, r.stdout
        assert r.returncode == RC_PURE_NOOP, (
            f"纯空跑应当以 {RC_PURE_NOOP} 退出，实得 {r.returncode}"
        )
        assert "✅" not in r.stdout, "纯空跑不许出现 ✅"

    def test_all_passed_exits_zero(self):
        """全绿（且真有检查跑过）⇒ 0；未就绪项不阻塞通过，但会被点名（每项一行）。"""
        r = self._run_summary(pass_n=3, fail_n=0, ready_n=0)
        assert r.returncode == RC_OK, r.stdout
        r2 = self._run_summary(pass_n=3, fail_n=0, ready_n=2)
        assert r2.returncode == RC_OK, r2.stdout
        assert "未就绪（跳过）: r0" in r2.stdout and "未就绪（跳过）: r1" in r2.stdout, r2.stdout
