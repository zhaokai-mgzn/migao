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
| 2 | **部署期硬断言接线**：`deploy.sh` 有唯一一份指纹函数 + 唯一一份断言段，段里三态齐备（`JWT_KEY_SAME_SOURCE` 取 `OK` / `MISMATCH` / `SKIPPED`），不一致分支必须 `exit 1`，且**排在 2.6 nginx 之前**（切完流量立刻判） | 删掉断言段 / 去掉 `exit 1` / 把 SKIPPED 写成 OK ⇒ 红 |
| 3 | **指纹口径同源**：shell 侧 `jwt_pubkey_fingerprint()` 与 `scripts/align_agent_jwt_key.py::fingerprint` 对同一份 PEM 必须给出**同一个**指纹（两份实现漂了 ⇒ 断言与处置工具互相打架） | 改成截 8 位 / 含换行 / 换算法 ⇒ 红 |
| 4 | **执行式：一致 ⇒ 绿**（桩 docker / curl，跑**真实** `deploy.sh`） | `JWT_KEY_SAME_SOURCE=OK` 不出现 ⇒ 红 |
| 5 | **执行式：不一致 ⇒ 判红且两个指纹都印出来** | 只有一句「401」不说差在哪 ⇒ 红 |
| 6 | **执行式：取不到 ⇒ SKIPPED（不可判定）且**不得**印 OK** | 空值当成「已对齐」⇒ 红（假绿） |
| 7 | **执行式：nginx 上游非 200 ⇒ 判红**（且**先**真的试过 reload） | 探不到也 exit 0 ⇒ 红 |
| 8 | **类级元守卫**：`deploy.sh` 里**每一个**会重建「被 nginx 代理的服务」的 `up -d --no-deps` 之后，必须在附近调用上游断言；唯一豁免 = green 探针容器（豁免的**依据** = nginx.conf 里没有任何 `*-green` 上游，同文件另判） | 新增一处裸 `up -d` ⇒ 红 |
| 9 | **手工路径同样带断言**：提到 `--force-recreate` 的**可复制提示**必须紧跟 reload + 探测 200 的命令 | 只给 recreate、不给 reload ⇒ 红（正是本次 502 的现实入口） |

## 红证（改前，逐条可复算）

