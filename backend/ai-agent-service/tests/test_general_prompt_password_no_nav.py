# case_ids: ST-003
"""general 域：「改密码」类问题不得先调 nav_guide（issue #8300 ST-003 两次实测）。

## 现场（不是猜）

run `41281948631`（全档）+ `41283850191`（合了 settings.md 版本后定点复跑）**两次同指纹**：

```
R1 you=改密码，旧密码xxx 新密码newpass123
   tools=nav_guide(action=navigate, question="改密码在哪里改")
   → nav_not_registered（登记项：无）
```

第一版修错了域：ST-003 的 `skill = Skill.GENERAL`（见 `eval_cases/settings.py`），
而 settings 域的 prompt 根本不进这条链路 —— 真正的驱动在 `general_agent.py` 的「导航类指引」，
它写明「XX 功能在哪一页就调 nav_guide」。**账号安全类**必须在通用提示里有显式例外。

## 判据

`general_agent.py` 的导航章节必须含「账号安全类例外」：点名改密码/重置密码/忘记密码、
写明**不要调 nav_guide**、并保留「不得索取或复述密码明文」。
红证：摘掉这段 ⇒ 本判据红（已实跑）。
"""
from pathlib import Path

GENERAL = (Path(__file__).resolve().parents[1] / "app" / "graph" / "skills" / "general_agent.py")


def _nav_section() -> str:
    """导航章节到下一个二级标题为止（不写死长度 —— 会随内容增长漂）。"""
    text = GENERAL.read_text(encoding="utf-8")
    start = text.index("🧭 导航类指引")   # 带标题记号：裸词在代码注释里也出现
    rest = text[start:]
    end = rest.find("\n## ", 1)
    return rest if end < 0 else rest[:end]


def test_general_prompt_excludes_password_questions_from_nav_guide():
    section = _nav_section()
    assert "账号安全类例外" in section, "导航章节缺「账号安全类例外」—— ST-003 会回到「先调 nav_guide」"
    for marker in ("改密码", "重置密码", "nav_guide"):
        assert marker in section, f"例外里没点名 {marker}"


def test_password_exception_keeps_the_security_clause():
    section = _nav_section()
    assert "不得" in section and "密码明文" in section, "例外里丢了安全口径（禁止索取/复述密码）"
