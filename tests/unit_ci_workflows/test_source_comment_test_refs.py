# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 结构类 L0 不变式统一挂 MC-012，
#   与 `test_case_prose_test_names.py` 同族 —— 那条守**用例库散文**，本条守**源码注释**。）
"""源码注释里点名的**测试类**必须真实存在（issue #6637）—— L0，离线、秒级。

## 病灶

`.java` 的 javadoc / `.sql` 迁移注释里写着「这里由 `XxxTest` 挡着」，而 `XxxTest` **并不存在**。
读注释的人（和下一个 AI）会据此认为「有守卫在挡」⇒ **把真实缺口读成已覆盖** —— 比不写注释更危险。

现取读数（2026-11-02，`origin/main`）：注释里引用而**仓库里没有同名类**的测试类名 **9 个**
（`OrderShippedAtWriteGuardTest` 已在本单修好；`@WebMvcTest` 是注解假阳性，不判）。

## 判据（全部按**现取**，不抄手写清单）

| # | 判什么 | 语料 |
|---|---|---|
| 1 | 注释里点名的 `[A-Z][A-Za-z0-9]*Test` 必须能解析到**真实存在**的测试类/文件 | `backend/**/*.java`、`backend/**/*.sql` 的**注释行** |
| 2 | `@` 前缀的注解（`@WebMvcTest` / `@DataJpaTest` …）**不是**类引用 ⇒ 不判 | 同上 |
| 3 | 射程 = 主源面：跳过 `src/test/**`（测试本体）与 `migration/V*/`、`migration-archive/`（**已发布迁移不可变**，#6539） | 同上 |
| 4 | 豁免台账 `.github/comment-test-refs-exempt.json`：**只许缩短** + 条目必须**活着**（销账即删）+ 条数 ≤ 冻结上限 | 台账 |

红证（每条都实跑）：新幽灵不在台账 ⇒ 红；台账条目已不存在 ⇒ 红；台账条数超冻结上限 ⇒ 红；
`@WebMvcTest` **不**误报；真实存在的类名引用 **不**误报。
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO_ROOT / ".github" / "comment-test-refs-exempt.json"

REF_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*Test)\b")
#: 主源面（扫描盘）与**不许**就地改的已发布迁移（#6539）
SCAN_ROOTS = ("backend",)
SKIP_PARTS = ("/src/test/", "/migration/V", "/migration-archive/")
#: 测试类/文件名的解析面（现取：这些目录里出现过的 stem 就算「存在」）
NAME_ROOTS = ("backend", "frontend", "tests", ".github")


def _is_comment_line(line: str) -> bool:
    s = line.strip()
    return s.startswith(("//", "*", "/*", "--")) or "//" in line or "* " in line


def existing_test_names(root: Path) -> set:
    """**存在面**：测试文件 stem ∪ 全仓 `class <Name>` 声明（现取，不写死清单）。"""
    names: set = set()
    for base in NAME_ROOTS:
        d = root / base
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            rel = "/" + str(p.relative_to(root))
            if p.suffix == ".java" and "/src/test/" in rel:
                names.add(p.stem)
                try:
                    for m in re.finditer(r"\bclass\s+([A-Z][A-Za-z0-9]*)", p.read_text(encoding="utf-8", errors="ignore")):
                        names.add(m.group(1))
                except OSError:
                    continue
            elif p.name.startswith("test_") and p.suffix == ".py":
                names.add(p.stem)
            elif ".test." in p.name or ".spec." in p.name:
                names.add(p.stem.split(".")[0])
    return names


def ghost_refs(root: Path) -> dict:
    """注释里引用但**不存在**的测试类名 ⇒ `{名字: ["相对路径:行号", …]}`。"""
    have = existing_test_names(root)
    ghosts: dict = {}
    for base in SCAN_ROOTS:
        d = root / base
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.suffix not in (".java", ".sql"):
                continue
            rel = "/" + str(p.relative_to(root))
            if any(part in rel for part in SKIP_PARTS):
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if not _is_comment_line(line):
                    continue
                for m in REF_RE.finditer(line):
                    name = m.group(1)
                    if name in have:
                        continue
                    if m.start() and line[m.start() - 1] == "@":   # `@WebMvcTest` 是注解
                        continue
                    ghosts.setdefault(name, []).append(f"{p.relative_to(root)}:{i}")
    return ghosts


def ledger_problems(ghosts: dict, ledger: dict) -> list:
    """台账三律：**只许缩短**（条数 ≤ 冻结上限）、条目**活着**（仍被引用）、**不许**漏登记。"""
    bad: list = []
    entries = ledger.get("entries") or []
    exempt = {e.get("name") for e in entries}
    frozen_max = ledger.get("frozen_max")
    if not isinstance(frozen_max, int):
        bad.append("台账缺 `frozen_max`（只许缩短要有可比的冻结上限）")
    elif len(entries) > frozen_max:
        bad.append(f"豁免条数 {len(entries)} > 冻结上限 {frozen_max} ⇒ **只许缩短**（新幽灵必须改名，不许登记）")
    for e in entries:
        name = e.get("name")
        if not name:
            bad.append(f"台账条目缺 `name`：{e}")
        elif not e.get("reopen_when"):
            bad.append(f"台账条目 {name} 缺 `reopen_when`（什么时候必须回来清账）")
        if name and name not in ghosts:
            bad.append(f"台账条目 {name} 已**不再被引用** ⇒ 销账即删（台账只许缩短）")
    for name, places in sorted(ghosts.items()):
        if name not in exempt:
            bad.append(f"新幽灵类名 `{name}`（{places[0]} 等 {len(places)} 处）—— 引用一个不存在的测试类，"
                       f"要么改成真名，要么（临时）登记进台账并写 reopen_when")
    return bad


def _load_ledger(path: Path = LEDGER_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_tree(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _min_ledger(names, frozen_max=None) -> dict:
    entries = [{"name": n, "files": [], "reason": "r", "reopen_when": "w"} for n in names]
    return {"frozen_max": frozen_max if frozen_max is not None else len(entries), "entries": entries}


class TestSourceCommentTestRefs:
    def test_repo_has_no_unregistered_ghost_test_refs(self):
        ghosts = ghost_refs(REPO_ROOT)
        problems = ledger_problems(ghosts, _load_ledger())
        assert problems == [], "\n".join(problems)

    def test_at_annotation_is_not_a_class_reference(self, tmp_path):
        _write_tree(tmp_path, "backend/api/src/main/java/A.java",
                    "/** 用 @WebMvcTest 起切片 */\nclass A {}\n")
        assert ghost_refs(tmp_path) == {}

    def test_real_test_class_reference_is_not_flagged(self, tmp_path):
        _write_tree(tmp_path, "backend/api/src/test/java/RealGuardTest.java",
                    "class RealGuardTest {}\n")
        _write_tree(tmp_path, "backend/api/src/main/java/B.java",
                    "/** 由 RealGuardTest 挡着 */\nclass B {}\n")
        assert ghost_refs(tmp_path) == {}

    def test_red_proof_new_ghost_is_detected(self, tmp_path):
        _write_tree(tmp_path, "backend/api/src/main/java/C.java",
                    "/** 由 FooBarBazTest 挡着 */\nclass C {}\n")
        ghosts = ghost_refs(tmp_path)
        assert "FooBarBazTest" in ghosts, ghosts
        problems = ledger_problems(ghosts, _min_ledger([]))
        assert problems and any("新幽灵" in p for p in problems), problems

    def test_red_proof_stale_exemption_is_detected(self, tmp_path):
        _write_tree(tmp_path, "backend/api/src/main/java/D.java", "class D {}\n")
        problems = ledger_problems(ghost_refs(tmp_path), _min_ledger(["GoneTest"]))
        assert problems and any("不再被引用" in p for p in problems), problems

    def test_red_proof_ledger_cannot_grow(self, tmp_path):
        _write_tree(tmp_path, "backend/api/src/main/java/E.java",
                    "/** 由 GhostOneTest 挡着；GhostTwoTest 也挡 */\nclass E {}\n")
        ghosts = ghost_refs(tmp_path)
        problems = ledger_problems(ghosts, _min_ledger(["GhostOneTest", "GhostTwoTest"], frozen_max=1))
        assert problems and any("只许缩短" in p for p in problems), problems
