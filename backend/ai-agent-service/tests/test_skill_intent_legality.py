# case_ids: OR-016, OR-028, OR-029
"""skill 声明的意图必须 ∈ `IntentType`（F1）—— 常驻 L0 不变式。

> 本文件 = issue #4027（P9 守卫族扩建）的 F1 落点。**只读静态守卫**（外加一次纯本地的
> prompt 构建调用）：不改产品代码，只把「skill 声明了一个枚举外的意图」变成每次 CI 都红。

## 病灶形状（**静默失效**，P1 实测复现）

`SkillConfig.intents`（`app/graph/skills/skill_config.py`）被两处消费，**都不校验取值**：

1. **分类器提示**：`skill_registry.get_intents_for_skills(...)` → `nodes._get_agent_intents(agent_type)`
   → `intent_classifier._build_classifier_prompt(agent_intents)`。提示按
   `_INTENT_DESCRIPTIONS.get(intent, intent)` 生成 —— **表里没有该意图时整行退化成裸英文 token**：
   ```
   意图列表：
   - order_query: 查询订单状态、订单信息
   - processing_order_generate: processing_order_generate      ← 裸 token（模型读到的唯一信息就是它自己）
   ```
   实测（`origin/main` @ 67db87ae，命令见文末）：`ORDER_SKILL_CONFIG.intents` 有 **3** 个
   枚举外意图（`processing_order_generate` / `processing_order_query` / `processing_order_update`），
   即分类器提示里 3 行裸 token。
2. **意图→skill 路由表**：`skill_registry.get_skill_route_map(...)` 用 `intents` 建
   `{intent_value: route_key}`。枚举外的意图**永远不可能被产生**：分类器出口
   `IntentClassifier._parse_response` 用 `IntentType(intent_str)` 校验，非法取值**静默降级为
   `general`**（`confidence=0.5`）；规则匹配器 `rule_matcher` 全程只用 `IntentType` 成员。
   ⇒ 这 3 个意图在路由表里是**死键**，而 `order_skill.py` 的注释却声称
   「intents 保留 ⇒『加工单』问题仍路由到订单 skill」——**假真值**（§19.1）。

**为什么必须由不变式看住**：枚举外意图既不报错、也不影响今天的功能（模型照旧按 `general`
兜底），它只体现为**提示里的噪音 + 一份说不清的路由表**；下一个加 skill 的人会照着这份
「看起来合法」的清单继续写。A8（#4010）只修了**枚举内**缺口（`_INTENT_DESCRIPTIONS` 缺 3 个键），
枚举**外**的越界一直是敞着的。

## 本文件锁的三条不变式（每条都有反例输入）

| 用例 | 锁什么 | 反例输入（改这一处即红） |
|---|---|---|
| `test_declared_skill_intents_are_in_the_intent_enum` | **源码面**：所有 skill 模块里 `SkillConfig(..., intents=[...])` 的字面量取值 ⊆ `IntentType` 值集 | 在任一 skill 的 `intents` 里加一个枚举外的名字（如 `order_skill.py` 保留 `processing_order_generate`）⇒ 必红（**修 order_skill 前它当前就是红的**） |
| `test_registered_skill_intents_are_in_the_intent_enum` | **运行时面**：`get_skill_registry()` 里每个已注册 skill 的 `intents` ⊆ `IntentType` | 走 `register()` 程序化注册一个带枚举外意图的 skill ⇒ 必红（源码面扫不到这条路径） |
| `test_declared_intents_cannot_degrade_to_bare_tokens` | **观察面**：声明过的意图必须在 `_INTENT_DESCRIPTIONS` 里有描述（= 提示里不出现裸 token） | 删掉 `_INTENT_DESCRIPTIONS` 里某个**被 skill 声明**的键 ⇒ 必红（枚举内缺口；与 A8 的守卫互补：A8 锁「枚举 ⊆ 描述表」，本用例锁「skill 声明 ⊆ 描述表」） |

> 三者不是重复：源码面覆盖**未注册**的 skill 定义、运行时面覆盖**程序化**注册、
> 观察面锁**模型实际读到的那行文本**（前两者绿而第三者红是可能的：描述表被删键）。

## 适用域声明（对谁生效 / 对谁**不**生效）

| 维度 | 覆盖 | 不覆盖（不写恒真判断凑数） |
|---|---|---|
| 声明面 | `app/graph/skills/**` 里**字面量** `intents=[...]`（AST 读，不是正则扫文本） | 非字面量（`intents=computed()`）⇒ **打印登记**，由运行时面兜底（不猜） |
| 意图值 | `IntentType` 的 **value** 集（`str, Enum`） | 枚举**成员名**（`ORDER_QUERY`）：代码里用 value 做字符串（`_INTENT_DESCRIPTIONS`/`INTENT_DOMAINS`/路由表都是 value），判成员名会误红 |
| skill 范围 | registry 里**全部**已注册 skill（不再按 persona 过滤 —— 过滤会让 B 端 skill 静默逃逸，同 P3 #4012 的 B 端绑定缺口） | 动态构造的临时 `SkillRegistry`（`create_skill_registry(tool_names)` 的子集） |
| 意图语义 | 「取值合法」这一件事 | 「该 skill 该不该声明这个意图」是产品判断（如订单 skill 是否声明 `after_sales`）⇒ 不判 |

## 复现命令（红证取证用的那两条）

```bash
# ① 修前红：3 个枚举外意图（现在是绿 —— 已修；红证留档见 PR）
backend/ai-agent-service/.venv/bin/python -m pytest \
  backend/ai-agent-service/tests/test_skill_intent_legality.py -q

# ② 分类器提示的实际输出（裸 token → 有描述的前后对比）
backend/ai-agent-service/.venv/bin/python -c "
from app.graph.skills.order_skill import ORDER_SKILL_CONFIG
from app.router.intent_classifier import _build_classifier_prompt
p = _build_classifier_prompt(ORDER_SKILL_CONFIG.intents)
print(p[p.index('意图列表：'):p.index('请严格以 JSON')])"
```
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
SKILLS_DIR = APP_DIR / "graph" / "skills"


# ──────────────────────────────────────────────────────────────────────────────
# 源码面：AST 读字面量 `intents=[...]`（**不扫正则/不读散文**）
# ──────────────────────────────────────────────────────────────────────────────


def declared_intent_lists() -> list[tuple[str, int, list[str]]]:
    """`app/graph/skills/**` 里所有**字面量** `intents=[...]` ⇒ `[(文件, 行号, 取值), …]`。

    形态覆盖：`SkillConfig(..., intents=[...])` / `create_skill_config(..., intents=[...])`
    以及模块级 `intents = [...]` 赋值（共享清单）。
    非字面量取值（如工厂函数里的 `intents=intents or []`）**不进清单** —— 它由运行时面兜底，
    硬判会误红正确代码（§19.1「基于错误的真相模型写出的护栏 = 永远红」）。
    """
    found: list[tuple[str, int, list[str]]] = []
    for path in sorted(SKILLS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = str(path.relative_to(APP_DIR.parent))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "intents" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        found.append((rel, node.lineno, _literal_strs(kw.value)))
            elif isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "intents" for t in node.targets) \
                        and isinstance(node.value, (ast.List, ast.Tuple)):
                    found.append((rel, node.lineno, _literal_strs(node.value)))
    assert found, f"{SKILLS_DIR} 下解析出 0 处字面量 `intents=[...]` —— 解析失效（fail-closed）"
    return found


def _literal_strs(node: ast.expr) -> list[str]:
    return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def intent_enum_values() -> set[str]:
    """`IntentType` 的取值集（`str, Enum` 的 value）。"""
    from app.router.intent_config import IntentType

    values = {member.value for member in IntentType}
    assert values, "`IntentType` 解析出 0 个取值 —— 枚举真相源失效（fail-closed）"
    return values


def illegal_intents(declared: dict[str, list[str]], enum_values: set[str]) -> list[str]:
    """**判据内核**（纯函数）：返回 `"<来源>: <意图>"` 形式的越界清单（保序去重）。

    `declared` 的键是**来源标签**（文件行 / skill 名），值是该来源声明的意图列表 ——
    来源标签进消息，便于直接定位到要删的那一行。
    """
    bad: list[str] = []
    for source, intents in declared.items():
        for intent in intents:
            if intent not in enum_values:
                entry = f"{source}: {intent}"
                if entry not in bad:
                    bad.append(entry)
    return bad


def test_declared_skill_intents_are_in_the_intent_enum():
    """**F1 核心不变式（源码面）**：skill 声明的每个意图必须是 `IntentType` 的取值。

    当前**绿**（本 PR 同时修掉 `order_skill.py` 的 3 个枚举外意图）；修之前它**是红的**
    —— 红证输出见 PR（`processing_order_generate` 等 3 条）。

    反例输入：在任一 skill 的 `intents=[...]` 里加一个枚举外的名字 ⇒ 必红。
    为什么值得一道门：枚举外意图**不会报错**，只让分类器提示退化成裸 token
    （模型只能靠 token 字面猜），并在路由表里留下永远不会命中的死键。
    """
    declared = {
        f"{rel} 第 {lineno} 行": intents
        for rel, lineno, intents in declared_intent_lists()
    }
    bad = illegal_intents(declared, intent_enum_values())
    assert bad == [], (
        f"skill 声明了 {len(bad)} 个**枚举外意图**（不在 `IntentType` 里）：\n  "
        + "\n  ".join(bad)
        + "\n→ 后果①：分类器提示里整行退化成裸英文 token（`_INTENT_DESCRIPTIONS.get(intent, intent)`）。"
        "\n→ 后果②：分类器出口按 `IntentType(...)` 校验，非法取值静默降级 `general` "
        "⇒ 该意图在 `get_skill_route_map` 里是**永远命中不了的死键**。"
        "\n→ 修法：从 `intents` 里删掉它（要真正支持新意图 ⇒ 先在 `IntentType` 加取值 + "
        "`_INTENT_DESCRIPTIONS` 加描述 + `INTENT_DOMAINS` 归域，四处一起改）。"
    )


def test_registered_skill_intents_are_in_the_intent_enum():
    """**F1 运行时面**：`get_skill_registry()` 里已注册 skill 的 `intents` 必须合法。

    与源码面的分工：这条覆盖**程序化注册**（`registry.register(config)`）这条路径
    —— 源码面只读 `app/graph/skills/**` 的字面量，扫不到运行时拼出来的配置。
    """
    from app.graph.skills.skill_registry import get_skill_registry

    skills = list(get_skill_registry().get_all())
    assert skills, "skill registry 为空 —— 解析失效（守卫会空转，fail-closed）"
    declared = {f"skill `{cfg.name}`": list(cfg.intents) for cfg in skills}
    bad = illegal_intents(declared, intent_enum_values())
    assert bad == [], (
        "已注册 skill 声明了枚举外意图（分类器提示裸 token + 路由表死键）：\n  "
        + "\n  ".join(bad)
    )


def test_declared_intents_cannot_degrade_to_bare_tokens():
    """**F1 观察面**：被 skill 声明过的意图必须在 `_INTENT_DESCRIPTIONS` 里有描述。

    锁的是**模型实际读到的那行文本**（`- <intent>: <desc>`）。与 A8 的守卫互补：
    A8 锁「`IntentType` ⊆ 描述表」（枚举内完整性，`tests/test_intent_classifier.py`），
    本用例锁「**skill 声明** ⊆ 描述表」—— 删掉一个被声明意图的描述键，A8 会红、
    本用例也会红；但若将来描述表改成从别处生成，两边的红点不同，这条仍独立成立。

    反例输入：删掉 `_INTENT_DESCRIPTIONS` 里某个被 skill 声明的键 ⇒ 必红。
    """
    from app.router.intent_classifier import _INTENT_DESCRIPTIONS

    declared = {
        f"{rel} 第 {lineno} 行": intents
        for rel, lineno, intents in declared_intent_lists()
    }
    bare = [
        f"{source}: {intent}"
        for source, intents in declared.items()
        for intent in intents
        if intent not in _INTENT_DESCRIPTIONS
    ]
    assert bare == [], (
        "以下被 skill 声明的意图在 `_INTENT_DESCRIPTIONS` 里**没有描述** "
        "⇒ 分类器提示退化成裸 token：\n  " + "\n  ".join(sorted(set(bare)))
    )


def test_order_skill_classifier_prompt_is_free_of_bare_tokens():
    """**F1 定点**（`order_skill` 的 3 个枚举外意图）：提示里每一行都必须带真实描述。

    本用例 = 上面三条的**端到端**读法：直接构建 `order` skill 的分类器提示并逐行核对
    「`- <intent>: <desc>` 的 desc ≠ intent」。修前实测输出（留档）：

    ```
    - processing_order_generate: processing_order_generate
    - processing_order_query: processing_order_query
    - processing_order_update: processing_order_update
    ```

    反例输入：把 3 个枚举外意图写回 `ORDER_SKILL_CONFIG.intents`（并同步描述表 —— 但描述表
    受 A8 守卫管辖，故这条在两者都放开时才会同时绿）⇒ 必红。
    """
    from app.graph.skills.order_skill import ORDER_SKILL_CONFIG
    from app.router.intent_classifier import _build_classifier_prompt

    prompt = _build_classifier_prompt(list(ORDER_SKILL_CONFIG.intents))
    lines = prompt[prompt.index("意图列表："):prompt.index("请严格以 JSON")].splitlines()
    bare = [
        line.strip() for line in lines
        if line.strip().startswith("- ") and ": " in line
        and line.strip().split(": ", 1)[0][2:] == line.strip().split(": ", 1)[1]
    ]
    print("\n[F1] order skill 分类器提示意图列表：\n  " + "\n  ".join(
        line.strip() for line in lines if line.strip().startswith("- ")
    ))
    assert bare == [], (
        f"`order` skill 的分类器提示里仍有 {len(bare)} 行**裸 token**（模型只能按 token 字面猜）：\n  "
        + "\n  ".join(bare)
    )


class TestIntentLegalityDetectorIsNotVacuous:
    """**:red_circle: 红证（注入式）+ 负例**：判据必须能报出，也必须能不报。"""

    def test_detector_reports_the_order_skill_shape(self):
        """注入 P1 实测的形态（3 个枚举外意图）⇒ **必须报出 3 条**。"""
        declared = {"order_skill.py 第 41 行": [
            "order_query", "order_create", "logistics_track",
            "processing_order_generate", "processing_order_query", "processing_order_update",
        ]}
        assert illegal_intents(declared, {"order_query", "order_create", "logistics_track"}) == [
            "order_skill.py 第 41 行: processing_order_generate",
            "order_skill.py 第 41 行: processing_order_query",
            "order_skill.py 第 41 行: processing_order_update",
        ]

    def test_detector_stays_quiet_on_legal_intents(self):
        """负例：全部合法 ⇒ **必须不报**（防恒红，R2）。"""
        declared = {"order_skill.py 第 41 行": ["order_query", "logistics_track", "order_create"]}
        assert illegal_intents(declared, {"order_query", "logistics_track", "order_create"}) == []

    def test_detector_reports_a_brand_new_skill_with_an_out_of_enum_intent(self):
        """注入：新增 skill 带枚举外意图（「下次加 skill 又写错」的形态）⇒ 必报。"""
        declared = {"brand_new_skill.py 第 12 行": ["invoice_query"]}
        assert illegal_intents(declared, {"order_query"}) == [
            "brand_new_skill.py 第 12 行: invoice_query"
        ]

    def test_literal_reader_reads_real_declarations(self):
        """读源自证：AST 读出的 `order_skill` 声明与运行时配置**一致**（判据不建在猜测上）。"""
        from app.graph.skills.order_skill import ORDER_SKILL_CONFIG

        reader = {
            rel: intents for rel, _lineno, intents in declared_intent_lists()
            if rel.endswith("/order_skill.py")
        }
        assert list(reader.values()) == [list(ORDER_SKILL_CONFIG.intents)], (
            f"AST 读到的 order_skill 声明 {reader} 与运行时配置 "
            f"{list(ORDER_SKILL_CONFIG.intents)} 不一致 —— 判据读错了真相源"
        )
        assert len(declared_intent_lists()) >= 10, (
            "字面量 `intents=[...]` 只解析出个位数 —— 解析疑似失效（漏读会让守卫空转）"
        )