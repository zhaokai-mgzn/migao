# case_ids: MC-012
"""`frontend/worker-h5` 的测试「必须在 CI 里被跑到」的防回退锁（issue #4786）。

## 背景（实测，非推断）

`frontend/worker-h5/`（工人端 H5 第一切片，issue #4765 已随 `01e72187f` 合入 main）是
**零依赖 + 零构建**的纯 ES module 目录，测试用 **Node 内置 `--test`**。
补本守卫之前，`.github/workflows/` 里**没有任何一条腿碰过这个目录**：

| 证据 | 实测 |
|---|---|
| `grep -rn 'worker-h5' .github/` | **0 命中** |
| 前端腿的路径面 | `admin-web-test` / `deploy-frontend.yml` / `demo-evidence.yml` 都只认 `frontend/admin-web/**` |
| 后果 | `frontend/worker-h5/tests/*.test.mjs`（4 文件 / 29 条测试）**只在本地跑** ⇒ 在 CI 里是**死文件**（改坏了没人拦） |

这是本仓最忌的形态 ——「**CI 不覆盖 ≠ 已覆盖**」。#4765 的包自己明确写了
「不得说成『CI 已覆盖本页面』」，本守卫就是把那句话变成机械判据。

## 本守卫锁什么

按 `.github/workflows/worker-h5-tests.yml` 的**结构真值**判（读 YAML，不扫全文正则 ——
否则「注释里提一句 `node --test`」就算数 = 假绿，同 `test_admin_web_next_build_gate.py` 口径）：

1. 存在 `pull_request` 触发，且 `paths` **含 `frontend/worker-h5/**`** —— 删掉它，
   worker-h5 的改动**不再触发**本腿 ⇒ 直接退回「死文件」（本单要治的形态本身）；
2. `paths` **含本 workflow 自身** —— 否则「只改这条腿」的 PR 不触发它，改坏了没有证据；
3. 存在一步执行 **`node --test`** 且指向 `frontend/worker-h5/tests/*.test.mjs` —— 删掉它，
   测试退回死文件；
4. 该步**不得被静默化**：step/job 级 `continue-on-error`、`|| true`、恒假 `if`
   —— 都是「红被吞」（等价于不装）；
5. 该步的存在性门控**必须真的接线**：存在性步要有 `id`，`node --test` 步的 `if` 必须引用
   它的 output —— 否则「目录不存在」的历史 ref 上会红出一条与被测代码无关的红；
6. 有 `actions/setup-node` 且**钉了主版本** —— 否则 Node 版本随 runner 镜像漂移
   （本腿依赖 `node --test` 的行为）；
7. `timeout-minutes` 存在 —— 否则挂死的腿会占满 runner 上限。

**红证是注入式的**（同 `test_case_trust_gate.py` 口径）：`_problems()` 是纯函数，
对真实 workflow 判绿，对下面每一种变异样本都必须判红 —— 所以「判据不会红」这种
空断言形态在本文件里结构上不可能出现。

**本守卫不执行 node**：`ci-workflow-tests` job 只有 Python（无 Node），跑 node 会让守卫
依赖环境、并把「测试本身是否通过」混进「接线是否正确」。测试是否真跑得动由本腿自己
在 CI 上给出（PR 的 `worker-h5 unit tests (node --test)` check 绿 = 29 pass）。
"""
import copy
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "worker-h5-tests.yml"
TESTS_DIR = REPO_ROOT / "frontend" / "worker-h5" / "tests"

JOB = "worker-h5-test"
NODE_STEP = "Run worker-h5 unit tests (node --test)"
DETECT_STEP = "Verify test files exist"
WORKER_H5_GLOB = "frontend/worker-h5/**"
TEST_GLOB = "frontend/worker-h5/tests/*.test.mjs"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), (
        f"{WORKFLOW_PATH.relative_to(REPO_ROOT)} 不存在 —— `frontend/worker-h5` 的测试在 CI 里"
        "没有任何腿跑它们（issue #4786 的形态本身）。删本 workflow 必须同时给出替代接线。"
    )
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8")) or {}


