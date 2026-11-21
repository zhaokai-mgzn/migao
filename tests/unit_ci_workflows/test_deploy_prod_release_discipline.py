# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""生产发布腿（`.github/workflows/deploy-prod.yml`）的**发布线纪律**守卫 —— issue #8971。

## 为什么要有这条

用户 2026-11-21 裁定：「开发模式不能直接合并到主干，应该合并到一个特定的 release 分支，最后能发布的时候
部署机就指定发布这个分支」。**口径只有变成判据才守得住** —— 本仓已经因为「闸门没覆盖到对象」连出两次事故：

- #8966：盘上 `deploy.sh` 与仓库漂移 ⇒ nginx 渲染回落到测试域名（站点 21 分钟不可用）；
- #8969：蓝绿 green 不挂卷 ⇒ 预验证永久失败，而 parity 守卫的清单里恰好没有 `volumes`。

同族风险：**生产 workflow 允许发布 release 之外的提交** ⇒ `BUILD_SHA` 被烘焙进镜像、`/api/version`
照样一本正经地报出来 ⇒「线上到底跑的是哪版」再次不可信（原 P1-2 的形态）。所以这里钉三条：

1. **只认 release**：必须存在 `git merge-base --is-ancestor <target> origin/release` 且不满足即 `exit 1`；
2. **身份不许回退**：`BUILD_SHA` 只能来自该纪律步骤的输出，**不允许** `git rev-parse HEAD` 这种
   「拿当前 checkout 顶替」的退化路径（那正是让身份说谎的那一行）；
3. **部署后必须回读**：冒烟步骤跑 `deploy/scripts/prod-smoke.sh` 并把发布身份传进去（版本身份回读校验）。

## 判据形态

`judge_*` 纯函数（吃 workflow 文本，返回违规清单）⇒ 实例判据直接断言「真文件 0 违规」，
再造**注入式红证**（把关键行删掉 ⇒ 必须报违规）。不联网、不跑 workflow。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml"
SMOKE = REPO_ROOT / "deploy" / "scripts" / "prod-smoke.sh"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps(doc: dict) -> list[dict]:
    return doc["jobs"]["deploy-prod"]["steps"]


def _runs(doc: dict) -> str:
    """把每个 step 的 run 拼起来（保留 step 边界用 `\\n#---\\n` 分隔，便于按 step 判定）。"""
    return "\n#---\n".join((s.get("run") or "") for s in _steps(doc))


# ── 判据本体（纯函数，便于注入式红证）──────────────────────────────────────────
def judge_release_discipline(text: str) -> list[str]:
    """返回违规清单（空 = 通过）。吃 YAML 文本而不是 dict，红证可以直接改文本。"""
    bad: list[str] = []
    doc = yaml.safe_load(text)
    steps = _steps(doc)
    runs = _runs(doc)

    # ① 触发器：只许手动。push 触发 ⇒ 每次合 main 都会碰生产。
    triggers = doc.get(True) or doc.get("on") or {}
    if not isinstance(triggers, dict):
        bad.append("on 段不是映射（无法判定触发器）")
        triggers = {}
    if "workflow_dispatch" not in triggers:
        bad.append("缺 workflow_dispatch（生产发布必须是手动入口）")
    if "push" in triggers:
        bad.append("存在 push 触发器 —— 生产发布绝不能被 push 触发")

    # ② 发布线纪律步骤：必须真判「是否在 release 线上」，且不满足即失败。
    discipline = [s for s in steps if "merge-base --is-ancestor" in (s.get("run") or "")]
    if not discipline:
        bad.append("没有步骤执行 `git merge-base --is-ancestor` —— 无法保证目标 commit 在 release 线上")
    else:
        body = "\n".join(s.get("run") or "" for s in discipline)
        if "origin/release" not in body:
            bad.append("发布线判据里没有 `origin/release` —— 比对了别的分支")
        if not re.search(r"^\s*exit 1\s*$", body, re.M):
            bad.append("发布线判据不满足时没有 `exit 1` —— 判红不生效（只是打印）")

    # ③ 身份不许回退：禁止「不是 ref 就拿 HEAD 顶」。
    if re.search(r"rev-parse\s+HEAD", runs):
        bad.append("workflow 里出现 `git rev-parse HEAD` —— BUILD_SHA 可能退化成「当前 checkout」，身份会说谎")

    # ④ 部署步骤的 BUILD_SHA 必须来自纪律步骤的输出。
    deploy_steps = [s for s in steps if "swas-deploy-ci.sh" in (s.get("run") or "")]
    if not deploy_steps:
        bad.append("没有调用 deploy/scripts/swas-deploy-ci.sh 的步骤")
    else:
        env = deploy_steps[0].get("env") or {}
        sha_src = str(env.get("BUILD_SHA", ""))
        if "steps.rel.outputs.sha" not in sha_src:
            bad.append(f"BUILD_SHA 没有取自发布线纪律步骤（现在是「{sha_src}」）")

    # ⑤ 部署后必须回读：冒烟脚本 + 发布身份入参。
    smoke_steps = [s for s in steps if "prod-smoke.sh" in (s.get("run") or "")]
    if not smoke_steps:
        bad.append("没有跑 deploy/scripts/prod-smoke.sh —— 部署后不回读身份/域名，等于没验")
    else:
        env = smoke_steps[0].get("env") or {}
        if "REL_SHA" not in env:
            bad.append("冒烟步骤没把发布身份（REL_SHA）传进去 —— 版本身份无法回读")

    return bad


