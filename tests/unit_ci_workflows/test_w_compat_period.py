# case_ids: MC-237
r"""`/w/` **兼容期**：不再成为任何跳转的目标，而**已印出的码仍可用**（issue #7813 P2c）。

## 这一页两件事，方向相反，必须同时成立

| 方向 | 口径 | 为什么它是硬的 |
|---|---|---|
| **收口** | `/w/` **不再是任何 302 / 跳转的目标** | 手机端对外只留 `/b` 一个命名空间（#7879 / #7906）；`/w/` 继续当目标 = 同一个功能两套入口，改了落地面却没人知道 |
| **保命** | **已印出的纸码不许失效** | 纸码（`/s/<短码>` `/o/<短码>`）印在实物上**不可重印**；`/w/?t=<token>` 也随短链 302 进过工人的手机书签 |

⇒ 本文件**不做**「删掉 `/w/`」那件事（那是 #7806 的 P3）；它只把「不再当目标」与「旧码仍可用」
钉成两条会红的判据，并**逐条给注入式红证**。

## 判据表（每条都带红证，红证走**同一份**纯函数）

| # | 判据 | 扫描面 | 红证（怎么让它单独变红） |
|---|---|---|---|
| 1 | **没有任何 302 / 跳转指向 `/w/`**：nginx `return 30x` / `rewrite … redirect\|permanent` / `add_header Location` / `proxy_redirect`、Java `sendRedirect(` / `.location(` / `*_PATH\|_ROUTE\|_URL = "/w/…"`、TS `Taro.navigateTo\|redirectTo\|reLaunch\|switchTab` / `href=` / `location.*` / 模板串 | `deploy/**`、`frontend/**`（生产代码；`tests/**` 剪掉 —— 判据面自己的夹具**必须**引用 `/w/` 才拿得到红证）、`backend/admin-api/src/main/java/**` | 任一面加一条 302 / 跳转移到 `/w/` ⇒ 具名红（文件 + 行号 + 形态） |
| 1b | **`/w/` 可以被「供应」，不可以被「跳转到」**：nginx 里 `rewrite … /w/… last\|break`（内部换页，URL 不变）**不算**跳转 | 同 1 | 把内部 `rewrite` 的 flag 改成 `redirect` ⇒ 红（判别力自证：同一条 `rewrite` 在 `last` 下不红） |
| 2 | **旧码仍可用**：`location /w/` 仍在、fallback 仍在**自己的前缀内**（`/w/index.html`）、`.mjs` 的 MIME 兜底仍在；`location /b/report/` 仍在且**内部** rewrite 到 `/w/`；`location /s/` 仍反代 admin-api（`proxy_pass` 不带 URI 后缀）；302 目标常量仍是 `/b/…`、查询串口径 `?t=` 未动 | `deploy/swas/nginx.conf` + `WorkerShortLinkService.java` + `frontend/worker-h5/**` 的静态面 | 删掉 `location /w/` ⇒ 红（`/w/?t=` 会落到 `location /` 的 SPA 兜底 = 200 + C 端首页）；把 `REPORT_PAGE_PATH` 改回 `/w/…` ⇒ 红 |
| 3 | **`/w/` 不再新增入口**：bmini 侧（`frontend/bmini-app/src/**`）没有任何把用户送到 `/w/` 的跳转 | `frontend/bmini-app/src/**` | 工人首页加一个 `Taro.navigateTo({ url: '/w/' })` ⇒ 红并点名该文件 |
| 3b | **「旧码直连」不是代码入口**：`H5_WORKER_SESSION_KEY` 这类**同源 localStorage 镜像**不是跳转（它只让旧码落到的那一页复用身份），不许被误判成入口 | 同 3 | 把镜像改成 `location.replace('/w/')` ⇒ 红（说明"镜像 ≠ 入口"这条口径真被区分了） |
| 5 | **扫描面非空自证**：扫到的文件数 > 0，且四个**必须在面内**的文件真在面内（nginx / 唯一 302 常量 / 入口台账 / app.config）；同时真语料上**至少认出 1 处** `/w/` 引用（内部 rewrite）⇒ 「零命中」不是因为扫描面塌了 | —— | 把某个必扫文件改路径 / 让扫描面塌成空集 ⇒ 红（「绿了但没扫」= 本仓最忌的形态） |
| 6 | **兼容期声明在案**：`frontend/worker-h5/README.md` 写清「只为已印出的码服务 / 不再新增功能 / 不再是 302 目标」三句口径 | `frontend/worker-h5/README.md` | 删掉任一句 ⇒ 红（声明被删了，收口就只剩一句口头约定） |

## 这一层**判不了**什么（照实登记，§19.1）

- ❌ 判不了**线上**：本机没有 nginx / 没有 docker，`try_files` 的语义是本文件按 nginx 前缀匹配 +
  兜底规则**模拟**的（同 `tests/unit_ci_workflows/test_bmini_h5_hosting.py` 的口径）。真机/线上的
  「`/w/` 返回的是本仓库这一份」由 `deploy/scripts/worker-h5-verify-served.sh` 承担。
- ❌ 判不了「工人真点得到四条面的入口」——那是 `frontend/bmini-app/tests/page-entry-reachability.test.ts`
  的 L2/L3（形态 + 可达）与真机档（U 档）的事；本文件只钉「`/w/` 不是它们的入口」。
- ❌ 判不了「页面内动态拼出来的 URL」：`'/' + 'w' + '/'` 这类拼接不在面内（假绿方向，不会误伤）。
- ❌ 判不了**已撤销 / 失效的纸码**：那由短链服务自己的 404/410 语义承担（`WorkerShortLinkControllerTest`）。
- ✅ 本文件**不改任何门禁的通过条件、不新增豁免**、不动任何豁免台账（不新增条目、不抬基线）。
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest

from unit_ci_workflows._source_parsing import (
    java_code,
    java_literals,
    typescript_literals,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

NGINX_CONF = "deploy/swas/nginx.conf"
SHORT_LINK_SERVICE = (
    "backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java"
)
WORKER_H5_README = "frontend/worker-h5/README.md"
WORKER_H5_ROOT = "frontend/worker-h5"
BMINI_SRC = "frontend/bmini-app/src"
APP_CONFIG = "frontend/bmini-app/src/app.config.ts"
PAGE_ENTRIES = "frontend/bmini-app/src/utils/pageEntries.ts"
WORKER_HOME = "frontend/bmini-app/src/pages/worker/home/index.tsx"

#: 扫描面（`(根, 后缀集)`）。**只扫生产代码**：`tests/**` 剪掉 —— 判据面自己的夹具与反证**必须**
#: 引用 `/w/`（本文件就是），把它算进「入口」会把判据自己判红，且那种红与产品无关。
SCAN_FACES: tuple[tuple[str, frozenset[str]], ...] = (
    ("deploy", frozenset({".conf", ".sh"})),
    ("frontend", frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".html"})),
    ("backend/admin-api/src/main/java", frozenset({".java"})),
)
#: 剪枝：依赖 / 构建产物 / 测试面（见上）。
PRUNE_DIRS = frozenset(
    {"node_modules", "dist", "build", "coverage", ".next", ".git", "tests", "__tests__"}
)

#: 四种面里**必须**在扫描面内的文件（判据 5 的「扫描面塌陷」红证：少一个 ⇒ 红）。
REQUIRED_IN_SURFACE = (
    NGINX_CONF,
    SHORT_LINK_SERVICE,
    PAGE_ENTRIES,
    APP_CONFIG,
)

#: 跳转形态（Java / TS / HTML 的**语句头**要命中它们，`/w/` 字面量才算「跳转目标」）。
NAV_MARKERS = (
    "sendRedirect(",
    ".location(",
    "navigateTo(",
    "redirectTo(",
    "reLaunch(",
    "switchTab(",
    "href=",
    "location.href",
    "location.assign(",
    "location.replace(",
    "window.location",
    "router.push(",
    "Router.push(",
    "navigate(",
)
#: 302 目标常量名的后缀（`REPORT_PAGE_PATH = "/w/…"` 这种形态）。
CONST_SUFFIXES = ("_PATH", "_ROUTE", "_URL", "_LANDING", "_LINK", "_LOCATION")


# ══════════════════════════════════════════════════════════════════════════════
# 一、读面：剥注释（**唯一一份**实现：nginx/shell 走 danger_scan，Java/TS 走 _source_parsing）
# ══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _line_comment_stripper():
    """`#` 行注释剥除（与 `.github/danger_scan.py` **同一份**实现，不另写一把尺子）。"""
    path = REPO_ROOT / ".github" / "danger_scan.py"
    if not path.is_file():
        raise AssertionError(f"取不到共享的剥注释实现：{path} ⇒ 判红而不是判绿")
    spec = importlib.util.spec_from_file_location("danger_scan_for_w_compat", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.strip_comment


def _strip_html_comments(text: str) -> str:
    """抹掉 `<!-- … -->`（保留行号）：HTML 注释里的 `href` 不是入口。"""
    out: list[str] = []
    index = 0
    while True:
        start = text.find("<!--", index)
        if start < 0:
            out.append(text[index:])
            return "".join(out)
        end = text.find("-->", start + 4)
        if end < 0:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:start])
        out.append("\n" * text.count("\n", start, end + 3))
        index = end + 3


def _code_only(rel: str, text: str) -> str:
    """判据只看**代码**：注释抹成空格（行号不变），字符串原样保留。"""
    suffix = Path(rel).suffix
    if suffix in {".conf", ".sh"}:
        return "\n".join(_line_comment_stripper()(line) for line in text.splitlines())
    if suffix == ".html":
        return _strip_html_comments(text)
    return java_code(text)  # Java / TS 共用同一份**引号感知**的词法走查


def _iter_scan_files() -> list[str]:
    """扫描面里的文件（仓库相对 / posix）。"""
    out: list[str] = []
    for root, suffixes in SCAN_FACES:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            rel_parts = path.relative_to(REPO_ROOT).parts
            if any(part in PRUNE_DIRS for part in rel_parts[:-1]):
                continue
            out.append(path.relative_to(REPO_ROOT).as_posix())
    return sorted(out)


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据 1 / 3：有没有「跳转到 `/w/`」（纯函数，红证与真判据共用这一份）
# ══════════════════════════════════════════════════════════════════════════════


def _is_w_target(value: str) -> bool:
    value = value.strip()
    return value == "/w" or value.startswith("/w/")


def _nav_head(head: str) -> bool:
    return any(marker in head for marker in NAV_MARKERS)


def _const_head(head: str) -> bool:
    """`FOO_PATH = "/w/…"` 这种「302 目标常量」形态（不是跳转语句，但语义上就是目标）。"""
    if not head.endswith("="):
        return False
    before = head[:-1].rstrip()
    name = ""
    for ch in reversed(before):
        if ch.isalnum() or ch in "_$":
            name = ch + name
        else:
            break
    return bool(name) and name.upper() == name and name.endswith(CONST_SUFFIXES)


def _line_of(code: str, pos: int) -> int:
    return code.count("\n", 0, pos) + 1


def _nginx_findings(rel: str, code: str) -> list[str]:
    """nginx / shell：`return 30x` / `rewrite … redirect|permanent` / `Location` 头。"""
    findings: list[str] = []
    for lineno, line in enumerate(code.splitlines(), 1):
        tokens = line.split()
        if not tokens:
            continue
        head = tokens[0]
        if head == "return" and len(tokens) >= 3 and tokens[1].startswith("30"):
            if _is_w_target(tokens[2]):
                findings.append(
                    f"{rel}:{lineno}: nginx `return {tokens[1]} {tokens[2]}` —— 302 指向 /w/"
                    f"（/w/ 不再是任何跳转的目标：落地面在 /b）"
                )
        if head == "rewrite" and len(tokens) >= 3 and _is_w_target(tokens[2]):
            flag = tokens[3].rstrip(";") if len(tokens) > 3 else ""
            if flag in {"redirect", "permanent"}:
                findings.append(
                    f"{rel}:{lineno}: nginx `rewrite … {tokens[2]} {flag}` —— 对外跳转到 /w/"
                    f"（内部换页请用 last/break：URL 留在 /b 下）"
                )
        if head in {"add_header", "proxy_redirect"}:
            for token in tokens[1:]:
                if _is_w_target(token.rstrip(';"')):
                    findings.append(f"{rel}:{lineno}: nginx `{head} … {token}` —— 响应头把客户端送去 /w/")
                    break
    return findings


def _literal_findings(rel: str, code: str, suffix: str) -> list[str]:
    """Java / TS：取**字符串字面量**（注释里的不算），再看它落在哪种语句位置上。"""
    findings: list[str] = []
    literals = (
        typescript_literals(code)
        if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs"}
        else java_literals(code)
    )
    for pos, value in literals:
        if not _is_w_target(value):
            continue
        head = code[:pos].rstrip()[-200:]
        lineno = _line_of(code, pos)
        if _nav_head(head):
            findings.append(
                f"{rel}:{lineno}: 跳转语句的目标是 {value!r} —— bmini / 服务端都不许把用户送去 /w/"
                f"（旧码直连由纸码 302 承担，不是代码入口）"
            )
        elif _const_head(head):
            findings.append(
                f"{rel}:{lineno}: 302 目标常量被写成 {value!r} —— 落地面必须是 /b…（/w/ 不再是目标）"
            )
    # 模板串（反引号）不在字面量走查里 —— 补一条纯字符串扫描（不按引号取值，只判语句头）。
    for lineno, line in enumerate(code.splitlines(), 1):
        index = line.find("`/w/")
        if index < 0:
            continue
        head = line[:index].rstrip()[-120:]
        if _nav_head(head) or _const_head(head):
            findings.append(f"{rel}:{lineno}: 模板串形式的 /w/ 跳转目标 —— 同族，一律不许")
    return findings


def _html_findings(rel: str, code: str) -> list[str]:
    """HTML：`href=` / `src=` 属性值（纯字符串操作，不按引号取值）。"""
    findings: list[str] = []
    for lineno, line in enumerate(code.splitlines(), 1):
        for attr in ("href=", "src="):
            index = line.find(attr)
            while index >= 0:
                rest = line[index + len(attr):]
                if rest[:1] in {"'", '"'}:
                    quote = rest[0]
                    value = rest[1:].split(quote, 1)[0]
                    if _is_w_target(value):
                        findings.append(f"{rel}:{lineno}: `{attr}{value}` —— 页面里的链接指向 /w/")
                        break
                index = line.find(attr, index + len(attr))
    return findings


def redirect_findings(sources: dict[str, str]) -> list[str]:
    """**唯一的判定**：给定「文件 → 原文」，交出所有「跳转 / 302 目标 = `/w/`」的具名读数。"""
    findings: list[str] = []
    for rel in sorted(sources):
        suffix = Path(rel).suffix
        code = _code_only(rel, sources[rel])
        if suffix in {".conf", ".sh"}:
            findings.extend(_nginx_findings(rel, code))
        elif suffix == ".html":
            findings.extend(_html_findings(rel, code))
        else:
            findings.extend(_literal_findings(rel, code, suffix))
    return findings


def internal_serving_sites(sources: dict[str, str]) -> list[str]:
    """**判别力自证**：真语料里`/w/`确实被「供应」着（内部 rewrite）—— 证明扫描器不是瞎的。

    没有这一条，「零命中」分不清「真没有跳转」与「扫描器根本没读到 `/w/`」。
    """
    sites: list[str] = []
    for rel in sorted(sources):
        if Path(rel).suffix not in {".conf", ".sh"}:
            continue
        code = _code_only(rel, sources[rel])
        for lineno, line in enumerate(code.splitlines(), 1):
            tokens = line.split()
            if len(tokens) >= 3 and tokens[0] == "rewrite" and _is_w_target(tokens[2]):
                flag = tokens[3].rstrip(";") if len(tokens) > 3 else ""
                if flag in {"last", "break"}:
                    sites.append(f"{rel}:{lineno}")
    return sites


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据 2：旧码仍可用（nginx 结构 + 静态面 → 一次真模拟）
# ══════════════════════════════════════════════════════════════════════════════


def _location_spans(conf: str) -> list[tuple[str, int, int]]:
    """`location <名字> { … }` ⇒ `(名字, 起始行下标, 结束行下标)`。

    **按行**配平大括号，且**先剥注释**（注释里写着 `location /w/ {` 的说明不得把解析带偏 ——
    这正是本仓「判据把原文当代码读」那一族，`redecode` 已踩过）。
    """
    lines = conf.splitlines()
    spans: list[tuple[str, int, int]] = []
    index = 0
    while index < len(lines):
        stripped = _line_comment_stripper()(lines[index]).strip()
        if stripped.startswith("location ") and stripped.endswith("{"):
            name = stripped[len("location "):-1].strip()
            start = index
            depth = 0
            while index < len(lines):
                current = _line_comment_stripper()(lines[index])
                depth += current.count("{") - current.count("}")
                index += 1
                if depth <= 0:
                    break
            spans.append((name, start, index))
            continue
        index += 1
    return spans


def _location_blocks(conf: str) -> dict[str, str]:
    """`location <名字> { … }` ⇒ 块体（同名取第一处；块体已剥注释）。"""
    lines = conf.splitlines()
    blocks: dict[str, str] = {}
    for name, start, end in _location_spans(conf):
        if name in blocks:
            continue
        body = [_line_comment_stripper()(line) for line in lines[start + 1:end - 1]]
        blocks[name] = "\n".join(body)
    return blocks


def drop_location(conf: str, name: str) -> str:
    """从配置里**整块**删掉一个 location（红证用；同名多处一起删）。"""
    lines = conf.splitlines(keepends=True)
    spans = [(start, end) for block, start, end in _location_spans(conf) if block == name]
    for start, end in sorted(spans, reverse=True):
        del lines[start:end]
    return "".join(lines)


def serve_w(rel: str, files: frozenset[str]) -> tuple[int, str]:
    """模拟 `location /w/ { try_files $uri $uri/ /w/index.html; }` 的取文件语义。

    `files` = `frontend/worker-h5/` 下的仓库内相对路径集合。返回 `(状态码, 真正返回的路径)`。
    """
    target = "index.html" if rel in {"", "/", "index.html"} else rel.lstrip("/")
    if target in files:
        return 200, target
    prefix = target.rstrip("/") + "/"
    if any(item.startswith(prefix) for item in files):
        index = prefix + "index.html"
        if index in files:
            return 200, index
    if "index.html" in files:
        return 200, "index.html"  # nginx 兜底：/w/index.html（仍在自己的命名空间内）
    return 404, ""


def serving_problems(conf: str, files: frozenset[str]) -> list[str]:
    """**唯一的判定**：`/w/` 的供应面 + 302 的落地面 + 已印出码的两跳，全都在 ⇒ 空列表。"""
    problems: list[str] = []
    blocks = _location_blocks(conf)

    worker = blocks.get("/w/")
    if worker is None:
        problems.append(
            "nginx 少了 `location /w/` —— 已印出的码（…/w/?t=<token>）会落到 `location /` 的 SPA 兜底"
            "（HTTP 200 + C 端首页：不是 404，监控不红，工人只当打不开）"
        )
    else:
        if "try_files" not in worker or "/w/index.html" not in worker:
            problems.append(
                "`location /w/` 的兜底不在自己的命名空间内（要 `try_files $uri $uri/ /w/index.html`）"
            )
        if "default_type application/javascript" not in worker:
            problems.append(
                "`location /w/` 丢了 `default_type application/javascript` ⇒ `/w/src/*.mjs` 的 MIME 变坏"
                "（浏览器拒绝执行 module script ⇒ 整页白屏，issue #6293）"
            )

    report_block = blocks.get("/b/report/")
    if report_block is None:
        problems.append(
            "nginx 少了 `location /b/report/` —— 纸码 302 的落地面没了（跳出 /b 命名空间 = 同一份页面两个地址）"
        )
    else:
        rewrites = [line.split() for line in report_block.splitlines() if line.strip().startswith("rewrite")]
        if not rewrites:
            problems.append("`location /b/report/` 没有 rewrite ⇒ 该前缀下没有任何页面（302 过去是 404/兜底）")
        else:
            tokens = rewrites[0]
            flag = tokens[3].rstrip(";") if len(tokens) > 3 else ""
            if len(tokens) < 4 or not _is_w_target(tokens[2]) or flag not in {"last", "break"}:
                problems.append(
                    "`location /b/report/` 必须**内部**换到 /w/ 那一份页面（`rewrite … /w/$1 last`）"
                    "**且 flag ∈ {last, break}** —— 带 redirect/permanent 就是对外的 /w/ 跳转"
                )

    short = blocks.get("/s/")
    if short is None:
        problems.append("nginx 少了 `location /s/` —— 纸上的 `/s/<短码>` 不再反代到 admin-api（302 那半边没了）")
    else:
        proxy = [line.strip() for line in short.splitlines() if line.strip().startswith("proxy_pass")]
        if not proxy:
            problems.append("`location /s/` 没有 proxy_pass ⇒ 短码没有服务端换 token 的路径")
        else:
            target = proxy[0][len("proxy_pass"):].strip().rstrip(";").strip()
            remainder = target.split("//", 1)[-1]
            if "/" in remainder:
                problems.append(
                    f"`location /s/` 的 proxy_pass 带了 URI 后缀（{target!r}）⇒ nginx 会把匹配到的前缀替换掉"
                    "（`/s/<码>` 变成 `<码>`，控制器收不到自己的路径）"
                )

    # 已印出的码的两跳：`/w/?t=` 仍是那页、`/w/machine.html` 仍是裁高页、未知页仍兜在本命名空间内
    first = serve_w("", files)
    if first != (200, "index.html"):
        problems.append(f"`/w/?t=<token>` 取不到 index.html（模拟读数 {first}）⇒ 已印出的码失效")
    machine = serve_w("machine.html", files)
    if machine != (200, "machine.html"):
        problems.append(f"`/w/machine.html`（裁高页）取不到（模拟读数 {machine}）⇒ 旧码进不了裁高面")
    module = serve_w("src/app.mjs", files)
    if module != (200, "src/app.mjs"):
        problems.append(f"`/w/src/app.mjs`（页面本体）取不到（模拟读数 {module}）⇒ 旧码打开是白屏")
    fallback = serve_w("gone.html", files)
    if fallback != (200, "index.html"):
        problems.append(f"未知页没有兜回 `/w/index.html`（模拟读数 {fallback}）⇒ 兜底跑出了命名空间")
    return problems


def _declared_const(code: str, name: str, suffix: str) -> list[str]:
    """按**字面量位置**取 `NAME = "…"` 的值（Java / TS 字面量走查；不走 Python 的 ast）。"""
    literals = (
        typescript_literals(code)
        if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs"}
        else java_literals(code)
    )
    out: list[str] = []
    for pos, value in literals:
        head = code[:pos].rstrip()[-200:]
        if not _const_head(head):
            continue
        before = head[:-1].rstrip()
        ident = ""
        for ch in reversed(before):
            if ch.isalnum() or ch in "_$":
                ident = ch + ident
            else:
                break
        if ident == name:
            out.append(value)
    return out


def report_target_problems(java_source: str) -> list[str]:
    """302 目标常量：必须是 `/b/…`，且查询串口径 `?t=` 未动（已印出的码靠它换 token）。"""
    problems: list[str] = []
    declared = _declared_const(java_code(java_source), "REPORT_PAGE_PATH", ".java")
    if len(declared) != 1:
        problems.append(
            f"`REPORT_PAGE_PATH` 应恰好声明 1 次（现取 {len(declared)} 次）—— 302 的目标只许有**一处**真值"
        )
        return problems
    target = declared[0]
    if not target.startswith("/b/"):
        problems.append(f"302 目标被写成 {target!r} —— 落地面必须在 `/b/` 下（/w/ 不再是目标）")
    code = java_code(java_source)
    if '"?t="' not in code:
        problems.append(
            '`reportPageLocation` 的查询串口径变了（源码里找不到 `"?t="`）—— 已印出的码靠 `?t=<token>` 换票'
        )
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 四、读真语料（真判据用；红证走上面的纯函数）
# ══════════════════════════════════════════════════════════════════════════════


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(f"受管文件不存在：{rel} ⇒ 判红（路径漂移不得静默跳过）")
    return path.read_text(encoding="utf-8")


def _real_sources() -> dict[str, str]:
    return {rel: _read(rel) for rel in _iter_scan_files()}


def _worker_h5_files() -> frozenset[str]:
    root = REPO_ROOT / WORKER_H5_ROOT
    if not root.is_dir():
        raise AssertionError(f"`{WORKER_H5_ROOT}` 不存在 ⇒ `/w/` 的静态面没了（已印出的码必失效）")
    return frozenset(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


# ══════════════════════════════════════════════════════════════════════════════
# 五、判据 1：没有任何 302 / 跳转指向 `/w/`
# ══════════════════════════════════════════════════════════════════════════════


def test_no_redirect_or_link_targets_w() -> None:
    """判据 1（全扫描面）：`deploy/**` + `frontend/**` + `backend/**` 里没有跳转目标 `/w/`。"""
    sources = _real_sources()
    findings = redirect_findings(sources)
    print(f"扫描面 {len(sources)} 个文件；/w/ 跳转命中 {len(findings)} 处")
    for line in findings:
        print("  " + line)
    assert findings == [], (
        "出现了指向 `/w/` 的 302 / 跳转（issue #7813 P2c：`/w/` 转入兼容期，不再是任何跳转的目标）：\n"
        + "\n".join(f"  {line}" for line in findings)
        + "\n修法：把落地面改成 `/b/…`（bmini）；`/w/` 只服务**已印出的码直连**这一条通道。"
    )


def test_serving_is_not_redirecting() -> None:
    """判据 1b：`/w/` 可以被**供应**（内部 rewrite，URL 不变），不可以被**跳转**到。"""
    sources = _real_sources()
    sites = internal_serving_sites(sources)
    print(f"内部换页（rewrite … /w/… last|break）读数 = {sites}")
    assert sites, (
        "真语料里**一处**都没认出「内部换页到 /w/」—— 而 `/b/report/` 正是这么供应的 ⇒ "
        "要么这条通道被拿掉了（旧码失效），要么扫描器读不到 `/w/`（下面那条零命中就成了假绿）"
    )
    assert any(NGINX_CONF in site for site in sites), (
        f"内部换页不在 {NGINX_CONF} 里（现取 {sites}）—— 302 的落地面换了实现 ⇒ 同步本判据"
    )


@pytest.mark.parametrize(
    ("name", "sources"),
    [
        (
            "nginx 写一条 302 到 /w/",
            {
                "deploy/swas/nginx.conf": (
                    "server {\n"
                    "    location /s/ {\n"
                    "        proxy_pass http://admin-api:8080;\n"
                    "    }\n"
                    "    location = /legacy {\n"
                    "        return 302 /w/?t=abc;\n"
                    "    }\n"
                    "}\n"
                )
            },
        ),
        (
            "Java 把 302 换回 /w/",
            {
                SHORT_LINK_SERVICE: (
                    "class WorkerShortLinkService {\n"
                    "    static void go(javax.servlet.http.HttpServletResponse r) {\n"
                    "        r.sendRedirect(\"/w/?t=\" + token);\n"
                    "    }\n"
                    "}\n"
                )
            },
        ),
        (
            "Java 把目标常量写成 /w/",
            {
                SHORT_LINK_SERVICE: (
                    "class WorkerShortLinkService {\n"
                    "    public static final String REPORT_PAGE_PATH = \"/w/report/\";\n"
                    "}\n"
                )
            },
        ),
        (
            "bmini 加一个按钮指向 /w/",
            {
                f"{BMINI_SRC}/pages/worker/home/index.tsx": (
                    "export default function Home() {\n"
                    "  return <Button onClick={() => Taro.navigateTo({ url: '/w/machine.html' })}>裁高</Button>\n"
                    "}\n"
                )
            },
        ),
        (
            "旧语料里加一条 href 到 /w/",
            {
                "frontend/worker-h5/index.html": '<a href="/w/machine.html">裁高</a>\n',
            },
        ),
    ],
)
def test_criterion_1_red_proof(name: str, sources: dict[str, str]) -> None:
    """判据 1 的红证（注入式）：每一种面加一条 /w/ 跳转 ⇒ **同一个**判定必须具名判红。"""
    findings = redirect_findings(sources)
    assert findings, f"[{name}] 注入后零命中 ⇒ 判据没有牙（红证失效）"
    assert any("/w/" in line for line in findings), f"[{name}] 命中读数里没有 /w/：{findings}"
    print(f"[{name}] 命中 {len(findings)} 处：{findings[0]}")


def test_criterion_1_negative_controls() -> None:
    """判据 1 的**负控**：内部换页 / 注释里的说明 / 非跳转用途的字符串，一律**不**判红。"""
    negative = {
        NGINX_CONF: (
            "# 说明：`return 302 /w/` 这种写法**不许**再出现（注释不是站点）\n"
            "location /b/report/ {\n"
            "    rewrite ^/b/report/(.*)$ /w/$1 last;\n"
            "}\n"
        ),
        f"{BMINI_SRC}/utils/workerSession.ts": (
            "// 把 `/b/` 的工人身份镜像到 `/w/` 报工页（同一 origin 的 localStorage）\n"
            "export const H5_WORKER_SESSION_KEY = 'migao:worker-h5:session'\n"
            "export function mirror() { localStorage.setItem('/w/ 说明不是入口', '1') }\n"
        ),
    }
    findings = redirect_findings(negative)
    print(f"负控命中 = {findings}")
    assert findings == [], (
        "负控被判红 ⇒ 判据把「注释里的说明 / 内部换页 / 普通字符串」当成了跳转（会逼出纸面修复）：\n"
        + "\n".join(f"  {line}" for line in findings)
    )


# ══════════════════════════════════════════════════════════════════════════════
# 六、判据 3：bmini 侧不再新增 `/w/` 入口（含「旧码直连」不是代码入口的负控）
# ══════════════════════════════════════════════════════════════════════════════


def test_bmini_never_links_to_w() -> None:
    """判据 3：bmini 的生产代码里没有任何 `/w/` 跳转（旧码直连 = 纸码 302，不是代码入口）。"""
    scoped = {
        rel: text
        for rel, text in _real_sources().items()
        if rel.startswith(BMINI_SRC + "/")
    }
    print(f"bmini 扫描面 {len(scoped)} 个文件")
    findings = redirect_findings(scoped)
    assert findings == [], (
        "bmini 侧出现了指向 `/w/` 的入口（issue #7813 P2c：`/w/` 不再新增入口）：\n"
        + "\n".join(f"  {line}" for line in findings)
        + "\n修法：新入口一律指向 bmini 自己的页面（`src/pages/worker/**`），纸码由 302 承担。"
    )
    assert len(scoped) > 0, "bmini 扫描面塌成空集 ⇒ 判红（「扫了 0 个文件」不是通过）"


def test_criterion_3_red_proof() -> None:
    """判据 3 的红证：工人首页加一个指向 `/w/` 的按钮 ⇒ 必须**点名那个文件**判红。"""
    home = f"{BMINI_SRC}/pages/worker/home/index.tsx"
    broken = {
        home: (
            "export default function Home() {\n"
            "  const goLegacy = () => Taro.redirectTo({ url: '/w/machine.html' })\n"
            "  return <Button onClick={goLegacy}>裁高（旧页）</Button>\n"
            "}\n"
        )
    }
    findings = redirect_findings(broken)
    assert findings, "注入了一条 /w/ 按钮却零命中 ⇒ 判据 3 没有牙"
    assert any(home in line for line in findings), f"判红没有点名页面（要找 {home}）：{findings}"
    print(f"[判据 3 红证] {findings[0]}")


def test_criterion_3b_session_mirror_is_not_an_entry() -> None:
    """判据 3b：`H5_WORKER_SESSION_KEY` 这类 localStorage 镜像是**身份复用**，不是入口。"""
    session = f"{BMINI_SRC}/utils/workerSession.ts"
    text = _read(session)
    assert "H5_WORKER_SESSION_KEY" in text, f"{session} 里没有会话镜像键 ⇒ 旧码落到的那一页拿不到身份"
    findings = redirect_findings({session: text})
    assert findings == [], (
        "会话镜像被判成入口 ⇒ 判据把「同源 localStorage 复用」读成「跳转到 /w/」，会逼出误删：\n"
        + "\n".join(f"  {line}" for line in findings)
    )
    # 反向：把镜像改成真跳转 ⇒ 同一判定必须红（说明「镜像 ≠ 入口」这条口径真被区分了）
    mutated = text.replace(
        "localStorage.setItem(H5_WORKER_SESSION_KEY",
        "location.replace('/w/'); localStorage.setItem(H5_WORKER_SESSION_KEY",
        1,
    )
    assert mutated != text, "红证变异没生效（锚点漂了）⇒ 先核 workerSession.ts 的现取形态"
    assert redirect_findings({session: mutated}), "把镜像改成 /w/ 跳转却仍判绿 ⇒ 判别力丢了"


# ══════════════════════════════════════════════════════════════════════════════
# 七、判据 2：旧码仍可用（已印出的纸码 / 书签仍到得了报工面与裁高面）
# ══════════════════════════════════════════════════════════════════════════════


def test_legacy_printed_codes_still_work() -> None:
    """判据 2：`/w/` 的供应面 + `/b/report/` 内部落地面 + `/s/` 反代 + 302 目标常量，四处全在。"""
    problems = serving_problems(_read(NGINX_CONF), _worker_h5_files())
    problems += report_target_problems(_read(SHORT_LINK_SERVICE))
    for line in problems:
        print("  " + line)
    assert problems == [], (
        "「已印出的码不许失效」被破坏（issue #7813 P2c：本单**不删** `/w/`、不改它的功能）：\n"
        + "\n".join(f"  {line}" for line in problems)
    )


def test_criterion_2_red_proof_deleting_location_w() -> None:
    """判据 2 的红证 ①：删掉 `location /w/` ⇒ 同一判定必须判红并指出「旧码会落到 C 端首页」。"""
    conf = _read(NGINX_CONF)
    broken = drop_location(conf, "/w/")
    assert "/w/" not in _location_blocks(broken), "红证变异没生效（解析出来的块里 `location /w/` 还在）"
    problems = serving_problems(broken, _worker_h5_files())
    assert any("location /w/" in line for line in problems), f"删掉 location /w/ 却没判红：{problems}"
    print(f"[判据 2 红证 ①] {problems[0]}")


def test_criterion_2_red_proof_rewrite_becomes_redirect() -> None:
    """判据 2 的红证 ②：把内部 rewrite 的 flag 改成 `redirect` ⇒ 判红（对外就是 /w/ 跳转了）。"""
    conf = _read(NGINX_CONF)
    anchor = "rewrite ^/b/report/(.*)$ /w/$1 last;"
    assert conf.count(anchor) == 1, f"锚点漂了：现取 nginx.conf 里 `{anchor}` 出现 {conf.count(anchor)} 次"
    broken = conf.replace(anchor, "rewrite ^/b/report/(.*)$ /w/$1 redirect;", 1)
    problems = serving_problems(broken, _worker_h5_files())
    assert any("last, break" in line or "redirect/permanent" in line for line in problems), (
        f"把内部换页改成对外 302 却没判红：{problems}"
    )
    print(f"[判据 2 红证 ②] {problems[0]}")


def test_criterion_2_red_proof_302_target_back_to_w() -> None:
    """判据 2 的红证 ③：把 `REPORT_PAGE_PATH` 改回 `/w/…` ⇒ 判红（落地面跑回兼容期目录）。"""
    source = _read(SHORT_LINK_SERVICE)
    broken = source.replace('REPORT_PAGE_PATH = "/b/report/"', 'REPORT_PAGE_PATH = "/w/"', 1)
    assert broken != source, "红证变异没生效（锚点 `REPORT_PAGE_PATH = \"/b/report/\"` 找不到）"
    problems = report_target_problems(broken)
    assert any("/b/" in line for line in problems), f"把 302 目标改回 /w/ 却没判红：{problems}"
    print(f"[判据 2 红证 ③] {problems[0]}")


# ══════════════════════════════════════════════════════════════════════════════
# 八、判据 5：扫描面非空自证 + 判据 6：兼容期声明在案
# ══════════════════════════════════════════════════════════════════════════════


def test_scan_surface_is_non_empty() -> None:
    """判据 5：「零命中」必须可分——扫描面非空、必扫文件在面内、真语料里认得出 `/w/`。"""
    scanned = _iter_scan_files()
    print(f"扫描面 = {len(scanned)} 个文件")
    assert len(scanned) > 0, "扫描面塌成空集 ⇒ 零命中是假绿（「扫了 0 个文件」不是通过）"
    missing = [rel for rel in REQUIRED_IN_SURFACE if rel not in scanned]
    assert missing == [], (
        "下列必扫文件不在扫描面内（扫描面悄悄塌了 ⇒ 判据变空断言）：\n"
        + "\n".join(f"  {rel}" for rel in missing)
    )
    sources = _real_sources()
    assert sources, "读到的语料为空 ⇒ 判红（读不到 ≠ 通过）"
    refused = [rel for rel, text in sources.items() if "/w/" in text]
    print(f"真语料里提及 /w/ 的文件 {len(refused)} 个（提及 ≠ 入口，判据只看跳转形态）")
    assert any(rel == NGINX_CONF for rel in refused), (
        f"{NGINX_CONF} 里读不到 `/w/` ⇒ 语料读错了对象（零命中会变成假绿）"
    )


def test_compat_period_declaration_is_in_place() -> None:
    """判据 6：`/w/` 的保留声明写清三句口径（只为旧码 / 不再新增功能 / 不再是 302 目标）。"""
    text = _read(WORKER_H5_README)
    required = ("已印出的码", "不再新增功能", "不再是 302 的目标")
    missing = [token for token in required if token not in text]
    assert missing == [], (
        f"`{WORKER_H5_README}` 缺口径：{missing} —— 兼容期必须写在**目录里**（不是只在 PR body）："
        "下一个改这个目录的人先看到它"
    )
    assert "旧码直连" in text, (
        "声明里没说清「兼容期保留的唯一通道 = 旧码直连」（否则下一个人会把它当新入口用）"
    )