def _on_key(wf: dict):
    """yaml 会把裸 `on:` 解析成布尔 True 键（与 test_behavior_eval_pr_thin 同一处理）。

    变异样本要**改在真键上**：写成 `wf["on"] = …` 会新增一个字符串键，而布尔 True 键
    仍在 ⇒ 判据读到的仍是旧值 ⇒ 红证**静默失效**（本文件自己的坑，实测踩到）。
    """
    return "on" if "on" in wf else True


def _triggers(wf: dict) -> dict:
    return wf.get("on") or wf.get(True) or {}


def _job(wf: dict) -> dict:
    job = (wf.get("jobs") or {}).get(JOB)
    assert isinstance(job, dict), f"找不到 job `{JOB}`（被改名/删除？本守卫的锁点失效）"
    return job


def _steps(job: dict) -> list:
    return [s for s in (job.get("steps") or []) if isinstance(s, dict)]


def _by_name(job: dict, name: str) -> dict:
    for s in _steps(job):
        if s.get("name") == name:
            return s
    pytest.fail(f"`{JOB}` 里找不到名为 `{name}` 的 step（本守卫的锁点被删/改名）")


def _is_true(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _problems(wf: dict) -> list:
    """纯函数判据：返回问题清单（空 = 接线成立）。变异样本据此判红。"""
    problems = []

    # ① pull_request 触发 + paths 含被测目录
    pr = _triggers(wf).get("pull_request")
    if pr is None:
        problems.append("缺 pull_request 触发 —— worker-h5 的改动不再触发本腿（退回「死文件」）")
        return problems
    paths = [str(p) for p in ((pr or {}).get("paths") or [])]
    if WORKER_H5_GLOB not in paths:
        problems.append(
            f"pull_request.paths 未含 {WORKER_H5_GLOB!r}（实为 {paths!r}）—— 改该目录不触发本腿"
        )
    # ② paths 含本 workflow 自身（否则「只改这条腿」的 PR 拿不到证据）
    if not any(p.endswith("worker-h5-tests.yml") for p in paths):
        problems.append(
            f"pull_request.paths 未含本 workflow 自身（实为 {paths!r}）—— 只改这条腿的 PR 不触发它"
        )

    job = (wf.get("jobs") or {}).get(JOB)
    if not isinstance(job, dict):
        problems.append(f"找不到 job `{JOB}` —— 本腿不存在")
        return problems
    steps = _steps(job)

    # ③ 存在 `node --test` 步且指向该目录的 *.test.mjs
    runner = [s for s in steps if "node --test" in (s.get("run") or "")]
    if not runner:
        problems.append(
            "没有任何 step 执行 `node --test` —— worker-h5 的测试在 CI 里退回「死文件」"
        )
    else:
        cmd = "\n".join(s.get("run") or "" for s in runner)
        if "frontend/worker-h5/tests/" not in cmd:
            problems.append(f"`node --test` 步没指向 frontend/worker-h5/tests/（实为 {cmd!r}）")
        if "*.test.mjs" not in cmd:
            problems.append(
                f"`node --test` 步没覆盖 *.test.mjs（实为 {cmd!r}）—— 新增/改名的测试会静默不跑"
            )

    # ④ 不得被静默化（「红被吞」等价于不装）
    if _is_true(job.get("continue-on-error")):
        problems.append(f"job `{JOB}` 有 continue-on-error —— 本腿的红被吞掉")
    for s in runner:
        label = s.get("name") or "<unnamed>"
        if _is_true(s.get("continue-on-error")):
            problems.append(f"`{label}` 有 continue-on-error —— 本腿的红被吞掉")
        if "|| true" in (s.get("run") or ""):
            problems.append(f"`{label}` 用 `|| true` 吞掉非零退出 —— 本腿的红被吞掉")
        cond = str(s.get("if") or "").strip().lower()
        if cond in ("false", "${{ false }}"):
            problems.append(f"`{label}` 的 if 恒假 —— 本腿永不执行")

    # ⑤ 存在性门控必须真的接线（否则历史 ref 上红出一条与被测代码无关的红）
    detect = [s for s in steps if s.get("name") == DETECT_STEP]
    if not detect:
        problems.append(f"缺 `{DETECT_STEP}` 步 —— 目录不存在的历史 ref 上手跑会红出无关的红")
    else:
        detect_id = detect[0].get("id")
        if not detect_id:
            problems.append(f"`{DETECT_STEP}` 没有 id ⇒ 下游 if 无法引用它的 output")
        elif not any(f"steps.{detect_id}.outputs." in str(s.get("if") or "") for s in runner):
            problems.append(
                f"`{NODE_STEP}` 的 if 未引用 `steps.{detect_id}.outputs.*` ⇒ 存在性门控未接线"
            )
        if "GITHUB_OUTPUT" not in (detect[0].get("run") or ""):
            problems.append(f"`{DETECT_STEP}` 没写 GITHUB_OUTPUT ⇒ 下游 if 永远拿不到值")

    # ⑥ Node 版本必须钉住（本腿依赖 `node --test` 的行为）
    setup_node = [
        s for s in steps if str(s.get("uses", "")).startswith("actions/setup-node")
    ]
    if not setup_node:
        problems.append("缺 actions/setup-node —— Node 版本随 runner 镜像漂移")
    elif not (setup_node[0].get("with") or {}).get("node-version"):
        problems.append("setup-node 未钉 node-version —— Node 版本随 runner 镜像漂移")

    # ⑦ 超时兜底
    if job.get("timeout-minutes") is None:
        problems.append(f"job `{JOB}` 缺 timeout-minutes —— 挂死的腿会占满 runner 上限")

    return problems


# ── 正向：真实 workflow 必须判绿 ────────────────────────────────────────────────
def test_real_workflow_wires_worker_h5_tests():
    problems = _problems(_load())
    assert problems == [], "worker-h5 测试的 CI 接线被破坏：\n" + "\n".join(f"  · {p}" for p in problems)


def test_workflow_is_valid_yaml_with_expected_job():
    wf = _load()
    job = _job(wf)
    assert job.get("runs-on") == "ubuntu-latest", f"`{JOB}` 的 runs-on 变了：{job.get('runs-on')!r}"
    assert _by_name(job, NODE_STEP).get("run", "").strip() == (
        f"node --test {TEST_GLOB}"
    ), f"`{NODE_STEP}` 的命令变了 —— 与守卫的 TEST_GLOB 不再同源"


def test_test_files_exist_so_the_glob_is_not_empty():
    """命令里的 glob 必须真的匹配到测试文件（否则是「指向空气」的假接线）。"""
    files = sorted(TESTS_DIR.glob("*.test.mjs"))
    assert files, (
        f"{TESTS_DIR.relative_to(REPO_ROOT)} 下没有任何 *.test.mjs —— 命令 "
        f"`node --test {TEST_GLOB}` 会指向空集（绿着空跑 = 假绿）"
    )
    # 反向：目录里若出现本腿 glob 覆盖不到的测试后缀，它们会静默不跑
    missed = sorted(
        p.name
        for p in TESTS_DIR.glob("*.test.*")
        if not p.name.endswith(".test.mjs")
    )
    assert missed == [], (
        f"以下测试文件不在本腿的 glob（*.test.mjs）覆盖内，会静默不跑：{missed} —— "
        "要么改名，要么同步改 workflow 与 TEST_GLOB"
    )


# ── 红证：每一种变异样本都必须被判红（注入式自证，判据不得是空壳）──────────────
def _mutate(mutator) -> list:
    wf = copy.deepcopy(_load())
    mutator(wf)
    return _problems(wf)


def test_red_proof_missing_worker_h5_path():
    """① paths 去掉 frontend/worker-h5/** ⇒ 必红（本单要治的形态本身）。"""
    def mut(wf):
        wf[_on_key(wf)]["pull_request"]["paths"] = [".github/workflows/worker-h5-tests.yml"]

    problems = _mutate(mut)
    assert any(WORKER_H5_GLOB in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_missing_self_path():
    """② paths 去掉本 workflow 自身 ⇒ 必红（只改这条腿的 PR 拿不到证据）。"""
    def mut(wf):
        wf[_on_key(wf)]["pull_request"]["paths"] = [WORKER_H5_GLOB]

    problems = _mutate(mut)
    assert any("本 workflow 自身" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_missing_pull_request_trigger():
    """③ 删掉 pull_request 触发 ⇒ 必红。"""
    def mut(wf):
        wf[_on_key(wf)] = {"workflow_dispatch": None}

    problems = _mutate(mut)
    assert any("pull_request" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_node_test_step_removed():
    """④ 删掉 `node --test` 步 ⇒ 必红（测试退回死文件）。"""
    def mut(wf):
        job = wf["jobs"][JOB]
        job["steps"] = [s for s in job["steps"] if s.get("name") != NODE_STEP]

    problems = _mutate(mut)
    assert any("node --test" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_glob_narrowed_to_one_file():
    """⑤ 把 glob 收窄到单个文件 ⇒ 必红（新增的测试会静默不跑）。"""
    def mut(wf):
        for s in wf["jobs"][JOB]["steps"]:
            if s.get("name") == NODE_STEP:
                s["run"] = "node --test frontend/worker-h5/tests/worker-h5-api.test.mjs"

    problems = _mutate(mut)
    assert any("*.test.mjs" in p for p in problems), f"应判红却得到 {problems!r}"


@pytest.mark.parametrize("level", ["step", "job"])
def test_red_proof_continue_on_error(level):
    """⑥ continue-on-error（step 级 / job 级）⇒ 必红（红被吞 = 等价于不装）。"""
    def mut(wf):
        if level == "job":
            wf["jobs"][JOB]["continue-on-error"] = True
        else:
            for s in wf["jobs"][JOB]["steps"]:
                if s.get("name") == NODE_STEP:
                    s["continue-on-error"] = True

    problems = _mutate(mut)
    assert any("continue-on-error" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_or_true_swallows_failure():
    """⑦ `|| true` 吞掉非零退出 ⇒ 必红。"""
    def mut(wf):
        for s in wf["jobs"][JOB]["steps"]:
            if s.get("name") == NODE_STEP:
                s["run"] = "node --test frontend/worker-h5/tests/*.test.mjs || true"

    problems = _mutate(mut)
    assert any("|| true" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_always_false_if():
    """⑧ 恒假 if ⇒ 必红（本腿永不执行）。"""
    def mut(wf):
        for s in wf["jobs"][JOB]["steps"]:
            if s.get("name") == NODE_STEP:
                s["if"] = "false"

    problems = _mutate(mut)
    assert any("恒假" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_detect_step_unwired():
    """⑨ 存在性步丢掉 id（门控未接线）⇒ 必红。"""
    def mut(wf):
        for s in wf["jobs"][JOB]["steps"]:
            if s.get("name") == DETECT_STEP:
                s.pop("id", None)

    problems = _mutate(mut)
    assert any("没有 id" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_node_step_unbound_from_detect():
    """⑩ `node --test` 步的 if 不再引用存在性 output ⇒ 必红。"""
    def mut(wf):
        for s in wf["jobs"][JOB]["steps"]:
            if s.get("name") == NODE_STEP:
                s.pop("if", None)

    problems = _mutate(mut)
    assert any("未接线" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_setup_node_removed():
    """⑪ 删掉 actions/setup-node ⇒ 必红（Node 版本随 runner 漂移）。"""
    def mut(wf):
        job = wf["jobs"][JOB]
        job["steps"] = [
            s for s in job["steps"] if not str(s.get("uses", "")).startswith("actions/setup-node")
        ]

    problems = _mutate(mut)
    assert any("setup-node" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_unpinned_node_version():
    """⑫ setup-node 不钉版本 ⇒ 必红。"""
    def mut(wf):
        for s in wf["jobs"][JOB]["steps"]:
            if str(s.get("uses", "")).startswith("actions/setup-node"):
                s["with"] = {}

    problems = _mutate(mut)
    assert any("node-version" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_missing_timeout():
    """⑬ 删掉 timeout-minutes ⇒ 必红。"""
    def mut(wf):
        wf["jobs"][JOB].pop("timeout-minutes", None)

    problems = _mutate(mut)
    assert any("timeout-minutes" in p for p in problems), f"应判红却得到 {problems!r}"


def test_checker_is_not_vacuous():
    """判据非空壳：空 workflow 必须被判红（否则上面所有「判红」都可能是恒绿）。"""
    problems = _problems({})
    assert problems, "空 workflow 竟判绿 —— 判据是空壳（恒真），红证全部无效"
