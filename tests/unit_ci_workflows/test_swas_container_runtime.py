# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/swas/docker-compose*.yml` 的**容器运行面**判据（issue #8197 P1-02 / P1-12）。

## 病（两条都在 2026-10-31 上线审计里，读数逐条在 findings.md）

1. **P1-02 日志无界增长**：四个服务**都没有 `logging:` 段** ⇒ docker 默认 json-file 驱动
   无上限 ⇒ 单机磁盘单调爬升 ⇒ 写满后四服务同时 502（`restart: unless-stopped` 救不了
   「写不进去」），而**没有任何读数会先变红**。
2. **P1-12 假活**：只有 ai-agent 有健康检查；`admin-api` / `admin-web` / `nginx` **没有** ⇒
   进程僵死（线程池耗尽 / 死锁）时容器仍 `Up`，`restart` 不会重启它。

## 判据（每条都能单独变红）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | `docker-compose.yml` **每个** service 都有 `logging`（driver=json-file / max-size=50m / max-file=3） | 少一个 service、或把 max-size 改大 ⇒ 红（含**新增服务未带 logging**） |
| 2 | `docker-compose.bluegreen.yml` 的**每个 green** 也有同一份 logging | green 是**真容器**（同样写日志）⇒ 漏了它留下一个无界增长点 |
| 3 | `deploy.sh` 的 `LOG_CAP_MB` / `LOG_MAX_FILES` 与 compose 的值**逐字相等** | 两处各写各的 ⇒ 红（读数与上界不同源时，「超上界」告警是假的） |
| 4 | `admin-api` / `admin-web` / `nginx` 都有 healthcheck；`ai-agent` 保留原判据 | 删掉任一 ⇒ 红 |
| 5 | healthcheck **与 `deploy.sh::wait_healthy` 同源**：同端口 + 同路径（`svc_port` / `svc_health_path`） | 把 `/actuator/health` 改成 `/health` ⇒ 红（两套判据 ⇒ 回滚抖动） |
| 6 | admin-web 的健康判据照抄 `wait_healthy` 的**状态码集合**（200/301/302） | 只认 200 ⇒ 红（比部署判据更严） |
| 7 | nginx 的 healthcheck 打 `:80/healthz`，且 `nginx.conf` 有 `location = /healthz` 回 200 + `access_log off` | 删 location / 改成探 https 静态面 ⇒ 红 |
| 8 | green ↔ 正式服务的 `logging` / `healthcheck` 逐字一致（抗漂移红线的延伸） | 只在正式服务加 ⇒ 红 |
| 9 | `deploy.sh` 有 **只读** 的容器日志水位读数：函数存在、**无删除动作**、在主流里**被调用**、输出 `MIGAO-DISK-WATERMARK` 且带上界对账 | 删调用 / 加 `rm` / 把读数段删掉 ⇒ 红 |
| 10 | 执行式：`container_log_footprint_mb()` 在替身 `docker` 上算出「MB + 容器数」 | 改成按容器名硬编码 ⇒ 红 |
| 11 | 判据 1~9 的注入式自证（在内存里变异文本，必须被检出并指名） | 任一注入**没被检出** ⇒ 红（判据自己空转） |

## 红证（改前，逐条可复算）

```bash
grep -c 'logging:' deploy/swas/docker-compose.yml     # 改前 0
grep -c 'healthcheck:' deploy/swas/docker-compose.yml # 改前 1（只有 ai-agent）
grep -c 'MIGAO-DISK-WATERMARK' deploy/swas/deploy.sh  # 改前 0
```
改后同一组命令分别给出 `4`（+3 个 green）/ `4`（+2 个 green）/ `1`，且本文件全绿。

## 边界（照实登记，§19.1）

- 判据读的是**compose 文本 + 脚本文本**，**不跑 docker** ⇒ 它证明不了 `docker compose config` 通过、
  也证明不了「容器真的按这个上限轮转」（本机无 docker）；
  **执行式判据 10** 跑的是 `deploy.sh` 里**抽出来的那个函数** + 替身 `docker`，不是真 docker。
