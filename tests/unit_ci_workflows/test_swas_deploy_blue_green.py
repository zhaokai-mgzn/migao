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

## issue #4828：**成功路径**残留窗口 ⇒ 上游切换打到 0（本文件新增的那批判据）

#4785 的蓝绿只把**失败路径**打到 0；**成功路径**仍有「替换正式容器 + JVM 启动 + nginx reload」的
窗口，当时**如实登记**为「与改动前同量级、未变差」。本单消灭它：`nginx.conf` 给每个后端一个
`upstream` 块（**每服务恰好一行 `server`**），`deploy.sh` 在**切流量**时只就地改那一行：

```
①   green 起 + `wait_healthy`（#4785 不动）
①.5 green 健康 ⇒ 改一行上游（正式色 → green 色）+ `nginx -t` 校验 + reload ⇒ 流量到 green
②   `docker compose up -d --no-deps <svc>`（替换正式容器 —— 这段空档**没有请求**打向它）
②.5 正式容器健康（`wait_healthy`）⇒ 改回正式色 + 校验 + reload
③   才 `rm -sf <svc>-green`
```

真机读数（`aliyun swas-open run-command` **只读探测**，2026-09-20 17:18 CST，原文见 PR body）：
`Started AdminApiApplication in 50.713 seconds (process running for 54.15)` ⇒ 窗口的**主体是 JVM 启动
≈51s**（容器 healthcheck = `StartPeriod 60s / Interval 30s / Timeout 5s / Retries 3`，与主会话抓到的
「正式容器 health: starting + 502」逐字吻合）；`wait_healthy` 跑在第 ② 步**之后** ⇒ 它只能事后发现，
覆盖不了这段。**窗口为什么是"几十秒"而不是"几秒"**：nginx 只在 §2.6 reload 一次，而它排在**整个**
per-service 循环之后 ⇒ 三服务的窗口一直重叠到那一刻，`api.migaozn.com` 的 502 = 新容器 JVM 启动耗时。

四条只读实证（每条都对应本设计的一个前提，**含反向对照**）：
① 现网联机配置 = 直连 `proxy_pass http://<svc>:<port>`（`upstream` 块数 = 0）⇒ 本 PR 之前没有可切的上游层；
② 主配置 `include /etc/nginx/conf.d/*.conf;` 且**没有 `resolver` 指令** ⇒ 上游在**配置加载时**解析并缓存
   （改 IP 必须 reload 才生效）—— 这就是 502 的根因，也是本设计「切流量 = 改一行 + reload」的立足点；
③ **反向对照（ⓑ 护栏真机自证）**：`upstream { server admin-api-green:8080; }` 且该容器不存在时，
   `nginx -t` 报 `[emerg] host not found in upstream "admin-api-green:8080"` **RC=1**；指向存在的
   `admin-api:8080` **RC=0**；随机名 RC=1 ⇒ **候选先校验后落盘**这条护栏在真机上确实拦得住
   「切到一个不存在的 green」。
   ⚠️ **诚实登记**：本轮第一次探测用了 `sed 's#server admin-api:8080;#…# '` 作对照，而现网配置里
   **根本没有 `upstream` 块**（`upstream_blocks=0`）⇒ sed 是 no-op ⇒ 候选 = 原文 ⇒ 恒 RC=0。
   **那是假对照，不是"护栏失效"**。上面的 ③ 是重做的**真**对照（显式构造 `upstream` 块）。
④ 单文件 bind mount 的同 inode 事实：宿主 `stat` 与容器内 `stat` 同为 `1831445`
   ⇒ 原地改写（`cat >`）生效、`mv`/`sed -i` 会换 inode 且**容器不报错**（docs/wiki/CI-CD.md 已登记）。
⑤ compose 的**替换**语义现场：`docker events` 依次是 `create migao-deploy-admin-api-green-1`
   → `create ef706d9748d7_migao-deploy-admin-api-1`（旧容器被**改名**后重建）⇒ 「旧容器先走」得到实证。
⑥ 远端 `deploy.sh`（497 行）仍是有 §2.5/§2.7、**无**上游切换的版本 ⇒ 现网行为 = #4785 的行为，
   本单尚未上线（改动只有合并且真正跑一次部署才会生效）。

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
3. **上游切换自身坏路径的对消**（判据 ⑨，本单第二版新增）：流量切到 green 之后，"运行中的 nginx
   还指着上一轮的 green"会变成一个新的、更糟的坏路径（`rm -sf green` = 删掉唯一在服务的后端
   ⇒ **全站所有域名同时 502**）。七条不变量各自可独立判红：
   快照必须在第 1 步覆盖配置**之前**读（否则恒为正式色 = **死代码**）；快照必须文件 ∪ 备份都看
   （②.5「先写文件、再 reload」之间被强杀时只有备份里还留着 green）；收敛必须排在删 residual green
   之前；收敛必须 fail-closed（正式容器不健康 ⇒ `exit 1` 且不碰任何容器）；收敛必须用**强制 reload**
   （`bg_reload_nginx`）而不是会短路的 `bg_switch_upstream`；切换必须有「nginx 在跑」的可行性前提
   （否则**首次部署**必红）；干净收口必须把备份归一化成正式色（否则收敛每轮都跑、误伤正常部署）。
4. **注入式红证**（每条判据各自可独立判红，且**注入必须真的落到文本上**，否则显式失败）。
5. **执行式红证**（桩 `docker` / `curl` / `flock` / `timeout`，跑**真实** `deploy.sh` 的**真实码路**）：
   - 注入「新容器（green）健康检查失败」⇒ 断言 docker 桩日志里**没有**任何正式容器替换、
     **没有**停删旧容器、且 `exit 1`（= **旧容器仍在服务**）；
   - 反向红证（判别力）：把蓝绿段**还原成旧写法** ⇒ 同一次注入下**必然**先替换正式容器 ⇒ 判据**有判别力**；
   - 内存预检不足 ⇒ 一个容器都不许起；
   - **残留 green 的收敛**：预置「上一轮把流量留在 green 上」的运行态 ⇒ 断言**删 green 之前**已经
     reload；正式容器不健康 ⇒ **一个容器操作都不做** + `exit 1`；并把收敛段删掉做**反向红证**
     （同一份注入下**必然**在任何 reload 之前就删 green）；
   - nginx 未在跑（首次部署）⇒ **跳过上游切换**且部署照常完成（钉「切换成了首次部署的硬前提」这个回归）。

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
# issue #4828：上游切换的锚点（nginx.conf 的 upstream 名 + deploy.sh 的两个切换调用）
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
UPSTREAMS = {"admin-api": "migao_admin_api", "ai-agent": "migao_ai_agent", "admin-web": "migao_admin_web"}
GREEN_SWITCH = 'bg_switch_upstream "$svc" green'
OFFICIAL_SWITCH = 'bg_switch_upstream "$svc" official'
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


def read_nginx_conf() -> str:
    """读 `deploy/swas/nginx.conf` 的**当前文本**（不读 `origin/main` 的可变引用 —— §18.3）。"""
    assert NGINX_CONF.is_file(), f"反空跑锚点：目标配置不存在 → {NGINX_CONF}"
    text = NGINX_CONF.read_text(encoding="utf-8")
    assert "proxy_pass" in text, "反空跑锚点：nginx.conf 里没有 proxy_pass（判据已过期）"
    return text


def upstream_server_lines(nginx_text: str) -> dict:
    """解析 `upstream <名> { ... }` 块里的 `server` 行 ⇒ {upstream 名: [行, ...]}。

    只认**块内**的 `server` 行（`server` 后必须跟空白）⇒ `server_name` / `location` 不会被误收。
    """
    blocks: dict = {}
    cur = None
    for ln in nginx_text.splitlines():
        m = re.match(r"^upstream\s+(\S+)\s*\{\s*$", ln)
        if m:
            cur = m.group(1)
            blocks[cur] = []
            continue
        if cur is None:
            continue
        if ln.strip() == "}":
            cur = None
            continue
        if re.match(r"^[ \t]*server[ \t]+", ln):
            blocks[cur].append(ln)
    return blocks


