# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI/结构守卫由 pytest 单测验证」是 misc.yml 里已登记的形态）
"""基础规则层 Prompt 文件「必须在磁盘上存在」的 L0 静态守卫（issue #4057 S5）。

## 病根（实测）

`app/graph/skills/base_skill.py` 的 `_read_cached` 对缺失/读失败**静默返回 `""`**
（两处 `_PROMPT_CACHE[path] = ""`）。三个**基础规则层**文件走的是同一条路径：

    references/base/identity.md     ← Layer 1 公共身份（所有 Skill 共享）
    references/base/principles.md   ← Layer 2 公共准则
    references/PROMPT-rules.md      ← Layer 2.5 共享写规则（确认卡铁律等）

⇒ 只要其中一个文件缺失/不可读（改名、打包漏拷、误删），**整层公共规则静默消失**：
System Prompt 少一整层、模型行为漂移，而**没有任何东西变红**（单测不会读文件缺失的目录，
快照测试读的是真目录 ⇒ 也发现不了"将来某次提交把它删了"）。

## 本文件锁的三条不变式

1. `base_skill._REQUIRED_PROMPT_FILES` 列出的每个相对路径**必须真实存在于磁盘**
   （删文件 ⇒ 本 L0 用例红 ⇒ CI 红）。
2. 清单**必须恰好是那三个基础规则文件** —— 否则「删文件 + 同时把名字从清单里删掉」
   会让判据自己变成空跑（§19.1「判据自己选择沉默」）。
3. 这三个文件必须真的走「必需」通道：`_build_system_prompt` 里对它们的 `_read_cached(...)`
   调用必须带 `required=True`（数量与清单一致）—— 否则清单只是装饰，缺失仍静默。

## 每条的**反例输入**（红证，命令见 PR body）

| 用例 | 改这一处即红 |
|---|---|
| `test_required_prompt_files_exist_on_disk` | `rm app/graph/skills/references/base/identity.md` |
| `test_required_file_list_is_exactly_the_three_base_layers` | 从上表删掉 `PROMPT-rules.md`（只删文件不改清单也会红） |
| `test_required_files_are_read_with_the_required_flag` | 把某个调用点的 `required=True` 删掉 |
| `TestGuardIsNotVacuous` | 注入式夹具：不存在的路径必须被报出；真给文件时必须不报 |

## 为什么是**纯静态 AST**（不 import 后端 app 包）

本文件跑在 CI 的 `ci workflow helper unit tests` job 里，该 job 只 `pip install pytest pyyaml`
（见 `.github/workflows/pr-check.yml`）—— **没有** pydantic/langchain 等后端依赖。
故真值由 AST 从 `base_skill.py` 反解；运行时行为（缺失即抛错）由
`backend/ai-agent-service/tests/test_prompt_snapshots.py` 的行为用例覆盖。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "backend" / "ai-agent-service"
BASE_SKILL_PY = SERVICE_ROOT / "app" / "graph" / "skills" / "base_skill.py"
REF_DIR = SERVICE_ROOT / "app" / "graph" / "skills" / "references"

REQUIRED_LIST_NAME = "_REQUIRED_PROMPT_FILES"
READ_CACHED_NAME = "_read_cached"
BUILD_PROMPT_NAME = "_build_system_prompt"

#: 三个基础规则层（issue #4057 S5 逐条点名）—— 清单必须**恰好**是这三个。
EXPECTED_REQUIRED = {
    "base/identity.md",
    "base/principles.md",
    "PROMPT-rules.md",
}


def _module_ast(path: Path) -> ast.Module:
    """读源码 AST；文件缺失即**报错**（fail-closed，不给"扫不到就通过"留口子）。"""
    assert path.is_file(), f"L0 守卫的被扫目标不存在：{path}（fail-closed，不静默跳过）"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_func(tree: ast.Module, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{BASE_SKILL_PY} 里找不到函数 `{name}` —— 守卫的真相源消失了（fail-closed）")


def required_prompt_files(tree: ast.Module) -> list[str]:
    """`base_skill._REQUIRED_PROMPT_FILES` 的字符串元素（保序）。

    fail-closed：常量不存在 / 不是字面量元组 / 解析出 0 条 ⇒ 报错，不静默返回空表
    （空表会让「文件都存在」退化成恒真空判据）。
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == REQUIRED_LIST_NAME for t in node.targets):
            continue
        value = node.value
        if not isinstance(value, (ast.Tuple, ast.List)):
            raise AssertionError(
                f"`{REQUIRED_LIST_NAME}` 不再是字面量元组/列表（{ast.dump(value)[:60]}）"
                f"—— 守卫无法反解，宁可红"
            )
        out = [
            el.value for el in value.elts
            if isinstance(el, ast.Constant) and isinstance(el.value, str)
        ]
        assert out, f"`{REQUIRED_LIST_NAME}` 解析出 0 个字符串路径 —— 守卫会空转（fail-closed）"
        return out
    raise AssertionError(
        f"`{BASE_SKILL_PY}` 里找不到 `{REQUIRED_LIST_NAME}` —— 基础规则层的必需清单消失了"
        f"（fail-closed：缺失即静默，「清单没了」必须比「文件没了」更早红）"
    )


