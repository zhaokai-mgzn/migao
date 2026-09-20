# case_ids: MC-016
r"""工人端 H5 对外落地面（`app.migaozn.com/w/`）的发布接线守卫（issue #4837）。

## 背景（实测，非推断）

`frontend/worker-h5/`（工人端 H5）**零依赖 + 零构建**，但此前**没有任何对外落地面**：
`grep -rn '/opt/migao-deploy' .github/workflows/` = **0 命中**（`deploy-frontend.yml` 只构建
admin-web；`mini-app.yml` 的 `xiaobu-h5-visual` 只 build 做视觉回归、**不发布**）。
而 `app.migaozn.com` 的静态根（nginx `root` = `/opt/migao-deploy/h5`）**同时承载线上 C 端 H5**
⇒ 稳定短链 302 到 `/w/` 时，`location /` 的 `try_files $uri $uri/ /index.html` **静默回落**：
**HTTP 200 + C 端 Taro H5**。实测（修复前）：

| 判据 | 实测值 |
|---|---|
| `curl -sI https://app.migaozn.com/w/` | **200**（所以「200」是**恒真的空断言**） |
| `curl -s https://app.migaozn.com/w/ \| shasum -a 256` | `3fe4eeed…` = **与 `/` 逐字节相同**（Taro C 端） |
| body 含 `TARO_ENV` / 不含 `src/app.mjs` | 1 / 0 |
| 远端 `/opt/migao-deploy/h5` | `index.html` + `js/` + `css/` + `chunk/`，**没有 `w/`** |

## 本守卫锁什么（每条都带注入式红证）

按**结构真值**判（读 YAML + 读真脚本 + **真跑一遍脚本**，不扫全文正则 ——
否则「注释里提一句」就算数 = 假绿，同 `test_worker_h5_ci_wiring.py` 口径）：

1. **发布步骤存在**且只通过 `deploy/scripts/swas-h5-publish-ci.sh` 发布，且**不得被静默化**
   （`continue-on-error` / `|| true` / 恒假 `if` —— 都是「红被吞」）；
2. **发布目标限定在 `<静态根>/w` 子树**（workflow 的 `H5_SUBDIR=w` ∧ CI 脚本默认值 ∧ 远端脚本的守卫函数）；
3. 🔴 **不得对静态根（父目录）做任何破坏性删除** —— 父目录同时承载线上 C 端 H5，清空即打掉 C 端。
   判据分三层：**脚本源码层**（每一条破坏性语句只允许指向 `$TARGET`/自建临时目录）+
   **行为层**（沙箱里跑真脚本：父目录 `index.html` 与 `js/` 逐字节不变）+ **自证层**
   （远端输出 `PARENT_INDEX_BEFORE_SHA256 == PARENT_INDEX_AFTER_SHA256`）；
4. **触发面含 `frontend/worker-h5/**`**（否则改了页面不发布 —— 正是本单要治的形态），
   且**刻意不含 `pull_request`**（PR 内容不得有机会落到线上静态根）；
5. **发布后有身份断言步骤**（`deploy/scripts/worker-h5-verify-served.sh`）——
   「200 就算过」不是判据（见上表：修复前就是 200）；
6. **行为级（沙箱跑真脚本）**：发布的 `w/index.html` 与 `w/src/app.mjs` 与本仓库**逐字节一致**、
   父目录不变、幂等（连跑两次同结果）、`w/` 子树内的陈旧文件被收敛、
   `tests/**` 不发、越界子目录（`..` / `.` / `/etc` / `a/b` / 空）**必须拒绝且什么都不动**；
7. **身份断言不是空断言**：起一个本地 HTTP server，`/w/` 返回 C 端页面时
   `worker-h5-verify-served.sh` **必须红**；返回本仓库文件时**必须绿**（同一条判据的两面）。

**⚠️ 本文件刻意分两层**：`_problems()` 是纯函数（结构层，注入式红证）；
沙箱行为层**真跑** `deploy/swas/h5-publish-remote.sh`（本地目录直达，**不联网**）——
「测试测的是另一份实现」这个形态结构上不可能出现。
"""
import copy
import hashlib
import http.server
import os
import re
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "worker-h5-publish.yml"
REMOTE_SCRIPT = REPO_ROOT / "deploy" / "swas" / "h5-publish-remote.sh"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-h5-publish-ci.sh"
VERIFY_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "worker-h5-verify-served.sh"

