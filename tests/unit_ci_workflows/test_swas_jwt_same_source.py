# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 部署结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""JWT 验签**同源**（issue #8976；2026-11-21 生产 AI 接口**全 401**）+ nginx 上游刷新断言。

## 病（生产实测，不是推断）

| 组件 | 取值处 | sha256(公钥体) 前 16 |
|---|---|---|
| admin-api（签发） | `.env.admin-api` 的 `JWT_*` = `file:/opt/migao-deploy/jwt/*.pem` | `c58e54d6143d4be8` |
| ai-agent（验签） | `deploy/swas/docker-compose.yml` 里**硬编码的 PEM** | `ba01a29fc44661b9` |

⇒ 生产 AI 接口**全部 401**：`TOKEN_INVALID: Signature verification failed`；
ai-agent 日志逐字 `verify_jwt_token: JWT verification failed: invalid token - Signature verification failed`。
这类不一致**永远不会自己好**（两侧都不报错，也没有任何读数为红）⇒ 只能在部署链上拦。

顺带两个同族（同一轮实测暴露）：

- **nginx 缓存旧上游 IP**：`docker compose up -d`（含 `--force-recreate`）重建容器就换 IP，而 nginx 在
  启动 / reload 时解析 `proxy_pass http://admin-api:8080` 后**永久缓存** ⇒ 重建后不 reload = 全站 502
  （实测 14:58–15:01 约 90s）；
- **classpath 兜底在嵌套 jar 下取不到**：`jar:nested:/app/app.jar/!BOOT-INF/classes/` 这类资源没有「文件」
  可指，加载器若先问 `Resource#exists()` / 用 `getFile()` 就永远读不到 ⇒ 兜底是坏的（只剩 `file:` 一条路）。

## 本文件判什么（每条都能单独变红）

| # | 判据 | 回归时会怎么红 |
|---|---|---|
| 1 | **密钥单一来源**：ai-agent 的 `JWT_PUBLIC_KEY` 必须是 `file:/opt/migao-deploy/jwt/public.pem`（**只给路径**），ai-agent 服务里**不得**再出现内联 PEM，且该服务挂同一份 `jwt:ro` 卷 | 把 PEM 写回 compose / 改回内容值 / 删卷 ⇒ 红 |
| 2 | **部署期硬断言接线**：`deploy.sh` 有唯一一份指纹函数 + 唯一一份断言段，段里四态齐备（`JWT_KEY_SAME_SOURCE` 取 `OK` / `MISMATCH` / `SKIPPED` / `INCOMPLETE`），不一致分支必须 `exit 1`，且**排在 2.6 nginx 之前**（切完流量立刻判） | 删掉断言段 / 去掉 `exit 1` / 把 SKIPPED 写成 OK ⇒ 红 |
| 3 | **指纹口径同源**：shell 侧 `jwt_pubkey_fingerprint()` 与 `scripts/align_agent_jwt_key.py::fingerprint` 对同一份 PEM 必须给出**同一个**指纹（两份实现漂了 ⇒ 断言与处置工具互相打架） | 改成截 8 位 / 含换行 / 换算法 ⇒ 红 |
| 4 | **执行式：一致 ⇒ 绿**（桩 docker / curl，跑**真实** `deploy.sh`） | `JWT_KEY_SAME_SOURCE=OK` 不出现 ⇒ 红 |
| 5 | **执行式：不一致 ⇒ 判红且两个指纹都印出来** | 只有一句「401」不说差在哪 ⇒ 红 |
| 6 | **执行式：两侧都走 classpath 默认 ⇒ SKIPPED**（这是**唯一**允许 SKIPPED 的形态）且**不得**印 OK；只有一侧有值时 ⇒ `INCOMPLETE` + `exit 1`（不完整**不得**当「不可判定就放过」） | 空值/缺一侧当成「已对齐」⇒ 红（假绿） |
| 7 | **执行式：nginx 上游非 200 ⇒ 判红**（且**先**真的试过 reload） | 探不到也 exit 0 ⇒ 红 |
| 8 | **类级元守卫**：`deploy.sh` 里**每一个**会重建「被 nginx 代理的服务」的 `up -d --no-deps` 之后，必须在附近调用上游断言；唯一豁免 = green 探针容器（豁免的**依据** = nginx.conf 里没有任何 `*-green` 上游，同文件另判） | 新增一处裸 `up -d` ⇒ 红 |
| 9 | **手工路径同样带断言**：提到 `--force-recreate` 的**可复制提示**必须紧跟 reload + 探测 200 的命令 | 只给 recreate、不给 reload ⇒ 红（正是本次 502 的现实入口） |
| 10 | **`\n` 转义形态的 PEM 也能算出指纹**（issue #8989 ②）：`.env.*` 的单行 + 字面 `\n` 形态必须先归一化；提取失败要把「读到了什么形态」写进输出 | 退回按行 awk ⇒ `\n` 形态恒 `<不可判定>` ⇒ 红 |
| 11 | **宿主 `file:` 路径缺失 ⇒ 部署前置校验 `exit 1`**（issue #8989 ④）：挡在**任何** `docker compose up` 之前，且不碰旧容器 | 部署到一半才炸 / ai-agent 起不来 ⇒ 红 |
| 12 | **反引号回归检测**（issue #8989 ①）：双引号 `echo` 里出现会触发命令替换的裸反引号 ⇒ 红 | 提示行再写 `` `JWT_*` `` ⇒ 部署日志出现 `command not found` |
| 13 | **断言读宿主权威源**（issue #8989 ③）：`jwt_key_fingerprint_of()` 不得再依赖 `docker compose exec`（容器没重建 ⇒ 读旧容器） | 改回读容器 ⇒ 红 |

## 红证（改前，逐条可复算）

```bash
grep -c 'JWT_PUBLIC_KEY: |' deploy/swas/docker-compose.yml   # 改前 1（内联 PEM）
grep -c 'JWT_KEY_SAME_SOURCE' deploy/swas/deploy.sh          # 改前 0（部署期没有任何断言）
grep -c 'NGINX_UPSTREAM=' deploy/swas/deploy.sh              # 改前 0（reload 之后不探测）
# issue #8989 三条（本文件新判据；改前必红、改后转绿）：
sed -n '/^jwt_pubkey_fingerprint()/,/^}/p' deploy/swas/deploy.sh | grep -cF 'raw//\\\\n'   # 改前 0（不归一化）
grep -c 'JWT_FILE_PATHS_CHECK=OK' deploy/swas/deploy.sh                            # 改前 0（无前置校验）
python3 -m pytest tests/unit_ci_workflows/test_swas_jwt_same_source.py -q -k backtick  # 改前红（提示行有裸反引号）
```

## 边界（照实登记，§19.1）

- 执行式判据跑的是**本机 + 桩化的外部依赖**（docker / curl / flock / timeout），**不是**真实 SWAS：
  它证明的是 `deploy.sh` 的**编排与判据**，证明不了「生产两台容器里的钥匙真的同源」——
  后者由本断言在**下一次部署的日志**里给出（`JWT_KEY_SAME_SOURCE=…` + 两侧来源 + 指纹）。
- 不判「ai-agent 真的加载了那份文件」：本文件判 compose 的**取值契约** + 部署期**读数**；
  运行期加载由 `backend/ai-agent-service/tests/test_config.py::TestJwtPublicKeyFilePrefix`（`file:` 解析 /
  fail-closed）与容器健康检查共同承担。
- 本机无 docker ⇒ **未做真实部署验证**；本 PR 的证据是「存量 31 passed 的生产读数已由临时 override 对齐」
  （见 issue #8976）+ 本文件的执行式判据。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tarfile
import textwrap
from pathlib import Path

import pytest
import yaml

from unit_ci_workflows.injection import inject

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
BASE_COMPOSE = REPO_ROOT / "deploy" / "swas" / "docker-compose.yml"
BG_COMPOSE = REPO_ROOT / "deploy" / "swas" / "docker-compose.bluegreen.yml"
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
PUBLIC_PEM = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa" / "public.pem"
ALIGN_SCRIPT = REPO_ROOT / "scripts" / "align_agent_jwt_key.py"

#: 生产口径：ai-agent 的公钥**只给路径**（内容 = admin-api 私钥那一对的 public 半份）
JWT_FILE_VALUE = "file:/opt/migao-deploy/jwt/public.pem"
JWT_DIR = "/opt/migao-deploy/jwt"
JWT_VOLUME = "/opt/migao-deploy/jwt:/opt/migao-deploy/jwt:ro"

