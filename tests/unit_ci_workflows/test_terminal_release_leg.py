# case_ids: MC-122
r"""观星台终端（工人端 APK / Windows 一体机 EXE）**正式发布链路**的常驻判据（issue #8195）。

## 病（开工前现取）

| 件 | 读数 |
|---|---|
| 终端更新检查地址（终端仓） | Windows `https://app.migaozn.com/terminal/latest.json`；Android `/terminal/android/latest.json` |
| `npx? nginx.conf` 里 `/terminal` | **0 命中** ⇒ 请求落到 `location /` 的 SPA fallback ⇒ **HTTP 200 + C 端元元 HTML**（缺失文件也是 200，监控不红） |
| 官网下载页 | `https://migaozn.com/download` = **404**（`(corporate)` 下没有该路由） |
| 终端产物怎么上线 | **没有任何通路**（没有 workflow、没有脚本、没有静态落位） |

⇒ 三条一起断：**清单地址打不到真文件**、**官网没有下载页**、**产物没有发布腿**。

## 本文件锁什么（每条都带注入式红证）

1. **nginx 静态面**（`app.migaozn.com` 的 `/terminal/`）：缺失文件必须 **404**，**不得**回落根 `index.html`
   （跨应用串端比 404 危险：URL 是 `/terminal/..`、页面是 C 端，而状态码 200）；JSON = `application/json`、
   exe/apk = `application/octet-stream`；**不限流**（一次下载 = 1 个请求，但限流会在真机批量更新时误伤）。
   裸前缀 `/terminal` 必须 301 到 `/terminal/`（否则它同样走 SPA fallback ⇒ 假 200）。
   判据是**真解析 + 真模拟**（`_serve()`：前缀 location 取最长者 + `try_files` + `return`），不是文本匹配。
2. **发布腿结构**（`.github/workflows/terminal-publish.yml`）：只允许 `workflow_dispatch`（发布是**人工闸**：
   必须点名 release tag；`push` 触发会让合并即发布）；发布 / 断言步骤不得带 `continue-on-error` / `|| true` /
   恒假 `if`；ACR 登录必须走唯一实现 `scripts/acr_login.sh --fatal`（登录是**承重**步骤：产物要推进 ACR）。
3. **CI 脚本契约**（`deploy/scripts/terminal-publish-ci.sh`）：逐字节一致的验收断言在案
   （远端 `latest.json` 哈希 == 本地、`android/latest.json` 哈希 == 本地、静态根 `index.html` 未被触碰、
   `PAYLOAD_MANIFEST_OK=1` 自证行、`[ "$STATUS" = "Success" ] || die`）；命令内容只做「按不可变 sha 取回
   远端执行体」并**在发起云调用之前**断言字节数 < 16384（`swas_command_content_legs_ledger.json` 的射程）。
4. **行为层（沙箱里真跑脚本）**：`prepare` 从一份「已下载的 release 目录」生成两份清单（sha256 / size /
   download_url / version / versionCode 全部按终端客户端的真实字段名），再让 `deploy/swas/terminal-publish-remote.sh`
   把载荷落到沙箱静态根 ⇒ 逐字节一致、父目录（C 端 `index.html`）不动、幂等、陈旧文件被收敛；
   **清单与载荷不一致 / 载荷缺件 / 多出未知文件 / 越界子目录 / 缺静态根 ⇒ 一律拒绝且什么都不动**。
5. **发布文档**（`docs/deployment/terminal-release.md`）：发布 / 回滚 / 证书现状（Windows 未签名 + SHA256 +
   SmartScreen）/ 不上架应用市场 —— 缺任一条 ⇒ 红。

## 边界（照实登记，别把「登记了」读成「治住了」）

- 本机**没有** nginx 二进制、**没有** docker、**没有** aliyun CLI ⇒ 证明不了 `nginx -t` 语法通过、
  跑不了「从传输镜像里 `docker cp`」那一步、也不发起任何云调用。
- **跨仓读权限不确定**：终端仓 `zhaokai-mgzn/migao-terminal` 当前是 **private**，本仓的 `GITHUB_TOKEN`
  读不到它的 Release ⇒ workflow 需要 `secrets.TERMINAL_REPO_TOKEN`（**由人添加**；缺它时 workflow
  **出声失败**而不是静默跳过）。这一条**不在**本文件的机械射程内（它需要一个真 token 才能验）。
- 线上那一步（SWAS 上的真实发布 + `https://app.migaozn.com/terminal/latest.json` 的 served 断言）由
  `.github/workflows/terminal-publish.yml` 的 served 步骤跑；**本文件不代替它**。
- `_serve()` 只模拟 nginx 的**前缀 / 精确 location + try_files + return**（本段用到的全集）；
  正则 location / `alias` / `rewrite` 不在面内 —— 故本文件另有一条判据要求 `app.migaozn.com` 段里
  **不出现**正则 location（否则模拟的前提不成立即红）。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "terminal-publish.yml"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "terminal-publish-ci.sh"
REMOTE_SCRIPT = REPO_ROOT / "deploy" / "swas" / "terminal-publish-remote.sh"
DOCKERFILE = REPO_ROOT / "deploy" / "terminal-dist" / "Dockerfile"
RELEASE_DOC = REPO_ROOT / "docs" / "deployment" / "terminal-release.md"

JOB = "publish"
CI_REL = "deploy/scripts/terminal-publish-ci.sh"
REMOTE_REL = "deploy/swas/terminal-publish-remote.sh"
SERVER_NAME = "app.migaozn.com"
STATIC_ROOT = "/opt/migao-deploy/h5"
SUBDIR = "terminal"
TERMINAL_REPO = "zhaokai-mgzn/migao-terminal"
DOWNLOAD_PAGE = "https://migaozn.com/download"

DESTRUCTIVE_RE = re.compile(r"(rm\s+-[A-Za-z]*[rf][A-Za-z]*\b|--delete\b|-delete\b)")


# ── 读盘（缺失即判据失败，不静默）────────────────────────────────────────────

def _read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _on_key(wf: dict):
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

    ⚠️ 只跳过**整行注释**，绝不按 `#` 截断行（朴素截断会让字符串里的 `#` 吃掉行尾 ⇒ 假绿）。
    """
    hits = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if not DESTRUCTIVE_RE.search(raw):
            continue
        if re.search(r"\bdocker\s+rm\b", raw) and "$cid" in raw:
            continue
        if any(tok in raw for tok in ("$TARGET", "$STAGE", "$WORK", "$work", "$TMPDIR", "$out_file", "$DIST_DIR")):
            continue
        hits.append(raw.strip())
    return hits


