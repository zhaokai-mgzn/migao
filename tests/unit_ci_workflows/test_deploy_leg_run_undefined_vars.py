# case_ids: MC-012, MC-059
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

## 判据 4~5（issue #5944）：这条 lint 是 **comment-aware** 的
病（现取读数）：注释里写一句含 `$foo` 的**说明** ⇒ `['x.yml::demo::foo']` **假红**（集成侧内存复算，
与本文件复算逐字一致）。作者唯一的过关办法 = 把注释改写成不含 `$` 的措辞 —— **判红逼人把东西写得更差**
（PR #5943 因此被挡两次）。根因：清洗只有 `SINGLE_QUOTED.sub` + `EXPR.sub`，**没有剥注释**。
修法 = 复用 `.github/danger_scan.py::strip_comment`（**唯一**一份剥注释实现，issue #5268），**不新增第二份**：

4. `test_comment_only_refs_are_not_flagged`（注释含 `$foo`/`$bar` ⇒ `[]`）⇄
   `test_executable_line_ref_is_flagged_by_name`（同一句搬到**可执行行** ⇒ 具名 `<file>::<step>::<var>`）；
5. `test_comment_stripping_does_not_misfire`（4 条负例锚：`${VAR#prefix}` / `${VAR##pattern}` /
   单引号 / 双引号内 `#`，每条**尾部再挂一个真未定义引用** ⇒ 误截断会连带切掉真判据，断言当场红）+
   `test_shared_yardstick_is_shell_safe`（直接打在共享尺子本体上）+
   `test_comment_apostrophe_does_not_hide_a_real_ref`（改前的**反向缺陷**：注释里的撇号会把后面的
   真代码整段抹掉 ⇒ 真未定义变量漏检，实测改前 `[]` / 改后具名红）+
   `test_comment_awareness_has_discriminating_power`（**注入式双向自证**：摘掉剥注释 ⇒ 注释语料必红）+
   `test_strip_comment_has_a_single_implementation`（同源 = 同一对象 + 本文件没有第二份）。
"""
from __future__ import annotations

import re
from pathlib import Path

import sys

import pytest
import yaml

#: 剥注释的**唯一**实现（`.github/danger_scan.py`，issue #5268）—— **复用，不复制**。
#: `tests/unit_ci_workflows/conftest.py` 已把 `.github` 挂进 `sys.path`（与 `test_danger_scan.py` 同一机制）。
from danger_scan import strip_comment

#: 声明本判据守的**接线**（§28.2.1）：`_lint` 的「剥注释」这一环取自
#: `.github/danger_scan.py::strip_comment` **这一个对象**（判据 4d 按 `is` 判同源）。
#: 登记 = `tests/unit_ci_workflows/wiring_claims_ledger.json`（未登记即红）。
WIRING_UNDER_TEST = ".github/danger_scan.py::strip_comment"

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


def _without_comments(body: str) -> str:
    """剥掉 shell 正文里的**行内注释** —— 逐行调用**共享**尺子，不新增第二份实现（issue #5944）。

    为什么逐行就够：shell 的注释是**行**作用域，且 `#` 只有在**行首 / 前面是空白、又不在引号内**时
    才是注释起点 —— `.github/danger_scan.py::strip_comment` 的启发式与 shell 同形
    （`${VAR#prefix}` 的 `#` 前是标识符字符、`echo "a#b"` 的 `#` 在引号内 ⇒ 两处都不剥）。
    """
    return "\n".join(strip_comment(line) for line in body.splitlines())


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
            # ⚠️ **顺序不许反**：剥注释必须在 `EXPR` / `SINGLE_QUOTED` **之前** —— 否则注释里的一个
            # 撇号（`# don't do this`）会跟后文任意一个 `'` 配对，把两者之间的**真代码整段抹掉**
            # （实测：真未定义变量因此**漏检** ⇒ 那是**反向缺陷**，比假红更坏）。负例锚 =
            # `test_comment_apostrophe_does_not_hide_a_real_ref`。
            # ⚠️ `set -u` 门（上面的 `SET_U.search(body)`）仍读**原文**：注释里写 `set -u` 仍会把该步
            # 纳入射程 —— 有意保守（本单只治假红，**不放宽射程**），真语料上 0 例。
            clean = SINGLE_QUOTED.sub("''", EXPR.sub('""', _without_comments(body)))
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


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4~5（issue #5944）：这条 lint 必须 **comment-aware**
#
# 病（现取读数）：注释里写一句含 `$foo` 的**说明** ⇒ `['x.yml::demo::foo']` 假红。作者唯一的过关
# 办法 = 把注释改写成不含 `$` 的措辞 —— 判红逼人把东西写得更差（PR #5943 因它被挡两次）。
# 根因：清洗只有 `SINGLE_QUOTED.sub` + `EXPR.sub`，**没有剥注释**。
# 修法 = 复用 `.github/danger_scan.py::strip_comment`（**唯一**一份，issue #5268），不新增第二份。
# ══════════════════════════════════════════════════════════════════════════════

_COMMENT_LINE = "          # 说明：这里的 $foo / $bar 只是注释，不参与执行"
COMMENT_ONLY = (
    "name: x\non: push\njobs:\n  j:\n    steps:\n      - name: demo\n        run: |\n"
    "          set -u\n"
    f"{_COMMENT_LINE}\n"
    "          echo ok\n"
)
_EXECUTABLE_LINE = "          echo ${foo} ${bar}"


def _executable_variant() -> str:
    """把注释那一句**搬到可执行行**（判据 4b 的对照语料；与注释语料逐字对照）。"""
    return COMMENT_ONLY.replace(_COMMENT_LINE, _EXECUTABLE_LINE)


def test_comment_only_refs_are_not_flagged():
    """判据 4a（#5944 的**假红**）：注释里的 `$foo` / `$bar` ⇒ `_lint` 返回 `[]`。"""
    assert _lint({"x.yml": COMMENT_ONLY}) == [], (
        "注释不参与执行 ⇒ 里面的 `$var` 既不是未定义引用、也不该判红（#5944：作者当时唯一的出路是"
        "把注释改写成不含 `$` 的措辞 —— 判红逼人把东西写得**更差**）"
    )