def upstream_hosts(conf_text: str) -> dict:
    """{compose 服务名: 'admin-api:8080' | 'admin-api-green:8080'} —— 从 upstream 块反推当前上游。"""
    svc_of = {v: k for k, v in UPSTREAMS.items()}
    out = {}
    for name, lines in upstream_server_lines(conf_text).items():
        svc = svc_of.get(name)
        if svc and lines:
            out[svc] = lines[0].strip()[len("server "):].rstrip(";")
    return out


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


def judge_upstream_indirection(nginx_text: str, deploy_text: str, base: dict) -> list:
    """⑦ issue #4828：`nginx.conf` 必须给每个后端一个**可切换的 upstream 间接层**，且指向与容器名一致。

    判据（每条都对应一个「写坏 = 全站所有域名同时挂」的具体形态）：
      · 恰好 3 个 `upstream` 块，名字 = `migao_admin_api` / `migao_ai_agent` / `migao_admin_web`；
      · 每块内**恰好 1 行** `server <compose 服务名>:<容器端口>;`（切换判据按这一点算；多一行就切不准）；
      · 上游指向必须与 `docker-compose.yml` 的服务名 / 容器端口**一致**（写错名字 = 全站 502）；
      · 所有 `proxy_pass` 必须走 upstream 名（谁敢留一条直连 `host:port` ⇒ 那个 location 切不动）；
      · `#2661` 的 `X-Forwarded-For $remote_addr` 覆盖头必须仍是 6 处（不许顺手削弱）；
      · `deploy.sh` 的切换机制各就位，且**写盘是原地改写**（换 inode = 容器读旧文件且不报错）。
    """
    v = []
    blocks = upstream_server_lines(nginx_text)
    if set(blocks) != set(UPSTREAMS.values()):
        v.append(f"upstream 块集合 = {sorted(blocks)}，期望 {sorted(UPSTREAMS.values())}")
    for svc, name in UPSTREAMS.items():
        lines = blocks.get(name, [])
        if len(lines) != 1:
            v.append(f"upstream {name} 的 `server` 行有 {len(lines)} 条（必须恰好 1 条 —— 切换判据按这一点算）")
            continue
        ports = [str(p).split(":")[-1] for p in (base["services"].get(svc, {}).get("ports") or [])]
        if not ports:
            v.append(f"docker-compose.yml 里 {svc} 没有 ports（判据锚点丢了）")
            continue
        want = f"server {svc}:{ports[0]};"
        got = lines[0].strip()
        if got != want:
            v.append(f"upstream {name} 指向 {got!r}，期望 {want!r}（上游指向必须与容器名/容器端口一致）")
    directs = re.findall(r"proxy_pass\s+https?://([A-Za-z0-9_.\-]+):(\d+)", nginx_text)
    if directs:
        v.append(f"仍有直连 host:port 的 proxy_pass {sorted(set(directs))}（这些 location 切不动上游）")
    names = set(re.findall(r"proxy_pass\s+https?://([A-Za-z0-9_]+)\s*;", nginx_text))
    if names != set(UPSTREAMS.values()):
        v.append(f"proxy_pass 引用的 upstream 名 = {sorted(names)}，期望 {sorted(UPSTREAMS.values())}")
    if len(re.findall(r"proxy_pass\s", nginx_text)) < 6:
        v.append("proxy_pass 少于 6 处（改动把某些 location 的上游弄丢了）")
    if nginx_text.count("proxy_set_header X-Forwarded-For $remote_addr;") != 6:
        v.append("`X-Forwarded-For $remote_addr` 不再是 6 处（#2661 的防伪造护栏被动了）")
    for token in ("nginx_conf_candidate", "nginx_conf_validate", "nginx_conf_write_in_place",
                  "bg_switch_upstream", "bg_restore_upstreams_at_exit", "upstream_host"):
        if token not in deploy_text:
            v.append(f"deploy.sh 里缺 `{token}`（上游切换机制不完整）")
    body = function_body(deploy_text, "nginx_conf_write_in_place")
    if 'cat > "$NGINX_CONF"' not in body:
        v.append("`nginx_conf_write_in_place` 不是 `cat > $NGINX_CONF` 的**原地改写**（同 inode 是硬要求）")
    for bad in ("mv ", "sed -i"):
        if bad in body:
            v.append(f"写盘路径出现 `{bad.strip()}` —— 换 inode ⇒ 容器读到的还是旧文件**且不报错**")
    return v


def judge_switch_sequence(deploy_text: str) -> list:
    """⑧ issue #4828：切换序列的不变量（顺序 + 前提 + 退出兜底 + 残留自愈）。

    · 切到 green **之前**：green 必须已过 `wait_healthy`（切流量前先证明新容器健康）；
    · 切回正式色 **之前**：正式容器必须已过 `wait_healthy`（切回去之前先证明它能服务）；
    · 删 green **之前**：上游必须已切回正式色（否则删的是唯一在服务的后端）；
    · 两个切换都必须被 `BG_SKIP=0` 包住（应急开关下没有 green，切换必然失败）；
    · EXIT trap 必须把上游写回正式色（正式容器不健康时**保持指向 green 且不删它**）；
    · 残留切换自愈必须排在「删残留 green」**之前**（SIGKILL 之后先删 green = 唯一后端消失）；
    · 先校验后落盘（候选 stdin → `nginx -t`），落盘后**再** `nginx -t` 一次。
    """
    v = []
    # ⚠️ 锚点必须**唯一**：`bg_switch_upstream "$svc" official` 在脚本里出现 3 次（EXIT trap / 残留自愈 /
    #    ②.5 步骤）⇒ 位置判据锚在**步骤注释**上，调用是否存在另判（否则判据会锚到自愈那一次 ⇒ 假红）。
    step_green = "  # ── ①.5 切流量到 green"
    step_official = "  # ── ②.5 切回正式色"
    anchors = {
        "green 健康检查": ('if ! wait_healthy "$GPORT" "$GREEN" "$GPATH"; then', "find"),
        "①.5 切到 green（步骤）": (step_green, "find"),
        "正式容器替换": (CANON_UP, "find"),
        "正式容器健康检查": ('if ! wait_healthy "$(svc_port "$svc")" "$svc" "$GPATH"; then', "find"),
        "②.5 切回正式色（步骤）": (step_official, "find"),
        "删 green（循环第 ③ 步）": ('$BG_COMPOSE rm -sf "$GREEN"', "rfind"),
    }
    idx = {}
    for label, (token, how) in anchors.items():
        i = deploy_text.rfind(token) if how == "rfind" else deploy_text.find(token)
        idx[label] = i
        if i < 0:
            v.append(f"找不到「{label}」的锚点（判据已过期）")
    for label, token in (("①.5 切到 green（步骤）", GREEN_SWITCH), ("②.5 切回正式色（步骤）", OFFICIAL_SWITCH)):
        i = idx[label]
        if i >= 0:
            step_text = deploy_text[i:deploy_text.find("\n  fi\n", i) if deploy_text.find("\n  fi\n", i) > i else i + 600]
            if token not in step_text:
                v.append(f"「{label}」里没有 `{token}`（切换调用不在该步骤内）")
    if idx["green 健康检查"] >= 0 and idx["①.5 切到 green（步骤）"] >= 0 \
            and idx["green 健康检查"] > idx["①.5 切到 green（步骤）"]:
        v.append("切到 green 发生在 green 健康检查**之前**（切流量前必须先证明新容器健康）")
    if idx["正式容器健康检查"] >= 0 and idx["②.5 切回正式色（步骤）"] >= 0 \
            and idx["正式容器健康检查"] > idx["②.5 切回正式色（步骤）"]:
        v.append("切回正式色发生在正式容器健康检查**之前**（切回前必须先证明正式容器能服务）")
    if idx["②.5 切回正式色（步骤）"] >= 0 and idx["删 green（循环第 ③ 步）"] >= 0 \
            and idx["②.5 切回正式色（步骤）"] > idx["删 green（循环第 ③ 步）"]:
        v.append("删 green 发生在切回正式色**之前**（= 删掉唯一在服务的后端）")
    for call in (GREEN_SWITCH, OFFICIAL_SWITCH):
        want = f'if [ "$BG_SWITCH_ON" = "1" ]; then\n    if ! {call}; then'
        if want not in deploy_text:
            v.append(
                f"`{call}` 没有被 `BG_SWITCH_ON=1` 包住（应急开关下没有 green、nginx 未跑时切了也无意义"
                " ⇒ 这两种情况都必须**一个字都不改配置**；`BG_SWITCH_ON=1` 蕴含 `BG_SKIP=0`）"
            )
    if "trap 'bg_restore_upstreams_at_exit; flock -u 9' EXIT" not in deploy_text:
        v.append("EXIT trap 没有挂 `bg_restore_upstreams_at_exit`（可捕获的退出路径会把上游留在 green）")
    if "trap 'flock -u 9' EXIT" not in deploy_text:
        v.append("开头的 `trap 'flock -u 9' EXIT` 被删了（脚本前半段的锁释放没了）")
    if "bg_official_healthy_now" not in deploy_text:
        v.append("EXIT trap 没有「正式容器此刻健康吗」的判据（不健康时写回正式色 = 当场 502）")
    if "刻意不删" not in deploy_text:
        v.append("EXIT trap 的「保持指向 green」分支没有说明该 green 容器**不许删**（它是唯一后端）")
    body = function_body(deploy_text, "bg_switch_upstream")
    if "| nginx_conf_validate" not in body or "| nginx_conf_write_in_place" not in body:
        v.append("`bg_switch_upstream` 没有「候选 stdin → 校验 → 落盘」两步")
    elif body.find("| nginx_conf_validate") > body.find("| nginx_conf_write_in_place"):
        v.append("落盘发生在候选校验**之前**（候选没验过就上线了）")
    if "docker compose exec -T nginx nginx -t" not in body:
        v.append("落盘后没有再 `nginx -t` 一次（没校验 nginx 真正加载的那份文件）")
    if body.count('cat "$NGINX_CONF_BAK" | nginx_conf_write_in_place') < 2:
        v.append(
            "落盘后的 `nginx -t` / `nginx -s reload` 失败时没有**就地写回上一版备份**"
            "（坏配置会留在联机文件上 —— 那正是「写坏 = 全站挂」的形态）"
        )
    if "cat > \"$NGINX_CONF\"" not in function_body(deploy_text, "nginx_conf_write_in_place"):
        v.append("落盘不是原地改写（见 judge_upstream_indirection 的同族判据）")
    return v


