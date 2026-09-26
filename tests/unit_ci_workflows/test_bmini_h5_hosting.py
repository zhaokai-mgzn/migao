# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。
#   本 PR 不新建用例族。）
r"""B 端 h5（`frontend/bmini-app` 的 `build:h5` 产物）**对外落地面**的常驻判据（issue #5668）。

## 病根（开工前实测）

| 件 | 读数 |
|---|---|
| `grep -rln bmini .github/workflows/ deploy/` | 只命中 CI（typecheck / 单测 / 构建，**不发布**） |
| `grep -n bmini deploy/swas/nginx.conf` | **0 命中** |
| ⇒ 结论 | 功能全做完，**浏览器里也打不开** |

## 本守卫锁什么（每条都带注入式红证）

1. **发布腿存在且未被静默化**：`push(main)` 触发面含 `frontend/bmini-app/**` + 发布链路自身
   + `deploy/swas/nginx.conf`；**刻意没有 `pull_request`**（这条腿写的是线上静态根）；
   发布/断言两个 step 不得带 `continue-on-error` / `|| true` / 恒假 `if`；
2. **产物身份断言在案**（#4249 的教训：**不许复用旧静态服务把旧产物当成交付**）：
   CI 侧必须拿 `PUBLISHED_INDEX_SHA256` 与**本仓库 `dist/index.html`** 比对，且要求远端给出
   `ASSET_REFS_SCOPED` / `ASSETS_PRESENT` 自证行（沉默不算通过）；
3. 🔴 **命名空间闸门**（本应用特有）：bmini 与 C 端**同为 Taro 产物、资源同名同路径**
   （实测两端都是 `js/app.js` / `css/app.css`，`<title>` 与 `window.TARO_ENV` 也逐字相同
   ⇒ **标记法区分不了这两端**）。产物必须按 `/<SUBDIR>/` 构建，且本地与远端**各判一次**
   （本地在发起云调用之前 fail-closed；远端在写入目标之前 fail-closed）；
4. 🔴 **nginx 语义**（本单最危险的一处）：`/b/` 必须有**落在自己命名空间内的 fallback**
   —— 否则 `/b/<子路由>` 会静默回落根 `index.html`（= C 端小布，**HTTP 200**，监控不红）；
   且**不得劫持根**（根仍由 `location /` 承担）。判据是**真解析 + 真模拟**（见 `_serve()`），
   不是文本匹配；
5. **类级固化**（`migao-dev-flow` §23）：**任何**静态 `location` 的 `try_files` fallback
   都不得跨出该 location 自己的前缀命名空间 —— 同一个静态根下多应用共用 fallback ⇒ 静默串端。
   这条是**类级**判据：新增第三个子应用时照样适用；
6. **行为层（沙箱跑真脚本）**：从目录发布 bmini 产物 ⇒ 逐字节一致、父目录（C 端）不变、
   幂等、子树内陈旧文件被收敛、越界子目录/缺静态根/缺发布源一律拒绝且什么都不动；
7. **落地面断言脚本不是空断言**：起一个 nginx 语义的本地 server，四种坏形态各跑一遍 ⇒
   **必须**判红：① `/b/<子路由>` 回落根页（nginx 少了 `/b/` 的 fallback）
   ② 根被劫持（根返回 bmini 产物）③ `/b/` 是**旧产物**（不是本仓库这次构建）
   ④ worker-h5（`/w/`）坏了。

**⚠️ 本文件刻意分两层**：结构层是纯函数（注入式红证）；沙箱层**真跑**
`deploy/swas/bmini-h5-publish-remote.sh`（本地目录直达，**不联网、不碰真实静态根**）。
「测试测的是另一份实现」这个形态结构上不可能出现。

## 边界（照实登记，别把"登记了"读成"治住了"）

- 本机**没有** nginx 二进制、**没有** docker ⇒ 证明不了 `nginx -t` 的语法通过，也跑不了
  「从传输镜像里 `docker cp` 取产物」那一步（`deploy/bmini-h5/Dockerfile` 只是结构判据的对象）。
- 线上那一步（SWAS 上的真实发布 + `https://app.migaozn.com/b/` 的 served 断言）由
  `.github/workflows/bmini-h5-publish.yml` 在 main 上跑；**本文件不代替它**。
- `_serve()` 只模拟 nginx 的**前缀 location + try_files + index** 三件事（本段用到的全集）；
  正则 location / `alias` / `rewrite` 等不在面内 —— 故本文件另有一条判据要求
  `app.migaozn.com` 段里**不出现**正则 location（否则模拟的前提不成立即红）。
"""
from __future__ import annotations

import copy
import hashlib
import http.server
import os
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "bmini-h5-publish.yml"
REMOTE_SCRIPT = REPO_ROOT / "deploy" / "swas" / "bmini-h5-publish-remote.sh"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "bmini-h5-publish-ci.sh"
VERIFY_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "bmini-h5-verify-served.sh"
WORKER_VERIFY_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "worker-h5-verify-served.sh"
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
WORKER_H5_DIR = REPO_ROOT / "frontend" / "worker-h5"

JOB = "publish"
PUBLISH_SCRIPT = "deploy/scripts/bmini-h5-publish-ci.sh"
VERIFY_SERVED = "deploy/scripts/bmini-h5-verify-served.sh"
BMINI_GLOB = "frontend/bmini-app/**"
NGINX_CONF_GLOB = "deploy/swas/nginx.conf"
STATIC_ROOT = "/opt/migao-deploy/h5"
SUBDIR = "b"
SERVER_NAME = "app.migaozn.com"