# ══════════════════════════════════════════════════════════════════════════
# 一、nginx：真解析 + 真模拟
# ══════════════════════════════════════════════════════════════════════════

LOCATION_HEAD_RE = re.compile(r"(?m)^[ \t]*location\s+(?P<spec>[^\n{]+?)\s*\{")


def _brace_body(text: str, open_brace_index: int) -> str:
    depth = 0
    i = open_brace_index
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index + 1:i]
        i += 1
    raise AssertionError("花括号不配平 —— conf 被改坏了")


def _server_blocks(conf: str) -> list[str]:
    blocks = []
    for m in re.finditer(r"\bserver\s*\{", conf):
        i = conf.index("{", m.start())
        blocks.append(_brace_body(conf, i))
    return blocks


def _app_server_block(conf: str) -> str:
    for body in _server_blocks(conf):
        if re.search(rf"server_name[^;]*\b{re.escape(SERVER_NAME)}\b", body) and "listen 443" in body:
            return body
    pytest.fail(f"nginx.conf 里找不到 {SERVER_NAME} 的 443 server 段")


def _locations(block: str) -> list[dict]:
    out = []
    for m in LOCATION_HEAD_RE.finditer(block):
        spec = m.group("spec").strip()
        mod = ""
        if spec.startswith("="):
            mod, spec = "=", spec[1:].strip()
        elif spec and spec[0] in "~^*":
            mod, spec = spec[0], spec[1:].strip()
        body = _brace_body(block, block.index("{", m.start()))
        tf = re.search(r"(?m)^\s*try_files\s+([^;]+);", body)
        rt = re.search(r"(?m)^\s*return\s+(\d{3})\s+(\S+);", body)
        dt = re.search(r"(?m)^\s*default_type\s+(\S+);", body)
        types = {}
        tm = re.search(r"types\s*\{([^}]*)\}", body)
        if tm:
            for entry in tm.group(1).split(";"):
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split()
                for ext in parts[1:]:
                    types[ext] = parts[0]
        out.append(
            {
                "mod": mod,
                "spec": spec,
                "body": body,
                "try_files": tf.group(1).split() if tf else None,
                "return": (rt.group(1), rt.group(2)) if rt else None,
                "default_type": dt.group(1) if dt else None,
                "types": types,
            }
        )
    return out


def _apply_location(loc: dict, path: str, files: set[str], block: str) -> str:
    if loc["return"]:
        code, target = loc["return"]
        return f"redirect:{code}:{target}"
    tf = loc["try_files"]
    if not tf:
        return path.lstrip("/") if path.lstrip("/") in files else "404"
    for arg in tf[:-1]:
        if arg == "$uri" and path.lstrip("/") in files:
            return path.lstrip("/")
        if arg == "$uri/":
            cand = (path.rstrip("/") + "/").lstrip("/")
            if cand in files:
                return cand
    last = tf[-1]
    if last.startswith("="):
        return last[1:] if last == "=404" else last
    if last.startswith("/"):
        return _serve(block, files, last, _depth=1)
    return "404"


def _serve(block: str, files: set[str], path: str, _depth: int = 0) -> str:
    """按 nginx 语义算出**被伺候的文件 / 重定向**（`"404"` = 404）。"""
    if _depth > 5:
        return "404"
    locs = _locations(block)
    if not locs:
        return "404"
    # ① 精确匹配优先
    for loc in locs:
        if loc["mod"] == "=" and loc["spec"] == path:
            return _apply_location(loc, path, files, block)
    # ② 前缀匹配取最长者（与书写顺序无关）
    best = None
    for loc in locs:
        if loc["mod"] == "" and path.startswith(loc["spec"]):
            if best is None or len(loc["spec"]) > len(best["spec"]):
                best = loc
    if best is None:
        return "404"
    return _apply_location(best, path, files, block)


def _live_lines(text: str) -> list[str]:
    """只保留**非整行注释**的行 —— 本判据必须能引用被判红的串（否则讲课的注释会把自己判红）。"""
    return [raw for raw in text.splitlines() if raw.strip() and not raw.lstrip().startswith("#")]


def _canonical_fs() -> set[str]:
    """线上静态根的**预期形态**：C 端根 + 工人端 `w/` + 终端 `terminal/`。"""
    return {
        "index.html",
        "js/app.js",
        "css/app.css",
        "w/index.html",
        "w/src/app.mjs",
        "terminal/latest.json",
        "terminal/android/latest.json",
        "terminal/GuanxingtaiSetup.exe",
        "terminal/GuanxingtaiTerminal-1.0.0.apk",
    }


def _terminal_location(block: str):
    for loc in _locations(block):
        if loc["mod"] == "" and loc["spec"] == f"/{SUBDIR}/":
            return loc
    return None


