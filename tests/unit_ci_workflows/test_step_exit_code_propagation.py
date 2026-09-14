"""
CI workflow 步骤的退出码传播守卫（issue #3270）。

背景（2026-09-11 实证）：
`xiaobu-acceptance.yml` 的「Start local stack」步骤写成：

    docker compose ... up --wait ... 2>&1 | tail -20

bash 默认返回**管道最后一个命令**的退出码。`tail` 永远成功 → 即使 compose
因为 postgres `exited (3)` 而失败，该步骤仍报 **success**：

    step 4 "Start local stack ..." -> success      ← 假绿
    step 5 "Diagnose ..."          -> skipped      ← if: failure() 永不触发，拿不到日志
    step 7 "Run xiaobu local_runner" -> failure    ← 只剩「评测连不上」的表象

后果：真因（栈没起来）被掩盖成「评测失败」，自 2026-08-31 起 9/9 全 failure
却长期无法定位。

本测试锁定：带管道的关键步骤必须 `set -o pipefail`，且其后必须有可触发的失败诊断步骤。
"""
# case_ids: MC-012, DF-011
import re
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / ".github" / "workflows"


def _steps(workflow: str):
    d = yaml.safe_load((WORKFLOWS_DIR / workflow).read_text(encoding="utf-8")) or {}
    out = []
    for job in (d.get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def _find_step(workflow: str, name_contains: str):
    for s in _steps(workflow):
        if name_contains in (s.get("name") or ""):
            return s
    return None


def _effective_run_lines(run: str):
    """剔除 bash 注释行后的有效命令（防「注释里提到 pipefail」造成假通过）。"""
    out = []
    for line in (run or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def _sets_pipefail(run: str) -> bool:
    return bool(re.search(r"set\s+-[a-z]*o\s+pipefail|set\s+-[a-z]*euo\s+pipefail",
                          _effective_run_lines(run)))


# 真实管道的单竖线：左邻不是 `|`、右邻也不是 `|`（`||` 两个竖线互相排除）。
# `|&`（管道 + stderr）仍命中 —— 它就是管道，退出码语义同 `|`。
_REAL_PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)")


def _count_real_pipes(run: str) -> int:
    """run 块里**真实管道**（单竖线）的数量 —— 排除 `||`（逻辑或 / SQL 字符串拼接）。

    issue #3527（PR #3523 实证）：本守卫原用 `"|" in run` 做文本启发式，把
    `test -f x || { ...; }` / `cmd || true` / SQL `'a' || 'b'` 也当管道 ——
    main 计数被顶到 38/38（BASELINE 28 + TOLERANCE 10，**零余量**），
    任何新 workflow 的 PR 必被顶红，只能改自己 workflow 的写法规避。
    `||` 取右操作数退出码，与「管道吞退出码」（issue #3270 假绿）无关，必须排除。

    fail-closed：**只**排除 `||`，真实管道（含 `|&`）检出与修前完全一致；
    不确定的单竖线（如 `grep -E "a|b"`）仍按管道计 —— 宁可保守告警也不放空守卫。
    """
    return len(_REAL_PIPE_RE.findall(run or ""))


class TestXiaobuStackExitCodePropagation:
    """xiaobu-acceptance 起栈步骤必须真实传播 compose 失败"""

    WORKFLOW = "xiaobu-acceptance.yml"

    def test_stack_step_exists_and_pipes(self):
        """前提：起栈步骤确实把 compose 输出管给 tail（因此需要 pipefail）"""
        step = _find_step(self.WORKFLOW, "Start local stack") or {}
        run = step.get("run") or ""
        assert "docker compose" in run, "起栈步骤未找到或不再调 docker compose（守卫前提失效）"
        assert "|" in run, "起栈步骤不再有管道 —— 本守卫前提变化，需同步修订"

    def test_stack_step_sets_pipefail(self):
        """核心契约：管道存在时必须有 set -o pipefail，否则 compose 失败被吞"""
        step = _find_step(self.WORKFLOW, "Start local stack") or {}
        run = step.get("run") or ""
        assert run, "起栈步骤未找到（守卫前提失效）"
        assert _sets_pipefail(run), (
            "起栈步骤有管道但无 pipefail —— compose 失败会变成 step success，"
            "真因被掩盖（issue #3270 实证：postgres exited 3 却报 success）。"
            "注意：断言只看非注释行（注释里写 pipefail 不算数）"
        )

    def test_diagnose_step_triggers_on_failure(self):
        """失败诊断步骤必须能在起栈失败时触发"""
        step = _find_step(self.WORKFLOW, "Diagnose on failure") or {}
        assert (step.get("if") or "").strip() == "failure()", (
            f"诊断步骤 if 应为 failure()，实为 {step.get('if')!r} —— "
            "否则起栈失败时不会 dump 容器日志（真因无法定位）"
        )

    def test_diagnose_provides_required_compose_env(self):
        """诊断步骤必须给 DEV_SERVICE_TOKEN 值，否则 compose 插值失败拿不到日志"""
        step = _find_step(self.WORKFLOW, "Diagnose on failure")
        env = (step.get("env") or {})
        assert "DEV_SERVICE_TOKEN" in env, (
            "诊断步骤缺 DEV_SERVICE_TOKEN —— deploy/docker-compose.yml 将其声明为 "
            "required（${DEV_SERVICE_TOKEN:?...}），缺它连 compose ps/logs 都会插值失败"
        )


class TestPipefailPatternInventory:
    """管道退出码吞失败是**系统性**模式，非单点（记录规模，防扩大）"""

    # 2026-09-11 基线：28 个 step 有管道但无 pipefail。
    # 不逐条修（部分管道的非零退出是预期行为，如 grep 无匹配 → 直接加 pipefail 会
    # 制造新的假失败），故本测试只做**规模告警**：数量增长需人工复核新引入的步骤。
    # issue #3527：计数只看**真实管道**（`||` 不算，见 `_count_real_pipes`）——
    # 修前 main 实测 38/38（零余量，`||` 误报贡献 18 格），排除后回落至 20/38。
    BASELINE = 28
    TOLERANCE = 10

    def _pipe_without_pipefail(self):
        hits = []
        for f in sorted(WORKFLOWS_DIR.glob("*.yml")):
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            for job in (d.get("jobs") or {}).values():
                for s in (job.get("steps") or []):
                    run = s.get("run") or ""
                    if _count_real_pipes(run) and "pipefail" not in run:
                        hits.append((f.name, s.get("name")))
        return hits

    def test_pipe_without_pipefail_not_growing(self):
        hits = self._pipe_without_pipefail()
        recent = hits[-8:]
        assert len(hits) <= self.BASELINE + self.TOLERANCE, (
            f"「有管道但无 pipefail」的步骤增至 {len(hits)} 个（基线 {self.BASELINE}）—— "
            "新步骤若用管道吞掉了退出码，请显式加 set -o pipefail，"
            f"或在本测试注释中说明该步骤的失败为何可忽略。尾部样本：{recent}"
        )


class TestPipeInventoryExcludesLogicalOr:
    """issue #3527：`||`（bash 逻辑或 / SQL 字符串拼接）**不是管道**，不得计入守卫。

    背景（PR #3523 实证）：
    上面的规模守卫用文本启发式 `"|" in run` 找「有管道但无 pipefail」的步骤，
    于是 `test -f x || { ...; }`、`cmd || true`、SQL 里的 `'a' || 'b'`
    都被当成管道 —— main 计数被顶到 **38/38**（BASELINE 28 + TOLERANCE 10，
    **零余量**）→ 任何新 workflow 的 PR 必被守卫顶红，只能改自己 workflow 的
    写法规避（语义等价但可读性下降）。

    判据（**fail-closed，禁止降门槛**）：
    * `||` 不计数 —— 它取右操作数退出码，与「管道吞掉退出码」（issue #3270）无关；
    * **真实管道（含 `|&`）检出集合必须与修前完全一致** —— 若连 `cmd | tail` 都被
      漏掉，守卫就废了（这才是真正的降级）；
    * BASELINE/TOLERANCE 常量**不得**被顺手放宽来掩盖误判。
    """

    @staticmethod
    def _hits(monkeypatch, tmp_path, steps):
        """把守卫指向合成 workflow 目录，返回命中列表（不依赖真实 .github/workflows）。"""
        (tmp_path / "synthetic.yml").write_text(
            yaml.safe_dump({"jobs": {"j": {"steps": steps}}}), encoding="utf-8"
        )
        monkeypatch.setitem(globals(), "WORKFLOWS_DIR", tmp_path)
        return TestPipefailPatternInventory()._pipe_without_pipefail()

    def test_logical_or_only_step_not_counted(self, tmp_path, monkeypatch):
        """只有 `||` 的步骤不计数（含 `cmd || true`、`test -f x || { ...; }`、SQL `||`）。"""
        hits = self._hits(monkeypatch, tmp_path, [
            {"name": "or-only", "run": (
                'test -f "$K/private.pem" || { echo "缺少密钥"; exit 1; }\n'
                "gh pr edit 1 --add-label x 2>/dev/null || true\n"
                'PSQL "SELECT order_no || \' / \' || status FROM orders LIMIT 12;"\n'
                "[ \"$found\" = \"1\" ] || echo \"未取到汇总\"\n"
            )},
        ])
        assert hits == [], (
            f"`||`（逻辑或/字符串拼接）被误判为管道 → {hits} —— "
            "issue #3527：main 已 38/38（零余量），新 workflow PR 会被守卫顶红"
        )

    def test_real_pipe_step_still_counted(self, tmp_path, monkeypatch):
        """真实管道仍必须计数（fail-closed：只排除 `||`，不得把 `|` 也放过）。"""
        hits = self._hits(monkeypatch, tmp_path, [
            {"name": "real-pipe", "run": "docker compose up --wait 2>&1 | tail -20"},
        ])
        assert [h[1] for h in hits] == ["real-pipe"], (
            f"真实管道 `| tail -20` 未被计数（{hits}）—— 守卫被放空，"
            "issue #3270 的假绿会复发"
        )

    def test_mixed_step_counts_only_real_pipe(self, tmp_path, monkeypatch):
        """混合行（既有 `||` 又有真实管道）只计真实管道：1 次命中，不是 2 次、也不是 0 次。"""
        mixed = "docker compose up 2>&1 | tail -20 || true"
        hits = self._hits(monkeypatch, tmp_path, [
            {"name": "mixed", "run": mixed},
            {"name": "or-only", "run": "cmd || true"},
        ])
        assert [h[1] for h in hits] == ["mixed"], (
            f"混合行的计数口径错误：命中 {hits}（预期只有 mixed 一条）"
        )
        assert _count_real_pipes(mixed) == 1, (
            "`| tail -20 || true` 里的真实管道计数应为 1（`||` 不计）"
        )

    def test_pipe_occurrence_counting(self):
        """计数口径逐例锁定：`||` 记 0，真实管道记 1，`|&` 也记（bash 管道语义）。"""
        cases = {
            "test -f x || { echo missing; exit 1; }": 0,
            "cmd || true": 0,
            "PSQL \"SELECT 'a' || 'b' FROM t\"": 0,
            "git describe --tags --abbrev=0 2>/dev/null || echo \"v0.0.0\"": 0,
            "docker compose up 2>&1 | tail -20": 1,
            "docker compose up 2>&1 |& tail -20": 1,
            "grep -c x file | tail -1 || true": 1,
            "${{ github.event.inputs.tier || 'smoke' }} | tail -5": 1,
        }
        for run, expected in cases.items():
            assert _count_real_pipes(run) == expected, (
                f"{run!r} 的真实管道计数应为 {expected}，实得 {_count_real_pipes(run)}"
            )

    def test_thresholds_unchanged(self):
        """阈值常量不得被顺手放宽（issue #3527 明令：修启发式，不修阈值）。"""
        assert (TestPipefailPatternInventory.BASELINE,
                TestPipefailPatternInventory.TOLERANCE) == (28, 10), (
            "BASELINE/TOLERANCE 被改动 —— 靠放宽阈值掩盖 `||` 误判 = 降门槛，禁止；"
            "必须修计数启发式（排除逻辑或）"
        )

    def test_main_inventory_recovers_margin(self):
        """验收（issue #3527）：main 计数回落到阈值以下，**余量恢复**。

        修前实测 **38/38**（`||` 误报贡献 18 格，真实管道 20 格）→ 零余量，
        任何新 workflow 都被顶红（PR #3523 实测）。排除 `||` 后回落至 20/38，
        余量 18 格。本测试是**比规模守卫早一格的余量预警**：计数顶到上限时
        先在这里看到（并给出归因提示），而不是等下个新 workflow 的 PR 被顶红。
        """
        hits = TestPipefailPatternInventory()._pipe_without_pipefail()
        limit = TestPipefailPatternInventory.BASELINE + TestPipefailPatternInventory.TOLERANCE
        print(f"[#3527] main 管道步骤计数 = {len(hits)}/{limit}（BASELINE "
              f"{TestPipefailPatternInventory.BASELINE} + TOLERANCE "
              f"{TestPipefailPatternInventory.TOLERANCE}）")
        assert len(hits) < limit, (
            f"main 计数 {len(hits)}/{limit} 已无余量 —— "
            "① 若计数里含 `||`（逻辑或/SQL 拼接）等误报：修 `_count_real_pipes` 启发式，"
            "禁止放宽 BASELINE/TOLERANCE；"
            "② 若确为新增真实管道：给这些步骤补 `set -o pipefail`（防 issue #3270 假绿），"
            f"不要为凑数改阈值。命中样本尾部：{hits[-5:]}"
        )


class TestVerifyAllPerCheckLogs:
    """`verify-all.sh` 的失败日志必须**按检查项唯一**（否则排查被带偏）。

    先例（真实踩到）：日志路径写成固定的 `/tmp/verify-all-$$.log`。
    `$$` 是 shell PID，在同一进程内**不变** → 每个检查项都覆盖同一个文件 →
    多项失败时只剩最后一项的日志，而脚本对每个失败项都打印
    「日志: /tmp/verify-all-$$.log」—— 你照着提示去看，看到的是**别人**的日志。

    与 issue #3270 的 pipefail 假绿同源：**报错指向的证据与实际原因不一致**，
    比直接报错更难查。
    """

    SCRIPT = Path(__file__).parent.parent.parent / "verify-all.sh"

    @staticmethod
    def _code_lines() -> list:
        """脚本的**有效代码行**（剥掉注释）——注释里会引用旧写法，裸 grep 会假绿。"""
        out = []
        for line in TestVerifyAllPerCheckLogs.SCRIPT.read_text(encoding="utf-8").splitlines():
            stripped = line.split("#", 1)[0]
            if stripped.strip():
                out.append(stripped)
        return out

    def test_log_path_is_not_a_single_shared_file(self):
        code = "\n".join(self._code_lines())
        assert "verify-all-$$.log" not in code, (
            "verify-all.sh 仍使用单一共享日志 /tmp/verify-all-$$.log —— "
            "多项失败时日志互相覆盖，提示的路径指向别人的日志"
        )

    def test_log_path_includes_check_identity(self):
        code = "\n".join(self._code_lines())
        assert re.search(r"verify-all-\$\$-\$\{?slug", code), (
            "日志路径未拼接检查项标识（slug）—— 无法做到按检查项唯一"
        )

    def test_slice_function_produces_unique_paths(self):
        """行为验证：**两个不同检查项**必须得到**不同**日志路径。

        只静态检查文本是不够的 —— slug 若被写成常量（如 `slug="fixed"`），
        文本里仍有 `${slug}` 且路径看似"唯一"，但两项检查其实又共用同一个文件
        （变异测试 M2 实测假绿）。故这里真跑两条**不同名称的失败检查**比对路径。
        """
        import subprocess
        import textwrap

        script = self.SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"^report\(\) \{[\s\S]*?^\}", script, re.M)
        assert m, "未能从 verify-all.sh 中抽出 report() 函数"
        snippet = textwrap.dedent("""
            set -uo pipefail
            PASS=0; FAIL=0; declare -a FAILED
        """) + m.group(0) + textwrap.dedent("""
            report "检查项 A" false
            report "检查项 B" false
            rm -f /tmp/verify-all-$$-*.log
        """)
        r = subprocess.run(["bash", "-c", snippet], capture_output=True, text=True)
        paths = re.findall(r"日志: (\S+)", r.stdout)
        assert len(paths) == 2, f"预期 2 条失败日志路径，实得 {paths}"
        assert paths[0] != paths[1], (
            f"两个不同检查项得到同一日志路径 {paths[0]!r} —— "
            "后跑的会覆盖先跑的，失败现场被销毁"
        )
        for p in paths:
            assert "verify-all-" in p and p.endswith(".log")