def test_executable_line_ref_is_flagged_by_name():
    """判据 4b（**不放宽射程**）：同一句搬到可执行行 ⇒ 必须**具名**判红 `<file>::<step>::<var>`。"""
    executable = _executable_variant()
    assert executable != COMMENT_ONLY, "变异未生效：可执行行语料与注释语料逐字相同（下面就是空断言）"
    assert _lint({"x.yml": executable}) == ["x.yml::demo::bar", "x.yml::demo::foo"], (
        "可执行行里的未定义变量没被判红（或判红不具名）⇒ 本 lint 的射程被放宽了（#5944 明令禁止）"
    )


#: 负例锚（判据 4c）：`#` **不是**注释起点的四种形态。每行尾部再挂一个**真**未定义引用 ——
#: 若剥注释在这一行误截断，尾部的真判据会**连带消失** ⇒ 断言当场红（不是「恰好绿」）。
HASH_IS_NOT_A_COMMENT = [
    ("param-expand-hash", "echo ${HOME#prefix} $UNDEF"),
    ("param-expand-double-hash", "echo ${HOME##pattern} $UNDEF"),
    ("single-quoted-hash", "echo 'a#b' $UNDEF"),
    ("double-quoted-hash", 'echo "a#b" $UNDEF'),
]


@pytest.mark.parametrize("label,line", HASH_IS_NOT_A_COMMENT, ids=[c[0] for c in HASH_IS_NOT_A_COMMENT])
def test_comment_stripping_does_not_misfire(label, line):
    """判据 4c（负例锚）：`${VAR#prefix}` / `${VAR##pattern}` / 引号内的 `#` **不得**被当注释起点。"""
    doc = (
        "name: x\non: push\njobs:\n  j:\n    steps:\n      - name: demo\n        run: |\n"
        f"          set -u\n          {line}\n"
    )
    assert _lint({"x.yml": doc}) == ["x.yml::demo::UNDEF"], (
        f"[{label}] 这一行的 `#` 被当成注释起点了 ⇒ 行尾那个**真**未定义变量被一起切掉"
        "（把真判据改弱 = 反向缺陷，代价比假红更大）"
    )