#: 机器可读四态（ASCII 锚点 —— 判据不拿中文文案当结构锚）
STATE_OK = "JWT_KEY_SAME_SOURCE=OK"
STATE_MISMATCH = "JWT_KEY_SAME_SOURCE=MISMATCH"
STATE_SKIPPED = "JWT_KEY_SAME_SOURCE=SKIPPED"
#: 第四态（issue #8989）：只有一侧可判 / 读到非公钥形态 ⇒ 配置不完整，**不放过**。
STATE_INCOMPLETE = "JWT_KEY_SAME_SOURCE=INCOMPLETE"
PREFLIGHT_OK = "JWT_FILE_PATHS_CHECK=OK"
PREFLIGHT_MARK = "== 1.6c JWT 文件式取值宿主路径预检"
NGINX_OK = "NGINX_UPSTREAM=OK"
NGINX_FAIL = "NGINX_UPSTREAM=FAIL"

#: 测试用 `file:` 值（脚本内 `/opt/migao-deploy` 会被 `_prepare` 映射到临时 work 目录）
JWT_AGENT_FILE_VALUE = "file:/opt/migao-deploy/jwt/agent.pem"

_BASH = shutil.which("bash") or "/bin/bash"


# ══════════════════════════════════════════════════════════════════════════
# 一、静态判据（纯函数：文本进 → 违规清单出；注入式红证驱动同一份本体）
# ══════════════════════════════════════════════════════════════════════════


def read_deploy_sh() -> str:
    assert DEPLOY_SH.is_file(), f"反空跑锚点：目标脚本不存在 → {DEPLOY_SH}"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert STATE_OK in text, "反空跑锚点：deploy.sh 里找不到 JWT 同源断言（判据已过期或被回退）"
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
    """剥掉**整行注释**后的代码行 —— 判据只判「真的会执行的那一行」。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _service_env(svc: dict) -> dict:
    env = svc.get("environment") or {}
    if isinstance(env, list):
        env = dict(str(item).split("=", 1) for item in env if "=" in str(item))
    return env


def judge_single_source(base: dict, bg: dict) -> list:
    """判据 1：ai-agent 的验签公钥**只给路径**（与 admin-api 同一份文件），不得再内联 PEM。"""
    v = []
    for label, doc, svc_name in (
        ("docker-compose.yml", base, "ai-agent"),
        ("docker-compose.bluegreen.yml", bg, "ai-agent-green"),
    ):
        svc = (doc.get("services") or {}).get(svc_name)
        if svc is None:
            v.append(f"{label} 里找不到 {svc_name}（判据坐标没了）")
            continue
        env = _service_env(svc)
        raw = env.get("JWT_PUBLIC_KEY")
        if raw is None:
            v.append(f"{label} 的 {svc_name} 没有 `JWT_PUBLIC_KEY`（公钥来源不可判定 ⇒ 部署期断言只会 SKIPPED）")
        elif "BEGIN PUBLIC KEY" in str(raw) or str(raw).lstrip().startswith("-----"):
            v.append(
                f"{label} 的 {svc_name} 又内联了 PEM 内容 —— 那正是 issue #8976 的根因形态"
                "（两把钥匙、永不报错、全 401）；只给 `file:` 路径"
            )
        elif str(raw).strip() != JWT_FILE_VALUE:
            v.append(f"{label} 的 {svc_name}.JWT_PUBLIC_KEY = {raw!r}，期望 {JWT_FILE_VALUE!r}（单一来源）")
        vols = [str(e) for e in (svc.get("volumes") or [])]
        if JWT_VOLUME not in vols:
            v.append(
                f"{label} 的 {svc_name} 缺卷 `{JWT_VOLUME}`（`file:` 取值的宿主面）—— 容器里没有该文件 ⇒ 起来即崩；"
                f"当前 = {vols}"
            )
    # 同源实体面：两侧必须挂**同一个宿主目录**（这就是「单一来源」可检验的那一半）
    api_vols = [str(e) for e in ((base.get("services") or {}).get("admin-api") or {}).get("volumes") or []]
    if not any(vol.startswith(JWT_DIR + ":") for vol in api_vols):
        v.append(f"docker-compose.yml 的 admin-api 没有挂 `{JWT_DIR}` —— 两侧不再是同一份文件（单一来源断了）")
    return v


def judge_deploy_assertion(text: str) -> list:
    """判据 2 / 6 / 13：部署期硬断言存在、唯一、四态齐备、不一致必须 `exit 1`、读宿主权威源。"""
    v = []
    for state in (STATE_OK, STATE_MISMATCH, STATE_SKIPPED, STATE_INCOMPLETE):
        if text.count(state) != 1:
            v.append(f"`{state}` 出现 {text.count(state)} 次（必须恰好 1 次 —— 四态各一条机器可读行）")
    if text.count("jwt_key_fingerprint_of() {") != 1:
        v.append(f"`jwt_key_fingerprint_of()` 定义出现 {text.count('jwt_key_fingerprint_of() {')} 次（必须恰好 1 次）")
    if text.count("jwt_pubkey_fingerprint() {") != 1:
        v.append(
            f"`jwt_pubkey_fingerprint()` 定义出现 {text.count('jwt_pubkey_fingerprint() {')} 次"
            "（必须恰好 1 次 —— 两份指纹实现必漂，而漂了没有任何东西会红）"
        )
    for svc in ("admin-api", "ai-agent"):
        if f"jwt_key_fingerprint_of {svc}" not in text:
            v.append(f"断言没有取 `{svc}` 侧的公钥（少取一侧 = 断言无从比较）")
    # 判据 13（issue #8989 ③）：只读宿主权威源，**不许**读运行中的容器（旧容器会让断言失真）
    if "jwt_key_fingerprint_of() {" in text:
        body = function_body(text, "jwt_key_fingerprint_of")
        if "docker compose exec" in body:
            v.append("`jwt_key_fingerprint_of()` 还在 `docker compose exec` 读容器（容器未重建 ⇒ 读到旧容器）")
        for token in (".env.admin-api", "docker-compose.yml", "jwt_env_value_of"):
            if token not in body:
                v.append(f"`jwt_key_fingerprint_of()` 没有读宿主权威源 {token!r}（issue #8989 ③）")
    # 判据 10（issue #8989 ②）：`\n` 转义形态必须先归一化
    if "jwt_pubkey_fingerprint() {" in text:
        fp_body = function_body(text, "jwt_pubkey_fingerprint")
        if "raw//\\\\n" not in fp_body:
            v.append("`jwt_pubkey_fingerprint()` 没有归一化字面 `\\n`（单行 .env 形态会恒 `<不可判定>`）")
        if "jwt_value_shape_of" not in text:
            v.append("提取失败时没有把「读到了什么形态」写进输出（不可归因）")
    # 不一致分支必须 fail-closed
    m = re.search(rf"{re.escape(STATE_MISMATCH)}(.*?)(?:else\n|^fi$)", text, re.S | re.M)
    if not m:
        v.append("找不到不一致分支（`JWT_KEY_SAME_SOURCE=MISMATCH` 之后到 else/fi 之间）")
    elif "exit 1" not in m.group(1):
        v.append("不一致分支没有 `exit 1`（不一致会被当成部署成功 —— 正是本单要拦的形态）")
    # 不完整分支必须 fail-closed（只有一侧有值 ≠ 可以放过）
    m = re.search(rf"{re.escape(STATE_INCOMPLETE)}(.*?)(?:^elif |^fi$)", text, re.S | re.M)
    if not m:
        v.append("找不到 INCOMPLETE 分支（一侧有值 / 取不到指纹时没有判红出口）")
    elif "exit 1" not in m.group(1):
        v.append("INCOMPLETE 分支没有 `exit 1`（配置不完整被当成部署成功）")
    # SKIPPED 分支不得印 OK（「取不到」不许判绿），且只允许「两侧都 absent」这一种形态
    m = re.search(rf"{re.escape(STATE_SKIPPED)}(.*?)(?:^elif |^fi$)", text, re.S | re.M)
    if not m:
        v.append("找不到 SKIPPED 分支")
    else:
        if STATE_OK in m.group(1):
            v.append("SKIPPED 分支里印了 OK（取不到对象却判绿 = 假绿）")
        guard = text[max(0, m.start() - 500):m.start()]
        if guard.count('= "absent"') < 2:
            v.append("SKIPPED 分支没有「两侧都 absent」的前置条件（SKIPPED 只允许两侧都走 classpath 默认）")
    # 位置：断言必须在 2.6 nginx **之前**（切完流量立刻判，不是收尾才判）
    i_jwt = text.find("== 2.5.9")
    # 取**最后一处** `up -d nginx`：断言函数体里还有一处「幂等起 nginx」（在 2.5.9 之前）
    i_nginx_up = text.rfind('docker compose up -d --no-deps nginx\n')
    if i_jwt < 0:
        v.append("deploy.sh 里找不到 JWT 同源断言段（`== 2.5.9`）")
    elif i_nginx_up >= 0 and i_jwt > i_nginx_up:
        v.append("JWT 同源断言排在 nginx 更新之后（应当在切完流量、收尾之前）")
    return v


def judge_preflight_wiring(text: str) -> list:
    """判据 11（issue #8989 ④）：`file:` 宿主路径预检必须在**任何** `up -d` 之前，且不读容器。"""
    v = []
    if text.count(PREFLIGHT_OK) != 1:
        v.append(f"`{PREFLIGHT_OK}` 出现 {text.count(PREFLIGHT_OK)} 次（缺前置校验 / 重复实现）")
    if text.count(PREFLIGHT_MARK) != 1:
        v.append(f"找不到唯一的前置校验段（`{PREFLIGHT_MARK}`）")
    for token in ("jwt_file_paths_of_env", "jwt_file_paths_of_compose", "jwt_host_path"):
        if token not in text:
            v.append(f"前置校验缺少 {token!r}（宿主路径来源会漏检）")
    start = text.find(PREFLIGHT_MARK)
    if start < 0:
        return v
    end = text.find('echo "  JWT_FILE_PATHS_CHECK=OK', start)
    body = text[start:end + 200 if end > start else start + 4000]
    if "docker compose exec" in body:
        v.append("前置校验在读运行中的容器（`docker compose exec`）—— 它要判的是**宿主**路径")
    # 位置：必须在第一处会执行到的 `up -d` 之前（蓝绿 green 的 up 也算）
    first_up = None
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.lstrip().startswith("#"):
            continue
        if "up -d" in ln:
            first_up = i
            break
    pre_line = text[:start].count("\n") + 1
    if first_up is None:
        v.append("deploy.sh 里找不到任何 `up -d`（判据坐标没了）")
    elif first_up < pre_line:
        v.append(f"前置校验在第 {pre_line} 行，晚于第一处 `up -d`（第 {first_up} 行）—— 挡不住 recreate")
    return v


