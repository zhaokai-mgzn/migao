#!/usr/bin/env python3
"""java_pointed_readings.py — Java「定点判据」的**可信读数**（issue #6495）

## 病（2026-11-03 本机实跑，逐条读数见 https://github.com/zhaokai-mgzn/migao/wiki/Development 的「Java 定点判据」节）

① **`.txt` 摘要不可信**：同一次运行 console/XML 报 **15** 条，而
   `target/surefire-reports/<fqn>.txt` 写 **`Tests run: 0`**（@Nested 类的通例）。
   issue #6495 的原始读数（`head -6 …txt`）正是读到这个摘要 ⇒ 得出「一条都没跑」的**误诊**。
② **真·空跑绿**：`-Dtest=<外层类>#<方法>`，而该方法**声明在 `@Nested` 内** ⇒
   `Tests run: 0 / BUILD SUCCESS / exit=0`，且**不产出 XML**。正解 = `<外层类>$<嵌套类>#<方法>`。
③ 反向**不成立**：「类里含 @Nested ⇒ `-Dtest=<类名>` 一条都不跑」是错的 ——
   实测 `OssConfigTest`（3 外层 + 12 嵌套）= **15/15**、`AgentBatchServiceTest`（38 条全在 @Nested）= **38/38**，
   加通配符 `*` **没有**额外收益。⇒ 别把通配符当「解锁 @Nested 的开关」传播。

## 本入口做什么

  `./scripts/java-test.sh <selector> [...]`

  · 选择器规范化：`#<方法>` 命中 @Nested 内方法 ⇒ 自动改写成 `$<嵌套类>#<方法>`（②的唯一正解），并打印纠正；
  · 跑完**只信 XML**（`TEST-<fqn>.xml` 的 `<testcase>` 计数，不去读 `.txt` 摘要）；
  · 断言 `Tests run > 0`（**0 = 红**），声明了 @Nested 的类还要求**嵌套用例真的跑到**；
  · `.txt` 摘要不读、不当读数源（口径写在告警里，不再重演 #6495 的误诊）。

退出码：`0` 真跑且绿 / `1` 红（空跑 / 用例失败 / 嵌套没跑到）/ `2` 用法 / `3` 不可判定（类找不到 / 模块找不到 / 无 mvnw）
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_GLOB = "backend/*"
TXT_CAVEAT = (
    "⚠️ 读数只取自 XML（TEST-<fqn>.xml 的 <testcase> 计数）。"
    "surefire 的 .txt 摘要在 @Nested 类上恒报 Tests run: 0 —— 判空跑/通过都别用它（issue #6495 的误诊就来自那里）。"
)


# ────────────────────────── Java 源解析（去注释 / 字面量 + 括号配平）──────────────────────────

def mask_literals_and_comments(src: str) -> str:
    """把注释与字符串/字符/文本块字面量替换成空格（保留换行与偏移）—— 括号配平才不会被它们骗。"""
    out = list(src)
    i, n = 0, len(src)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if c == "/" and src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif c == "/" and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif src.startswith('"""', i):
            j = src.find('"""', i + 3)
            j = n if j < 0 else j + 3
            blank(i, j)
            i = j
        elif c in "\"'":
            quote, j = c, i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == quote:
                    j += 1
                    break
                if src[j] == "\n":
                    break
                j += 1
            blank(i, j)
            i = j
        else:
            i += 1
    return "".join(out)


@dataclass
class ClassBody:
    name: str
    header_start: int
    body_start: int  # `{` 的偏移
    body_end: int  # 配平的 `}` 的偏移
    nested: bool


def class_bodies(masked: str) -> list[ClassBody]:
    """枚举所有 `class X … { … }`（含内部类）；`nested` = 声明前**紧邻**（只在同一容器内）`@Nested`。"""
    bodies: list[ClassBody] = []
    for m in re.finditer(r"\bclass\s+(\w+)", masked):
        brace = masked.find("{", m.end())
        if brace < 0:
            continue
        depth, j, end = 0, brace, len(masked) - 1
        while j < len(masked):
            if masked[j] == "{":
                depth += 1
            elif masked[j] == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
            j += 1
        # 注解窗口的**下限**：容器类的 `{`（第一个内部类没有「前一个兄弟」）∪ 前一个已闭合兄弟的 `}`
        container = next((b for b in reversed(bodies) if b.body_start < m.start() < b.body_end), None)
        floor = container.body_start if container else 0
        floor = max(floor, max((b.body_end for b in bodies if b.body_end <= m.start()), default=floor))
        nested = re.search(r"@Nested\b", masked[floor:m.start()]) is not None
        bodies.append(ClassBody(m.group(1), m.start(), brace, end, nested))
    return bodies


