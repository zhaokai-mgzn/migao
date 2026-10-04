# case_ids: MC-016
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 部署接线类 L0 不变式挂 MC-016
#   「工人端 H5 静态落位 + 页面身份断言」—— issue #6306 补的是这条腿的**发布资产可达性**面。）
r"""发布自检腿的 **module 闭包加载判据** 类级元守卫（issue #6306）。

## 病（实测 2026-10-04，真浏览器 —— 不是推断）

工人端主页 `/w/` 与一体机页 `/w/machine.html` **整页白屏**：真浏览器读数 `bodyText=""`、
`rootChildren=0`、console 逐字 `Failed to load module script: … MIME type of "text/html"`；
坏点 = `/shared/operation-display.mjs` → `200 text/html`（导入者 `render.mjs` / `machine.mjs`）。

根因 = 共享模块住在**仓根** `frontend/shared/`，而发布集只有 `index.html` + `machine.html` + `src/**`
⇒ 线上那个 URL 上什么都没有，被 nginx `location /` 的 `try_files $uri $uri/ /index.html` 接成
**`200` + C 端 index.html**。本单的修法是**树内迁移**（模块搬进 `worker-h5/src/shared/`），
本文件守的是**类**：让「发布集里引用了发布集外的依赖」这类缺陷进不来。

🔴 **为什么必须单立这个守卫（#6293 的 MIME 判据挡不住它）**：`worker-h5-verify-served.sh` 的 ⑥ 走的是
**本仓** `src/**` 的现取文件清单 —— 一个「**仓里存在、线上不存在**」的依赖天然在它的面之外；
而「状态码 200 + 字节哈希逐字节一致 + MIME 也对」这件事**可以同时全绿而页面整页白屏**。

## 本守卫锁什么（每条都能单独变红；红证 = 内存变异 + 一次真跑）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| 1 | **按现取腿集合判**（`deploy/scripts/*-verify-served.sh`，**不写死清单**）：每条腿要么带 module 闭包判据、要么在台账 `tests/unit_ci_workflows/served_leg_module_closure_ledger.json` 里**具名豁免** | 新增第四条腿而不表态 ⇒ 指名判红 |
| 2 | **台账双向活着**：豁免的腿**真没**带判据、带判据的腿**不在**豁免册里、豁免条目不许空转（reason/issue/owner/restart_condition 齐备）、台账不许「全豁免」 | 给已落判据的腿再挂豁免 ⇒ 红；清空豁免册却不落判据 ⇒ 红 |
| 3 | **四组结构锚逐字在位**（起点 = 现取 `*.html` 入口 / 静态 `import` + 动态 `import()` / 空集 fail-closed / `<link rel=stylesheet href>` 断 200） | 删掉任一组（内存变异）⇒ 具名判红 |
| 4 | **判别力自证**：把每组锚换成退化形态（起点写死 `index.html`、只认 `from`、空集返回 0、样式表判据删掉）⇒ 各自判红；**只改注释 ⇒ 不红**（对照读数） | 守卫自己被文案喂红 ⇒ 红 |
| 5 | **实例判据真跑**（活体）：本地静态服务上 ① 完整发布树 ⇒ **绿**；② `.mjs` 发成 `text/html`（线上实测形态）⇒ **红**且**指名**是闭包判据/哪个 URL | 夹具把页面弄坏 ⇒ 假红自证；判据空跑 ⇒ 绿 |

## 边界（照实登记，§19.1）

- 判据 1/2 只保证「**每条现取腿都被显式裁定**」——**不保证**豁免一定合理（那是人的判断，写进了
  `restart_condition` 供复核）；`bmini` / `c-end` 两条腿的豁免理由（打包产物、仓内无 `dist/`）
  由各自 owner 复核。
- 判据 3 认的是**结构锚**（四组片段逐字在位），**不是**语义：把锚点写在死代码里（如 `if false; then … fi`
  里）本守卫看不出来 —— 那一半由判据 5 的**真跑**与线上 CI 承担。
- 判据 5 只在**本机静态服务**上真跑（零网络）；它证明不了线上 nginx 已 reload / 线上的真实响应头
  —— 那是发布腿活体断言（`worker-h5-verify-served.sh` ⑦）在 CI 上的面。
- 本守卫**不改**任何门禁的通过条件、不新增豁免。
"""
from __future__ import annotations