- 它证明不了「healthcheck 真的让 docker 报 healthy」（`start_period` / 镜像里有没有 `wget`/`node`
  要上真机看）：`admin-api` 用 `wget`（其 Dockerfile 已用同一形态）、`admin-web` 用 node 的 fetch、
  `nginx:alpine` 用 busybox `wget`。
- 「docker 不会因 unhealthy 自动重启」这一点**没有**被本单改变（那要另接 autoheal）—— 本单只让
  「假活」在 `docker compose ps` / `docker inspect` 上不再长得像健康。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "deploy" / "swas" / "docker-compose.yml"
BG_COMPOSE = REPO_ROOT / "deploy" / "swas" / "docker-compose.bluegreen.yml"
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"

#: 文档化的日志上界（**唯一口径**：改这里 = 改 compose + deploy.sh 三处，缺一处判红）
DOC_MAX_SIZE = "50m"
DOC_MAX_FILE = "3"
#: 没有健康检查的服务登记表（今天为空 —— 「未登记即红」，新增服务必须显式登记理由）
HEALTHCHECK_MISSING_ALLOWED: dict[str, str] = {}

#: `wait_healthy` 的判据来源 = deploy.sh 的两张表。**不在这里抄一份真值**：
#: 判据 5 现取 `svc_port()` / `svc_health_path()` 的 `case` 分支逐条比对（两处各写各的 ⇒ 红）。
HEALTHCHECK_SAME_SOURCE_SERVICES = ("admin-api", "admin-web")


# ══════════════════════════════════════════════════════════════════════════
# 一、纯函数判据（吃**文本** ⇒ 注入式自证可以把变异后的文本喂进来）
# ══════════════════════════════════════════════════════════════════════════


def _services(text: str) -> dict:
    return yaml.safe_load(text)["services"]


def judge_logging(compose_text: str, *, file_label: str) -> list[str]:
    """判据 1 / 2：**每个** service 的 `logging` 逐字段等于文档值（含新增服务）。"""
    v: list[str] = []
    services = _services(compose_text)
    if not services:
        return [f"{file_label} 里一个 service 都没有 —— 本判据的坐标没了"]
    for name, svc in services.items():
        logging_cfg = (svc or {}).get("logging")
        if not logging_cfg:
            v.append(f"{file_label} 的 {name} 没有 `logging:` ⇒ json-file 无上限（P1-02）")
            continue
        if logging_cfg.get("driver") != "json-file":
            v.append(f"{file_label} 的 {name}.logging.driver = {logging_cfg.get('driver')!r}，期望 'json-file'")
        options = logging_cfg.get("options") or {}
        if str(options.get("max-size")) != DOC_MAX_SIZE:
            v.append(
                f"{file_label} 的 {name}.logging.options.max-size = {options.get('max-size')!r}，"
                f"期望 {DOC_MAX_SIZE!r}（与 deploy.sh 的 LOG_CAP_MB 同源）"
            )
        if str(options.get("max-file")) != DOC_MAX_FILE:
            v.append(
                f"{file_label} 的 {name}.logging.options.max-file = {options.get('max-file')!r}，"
                f"期望 {DOC_MAX_FILE!r}（与 deploy.sh 的 LOG_MAX_FILES 同源）"
            )
    return v


def _flatten_healthcheck(svc: dict) -> str:
    hc = svc.get("healthcheck") or {}
    test = hc.get("test")
    return " ".join(test) if isinstance(test, list) else str(test or "")


def _health_url(flat: str) -> tuple[str | None, str | None]:
    """从 healthcheck 命令里抽出**(端口, 路径)**；不带端口（如 nginx 的 `:80/healthz`）⇒ 端口 None。"""
    m = re.search(r"http://127\.0\.0\.1:(\d+)(/[^\s'\"]*)", flat)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"http://127\.0\.0\.1(/[^\s'\"]*)", flat)
    if m:
        return None, m.group(1)
    return None, None