WORKER_H5_DIR = REPO_ROOT / "frontend" / "worker-h5"
WORKER_INDEX = WORKER_H5_DIR / "index.html"
WORKER_APP = WORKER_H5_DIR / "src" / "app.mjs"

JOB = "publish"
PUBLISH_SCRIPT = "deploy/scripts/swas-h5-publish-ci.sh"
VERIFY_SERVED = "deploy/scripts/worker-h5-verify-served.sh"
WORKER_H5_GLOB = "frontend/worker-h5/**"
STATIC_ROOT = "/opt/migao-deploy/h5"
SUBDIR = "w"

# 修复前线上 `/w/` 返回的东西（nginx try_files 静默回落到的 C 端 Taro H5 页）。
# 内容按实测特征构造：含 `window.TARO_ENV` 与 C 端标题，**不含** `src/app.mjs`。
C_END_PAGE = (
    '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"/>'
    "<title>米高窗帘 · 小布智能助手</title>"
    "<script>window.TARO_ENV = 'h5'</script>"
    '<script defer="defer" src="/js/app.js"></script></head>'
    '<body><div id="app"></div></body></html>'
).encode("utf-8")

DESTRUCTIVE_RE = re.compile(r"(rm\s+-[A-Za-z]*[rf][A-Za-z]*\b|--delete\b|-delete\b)")


# ── 读盘（缺失即判据失败，不静默）────────────────────────────────────────────

def _read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _on_key(wf: dict):
    """yaml 会把裸 `on:` 解析成布尔 True 键（同 test_worker_h5_ci_wiring.py 的处理）。

    变异样本必须改在**真键**上：写 `wf["on"] = …` 只会新增一个字符串键，
    布尔 True 键仍在 ⇒ 判据读到的还是旧值 ⇒ 红证**静默失效**。
    """
    return "on" if "on" in wf else True


def _triggers(wf: dict) -> dict:
    value = wf.get("on")
    if value is None:
        value = wf.get(True)
    return value if isinstance(value, dict) else {}


def _steps(wf: dict) -> list:
    job = (wf.get("jobs") or {}).get(JOB) or {}
    steps = job.get("steps")
    return steps if isinstance(steps, list) else []


def _run_text(step) -> str:
    return str((step or {}).get("run") or "")


def _root_destructive_lines(text: str) -> list:
    """在给定文本里找「既命名静态根、又做破坏性删除」的行（红线判据）。"""
    hits = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]
        if STATIC_ROOT not in line:
            continue
        if DESTRUCTIVE_RE.search(line):
            hits.append(raw.strip())
    return hits


def _unsanctioned_destructive_lines(text: str) -> list:
    """脚本里的破坏性语句必须只指向 `$TARGET`（受守卫的子树）或自建临时目录。

    这是**源码层**的红线；行为层的红证见 `test_sandbox_parent_is_untouched` /
    `test_sandbox_can_go_red_when_parent_is_purged`（后者证明这条源码判据不是纸上功夫）。
    """
    hits = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]
        if not DESTRUCTIVE_RE.search(line):
            continue
        if any(tok in line for tok in ("$TARGET", "$STAGE", "$WORK", "$TMPDIR", "$out_file")):
            continue
        hits.append(raw.strip())
    return hits


# ── 结构层判据（纯函数；注入式红证的判据对象）───────────────────────────────

