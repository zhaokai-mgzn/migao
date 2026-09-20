# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/swas/deploy.sh` **严格蓝绿**守卫 —— issue #4785（2026-09-21 云测试环境事故）。

## 事故机理（**主会话实测**，非推断）

`ca724257e` 那次部署失败 ⇒ **旧容器已被替换、新容器起不来** ⇒ `api.migaozn.com` 502 ⇒
环境不可用直到**手工回滚**。造成它的就是 `deploy/swas/deploy.sh` 的这一行：

```bash
docker compose up -d --no-deps $UP_SERVICES     # 先替换，健康检查在第 3 步（之后）
```

`docker compose up -d` 用的是 compose 的**替换**语义（**停旧 → 删旧 → 建新 → 起新**，不是滚动、
更不是蓝绿）⇒ 只要镜像 digest 变了，**旧容器在新容器创建之前就已经被删除**。第 3 步的健康检查
（L129-152）只能**事后发现**，此时旧容器已经没了 —— 这就是「窗口期」的来源。
#4767（已合并 `0211d6a7a`）把「永久坏状态」降到「失败即回滚（窗口 ≈2–4min）」，本单根治到**窗口 = 0**。

## 本文件锁什么

1. **静态判据**（读脚本**当前文本**，不读可变引用 —— §18.3）：批量替换那一步必须消失；正式容器的
   替换必须发生在 **green 健康检查之后**；失败分支必须「删 green + exit 1」且**不得**碰正式容器；
   健康检查判据**全脚本唯一一份**（green 与正式容器共用同一函数）；flock 覆盖范围含新增段；
   应急开关 / 内存预检 fail-closed / 残留 green 清理 / nginx 优雅重载（含 restart 回落）各就位；
   新增的 override 文件必须被同步到服务器。
2. **抗漂移判据**：`docker-compose.bluegreen.yml` 的每个 green 服务与 `docker-compose.yml` 对应服务的
   `image / env_file / environment / mem_limit / cpus / healthcheck` **逐字一致**，端口是**第二端口**
   （同容器端口、不同宿主端口），`restart: "no"`；且 `docker-compose.yml` **既有服务定义未被改动**
   （里面不得出现任何 `*-green`）。
3. **注入式红证**（每条判据各自可独立判红，且**注入必须真的落到文本上**，否则显式失败）。
4. **执行式红证**（桩 `docker` / `curl` / `flock` / `timeout`，跑**真实** `deploy.sh` 的**真实码路**）：
   - 注入「新容器（green）健康检查失败」⇒ 断言 docker 桩日志里**没有**任何正式容器替换、
     **没有**停删旧容器、且 `exit 1`（= **旧容器仍在服务**）；
   - 反向红证（判别力）：把蓝绿段**还原成旧写法** ⇒ 同一次注入下**必然**先替换正式容器 ⇒ 判据**有判别力**；
   - 内存预检不足 ⇒ 一个容器都不许起。

## ⚠️ 红证的真实性边界（**照实登记，不粉饰**）

