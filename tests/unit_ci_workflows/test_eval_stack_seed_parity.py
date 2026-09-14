# case_ids: CH-010
"""评测栈种子口径单一源 + 跨 workflow 一致性（L0 静态锁，issue #3563）。

## 为什么要这层锁（L0，秒级零 LLM）

同一个用例 CH-010（persona=xiaobu）在两个 workflow 上跑出**相反结论**：

| workflow | run | `products=` | `product_search` 首条 | CH-010 |
|---|---|---|---|---|
| `agent-behavior-eval` | 34805981549 | **4** | `2699系列雪尼尔窗帘面料`（B 端 fixture） | **❌ 0%** |
| `xiaobu-acceptance` | 34807824585 | **3** | `北欧风窗帘`（C 端 fixture） | **✅ 100%** |

根因**不在 agent**：CH-010 第 2 轮输入是「**第一款**，白色…」——"第一款"指代
`product_search` 列表首条，而商品列表默认 `ORDER BY created_at DESC`；
`mibao_eval_seed.sql` 在 `xiaobu_eval_seed.sql` **之后**执行（`created_at DEFAULT NOW()`）
→ B 端 `prod_eval_2699` 恒排第一 → C 端用例拿着 B 端商品往下走（无「白色」色号、
绑 `per_area` 刺绣工艺）→ 交互链断裂。

三个评测 workflow 的种子规则此前**各写一份、且互不相等**：
`xiaobu-acceptance` / `post-deploy-eval` 只在 `persona=mibao` 时叠 B 端种子，
`agent-behavior-eval` **无条件**叠加（"一个 job 里可能同时有双端分桶"），
且两个 persona 分桶共用同一套栈 —— 于是"同 persona 在不同 workflow 上数据栈不同"。

## 本文件锁定什么（§16.1「能 L0 拦的不许流到 L2+」）

1. **单一实现**：种子注入规则只存在于 `scripts/eval_stack_seed.sh`，workflow 只调用它
   （`--dry-run` 下按 persona 列出该装的种子），任何一边私自内联 SQL 即红；
2. **规则等价 + 反例**：`xiaobu` 栈 = 仅 C 端种子（**不得含 B 端**）；`mibao` 栈 = C 端 + B 端；
3. **同栈不混 persona**：`agent-behavior-eval` 必须按 persona 分 job（各自独立栈），
   `post-deploy-eval` 的 matrix 必须逐腿带 persona —— 混栈即红；
4. **归属锁定**：CH-010 只属 xiaobu、OR-016 只属 mibao（后者是"双端点名商品用例
   已被语义收口归到 B 端"的证据，防止有人把它挪回 C 端重演 0 分）。

## case_ids 说明（不编造）

本文件是**基建静态锁**，不是行为用例本身；声明的 `CH-010` 是**该锁要保护的、被本根因
判错的既有行为用例**（C 端"推荐几款热销窗帘 → 第一款"链路，其正确性直接依赖
"xiaobu 栈不含 B 端商品"）。用例库里**没有**"评测栈种子口径"这一域的用例，
故只声明真实存在的 CH-010，不新增/不伪造 ID。
"""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
SEED_SCRIPT = REPO_ROOT / "scripts" / "eval_stack_seed.sh"

# 评测 family：凡"起独立栈 + 注种子 + 跑 local_runner"的 workflow 都必须走单一源。
# 漏登记 = 新造第五套口径的入口，故本集合是**白名单**而非"扫全部 yml"。
EVAL_WORKFLOWS = (
    "xiaobu-acceptance.yml",
    "post-deploy-eval.yml",
    "agent-behavior-eval.yml",
)
SEED_STEP_NAME = "Seed 评测业务数据"
# 单一源调用形态：`bash scripts/eval_stack_seed.sh --persona <表达式>`
CALL_RE = re.compile(r"bash\s+scripts/eval_stack_seed\.sh\s+--persona\s+(\S+)")
FIXTURE_RE = re.compile(r"[\w/]*fixtures/(\w+_eval_seed\.sql)")

def _load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS_DIR / name).read_text(encoding="utf-8")) or {}


def _jobs(name: str) -> dict:
    return _load_workflow(name).get("jobs") or {}


def _steps(workflow: str) -> list:
    out = []
    for job in _jobs(workflow).values():
        out.extend(job.get("steps") or [])
    return out