def _problems(wf, remote_src=None, ci_src=None) -> list:
    if remote_src is None:
        remote_src = _read(REMOTE_SCRIPT)
    if ci_src is None:
        ci_src = _read(CI_SCRIPT)
    problems = []

    if remote_src is None:
        problems.append("远端执行体 deploy/swas/h5-publish-remote.sh 缺失 —— 发布逻辑没有单一出处")
    if ci_src is None:
        problems.append("CI 发布脚本 deploy/scripts/swas-h5-publish-ci.sh 缺失")
    if not _read(VERIFY_SCRIPT):
        problems.append("身份断言脚本 deploy/scripts/worker-h5-verify-served.sh 缺失")

    on = _triggers(wf)
    if not on:
        problems.append("workflow 没有可识别的 on 触发器")

    # ④ 触发面：push(main) 必须含 worker-h5 与链路自身；**不得**有 pull_request
    push = on.get("push") if isinstance(on.get("push"), dict) else {}
    branches = push.get("branches") or []
    if "main" not in branches:
        problems.append(f"push 触发面缺 main：{branches}")
    paths = push.get("paths") or []
    if WORKER_H5_GLOB not in paths:
        problems.append(f"push.paths 缺 {WORKER_H5_GLOB}（改了页面不发布）")
    if ".github/workflows/worker-h5-publish.yml" not in paths:
        problems.append("push.paths 缺本 workflow 自身（只改这条腿时不会触发 ⇒ 改坏了没有证据）")
    if "pull_request" in on or "pull_request_target" in on:
        problems.append("不得有 pull_request 触发：本 workflow 写的是**线上静态根**，PR 分流内容不该有机会落上去")

    # ① 发布步骤存在、指向单一脚本、未被静默化
    publish_steps = [s for s in _steps(wf) if PUBLISH_SCRIPT in _run_text(s)]
    verify_steps = [s for s in _steps(wf) if VERIFY_SERVED in _run_text(s)]
    if len(publish_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个跑 {PUBLISH_SCRIPT} 的 step，实际 {len(publish_steps)}")
    if len(verify_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个跑 {VERIFY_SERVED} 的身份断言 step，实际 {len(verify_steps)}")
    for step in publish_steps + verify_steps:
        if step.get("continue-on-error"):
            problems.append(f"step `{step.get('name')}` 带 continue-on-error ⇒ 红被吞")
        if "|| true" in _run_text(step):
            problems.append(f"step `{step.get('name')}` 带 `|| true` ⇒ 红被吞")
        if str(step.get("if", "")).strip().lower() in ("false", "0"):
            problems.append(f"step `{step.get('name')}` 的 if 恒假 ⇒ 红被吞")

    # ③ 红线（源码层）：workflow 自己不得对静态根做破坏性操作
    for step in _steps(wf):
        for line in _root_destructive_lines(_run_text(step)):
            problems.append(f"workflow 步骤里对静态根做破坏性删除（红线）：{line}")

    # ② 目标限定在 <静态根>/w 子树
    env = wf.get("env") or {}
    if env.get("H5_STATIC_ROOT") != STATIC_ROOT:
        problems.append(f"env.H5_STATIC_ROOT 必须是 {STATIC_ROOT}，实际 {env.get('H5_STATIC_ROOT')!r}")
    if env.get("H5_SUBDIR") != SUBDIR:
        problems.append(f"env.H5_SUBDIR 必须是 {SUBDIR!r}，实际 {env.get('H5_SUBDIR')!r}")

    if ci_src is not None:
        m = re.search(r"^SUBDIR=\$\{H5_SUBDIR-([^}]*)\}", ci_src, re.M)
        if not m or m.group(1) != SUBDIR:
            problems.append(
                "CI 脚本的 SUBDIR 默认值必须是 'w' 且用 `${H5_SUBDIR-w}`（显式置空 ⇒ 拒绝，而不是悄悄回落 w）："
                f"实际 {m.group(1)!r}" if m else "CI 脚本里找不到 `SUBDIR=${H5_SUBDIR-…}` 默认值"
            )
        m = re.search(r"^STATIC_ROOT=\$\{H5_STATIC_ROOT-([^}]*)\}", ci_src, re.M)
        if not m or m.group(1) != STATIC_ROOT:
            problems.append(f"CI 脚本的 STATIC_ROOT 默认值必须是 {STATIC_ROOT}")
        for token in ("TARGET=", "PUBLISHED_INDEX_SHA256", "PARENT_INDEX_BEFORE_SHA256", "PARENT_INDEX_AFTER_SHA256"):
            if token not in ci_src:
                problems.append(f"CI 脚本缺少发布自证/验收断言 `{token}`")
        for line in _unsanctioned_destructive_lines(ci_src):
            problems.append(f"CI 脚本里有未限定到 $TARGET 的破坏性语句（红线）：{line}")

    if remote_src is not None:
        if "assert_target_safe()" not in remote_src:
            problems.append("远端脚本必须在动手前调用 assert_target_safe()")
        if "purge_target()" not in remote_src:
            problems.append("远端脚本的清空动作必须走 purge_target()（只收敛 $TARGET 子树）")
        for line in _unsanctioned_destructive_lines(remote_src):
            problems.append(f"远端脚本里有未限定到 $TARGET 的破坏性语句（红线）：{line}")

    return problems


def _load_workflow() -> dict:
    text = _read(WORKFLOW_PATH)
    if text is None:
        pytest.fail(
            f"{WORKFLOW_PATH.relative_to(REPO_ROOT)} 不存在 —— 工人端 H5 又回到「没有任何对外落地面」"
            "（issue #4837 的形态本身）。删本 workflow 必须同时给出替代接线。"
        )
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


# ── 结构层：真文件判绿 ───────────────────────────────────────────────────────

def test_real_workflow_and_scripts_have_no_problems():
    problems = _problems(_load_workflow())
    assert problems == [], "发布接线判据不通过：\n  - " + "\n  - ".join(problems)


def test_worker_h5_entry_files_exist():
    """判据的前提资产（否则下面的身份断言无参照物）。"""
    assert WORKER_INDEX.is_file()
    assert WORKER_APP.is_file()
    assert "src/app.mjs" in WORKER_INDEX.read_text(encoding="utf-8")


# ── 结构层：注入式红证（每个变异都必须判红）────────────────────────────────

def _workflow_mutations(wf: dict) -> dict:
    def drop_publish(mut):
        mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if PUBLISH_SCRIPT not in _run_text(s)]

    def drop_verify(mut):
        mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if VERIFY_SERVED not in _run_text(s)]

    def drop_worker_path(mut):
        push = _triggers(mut)["push"]
        push["paths"] = [p for p in push["paths"] if p != WORKER_H5_GLOB]

    def drop_self_path(mut):
        push = _triggers(mut)["push"]
        push["paths"] = [p for p in push["paths"] if p != ".github/workflows/worker-h5-publish.yml"]

    def add_pull_request(mut):
        _triggers(mut)["pull_request"] = {"paths": [WORKER_H5_GLOB]}

    def silence_with_continue_on_error(mut):
        for step in _steps(mut):
            if PUBLISH_SCRIPT in _run_text(step):
                step["continue-on-error"] = True

    def silence_with_or_true(mut):
        for step in _steps(mut):
            if PUBLISH_SCRIPT in _run_text(step):
                step["run"] = _run_text(step) + "\n|| true"

    def silence_with_false_if(mut):
        for step in _steps(mut):
            if PUBLISH_SCRIPT in _run_text(step):
                step["if"] = "false"

    def add_root_wide_delete(mut):
        mut["jobs"][JOB]["steps"].append(
            {"name": "rsync worker-h5", "run": "rsync -a --delete frontend/worker-h5/ /opt/migao-deploy/h5/"}
        )

    def retarget_subdir(mut):
        mut["env"]["H5_SUBDIR"] = "."

    def retarget_static_root(mut):
        mut["env"]["H5_STATIC_ROOT"] = "/opt/migao-deploy"

    return {
        "删掉发布步骤": drop_publish,
        "删掉身份断言步骤": drop_verify,
        "触发面去掉 frontend/worker-h5/**": drop_worker_path,
        "触发面去掉 workflow 自身": drop_self_path,
        "给发布加上 pull_request 触发": add_pull_request,
        "发布步骤 continue-on-error": silence_with_continue_on_error,
        "发布步骤 || true": silence_with_or_true,
        "发布步骤 if: false": silence_with_false_if,
        "往静态根做 --delete": add_root_wide_delete,
        "把子目录改成 .": retarget_subdir,
        "把静态根改成上层目录": retarget_static_root,
    }