import glob
import http.server
import json
import re
import socket
import subprocess
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "deploy" / "scripts"
LEDGER_PATH = Path(__file__).resolve().parent / "served_leg_module_closure_ledger.json"

#: 必须**带**判据的那条腿（本单的落码面）：不是写死「只有它」——
#: 判据 1 走现取集合，本常量只在**红证/正面判**里指名（避免红证在别的腿上漂）。
WORKER_LEG = "worker-h5-verify-served.sh"
WORKER_SRC = REPO_ROOT / "frontend" / "worker-h5"


def leg_files() -> list[Path]:
    """现取的发布自检腿集合（**不写死清单**：将来新增一条腿 = 自动纳入本守卫）。"""
    return sorted(SCRIPTS_DIR.glob("*-verify-served.sh"))


def ledger() -> dict:
    """台账：**缺文件 ⇒ 抛错**（缺台账 ≠ 无需登记）。"""
    assert LEDGER_PATH.is_file(), (
        f"台账缺失：{LEDGER_PATH.relative_to(REPO_ROOT)} —— 本守卫 fail-closed"
        "（腿的豁免面必须有人裁定，并在 diff 里可见）"
    )
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def closure_problems(name: str, text: str, markers: dict) -> list[str]:
    """**纯函数**：这条腿的 module 闭包判据是否**真的在**（认结构，不认注释文案）。

    四组锚逐组核；每组缺失**具名**报出（红得不具体 = 排查时看不出缺哪一面）。
    """
    bad: list[str] = []
    for key, label in (
        ("entry_glob", "起点：发布集内每个 `*.html` 入口（现取，不许写死 index.html）"),
        ("import_scan", "解析面：静态 `import … from` **与**动态 `import('…')` 字面量"),
        ("empty_set_fail_closed", "空集 fail-closed（「没跑」必须长得像「没跑」）"),
        ("stylesheet_check", "入口 `<link rel=\"stylesheet\" href>` 断 200（正向盲区）"),
    ):
        anchor = markers.get(key) or ""
        if not anchor:
            bad.append(f"{name}: 台账 `criteria_markers.{key}` 为空 —— 判据锚点没登记（不许空转）")
            continue
        # **逐字子串**匹配（不是正则）：锚点是 shell 源码片段，里面全是正则元字符
        # （`$ROOT` 的 `$`、`*.html` 的 `*`、`import(` 的 `(`）—— 当正则用会命中错的形态（实测踩过）。
        if anchor not in text:
            bad.append(f"{name}: 缺【{label}】（锚点 {anchor!r} 在该腿里找不到）—— module 闭包判据不完整")
    return bad


def leg_set_problems(files: list[Path], markers: dict, exemptions: dict) -> list[str]:
    """**纯函数**（判据 1/2/3 的唯一口径，红证直接喂变异）：现取腿集合 ⇄ 台账 的双向核对。"""
    bad: list[str] = []
    if not files:
        bad.append(
            f"{SCRIPTS_DIR.relative_to(REPO_ROOT)} 下一条 `*-verify-served.sh` 都取不到 ⇒ "
            "本守卫会**静默空跑**（fail-closed，不许当通过）"
        )
    if not exemptions and not any(
        closure_problems(p.name, p.read_text(encoding="utf-8"), markers) == [] for p in files
    ):
        bad.append("台账的豁免册为空、且没有任何一条腿带 module 闭包判据 ⇒ 这个面无人管（fail-closed）")
    for path in files:
        text = path.read_text(encoding="utf-8")
        problems = closure_problems(path.name, text, markers)
        if path.name in exemptions:
            if not problems:
                bad.append(
                    f"{path.name}: **已在台账里豁免，但它已经带上了 module 闭包判据** ⇒ "
                    "豁免册只许缩短（销掉这一条，让判据自己被判）"
                )
            entry = exemptions[path.name] or {}
            for key in ("reason", "issue", "owner", "restart_condition"):
                if not entry.get(key):
                    bad.append(f"{path.name}: 豁免条目缺 {key!r}（豁免不许匿名存在）")
        else:
            bad += problems
    for name in sorted(set(exemptions) - {p.name for p in files}):
        bad.append(
            f"台账里的豁免 {name!r} 是**陈旧条目**（现取腿集合里没有这条腿）⇒ 销账（台账只许缩短）"
        )
    return bad