def _nginx_problems(conf: str) -> list[str]:
    """nginx 面（判据 1）的**唯一判定本体** —— 正样本与变异体都喂它。"""
    problems: list[str] = []
    block = _app_server_block(conf)
    files = _canonical_fs()

    for m in LOCATION_HEAD_RE.finditer(block):
        if m.group("spec").strip()[:1] in ("~", "^", "*"):
            problems.append(
                f"{SERVER_NAME} 段出现了非前缀 location（模拟器不覆盖该形态，需同步判据）："
                f"{m.group(0).strip()[:60]}"
            )

    loc = _terminal_location(block)
    if loc is None:
        problems.append(
            f"`{SERVER_NAME}` 段缺 `location /{SUBDIR}/` —— `/terminal/latest.json` 会落到 `location /` 的 "
            "SPA fallback（HTTP 200 + C 端元一页，缺失文件也是 200）"
        )
        return problems

    if loc["try_files"] != ["$uri", "=404"]:
        problems.append(
            f"`location /{SUBDIR}/` 的 try_files 必须是 `$uri =404`（缺失文件 404、**不回落**根 index.html），"
            f"实际 {loc['try_files']}"
        )
    if loc["default_type"] != "application/octet-stream":
        problems.append(
            f"`location /{SUBDIR}/` 缺 `default_type application/octet-stream`（exe/apk 被当文本渲染），"
            f"实际 {loc['default_type']!r}"
        )
    if re.search(r"\btypes\s*\{", "\n".join(_live_lines(conf))):
        problems.append(
            "nginx.conf 出现 `types {}` 块 —— 它在 nginx 里是**替换**而不是合并继承表（会一并冲掉 "
            "text/css / application/javascript）⇒ 类级判据 test_served_leg_mime_guard.py 禁止；"
            "本面用 `default_type` 兜（只对表里没有的扩展名生效：exe/apk ⇒ 八位字节流）"
        )
    if "limit_req" in loc["body"]:
        problems.append(
            f"`location /{SUBDIR}/` 不得挂 limit_req —— 批量更新时几十台设备同 IP 连下，限流必然误伤"
        )
    if "X-Content-Type-Options" not in loc["body"]:
        problems.append(f"`location /{SUBDIR}/` 缺 `X-Content-Type-Options: nosniff`")

    # 裸前缀 `/terminal`：必须 301 到 `/terminal/`（否则它同样走 SPA fallback 的假 200）
    bare = [x for x in _locations(block) if x["mod"] == "" and x["spec"] == f"/{SUBDIR}"]
    if not bare:
        problems.append(
            f"`{SERVER_NAME}` 段缺 `location /{SUBDIR}` —— 裸前缀会落到 `location /` 的 SPA fallback（假 200）"
        )
    elif not (bare[0]["return"] and bare[0]["return"][0] == "301" and bare[0]["return"][1] == f"/{SUBDIR}/"):
        problems.append(f"`location /{SUBDIR}` 必须 `return 301 /{SUBDIR}/`，实际 {bare[0]['return']}")

    # 模拟（正面）
    cases_positive = {
        f"/{SUBDIR}/latest.json": f"{SUBDIR}/latest.json",
        f"/{SUBDIR}/android/latest.json": f"{SUBDIR}/android/latest.json",
        f"/{SUBDIR}/GuanxingtaiSetup.exe": f"{SUBDIR}/GuanxingtaiSetup.exe",
        f"/{SUBDIR}/GuanxingtaiTerminal-1.0.0.apk": f"{SUBDIR}/GuanxingtaiTerminal-1.0.0.apk",
    }
    for path, expect in cases_positive.items():
        served = _serve(block, files, path)
        if served != expect:
            problems.append(f"`{path}` 落到 `{served}` —— 期望 `{expect}`")

    # 模拟（反面：缺失文件 / 裸前缀 / 目录入口 都不得回落根 index.html 或 200）
    for path in (f"/{SUBDIR}/missing.exe", f"/{SUBDIR}/android/missing.json"):
        served = _serve(block, files, path)
        if served != "404":
            problems.append(
                f"`{path}` 落到 `{served}` —— 期望 `404`（缺失文件回落根 index.html = 静默串端 + 假 200）"
            )
    bare_served = _serve(block, files, f"/{SUBDIR}")
    if bare_served != f"redirect:301:/{SUBDIR}/":
        problems.append(f"`/{SUBDIR}` 落到 `{bare_served}` —— 期望 301 到 `/{SUBDIR}/`（SPA fallback 是假 200）")
    dir_served = _serve(block, files, f"/{SUBDIR}/")
    if dir_served == "index.html" or dir_served.startswith("redirect"):
        problems.append(
            f"`/{SUBDIR}/` 落到 `{dir_served}` —— 下载面的目录请求不许回落成页面/跳转（缺文件就是 404）"
        )

    # 零回归：根 / 根级子路由 / 工人端 `/w/` 不变
    if _serve(block, files, "/") != "index.html":
        problems.append("根 `/` 不再由 C 端 index.html 承担")
    if _serve(block, files, "/some/c-end/route") != "index.html":
        problems.append("根级子路由不再回落到 C 端 index.html（C 端 SPA fallback 被改坏）")
    if _serve(block, files, "/w/") != "w/index.html":
        problems.append("`/w/` 不再落到 `w/index.html`（工人端报工面零回归判据）")

    # 类级：任何静态 location 的 try_files fallback 都不得跨出自己的前缀命名空间
    for other in _locations(block):
        tf = other["try_files"]
        if not tf or other["spec"].startswith("/api") or "proxy_pass" in other["body"]:
            continue
        last = tf[-1]
        if not last.startswith("/"):
            continue
        if other["spec"] == "/" and last != "/index.html":
            problems.append(f"`location /` 的 fallback 必须是 `/index.html`，实际 `{last}`")
        elif other["spec"] != "/" and not last.startswith(other["spec"]):
            problems.append(f"`location {other['spec']}` 的 fallback `{last}` 跨出了自己的命名空间")
    return problems