def methods_in(masked: str, start: int, end: int) -> set[str]:
    return {m.group(1) for m in re.finditer(r"\bvoid\s+(\w+)\s*\(", masked[start:end])}


@dataclass
class TestClass:
    fqn: str
    simple: str
    path: Path
    module: Path
    has_nested: bool = False
    nested: dict[str, set[str]] = field(default_factory=dict)  # 嵌套类名 → 其内 void 方法
    outer_methods: set[str] = field(default_factory=set)

    def nested_owner_of(self, method: str) -> str | None:
        for name, methods in self.nested.items():
            if method in methods:
                return name
        return None


def parse_test_class(path: Path, root: Path = REPO_ROOT) -> TestClass:
    masked = mask_literals_and_comments(path.read_text(encoding="utf-8", errors="replace"))
    simple = path.stem
    bodies = class_bodies(masked)
    outer = next((b for b in bodies if b.name == simple and b.header_start >= 0), None)
    tc = TestClass(fqn="", simple=simple, path=path, module=module_of(path, root))
    if outer is None:  # 文件名与类名不一致（少见的内部类文件）⇒ 退化成「全文件扫」
        tc.outer_methods = methods_in(masked, 0, len(masked))
    else:
        inner = [b for b in bodies if outer.body_start < b.header_start < outer.body_end]
        nested = [b for b in inner if b.nested]
        tc.has_nested = bool(nested)
        tc.nested = {b.name: methods_in(masked, b.body_start, b.body_end) for b in nested}
        outer_only = list(masked[outer.body_start:outer.body_end])
        for b in sorted(nested, key=lambda x: x.body_start, reverse=True):
            for k in range(b.body_start - outer.body_start, b.body_end - outer.body_start + 1):
                if 0 <= k < len(outer_only):
                    outer_only[k] = " "
        tc.outer_methods = methods_in("".join(outer_only), 0, len("".join(outer_only)))
    return tc


def module_of(path: Path, root: Path = REPO_ROOT) -> Path:
    """测试文件所属模块目录（`backend/<mod>`）。"""
    for parent in path.parents:
        if parent.parent == root / "backend":
            return parent
    return path.parent


def find_src_root(path: Path) -> Path:
    for parent in path.parents:
        if parent.name == "java" and parent.parent.name in ("test", "main"):
            return parent
    return path.parent


def index_test_classes(root: Path = REPO_ROOT) -> dict[str, TestClass]:
    """现取全部 Java 测试类：simple name → TestClass（同名的取第一个并保留全部见 `index_all`）。"""
    return {tc.simple: tc for tc in index_all(root)}


def index_all(root: Path = REPO_ROOT) -> list[TestClass]:
    out: list[TestClass] = []
    for module in sorted(root.glob(MODULE_GLOB)):
        test_java = module / "src" / "test" / "java"
        if not test_java.is_dir():
            continue
        for path in sorted(test_java.rglob("*.java")):
            tc = parse_test_class(path, root)
            tc.fqn = ".".join(path.relative_to(find_src_root(path)).with_suffix("").parts)
            out.append(tc)
    return out


# ────────────────────────── 选择器规范化 ──────────────────────────

SELECTOR_SPLIT = re.compile(r",")
DEFAULT_SELECTOR_RE = re.compile(r"-Dtest=(\S+)")


def split_selectors(selector: str) -> list[str]:
    return [s.strip() for s in SELECTOR_SPLIT.split(selector) if s.strip()]