def test_workflow_mutations_are_all_detected():
    wf = _load_workflow()
    undetected = []
    for name, mutate in _workflow_mutations(copy.deepcopy(wf)).items():
        mutant = copy.deepcopy(wf)
        mutate(mutant)
        if len(_problems(mutant)) == 0:
            undetected.append(name)
    assert undetected == [], f"这些变异**没有被判红**（= 空断言）：{undetected}"


def test_script_mutations_are_all_detected():
    remote_src = _read(REMOTE_SCRIPT)
    ci_src = _read(CI_SCRIPT)
    assert isinstance(remote_src, str), "远端执行体缺失 ⇒ 无法做脚本层红证"

    bad_remote_parent_delete = remote_src.replace(
        'find "$TARGET" -mindepth 1 -delete', 'find "$STATIC_ROOT" -mindepth 1 -delete'
    )
    assert bad_remote_parent_delete != remote_src, "变异注入未生效（找不到被替换的清理语句）"

    bad_remote_rm_root = remote_src + '\nrm -rf "$STATIC_ROOT"\n'
    bad_remote_no_guard = remote_src.replace("assert_target_safe()", "true")
    assert bad_remote_no_guard != remote_src, "变异注入未生效（找不到 assert_target_safe() 调用）"

    bad_ci_subdir = re.sub(r"^SUBDIR=\$\{H5_SUBDIR-([^}]*)\}", "SUBDIR=${H5_SUBDIR-tmp}", ci_src or "", count=1, flags=re.M)
    assert bad_ci_subdir != (ci_src or ""), "变异注入未生效（找不到 SUBDIR 默认值）"

    bad_ci_delete_root = (ci_src or "") + '\nrsync -a --delete /tmp/x/ "$STATIC_ROOT/../"\n'

    samples = {
        "远端脚本把清理目标换成静态根": (bad_remote_parent_delete, ci_src),
        "远端脚本新增 rm -rf 静态根": (bad_remote_rm_root, ci_src),
        "远端脚本去掉目标守卫": (bad_remote_no_guard, ci_src),
        "CI 脚本子目录默认值被改": (remote_src, bad_ci_subdir),
        "CI 脚本新增未限定目标的删除": (remote_src, bad_ci_delete_root),
    }
    undetected = []
    for name, (remote, ci) in samples.items():
        if len(_problems(_load_workflow(), remote_src=remote, ci_src=ci)) == 0:
            undetected.append(name)
    assert undetected == [], f"这些脚本变异**没有被判红**（= 空断言）：{undetected}"