def judge_no_command_substitution_in_echo(text: str) -> list:
    """判据 12（issue #8989 ①）：双引号 `echo` 里不得出现裸反引号（会被当命令替换）。"""
    v = []
    for i, ln in enumerate(text.splitlines(), 1):
        s = ln.strip()
        if s.startswith("#") or not s.startswith('echo "'):
            continue
        if re.search(r"(?<!\\)`", s):
            v.append(
                f"第 {i} 行 echo 的双引号里有裸反引号（命令替换 ⇒ 日志出现 command not found / 提示语被吃）：{s[:110]}"
            )
    return v


def judge_upstream_assertion_wiring(text: str, nginx_text: str) -> list:
    """判据 8 / 9：凡重建「被 nginx 代理的服务」之后都必须断言；green 豁免必须有**依据**。"""
    v = []
    if text.count("nginx_expect_upstream_ok() {") != 1:
        v.append(f"`nginx_expect_upstream_ok()` 定义出现 {text.count('nginx_expect_upstream_ok() {')} 次（必须恰好 1 次）")
    if "NGINX_PROBE_TRIES" not in text or "api/version" not in text:
        v.append("上游断言里没有「探测 + 重试预算」（`NGINX_PROBE_TRIES` / `/api/version`）")
    body = function_body(text, "nginx_expect_upstream_ok") if "nginx_expect_upstream_ok() {" in text else ""
    for token in ("nginx -s reload", "exit 1", "/api/version", "%{http_code}"):
        if token not in body:
            v.append(f"`nginx_expect_upstream_ok()` 缺少 {token!r}（判据被删/被放宽）")

    lines = text.splitlines()
    code_idx = [i for i, ln in enumerate(lines) if not ln.lstrip().startswith("#")]
    up_lines = [i for i in code_idx if "up -d --no-deps" in lines[i] and "sh -c" not in lines[i]]
    # 断言函数**自身**里的 `up -d nginx`（幂等兜底）不需要再被自己跟随
    fn_start = text.find("nginx_expect_upstream_ok() {")
    fn_end = text.find("\n}\n", fn_start) if fn_start >= 0 else -1
    offsets, acc = [], 0
    for ln in lines:
        offsets.append(acc)
        acc += len(ln) + 1
    if not up_lines:
        v.append("deploy.sh 里找不到任何 `up -d --no-deps`（判据坐标没了）")
    for i in up_lines:
        line = lines[i]
        if fn_start >= 0 and fn_start <= offsets[i] <= fn_end:
            continue  # 断言函数自身
        if line.lstrip().startswith("echo"):
            continue  # 打印给人看的可复制提示（判据 9 单独管它）
        if '"$GREEN"' in line or "${GREEN}" in line:
            # green 是**探针容器**（不在任何 nginx upstream 里）⇒ 重建它不影响代理目标。
            # 该豁免必须**有依据**：nginx.conf 里不许出现任何 `*-green` 上游名。
            if "-green" in nginx_text:
                v.append("nginx.conf 里出现了 `*-green` 上游 —— green 豁免的前提失效（重建 green 也会影响流量）")
            continue
        window = "\n".join(lines[i + 1:i + 13])
        if "nginx_expect_upstream_ok" not in window:
            v.append(
                f"`{line.strip()}` 之后 12 行内没有调用 `nginx_expect_upstream_ok`"
                "（重建换 IP ⇒ 不清 nginx 缓存 = 全站 502）"
            )
    # 判据 9：手工 recreate 的可复制提示必须带 reload + 探测
    for i, ln in enumerate(lines):
        if "--force-recreate" in ln and ln.lstrip().startswith("echo"):
            # 窗口放宽到 7 行：提示里允许夹说明性注释，但 reload 与探测**必须**在同一段可复制命令里
            window = "\n".join(lines[i:i + 7])
            if "nginx -s reload" not in window:
                v.append(f"提示了 `--force-recreate` 却没说 reload（第 {i + 1} 行）⇒ 照抄的人会打出 502")
            if "/api/version" not in window:
                v.append(f"提示了 `--force-recreate` 却没有探测命令（第 {i + 1} 行）")
    return v


def all_violations(text: str, base: dict, bg: dict, nginx_text: str) -> list:
    return (
        judge_single_source(base, bg)
        + judge_deploy_assertion(text)
        + judge_preflight_wiring(text)
        + judge_no_command_substitution_in_echo(text)
        + judge_upstream_assertion_wiring(text, nginx_text)
    )


# ══════════════════════════════════════════════════════════════════════════
# 二、静态判据（读仓内现状）+ 注入式红证
# ══════════════════════════════════════════════════════════════════════════


def test_real_files_satisfy_every_judgement():
    v = all_violations(read_deploy_sh(), read_yaml(BASE_COMPOSE), read_yaml(BG_COMPOSE),
                       NGINX_CONF.read_text(encoding="utf-8"))
    assert not v, "JWT 同源 / nginx 上游断言判据未满足：\n- " + "\n- ".join(v)


def _inject(text: str, old: str, new: str, *, count: int = 1) -> str:
    """注入 = 仓库唯一原语 `inject()`（issue #7017）：**不许**裸 `str.replace`。

    裸 replace 的失效形态是「锚点漂了 ⇒ 静默返回原串 ⇒ 红证没生效，却被读成『判据没牙』」；
    `inject()` 对 0 命中 / 不唯一 / 空操作**一律抛错**（判据 = tests/unit_ci_workflows/test_red_proof_anchor_liveness.py）。
    """
    return inject(text, old, new, count=count, where="deploy/swas/deploy.sh")


def test_injection_inline_pem_back_goes_red():
    """注入①：把 ai-agent 的 `file:` 值换回内联 PEM ⇒ 判据 1 必红（= 本单的根因形态）。"""
    base = read_yaml(BASE_COMPOSE)
    mutated = yaml.safe_load(yaml.safe_dump(base))
    mutated["services"]["ai-agent"]["environment"]["JWT_PUBLIC_KEY"] = (
        "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n"
    )
    v = judge_single_source(mutated, read_yaml(BG_COMPOSE))
    assert any("内联" in x for x in v), v