def normalize(selector: str, index: dict[str, TestClass]) -> tuple[str, list[str]]:
    """返回 (可用选择器, 纠正说明)。修的是 #6495 形态②：`Outer#method` 而 method 在 @Nested 内 ⇒ 静默空跑。"""
    fixed: list[str] = []
    notes: list[str] = []
    for part in split_selectors(selector):
        if "#" in part and "$" not in part:
            cls, method = part.split("#", 1)
            tc = index.get(cls.rsplit(".", 1)[-1])
            owner = tc.nested_owner_of(method) if tc else None
            if owner:
                good = f"{cls}${owner}#{method}"
                notes.append(
                    f"🔧 `-Dtest={part}` 会**静默空跑**（该方法声明在 @Nested `{owner}` 内，"
                    f"类名过滤器收集不到）⇒ 已改写成 `-Dtest={good}`（实测正解）"
                )
                fixed.append(good)
                continue
        fixed.append(part)
    return ",".join(fixed), notes


def bad_selectors_in_text(text: str, index: dict[str, TestClass]) -> list[tuple[str, str]]:
    """扫一段文本里的 `-Dtest=<外层类>#<@Nested 内方法>`（真·空跑形态）⇒ [(选择器, 正解)]。"""
    bad: list[tuple[str, str]] = []
    for m in DEFAULT_SELECTOR_RE.finditer(text):
        token = m.group(1).strip("\"'`,)")
        for part in split_selectors(token):
            if "#" not in part or "$" in part or "*" in part:
                continue
            cls, method = part.split("#", 1)
            tc = index.get(cls.rsplit(".", 1)[-1])
            owner = tc.nested_owner_of(method) if tc else None
            if owner:
                bad.append((part, f"{cls}${owner}#{method}"))
    return bad


# ────────────────────────── surefire XML 读数（唯一可信源）──────────────────────────

@dataclass
class Readings:
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    nested_tests: int = 0  # <testcase classname="…"> 不是外层 fqn 的那些（= 跑到 @Nested 里了）

    @property
    def outer_tests(self) -> int:
        return self.tests - self.nested_tests


def read_xml(report_dir: Path, fqn: str) -> Readings:
    """只读 XML。报告缺失 ⇒ 全零（= 空跑，由调用方判红）。"""
    r = Readings()
    for xml in sorted(report_dir.glob(f"TEST-{fqn}.xml")):
        try:
            tree = ET.parse(xml)
        except ET.ParseError:
            continue
        root = tree.getroot()
        r.tests += int(root.get("tests", 0))
        r.failures += int(root.get("failures", 0))
        r.errors += int(root.get("errors", 0))
        r.skipped += int(root.get("skipped", 0))
        for case in root.iter("testcase"):
            if case.get("classname") != fqn:
                r.nested_tests += 1
    return r


# ────────────────────────── 跑与判定 ──────────────────────────