执行式红证跑的是**本机 + 桩化的外部依赖**（docker / curl / flock / timeout），
**不是**真实 SWAS 环境实测 —— 桩化的是「外部依赖」，被测的是 `deploy.sh` 的**编排逻辑本身**。
「上真机后怎么验证」的可执行判据见 `docs/wiki/CI-CD.md` 的严格蓝绿小节（看 green 出现→消失的顺序 +
推一个坏镜像看旧容器是否仍在）。本机无 docker ⇒ **本 PR 未做真实远端部署验证**。
"""
import os
import re
import shutil
import subprocess
import tarfile
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
BASE_COMPOSE = REPO_ROOT / "deploy" / "swas" / "docker-compose.yml"
BG_COMPOSE = REPO_ROOT / "deploy" / "swas" / "docker-compose.bluegreen.yml"

GREENS = {"admin-api-green": "admin-api", "ai-agent-green": "ai-agent", "admin-web-green": "admin-web"}
# 正式容器的替换调用（判据锚点；写成常量以免 f-string 里出现反斜杠 —— py3.11 不允许）
CANON_UP = 'docker compose up -d --no-deps "$svc"'
# 与 deploy.sh 的 `BG_*_PORT` 默认值必须一致（判据见 test_green_ports_match_deploy_sh_defaults）
DEFAULT_GREEN_PORTS = {"admin-api": 18080, "ai-agent": 18000, "admin-web": 13001}

# 旧写法（**逐字内联**，取自本 PR 之前的脚本；内联而不是 `git show origin/main:…` ——
# 后者会随合并变成「修复后」文本 ⇒ 判据自红，§18.3）
OLD_FORM_SNIPPET = (
    "# shellcheck disable=SC2086\n"
    "docker compose up -d --no-deps $UP_SERVICES\n"
    "# 容器重建后 IP 可能变化，nginx 启动时缓存旧上游 IP → reload/restart 否则 502\n"
    "docker compose restart nginx"
)


# ══════════════════════════════════════════════════════════════════════════
# 读源 + 反空跑锚点
# ══════════════════════════════════════════════════════════════════════════

def read_deploy_sh() -> str:
    assert DEPLOY_SH.is_file(), f"反空跑锚点：目标脚本不存在 → {DEPLOY_SH}"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "== 2.5 严格蓝绿预验证" in text, (
        "反空跑锚点：deploy.sh 里找不到蓝绿段（判据已过期或脚本被改写）—— 这不是「通过」"
    )
    return text


def read_yaml(path: Path) -> dict:
    assert path.is_file(), f"反空跑锚点：文件不存在 → {path}"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict) and isinstance(doc.get("services"), dict), f"{path} 不是合法 compose"
    return doc


def function_body(text: str, name: str) -> str:
    """取 shell 函数体（`name() {` 到配对的 `}` 行）。取不到 ⇒ 显式失败（不是「通过」）。"""
    m = re.search(rf"^{re.escape(name)}\(\) \{{$", text, re.M)
    assert m, f"反空跑锚点：脚本里找不到函数 `{name}()`"
    end = text.find("\n}\n", m.end())
    assert end != -1, f"函数 `{name}()` 没有配对的收尾 `}}`（脚本语法已坏）"
    return text[m.end():end]


def non_comment(text: str) -> str:
    """剥掉**整行注释**后的代码行 —— 判据只判「真的会执行的那一行」。

    必要性：本脚本的注释里**刻意引用了旧写法**（`docker compose up -d --no-deps $UP_SERVICES`）
    用于说明事故机理；不剥注释 ⇒ 判据会把说明文字当命令 ⇒ **恒红**（判据自身缺陷）。
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数：文本进 → 违规清单出；注入式红证驱动**同一份本体**）
# ══════════════════════════════════════════════════════════════════════════

def judge_no_batch_replace(text: str) -> list:
    """① 批量替换那一步必须消失；正式容器的替换必须在 green 健康检查**之后**。"""
    v = []
    code = non_comment(text)
    if re.search(r"docker compose up -d --no-deps \$UP_SERVICES", code):
        v.append("仍存在**批量替换** `docker compose up -d --no-deps $UP_SERVICES`（= 事故机理那一步）")
    i_bg = text.find("2.5 严格蓝绿")
    if i_bg < 0:
        v.append("找不到蓝绿预验证段（2.5）")
    i_hc3 = text.find("== 3. 健康检查")
    if i_hc3 < 0:
        v.append("找不到第 3 步健康检查")
    if i_bg >= 0 and i_hc3 >= 0 and i_bg > i_hc3:
        v.append("蓝绿段排在第 3 步健康检查**之后**（顺序反了）")
    i_green_hc = text.find('if ! wait_healthy "$GPORT"')
    i_canon = text.find('docker compose up -d --no-deps "$svc"')
    if i_green_hc < 0:
        v.append("找不到 green 的健康检查调用（`if ! wait_healthy \"$GPORT\"`）")
    if i_canon < 0:
        v.append("找不到正式容器的替换调用（`docker compose up -d --no-deps \"$svc\"`）")
    if i_green_hc >= 0 and i_canon >= 0 and i_green_hc > i_canon:
        v.append("正式容器替换发生在 green 健康检查**之前**（= 先替换再验证，蓝绿没成立）")
    return v


def judge_single_hc_judgement(text: str) -> list:
    """② 健康检查判据**全脚本唯一一份**（green 与正式容器共用 ⇒ 判据不可能漂移）。"""
    v = []
    if text.count("wait_healthy() {") != 1:
        v.append(f"`wait_healthy()` 定义出现 {text.count('wait_healthy() {')} 次（必须恰好 1 次）")
    loops = re.findall(r'for i in \$\(seq 1 "\$HC_RETRIES"\)', text)
    if len(loops) != 1:
        v.append(f"重试循环出现 {len(loops)} 份（必须恰好 1 份 —— 两份判据会漂移）")
    calls = re.findall(r"wait_healthy \"", text)
    if len(calls) < 3:
        v.append(f"`wait_healthy` 调用点 {len(calls)} 个（应 ≥3：green 健康检查 + 正式容器健康检查 + 第 3 步）")
    body = function_body(text, "wait_healthy")
    for token in ('"200"', '"301"', '"302"', "-m 10"):
        if token not in body:
            v.append(f"`wait_healthy` 判据缺少 {token}（判据被放宽 = 削弱门禁）")
    m = re.search(r"^HC_RETRIES=\$\{HC_RETRIES:-(\d+)\}", text, re.M)
    if not m:
        v.append("找不到 `HC_RETRIES=${HC_RETRIES:-<默认值>}`（健康检查重试预算的默认值锚点）")
    elif m.group(1) != "10":
        v.append(f"健康检查重试默认值 {m.group(1)} ≠ 10（改动前是 10 次 × 10s，不许放宽）")
    m = re.search(r"^HC_INTERVAL_SECONDS=\$\{HC_INTERVAL_SECONDS:-(\d+)\}", text, re.M)
    if not m or m.group(1) != "10":
        v.append("健康检查间隔默认值不是 10s（改动前是 10s，不许放宽）")
    return v