def missing_required_files(ref_dir: Path, rel_paths) -> list[str]:
    """`rel_paths` 里在 `ref_dir` 下**不存在**的那些（纯函数，供注入式红证驱动）。"""
    return [p for p in rel_paths if not (ref_dir / p).is_file()]


def required_flag_call_count(tree: ast.Module, func_name: str = BUILD_PROMPT_NAME) -> int:
    """`_build_system_prompt` 里 `_read_cached(..., required=True)` 的调用数（纯静态）。"""
    func = _find_func(tree, func_name)
    count = 0
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == READ_CACHED_NAME):
            continue
        if any(kw.arg == "required" and isinstance(kw.value, ast.Constant) and kw.value.value is True
               for kw in node.keywords):
            count += 1
    return count


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ①：清单里的文件必须在磁盘上
# ──────────────────────────────────────────────────────────────────────────────


def test_required_prompt_files_exist_on_disk():
    """**核心不变式**：基础规则层的三个文件必须真实存在（删文件 ⇒ CI 红）。

    反例输入：`rm app/graph/skills/references/base/identity.md` ⇒ 必红。
    """
    rel_paths = required_prompt_files(_module_ast(BASE_SKILL_PY))
    missing = missing_required_files(REF_DIR, rel_paths)
    assert missing == [], (
        f"基础规则层 Prompt 文件缺失：{missing}\n"
        f"  清单（{REQUIRED_LIST_NAME}）= {rel_paths}\n"
        f"  查找目录 = {REF_DIR}\n"
        f"→ 这些文件是**每个 Skill 都注入**的公共层；缺失即整层规则静默消失"
        f"（`_read_cached` 改前返回 \"\" 而无人变红）。补回文件，不要从清单里删名字。"
    )


def test_required_file_list_is_exactly_the_three_base_layers():
    """清单必须**恰好**是那三个基础规则文件（防「删文件 + 删名字」让判据空跑）。"""
    rel_paths = required_prompt_files(_module_ast(BASE_SKILL_PY))
    assert set(rel_paths) == EXPECTED_REQUIRED, (
        f"必需清单与三个基础规则层不一致：\n"
        f"  实测 = {sorted(rel_paths)}\n"
        f"  期望 = {sorted(EXPECTED_REQUIRED)}\n"
        f"→ 少了某个文件 ⇒ 它缺失时不再有人拦（判据自己选择沉默）；"
        f"多了别的文件 ⇒ 请同步本守卫的 EXPECTED_REQUIRED 并说明理由。"
    )


def test_required_files_are_read_with_the_required_flag():
    """清单必须**真的接进**读取通道：`_build_system_prompt` 的 required=True 调用数 == 清单长度。"""
    tree = _module_ast(BASE_SKILL_PY)
    rel_paths = required_prompt_files(tree)
    count = required_flag_call_count(tree)
    assert count == len(rel_paths), (
        f"`{BUILD_PROMPT_NAME}` 里 `{READ_CACHED_NAME}(..., required=True)` 的调用数是 {count}"
        f"（清单有 {len(rel_paths)} 个必需文件）\n"
        f"→ 清单没接进读取通道 = 装饰：文件缺失时依然静默返回 \"\"（issue #4057 S5 的病根）"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ②：判据自身可红 + 不恒真（注入式夹具）
# ──────────────────────────────────────────────────────────────────────────────


class TestGuardIsNotVacuous:
    """**:red_circle: 红证**（注入式）+ **负例**：判据必须能报出，也必须能不报。"""

    def test_detector_reports_a_planted_missing_file(self, tmp_path):
        """缺文件 ⇒ **必须报出**（否则判据是空的）。"""
        (tmp_path / "base").mkdir()
        (tmp_path / "base" / "principles.md").write_text("x", encoding="utf-8")
        assert missing_required_files(
            tmp_path, ["base/identity.md", "base/principles.md", "PROMPT-rules.md"]
        ) == ["base/identity.md", "PROMPT-rules.md"]

    def test_detector_stays_quiet_when_all_files_are_present(self, tmp_path):
        """负例：文件齐全 ⇒ **必须不报**（防恒红）。"""
        (tmp_path / "base").mkdir()
        for rel in ("base/identity.md", "base/principles.md", "PROMPT-rules.md"):
            (tmp_path / rel).write_text("x", encoding="utf-8")
        assert missing_required_files(
            tmp_path, ["base/identity.md", "base/principles.md", "PROMPT-rules.md"]
        ) == []

    def test_required_flag_counter_reads_a_planted_source(self, tmp_path):
        """计数判据不是恒真：植入「漏 required=True」的源码 ⇒ 计数必须变。"""
        planted = tmp_path / "planted.py"
        planted.write_text(
            "def _build_system_prompt(skill):\n"
            "    a = _read_cached(_os.path.join(_ref_dir, 'base/identity.md'), required=True)\n"
            "    b = _read_cached(_os.path.join(_ref_dir, 'base/principles.md'))\n"
            "    return a, b\n",
            encoding="utf-8")
        assert required_flag_call_count(_module_ast(planted)) == 1, (
            "漏掉 required=True 的调用点没有被计数判据看见 —— 判据失效"
        )