DESTRUCTIVE_RE = re.compile(r"(rm\s+-[A-Za-z]*[rf][A-Za-z]*\b|--delete\b|-delete\b)")

# C 端小布的一页（与 `/` 的落地面同形；**注意**：bmini 产物的 `<title>` 与它逐字相同 ——
# 这正是本单不能靠标记判身份的原因，见模块 docstring 判据 3）
C_END_PAGE = (
    '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"/>'
    "<title>米高窗帘 · 小布智能助手</title>"
    "<script>window.TARO_ENV = 'h5'</script>"
    '<script defer="defer" src="/js/app.js"></script></head>'
    '<body><div id="app"></div></body></html>'
).encode("utf-8")

# bmini 产物的一页（结构照实测的 `dist/index.html`：`/b/` 前缀 + Taro 占位脚本）。
# `legacy=True` 造出**默认 publicPath** 的那一版（引用根级 `/js/app.js`）—— 判据 3 的红证输入。
def _bmini_page(legacy: bool = False) -> bytes:
    prefix = "" if legacy else f"/{SUBDIR}"
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"/>'
        "<title>米高窗帘 · 小布智能助手</title>"
        "<script>window.TARO_ENV = 'h5'</script>"
        f'<script defer="defer" src="{prefix}/js/app.js"></script>'
        f'<link href="{prefix}/css/app.css" rel="stylesheet"></head>'
        '<body><div id="app"></div></body></html>'
    ).encode("utf-8")


# ── 读盘（缺失即判据失败，不静默）────────────────────────────────────────────

def _read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _on_key(wf: dict):
    """yaml 会把裸 `on:` 解析成布尔 True 键（同 test_worker_h5_hosting.py 的处理）。"""
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


def _unsanctioned_destructive_lines(text: str) -> list:
    """破坏性语句必须只指向受守卫的目标或自建临时目录（源码层红线）。

    `docker rm -f <临时容器>` 属**容器**清理（不碰文件系统），且只针对本脚本自己
    `docker create` 出来的容器 ⇒ 单独放行（判据仍要求它出现的行里有 `$cid` 变量名）。
    """
    hits = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]
        if not DESTRUCTIVE_RE.search(line):
            continue
        if re.search(r"\bdocker\s+rm\b", line) and "$cid" in line:
            continue
        if any(tok in line for tok in ("$TARGET", "$STAGE", "$WORK", "$work", "$TMPDIR", "$out_file")):
            continue
        hits.append(raw.strip())
    return hits


# ── 结构层：发布腿（纯函数 + 注入式红证）────────────────────────────────────

