# case_ids: MC-084
"""合并凭据 ⇄ push 触发面：让「用内置 token 合并 ⇒ 部署主触发被吞」**这一类**进不来（issue #6418）。

## 病（现取读数，2026-10-06；复算命令见下）

`automerge.yml` 用**内置** `secrets.GITHUB_TOKEN` 执行 `gh pr merge --auto` ⇒ 合并者恒为
`app/github-actions` ⇒ GitHub 的**反递归抑制**（GITHUB_TOKEN 引发的事件，除 `workflow_dispatch` /
`repository_dispatch` 外不创建新的 workflow run）吞掉该次合并产生的 `push` 事件 ⇒ 三条部署腿
（`deploy-frontend` / `deploy-admin-api` / `deploy-ai-agent-service`）的**主触发面**（`on.push`）
整条失效 —— `.github/workflows/deploy-reconcile.yml` 文件头自己写着「部署腿的主触发实际已失效」。

| 读数 | 现取证据 |
|---|---|
| 合并者 | 近 40 个已合并 PR：**38 个 `mergedBy=app/github-actions`**；自 2026-10-05T13:00Z 起 15/15 全是它 |
| push run | 同期 **0 条**；最近一次 = 2026-10-05T12:02:41Z |
| 有 push run 的提交是谁合的 | 最近 80 个 main commit 里只有 8 个有 push run，**8/8 都是人工合并**（`mergedBy=zhaokai-mgzn`） |

    gh pr list --state merged --limit 40 --json number,mergedBy
    gh run list --branch main --event push --limit 300 --json headSha,createdAt

⇒ 修法 = 合并这一步改用**非内置**凭据（`secrets.AUTOMERGE_PAT`）：合并者是 PAT 持有者而非 app
⇒ push 事件恢复触发。本文件的职责是**让这一类不再回来**。

## 判据

1. **实例判据**：`automerge.yml` 里每个会 arm merge 的 job 必须引用 `secrets.AUTOMERGE_PAT`，
   且**不得**把内置凭据（`secrets.GITHUB_TOKEN` / `github.token`）直接绑到 `GH_TOKEN`；
2. **类级元守卫（未登记即红）**：任何 job 的步骤文本里出现 arm 命令却不在**冻结登记表**
   `MERGE_JOBS_FROZEN` 里 ⇒ 红（新造一条会 arm 的路径必须同批进表并带上凭据口径）；
   登记表**双向**比对（登记的 job 不再 arm ⇒ 也红 —— 否则台账会腐烂成"给不存在的保护盖章"）；
3. **出声**：缺 secret 的回落必须**具名**（`::warning::` + 写明「抑制 ⇒ 部署主触发不恢复」），
   不许静默降级；
4. **红证 + 对照**：注入式（内存构造，不动磁盘）逐条证明会红；只加注释 ⇒ 不红。

## 有意不做（照实登记，§19.1）

- **不判**「`AUTOMERGE_PAT` 这枚 secret 在仓库里真的配了没有」—— 本判据只读仓内文件，零 `gh`、
  零网络（与 `test_publish_leg_fallback_surface.py` 同口径：运行期读数刻意不进判据）。
  运行期那一半由 arm step 自己打印的 actor 读数 + 缺 secret 时的 `::warning::` 承接。
- **不判**「PAT 的权限是否够」—— 那是 GitHub 侧的运行期行为（合并含 `.github/workflows/**`
  的 PR 需要 Workflows 权限），判据看不见。
"""
import json
import re
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
AUTOMERGE = WORKFLOWS_DIR / "automerge.yml"

#: 非内置凭据（合并者的身份与内置 token 不同 ⇒ 不触发 GitHub 反递归抑制）
PAT_REF = "secrets.AUTOMERGE_PAT"
#: 内置凭据的两种写法（都必须在 arm job 里**不被**绑到 GH_TOKEN）
BUILTIN_TOKEN_REFS = ("secrets.GITHUB_TOKEN", "github.token")
#: arm 命令的形态（判「哪些 job 会 arm」用这个，而不是 job 名 —— 名字会漂，形态不会）
ARM_MARKERS = ("gh pr merge", "MERGE_CMD_FAILED")
#: 🔒 冻结登记表：会 arm auto-merge 的 job（**只许缩短**；新增一条 arm 路径必须同批改这里 ——
#:    判据在 `test_registry_is_bidirectional`，两侧不一致即红）
MERGE_JOBS_FROZEN = ("enable-auto-merge", "enable-auto-merge-bot-safe")
#: 缺 secret 时回落告警的**具名**要素（少一个 ⇒ 静默降级，判红）
FALLBACK_WARN_MARKER = "AUTOMERGE_PAT 未配置"