def judge_fail_keeps_old_container(text: str) -> list:
    """③ green 起不来 / 健康检查失败 ⇒ **删 green + exit 1**，且**不得**碰正式容器。"""
    v = []
    blocks = {
        "green 起不来分支": r'if ! \$BG_COMPOSE up -d --no-deps "\$GREEN"; then(.*?)\n    fi\n',
        "green 健康检查失败分支": r'if ! wait_healthy "\$GPORT" "\$GREEN" "\$GPATH"; then(.*?)\n    fi\n',
    }
    for label, pat in blocks.items():
        m = re.search(pat, text, re.S)
        if not m:
            v.append(f"找不到{label}（判据已过期）")
            continue
        blk = m.group(1)
        if "exit 1" not in blk:
            v.append(f"{label}没有 `exit 1`（失败会被当成成功）")
        if "rm -sf" not in blk:
            v.append(f"{label}没有清理 green（残留容器会占第二端口/容器名）")
        if "up -d" in blk:
            v.append(f"{label}里出现 `up -d` —— 会替换正式容器（违反「失败即保持旧容器」）")
    # 失败路径的提示语必须明确「旧容器保持不动」（不许让人从 502 反推）
    if "旧容器保持不动" not in text:
        v.append("失败路径没有「旧容器保持不动」的明确提示语")
    return v


def judge_lock_intact(text: str) -> list:
    """④ flock 必须仍是**整脚本**作用域，且新增段落在锁内（不许把蓝绿挪到锁外）。"""
    v = []
    for token in ('exec 9>"$LOCK"', "flock -n 9", "flock -w 600 9", "trap 'flock -u 9' EXIT"):
        if token not in text:
            v.append(f"flock 相关行被改动：找不到 `{token}`")
    i_lock = text.find("flock -n 9")
    i_bg = text.find("2.5 严格蓝绿")
    if i_lock >= 0 and i_bg >= 0 and i_bg < i_lock:
        v.append("蓝绿段出现在 flock **之前** —— 并发部署会互抢 green 容器")
    return v


def judge_safety_rails(text: str) -> list:
    """⑤ 应急开关 / 内存预检 fail-closed / 残留清理 / nginx 优雅重载（含回落）。"""
    v = []
    if "BG_OFF_FILE" not in text or '[ -f "$BG_OFF_FILE" ]' not in text:
        v.append("缺少应急开关（`BG_OFF_FILE` + `[ -f \"$BG_OFF_FILE\" ]`）—— 蓝绿改坏时没有放行口")
    if "跳过蓝绿预验证" not in text:
        v.append("应急开关分支没有明确提示（跳过蓝绿 ≠ 静默降级）")
    m = re.search(r'if \[ -f "\$BG_OFF_FILE" \]; then(.*?)\nelse\n', text, re.S)
    if not m or "BG_SKIP=1" not in m.group(1):
        v.append("应急开关分支没有置 `BG_SKIP=1`（跳过逻辑接不上）")
    if text.count(CANON_UP) != 1:
        v.append(
            f"正式容器替换调用出现 {text.count(CANON_UP)} 次（应恰好 1 次、且在 if/else 之外）"
            " —— 应急开关一旦也跳过它，`.blue-green-off` 会静默变成「本次不部署」"
        )
    # 注释里引用该调用是允许的（说明文字），但**代码行**里必须恰好 1 次
    if non_comment(text).count(CANON_UP) != 1:
        v.append("代码行里 `" + CANON_UP + "` 不是恰好 1 次")
    if "MemAvailable" not in text:
        v.append("缺少内存预检（green 与旧容器并存 ⇒ 必须容得下最重服务）")
    else:
        m = re.search(r'if \[ "\$\{MEM_AVAIL_MB:-0\}" -lt "\$BG_MEM_NEED_MB" \]; then(.*?)\n  fi\n', text, re.S)
        if not m or "exit 1" not in m.group(1):
            v.append("内存预检不是 fail-closed（不足时必须中止部署、旧容器不动）")
    if "rm -sf $BG_GREENS" not in text:
        v.append("缺少残留 green 清理（上一轮被强杀留下的容器会占第二端口/容器名）")
    if "docker compose exec -T nginx nginx -s reload || docker compose restart nginx" not in text:
        v.append("nginx 上游刷新不是「reload 优先 + restart 回落」（硬 restart 会当场丢弃在途连接）")
    if "cp src/deploy/swas/docker-compose.bluegreen.yml ./docker-compose.bluegreen.yml" not in text:
        v.append("新增的 override 文件没有被同步到服务器（green 服务定义永远到不了远端）")
    return v


