# case_ids: PP-011
"""类级元守卫：**LPAPI `openPrinter` 必须带设备参数**（issue #6439 真机实测缺陷的类级固化）。

## 病灶（真机实测，2026-10-06）

macOS + Chrome 153 + 德佟 DP235S：`openPrinter()` **空参**会让 SDK 走它自己的
`searchPrinter()` 重扫（反混淆 `lpapi-ble@1.7.260618` 的 `libs/index.umd.js` 读出该分支），
而 **Web Bluetooth 没有用户手势就扫不了** ⇒ **恒回** `statusCode=2 ERROR_NO_PRINTER`
「未搜索到到打印机设备！」。

🔴 危险处在于它**看起来是好的**：两个前端（`frontend/bmini-app` 与 `frontend/admin-web`）
**各写了一遍**同样的空参调用，而两侧单测都用替身、替身不校验入参 ⇒
**判据全绿、真机必挂**（前者自 2026-09-29 起一直如此，后者是本单新增时同款复制的）。

⇒ 实例判据（两侧测试里各一条「入参断言」）只钉住**已经看过的那两处**；
   本守卫钉住**这一类**：内部源码里任何 `openPrinter(` 调用都**不许**是空参形态。

## 判据（都能判红）

| # | 判什么 | 会怎么红 |
|---|---|---|
| 1 | 每个 `openPrinter(` 调用都带**非空实参** | 改回 `openPrinter()` ⇒ 具名报出 `文件::行号` 与该处实参 |
| 2 | **反空跑锚点**：两处已知调用点必须被扫到（扫描面失效 ⇒ 红） | 改目录 / 改后缀 / 删除调用 ⇒ 红 |
| 3 | **判别力自证**：把空参形态注入到真语料里 ⇒ 判红；未注入 ⇒ 不报 | 守卫退化成恒绿 ⇒ 红 |

## 边界（照实登记，不粉饰）

- 只扫 `frontend/*/src/**` 的 `.ts` / `.tsx`（**生产源码**；测试替身里的 `openPrinter()` 定义不在此列）。
- 🔴 **先剥注释再扫**（本守卫第一版就栽在这里）：文件头/行尾的**说明文字**里合法地写着
  `` `openPrinter()` **空参必失败** `` 这类话（那正是本单要讲清的事）⇒ 不剥注释就会把**提及**
  当成**调用**判红。同族教训见 `migao-dev-flow` §2.2「**引用即实例**：内容扫描式机制分不清
  「引用」与「使用」」。剥离**保留行号**（块注释按换行数换行、行注释原位删）。
- 不做语义分析：只做**括号配平**后判实参是否为空串 ⇒ 多行实参、嵌套调用都能正确取到。
- 判不了「实参**内容**对不对」（`autoScan:false` 是否真在里面）—— 那一半由两侧的实例判据承担
  （`frontend/bmini-app/tests/inbound-print-channel.test.ts` 与
  `frontend/admin-web/tests/unit/lib/label-print-lpapi.test.ts` 的入参 `toEqual`）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 必须被扫到的**已知调用点**（反空跑锚点：少一个就说明扫描面失效了）
EXPECTED_SITES = (
    "frontend/bmini-app/src/utils/inbound/lpapiTransport.ts",
    "frontend/admin-web/src/lib/label-print/lpapi.ts",
)

_OPEN_PRINTER = re.compile(r"openPrinter\s*\(")

#: 注释剥离（**保留行号**）：块注释按原换行数换成换行、行注释原位删除。
#: 不剥注释 ⇒ 文件头里那句「`openPrinter()` 空参必失败」会被当成调用判红（第一版实测）。
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")


def strip_comments(text: str) -> str:
    """剥掉 `/* … */` 与 `// …`，**保持行号不变**（判红要能指名到行）。

    局限（照实登记）：行注释剥离不看字符串上下文 ⇒ 行内字符串里的 `https://…` 会被截断，
    该行 `//` 之后的内容随之消失。对本守卫的射程（找 `openPrinter(` 调用）影响可忽略。
    """
    text = _BLOCK_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return _LINE_COMMENT.sub("", text)


def _args_at(text: str, open_paren: int) -> str:
    """取 `openParen` 位置那对括号里的实参原文（按括号配平，支持多行/嵌套）。"""
    depth = 0
    for index in range(open_paren, len(text)):
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : index]
    return text[open_paren + 1 :]


def find_calls(text: str) -> list[tuple[int, str]]:
    """`(行号, 实参原文)` 列表 —— 纯函数 ⇒ 便于注入式判别力自证。"""
    found: list[tuple[int, str]] = []
    for match in _OPEN_PRINTER.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        found.append((line, _args_at(text, match.end() - 1)))
    return found


def scan(root: Path = REPO_ROOT) -> list[tuple[str, int, str]]:
    """扫生产源码里的全部 `openPrinter(` 位置（仓库相对路径、行号、实参）。"""
    sites: list[tuple[str, int, str]] = []
    for pattern in ("frontend/*/src/**/*.ts", "frontend/*/src/**/*.tsx"):
        for path in sorted(root.glob(pattern)):
            if "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for line, args in find_calls(strip_comments(text)):
                sites.append((str(path.relative_to(root)), line, args))
    return sites


def empty_arg_violations(sites: list[tuple[str, int, str]]) -> list[str]:
    """空参调用 = 违规（纯函数 ⇒ 可与注入形态一起在内存里自证）。"""
    return [
        f"{path}:{line} —— `openPrinter()` 空参调用（实参 = {args!r}）"
        for path, line, args in sites
        if args.strip() == ""
    ]


def test_no_empty_open_printer_call() -> None:
    """判据 1：生产源码里不许出现空参 `openPrinter()`。"""
    violations = empty_arg_violations(scan())
    assert violations == [], (
        "🔴 空参 `openPrinter()` ⇒ SDK 走自己的 searchPrinter() 重扫，而 Web Bluetooth 没有用户手势"
        "扫不了 ⇒ 真机恒回 ERROR_NO_PRINTER（issue #6439 实测）。必须显式喂设备：\n"
        "    openPrinter({ name, deviceId, checkDeviceName: false, autoScan: false })\n"
        "违规处：\n  - " + "\n  - ".join(violations)
    )


def test_scan_face_is_alive() -> None:
    """判据 2（反空跑锚点）：两处已知调用点必须被扫到，否则「没扫到」会伪装成「没问题」。"""
    scanned = {path for path, _line, _args in scan()}
    missing = [path for path in EXPECTED_SITES if path not in scanned]
    assert missing == [], (
        "🔴 扫描面失效：这些**已知有 openPrinter 调用**的文件没被扫到 —— "
        "此时判据 1 的绿是**假绿**（空集比空集是恒等）。缺：\n  - " + "\n  - ".join(missing)
    )


def test_guard_has_teeth() -> None:
    """判据 3（判别力自证）：把空参形态注入**真语料** ⇒ 必红；未注入 ⇒ 不报。"""
    # 反向对照 0：真实语料（未注入）⇒ 无违规
    assert empty_arg_violations(scan()) == []

    # 注入 A（端到端，走 `find_calls` 真路径）：把锚点文件里那处**真调用**的实参掏空
    rel = EXPECTED_SITES[1]
    source = strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8"))
    open_paren = source.find("openPrinter(") + len("openPrinter")
    assert "openPrinter(" in source, "注入前提不成立：锚点文件里没有 openPrinter 调用"
    args = _args_at(source, open_paren)
    assert args.strip() != "", "注入前提不成立：锚点那一处本来就是空参（守卫本该早就判红）"
    hollowed = source[: open_paren + 1] + source[open_paren + 1 + len(args) :]
    assert hollowed != source, "注入未生效（文本没变）"
    assert any(a.strip() == "" for _line, a in find_calls(hollowed)), "注入空参后端到端未判红"

    # 反向对照 3：🔴 **注释里的「提及」不得判红** —— 守卫第一版正是被文件头那句
    # 「`openPrinter()` 空参必失败」喂红的（引用 ≠ 使用，见「边界」）。
    mention = "// 说明：openPrinter() 空参必失败\n/** openPrinter() */\nconst x = 1\n"
    assert find_calls(strip_comments(mention)) == [], "注释里的提及被判成调用 ⇒ 守卫会把自己的文档喂红"
    assert strip_comments(mention).count("\n") == mention.count("\n"), "剥注释改变了行号（判红就指不准了）"

    # 注入 B（最小形态）：判据函数本身对空参必须报违规
    assert empty_arg_violations([(rel, 1, "")]) != [], "空参形态未被判红 ⇒ 守卫没有牙"

    # 反向对照 1：非空实参（多行 / 嵌套）**不得**被判红
    assert empty_arg_violations([("x.ts", 1, "\n  { name, deviceId },\n")]) == []

    # 反向对照 2：括号配平 —— 嵌套括号的实参要完整取出（否则 `({ a: () => 1 })` 会被误判成空）
    _line, nested_args = find_calls("api.openPrinter({ name, fn: () => 1 })")[0]
    assert nested_args.strip() == "{ name, fn: () => 1 }"
