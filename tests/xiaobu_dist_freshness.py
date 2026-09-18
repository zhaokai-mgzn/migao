#!/usr/bin/env python3
"""tests/xiaobu_dist_freshness.py — 小布 H5 视觉腿的「产物新鲜度」前置断言（issue #4249）。

## 病根（本文件是它的直接对策）

`tests/playwright.xiaobu.config.ts` 曾把**构建与起服务写在同一条 `webServer.command`** 里，而本地
`reuseExistingServer: true`：只要 10086 上已有静态服务在听（上次跑遗留 / 另一个会话起的），Playwright
**直接复用**它 ⇒ **整条命令一步都不执行**（含 `taro build`）⇒ 服务的是**旧 `dist/`**。
实测形态：`--update-snapshots` 报 `8 passed`（全绿）而基线 PNG **逐字节没变** —— 「DOM 断言绿 +
截图基线被写成旧画面」同时发生、**没有任何东西变红**；错基线提交后，真实视觉回归被它**永久放行**。

## 判据（内容指纹，**不依赖 mtime 精度**；§19.2 ③ / issue #4249 的 assertDistFresh 等价物）

构建步骤（`ensure`）落 `dist/.build-stamp.json` = { sourceHash, distHash, builtAt }，
视觉腿起服务**之前**校验三件事：

  ① `sourceHash` == 当前 `src/` + `config/` + 根级构建输入的内容指纹（sha256 over 相对路径 + 内容）
     ⇒ dist 是**当前源码**的产物；
  ② `distHash` == 当前 `dist/` 内容指纹 ⇒ 落指纹之后产物没被换掉（内容级，与时间无关）；
  ③ 关键产物 `dist/index.html` 存在 ⇒ 起服务后真的有东西可服务。

三态退出码（与仓内既有口径一致）：`0` = 新鲜；`1` = 陈旧/构建失败（fail-closed）；`3` = **未判定**
（没有构建指纹）—— 「看不了」不得当「没问题」，故**不是 0**。

## 两个子命令（CI 与本地行为不同，这正是"不改 CI 侧行为"的落点）

- `check  --project <mini-app>`：只校验。**不构建**。CI 走这条（构建由 workflow 的步骤单独完成，
  本包无权改 `.github/**`）⇒ 无指纹时 exit 3，由配置侧**只告警不阻塞** ⇒ CI 行为与改动前等价。
- `ensure --project <mini-app>`：本地走这条 —— 产物新鲜则**跳过重建**（快路径），否则**先删旧指纹
  再显式构建**（`npm run build:h5`，可用 `--build-cmd` 覆盖，供测试注入），构建退出 0 才落新指纹。
  构建失败 ⇒ exit 1 并把构建输出尾巴带出来（旧写法 `>/dev/null 2>&1;` 把构建失败**吞掉**、服务照起）。

## 边界（照实登记）

- 「构建退出 0 但产物逐字节不变」与「产物本来就是最新的」在**内容层不可区分**（能区分的只有 mtime，
  §19.2 ③ 明令禁止）⇒ 护栏强度 = 「构建步骤确实跑过（退出 0）+ 产物与本次指纹自洽」，
  与 `frontend/mini-app/e2e/lib/harness.js: assertDistFresh`（weapp 侧）同强度。
- 指纹覆盖 `src/` + `config/` + 根级构建输入（`package.json` / `babel.config.js` / `tsconfig.json` /
  `project.config.json`，存在才纳入），**不含依赖树内容**（同 weapp 口径）。
- 只认 `dist/index.html` 作关键产物（H5 入口）——多认几个路径会引入「产物布局变了就假红」的风险。
- CI 侧本护栏为**诊断态**（无指纹 ⇒ 未判定不阻塞）：CI 的保证仍来自 workflow 的步骤顺序，
  **本文件不新增 CI 侧强度、也不改其行为**。

红证与用例见 `tests/unit_ci_workflows/test_xiaobu_h5_dist_freshness.py`（`case_ids: MC-012`）。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

STAMP_NAME = ".build-stamp.json"
# 关键产物（H5 入口）：起服务后 200 的那个文件
DIST_ARTIFACTS = ("index.html",)
# 影响构建产物的源码根目录（同 frontend/mini-app/e2e/lib/source-hash.js 的口径）
SOURCE_ROOTS = ("src", "config")
# 根级构建输入：存在才纳入指纹（改了依赖/编译配置而不重建，同样该判陈旧）
SOURCE_ROOT_FILES = ("package.json", "babel.config.js", "tsconfig.json", "project.config.json")
DEFAULT_BUILD_CMD = "npm run build:h5"
SKIP_NAMES = {".DS_Store", STAMP_NAME}

EXIT_OK = 0
EXIT_STALE = 1
EXIT_UNDECIDABLE = 3

REBUILD_HINT = "请先执行：cd frontend/mini-app && npm run build:h5（或让本护栏的 ensure 子命令代跑）"


class Verdict:
    """三态判定结果（`code` 即退出码）。"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message

    @property
    def ok(self) -> bool:
        return self.code == EXIT_OK

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Verdict(code={self.code}, message={self.message!r})"