def judge_upstream_switch_rails(deploy_text: str) -> list:
    """⑨ issue #4828：把「上游切换」**自身**引入的坏路径逐条对消（不变量，不是某行的措辞）。

    切换流量到 green 解决了原窗口，但它同时引入一个新的、更糟的坏路径：
    「运行中的 nginx 仍指着上一轮的 green」时把 green 删掉 ⇒ **删的是唯一还在服务的后端**
    （= 全站所有域名同时 502）。本判据钉住七条对消措施：

      1. 残留切换快照必须在**第 1 步覆盖配置之前**读 —— 第 1 步每次都把 canonical（正式色）配置
         抄进 `$NGINX_CONF`，之后快照恒为「正式色」⇒ 判据退化成**死代码**（本单第一版的形态）；
      2. 快照必须同时看 `$NGINX_CONF` 与 `$NGINX_CONF_BAK` —— ②.5 是「先写文件、再 reload」，
         在两者之间被强杀时**文件已是正式色而运行态仍指着 green**（green 因为第 ③ 步没跑到而仍存活）
         ⇒ 只看文件会漏判；
      3. 收敛必须排在 `rm -sf $BG_GREENS` **之前**；
      4. 收敛必须 fail-closed：正式容器不健康 ⇒ `exit 1` 且**不碰任何容器**（green 继续服务）；
      5. 收敛必须用**强制 reload**（`bg_reload_nginx`）而不是 `bg_switch_upstream` —— 后者在
         「文件已等于目标」时短路 ⇒ **不 reload** ⇒ 运行态收不回来（第一版的第二个漏洞）；
      6. 上游切换必须有**可行性前提**（真的有一个在跑的 nginx）—— 否则**首次部署**（nginx 尚未起、
         且此刻起不来：canonical 上游容器都还不存在）会在切换步骤必然失败；
      7. 干净收口后必须把备份归一化成正式色 —— 否则第 2 条的快照**每轮都为真** ⇒ 收敛段每轮都跑，
         而它第 4 条的 fail-closed 分支会**误伤正常部署**（把「某个非关键服务此刻不健康」变成「部署被阻断」）。
    """
    v = []
    i_snap = deploy_text.find("BG_PREV_GREEN=$(")
    i_sync = deploy_text.find("cp src/deploy/swas/nginx.conf ./nginx/nginx.conf")
    if i_snap < 0:
        v.append("缺少残留切换快照（`BG_PREV_GREEN=$(...)`）—— 强杀之后无法判「流量是否还在 green 上」")
    if i_sync < 0:
        v.append("找不到第 1 步的配置同步（`cp src/deploy/swas/nginx.conf ./nginx/nginx.conf`）")
    if i_snap >= 0 and i_sync >= 0:
        if i_snap > i_sync:
            v.append(
                "残留切换快照排在**第 1 步覆盖配置之后** —— 那时文件已是正式色 ⇒ 快照恒为空 ⇒ "
                "判据是**死代码**（必须先读、再覆盖）"
            )
        snap_stmt = deploy_text[i_snap:i_snap + 400]
        for token in ('"$NGINX_CONF"', '"$NGINX_CONF_BAK"'):
            if token not in snap_stmt:
                v.append(
                    f"残留切换快照没有读 {token}（文件 ∪ 上一版备份都要看：②.5「先写文件、再 reload」"
                    " 之间被强杀时，只有备份里还留着 green ⇒ 漏判 = 删掉唯一在服务的 green）"
                )
        if "-green" not in snap_stmt:
            v.append("残留切换快照没有按 `-green` 形态识别（判据锚点丢了）")

    i_conv = deploy_text.find("② 残留切换收敛")
    # ⚠️ 锚点必须带 `$BG_COMPOSE` 前缀：注释里也出现过裸 `rm -sf $BG_GREENS`（说明文字），
    #    用裸命令当锚点会锚到**注释**上 ⇒ 判据假红（既有判据就这样红过一次）。
    i_clean = deploy_text.find('$BG_COMPOSE rm -sf $BG_GREENS')
    if i_conv < 0:
        v.append("缺少「残留切换收敛」（上一轮把流量留在 green 上时先删 green ⇒ 唯一后端消失、全站 502）")
    elif i_clean < 0:
        v.append("找不到残留 green 清理（`$BG_COMPOSE rm -sf $BG_GREENS`）")
    elif i_conv > i_clean:
        v.append("「残留切换收敛」排在删残留 green **之后**（顺序反了 —— 先删就没得救了）")
    else:
        blk = deploy_text[i_conv:i_clean]
        if "exit 1" not in blk:
            v.append("残留切换收敛不是 fail-closed（正式容器不健康时必须 `exit 1`、不碰任何容器）")
        if "不碰任何容器" not in blk:
            v.append("残留切换收敛没有明确「不碰任何容器」（读者会以为它仍会去动容器）")
        if "bg_official_healthy_now" not in blk:
            v.append("残留切换收敛没有先判「正式容器此刻是否健康」就 reload（不健康时收回正式色 = 当场 502）")
        if "bg_reload_nginx" not in blk:
            v.append(
                "残留切换收敛没有用**强制 reload**（`bg_reload_nginx`）—— 用 `bg_switch_upstream` 会在"
                "「文件已等于目标」时短路 ⇒ **不 reload** ⇒ 运行态收不回来（这是本单第一版的漏洞）"
            )
        if OFFICIAL_SWITCH in blk:
            v.append("残留切换收敛里出现 `bg_switch_upstream ... official`（会短路、不 reload）")
    body = function_body(deploy_text, "bg_reload_nginx")
    if "nginx -s reload" not in body:
        v.append("`bg_reload_nginx` 没有 `nginx -s reload`")
    if "nginx -t" not in body:
        v.append("`bg_reload_nginx` reload 之前没有 `nginx -t`（配置坏了会当场把 worker 换掉）")
    if "cand" in body or "NGINX_CONF_BAK" in body:
        v.append("`bg_reload_nginx` 里出现「比较/短路/写回」逻辑 —— 它必须**无条件 reload**（否则收不回来）")

    probe = "if docker compose exec -T nginx nginx -t >/dev/null 2>&1; then BG_NGINX_UP=1; fi"
    if probe not in deploy_text:
        v.append(
            "缺少上游切换的**可行性前提**（在 nginx 容器里 `nginx -t`）—— 首次部署时 nginx 尚未起、"
            "且此刻起不来（上游容器还不存在）⇒ 切换步骤必然失败（D4 回归）"
        )
    if "BG_SWITCH_ON=1" not in deploy_text:
        v.append("缺少上游切换开关 `BG_SWITCH_ON`（`BG_SKIP` / `BG_NGINX_UP` 两个前提必须收口到一个变量）")
    if deploy_text.count('if [ "$BG_SWITCH_ON" = "1" ]; then') < 2:
        v.append("`BG_SWITCH_ON` 没有门住两个切换点（①.5 切 green + ②.5 切回正式色）")
    if '[ "$BG_SWITCH_ON" = "1" ] &&' not in deploy_text:
        v.append("残留切换收敛没有被 `BG_SWITCH_ON` 门住（nginx 未在跑时也会去收敛/判断正式容器）")

    # ⚠️ 归一化的锚点必须用**带门的整句**：`cp "$NGINX_CONF" "$NGINX_CONF_BAK"` 在
    #    `bg_switch_upstream` 里也出现一次（那是「切换前留上一版备份」）⇒ 用裸 `cp` 当锚点会锚到
    #    函数体那一处 ⇒ 位置判据恒判红（判据自身缺陷，本判据第一版就这样红过）。
    norm_gate = 'if [ "$BG_SWITCHED" = "" ] && [ -f "$NGINX_CONF" ]; then'
    i_norm = deploy_text.find(norm_gate)
    i_reload26 = deploy_text.find("docker compose exec -T nginx nginx -s reload || docker compose restart nginx")
    if i_norm < 0:
        v.append(
            "缺少「收口归一化」（干净收口后把备份写成正式色）—— 否则快照每轮都为真 ⇒ 收敛段每轮都跑，"
            "其 fail-closed 分支会误伤正常部署"
        )
    else:
        if 'cp "$NGINX_CONF" "$NGINX_CONF_BAK"' not in deploy_text[i_norm:i_norm + 200]:
            v.append('「收口归一化」里没有写上一版备份（`cp "$NGINX_CONF" "$NGINX_CONF_BAK"`）')
        if i_reload26 < 0 or i_norm < i_reload26:
            v.append("「收口归一化」没有排在 2.6 的 nginx reload **之后**（那时上游才真正全部回到正式色）")
    return v


