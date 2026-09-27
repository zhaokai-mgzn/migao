#!/usr/bin/env python3
"""C 端 H5 **产物新鲜度**守卫（issue #4184 判据 2）。

## 病灶（实测，2026-09-25 12:39 +08）

```
$ curl -sI https://app.migaozn.com/js/app.js | grep -i last-modified
last-modified: Sun, 30 Aug 2026 06:54:48 GMT      # = 08-30 14:54 +08
$ git log -1 --format=%cI origin/main -- frontend/mini-app
2026-09-21T06:13:46Z                              # = 09-21 14:13 +08
```

⇒ **线上产物比源码改动落后 ~22 天**，而**没有任何东西会因此变红**（「C 端已部署」的说法会一直被当真）。

## 判据

`线上产物的 Last-Modified` **≥** `origin/main 上 frontend/mini-app/** 的最近一次改动时间 − 宽限期`。

- 宽限期（`--grace-hours`，默认 6h）：刚合并还没部署完时**不该红**；
- **fail-closed**：取不到 Last-Modified / 取不到源码改动时间 ⇒ 判 **无法判定**（exit 3），**不得当"新鲜"读**
  —— 网络与部署都可能让人误以为"没红就是好的"。

## 判红（gate）—— 默认口径，issue #4184 用户裁定 B

超期 ⇒ **判红**：`::error::` + **exit 2**（默认就是 gate）。
理由（用户 2026-09-27 逐字裁定「通路建好并自证（含新鲜度判据从 warning 翻成 gate），但首次发布由人手动触发」）：
C 端 H5 的**发布通路已经建好**（`.github/workflows/c-end-h5-publish.yml`）⇒ 「没有通路所以只告警」这个
前提**已不成立**；此时只告警 = 让「线上落后 28 天」继续长得像健康。

🔴 **后果如实登记（不粉饰）**：通路建好而**首次发布尚未发生**之前，这条腿在 `main` 上**会红**，
直到有人手动发布一次（`gh workflow run c-end-h5-publish.yml --ref main -f publish=true`）。
这是**真实且可操作的**红 —— 不许再用「先 warning 一段时间」把它藏起来（那正是用户否掉的那个选项）。

人工排障 / 一次性诊断要看「不判红的读数」⇒ `--no-gate`（只 `::warning::` + exit 0）。

## 读数（本仓机制协议）

`scripts/mechanism_liveness.sh` 是**唯一**发射器；本脚本只交一行
`MIGAO-H5FRESH-SUMMARY seen=… acted=… rc=… why=…`（与 `stale_report_reaper.py` 同形）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

URL_ENV = "MIGAO_H5_URL"
DEFAULT_URL = "https://app.migaozn.com/js/app.js"
SOURCE_PATH = "frontend/mini-app"
EXIT_OK, EXIT_USAGE, EXIT_STALE, EXIT_UNKNOWN = 0, 1, 2, 3


def fetch_last_modified(url: str, timeout: int = 20) -> datetime | None:
    """线上产物的 `Last-Modified`（HEAD 请求）。取不到 ⇒ None（无法判定，**不等于**新鲜）。"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310（URL 由调用方给定）
            raw = resp.headers.get("Last-Modified")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_source_change(ref: str, cwd: Path, path: str = SOURCE_PATH) -> datetime | None:
    """`ref` 上最近一次改到 `path` 的提交时间（committer date）。取不到 ⇒ None。"""
    proc = subprocess.run(["git", "log", "-1", "--format=%cI", ref, "--", path],
                          cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return datetime.fromisoformat(proc.stdout.strip())
    except ValueError:
        return None


def judge(live: datetime | None, source: datetime | None, *, grace_hours: int) -> tuple[str, str]:
    """纯函数 ⇒ (verdict, 读数)。verdict ∈ {fresh, stale, unknown}（**可单测**，不碰网络）。"""
    if live is None:
        return "unknown", "取不到线上产物的 Last-Modified ⇒ 无法判定（**不等于**新鲜）"
    if source is None:
        return "unknown", f"取不到 {SOURCE_PATH} 在 origin/main 上的最近改动时间 ⇒ 无法判定"
    delta = live - source
    if delta >= -timedelta(hours=grace_hours):
        return "fresh", (f"线上产物 {live:%Y-%m-%dT%H:%MZ} ≥ 最近一次源码改动 {source:%Y-%m-%dT%H:%MZ}"
                         f"（差 {delta.total_seconds() / 3600:.1f}h；宽限 {grace_hours}h）")
    return "stale", (f"线上产物**陈旧**：{live:%Y-%m-%dT%H:%MZ} 早于 {SOURCE_PATH} 最近改动 "
                     f"{source:%Y-%m-%dT%H:%MZ}（落后 {abs(delta.total_seconds()) / 86400:.1f} 天）")


def summarise(rc: int, seen: int, acted: int, why: str) -> None:
    print("MIGAO-H5FRESH-SUMMARY "
          f"seen={seen} acted={acted} rc={rc} why={why.replace(chr(10), ' ')[:200]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="h5-freshness-guard",
                                 description="C 端 H5 产物新鲜度守卫（默认判红 = gate；--no-gate 仅人工诊断）")
    ap.add_argument("--url", default=os.environ.get(URL_ENV) or DEFAULT_URL)
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--grace-hours", type=int, default=6)
    ap.add_argument("--no-gate", dest="gate", action="store_false",
                    help="只 ::warning:: 并 exit 0（**仅**人工诊断用；默认是判红）")
    args = ap.parse_args(argv)

    live = fetch_last_modified(args.url)
    source = last_source_change(args.ref, Path.cwd())
    verdict, why = judge(live, source, grace_hours=args.grace_hours)

    seen, acted = 1, 0
    if verdict == "unknown":
        print(f"⏭️  {why}", file=sys.stderr)
        summarise(EXIT_UNKNOWN, seen, acted, why)
        return EXIT_UNKNOWN
    if verdict == "stale":
        acted = 1
        # 判红 vs 报告型：**同一份读数**，两种出口。默认判红（gate）；`--no-gate` 只给人工诊断。
        level = "warning" if not args.gate else "error"
        print(f"::{level}:: {why}（URL={args.url}；发布通路 = .github/workflows/c-end-h5-publish.yml，"
              f"人工发布：gh workflow run c-end-h5-publish.yml --ref main -f publish=true）")
    print(f"{'✅' if verdict == 'fresh' else '⚠️ '} {why}")
    if verdict == "stale" and args.gate:
        summarise(EXIT_STALE, seen, acted, why)
        return EXIT_STALE
    summarise(EXIT_OK, seen, acted, why)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())