```bash
grep -c 'JWT_PUBLIC_KEY: |' deploy/swas/docker-compose.yml   # 改前 1（内联 PEM）
grep -c 'JWT_KEY_SAME_SOURCE' deploy/swas/deploy.sh          # 改前 0（部署期没有任何断言）
grep -c 'NGINX_UPSTREAM=' deploy/swas/deploy.sh              # 改前 0（reload 之后不探测）
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

#: 机器可读三态（ASCII 锚点 —— 判据不拿中文文案当结构锚）
STATE_OK = "JWT_KEY_SAME_SOURCE=OK"
STATE_MISMATCH = "JWT_KEY_SAME_SOURCE=MISMATCH"
STATE_SKIPPED = "JWT_KEY_SAME_SOURCE=SKIPPED"
NGINX_OK = "NGINX_UPSTREAM=OK"
NGINX_FAIL = "NGINX_UPSTREAM=FAIL"

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
    """判据 2：部署期硬断言存在、唯一、三态齐备、不一致必须 `exit 1`、且在 2.6 nginx 之前。"""
    v = []
    for state in (STATE_OK, STATE_MISMATCH, STATE_SKIPPED):
        if text.count(state) != 1:
            v.append(f"`{state}` 出现 {text.count(state)} 次（必须恰好 1 次 —— 三态各一条机器可读行）")
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
    # 不一致分支必须 fail-closed
    m = re.search(rf"{re.escape(STATE_MISMATCH)}(.*?)(?:else\n|^fi$)", text, re.S | re.M)
    if not m:
        v.append("找不到不一致分支（`JWT_KEY_SAME_SOURCE=MISMATCH` 之后到 else/fi 之间）")
    elif "exit 1" not in m.group(1):
        v.append("不一致分支没有 `exit 1`（不一致会被当成部署成功 —— 正是本单要拦的形态）")
    # SKIPPED 分支不得印 OK（「取不到」不许判绿）
    m = re.search(rf"{re.escape(STATE_SKIPPED)}(.*?)(?:^elif |^fi$)", text, re.S | re.M)
    if not m:
        v.append("找不到 SKIPPED 分支")
    elif STATE_OK in m.group(1):
        v.append("SKIPPED 分支里印了 OK（取不到对象却判绿 = 假绿）")
    # 位置：断言必须在 2.6 nginx **之前**（切完流量立刻判，不是收尾才判）
    i_jwt = text.find("== 2.5.9")
    # 取**最后一处** `up -d nginx`：断言函数体里还有一处「幂等起 nginx」（在 2.5.9 之前）
    i_nginx_up = text.rfind('docker compose up -d --no-deps nginx\n')
    if i_jwt < 0:
        v.append("deploy.sh 里找不到 JWT 同源断言段（`== 2.5.9`）")
    elif i_nginx_up >= 0 and i_jwt > i_nginx_up:
        v.append("JWT 同源断言排在 nginx 更新之后（应当在切完流量、收尾之前）")
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
    """注入③：把 `JWT_KEY_SAME_SOURCE=OK` 那一行删掉 ⇒ 判据 2 必红（三态不齐）。"""
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


def _make_src_tar(dest: Path) -> None:
    stage = dest.parent / "stage" / "migao-main" / "deploy" / "swas"
    stage.mkdir(parents=True, exist_ok=True)
    for name in ("docker-compose.yml", "docker-compose.bluegreen.yml", "nginx.conf"):
        shutil.copy(REPO_ROOT / "deploy" / "swas" / name, stage / name)
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(dest.parent / "stage" / "migao-main", arcname="migao-main")


def _prepare(tmp_path: Path) -> tuple:
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
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    return work, script, bin_dir, state, tar_path, keys


def _run(tmp_path: Path, *, admin_raw: str, agent_raw: str, admin_pem: str = "",
         agent_pem: str = "", probe_code: int = 200, extra_env: dict | None = None):
    work, script, bin_dir, state, tar_path, keys = _prepare(tmp_path)
    (keys / "admin-api.env").write_text(admin_raw, encoding="utf-8")
    (keys / "ai-agent.env").write_text(agent_raw, encoding="utf-8")
    (keys / "admin-api.pem").write_text(admin_pem, encoding="utf-8")
    (keys / "ai-agent.pem").write_text(agent_pem, encoding="utf-8")
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
        agent_raw=JWT_FILE_VALUE,
        admin_pem=committed_pem,
        agent_pem=other,
    )
    assert proc.returncode != 0, f"不同源却返回 0（假绿）：\n{proc.stdout}"
    assert STATE_MISMATCH in proc.stdout, proc.stdout
    assert _python_fingerprint(committed_pem) in proc.stdout, "admin-api 侧指纹没印出来（差在哪不可归因）"
    assert _python_fingerprint(other) in proc.stdout, "ai-agent 侧指纹没印出来（差在哪不可归因）"
    assert "admin-api" in proc.stdout and "ai-agent" in proc.stdout
    assert STATE_OK not in proc.stdout, "不一致的部署里不得同时出现 OK"


def test_exec_unjudgeable_is_skipped_not_green(tmp_path, committed_pem):
    """判据 6：任一侧取不到 ⇒ `JWT_KEY_SAME_SOURCE=SKIPPED`、**不得**印 OK，且不因此判红。"""
    proc, _ = _run(tmp_path, admin_raw=JWT_FILE_VALUE, agent_raw="", admin_pem=committed_pem)
    assert STATE_SKIPPED in proc.stdout, f"取不到却没有任何 SKIPPED 读数：\n{proc.stdout}"
    assert STATE_OK not in proc.stdout, "取不到对象却判绿（假绿）"
    assert proc.returncode == 0, (
        f"不可判定不得当成部署失败（本仓口径 = SKIPPED 但不判绿）：\n{proc.stdout}"
    )


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


if __name__ == "__main__":  # pragma: no cover - 手工复算入口
    raise SystemExit(pytest.main([__file__, "-q"]))