def judge_bg_compose_antidrift(base: dict, bg: dict, deploy_text: str) -> list:
    """⑥ green 服务与正式服务**逐字一致**（除三处刻意差异）；既有服务定义未被改动。"""
    v = []
    if set(bg["services"]) != set(GREENS):
        v.append(f"bluegreen override 的服务集合 = {sorted(bg['services'])}，期望 {sorted(GREENS)}")
    if any(k.endswith("-green") for k in base["services"]):
        v.append("docker-compose.yml 里出现 `*-green` —— 既有服务定义被改动了（只许新增 override 文件）")
    for g, s in GREENS.items():
        if g not in bg["services"]:
            v.append(f"override 里缺 {g}")
            continue
        if s not in base["services"]:
            v.append(f"docker-compose.yml 里找不到 {s}")
            continue
        b, x = base["services"][s], bg["services"][g]
        for key in ("image", "env_file", "environment", "mem_limit", "cpus", "healthcheck"):
            if b.get(key) != x.get(key):
                v.append(f"{g}.{key} 与 {s} 不一致（green 跑的就是同一份配置，漂移即判红）")
        if x.get("restart") != "no":
            v.append(f'{g}.restart = {x.get("restart")!r}，必须是 "no"（探针不许自愈复活）')
        ports = x.get("ports") or []
        if len(ports) != 1:
            v.append(f"{g}.ports = {ports}（必须恰好 1 条：只发布第二端口）")
            continue
        m = re.match(r"^127\.0\.0\.1:\$\{(BG_[A-Z_]+):-(\d+)\}:(\d+)$", str(ports[0]))
        if not m:
            v.append(f"{g}.ports 形态不合规：{ports[0]}（应为 127.0.0.1:${{BG_*_PORT:-<默认>}}:<容器端口>）")
            continue
        var, host_port, cport = m.group(1), int(m.group(2)), m.group(3)
        base_ports = [str(p) for p in (b.get("ports") or [])]
        base_cport = base_ports[0].split(":")[-1] if base_ports else None
        if cport != base_cport:
            v.append(f"{g} 的容器端口 {cport} ≠ {s} 的 {base_cport}")
        if f":{host_port}:" in " ".join(base_ports):
            v.append(f"{g} 的宿主端口 {host_port} 与 {s} 冲突（会抢宿主端口 ⇒ green 必然起不来）")
        if DEFAULT_GREEN_PORTS[s] != host_port:
            v.append(f"{g} 的第二端口默认值 {host_port} ≠ 判据里的 {DEFAULT_GREEN_PORTS[s]}")
        # deploy.sh 的同名默认值必须与 override 一致（两边不一致 ⇒ 健康检查打在别的端口上）
        if f"{var}=${{{var}:-{host_port}}}" not in deploy_text:
            v.append(f"deploy.sh 里找不到 `{var}=${{{var}:-{host_port}}}`（与 override 默认值不一致）")
    return v


def all_violations(text: str, base: dict, bg: dict) -> list:
    return (
        judge_no_batch_replace(text)
        + judge_single_hc_judgement(text)
        + judge_fail_keeps_old_container(text)
        + judge_lock_intact(text)
        + judge_safety_rails(text)
        + judge_bg_compose_antidrift(base, bg, text)
    )


# ══════════════════════════════════════════════════════════════════════════
# 一、静态判据（读脚本当前文本）
# ══════════════════════════════════════════════════════════════════════════

def test_real_files_satisfy_every_judgement():
    text = read_deploy_sh()
    base, bg = read_yaml(BASE_COMPOSE), read_yaml(BG_COMPOSE)
    v = all_violations(text, base, bg)
    assert not v, "蓝绿判据未满足：\n- " + "\n- ".join(v)


@pytest.mark.parametrize("judge_name", [
    "judge_no_batch_replace",
    "judge_single_hc_judgement",
    "judge_fail_keeps_old_container",
    "judge_lock_intact",
    "judge_safety_rails",
])
def test_each_judge_is_clean_on_the_real_script(judge_name):
    """逐条判据在真实脚本上必须各自干净（避免一条判据恒红被"整体红"掩盖）。"""
    text = read_deploy_sh()
    v = globals()[judge_name](text)
    assert not v, f"{judge_name} 判红：\n- " + "\n- ".join(v)