def test_injection_volume_removed_goes_red():
    """注入②：删掉 ai-agent 的 jwt 卷 ⇒ 判据 1 必红（`file:` 取值的宿主面没了）。"""
    base = read_yaml(BASE_COMPOSE)
    mutated = yaml.safe_load(yaml.safe_dump(base))
    mutated["services"]["ai-agent"]["volumes"] = []
    v = judge_single_source(mutated, read_yaml(BG_COMPOSE))
    assert any("缺卷" in x for x in v), v


def test_injection_assertion_removed_goes_red():
    """注入③：把 `JWT_KEY_SAME_SOURCE=OK` 那一行删掉 ⇒ 判据 2 必红（四态不齐）。"""
    mutated = _inject(read_deploy_sh(), f'echo "  {STATE_OK}"\n', "")
    assert judge_deploy_assertion(mutated), "删掉 OK 行后判据没红（判据无判别力）"


def test_injection_mismatch_not_fatal_goes_red():
    """注入④：把不一致分支的 `exit 1` 去掉 ⇒ 必红（不一致会被当成成功）。"""
    text = read_deploy_sh()
    start = text.find(STATE_MISMATCH)
    assert start > 0
    end = text.find("exit 1", start)
    assert end > start, "找不到不一致分支的 exit 1（判据已过期）"
    mutated = text[:end] + "true" + text[end + len("exit 1"):]
    assert any("exit 1" in x for x in judge_deploy_assertion(mutated)), "去掉 exit 1 后判据没红"


def test_injection_skipped_pretends_ok_goes_red():
    """注入⑤：在 SKIPPED 分支里也印 OK ⇒ 必红（取不到对象判绿 = 假绿）。"""
    text = read_deploy_sh()
    mutated = _inject(text, f'echo "  {STATE_SKIPPED}"\n',
                      f'echo "  {STATE_SKIPPED}"\necho "  {STATE_OK}"\n')
    assert any("假绿" in x for x in judge_deploy_assertion(mutated)), judge_deploy_assertion(mutated)


def test_injection_bare_up_without_upstream_assertion_goes_red():
    """注入⑥：新增一处裸 `up -d`（不被断言跟随）⇒ 判据 8 必红（类级：同类进不来）。"""
    text = read_deploy_sh()
    mutated = _inject(
        text,
        'echo "== deploy.sh 完成',
        'docker compose up -d --no-deps admin-api\necho "== deploy.sh 完成',
    )
    v = judge_upstream_assertion_wiring(mutated, NGINX_CONF.read_text(encoding="utf-8"))
    assert any("nginx_expect_upstream_ok" in x for x in v), v


def test_injection_force_recreate_hint_without_reload_goes_red():
    """注入⑦：`--force-recreate` 的提示去掉 reload ⇒ 必红（照抄的人会把站点打成 502）。"""
    text = read_deploy_sh()
    mutated = _inject(
        text,
        '  echo "        docker compose exec -T nginx nginx -s reload || docker compose restart nginx"\n',
        "",
    )
    v = judge_upstream_assertion_wiring(mutated, NGINX_CONF.read_text(encoding="utf-8"))
    assert any("reload" in x for x in v), v


def test_no_bare_backtick_in_echo_hints():
    """判据 12 / 红证 c（issue #8989 ①）：仓内**现状**的双引号 echo 里不得有裸反引号。"""
    v = judge_no_command_substitution_in_echo(read_deploy_sh())
    assert not v, "部署提示行里有会被 shell 当命令执行的裸反引号：\n- " + "\n- ".join(v)


def test_injection_bare_backtick_in_hint_goes_red():
    """注入⑧（issue #8989 ① 红证 c）：提示行再出现裸反引号 ⇒ 判据必红（真会被 shell 执行）。"""
    mutated = _inject(
        read_deploy_sh(),
        'echo "     让它可以判定：两侧都显式配「JWT_*」',
        'echo "     让它可以判定：两侧都显式配 `JWT_*`',
    )
    v = judge_no_command_substitution_in_echo(mutated)
    assert any("裸反引号" in x for x in v), v


def test_injection_assertion_reads_container_goes_red():
    """注入⑨（issue #8989 ③）：断言改回 `docker compose exec` ⇒ 判据必红（旧容器会失真）。"""
    text = read_deploy_sh()
    mutated = _inject(
        text,
        "      raw=$(jwt_env_value_of .env.admin-api JWT_PUBLIC_KEY)",
        "      raw=$(docker compose exec -T admin-api sh -c 'printf %s \"$JWT_PUBLIC_KEY\"')",
    )
    v = judge_deploy_assertion(mutated)
    assert any("docker compose exec" in x for x in v), v


def test_injection_escaped_newline_normalization_removed_goes_red():
    """注入⑩（issue #8989 ②）：删掉字面 `\\n` 归一化 ⇒ 判据必红（单行 .env 形态恒不可判定）。"""
    text = read_deploy_sh()
    mutated = _inject(text, "  raw=${raw//\\\\n/$'\\n'}\n", "")
    v = judge_deploy_assertion(mutated)
    assert any("归一化" in x for x in v), v


def test_injection_preflight_moved_after_up_goes_red():
    """注入⑪（issue #8989 ④）：把前置校验挪到第一处 `up -d` 之后 ⇒ 判据必红（挡不住破坏形态）。"""
    text = read_deploy_sh()
    start = text.find(PREFLIGHT_MARK)
    # 结构锚（issue #6802 同族）：原用中文注释标题 `# 1.7 模型名 canonical 自愈` 当块边界，
    # 被判据判为「中文/注释级文案当结构位置」，且台账已冻结在上限 42/42 无法再登记 ⇒
    # 改取 1.7 段**代码首行**（全脚本唯一）。语义不变：仍是从 PREFLIGHT_MARK 到 1.7 段起点。
    end = text.find("if [ -f .env.ai-agent ]; then", start)
    assert start > 0 and end > start
    block = text[start:end]
    mutated = text[:start] + text[end:]
    anchor = "# ── 2.6 nginx（流量入口本身"
    mutated = _inject(mutated, anchor, block + anchor)
    v = judge_preflight_wiring(mutated)
    assert any("晚于第一处" in x for x in v), v




# ══════════════════════════════════════════════════════════════════════════
# 三、指纹口径同源（shell ⇄ scripts/align_agent_jwt_key.py）
# ══════════════════════════════════════════════════════════════════════════


def _python_fingerprint(pem: str) -> str | None:
    """测试侧独立实现（**不复用**脚本私有函数，避免「两边一起错」）。"""
    import base64

    m = re.search(r"-----BEGIN PUBLIC KEY-----(.*?)-----END PUBLIC KEY-----", pem, re.S)
    if not m:
        return None
    body = "".join(m.group(1).split())
    try:
        base64.b64decode(body, validate=True)
    except Exception:
        return None
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _run_shell_fingerprint(pem: str) -> subprocess.CompletedProcess:
    """把 deploy.sh 的 `_sha256_hex` + `jwt_pubkey_fingerprint` **原样**跑一遍（真跑，不是重写）。"""
    text = read_deploy_sh()
    script = (
        "set -uo pipefail\n"
        "_sha256_hex() {" + function_body(text, "_sha256_hex") + "\n}\n"
        "jwt_pubkey_fingerprint() {" + function_body(text, "jwt_pubkey_fingerprint") + "\n}\n"
        "cat <<'MIGAO_PEM_EOF' | jwt_pubkey_fingerprint\n"
    )
    return subprocess.run(
        [_BASH, "-c", script + pem + "\nMIGAO_PEM_EOF\n"],
        capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
    )


def test_shell_fingerprint_matches_python_tooling():
    """判据 3：shell 侧指纹 == `scripts/align_agent_jwt_key.py` 的口径（同一份 PEM 同一指纹）。"""
    pem = PUBLIC_PEM.read_text(encoding="utf-8")
    proc = _run_shell_fingerprint(pem)
    assert proc.returncode == 0, f"shell 指纹函数跑不动（脚本已坏）：{proc.stdout}{proc.stderr}"
    assert proc.stdout.strip() == _python_fingerprint(pem), (
        f"两侧指纹口径漂了：shell={proc.stdout.strip()!r} python={_python_fingerprint(pem)!r} —— "
        "部署期断言与处置工具会互相打架"
    )


def test_shell_fingerprint_discriminates_and_rejects_non_pem():
    """判别力：改成另一对公钥 ⇒ 指纹必须不同；非公钥文本 ⇒ 非零退出（不可判定）。"""
    pem = PUBLIC_PEM.read_text(encoding="utf-8")
    tampered = pem.replace("yDkix6IDMt3w", "yOdUYhPbpkCb")
    assert tampered != pem
    good = _run_shell_fingerprint(pem).stdout.strip()
    bad = _run_shell_fingerprint(tampered).stdout.strip()
    assert good and bad and good != bad, f"换一把公钥却印同一个指纹（判据退化）：{good!r} / {bad!r}"
    junk = _run_shell_fingerprint("not a pem")
    assert junk.returncode != 0, f"非公钥文本必须非零退出（否则「读不到」会被当成「对齐」）：{junk.stdout!r}"


