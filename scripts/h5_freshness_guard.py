#!/usr/bin/env python3
"""C 端 H5 **产物新鲜度**守卫（issue #4184 判据 2）。

## 病灶（实测，2026-09-25 12:39 +08）

```
$ curl -sI https://app.migaozn.com/js/app.js | grep -i last-modified
last-modified: Sun, 30 Aug 2026 06:54:48 GMT      # = 08-30 14:54 +08
$ git log -1 --format=%cI origin/main -- frontend/mini-app ':(exclude)frontend/mini-app/tests'
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

## 三态**不许塌**：浅克隆 ≠ 陈旧（issue #7073）

CI run `38971606256`（`schedule` / sha `2f4b8b84b`）判「线上 `2026-10-09T14:15Z` 早于
`frontend/mini-app` 最近改动 `2026-10-16T16:18Z`」并 **exit 2** —— 而 `2026-10-16T16:18Z`
**正是 HEAD 自己的提交时间**：那条腿的 checkout 是**默认 `fetch-depth: 1`（浅克隆）**⇒
`git log -1 <ref> -- frontend/mini-app` 只有 1 个提交可取、**不判路径** ⇒ 判据把「线上新鲜」算成「陈旧」，
**每天 cron 恒判红一次**（真信号被淹）。真值（全 history 复算）= `2026-10-08T03:20:02Z`（`9ebdf73d8`）。

⇒ 本脚本**自己**判「历史够不够用」（`_is_shallow`）：浅克隆 ⇒ `rc=3`（**无法判定**，具名点名「浅克隆」，
按 `::error::` 上报）——**绝不**塌成 `rc=2`（确实陈旧）。两处修：调用面的 checkout 给
`fetch-depth: 0`（`.github/workflows/c-end-h5-publish.yml`）+ 本脚本能判「读不到历史」（下一个调用面的兜底）。

## 🔴 时间戳只是**代理** ⇒ 判「陈旧」前必须做**内容等价**复核（issue #8924）

`Last-Modified` 判的是「发布时间」，不是「内容是否真的落后」。两者会分叉：
源码改动**不影响产物字节**时（devDependency 升级 / 只动 lint 配置 / 注释），时间戳会判「陈旧」，
而要人跑一次发布，发布出来的字节与线上**完全相同**（issue #6672 已经因为 `tests/**` 修过一次口径，
但那只是**一个**特例：把「哪些改动不影响产物」写成白名单，永远会漏）。

⇒ 判「陈旧」之后，**如果手里有本次构建产物**（`--dist-dir`），就把线上产物与它**逐字节比对**：

- 全部等价 ⇒ `verdict=equivalent` ⇒ **exit 0**（读数写明「仅发布时间戳旧，内容无差异 ⇒ 不需要发布」）；
- 有差异 ⇒ 仍 `stale` ⇒ **exit 2**，并把**差异文件清单**印出来（哪几个文件、各多大）——
  「真陈旧」的判别力**一分不降**，只是不再为「等价」付一次无意义的发布；
- `--dist-dir` 指向的目录不存在 / 读不出 ⇒ **不得**当等价（fail-closed，仍 exit 2 并点名原因）。

构建**确定性**是这条判据成立的前提，实测（2026-11-23，本机 + 线上同一份工具链）：
同一份源码连跑两次 `npm run build:h5` ⇒ `js/app.js` / `index.html` 的 sha256 **逐字节一致**
（`c60722d3…` / `e4ab045f…`）；且**线上** `index.html` / `css/app.css` 与本机 HEAD 构建**完全一致**
（`e4ab045f…` / `a328eb9b…`）—— 只有 `js/app.js` 不同（线上 258451 vs 构建 258576 字节；
构建须与发布腿同 env —— `TARO_APP_API_URL` / `TARO_APP_AI_API_URL` 会被 baked 进产物，
差这两个变量时字节数会再偏 24 字节 —— 差异本身来自 11-18 的 `zustand 5.0.15→5.1.0`
运行时依赖升级）⇒ 那一天的红是**真陈旧**，不是假红。
规范化只做两件无争议的事（BOM / CRLF），**不做**「标准化后再比」这种会放过真差异的处理。

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
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

URL_ENV = "MIGAO_H5_URL"
DEFAULT_URL = "https://app.migaozn.com/js/app.js"
SOURCE_PATH = "frontend/mini-app"

# 🔴 **产物来源面**（issue #6672，2026-10-10 实测）：`tests/**` **不进** Taro 构建产物 ⇒
# 只改测试**不能**让线上产物"陈旧"。实测：PR #6659 只改了 `frontend/mini-app/tests/setup.ts`，
# 就把 main 上这条腿判红，并要求人工跑一次 `c-end-h5-publish.yml` —— 发布出来的字节与上一版**完全一样**（纯浪费）。
SOURCE_EXCLUDES = ("frontend/mini-app/tests",)
EXIT_OK, EXIT_USAGE, EXIT_STALE, EXIT_UNKNOWN = 0, 1, 2, 3

#: `dist/index.html` 对应站点**根**（其余文件按相对路径拼）
DIST_INDEX = "index.html"


def _normalise(raw: bytes) -> bytes:
    """只做两件无争议的规范化（BOM / CRLF）；**不**做任何会放过真差异的「标准化」。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.replace(b"\r\n", b"\n").rstrip(b"\n")