def test_green_ports_are_not_the_live_ports():
    """第二端口不得撞正式端口（8080/8000/3001）—— 撞了就与旧容器抢宿主端口。"""
    base, bg = read_yaml(BASE_COMPOSE), read_yaml(BG_COMPOSE)
    live = {p.split(":")[1] for s in base["services"].values() for p in (s.get("ports") or [])}
    for g, s in GREENS.items():
        host = str(bg["services"][g]["ports"][0]).split(":")[1]
        assert host not in live, f"{g} 的第二端口 {host} 撞上了正式端口集合 {sorted(live)}"


# ══════════════════════════════════════════════════════════════════════════
# 二、注入式红证（每条判据各自可独立判红；注入必须真的落到文本上）
# ══════════════════════════════════════════════════════════════════════════

def _inject(text: str, old: str, new: str) -> str:
    """替换注入；**没替换到 ⇒ 显式失败**（否则「注入式红证」是空跑）。"""
    assert old in text, f"注入锚点不存在（判据已过期）：{old[:60]!r}"
    out = text.replace(old, new, 1)
    assert out != text, "注入没有改变文本（空跑）"
    return out


def test_injection_batch_replace_goes_red():
    """注入①：把蓝绿段换回旧的「批量替换」⇒ `judge_no_batch_replace` 必红。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        '  docker compose up -d --no-deps "$svc"',
        "  docker compose up -d --no-deps $UP_SERVICES",
    )
    assert judge_no_batch_replace(injected), "注入批量替换后判据没红（判据无判别力）"


def test_injection_remove_green_health_check_goes_red():
    """注入②：删掉 green 的健康检查 ⇒ 正式容器替换不再「在验证之后」⇒ 必红。"""
    text = read_deploy_sh()
    injected = _inject(text, 'if ! wait_healthy "$GPORT" "$GREEN" "$GPATH"; then', "if false; then")
    v = judge_no_batch_replace(injected) + judge_fail_keeps_old_container(injected)
    assert v, "删掉 green 健康检查后判据没红（判据无判别力）"


def test_injection_second_hc_judgement_goes_red():
    """注入③：再抄一份重试循环（两套判据会漂移）⇒ 必红。"""
    text = read_deploy_sh()
    injected = text + "\nwait_healthy2() {\n" + function_body(text, "wait_healthy") + "\n}\n"
    assert judge_single_hc_judgement(injected), "出现第二份判据后没红（判据无判别力）"


def test_injection_loosen_hc_retries_goes_red():
    """注入④：把重试预算放宽（10 → 1）⇒ 必红（不许放宽门禁）。"""
    text = read_deploy_sh()
    injected = _inject(text, "HC_RETRIES=${HC_RETRIES:-10}", "HC_RETRIES=${HC_RETRIES:-1}")
    assert judge_single_hc_judgement(injected), "放宽重试预算后没红（判据无判别力）"


def test_injection_touch_canonical_in_failure_branch_goes_red():
    """注入⑤：在 green 失败分支里替换正式容器 ⇒ 必红（这正是「先替换再验证」的形态）。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        '      echo "  ❌ $svc 新镜像（tag=${TAG}）健康检查未通过 ⇒ **旧容器保持不动、流量未切**，环境未受影响"\n',
        '      echo "  ❌ 健康检查未通过"\n      docker compose up -d --no-deps "$svc"\n',
    )
    assert judge_fail_keeps_old_container(injected), "失败分支里替换正式容器后没红（判据无判别力）"


def test_injection_move_bg_outside_lock_goes_red():
    """注入⑥：把**整段**蓝绿逻辑挪到 flock 之前 ⇒ 必红（并发部署会互抢 green 容器）。"""
    text = read_deploy_sh()
    i_sec_start = text.rfind("# ══", 0, text.find("2.5 严格蓝绿"))
    i_sec_end = text.find("# ── 2.6 nginx")
    i_lock = text.find("flock -n 9")
    assert 0 < i_lock < i_sec_start < i_sec_end, "锚点位置异常（判据已过期）"
    section = text[i_sec_start:i_sec_end]
    assert "BG_COMPOSE up -d" in section, "反空跑锚点：切出的段里没有蓝绿逻辑"
    injected = text[:i_lock] + section + text[i_lock:i_sec_start] + text[i_sec_end:]
    assert injected != text, "注入没有改变文本（空跑）"
    assert judge_lock_intact(injected), "把蓝绿段挪到锁外后没红（判据无判别力）"