def _workflow_problems(wf, remote_src=None, ci_src=None, verify_src=None) -> list:
    if remote_src is None:
        remote_src = _read(REMOTE_SCRIPT)
    if ci_src is None:
        ci_src = _read(CI_SCRIPT)
    if verify_src is None:
        verify_src = _read(VERIFY_SCRIPT)
    problems: list = []

    if not remote_src:
        problems.append("远端执行体 deploy/swas/bmini-h5-publish-remote.sh 缺失 —— 发布逻辑没有单一出处")
    if not ci_src:
        problems.append("CI 发布脚本 deploy/scripts/bmini-h5-publish-ci.sh 缺失")
    if not verify_src:
        problems.append("落地面断言脚本 deploy/scripts/bmini-h5-verify-served.sh 缺失")

    on = _triggers(wf)
    if not on:
        problems.append("workflow 没有可识别的 on 触发器")

    push = on.get("push") if isinstance(on.get("push"), dict) else {}
    if "main" not in (push.get("branches") or []):
        problems.append(f"push 触发面缺 main：{push.get('branches')}")
    paths = push.get("paths") or []
    for required in (BMINI_GLOB, NGINX_CONF_GLOB, ".github/workflows/bmini-h5-publish.yml"):
        if required not in paths:
            problems.append(f"push.paths 缺 {required}")
    for chain in ("deploy/swas/bmini-h5-publish-remote.sh", PUBLISH_SCRIPT, VERIFY_SERVED):
        if chain not in paths:
            problems.append(f"push.paths 缺发布链路自身 {chain}（改坏了没有证据）")
    if not any(str(p).startswith("deploy/bmini-h5/") for p in paths):
        problems.append("push.paths 缺传输载体目录 deploy/bmini-h5/**（改了 Dockerfile 不重跑 ⇒ 改坏了没有证据）")
    if "pull_request" in on or "pull_request_target" in on:
        problems.append("不得有 pull_request 触发：本 workflow 写的是**线上静态根**，PR 分流内容不该有机会落上去")

    publish_steps = [s for s in _steps(wf) if PUBLISH_SCRIPT in _run_text(s)]
    verify_steps = [s for s in _steps(wf) if VERIFY_SERVED in _run_text(s)]
    build_steps = [s for s in _steps(wf) if "build:h5" in _run_text(s)]
    if len(publish_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个跑 {PUBLISH_SCRIPT} 的 step，实际 {len(publish_steps)}")
    if len(verify_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个跑 {VERIFY_SERVED} 的落地面断言 step，实际 {len(verify_steps)}")
    if len(build_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个 `npm run build:h5` step（产物必须在 CI 构建），实际 {len(build_steps)}")
    for step in publish_steps + verify_steps + build_steps:
        if step.get("continue-on-error"):
            problems.append(f"step `{step.get('name')}` 带 continue-on-error ⇒ 红被吞")
        if "|| true" in _run_text(step):
            problems.append(f"step `{step.get('name')}` 带 `|| true` ⇒ 红被吞")
        if str(step.get("if", "")).strip().lower() in ("false", "0"):
            problems.append(f"step `{step.get('name')}` 的 if 恒假 ⇒ 红被吞")

    env = wf.get("env") or {}
    if env.get("H5_STATIC_ROOT") != STATIC_ROOT:
        problems.append(f"env.H5_STATIC_ROOT 必须是 {STATIC_ROOT}，实际 {env.get('H5_STATIC_ROOT')!r}")
    if env.get("H5_SUBDIR") != SUBDIR:
        problems.append(f"env.H5_SUBDIR 必须是 {SUBDIR!r}，实际 {env.get('H5_SUBDIR')!r}")
    # 🔴 命名空间闸门的一半在构建期：资源前缀必须与落位一致（否则产物引用 C 端的包）
    if env.get("TARO_APP_H5_PUBLIC_PATH") != f"/{SUBDIR}/":
        problems.append(
            f"env.TARO_APP_H5_PUBLIC_PATH 必须是 '/{SUBDIR}/'（落位在 /{SUBDIR}/ ⇒ 资源前缀同前缀），"
            f"实际 {env.get('TARO_APP_H5_PUBLIC_PATH')!r} —— 漏了它产物会引用根级 /js/app.js（= C 端的包）"
        )
    if not str(env.get("TARO_APP_API_URL") or "").startswith("https://"):
        problems.append(
            f"env.TARO_APP_API_URL 必须是 https 公网地址（h5 是浏览器直连，不是微信内），实际 {env.get('TARO_APP_API_URL')!r}"
        )

    if ci_src:
        # 判据形态**逐字**在案（不是"提到过这个词"）：这几行就是本腿的全部价值 ——
        # 产品身份（线上 == 这次构建）、静态根未被触碰、命名空间与完整性自证、远端不许静默失败。
        for token in (
            'grep -q "^TARGET=$EXPECTED_TARGET$"',
            '[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ]',
            '[ "$PARENT_BEFORE" = "$PARENT_AFTER" ]',
            'grep -q "^ASSET_REFS_SCOPED=1$"',
            'grep -q "^ASSETS_PRESENT=1$"',
            '[ "$STATUS" = "Success" ] || die',
        ):
            if token not in ci_src:
                problems.append(f"CI 脚本缺少验收断言（逐字形态）`{token}`")
        for token in ("PUBLISHED_INDEX_SHA256", "PARENT_INDEX_BEFORE_SHA256", "PARENT_INDEX_AFTER_SHA256"):
            if token not in ci_src:
                problems.append(f"CI 脚本缺少发布自证标记 `{token}`")
        if 'LOCAL_INDEX="$DIST_DIR/index.html"' not in ci_src:
            problems.append("CI 脚本必须把 `frontend/bmini-app/dist/index.html` 作为身份基准（产物单一源）")
        for line in _unsanctioned_destructive_lines(ci_src):
            problems.append(f"CI 脚本里有未限定目标的破坏性语句（红线）：{line}")

    if remote_src:
        for token in ("assert_target_safe()", "purge_target()", "assert_product_scoped()"):
            if token not in remote_src:
                problems.append(f"远端脚本必须调用 {token}")
        for line in _unsanctioned_destructive_lines(remote_src):
            problems.append(f"远端脚本里有未限定目标的破坏性语句（红线）：{line}")

    return problems


def _load_workflow() -> dict:
    text = _read(WORKFLOW_PATH)
    if text is None:
        pytest.fail(
            f"{WORKFLOW_PATH.relative_to(REPO_ROOT)} 不存在 —— B 端 h5 又回到「没有任何对外落地面」"
            "（issue #5668 的形态本身）。删本 workflow 必须同时给出替代接线。"
        )
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def test_real_publish_leg_has_no_problems():
    problems = _workflow_problems(_load_workflow())
    assert problems == [], "发布接线判据不通过：\n  - " + "\n  - ".join(problems)


def test_workflow_mutations_are_all_detected():
    wf = _load_workflow()

    def drop_publish(mut):
        mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if PUBLISH_SCRIPT not in _run_text(s)]

    def drop_verify(mut):
        mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if VERIFY_SERVED not in _run_text(s)]

    def drop_build(mut):
        mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if "build:h5" not in _run_text(s)]

    def drop_bmini_path(mut):
        push = _triggers(mut)["push"]
        push["paths"] = [p for p in push["paths"] if p != BMINI_GLOB]

    def drop_nginx_path(mut):
        push = _triggers(mut)["push"]
        push["paths"] = [p for p in push["paths"] if p != NGINX_CONF_GLOB]

    def add_pull_request(mut):
        _triggers(mut)["pull_request"] = {"paths": [BMINI_GLOB]}

    def silence_verify(mut):
        for step in _steps(mut):
            if VERIFY_SERVED in _run_text(step):
                step["continue-on-error"] = True

    def retarget_subdir(mut):
        mut["env"]["H5_SUBDIR"] = "."

    def retarget_root(mut):
        mut["env"]["H5_STATIC_ROOT"] = "/opt/migao-deploy"

    def drop_public_path(mut):
        mut["env"].pop("TARO_APP_H5_PUBLIC_PATH", None)

    def api_to_localhost(mut):
        mut["env"]["TARO_APP_API_URL"] = "http://localhost:8080"

    mutations = {
        "删掉发布步骤": drop_publish,
        "删掉落地面断言步骤": drop_verify,
        "删掉 build:h5 步骤": drop_build,
        "触发面去掉 frontend/bmini-app/**": drop_bmini_path,
        "触发面去掉 nginx.conf": drop_nginx_path,
        "给发布加 pull_request 触发": add_pull_request,
        "断言步骤 continue-on-error": silence_verify,
        "把子目录改成 .": retarget_subdir,
        "把静态根改成上层目录": retarget_root,
        "去掉 TARO_APP_H5_PUBLIC_PATH": drop_public_path,
        "把 API 地址改成 localhost": api_to_localhost,
    }
    undetected = []
    for name, mutate in mutations.items():
        mutant = copy.deepcopy(wf)
        mutate(mutant)
        if len(_workflow_problems(mutant)) == 0:
            undetected.append(name)
    assert undetected == [], f"这些变异**没有被判红**（= 空断言）：{undetected}"


