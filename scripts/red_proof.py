#!/usr/bin/env python3
"""red_proof — 红证生成动作的缓存卫生 + 注入自证（issue #4260）。

## 病根：取红证的动作本身会骗人

「注入缺陷 → 跑测试 → 应红 → 还原」里，**改前/改后同字节长度**的文件在**同一秒内**替换时，
Python 的 `.pyc` 头只记 `(mtime 秒, size)` 两项 —— 两者都**没变** ⇒ 解释器**不重编译**、
直接复用旧 `.pyc` ⇒ **注入未生效**，而测试读到的是**旧行为**：

- **假绿证**：注入没生效 ⇒ 测试仍绿 ⇒ 误判「这条判据不会红」（结论是"空断言"，其实是注入失败）
  ⇒ 可能把一个**本来有效**的护栏当废的删掉/放宽；
- **假红证 / 错归因**：读到旧值下的红 ⇒ 把红归因给没生效的注入，写出错误的因果。

它出在**证据生成层** —— 这层是用来抓其它所有问题的；`migao-acceptance` 要求「每条断言都要有红证」，
**红证的可信度本身却没有任何东西保护**。实测（PKG-ROUTE / #4246）：守卫红线第一次对照读成了旧值。

**同族载体**（不止 Python）：Java `.class`（增量编译）、JS/TS 转换缓存（`.next/cache`、vitest/vite
transform cache）、Shell/生成物（同秒替换 + mtime 精度不足）。共同形态 = **依赖时间粒度做新鲜度判定**。

## 固化下来的动作（不靠每个 agent 自觉）

    # ① 记基线（内容指纹，非 mtime/size）
    python3 scripts/red_proof.py fingerprint --json <file>... > /tmp/red_proof.json
    # ② 注入缺陷（同秒同长度也没关系）
    # ③ 自证「注入真的生效了」+ **清缓存**（未生效 ⇒ 非零退出，绝不静默跑测试）
    python3 scripts/red_proof.py injected --manifest /tmp/red_proof.json
    # ④ 跑测试，取红证（此时读到的一定是注入后的真值）
    # ⑤ 还原
    # ⑥ 自证还原干净 + **再清一次缓存**（否则下一轮取的是本轮残留）
    python3 scripts/red_proof.py restored --manifest /tmp/red_proof.json

`--no-clear` 是**诊断模式**：保留旧产物、只报告「运行时会复用它 ⇒ 会读到旧值」并**非零退出**
（用它复现本缺陷：naive 流程在这里会静默拿到假绿证）。

## 载体覆盖（照实登记能力边界，别把「登记了」读成「治住了」）

| 载体 | 本脚本做什么 | 边界 |
|---|---|---|
| Python `.pyc` | 清 `__pycache__` + `*.pyc/*.pyo` + **`sys.pycache_prefix` 真实落点** | 已落码；`pycache_prefix` 是**本机实测的盲区**（见下） |
| Python 测试缓存 | 清 `.pytest_cache` / `.mypy_cache` / `.ruff_cache` | 已落码 |
| JS/TS | 清 `.next/cache` / `node_modules/.cache` / `node_modules/.vite` / `.turbo` / `.jest-cache` / `.parcel-cache` / `*.tsbuildinfo` / `.eslintcache` | 已落码（按目录名白名单，不解析框架版本） |
| Java `.class` | 清 `target/classes` / `target/test-classes` / `build/classes` | 已落码；**未覆盖**自定义 `outputDirectory` / Gradle 变体目录 |
| Shell / 生成物 | **不做时间粒度判定**：一律用**内容指纹**（`content_fingerprint`）判新鲜度 | 已落码（指纹与载体无关） |

**为什么不能只清 `__pycache__`**：`sys.pycache_prefix` / `PYTHONPYCACHEPREFIX` 非空时（macOS 系统
python 默认 `~/Library/Caches/com.apple.python`），`.pyc` **落在仓库外** ⇒ `rm -rf __pycache__` 是**空操作**，
而它看起来"做了清缓存这件事"。故本脚本按 `importlib.util.cache_from_source()` 的**真实落点**清。

## 落码状态登记（照实，别把「脚本存在」读成「有门禁」）

- **未接 CI required check**：现为人工 / 取红证流程调用；自测红证见
  `tests/unit_ci_workflows/test_red_proof_guard.py`。
- 不改 Python/构建工具链本身（`PYTHONDONTWRITEBYTECODE` 之类全局开关会影响性能与其它流程）——
  治的是**取红证的动作**，不是运行环境（issue #4260「不做」）。
- 规范条文见 `docs/testing/test-engineering-standards.md` 的「红证卫生」节。

退出码（与仓内既有三态口径一致）：`0` = 自证通过；`1` = 检出问题（fail-closed）；`3` = **无法判定**
（清单缺失/不可读）—— 「看不了」不得当「没问题」。
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MAX_INLINE_TEXT = 256 * 1024      # 清单里内联原文的上限（超过只留哈希，diff 留痕退化为哈希对照）

# ── 缓存产物白名单（只删这些；**不删**任何别的东西）────────────────────────────────
CACHE_DIR_NAMES = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                   ".jest-cache", ".parcel-cache", ".turbo")
CACHE_NESTED_DIRS = (".next/cache", "node_modules/.cache", "node_modules/.vite",
                     "target/classes", "target/test-classes", "build/classes")
CACHE_FILE_NAMES = (".eslintcache",)
CACHE_FILE_SUFFIXES = (".pyc", ".pyo", ".tsbuildinfo")
# 不下钻的重目录（它们各自的缓存目录已由 CACHE_NESTED_DIRS 在上层收走）
_PRUNE = frozenset(("node_modules", ".git", ".venv", "venv", "dist", "build", "target",
                    ".next", "coverage"))


class RedProofError(RuntimeError):
    """红证不可信（注入未生效 / 与声明不符 / 未还原 / 缓存未清）。"""


class RedProofUndecidable(RedProofError):
    """**无法判定**（清单缺失/不可读）—— 「看不了」不得当「没问题」（退出码 3）。"""


# ── 纯函数层（可单测；CLI 只是薄壳）──────────────────────────────────────────────

def content_fingerprint(path) -> str:
    """文件内容的 sha256（`sha256:<hex>`）。

    **只用内容**：与 mtime / 文件大小无关 —— 同秒同长度替换照样变，而 `(mtime, size)` 判据不会
    （那正是本缺陷的形态：§19.2 ③「不写死易变数字 / 不依赖时间粒度」同族）。
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def assert_injection_effective(before_fp, after_fp, expect_changed=True, *,
                               expected_fp=None, label=""):
    """**注入自证**：先断言「注入真的生效了」，**再**跑测试取红证。

    - `expect_changed=True`：指纹必须**变**（否则报错 —— 这就是「没生效」与「判据是空的」不可区分
      的那一步，必须 fail-closed 而不是静默继续跑测试）；
    - `expect_changed=False`：还原校验，指纹必须**回到基线**；
    - `expected_fp`：声明预期值（不只「变了」，而是「变成了我声明的那个」）。
    """
    where = f"（{label}）" if label else ""
    if expect_changed and before_fp == after_fp:
        raise RedProofError(
            f"注入未生效{where}：内容指纹前后一致 {after_fp} —— 文件内容**没变**。\n"
            "  · 这不是「判据不会红」，而是**注入没落到文件上**"
            "（同秒同长度写回同样字节 / sed 未命中 / 替换目标不存在…）。\n"
            "  · 若你确信内容已变：说明你的「注入后校验」读的是**缓存产物**（`.pyc` / transform cache）"
            "而不是源文件 —— 先 `red_proof.py clear` 再取红证。")
    if not expect_changed and before_fp != after_fp:
        raise RedProofError(
            f"未还原{where}：内容指纹 {after_fp} != 基线 {before_fp}（还原动作没生效或没做全）。")
    if expected_fp is not None and after_fp != expected_fp:
        raise RedProofError(
            f"注入结果与声明不符{where}：实测 {after_fp}，声明 {expected_fp}。")