def test_injection_green_port_drift_goes_red():
    """注入⑦：green 的端口与正式服务撞车 ⇒ 必红。"""
    base, bg = read_yaml(BASE_COMPOSE), read_yaml(BG_COMPOSE)
    drifted = yaml.safe_load(yaml.safe_dump(bg))
    drifted["services"]["admin-api-green"]["ports"] = ["127.0.0.1:8080:8080"]
    assert judge_bg_compose_antidrift(base, drifted, read_deploy_sh()), "端口撞车后没红（判据无判别力）"


def test_injection_green_env_drift_goes_red():
    """注入⑧：green 的 environment 与正式服务漂移 ⇒ 必红。"""
    base, bg = read_yaml(BASE_COMPOSE), read_yaml(BG_COMPOSE)
    drifted = yaml.safe_load(yaml.safe_dump(bg))
    drifted["services"]["admin-api-green"]["environment"] = {"TZ": "Asia/Shanghai"}
    assert judge_bg_compose_antidrift(base, drifted, read_deploy_sh()), "env 漂移后没红（判据无判别力）"


def test_injection_green_restart_policy_goes_red():
    """注入⑨：green 用 `unless-stopped`（探针会自愈复活）⇒ 必红。"""
    base, bg = read_yaml(BASE_COMPOSE), read_yaml(BG_COMPOSE)
    drifted = yaml.safe_load(yaml.safe_dump(bg))
    drifted["services"]["admin-api-green"]["restart"] = "unless-stopped"
    assert judge_bg_compose_antidrift(base, drifted, read_deploy_sh()), "restart 策略漂移后没红（判据无判别力）"


# ══════════════════════════════════════════════════════════════════════════
# 三、执行式红证（桩外部依赖，跑真实 deploy.sh 的真实码路）
# ══════════════════════════════════════════════════════════════════════════

CURL_STUB = """#!/bin/bash
# 桩 curl：① codeload 源码包 → 把预置 tar 拷过去；② 健康检查 → 按 $HC_STATE/hc-<端口> 回放状态码
out=""; url=""; fmt=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  *codeload.github.com*) cp "$STUB_TAR" "$out"; exit 0 ;;
esac
port=$(printf '%s' "$url" | sed -n 's#^http://127\\.0\\.0\\.1:\\([0-9][0-9]*\\)/.*#\\1#p')
code=$(cat "$HC_STATE/hc-$port" 2>/dev/null || echo 200)
if [ -n "$out" ]; then : > "$out"; fi
if [ -n "$fmt" ]; then printf '%s' "$code"; fi
exit 0
"""

DOCKER_STUB = """#!/bin/bash
# 桩 docker：只记录调用（顺序敏感），不做任何真实容器操作
echo "docker $*" >> "$DOCKER_LOG"
case "$*" in
  *"compose exec"*) exit "${STUB_RELOAD_RC:-0}" ;;
esac
exit 0
"""

FLOCK_STUB = """#!/bin/bash
# 桩 flock：no-op（macOS 无 flock；锁语义由 issue #4767 核清，本单未改动 flock 相关行 ——
# 静态判据 judge_lock_intact 覆盖「锁仍在 + 新增段在锁内」）
exit 0
"""