def _root_of(url: str) -> str:
    """由产物 URL 求出站点根（`.../js/app.js` ⇒ `https://host`）；取不到 ⇒ 空串。"""
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def served_equivalence(dist_dir: Path, url: str, timeout: int = 20) -> tuple[bool, list[str], str]:
    """本次构建产物 ⇄ 线上产物**逐字节等价**判定（issue #8924）。

    返回 `(equal, diffs, detail)`：
      - `equal=True` 只在**每个**文件都能取到线上对应物且规范化后字节相同；
      - 任一个取不到（404 / 网络 / 空）⇒ 放进 `diffs` ⇒ **不算等价**（fail-closed）；
      - `detail` 是给出可归因读数的短句（文件数 / 差异数）。
    """
    root = _root_of(url)
    if not root:
        return False, ["<无法从 URL 求出站点根>"], f"URL 不合法：{url!r}"
    files = sorted(p for p in dist_dir.rglob("*") if p.is_file() and p.name != ".DS_Store")
    if not files:
        return False, [f"<{dist_dir} 里没有任何文件>"], f"构建产物目录为空：{dist_dir}"
    diffs: list[str] = []
    for path in files:
        rel = path.relative_to(dist_dir).as_posix()
        target = root + ("/" if rel == DIST_INDEX else "/" + rel)
        try:
            with urllib.request.urlopen(  # noqa: S310（URL 由调用方给定）
                urllib.request.Request(target, method="GET"), timeout=timeout
            ) as resp:
                live = resp.read()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            diffs.append(f"{rel}（线上取不到：{exc}）")
            continue
        if _normalise(live) != _normalise(path.read_bytes()):
            diffs.append(f"{rel}（线上 {len(live)} 字节 ≠ 构建 {path.stat().st_size} 字节）")
    if diffs:
        return False, diffs, f"比对 {len(files)} 个文件，差异 {len(diffs)} 个"
    return True, [], f"{len(files)} 个文件逐字节一致"


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


