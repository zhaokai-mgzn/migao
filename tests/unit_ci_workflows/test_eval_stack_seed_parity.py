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
3. **同栈不混 persona**：`post-deploy-eval` 的 matrix 必须逐腿带 persona（每条腿各自独立栈），
   `xiaobu-acceptance` 的注种子必须吃**单值** persona 输入（一次 run 一套栈）—— 混栈即红；
4. **归属锁定**：CH-010 只属 xiaobu、OR-016 只属 mibao（后者是"双端点名商品用例
   已被语义收口归到 B 端"的证据，防止有人把它挪回 C 端重演 0 分）。

## 2026-09-17 变更：第三个 workflow 移出本 family（用户裁定 2′/4′，issue #4034）

`agent-behavior-eval.yml` 的 `behavior-eval` job（起 docker 栈 + 注种子 + 跑 `local_runner.py`
+ 真实 LLM）**整体删除**：PR 上只剩纯静态的 `map` job（diff → case_ids，零 LLM）。
它**不再起栈、不再注种子、不再跑 runner** ⇒ 已不是本 family 的成员，故从 `EVAL_WORKFLOWS`
移出（连同一切按 workflow 参数化的用例；移出的理由写在那个常量上方）。

⚠️ **移出不是豁免**（§19.1 元规则：白名单只许缩短，不许成为藏身处）：
`TestExcludedWorkflowHasNoStackMachinery` 用**结构判据**证明它真的没有栈机件；
LLM job 一旦被加回来那条守卫先红 —— 那时本集合必须同步加回。PR 层零 LLM 的机械锁
（含"自动 LLM 触发白名单"）见 `tests/unit_ci_workflows/test_behavior_eval_pr_thin.py`。

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
#
# ★ 2026-09-17 移出 `agent-behavior-eval.yml`（用户裁定 2′/4′，issue #4034）：它的
#   `behavior-eval` job（起栈 + 注种子 + local_runner + 真实 LLM）**整体删除**，PR 上
#   只剩纯静态的 `map` job ⇒ 已不属于本 family（白名单的语义是"谁起栈谁登记"）。
#   ⚠️ 这不是"为了让测试变绿而放宽"：移出**由结构判据背书** ——
#   `TestExcludedWorkflowHasNoStackMachinery` 断言该文件里**一件栈机件都没有**
#   （零种子单一源调用 / 零 docker compose / 零 local_runner / 零 `id: eval` 步骤）。
#   把 LLM job 加回来 ⇒ 那条守卫先红 ⇒ 本集合必须同步加回，本 family 的判据一个都不会少。
EVAL_WORKFLOWS = (
    "xiaobu-acceptance.yml",
    "post-deploy-eval.yml",
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


class TestExcludedWorkflowHasNoStackMachinery:
    """`agent-behavior-eval.yml` 被移出 `EVAL_WORKFLOWS` 的**结构性理由**（不是豁免）。

    白名单的惯例是"漏登记 = 新造一套口径的入口"，所以"移出"必须能被**证伪**，否则它就成了
    藏 LLM job 的地方（§19.1：基于错误真相模型写出的护栏 = 永远被豁免的空判据）。
    本类断言该 workflow 的**步骤正文**里一件栈机件都没有：
    ① 不调用种子单一源（不起栈就不注种子）；② 无 `docker compose`；
    ③ 无 `local_runner.py`（零 LLM 的机械形式）；④ 无 `id: eval` 步骤。
    另外单列一条：被删的 `behavior-eval` job 不得回来。

    ⚠️ **必须先剥掉 YAML 注释行**：该文件头部注释**合法地**记着沿革（"曾经的栈怎么起 /
    runner 在哪 / job 级槽位叫什么"），按原文搜会把沿革说明误判成"机件回来了"（假红）；
    反过来只搜注释则等于不搜（假绿）—— 故判据落在"步骤正文"这一层。
    """

    EXCLUDED = "agent-behavior-eval.yml"

    def _stack_surface(self) -> str:
        """步骤正文（name + run + with.script），逐行剥掉 `#` 注释行后拼接。"""
        chunks = []
        for job in _jobs(self.EXCLUDED).values():
            for s in job.get("steps") or []:
                chunks.append(s.get("name") or "")
                chunks.append(s.get("run") or "")
                chunks.append(str((s.get("with") or {}).get("script") or ""))
        text = "\n".join(chunks)
        return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))

    def test_excluded_workflow_has_no_stack_machinery(self):
        """零栈机件 —— 任何一件回来，本 workflow 就不再是「纯静态」，必须重回白名单。"""
        text = self._stack_surface()
        for banned in ("eval_stack_seed.sh", "docker compose", "local_runner.py"):
            assert banned not in text, (
                f"{self.EXCLUDED} 的步骤正文里出现了栈机件 {banned!r} —— "
                "它已不是「纯静态映射」workflow（裁定 2′/4′，#4034）：把 LLM/栈加回来必须"
                "**同时**把它加回 EVAL_WORKFLOWS 并由本文件全部判据重新覆盖，"
                "不许借「移出白名单」把起栈的 job 藏在外面"
            )
        step_ids = [s.get("id") for job in _jobs(self.EXCLUDED).values()
                    for s in (job.get("steps") or [])]
        assert "eval" not in step_ids, (
            f"{self.EXCLUDED} 出现了 `id: eval` 步骤（{step_ids}）—— "
            "PR 层零 LLM 的形态是「没有评测步骤」，不是「评测步骤恒 exit 0」"
        )

    def test_deleted_eval_job_has_not_come_back(self):
        """被删的 `behavior-eval` job 不得回来（回来即重新成为 PR 层真实 LLM 入口）。"""
        jobs = _jobs(self.EXCLUDED)
        assert "behavior-eval" not in jobs, (
            f"{self.EXCLUDED} 又有了 `behavior-eval` job（现为 {sorted(jobs)}）—— "
            "裁定 2′/4′（#4034）删掉它正是因为「永不执行的死 job」也算死机制；"
            "把它加回来 = 重新在每个行为 PR 上烧真实 token + 占评测槽位"
        )


