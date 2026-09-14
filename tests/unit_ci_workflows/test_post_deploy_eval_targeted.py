"""
部署后评测「diff 定向 + 宽爆炸半径回退全量 + 每 3 天全量」守卫（issue #3654，用户裁定 2026-09-14）。

背景：部署后全量是 CI 真实 LLM 成本主因之一（近 2.5h ≈ ¥135-295）。本包把部署后评测改为：
  · 部署触发（workflow_run）→ `git diff <被评SHA>^ <被评SHA>` 驱动定向：
    diff → case_ids（复用 #3502 的 behavior_mapping 映射表）+ fast（--max-retries 0）；
  · 三个保守边界**必须回退全量**（宁多跑不少跑，安全优先）：
      ① 宽爆炸半径文件（base_skill/nodes/references/registry/factory/app/graph/**）——
         共享/行为层，映射不精确，命中即全量（**显式硬规则**，不只兜底）；
      ② 无 AI 行为文件（docs/前端等）—— case_ids 空 → 全量兜底（现状）；
      ③ 有 AI 行为文件但映射表未覆盖（default_net）—— 部署后拦截是硬门禁，
         不走 PR 层「default_net 只报告」的语义 → 全量。
  · 全量改**每 3 天 schedule cron**（tier 恒 normal）；schedule 抑制 = "main 未动即跳过"。
  · 不破坏：#3587 抑制（fail-open + 链接链）、eval-stack-global 槽位、
    completion_verdict 判定、失败建 issue（去重）、report-only 语义
    （后者由 test_post_deploy_eval_supersede.py 的既有类继续锁，本文件不再重复）。

本测试分组：
  A. compute_mode 纯函数（三形态推演 + 保守边界 + persona 过滤）；
  B. 宽爆炸半径清单锁定（变异守卫：从清单删文件 → 本测试红，证明清单被锁住）；
  C. CLI 接线（真跑脚本 + 真实用例库 persona 过滤，零 LLM）；
  D. workflow YAML 静态接线（schedule 触发 / 定向步骤只挂 workflow_run / Run 步骤消费 mode）。
"""
# case_ids: MC-012, OR-016, AS-007, PR-019
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / ".github" / "scripts"
SCRIPT = SCRIPTS_DIR / "eval_targeted_cases.py"
WORKFLOW = "post-deploy-eval.yml"

# ── 宽爆炸半径清单的**锁定内容**（变异守卫：清单被删条目 → 本组红）──
# 与脚本内 WIDE_BLAST_RADIUS_PREFIXES 保持一致；新增共享层文件时两边都要登记。
REQUIRED_WIDE_BLAST = (
    "backend/ai-agent-service/app/graph/skills/base_skill.py",  # 守卫/共享 Skill 基类
    "backend/ai-agent-service/app/graph/nodes.py",              # 图节点路由
    "backend/ai-agent-service/app/graph/skills/references/",    # Skill 共享示例库
    "backend/ai-agent-service/app/tools/registry.py",           # 工具注册表
    "backend/ai-agent-service/app/llm/factory.py",              # LLM 工厂
    "backend/ai-agent-service/app/graph/",                      # graph 全家兜底
)

# 与 local_runner 同源的 persona 可执行集（纯函数测试用**代表性子集**即可——
# 关键是对应 persona 是否包含/排除哪些映射输出；真实集由 C 组 CLI 测试锁定）。
# 现实（2026-09-14 实测 load_case_dicts + select_cases_for_persona）：
#   · 映射表输出的用例大多是**双端**（persona 未声明）→ mibao 全收、xiaobu 经
#     #3266 工具集/语义过滤后多数被排除（OR-016/AS-007/PR-019/PR-020 均不在 xiaobu 集）；
#   · CH-010 是显式 xiaobu 专属 → 只在 xiaobu 集；
#   · CH-021/CH-022 有 skip_reason → 两端都不在可执行集（映射可命中但被本端过滤掉）。
MIBAO_CASE_IDS = {
    "OR-016", "AS-007", "PR-019", "PR-020", "CH-003", "CH-008", "CH-013",
    "CH-014", "CH-015", "CH-019", "CH-026", "CU-003", "CU-004", "DA-004",
    "DF-011", "DF-012", "FN-001", "HR-001", "HR-005", "PG-013", "PP-002",
    "PP-006", "ST-003", "ST-005",
}
XIAOBU_CASE_IDS = {
    "CH-010", "OR-012", "OR-017", "CH-024", "KN-001",  # 显式 xiaobu + 过工具集过滤的双端
}

