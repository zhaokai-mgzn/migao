#!/usr/bin/env python3
"""只读合成探针（issue #8203 · P0-04；审计原文 `acceptance/2026-10-31-launch-audit/findings.md`）。

## 病（改前，durable 读数）

- `docs/deployment/production-deployment.md` §5 把「SLS 采集 + 告警（CPU/内存/磁盘/5xx/健康检查）触达值班」
  列为**必须项**，而仓库内**零实现**（`.github/workflows/` 无 alert 腿、`deploy/` 无 metrics 配置）；
- 线上**唯一**可信探针是 `GET /api/version`（200）与 `ai-api/health`（200），`/actuator/health` 公网 **404**
  （nginx 整段屏蔽）⇒ **没有外部合成探针**；
- 后果：5xx / 白屏 / 证书到期 / 发布失败**都不会主动惊动人**。关联实证 = P0-02（C 端发布腿红 8 次无人处置）、
  P1-03（夜间腿停 55 天）、P1-04（成功即红）。

## 本脚本只做一件事

**从公网打三个只读面，失败即非零退出** —— 由**既有** workflow（`.github/workflows/post-merge-verify.yml`）
承载，判红沿用该腿既有的 **P1 值班 issue** 出口（⛔ 不新增 schedule、不新造告警通道、不加 secret）。

三个面（= 审计 P0-04 验收标准 1 里**当前存在**的那几个）：

| 面 | 判据 | 为什么 |
|---|---|---|
| `https://api.migaozn.com/api/version` | `200` + JSON 含 `app`/`sha`/`builtAt` | 后端活着**且**是这次构建（`sha` 由构建期注入，见 `VersionController`） |
| `https://app.migaozn.com/b/` | `200` + 非空 body | B 端 H5 落地（商家扫码入口） |
| `https://app.migaozn.com/w/` | `200` + 非空 body | 工人报工落地（车间入口） |

**刻意不探 `merchant.migaozn.com/login`**：它的 200 只证静态壳（chunk 可能已删，见审计 P2-03），
证明力弱于上面三条；也**刻意不探 `/terminal/latest.json`**：终端发布尚未上线，发布前它**必然 404**
—— 把它做成探针就等于做一个**永久红**（这正是审计 P1-04「成功即红」的教训）。将来接了终端发布，
按 `Target(allow_status=(404,))` 加一条即可（脚本已支持该语义，见 `allow_status`）。

## 判据（会红才算判据）

- 任一目标失败（连不上 / 状态码不符 / JSON 解析失败 / 缺字段 / body 为空）⇒ **退出码 1**，
  并逐条打印「哪个 URL / 期望什么 / 实际拿到什么 / 复算命令」；
- 重试 `--attempts`（默认 2）**只对网络层 / 5xx 瞬态**生效：滚动重启窗口内的 502 不该开 P1 值班单；
  `4xx` / JSON 形状不符**当场判红**（重试改变不了它们，只会把红推后）。
- **三态**：`0` 全通过 / `1` 至少一条失败 / `2` 用法错误 / `3` **无法判定**（没有可探目标）。
  `3` 不得当 `0` 读（本仓「空跑 = 假绿」同族）。

## 零写（结构性保证）

只发 `GET`；不写任何文件、不碰数据库、不需要凭据（因此可以放在公开 workflow 的只读腿上）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_API_BASE = "https://api.migaozn.com"
DEFAULT_APP_BASE = "https://app.migaozn.com"

USER_AGENT = "migao-synthetic-probe/1.0 (+issue #8203)"

#: 单次请求最多读多少 body（防止一个超大响应把探针自己拖死）
MAX_BODY_BYTES = 64 * 1024

#: 重试只对这些状态码生效（= 滚动重启窗口的瞬态）。4xx 不重试。
TRANSIENT_STATUS = frozenset({425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Target:
    """一个被探的只读面。"""

    name: str
    url: str
    expect_status: int = 200
    #: 要求 body 是 JSON 且**含这些键**（值可以为空串 —— 空 = 「探不到」，由人看输出判断，不在这里判红）
    require_fields: tuple[str, ...] = ()
    #: body 至少多少字节（静态页用它挡「200 + 空 body = 白屏」）
    min_body_bytes: int = 1
    #: 额外允许的状态码（不判红、但输出里标 `allowed`）。给「发布前必然 404」的面留的语义。
    allow_status: tuple[int, ...] = ()


@dataclass
class Result:
    target: Target
    ok: bool
    status: int | None
    detail: str
    body_bytes: int = 0
    fields: dict = field(default_factory=dict)


def default_targets(api_base: str = DEFAULT_API_BASE, app_base: str = DEFAULT_APP_BASE) -> list[Target]:
    """线上真实存在的三个只读面（改这里 = 改探针覆盖面；判据钉住这三条 URL）。"""
    api_base = api_base.rstrip("/")
    app_base = app_base.rstrip("/")
    return [
        Target(
            name="admin-api /api/version",
            url=f"{api_base}/api/version",
            require_fields=("app", "sha", "builtAt"),
        ),
        Target(name="B 端 H5 落地 /b/", url=f"{app_base}/b/", min_body_bytes=1),
        Target(name="工人报工落地 /w/", url=f"{app_base}/w/", min_body_bytes=1),
    ]


def fetch(url: str, timeout: float) -> tuple[int | None, bytes, str]:
    """GET 一个 URL。**从不抛**：网络层错误 ⇒ `(None, b"", 原因)`。

    Returns:
        (status, body, note)；`status is None` 表示连不上 / 超时 / DNS 失败。
    """
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 固定 https 目标
            body = response.read(MAX_BODY_BYTES)
            return response.status, body, ""
    except urllib.error.HTTPError as exc:  # 4xx/5xx 也带 status
        try:
            body = exc.read(MAX_BODY_BYTES)
        except Exception:  # pragma: no cover - 读错误体失败不影响判定
            body = b""
        return exc.code, body, ""
    except Exception as exc:  # URLError / timeout / ssl / 其它
        return None, b"", f"{type(exc).__name__}: {exc}"


def check(target: Target, fetch_fn=fetch, timeout: float = 10.0) -> Result:
    """判一个目标（纯判定 + 一次拉取；重试在 `run()` 里）。"""
    status, body, note = fetch_fn(target.url, timeout)
    if status is None:
        return Result(target, False, None, f"连接失败（{note or '未知原因'}）")
    if status in target.allow_status:
        return Result(target, True, status, f"允许的状态码 {status}（该面当前可能尚未发布）", len(body))
    if status != target.expect_status:
        return Result(target, False, status, f"期望 {target.expect_status}，实际 {status}", len(body))
    if len(body) < target.min_body_bytes:
        return Result(target, False, status, f"body 只有 {len(body)} 字节（空响应 = 白屏）", len(body))

    if target.require_fields:
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            return Result(target, False, status, "响应不是合法 JSON", len(body))
        if not isinstance(payload, dict):
            return Result(target, False, status, f"JSON 顶层不是对象（{type(payload).__name__}）", len(body))
        missing = [name for name in target.require_fields if name not in payload]
        if missing:
            return Result(target, False, status, f"JSON 缺字段 {missing}", len(body))
        fields = {name: str(payload.get(name, "")) for name in target.require_fields}
        sha = fields.get("sha", "")
        detail = f"200 JSON 字段齐备 · sha={sha or '（空 = 探不到构建身份）'}"
        return Result(target, True, status, detail, len(body), fields)

    return Result(target, True, status, f"200 · body {len(body)} 字节", len(body))


def run(
    targets: list[Target],
    fetch_fn=fetch,
    timeout: float = 10.0,
    attempts: int = 2,
    retry_delay: float = 5.0,
    sleep_fn=time.sleep,
) -> list[Result]:
    """跑全部目标；返回逐条结果（**顺序与输入一致**，便于人读）。"""
    results: list[Result] = []
    for target in targets:
        attempt = 0
        while True:
            attempt += 1
            result = check(target, fetch_fn=fetch_fn, timeout=timeout)
            # 只有「瞬态」才重试：连接失败 / 5xx。4xx 与形状不符当场定案。
            transient = result.status is None or result.status in TRANSIENT_STATUS
            if result.ok or not transient or attempt >= attempts:
                if not result.ok and attempt > 1:
                    result = Result(
                        result.target,
                        False,
                        result.status,
                        f"{result.detail}（已重试 {attempt} 次）",
                        result.body_bytes,
                        result.fields,
                    )
                results.append(result)
                break
            sleep_fn(retry_delay)
    return results


def render(results: list[Result]) -> str:
    """人读输出（一行一条 + 一行汇总 + 复算命令）。"""
    lines: list[str] = []
    passed = 0
    for result in results:
        mark = "✅" if result.ok else "❌"
        if result.ok:
            passed += 1
        lines.append(f"{mark} {result.target.name} → {result.status} {result.detail}")
        lines.append(f"   URL: {result.target.url}")
    lines.append("")
    lines.append(f"SYNTHETIC_PROBE pass={passed} fail={len(results) - passed} total={len(results)}")
    if passed != len(results):
        lines.append("复算（零成本、本机可跑）：python3 scripts/synthetic_probe.py")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读合成探针（issue #8203）：打线上三个只读面，失败即非零退出",
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="admin-api 基地址（默认线上）")
    parser.add_argument("--app-base", default=DEFAULT_APP_BASE, help="静态站基地址（默认线上）")
    parser.add_argument("--timeout", type=float, default=10.0, help="单次请求超时秒数")
    parser.add_argument("--attempts", type=int, default=2, help="瞬态失败的重试次数（默认 2）")
    parser.add_argument("--retry-delay", type=float, default=5.0, help="重试间隔秒数")
    return parser


def main(argv: list[str] | None = None, fetch_fn=fetch, sleep_fn=time.sleep) -> int:
    args = build_parser().parse_args(argv)
    targets = default_targets(args.api_base, args.app_base)
    if not targets:
        # 「没有探针目标」不是通过（同族：空跑 = 假绿）
        print("::error::没有可探目标 ⇒ 无法判定（退出码 3，不得当 0 读）")
        return 3
    results = run(
        targets,
        fetch_fn=fetch_fn,
        timeout=args.timeout,
        attempts=max(1, args.attempts),
        retry_delay=max(0.0, args.retry_delay),
        sleep_fn=sleep_fn,
    )
    print(render(results))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":  # pragma: no cover - 入口
    sys.exit(main())