def test_ci_script_mutations_are_all_detected():
    ci_src = _read(CI_SCRIPT)
    assert isinstance(ci_src, str), "CI 发布脚本缺失 ⇒ 无法做脚本层红证"

    no_identity = ci_src.replace("[ \"$REMOTE_INDEX_SHA\" = \"$LOCAL_SHA\" ]", "true")
    assert no_identity != ci_src, "变异注入未生效（找不到产物身份断言）"

    no_scope_gate = ci_src.replace("ASSET_REFS_SCOPED=1", "ASSET_REFS_SCOPED=0")
    assert no_scope_gate != ci_src, "变异注入未生效（找不到命名空间自证行）"

    root_delete = ci_src + '\nrsync -a --delete /tmp/x/ "$STATIC_ROOT/../"\n'

    samples = {
        "去掉「线上哈希 == 本仓库产物哈希」断言": no_identity,
        "把命名空间自证行改成 0（远端不再自证）": no_scope_gate,
        "新增未限定目标的删除": root_delete,
    }
    undetected = []
    for name, mutant in samples.items():
        if len(_workflow_problems(_load_workflow(), ci_src=mutant)) == 0:
            undetected.append(name)
    assert undetected == [], f"这些脚本变异**没有被判红**（= 空断言）：{undetected}"


# ── nginx：真解析 + 真模拟（判据 4 / 5）──────────────────────────────────────

LOCATION_RE = re.compile(r"^\s*location\s+(?P<mod>[=~^*]*)\s*(?P<prefix>\S+)\s*\{(?P<body>[^}]*)\}", re.S | re.M)