# ── 行为层：沙箱里真跑远端脚本（不联网）────────────────────────────────────

def _make_sandbox(tmp_path: Path) -> Path:
    """造一个「静态根」沙箱：父目录 = C 端 H5 产物，另有沙箱外的哨兵文件。"""
    root = tmp_path / "h5"
    (root / "js").mkdir(parents=True)
    (root / "css").mkdir()
    (root / "index.html").write_bytes(C_END_PAGE)
    (root / "js" / "app.js").write_text("// C 端 Taro 产物", encoding="utf-8")
    (root / "css" / "app.css").write_text(".c-end{}", encoding="utf-8")
    (tmp_path / "sentinel-outside.txt").write_text("静态根之外的文件，任何情况下都不该被动", encoding="utf-8")
    return root


def _run_publish(root: Path, subdir: str = SUBDIR, from_dir=None, sha=None, script: Path = None):
    env = dict(os.environ)
    env["H5_STATIC_ROOT"] = str(root)
    env["H5_SUBDIR"] = subdir
    env.pop("H5_PUBLISH_SHA", None)
    env.pop("H5_PUBLISH_FROM_DIR", None)
    if from_dir is not None:
        env["H5_PUBLISH_FROM_DIR"] = str(from_dir)
    if sha is not None:
        env["H5_PUBLISH_SHA"] = sha
    return subprocess.run(
        ["bash", str(script or REMOTE_SCRIPT)],
        capture_output=True, text=True, env=env, timeout=180, cwd=str(REPO_ROOT),
    )


