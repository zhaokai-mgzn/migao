#!/usr/bin/env python3
"""bmini 小程序**上传前**自检：五道闸 + 主包体积（issue #8629）。

## 为什么要有它

2026-11-04 上传前手工核对，连踩三个坑（每个都真发生过）：

1. 省掉 `TARO_APP_API_URL` ⇒ 包里烘进 `http://localhost:8080`
   （`frontend/bmini-app/src/utils/constants.ts` 的默认值），真机连不上；
2. 包里的中文被 webpack 编译成 **unicode 转义**（`\\u4eba\\u5de5\\u5ba2\\u670d`）
   ⇒ 直接 `grep "AI生成"` 恒 0 命中，会把「标识没进包」误判成「已进包」的反面，
   也会把「已进包」误判成没进 —— **本脚本先解码再匹配**；
3. `appid` 在仓里是 `touristappid` 占位 ⇒ 不配 `project.private.config.json`
   就上传会传到游客账号，白折腾一轮。

## 用法

    python3 scripts/bmini-build-check.py                 # 检查 frontend/bmini-app/dist
    python3 scripts/bmini-build-check.py --dist ~/x/dist
    python3 scripts/bmini-build-check.py --strict-appid  # 上传前：appid 占位也算失败
    python3 scripts/bmini-build-check.py --self-test     # 造 fixture 验红绿

退出码：0 = 全绿（允许有 warn）/ 1 = 有 fail / 2 = 用法或环境错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = REPO_ROOT / "frontend" / "bmini-app" / "dist"
PRIVATE_CFG = REPO_ROOT / "frontend" / "bmini-app" / "project.private.config.json"
PLACEHOLDER_APPID = "touristappid"
MAIN_PKG_LIMIT = 2 * 1024 * 1024  # 微信主包硬上限 2 MB
WARN_RATIO = 0.95
DEFAULT_API = "https://app.migaozn.com"
AI_TESTID = "ai-generated-label"
AI_NOTE_TEXT = "内容由人工智能生成"

_UNICODE_ESC = re.compile(r"\\u([0-9a-fA-F]{4})")


def decode_unicode_escapes(text: str) -> str:
    """把 `\\u4eba` 这类转义还原成中文（包里就是这种形态）。"""
    return _UNICODE_ESC.sub(lambda m: chr(int(m.group(1), 16)), text)


def js_files(dist: Path) -> list[Path]:
    return [p for p in dist.rglob("*.js") if p.is_file()]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def bundle_text(dist: Path) -> tuple[str, str]:
    """返回 (原文, 解码后文本) —— 两次扫描各自用对的那份。"""
    raw = "\n".join(read_text(p) for p in js_files(dist))
    return raw, decode_unicode_escapes(raw)


def resolve_appid(dist: Path) -> tuple[str | None, str]:
    """优先 project.private.config.json（开发者工具真实上传用的那份），回落 dist 里的。"""
    if PRIVATE_CFG.exists():
        try:
            appid = json.loads(read_text(PRIVATE_CFG)).get("appid")
            if appid:
                return appid, str(PRIVATE_CFG.relative_to(REPO_ROOT))
        except json.JSONDecodeError:
            pass
    cfg = dist / "project.config.json"
    if cfg.exists():
        try:
            return json.loads(read_text(cfg)).get("appid"), str(cfg)
        except json.JSONDecodeError:
            return None, str(cfg)
    return None, "dist/project.config.json（缺失）"


def run_checks(dist: Path, api_url: str, strict_appid: bool) -> list[tuple[str, str, str]]:
    """返回 [(level, 名称, 说明)]，level ∈ ok / warn / fail。"""
    checks: list[tuple[str, str, str]] = []
    if not dist.is_dir():
        return [("fail", "dist 目录", f"不存在：{dist}（先跑一次 build:weapp）")]

    files = js_files(dist)
    if not files:
        return [("fail", "构建产物", f"{dist} 下没有任何 .js —— 这不是一次成功的构建")]

    raw, decoded = bundle_text(dist)

    # 1 API 域名
    hits = raw.count(api_url)
    checks.append(
        ("ok" if hits else "fail", "API 域名",
         f"命中 {api_url} ×{hits}" if hits else
         f"包里没有 {api_url} —— 构建时漏了 TARO_APP_API_URL，真机会连 localhost")
    )

    # 2 localhost
    local = raw.count("localhost")
    checks.append(
        ("ok" if local == 0 else "fail", "本地地址",
         "0 处 localhost" if local == 0 else
         f"{local} 处 localhost —— 用 TARO_APP_API_URL=https://app.migaozn.com 重新构建")
    )

    # 3 构建期变量
    env_hits = raw.count("process.env")
    checks.append(
        ("ok" if env_hits == 0 else "fail", "构建期变量",
         "0 处 process.env" if env_hits == 0 else
         f"{env_hits} 处 process.env —— 环境变量没被替换，真机会读到 undefined")
    )

    # 4 appid
    appid, source = resolve_appid(dist)
    if not appid:
        checks.append(("fail", "appid", f"读不到（{source}）—— 配 project.private.config.json"))
    elif appid == PLACEHOLDER_APPID:
        checks.append(
            ("fail" if strict_appid else "warn", "appid",
             f"仍是占位 {PLACEHOLDER_APPID}（{source}）—— 上传前必须在 "
             "frontend/bmini-app/project.private.config.json 写真实 appid，否则传到游客账号")
        )
    else:
        checks.append(("ok", "appid", f"{appid}（{source}）"))

    # 5 AI 标识（解码后匹配）
    has_testid = AI_TESTID in decoded
    has_note = AI_NOTE_TEXT in decoded
    checks.append(
        ("ok" if (has_testid and has_note) else "fail", "AI 标识",
         f"{AI_TESTID} ✓ / 「{AI_NOTE_TEXT}」 ✓" if (has_testid and has_note) else
         f"{AI_TESTID}={has_testid}、「{AI_NOTE_TEXT}」={has_note} —— "
         "微信「深度合成-AI问答」类目要求 AI 生成内容显著标注（BM-007）")
    )

    # 附：主包体积
    total = sum(p.stat().st_size for p in dist.rglob("*") if p.is_file())
    mb = total / 1024 / 1024
    if total > MAIN_PKG_LIMIT:
        level, note = "fail", f"{mb:.2f} MB 超过微信主包上限 2 MB"
    elif total > MAIN_PKG_LIMIT * WARN_RATIO:
        level, note = "warn", f"{mb:.2f} MB（余量不足，考虑分包）"
    else:
        level, note = "ok", f"{mb:.2f} MB / 2 MB"
    checks.append((level, "主包体积", note))
    return checks


def render(checks: list[tuple[str, str, str]]) -> int:
    icon = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}
    for level, name, detail in checks:
        print(f"{icon[level]} {name:<8} {detail}")
    fails = sum(1 for c in checks if c[0] == "fail")
    warns = sum(1 for c in checks if c[0] == "warn")
    print(f"\n{'✅ 通过' if not fails else '❌ 未通过'}（fail={fails} warn={warns}）")
    return 0 if fails == 0 else 1


def _fixture(root: Path, *, appid: str, extra_js: str = "", with_ai: bool = True) -> Path:
    dist = root / "dist"
    (dist / "pages" / "chat" / "index").mkdir(parents=True, exist_ok=True)
    (dist / "app.js").write_text('var u="https://app.migaozn.com";', encoding="utf-8")
    ai = (
        'var t="ai-generated-label";var n="\\u5185\\u5bb9\\u7531\\u4eba\\u5de5\\u667a\\u80fd\\u751f\\u6210";'
        if with_ai else ""
    )
    (dist / "pages" / "chat" / "index" / "index.js").write_text(ai + extra_js, encoding="utf-8")
    (dist / "project.config.json").write_text(json.dumps({"appid": appid}), encoding="utf-8")
    return dist


def self_test() -> int:
    """红绿自证：好 fixture 必须全绿，三种坏 fixture 必须各自判红。"""
    global PRIVATE_CFG
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        PRIVATE_CFG = root / "nonexistent.json"  # 让 appid 走 dist 里的那份

        cases = [
            ("good", _fixture(root / "a", appid="wx0000000000000001"), ("fail", [])),
            ("localhost", _fixture(root / "b", appid="wx0000000000000001",
                                   extra_js='var x="http://localhost:8080";'), ("fail", ["本地地址"])),
            ("no-ai", _fixture(root / "c", appid="wx0000000000000001", with_ai=False), ("fail", ["AI 标识"])),
            ("placeholder-appid", _fixture(root / "d", appid=PLACEHOLDER_APPID), ("fail", ["appid"])),
        ]

        ok = True
        for name, dist, (want, want_fail_names) in cases:
            checks = run_checks(dist, DEFAULT_API, strict_appid=True)
            fails = [c[1] for c in checks if c[0] == "fail"]
            passed = (not fails) if want == "ok" else all(n in fails for n in want_fail_names)
            print(f"  {'✓' if passed else '✗'} self-test: {name}（fail={fails or '无'}）")
            ok &= passed
        print(f"\n{'✅' if ok else '❌'} self-test {'通过' if ok else '未通过'}")
        return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="bmini 小程序上传前自检")
    ap.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    ap.add_argument("--api-url", default=DEFAULT_API)
    ap.add_argument("--strict-appid", action="store_true",
                    help="上传前用：appid 是 touristappid 占位也算失败")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.dist.is_dir():
        print(f"❌ dist 不存在：{args.dist}\n   先在 frontend/bmini-app 跑 "
              "TARO_APP_API_URL=https://app.migaozn.com npx taro build --type weapp", file=sys.stderr)
        return 2
    print(f"bmini 上传前自检 · dist={args.dist}\n")
    return render(run_checks(args.dist, args.api_url, args.strict_appid))


if __name__ == "__main__":
    sys.exit(main())