# 真实管道正则（与 test_step_exit_code_propagation.py 同款：排除 `||`）
_REAL_PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)")


def _load_script():
    """加载 eval_targeted_cases.py 模块（脚本自带 sys.path 注入，零第三方依赖）。"""
    spec = importlib.util.spec_from_file_location("eval_targeted_cases", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_workflow() -> dict:
    d = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / WORKFLOW).read_text(encoding="utf-8")) or {}
    # PyYAML 1.1 把 YAML 1.2 的 `on:` 键解析成布尔 True（与 test_close_linked_issues_chain 同款兼容）
    d["on"] = d.get("on") or d.get(True) or {}
    return d


def _eval_job() -> dict:
    return _load_workflow()["jobs"]["eval"]


def _steps() -> list:
    return _eval_job()["steps"]


def _named(*keywords) -> list:
    return [s for s in _steps() if any(k in (s.get("name") or "") for k in keywords)]


# ════════════════════════════════════════════════════════════════════════════
# A. compute_mode 纯函数：三形态推演 + 保守边界 + persona 过滤
# ════════════════════════════════════════════════════════════════════════════
class TestComputeMode:
    def setup_method(self):
        self.mod = _load_script()

    # ── 推演 ①：diff 只改某工具文件 → 跑对应 case_ids（fast）──
    def test_order_tool_change_targets_or016_for_mibao(self):
        mode, case_ids, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/tools/order_create.py"], "mibao", MIBAO_CASE_IDS)
        assert mode == "targeted", reason
        assert case_ids == ["OR-016"], case_ids
        assert "命中规则" in reason

    def test_order_tool_change_uses_default_net_for_xiaobu(self):
        """同一次部署的 xiaobu 腿：映射出的 OR-016 不在本端可执行集（#3266 过滤）
        → 跑本端默认网子集（最窄主链路信号）。

        ⚠️ 期望集随 #3725 变化：默认网补进 OR-017（C 端加工项闭环）后，本端子集
        = `DEFAULT_BEHAVIOR_CASES ∩ xiaobu 可执行集` = {CH-010, OR-017}（两条都在注入集里）。
        """
        mode, case_ids, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/tools/order_create.py"], "xiaobu", XIAOBU_CASE_IDS)
        assert mode == "targeted", reason
        assert case_ids == ["CH-010", "OR-017"], case_ids  # = DEFAULT_BEHAVIOR_CASES ∩ xiaobu 集
        assert "默认网子集" in reason

    def test_aftersales_change_default_net_for_xiaobu(self):
        """售后改动映射到 AS-007，但 AS-007 不在 xiaobu 可执行集 → 本端默认网子集
        （#3725 后该子集含 OR-017）。
        注：diff 文件故意用 `app/tools/aftersales_tool.py`（不在 app/graph/ 下，避开宽爆炸半径）。"""
        mode, case_ids, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/tools/aftersales_tool.py"],
            "xiaobu", XIAOBU_CASE_IDS)
        assert mode == "targeted", reason
        assert case_ids == ["CH-010", "OR-017"], case_ids
        assert "默认网子集" in reason

    def test_aftersales_change_targets_as007_for_mibao(self):
        """同一售后改动对 mibao：AS-007 在 B 端可执行集（双端用例）→ 直接定向。"""
        mode, case_ids, _ = self.mod.compute_mode(
            ["backend/ai-agent-service/app/tools/aftersales_tool.py"],
            "mibao", MIBAO_CASE_IDS)
        assert mode == "targeted" and case_ids == ["AS-007"], case_ids

    def test_multi_file_diff_union_sorted(self):
        """多文件命中多条规则 → 并集 + 字典序稳定排序。"""
        files = ["backend/ai-agent-service/app/tools/order_create.py",
                 "backend/ai-agent-service/app/tools/order_query.py"]
        mode, case_ids, _ = self.mod.compute_mode(files, "mibao", MIBAO_CASE_IDS)
        assert mode == "targeted"
        assert case_ids == ["OR-016"], case_ids  # 并集去重（两条规则都指向 OR-016）

    # ── 推演 ②：diff 含宽爆炸半径文件 → 必须回退全量（显式硬规则）──
    def test_base_skill_forces_full(self):
        mode, case_ids, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/graph/skills/base_skill.py"], "mibao", MIBAO_CASE_IDS)
        assert mode == "full", reason
        assert case_ids == [], case_ids
        assert "宽爆炸半径" in reason

    def test_nodes_forces_full(self):
        mode, _, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/graph/nodes.py"], "xiaobu", XIAOBU_CASE_IDS)
        assert mode == "full", reason

    def test_references_forces_full(self):
        mode, _, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/graph/skills/references/order_examples.md"],
            "mibao", MIBAO_CASE_IDS)
        assert mode == "full", reason

    def test_registry_forces_full(self):
        mode, _, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/tools/registry.py"], "mibao", MIBAO_CASE_IDS)
        assert mode == "full", reason

    def test_factory_forces_full(self):
        mode, _, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/llm/factory.py"], "mibao", MIBAO_CASE_IDS)
        assert mode == "full", reason

    def test_wide_blast_wins_over_mapping_rules(self):
        """宽爆炸半径优先于规则命中：即使同一 diff 里还有 order_create.py。"""
        files = ["backend/ai-agent-service/app/tools/order_create.py",
                 "backend/ai-agent-service/app/graph/nodes.py"]
        mode, _, reason = self.mod.compute_mode(files, "mibao", MIBAO_CASE_IDS)
        assert mode == "full", reason

    # ── 推演 ③：diff 是 docs/cases/前端 → case_ids 空 → 全量兜底 ──
    def test_docs_only_diff_falls_back_full(self):
        mode, case_ids, reason = self.mod.compute_mode(
            ["docs/testing/eval-environments.md", "frontend/admin-web/package.json"],
            "mibao", MIBAO_CASE_IDS)
        assert mode == "full", reason
        assert case_ids == [], case_ids
        assert "无 AI 行为文件" in reason

    # ── 保守边界：映射表未覆盖的域（default_net）→ 全量 ──
    def test_unmapped_ai_file_falls_back_full(self):
        """有 AI 行为文件但无规则命中（如 utils/logger、config.py）→ 全量（§13.2 盲区）。
        注意：部署层**不用** PR 层的默认网（PR 层 default_net=4 条只报告；部署后拦截是
        硬门禁，口径从严：宁多跑不少跑）。"""
        mode, case_ids, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/utils/logger.py"], "mibao", MIBAO_CASE_IDS)
        assert mode == "full", reason
        assert case_ids == [], case_ids
        assert "映射表未覆盖" in reason

    # ── 其它兜底 ──
    def test_empty_diff_falls_back_full(self):
        mode, _, reason = self.mod.compute_mode([], "mibao", MIBAO_CASE_IDS)
        assert mode == "full", reason
        assert "空 diff" in reason

    def test_persona_with_no_cases_falls_back_full(self):
        """规则命中 + 本端既无对应用例又无默认网子集（用例库异常）→ 全量。"""
        mode, _, reason = self.mod.compute_mode(
            ["backend/ai-agent-service/app/tools/order_create.py"], "mibao", set())
        assert mode == "full", reason