def _seed_steps(workflow: str) -> list:
    """该 workflow 里所有"注种子"步骤。"""
    return [s for s in _steps(workflow) if SEED_STEP_NAME in (s.get("name") or "")]


def _seed_step_bodies(workflow: str) -> str:
    return "\n".join((s.get("run") or "") for s in _seed_steps(workflow))


def _seed_persona_expr(workflow: str) -> str:
    """种子步骤传给单一源的 persona 表达式（必须唯一）。"""
    calls = CALL_RE.findall(_seed_step_bodies(workflow))
    assert len(calls) == 1, (
        f"{workflow} 的种子步骤必须**恰好一次**调用单一源 "
        f"`bash scripts/eval_stack_seed.sh --persona <表达式>`，实为 {calls} —— "
        "多写一份/少写一份都会让规则重新分叉（issue #3563）"
    )
    return calls[0]


def _run_seed_script(monkeypatch, tmp_path, persona: str):
    """执行单一源（--dry-run），返回它按顺序调用的每个种子文件。

    用假 `docker` 可执行文件在 PATH 最前面截获 `docker compose exec -T postgres psql …`
    （脚本把 fixture 从 stdin 重定向进 psql，故从**重定向到 stdin 的文件名**取证）。
    """
    fakebin = tmp_path / "bin"
    fakebin.mkdir(exist_ok=True)
    trace = tmp_path / "trace.txt"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "' + str(trace) + '"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fakebin}:{__import__('os').environ['PATH']}")

    proc = subprocess.run(
        ["bash", str(SEED_SCRIPT), "--persona", persona, "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"eval_stack_seed.sh --persona {persona} --dry-run 失败：\n{proc.stdout}\n{proc.stderr}"
    )
    return FIXTURE_RE.findall(proc.stdout)


class TestSeedRuleSingleSource:
    """规则只有一个实现：三个评测 workflow 都调用 scripts/eval_stack_seed.sh。"""

    def test_seed_script_exists(self):
        assert SEED_SCRIPT.is_file(), (
            f"缺少种子注入单一源 {SEED_SCRIPT.relative_to(REPO_ROOT)} —— "
            "issue #3563 的修法就是把它抽出来，不许各 workflow 内联"
        )

    @pytest.mark.parametrize("workflow", EVAL_WORKFLOWS)
    def test_workflow_has_single_seed_step(self, workflow: str):
        steps = _seed_steps(workflow)
        assert len(steps) == 1, (
            f"{workflow} 的注种子步骤应为 1 个（实测 {len(steps)}）—— "
            "两个注种子步骤 = 两处规则，必然漂移"
        )

    @pytest.mark.parametrize("workflow", EVAL_WORKFLOWS)
    def test_workflow_delegates_to_single_source(self, workflow: str):
        _seed_persona_expr(workflow)      # 内部断言"恰好一次调用"

    @pytest.mark.parametrize("workflow", EVAL_WORKFLOWS)
    def test_workflow_does_not_inline_fixture_sql(self, workflow: str):
        """workflow 不得自己内联 fixture 路径 —— 否则可绕开单一源各写一套（本 issue 的根因形态）。"""
        body = _seed_step_bodies(workflow)
        leaked = FIXTURE_RE.findall(body)
        assert not leaked, (
            f"{workflow} 的种子步骤内联了 fixture（{leaked}）—— 规则必须只在 "
            f"{SEED_SCRIPT.relative_to(REPO_ROOT)} 里，workflow 只调用它"
        )

    @pytest.mark.parametrize("workflow", EVAL_WORKFLOWS)
    def test_seed_step_passes_persona_via_expression_not_literal(self, workflow: str):
        """persona 必须由**表达式/matrix**传入，不能写死 —— 写死即"某个 persona 恒用错栈"。"""
        expr = _seed_persona_expr(workflow)
        assert "${{" in expr, (
            f"{workflow} 把 persona 写成了字面量 {expr!r} —— 栈口径必须随本次实际 persona 走"
        )
        for literal in ("mibao", "xiaobu"):
            assert literal not in expr, (
                f"{workflow} 的 persona 表达式含字面量 {literal!r}（{expr}）—— "
                "条件分支应下沉到单一源，workflow 侧不得自行判断 persona"
            )


class TestSeedRuleEquivalence:
    """规则本身：xiaobu 栈不含 B 端种子，mibao 栈含。"""

    def test_xiaobu_stack_is_c_end_only(self, monkeypatch, tmp_path):
        seeds = _run_seed_script(monkeypatch, tmp_path, "xiaobu")
        assert "xiaobu_eval_seed.sql" in seeds, (
            f"xiaobu 栈未注入 C 端种子（实测 {seeds}）—— C 端用例会因空库无商品全红"
        )
        assert "mibao_eval_seed.sql" not in seeds, (
            "❌ xiaobu 栈注入了 B 端种子（issue #3563 根因）：\n"
            "  mibao_eval_seed.sql 后执行 → created_at 更新 → `ORDER BY created_at DESC`\n"
            "  使 B 端 prod_eval_2699 恒排第一 → C 端用例「第一款」指到 B 端商品\n"
            "  → CH-010 在 behavior-eval 上 0%、在 xiaobu-acceptance 上 100%（实测）"
        )

    def test_mibao_stack_adds_b_end_fixture(self, monkeypatch, tmp_path):
        seeds = _run_seed_script(monkeypatch, tmp_path, "mibao")
        assert seeds == ["xiaobu_eval_seed.sql", "mibao_eval_seed.sql"], (
            f"mibao 栈必须是「C 端种子 + B 端种子」且 C 端在前（实测 {seeds}）—— "
            "B 端点名用例（OR-016 的 2699 商品 / PR-020 的刺绣工艺）#3496 归因过：缺数据会长得像能力回归"
        )

    def test_both_personas_share_the_c_end_base(self, monkeypatch, tmp_path):
        """两端共用的 C 端底座必须一致（差异只能是"有没有 B 端那一层"）。"""
        xiaobu = _run_seed_script(monkeypatch, tmp_path, "xiaobu")
        mibao = _run_seed_script(monkeypatch, tmp_path, "mibao")
        assert xiaobu == mibao[: len(xiaobu)], (
            f"两端的 C 端底座不一致：xiaobu={xiaobu} / mibao={mibao} —— "
            "同 persona 在不同 workflow 上会因为底座顺序不同而拿到不同数据"
        )

    def test_unknown_persona_is_fail_closed(self, monkeypatch, tmp_path):
        """非法 persona 必须报错退出（不得静默按 C 端跑 = 让 B 端用例跑在缺数据的栈上）。"""
        import os
        fakebin = tmp_path / "bin"
        fakebin.mkdir(exist_ok=True)
        docker = fakebin / "docker"
        docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        docker.chmod(0o755)
        monkeypatch.setenv("PATH", f"{fakebin}:{os.environ['PATH']}")
        proc = subprocess.run(
            ["bash", str(SEED_SCRIPT), "--persona", "米宝", "--dry-run"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert proc.returncode != 0, (
            "非法 persona 未 fail-closed —— 静默回落会让「该 persona 专属用例」跑在错栈上"
        )


class TestNoMixedPersonaStack:
    """反例锁定：一个栈只服务一个 persona（本 issue 的直接形态）。"""

    def test_behavior_eval_runs_one_persona_per_job(self):
        """`agent-behavior-eval` 必须按 persona 分 job（各自独立栈）—— 混栈即红。"""
        d = _load_workflow("agent-behavior-eval.yml")
        eval_jobs = {
            name: job for name, job in (d.get("jobs") or {}).items()
            if any(SEED_STEP_NAME in (s.get("name") or "") for s in (job.get("steps") or []))
        }
        assert eval_jobs, "未找到注种子的评测 job（守卫前提失效）"
        matrix_jobs = [n for n, j in eval_jobs.items() if (j.get("strategy") or {}).get("matrix")]
        assert matrix_jobs, (
            "❌ agent-behavior-eval 的评测 job 没有 persona matrix（issue #3563 根因形态）：\n"
            "  单个 job 里先跑 mibao 分桶再跑 xiaobu 分桶 → **同一套栈**服务两个 persona，\n"
            "  而两者需要的种子集合不同（xiaobu 不得含 B 端）→ 必然有一端被错栈污染。\n"
            "  修法：matrix persona（每个 persona 一个 job + 各自全新栈），"
            "与 post-deploy-eval.yml 同款隔离（#3515 先例）。"
        )
        for name in matrix_jobs:
            seed_body = "\n".join(
                (s.get("run") or "") for s in (eval_jobs[name].get("steps") or [])
                if SEED_STEP_NAME in (s.get("name") or "")
            )
            assert "matrix.persona" in seed_body, (
                f"job {name} 的种子步骤没有用 matrix.persona 传 persona（{seed_body[:120]}）"
            )

    def test_post_deploy_matrix_leg_carries_persona(self):
        """`post-deploy-eval` 的每一条 matrix 腿都必须带 persona（漏了 = 全腿按 xiaobu 的栈跑）。"""
        matrix = ((_jobs("post-deploy-eval.yml").get("eval") or {}).get("strategy") or {}).get("matrix")
        if matrix is None:
            matrix = next(
                ((j.get("strategy") or {}).get("matrix")
                 for j in _jobs("post-deploy-eval.yml").values()
                 if (j.get("strategy") or {}).get("matrix")),
                None,
            )
        assert matrix, "post-deploy-eval 未找到 persona matrix（守卫前提失效，需同步本测试）"
        include = matrix.get("include") if isinstance(matrix, dict) else None
        if include:
            personas = sorted(leg.get("persona") for leg in include if leg.get("persona"))
        else:
            # list 形态：`persona: [mibao, xiaobu]`（post-deploy-eval 现状）
            personas = sorted(matrix.get("persona") or [])
        assert personas == ["mibao", "xiaobu"], (
            f"post-deploy-eval 的 matrix 腿 persona={personas} —— "
            "必须恰好 mibao + xiaobu 各一条（各自独立栈 + 独立新库，#3515）"
        )


class TestEvalWorkflowKnobParity:
    """同类漂移锁定（issue #3563 排查副产品）：评测旋钮不许"各写一份"。

    同族 workflow 的**同语义旋钮**若各写一份口径，就会出现"某一路静默缺失"：

    | 旋钮 | 语义 | 缺失后果 |
    |---|---|---|
    | `EVAL_ROUND_SLEEP` / `EVAL_CASE_SLEEP` | 固定节流 | 缺失 → 回落 runner 默认值（墙钟变长） |
    | `EVAL_CONCURRENCY` | 用例级并发 | 缺失 → 回落 1（串行，迭代档变慢） |
    | `AGENT_EVAL_FLAKE_LOG` | 波动台账落盘 | 缺失 → 台账**永不生成**，artifact 空、"按台账放行"退化 |
    | `AGENT_EVAL_TRACE_ALL` | 逐轮轨迹（含通过的写用例） | 缺失 → 假绿看不见（#3270 实证） |

    `AGENT_EVAL_FLAKE_LOG` 是真实踩到的：`post-deploy-eval` 上传
    `agent-eval-flakes.json` 但从不落盘它（runner 只在设了该变量时才写，
    `local_runner.py:3899`），`agent-behavior-eval` 更是既不落盘也不上传 ——
    波动台账（§14.3/§16.5 的观测信号）在这两路上静默缺失。
    """

    KNOBS = (
        "EVAL_ROUND_SLEEP",
        "EVAL_CASE_SLEEP",
        "EVAL_CONCURRENCY",
        "AGENT_EVAL_FLAKE_LOG",
        "AGENT_EVAL_TRACE_ALL",
    )

    @pytest.mark.parametrize("workflow", EVAL_WORKFLOWS)
    @pytest.mark.parametrize("knob", KNOBS)
    def test_eval_knob_is_set(self, workflow: str, knob: str):
        steps = _steps(workflow)
        eval_steps = [s for s in steps
                      if "local_runner" in ((s.get("name") or "") + (s.get("run") or ""))]
        assert eval_steps, f"{workflow} 未找到评测步骤（守卫前提失效）"
        present = any(knob in (s.get("env") or {}) for s in eval_steps)
        assert present, (
            f"{workflow} 的评测步骤未设 {knob} —— 同族 workflow 的同语义旋钮各写一份，"
            "漏设的一路会静默回落到默认值（台账/轨迹/并发/节流语义漂移）"
        )

    @pytest.mark.parametrize("workflow", EVAL_WORKFLOWS)
    def test_sleep_knobs_agree_on_values(self, workflow: str):
        """节流值必须三路同值（否则"同档位在不同 workflow 上墙钟/限流行为不同"）。"""
        seen = {}
        for s in _steps(workflow):
            env = s.get("env") or {}
            for k in ("EVAL_ROUND_SLEEP", "EVAL_CASE_SLEEP"):
                if k in env:
                    seen[k] = str(env[k]).strip('"')
        assert seen.get("EVAL_ROUND_SLEEP") == "0.2", (
            f"{workflow}: EVAL_ROUND_SLEEP={seen.get('EVAL_ROUND_SLEEP')!r}，仓库口径为 '0.2'"
        )
        assert seen.get("EVAL_CASE_SLEEP") == "0.3", (
            f"{workflow}: EVAL_CASE_SLEEP={seen.get('EVAL_CASE_SLEEP')!r}，仓库口径为 '0.3'"
        )


class TestSeedBeforeEvalOrdering:
    """注种子必须早于评测（否则空库上依赖数据的用例必然失败）。"""

    @pytest.mark.parametrize("workflow", EVAL_WORKFLOWS)
    def test_seed_step_precedes_eval_step(self, workflow: str):
        for job_name, job in _jobs(workflow).items():
            steps = job.get("steps") or []
            names = [s.get("name") or "" for s in steps]
            runs = [s.get("run") or "" for s in steps]
            seed_idx = [i for i, n in enumerate(names) if SEED_STEP_NAME in n]
            if not seed_idx:
                continue
            # 评测步骤的判据：步骤名或命令体里出现 local_runner
            eval_idx = [i for i in range(len(steps))
                        if "local_runner" in names[i] or "local_runner" in runs[i]]
            assert eval_idx, (
                f"{workflow}/{job_name} 有注种子步骤但没有任何 local_runner 评测步骤 —— "
                "守卫前提失效，需同步本测试"
            )
            assert min(seed_idx) < min(eval_idx), (
                f"{workflow}/{job_name}: 注种子必须在评测之前"
                f"（seed@{seed_idx} vs eval@{eval_idx}）"
            )


class TestCasePersonaOwnershipLock:
    """归属锁定：这两个用例分别是两端"错栈即 0 分"的证据，不许被挪到另一端。"""

    @staticmethod
    def _owners() -> dict:
        sys.path.insert(0, str(REPO_ROOT / ".github"))
        sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
        render_spec = importlib.util.spec_from_file_location(
            "_mg_render_cases", REPO_ROOT / ".github" / "render_cases.py"
        )
        render = importlib.util.module_from_spec(render_spec)
        sys.modules["_mg_render_cases"] = render
        render_spec.loader.exec_module(render)
        sys.modules["render_cases"] = render

        filter_spec = importlib.util.spec_from_file_location(
            "_mg_eval_case_filter", REPO_ROOT / "tests" / "agent_eval" / "eval_case_filter.py"
        )
        filt = importlib.util.module_from_spec(filter_spec)
        sys.modules["_mg_eval_case_filter"] = filt
        filter_spec.loader.exec_module(filt)

        cases = render.load_case_dicts(str(REPO_ROOT / ".github" / "cases"))
        return {
            p: {c.get("id", "") for c in filt.select_cases_for_persona(cases, p)}
            for p in ("mibao", "xiaobu")
        }

    def test_ch010_is_xiaobu_only(self):
        """CH-010 是 C 端专属：它只该跑在"仅 C 端种子"的栈上（本 issue 的受害用例）。"""
        owners = self._owners()
        assert "CH-010" in owners["xiaobu"], "CH-010 不在 xiaobu 可跑集 —— 守卫前提失效"
        assert "CH-010" not in owners["mibao"], (
            "CH-010 出现在 mibao 可跑集 —— 它会跑在含 B 端商品的栈上，"
            "「第一款」再次指到 prod_eval_2699（issue #3563 的 0 分形态）"
        )

    def test_or016_is_mibao_only(self):
        """OR-016 点名 B 端 fixture 商品 → 归 B 端栈（这正是"错栈即 0 分"的反面证据）。"""
        owners = self._owners()
        assert "OR-016" in owners["mibao"], "OR-016 不在 mibao 可跑集 —— 守卫前提失效"
        assert "OR-016" not in owners["xiaobu"], (
            "OR-016 出现在 xiaobu 可跑集 —— 它点名「2699系列雪尼尔窗帘面料」（B 端 fixture），"
            "跑 C 端栈必然搜不到（#3496 归因的假失败形态）"
        )