# ── 判据（真语料）─────────────────────────────────────────────────────────────


def test_real_repo_has_no_problems():
    """主判据：真语料上问题清单必须为空（清单的判别力由下面的注入式红证逐条自证）。"""
    data = ledger()
    bad = leg_set_problems(leg_files(), data.get("criteria_markers") or {}, data.get("exemptions") or {})
    assert bad == [], "发布腿 module 闭包判据 / 豁免台账有问题：\n" + "\n".join(f"  · {i}" for i in bad)


def test_coordinates_are_live_not_scanning_air():
    """坐标自证：腿集合、worker 腿、四组锚点、台账都**真的**取到了（防「扫空气」恒绿）。"""
    files = leg_files()
    assert len(files) >= 3, f"只取到 {len(files)} 条发布自检腿（worker / bmini / c-end 三端）"
    assert any(p.name == WORKER_LEG for p in files), f"现取腿集合里没有 {WORKER_LEG}"
    data = ledger()
    markers = data.get("criteria_markers") or {}
    assert len([k for k in markers if not k.startswith("_")]) == 4, (
        f"台账的判据锚点应有 4 组（现取 {sorted(k for k in markers if not k.startswith('_'))}）"
    )
    workers = [p for p in files if p.name == WORKER_LEG]
    assert closure_problems(WORKER_LEG, workers[0].read_text(encoding="utf-8"), markers) == [], (
        f"{WORKER_LEG} 没有带上完整的 module 闭包判据（本单的落码面）"
    )


def test_exemptions_name_the_two_bundled_legs():
    """豁免面**具名**：bmini / c-end 两条腿（打包产物）—— 别的腿不许出现在豁免册里。"""
    exemptions = ledger().get("exemptions") or {}
    assert set(exemptions) == {"bmini-h5-verify-served.sh", "c-end-h5-verify-served.sh"}, (
        "豁免册的成员变了（现取 "
        f"{sorted(exemptions)}）—— 豁免只许缩短，扩面必须在 PR 里显式说明并改本判据"
    )
    assert WORKER_LEG not in exemptions, f"{WORKER_LEG} 不许被豁免（它是本单的落码面）"


# ── 注入式红证（全在内存里；每条都先自证「变异真的生效」）────────────────────────


def _worker_text() -> str:
    return (SCRIPTS_DIR / WORKER_LEG).read_text(encoding="utf-8")


def _mutate(text: str, old: str, new: str) -> str:
    assert old in text, f"变异锚点不在文本里（fail-closed，锚点随重构漂移）：{old!r}"
    mutated = text.replace(old, new, 1)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 该红证是空断言）"
    return mutated


def _live_markers() -> dict:
    return ledger().get("criteria_markers") or {}


def test_red_proof_dropping_the_entry_glob_is_reported():
    """① 把「起点 = 现取 `*.html` 入口」换成**写死 index.html** ⇒ 判红。

    为什么这条是关键：`machine.mjs` 恰是坏点导入者之一 —— 只从 `index.html` 出发**会漏掉那条链**。
    """
    markers = _live_markers()
    mutated = _mutate(
        _worker_text(),
        markers["entry_glob"],
        "find \"$ROOT/frontend/worker-h5\" -maxdepth 1 -name 'index.html' -type f",
    )
    problems = closure_problems(WORKER_LEG, mutated, markers)
    assert any("入口" in p for p in problems), f"把起点写死成 index.html 竟没判红：{problems}"


