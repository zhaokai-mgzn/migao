# case_ids: MC-103
"""Post-Merge Verify 的**取数面读数探针**必须真有牙（issue #6968）。

## 病灶（2026-10-15 现取，不是推断）

main 侧守护腿连挂多轮：`tests/unit_ci_workflows/test_case_id_claims.py` 两条常驻出口
（`test_repo_case_id_claims_are_clean` / `test_repo_corpus_face_is_clean`）报
「判定不了：没有 API 凭据（GITHUB_TOKEN/GH_TOKEN 都为空）」。

`.github/workflows/post-merge-verify.yml` 的「取数面读数」步**本来就是为这件事加的诊断探针**，
而它自己 `import` 就失败（`sys.path` 插的是 `tests/unit_ci_workflows`，而本仓判据按**包**导入
`unit_ci_workflows.*`）⇒ 每轮逐字输出：

    探针自身失败（不影响判定）: ModuleNotFoundError No module named 'unit_ci_workflows'

⇒ **诊断面形同不存在** ⇒「① 模板侧没解出 token」与「② 解出了没进子进程」**从未被分开过**
（这正是这条红能连挂多轮而没人定位的**直接原因**）。

## 本判据钉的两件事

| # | 判据 | 红证（注入 ⇒ 必红） |
|---|---|---|
| 1 | **探针必须能回答那个问题**：在 `PYTHONPATH=tests` 下**逐字**打印 `creds = {...}` 行 | 把 `PYTHONPATH` 换回 `tests/unit_ci_workflows` ⇒ 判据非空（旧形态） |
| 2 | **探针失败 ⇒ 本步响亮失败**（不许「只打印、绝不影响判定」） | 抹掉 `::error::` + `exit 1` ⇒ 判据非空 |
| 3 | driver 交给判据解释器的环境**必须带凭据**（`credential_env_reading` / `_judging_env`） | 让 `_judging_env` 不补齐 ⇒ 判据非空 |
| 4 | 读数**不判答案好坏**：无凭据时 `creds` 打印全 0 **也算探针正常**（那是读数，不是故障） | —— |

## 边界（照实登记，别读成「已覆盖」）

- ❌ **判不了「CI 上凭据为什么是空的」**：那要在真 runner 上读 step shell 与子进程两层读数 ——
  本判据只保证**那两层读数真的会被打出来且坏掉会红**（诊断面**可达**），不替 CI 下结论。
- ❌ 不等于「判据 7 的判定口径正确」（那是 `test_case_id_claims.py` 自己的面）。
- ❌ 不改任何门禁的通过条件、不新增豁免。
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT_REL = "scripts/post_merge_verify.py"
SCRIPT = REPO / SCRIPT_REL
WORKFLOW_REL = ".github/workflows/post-merge-verify.yml"
WORKFLOW = REPO / WORKFLOW_REL
#: 探针真正用的导入路径（**包**形态：`unit_ci_workflows.*`）。
PROBE_PYTHONPATH = "tests"
#: 探针必须打出的那行读数（判据 1 的锚）。
READING_RE = re.compile(r"creds = \{")
#: 探针失败时的两个出口（判据 2 的锚）。
LOUD_MARKERS = ("::error::", "exit 1")


def _leg():
    """把 `scripts/post_merge_verify.py` 当模块加载（不复制它的任何逻辑）。"""
    spec = importlib.util.spec_from_file_location("post_merge_verify_credprobe", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"加载不了 {SCRIPT_REL}（本判据无从判定 ⇒ 大声失败）")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _verify_step_run() -> str:
    """`判定（定向跑判据面）` 步的 `run:` 文本（判据 2 的判定面）。"""
    import yaml

    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    runs = [
        str(step.get("run", ""))
        for job in (doc.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if isinstance(step, dict) and step.get("id") == "verify"
    ]
    assert runs, f"{WORKFLOW_REL} 里找不到 `id: verify` 的步 ⇒ 本判据无从判定（大声失败）"
    return runs[0]


def _strip_comments(text: str) -> str:
    """去掉 YAML `run:` 文本里的**整行 shell 注释**（判据读**行为**，不吃自己的说明文字）。

    ⚠️ 必须做：判定文本里就有「上一版插错成 `tests/unit_ci_workflows`」这类**说明**，
    它们是给下一次的人看的 —— 判据读到它们会**假红**（改文案即红 = 判到的是说明而不是行为）。
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _probe_problems(run_text: str) -> list[str]:
    """探针的两个前提（判据 1 / 判据 2）⇒ 问题清单。纯函数（红证可注入变异）。

    ⚠️ `PYTHONPATH` 必须**正则取值再逐字比**，不能用 `"PYTHONPATH=tests" in text` —— 后者对
    `PYTHONPATH=tests/unit_ci_workflows`（**旧形态，正是要判红的那个坏形态**）也是 `True`
    （子串包含）⇒ 判据**没有判别力**。本判据初版就踩了这一条，由红证 ① 当场抓到。
    两条实现细节都是**实测**：先踩「子串判据没判别力」，再踩「读到注释里的反例说明 ⇒ 假红」。
    """
    body = _strip_comments(run_text)          # 只判行为行
    problems: list[str] = []
    found = re.findall(r"PYTHONPATH=([^\s\"']+)", body)
    if not found:
        problems.append("探针块里找不到 `PYTHONPATH=...` ⇒ 它没有把仓根补进导入路径")
    elif any(value != PROBE_PYTHONPATH for value in found):
        bad = sorted({v for v in found if v != PROBE_PYTHONPATH})
        problems.append(
            f"探针的导入路径必须**逐字**是 `{PROBE_PYTHONPATH}`（本仓判据按包导入 `unit_ci_workflows.*`），"
            f"现取 {bad} —— 插 `tests/unit_ci_workflows` 会让探针自己 `ModuleNotFoundError`（issue #6968 的形态）"
        )
    if not READING_RE.search(body):
        problems.append("探针块里找不到 `creds = {` 那行读数 ⇒ 它不是在与判据同源的面上取数")
    # 判据 2：探针失败必须**响亮**（::error:: + 非零退出），不许「只打印、不影响判定」。
    if "grep" not in body or not all(m in body for m in LOUD_MARKERS):
        problems.append(
            "探针失败**不响亮**（缺 `grep` 读数行检查 / `::error::` / `exit 1`）⇒ 它会静默坏掉："
            "issue #6968 的原始注释逐字写着「探针自己失败只打印，绝不判红」，那正是它坏了两小时没人知道的原因"
        )
    return problems