def all_violations(text: str, base: dict, bg: dict, nginx_text: str) -> list:
    return (
        judge_no_batch_replace(text)
        + judge_single_hc_judgement(text)
        + judge_fail_keeps_old_container(text)
        + judge_lock_intact(text)
        + judge_safety_rails(text)
        + judge_bg_compose_antidrift(base, bg, text)
        + judge_upstream_indirection(nginx_text, text, base)
        + judge_switch_sequence(text)
        + judge_upstream_switch_rails(text)
    )


# ══════════════════════════════════════════════════════════════════════════
# 一、静态判据（读脚本当前文本）
# ══════════════════════════════════════════════════════════════════════════

def test_real_files_satisfy_every_judgement():
    text = read_deploy_sh()
    base, bg = read_yaml(BASE_COMPOSE), read_yaml(BG_COMPOSE)
    v = all_violations(text, base, bg, read_nginx_conf())
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


def test_upstream_indirection_is_clean_on_the_real_files():
    """⑦ #4828 的上游间接层判据在真实文件上必须干净（各自独立判红，避免被「整体红」掩盖）。"""
    v = judge_upstream_indirection(read_nginx_conf(), read_deploy_sh(), read_yaml(BASE_COMPOSE))
    assert not v, "上游间接层判据判红：\n- " + "\n- ".join(v)


def test_switch_sequence_is_clean_on_the_real_script():
    """⑧ #4828 的切换序列判据在真实脚本上必须干净。"""
    v = judge_switch_sequence(read_deploy_sh())
    assert not v, "切换序列判据判红：\n- " + "\n- ".join(v)


def test_upstream_switch_rails_are_clean_on_the_real_script():
    """⑨ #4828 第二版：上游切换**自身坏路径**的对消措施在真实脚本上必须干净（独立判红）。"""
    v = judge_upstream_switch_rails(read_deploy_sh())
    assert not v, "上游切换护栏判据判红：\n- " + "\n- ".join(v)


def test_nginx_conf_parses_as_three_switchable_upstreams():
    """🔴 反空跑锚点：判据 ⑦ 的解析器必须真的解析出 3 块、每块恰好 1 行 `server`。

    没有这一条，解析器一旦静默返回空 dict，判据 ⑦ 就会「看起来通过」而其实什么都没查。
    """
    blocks = upstream_server_lines(read_nginx_conf())
    assert set(blocks) == set(UPSTREAMS.values()), f"解析结果 = {blocks}"
    assert all(len(lines) == 1 for lines in blocks.values()), f"解析结果 = {blocks}"


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
# 二·2、注入式红证（issue #4828：上游切换的每条判据各自可独立判红）
# ══════════════════════════════════════════════════════════════════════════

def test_injection_upstream_points_to_wrong_container_goes_red():
    """注入⑩：upstream 指向一个不存在的容器名 ⇒ 必红（写错名字 = 全站所有域名 502）。"""
    injected = _inject(read_nginx_conf(), "server admin-api:8080;", "server admin-api-blue:8080;")
    assert judge_upstream_indirection(injected, read_deploy_sh(), read_yaml(BASE_COMPOSE)), "上游指向漂移后没红"


def test_injection_duplicate_upstream_server_line_goes_red():
    """注入⑪：一个 upstream 块里塞两行 `server` ⇒ 必红（切换判据按「每服务恰好一行」算）。"""
    injected = _inject(
        read_nginx_conf(),
        "upstream migao_admin_api {\n    server admin-api:8080;\n}",
        "upstream migao_admin_api {\n    server admin-api:8080;\n    server admin-api-green:8080;\n}",
    )
    assert judge_upstream_indirection(injected, read_deploy_sh(), read_yaml(BASE_COMPOSE)), "上游多出一行后没红"


def test_injection_direct_proxy_pass_goes_red():
    """注入⑫：某个 location 改回直连 `host:port` ⇒ 必红（那个 location 切不动上游）。"""
    injected = _inject(
        read_nginx_conf(), "proxy_pass http://migao_admin_api;", "proxy_pass http://admin-api:8080;"
    )
    assert judge_upstream_indirection(injected, read_deploy_sh(), read_yaml(BASE_COMPOSE)), "直连 proxy_pass 没红"


def test_injection_xff_hardening_dropped_goes_red():
    """注入⑬：删掉一处 `X-Forwarded-For $remote_addr`（#2661 防伪造护栏）⇒ 必红（不许顺手削弱）。"""
    xff_line = (
        "        proxy_set_header X-Forwarded-For $remote_addr;"
        "  # 覆盖为真实客户端 IP，防伪造（Issue #2661）\n"
    )
    injected = _inject(read_nginx_conf(), xff_line, "")
    assert judge_upstream_indirection(injected, read_deploy_sh(), read_yaml(BASE_COMPOSE)), "XFF 护栏被删后没红"


def test_injection_write_with_mv_goes_red():
    """注入⑭：写盘改成 `mv`（换 inode ⇒ 容器读到的还是旧文件**且不报错**）⇒ 必红。"""
    injected = _inject(read_deploy_sh(), '  cat > "$NGINX_CONF"\n}', '  mv "$NGINX_CONF.cand" "$NGINX_CONF"\n}')
    assert judge_upstream_indirection(read_nginx_conf(), injected, read_yaml(BASE_COMPOSE)), "写盘换成 mv 后没红"
    assert judge_switch_sequence(injected), "写盘换成 mv 后切换序列判据也没红"


def test_injection_switch_back_removed_goes_red():
    """注入⑮：删掉整个「②.5 切回正式色」步骤 ⇒ 必红（删 green 时上游还指着它 = 删掉唯一后端）。"""
    text = read_deploy_sh()
    start = text.find("  # ── ②.5 切回正式色")
    end = text.find("  # ── ③ 正式容器接棒")
    assert 0 < start < end, "反空跑锚点：找不到 ②.5 段"
    injected = text[:start] + text[end:]
    assert judge_switch_sequence(injected), "删掉切回正式色后没红"


