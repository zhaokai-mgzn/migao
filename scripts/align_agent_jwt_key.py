#!/usr/bin/env python3
"""把 ai-agent 的 `JWT_PUBLIC_KEY` 对齐到 admin-api 的签发密钥（issue #6801）。

## 病（为什么需要这条命令）

admin-api 与 ai-agent 的验签公钥是**各自独立下发**的：

| 服务 | 取值处 | 是否入仓 |
|---|---|---|
| admin-api | `jwt.public-key` = `classpath:rsa/public.pem`（`backend/admin-api/src/main/resources/rsa/public.pem`） | ✅ 入仓 |
| ai-agent | `.env` 的 `JWT_PUBLIC_KEY` | ❌ gitignored |

⇒ 仓库里**换过密钥对**之后，本地那份 `.env` 会**静默陈旧**，而两侧都不报错。真栈形态是
`06-agent-sessions` / `07-chat` 收到 `401`（ai-agent 日志逐字
`JWT verification failed: invalid token - Signature verification failed`）——
**读起来像产品鉴权缺陷**，实际是环境失配（2026-08-13 的 #360 换过密钥对，本地 `.env` 停在更早那对）。

## 用法

    python3 scripts/align_agent_jwt_key.py            # 就地改写 <repo>/backend/ai-agent-service/.env
    python3 scripts/align_agent_jwt_key.py --check    # 只报状态，不写盘

退出码（三态，`3` 不得当 `0` 读）：`0` 已对齐（或已写好）；`1` 失配 / 写盘失败；`3` 判不了（取不到键）。
⚠️ 改完 `.env` **必须重启 ai-agent**（配置不热加载）。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_PUBLIC_PEM = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa" / "public.pem"
AGENT_ENV = REPO_ROOT / "backend" / "ai-agent-service" / ".env"
KEY = "JWT_PUBLIC_KEY"


def fingerprint(raw: str | None) -> str | None:
    """公钥指纹：只吃 PEM 正文（空白无关）。私钥 / 非 PEM / 非 base64 ⇒ None（fail-closed）。"""
    if not raw:
        return None
    t = raw.strip().strip('"').strip("'").replace("\\n", "\n")
    if "PRIVATE KEY" in t:
        return None
    m = re.search(r"-----BEGIN PUBLIC KEY-----(.*?)-----END PUBLIC KEY-----", t, re.S)
    if not m:
        return None
    body = "".join(m.group(1).split())
    try:
        base64.b64decode(body, validate=True)
    except Exception:
        return None
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def read_env_value(text: str, key: str = KEY) -> str | None:
    """取 `.env` 里某键的原始值（`.env` 既有 `KEY=` 也有 `export KEY=` 两种形态）。

    **只认单行形态**：值被写成真多行（即文件已被写坏）⇒ 返回 None（fail-closed，不得当对齐读）。
    """
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("export "):
            s = s[len("export "):].lstrip()
        if s.startswith(key + "="):
            return s.split("=", 1)[1]
    return None


def _first_readable(*paths: Path) -> str | None:
    """按序取第一个可读文件的内容（worktree 形态：本仓缺件时回落主仓）。"""
    for path in paths:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def resolve(env_path: Path, pem_path: Path) -> tuple[str | None, str | None, str | None]:
    """返回 `(admin-api 指纹, ai-agent 指纹, admin-api 公钥原文)`。

    取不到 / 非法 ⇒ 指纹为 `None`（判不了，**不得当对齐读**）。
    admin-api 侧优先吃 `JWT_PUBLIC_KEY_PEM`（compose 注入形态），否则读 `pem_path`（入仓的 classpath 公钥）
    —— 写盘时**必须写这一份**（否则会把「注入的那一对」误写成「入仓的那一对」）。
    """
    injected = os.environ.get("JWT_PUBLIC_KEY_PEM")
    if injected:
        api_raw, api_fp = injected, fingerprint(injected)
    else:
        api_raw = _first_readable(pem_path, Path(os.environ.get("ALIGN_PEM_FALLBACK", "")) if os.environ.get("ALIGN_PEM_FALLBACK") else pem_path)
        api_fp = fingerprint(api_raw)
    env_raw = _first_readable(env_path, Path(os.environ.get("ALIGN_ENV_FALLBACK", "")) if os.environ.get("ALIGN_ENV_FALLBACK") else env_path)
    agent_fp = fingerprint(read_env_value(env_raw)) if env_raw else None
    return api_fp, agent_fp, api_raw


def resolve_fingerprints(env_path: Path, pem_path: Path) -> tuple[str | None, str | None]:
    api_fp, agent_fp, _ = resolve(env_path, pem_path)
    return api_fp, agent_fp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把 ai-agent 的 JWT_PUBLIC_KEY 对齐到 admin-api 签发密钥")
    ap.add_argument("--check", action="store_true", help="只报状态、不写盘")
    ap.add_argument("--state", action="store_true",
                    help="机器可读三态单行（供 ui_smoke_merchant.sh 预检消费）："
                         "aligned:<fp> | mismatch:<api_fp>:<agent_fp> | unknown:<api_fp|na>:<agent_fp|na>")
    ap.add_argument("--env", default=os.environ.get("ALIGN_ENV") or str(AGENT_ENV),
                    help=f"ai-agent .env 路径（默认 {AGENT_ENV}）")
    ap.add_argument("--public-pem", default=os.environ.get("ALIGN_PEM") or str(API_PUBLIC_PEM),
                    help="admin-api 公钥路径")
    args = ap.parse_args(argv)

    env_path, pem_path = Path(args.env), Path(args.public_pem)

    if args.state:
        # ⚠️ `--state` 是**纯报告档，永远 exit 0**：三态已经在输出里，调用方（起栈脚本）就靠它取词。
        #    若这里按状态给非零码，`"$(… --state || echo unknown)"` 那类写法会把 fallback 文本**追加**上去
        #    ⇒ 变量变成两行 ⇒ 指纹串里混进 `na`（实测踩过）。
        api_fp, agent_fp, _ = resolve(env_path, pem_path)
        if api_fp and api_fp == agent_fp:
            print(f"aligned:{api_fp}")
        elif api_fp and agent_fp:
            print(f"mismatch:{api_fp}:{agent_fp}")
        else:
            print(f"unknown:{api_fp or 'na'}:{agent_fp or 'na'}")
        return 0

    api_fp, agent_fp, api_raw = resolve(env_path, pem_path)
    if api_fp is None:
        print(f"✗ 判不了：读不到 / 不是合法公钥 PEM —— {pem_path}", file=sys.stderr)
        return 3
    if agent_fp is None:
        print(f"✗ 判不了：{env_path} 里取不到可读的 {KEY}（缺文件 / key 缺失 / 被写成真多行）", file=sys.stderr)
        return 3
    if agent_fp == api_fp:
        print(f"✓ 已对齐（指纹 {api_fp}）—— 无需改动")
        return 0

    if args.check:
        print(f"✗ 失配：admin-api={api_fp} ai-agent={agent_fp}")
        return 1

    env_text = env_path.read_text(encoding="utf-8")
    # 写盘对象 = `resolve()` 认的那一份（注入优先），**不是**无条件读 classpath 那份
    pem_raw = api_raw or ""
    # 归一为**单行 + \n 转义**形态（仓库既有形态；`re.sub` 的替换体走 lambda，
    # 否则 `\n` 会被当成转义展开成真换行 ⇒ 把 .env 写坏，实测踩过）
    canonical = pem_raw.strip().replace("\n", "\\n")
    new_line = f'{KEY}="{canonical}"'
    if re.search(rf"^{KEY}=", env_text, re.M):
        new_text = re.sub(rf"^{KEY}=.*$", lambda _m: new_line, env_text, count=1, flags=re.M)
    else:
        new_text = env_text.rstrip("\n") + "\n" + new_line + "\n"
    # 写坏防护：写完必须**只有一行**该键，且指纹可读
    if sum(1 for ln in new_text.splitlines() if ln.startswith(KEY + "=")) != 1:
        print("✗ 写盘中止：改写后该键不是单行形态（拒绝写坏 .env）", file=sys.stderr)
        return 1
    if fingerprint(read_env_value(new_text)) != api_fp:
        print("✗ 写盘中止：改写后指纹读不出来（拒绝写坏 .env）", file=sys.stderr)
        return 1

    shutil.copy2(env_path, env_path.with_suffix(env_path.suffix + ".bak-align"))
    env_path.write_text(new_text, encoding="utf-8")
    print(f"✓ 已对齐：{agent_fp or '判不了'} → {api_fp}")
    print(f"  已改写 {env_path}（备份 {env_path.name}.bak-align）")
    print("  ⚠️ 必须重启 ai-agent 才生效（.env 不热加载）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
