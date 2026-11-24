# case_ids: MC-351
"""M1-a/M1-b 零停机切换 + 优雅退出的守卫（issue #9098）。

## 这两项要解决的**具体**失败形态（不是「不够优雅」）

M1-a（切换模型）：发布成功路径写的是 `docker compose up -d --no-deps "$svc"`
（`deploy/swas/deploy.sh` 的 2.5 段）——compose 的**替换**语义 = 停旧 → 删旧 → 建新 → 起新
⇒ 从停旧到新容器 healthy 之间**没有进程在服务**；nginx 的 `proxy_pass http://admin-api:8080`
把 compose DNS 的结果缓存在 worker 里 ⇒ 重建换 IP 后再 `nginx -s reload` 才恢复
（生产实测窗口 **90s**，`deploy/swas/deploy.sh` 的 `nginx_expect_upstream_ok` 就是为此而写）。
严格蓝绿预验证（#4785）只把**失败路径**打到 0；**成功路径**的窗口一直在。

M1-b（优雅退出）：Spring 默认 `server.shutdown=immediate`、uvicorn 默认 graceful 窗口很短，
而 docker 的 `stop` 在 `stop_grace_period`（默认 **10s**）后直接 `SIGKILL`
⇒ 在途请求 / 正在生成的 SSE 流被硬切，客户端看到「回答说到一半没了」。

## 本文件锁什么（每条都能单独变红）

1. **upstream 形态**：`deploy/swas/nginx.conf` 里必须有三个 upstream
   （`migao_admin_api` / `migao_ai_agent` / `migao_admin_web`），成员用
   **容器名:容器内端口**（8080/8000/3001）；`proxy_pass` **一律指 upstream 名**，
   不得再出现 `proxy_pass http://admin-api:8080` 这类**服务名直连**（那正是 502 的来源）。
   ⚠️ 稳态**只写现行实例一条成员**（不是两条）：nginx 在**解析配置时**就对 upstream 服务名做
   DNS 解析，green 容器没跑时写它的名字 ⇒ `[emerg] host not found in upstream` ⇒ **全站起不来**。
   「切换后每个 upstream 恰有两个后端」由**行为判据**证明（见第 4 条：真跑改写器）。
2. **渲染不退化**：`MIGAO_PUBLIC_DOMAIN` 那份整文件 `sed` 渲染后 `server_name` 必须仍是站点域
   （既有的 #8966 断言不许被本改动带坏），且 upstream 块**不参与**域名替换。
3. **切换顺序（顺序即安全顺序）**：`deploy.sh` 的 2.5 段必须是
   green 起 → green 健康 → 迁移闸门 → **只切 upstream**（`nginx -t` + reload）→ 入口 200 断言
   → **drain**（等旧 worker 收尾）→ **现在才**重建正式容器 → 入口切回正式容器 → 删 green。
   判据把**行号**打出来（点名而不是「大体上有」）。
   🔴 **红证**：把切换改回「`docker compose up -d` 重建 + reload」⇒ 判据红（见注入式红证）。
4. **改写器是行为判据**（不是数行数）：从 `deploy.sh` 抽出那段 python 改写器，在真实
   `nginx.conf` 的副本上跑 ⇒ 三个服务切换后**各有两个后端**（green 主 + 正式 backup）、
   切回后与原文**逐字节一致**（幂等、可回退）；未知 upstream / 标记缺失 ⇒ 非零退出且**文件不动**。
5. **优雅退出必须在「实际生效位置」**：`application.yml` 的 `server.shutdown: graceful` +
   `spring.lifecycle.timeout-per-shutdown-phase`（有值且与理由一致）；ai-agent **启动命令**
   含 `--timeout-graceful-shutdown`（`Dockerfile` 的 CMD，且 compose **没有**用 `command:`
   覆盖掉它 —— 覆盖了那个 flag 就是死配置）；两侧 compose 的 `stop_grace_period` 必须
   **≥ 应用自己的优雅退出预算**（否则 docker 默认 10s 就 SIGKILL，应用配多少都没用）。
6. **文档同步**：`docs/deployment/zero-downtime-release.md` 的 M1-a / M1-b 必须从「缺口」
   改成「已实施 + 怎么验证」，并留**真实读数占位**；占位没填就必须标记为未实测
   （不许把「配好了」写成「已验证」）。

## 边界（照实登记）

- 本文件**不执行** `deploy.sh`、不连 docker、不连测试/生产环境 ⇒ 它证的是
  「配置与切换顺序是零停机形态」，**不证**「线上这次发布真的零 5xx」——后者是 ADR 里
  「真机读数」表（本 PR 未填，需要测试环境通道）与 M2-d 的观测面。
- 真机事实：生产/测试的 nginx 跑在**容器**里（`migao-deploy-nginx-1`），宿主没有 nginx 二进制、
  没有 `/etc/nginx` ⇒ 本文档/脚本里一切 reload 都走 `docker compose exec -T nginx nginx -s reload`。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # tests/ ⇒ `unit_ci_workflows` 可导入
from unit_ci_workflows.injection import inject  # noqa: E402

NGINX = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
DEPLOY = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
COMPOSE = REPO_ROOT / "deploy" / "swas" / "docker-compose.yml"
COMPOSE_BG = REPO_ROOT / "deploy" / "swas" / "docker-compose.bluegreen.yml"
APPLICATION_YML = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "application.yml"
AI_AGENT_DOCKERFILE = REPO_ROOT / "backend" / "ai-agent-service" / "Dockerfile"
AI_AGENT_MAIN = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "main.py"
AI_AGENT_PROBE_TEST = REPO_ROOT / "backend" / "ai-agent-service" / "tests" / "test_stream_probe.py"
AI_AGENT_PROBE_LEDGER = REPO_ROOT / "backend" / "ai-agent-service" / "tests" / "test_llm_health.py"
PROBE_PATH = "/internal/stream-probe"
#: 探针 handler 里**不许出现**的符号（写库 / LLM / 会话存储 / 外部服务调用）——
#: 只读探针一旦带上写面，就再也不能在发布期反复跑（那正是本端点存在的理由）。
PROBE_FORBIDDEN = (
    "AsyncSession", "SessionService", "SessionStateStore", "get_db", "LLMFactory",
    "openai", "langchain", "admin_api", ".commit(", ".execute(", ".insert(", ".update(",
)
DOC = REPO_ROOT / "docs" / "deployment" / "zero-downtime-release.md"

#: 服务 → (upstream 名, 容器内端口)。端口 = **容器端口**（宿主第二端口 18080/18000/13001 只在宿主侧）。
UPSTREAMS: dict[str, tuple[str, int]] = {
    "admin-api": ("migao_admin_api", 8080),
    "ai-agent": ("migao_ai_agent", 8000),
    "admin-web": ("migao_admin_web", 3001),
}
#: 宿主侧第二端口 —— 出现在 upstream 成员里就是错的（nginx 在容器里，连不到宿主 127.0.0.1）。
HOST_SECOND_PORTS = {18080, 18000, 13001}
MEMBER_BEGIN = ">>> migao-upstream-members"
MEMBER_END = "<<< migao-upstream-members"

#: SSE 最长流时长（`backend/ai-agent-service/app/api/chat.py` 的 `stream_timeout=180`）——
#: ai-agent 的优雅退出预算必须 **≥** 它，否则「切换期流不断」是假的。
SSE_MAX_SECONDS = 180

_MEMBER_RE = re.compile(r"^server\s+([A-Za-z0-9_.-]+):(\d+)\b([^;]*);")
_UPSTREAM_RE = re.compile(r"^upstream\s+([A-Za-z0-9_]+)\s*\{\s*$")


# ══════════════════════════════════════════════════════════════════════════
# 读源 + 反空跑锚点
# ══════════════════════════════════════════════════════════════════════════

def read(path: Path) -> str:
    assert path.is_file(), f"反空跑锚点：目标文件不存在 → {path}"
    return path.read_text(encoding="utf-8")


def read_nginx() -> str:
    text = read(NGINX)
    assert "proxy_pass http://migao_admin_api;" in text, (
        "反空跑锚点：nginx.conf 里找不到 `proxy_pass http://migao_admin_api;`"
        "（判据已过期，或 upstream 改动没落地）"
    )
    return text


def read_deploy() -> str:
    text = read(DEPLOY)
    assert "== 2.5 严格蓝绿预验证" in text, "反空跑锚点：deploy.sh 里找不到蓝绿段（判据已过期）"
    return text


# ══════════════════════════════════════════════════════════════════════════
# 解析：upstream 块 / 成员 / 渲染（纯函数：文本进 → 结构出）
# ══════════════════════════════════════════════════════════════════════════

def upstream_blocks(text: str) -> dict[str, list[str]]:
    """`{upstream 名: 块内行}`。块 = `upstream <名> {` 到列首 `}`。"""
    out: dict[str, list[str]] = {}
    name: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if name is None:
            m = _UPSTREAM_RE.match(line.strip())
            if m:
                name, body = m.group(1), []
            continue
        if line.strip() == "}":
            out[name] = body
            name = None
            continue
        body.append(line)
    return out


def members_of(body: list[str]) -> list[tuple[str, int, str]]:
    """块内的 `server host:port flags;` 成员 → [(host, port, flags)]。"""
    out: list[tuple[str, int, str]] = []
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _MEMBER_RE.match(stripped)
        if m:
            out.append((m.group(1), int(m.group(2)), m.group(3).strip()))
    return out


def active_members(body: list[str]) -> list[tuple[str, int, str]]:
    """非 `backup` 成员（稳态应该恰好 1 个）。"""
    return [m for m in members_of(body) if "backup" not in m[2].split()]


def proxy_pass_targets(text: str) -> list[str]:
    """所有 `proxy_pass http://<host>[:port][/path];` 的 host[:port] 部分（按出现顺序）。"""
    # ⚠️ 必须带结尾 `;`：注释里也写着 `proxy_pass http://admin-api:8080` 这类**事故说明**，
    #    不带 `;` 就会把说明文字当成"仍然直连"（判据自身缺陷 ⇒ 恒红）。
    return re.findall(r"proxy_pass\s+http://([^/;\s]+)\s*;", text)


def render_domain(text: str, domain: str) -> str:
    """**与 deploy.sh 同一份**渲染：整文件 `sed s/migaozn\\.com/<domain>/g`。

    同一份 = 判据先从 deploy.sh 里确认那条 sed 还在（`sed "s/migaozn\\.com/${MIGAO_PUBLIC_DOMAIN}/g"`），
    而不是另写一套渲染语义（两套语义 = 判据测的是「我以为的渲染」）。
    """
    deploy = read_deploy()
    assert 'sed "s/migaozn\\.com/${MIGAO_PUBLIC_DOMAIN}/g"' in deploy, (
        "deploy.sh 的域名渲染不再是「整文件 sed s/migaozn\\.com/…/g」⇒ 本判据的渲染语义已过期，"
        "请同步本文件（不许在判据里另造一套渲染）"
    )
    return text.replace("migaozn.com", domain)


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（文本进 → 违规清单出；注入式红证驱动**同一份本体**）
# ══════════════════════════════════════════════════════════════════════════

def _count_contains(lines: list[str], needle: str) -> int:
    """含 `needle` 的行数（`list.count()` 比的是**元素相等**，不是子串 —— 用它会把判据写成空断言）。"""
    return sum(1 for line in lines if needle in line)


def judge_upstream_shape(text: str) -> list[str]:
    """判据 1：三个 upstream 存在 + 成员是容器名:容器端口 + proxy_pass 只指 upstream 名。"""
    bad: list[str] = []
    blocks = upstream_blocks(text)
    for svc, (name, port) in UPSTREAMS.items():
        body = blocks.get(name)
        if body is None:
            bad.append(f"nginx.conf 缺 `upstream {name}`（{svc} 的流量没有摘挂面）")
            continue
        actives = active_members(body)
        if len(actives) != 1:
            bad.append(
                f"`upstream {name}` 的**非 backup** 成员是 {len(actives)} 个（稳态必须恰好 1 个）："
                f"{actives} —— green 没在跑时写它的名字 ⇒ `[emerg] host not found in upstream` ⇒ 全站起不来"
            )
            continue
        host, mport, flags = actives[0]
        if host != svc:
            bad.append(f"`upstream {name}` 的成员是 `{host}`，应为现行实例容器名 `{svc}`")
        if mport != port:
            hint = "（宿主第二端口！nginx 在容器里连不到宿主的 127.0.0.1）" if mport in HOST_SECOND_PORTS else ""
            bad.append(f"`upstream {name}` 的成员端口是 {mport}，应为**容器内端口** {port}{hint}")
        if "max_fails" not in flags:
            bad.append(f"`upstream {name}` 的成员缺 `max_fails`（坏成员要能被摘掉，而不是一直分到流量）")
        if _count_contains(body, MEMBER_BEGIN) != 1 or _count_contains(body, MEMBER_END) != 1:
            bad.append(
                f"`upstream {name}` 缺成员标记（`# {MEMBER_BEGIN}` / `# {MEMBER_END}` 各要恰好 1 处）"
                " —— deploy.sh 的改写器按标记替换成员行"
            )
    # upstream 必须在 http 上下文（本文件的 http 上下文 = 第一个 server 块之前）
    first_server = text.find("\nserver {")
    if first_server < 0:
        bad.append("nginx.conf 里找不到 `server {`（判据已过期）")
    else:
        for name in blocks:
            if text.find(f"upstream {name} {{") > first_server:
                bad.append(f"`upstream {name}` 写在 server 块**之后** ⇒ 不在 http 上下文（nginx 会拒绝启动）")

    targets = proxy_pass_targets(text)
    allowed = {name for name, _ in UPSTREAMS.values()}
    direct = [t for t in targets if t.split(":")[0] in UPSTREAMS or t.split(":")[0] in {"admin-api", "ai-agent", "admin-web"}]
    if direct:
        bad.append(
            f"仍有**服务名直连**的 proxy_pass：{sorted(set(direct))} —— 那正是「重建容器 = 换 IP = 502」的来源；"
            "必须写 `proxy_pass http://<upstream 名>;`"
        )
    unknown = [t for t in targets if t not in allowed]
    if unknown:
        bad.append(f"proxy_pass 指向了未登记的 host：{sorted(set(unknown))}（允许的 upstream 名：{sorted(allowed)}）")
    if len(targets) < len(UPSTREAMS):
        bad.append(f"proxy_pass 只有 {len(targets)} 处 ⇒ 有面没接到 upstream 上（判据已过期？）")

    m = re.search(r"^worker_shutdown_timeout\s+(\d+)s;", text, re.MULTILINE)
    if not m:
        bad.append("nginx.conf 缺 `worker_shutdown_timeout`（reload 时旧 worker 的兜底上限）")
    elif int(m.group(1)) < SSE_MAX_SECONDS:
        bad.append(
            f"`worker_shutdown_timeout {m.group(1)}s` < SSE 最长流 {SSE_MAX_SECONDS}s ⇒ 切换期会把长流切断"
        )
    return bad


def judge_rendered(canonical: str, domain: str = "cytda.com") -> list[str]:
    """判据 2：渲染后 `server_name` 仍是站点域，upstream 块不参与域名替换。"""
    bad: list[str] = []
    rendered = render_domain(canonical, domain)
    names = re.findall(r"^\s*server_name\s+(.+);", rendered, re.MULTILINE)
    if not names:
        bad.append("渲染产物里一行 `server_name` 都没有（渲染逻辑被带坏了？）")
    else:
        if f"server_name api.{domain};" not in rendered:
            bad.append(
                f"渲染后 `server_name` 里没有站点域 {domain} 的 **api 面**（`server_name api.{domain};`）：{names}"
            )
        joined = " ".join(names)
        if domain not in joined:
            bad.append(f"渲染后 `server_name` 里没有站点域 {domain}：{names}")
        if "migaozn.com" in rendered:
            bad.append("渲染后仍残留测试域 `migaozn.com`（#8966 的断言会判失败）")
    if upstream_blocks(rendered).keys() != upstream_blocks(canonical).keys():
        bad.append("渲染改变了 upstream 块集合（upstream 名不该含域名）")
    for name, body in upstream_blocks(canonical).items():
        if members_of(body) != members_of(upstream_blocks(rendered).get(name, [])):
            bad.append(f"渲染改变了 `upstream {name}` 的成员（成员不该含域名）")
    return bad


def _loop_region(text: str) -> tuple[int, int]:
    """2.5 的 per-service 切换循环区间（`for svc in $UP_SERVICES; do` → 2.5.9 分节线）。"""
    start = text.find("for svc in $UP_SERVICES; do")
    assert start >= 0, "反空跑锚点：deploy.sh 里找不到 `for svc in $UP_SERVICES; do`"
    end = text.find("2.5.9 JWT 验签同源硬断言", start)
    assert end > start, "反空跑锚点：找不到 2.5.9 分节线（切换循环的边界）"
    return start, end


def _lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def judge_cutover_sequence(text: str) -> tuple[list[str], dict[str, int]]:
    """判据 3：切换顺序 + 「正式容器不在窗口期重建」。返回 (违规清单, 行号读数)。"""
    bad: list[str] = []
    start, end = _loop_region(text)
    region = text[start:end]

    def find(pattern: str, label: str) -> int:
        i = region.find(pattern)
        if i < 0:
            bad.append(f"切换循环里找不到「{label}」（`{pattern}`）")
            return -1
        return start + i

    p_green = find('$BG_COMPOSE up -d --no-deps "$GREEN"', "green 起来")
    p_hc = find('wait_healthy "$GPORT" "$GREEN" "$GPATH"', "green 健康检查")
    p_switch = find('nginx_upstream_switch "$svc" green', "只切 upstream 到 green")
    p_entry = find('nginx_expect_upstream_ok "${svc} 切到 green 后"', "切到 green 后的入口 200 断言")
    p_drain = find('upstream_drain_wait "$svc"', "drain（等旧 worker 收尾）")
    p_canon = find('docker compose up -d --no-deps "$svc"', "正式容器重建")
    p_back = find('nginx_upstream_switch "$svc" formal', "把 upstream 切回正式容器")

    readings = {
        "green 起": _lineno(text, p_green) if p_green >= 0 else -1,
        "green 健康": _lineno(text, p_hc) if p_hc >= 0 else -1,
        "切 upstream→green": _lineno(text, p_switch) if p_switch >= 0 else -1,
        "入口 200 断言": _lineno(text, p_entry) if p_entry >= 0 else -1,
        "drain": _lineno(text, p_drain) if p_drain >= 0 else -1,
        "重建正式容器": _lineno(text, p_canon) if p_canon >= 0 else -1,
        "切 upstream→正式": _lineno(text, p_back) if p_back >= 0 else -1,
    }

    if all(p >= 0 for p in (p_green, p_hc, p_switch, p_entry, p_drain, p_canon, p_back)):
        ordered = [p_green, p_hc, p_switch, p_entry, p_drain, p_canon, p_back]
        if ordered != sorted(ordered):
            pairs = list(readings.items())
            bad.append(
                "切换顺序不是「顺序即安全顺序」——期望 green起 < green健康 < 切upstream < 入口200 < drain "
                f"< 重建正式容器 < 切回正式容器；实测行号：{pairs}"
            )
    # 「重建正式容器」必须**恰好 1 次**（应急开关不许跳过它，也不许有两处重建）
    recreate_count = region.count('docker compose up -d --no-deps "$svc"')
    if recreate_count != 1:
        bad.append(
            "切换循环里 `docker compose up -d --no-deps \"$svc\"` 出现 "
            f"{recreate_count} 次（必须恰好 1 次：重建在流量切走之后）"
        )
    # 切 upstream 失败 ⇒ 不重建、不删 green 以外的东西、exit 1（旧容器继续服务）
    m = re.search(r'if \[ "\$SWITCH_RC" != "0" \]; then(.*?)\n  fi\n', region, re.S)
    if not m:
        bad.append("找不到「upstream 切换失败」的分支（`if [ \"$SWITCH_RC\" != \"0\" ]`）")
    else:
        blk = m.group(1)
        if "exit 1" not in blk:
            bad.append("upstream 切换失败的分支没有 `exit 1`（失败会被当成成功继续往下重建）")
        if 'docker compose up -d --no-deps "$svc"' in blk:
            bad.append("upstream 切换失败的分支里仍在重建正式容器（= 窗口还在）")
    # 切回失败 ⇒ 不许删 green（它正承载流量）
    m = re.search(r"if ! nginx_upstream_switch \"\$svc\" formal; then(.*?)\n  fi\n", region, re.S)
    if not m:
        bad.append("找不到「切回正式容器」的失败分支")
    else:
        if "exit 1" not in m.group(1):
            bad.append("「切回正式容器」失败的分支没有 `exit 1`（会走到删 green ⇒ 把唯一承载流量的实例删掉）")
    # 应急开关 / 入口不在运行 ⇒ 回落老路径（重建 + reload），且**必须**明确喊出来
    if "nginx_expect_upstream_ok \"${svc} 重建后\"" not in region:
        bad.append("缺少「未走 upstream 摘挂」时的回落断言 `nginx_expect_upstream_ok \"${svc} 重建后\"`")
    if "不是零停机" not in region:
        bad.append("回落路径没有明确说明「本次不是零停机」（静默降级 = 假绿）")
    return bad, readings


def judge_switch_function(text: str) -> list[str]:
    """判据 3b：`nginx_upstream_switch` 只改配置 + `nginx -t` + reload，**不重建/不 restart**。"""
    bad: list[str] = []
    if text.count("nginx_upstream_switch() {") != 1:
        bad.append(f"`nginx_upstream_switch()` 定义出现 {text.count('nginx_upstream_switch() {')} 次（必须恰好 1 次）")
        return bad
    start = text.find("nginx_upstream_switch() {")
    end = text.find("\n}\n", start)
    if end < 0:
        bad.append("`nginx_upstream_switch()` 没有配对的收尾 `}`")
        return bad
    body = text[start:end]
    for token, why in (
        ("nginx -t", "切换前必须 `nginx -t`（写坏的配置不许 reload 进场）"),
        ("nginx -s reload", "切换动作必须是 reload（优雅：旧 worker 把在途请求做完）"),
        ("cp -f", "必须备份一份再改（回退要能秒级完成）"),
        ('docker compose ps -q nginx', "必须检查 nginx 在运行（入口不在时无从 reload）"),
    ):
        if token not in body:
            bad.append(f"`nginx_upstream_switch()` 缺 `{token}`：{why}")
    for forbidden, why in (
        ("docker compose up -d", "切换面**不许**重建任何容器（那就是窗口本身）"),
        ("docker compose restart", "切换面**不许** restart（硬重启 = 当场丢弃在途连接）"),
    ):
        if forbidden in body:
            bad.append(f"`nginx_upstream_switch()` 里出现 `{forbidden}`：{why}")
    # 恢复动作：任一失败分支都要把备份拷回去
    if body.count("cp -f") < 2:
        bad.append("`nginx_upstream_switch()` 的失败分支没有把备份拷回（改了配置却不回退 = 入口留在坏形态）")
    if "return 3" not in body:
        bad.append("`nginx_upstream_switch()` 没有「入口不在运行 ⇒ 回落重建路径」的三态出口（return 3）")
    return bad


def judge_graceful(
    app_text: str,
    dockerfile_text: str,
    compose_text: str,
    compose_bg_text: str,
) -> list[str]:
    """判据 5：优雅退出三处同时成立（应用 / 启动命令 / stop_grace_period）。"""
    bad: list[str] = []
    app = yaml.safe_load(app_text)
    server = (app or {}).get("server") or {}
    spring = (app or {}).get("spring") or {}
    if server.get("shutdown") != "graceful":
        bad.append(
            "application.yml 的 `server.shutdown` 不是 `graceful`"
            f"（实测 {server.get('shutdown')!r}）⇒ SIGTERM 时在途请求被硬切"
        )
    phase = ((spring.get("lifecycle") or {}).get("timeout-per-shutdown-phase"))
    if not phase:
        bad.append("application.yml 缺 `spring.lifecycle.timeout-per-shutdown-phase`（优雅退出的时间预算）")
    else:
        seconds = _duration_seconds(phase)
        if seconds is None or seconds < 10:
            bad.append(f"`timeout-per-shutdown-phase: {phase!r}` 不是 ≥10s 的合法时长（预算太短 = 退化成硬切）")

    cmd = re.search(r'^CMD\s+(\[.*\])\s*$', dockerfile_text, re.MULTILINE)
    if not cmd:
        bad.append("ai-agent Dockerfile 里找不到 exec 形态的 `CMD [...]`（判据已过期）")
        ai_budget = None
    else:
        argv = yaml.safe_load(cmd.group(1))
        if "--timeout-graceful-shutdown" not in argv:
            bad.append(
                "ai-agent 的**启动命令**没有 `--timeout-graceful-shutdown`"
                f"（实测 CMD={argv}）⇒ SIGTERM 时正在生成的 SSE 流被切断"
            )
            ai_budget = None
        else:
            ai_budget = _duration_seconds(argv[argv.index("--timeout-graceful-shutdown") + 1])
            if ai_budget is None or ai_budget < SSE_MAX_SECONDS:
                bad.append(
                    f"`--timeout-graceful-shutdown {ai_budget}` < SSE 最长流 {SSE_MAX_SECONDS}s"
                    " ⇒ 「切换期流不中断」是假的"
                )
    compose = yaml.safe_load(compose_text)["services"]
    compose_bg = yaml.safe_load(compose_bg_text)["services"]
    if "command" in (compose.get("ai-agent") or {}):
        bad.append("compose 用 `command:` 覆盖了 ai-agent 的启动命令 ⇒ Dockerfile 里的优雅退出参数是**死配置**")
    api_stop = _duration_seconds((compose.get("admin-api") or {}).get("stop_grace_period"))
    if api_stop is None:
        bad.append(
            "compose 的 admin-api 缺 `stop_grace_period` ⇒ docker 默认 10s 后 SIGKILL，"
            "`server.shutdown=graceful` 的预算给了也没用"
        )
    else:
        api_budget = _duration_seconds(phase) if phase else None
        if api_budget and api_stop < api_budget:
            bad.append(
                f"compose admin-api 的 `stop_grace_period` {api_stop}s < 应用预算 {api_budget}s"
                " ⇒ 优雅退出还没走完就被 SIGKILL"
            )
    ai_stop = _duration_seconds((compose.get("ai-agent") or {}).get("stop_grace_period"))
    if ai_stop is None:
        bad.append("compose 的 ai-agent 缺 `stop_grace_period`（默认 10s ⇒ SSE 必断）")
    elif ai_budget and ai_stop < ai_budget:
        bad.append(
            f"compose ai-agent 的 `stop_grace_period` {ai_stop}s < uvicorn 预算 {ai_budget}s"
            " ⇒ 长流收尾还没走完就被 SIGKILL"
        )
    # 抗漂移：green 探针与正式服务同口径（否则「预验证通过、正式容器被砍」）
    for svc in ("admin-api", "ai-agent"):
        g = compose_bg.get(f"{svc}-green") or {}
        if "stop_grace_period" in (compose.get(svc) or {}) and "stop_grace_period" not in g:
            bad.append(f"`{svc}-green` 缺 `stop_grace_period`（与正式服务不同口径 ⇒ 预验证与真跑不一致）")
        elif "stop_grace_period" in g and g.get("stop_grace_period") != (compose.get(svc) or {}).get("stop_grace_period"):
            bad.append(
                f"`{svc}-green` 的 `stop_grace_period`={g.get('stop_grace_period')!r} 与正式服务 "
                f"{(compose.get(svc) or {}).get('stop_grace_period')!r} 不一致"
            )
    return bad


def _duration_seconds(value: object) -> int | None:
    """`'30s'` / `'210s'` / `'1m'` / `30` → 秒；认不出 ⇒ None（不猜）。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    m = re.fullmatch(r"(\d+)(ms|s|m|h)?", text)
    if not m:
        return None
    n = int(m.group(1))
    return {"ms": max(1, n // 1000), None: n, "s": n, "m": n * 60, "h": n * 3600}[m.group(2)]



def _probe_region(main_text: str) -> str:
    """`app/main.py` 里 `# >>> stream-probe` / `# <<< stream-probe` 之间的实现段（夹取 + 事件生成）。"""
    begin = main_text.find("# >>> stream-probe")
    finish = main_text.find("# <<< stream-probe")
    assert begin >= 0 and finish > begin, (
        "app/main.py 里找不到 `# >>> stream-probe` / `# <<< stream-probe` 标记"
        "（判据要取这一段做静态判据，别把逻辑挪走）"
    )
    return main_text[begin:finish]


def _probe_route(main_text: str) -> str:
    """`@app.get("/internal/stream-probe")` 那个路由段（到下一个 `@app.` 为止）。"""
    start = main_text.find(f'@app.get("{PROBE_PATH}")')
    assert start >= 0, f'app/main.py 里找不到 `@app.get("{PROBE_PATH}")`'
    end = main_text.find("\n    @app.", start + 10)
    return main_text[start:end if end > 0 else len(main_text)]


def _code_lines(block: str, base_lineno: int) -> list[tuple[int, str]]:
    """(行号, 代码行)：剥掉整行注释（注释里**刻意写着**「不碰 DB / 不调 LLM」这类说明）。"""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(block.splitlines(), start=base_lineno):
        if line.lstrip().startswith("#"):
            continue
        out.append((i, line))
    return out


def judge_stream_probe(main_text: str, ledger_text: str) -> list[str]:
    """判据 7：只读流式探针（M1-b 的可重复读数面，issue #9098）。"""
    bad: list[str] = []
    region = _probe_region(main_text)
    route = _probe_route(main_text)
    for token, where, why in (
        ("Depends(verify_service_token)", "路由", "必须挂内部服务 token 鉴权（缺/错 ⇒ 401，不许匿名可达）"),
        ("_probe_limit(seconds)", "路由", "路由必须用**同一个**夹取函数（另写一份 = 两套语义）"),
        ("_probe_events(", "路由", "路由必须用**同一个**事件生成器（判据测的就是它）"),
        ("text/event-stream", "路由", "响应类型必须是 SSE"),
        ("min(int(seconds), STREAM_PROBE_MAX_SECONDS)", "实现段", "`seconds` 必须夹到上限（否则能开一条跑几小时的流）"),
        ("max(1,", "实现段", "`seconds` 必须有下限 1（0 会变成空流）"),
        ("event: notice", "实现段", "被夹取时必须**自报**（不静默）"),
        ("event: ping", "实现段", "必须真的发心跳事件"),
        ("is_disconnected", "实现段", "客户端断开必须立刻结束（否则上限时长会跑满）"),
    ):
        haystack = route if where == "路由" else region
        if token not in haystack:
            bad.append(f"`{PROBE_PATH}` 的{where}缺 `{token}`：{why}")
    for token in ("STREAM_PROBE_MAX_SECONDS = 200", "STREAM_PROBE_DEFAULT_SECONDS = 30"):
        if token not in main_text:
            bad.append(f"app/main.py 缺 `{token}`（预算必须与 nginx worker_shutdown_timeout 200s 同源）")
    for label, block in (("实现段", region), ("路由", route)):
        base = main_text[: main_text.find(block)].count("\n") + 1
        for lineno, line in _code_lines(block, base):
            for symbol in PROBE_FORBIDDEN:
                if symbol in line:
                    bad.append(
                        f"`{PROBE_PATH}` 的{label}第 {lineno} 行出现 `{symbol}`（写库 / LLM / 外部服务）"
                        " ⇒ 探针不再是只读的（发布期就不敢反复跑了）"
                    )
    if f'"{PROBE_PATH}"' not in ledger_text:
        bad.append(
            "`app/main.py` 的探针**没有登记**到 `tests/test_llm_health.py` 的 `APP_LEVEL_PROBES`"
            "（类级元守卫：每个探针都要回答「它到底探什么」）"
        )
    return bad


def judge_doc(text: str) -> list[str]:
    """判据 6：M1-a / M1-b 必须写「已实施 + 怎么验证 + 真实读数占位（未填即标未实测）」。"""
    bad: list[str] = []
    m1a = _doc_section(text, "M1-a")
    m1b = _doc_section(text, "M1-b")
    if not m1a:
        bad.append("ADR 缺 `### M1-a` 小节")
    else:
        for marker, why in (
            ("已实施", "M1-a 必须从「缺口」改成「已实施」（否则读者仍以为切换会重建容器）"),
            ("upstream migao_admin_api", "M1-a 必须点名真实 upstream 名（照抄配置，不写示例名）"),
            ("proxy_pass http://migao_admin_api", "M1-a 必须写明 proxy_pass 已指向 upstream 名"),
            ("host not found in upstream", "M1-a 必须写明「稳态只写一条成员」的原因（green 不在跑时 DNS 解析失败）"),
            ("nginx -t", "M1-a 必须给出验证命令 `nginx -t`"),
            ("nginx -s reload", "M1-a 必须给出验证命令 `nginx -s reload`"),
            ("docker exec migao-deploy-nginx-1", "M1-a 必须写清 reload 走**容器**（宿主没有 nginx 二进制）"),
            ("真机读数", "M1-a 必须留「真机读数」占位表（未实测不许写成已验证）"),
            ("待填", "M1-a 的真机读数占位必须显式写「待填」"),
        ):
            if marker not in m1a:
                bad.append(f"M1-a 缺 `{marker}`：{why}")
    if not m1b:
        bad.append("ADR 缺 `### M1-b` 小节")
    else:
        for marker, why in (
            ("已实施", "M1-b 必须从「未配置」改成「已实施」"),
            ("server.shutdown=graceful", "M1-b 必须点名 admin-api 的配置键"),
            ("spring.lifecycle.timeout-per-shutdown-phase=30s", "M1-b 必须写出**取值**（不是只说「配了」）"),
            ("--timeout-graceful-shutdown", "M1-b 必须点名 ai-agent 的启动参数"),
            ("stop_grace_period", "M1-b 必须写明 compose 的 stop_grace_period（否则 docker 默认 10s 就 SIGKILL）"),
            ("真机读数", "M1-b 必须留「真机读数」占位表"),
            ("待填", "M1-b 的真机读数占位必须显式写「待填」"),
        ):
            if marker not in m1b:
                bad.append(f"M1-b 缺 `{marker}`：{why}")
    if "未实测" not in text:
        bad.append("ADR 必须显式标注「本 PR 未在真机实测」（用户口径：未验证的不要写成已验证）")
    return bad


def _doc_section(text: str, item: str) -> str:
    """按 `### ` 切小节，取标题以 `item ` 开头的那一段（到下一个 `### `/`## ` 为止）。"""
    out: list[str] = []
    capturing = False
    for line in text.splitlines():
        if line.startswith("### "):
            capturing = line[4:].strip().startswith(item + " ")
            if capturing:
                out.append(line)
            continue
        if line.startswith("## ") or line.startswith("# "):
            capturing = False
            continue
        if capturing:
            out.append(line)
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════
# 判据 1：upstream 形态
# ══════════════════════════════════════════════════════════════════════════

def test_upstream_shape_is_add_remove_not_direct_dns():
    text = read_nginx()
    bad = judge_upstream_shape(text)
    assert not bad, "nginx.conf 的 upstream 形态不成立：\n" + "\n".join(f"  - {b}" for b in bad)


def test_each_upstream_member_uses_container_port_not_host_second_port():
    blocks = upstream_blocks(read_nginx())
    for svc, (name, port) in UPSTREAMS.items():
        for host, mport, _flags in members_of(blocks.get(name, [])):
            assert mport not in HOST_SECOND_PORTS, (
                f"`upstream {name}` 的成员 `{host}:{mport}` 用了宿主第二端口 —— nginx 在容器里，"
                f"只能走**容器内端口** {port}（宿主端口只在宿主侧可达；ADR M1-a 第 2 点）"
            )


# ══════════════════════════════════════════════════════════════════════════
# 判据 2：渲染不退化
# ══════════════════════════════════════════════════════════════════════════

def test_domain_rendering_keeps_server_name_and_upstreams():
    canonical = read_nginx()
    bad = judge_rendered(canonical)
    assert not bad, "`MIGAO_PUBLIC_DOMAIN` 渲染被 upstream 改动带坏了：\n" + "\n".join(f"  - {b}" for b in bad)


# ══════════════════════════════════════════════════════════════════════════
# 判据 3：切换顺序（点名行号）+ 切换面不许重建容器
# ══════════════════════════════════════════════════════════════════════════

def test_cutover_sequence_switches_upstream_before_recreating_the_formal_container():
    bad, readings = judge_cutover_sequence(read_deploy())
    print("切换顺序行号读数：" + "；".join(f"{k}=L{v}" for k, v in readings.items()))
    assert not bad, (
        "deploy.sh 的切换顺序不是零停机形态：\n"
        + "\n".join(f"  - {b}" for b in bad)
        + "\n行号读数：" + "；".join(f"{k}=L{v}" for k, v in readings.items())
    )


def test_switch_function_only_reloads_and_restores_on_failure():
    bad = judge_switch_function(read_deploy())
    assert not bad, "`nginx_upstream_switch()` 不满足「只切配置 + reload + 失败恢复」：\n" + "\n".join(
        f"  - {b}" for b in bad
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 4：改写器行为（真跑 deploy.sh 里那段 python，在真实 nginx.conf 的副本上）
# ══════════════════════════════════════════════════════════════════════════

REWRITER_BEGIN = "# >>> upstream-members-rewrite"
REWRITER_END = "# <<< upstream-members-rewrite"


def extract_rewriter(deploy_text: str) -> str:
    """抽出 `rewrite_upstream_members()` 里那段 python（heredoc 体），单独跑。"""
    assert REWRITER_BEGIN in deploy_text and REWRITER_END in deploy_text, (
        f"deploy.sh 里找不到改写器标记 `{REWRITER_BEGIN}` / `{REWRITER_END}`"
    )
    region = deploy_text.split(REWRITER_BEGIN, 1)[1].split(REWRITER_END, 1)[0]
    m = re.search(r"<<'PY_UPSTREAM_MEMBERS'\n(.*?)\nPY_UPSTREAM_MEMBERS\n", region, re.S)
    assert m, "改写器区域里找不到 `<<'PY_UPSTREAM_MEMBERS' … PY_UPSTREAM_MEMBERS` heredoc"
    body = m.group(1)
    assert "os.replace" in body, "改写器没有原子写入（`os.replace`）⇒ 存在半截文件风险"
    return body


def run_rewriter(tmp_path: Path, conf: Path, target: str, members: str) -> subprocess.CompletedProcess:
    script = tmp_path / "rewriter.py"
    script.write_text(extract_rewriter(read_deploy()), encoding="utf-8")
    env = dict(os.environ)
    env.update(
        UPSTREAM_FILE=str(conf),
        UPSTREAM_TARGET=target,
        UPSTREAM_MEMBERS=members,
        UPSTREAM_BEGIN=f"# {MEMBER_BEGIN}",
        UPSTREAM_END=f"# {MEMBER_END}",
    )
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def green_members(svc: str) -> str:
    port = UPSTREAMS[svc][1]
    return f"server {svc}-green:{port} max_fails=2 fail_timeout=10s;\nserver {svc}:{port} backup;\n"


def formal_members(svc: str) -> str:
    port = UPSTREAMS[svc][1]
    return f"server {svc}:{port} max_fails=2 fail_timeout=10s;\n"


def test_rewriter_switches_each_service_to_two_backends(tmp_path: Path):
    canonical = read_nginx()
    for svc, (name, _port) in UPSTREAMS.items():
        conf = tmp_path / f"switch-{svc}.conf"
        conf.write_text(canonical, encoding="utf-8")
        proc = run_rewriter(tmp_path, conf, name, green_members(svc))
        assert proc.returncode == 0, f"改写 `upstream {name}` 失败：rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        blocks = upstream_blocks(conf.read_text(encoding="utf-8"))
        members = members_of(blocks[name])
        assert len(members) == 2, f"`upstream {name}` 切换后应有两个后端，实测 {members}"
        assert members[0][0] == f"{svc}-green" and "backup" not in members[0][2].split(), (
            f"`upstream {name}` 的主成员应是 {svc}-green，实测 {members}"
        )
        assert members[1][0] == svc and "backup" in members[1][2].split(), (
            f"`upstream {name}` 的兜底成员应是 {svc} 且带 backup（主成员挂了才回落），实测 {members}"
        )
        # 其它两个 upstream 一字未动
        for other, (other_name, _p) in UPSTREAMS.items():
            if other == svc:
                continue
            assert upstream_blocks(conf.read_text(encoding="utf-8"))[other_name] == upstream_blocks(canonical)[other_name], (
                f"改 `upstream {name}` 时连带改了 `upstream {other_name}`"
            )


def test_rewriter_restores_byte_identical_and_is_idempotent(tmp_path: Path):
    original = read_nginx()
    for svc, (name, _port) in UPSTREAMS.items():
        conf = tmp_path / f"nginx-{svc}.conf"
        conf.write_text(original, encoding="utf-8")
        assert run_rewriter(tmp_path, conf, name, green_members(svc)).returncode == 0
        first = conf.read_text(encoding="utf-8")
        assert run_rewriter(tmp_path, conf, name, green_members(svc)).returncode == 0, "同一输入第二次改写失败"
        assert conf.read_text(encoding="utf-8") == first, "改写不是幂等的（连跑两次结果不同）"
        assert run_rewriter(tmp_path, conf, name, formal_members(svc)).returncode == 0
        assert conf.read_text(encoding="utf-8") == original, (
            f"`upstream {name}` 切回正式容器后与原文**不一致**（必须逐字节一致：稳态 = canonical）"
        )


def test_rewriter_refuses_unknown_upstream_and_missing_markers(tmp_path: Path):
    original = read_nginx()
    conf = tmp_path / "nginx.conf"
    conf.write_text(original, encoding="utf-8")
    proc = run_rewriter(tmp_path, conf, "migao_nonexistent", formal_members("admin-api"))
    assert proc.returncode != 0, "未知 upstream 名却改写成功（会静默写出第二个文件级联）"
    assert conf.read_text(encoding="utf-8") == original, "失败路径居然改了文件"

    stripped = inject(original, f"    # {MEMBER_BEGIN}\n", "", where="deploy/swas/nginx.conf", count=3)
    conf.write_text(stripped, encoding="utf-8")
    proc = run_rewriter(tmp_path, conf, "migao_admin_api", formal_members("admin-api"))
    assert proc.returncode != 0, "成员标记缺失却改写成功（会写到错误的行区间）"
    assert conf.read_text(encoding="utf-8") == stripped, "失败路径居然改了文件"

    proc = run_rewriter(tmp_path, conf, "migao_admin_api", "")
    assert proc.returncode != 0, "空成员清单却改写成功（= 写出一个没有任何后端的 upstream）"


# ══════════════════════════════════════════════════════════════════════════
# 判据 5：优雅退出（三处同时成立）
# ══════════════════════════════════════════════════════════════════════════

def test_graceful_shutdown_is_configured_where_it_actually_takes_effect():
    bad = judge_graceful(
        read(APPLICATION_YML),
        read(AI_AGENT_DOCKERFILE),
        read(COMPOSE),
        read(COMPOSE_BG),
    )
    assert not bad, "优雅退出没有落在**实际生效位置**：\n" + "\n".join(f"  - {b}" for b in bad)


# ══════════════════════════════════════════════════════════════════════════
# 判据 6：文档已实施 + 怎么验证 + 读数占位
# ══════════════════════════════════════════════════════════════════════════

def test_doc_moved_m1a_m1b_from_gap_to_implemented_with_verification():
    bad = judge_doc(read(DOC))
    assert not bad, "ADR 的 M1-a/M1-b 还停在「缺口」或缺验证/读数占位：\n" + "\n".join(f"  - {b}" for b in bad)


# ══════════════════════════════════════════════════════════════════════════
# 判据 7：只读流式探针（M1-b 的可重复读数面）
# ══════════════════════════════════════════════════════════════════════════

def test_stream_probe_is_readonly_gated_and_declared():
    bad = judge_stream_probe(read(AI_AGENT_MAIN), read(AI_AGENT_PROBE_LEDGER))
    assert not bad, "只读流式探针不满足「零写 + 有鉴权 + 有夹取 + 已登记」：\n" + "\n".join(
        f"  - {b}" for b in bad
    )
    # 行为判据必须在 ai-agent 自己的测试套里（本文件只做静态面，避免把 AI 服务的依赖拖进来）
    assert AI_AGENT_PROBE_TEST.is_file(), f"缺行为判据文件：{AI_AGENT_PROBE_TEST}"
    probe_test = read(AI_AGENT_PROBE_TEST)
    assert "# case_ids: MC-351" in probe_test, "行为判据文件头部必须声明 `# case_ids: MC-351`"
    for marker in ("401", "event: notice", "event: ping", "is_disconnected"):
        assert marker in probe_test, f"行为判据文件没覆盖 `{marker}`（判据面缺一块）"


# ══════════════════════════════════════════════════════════════════════════
# 注入式红证（在临时字符串上做；注入必须先自证落到文本上）
# ══════════════════════════════════════════════════════════════════════════

def test_injection_revert_cutover_to_recreate_plus_reload_goes_red():
    """🔴 本包的核心红证：把切换改回「`docker compose up -d` 重建 + reload」⇒ 判据红。"""
    text = read_deploy()
    mutated = inject(
        text,
        'nginx_upstream_switch "$svc" green || SWITCH_RC=$?',
        'docker compose up -d --no-deps "$svc"',
        where="deploy/swas/deploy.sh",
        count=1,
    )
    assert mutated != text, "注入未生效：切换调用没有被替换成重建"
    bad, readings = judge_cutover_sequence(mutated)
    assert bad, f"把「只切 upstream」改回「重建容器」后判据仍然绿 ⇒ 判据没有判别力。行号读数：{readings}"
    joined = "\n".join(bad)
    assert "切 upstream" in joined or "出现 2 次" in joined, (
        f"判红必须点名「切换面消失 / 重建出现两次」，实得：{bad}"
    )


def test_injection_upstream_member_on_host_second_port_goes_red():
    text = read_nginx()
    mutated = inject(
        text,
        "    server admin-api:8080 max_fails=2 fail_timeout=10s;",
        "    server admin-api:18080 max_fails=2 fail_timeout=10s;",
        where="deploy/swas/nginx.conf",
        count=1,
    )
    bad = judge_upstream_shape(mutated)
    assert any("容器内端口" in b for b in bad), f"成员写到宿主第二端口却判绿 ⇒ 判据没有判别力。实得：{bad}"


def test_injection_proxy_pass_back_to_service_name_goes_red():
    text = read_nginx()
    mutated = inject(
        text,
        "proxy_pass http://migao_admin_api;",
        "proxy_pass http://admin-api:8080;",
        where="deploy/swas/nginx.conf",
        count=5,
    )
    bad = judge_upstream_shape(mutated)
    assert any("服务名直连" in b for b in bad), f"proxy_pass 改回服务名却判绿。实得：{bad}"


def test_injection_drop_worker_shutdown_timeout_goes_red():
    text = read_nginx()
    m = re.search(r"^worker_shutdown_timeout .*\n", text, re.MULTILINE)
    assert m, "反空跑锚点：nginx.conf 里没有 `worker_shutdown_timeout`（注入无从下手 ⇒ 判据已过期）"
    bad = judge_upstream_shape(text[: m.start()] + text[m.end():])
    assert any("worker_shutdown_timeout" in b for b in bad), f"删掉 worker_shutdown_timeout 却判绿。实得：{bad}"


def test_injection_drop_shutdown_graceful_goes_red():
    text = read(APPLICATION_YML)
    mutated = inject(text, "  shutdown: graceful\n", "", where="application.yml", count=1)
    bad = judge_graceful(mutated, read(AI_AGENT_DOCKERFILE), read(COMPOSE), read(COMPOSE_BG))
    assert any("server.shutdown" in b for b in bad), f"删掉 `server.shutdown: graceful` 却判绿。实得：{bad}"


def test_injection_drop_uvicorn_graceful_flag_goes_red():
    mutated = inject(
        read(AI_AGENT_DOCKERFILE),
        ', "--timeout-graceful-shutdown", "200"',
        "",
        where="backend/ai-agent-service/Dockerfile",
        count=1,
    )
    bad = judge_graceful(read(APPLICATION_YML), mutated, read(COMPOSE), read(COMPOSE_BG))
    assert any("--timeout-graceful-shutdown" in b for b in bad), f"删掉 uvicorn 优雅退出参数却判绿。实得：{bad}"


def test_injection_drop_stop_grace_period_goes_red():
    text = read(COMPOSE)
    mutated = inject(text, "    stop_grace_period: 45s\n", "", where="deploy/swas/docker-compose.yml", count=1)
    bad = judge_graceful(read(APPLICATION_YML), read(AI_AGENT_DOCKERFILE), mutated, read(COMPOSE_BG))
    assert any("stop_grace_period" in b for b in bad), f"删掉 compose 的 stop_grace_period 却判绿。实得：{bad}"


def test_injection_doc_downgrade_goes_red():
    """把「已实施」整体降级成「未实施」⇒ 文档判据必须红（不许「表格里改了、正文还留着」）。"""
    text = read(DOC)
    n = text.count("已实施")
    assert n >= 2, f"反空跑锚点：ADR 里「已实施」只有 {n} 处（M1-a / M1-b 各至少要一处）"
    mutated = inject(text, "已实施", "未实施", where="docs/deployment/zero-downtime-release.md", count=n)
    bad = judge_doc(mutated)
    assert bad, "把「已实施」全部降级成「未实施」后文档判据仍然绿 ⇒ 判据没有判别力"
    assert any("M1-a" in b or "M1-b" in b for b in bad), f"判红必须点名 M1-a/M1-b，实得：{bad}"


def test_injection_rendering_dropped_domain_goes_red():
    text = read_nginx()
    mutated = inject(text, "server_name api.migaozn.com;", "server_name api.other.example;", where="nginx.conf", count=1)
    bad = judge_rendered(mutated)
    assert any("站点域" in b for b in bad), f"渲染后 server_name 丢站点域却判绿。实得：{bad}"


def test_injection_probe_without_auth_goes_red():
    """红证：摘掉 `Depends(verify_service_token)` ⇒ 匿名可达 ⇒ 判据红。"""
    mutated = inject(
        read(AI_AGENT_MAIN),
        "        authorized: bool = Depends(verify_service_token),\n",
        "",
        where="backend/ai-agent-service/app/main.py",
        count=1,
    )
    bad = judge_stream_probe(mutated, read(AI_AGENT_PROBE_LEDGER))
    assert any("鉴权" in b for b in bad), f"摘掉鉴权却判绿。实得：{bad}"


def test_injection_probe_without_clamp_goes_red():
    """红证：去掉时长夹取 ⇒ 调用方能开一条跑几小时的流 ⇒ 判据红。"""
    mutated = inject(
        read(AI_AGENT_MAIN),
        "    return max(1, min(int(seconds), STREAM_PROBE_MAX_SECONDS))\n",
        "    return int(seconds)\n",
        where="backend/ai-agent-service/app/main.py",
        count=1,
    )
    bad = judge_stream_probe(mutated, read(AI_AGENT_PROBE_LEDGER))
    assert any("夹到上限" in b or "下限 1" in b for b in bad), f"去掉夹取却判绿。实得：{bad}"


def test_injection_probe_touching_the_db_goes_red():
    """红证：handler 里塞一条写库调用 ⇒ 不再只读 ⇒ 判据红并**点名行号**。"""
    mutated = inject(
        read(AI_AGENT_MAIN),
        "        if await is_disconnected():\n",
        "        await SessionService().commit()  # 注入：写面\n        if await is_disconnected():\n",
        where="backend/ai-agent-service/app/main.py",
        count=1,
    )
    bad = judge_stream_probe(mutated, read(AI_AGENT_PROBE_LEDGER))
    assert any("写库" in b for b in bad), f"handler 里出现写库调用却判绿。实得：{bad}"


def test_injection_probe_unregistered_goes_red():
    """红证：探针不登记到 APP_LEVEL_PROBES（类级元守卫被绕过）⇒ 判据红。"""
    mutated = inject(
        read(AI_AGENT_PROBE_LEDGER),
        '    "/internal/stream-probe":',
        '    "/internal/stream-probe-unregistered":',
        where="backend/ai-agent-service/tests/test_llm_health.py",
        count=1,
    )
    bad = judge_stream_probe(read(AI_AGENT_MAIN), mutated)
    assert any("登记" in b for b in bad), f"探针未登记却判绿。实得：{bad}"