def test_shell_fingerprint_accepts_escaped_newline_env_form():
    """判据 10 / 红证 a（issue #8989 ②）：`.env` 的**单行 + 字面 `\\n`** 形态也必须算出指纹。

    改前实现用 awk 按行匹配 `-----BEGIN PUBLIC KEY-----` ⇒ 单行 `.env` 形态取不到 body ⇒
    返回 `<不可判定>` ⇒ 生产上这条断言**永远 SKIPPED**（比不加更糟：给了已守护的错觉）。
    """
    pem = PUBLIC_PEM.read_text(encoding="utf-8")
    assert "\n" in pem, "反空跑锚点：入仓公钥不是多行 PEM，本判据无从构造单行形态"
    escaped = pem.replace("\n", "\\n")
    assert "\\n" in escaped and "\n" not in escaped
    proc = _run_shell_fingerprint(escaped)
    assert proc.returncode == 0, (
        f"单行 + 字面 \\n 形态取不到指纹（改前的病）：{proc.stdout}{proc.stderr}"
    )
    assert proc.stdout.strip() == _python_fingerprint(pem), (
        f"归一化后的指纹与 Python 工具口径不一致：shell={proc.stdout.strip()!r} "
        f"python={_python_fingerprint(pem)!r}"
    )


def test_shell_fingerprint_shape_is_attributable_on_failure():
    """判据 10（可归因）：提取失败时能说出「读到了什么形态」，不再只有 `<不可判定>`。"""
    text = read_deploy_sh()
    script = (
        "set -uo pipefail\n"
        "jwt_value_shape_of() {" + function_body(text, "jwt_value_shape_of") + "\n}\n"
        'jwt_value_shape_of "not a pem"\n'
        'printf "\\n"\n'
        'jwt_value_shape_of "-----BEGIN PRIVATE KEY-----\\nAAAA\\n-----END PRIVATE KEY-----"\n'
    )
    proc = subprocess.run(
        [_BASH, "-c", script], capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT)
    )
    assert proc.returncode == 0, proc.stderr
    assert "非 PEM 文本" in proc.stdout and "首 40 字" in proc.stdout, proc.stdout
    assert "私钥 PEM" in proc.stdout, proc.stdout



# ══════════════════════════════════════════════════════════════════════════
# 四、执行式红证（桩 docker / curl，跑**真实** deploy.sh）
# ══════════════════════════════════════════════════════════════════════════

CURL_STUB = """#!/bin/bash
# 桩 curl：① codeload 源码包 → 拷预置 tar；② 健康检查 → 按 $HC_STATE/hc-<端口>；③ 上游探测 → $STUB_PROBE_CODE
out=""; url=""; fmt=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    --resolve) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  *codeload.github.com*) cp "$STUB_TAR" "$out"; exit 0 ;;
  *"/api/version"*) code="${STUB_PROBE_CODE:-200}" ;;
  *)
    port=$(printf '%s' "$url" | sed -n 's#^http://127\\.0\\.0\\.1:\\([0-9][0-9]*\\)/.*#\\1#p')
    code=$(cat "$HC_STATE/hc-$port" 2>/dev/null || echo 200)
    ;;
esac
if [ -n "$out" ]; then : > "$out"; fi
if [ -n "$fmt" ]; then printf '%s' "$code"; fi
exit 0
"""

#: 桩 docker：按「服务 + 取的是哪一侧」回放预置读数（= 容器里**实际生效**的 env / `file:` 内容）
DOCKER_STUB = r"""#!/bin/bash
echo "docker $*" >> "$DOCKER_LOG"
svc=""
case "$*" in
  *admin-api*) svc="admin-api" ;;
  *ai-agent*)  svc="ai-agent" ;;
esac
case "$*" in
  *JWT_PUBLIC_KEY_PEM*) exit 0 ;;
  *" sh -c "*) cat "$STUB_KEYS/${svc}.env" 2>/dev/null; exit 0 ;;
  *" cat "*)   cat "$STUB_KEYS/${svc}.pem" 2>/dev/null; exit 0 ;;
  *"compose ps -q nginx"*) echo "nginx-container-id"; exit 0 ;;
  *"nginx -s reload"*) exit "${STUB_RELOAD_RC:-0}" ;;
esac
exit 0
"""

FLOCK_STUB = """#!/bin/bash
# 桩 flock：no-op（macOS 无 flock；锁语义由既有判据覆盖，本文件未改动 flock 相关行）
exit 0
"""