def diff_summary(before_text, after_text, label="", max_lines=40) -> str:
    """注入前后的**内容差异留痕**（报告里要贴这个，而不是只写「改了 X 就跑红了」）。"""
    lines = list(difflib.unified_diff(before_text.splitlines(), after_text.splitlines(),
                                      fromfile="a/" + label, tofile="b/" + label,
                                      lineterm="", n=2))
    if not lines:
        return "（内容逐字节相同 —— **无差异**：注入未落到文件上）"
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines] + [f"… （截断，共 {len(lines)} 行）"])
    return "\n".join(lines)


def _pycache_prefix_root(root):
    """`root` 在 `sys.pycache_prefix` 下对应的子树（`None` = 没开 prefix）。"""
    prefix = getattr(sys, "pycache_prefix", None) or os.environ.get("PYTHONPYCACHEPREFIX")
    if not prefix:
        return None
    parts = Path(root).resolve().parts[1:]        # 去掉锚点（'/'）
    return Path(prefix).joinpath(*parts) if parts else None


def _pyc_matches_source(pyc, source) -> bool:
    """`.pyc` 头里的新鲜度信息是否**与当前源文件一致**（= 运行时会**复用**它，不重编译）。

    时间戳式（默认）比 `(mtime 秒, size)`；哈希式（PEP 552）比源码哈希。
    ⚠️ 它**只能**回答「运行时会复用这个产物吗」，**不能**回答「这个产物是不是旧的」——
    本缺陷的确切形态正是「头一致但内容不同」，所以**唯一的治法是把产物清掉**（本脚本默认动作）。
    """
    try:
        with open(pyc, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    if len(head) < 16 or not os.path.exists(source):
        return False
    flags = int.from_bytes(head[4:8], "little")
    if flags & 0b1:                               # 哈希式
        with open(source, "rb") as f:
            return head[8:16] == importlib.util.source_hash(f.read())
    st = os.stat(source)
    return (int.from_bytes(head[8:12], "little") == int(st.st_mtime)
            and int.from_bytes(head[12:16], "little") == st.st_size)


def bytecode_would_be_reused(sources) -> list:
    """运行时会**复用**的既有字节码产物清单 `[(source, pyc), …]`（非空 ⇒ 注入会被掩盖）。"""
    out = []
    for src in sources:
        src = Path(src)
        if src.suffix != ".py" or not src.is_file():
            continue
        try:
            pyc = importlib.util.cache_from_source(str(src.resolve()))
        except (ValueError, NotImplementedError):
            continue
        if pyc and os.path.exists(pyc) and _pyc_matches_source(pyc, src):
            out.append((src, Path(pyc)))
    return out


def _iter_cache_artifacts(root):
    """现存缓存产物（白名单内；**只读不删**）。"""
    root = Path(root)
    if root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root):
            d = Path(dirpath)
            for rel in CACHE_NESTED_DIRS:          # 两段式（须在下钻剪枝**之前**收）
                if (d / rel).is_dir():
                    yield d / rel
            for name in list(dirnames):
                if name in CACHE_DIR_NAMES:
                    yield d / name
                    dirnames.remove(name)          # 已收走，不再下钻
                elif name in _PRUNE:
                    dirnames.remove(name)
            for name in filenames:
                if name in CACHE_FILE_NAMES or name.endswith(CACHE_FILE_SUFFIXES):
                    yield d / name
    # 仓库**外**的字节码落点（sys.pycache_prefix）：逐个 `.pyc` 列出，便于报告「到底清了什么」
    pr = _pycache_prefix_root(root)
    if pr and pr.is_dir():
        for dirpath, _dirnames, filenames in os.walk(pr):
            for name in filenames:
                if name.endswith((".pyc", ".pyo")):
                    yield Path(dirpath) / name


