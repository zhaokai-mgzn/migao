# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。
#   本 PR 不新建用例族。）
r"""`deploy/swas/nginx.conf` 的**限流防刷**常驻判据（关联 issue #20 第 3 项）。

## 为什么要一条常驻判据

限流参数是**配置里的裸数字**：删掉一行 `limit_req_zone`、把 `burst=200` 改成 `burst=2`、
或者把限流顺手加到静态面（`/w/` 报工页、admin-web 的 JS/CSS）上 —— 这几种改动**都不会有任何东西变红**，
而最后一种会直接把车间报工打断（`/w/` 一次页面加载要取十几个静态文件）。
本文件把三件事钉成判据：**① 限流存在且参数是文档值 ② 阈值仍压得住重算出来的实测用量
③ 静态面没有被误伤**。

## 判据（每条都能单独变红）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | zone 表 == 文档表（键 / rate / 内存尺寸逐字） | 删一个 zone / 改 rate / 改 key ⇒ 红 |
| 2 | `limit_req_status 429` + `limit_req_log_level warn` 在 http 上下文 | 删掉 ⇒ 红（默认 503 会把人引向错误排查方向） |
| 3 | **「挂了限流的 location」⟺「带 `proxy_pass` 的 location」**（双向） | 给静态 `location /` 加限流 ⇒ 红；把某个 API location 的限流删光 ⇒ 红 |
| 4 | 5 个动态入口的 (zone → burst) == 文档表 | 把 `/s/` 的 burst 从 1000 改成 1 ⇒ 红 |
| 5 | 工人面没有小额 per-IP 额度：`/s/` 只挂 worker_entry | `/s/` 挂上 api_perip（10 r/s）⇒ 红 |
| 6 | **阈值仍 ≥ 10× 重算出来的实测用量**（不是注释里的死数） | admin-web 某个页面并发涨到 21 ⇒ 红（逼着重新推导） |
| 7 | 注入式红证（本文件内真跑）：删 zone / 砍 burst / 给静态面加限流 | 任一注入**没被检出** ⇒ 红（判据自己空转） |

## 阈值是怎么推导的（判据 6 每次**重算**，不是抄注释）

- **一次正常「最重的 admin-web 页面」加载** = `max_parallel_api_wave()`（从
  `frontend/admin-web/src/app/**` 真扫 `Promise.all` / `Promise.allSettled` 的元素里有多少个
  `<x>Api.<m>(` 调用，取最大值）+ **3 个单例**（懒加载的「算料配置」tab、`/api/auth/me` 引导、
  未读通知数）—— 那 3 个单例由 `_SINGLETON_ANCHORS` 逐条钉在源文件的现场锚点上（锚点消失 ⇒ 红，
  免得"9"这个数悄悄过期）。
- **工人端**：一次扫码 = `resolveScan` + `completeByScan` 两个请求（锚点 = `api.mjs` 里那两个端点
  字面量），页面加载 = 1 个（`current-worker`），`/s/<码>` = 1 个。
- 判据对每个 zone 要求 `burst ≥ 10 ×` 该面正常用量的上界。余量是**下界**，不是精确值。

## 边界（照实登记，**不是**「已覆盖」）

- 判据读的是**配置文本与 TS 源码文本**，**不跑 nginx** ⇒ 它证明不了 `nginx -t` 的语法通过
  （本机没有 nginx 二进制、没有 docker；见 PR body 的「未取证」）。
- `max_parallel_api_wave()` 只认「`Promise.all([...])` 里字面量写出来的 `<x>Api.<m>(`」这一形态：
  拆成变量再并发、或 `.then()` 串起来的页面**扫不到**（**假绿方向**，不会误伤）。
- 工人端的「一次扫码 = 2 个请求」是按端点字面量**数出来的**，不跟踪调用图：将来若扫码流程多打一个端点，
  本条**不会**自动跟着涨（已登记为残余，见 PR body）。
- 配置注释里的中文说明与表格**不参与判定** —— 判定只吃结构化解析出来的指令。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
ADMIN_WEB_APP_DIR = REPO_ROOT / "frontend" / "admin-web" / "src" / "app"
ADMIN_WEB_SRC = REPO_ROOT / "frontend" / "admin-web" / "src"
WORKER_H5_SRC = REPO_ROOT / "frontend" / "worker-h5" / "src"

#: 文档化的 zone 表（**唯一口径**）：zone 名 → 取 key 的表达式 / rate / 共享内存尺寸。
#: 改 `nginx.conf` 的 zone 而不改这里（或反之）⇒ 判据 1 红。
DOCUMENTED_ZONES: dict[str, dict[str, str]] = {
    # 通用动态面：burst 200 = 22× 实测的一屏 9 个请求；10 r/s = 600 r/m
    "api_perip": {"key": "$api_perip_key", "rate": "10r/s", "size": "10m"},
    # 登录面（密码/PIN 类；C 端微信/SMS 登录走通用档，见 nginx.conf 注释）：正常一次登录 1 个请求 ⇒ burst 60 = 60×
    "auth_perip": {"key": "$auth_login_key", "rate": "1r/s", "size": "10m"},
    # 花钱/可被刷面（短信下发、注册提交）：burst 10 = 10× 正常值
    "abuse_perip": {"key": "$abuse_key", "rate": "6r/m", "size": "10m"},
    # 工人会话面：一次扫码 2 个请求 ⇒ burst 60 够连扫 30 件
    "worker_sess": {"key": "$worker_sess_key", "rate": "2r/s", "size": "10m"},
    # 工人入口面（per-IP 兜底）：一次扫码 1 个请求 ⇒ burst 1000；50 r/s 够整层车间共用出口 IP
    "worker_entry": {"key": "$worker_entry_key", "rate": "50r/s", "size": "10m"},
}

#: 文档化的「哪些 location 挂哪些 zone（burst=?）」表。**限流 ⟺ 带 `proxy_pass`** 的闭包由判据 3 钉。
DOCUMENTED_LIMITS: dict[tuple[str, str], dict[str, int]] = {
    ("api.migaozn.com", "/"): {
        "api_perip": 200, "auth_perip": 60, "abuse_perip": 10,
        "worker_sess": 60, "worker_entry": 1000,
    },
    ("ai-api.migaozn.com", "/"): {"api_perip": 200},
    ("app.migaozn.com", "/s/"): {"worker_entry": 1000},
    ("app.migaozn.com", "/api/chat/"): {"api_perip": 200},
    ("app.migaozn.com", "/api/"): {
        "api_perip": 200, "auth_perip": 60, "abuse_perip": 10,
        "worker_sess": 60, "worker_entry": 1000,
    },
}

#: 静态/前端面：**必须没有**限流（一次页面加载要取几十个静态文件）。值 = 为什么不挂。
STATIC_NO_LIMIT: dict[tuple[str, str], str] = {
    # admin-web 的页面 + JS/CSS/字体
    ("migaozn.com", "/"): "admin-web 静态/SSR 面：限流会误伤正常页面加载",
    # C 端 H5 与**工人端 `/w/`**（同一 root）
    ("app.migaozn.com", "/"): "C 端 H5 + 工人端 /w/ 的静态面：限流会打断车间报工",
}

#: 「正常用量」的现场锚点：这些字符串必须在源码里（消失 ⇒ 红），否则下面的常量就是抄来的死数。
_SINGLETON_ANCHORS: tuple[tuple[str, str], ...] = (
    ("frontend/admin-web/src/store/auth.ts", "authApi.getUserInfo"),
    ("frontend/admin-web/src/components/layout/NotificationBell.tsx", "POLL_INTERVAL"),
    ("frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx", "getCraftCalcConfig"),
)
_SINGLETON_COST = len(_SINGLETON_ANCHORS)

#: 工人端请求锚点：（文件, 端点字面量, 该流程里的请求数上界）
_WORKER_SCAN_ENDPOINTS = (
    "frontend/worker-h5/src/api.mjs",
    ("/api/worker/production/scan?", "/api/worker/production/scan/complete"),
)
_WORKER_PAGE_LOAD_ENDPOINTS = ("/api/worker/production/current-worker",)

_HEADROOM_FACTOR = 10


# ══════════════════════════════════════════════════════════════════════════════
# 一、nginx.conf 的**结构化**读取（剥注释走引号感知的手写扫描器；不用 split('#') 也不用 re.sub）
# ══════════════════════════════════════════════════════════════════════════════


def strip_comment(line: str) -> str:
    """剥掉行内注释（`#`），但**跳过引号内**的 `#`。手写扫描 = 不依赖正则、也不做朴素截断。"""
    out: list[str] = []
    quote = ""
    for char in line:
        if quote:
            out.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            out.append(char)
            continue
        if char == "#":
            break
        out.append(char)
    return "".join(out)


class Block:
    """nginx 配置块（`header { … }`）。`directives` 是**本层**的单条指令（`;` 结尾）。"""

    def __init__(self, header: str) -> None:
        self.header = header
        self.directives: list[str] = []
        self.children: list[Block] = []


def parse_nginx(text: str) -> Block:
    """→ 配置树（父子相连）。剥注释 + 引号感知（`map` 里 `"~^[0-9A-Za-z_-]{8,64}$"` 的花括号**不算**块）。"""
    root = Block("<root>")
    stack: list[Block] = [root]
    buf: list[str] = []
    quote = ""
    for raw_line in text.splitlines():
        line = strip_comment(raw_line)
        for char in line:
            if quote:
                buf.append(char)
                if char == quote:
                    quote = ""
                continue
            if char in "\"'":
                quote = char
                buf.append(char)
                continue
            if char == "{":
                block = Block("".join(buf).strip())
                stack[-1].children.append(block)
                stack.append(block)
                buf = []
                continue
            if char == "}":
                statement = "".join(buf).strip()
                if statement:
                    stack[-1].directives.append(statement)
                buf = []
                if len(stack) > 1:
                    stack.pop()
                continue
            if char == ";":
                statement = "".join(buf).strip()
                if statement:
                    stack[-1].directives.append(statement)
                buf = []
                continue
            buf.append(char)
    return root


def walk(block: Block, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Block]]:
    """→ [(上下文路径, 块)]。路径形如 `('server', 'location /api/')`，够定位、不依赖行号。"""
    found = [(path, block)]
    for child in block.children:
        found += walk(child, path + (child.header,))
    return found


def _servers(root: Block) -> dict[str, Block]:
    """→ {主域名: 443 server 块}。只认 `listen 443`（80 那个只做 301）。"""
    out: dict[str, Block] = {}
    for block in root.children:
        if block.header != "server":
            continue
        if not any(d.startswith("listen 443") for d in block.directives):
            continue
        names = [d for d in block.directives if d.startswith("server_name ")]
        if not names:
            continue
        out[names[0].split()[1]] = block
    return out


def _locations(server: Block) -> dict[str, Block]:
    """→ {location 头（如 `/api/`）: 块}。只取**前缀** location（正则 location 不在限流面内）。"""
    out: dict[str, Block] = {}
    for block in server.children:
        if not block.header.startswith("location "):
            continue
        target = block.header.split(None, 1)[1].strip()
        if target.startswith(("~", "=", "^~")):
            continue
        out[target] = block
    return out


def zones_of(text: str) -> dict[str, dict[str, str]]:
    """→ {zone 名: {key, rate, size}}（`limit_req_zone` 的现取表）。"""
    out: dict[str, dict[str, str]] = {}
    for _path, block in walk(parse_nginx(text)):
        for statement in block.directives:
            if not statement.startswith("limit_req_zone "):
                continue
            body = statement[len("limit_req_zone "):]
            key_expr, _sep, rest = body.partition(" zone=")
            if not _sep:
                continue
            name_and_size, _sep2, rate = rest.partition(" rate=")
            name, _colon, size = name_and_size.partition(":")
            out[name.strip()] = {"key": key_expr.strip(), "rate": rate.strip(), "size": size.strip()}
    return out


def http_level(text: str) -> list[str]:
    """→ 文件**顶层**（本文件 = conf.d 的 http 上下文）的指令清单。"""
    return list(parse_nginx(text).directives)


def limits_of(text: str) -> dict[tuple[str, str], dict[str, int]]:
    """→ {(域名, location 头): {zone: burst}}（`limit_req` 的现取表）。"""
    out: dict[tuple[str, str], dict[str, int]] = {}
    for domain, server in _servers(parse_nginx(text)).items():
        for target, location in _locations(server).items():
            zones: dict[str, int] = {}
            for statement in location.directives:
                if not statement.startswith("limit_req "):
                    continue
                zone = re.search(r"zone=([A-Za-z0-9_]+)", statement)
                burst = re.search(r"burst=([0-9]+)", statement)
                if zone and burst:
                    zones[zone.group(1)] = int(burst.group(1))
            if zones:
                out[(domain, target)] = zones
    return out


def maps_of(text: str) -> dict[str, str]:
    """→ {结果变量名: 源表达式}（`map <源> <$结果> { … }` —— map 头是**块头**不是指令）。"""
    out: dict[str, str] = {}
    for _path, block in walk(parse_nginx(text)):
        if not block.header.startswith("map "):
            continue
        parts = block.header.split()
        if len(parts) >= 3 and parts[2].startswith("$"):
            out[parts[2][1:]] = parts[1]
    return out


def map_entries(text: str) -> dict[str, list[str]]:
    """→ {结果变量名: [该 map 的条目原文, …]}（`default …;` 与 `~regex …;`）。"""
    out: dict[str, list[str]] = {}
    for _path, block in walk(parse_nginx(text)):
        if not block.header.startswith("map "):
            continue
        parts = block.header.split()
        if len(parts) >= 3 and parts[2].startswith("$"):
            out[parts[2][1:]] = list(block.directives)
    return out


def proxied_locations(text: str) -> set[tuple[str, str]]:
    """→ 带 `proxy_pass` 的 (域名, location 头) 集（= 动态面；判据 3 的另一半）。"""
    out: set[tuple[str, str]] = set()
    for domain, server in _servers(parse_nginx(text)).items():
        for target, location in _locations(server).items():
            if any(d.startswith("proxy_pass ") for d in location.directives):
                out.add((domain, target))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据本体（纯函数：吃配置文本 → 产出问题清单；注入式红证直接喂变异文本）
# ══════════════════════════════════════════════════════════════════════════════


def problems(text: str, page_cost: int, worker_scan_cost: int) -> list[str]:
    """配置文本 → 问题清单（空 = 全部判据通过）。**唯一口径**：主判据与注入式红证都走它。"""
    bad: list[str] = []

    got_zones = zones_of(text)
    for name, want in DOCUMENTED_ZONES.items():
        live = got_zones.get(name)
        if live is None:
            bad.append(f"zone `{name}` 不在配置里（预期 key={want['key']} rate={want['rate']}）")
            continue
        for field in ("key", "rate", "size"):
            if live[field] != want[field]:
                bad.append(f"zone `{name}` 的 {field} 变了：配置={live[field]!r} 文档={want[field]!r}")
    extra = sorted(set(got_zones) - set(DOCUMENTED_ZONES))
    if extra:
        bad.append(f"配置里有未登记的 zone：{extra}（新增 zone 必须同步本文件的文档表）")

    top = " | ".join(http_level(text))
    if "limit_req_status 429" not in top:
        bad.append("顶层缺 `limit_req_status 429`（默认 503「服务不可用」会把人引向错误的排查方向）")
    if "limit_req_log_level warn" not in top:
        bad.append("顶层缺 `limit_req_log_level warn`（被拦的请求必须在日志里看得见）")

    got_limits = limits_of(text)
    for where, want in DOCUMENTED_LIMITS.items():
        live = got_limits.get(where)
        if live != want:
            bad.append(f"{where[0]}{where[1]} 的限流表变了：配置={live} 文档={want}")
    for where in sorted(set(got_limits) - set(DOCUMENTED_LIMITS)):
        bad.append(f"{where[0]}{where[1]} 挂了未登记的限流：{got_limits[where]}")

    # 判据 3：限流 ⟺ 动态（带 proxy_pass）—— 两个方向都判
    limited = set(got_limits)
    proxied = proxied_locations(text)
    for where in sorted(limited - proxied):
        bad.append(f"{where[0]}{where[1]} 不是动态面却挂了限流（静态/跳转面不该限流）")
    for where in sorted(proxied - limited):
        if where in STATIC_NO_LIMIT:
            continue  # 已登记的静态/前端面（带理由：一次页面加载要取几十个静态文件）
        bad.append(f"{where[0]}{where[1]} 是动态面（有 proxy_pass）却没有限流，也没有登记为静态面")

    # 判据 3b：文档化的静态面必须真的没有限流（显式列一遍，红证要能单独命中它）
    for where, why in STATIC_NO_LIMIT.items():
        if where in got_limits:
            bad.append(f"{where[0]}{where[1]} 被挂上了限流（{why}）⇒ 正常页面加载会被打断")

    # 判据 5：工人短链只吃「很宽」的 per-IP 档，不许吃通用档（10 r/s 会误伤一个班次）
    short_link = got_limits.get(("app.migaozn.com", "/s/"), {})
    if "api_perip" in short_link:
        bad.append("`/s/` 挂上了 api_perip（10 r/s）—— 车间一个班次共用一个出口 IP，会误伤扫码")
    if short_link.get("worker_entry", 0) < _HEADROOM_FACTOR:
        bad.append(f"`/s/` 的 worker_entry burst 太小：{short_link.get('worker_entry')}")

    # 判据 6：阈值仍压得住**重算**出来的实测用量（≥10×）
    worker_total = worker_scan_cost + len(_WORKER_PAGE_LOAD_ENDPOINTS)
    headroom_cases = {
        ("api.migaozn.com", "/", "api_perip"): page_cost,
        ("api.migaozn.com", "/", "auth_perip"): 1,
        ("api.migaozn.com", "/", "abuse_perip"): 1,
        ("api.migaozn.com", "/", "worker_sess"): worker_total,
        ("api.migaozn.com", "/", "worker_entry"): 1,
        ("app.migaozn.com", "/api/", "worker_sess"): worker_total,
        ("app.migaozn.com", "/s/", "worker_entry"): 1,
    }
    for (domain, target, zone), cost in headroom_cases.items():
        burst = got_limits.get((domain, target), {}).get(zone)
        if burst is None:
            continue  # 缺失已由上面的表相等判据报出
        need = _HEADROOM_FACTOR * cost
        if burst < need:
            bad.append(
                f"{domain}{target} 的 zone `{zone}` burst={burst} < {_HEADROOM_FACTOR}× 实测用量 "
                f"({cost}) = {need} —— 余量不足会打断正常使用"
            )
    return bad


# ══════════════════════════════════════════════════════════════════════════════
# 三、从**源码**重算「正常用量」（判据 6 的输入；锚点消失 ⇒ 红，不许抄死数）
# ══════════════════════════════════════════════════════════════════════════════


def max_parallel_api_wave(app_dir: Path = ADMIN_WEB_APP_DIR) -> tuple[int, str]:
    """→ (最大并发 API 波, 出处)。扫 `Promise.all/allSettled([...])` 里 `<x>Api.<m>(` 的个数。"""
    best = (0, "")
    for path in sorted(app_dir.rglob("*.tsx")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"Promise\.(?:all|allSettled)\(\s*\[", source):
            index = match.end()
            depth = 1
            while index < len(source) and depth > 0:
                if source[index] == "[":
                    depth += 1
                elif source[index] == "]":
                    depth -= 1
                index += 1
            calls = len(re.findall(r"[A-Za-z]+Api\.[A-Za-z]+\(", source[match.end():index - 1]))
            if calls > best[0]:
                line = source[: match.start()].count("\n") + 1
                best = (calls, f"{path.relative_to(REPO_ROOT).as_posix()}:{line}")
    return best


def measured_page_cost() -> tuple[int, str, list[str]]:
    """→ (一次最重页面加载的动态请求数, 出处, 锚点缺失清单)。3 个单例由现场锚点钉住。"""
    wave, where = max_parallel_api_wave()
    missing: list[str] = []
    for rel, anchor in _SINGLETON_ANCHORS:
        if anchor not in (REPO_ROOT / rel).read_text(encoding="utf-8"):
            missing.append(f"{rel} 里找不到锚点 {anchor!r}")
    return wave + _SINGLETON_COST, where, missing


def measured_worker_scan_cost() -> tuple[int, list[str]]:
    """→ (一次扫码的请求数, 缺失锚点)。按 `api.mjs` 里的端点字面量数，不追调用图。"""
    rel, endpoints = _WORKER_SCAN_ENDPOINTS
    source = (REPO_ROOT / rel).read_text(encoding="utf-8")
    missing = [f"{rel} 里找不到端点 {ep!r}" for ep in endpoints if ep not in source]
    for ep in _WORKER_PAGE_LOAD_ENDPOINTS:
        if ep not in source:
            missing.append(f"{rel} 里找不到端点 {ep!r}")
    return len(endpoints), missing


# ══════════════════════════════════════════════════════════════════════════════
# 四、判据
# ══════════════════════════════════════════════════════════════════════════════


def test_rate_limit_config_is_intact() -> None:
    """主判据：配置文本 → 问题清单必须为空（问题清单本身由注入式红证证明不是空转）。"""
    text = NGINX_CONF.read_text(encoding="utf-8")
    page_cost, where, missing = measured_page_cost()
    scan_cost, worker_missing = measured_worker_scan_cost()
    print(
        f"[读数] 最重页面动态请求={page_cost}（出处 {where}）；一次扫码请求数={scan_cost}；"
        f"zone 数={len(zones_of(text))}；挂限流的 location 数={len(limits_of(text))}"
    )
    assert missing == [], f"'正常用量'的现场锚点消失（常量已过期，必须重新推导）：{missing}"
    assert worker_missing == [], f"工人端端点锚点消失：{worker_missing}"
    assert page_cost >= _SINGLETON_COST + 1, (
        f"并发波扫描结果为 {page_cost - _SINGLETON_COST} ⇒ 扫描器可能扫错了对象，本判据会退化成空跑"
    )
    assert scan_cost >= 2, f"扫码请求数扫出 {scan_cost} ⇒ 扫错了对象"
    found = problems(text, page_cost, scan_cost)
    assert found == [], "nginx 限流配置与文档表不符：\n" + "\n".join(f"  · {item}" for item in found)


def test_zone_keys_are_maps_and_raw_header_keys_are_bounded() -> None:
    """zone 的 key 必须由 `map` 产生（空 key 不计账 = 分档隔离的前提）；
    且**以请求头为源**的 map 必须带形态正则 —— 否则畸形/超长头会撑爆共享内存（那是 503，不是 429）。"""
    text = NGINX_CONF.read_text(encoding="utf-8")
    got_zones = zones_of(text)
    assert len(got_zones) == len(DOCUMENTED_ZONES), f"zone 数不对：{sorted(got_zones)}"
    maps = maps_of(text)
    entries = map_entries(text)
    for name, live in sorted(got_zones.items()):
        key = live["key"]
        assert key.startswith("$"), f"zone `{name}` 的 key 不是变量：{key!r}"
        assert key[1:] in maps, f"zone `{name}` 的 key {key} 不是任何 map 的结果变量（分档前提不成立）"
        assert any(item.startswith("default ") for item in entries[key[1:]]), (
            f"map `{key[1:]}` 没有 default 条目 ⇒ 未命中时取不到值"
        )
    for target, source in sorted(maps.items()):
        if not source.startswith("$http_"):
            continue
        regex_entries = [item for item in entries[target] if item.lstrip(chr(34) + chr(39)).startswith("~")]
        assert regex_entries, (
            f"map `{target}` 直接吃请求头 {source} 且没有形态正则 ⇒ 伪造的头会长出任意 key、撑爆共享内存"
        )


def test_real_config_has_no_limiter_on_static_surfaces() -> None:
    """静态面（工人端 `/w/` 与 admin-web 的 JS/CSS）**一个限流都不许有**。"""
    text = NGINX_CONF.read_text(encoding="utf-8")
    got = limits_of(text)
    for where, why in STATIC_NO_LIMIT.items():
        assert where not in got, f"{where[0]}{where[1]} 挂上了限流：{got.get(where)}（{why}）"
    servers = _servers(parse_nginx(text))
    root_location = _locations(servers["app.migaozn.com"])["/"]
    assert "try_files" in " ".join(root_location.directives), (
        "app.migaozn.com 的 `location /` 不再是静态 try_files 形态 ⇒ 本判据的对象变了，先核对再改"
    )


# ── 注入式红证（本文件内真跑：改**文本**喂给同一套判据，必须被检出并指名）──────────────


def _live_text() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


def _inject(text: str, needle: str, replacement: str) -> str:
    assert needle in text, f"注入点定位失败（fail-closed）：找不到 {needle!r}"
    mutated = text.replace(needle, replacement, 1)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    return mutated


def test_red_proof_removing_a_zone_is_detected() -> None:
    """红证①：把 `worker_entry` 的 zone 定义整行删掉 ⇒ 判据必须报出该 zone 缺失。"""
    text = _live_text()
    needle = "limit_req_zone $worker_entry_key  zone=worker_entry:10m rate=50r/s;"
    mutated = _inject(text, needle, "")
    page_cost, _where, _missing = measured_page_cost()
    scan_cost, _missing2 = measured_worker_scan_cost()
    found = problems(mutated, page_cost, scan_cost)
    assert any("worker_entry" in item and "不在配置里" in item for item in found), (
        f"删掉 zone 定义后判据没指名它：{found}"
    )


def test_red_proof_gutting_a_burst_is_detected() -> None:
    """红证②：把 `/s/` 的 burst 从 1000 砍到 1 ⇒ 判据必须报出余量不足（车间扫码会被打断）。"""
    text = _live_text()
    needle = "location /s/ {\n        limit_req zone=worker_entry burst=1000 nodelay;"
    mutated = _inject(text, needle, needle.replace("burst=1000", "burst=1"))
    page_cost, _where, _missing = measured_page_cost()
    scan_cost, _missing2 = measured_worker_scan_cost()
    found = problems(mutated, page_cost, scan_cost)
    assert any("/s/" in item and "余量不足" in item for item in found), f"砍 burst 后判据没报出：{found}"


def test_red_proof_throttling_static_surface_is_detected() -> None:
    """红证③：给工人端静态 `location /` 加一条限流 ⇒ 判据必须报出「静态面不该限流」。"""
    text = _live_text()
    mutated = _inject(text, "    location / {\n        try_files $uri $uri/ /index.html;\n    }",
                      "    location / {\n        limit_req zone=api_perip burst=5 nodelay;\n"
                      "        try_files $uri $uri/ /index.html;\n    }")
    page_cost, _where, _missing = measured_page_cost()
    scan_cost, _missing2 = measured_worker_scan_cost()
    found = problems(mutated, page_cost, scan_cost)
    assert any("静态/跳转面不该限流" in item or "挂上了限流" in item for item in found), (
        f"给静态面加限流后判据没报出：{found}"
    )


def test_red_proof_raised_page_cost_tightens_the_requirement() -> None:
    """红证④：把「实测用量」抬高 20 倍（模拟页面长大）⇒ 现有 burst 必须被判不足。"""
    text = _live_text()
    page_cost, _where, _missing = measured_page_cost()
    scan_cost, _missing2 = measured_worker_scan_cost()
    found = problems(text, page_cost * 20, scan_cost)
    assert any("api_perip" in item and "余量不足" in item for item in found), (
        f"实测用量涨上去后限流没有跟着被判不足（说明余量判据与读数无关）：{found}"
    )