def _iter_files(root: Path):
    """递归列出文件（跳过 `.DS_Store` 与构建指纹自身；路径排序保证与文件系统顺序无关）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".DS_Store")
        for name in sorted(filenames):
            if name in SKIP_NAMES:
                continue
            yield Path(dirpath) / name


def _hash_files(root: Path, files) -> dict:
    root = Path(root)
    digest = hashlib.sha256()
    count = 0
    for path in files:
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        count += 1
    return {"hash": digest.hexdigest(), "files": count}


def compute_source_hash(project_root) -> dict:
    """`src/` + `config/` + 根级构建输入的内容指纹（与 mtime 无关）。"""
    project_root = Path(project_root)
    files = []
    for name in SOURCE_ROOTS:
        root = project_root / name
        if root.is_dir():
            files.extend(_iter_files(root))
    for name in SOURCE_ROOT_FILES:
        path = project_root / name
        if path.is_file():
            files.append(path)
    files.sort(key=lambda p: str(p.relative_to(project_root)))
    result = _hash_files(project_root, files)
    result["roots"] = [name for name in SOURCE_ROOTS if (project_root / name).is_dir()]
    return result


def compute_dist_hash(dist_dir) -> dict:
    """`dist/` 当前内容指纹（不含构建指纹自身）。"""
    dist_dir = Path(dist_dir)
    if not dist_dir.is_dir():
        return {"hash": "", "files": 0}
    return _hash_files(dist_dir, sorted(_iter_files(dist_dir), key=lambda p: str(p.relative_to(dist_dir))))


def read_stamp(project_root):
    """读构建指纹；缺失/损坏 → None（调用方按「未判定」处理，不当成通过）。"""
    try:
        data = json.loads((Path(project_root) / "dist" / STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_stamp(project_root) -> dict:
    """落构建指纹（构建链的第二步；`ensure` 在构建退出 0 之后调用）。"""
    project_root = Path(project_root)
    dist = project_root / "dist"
    source = compute_source_hash(project_root)
    dist_hash = compute_dist_hash(dist)
    stamp = {
        "sourceHash": source["hash"],
        "sourceFiles": source["files"],
        "sourceRoots": source["roots"],
        "distHash": dist_hash["hash"],
        "distFiles": dist_hash["files"],
        "builtAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "builder": "tests/xiaobu_dist_freshness.py",
    }
    (dist / STAMP_NAME).write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return stamp


def check(project_root) -> Verdict:
    """校验「起服务要用的 dist 是当前源码的产物」——不构建。"""
    project_root = Path(project_root)
    dist = project_root / "dist"
    stamp = read_stamp(project_root)
    if stamp is None:
        return Verdict(
            EXIT_UNDECIDABLE,
            f"⚠️ 未判定：没有构建指纹 {dist / STAMP_NAME}（无法判断 dist 是否当前源码的产物）\n"
            "  本地跑视觉腿走 ensure（会显式构建并落指纹）；CI 侧构建由 workflow 完成，此处只告警不阻塞。",
        )

    missing = [name for name in DIST_ARTIFACTS if not (dist / name).exists()]
    if missing:
        return Verdict(
            EXIT_STALE,
            f"❌ 构建产物缺失：{', '.join(missing)}（指纹声称 dist 构建于 {stamp.get('builtAt')}）\n"
            "  ⇒ 起静态服务只会服务 404/旧文件，跑出来的绿不是当前代码的绿。\n" + REBUILD_HINT,
        )

    source = compute_source_hash(project_root)
    if stamp.get("sourceHash") != source["hash"]:
        return Verdict(
            EXIT_STALE,
            "❌ 构建产物陈旧（内容指纹与当前源码不一致）：\n"
            f"  dist 构建于 {stamp.get('builtAt')}（源码指纹 {str(stamp.get('sourceHash'))[:12]}…，"
            f"{stamp.get('sourceFiles')} 个文件）\n"
            f"  当前源码指纹 {source['hash'][:12]}…（{source['files']} 个文件）\n"
            "  ⇒ 继续跑等于「用旧构建验证新代码」：旧产物渲染的 DOM 可能让新断言照过，"
            "而截图基线会被写成**旧画面**且全绿（issue #4249 实测形态）。\n" + REBUILD_HINT,
        )

    dist_hash = compute_dist_hash(dist)
    if stamp.get("distHash") != dist_hash["hash"]:
        return Verdict(
            EXIT_STALE,
            "❌ 构建产物在落指纹之后被替换（dist 内容指纹与指纹文件不符）：\n"
            f"  指纹记录 {str(stamp.get('distHash'))[:12]}…（{stamp.get('distFiles')} 个文件）\n"
            f"  当前 dist {dist_hash['hash'][:12]}…（{dist_hash['files']} 个文件）\n"
            "  ⇒ 被服务的东西不是本次构建的产物（可能是另一个检出/另一次构建写进了同一个 dist/）。\n"
            + REBUILD_HINT,
        )

    return Verdict(
        EXIT_OK,
        f"✔ 产物新鲜：源码指纹 {source['hash'][:12]}… / dist 指纹 {dist_hash['hash'][:12]}…"
        f"（构建于 {stamp.get('builtAt')}）",
    )


def _output_tail(text: str, lines: int = 15, limit: int = 2000) -> str:
    kept = "\n".join(text.strip().splitlines()[-lines:])
    return kept[-limit:]


def ensure(project_root, build_cmd=None, env=None) -> Verdict:
    """本地路径：产物新鲜则跳过重建；否则先删旧指纹再显式构建，构建成功才落新指纹。"""
    project_root = Path(project_root)
    stamp_path = project_root / "dist" / STAMP_NAME
    current = check(project_root)
    if current.ok:
        return Verdict(EXIT_OK, f"{current.message}\n（产物已新鲜，跳过重建）")

    # 先删旧指纹：构建失败/中断时绝不能留下一个「声称新鲜」的旧指纹（否则下次 check 假绿）
    if stamp_path.exists():
        stamp_path.unlink()

    command = build_cmd or DEFAULT_BUILD_CMD
    proc = subprocess.run(
        command,
        shell=True,
        cwd=str(project_root),
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )
    tail = _output_tail((proc.stdout or "") + (proc.stderr or ""))
    if proc.returncode != 0:
        return Verdict(
            EXIT_STALE,
            f"❌ 构建失败（exit {proc.returncode}）：{command}\n"
            f"  （旧实现把构建写进 webServer 命令并 `>/dev/null 2>&1;` 吞掉退出码，构建挂了也照样起服务）\n"
            f"  构建输出（末 15 行）：\n{tail}",
        )
    if not (project_root / "dist").is_dir():
        return Verdict(
            EXIT_STALE,
            f"❌ 构建退出 0 但没有 dist/ 目录：{command}\n  构建输出（末 15 行）：\n{tail}",
        )

    stamp = write_stamp(project_root)
    after = check(project_root)
    if not after.ok:
        return Verdict(
            EXIT_STALE,
            f"❌ 构建后仍未通过新鲜度校验（指纹 {str(stamp.get('sourceHash'))[:12]}… 未能证明产物来自当前源码）\n"
            + after.message,
        )
    return Verdict(EXIT_OK, f"✔ 已重建并落构建指纹（{command}）\n{after.message}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="小布 H5 视觉腿的产物新鲜度护栏（issue #4249）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (
        ("check", "只校验（不构建；无指纹 ⇒ exit 3 未判定）"),
        ("ensure", "必要时显式构建再校验（本地路径，失败关闭）"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--project", required=True, help="mini-app 项目根（含 src/ 与 dist/）")
        if name == "ensure":
            p.add_argument("--build-cmd", default=None, help=f"构建命令（默认 {DEFAULT_BUILD_CMD}）")
    args = parser.parse_args(argv)

    project_root = Path(args.project).expanduser().resolve()
    if not (project_root / "src").is_dir():
        print(f"⚠️ 未判定：{project_root} 下没有 src/ —— 项目根给错了？", file=sys.stderr)
        return EXIT_UNDECIDABLE

    verdict = check(project_root) if args.cmd == "check" else ensure(project_root, args.build_cmd)
    print(verdict.message)
    return verdict.code


if __name__ == "__main__":
    sys.exit(main())