# ════════════════════════════════════════════════════════════════════════════
# B. 宽爆炸半径清单锁定（变异守卫）
# ════════════════════════════════════════════════════════════════════════════
class TestWideBlastRadiusListLocked:
    """清单本身是护栏：任何条目被删 → 本组红（证明清单没有被悄悄放宽）。"""

    def setup_method(self):
        self.mod = _load_script()

    def test_required_entries_present(self):
        missing = [p for p in REQUIRED_WIDE_BLAST
                   if p not in self.mod.WIDE_BLAST_RADIUS_PREFIXES]
        assert not missing, (
            f"宽爆炸半径清单缺少以下条目（从清单删掉 = 该文件改动不再强制全量 = "
            f"共享层回归漏网）：{missing}"
        )

    def test_entries_are_repo_relative_prefixes(self):
        """清单必须是仓根相对路径前缀（否则 _hits_wide_blast 的 startswith 匹配失效）。"""
        for p in self.mod.WIDE_BLAST_RADIUS_PREFIXES:
            assert p.startswith("backend/ai-agent-service/app/"), (
                f"清单条目 {p!r} 不在 ai-agent 本体源码路径下——前缀匹配会误伤/漏配"
            )
            assert not p.startswith("/"), f"清单条目 {p!r} 必须是相对路径"

    def test_graph_prefix_covers_nodes_and_base_skill(self):
        """`app/graph/` 兜底条目必须覆盖 nodes.py 与 base_skill.py（否则删细条目即漏网）。"""
        assert "backend/ai-agent-service/app/graph/" in self.mod.WIDE_BLAST_RADIUS_PREFIXES