class TestSeedRuleSingleSource:
    """规则只有一个实现：`EVAL_WORKFLOWS`（白名单）里的评测 workflow 都调用单一源。"""

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
    """反例锁定：一个栈只服务一个 persona（本 issue 的直接形态）。

    ⚠️ 原判据 `test_behavior_eval_runs_one_persona_per_job` 的被测对象**已不存在**：
    `agent-behavior-eval.yml` 的 `behavior-eval`（persona matrix + 独立栈）job 已按
    裁定 2′/4′（issue #4034）**整体删除** —— PR 上不再起任何栈，也就不存在 PR 层的
    「同一套栈服务两个 persona」这一风险面（PR 层零 LLM 的机械锁见
    `tests/unit_ci_workflows/test_behavior_eval_pr_thin.py`）。
    故把**同一条 premise**（「一个栈只服务一个 persona」）钉在**剩余**两路上：
    注种子的 persona 来源必须是「每条腿 / 每次 run 恰好一个值」的表达式 ——
    workflow 侧一旦自行判断 persona（写死、分支、合并两套种子）即红。
    """

    # 种子步骤的 persona 来源：必须是**单值**的（每条 matrix 腿 / 每次 run 恰一个 persona）
    #   · post-deploy-eval：persona matrix 逐腿展开 ⇒ 一条腿 = 一个 persona（#3515 的隔离形态）
    #   · xiaobu-acceptance：单值 dispatch 输入（它自己的 matrix 是 **shard**，不是 persona）
    # 反向变异：来源换成写死字面量、或换成「按 persona 分支 / 两套种子叠一起」的写法 ⇒ 红。
    PERSONA_SOURCE = {
        "post-deploy-eval.yml": "matrix.persona",
        "xiaobu-acceptance.yml": "github.event.inputs.persona",
    }

    @staticmethod
    def _seed_code(workflow: str) -> str:
        """注种子步骤的**可执行**正文（剥掉 `#` 注释行后拼接）。

        剥注释是必须的：两处种子步骤的注释里都**合法地**解释着 persona 口径
        （如「非 mibao 时仅注 C 端种子」），按原文搜会把解释文字当成"workflow 在自行
        判断 persona"（假红）；反过来只搜注释等于不搜（假绿）—— 判据只看命令行。
        """
        return "\n".join(ln for ln in _seed_step_bodies(workflow).splitlines()
                         if not ln.lstrip().startswith("#"))

    @pytest.mark.parametrize("workflow,source", sorted(PERSONA_SOURCE.items()))
    def test_each_stack_gets_exactly_one_persona(self, workflow: str, source: str):
        body = self._seed_code(workflow)
        assert body, f"{workflow} 找不到注种子步骤（守卫前提失效）"
        assert source in body, (
            f"{workflow} 的注种子步骤没有从 {source!r} 取 persona（{body.strip()[:160]}）—— "
            "persona 必须随本次实际要跑的那一套栈走，否则会拿别人的栈跑（#3563 的 0 分形态）"
        )
        assert not ("mibao" in body and "xiaobu" in body), (
            f"{workflow} 的注种子命令里同时出现 mibao 与 xiaobu 两个字面量 —— "
            "workflow 侧在自行判断 persona：条件分支应下沉到单一源 eval_stack_seed.sh，"
            "否则「哪套种子上哪套栈」会有第二份口径（本 issue 的根因形态）"
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

    `AGENT_EVAL_FLAKE_LOG` 是真实踩到的（#3563 当时的形态；逐路现状由本类锁住）：
    `post-deploy-eval` 上传 `agent-eval-flakes.json` 却不设这个变量（runner 侧按该变量
    决定台账落盘**路径** —— 见 `local_runner.py` 里按「flake 台账」检索的那一段）；
    `agent-behavior-eval`（该 workflow 的评测 job 现已整体删除，见本文件头部变更节）
    更是既不落盘也不上传 —— 波动台账（§14.3/§16.5 的观测信号）在这两路上静默缺失。
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


class TestEvalConcurrencySlot:
    """评测类 workflow 统一并发槽位（issue #3563：required 不再被评测饿死）。

    实测背景（2026-09-14 05:28Z）：13 个 in-progress 里 6 条是评测型 job
    （各自一套 docker 栈 + 真实 LLM），queued 60 个 run，**required 检查被饿死**，
    9 个 PR 全部 BLOCKED。

    ★ 落地形态是**两层**（与 AD 的 #3587 对 xiaobu-acceptance 的方案一致）：
      · **文件级** group 保持「按 PR」+ `cancel-in-progress: true`
        —— 同 PR 新 push 即时取消被取代的 run（省栈省 token；PR 迭代必需品）；
      · **job 级 / 文件级** group = 共享槽位 `eval-stack-global`（`cancel-in-progress: false`）
        —— 真正会起栈的 job 全局串行，required 不再被长任务饿死。
    **不要**把文件级 group 直接换成按 run 区分的槽位：那样新 push 必须排在旧 run 后面，
    丢掉 PR 迭代性，还让被取代的旧 run 跑完整套栈（最坏组合）。
    单一说明见 `docs/testing/eval-environments.md` §3.3。

    ⚠️ 槽位持有者**由三处变两处**（用户裁定 2′/4′，issue #4034）：
    `agent-behavior-eval.yml` 的 `behavior-eval` job（job 级槽位 `eval-stack-global-<persona>`）
    已随该 job **整体删除** —— 该 workflow 现在只有纯静态 `map` job，不起栈 ⇒ **不再占评测槽位**
    （它仍保留**文件级**按 PR 取消：那省的是 runner 分钟数，与槽位无关）。
    仍持有槽位的是 `xiaobu-acceptance.yml`（job 级）与 `post-deploy-eval.yml`（文件级）。
    """

    GROUP = "eval-stack-global"

    # 仍「真正起栈」、因而必须进共享槽位的 job 名（= **槽位持有者**白名单）
    # ⚠️ 原 `agent-behavior-eval.yml: behavior-eval` 项随该 job 删除而移除；
    #    「移出」由 `TestExcludedWorkflowHasNoStackMachinery` 的结构判据背书（零栈机件），
    #    不是为了让测试变绿 —— 起栈的 job 一旦回来，本表的判据必须把它重新覆盖。
    EVAL_JOB = {
        "xiaobu-acceptance.yml": "xiaobu-acceptance",
    }

    @pytest.mark.parametrize("workflow", ("xiaobu-acceptance.yml", "agent-behavior-eval.yml"))
    def test_file_level_group_keeps_per_pr_cancel(self, workflow: str):
        """文件级必须仍是**按 PR** + cancel-in-progress=true（PR 迭代的取消能力别丢）。

        （`agent-behavior-eval` 现在只剩静态 `map` job，但它仍由 PR 触发 —— 本判据对它
        同样成立：同一 PR 连推多次时，被取代的映射 run 该立刻作废。）
        """
        conc = _load_workflow(workflow).get("concurrency") or {}
        assert conc.get("cancel-in-progress") is True, (
            f"{workflow} 文件级 cancel-in-progress={conc.get('cancel-in-progress')!r}，必须为 True —— "
            "同一 PR 连推多次时，被取代的 run 应立刻作废（省栈省 token）"
        )
        assert self.GROUP not in str(conc.get("group") or ""), (
            f"{workflow} 把**文件级** group 换成了共享槽位（{conc.get('group')!r}）—— "
            "那样新 push 必须排在旧 run 后面：丢 PR 迭代性 + 旧 run 跑完整套栈 = 最坏组合。"
            "共享槽位要加在 **job 级**（见 test_eval_job_has_global_slot）"
        )
        assert "pull_request.number" in str(conc.get("group") or ""), (
            f"{workflow} 文件级 group 未按 PR 号分组（{conc.get('group')!r}）"
        )

    @pytest.mark.parametrize("workflow", tuple(EVAL_JOB))
    def test_eval_job_has_global_slot(self, workflow: str):
        """真正的并发约束在 **job 级**：起栈的 job 必须进共享槽位且不 cancel 正在跑的。"""
        job = (_jobs(workflow).get(self.EVAL_JOB[workflow])) or {}
        conc = job.get("concurrency") or {}
        assert str(conc.get("group") or "").startswith(self.GROUP), (
            f"{workflow}/{self.EVAL_JOB[workflow]} 的 job 级 concurrency.group="
            f"{conc.get('group')!r}，应以 {self.GROUP!r} 开头 —— "
            "没有它 = 跨 PR 无约束 → 并发建栈把栈启动从 3.4min 抬到 12min、required 被饿死"
        )
        assert conc.get("cancel-in-progress") is False, (
            f"{workflow}/{self.EVAL_JOB[workflow]} job 级 cancel-in-progress 必须为 False —— "
            "评测 job 的产物就是结论本身，cancel 正在跑的一条 = 那个 PR 永远拿不到该信号（#3526）"
        )

    def test_multi_persona_run_holds_the_slot_for_the_whole_run(self):
        """persona 腿「互相挤掉 pending」的风险现在落在**唯一的多 persona workflow** 上。

        （原判据 `test_behavior_eval_slot_is_per_persona` 的被测对象 —— `agent-behavior-eval`
        的 `behavior-eval` job 与它的 `eval-stack-global-<persona>` job 级槽位 —— 已随该 job
        整体删除；同一条 premise 由本测试在**新载体**上继续钉住，条目没有消失。）

        `post-deploy-eval` 的两条 persona 腿在**同一个 job 的 matrix** 里 ⇒ 槽位必须挂在
        **文件级**（一次 run 一把锁，两条腿同进同出），且 `cancel-in-progress: false`。
        反向变异：把槽位下沉到 job 级并按 persona 区分、或把 cancel-in-progress 改成 true ⇒ 红。
        """
        conc = _load_workflow("post-deploy-eval.yml").get("concurrency") or {}
        assert str(conc.get("group") or "").startswith(self.GROUP), (
            f"post-deploy-eval 的槽位不在文件级（group={conc.get('group')!r}）—— "
            "它的两条 persona 腿必须由**整个 run 一把锁**串行，否则另一 run 的 mibao 腿"
            "会把本 run 的 pending xiaobu 腿挤掉（丢一整个 persona 的结论而不自知）"
        )
        assert conc.get("cancel-in-progress") is False, (
            f"post-deploy-eval 文件级 cancel-in-progress={conc.get('cancel-in-progress')!r} —— "
            "长评测的产物就是结论本身，取消正在跑的一条 = 那个结论永久丢失（#3526）"
        )
        job = _jobs("post-deploy-eval.yml").get("eval") or {}
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        assert matrix.get("persona"), (
            f"post-deploy-eval 的 eval job 不是 persona matrix（matrix={matrix!r}）—— "
            "两条腿需要各自独立栈 + 独立新库（#3515），本测试的「一 run 一把锁」前提失效"
        )
        job_group = str((job.get("concurrency") or {}).get("group") or "")
        assert not job_group or job_group == str(conc.get("group")), (
            f"post-deploy-eval/eval 的 job 级槽位 {job_group!r} 与文件级 {conc.get('group')!r} "
            "不同源 —— 按腿区分的槽位会让两条腿分别入队，另一 run 的腿可趁机插进来挤掉 "
            "pending（原 per-persona 槽位要防的正是这件事）"
        )

    @pytest.mark.parametrize("workflow", tuple(EVAL_JOB))
    def test_slot_semantics_are_observable(self, workflow: str):
        """槽位语义必须写进 run summary —— 否则「排队/被取消」会被误读成「卡住/PR 有问题」。

        只对**持有槽位**的 workflow 断言：`agent-behavior-eval` 已不起栈、不占槽位，
        再要求它播报槽位语义就会变成一条永远为真（或要求它讲一个与己无关的机制）的空判据。
        """
        bodies = "\n".join((s.get("run") or "") for s in _steps(workflow))
        assert "GITHUB_STEP_SUMMARY" in bodies, (
            f"{workflow} 未把并发槽位语义写进 GITHUB_STEP_SUMMARY（可观测性要求）"
        )
        assert self.GROUP in bodies, f"{workflow} 的槽位说明未提到 group 名 {self.GROUP!r}"
        assert "排队" in bodies and "取消" in bodies, (
            f"{workflow} 的槽位说明必须同时讲清「排队」与「被取消」两种状态"
        )

    def test_both_slot_holders_share_the_same_slot_name(self):
        """两处槽位持有者用**同一个**槽位名 —— 只读断言，不改它。

        `post-deploy-eval` 是**文件级**槽位（它没有 PR 触发，不存在 PR 迭代问题），
        故它的文件级 group 就等于共享槽位名；`xiaobu-acceptance` 是 job 级。
        （第三个持有者 `agent-behavior-eval` 的 `eval-stack-global-<persona>` 已随
        `behavior-eval` job 删除 —— 带 persona 后缀的槽位名自此只应出现在沿革里。）
        """
        pde = _load_workflow("post-deploy-eval.yml").get("concurrency") or {}
        pde_group = str(pde.get("group") or "")
        assert pde_group, (
            "post-deploy-eval.yml 尚未加 concurrency 槽位（#3587 负责）—— 跨包一致性哨兵，"
            f"落地后应为 {self.GROUP!r}"
        )
        assert pde_group.startswith(self.GROUP), (
            f"post-deploy-eval 的槽位名 {pde_group!r} 与本 PR 的 {self.GROUP!r} 不一致 —— "
            "group 名是契约，改名等于把队列拆散（§3.3 注意事项 4）"
        )
        for wf, job_name in self.EVAL_JOB.items():
            group = str(((_jobs(wf).get(job_name) or {}).get("concurrency") or {}).get("group") or "")
            assert group.startswith(self.GROUP), (
                f"{wf}/{job_name} 的 job 级槽位 {group!r} 与 post-deploy-eval 不同源"
            )


class TestPrLayerIsSignalOnlyNotGate:
    """PR 层是**信号**而非门禁：零真实 LLM、零建 issue（用户裁定 2′/4′，issue #4034）。

    沿革（为什么原类 `TestBehaviorGateIsNonBlocking` 的判据全部失去被测对象）：
    2026-09-14~09-17 本 workflow 曾是 PR 门禁（规则命中 = 强信号：报告 + PR 评论 +
    自动开 issue、步骤恒 `exit 0` 不拦合并）。该评测 job 已**整体删除** ⇒
    「恒 exit 0 / 开 issue / issues: write / ruleFail 三元」这一组语义**在 PR 层不复存在**；
    但**不许**因此删掉了事 —— 本条把同一件事（LLM 结论不得在 PR 层被误读）钉在**新边界**上：

      a. **零 LLM**：没有 `id: eval` 步骤，任何步骤的命令体都不得出现 `local_runner.py`
         （PR 路径上的 LLM 调用数 = 0；同源判据见 `test_behavior_eval_pr_thin.py` 的触发白名单）；
      b. **零建 issue**：不得有 `issues.create(`（PR 评论走 `issues.createComment(`，
         那是 `pull-requests: write` 覆盖的 PR 评论，不是 issue）；
      c. **零死权限**：`permissions` 不得声明 `issues: *`（声明了却没有消费方 = §19.2 死权限）；
      d. **反假绿 + 可执行出口**：映射评论必须自己说清「没有跑任何 LLM」（否则「有映射结论」
         会被读成「评测通过」），并给出可复制的派发命令（裁定后它是 PR 上唯一输出）。
    """

    WORKFLOW = "agent-behavior-eval.yml"

    def _script_text(self) -> str:
        """步骤正文（name + run + with.script），**剥掉 `#` 注释行**。

        必须剥注释：该文件头部沿革**合法地**写着 `local_runner.py` / `eval_stack_seed.sh`
        （"曾经的评测怎么跑"），按原文搜会把沿革误判成"LLM 回来了"（假红）；
        而只看注释又等于不搜（假绿）—— 故判据落在"步骤正文"这一层。
        """
        chunks = []
        for s in _steps(self.WORKFLOW):
            chunks.append(s.get("name") or "")
            chunks.append(s.get("run") or "")
            chunks.append(str((s.get("with") or {}).get("script") or ""))
        text = "\n".join(chunks)
        return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))

    def test_no_eval_step_and_no_llm_runner(self):
        """(a) 零 LLM：没有评测步骤，也没有任何命令体调用 `local_runner.py`。"""
        ids = [s.get("id") for s in _steps(self.WORKFLOW)]
        assert "eval" not in ids, (
            f"出现 `id: eval` 评测步骤（{ids}）—— PR 层零 LLM 的形态是「没有评测步骤」，"
            "不是「评测步骤恒 exit 0」；真要在 PR 上恢复评测，必须先改裁定并同步 "
            "test_behavior_eval_pr_thin.py 的触发白名单"
        )
        body = self._script_text()
        assert "local_runner.py" not in body, (
            "步骤命令体里出现 `local_runner.py` —— PR 路径上的真实 LLM 调用数不再为 0"
            "（裁定 2′/4′ 的要点就是省钱：LLM 负责发现，不负责每个 PR）"
        )

    def test_no_issue_creation_step(self):
        """(b) 零建 issue：PR 层只发评论，不再有「规则命中失败 → 自动开 issue」这条链。"""
        scripts = "\n".join(str((s.get("with") or {}).get("script") or "")
                            for s in _steps(self.WORKFLOW))
        assert not re.search(r"issues\.create\s*\(", scripts), (
            "出现 `issues.create(` —— 建 issue 的步骤随评测 job 一并停用了（裁定 2′/4′）；"
            "若确认这是新加的必要步骤，须同时把 `issues: write` 补回来（#3497），"
            "并同步 test_workflow_issue_permissions.py 的口径"
        )

    def test_permissions_do_not_declare_issues_write(self):
        """(c) 零死权限：`issues: *` 不得声明（声明了却没有消费方 = §19.2「声明无消费」）。"""
        perms = _load_workflow(self.WORKFLOW).get("permissions") or {}
        assert "issues" not in perms, (
            f"permissions 声明了 issues={perms.get('issues')!r}，但本 workflow 已无任何 "
            "`issues.*` 调用（建 issue 的步骤随 job 删除）—— 这正是「声明无消费」的死权限："
            "读者会以为有人在建 issue，而权限本身也在暗示一条已停用的链路。"
            "真需要时应**同时**加回声明与消费方"
        )

    def test_pr_comment_declares_no_llm_ran_and_gives_dispatch_command(self):
        """(d) 反假绿 + 可执行出口：评论写明「没跑 LLM」，并给出派发命令。"""
        scripts = "\n".join(str((s.get("with") or {}).get("script") or "")
                            for s in _steps(self.WORKFLOW))
        assert "没有跑任何真实 LLM" in scripts, (
            "PR 评论没有明确写出「本次没有跑任何真实 LLM」—— 读者会把「有映射结论」读成"
            "「评测通过」（假绿）；「没跑」必须长得像「没跑」（§16.7 禁空跑 ③）"
        )
        assert "把本评论读成" in scripts and "评测通过" in scripts, (
            "PR 评论缺少「不要把本评论读成评测通过」这条显式否认 —— 只写「没跑」不够，"
            "要直接把误读路径封掉"
        )
        assert "尚未执行" in scripts, (
            "映射用例的**未执行**状态没出现在 PR 评论里（评论是裁定后 PR 上唯一的输出口，"
            "run summary 读者不一定会看）"
        )
        assert "gh workflow run post-deploy-eval.yml" in scripts, (
            "PR 评论没给出可复制的派发命令（`gh workflow run post-deploy-eval.yml …`）—— "
            "裁定后本评论是唯一输出，缺它读者只拿到「要跑」而拿不到「怎么跑」"
        )
        assert "purpose=debug" in scripts, (
            "派发命令未标注 `purpose=debug`（定点复现、**非判定用途**）—— 不标注会把 PR 层"
            "窄跑的结论误升为判定结论（#3769：判定用途只允许全库跑）"
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