TIMEOUT_STUB = """#!/bin/bash
# 桩 timeout：只透传
shift
exec "$@"
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


_UNSET = object()
COMPOSE_AGENT_KEY_LINE = "      JWT_PUBLIC_KEY: file:/opt/migao-deploy/jwt/public.pem\n"


def _make_src_tar(dest: Path, agent_compose_raw=_UNSET, classpath_pem: str = "") -> None:
    stage = dest.parent / "stage" / "migao-main" / "deploy" / "swas"
    stage.mkdir(parents=True, exist_ok=True)
    work = dest.parent / "opt-migao-deploy"
    compose_text = (REPO_ROOT / "deploy" / "swas" / "docker-compose.yml").read_text(encoding="utf-8")
    if agent_compose_raw is not _UNSET:
        assert compose_text.count(COMPOSE_AGENT_KEY_LINE) == 1, (
            "反空跑锚点：compose 里 ai-agent 的 JWT_PUBLIC_KEY 行已变（本判据的注入坐标漂了）"
        )
        repl = "" if agent_compose_raw is None else f"      JWT_PUBLIC_KEY: {agent_compose_raw}\n"
        compose_text = compose_text.replace(COMPOSE_AGENT_KEY_LINE, repl)
    # 生产根 `/opt/migao-deploy` → 本用例 work（与 deploy.sh 文本替换同口径）
    compose_text = compose_text.replace("/opt/migao-deploy", str(work))
    (stage / "docker-compose.yml").write_text(compose_text, encoding="utf-8")
    for name in ("docker-compose.bluegreen.yml", "nginx.conf"):
        text = (REPO_ROOT / "deploy" / "swas" / name).read_text(encoding="utf-8")
        (stage / name).write_text(text.replace("/opt/migao-deploy", str(work)), encoding="utf-8")
    if classpath_pem:
        repo_tree = dest.parent / "stage" / "migao-main"
        pub = repo_tree / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa"
        pub.mkdir(parents=True, exist_ok=True)
        (pub / "public.pem").write_text(classpath_pem, encoding="utf-8")
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(dest.parent / "stage" / "migao-main", arcname="migao-main")


def _prepare(tmp_path: Path, *, agent_compose_raw=_UNSET, classpath_pem: str = "",
             cache_pem: str = "") -> tuple:
    work = tmp_path / "opt-migao-deploy"
    work.mkdir(exist_ok=True)
    text = DEPLOY_SH.read_text(encoding="utf-8")
    text = text.replace("/opt/migao-deploy", str(work))
    text = text.replace("/tmp/migao-deploy.lock", str(work / "deploy.lock"))
    text = text.replace("/tmp/hc_", f"{work}/hc_")
    script = work / "deploy.sh"
    script.write_text(text, encoding="utf-8")
    (work / ".env.admin-api").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    (work / ".env.ai-agent").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    if classpath_pem:
        # 部署树里的 admin-api classpath 公钥（1.3c 在 1.4 构建前读取它；构建成功后 `src/` 被删）
        pub = work / "src" / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa"
        pub.mkdir(parents=True, exist_ok=True)
        (pub / "public.pem").write_text(classpath_pem, encoding="utf-8")
    if cache_pem:
        # 「配置复用 / 回滚」档：盘上没有 `src/`，只有 1.3c 落盘的持久缓存（issue #9059）
        (work / ".migao-admin-api-classpath-public.pem").write_text(cache_pem, encoding="utf-8")
    tar_path = tmp_path / "src.tar.gz"
    _make_src_tar(tar_path, agent_compose_raw=agent_compose_raw, classpath_pem=classpath_pem)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_exe(bin_dir / "curl", CURL_STUB)
    _write_exe(bin_dir / "docker", DOCKER_STUB)
    _write_exe(bin_dir / "flock", FLOCK_STUB)
    _write_exe(bin_dir / "timeout", TIMEOUT_STUB)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    return work, script, bin_dir, state, tar_path, keys


def _run(tmp_path: Path, *, admin_raw: str, agent_raw: str, admin_pem: str = "",
         agent_pem: str = "", probe_code: int = 200, extra_env: dict | None = None,
         agent_compose_raw=_UNSET, classpath_pem: str = "", cache_pem: str = ""):
    work, script, bin_dir, state, tar_path, keys = _prepare(
        tmp_path, agent_compose_raw=agent_compose_raw, classpath_pem=classpath_pem,
        cache_pem=cache_pem)
    # 生产根 `/opt/migao-deploy` → 本用例 work（与 deploy.sh / compose 的文本替换同口径）
    admin_raw = admin_raw.replace("/opt/migao-deploy", str(work))
    agent_raw = agent_raw.replace("/opt/migao-deploy", str(work))
    # 宿主权威源（issue #8989 ③）：断言读这里，**不**读容器。
    (work / ".env.admin-api").write_text(
        f"SMS_BYPASS_CODE=123456\nJWT_PUBLIC_KEY={admin_raw}\n", encoding="utf-8"
    )
    (work / ".env.ai-agent").write_text(
        f"SMS_BYPASS_CODE=123456\nJWT_PUBLIC_KEY={agent_raw}\n", encoding="utf-8"
    )
    jwt_dir = work / "jwt"
    jwt_dir.mkdir(exist_ok=True)
    if admin_pem:
        (jwt_dir / "public.pem").write_text(admin_pem, encoding="utf-8")
    if agent_pem:
        (jwt_dir / "agent.pem").write_text(agent_pem, encoding="utf-8")
    (keys / "admin-api.env").write_text(admin_raw, encoding="utf-8")
    (keys / "ai-agent.env").write_text(agent_raw, encoding="utf-8")
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "HC_STATE": str(state),
        "STUB_TAR": str(tar_path),
        "STUB_KEYS": str(keys),
        "STUB_PROBE_CODE": str(probe_code),
        "HC_RETRIES": "2",
        "HC_INTERVAL_SECONDS": "0",
        "NGINX_PROBE_TRIES": "2",
        "NGINX_PROBE_INTERVAL": "0",
        "BG_MEM_NEED_MB": "0",
        "MIGAO_PUBLIC_DOMAIN": "cytda.test",
        "BG_OFF_FILE": str(work / ".blue-green-off"),
        **(extra_env or {}),
    }
    proc = subprocess.run(
        [_BASH, str(script), "sha-test"],
        cwd=str(work), env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, docker_log.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def committed_pem() -> str:
    assert PUBLIC_PEM.is_file(), f"入仓公钥不存在：{PUBLIC_PEM} —— 判据无从行使"
    return PUBLIC_PEM.read_text(encoding="utf-8")


def test_exec_aligned_keys_are_green(tmp_path, committed_pem):
    """判据 4：两侧同一个 `file:` 文件 ⇒ `JWT_KEY_SAME_SOURCE=OK` 且 exit 0。"""
    proc, _ = _run(
        tmp_path,
        admin_raw=JWT_FILE_VALUE,
        agent_raw=JWT_FILE_VALUE,
        admin_pem=committed_pem,
        agent_pem=committed_pem,
    )
    assert proc.returncode == 0, f"对齐形态却判失败：\n{proc.stdout}\n{proc.stderr}"
    assert STATE_OK in proc.stdout, proc.stdout
    assert _python_fingerprint(committed_pem) in proc.stdout, "必须把指纹打进部署日志（可对账）"


def test_exec_mismatched_keys_fail_deploy_with_both_fingerprints(tmp_path, committed_pem):
    """判据 5：两侧不同钥匙 ⇒ exit != 0，且**两个指纹都印出来** + 排查口。"""
    other = committed_pem.replace("yDkix6IDMt3w", "yOdUYhPbpkCb")
    proc, _ = _run(
        tmp_path,
        admin_raw=JWT_FILE_VALUE,
        agent_raw="",
        admin_pem=committed_pem,
        agent_compose_raw=JWT_AGENT_FILE_VALUE,
        agent_pem=other,
    )
    assert proc.returncode != 0, f"不同源却返回 0（假绿）：\n{proc.stdout}"
    assert STATE_MISMATCH in proc.stdout, proc.stdout
    assert _python_fingerprint(committed_pem) in proc.stdout, "admin-api 侧指纹没印出来（差在哪不可归因）"
    assert _python_fingerprint(other) in proc.stdout, "ai-agent 侧指纹没印出来（差在哪不可归因）"
    assert "admin-api" in proc.stdout and "ai-agent" in proc.stdout
    assert STATE_OK not in proc.stdout, "不一致的部署里不得同时出现 OK"


def test_exec_both_classpath_default_is_skipped_not_green(tmp_path, committed_pem):
    """判据 6：**两侧都走 classpath 默认** ⇒ `SKIPPED`、**不得**印 OK，且不因此判红（唯一允许形态）。"""
    # 宿主的 public.pem 仍在（bluegreen 里还声明着 file:），但两侧**候选源**都没配
    proc, _ = _run(
        tmp_path, admin_raw="", agent_raw="", admin_pem=committed_pem, agent_compose_raw=None
    )
    assert STATE_SKIPPED in proc.stdout, f"两侧都没配却没有任何 SKIPPED 读数：\n{proc.stdout}"
    assert STATE_OK not in proc.stdout, "取不到对象却判绿（假绿）"
    assert STATE_INCOMPLETE not in proc.stdout, "两侧都没配就不该报「配置不完整」"
    assert "classpath 默认" in proc.stdout, "SKIPPED 必须打印可归因原因（不是空口的「取不到」）"
    assert proc.returncode == 0, (
        f"两侧都没配不得当成部署失败（本仓口径 = SKIPPED 但不判绿）：\n{proc.stdout}"
    )


def test_exec_one_sided_key_is_incomplete_and_fails(tmp_path, committed_pem):
    """判据 6b：只有一侧有值 ⇒ `INCOMPLETE` + exit 1（「不可判定」不许当放过）。"""
    proc, _ = _run(
        tmp_path,
        admin_raw=JWT_FILE_VALUE,
        agent_raw="",
        admin_pem=committed_pem,
        agent_compose_raw=None,
    )
    assert proc.returncode != 0, f"一侧有钥匙另一侧没有却部署成功：\n{proc.stdout}"
    assert STATE_INCOMPLETE in proc.stdout, proc.stdout
    assert STATE_SKIPPED not in proc.stdout, "一侧有值不许报 SKIPPED（那会被读成「只是这次读不到」）"
    assert STATE_OK not in proc.stdout


def test_exec_missing_host_jwt_file_fails_before_any_up(tmp_path, committed_pem):
    """判据 11 / 红证 b（issue #8989 ④）：宿主 `file:` 路径缺失 ⇒ **前置校验** exit 1，且零 `up -d`。

    改前：这条路径只在**重建容器**时才被读 ⇒ ai-agent fail-closed 起不来（AI 接口全挂），
    而断言此刻 SKIPPED ⇒ 拦不住。改后：在任何 `docker compose up` 之前就判红。
    """
    proc, docker_log = _run(
        tmp_path,
        admin_raw=JWT_FILE_VALUE,
        agent_raw="",
        admin_pem=committed_pem,
        agent_compose_raw="file:/opt/migao-deploy/jwt/absent.pem",
    )
    assert proc.returncode != 0, f"宿主文件缺失却部署成功：\n{proc.stdout}"
    assert "absent.pem" in proc.stdout, f"没把缺失的路径印出来（不可归因）：\n{proc.stdout}"
    assert "不存在" in proc.stdout, proc.stdout
    assert PREFLIGHT_OK not in proc.stdout, "缺失却被判 OK（假绿）"
    assert "up -d" not in docker_log, f"前置校验之后仍发生了容器重建（顺序错了）：\n{docker_log}"
    assert "JWT_KEY_SAME_SOURCE" not in proc.stdout, "前置校验就该中止，不该走到同源断言"


def test_exec_nginx_upstream_not_200_fails(tmp_path, committed_pem):
    """判据 7：本机上游非 200 ⇒ 判红，且**先**真的试过 reload（不是没动 nginx 就报错）。"""
    proc, log = _run(
        tmp_path,
        admin_raw=JWT_FILE_VALUE,
        agent_raw=JWT_FILE_VALUE,
        admin_pem=committed_pem,
        agent_pem=committed_pem,
        probe_code=502,
    )
    assert proc.returncode != 0, f"上游 502 却部署成功：\n{proc.stdout}"
    assert NGINX_FAIL in proc.stdout, proc.stdout
    assert NGINX_OK not in proc.stdout, "上游客读数与失败读数同时出现"
    assert "nginx -s reload" in log, "没试 reload 就直接判失败（判据位置不对）"


def test_exec_nginx_upstream_200_is_green(tmp_path, committed_pem):
    """正向：上游 200 ⇒ `NGINX_UPSTREAM=OK` 且部署继续（说明上一条的 FAIL 不是恒红）。"""
    proc, log = _run(
        tmp_path,
        admin_raw=JWT_FILE_VALUE,
        agent_raw=JWT_FILE_VALUE,
        admin_pem=committed_pem,
        agent_pem=committed_pem,
    )
    assert proc.returncode == 0, f"正常路径没通过：\n{proc.stdout}\n{proc.stderr}"
    assert NGINX_OK in proc.stdout, proc.stdout
    assert log.count("up -d --no-deps nginx") >= 1, log
    assert "compose exec -T nginx nginx -s reload" in log, "nginx 没有走优雅重载"


# ══════════════════════════════════════════════════════════════════════════
# 五、宿主公钥**物化**（issue #9051）：引入宿主文件依赖必须同时回答「谁创建它」
# ══════════════════════════════════════════════════════════════════════════
#
# 现场（2026-11-23，测试环境 api.migaozn.com；run 45106135656）：
#   `❌ JWT 文件式取值指向的宿主路径**不存在**：/opt/migao-deploy/jwt/public.pem`
#   两次尝试同一读数；同 sha 在 17:55 / 23:32 的 schedule「success」是 `skip=true`（Deploy 步 skipped，
#   **没有部署**）的档 ⇒ 那不是「瞬时抖动后恢复」，是「从未部署成功」。
# 改前：这条宿主路径**没有任何一步负责创建** ⇒ 1.6c 自 2026-11-22T08:48Z 起每次都红（部署腿恒红）。

def test_exec_missing_host_pubkey_is_materialized_from_inline_env_pem(tmp_path, committed_pem):
    """内联 PEM 是宿主权威源 ⇒ 缺失的 `file:` 公钥由它**物化**，部署继续（1.6c + 2.5.9 仍然复核）。

    红证：摘掉 `deploy.sh` 的 1.6d 段 ⇒ 本用例当场红（`JWT_FILE_SELFHEAL=created` 不出现 +
    1.6c 判「不存在」）。
    """
    work = tmp_path / "opt-migao-deploy"
    proc, docker_log = _run(
        tmp_path,
        admin_raw=committed_pem.replace("\n", "\\n"),   # `.env` 的单行 + 字面 \n 形态（真实宿主形态）
        agent_raw="",
    )
    assert proc.returncode == 0, f"宿主权威源（内联 PEM）在，却仍然部署失败：\n{proc.stdout}\n{proc.stderr}"
    written = work / "jwt" / "public.pem"
    assert written.is_file(), f"缺失的公钥没有被物化：\n{proc.stdout}"
    assert written.read_text(encoding="utf-8").strip() == committed_pem.strip(), "物化出来的不是权威源那一份"
    assert f"JWT_FILE_SELFHEAL=created path={work}/jwt/public.pem" in proc.stdout, proc.stdout
    assert PREFLIGHT_OK in proc.stdout, "物化之后 1.6c 仍应逐条校验并给出 OK"
    assert STATE_OK in proc.stdout, "2.5.9 必须复核两侧同源（物化不是放宽）"
    assert "up -d" in docker_log, "物化之后部署必须继续（否则等于把红换成了静默不部署）"


def test_exec_missing_host_pubkey_is_materialized_from_deploy_tree_classpath(tmp_path, committed_pem):
    """`.env.admin-api` **没配**公钥时，权威源 = 部署树里 admin-api 的 classpath 公钥。

    ⇒ 物化该文件 **并且**把 `.env.admin-api` 钉成同一条 `file:` 路径 —— 否则 2.5.9 只能报 INCOMPLETE
    （一侧有值、另一侧「未配置」），部署腿会以另一个红收场。
    """
    work = tmp_path / "opt-migao-deploy"
    proc, docker_log = _run(
        tmp_path,
        admin_raw="",
        agent_raw="",
        classpath_pem=committed_pem,
    )
    assert proc.returncode == 0, f"部署树里有 classpath 公钥，却仍然部署失败：\n{proc.stdout}\n{proc.stderr}"
    written = work / "jwt" / "public.pem"
    assert written.is_file() and written.read_text(encoding="utf-8").strip() == committed_pem.strip()
    assert f"JWT_FILE_SELFHEAL=created path={work}/jwt/public.pem" in proc.stdout, proc.stdout
    env_admin = (work / ".env.admin-api").read_text(encoding="utf-8")
    assert f"JWT_PUBLIC_KEY=file:{work}/jwt/public.pem" in env_admin, (
        f"没有把 .env.admin-api 钉到同一份文件 ⇒ 2.5.9 无法判定两侧同源：\n{env_admin}"
    )
    assert STATE_OK in proc.stdout, proc.stdout
    assert "up -d" in docker_log


def test_exec_missing_host_pubkey_without_authority_still_fails_closed(tmp_path):
    """**真缺失仍然是红**：三条权威源都没有 ⇒ 一个字节都不写，1.6c 前置校验 exit 1、零 `up -d`。

    这是「物化」不降低判别力的承重用例（红证：把 1.6d 的失败分支改成放行 ⇒ 本用例红）。
    """
    proc, docker_log = _run(tmp_path, admin_raw="", agent_raw="")
    assert proc.returncode != 0, f"没有任何权威源却部署成功（假绿）：\n{proc.stdout}"
    assert "public.pem" in proc.stdout and "不存在" in proc.stdout, proc.stdout
    assert "JWT_FILE_SELFHEAL=created" not in proc.stdout, "没有权威源却报了「已物化」"
    assert PREFLIGHT_OK not in proc.stdout
    assert "up -d" not in docker_log
    assert "JWT_KEY_SAME_SOURCE" not in proc.stdout, "前置校验就该中止，不该走到同源断言"


HOST_FILE_LEDGER = REPO_ROOT / "deploy" / "swas" / "host-file-provisioning.json"


def test_every_compose_file_style_host_path_is_registered():
    """**类级元守卫**（issue #9051）：compose 里每个 `file:` 宿主路径都必须登记「谁创建它」。

    口径（让**这一类**进不来，不是只修这一处）：
      - 新加一条 `X: file:/…`（= 又引入一个宿主文件依赖）却没登记 ⇒ 本判据红，逼作者回答
        「谁物化它 / 缺失时哪条判据兜住 / 人怎么处置」；
      - 登记的 `provisioned_by` 指向 `deploy.sh::1.6d` 时，deploy.sh 里必须真有那个锚点
        （`JWT_FILE_SELFHEAL=created`）⇒ 表与实现不许漂；
      - 私钥类只能登记为「人工」，**不许**由仓库物化。

    红证（实跑）：往 `deploy/swas/docker-compose.yml` 加一行 `JWT_PUBLIC_KEY: file:/opt/x/absent.pem` ⇒ 本判据红。
    """
    import json
    ledger = json.loads(HOST_FILE_LEDGER.read_text(encoding="utf-8"))
    registered = {e["path"]: e for e in ledger["paths"]}
    referenced: set[str] = set()
    for name in ("docker-compose.yml", "docker-compose.bluegreen.yml"):
        text = (REPO_ROOT / "deploy" / "swas" / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            key, _, value = stripped.partition(":")
            if key.strip() in ("JWT_PUBLIC_KEY", "JWT_PRIVATE_KEY") and value.strip().startswith("file:"):
                referenced.add(value.strip()[len("file:"):].strip())
    assert referenced, "反空跑锚点：compose 里一条 file: 取值都没扫到（判据扫描面漂了）"
    unregistered = sorted(referenced - set(registered))
    assert not unregistered, (
        "compose 引用了未登记的宿主文件路径（引入宿主依赖必须同时回答「谁创建它」）："
        f"{unregistered} ⇒ 到 deploy/swas/host-file-provisioning.json 登记 provisioned_by / fail_closed_by / remediation"
    )
    deploy_sh = DEPLOY_SH.read_text(encoding="utf-8")
    for path, entry in registered.items():
        anchor = entry.get("evidence_anchor", "")
        if "::1.6d" in entry.get("provisioned_by", ""):
            assert anchor in deploy_sh, (
                f"登记表说 {path} 由 1.6d 物化，但 deploy.sh 里找不到锚点 {anchor!r}（表与实现漂了）"
            )
        if entry.get("kind") == "secret":
            assert "manual" in entry.get("provisioned_by", ""), (
                f"{path} 是私钥 ⇒ 只能登记为人工提供（仓库不许物化私钥）"
            )


# ══════════════════════════════════════════════════════════════════════════
# 六、`JWT_PUBLIC_KEY` 的**取值形态**（issue #9059）：`classpath:` 不许再塌成 unjudgeable
# ══════════════════════════════════════════════════════════════════════════
#
# 现场（run 45116137752，sha `d38b335`，2026-11-23）：
#   admin-api（签发）: 指纹=<不可判定> 来源=.env.admin-api 的 JWT_PUBLIC_KEY
#                     （提取指纹失败：读到了 非 PEM 文本（24 字节，首 40 字：classpath:rsa/public.pem））
#   ai-agent（验签）: 指纹=ba01a29fc44661b9
#   JWT_KEY_SAME_SOURCE=INCOMPLETE ⇒ 中止部署 ⇒ 回滚 sha-1099156
# ⇒ 两侧本该同源（宿主那份就是 1.6d 从**同一份** classpath 资源物化的），只是断言不会解析 `classpath:`。

def test_exec_classpath_admin_key_is_judged_same_source(tmp_path, committed_pem):
    """`classpath:rsa/public.pem` 必须解析成**同一份**公钥再比指纹 ⇒ `JWT_KEY_SAME_SOURCE=OK`、exit 0。

    红证：摘掉 `jwt_key_fingerprint_of` 的 `classpath:*` 分支 ⇒ 本用例当场红（退回 unjudgeable）。
    """
    proc, _ = _run(
        tmp_path,
        admin_raw="classpath:rsa/public.pem",
        agent_raw="",
        admin_pem=committed_pem,          # ai-agent 读的宿主文件（1.6d 物化的那一份）
        classpath_pem=committed_pem,      # 部署树里的 classpath 资源（admin-api 默认签发公钥）
    )
    assert proc.returncode == 0, f"classpath: 形态被当成不可判定 ⇒ 部署恒定中止：\n{proc.stdout}\n{proc.stderr}"
    assert STATE_OK in proc.stdout, proc.stdout
    assert "（classpath 资源" in proc.stdout, f"读数必须点名解析来源（可归因）：\n{proc.stdout}"
    assert _python_fingerprint(committed_pem) in proc.stdout


def test_exec_classpath_resolves_from_persistent_cache_when_src_gone(tmp_path, committed_pem):
    """配置复用 / 回滚档（盘上没有 `src/`）⇒ 从 1.3c 的**持久缓存**解析（issue #9059 的第二个面）。"""
    proc, _ = _run(
        tmp_path,
        admin_raw="classpath:rsa/public.pem",
        agent_raw="",
        cache_pem=committed_pem,          # 只有缓存，没有 src/
    )
    assert proc.returncode == 0, f"持久缓存没被用上 ⇒ 复用档永远 unjudgeable：\n{proc.stdout}"
    assert STATE_OK in proc.stdout, proc.stdout
    assert "（classpath 资源" in proc.stdout, proc.stdout