def _is_shallow(cwd: Path) -> bool:
    """检出是浅克隆吗（`--depth`/`fetch-depth: <0`）？**判不了 ⇒ `False`**（退回原行为，不改口径）。

    ⚠️ 为什么必须自证这件事（issue #7073，CI run `38971606256` 逐字读数）：浅克隆里
    `git log -1 <ref> -- frontend/mini-app` **不判路径**（只有一个提交可取）⇒ 它回的是 **HEAD 自己的
    提交时间**（CI 读数 `2026-10-16T16:18Z` = `2f4b8b84b` 的提交时间），而真值（全 history）=
    `2026-10-08T03:20:02Z`（`9ebdf73d8`）⇒ 判据把**新鲜的**线上产物判成**陈旧**并每天恒判红一次
    （真信号被淹）。修法是**两处**：① 调用面的 checkout 给 `fetch-depth: 0`（本单的 workflow 改动，
    由 `tests/unit_ci_workflows/test_h5_freshness_needs_full_history.py` 钉住）② 判据自己**有能力**
    判「历史读不到」（这里）—— 只做 ① 的话，下一个调用面还会重演。
    """
    proc = subprocess.run(["git", "rev-parse", "--is-shallow-repository"],
                          cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def last_source_change(ref: str, cwd: Path, path: str = SOURCE_PATH) -> tuple[datetime | None, str]:
    """`ref` 上最近一次改到 `path`（**不含**产物来源之外的 `tests/**`，issue #6672）的提交时间。

    返回 `(时间, 具名原因)`：取不到 ⇒ `(None, 原因)`（**不等于**新鲜）。
    - 浅克隆 / 历史不足 ⇒ 原因**点名浅克隆**（三态不许塌：这一支必须走 `rc=3` 无法判定，
      **不得**塌成 `rc=2` 确实陈旧 —— issue #7073）；
    - 其它取不到（ref 不存在 / 路径不存在）⇒ 原因照旧。
    """
    if _is_shallow(cwd):
        return None, (f"检出是**浅克隆**（`git rev-parse --is-shallow-repository` = true）⇒ `git log` 只有 "
                      f"1 个提交、**不判路径** ⇒ 取不到 {path} 的真实历史（会把 HEAD 的提交时间当成源码改动）")
    # 只排除落在本次 `path` 之下的那些排除项（path 可被调用方覆盖 ⇒ 不误伤）
    excludes = [f":(exclude){e}" for e in SOURCE_EXCLUDES if e == path or e.startswith(path.rstrip("/") + "/")]
    proc = subprocess.run(["git", "log", "-1", "--format=%cI", ref, "--", path, *excludes],
                          cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None, f"取不到 {path} 在 {ref} 上的最近改动时间（ref/路径不存在，或历史不足）"
    try:
        return datetime.fromisoformat(proc.stdout.strip()), ""
    except ValueError:
        return None, f"`git log` 的读数不是合法时间戳：{proc.stdout.strip()!r}"


def unknown_level(why: str) -> str:
    """`rc=3`（无法判定）该以什么等级上报：**浅克隆 = CI 接线缺口 ⇒ `error`**，其余按告警。

    浅克隆不是「线上可能不新鲜」，而是**判据根本算不出对象**（issue #7073 的假红就是这样来的）
    ⇒ 必须上报，不能只留一行 stderr 让人以为「没红就是好的」。
    """
    return "error" if "浅克隆" in why else "warning"


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


def main(argv: list[str] | None = None, cwd: Path | None = None) -> int:
    """CLI 入口。`cwd` 只给判据用（默认进程 cwd）—— 让判据能在**真浅克隆**里驱动同一条路径。"""
    ap = argparse.ArgumentParser(prog="h5-freshness-guard",
                                 description="C 端 H5 产物新鲜度守卫（默认判红 = gate；--no-gate 仅人工诊断）")
    ap.add_argument("--url", default=os.environ.get(URL_ENV) or DEFAULT_URL)
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--grace-hours", type=int, default=6)
    ap.add_argument("--dist-dir", default=None,
                    help="本次构建产物目录（**做内容等价复核**用）。给了它且判「陈旧」时，"
                         "线上与产物**逐字节等价** ⇒ exit 0（不需要发布）；有差异 ⇒ 仍 exit 2（真陈旧）")
    ap.add_argument("--no-gate", dest="gate", action="store_false",
                    help="只 ::warning:: 并 exit 0（**仅**人工诊断用；默认是判红）")
    args = ap.parse_args(argv)

    live = fetch_last_modified(args.url)
    source, reason = last_source_change(args.ref, cwd if cwd is not None else Path.cwd())
    verdict, why = judge(live, source, grace_hours=args.grace_hours)
    if verdict == "unknown" and source is None and reason:
        why = f"{reason} ⇒ 无法判定（**不等于**新鲜）"

    # 🔴 判「陈旧」之前先做**内容等价**复核（issue #8924）：时间戳旧 ≠ 内容落后。
    if verdict == "stale" and args.dist_dir:
        dist = Path(args.dist_dir)
        if not dist.is_dir():
            why = f"{why}；内容等价复核**不可用**（--dist-dir 不存在：{dist}）⇒ 仍判红（fail-closed）"
        else:
            equal, diffs, detail = served_equivalence(dist, args.url)
            if equal:
                verdict = "equivalent"
                why = (f"线上产物与本次构建**逐字节等价**（{detail}）—— 仅发布时间戳旧"
                       f"（线上 {live:%Y-%m-%dT%H:%MZ} 早于源码改动 {source:%Y-%m-%dT%H:%MZ}），"
                       f"内容没有差异 ⇒ **不需要发布**")
            else:
                head = "、".join(diffs[:5]) + (f" 等 {len(diffs)} 个" if len(diffs) > 5 else "")
                why = f"{why}；内容复核**不等价**：{head}"

    seen, acted = 1, 0
    if verdict == "unknown":
        # 浅克隆 ⇒ `::error::`（它会让判据把新鲜判成陈旧）；其余取不到 ⇒ `::warning::`（网络/ref 面）。
        # 两者都走 **exit 3**（无法判定），**绝不**与「确实陈旧」（exit 2，判红）合并 —— issue #7073 判据 3。
        print(f"::{unknown_level(why)}:: ⏭️  {why}", file=sys.stderr)
        summarise(EXIT_UNKNOWN, seen, acted, why)
        return EXIT_UNKNOWN
    if verdict == "stale":
        acted = 1
        # 判红 vs 报告型：**同一份读数**，两种出口。默认判红（gate）；`--no-gate` 只给人工诊断。
        level = "warning" if not args.gate else "error"
        print(f"::{level}:: {why}（URL={args.url}；发布通路 = .github/workflows/c-end-h5-publish.yml，"
              f"人工发布：gh workflow run c-end-h5-publish.yml --ref main -f publish=true）")
    print(f"{'✅' if verdict in ('fresh', 'equivalent') else '⚠️ '} {why}")
    if verdict == "stale" and args.gate:
        summarise(EXIT_STALE, seen, acted, why)
        return EXIT_STALE
    summarise(EXIT_OK, seen, acted, why)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())