def test_nginx_terminal_surface_has_no_problems():
    conf = _read(NGINX_CONF)
    assert conf, "deploy/swas/nginx.conf 缺失"
    problems = _nginx_problems(conf)
    assert problems == [], "终端静态面判据不通过：\n  - " + "\n  - ".join(problems)


def _replace_in_terminal(conf: str, old: str, new: str) -> str:
    assert old in conf, f"变异注入未生效（找不到 {old!r}）"
    return conf.replace(old, new, 1)


def test_nginx_mutations_are_all_detected():
    conf = _read(NGINX_CONF) or ""
    assert _nginx_problems(conf) == [], "正样本不是绿的 ⇒ 红证没有意义"

    drop_loc = _replace_in_terminal(conf, f"location /{SUBDIR}/ {{", "location /__removed__/ {")
    spa_fallback = _replace_in_terminal(conf, "try_files $uri =404;", "try_files $uri $uri/ /index.html;")
    drop_bare = _replace_in_terminal(conf, f"location /{SUBDIR} {{\n", f"location /{SUBDIR}-gone {{\n")
    mime = _replace_in_terminal(
        conf, "        default_type application/octet-stream;", "        default_type text/plain;"
    )
    throttled = _replace_in_terminal(
        conf,
        f"        try_files $uri =404;",
        f"        try_files $uri =404;\n        limit_req zone=api_perip burst=200 nodelay;",
    )
    inject_types = _replace_in_terminal(
        conf,
        "        try_files $uri =404;",
        "        types { application/json json; }\n        try_files $uri =404;",
    )

    cases = {
        "删掉 /terminal/ 的 location": drop_loc,
        "把 404 改回 SPA fallback": spa_fallback,
        "删掉裸前缀 301": drop_bare,
        "把 default_type 改成 text/plain（exe/apk 被当文本）": mime,
        "给 /terminal/ 挂上限流": throttled,
        "注入 types{} 块（替换继承表）": inject_types,
    }
    undetected = []
    for name, mutant in cases.items():
        if not _nginx_problems(mutant):
            undetected.append(name)
    assert undetected == [], f"这些 nginx 变异**没有被判红**（= 空断言）：{undetected}"


# ══════════════════════════════════════════════════════════════════════════
# 二、发布腿（workflow）＋ CI 脚本契约（纯函数 + 注入式红证）
# ══════════════════════════════════════════════════════════════════════════

CI_REQUIRED_TOKENS = (
    # 命令内容契约（swas_command_content_legs_ledger.json 的射程；逐字形态，判据是常量）
    "COMMAND_CONTENT_LIMIT_BYTES=${TERMINAL_COMMAND_CONTENT_LIMIT_BYTES:-16384}",
    '-ge "$COMMAND_CONTENT_LIMIT_BYTES"',
    "api-swas-open-2020-06-01-runcommand",
    '--command-content "$COMMAND_CONTENT"',
    # prepare 的字段契约（终端客户端真实字段名：snake_case + versionCode）
    '"download_url"',
    '"published_at"',
    '"versionCode"',
    "PREPARE_OK",
    # 发布后的四条验收断言（逐字形态）
    'grep -q "^TARGET=$EXPECTED_TARGET$"',
    '[ "$REMOTE_LATEST_SHA" = "$LOCAL_LATEST_SHA" ]',
    '[ "$REMOTE_ANDROID_SHA" = "$LOCAL_ANDROID_SHA" ]',
    '[ "$PARENT_BEFORE" = "$PARENT_AFTER" ]',
    'grep -q "^PAYLOAD_MANIFEST_OK=1$"',
    '[ "$STATUS" = "Success" ] || die',
)

REMOTE_REQUIRED_TOKENS = (
    "assert_target_safe()",
    "purge_target()",
    "assert_payload_complete()",
    "PAYLOAD_MANIFEST_OK=1",
    "PARENT_INDEX_BEFORE_SHA256=",
    "PARENT_INDEX_AFTER_SHA256=",
    "PUBLISHED_LATEST_SHA256=",
    "PUBLISHED_ANDROID_SHA256=",
    "RELEASE_TAG=",
)