TIMEOUT_STUB = """#!/bin/bash
# 桩 timeout：只透传（测的是 deploy.sh 的编排，不是 timeout 本身）
shift
exec "$@"
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _make_src_tar(dest: Path) -> None:
    """造一个 `migao-main/deploy/swas/*` 的 tar（配合 `--strip-components=1`）。"""
    stage = dest.parent / "stage" / "migao-main" / "deploy" / "swas"
    stage.mkdir(parents=True, exist_ok=True)
    for name in ("docker-compose.yml", "docker-compose.bluegreen.yml", "nginx.conf"):
        shutil.copy(REPO_ROOT / "deploy" / "swas" / name, stage / name)
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(dest.parent / "stage" / "migao-main", arcname="migao-main")


def _prepare(tmp_path: Path, script_text: str) -> tuple:
    """沙箱：脚本副本（改写绝对路径）+ 桩 bin + 源码 tar + .env 文件。"""
    work = tmp_path / "opt-migao-deploy"
    work.mkdir(exist_ok=True)
    text = script_text
    # 绝对路径改写（同 test_swas_deploy_ci_bootstrap.py 的既有手法）：只改**路径**，不改逻辑
    text = text.replace("/opt/migao-deploy", str(work))
    text = text.replace("/tmp/migao-deploy.lock", str(work / "deploy.lock"))
    text = text.replace("/tmp/hc_", f"{work}/hc_")
    script = work / "deploy.sh"
    script.write_text(text, encoding="utf-8")
    # 配置自愈/fail-closed 前置：显式声明 SMS_BYPASS_CODE（否则脚本按设计中止）
    (work / ".env.admin-api").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    (work / ".env.ai-agent").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    tar_path = tmp_path / "src.tar.gz"
    _make_src_tar(tar_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_exe(bin_dir / "curl", CURL_STUB)
    _write_exe(bin_dir / "docker", DOCKER_STUB)
    _write_exe(bin_dir / "flock", FLOCK_STUB)
    _write_exe(bin_dir / "timeout", TIMEOUT_STUB)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    return work, script, bin_dir, state, tar_path


def _run(tmp_path: Path, script_text: str, *, hc: dict, extra_env: dict | None = None):
    """跑脚本；`hc` = {端口: 状态码}（未列出的端口一律 200）。"""
    work, script, bin_dir, state, tar_path = _prepare(tmp_path, script_text)
    for port, code in hc.items():
        (state / f"hc-{port}").write_text(str(code), encoding="utf-8")
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "HC_STATE": str(state),
        "STUB_TAR": str(tar_path),
        "HC_RETRIES": "2",
        "HC_INTERVAL_SECONDS": "0",
        # /proc/meminfo 在 macOS 不存在 ⇒ 预检恒判「0MB」；执行式场景把门槛设为 0 以聚焦编排，
        # 「预检不足即中止」由独立场景（BG_MEM_NEED_MB=999999）覆盖。
        "BG_MEM_NEED_MB": "0",
        "BG_OFF_FILE": str(work / ".blue-green-off"),
        **(extra_env or {}),
    }
    proc = subprocess.run(
        ["bash", str(script), "sha-test"],
        cwd=str(work), env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, docker_log.read_text(encoding="utf-8")


def _old_form_script(text: str) -> str:
    """把蓝绿段**还原成旧写法**（用于反向红证：证明判据有判别力）。

    切点 = `echo "== 2.5 严格蓝绿预验证` 到 nginx 重载行（**保留**上方的辅助函数定义 ⇒
    `wait_healthy` 仍可用，第 3 步健康检查照跑）—— 还原后的脚本 = 本 PR 之前的行为：
    **先批量替换容器，再健康检查**。
    """
    i_start = text.find('echo "== 2.5 严格蓝绿预验证')
    assert i_start > 0, "反空跑锚点：找不到蓝绿段起点"
    end_line = "docker compose exec -T nginx nginx -s reload || docker compose restart nginx"
    i_end = text.find(end_line)
    assert i_end > i_start, "反空跑锚点：蓝绿段边界定位失败"
    out = text[:i_start] + OLD_FORM_SNIPPET + text[i_end + len(end_line):]
    assert out != text, "还原旧写法没有改变文本（空跑）"
    return out


def test_old_form_reconstruction_goes_red_statically():
    """判别力（静态）：还原成旧写法 ⇒ `judge_no_batch_replace` 必红。"""
    old = _old_form_script(read_deploy_sh())
    v = judge_no_batch_replace(old)
    assert v, "还原成旧写法后判据没红（判据无判别力）"
    assert any("批量替换" in x for x in v), v


def test_exec_green_unhealthy_keeps_old_container(tmp_path):
    """🔴 红证（issue #4785 验收判据）：**新容器健康检查失败 ⇒ 旧容器仍在服务**。

    注入：admin-api 的 green 容器健康检查返回 503（= 新镜像起不来）。
    断言：docker 桩日志里**没有**正式容器替换、**没有**停删旧容器、nginx 未被触碰，且 exit 1。
    """
    proc, log = _run(tmp_path, read_deploy_sh(), hc={18080: 503})
    assert proc.returncode != 0, f"green 不健康时脚本仍返回 0（假绿）\n{proc.stdout}"
    lines = [ln for ln in log.splitlines() if ln.strip()]
    canon = [ln for ln in lines if re.search(r"up -d --no-deps admin-api$", ln)]
    assert not canon, f"旧容器被替换了（正是事故机理）：\n" + "\n".join(canon)
    assert not any(re.search(r"compose (stop|rm|down|kill)\b", ln) and "-green" not in ln for ln in lines), (
        "日志里出现对正式容器的停/删操作：\n" + "\n".join(lines)
    )
    assert not any("up -d --no-deps nginx" in ln for ln in lines), "nginx 被更新了（说明流程没在失败处停住）"
    assert any(re.search(r"up -d --no-deps admin-api-green", ln) for ln in lines), (
        "green 容器根本没起（判据没走到该走的地方）:\n" + "\n".join(lines)
    )
    assert any(re.search(r"rm -sf .*admin-api-green", ln) for ln in lines), "失败的 green 没有被清理"
    assert "旧容器保持不动" in proc.stdout, f"输出里没有「旧容器保持不动」的明确提示：\n{proc.stdout}"
    # 旧容器仍在服务的**可验证判据**：没有任何一条命令作用在正式 admin-api 容器上
    assert not any(re.search(r"--no-deps admin-api(?!-green)", ln) and "up -d" in ln for ln in lines)


def test_exec_old_form_replaces_before_health_check(tmp_path):
    """🔴 反向红证（判别力）：还原成旧写法 ⇒ 同一次注入下**必然先替换正式容器**。

    这一条证明上一条判据**不是空断言**：同样的「新镜像不健康」，旧写法就是把旧容器换掉
    （2026-09-21 事故的机理），而新写法不会。
    """
    proc, log = _run(tmp_path, _old_form_script(read_deploy_sh()), hc={8080: 503})
    assert proc.returncode != 0
    assert any("up -d --no-deps nginx admin-api ai-agent admin-web" in ln for ln in log.splitlines()), (
        "旧写法居然没有批量替换容器（判据锚点已过期）:\n" + log
    )
    assert "旧容器保持不动" not in proc.stdout


def test_exec_happy_path_switches_after_green_is_healthy(tmp_path):
    """正向：green 健康 ⇒ 才替换正式容器 ⇒ 再删 green ⇒ nginx reload；全程 exit 0。"""
    proc, log = _run(tmp_path, read_deploy_sh(), hc={})
    assert proc.returncode == 0, f"正常路径没通过：\n{proc.stdout}\n{proc.stderr}"
    lines = [ln for ln in log.splitlines() if ln.strip()]
    i_green = next(i for i, ln in enumerate(lines) if re.search(r"up -d --no-deps admin-api-green", ln))
    i_canon = next(i for i, ln in enumerate(lines) if re.search(r"up -d --no-deps admin-api$", ln))
    i_rm = next(
        i for i, ln in enumerate(lines) if re.search(r"rm -sf admin-api-green$", ln)
    )
    assert i_green < i_canon < i_rm, f"顺序不对（green → 正式 → 删 green）：\n" + "\n".join(lines)
    assert any("compose exec -T nginx nginx -s reload" in ln for ln in lines), "nginx 没有走优雅重载"
    assert any("up -d --no-deps nginx" in ln for ln in lines), "nginx 没有更新"
    assert "蓝绿预验证结束： admin-api ai-agent admin-web" in proc.stdout, proc.stdout


def test_exec_nginx_reload_falls_back_to_restart(tmp_path):
    """reload 失败 ⇒ 回落 restart（= 改动前行为，不引入新的坏路径）。"""
    proc, log = _run(tmp_path, read_deploy_sh(), hc={}, extra_env={"STUB_RELOAD_RC": "1"})
    assert proc.returncode == 0, proc.stdout
    lines = log.splitlines()
    assert any("compose exec -T nginx nginx -s reload" in ln for ln in lines), "没有先试 reload"
    assert any(ln.endswith("compose restart nginx") for ln in lines), "reload 失败后没有回落 restart"


def test_exec_insufficient_memory_aborts_without_touching_containers(tmp_path):
    """内存预检不足 ⇒ **一个容器都不许起**（fail-closed：旧容器保持不动）。"""
    proc, log = _run(tmp_path, read_deploy_sh(), hc={}, extra_env={"BG_MEM_NEED_MB": "999999"})
    assert proc.returncode != 0, "内存不足时脚本仍返回 0"
    assert not any("up -d" in ln for ln in log.splitlines()), (
        "内存不足却仍然起了容器：\n" + log
    )
    assert "旧容器保持不动" in proc.stdout, proc.stdout


def test_exec_escape_hatch_skips_blue_green(tmp_path):
    """应急开关：存在 `.blue-green-off` ⇒ 跳过蓝绿（走 #4767 兜底路径），且**不静默**。"""
    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".blue-green-off").write_text("", encoding="utf-8")
    proc, log = _run(tmp_path, read_deploy_sh(), hc={})
    assert proc.returncode == 0, proc.stdout
    assert "跳过蓝绿预验证" in proc.stdout, proc.stdout
    lines = log.splitlines()
    assert not any("admin-api-green" in ln for ln in lines), "应急开关没有真正跳过蓝绿"
    # ⚠️ 关键：应急开关只许跳过「预验证」，**不许**连带跳过更新本身（否则 = 静默不部署）
    for svc in ("admin-api", "ai-agent", "admin-web"):
        assert any(re.search(rf"up -d --no-deps {svc}$", ln) for ln in lines), (
            f"应急开关下 {svc} 正式容器没有被更新（静默不部署）：\n" + log
        )