def test_exec_unresolvable_classpath_stays_unjudgeable_and_fails(tmp_path, committed_pem):
    """**解析不到仍然红**：`classpath:` 指向不存在的资源 ⇒ `INCOMPLETE` + exit 1（不许判绿）。"""
    proc, _ = _run(
        tmp_path,
        admin_raw="classpath:rsa/absent.pem",
        agent_raw="",
        admin_pem=committed_pem,
    )
    assert proc.returncode != 0, f"解析不到的 classpath 却部署成功（假绿）：\n{proc.stdout}"
    assert STATE_INCOMPLETE in proc.stdout, proc.stdout
    assert STATE_OK not in proc.stdout, "解析不到却印了 OK"
    assert "classpath" in proc.stdout and "不可判定" in proc.stdout, f"读数必须可归因：\n{proc.stdout}"


JWT_FORMS_LEDGER = REPO_ROOT / "deploy" / "swas" / "jwt-value-forms.json"


def _case_patterns_of_raw(body: str) -> set:
    """从 `jwt_key_fingerprint_of` 的 `case "${raw}" in` 块里取出**全部**分支模式。"""
    start = body.index('case "${raw}" in')
    block = body[start:]
    end = block.index("\n  esac")
    patterns = set()
    for line in block[:end].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("case "):
            continue
        if stripped.endswith(")") and " " not in stripped.split(")")[0].strip():
            patterns.add(stripped[:-1].strip('"'))
    return patterns