def _workflow_problems(wf, ci_src=None, remote_src=None) -> list:
    if ci_src is None:
        ci_src = _read(CI_SCRIPT)
    if remote_src is None:
        remote_src = _read(REMOTE_SCRIPT)
    problems: list = []

    if not remote_src:
        problems.append(f"远端执行体 {REMOTE_REL} 缺失 —— 发布逻辑没有单一出处")
    if not ci_src:
        problems.append(f"CI 发布脚本 {CI_REL} 缺失")

    on = _triggers(wf)
    if set(on) != {"workflow_dispatch"}:
        problems.append(
            "触发面必须**只有** workflow_dispatch（发布是人工闸：必须点名 release tag），"
            f"实际 {sorted(on)}"
        )
    dispatch = on.get("workflow_dispatch") if isinstance(on.get("workflow_dispatch"), dict) else {}
    inputs = (dispatch or {}).get("inputs") or {}
    tag_input = inputs.get("release_tag") if isinstance(inputs, dict) else None
    if not isinstance(tag_input, dict) or not tag_input.get("required"):
        problems.append("workflow_dispatch 必须有 required 输入 `release_tag`（发布哪一版不能靠猜）")

    if (wf.get("permissions") or {}).get("contents") != "read":
        problems.append("permissions.contents 必须是 read（本腿不需要写仓库）")
    conc = wf.get("concurrency") or {}
    if conc.get("group") != "terminal-publish":
        problems.append(f"concurrency.group 必须是 terminal-publish，实际 {conc.get('group')!r}")
    if conc.get("cancel-in-progress") is not False:
        problems.append("concurrency.cancel-in-progress 必须显式 false（并发发布会让「谁最后落地」不可判定）")

    env = wf.get("env") or {}
    expected_env = {
        "TERMINAL_REPO": TERMINAL_REPO,
        "TERMINAL_STATIC_ROOT": STATIC_ROOT,
        "TERMINAL_SUBDIR": SUBDIR,
        "IMAGE_NAME": "terminal-dist",
    }
    for key, value in expected_env.items():
        if env.get(key) != value:
            problems.append(f"env.{key} 必须是 {value!r}，实际 {env.get(key)!r}")

    steps = _steps(wf)
    prepare_steps = [s for s in steps if "terminal-publish-ci.sh prepare" in _run_text(s)]
    publish_steps = [s for s in steps if "terminal-publish-ci.sh publish" in _run_text(s)]
    served_steps = [s for s in steps if "/terminal/latest.json" in _run_text(s) and "curl" in _run_text(s)]
    login_steps = [s for s in steps if "scripts/acr_login.sh" in _run_text(s)]
    if len(prepare_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个 prepare step，实际 {len(prepare_steps)}")
    if len(publish_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个 publish step，实际 {len(publish_steps)}")
    if len(served_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个落地面断言 step（curl 清单），实际 {len(served_steps)}")
    if len(login_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个 ACR 登录 step（走 scripts/acr_login.sh），实际 {len(login_steps)}")
    if served_steps:
        served_body = _run_text(served_steps[0])
        for token, why in (
            ("application/json", "清单必须是 application/json（终端按 JSON 解析）"),
            ("application/octet-stream", "安装包必须是 application/octet-stream"),
            ("__absent__", "缺失文件必须 404（不许回落 SPA）"),
        ):
            if token not in served_body:
                problems.append(f"落地面断言步骤缺少 `{token}` —— {why}")

    for step in prepare_steps + publish_steps + served_steps + login_steps:
        if step.get("continue-on-error"):
            problems.append(f"step `{step.get('name')}` 带 continue-on-error ⇒ 红被吞")
        if "|| true" in _run_text(step):
            problems.append(f"step `{step.get('name')}` 带 `|| true` ⇒ 红被吞")
        if str(step.get("if", "")).strip().lower() in ("false", "0"):
            problems.append(f"step `{step.get('name')}` 的 if 恒假 ⇒ 红被吞")

    if login_steps and "--fatal" not in _run_text(login_steps[0]):
        problems.append("ACR 登录必须带 `--fatal`（本腿把载荷推进 ACR ⇒ 登录是**承重**步骤）")

    build_steps = [s for s in steps if "deploy/terminal-dist/Dockerfile" in _run_text(s)]
    if len(build_steps) != 1:
        problems.append("必须恰好 1 个 step 用 deploy/terminal-dist/Dockerfile 构建传输镜像")
    for step in build_steps:
        body = _run_text(step)
        if "docker push" not in body:
            problems.append("构建传输镜像的 step 必须包含 docker push")
        if "timeout" not in body:
            problems.append("docker push 必须有显式墙钟上界（timeout）—— 推 ACR 挂住会烧满 job 上界")
        if "docker manifest inspect" not in body:
            problems.append("推完必须 `docker manifest inspect` 复验（推失败/推一半 ⇒ 在远端 pull 之前 fail-closed）")
    if not any("gh release download" in _run_text(s) for s in steps):
        problems.append("必须有一个 step 从终端仓 Release 下载产物（gh release download）")
    download_steps = [s for s in steps if "gh release download" in _run_text(s)]
    if download_steps and "TERMINAL_REPO_TOKEN" not in str(
        (download_steps[0].get("env") or {}).get("GH_TOKEN", "")
    ):
        problems.append(
            "下载终端仓 Release 必须用 `secrets.TERMINAL_REPO_TOKEN`（终端仓是 private，本仓 GITHUB_TOKEN 读不到）"
        )

    if ci_src:
        for token in CI_REQUIRED_TOKENS:
            if token not in ci_src:
                problems.append(f"CI 脚本缺少验收断言（逐字形态）`{token}`")
        for line in _unsanctioned_destructive_lines(ci_src):
            problems.append(f"CI 脚本里有未限定目标的破坏性语句（红线）：{line}")
    if remote_src:
        for token in REMOTE_REQUIRED_TOKENS:
            if token not in remote_src:
                problems.append(f"远端脚本缺少自证/守卫标记 `{token}`")
        for line in _unsanctioned_destructive_lines(remote_src):
            problems.append(f"远端脚本里有未限定目标的破坏性语句（红线）：{line}")
    return problems


def _load_workflow() -> dict:
    text = _read(WORKFLOW_PATH)
    if text is None:
        pytest.fail(
            "`.github/workflows/terminal-publish.yml` 不存在 —— 终端产物又回到「没有任何发布通路」"
            "（issue #8195 的形态本身）"
        )
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def test_real_publish_leg_has_no_problems():
    problems = _workflow_problems(_load_workflow())
    assert problems == [], "发布接线判据不通过：\n  - " + "\n  - ".join(problems)


def test_workflow_mutations_are_all_detected():
    wf = _load_workflow()

    def drop_publish(mut):
        mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if "terminal-publish-ci.sh publish" not in _run_text(s)]

    def drop_prepare(mut):
        mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if "terminal-publish-ci.sh prepare" not in _run_text(s)]

    def drop_served(mut):
        mut["jobs"][JOB]["steps"] = [
            s for s in _steps(mut) if not ("/terminal/latest.json" in _run_text(s) and "curl" in _run_text(s))
        ]

    def add_push(mut):
        _triggers(mut)["push"] = {"branches": ["main"]}

    def tag_not_required(mut):
        _triggers(mut)["workflow_dispatch"]["inputs"]["release_tag"]["required"] = False

    def fatal_login_dropped(mut):
        for step in _steps(mut):
            if "scripts/acr_login.sh" in _run_text(step):
                step["run"] = _run_text(step).replace(" --fatal", "")

    def silence_publish(mut):
        for step in _steps(mut):
            if "terminal-publish-ci.sh publish" in _run_text(step):
                step["continue-on-error"] = True

    def retarget_root(mut):
        mut["env"]["TERMINAL_STATIC_ROOT"] = "/opt/migao-deploy"

    def retarget_subdir(mut):
        mut["env"]["TERMINAL_SUBDIR"] = "."

    def token_missing(mut):
        for step in _steps(mut):
            if "gh release download" in _run_text(step):
                (step.get("env") or {})["GH_TOKEN"] = "${{ secrets.GITHUB_TOKEN }}"

    mutations = {
        "删掉 publish 步骤": drop_publish,
        "删掉 prepare 步骤": drop_prepare,
        "删掉落地面断言步骤": drop_served,
        "加 push 触发（合并即发布）": add_push,
        "release_tag 不再 required": tag_not_required,
        "ACR 登录去掉 --fatal": fatal_login_dropped,
        "publish 步骤 continue-on-error": silence_publish,
        "静态根改成上层目录": retarget_root,
        "子目录改成 .": retarget_subdir,
        "下载用本仓 GITHUB_TOKEN": token_missing,
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

    no_identity = ci_src.replace('[ "$REMOTE_LATEST_SHA" = "$LOCAL_LATEST_SHA" ]', "true")
    assert no_identity != ci_src, "变异注入未生效（找不到产物身份断言）"

    no_android = ci_src.replace('[ "$REMOTE_ANDROID_SHA" = "$LOCAL_ANDROID_SHA" ]', "true")
    assert no_android != ci_src, "变异注入未生效（找不到 Android 清单身份断言）"

    no_bytes = ci_src.replace('-ge "$COMMAND_CONTENT_LIMIT_BYTES"', '-lt "$COMMAND_CONTENT_LIMIT_BYTES"')
    assert no_bytes != ci_src, "变异注入未生效（找不到字节前置断言）"

    root_delete = ci_src + '\nrm -rf "$STATIC_ROOT/../"\n'

    samples = {
        "去掉「线上 latest.json 哈希 == 本地」断言": no_identity,
        "去掉「线上 android/latest.json 哈希 == 本地」断言": no_android,
        "把字节前置断言改成恒假": no_bytes,
        "新增未限定目标的删除": root_delete,
    }
    undetected = []
    for name, mutant in samples.items():
        if len(_workflow_problems(_load_workflow(), ci_src=mutant)) == 0:
            undetected.append(name)
    assert undetected == [], f"这些脚本变异**没有被判红**（= 空断言）：{undetected}"


def test_transport_dockerfile_lines_are_all_comments_or_instructions():
    text = _read(DOCKERFILE)
    if text is None:
        pytest.fail(
            "deploy/terminal-dist/Dockerfile 缺失 —— 产物没有传输载体（SWAS 上既没有 node 也没有这些二进制）"
        )
    instructions = {"FROM", "COPY", "ADD", "RUN", "WORKDIR", "USER", "ENV", "LABEL", "ARG", "ENTRYPOINT", "CMD"}
    bad = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split()[0].upper()
        if head not in instructions:
            bad.append(f"第 {lineno} 行不是合法指令：{line[:60]}")
    assert bad == [], (
        "Dockerfile 里裸写散文会被当成指令 ⇒ `dockerfile parse error on line N: unknown instruction`"
        "（本机没有 docker 二进制 ⇒ 只有 CI 能发现）：\n  " + "\n  - ".join(bad)
    )
    assert "FROM alpine:3.20" in text, "传输镜像必须是一个极小的 alpine 基底（只装 /dist）"
    assert "COPY . /dist" in text, "载荷必须落在 /dist（远端 docker cp 的固定坐标）"


def test_release_runbook_documents_release_rollback_and_signing():
    text = _read(RELEASE_DOC)
    if text is None:
        pytest.fail("docs/deployment/terminal-release.md 缺失 —— 发布/回滚/证书现状没有承载体")
    required = {
        "发布": "发布步骤（怎么发）",
        "回滚": "回滚步骤（发坏了怎么办）",
        "SmartScreen": "Windows 未签名 + SmartScreen 现状",
        "SHA256": "校验值口径",
        "应用市场": "不上架应用市场的口径",
        "versionCode": "Android 更新的唯一比较依据（versionCode 必须单调递增）",
        "/terminal/latest.json": "Windows 清单地址",
        "/terminal/android/latest.json": "Android 清单地址",
    }
    missing = [f"{why}（缺 `{token}`）" for token, why in required.items() if token not in text]
    assert missing == [], "发布文档缺条目：\n  - " + "\n  - ".join(missing)


# ══════════════════════════════════════════════════════════════════════════
# 三、行为层：沙箱里真跑 prepare + 远端脚本（不联网、不碰真实静态根）
# ══════════════════════════════════════════════════════════════════════════

WIN_ASSET = "GuanxingtaiSetup.exe"
APK_ASSET = "GuanxingtaiTerminal-1.0.1.apk"
TAG = "terminal-v1.0.1"
VERSION = "1.0.1.0"
VERSION_CODE = "7"


def _make_release(tmp_path: Path) -> Path:
    rel = tmp_path / "release"
    rel.mkdir()
    (rel / WIN_ASSET).write_bytes(b"MZ" + bytes(range(256)) * 8)
    (rel / APK_ASSET).write_bytes(b"PK\x03\x04" + bytes(range(256)) * 12)
    (rel / "SHA256SUMS.txt").write_text("（终端仓的自带校验文件）", encoding="utf-8")
    return rel


def _prepare(tmp_path: Path, release: Path | None = None, out: Path | None = None, extra=()):
    release = release or _make_release(tmp_path)
    out = out or (tmp_path / "dist")
    args = [
        "bash", str(CI_SCRIPT), "prepare",
        "--release-dir", str(release),
        "--out", str(out),
        "--tag", TAG,
        "--version", VERSION,
        "--android-version-code", VERSION_CODE,
        "--notes", "首个发布版：车间一体机裁高终端",
        "--published-at", "2026-10-31",
        *extra,
    ]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120), out


def _make_static_root(tmp_path: Path) -> Path:
    root = tmp_path / "h5"
    (root / "js").mkdir(parents=True)
    (root / "w").mkdir()
    (root / "terminal" / "android").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>观星台 · 元元</title>", encoding="utf-8")
    (root / "js" / "app.js").write_text("// C 端 Taro 产物", encoding="utf-8")
    (root / "w" / "index.html").write_text("<!doctype html><title>报工</title>", encoding="utf-8")
    (root / "terminal" / "stale.txt").write_text("上一版留下的陈旧文件，发布后必须消失", encoding="utf-8")
    (root / "terminal" / "android" / "stale-android.txt").write_text("陈旧", encoding="utf-8")
    return root


def _run_remote(root: Path, payload: Path, extra=()):
    args = [
        "bash", str(REMOTE_SCRIPT),
        "--from-dir", str(payload),
        "--static-root", str(root),
        "--subdir", SUBDIR,
        "--release-tag", TAG,
        *extra,
    ]
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )


def test_prepare_generates_client_shaped_manifests(tmp_path):
    result, out = _prepare(tmp_path)
    assert result.returncode == 0, f"prepare 失败：\n{result.stdout}\n{result.stderr}"

    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    android = json.loads((out / "latest-android.json").read_text(encoding="utf-8"))
    win_bytes = (out / WIN_ASSET).read_bytes()
    apk_bytes = (out / APK_ASSET).read_bytes()

    # Windows：终端 Program.cs 读 `version` / `notes` / `download_url`（字符串比较）
    assert latest["version"] == VERSION
    assert latest["notes"].startswith("首个发布版")
    assert latest["download_url"].endswith("/" + WIN_ASSET)
    assert latest["download_url"].startswith("https://app.migaozn.com/terminal/")
    assert latest["sha256"] == _sha(win_bytes)
    assert latest["size"] == len(win_bytes)
    assert latest["published_at"] == "2026-10-31"

    # Android：Updater.java 读 `versionCode`（int，必须单调递增）+ `versionName` + `download_url`
    assert android["versionCode"] == int(VERSION_CODE)
    assert android["versionName"] == "1.0.1"
    assert android["download_url"].endswith("/" + APK_ASSET)
    assert android["sha256"] == _sha(apk_bytes)
    assert android["size"] == len(apk_bytes)

    assert "PREPARE_OK" in result.stdout
    assert "SHA256SUMS.txt" not in (out / "latest.json").read_text(encoding="utf-8")


def test_prepare_rejects_bad_inputs(tmp_path):
    release = _make_release(tmp_path)
    cases = {
        "缺 release 目录": [
            "--release-dir", str(tmp_path / "nope"), "--out", str(tmp_path / "d1"),
            "--tag", TAG, "--version", VERSION, "--android-version-code", VERSION_CODE,
        ],
        "versionCode 不是整数": [
            "--release-dir", str(release), "--out", str(tmp_path / "d2"),
            "--tag", TAG, "--version", VERSION, "--android-version-code", "abc",
        ],
        "tag 含引号（注入）": [
            "--release-dir", str(release), "--out", str(tmp_path / "d3"),
            "--tag", 'v1"x', "--version", VERSION, "--android-version-code", VERSION_CODE,
        ],
        "version 为空": [
            "--release-dir", str(release), "--out", str(tmp_path / "d4"),
            "--tag", TAG, "--version", "", "--android-version-code", VERSION_CODE,
        ],
    }
    for name, args in cases.items():
        result = subprocess.run(
            ["bash", str(CI_SCRIPT), "prepare", *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        assert result.returncode != 0, f"坏输入**没有被拒绝**：{name}\n{result.stdout}"
        assert "PREPARE_OK" not in result.stdout, f"坏输入（{name}）仍然报了成功"


def test_remote_publish_is_idempotent_and_keeps_parent_untouched(tmp_path):
    _, payload = _prepare(tmp_path)
    root = _make_static_root(tmp_path)
    parent_before = _file_sha(root / "index.html")
    latest_sha = _file_sha(payload / "latest.json")
    android_sha = _file_sha(payload / "latest-android.json")

    result = _run_remote(root, payload)
    assert result.returncode == 0, f"远端发布失败：\n{result.stdout}\n{result.stderr}"
    out = result.stdout

    assert f"TARGET={root / SUBDIR}" in out
    assert f"RELEASE_TAG={TAG}" in out
    assert "PAYLOAD_MANIFEST_OK=1" in out
    assert f"PUBLISHED_LATEST_SHA256={latest_sha}" in out
    assert f"PUBLISHED_ANDROID_SHA256={android_sha}" in out
    assert _file_sha(root / "index.html") == parent_before, "静态根 index.html 被触碰（红线）"

    assert _file_sha(root / SUBDIR / "latest.json") == latest_sha
    assert _file_sha(root / SUBDIR / "android" / "latest.json") == android_sha
    assert (root / SUBDIR / WIN_ASSET).exists()
    assert (root / SUBDIR / APK_ASSET).exists()
    # 陈旧文件被收敛（同一子树内的上一版残留）
    assert not (root / SUBDIR / "stale.txt").exists()
    assert not (root / SUBDIR / "android" / "stale-android.txt").exists()
    # 载荷里不属于发布面的文件不会被搬上线
    assert not (root / SUBDIR / "SHA256SUMS.txt").exists()

    first = {p.relative_to(root / SUBDIR).as_posix(): _file_sha(p) for p in (root / SUBDIR).rglob("*") if p.is_file()}
    again = _run_remote(root, payload)
    assert again.returncode == 0, f"重复发布失败（不幂等）：\n{again.stdout}\n{again.stderr}"
    second = {p.relative_to(root / SUBDIR).as_posix(): _file_sha(p) for p in (root / SUBDIR).rglob("*") if p.is_file()}
    assert first == second, "重复发布的字节不一致（幂等判据）"


def test_remote_publish_fails_closed_on_bad_payload(tmp_path):
    _, payload = _prepare(tmp_path)
    root = _make_static_root(tmp_path)
    sentinel = root / SUBDIR / "KEEP-ME.txt"
    sentinel.write_text("失败时一个字节都不许动", encoding="utf-8")
    before = _file_sha(root / "index.html")

    # ① 载荷里的 exe 被改坏（与清单 sha256 不一致）
    tampered = tmp_path / "tampered"
    shutil.copytree(payload, tampered)
    with (tampered / WIN_ASSET).open("ab") as fh:
        fh.write(b"corrupted")
    # ② 缺一个载荷文件
    missing = tmp_path / "missing"
    shutil.copytree(payload, missing)
    (missing / APK_ASSET).unlink()
    # ③ 多出未知文件
    extra = tmp_path / "extra"
    shutil.copytree(payload, extra)
    (extra / "evil.sh").write_text("echo pwn", encoding="utf-8")
    # ④ 清单本身被改坏（sha256 字段）
    bad_manifest = tmp_path / "bad_manifest"
    shutil.copytree(payload, bad_manifest)
    (bad_manifest / "latest.json").write_text("{not json", encoding="utf-8")

    cases = {
        "载荷被改坏（清单 sha256 不符）": _run_remote(root, tampered),
        "载荷缺件": _run_remote(root, missing),
        "载荷多出未知文件": _run_remote(root, extra),
        "清单格式坏": _run_remote(root, bad_manifest),
        "越界子目录": _run_remote(root, payload, extra=("--subdir", "../escape")),
        "子目录为空": _run_remote(root, payload, extra=("--subdir", "")),
    }
    for name, result in cases.items():
        assert result.returncode != 0, f"{name}：**没有被拒绝**\n{result.stdout}"
        assert sentinel.exists(), f"{name}：失败后仍然动了目标子树（红线）"
        assert _file_sha(root / "index.html") == before, f"{name}：静态根 index.html 被改动"

    missing_root = subprocess.run(
        ["bash", str(REMOTE_SCRIPT), "--from-dir", str(payload),
         "--static-root", str(tmp_path / "does-not-exist"), "--subdir", SUBDIR, "--release-tag", TAG],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert missing_root.returncode != 0, "缺静态根时**没有被拒绝**（不许自己新建目录）"
    assert not (tmp_path / "does-not-exist").exists(), "缺静态根时居然新建了目录"


def test_publish_command_content_stays_small_and_never_inlines_the_remote_body(tmp_path):
    """命令内容契约（`swas_command_content_legs_ledger.json` 的读数层）：只做「按 sha 取回执行体」。"""
    _, payload = _prepare(tmp_path)
    env = dict()
    env.update({
        "TERMINAL_PUBLISHED_COMMIT": "a" * 40,
        "TERMINAL_PRINT_COMMAND_CONTENT": "1",
        "TERMINAL_STATIC_ROOT": str(payload),
        "PATH": __import__("os").environ.get("PATH", ""),
    })
    result = subprocess.run(
        ["bash", str(CI_SCRIPT), "publish", "i-123", "cn-hangzhou", "sha-abcdef0",
         "--dist-dir", str(payload), "--release-tag", TAG],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, env=env,
    )
    assert result.returncode == 0, f"命令内容组装失败：\n{result.stdout}\n{result.stderr}"
    assert "COMMAND_CONTENT_BEGIN" in result.stdout
    content = result.stdout.split("COMMAND_CONTENT_BEGIN", 1)[1].split("COMMAND_CONTENT_END", 1)[0]
    assert "codeload.github.com" in content and "a" * 40 in content, "命令内容必须按不可变 sha 取回执行体"
    assert "assert_payload_complete" not in content, (
        "远端执行体被内联进命令内容（#6095/#6124 的病根）—— 命令内容只许做「取回并执行」"
    )
    match = re.search(r"COMMAND_CONTENT_BYTES=(\d+)", result.stdout)
    assert match, "命令内容字节数没有打印（字节前置断言必须在发起云调用之前）"
    assert int(match.group(1)) < 16384