def _server_blocks(conf: str) -> list[str]:
    """切出 nginx.conf 里每个 `server { … }` 段（按花括号配平）。"""
    blocks = []
    for m in re.finditer(r"\bserver\s*\{", conf):
        i = conf.index("{", m.start())
        depth, j = 0, i
        while j < len(conf):
            if conf[j] == "{":
                depth += 1
            elif conf[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blocks.append(conf[i + 1:j])
    return blocks


def _app_server_block(conf: str) -> str:
    for body in _server_blocks(conf):
        if re.search(rf"server_name[^;]*\b{re.escape(SERVER_NAME)}\b", body) and "listen 443" in body:
            return body
    pytest.fail(f"nginx.conf 里找不到 {SERVER_NAME} 的 443 server 段")


def _locations(block: str) -> list[dict]:
    out = []
    for m in LOCATION_RE.finditer(block):
        if m.group("mod").strip():
            continue  # 只收前缀 location（模拟器覆盖的形态；正则 location 另由判据挡下）
        body = m.group("body")
        tf = re.search(r"try_files\s+([^;]+);", body)
        out.append(
            {
                "prefix": m.group("prefix"),
                "try_files": tf.group(1).split() if tf else None,
                "proxy_pass": bool(re.search(r"proxy_pass\s+\S+;", body)),
            }
        )
    return out


def _serve(block: str, files: set[str], request_path: str, index: str = "index.html") -> str:
    """按 nginx 语义（前缀 location 取最长者 + try_files + index）算出**被伺候的文件**。

    `files` = 虚拟文件系统（静态根下的相对路径集合，目录由路径前缀隐含）。
    返回 `(相对路径)` 或 `"404"`。**本函数就是判据 4/5 的判据对象**：它认的是结构，
    不认注释与文案 —— 「注释里写了要有 fallback」不会让它绿。
    """
    dirs = {""}
    for f in files:
        parts = f.split("/")
        for k in range(1, len(parts)):
            dirs.add("/".join(parts[:k]))
    locs = _locations(block)
    if not locs:
        return "404"

    def exists_file(p: str) -> bool:
        return p.lstrip("/") in files

    def exists_dir(p: str) -> bool:
        return p.strip("/") in dirs or p == "/"

    def resolve(path: str, depth: int = 0) -> str:
        if depth > 5:  # 内部重定向成环
            return "404"
        # 前缀匹配取最长者（与书写顺序无关）
        matched = None
        for loc in locs:
            p = loc["prefix"]
            if path == p or path.startswith(p) or (p == "/"):
                if matched is None or len(p) > len(matched["prefix"]):
                    matched = loc
        if matched is None:
            return "404"
        tf = matched["try_files"]
        if not tf:
            return "404" if not exists_file(path) else path.lstrip("/")
        for arg in tf[:-1]:
            if arg == "$uri":
                if exists_file(path):
                    return path.lstrip("/")
                if exists_dir(path) and exists_file(path.rstrip("/") + "/" + index):
                    return (path.rstrip("/") + "/" + index).lstrip("/")
            elif arg == "$uri/":
                cand = path.rstrip("/") + "/"
                if exists_dir(cand) and exists_file(cand + index):
                    return (cand + index).lstrip("/")
        last = tf[-1]
        if last.startswith("="):
            return last[1:] if last == "=404" else last
        return resolve(last, depth + 1)

    return resolve(request_path)


def _app_locations():
    return _locations(_app_server_block(_read(NGINX_CONF) or ""))


def _static_fs() -> set[str]:
    """线上静态根的**预期形态**：C 端（根 `index.html` + `js/`）、工人端 `w/`、bmini `b/`。"""
    return {
        "index.html",
        "js/app.js",
        "css/app.css",
        f"{SUBDIR}/index.html",
        f"{SUBDIR}/js/app.js",
        f"{SUBDIR}/css/app.css",
        f"{SUBDIR}/chunk/850.js",
        "w/index.html",
        "w/src/app.mjs",
    }


APP_BLOCK = None


def _block():
    global APP_BLOCK
    if APP_BLOCK is None:
        APP_BLOCK = _app_server_block(_read(NGINX_CONF) or "")
    return APP_BLOCK


def test_app_server_has_no_regex_location():
    """模拟器的前提：本段不出现正则 location（有不等于判据失效，直接红）。"""
    block = _read(NGINX_CONF) or ""
    for m in LOCATION_RE.finditer(_app_server_block(block)):
        if m.group("mod").strip():
            pytest.fail(f"{SERVER_NAME} 段出现了非前缀 location（模拟器不覆盖该形态，需同步判据）：{m.group(0)[:60]}")


def test_bmini_subroute_is_served_by_own_fallback():
    """判据 4 正面：`/b/<任意子路由>` 必须返回 **bmini 自己的 index.html**。"""
    files = _static_fs()
    served = _serve(_block(), files, f"/{SUBDIR}/orders/2026/detail")
    assert served == f"{SUBDIR}/index.html", (
        f"`/{SUBDIR}/orders/2026/detail` 落到 `{served}` —— 期望 `{SUBDIR}/index.html`"
        "（若落到 `index.html` 就是**静默串端**：URL 是 /b/…、页面是 C 端小布，且 HTTP 200）"
    )
    assert _serve(_block(), files, f"/{SUBDIR}/") == f"{SUBDIR}/index.html"
    assert _serve(_block(), files, f"/{SUBDIR}/index.html") == f"{SUBDIR}/index.html"


def test_root_still_served_by_c_end_and_not_hijacked():
    """判据 4 反面：根与根级子路由仍由 C 端承担（`/b/` 规则不许吃掉根）。"""
    files = _static_fs()
    assert _serve(_block(), files, "/") == "index.html"
    served = _serve(_block(), files, "/some/c-end/spa/route")
    assert served == "index.html", (
        f"根级子路由落到 `{served}` —— 期望 C 端的 `index.html`（`/b/` 的规则劫持了根？）"
    )


def test_worker_h5_landing_unchanged_by_the_new_location():
    """零回归（结构层）：`/w/` 仍靠 `location /` 的目录索引落地，`/s/` 仍走 admin-api 代理。"""
    files = _static_fs()
    assert _serve(_block(), files, "/w/") == "w/index.html"
    assert _serve(_block(), files, "/w/src/app.mjs") == "w/src/app.mjs"
    s_locations = [loc for loc in _app_locations() if loc["prefix"] == "/s/"]
    assert len(s_locations) == 1, "`/s/` 段必须仍有且只有一条前缀 location（工人端稳定短链）"
    assert s_locations[0]["proxy_pass"], "`/s/` 必须仍是 admin-api 代理（不许被静态面吃掉）"
    t = _read(NGINX_CONF) or ""
    assert "limit_req zone=worker_entry burst=1000 nodelay;" in t, "`/s/` 的限流档被改动（工人端零回归判据）"


def test_class_level_invariant_fallback_must_stay_in_own_namespace():
    """判据 5（**类级固化**）：任何静态 location 的 try_files fallback 都不得跨出自己的前缀。

    病灶类别 = 「**同一个静态根下多个应用共用 fallback ⇒ 静默串端**」。
    实例（`/b/` 的 fallback 必须落在 `/b/`）只覆盖今天这一个子应用；这条类级判据对
    **将来新增的第三个子应用**同样生效：`location /x/ { try_files … /index.html; }` ⇒ 红。
    """
    offenders = []
    for loc in _app_locations():
        tf = loc["try_files"]
        if not tf or loc["proxy_pass"]:
            continue
        last = tf[-1]
        if not last.startswith("/"):
            continue
        prefix = loc["prefix"]
        if prefix != "/" and not last.startswith(prefix):
            offenders.append(f"location {prefix} 的 fallback `{last}` 跨出了自己的命名空间")
        if prefix == "/" and last != "/index.html":
            offenders.append(f"location / 的 fallback 必须是 `/index.html`（本段根 = C 端），实际 `{last}`")
    assert offenders == [], "类级判据（fallback 不得跨命名空间）不通过：\n  - " + "\n  - ".join(offenders)


def test_nginx_mutations_are_all_detected():
    """注入式红证：把实现改坏 ⇒ 上面四条判据必须红（证明它们不是空断言）。"""
    original = _read(NGINX_CONF) or ""
    files = _static_fs()

    drop_own_fallback = original.replace(
        f"try_files $uri $uri/ /{SUBDIR}/index.html;", "try_files $uri $uri/ /index.html;"
    )
    assert drop_own_fallback != original, "变异注入未生效（找不到 `/b/` 的 fallback）"

    drop_location = original.replace(f"location /{SUBDIR}/ {{", "location /__removed__/ {")
    assert drop_location != original, "变异注入未生效（找不到 `/b/` 的 location）"

    hijack_root = original.replace(
        "        try_files $uri $uri/ /index.html;\n    }\n", f"        try_files $uri $uri/ /{SUBDIR}/index.html;\n    }}\n", 1
    )
    assert hijack_root != original, "变异注入未生效（找不到根 location 的 fallback）"

    cases = {
        "去掉 /b/ 自己的 fallback（改回根 index.html）": (drop_own_fallback, f"/{SUBDIR}/deep/route", f"{SUBDIR}/index.html"),
        "删掉 /b/ 的 location": (drop_location, f"/{SUBDIR}/deep/route", f"{SUBDIR}/index.html"),
        "让 /b/ 的规则吃掉根": (hijack_root, "/some/c-end/route", "index.html"),
    }
    undetected = []
    for name, (mutant, path, expected) in cases.items():
        block = _app_server_block(mutant)
        if _serve(block, files, path) == expected:
            undetected.append(name)
    assert undetected == [], f"这些 nginx 变异**没有被判红**（= 空断言）：{undetected}"

    # 类级判据也必须红（「根 fallback 指向 /b/」= fallback 跨命名空间的同族形态）
    hijacked = _locations(_app_server_block(hijack_root))
    root_loc = [loc for loc in hijacked if loc["prefix"] == "/"]
    assert root_loc and root_loc[0]["try_files"][-1] != "/index.html", (
        "类级判据对「根 fallback 被指向子应用」这一变异不敏感（空断言）"
    )


# ── 行为层：沙箱里真跑远端脚本（不联网、不碰真实静态根）──────────────────────

def _make_bmini_dist(tmp_path: Path, legacy: bool = False) -> Path:
    dist = tmp_path / ("dist-legacy" if legacy else "dist")
    (dist / "js").mkdir(parents=True)
    (dist / "css").mkdir()
    (dist / "chunk").mkdir()
    (dist / "index.html").write_bytes(_bmini_page(legacy=legacy))
    (dist / "js" / "app.js").write_text("// bmini h5 入口", encoding="utf-8")
    (dist / "css" / "app.css").write_text(".bmini{}", encoding="utf-8")
    (dist / "chunk" / "850.js").write_text("// 懒加载 chunk", encoding="utf-8")
    return dist


def _make_static_root(tmp_path: Path) -> Path:
    """造一个「静态根」沙箱：父目录 = C 端产物 + 工人端 `w/`，另有沙箱外的哨兵文件。"""
    root = tmp_path / "h5"
    (root / "js").mkdir(parents=True)
    (root / "css").mkdir()
    (root / "index.html").write_bytes(C_END_PAGE)
    (root / "js" / "app.js").write_text("// C 端 Taro 产物", encoding="utf-8")
    (root / "css" / "app.css").write_text(".c-end{}", encoding="utf-8")
    (root / "w" / "src").mkdir(parents=True)
    shutil.copy(WORKER_H5_DIR / "index.html", root / "w" / "index.html")
    shutil.copy(WORKER_H5_DIR / "src" / "app.mjs", root / "w" / "src" / "app.mjs")
    (tmp_path / "sentinel-outside.txt").write_text("静态根之外的文件，任何情况下都不该被动", encoding="utf-8")
    return root


def _run_publish(root: Path, subdir: str = SUBDIR, from_dir=None, image=None, script: Path = None):
    env = dict(os.environ)
    env["H5_STATIC_ROOT"] = str(root)
    env["H5_SUBDIR"] = subdir
    env.pop("H5_PUBLISH_IMAGE", None)
    env.pop("H5_PUBLISH_FROM_DIR", None)
    if from_dir is not None:
        env["H5_PUBLISH_FROM_DIR"] = str(from_dir)
    if image is not None:
        env["H5_PUBLISH_IMAGE"] = image
    return subprocess.run(
        ["bash", str(script or REMOTE_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=180, cwd=str(REPO_ROOT),
    )


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): _file_sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def test_sandbox_publish_is_identity_and_preserves_parent(tmp_path):
    root = _make_static_root(tmp_path)
    parent_before = _tree(root)
    dist = _make_bmini_dist(tmp_path)

    proc = _run_publish(root, from_dir=dist)
    assert proc.returncode == 0, f"沙箱发布失败：\n{proc.stdout}\n{proc.stderr}"

    # ① 身份：发布的 index.html 与产物逐字节一致
    published = root / SUBDIR / "index.html"
    assert _file_sha(published) == _file_sha(dist / "index.html"), "发布的 index.html 与产物不一致"
    assert (root / SUBDIR / "js" / "app.js").is_file(), "子资源（js/）没落上去"
    assert (root / SUBDIR / "chunk" / "850.js").is_file(), "懒加载 chunk 没落上去"

    # ② 红线：父目录（C 端 + 工人端）逐字节不变
    after = _tree(root)
    for rel, sha in parent_before.items():
        assert after.get(rel) == sha, f"父目录文件被改动：{rel}"
    assert (tmp_path / "sentinel-outside.txt").is_file()

    # ③ 自证层：远端输出必须报告父目录未被触碰 + 哈希
    assert f"TARGET={root}/{SUBDIR}" in proc.stdout
    before = re.search(r"^PARENT_INDEX_BEFORE_SHA256=(.+)$", proc.stdout, re.M)
    after_m = re.search(r"^PARENT_INDEX_AFTER_SHA256=(.+)$", proc.stdout, re.M)
    assert isinstance(before, re.Match) and isinstance(after_m, re.Match), f"缺父目录自证行：\n{proc.stdout}"
    assert before.group(1).strip() == _file_sha(root / "index.html")
    assert before.group(1) == after_m.group(1)
    pub = re.search(r"^PUBLISHED_INDEX_SHA256=(.+)$", proc.stdout, re.M)
    assert isinstance(pub, re.Match), f"缺发布自证行：\n{proc.stdout}"
    assert pub.group(1).strip() == _file_sha(dist / "index.html")
    assert "ASSET_REFS_SCOPED=1" in proc.stdout and "ASSETS_PRESENT=1" in proc.stdout


def test_sandbox_publish_is_idempotent_and_converges_only_target_subtree(tmp_path):
    root = _make_static_root(tmp_path)
    dist = _make_bmini_dist(tmp_path)
    first = _run_publish(root, from_dir=dist)
    assert first.returncode == 0, first.stdout + first.stderr
    tree_after_first = _tree(root)

    stale = root / SUBDIR / "stale.js"  # 上一次发布留下的、这次不该存在的文件
    stale.write_text("// 残留", encoding="utf-8")
    second = _run_publish(root, from_dir=dist)
    assert second.returncode == 0, second.stdout + second.stderr
    assert not stale.exists(), "目标子树内的陈旧文件必须被收敛（幂等的另一半）"
    assert _tree(root) == tree_after_first, "连跑两次结果不一致（不幂等）"
    assert (root / "js" / "app.js").is_file(), "父目录被误删"


def test_sandbox_refuses_out_of_scope_subdir(tmp_path):
    for bad in ("..", ".", "", "/etc", "a/b", ".hidden", f"{SUBDIR}/../.."):
        root = _make_static_root(tmp_path / f"case-{abs(hash(bad))}")
        parent_before = _tree(root)
        proc = _run_publish(root, subdir=bad, from_dir=_make_bmini_dist(tmp_path / f"dist-{abs(hash(bad))}"))
        assert proc.returncode != 0, f"越界子目录 {bad!r} 竟被放行：\n{proc.stdout}"
        assert _tree(root) == parent_before, f"越界子目录 {bad!r} 时静态根被改动（红线）"


def test_sandbox_refuses_absent_root_missing_source_and_missing_image(tmp_path):
    absent = tmp_path / "not-there" / "h5"
    proc = _run_publish(absent, from_dir=_make_bmini_dist(tmp_path))
    assert proc.returncode != 0, "静态根不存在时应 fail-closed（宁可红，不新建目录）"
    assert not absent.exists(), "拒绝路径上不许建目录"

    root = _make_static_root(tmp_path / "r2")
    proc = _run_publish(root)  # 既无 from_dir 也无 image
    assert proc.returncode != 0, "既没给发布源也没给镜像时必须拒绝"
    assert not (root / SUBDIR).exists(), "拒绝时不该产出目标子树"

    # 构造一个不可拉的镜像名 ⇒ 本机没有 docker/网络，必须**显式失败**而不是静默成功
    proc = _run_publish(root, image="example.invalid/bmini-h5:sha-0000000")
    assert proc.returncode != 0, "取不到产物时竟返回 0（静默半成品）"
    assert not (root / SUBDIR).exists(), "取不到产物时不该产出目标子树"


def test_sandbox_refuses_product_that_escapes_its_namespace(tmp_path):
    """判据 3 的红证（命名空间闸门）：**默认 publicPath** 的产物（引用根级 `/js/app.js`）必须被拒。

    这一条防的是「同一个静态根下两端共用资源路径」—— 若放行，浏览器会在 `/b/` 的页面上
    加载 **C 端的包**：HTTP 200、页面能打开、跑的却是另一个应用（比 404 难发现得多）。
    """
    root = _make_static_root(tmp_path)
    before = _tree(root)
    legacy = _make_bmini_dist(tmp_path, legacy=True)

    proc = _run_publish(root, from_dir=legacy)
    assert proc.returncode != 0, f"引用根级资源的产物竟被发布出去：\n{proc.stdout}"
    assert "ASSET_REFS_SCOPED" not in proc.stdout, "拒绝路径上不该打出自证行"
    assert _tree(root) == before, "拒绝发布时静态根被改动（红线）"
    assert not (root / SUBDIR).exists(), "拒绝发布时不该产出目标子树"

    # 完整性闸门同理：index.html 引用的文件不在产物里 ⇒ 拒绝（防「只发了 index」的半成品）
    broken = _make_bmini_dist(tmp_path / "broken")
    (broken / "js" / "app.js").unlink()
    proc = _run_publish(_make_static_root(tmp_path / "r3"), from_dir=broken)
    assert proc.returncode != 0, f"缺子资源的半成品竟被发布：\n{proc.stdout}"


# ── 落地面断言脚本自身的红/绿两面（防空断言）────────────────────────────────

class _NginxishServer:
    """一个**只实现本单用到的 nginx 语义**的本地 server（前缀 location + try_files + index）。

    `mode` 用来造四种坏形态（判据 7）：
      · ``ok``            —— 线上已按本单的 nginx 配置生效
      · ``no_b_location`` —— nginx 少了 `/b/` 自己的 fallback（`/b/<子> `回落根页）
      · ``root_hijacked`` —— 根被 `/b/` 规则吃掉（根返回 bmini 产物）
      · ``stale_b``       —— `/b/` 上是**旧产物**（不是本仓库这次构建）
      · ``w_broken``      —— worker-h5 的 `/w/` 坏了
    """

    def __init__(self, served_root: Path, mode: str = "ok"):
        self.root = served_root
        self.mode = mode
        self._server = None
        self._thread = None

    def _route(self, path: str):
        root = self.root
        bmini = (root / SUBDIR / "index.html").read_bytes() if (root / SUBDIR / "index.html").is_file() else b""
        c_end = (root / "index.html").read_bytes()
        if path.startswith(f"/{SUBDIR}/"):
            if self.mode == "no_b_location":
                return c_end
            if self.mode == "stale_b":
                return '<!doctype html><title>米高窗帘 · 小布智能助手</title><script>// 旧产物</script>'.encode("utf-8")
            if path in (f"/{SUBDIR}/", f"/{SUBDIR}/index.html"):
                return bmini
            return bmini  # 有 fallback ⇒ 子路由也回 bmini index
        if path.startswith("/w/"):
            if self.mode == "w_broken":
                return c_end  # 静默回落到 C 端（工人端坏掉的真实形态）
            rel = path.lstrip("/")
            if rel.endswith("/"):
                rel += "index.html"
            f = root / rel
            if f.is_file():
                return f.read_bytes()
            return c_end
        if path.startswith("/s/"):
            return b'{"error":"short code not found"}'  # admin-api 的 404 形态
        if self.mode == "root_hijacked":
            return bmini
        return c_end

    class _Handler(http.server.BaseHTTPRequestHandler):
        server_version = "NginxishTest/1.0"

        def log_message(self, *args):
            return None

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            body = self.server.route(path)  # type: ignore[attr-defined]
            code = 200 if body is not None else 404
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def __enter__(self):
        outer = self

        class _Server(http.server.ThreadingHTTPServer):
            def route(self, path):
                return outer._route(path)

        self._server = _Server(("127.0.0.1", 0), self._Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        for _ in range(100):
            with socket.socket() as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(("127.0.0.1", self._server.server_address[1])) == 0:
                    break
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        return False


def _served_root_with(tmp_path: Path, dist: Path) -> Path:
    root = _make_static_root(tmp_path)
    shutil.copytree(dist, root / SUBDIR)
    return root


def _run_verify(base_url: str, dist: Path, wait_seconds: int = 0):
    env = dict(os.environ)
    env["BMINI_NGINX_WAIT_SECONDS"] = str(wait_seconds)
    return subprocess.run(
        ["bash", str(VERIFY_SCRIPT), base_url, str(dist)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, env=env, cwd=str(REPO_ROOT),
    )


def test_verify_served_is_green_on_correct_landing(tmp_path):
    dist = _make_bmini_dist(tmp_path)
    root = _served_root_with(tmp_path, dist)
    with _NginxishServer(root, "ok") as base:
        proc = _run_verify(base, dist)
    assert proc.returncode == 0, f"落地面断言在正确落地上竟失败：\n{proc.stdout}\n{proc.stderr}"
    assert "✅ 全部通过" in proc.stdout


@pytest.mark.parametrize(
    "mode, marker",
    [
        ("no_b_location", f"GET /{SUBDIR}/__bmini_spa_probe__/deep/route"),
        ("root_hijacked", "GET / 返回的是"),
        ("stale_b", "≠ 本仓库"),
        ("w_broken", "worker-h5 身份断言脚本判红"),
    ],
)
def test_verify_served_is_red_on_broken_landings(tmp_path, mode, marker):
    """判据 7：四种坏形态必须判红（否则上面的绿是空断言）。"""
    dist = _make_bmini_dist(tmp_path)
    if mode == "stale_b":
        pass
    root = _served_root_with(tmp_path, dist)
    with _NginxishServer(root, mode) as base:
        proc = _run_verify(base, dist)
    assert proc.returncode == 1, f"坏形态 {mode} 竟判绿（空断言）：\n{proc.stdout}"
    assert "❌" in proc.stdout
    assert any(line for line in proc.stdout.splitlines() if marker in line), (
        f"判红信息里找不到 {marker!r}（红得不具体 = 排查时看不出是哪条判据）：\n{proc.stdout}"
    )