def test_injection_switch_moved_before_green_health_check_goes_red():
    """注入⑯：把「切到 green」整段挪到 green 健康检查**之前** ⇒ 必红（先切流量再验证）。"""
    text = read_deploy_sh()
    start = text.find("  # ── ①.5 切流量到 green")
    end = text.find("  # ── ② 切换：替换正式容器")
    assert 0 < start < end, "反空跑锚点：找不到 ①.5 段"
    block = text[start:end]
    assert GREEN_SWITCH in block, "反空跑锚点：①.5 段里没有切换调用"
    cut = text[:start] + text[end:]
    anchor = cut.find('    if ! wait_healthy "$GPORT" "$GREEN" "$GPATH"; then')
    assert anchor > 0, "反空跑锚点：找不到 green 健康检查"
    injected = cut[:anchor] + block + cut[anchor:]
    assert judge_switch_sequence(injected), "把切换挪到健康检查之前后没红"


# ══════════════════════════════════════════════════════════════════════════
# 二·3、注入式红证（issue #4828 第二版：上游切换**自身坏路径**的对消措施，逐条可独立判红）
# ══════════════════════════════════════════════════════════════════════════

CONVERGE_HEAD = "  # ── ② 残留切换收敛"
CLEANUP_HEAD = "  # 残留清理：上一轮被强杀"


def _convergence_span(text: str) -> tuple:
    """定位收敛段 [start, end) —— 取不到 ⇒ 显式失败（否则下面的注入是空跑）。"""
    start = text.find(CONVERGE_HEAD)
    end = text.find(CLEANUP_HEAD)
    assert 0 < start < end, "反空跑锚点：找不到收敛段边界（判据已过期）"
    return start, end


def test_injection_residual_convergence_removed_goes_red():
    """注入⑰：删掉「残留切换收敛」⇒ 必红（强杀之后先删 green = 唯一后端消失、全站 502）。"""
    text = read_deploy_sh()
    start, end = _convergence_span(text)
    injected = text[:start] + text[end:]
    assert injected != text, "注入没有改变文本（空跑）"
    assert judge_upstream_switch_rails(injected), "删掉收敛段后没红"


def test_injection_convergence_after_cleanup_goes_red():
    """注入⑱：把收敛段挪到「删残留 green」**之后** ⇒ 必红（先删就没得救了）。"""
    text = read_deploy_sh()
    start, end = _convergence_span(text)
    block = text[start:end]
    cut = text[:start] + text[end:]
    anchor = "$BG_COMPOSE rm -sf $BG_GREENS >/dev/null 2>&1 || true\n"
    assert anchor in cut, "反空跑锚点：找不到删残留 green 那一行"
    injected = cut.replace(anchor, anchor + block, 1)
    assert injected != text, "注入没有改变文本（空跑）"
    assert judge_upstream_switch_rails(injected), "收敛段挪到删除之后没红"


def test_injection_snapshot_after_config_sync_goes_red():
    """注入⑲：把残留切换快照挪到**第 1 步覆盖配置之后** ⇒ 必红（快照恒为空 = 判据退化成死代码）。"""
    text = read_deploy_sh()
    snap_start = text.find("BG_PREV_GREEN=$(")
    assert snap_start > 0, "反空跑锚点：找不到快照语句"
    snap_end = text.find("\n\n", snap_start)
    assert snap_end > snap_start, "反空跑锚点：快照语句没有以空行收尾"
    stmt = text[snap_start:snap_end]
    cut = text[:snap_start] + text[snap_end + 2:]
    sync = "cp src/deploy/swas/nginx.conf ./nginx/nginx.conf\n"
    assert sync in cut, "反空跑锚点：找不到第 1 步的配置同步"
    injected = cut.replace(sync, sync + stmt + "\n\n", 1)
    assert injected != text, "注入没有改变文本（空跑）"
    assert judge_upstream_switch_rails(injected), "快照挪到第 1 步之后没红"


def test_injection_snapshot_without_backup_goes_red():
    """注入⑳：快照只看文件、不看备份 ⇒ 必红（②.5「先写文件、再 reload」之间被强杀会被漏判）。"""
    injected = _inject(
        read_deploy_sh(), '"$NGINX_CONF" "$NGINX_CONF_BAK" 2>/dev/null', '"$NGINX_CONF" 2>/dev/null'
    )
    assert judge_upstream_switch_rails(injected), "快照不看备份后没红"


def test_injection_forced_reload_replaced_by_short_circuit_goes_red():
    """注入㉑：收敛改用 `bg_switch_upstream`（文件已等于目标 ⇒ 短路、**不 reload**）⇒ 必红。"""
    injected = _inject(
        read_deploy_sh(), "    if ! bg_reload_nginx; then", '    if ! bg_switch_upstream "$svc" official; then'
    )
    assert judge_upstream_switch_rails(injected), "收敛不做强制 reload 后没红"


def test_injection_convergence_failopen_goes_red():
    """注入㉒：收敛去掉**全部** `exit 1`（不健康 / reload 失败都继续往下走）⇒ 必红。

    ⚠️ 必须清掉**所有**退出点：收敛有两个 exit（正式容器不健康、收不回正式色），只删一个 ⇒
    判据仍看得到 `exit 1` ⇒ 注入是**空跑**（本判据第一版就这样假绿过一次）。
    """
    text = read_deploy_sh()
    start, end = _convergence_span(text)
    block = text[start:end]
    stripped = re.sub(r"^[ \t]*exit 1\n", "", block, flags=re.M)
    assert stripped != block, "反空跑锚点：收敛段里没有 `exit 1`（判据已过期）"
    assert "exit 1" not in stripped, "反空跑锚点：注入没有清掉全部退出点"
    injected = text[:start] + stripped + text[end:]
    assert injected != text, "注入没有改变文本（空跑）"
    assert judge_upstream_switch_rails(injected), "收敛去掉 fail-closed 后没红"


def test_injection_nginx_up_probe_removed_goes_red():
    """注入㉓：去掉「nginx 在跑吗」的可行性前提 ⇒ 必红（首次部署时切换步骤必然失败）。"""
    text = read_deploy_sh()
    probe = (
        "  BG_NGINX_UP=0\n"
        "  if docker compose exec -T nginx nginx -t >/dev/null 2>&1; then BG_NGINX_UP=1; fi\n"
    )
    assert probe in text, "反空跑锚点：找不到可行性探测"
    injected = text.replace(probe, "  BG_NGINX_UP=1\n", 1)
    assert injected != text, "注入没有改变文本（空跑）"
    assert judge_upstream_switch_rails(injected), "去掉可行性前提后没红"


def test_injection_switch_gate_reverted_to_bg_skip_goes_red():
    """注入㉔：把 ①.5 的门从 `BG_SWITCH_ON=1` 退回 `BG_SKIP=0` ⇒ 必红（nginx 未跑时也会去切）。"""
    injected = _inject(
        read_deploy_sh(),
        'if [ "$BG_SWITCH_ON" = "1" ]; then\n    if ! bg_switch_upstream "$svc" green; then',
        'if [ "$BG_SKIP" = "0" ]; then\n    if ! bg_switch_upstream "$svc" green; then',
    )
    assert judge_switch_sequence(injected), "门退回 BG_SKIP 后没红"


def test_injection_cleanup_normalization_removed_goes_red():
    """注入㉕：删掉「收口归一化」⇒ 必红（快照每轮都为真 ⇒ 收敛每轮都跑，fail-closed 分支误伤正常部署）。"""
    text = read_deploy_sh()
    norm = (
        'if [ "$BG_SWITCHED" = "" ] && [ -f "$NGINX_CONF" ]; then\n'
        '  cp "$NGINX_CONF" "$NGINX_CONF_BAK" 2>/dev/null || true\n'
        "fi\n"
    )
    assert norm in text, "反空跑锚点：找不到归一化语句"
    injected = text.replace(norm, "", 1)
    assert injected != text, "注入没有改变文本（空跑）"
    assert judge_upstream_switch_rails(injected), "删掉归一化后没红"


def test_injection_forced_reload_gains_short_circuit_goes_red():
    """注入㉖：给 `bg_reload_nginx` 加上「比较/短路」逻辑 ⇒ 必红（它必须无条件 reload）。"""
    injected = _inject(read_deploy_sh(), "bg_reload_nginx() {\n", "bg_reload_nginx() {\n  local cand=1\n")
    assert judge_upstream_switch_rails(injected), "bg_reload_nginx 出现短路逻辑后没红"