def run_selector(selector: str, index: dict[str, TestClass], extra: list[str], mvn: str = "./mvnw",
                 repo_root: Path = REPO_ROOT) -> int:
    parts = split_selectors(selector)
    classes: list[TestClass] = []
    for p in parts:
        key = p.split("#")[0].split("$")[0].rsplit(".", 1)[-1]
        tc = index.get(key)
        if tc is None:
            print(f"❌ 不可判定：找不到测试类 `{key}`（现取 {len(index)} 个测试类）", file=sys.stderr)
            return 3
        classes.append(tc)
    if not classes:
        print("❌ 用法：java-test.sh <类名|类名#方法|外层$嵌套[#方法]>", file=sys.stderr)
        return 2
    module = classes[0].module
    reports = module / "target" / "surefire-reports"
    if not (module / "mvnw").exists():
        print(f"❌ 不可判定：{module.relative_to(repo_root)} 下没有 mvnw", file=sys.stderr)
        return 3

    offline = os.environ.get("MIGAO_MVN_OFFLINE", "1") == "1"  # 默认离线（本仓常用口径）；冷缓存用 MIGAO_MVN_OFFLINE=0
    # 报告卫生（与 issue #5216 同口径，别处已踩过）：跑 Maven **前先删**目标报告 ——
    # 否则「这次一条都没跑到」会读到**上一次**留下的 `Tests run: N` ⇒ 又一种假绿（本工具首版真踩了：
    # 先跑正确的 `$Create#…`（1 条）再 `--no-fix` 跑坏写法，读到陈旧的 1 条 ⇒ 判绿）。
    for tc in classes:
        for stale in reports.glob(f"TEST-{tc.fqn}.xml"):
            stale.unlink()
    cmd = [mvn] + (["-o"] if offline else []) + ["test", f"-Dtest={selector}", "-DfailIfNoTests=false"] + extra
    print(f"▶ cd {module.relative_to(repo_root)} && {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=module, capture_output=True, text=True)
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-25:])

    readings = {tc.fqn: read_xml(reports, tc.fqn) for tc in classes}
    total = Readings()
    rc = 0
    for tc in classes:
        r = readings[tc.fqn]
        total.tests += r.tests
        total.failures += r.failures
        total.errors += r.errors
        total.skipped += r.skipped
        total.nested_tests += r.nested_tests
        if r.tests == 0:
            print(
                f"❌ 空跑：`{tc.simple}` 一条都没跑到（surefire 没有产出任何 <testcase>）\n"
                f"   · 若选择器是 `#方法` 形态，该方法可能声明在 @Nested 内 ⇒ 用 `{tc.simple}$<嵌套类>#<方法>`\n"
                f"   · 若选择器是类名，请确认类名拼写 / 是否被 @Disabled"
            )
            rc = 1
        elif tc.has_nested and r.nested_tests == 0:
            print(
                f"❌ `{tc.simple}` 声明了 @Nested（{', '.join(tc.nested)}），但一条嵌套用例都没跑到"
                f"（读到 {r.tests} 条，全部来自外层类）⇒ 视为空跑，红"
            )
            rc = 1
        else:
            where = f"外层 {r.outer_tests} / @Nested {r.nested_tests}" if tc.has_nested else "扁平类"
            print(
                f"✅ {tc.simple}: Tests run {r.tests}（{where}）· Failures {r.failures} · "
                f"Errors {r.errors} · Skipped {r.skipped}"
            )
    if total.failures or total.errors:
        print(f"❌ 用例失败：Failures {total.failures} · Errors {total.errors}（读数来自 XML）")
        rc = 1
    if proc.returncode != 0 and rc == 0:
        print(f"❌ mvn 退出码 {proc.returncode}（用例读数未报红，但构建失败）")
        rc = 1
    if rc != 0:
        print("── mvn 尾部 ──\n" + tail)
    print(TXT_CAVEAT)
    return rc


def explain(selector: str, index: dict[str, TestClass]) -> int:
    rc = 0
    for part in split_selectors(selector):
        cls = part.split("#")[0].split("$")[0].rsplit(".", 1)[-1]
        tc = index.get(cls)
        if tc is None:
            print(f"❌ 找不到测试类 `{cls}`（现取 {len(index)} 个测试类）")
            rc = 3
            continue
        nested = ", ".join(sorted(tc.nested)) or "（无）"
        print(f"· {tc.fqn}\n    源码 {tc.path.relative_to(REPO_ROOT)}\n    @Nested: {nested}")
        fixed, notes = normalize(part, index)
        print(f"    选择器 {part} ⇒ {fixed}")
        for note in notes:
            print("    " + note)
    print(TXT_CAVEAT)
    return rc


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Java 定点判据的可信读数（issue #6495）")
    parser.add_argument("--check", action="store_true", help="只解析选择器（不跑）；纠正说明照常打印")
    parser.add_argument("--no-fix", action="store_true",
                        help="不纠正选择器：按你给的跑（复现 #6495 形态②时用；空跑即红）")
    parser.add_argument("--root", default=str(REPO_ROOT), help="仓库根（判据用：指向固定树）")
    parser.add_argument("selectors", nargs="*", help="类名 / 类名#方法 / 外层$嵌套[#方法]，逗号分隔")
    extra: list[str] = []
    if "--" in argv:  # `--` 之后的参数原样传给 mvn（argparse 会把 `--` 当选项终止符，故先切）
        cut = argv.index("--")
        extra, argv = argv[cut + 1:], argv[:cut]
    args, unknown = parser.parse_known_args(argv)
    extra = extra + unknown
    if not args.selectors:
        parser.print_usage()
        return 2
    index = index_test_classes(Path(args.root).resolve())
    if not index:
        print(f"❌ 不可判定：{args.root} 下没有 Java 测试类", file=sys.stderr)
        return 3
    selector = ",".join(args.selectors)
    if args.check:
        return explain(selector, index)
    if args.no_fix:
        return run_selector(selector, index, extra)
    fixed, notes = normalize(selector, index)
    for note in notes:
        print(note)
    return run_selector(fixed, index, extra)


if __name__ == "__main__":
    sys.exit(main())
