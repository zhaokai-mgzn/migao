# case_ids: MC-346
# （tests/unit_ci_workflows/** 的 CI/部署契约类判据；用例登记见 .github/cases/misc.yml 的 MC-346）
"""零停机发布 ADR 的**静态守卫**（issue #9084，用户 2026-11-23 裁定「集群部署不影响用户，让用户无感」）。

## 病（为什么文档也要判据）

`docs/deployment/zero-downtime-release.md` 是一份**设计 ADR**：它说的每一句都可能在**没有代码变化**的情况下
腐烂 —— 端口改了、nginx 从「无 upstream」变成「有 upstream」、graceful 从「未配置」变成「已配置」、
redis 从「本机容器」变成「云实例」。这类文档腐烂**不会让任何东西变红**，而它恰恰是后续每个包的行动依据
（例如某个包照着「18080 是第二端口」去写切换逻辑，而配置已经变了）。

同类先例：`tests/unit_ci_workflows/test_swas_deploy_blue_green.py` 用**静态判据**钉住 `deploy.sh` 的蓝绿语义；
本文件把同一形态用在**设计文档**上。

## 本文件锁三件事（每条都能单独变红）

1. **M1 六项 / M2 五项关键字必须在各自小节里**（`M1-a`…`M1-f`、`M2-a`…`M2-e`）——
   只在小节外提到不算：删掉任一项的实现段 ⇒ 判红并**点名缺的是哪一项 / 哪个关键字**。
2. **文档的事实性断言必须与仓内真实配置逐字一致**（漂移 ⇒ 判红并**点名哪一条漂移**）：
   - 第二端口 `18080/18000/13001` ⇄ `deploy/swas/docker-compose.bluegreen.yml` 的 `${BG_*_PORT:-…}`
     默认值 ⇄ `deploy/swas/deploy.sh` 的 `BG_*_PORT=${BG_*_PORT:-…}`（三处必须同一组）；
   - 「`proxy_pass http://admin-api:8080` 走 compose DNS 名、nginx.conf 没有 upstream 块」⇄ `deploy/swas/nginx.conf`；
   - uploads 宿主路径 `/opt/migao-deploy/uploads` ⇄ `deploy/swas/docker-compose.yml` 的 volumes；
   - 「redis 是本机容器、仓库 compose 未定义 redis」⇄ `deploy/swas/docker-compose.yml` 的服务键集合；
   - 「应用优雅退出**当前未配置**（未验证）」⇄ `application.yml` / ai-agent `Dockerfile`（真配了 ⇒ 文档必须同步，
     否则判红：这正是「文档与配置必须一起走」的机械提醒）。
3. **注入式红证**（在临时副本上做，不改仓库）：删 M1 任一项 ⇒ 红；`18080` 改 `18081` ⇒ 红；
   删 M2 任一项 ⇒ 红；反向漂移（配置侧把默认端口改掉、文档不动）⇒ 红。**注入必须先自证落到文本上**
   （`mutated != original`），否则断言本身就是空的。

## 边界（照实登记）

- 判据只读**文本**，不执行 `deploy.sh`、不连生产、不联网 ⇒ 它证的是「设计文档与仓库配置一致」，
  **不证**「线上真的零停机」（那要靠 ADR 里 M1 的演练与 M2 的灰度读数）。
- ADR 里的「生产读数」（磁盘/内存/Swap/今天的事故）**不在本判据射程内** —— 那些是一次性现场读数，
  没有 durable 载体可交叉校验（ADR 里已标注日期与出处）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "deployment" / "zero-downtime-release.md"
COMPOSE_BG = REPO_ROOT / "deploy" / "swas" / "docker-compose.bluegreen.yml"
COMPOSE = REPO_ROOT / "deploy" / "swas" / "docker-compose.yml"
NGINX = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
DEPLOY = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
APPLICATION_YML = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "application.yml"
AI_AGENT_DOCKERFILE = REPO_ROOT / "backend" / "ai-agent-service" / "Dockerfile"

#: M1 六项：小节名 → 必须出现在**该小节正文**里的关键字。
#: 关键字选取口径：**只有这一项才会出现的实现锚点**（删掉实现段就必然消失），不用「战略」「优化」这类空话。
M1_ITEMS: dict[str, tuple[str, ...]] = {
    "M1-a": (
        "upstream",                                # 切换模型 = upstream 摘挂
        "nginx -s reload",                         # 切换动作 = reload（不是重建容器）
        "proxy_pass http://admin-api:8080",        # 现状事实（nginx 直连服务名）
        "nginx.conf 没有 upstream 块",              # 现状事实（所以才是缺口）
    ),
    "M1-b": (
        "server.shutdown=graceful",
        "spring.lifecycle.timeout-per-shutdown-phase=30s",
        "--timeout-graceful-shutdown",
        "未配置",                                   # 当前状态必须如实标注
    ),
    "M1-c": (
        "/actuator/health/readiness",
        "/actuator/health/liveness",
    ),
    "M1-d": (
        "Last-Event-ID",
        "drain",
    ),
    "M1-e": (
        "expand",
        "contract",
        "不得与发版同批",
    ),
    "M1-f": (
        "EFFECTIVE_TAG",
        "/api/version",
        "同源",
    ),
}

#: M2 五项：同上。
M2_ITEMS: dict[str, tuple[str, ...]] = {
    "M2-a": (
        "uploads",
        "OSS",
        "redis",
        "本机容器",
        "compose 未定义 redis",
        "会话",
        "JWT",
        "单例锁",
    ),
    "M2-b": (
        "SLB",
        "健康检查",
        "灰度",
        "connection-drain",
    ),
    "M2-c": (
        "max_connections",
        "maximum-pool-size",
        "算式",
    ),
    "M2-d": (
        "CloudMonitor",
        "待核对",                                   # 指标名没核对到就必须标「待核对」，不许编
        "不自建采集",
    ),
    "M2-e": (
        "影子",
        "灰度",
        "回退点",
    ),
}

ALL_ITEMS = {**M1_ITEMS, **M2_ITEMS}

#: 第二端口：文档里出现的 5 位端口号（`18080` / `18000` / `13001` 以及任何漂移值）。
_PORT_RE = re.compile(r"\b(1[38]\d{3})\b")
_BG_PORT_RE = re.compile(r"BG_(?:ADMIN_API|AI_AGENT|ADMIN_WEB)_PORT(?::?-)(\d+)")


# ── 解析与判据（纯函数；注入式红证复用同一份实现，保证「判据本体不变、只换输入」）────────────────

def _sections(text: str) -> dict[str, str]:
    """按 `### ` 切小节；`## ` / `# ` 结束当前小节。返回 {小节标题: 正文}。

    正文**含标题行本身**（标题也是该小节的一部分 —— 关键字写在标题里同样算「在该小节里」，
    例如 `### M1-e DB 迁移：**expand / contract**，且**不得与发版同批**`）。
    """
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            out[current] = [line]
        elif line.startswith("## ") or line.startswith("# "):
            current = None
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def _compose_services(text: str) -> set[str]:
    """`services:` 块下的顶层服务键（缩进两空格）。前面 `x-logging` 锚点里的 `options:` 不算。"""
    after = text.split("\nservices:\n", 1)
    if len(after) != 2:
        return set()
    services: set[str] = set()
    for line in after[1].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith("  "):          # 回到顶层键 ⇒ services 块结束
            break
        m = re.match(r"^  ([A-Za-z][A-Za-z0-9-]*):\s*$", line)
        if m:
            services.add(m.group(1))
    return services


def _section_of(sections: dict[str, str], item: str) -> tuple[str | None, str]:
    """按前缀找小节（小节标题 = `M1-a 切换模型：…`），返回 (标题, 正文)；找不到 ⇒ (None, "")。"""
    for title, body in sections.items():
        if title.startswith(item + " ") or title == item:
            return title, body
    return None, ""


def _item_violations(text: str) -> list[str]:
    """M1/M2 逐项：小节必须存在，且每个关键字必须在该小节正文里。"""
    sections = _sections(text)
    violations: list[str] = []
    for item, markers in ALL_ITEMS.items():
        title, body = _section_of(sections, item)
        if title is None:
            violations.append(f"缺小节 `### {item} …`（ADR 的里程碑项被删了？）")
            continue
        for marker in markers:
            if marker not in body:
                violations.append(f"`{item}` 小节缺关键字 `{marker}`（实现/事实锚点被删或写到了别处）")
    return violations


def _ports_from(text: str) -> set[int]:
    return {int(m) for m in _BG_PORT_RE.findall(text)}


def _port_violations(doc_text: str, bg_text: str, deploy_text: str) -> list[str]:
    """三处端口必须同一组：compose 默认值 = deploy.sh 默认值 = 文档 M1-a 里的读数。"""
    bg_ports = _ports_from(bg_text)
    deploy_ports = _ports_from(deploy_text)
    if len(bg_ports) != 3 or len(deploy_ports) != 3:
        return [
            f"配置侧的第二端口读不全（compose={sorted(bg_ports)} / deploy.sh={sorted(deploy_ports)}）"
            " ⇒ 文档的事实断言无法交叉校验（先修配置或改判据，不许静默当绿）"
        ]
    if bg_ports != deploy_ports:
        return [f"第二端口在 compose {sorted(bg_ports)} 与 deploy.sh {sorted(deploy_ports)} 不一致（配置自身已漂移）"]
    _, m1a = _section_of(_sections(doc_text), "M1-a")
    if not m1a:
        return ["文档缺 `### M1-a` 小节 ⇒ 端口断言没有落点"]
    doc_ports = {int(m) for m in _PORT_RE.findall(m1a)}
    missing = bg_ports - doc_ports
    extra = doc_ports - bg_ports
    if missing or extra:
        return [
            "第二端口与真实配置不一致（漂移）："
            f"配置 = {sorted(bg_ports)}（来源 deploy/swas/docker-compose.bluegreen.yml 的 `${{BG_*_PORT:-…}}` "
            "与 deploy/swas/deploy.sh 的 `BG_*_PORT=${BG_*_PORT:-…}`），"
            f"文档 M1-a = {sorted(doc_ports)}"
            + (f"；文档缺 {sorted(missing)}" if missing else "")
            + (f"；文档多出 {sorted(extra)}（不是任何服务的第二端口）" if extra else "")
        ]
    return []


# ── 文档存在 / 结构 ────────────────────────────────────────────────────────────────

def test_adr_exists() -> None:
    assert DOC.is_file(), f"缺设计 ADR：{DOC.relative_to(REPO_ROOT)}（issue #9084 的交付物之一）"
    text = DOC.read_text(encoding="utf-8")
    assert "M1" in text and "M2" in text, "ADR 必须同时给出 M1（单机零停机）与 M2（集群无感）"


# ── M1 / M2 关键字（逐项，缺一项单独红）────────────────────────────────────────────

@pytest.mark.parametrize("item", sorted(ALL_ITEMS))
def test_each_milestone_item_has_its_keywords(item: str) -> None:
    text = DOC.read_text(encoding="utf-8")
    violations = _item_violations(text)
    own = [v for v in violations if f"`{item}`" in v or f"`### {item}" in v]
    assert not own, f"{item} 的判据不成立：\n" + "\n".join(own)


def test_all_items_are_green_together() -> None:
    """整体一遍（与逐项参数化互补：这条能在**更早**的位置报出「多删了几项」）。"""
    text = DOC.read_text(encoding="utf-8")
    violations = _item_violations(text)
    assert not violations, "ADR 的里程碑项不完整：\n" + "\n".join(violations)


# ── 事实断言 ⇄ 真实配置（漂移即红、点名哪一条）──────────────────────────────────────

def test_second_ports_match_compose_and_deploy_defaults() -> None:
    violations = _port_violations(
        DOC.read_text(encoding="utf-8"),
        COMPOSE_BG.read_text(encoding="utf-8"),
        DEPLOY.read_text(encoding="utf-8"),
    )
    assert not violations, "\n".join(violations)


def test_proxy_pass_and_no_upstream_claims_match_nginx() -> None:
    doc = DOC.read_text(encoding="utf-8")
    nginx = NGINX.read_text(encoding="utf-8")
    assert "proxy_pass http://admin-api:8080" in nginx, (
        "nginx.conf 里不再有 `proxy_pass http://admin-api:8080`（改成了 upstream？）"
        " ⇒ ADR 的现状断言已过期：请同步 ADR 的 M1-a 小节"
    )
    assert "proxy_pass http://admin-api:8080" in doc, "ADR 的现状断言缺 `proxy_pass http://admin-api:8080`"
    assert "upstream" not in nginx, (
        "nginx.conf 里出现了 `upstream` —— ADR 的「nginx.conf 没有 upstream 块」已过期；"
        "要么撤掉该改动，要么同步 ADR 的 M1-a 小节（切换模型已经换了）"
    )
    assert "nginx.conf 没有 upstream 块" in doc, "ADR 必须如实写出「nginx.conf 没有 upstream 块」这个缺口前提"


def test_uploads_host_path_claim_matches_compose() -> None:
    doc = DOC.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "- /opt/migao-deploy/uploads:/app/uploads" in compose, (
        "compose 里 uploads 的宿主卷不再是 `/opt/migao-deploy/uploads:/app/uploads` ⇒ ADR 的 M2-a 现状断言已过期"
    )
    assert "/opt/migao-deploy/uploads" in doc, "ADR 必须点明 uploads 的宿主路径（M2-a 的外置对象）"


def test_redis_is_a_host_container_and_not_in_repo_compose() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    services = _compose_services(compose)
    assert services == {"admin-api", "ai-agent", "admin-web", "nginx"}, (
        f"仓库 compose 的服务键变了：{sorted(services)} —— ADR 的「仓库 compose 未定义 redis」断言需要复核"
    )
    assert "redis" not in services, "仓库 compose 里出现了 redis 服务 —— ADR 的「本机容器 / 无仓库承载」断言已过期"
    doc = DOC.read_text(encoding="utf-8")
    assert "compose 未定义 redis" in doc, "ADR 必须写明「仓库 compose 未定义 redis」（承载面缺失，不只是「用了 redis」）"
    assert "本机容器" in doc, "ADR 必须写明「redis 是本机容器」这个事实（决定 M2 的外置动作）"


def test_graceful_shutdown_is_still_unconfigured_as_the_adr_claims() -> None:
    """ADR 说「当前未配置（未验证）」。这条把「未配置」变成机械事实 —— 一旦有人配了，文档必须同步。

    这不是「不许配」：配好后把 ADR 的 M1-b 行改成「已配置 + 配置位置 + 生效实测」即可，本判据随即转绿。
    """
    doc = DOC.read_text(encoding="utf-8")
    application = APPLICATION_YML.read_text(encoding="utf-8")
    dockerfile = AI_AGENT_DOCKERFILE.read_text(encoding="utf-8")
    _, m1b = _section_of(_sections(doc), "M1-b")
    assert m1b, "ADR 缺 M1-b 小节（应用优雅退出）"
    assert "未配置" in m1b, "ADR 的 M1-b 必须标注「当前是否已配置」（用户要求：未验证的不要写成已验证）"

    configured = []
    if "server.shutdown" in application or "timeout-per-shutdown-phase" in application:
        configured.append("backend/admin-api/src/main/resources/application.yml（Spring 优雅退出已配置）")
    if "--timeout-graceful-shutdown" in dockerfile:
        configured.append("backend/ai-agent-service/Dockerfile（uvicorn 优雅退出已配置）")
    assert not configured, (
        "仓内已经把优雅退出配上了，但 ADR 的 M1-b 还停在「未配置」：请同步 ADR（列出配置位置 + 生效实测方式）——"
        "漂移点：\n" + "\n".join(f"  - {c}" for c in configured)
    )


# ── 注入式红证（在临时副本上做；注入先自证落到文本上）────────────────────────────────

def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _drop_section(text: str, item: str) -> str:
    """删掉整个 `### <item> …` 小节（到下一个 `### `/`## ` 为止），模拟「实现段被删」。"""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    dropping = False
    for line in lines:
        if line.startswith("### "):
            dropping = line[4:].strip().startswith(item + " ")
        elif line.startswith("## ") or line.startswith("# "):
            dropping = False
        if not dropping:
            out.append(line)
    return "".join(out)


def test_injection_dropping_any_m1_item_goes_red() -> None:
    original = _doc_text()
    for item in sorted(M1_ITEMS):
        mutated = _drop_section(original, item)
        assert mutated != original, f"注入未生效：删 `{item}` 小节没有改变文本（判据会变成空断言）"
        violations = _item_violations(mutated)
        assert any(item in v for v in violations), (
            f"删掉 `{item}` 小节后判据仍然绿 ⇒ 这一项没有判别力。实得：{violations}"
        )


def test_injection_dropping_any_m2_item_goes_red() -> None:
    original = _doc_text()
    for item in sorted(M2_ITEMS):
        mutated = _drop_section(original, item)
        assert mutated != original, f"注入未生效：删 `{item}` 小节没有改变文本"
        violations = _item_violations(mutated)
        assert any(item in v for v in violations), (
            f"删掉 `{item}` 小节后判据仍然绿 ⇒ 这一项没有判别力。实得：{violations}"
        )


def test_injection_port_18081_goes_red() -> None:
    original = _doc_text()
    assert "18080" in original, "基线文档里没有 18080 ⇒ 注入无从下手（判据已与配置脱节）"
    mutated = original.replace("18080", "18081")
    assert mutated != original, "注入未生效：`18080` → `18081` 没有改变文本"
    violations = _port_violations(
        mutated,
        COMPOSE_BG.read_text(encoding="utf-8"),
        DEPLOY.read_text(encoding="utf-8"),
    )
    assert violations, "把 ADR 里的 18080 改成 18081 后端口判据仍然绿 ⇒ 判据没有判别力"
    joined = "\n".join(violations)
    assert "18080" in joined and "18081" in joined, (
        f"端口漂移的判红必须**点名**期望值与文档值（实得：{violations}）"
    )


def test_reverse_drift_config_port_change_without_doc_update_goes_red() -> None:
    """反向：配置侧把默认端口改掉、文档不动 ⇒ 同样判红（判据不是「只盯文档」）。"""
    bg = COMPOSE_BG.read_text(encoding="utf-8")
    mutated = bg.replace("BG_ADMIN_API_PORT:-18080", "BG_ADMIN_API_PORT:-18081")
    assert mutated != bg, "注入未生效：compose 的 `BG_ADMIN_API_PORT:-18080` 没被改到"
    violations = _port_violations(_doc_text(), mutated, DEPLOY.read_text(encoding="utf-8"))
    assert violations, "配置侧端口漂移、文档未同步时判据仍然绿 ⇒ 交叉校验只做了单向"