# ── 实例判据 ──────────────────────────────────────────────────────────────────
def test_deploy_prod_workflow_has_release_discipline():
    failures = judge_release_discipline(WORKFLOW.read_text(encoding="utf-8"))
    assert not failures, "deploy-prod.yml 发布线纪律被破坏：\n" + "\n".join(f"  - {f}" for f in failures)


def test_deploy_prod_only_manual_trigger():
    triggers = _load().get(True) or _load().get("on") or {}
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers


def test_deploy_prod_declares_production_environment():
    """生产发布必须挂在 `production` Environment 上（否则 required reviewers 那层保护不存在）。"""
    assert _load()["jobs"]["deploy-prod"]["environment"] == "production"


# ── 冒烟脚本本身：fail-closed（不可判定 ≠ 通过）──────────────────────────────
def test_smoke_script_is_fail_closed():
    text = SMOKE.read_text(encoding="utf-8")
    assert SMOKE.exists(), "prod-smoke.sh 不存在"
    assert "exit 1" in text, "冒烟失败时没有 exit 1"
    assert "exit 3" in text, "「不可判定」没有独立退出码（会被读成通过）"
    assert "migaozn" in text, "冒烟没有域名泄漏断言"


def test_smoke_script_checks_version_identity():
    """版本身份回读：冒烟必须比对 `/version` 的 sha 与发布身份，而不只是看 200。"""
    text = SMOKE.read_text(encoding="utf-8")
    assert "REL_SHA" in text
    assert '"sha"' in text or "grep -o" in text


# ── 注入式红证（判据必须真能红）──────────────────────────────────────────────
def test_red_proof_removing_ancestor_check_goes_red():
    original = WORKFLOW.read_text(encoding="utf-8")
    mutated = original.replace(
        'if ! git merge-base --is-ancestor "$TARGET" origin/release; then',
        'if false; then',
    )
    assert mutated != original, "注入未生效（锚点变了？）"
    assert judge_release_discipline(mutated), "删掉「是否在 release 线上」的判定却仍判绿"


def test_red_proof_head_fallback_goes_red():
    original = WORKFLOW.read_text(encoding="utf-8")
    # 注意：注入必须落在 `run: |` 块**内部**且保持缩进，否则 YAML 先炸，红的是语法不是判据
    mutated = original.replace(
        "          git fetch --quiet --tags --force origin",
        "          git fetch --quiet --tags --force origin\n          git rev-parse HEAD",
        1,
    )
    assert mutated != original
    assert any("rev-parse HEAD" in f for f in judge_release_discipline(mutated)), \
        "把身份退化成「当前 checkout」却仍判绿"


def test_red_proof_missing_smoke_goes_red():
    original = WORKFLOW.read_text(encoding="utf-8")
    mutated = original.replace("bash deploy/scripts/prod-smoke.sh", "echo skipped")
    assert mutated != original
    assert any("prod-smoke.sh" in f for f in judge_release_discipline(mutated)), \
        "把部署后冒烟删掉却仍判绿"