def test_injection_convergence_without_health_gate_goes_red():
    """注入㉗：收敛去掉「正式容器此刻健康吗」的判据 ⇒ 必红（不健康时收回正式色 = 当场 502）。"""
    injected = _inject(read_deploy_sh(), 'if ! bg_official_healthy_now "$svc"; then', "if false; then")
    assert judge_upstream_switch_rails(injected), "收敛去掉健康判据后没红"


def test_injection_convergence_without_switch_gate_goes_red():
    """注入㉘：收敛去掉 `BG_SWITCH_ON` 的门 ⇒ 必红（nginx 未在跑时也会去收敛、判正式容器）。"""
    injected = _inject(
        read_deploy_sh(),
        'if [ "$BG_SWITCH_ON" = "1" ] && [ -n "${BG_PREV_GREEN// /}" ]; then',
        'if [ -n "${BG_PREV_GREEN// /}" ]; then',
    )
    assert judge_upstream_switch_rails(injected), "收敛去掉执行开关后没红"


def test_injection_forced_reload_without_nginx_t_goes_red():
    """注入㉙：`bg_reload_nginx` 丢掉 reload 前的 `nginx -t` ⇒ 必红（坏配置会当场把 worker 换掉）。"""
    injected = _inject(
        read_deploy_sh(),
        "  if ! docker compose exec -T nginx nginx -t >/dev/null 2>&1; then\n"
        '    echo "  ❌ 联机配置未通过 nginx -t ⇒ 不 reload（上一版配置仍在服务，旧 worker 继续跑）"\n'
        "    return 1\n"
        "  fi\n",
        "",
    )
    body = function_body(injected, "bg_reload_nginx")
    assert "nginx -s reload" in body and "nginx -t" not in body, f"注入没生效（空跑）：{body!r}"
    assert judge_upstream_switch_rails(injected), "强制 reload 丢掉 nginx -t 后没红"


def test_injection_normalization_moved_before_nginx_reload_goes_red():
    """注入㉚：把收口归一化挪到 §2.6 的 nginx reload **之前** ⇒ 必红（那时上游还没全部收口）。"""
    text = read_deploy_sh()
    norm = (
        'if [ "$BG_SWITCHED" = "" ] && [ -f "$NGINX_CONF" ]; then\n'
        '  cp "$NGINX_CONF" "$NGINX_CONF_BAK" 2>/dev/null || true\n'
        "fi\n"
    )
    anchor = "docker compose exec -T nginx nginx -s reload || docker compose restart nginx\n"
    assert norm in text and anchor in text, "反空跑锚点：找不到归一化语句 / §2.6 reload 行"
    cut = text.replace(norm, "", 1)
    injected = cut.replace(anchor, norm + anchor, 1)
    assert injected != text, "注入没有改变文本（空跑）"
    assert judge_upstream_switch_rails(injected), "归一化挪到 reload 之前后没红"


def test_injection_exit_trap_removed_goes_red():
    """注入⑱：EXIT trap 改回「只解锁」⇒ 必红（可捕获的退出路径会把上游留在 green）。"""
    injected = _inject(
        read_deploy_sh(), "trap 'bg_restore_upstreams_at_exit; flock -u 9' EXIT", "trap 'flock -u 9' EXIT"
    )
    assert judge_switch_sequence(injected), "EXIT trap 不写回上游后没红"


def test_injection_pre_write_validation_removed_goes_red():
    """注入⑲：去掉「候选先校验后落盘」⇒ 必红。"""
    injected = _inject(
        read_deploy_sh(),
        "  if ! printf '%s\\n' \"$cand\" | nginx_conf_validate; then",
        "  if false; then",
    )
    assert judge_switch_sequence(injected), "去掉先校验后落盘后没红"


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
# 桩 docker：① 记录调用（顺序敏感，$DOCKER_LOG 的**行格式保持不变** —— 既有判据按行匹配）；
#   ② 每次调用前把**当前** nginx.conf 的上游行快照进 $DOCKER_SNAP（**单独文件**，不污染 $DOCKER_LOG）
#      ⇒ 可以断言「替换正式容器**那一刻**上游是不是已经指向 green」（#4828 零窗口的核心判据）。
#   ③ `nginx -t` 的三种调用点**分开**给返回码（否则它们会互相污染，判据变成空断言）：
#      · 候选校验（wrapper：`exec -T nginx sh -c`）    → STUB_NGINX_T_RC
#      · 联机文件 `nginx -t`（可行性探测 / 落盘后复校）→ STUB_NGINX_PROBE_RC
#      （可行性探测与落盘后复校共用 argv ⇒ 无法再细分；前者有独立用例覆盖「跳过切换」）
echo "docker $*" >> "$DOCKER_LOG"
{ printf '%s\\t' "$*"; grep -E '^[[:space:]]*server[[:space:]]+' ./nginx/nginx.conf 2>/dev/null | tr '\\n' ' '; printf '\\n'; } >> "$DOCKER_SNAP"
case "$*" in
  *"compose exec -T nginx sh -c"*)    exit "${STUB_NGINX_T_RC:-0}" ;;
  *"compose exec -T nginx nginx -t"*) exit "${STUB_NGINX_PROBE_RC:-0}" ;;
  *"nginx -s reload"*)                exit "${STUB_RELOAD_RC:-0}" ;;
  *"compose exec"*)                   exit 0 ;;
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


def _prepare(tmp_path: Path, script_text: str, pre_nginx_conf: str | None = None) -> tuple:
    """沙箱：脚本副本（改写绝对路径）+ 桩 bin + 源码 tar + .env 文件。

    `pre_nginx_conf`：预置 `./nginx/nginx.conf` 的内容 —— 用来模拟「**上一轮被强杀**，把流量留在了
    green 上」这个运行态（第 1 步会把它覆盖回正式色 ⇒ 只有第 1 步**之前**读才拿得到）。
    """
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
    if pre_nginx_conf is not None:
        (work / "nginx").mkdir(exist_ok=True)
        (work / "nginx" / "nginx.conf").write_text(pre_nginx_conf, encoding="utf-8")
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


def _run(tmp_path: Path, script_text: str, *, hc: dict, extra_env: dict | None = None,
         pre_nginx_conf: str | None = None):
    """跑脚本；`hc` = {端口: 状态码}（未列出的端口一律 200）。"""
    work, script, bin_dir, state, tar_path = _prepare(tmp_path, script_text, pre_nginx_conf)
    for port, code in hc.items():
        (state / f"hc-{port}").write_text(str(code), encoding="utf-8")
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("", encoding="utf-8")
    docker_snap = tmp_path / "docker.snap"
    docker_snap.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "DOCKER_SNAP": str(docker_snap),
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
    """reload 失败 ⇒ 回落 restart（= 改动前行为，不引入新的坏路径）。

    #4828 起，「上游切换」自己那条 reload 走的是**另一条**路径：失败即就地写回上一版 + 中止
    （切换阶段的硬 restart 会当场丢掉在途连接，所以那里**不**回落 restart —— 见
    `test_exec_switch_reload_failure_restores_conf_and_aborts`）。本用例只钉 §2.6 末尾那条
    reload 的回落：用应急开关把切换段关掉，好让**只有** §2.6 的 reload 被触发。
    """
    (tmp_path / "opt-migao-deploy").mkdir(exist_ok=True)
    (tmp_path / "opt-migao-deploy" / ".blue-green-off").write_text("", encoding="utf-8")
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


# ══════════════════════════════════════════════════════════════════════════
# 四、执行式红证（issue #4828：上游切换）—— 跑**真实脚本**，断言**当时磁盘上的配置**
#
# 桩在每次 docker 调用前把当时的 `nginx.conf` 上游快照进 `$DOCKER_SNAP` ⇒ 断言的是
# 「替换正式容器 / 删 green 那一刻，上游到底指向谁」这个**行为事实**，而不是「代码里有某一行」。
# ⚠️ 仍是**桩化**验证（docker/curl/flock/timeout 是桩，被测的是 deploy.sh 的编排逻辑本身），
#    **不是**真实远端部署 —— 真机只读证据见本文件 docstring 与 PR body。
# ══════════════════════════════════════════════════════════════════════════