def workflow_text():
    return AUTOMERGE.read_text(encoding="utf-8")


def workflow_doc():
    return yaml.safe_load(workflow_text())


def _job_text(job):
    return json.dumps(job, ensure_ascii=False)


def arm_jobs(doc):
    """会 arm auto-merge 的 job：`{job 名: job}` —— 按**形态**（含 arm 命令）取，不按名字。"""
    out = {}
    for name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        text = _job_text(job)
        if any(marker in text for marker in ARM_MARKERS):
            out[name] = job
    return out


def _step_env(job):
    env = {}
    for step in job.get("steps") or []:
        if isinstance(step, dict) and isinstance(step.get("env"), dict):
            env.update(step["env"])
    return env


def credential_problems(doc):
    """判定本体（纯函数：喂**解析后的 doc**，红证靠内存构造）。返回问题清单（空 = 绿）。"""
    problems = []
    arm = arm_jobs(doc)
    if not arm:
        # 防空断言：一个 arm job 都没识别到 ⇒ 判据没在判任何东西
        problems.append("一个 arm job 都没识别到 ⇒ 判据空跑（形态匹配已过期，见 ARM_MARKERS）")
        return problems
    missing = sorted(set(MERGE_JOBS_FROZEN) - set(arm))
    extra = sorted(set(arm) - set(MERGE_JOBS_FROZEN))
    if missing:
        problems.append(
            f"登记表里的 arm job 不再 arm 了：{missing} ⇒ 同批改 MERGE_JOBS_FROZEN"
            "（台账不许给不存在的保护盖章）"
        )
    if extra:
        problems.append(
            f"出现**未登记**的 arm job：{extra} ⇒ 新造一条会 arm auto-merge 的路径必须同批登记"
            "并带上「非内置凭据 + 显式回落」口径"
        )
    for name, job in sorted(arm.items()):
        text = _job_text(job)
        env = _step_env(job)
        if PAT_REF not in text:
            problems.append(
                f"{name}：没引用 `{PAT_REF}` —— 用内置 token 合并 ⇒ 合并者恒为 app/github-actions"
                " ⇒ push 被 GitHub 反递归抑制吞掉 ⇒ 三条部署腿的主触发不恢复（#6418）"
            )
        gh_token = str(env.get("GH_TOKEN", ""))
        if gh_token and any(ref in gh_token for ref in BUILTIN_TOKEN_REFS):
            problems.append(
                f"{name}：把内置凭据直接绑到 `GH_TOKEN`（env.GH_TOKEN={gh_token}）"
                " —— 这正是 #6418 的缺陷形态（内置 token 合并 ⇒ push 面失效）"
            )
        if "FALLBACK_TOKEN" not in env:
            problems.append(
                f"{name}：缺显式回落声明（`env.FALLBACK_TOKEN`）—— 缺 secret 时既要仍能 arm"
                "（不卡合并），又必须**具名出声**，不许静默降级"
            )
        if FALLBACK_WARN_MARKER not in text or "::warning::" not in text:
            problems.append(
                f"{name}：缺「未配置 ⇒ 回落」的具名告警（要 `::warning::` 且写明"
                f"「{FALLBACK_WARN_MARKER}」与抑制后果）"
            )
    return problems