def cache_artifacts(root, sources=()) -> list:
    """现存缓存产物清单（清完之后应恒为空 —— 否则不许取红证）。"""
    found = list(_iter_cache_artifacts(root))
    for src in sources:
        src = Path(src)
        if src.suffix != ".py":
            continue
        try:
            pyc = importlib.util.cache_from_source(str(src.resolve()))
        except (ValueError, NotImplementedError):
            pyc = None
        if pyc and os.path.exists(pyc):
            found.append(Path(pyc))
    seen, uniq = set(), []
    for p in found:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def clear_caches(root, sources=()) -> list:
    """清缓存（**注入前后各一次**），返回「清了什么」。

    按白名单删目录/文件；父目录先删（子项随之消失，不再重复报）。
    """
    targets = sorted(set(cache_artifacts(root, sources)), key=lambda p: (len(p.parts), str(p)))
    removed = []
    for t in targets:
        if not t.exists():
            continue
        try:
            if t.is_dir():
                shutil.rmtree(t)
            else:
                t.unlink()
        except OSError:
            continue                               # 删不掉的会留在 cache_artifacts 里 ⇒ 由调用方 fail-closed
        removed.append(t)
    return removed


def assert_caches_clear(root, sources=()):
    """清完之后仍剩缓存产物 ⇒ fail-closed（「清了」必须长得像「清了」）。"""
    left = cache_artifacts(root, sources)
    if left:
        raise RedProofError(
            "缓存未清干净 —— 取到的红证可能是**旧值下的红**：\n  · "
            + "\n  · ".join(str(p) for p in left[:10]))