def _deploy_case_table(deploy_text: str, func_name: str) -> dict[str, str]:
    """从 deploy.sh 的 `case "$1" in <svc>) echo <值> ;; …` 取「服务 → 值」表（现取，不抄真值）。"""
    body = _function_body(deploy_text, func_name)
    out: dict[str, str] = {}
    for svc, value in re.findall(r"^\s*(\S+?)\)\s*echo\s+(\S+)\s*;;", body, re.M):
        if svc.startswith("*"):
            continue
        out[svc] = value.strip('"')
    return out


def judge_healthchecks(compose_text: str, deploy_text: str, nginx_text: str) -> list[str]:
    """判据 4 / 5 / 6 / 7：三个服务必须有健康检查；admin-api / admin-web 与 `wait_healthy` 同源。"""
    v: list[str] = []
    services = _services(compose_text)

    for name in ("admin-api", "ai-agent", "admin-web", "nginx"):
        if name not in services:
            v.append(f"docker-compose.yml 里找不到服务 {name}（判据坐标没了）")
            continue
        if not (services[name].get("healthcheck") or {}).get("test"):
            if name in HEALTHCHECK_MISSING_ALLOWED:
                continue
            v.append(f"{name} 没有 healthcheck ⇒ 进程僵死时容器仍 `Up`（P1-12 假活），且未登记豁免")

    # 「同源」的坐标本身必须在（否则判据 5 是空断言）
    for token in ("svc_port()", "svc_health_path()", "wait_healthy()"):
        if token not in deploy_text:
            v.append(f"deploy.sh 里找不到 {token} —— 「healthcheck 与 wait_healthy 同源」的锚点没了")
    ports = _deploy_case_table(deploy_text, "svc_port")
    paths = _deploy_case_table(deploy_text, "svc_health_path")

    # 判据 5：同端口 + 同路径（两侧都**现取**：compose 的 healthcheck 文本 vs deploy.sh 的 case 表）
    # ⚠️ 用「把 URL 拆成 (端口, 路径) 再**逐字**比」而不是 `in`：`/actuator/health` 以 `/health`
    #    结尾 ⇒ 子串比较会把「路径漂移成 /health」判成通过（假绿，本单第一版就踩了）。
    for name in HEALTHCHECK_SAME_SOURCE_SERVICES:
        flat = _flatten_healthcheck(services.get(name) or {})
        if not flat:
            continue  # 已在判据 4 判红
        want_port, want_path = ports.get(name), paths.get(name)
        if not want_port or not want_path:
            v.append(f"deploy.sh 的 svc_port / svc_health_path 里没有 {name}（判据 5 无从判定）")
            continue
        got_port, got_path = _health_url(flat)
        if got_port != want_port:
            v.append(f"{name} 的 healthcheck 端口 = {got_port!r}，deploy.sh::svc_port = {want_port!r} ⇒ 不同源：{flat}")
        if got_path != want_path:
            v.append(
                f"{name} 的 healthcheck 路径 = {got_path!r}，deploy.sh::svc_health_path = {want_path!r} ⇒ 不同源：{flat}"
            )

    # 判据 6：admin-web 的状态码集合必须与 wait_healthy 一致（200/301/302）
    web_flat = _flatten_healthcheck(services.get("admin-web") or {})
    if web_flat:
        for code in ("200", "301", "302"):
            if code not in web_flat:
                v.append(f"admin-web 的 healthcheck 没把 {code} 算作存活（wait_healthy 认 200/301/302）")
    m = re.search(r'if \[ "\$code" = "200" \].*?echo "  \$name OK', deploy_text, re.S)
    if not m:
        v.append("deploy.sh::wait_healthy 的「可接受状态码」段没找到（判据 6 的坐标没了）")

    # 判据 7：nginx 的健康面 = nginx.conf 的 `location = /healthz`
    nginx_flat = _flatten_healthcheck(services.get("nginx") or {})
    if nginx_flat:
        if "/healthz" not in nginx_flat:
            v.append(f"nginx 的 healthcheck 没有探本地面 /healthz：{nginx_flat}")
        if "127.0.0.1" not in nginx_flat:
            v.append(f"nginx 的 healthcheck 没走本机回环 127.0.0.1：{nginx_flat}")
    healthz = re.search(r"^\s*location = /healthz\s*\{", nginx_text, re.M)
    if not healthz:
        v.append("nginx.conf 里没有 `location = /healthz`（nginx 容器的健康面就没了）")
    else:
        block = nginx_text[healthz.end():].split("}", 1)[0]
        if "return 200" not in block:
            v.append("nginx.conf 的 `location = /healthz` 不返回 200")
        if "access_log off" not in block:
            v.append("nginx.conf 的 `location = /healthz` 没关访问日志（健康检查会刷日志）")
    return v