# ════════════════════════════════════════════════════════════════════════════
# C. CLI 接线（真跑脚本 + 真实用例库 persona 过滤，零 LLM）
# ════════════════════════════════════════════════════════════════════════════
class TestTargetedCliWiring:
    """脚本 CLI 端到端：diff 文件列表 → mode/case_ids（persona 过滤走真实用例库）。"""

    def _run(self, diff_lines: list, persona: str):
        diff_file = Path(__file__).parent / f"_diff_{persona}.txt"
        diff_file.write_text("\n".join(diff_lines) + "\n", encoding="utf-8")
        try:
            r = subprocess.run(
                [sys.executable, str(SCRIPT), "--diff-file", str(diff_file),
                 "--persona", persona, "--repo-root", str(REPO_ROOT)],
                capture_output=True, text=True, timeout=120)
            assert r.returncode == 0, f"选择器退出码非 0（应恒 0/fail-open）：\n{r.stdout}\n{r.stderr}"
            return r.stdout
        finally:
            diff_file.unlink(missing_ok=True)

    def test_order_change_mibao_targeted(self):
        out = self._run(["backend/ai-agent-service/app/tools/order_create.py"], "mibao")
        assert "mode=targeted" in out, out
        assert "case_ids=OR-016" in out, out

    def test_order_change_xiaobu_default_net(self):
        out = self._run(["backend/ai-agent-service/app/tools/order_create.py"], "xiaobu")
        assert "mode=targeted" in out, out
        assert "case_ids=CH-010,OR-017" in out, out  # 真实 xiaobu 集：默认网子集（#3725 后含 OR-017）

    def test_order_change_mibao_targeted_through_cli(self):
        out = self._run(["backend/ai-agent-service/app/tools/order_create.py"], "mibao")
        assert "mode=targeted" in out, out
        assert "case_ids=OR-016" in out, out

    def test_base_skill_full_via_cli(self):
        out = self._run(["backend/ai-agent-service/app/graph/skills/base_skill.py"], "mibao")
        assert "mode=full" in out, out

    def test_unmapped_ai_file_full_via_cli(self):
        out = self._run(["backend/ai-agent-service/app/config.py"], "mibao")
        assert "mode=full" in out, out

    def test_git_diff_derivation_uses_parent_sha(self):
        """--sha 模式：git diff <sha>^ <sha> 必须真的取到父提交的 diff（当前分支 HEAD）。"""
        head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        out = subprocess.run(
            [sys.executable, str(SCRIPT), "--sha", head, "--persona", "mibao",
             "--repo-root", str(REPO_ROOT)],
            capture_output=True, text=True, timeout=120).stdout
        assert "mode=" in out and "reason=" in out, out
        # HEAD 的相对父 diff 一定存在（本测试文件本身就是未提交改动）→ 必有输出
        assert "（空 diff" not in out, f"HEAD 被当成首提交（取父 diff 失败）：{out}"

    def test_sha_without_parent_falls_back_full(self):
        """首提交/取不到父的 SHA → 空 diff = 全量兜底（绝不崩溃）。"""
        out = subprocess.run(
            [sys.executable, str(SCRIPT), "--sha", "0" * 40, "--persona", "mibao",
             "--repo-root", str(REPO_ROOT)],
            capture_output=True, text=True, timeout=120).stdout
        assert "mode=full" in out, out
        assert "空 diff" in out, out

    def test_writes_github_output(self, tmp_path):
        out_file = tmp_path / "out.txt"
        env = dict(os.environ)
        env["GITHUB_OUTPUT"] = str(out_file)
        diff_file = tmp_path / "diff.txt"
        diff_file.write_text("backend/ai-agent-service/app/tools/order_create.py\n",
                             encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--diff-file", str(diff_file), "--persona", "mibao",
             "--repo-root", str(REPO_ROOT)],
            capture_output=True, text=True, timeout=120, env=env)
        assert r.returncode == 0
        content = out_file.read_text(encoding="utf-8")
        assert "mode=targeted" in content, content
        assert "case_ids=OR-016" in content, content

    def test_writes_github_output(self, tmp_path):
        out_file = tmp_path / "out.txt"
        env = dict(os.environ)
        env["GITHUB_OUTPUT"] = str(out_file)
        diff_file = tmp_path / "diff.txt"
        diff_file.write_text("backend/ai-agent-service/app/tools/order_create.py\n",
                             encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--diff-file", str(diff_file), "--persona", "mibao",
             "--repo-root", str(REPO_ROOT)],
            capture_output=True, text=True, timeout=120, env=env)
        assert r.returncode == 0
        content = out_file.read_text(encoding="utf-8")
        assert "mode=targeted" in content, content
        assert "case_ids=OR-016" in content, content