SVC_PORTS = (("admin-api", 8080), ("ai-agent", 8000), ("admin-web", 3001))


def _snap(tmp_path: Path) -> list:
    """读 docker 桩的快照 ⇒ [(docker 调用参数, 当时 nginx.conf 的 upstream server 行), ...]。"""
    out = []
    for ln in (tmp_path / "docker.snap").read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        args, _, upstreams = ln.partition("\t")
        out.append((args, upstreams.strip()))
    return out


def _deployed_conf(tmp_path: Path) -> str:
    return (tmp_path / "opt-migao-deploy" / "nginx" / "nginx.conf").read_text(encoding="utf-8")


def test_exec_happy_path_traffic_sits_on_green_during_official_replace(tmp_path):
    """🔴 #4828 核心判据：**替换正式容器的这一刻，上游已经指向 green**（⇒ 那几十秒零 502）。

    反空跑：快照必须真的抓到这三对调用（抓不到 ⇒ 显式失败，不是「通过」）。
    """
    proc, log = _run(tmp_path, read_deploy_sh(), hc={})
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    snap = _snap(tmp_path)
    assert snap, f"docker 桩快照为空（判据空跑）：\n{log}"
    for svc, port in SVC_PORTS:
        cur = next((u for a, u in snap if re.search(rf"up -d --no-deps {svc}$", a)), None)
        assert cur is not None, f"没抓到「替换 {svc} 正式容器」那一刻的快照：\n" + "\n".join(f"{a} => {u}" for a, u in snap)
        assert f"{svc}-green:{port};" in cur, (
            f"替换 {svc} 正式容器时上游**不是** green ⇒ 那几十秒会 502（#4828 要消灭的窗口）：{cur!r}"
        )
        after = next((u for a, u in snap if re.search(rf"rm -sf {svc}-green$", a)), None)
        assert after is not None, f"没抓到「删 {svc}-green」那一刻的快照"
        assert f"{svc}-green" not in after, f"删 {svc}-green 时上游还指着它（= 删掉唯一在服务的后端）：{after!r}"
        assert f"{svc}:{port};" in after, f"删 {svc}-green 时上游应已回到正式色 {svc}:{port}：{after!r}"
    # 退出不变式（INV-A）：脚本正常结束时，磁盘上的上游必须全是正式色
    assert upstream_hosts(_deployed_conf(tmp_path)) == {s: f"{s}:{p}" for s, p in SVC_PORTS}, (
        _deployed_conf(tmp_path)
    )


def test_exec_green_unhealthy_never_touches_upstream(tmp_path):
    """失败路径（#4785 的锚点不变）：green 不健康 ⇒ 上游**一个字都没改**、正式容器未被替换。"""
    proc, _log = _run(tmp_path, read_deploy_sh(), hc={18080: 503})
    assert proc.returncode != 0
    snap = _snap(tmp_path)
    assert snap, "docker 桩快照为空（判据空跑）"
    assert not any("-green" in u for _a, u in snap), (
        "green 不健康却动过上游（流量切换必须在健康检查之后）：\n" + "\n".join(f"{a} => {u}" for a, u in snap)
    )
    assert not any(re.search(r"up -d --no-deps admin-api$", a) for a, _u in snap), "green 不健康却替换了正式容器"
    assert upstream_hosts(_deployed_conf(tmp_path)) == {s: f"{s}:{p}" for s, p in SVC_PORTS}


def test_exec_candidate_failing_nginx_t_never_reaches_live_conf(tmp_path):
    """🔴 红证（#4828 的「写坏 = 全站挂」对消）：候选过不了 `nginx -t` ⇒ **联机文件一字未改**且中止。"""
    proc, _log = _run(tmp_path, read_deploy_sh(), hc={}, extra_env={"STUB_NGINX_T_RC": "1"})
    assert proc.returncode != 0, "候选没过校验，脚本却返回 0"
    snap = _snap(tmp_path)
    assert not any(re.search(r"up -d --no-deps admin-api$", a) for a, _u in snap), "候选没过校验却替换了正式容器"
    assert upstream_hosts(_deployed_conf(tmp_path)) == {s: f"{s}:{p}" for s, p in SVC_PORTS}, "候选没过校验，联机文件却被改了"
    assert "联机配置一字未改" in proc.stdout, proc.stdout


def test_exec_switch_reload_failure_restores_conf_and_aborts(tmp_path):
    """🔴 红证：切换阶段的 reload 失败 ⇒ **就地写回上一版** + 中止（不 reload 就不上线；不硬 restart）。"""
    proc, log = _run(tmp_path, read_deploy_sh(), hc={}, extra_env={"STUB_RELOAD_RC": "1"})
    assert proc.returncode != 0, "切换 reload 失败，脚本却返回 0"
    snap = _snap(tmp_path)
    assert not any(re.search(r"up -d --no-deps admin-api$", a) for a, _u in snap), "reload 失败却继续替换正式容器"
    assert upstream_hosts(_deployed_conf(tmp_path)) == {s: f"{s}:{p}" for s, p in SVC_PORTS}, (
        "reload 失败后联机配置没有写回上一版"
    )
    assert "nginx reload 失败" in proc.stdout, proc.stdout
    assert not any(ln.endswith("compose restart nginx") for ln in log.splitlines()), (
        "切换阶段回落到了硬 restart（会当场丢弃在途连接 —— 这里只许写回 + 中止）"
    )


def test_exec_official_unhealthy_keeps_traffic_on_green(tmp_path):
    """🔴 失败路径的安全性：正式容器替换后**不健康** ⇒ 上游**保持指向 green**，且 green **不许被删**。

    这条钉的是「退出兜底」的边界：那时 green 是唯一还能服务的后端，写回正式色 = 当场 502。
    """
    proc, _log = _run(tmp_path, read_deploy_sh(), hc={8080: 503})
    assert proc.returncode != 0, proc.stdout
    hosts = upstream_hosts(_deployed_conf(tmp_path))
    assert hosts.get("admin-api") == "admin-api-green:8080", (
        f"正式容器不健康却把上游写回正式色（= 把还能服务的 green 换成坏容器）：{hosts}"
    )
    assert "保持上游指向 green" in proc.stdout, proc.stdout
    snap = _snap(tmp_path)
    i_replace = next(i for i, (a, _u) in enumerate(snap) if re.search(r"up -d --no-deps admin-api$", a))
    assert not any(re.search(r"rm -sf admin-api-green$", a) for a, _u in snap[i_replace:]), (
        "正式容器不健康却把 green 删了（唯一后端消失）"
    )


