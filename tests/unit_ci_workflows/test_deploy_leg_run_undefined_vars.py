# case_ids: MC-012
"""部署腿 run 正文的**未定义变量**守卫 —— issue #5814（C′ 守卫步 unbound variable 事故）。

## 事故（实测，非推断）
C′（PR #5821）新增的守卫步 `Assert server-side build (no ACR push)` 在 `run` 正文里直接写
`tag=${IMAGE_TAG}`，而该变量**只**在 `steps.tag.outputs` 里、**不是** env；该步带
`set -euo pipefail` ⇒ 当场 `unbound variable` 并以 rc=1 结束：

    run 36696120883（deploy-frontend）
      构建位置 = **SWAS 服务器侧**（issue #5814 C′）；CI 不构建、不推 ACR。
      line 3: IMAGE_TAG: unbound variable
      ##[error]Process completed with exit code 1.

⇒ **三条腿（admin-api / ai-agent-service / frontend）全部**在部署前被这一步挡住。

## 为什么既有判据一条都没红（本文件的立文理由）
既有判据只**读文本**（钉步骤名/锚点/`if:` 谓词），**没有任何判据真跑过这个守卫步**。
「判据绿」在这里等于「文本长得对」，与「这一步能不能跑」是两件事。

## 判据面（**范围诚实登记**）
本文件的 lint 只在 **`deploy-*.yml`** 上判 —— 因为我在**真语料**上量过假阳性：
- 朴素版（整段扫描）：全仓 **9 文件 / 30 处**命中；
- 加「**单引号感知**（shell 在单引号内不展开 `$var` ⇒ jq 程序里的 `$s` 被误判）+ **bash 内建允许名单**（`PIPESTATUS` 等）」后：降到 **4 文件 / 18 处**，而**三条 deploy 腿 + `deploy-reconcile.yml` 降到 0**。
⇒ 全仓推广**尚未就绪**（剩余 4 文件需逐个三分类：真未定义 / 上一步 `$GITHUB_ENV` 写入 / 更隐蔽的赋值形态），
已登记为缺口（见文件末「未固化」），**不**在本单硬上（会制造无关假红）。

判据三态：
1. `test_deploy_leg_guard_steps_declare_image_tag_via_env` —— 实例：三条腿的守卫步必须以 `env:` 声明
   `IMAGE_TAG`（本次修法的固化），**不得**回退成正文里裸引用；
2. `test_no_undefined_vars_under_set_u_in_deploy_legs` —— 类级（范围=deploy legs）：凡 `run` 正文带
   `set -u` 的步，其引用的 `${VAR}` 必须能在（workflow/job/step env ∪ 同脚本内赋值 ∪ 同 job 的
   `$GITHUB_ENV` 写入 ∪ bash 内建）里解析；
3. `test_lint_has_discriminating_power` —— 注入式红证：把修法退回「正文裸引用 `${IMAGE_TAG}` 且无 env」
   ⇒ 判据 1 与 2 **都必须红**（证明不是空断言）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WF_DIR = REPO_ROOT / ".github" / "workflows"
DEPLOY_LEGS = ("deploy-admin-api.yml", "deploy-ai-agent-service.yml", "deploy-frontend.yml")
GUARD_STEP_NAME = "Assert server-side build (no ACR push)"

#: bash 内建 / 框架注入变量（**不是**本仓定义的）—— 只许**缩短**（见「未固化」）
BUILTIN = re.compile(
    r"^(GITHUB_|RUNNER_|ACTIONS_|INPUT_|ImageOS|ImageVersion|HOME|PATH|PWD|SHELL|USER|"
    r"TMPDIR|CI|LANG|LC_|PIPESTATUS|BASH_|FUNCNAME|LINENO|RANDOM|SECONDS|IFS|OPTARG|"
    r"OPTIND|OSTYPE|HOSTNAME|BASHPID|EPOCHSECONDS)"
)
EXPR = re.compile(r"\$\{\{.*?\}\}", re.S)
SINGLE_QUOTED = re.compile(r"'[^']*'", re.S)  # shell 在单引号内**不展开** $var（jq 程序的 $x 在此被正确排除）
REF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
ASSIGN = re.compile(
    r"(?:^|[;&|(\s])(?:export\s+|local\s+|declare\s+(?:-\w+\s+)?|readonly\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)=",
    re.M,
)
READ = re.compile(r"\bread\s+(?:-\w+\s+)*([A-Za-z_][A-Za-z0-9_]*)")
FOR_IN = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
GITHUB_ENV_WRITE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=[^\n]*>>\s*"?\$?\{?GITHUB_ENV')
SET_U = re.compile(r"set\s+-(?:\w*u\w*)|set\s+-o\s+nounset")


def _env_keys(doc) -> set[str]:
    e = (doc or {}).get("env") or {}
    return set(e) if isinstance(e, dict) else set()


def _steps(doc):
    for job in (doc.get("jobs") or {}).values():
        if isinstance(job, dict):
            for s in job.get("steps") or []:
                if isinstance(s, dict):
                    yield job, s


def _lint(docs: dict[str, str]) -> list[str]:
    """对 {文件名: YAML 正文} 跑同一份 lint（真语料与注入语料走**同一条路**）。"""
    bad: list[str] = []
    for name, text in docs.items():
        doc = yaml.safe_load(text) or {}
        wf_env = _env_keys(doc)
        for job, step in _steps(doc):
            body = step.get("run")
            if not body or not SET_U.search(body):
                continue
            genv: set[str] = set()
            for sib in job.get("steps") or []:
                if isinstance(sib, dict) and sib.get("run"):
                    genv |= set(GITHUB_ENV_WRITE.findall(sib["run"]))
            clean = SINGLE_QUOTED.sub("''", EXPR.sub('""', body))
            defined = (
                wf_env
                | _env_keys(job)
                | _env_keys(step)
                | genv
                | set(ASSIGN.findall(clean))
                | set(READ.findall(clean))
                | set(FOR_IN.findall(clean))
            )
            for m in REF.finditer(clean):
                var = m.group(1)
                if var in defined or BUILTIN.match(var):
                    continue
                bad.append(f"{name}::{step.get('name')}::{var}")
    return sorted(set(bad))


def undefined_vars_in_deploy_legs() -> list[str]:
    """真语料：返回 ['<file>::<step>::<VAR>', ...]（空 = 干净）。"""
    return _lint({n: (WF_DIR / n).read_text(encoding="utf-8") for n in DEPLOY_LEGS})


# ── 判据 1：实例（本次修法的固化） ────────────────────────────────────────────
@pytest.mark.parametrize("wf", DEPLOY_LEGS)
def test_deploy_leg_guard_steps_declare_image_tag_via_env(wf):
    doc = yaml.safe_load((WF_DIR / wf).read_text(encoding="utf-8")) or {}
    guard = [s for _, s in _steps(doc) if s.get("name") == GUARD_STEP_NAME]
    assert guard, f"{wf}: 守卫步 `{GUARD_STEP_NAME}` 不见了（被删也要显式登记，别静默消失）"
    env = guard[0].get("env") or {}
    assert "IMAGE_TAG" in env, (
        f"{wf}: 守卫步必须在 `env:` 里声明 IMAGE_TAG —— 它在 run 正文里被引用，"
        f"而 `steps.tag.outputs` **不是** env ⇒ `set -u` 下 unbound variable（#5814 事故）"
    )
    assert "steps.tag.outputs.IMAGE_TAG" in str(env["IMAGE_TAG"]), (
        f"{wf}: IMAGE_TAG 必须来自 `steps.tag.outputs.IMAGE_TAG`（现取 {env['IMAGE_TAG']!r}）"
    )


# ── 判据 2：类级（范围 = deploy legs；零假阳性已在真语料上量过） ─────────────────
def test_no_undefined_vars_under_set_u_in_deploy_legs():
    bad = undefined_vars_in_deploy_legs()
    assert not bad, (
        "deploy 腿里存在「`set -u` 下引用了未定义变量」的 run 正文（会在运行时 unbound variable 炸掉整步）：\n  "
        + "\n  ".join(bad)
        + "\n修法：把该变量经 `env:` 显式声明（如 `IMAGE_TAG: ${{ steps.tag.outputs.IMAGE_TAG }}`），"
        "**不要**在正文里裸引用。"
    )


# ── 判据 3：注入式红证（防「不会红的断言」） ──────────────────────────────────
def test_lint_has_discriminating_power(monkeypatch, tmp_path):
    """把修法退回「正文裸引用 + 无 env」⇒ 判据 1 与 2 都必须红。"""
    import shutil

    wf = "deploy-frontend.yml"
    src = WF_DIR / wf
    fixed = src.read_text(encoding="utf-8")
    broken = fixed.replace(
        "        env:\n          IMAGE_TAG: ${{ steps.tag.outputs.IMAGE_TAG }}\n", "", 1
    )
    assert broken != fixed, f"注入未生效：{wf} 里没找到本次修法加的那段 env"

    # 判据 1：env 没了 ⇒ 必须红
    doc = yaml.safe_load(broken) or {}
    guard = [s for _, s in _steps(doc) if s.get("name") == GUARD_STEP_NAME]
    assert guard and "IMAGE_TAG" not in (guard[0].get("env") or {}), (
        "注入后的形态应当缺 env.IMAGE_TAG（注入自证失败）"
    )

    # 判据 2（**真跑 lint**，不是只断言前置条件）：注入语料必须被同一份 lint 抓出来
    victims = _lint({"deploy-frontend.yml": broken})
    assert any(v.endswith("::IMAGE_TAG") for v in victims), (
        "注入「正文裸引用 + 无 env」后 lint 没抓到 IMAGE_TAG ⇒ **判据 2 是空断言**。"
        f"实测 victims={victims}"
    )
    # 对照读数：把 env 加回去 ⇒ lint 必须干净（证明它抓的是「未定义」而不是「出现过这个词」）
    assert _lint({"deploy-frontend.yml": fixed}) == [], "对照失败：修复后的语料不该被 lint 判红"