def judge_green_parity(base_text: str, bg_text: str) -> list[str]:
    """判据 8：green 与正式服务的 logging / healthcheck 逐字一致（抗漂移红线的延伸）。"""
    v: list[str] = []
    base = _services(base_text)
    bg = _services(bg_text)
    for green, formal in (
        ("admin-api-green", "admin-api"),
        ("ai-agent-green", "ai-agent"),
        ("admin-web-green", "admin-web"),
    ):
        g = bg.get(green)
        b = base.get(formal)
        if not g or not b:
            v.append(f"找不到 {green} 或 {formal}（判据坐标没了）")
            continue
        for key in ("logging", "healthcheck"):
            if g.get(key) != b.get(key):
                v.append(f"{green}.{key} 与 {formal} 不一致（green 跑的就是同一份配置）")
    return v


def _function_body(text: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\)\s*\{{(.*?)^\}}", text, re.S | re.M)
    return m.group(1) if m else ""


def judge_watermark_reading(deploy_text: str) -> list[str]:
    """判据 3 / 9：读数函数存在、**只读**、**接线**、且与 compose 的上界同源。"""
    v: list[str] = []
    for const, value in (("LOG_CAP_MB", DOC_MAX_SIZE.rstrip("m")), ("LOG_MAX_FILES", DOC_MAX_FILE)):
        m = re.search(rf"^{const}=\$\{{{const}:-(\d+)\}}", deploy_text, re.M)
        if not m:
            v.append(f"deploy.sh 里找不到 `{const}=${{{const}:-…}}` 默认值")
        elif m.group(1) != value:
            v.append(f"deploy.sh 的 {const} 默认值 = {m.group(1)}，而 compose 是 {value} ⇒ 两处不同源")

    body = _function_body(deploy_text, "container_log_footprint_mb")
    if not body:
        v.append("deploy.sh 里没有 `container_log_footprint_mb()` —— 容器日志占用没有读数（P1-02 的另一半）")
    else:
        # 只读：函数体内不许出现任何删除 / 截断动作
        for bad in (r"\brm\b", "prune", "truncate", r'>\s*"\$path', "-delete", "docker system"):
            if re.search(bad, body):
                v.append(f"container_log_footprint_mb() 体内出现删除类动作 /{bad}/ ⇒ 读数必须**只读**（铁律 10）")
        if "docker compose ps -q" not in body:
            v.append("container_log_footprint_mb() 没有用 `docker compose ps -q` 限定本项目容器（会数到别人的日志）")

    # 接线：必须在主流里**被调用**（只定义不调用 = 空读数）
    if not re.search(r"^LOG_READING=\$\(container_log_footprint_mb", deploy_text, re.M):
        v.append("container_log_footprint_mb 没有被主流调用（定义 ≠ 接线）")

    # 读数行 + 上界对账（读数必须能自证「轮转没生效」）
    if "MIGAO-DISK-WATERMARK" not in deploy_text:
        v.append("部署日志里没有 `MIGAO-DISK-WATERMARK` 读数行")
    else:
        line = next(l for l in deploy_text.splitlines() if "MIGAO-DISK-WATERMARK" in l)
        for field in ("container_logs_mb=", "containers=", "log_cap_per_container_mb=", "root_pct="):
            if field not in line:
                v.append(f"`MIGAO-DISK-WATERMARK` 读数行缺字段 {field}")
    if "轮转没有生效" not in deploy_text:
        v.append("没有「日志实测占用 > 上界总和 ⇒ 轮转没生效」的告警出口（读数就只是装饰）")
    return v