def test_exec_switch_expectation_has_discriminative_power(tmp_path):
    """🔴 反向红证（判别力）：把蓝绿段**还原成旧写法**（无上游切换）⇒ 上面那条快照判据**必然**不成立。

    这一条证明 `test_exec_happy_path_traffic_sits_on_green_during_official_replace` **不是空断言**：
    同一份桩、同一次调用，旧写法（= 本 PR 之前的行为）在替换正式容器时上游**仍是正式色**
    ⇒ 那几十秒就是 #4828 要消灭的 502 窗口。
    """
    proc, _log = _run(tmp_path, _old_form_script(read_deploy_sh()), hc={})
    assert proc.returncode == 0, proc.stdout
    snap = _snap(tmp_path)
    assert snap, "docker 桩快照为空（判据空跑）"
    cur = next(
        (u for a, u in snap if "up -d --no-deps" in a and re.search(r"\badmin-api\b", a)), None
    )
    assert cur is not None, "没抓到替换正式容器的快照（旧写法是批量替换，锚点要兼容两种形态）"
    assert "admin-api-green" not in cur, (
        f"旧写法下替换正式容器时上游居然不是正式色（判据锚点已过期）：{cur!r}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 五、执行式红证（issue #4828 第二版：上游切换**自身**的坏路径 —— 残留 green 的收敛）
#
# 注入 = 预置 `./nginx/nginx.conf` 为「admin-api 上游 = admin-api-green」，即模拟**上一轮被强杀
# 留下的运行态**（那时文件仍写着 green；第 1 步会把它覆盖回正式色 ⇒ 只有第 1 步之前读才拿得到）。
# 断言 = **删 green 之前**必须先 reload 把上游收回正式色；正式容器不健康时**一个容器都不许动**。
# ⚠️ 仍是**桩化**验证（docker / curl / flock / timeout 是桩，被测的是 `deploy.sh` 的编排逻辑本身），
#    **不是**真实远端部署 —— 真机只读证据（含 nginx -t 的反向对照）见本文件 docstring。
# ══════════════════════════════════════════════════════════════════════════


def _conf_with_green(svc: str = "admin-api", port: int = 8080) -> str:
    """canonical nginx.conf 的某个 upstream 指向 green 色（模拟「上一轮把流量留在了 green 上」）。"""
    text = (REPO_ROOT / "deploy" / "swas" / "nginx.conf").read_text(encoding="utf-8")
    out = text.replace(f"server {svc}:{port};", f"server {svc}-green:{port};", 1)
    assert out != text, "反空跑锚点：预置用的 nginx.conf 里找不到目标上游行（判据已过期）"
    return out


def test_residual_green_fixture_really_looks_like_a_killed_run():
    """🔴 反空跑锚点：预置配置必须真的被解析成「上游 = green」——否则下面三条执行式判据是空跑。"""
    hosts = upstream_hosts(_conf_with_green())
    assert hosts["admin-api"] == "admin-api-green:8080", hosts
    assert hosts["ai-agent"] == "ai-agent:8000" and hosts["admin-web"] == "admin-web:3001", hosts


def test_exec_residual_green_is_converged_before_removing_greens(tmp_path):
    """🔴 #4828 红证：上一轮把流量留在 green 上 ⇒ 本轮**先 reload 收回正式色、再删 green**。

    判据形态（可观测的行为事实）：**第一次 `rm -sf ...-green` 之前**必须已经发生过 nginx reload。
    没有收敛时，那句 `$BG_COMPOSE rm -sf $BG_GREENS` 会在**任何 reload 之前**把 green 删掉
    ⇒ 运行中的 nginx 仍指着它 = 删掉唯一在服务的后端（判别力见下一条反向红证）。
    """
    proc, log = _run(tmp_path, read_deploy_sh(), hc={}, pre_nginx_conf=_conf_with_green())
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "上游已收回正式色" in proc.stdout, proc.stdout
    lines = [ln for ln in log.splitlines() if ln.strip()]
    i_first_rm = next(i for i, ln in enumerate(lines) if "rm -sf" in ln)
    assert any("nginx -s reload" in ln for ln in lines[:i_first_rm]), (
        "删 green 之前没有 reload ⇒ 运行中的 nginx 仍指着 green（删掉的就是唯一在服务的后端）:\n"
        + "\n".join(f"{i}: {ln}" for i, ln in enumerate(lines[: i_first_rm + 1]))
    )


def test_exec_residual_green_with_unhealthy_official_touches_nothing(tmp_path):
    """🔴 红证（fail-closed）：上一轮留在 green + 正式容器不健康 ⇒ **一个容器操作都不做** + exit 1。

    这是「不许把唯一还在服务的后端删掉」的硬边界：宁可这轮不部署，也不能全站 502。
    应急放行 = `touch $BG_OFF_FILE`（既有逃生口，见 `test_exec_escape_hatch_skips_blue_green`）。
    """
    proc, log = _run(tmp_path, read_deploy_sh(), hc={8080: 503}, pre_nginx_conf=_conf_with_green())
    assert proc.returncode != 0, f"正式容器不健康时脚本仍返回 0（假绿）\n{proc.stdout}"
    lines = [ln for ln in log.splitlines() if ln.strip()]
    assert not any("up -d" in ln for ln in lines), "收敛期间起了容器：\n" + "\n".join(lines)
    assert not any("rm -sf" in ln for ln in lines), (
        "收敛期间删了容器（可能删掉唯一在服务的 green）：\n" + "\n".join(lines)
    )
    assert "不碰任何容器" in proc.stdout, proc.stdout


def test_exec_residual_convergence_has_discriminative_power(tmp_path):
    """🔴 反向红证（判别力）：删掉收敛段 ⇒ 同一次注入下**必然**在任何 reload 之前就删 green。

    这一条证明上面两条不是空断言：同一份桩、同一份预置运行态，去掉收敛段后行为**确实**变坏。
    """
    text = read_deploy_sh()
    start, end = _convergence_span(text)
    injected = text[:start] + text[end:]
    assert judge_upstream_switch_rails(injected), "反空跑锚点：删掉收敛段后静态判据没红（判据已过期）"
    proc, log = _run(tmp_path, injected, hc={}, pre_nginx_conf=_conf_with_green())
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "上游已收回正式色" not in proc.stdout, "收敛段已被删却仍打印收敛信息（锚点已过期）"
    lines = [ln for ln in log.splitlines() if ln.strip()]
    i_first_rm = next(i for i, ln in enumerate(lines) if "rm -sf" in ln)
    assert not any("nginx -s reload" in ln for ln in lines[:i_first_rm]), (
        "去掉收敛段后居然仍在删 green 之前 reload（判据无判别力）:\n"
        + "\n".join(lines[: i_first_rm + 1])
    )


def test_exec_failclosed_gate_has_discriminative_power(tmp_path):
    """🔴 反向红证（判别力）：去掉收敛的健康判据 ⇒ **同一次注入下**必然去动容器 / 删 green。

    这一条证明 `test_exec_residual_green_with_unhealthy_official_touches_nothing` **不是空断言**：
    同一份桩、同一份预置运行态 + 同一份「正式容器不健康」注入，去掉判据后行为**确实**变坏
    （不再中止，直接往下走并删 green）。
    """
    injected = _inject(read_deploy_sh(), 'if ! bg_official_healthy_now "$svc"; then', "if false; then")
    assert judge_upstream_switch_rails(injected), "反空跑锚点：去掉健康判据后静态判据没红（判据已过期）"
    proc, log = _run(tmp_path, injected, hc={8080: 503}, pre_nginx_conf=_conf_with_green())
    assert proc.returncode != 0, proc.stdout
    lines = [ln for ln in log.splitlines() if ln.strip()]
    assert any("rm -sf" in ln for ln in lines), (
        "去掉健康判据后居然还是没动任何容器（判据无判别力）:\n" + "\n".join(lines)
    )
    assert "不碰任何容器" not in proc.stdout, proc.stdout


def test_exec_without_running_nginx_skips_upstream_switch(tmp_path):
    """#4828 ⓖ：nginx 还没起（首次部署 / nginx 不可用）⇒ **跳过上游切换**且不因此中止。

    注入：让「nginx 在跑吗」的探测失败（`compose exec -T nginx nginx -t` 非零）。
    断言：全程不碰上游（快照里没有任何 `-green`）、部署照常完成（exit 0）。
    这一条钉的是「把上游切换做成了首次部署的硬前提」这个回归（首次部署时 nginx 尚未起、
    且此刻起不来 —— canonical 上游容器都还不存在）。
    """
    proc, _log = _run(tmp_path, read_deploy_sh(), hc={}, extra_env={"STUB_NGINX_PROBE_RC": "1"})
    assert proc.returncode == 0, f"nginx 未在跑时部署被中止了（首次部署回归）：\n{proc.stdout}\n{proc.stderr}"
    assert "跳过上游切换" in proc.stdout, proc.stdout
    snap = _snap(tmp_path)
    assert snap, "docker 桩快照为空（判据空跑）"
    assert not any("-green" in u for _a, u in snap), (
        "nginx 未在跑却动了上游：\n" + "\n".join(f"{a} => {u}" for a, u in snap)
    )


def test_exec_clean_finish_normalizes_backup_to_official(tmp_path):
    """#4828 收口：干净跑完 ⇒ 上一版备份被归一化成正式色（否则下轮快照恒为真、收敛每轮都跑）。"""
    proc, _log = _run(tmp_path, read_deploy_sh(), hc={}, pre_nginx_conf=_conf_with_green())
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    bak = tmp_path / "opt-migao-deploy" / "nginx" / "nginx.conf.last-good"
    assert bak.is_file(), "收口后没有写上一版备份（收敛的判据下一轮会缺一半）"
    assert upstream_hosts(bak.read_text(encoding="utf-8")) == {s: f"{s}:{p}" for s, p in SVC_PORTS}, (
        "收口后的备份不是正式色 ⇒ 下一轮快照把「上一轮没走完」误判为真"
    )