def _tree(root: Path) -> dict:
    return {
        str(p.relative_to(root)): _file_sha(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_sandbox_publish_is_identity_and_preserves_parent(tmp_path):
    root = _make_sandbox(tmp_path)
    parent_before = _tree(root)

    proc = _run_publish(root, from_dir=WORKER_H5_DIR)
    assert proc.returncode == 0, f"沙箱发布失败：\n{proc.stdout}\n{proc.stderr}"

    # ① 身份：发布的 index.html / src/app.mjs 与仓库逐字节一致
    published_index = root / SUBDIR / "index.html"
    published_app = root / SUBDIR / "src" / "app.mjs"
    assert _file_sha(published_index) == _file_sha(WORKER_INDEX), "发布的 index.html 与仓库不一致"
    assert _file_sha(published_app) == _file_sha(WORKER_APP), "发布的 src/app.mjs 与仓库不一致"
    body = published_index.read_text(encoding="utf-8")
    assert "src/app.mjs" in body
    assert "TARO_" not in body and "小布智能助手" not in body

    # tests/ 不发
    assert not (root / SUBDIR / "tests").exists(), "tests/ 不该被发布"

    # ② 红线：父目录（C 端 H5）逐字节不变
    assert _tree(root)["index.html"] == parent_before["index.html"]
    assert (root / "js" / "app.js").is_file()
    assert (root / "css" / "app.css").is_file()
    assert _tree(root)["js/app.js"] == parent_before["js/app.js"]
    assert (tmp_path / "sentinel-outside.txt").is_file()

    # ③ 自证层：远端输出必须报告父目录未被触碰
    assert f"TARGET={root}/{SUBDIR}" in proc.stdout
    before = re.search(r"^PARENT_INDEX_BEFORE_SHA256=(.+)$", proc.stdout, re.M)
    after = re.search(r"^PARENT_INDEX_AFTER_SHA256=(.+)$", proc.stdout, re.M)
    assert isinstance(before, re.Match) and isinstance(after, re.Match), f"缺父目录自证行：\n{proc.stdout}"
    assert before.group(1).strip() == _file_sha(root / "index.html")
    assert before.group(1) == after.group(1)
    published = re.search(r"^PUBLISHED_INDEX_SHA256=(.+)$", proc.stdout, re.M)
    assert isinstance(published, re.Match), f"缺发布自证行：\n{proc.stdout}"
    assert published.group(1).strip() == _file_sha(WORKER_INDEX)


def test_sandbox_publish_is_idempotent_and_converges_only_w_subtree(tmp_path):
    root = _make_sandbox(tmp_path)
    first = _run_publish(root, from_dir=WORKER_H5_DIR)
    assert first.returncode == 0, first.stdout + first.stderr
    tree_after_first = _tree(root)

    # 目标子树里放一个陈旧文件（模拟上一次发布留下的、这次不该存在的文件）
    stale = root / SUBDIR / "stale.js"
    stale.write_text("// 上一次发布的残留", encoding="utf-8")

    second = _run_publish(root, from_dir=WORKER_H5_DIR)
    assert second.returncode == 0, second.stdout + second.stderr
    assert not stale.exists(), "w/ 子树内的陈旧文件必须被收敛（幂等的另一半）"
    assert _tree(root) == tree_after_first, "连跑两次结果不一致（不幂等）"
    assert (root / "js" / "app.js").is_file(), "父目录被误删"


@pytest.mark.parametrize("bad_subdir", ["..", ".", "", "/etc", "a/b", ".hidden", "w/../.."])
def test_sandbox_refuses_out_of_scope_subdir(tmp_path, bad_subdir):
    root = _make_sandbox(tmp_path)
    parent_before = _tree(root)
    outside_before = sorted(p.name for p in tmp_path.iterdir())

    proc = _run_publish(root, subdir=bad_subdir, from_dir=WORKER_H5_DIR)

    assert proc.returncode != 0, f"越界子目录 {bad_subdir!r} 竟被放行：\n{proc.stdout}"
    assert _tree(root) == parent_before, f"越界子目录 {bad_subdir!r} 时静态根被改动（红线）"
    assert sorted(p.name for p in tmp_path.iterdir()) == outside_before, "越界子目录时在静态根之外产生了副作用"


def test_sandbox_refuses_absent_static_root_and_missing_source(tmp_path):
    absent = tmp_path / "not-there" / "h5"
    proc = _run_publish(absent, from_dir=WORKER_H5_DIR)
    assert proc.returncode != 0, "静态根不存在时应 fail-closed（宁可红，不新建目录）"
    assert not absent.exists(), "拒绝路径上不许建目录"

    root = _make_sandbox(tmp_path)
    proc = _run_publish(root)  # 既无 from_dir 也无 sha
    assert proc.returncode != 0, "既没给发布源也没给 sha 时必须拒绝"
    assert (root / SUBDIR).exists() is False, "拒绝时不该产出 w/ 子树"


def test_sandbox_can_go_red_when_parent_is_purged(tmp_path):
    """红证（证明上面的「父目录不变」断言**有判别力**）：

    把清理目标从 `$TARGET` 换成 `$STATIC_ROOT` 的变异脚本跑一遍 ⇒ 父目录**必须**被打坏。
    如果这一条绿（父目录没事），说明沙箱根本抓不到「清空静态根」这种实现 ⇒
    `test_sandbox_publish_is_identity_and_preserves_parent` 的父目录断言就是空断言。
    """
    root = _make_sandbox(tmp_path)
    mutant = tmp_path / "mutant-publish.sh"
    src = _read(REMOTE_SCRIPT)
    assert isinstance(src, str), "远端执行体缺失"
    mutated = src.replace('find "$TARGET" -mindepth 1 -delete', 'find "$STATIC_ROOT" -mindepth 1 -delete')
    assert mutated != src, "变异注入未生效"
    mutant.write_text(mutated, encoding="utf-8")

    proc = _run_publish(root, from_dir=WORKER_H5_DIR, script=mutant)
    assert (root / "js" / "app.js").exists() is False, (
        "变异脚本没有打坏父目录 —— 说明沙箱的父目录断言抓不到这类实现（空断言）：\n" + proc.stdout
    )


# ── 身份断言脚本自身的红/绿两面（防空断言）────────────────────────────────

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 静音访问日志
        return None


def _serve(directory: Path):
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(directory), **kw)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _wait_port(host: str, port: int) -> None:
    for _ in range(100):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((host, port)) == 0:
                return


def _run_verify(base_url: str):
    return subprocess.run(
        ["bash", str(VERIFY_SCRIPT), base_url],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
    )


def test_verify_served_is_green_on_real_worker_h5(tmp_path):
    served = tmp_path / "served"
    (served / SUBDIR / "src").mkdir(parents=True)
    (served / SUBDIR / "index.html").write_bytes(WORKER_INDEX.read_bytes())
    (served / SUBDIR / "src" / "app.mjs").write_bytes(WORKER_APP.read_bytes())
    server = _serve(served)
    try:
        _wait_port("127.0.0.1", server.server_address[1])
        proc = _run_verify(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
    assert proc.returncode == 0, f"身份断言在真页面上竟失败：\n{proc.stdout}\n{proc.stderr}"
    assert "✅ 落地面身份断言全过" in proc.stdout


def test_verify_served_is_red_on_c_end_fallback(tmp_path):
    """修复前的真实状态：`/w/` 返回 C 端 Taro 页面（200）。

    「200 就算过」在这种输入下必须**红** —— 这是本单防空断言的核心红证。
    """
    served = tmp_path / "served"
    (served / SUBDIR).mkdir(parents=True)
    (served / SUBDIR / "index.html").write_bytes(C_END_PAGE)
    server = _serve(served)
    try:
        _wait_port("127.0.0.1", server.server_address[1])
        proc = _run_verify(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
    assert proc.returncode == 1, f"C 端回落到 /w/ 时身份断言竟判绿（空断言）：\n{proc.stdout}"
    assert "❌ 落地面身份断言**失败" in proc.stdout
    assert "TARO_" in proc.stdout or "小布智能助手" in proc.stdout