def test_shared_yardstick_is_shell_safe():
    """判据 4c′：直接打在**共享尺子本体**上（`_lint` 用的就是同一个对象，见判据 4d）。"""
    assert strip_comment("echo ${VAR#prefix}") == "echo ${VAR#prefix}", "${VAR#prefix} 被误当注释"
    assert strip_comment("echo ${VAR##pattern}") == "echo ${VAR##pattern}", "${VAR##pattern} 被误当注释"
    assert strip_comment("echo 'a#b'") == "echo 'a#b'", "单引号内的 `#` 被误当注释"
    assert strip_comment('echo "a#b"') == 'echo "a#b"', "双引号内的 `#` 被误当注释"
    assert strip_comment("echo ok  # 说明 $foo") == "echo ok  ", "真注释没被剥掉（另一个方向）"


def test_comment_apostrophe_does_not_hide_a_real_ref():
    """判据 4e（**反向缺陷**的负例锚）：注释里的撇号不得吞掉后文的真判据。

    改前形态（先跑 `SINGLE_QUOTED`、而注释根本没剥）：`# don't` 的撇号与后文任意一个 `'` 配对，
    **两者之间的真代码被整段抹掉** —— 实测改前读数 `[]`（真未定义变量被**漏检**），
    改后 `['x.yml::demo::REAL_UNDEFINED']`。⇒ 「剥注释放在 `SINGLE_QUOTED` 之前」不是洁癖。
    """
    doc = (
        "name: x\non: push\njobs:\n  j:\n    steps:\n      - name: demo\n        run: |\n"
        "          set -u\n"
        "          echo start  # don't do this\n"
        "          echo ${REAL_UNDEFINED}\n"
        "          echo 'quoted'\n"
    )
    assert _lint({"x.yml": doc}) == ["x.yml::demo::REAL_UNDEFINED"], (
        "注释里的撇号把中间的真代码（含真未定义引用）整段抹掉了 ⇒ 判据**漏检**（改前就是这个读数）"
    )


def test_comment_awareness_has_discriminating_power(monkeypatch):
    """判据 5（**类级**：这条 lint 是 comment-aware 的）—— 注入式双向自证。

    ① 变异注入（先自证变异生效）：把 `_lint` 用的那把尺子换成**恒等函数** = 改前形态 ⇒
       注释语料必须**变红**（证明判据 4a 不是空断言 —— 它真的会红）；
    ② 同一注入下，可执行行语料**照旧**具名红（证明判据本体没被注入拆掉）；
    ③ 撤掉注入 ⇒ 注释语料回到 `[]`（证明那条绿来自**剥注释**这一环，不是语料本身干净）。
    """
    executable = _executable_variant()
    assert _lint({"x.yml": COMMENT_ONLY}) == [], "真尺子下注释语料应当绿（本自证的前置读数）"
    assert _lint({"x.yml": executable}) == ["x.yml::demo::bar", "x.yml::demo::foo"]

    monkeypatch.setattr(sys.modules[__name__], "strip_comment", lambda line: line)  # ← 变异注入
    mutated_comment = _lint({"x.yml": COMMENT_ONLY})
    mutated_executable = _lint({"x.yml": executable})
    monkeypatch.undo()
    restored = _lint({"x.yml": COMMENT_ONLY})

    assert mutated_comment == ["x.yml::demo::bar", "x.yml::demo::foo"], (
        "把「剥注释」这一环摘掉后注释语料**没有**变红 ⇒ 判据 4a 是无判别力的空断言："
        f"实测注入后 = {mutated_comment}"
    )
    assert mutated_executable == ["x.yml::demo::bar", "x.yml::demo::foo"], (
        f"注入把判据本体拆掉了（可执行行语料照旧该红）：实测 {mutated_executable}"
    )
    assert restored == [], f"撤掉注入后注释语料没回到绿 ⇒ 读数不可归因（实测 {restored}）"


def test_strip_comment_has_a_single_implementation():
    """判据 4d（**单一实现**）：本文件用**共享**尺子，不复制第二份（#5944 判据 4）。"""
    import danger_scan

    assert strip_comment is danger_scan.strip_comment, (
        "本判据用的剥注释实现不是 `.github/danger_scan.py::strip_comment` 那个**对象** ⇒ 出现第二把尺子"
    )
    # 自指陷阱：断言的「针」**不能**在本文件里连续出现（否则这句话自己把文件喂红）⇒ 运行时拼出来
    needle = "def " + "strip_comment"
    assert needle not in Path(__file__).read_text(encoding="utf-8"), (
        "本文件里出现了第二份剥注释实现 —— 复用 `.github/danger_scan.py` 那一份，不要复制"
    )