def all_violations(base_text: str, bg_text: str, deploy_text: str, nginx_text: str) -> list[str]:
    return (
        judge_logging(base_text, file_label="docker-compose.yml")
        + judge_logging(bg_text, file_label="docker-compose.bluegreen.yml")
        + judge_healthchecks(base_text, deploy_text, nginx_text)
        + judge_green_parity(base_text, bg_text)
        + judge_watermark_reading(deploy_text)
    )


# ══════════════════════════════════════════════════════════════════════════
# 二、静态判据（读仓内现状）
# ══════════════════════════════════════════════════════════════════════════


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_container_runtime_invariants_hold():
    v = all_violations(
        _read(BASE_COMPOSE), _read(BG_COMPOSE), _read(DEPLOY_SH), _read(NGINX_CONF)
    )
    assert not v, "容器运行面判据未通过：\n- " + "\n- ".join(v)


# ══════════════════════════════════════════════════════════════════════════
# 三、判据 10：**执行式** —— 抽出的读数函数在替身 docker 上真的算得出「MB + 容器数」
# ══════════════════════════════════════════════════════════════════════════


def _extract_watermark_functions() -> str:
    deploy_text = _read(DEPLOY_SH)
    cap = _function_body(deploy_text, "log_cap_per_container_mb")
    footprint = _function_body(deploy_text, "container_log_footprint_mb")
    assert cap, "deploy.sh 里找不到 log_cap_per_container_mb()"
    assert footprint, "deploy.sh 里找不到 container_log_footprint_mb()"
    cap_const = re.search(r"^LOG_CAP_MB=\$\{LOG_CAP_MB:-(\d+)\}", deploy_text, re.M)
    files_const = re.search(r"^LOG_MAX_FILES=\$\{LOG_MAX_FILES:-(\d+)\}", deploy_text, re.M)
    assert cap_const and files_const, "deploy.sh 里找不到 LOG_CAP_MB / LOG_MAX_FILES 默认值"
    return (
        f"LOG_CAP_MB={cap_const.group(1)}\n"
        f"LOG_MAX_FILES={files_const.group(1)}\n"
        f"log_cap_per_container_mb() {{{cap}}}\n"
        f"container_log_footprint_mb() {{{footprint}}}\n"
    )


def test_log_footprint_reading_is_executable_and_counts_project_containers(tmp_path):
    """真跑抽出来的函数（替身 docker + 两个真日志文件）⇒ 读数 = 实际占用 MB + 容器数。"""
    log1 = tmp_path / "c1-json.log"
    log2 = tmp_path / "c2-json.log"
    log1.write_bytes(b"0" * (2 * 1024 * 1024))
    log2.write_bytes(b"0" * (1024 * 1024))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "compose" ]; then printf "c1\\nc2\\n"; exit 0; fi\n'
        'if [ "$1" = "inspect" ]; then\n'
        '  for last in "$@"; do :; done\n'
        '  case "$last" in\n'
        f'    c1) echo "{log1}" ;;\n'
        f'    c2) echo "{log2}" ;;\n'
        "    *) exit 1 ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    script = (
        "set -uo pipefail\n"
        + _extract_watermark_functions()
        + 'read -r mb count <<EOF\n$(container_log_footprint_mb)\nEOF\n'
        + 'printf "%s %s %s\\n" "$mb" "$count" "$(log_cap_per_container_mb)"\n'
    )
    out = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin"},
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    mb, count, cap = out.stdout.split()
    assert count == "2", f"应当只数本项目容器（替身回了 2 个），实测 {count}"
    # 期望 MB = 两个文件 `du -k` 之和 // 1024（与函数同一算法，避免依赖稀疏文件/块大小假设）
    du = subprocess.run(["du", "-k", str(log1), str(log2)], capture_output=True, text=True, check=True)
    expected = sum(int(line.split()[0]) for line in du.stdout.strip().splitlines()) // 1024
    assert int(mb) == expected, f"日志占用读数 {mb}MB ≠ 复算 {expected}MB"
    assert int(cap) == int(DOC_MAX_SIZE.rstrip("m")) * int(DOC_MAX_FILE), "单容器上界 != max-size × max-file"