def test_every_jwt_value_form_is_registered():
    """**类级元守卫**（issue #9059）：取值形态**双向**登记，未登记即红。

    口径（让这一类进不来）：
      - `deploy/swas/deploy.sh::jwt_key_fingerprint_of` 的 `case "${raw}" in` 分支
        ⇄ `deploy/swas/jwt-value-forms.json` 的 `pattern` **双向相等**：
        新增一种写法却不登记（⇒ 下一种写法又会静默变成 unjudgeable）⇒ 红；
        登记了而代码里没有（⇒ 登记表成了假承诺）⇒ 红；
      - 每种形态的 `on_unresolvable` **不得**是判绿（fail-closed 是硬口径）；
      - 每个 `anchor` 必须真的出现在 deploy.sh 里（登记与实现不许漂）。

    红证（实跑）：把 `classpath:*` 分支摘掉 ⇒ 本判据红（登记了但代码里没有）。
    """
    import json
    ledger = json.loads(JWT_FORMS_LEDGER.read_text(encoding="utf-8"))
    forms = {f["pattern"]: f for f in ledger["forms"]}
    body = function_body(read_deploy_sh(), "jwt_key_fingerprint_of")
    code = _case_patterns_of_raw(body)
    assert code, "反空跑锚点：没从 jwt_key_fingerprint_of 里扫到任何 case 分支（扫描面漂了）"
    assert sorted(code) == sorted(forms), (
        "取值形态与登记表不一致 ⇒ 要么有新写法没登记（会静默变成 unjudgeable 恒定中止），"
        f"要么登记了代码里没有。代码={sorted(code)} / 登记={sorted(forms)}"
    )
    deploy_sh = read_deploy_sh()
    for pattern, form in forms.items():
        assert form.get("on_unresolvable"), f"{pattern}: 缺 on_unresolvable（解析不到时算什么没写）"
        assert "判绿" not in form["on_unresolvable"].replace("不得判绿", ""), (
            f"{pattern}: on_unresolvable 不许是判绿（fail-closed 是硬口径）：{form['on_unresolvable']!r}"
        )
        assert form["anchor"] in deploy_sh, (
            f"{pattern}: 登记表说它有 {form['anchor']!r} 的读数/实现，deploy.sh 里找不到 ⇒ 表与实现漂了"
        )


def test_no_bare_cjk_command_lines_in_deploy_sh():
    """**类级元守卫**：`deploy.sh` 里不许出现「中文提示被当成命令」的裸行。

    实证（issue #9059 附带发现，run 45116137752）：
      `/opt/migao-deploy/deploy.sh: line 1653: JWT_*: command not found`
      —— **旧版**脚本里一句含 `JWT_*` 的中文提示没有引号包裹，被 bash 当成命令执行。
      回滚档跑的是旧镜像里的旧脚本 ⇒ 现行代码修不了它；但**这一类**必须挡住：
      提示文案只能出现在 `echo` / `printf` / 注释 / 变量赋值里。

    红证（实跑）：在 deploy.sh 里加一行 `JWT_*：两侧必须同源`（无 echo）⇒ 本判据红并具名行号。
    """
    import re as _re
    cjk = _re.compile(r"[\u4e00-\u9fff]")
    allowed = ("echo", "printf", ":", "cat", "exit", "#")
    offenders = []
    for lineno, line in enumerate(read_deploy_sh().splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(allowed):
            continue
        if "=" in stripped.split()[0]:        # 变量赋值（`_jwt_src="…"` / `CACHE_RECOVER_MSG="…"`）
            continue
        first = stripped.split()[0]
        if cjk.search(first):
            offenders.append(f"L{lineno}: {stripped[:100]}")
    assert offenders == [], (
        "这些行把**中文提示**放在了命令位置（bash 会当成命令执行 ⇒ `command not found`，"
        "issue #9059 的回滚档实证）：\n" + "\n".join(offenders) + "\n⇒ 用 echo/printf 包裹或改成注释"
    )


if __name__ == "__main__":  # pragma: no cover - 手工复算入口
    raise SystemExit(pytest.main([__file__, "-q"]))