def _judging_env_problems(module) -> list[str]:
    """判据 3：driver 交给判据解释器的环境必须带凭据。纯函数。"""
    problems: list[str] = []
    if not hasattr(module, "_judging_env") or not hasattr(module, "credential_env_reading"):
        return ["`scripts/post_merge_verify.py` 缺 `_judging_env` / `credential_env_reading`（issue #6968 的接线点）"]
    # ① 无凭据 ⇒ 读数全 0（且**不**凭空造一个 token）
    empty = module.credential_env_reading({"PATH": "/usr/bin"})
    if set(empty) != set(module.JUDGING_ENV_KEYS):
        problems.append(f"读数键集与 `JUDGING_ENV_KEYS` 不一致：{sorted(empty)}")
    if any(v != 0 for v in empty.values()):
        problems.append(f"空环境里读数竟然非 0：{empty}（读数必须与判据同源，不许凭空造 token）")
    # ② 只有 GH_TOKEN ⇒ 判据解释器里 GITHUB_TOKEN 也必须是同一个值（两个键都能使）
    env = module._judging_env({"GH_TOKEN": "tok-123", "GITHUB_REPOSITORY": "o/r"})
    if (env.get("GITHUB_TOKEN") or "") != "tok-123":
        problems.append("只有 `GH_TOKEN` 时没有把它补进 `GITHUB_TOKEN` ⇒ 判据 7 会报「没有 API 凭据」")
    # ③ 已有 GITHUB_TOKEN ⇒ **不得**被覆盖（`setdefault` 语义）
    env2 = module._judging_env({"GITHUB_TOKEN": "real", "GH_TOKEN": "other"})
    if env2.get("GITHUB_TOKEN") != "real":
        problems.append("已有的 `GITHUB_TOKEN` 被覆盖了（必须 `setdefault`，注入点优先）")
    # ④ **同源面**：driver 的 `CREDENTIAL_ENVS` 必须**逐字**等于判据自己的 `TOKEN_ENVS`
    #    （`scripts/post_merge_verify.py::CREDENTIAL_ENVS` 的注释声明了这一条 —— 由本腿承担：
    #    判据改成读第三个键、或驱动侧少一个键 ⇒ 当场红。读的是**真模块**，不是复制一份清单）。
    import unit_ci_workflows.test_case_id_claims as claims

    if tuple(module.CREDENTIAL_ENVS) != tuple(claims.TOKEN_ENVS):
        problems.append(
            f"`CREDENTIAL_ENVS`={tuple(module.CREDENTIAL_ENVS)} 与判据的 `TOKEN_ENVS`="
            f"{tuple(claims.TOKEN_ENVS)} 不再是同一集合 ⇒ driver 补的凭据与判据取的不是一套"
        )
    if not set(module.CREDENTIAL_ENVS) <= set(module.JUDGING_ENV_KEYS):
        problems.append("凭据键不在 `JUDGING_ENV_KEYS` 里 ⇒ 读数看不到它们")
    return problems