# ════════════════════════════════════════════════════════════════════════════
# D. workflow YAML 静态接线
# ════════════════════════════════════════════════════════════════════════════
class TestWorkflowTargetedWiring:
    def test_schedule_trigger_every_3_days_at_0300(self):
        sched = (_load_workflow().get("on") or {}).get("schedule") or []
        crons = [s.get("cron", "") for s in sched]
        assert any("*/3" in c for c in crons), f"缺少每 3 天 cron：{crons}"
        assert any(c.startswith("0 3 ") for c in crons), (
            f"时刻应选低流量 03:00（避开部署/合并高峰）：{crons}"
        )

    def test_eval_job_if_keeps_deploy_schedule_guard_and_adds_own_schedule(self):
        cond = str(_eval_job().get("if") or "")
        assert "github.event_name == 'schedule'" in cond, (
            "本 workflow 自己的 schedule 触发必须放行（否则每 3 天全量永不跑）"
        )
        assert "workflow_run.event != 'schedule'" in cond, (
            "deploy workflow 的 20 分钟对账定时防呆被删（#2935）——两种 schedule 必须靠事件名区分"
        )

    def test_target_step_only_for_workflow_run(self):
        steps = _named("定向用例选择")
        assert len(steps) == 1
        step = steps[0]
        assert step.get("id") == "target", "定向步骤缺 id=target（Run 步骤引用不到）"
        cond = step.get("if") or ""
        assert "github.event_name == 'workflow_run'" in cond, (
            f"定向步骤 if={cond!r} —— 必须只对部署自动门禁生效"
            "（schedule=每 3 天全量恒 full；dispatch=手动 inputs 优先）"
        )

    def test_target_step_runs_before_any_cost_step(self):
        idx = next(i for i, s in enumerate(_steps()) if s.get("id") == "target")
        cost = next(i for i, s in enumerate(_steps())
                    if "Start local stack" in (s.get("name") or ""))
        assert idx < cost, "定向用例选择必须在栈构建之前（它是省成本决策，不是评测步骤）"

    def test_run_step_consumes_targeted_mode_with_fast(self):
        run_step = _named("（真实 LLM）")[0]
        env = run_step.get("env") or {}
        assert "TARGET_MODE" in env and "TARGET_CASE_IDS" in env, (
            "Run 步骤未消费定向步骤输出（TARGET_MODE/TARGET_CASE_IDS）"
        )
        run = run_step.get("run") or ""
        assert "--max-retries 0" in run, "定向档必须 fast（--max-retries 0），否则省不下重试成本"
        assert "TARGET_CASE_IDS" in run
        assert "MODE=\"${TARGET_MODE:-full}\"" in run or 'MODE="${TARGET_MODE:-full}"' in run, (
            "定向未命中时必须回落全量（schedule/dispatch 下 steps.target 为空）"
        )
        assert "|| 'normal'" in run, "schedule 触发 tier 必须回落 normal（全量档）"

    def test_run_step_has_no_real_pipes(self):
        """Run 步骤不得引入真实管道：全仓管道规模守卫（TestPipefailPatternInventory）
        已顶在上限，新增竖线会把无关的退出码传播守卫顶红。"""
        run_step = _named("（真实 LLM）")[0]
        run = run_step.get("run") or ""
        assert not _REAL_PIPE_RE.search(run), (
            "Run 步骤出现真实管道（单竖线）——会顶爆全仓管道规模守卫，且本步不需要管道"
        )

    def test_supersede_step_passes_mode_to_script(self):
        step = _named("抑制判定")[0]
        env = step.get("env") or {}
        mode = str(env.get("MODE", ""))
        assert "github.event_name == 'schedule'" in mode and "schedule" in mode, (
            f"抑制判定未区分 schedule/deploy 两种判据（MODE={mode!r}）"
        )

    def test_schedule_never_gets_targeted(self):
        """schedule → 定向步骤被跳过 → TARGET_MODE 空 → Run 步骤回落全量：
        每 3 天全量必须跑 tier=normal 全量双 persona（覆盖部署定向漏掉的部分）。"""
        target = _named("定向用例选择")[0]
        assert "workflow_run" in (target.get("if") or ""), "定向步骤未限制 workflow_run"
        # Run 步骤的 TIER 表达式在无 inputs（schedule）时回落 normal
        run_step = _named("（真实 LLM）")[0]
        assert "github.event.inputs.tier || 'normal'" in (run_step.get("run") or "")