# ── 清单（基线留痕）───────────────────────────────────────────────────────────

def make_manifest(paths, root) -> dict:
    files = {}
    for p in paths:
        p = Path(p).resolve()
        if not p.is_file():
            raise RedProofError(f"记基线时文件不存在：{p}")
        raw = p.read_bytes()
        rec = {"sha256": content_fingerprint(p), "size": len(raw)}
        rec["text"] = raw.decode("utf-8", "replace") if len(raw) <= MAX_INLINE_TEXT else None
        files[str(p)] = rec
    return {"tool": "red_proof", "issue": 4260, "root": str(Path(root).resolve()), "files": files}


def load_manifest(path):
    p = Path(path)
    if not p.is_file():
        raise RedProofUndecidable(f"清单不存在或不可读：{p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RedProofUndecidable(f"清单解析失败（{e.__class__.__name__}）：{p}") from e
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise RedProofUndecidable(f"清单结构不对（缺 files）：{p}")
    return data


# ── CLI（薄壳）──────────────────────────────────────────────────────────────

def _cmd_fingerprint(args) -> int:
    man = make_manifest(args.paths, args.root)
    if args.json:
        print(json.dumps(man, ensure_ascii=False, indent=2))
    else:
        for path, rec in man["files"].items():
            print(f"{rec['sha256']}  {rec['size']:>9}  {path}")
    return 0


def _cmd_clear(args) -> int:
    removed = clear_caches(args.root, args.source)
    for p in removed:
        print(f"  · 已清 {p}")
    assert_caches_clear(args.root, args.source)
    print(f"✅ 缓存已清（{len(removed)} 项）")
    return 0


def _report_injection(label, rec, live_fp, live_text):
    print(f"  · {label}")
    print(f"      注入前 {rec['sha256']}")
    print(f"      注入后 {live_fp}")
    if rec.get("text") is not None and live_text is not None:
        for line in diff_summary(rec["text"], live_text, label).splitlines():
            print("      " + line)
    else:
        print("      （文件过大，只留哈希对照）")


def _read_live(path):
    p = Path(path)
    if not p.is_file():
        raise RedProofError(f"注入后文件不存在：{p}（注入把树弄坏了，红证不可信）")
    raw = p.read_bytes()
    return content_fingerprint(p), (raw.decode("utf-8", "replace")
                                    if len(raw) <= MAX_INLINE_TEXT else None)


def _cmd_injected(args) -> int:
    man = load_manifest(args.manifest)
    root = args.root or man["root"]
    expects = dict(e.split("=", 1) for e in args.expect)
    print(f"[red_proof] 注入自证：{len(man['files'])} 个文件")
    for path, rec in man["files"].items():
        live_fp, live_text = _read_live(path)
        assert_injection_effective(rec["sha256"], live_fp, True,
                                   expected_fp=expects.get(path), label=path)
        _report_injection(path, rec, live_fp, live_text)

    stale = bytecode_would_be_reused(man["files"])
    print(f"[red_proof] 缓存诊断：运行时会复用 {len(stale)} 个既有字节码产物")
    for src, pyc in stale:
        print(f"  · {pyc}  ← 服务于 {src}")
    if args.no_clear:
        if stale:
            print("❌ 检出「运行时会复用旧产物」：注入**不会生效**，测试会读到**旧值**"
                  "（= 假绿证 / 错归因）。\n"
                  "   → 去掉 --no-clear 先清缓存，或手工清掉上面这些产物后再取红证。",
                  file=sys.stderr)
            return 1
        print("✅ 未发现会被复用的旧产物（--no-clear 诊断模式）")
        return 0

    removed = clear_caches(root, man["files"])
    for p in removed:
        print(f"  · 已清 {p}")
    assert_caches_clear(root, man["files"])
    print(f"✅ 注入已自证生效 + 缓存已清（{len(removed)} 项）"
          "—— 现在可以跑测试取红证（跑完务必 `restored` 还原并再清一次）")
    return 0


def _cmd_restored(args) -> int:
    man = load_manifest(args.manifest)
    root = args.root or man["root"]
    print(f"[red_proof] 还原自证：{len(man['files'])} 个文件")
    for path, rec in man["files"].items():
        live_fp, _ = _read_live(path)
        assert_injection_effective(rec["sha256"], live_fp, False, label=path)
        print(f"  · {path}\n      基线 {rec['sha256']}\n      当前 {live_fp}（一致）")
    removed = clear_caches(root, man["files"])
    assert_caches_clear(root, man["files"])
    print(f"✅ 已还原 + 缓存已清（{len(removed)} 项）—— 下一轮取红证不会被本轮残留污染")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="red_proof.py",
        description="红证卫生：注入前后清缓存 + 内容指纹自证（issue #4260）")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fingerprint", help="记基线内容指纹（可 --json 出清单）")
    f.add_argument("paths", nargs="+")
    f.add_argument("--root", default=str(REPO_ROOT), help="清缓存的作用域（写进清单）")
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=_cmd_fingerprint)

    c = sub.add_parser("clear", help="清缓存（注入前后各一次）")
    c.add_argument("--root", default=str(REPO_ROOT))
    c.add_argument("--source", action="append", default=[],
                   help="额外按真实落点清该源文件的字节码（可重复）")
    c.set_defaults(func=_cmd_clear)

    i = sub.add_parser("injected", help="自证注入生效 + 清缓存（未生效 ⇒ 非零退出）")
    i.add_argument("--manifest", required=True)
    i.add_argument("--expect", action="append", default=[],
                   help="声明预期：<绝对路径>=<sha256:...>（可重复）")
    i.add_argument("--root", default=None, help="清缓存作用域（默认取清单里的 root）")
    i.add_argument("--no-clear", action="store_true",
                   help="诊断模式：只报告「会复用旧产物」并非零退出，不清缓存")
    i.set_defaults(func=_cmd_injected)

    r = sub.add_parser("restored", help="自证还原干净 + 再清一次缓存")
    r.add_argument("--manifest", required=True)
    r.add_argument("--root", default=None, help="清缓存作用域（默认取清单里的 root）")
    r.set_defaults(func=_cmd_restored)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RedProofUndecidable as e:
        print(f"⚠️ 无法判定：{e}", file=sys.stderr)
        return 3
    except RedProofError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