# ══════════════════════════════════════════════════════════════════════════
# 判据 1 / 2：探针的两个前提（工作树真文本）
# ══════════════════════════════════════════════════════════════════════════
def test_probe_step_is_wired_to_answer_the_question() -> None:
    """判据 1 / 2 的常驻出口：探针能取数，且它坏掉会**响亮失败**。"""
    problems = _probe_problems(_verify_step_run())
    assert problems == [], "取数面读数探针的接线报红（issue #6968）：\n" + "\n".join(f"  - {p}" for p in problems)


def test_probe_reads_the_real_criterion_module() -> None:
    """判据 1 的**直连真对象**（§28.1 出口 ④）：`PYTHONPATH=tests` 下真能导入并打印 `creds =` 行。

    这是「探针自称与判据同源」这句声明的**内容级**核验 —— 探针 import 的模块**真的**能加载、
    `TOKEN_ENVS` / `scan_claims` / `current_pr` **真的**在（不是拼出来的字符串）。
    零网络（只 import + 读仓内 claim 文件）。
    """
    code = (
        "import unit_ci_workflows.test_case_id_claims as t;"
        "print('creds =', {k: 0 for k in t.TOKEN_ENVS}, '| current_pr =',"
        " t.current_pr(t.parse_claims(t.scan_claims(t.REPO_ROOT / t.CLAIMS_REL)[0])))"
    )
    import os

    env = {**os.environ, "PYTHONPATH": PROBE_PYTHONPATH}
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True,
                          text=True, env=env)
    assert proc.returncode == 0, (
        f"`PYTHONPATH={PROBE_PYTHONPATH}` 下导入判据模块失败 —— 探针会重演 issue #6968：\n{proc.stderr[:600]}"
    )
    assert READING_RE.search(proc.stdout), f"探针没打出 `creds =` 行：{proc.stdout!r}"


# ══════════════════════════════════════════════════════════════════════════
# 红证（注入式，各能单独变红）
# ══════════════════════════════════════════════════════════════════════════
def test_red_proof_broken_import_path_turns_it_red() -> None:
    """红证 ①：把 `PYTHONPATH` 换回旧形态（`tests/unit_ci_workflows`）⇒ 判据 1 必红。"""
    text = _verify_step_run().replace(f"PYTHONPATH={PROBE_PYTHONPATH}",
                                      "PYTHONPATH=tests/unit_ci_workflows")
    assert text != _verify_step_run(), "变异点失配：找不到 `PYTHONPATH=tests`（红证不得是空断言）"
    assert _probe_problems(text) != [], "旧的（坏）导入路径竟然没被判红 ⇒ 空断言"


def test_red_proof_silent_probe_turns_it_red() -> None:
    """红证 ②：把 fail-loud 出口抹掉（退回「只打印、不影响判定」）⇒ 判据 2 必红。"""
    text = _verify_step_run()
    for marker in LOUD_MARKERS:
        assert marker in text, f"变异点失配：工作树里找不到 `{marker}`（红证不得是空断言）"
    stripped = text.replace("::error::", "").replace("exit 1", "")
    assert _probe_problems(stripped) != [], "探针静默失败竟然没被判红 ⇒ 空断言"


def test_red_proof_dropping_credential_passthrough_turns_it_red() -> None:
    """红证 ③：driver 不补齐凭据（`_judging_env` 退化成纯拷贝）⇒ 判据 3 必红。"""
    module = _leg()
    original = module._judging_env

    def degraded(env=None):
        return dict(module.os.environ if env is None else env)

    module._judging_env = degraded
    try:
        assert _judging_env_problems(module) != [], "凭据没补齐竟然没被判红 ⇒ 空断言"
    finally:
        module._judging_env = original


def test_negative_control_probe_is_green_on_the_real_tree() -> None:
    """负控（反向对照）：真工作树上三条判据**都必须非空**（否则上面全是空断言）。"""
    module = _leg()
    assert _probe_problems(_verify_step_run()) == []
    assert _judging_env_problems(module) == []
    # 判据读的是**行为**：把 `run:` 的注释行全删 ⇒ 仍须绿。
    # ⚠️ 前提是**每条**真行为都不在注释里 —— 上面 `test_probe_step_is_wired_to_answer_the_question`
    # 已经把 `PYTHONPATH=` / `creds = {` 都钉在**非注释**行上（否则这里会红），故两判据互为对照。
    assert _probe_problems(_strip_comments(_verify_step_run())) == [], (
        "探针的判定吃到了注释文字（改文案会假红）⇒ 判定面写错了"
    )