# ══════════════════════════════════════════════════════════════════════════════
class TestRealWorkflow:
    """真语料：当前 `automerge.yml` 必须零问题（这是"修复真的落地了"的那一半）。"""

    def test_real_workflow_has_no_problems(self):
        problems = credential_problems(workflow_doc())
        assert problems == [], "automerge.yml 合并凭据判据未通过：\n  - " + "\n  - ".join(problems)

    def test_registry_matches_reality(self):
        """登记表 ⇄ 现取**双向**相等：少一条（job 名改了/arm 被删）或多一条（新 arm 路径）都红。"""
        arm = set(arm_jobs(workflow_doc()))
        assert arm == set(MERGE_JOBS_FROZEN), (
            f"冻结登记表 {sorted(MERGE_JOBS_FROZEN)} ≠ 现取会 arm 的 job {sorted(arm)}"
        )

    def test_both_arm_jobs_are_covered(self):
        """反空跑锚点：真文件里必须**至少**取到 2 条 arm 路径（防形态匹配静默失效）。"""
        assert len(arm_jobs(workflow_doc())) >= 2

    def test_pat_reference_appears_in_both_jobs(self):
        for name, job in arm_jobs(workflow_doc()).items():
            assert PAT_REF in _job_text(job), f"{name} 未引用非内置凭据"


class TestRedProofs:
    """注入式红证：每条都自证「注入生效 + 判据真红」，另附**对照读数**（只加注释 ⇒ 不红）。"""

    def test_baseline_is_green_before_injection(self):
        """注入前的基线读数（防「怎么注入都不红」的空断言）。"""
        assert credential_problems(workflow_doc()) == []

    def test_removing_pat_reference_is_caught(self):
        doc = workflow_doc()
        step = doc["jobs"]["enable-auto-merge"]["steps"][1]
        assert "AUTOMERGE_PAT" in step["env"]  # 自证注入坐标对
        del step["env"]["AUTOMERGE_PAT"]
        problems = credential_problems(doc)
        assert any("没引用" in p for p in problems), problems

    def test_binding_builtin_token_to_gh_token_is_caught(self):
        doc = workflow_doc()
        job = doc["jobs"]["enable-auto-merge"]
        job["steps"][1]["env"]["GH_TOKEN"] = "${{ secrets.GITHUB_TOKEN }}"
        problems = credential_problems(doc)
        assert any("绑到 `GH_TOKEN`" in p for p in problems), problems

    def test_removing_fallback_declaration_is_caught(self):
        doc = workflow_doc()
        del doc["jobs"]["enable-auto-merge-bot-safe"]["steps"][-1]["env"]["FALLBACK_TOKEN"]
        problems = credential_problems(doc)
        assert any("缺显式回落声明" in p for p in problems), problems

    def test_removing_fallback_warning_is_caught(self):
        doc = workflow_doc()
        run = doc["jobs"]["enable-auto-merge"]["steps"][1]["run"]
        doc["jobs"]["enable-auto-merge"]["steps"][1]["run"] = run.replace(
            FALLBACK_WARN_MARKER, "凭据缺失")
        problems = credential_problems(doc)
        assert any("具名告警" in p for p in problems), problems

    def test_unregistered_new_arm_job_is_caught(self):
        doc = workflow_doc()
        doc["jobs"]["sneaky-arm"] = {
            "runs-on": "ubuntu-latest",
            "steps": [{"run": "gh pr merge 1 --auto"}],
        }
        problems = credential_problems(doc)
        assert any("未登记" in p and "sneaky-arm" in p for p in problems), problems

    def test_deleting_all_arm_jobs_is_caught(self):
        """删光 ⇒ 红（fail-closed：「没东西可判」不是通过）。"""
        doc = workflow_doc()
        for name in list(doc["jobs"]):
            doc["jobs"][name] = {"runs-on": "ubuntu-latest", "steps": [{"run": "echo nope"}]}
        problems = credential_problems(doc)
        assert any("空跑" in p for p in problems), problems

    def test_comment_only_change_is_not_red(self):
        """对照读数：往 YAML 里加注释（含 PAT 名与 arm 命令字样）**不**得判红。"""
        text = workflow_text()
        injected = (
            "# 说明：合并凭据走 secrets.AUTOMERGE_PAT；缺它时回落；旧写法 gh pr merge 会被吞\n"
            + text
        )
        assert injected != text
        assert credential_problems(yaml.safe_load(injected)) == []

    def test_arm_marker_matches_the_real_command(self):
        """形态锚点自证：真文件里确实有 `gh pr merge` —— 否则上面的 `arm_jobs` 会静默空跑。"""
        assert re.search(r"gh pr merge", workflow_text())