def test_red_proof_dropping_the_dynamic_import_scan_is_reported():
    """② 解析面退化成「只认 `import`（静态/裸）」⇒ 判红（`app.mjs` 有真实的 `await import('./api.mjs')`）。"""
    markers = _live_markers()
    # 锚点 = 台账里登记的**逐字**片段（含 `(?` ——「动态 `import(` 也要认」那一面）
    mutated = _mutate(_worker_text(), markers["import_scan"], r"\bimport\s+")
    problems = closure_problems(WORKER_LEG, mutated, markers)
    assert any("解析面" in p for p in problems), f"只认静态 import 竟没判红：{problems}"


def test_red_proof_dropping_the_emptyset_branch_is_reported():
    """③ 空集分支**整段删掉**（闭包为空却全绿）⇒ 判红（「没跑」不许长得像「通过」）。"""
    markers = _live_markers()
    text = _worker_text()
    # 形态照 test_served_leg_mime_guard.py 的同款红证：删掉**整段** `if … then bad … fi`
    mutated = re.sub(
        r'if \[ "\$CLOSURE_MJS" -eq 0 \]; then\s*\n\s*bad "module 闭包集合为空[^"]*"\nfi\n',
        "",
        text,
    )
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    problems = closure_problems(WORKER_LEG, mutated, markers)
    assert any("空集" in p for p in problems), f"删掉空集分支竟没判红：{problems}"


def test_red_proof_dropping_the_stylesheet_check_is_reported():
    """④ 样式表判据被删（CSS 404 时页面无样式而 module 闭包照样全绿）⇒ 判红。"""
    markers = _live_markers()
    mutated = _mutate(_worker_text(), markers["stylesheet_check"], "rel-no-such-attr")
    problems = closure_problems(WORKER_LEG, mutated, markers)
    assert any("正向盲区" in p for p in problems), f"删掉样式表判据竟没判红：{problems}"


def test_control_comment_only_edit_does_not_turn_red():
    """对照读数：**只加注释** ⇒ 结论不变（守卫不被自己的文案喂红）。"""
    markers = _live_markers()
    text = _worker_text() + "\n# 只加一行注释（issue #6306 的对照读数）\n"
    assert closure_problems(WORKER_LEG, text, markers) == []


def test_red_proof_unregistered_leg_is_reported():
    """判据 1 的红证：**多出一条腿**而不在台账里表态 ⇒ 具名判红。"""
    data = ledger()
    files = leg_files()
    ghost = files[0].parent / "__ghost-verify-served.sh"
    try:
        ghost.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
        problems = leg_set_problems(
            sorted(SCRIPTS_DIR.glob("*-verify-served.sh")),
            data["criteria_markers"],
            data["exemptions"],
        )
    finally:
        ghost.unlink(missing_ok=True)
    assert any("__ghost-verify-served.sh" in p for p in problems), (
        f"新增一条不带判据的腿竟没判红（= 未登记即红失效）：{problems}"
    )


def test_red_proof_exempting_a_leg_that_already_has_the_criterion_is_reported():
    """判据 2 的红证：给**已带判据**的 worker 腿再挂一条豁免 ⇒ 红（豁免册只许缩短）。"""
    data = ledger()
    exemptions = dict(data["exemptions"])
    exemptions[WORKER_LEG] = {"reason": "r", "issue": "#x", "owner": "o", "restart_condition": "c"}
    problems = leg_set_problems(leg_files(), data["criteria_markers"], exemptions)
    assert any("已在台账里豁免" in p for p in problems), f"给已落判据的腿挂豁免竟没判红：{problems}"


def test_red_proof_empty_leg_set_is_reported():
    """判据 1 的 fail-closed：一条腿都取不到 ⇒ 判红（绝不静默通过）。"""
    data = ledger()
    problems = leg_set_problems([], data["criteria_markers"], data["exemptions"])
    assert any("静默空跑" in p for p in problems), f"空腿集竟没判红：{problems}"


def test_red_proof_stale_exemption_is_reported():
    """判据 2 的红证：台账里留着**不存在的腿**的豁免 ⇒ 红（陈旧即红，台账只许缩短）。"""
    data = ledger()
    exemptions = dict(data["exemptions"])
    exemptions["__gone-verify-served.sh"] = {
        "reason": "r", "issue": "#x", "owner": "o", "restart_condition": "c",
    }
    problems = leg_set_problems(leg_files(), data["criteria_markers"], exemptions)
    assert any("陈旧条目" in p for p in problems), f"陈旧豁免竟没判红：{problems}"