# ══════════════════════════════════════════════════════════════════════════
# 四、注入式红证（判据真的会红：在**内存里**变异文本，必须被检出并指名）
# ══════════════════════════════════════════════════════════════════════════


def _inject(text: str, needle: str, replacement: str) -> str:
    assert needle in text, f"注入点定位失败（fail-closed）：找不到 {needle!r}"
    mutated = text.replace(needle, replacement, 1)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    return mutated


def test_injection_service_without_logging_is_caught():
    base = _read(BASE_COMPOSE)
    mutated = _inject(
        base,
        "    logging: *migao-logging\n    # 健康检查（issue #8197 P1-12「假活」）",
        "    # 健康检查（issue #8197 P1-12「假活」）",
    )
    v = judge_logging(mutated, file_label="docker-compose.yml")
    assert any("admin-api" in x and "logging" in x for x in v), v


def test_injection_healthcheck_removed_is_caught():
    base = _read(BASE_COMPOSE)
    start = base.index("    healthcheck:\n      test: [\"CMD-SHELL\", \"wget --no-verbose")
    end = base.index("start_period: 60s", start) + len("start_period: 60s\n")
    mutated = base[:start] + base[end:]
    v = judge_healthchecks(mutated, _read(DEPLOY_SH), _read(NGINX_CONF))
    assert any("admin-api" in x and "healthcheck" in x for x in v), v


def test_injection_healthcheck_path_drift_is_caught():
    deploy = _read(DEPLOY_SH)
    mutated = _inject(deploy, "admin-api) echo /actuator/health ;;", "admin-api) echo /health ;;")
    v = judge_healthchecks(_read(BASE_COMPOSE), mutated, _read(NGINX_CONF))
    assert any("不同源" in x for x in v), v


def test_injection_delete_in_reading_function_is_caught():
    deploy = _read(DEPLOY_SH)
    mutated = _inject(
        deploy,
        "    total=$((total + ${kb:-0}))\n",
        "    total=$((total + ${kb:-0}))\n    rm -f \"$path\"\n",
    )
    v = judge_watermark_reading(mutated)
    assert any("只读" in x for x in v), v


def test_injection_reading_not_wired_is_caught():
    deploy = _read(DEPLOY_SH)
    mutated = _inject(
        deploy, "LOG_READING=$(container_log_footprint_mb || echo \"0 0\")", "LOG_READING=\"0 0\""
    )
    v = judge_watermark_reading(mutated)
    assert any("没有被主流调用" in x for x in v), v


def test_injection_cap_drift_is_caught():
    mutated = _inject(_read(BASE_COMPOSE), 'max-size: "50m"', 'max-size: "500m"')
    v = judge_logging(mutated, file_label="docker-compose.yml")
    assert any("max-size" in x for x in v), v


def test_injection_green_without_logging_is_caught():
    bg = _read(BG_COMPOSE)
    mutated = _inject(
        bg,
        "    logging: *migao-logging\n    # 与 docker-compose.yml 的 admin-api **逐字一致**",
        "    # 与 docker-compose.yml 的 admin-api **逐字一致**",
    )
    v = judge_green_parity(_read(BASE_COMPOSE), mutated)
    assert any("admin-api-green.logging" in x for x in v), v


def test_injection_nginx_health_location_removed_is_caught():
    nginx = _read(NGINX_CONF)
    mutated = _inject(nginx, "    location = /healthz {", "    location = /healthz-renamed {")
    v = judge_healthchecks(_read(BASE_COMPOSE), _read(DEPLOY_SH), mutated)
    assert any("/healthz" in x for x in v), v


if __name__ == "__main__":  # pragma: no cover - 手工复算入口
    raise SystemExit(pytest.main([__file__, "-q"]))