# ── 判据 5：实例判据真跑（活体，零网络）──────────────────────────────────────
#
# 「判据绿 ≠ 接线在」（migao-dev-flow §28.2）：上面的结构层只证明**锚点在位**。
# 本节真跑 `worker-h5-verify-served.sh` 对着**本地静态服务**：
#   ① 完整发布树（= 远端发布集的形状）⇒ 必须**绿**；
#   ② `.mjs` 被发成 `text/html`（线上实测形态，#6306 的病）⇒ 必须**红**且指名 URL。
# 夹具把 ② 的 ① 面弄坏（少铺文件）会造**假红**（#6293 已实证过同一个坑）⇒ `src/**` **整棵递归**铺。


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 静音访问日志
        return None

    def guess_type(self, path):  # noqa: A003 - stdlib 的钩子名就是这样
        if str(path).lower().endswith(".mjs"):
            return "text/javascript"
        return super().guess_type(path)


class _HtmlMjsHandler(_QuietHandler):
    """坏形态夹具：`.mjs` 以 **`text/html`** 发出（= issue #6306 的线上实测形态）。

    身份 / 字节**完全正确**（HTTP 200 + 逐字节一致），只有响应头错 ⇒ 浏览器拒绝执行 module script。
    """

    def guess_type(self, path):  # noqa: A003
        if str(path).lower().endswith(".mjs"):
            return "text/html"
        return super().guess_type(path)


def _copy_worker_tree(dest: Path) -> None:
    """铺一份「已正确发布」的 `w/` 子树 = 远端发布集：index.html + machine.html + `src/**`（递归）。"""
    (dest / "w").mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "machine.html"):
        (dest / "w" / name).write_bytes((WORKER_SRC / name).read_bytes())
    subprocess.run(
        ["cp", "-R", str(WORKER_SRC / "src"), str(dest / "w" / "src")],
        check=True, capture_output=True,
    )


def _serve(directory: Path, handler_cls: type = _QuietHandler):
    handler = lambda *a, **kw: handler_cls(*a, directory=str(directory), **kw)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for _ in range(100):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", server.server_address[1])) == 0:
                return server


def _run_verify(base_url: str):
    return subprocess.run(
        ["bash", str(SCRIPTS_DIR / WORKER_LEG), base_url],
        capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT),
    )


def test_verify_served_is_green_on_the_real_publish_set(tmp_path):
    """① 完整发布树 ⇒ 闭包判据必须**绿**，且报出七条链上的模块（含树内共享模块）。"""
    served = tmp_path / "served"
    _copy_worker_tree(served)
    server = _serve(served)
    try:
        proc = _run_verify(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
    assert proc.returncode == 0, f"完整发布树上闭包判据竟判红：\n{proc.stdout}\n{proc.stderr}"
    assert "⑦ module 闭包加载判据" in proc.stdout
    assert "src/shared/operation-display.mjs" in proc.stdout, (
        "闭包判据没走到树内共享模块（#6306 的修复对象）—— 判据扫描面不对：\n" + proc.stdout
    )
    assert "✅ 落地面身份断言全过" in proc.stdout


def test_verify_served_is_red_when_the_module_is_served_as_html(tmp_path):
    """② 线上实测形态（`200 text/html` 的 module）⇒ 必须红，且**指名是哪个 URL**。"""
    served = tmp_path / "served"
    _copy_worker_tree(served)
    server = _serve(served, _HtmlMjsHandler)
    try:
        proc = _run_verify(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
    assert proc.returncode == 1, f"`.mjs` 被发成 text/html 时竟判绿（空断言）：\n{proc.stdout}"
    assert "∉ JS MIME 白名单" in proc.stdout, f"判红信息里没有 MIME 判据：\n{proc.stdout}"
    assert "src/app.mjs" in proc.stdout or "src/machine-app.mjs" in proc.stdout, (
        "判红信息里没有指名入口脚本 URL（红得不具体 = 排查时看不出坏在哪）：\n" + proc.stdout
    )
