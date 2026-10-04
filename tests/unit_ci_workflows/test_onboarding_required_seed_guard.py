# case_ids: MC-083
"""类级元守卫：**开租必需初始数据清单 ⇄ 入驻链路的播种调用**（issue #6295）。

## 病灶（这一族缺陷的形态）

入驻链路（`RegistrationService.approveApplication`）此前种了行业生产模板、**唯独漏了商品分类**
⇒ 新租户 `categories` 表为空，而建商品（非草稿）要求 `categoryId` 非空 ⇒
**开箱第一次建商品必撞 422「分类ID不能为空」**（#6295）。

这不是一处笔误，是**一族**：只要「开租必需种什么」只活在人的记忆与代码评审里，
下一次新增域（客户标签 / 工艺 / 岗位…）就会再漏一次，而且**不会有任何东西变红**
（#4430 对生产模板的复盘逐字如此：「删掉那一行调用 CI 全绿」）。

## 本守卫锁六条（每条都能单独变红）

| # | 判什么 | 怎么红 |
|---|---|---|
| 1 | **清单里的项，链路里必须真的种**：`OnboardingInitialData.REQUIRED` 每条的 `seedAnchor` 必须逐字出现在 `RegistrationService` 的**代码**里（剥注释与字符串后判定 ⇒ 「注释里写一句调用」不算） | 删掉某个播种调用（= #6295 的原始形态）⇒ 具名报出该 key |
| 2 | **未登记即红**：链路里出现的每个 `*Seed*` / `*Template*` 协作者**接收者**都必须有清单条目认领 | 新增一个种子服务却忘了登记 ⇒ 具名报出该接收者 |
| 3 | **后置条件校验接线在**：`assertRequiredInitialData(` 必须在链路里被调用，且清单中**每个 enforced 项**的键常量必须出现在该校验方法体内 | 删掉校验调用 / 删掉某一项的检查行 ⇒ 具名报出 |
| 4 | **豁免台账只许缩短 + 双向对齐**：非 enforced（尽力而为）项必须在 `onboarding_required_seed_ledger.json` 的 `best_effort` 里写明 `reason` + `reopen_condition`；台账里不许有清单中不存在的键；条数不得超过 `exemptions_frozen_count`（**现取**比对，不是快照断言） | 少写理由 / 多出条目 / 条数超过冻结上限 ⇒ 红 |
| 5 | **默认值单一来源**：`DEFAULT_PRODUCT_CATEGORY_NAME` 的字面量在整个 `admin-api` 主源码里**恰出现一次**（只在定义处） | 别处再抄一份字面量（「散落的魔法常量」）⇒ 具名报出文件 |
| 6 | **判别力自证**：第 1~5 条的坏形态在内存里各自判红（对真语料做变异，不改盘上文件）、且「只改注释」**不**红 | 守卫本身退化成恒绿 ⇒ 红 |

## 边界（如实登记，`migao-dev-flow` §19.1）

- 判的是**接线锚在不在**（结构面）：`RegistrationService` 里真的出现了那两次调用、校验方法真的引用了那些键。
  「那段接线在真 session / 真入库上跑得对不对」由实例判据承担 ——
  `backend/admin-api/src/test/java/com/migao/admin/service/NewTenantOnboardingCategoryRealDbTest.java`
  （真 PG：入驻 ⇒ 分类恰 1 行 ⇒ 首建商品成功；注入摘掉种子 ⇒ 逐字 422）。
- 判据 2 的扫描面 = `RegistrationService` 一个文件里的 `*Seed*` / `*Template*` 接收者。
  它**不**裁「种子写得对不对」，只裁「有没有登记」。
- 本守卫不跑被它引用的 Dev 测试（不 `pytest` 嵌套 Java），否则「未登记即红」会变成全量套件再跑一遍。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin"
CHECKLIST = SERVICE_DIR / "service" / "OnboardingInitialData.java"
ONBOARDING = SERVICE_DIR / "service" / "RegistrationService.java"
LEDGER = Path(__file__).resolve().parent / "onboarding_required_seed_ledger.json"

#: 后置条件校验方法名（判据 3 的接线锚；改名 ⇒ 红，改名的同时改本常量）
POSTCONDITION_METHOD = "assertRequiredInitialData("
#: 必需初始数据清单的字段名（真值源）
CHECKLIST_FIELD = "REQUIRED"
#: 默认值常量的名字（判据 5 靠它从真值源**现取**字面量，不写死在判据里）
DEFAULT_NAME_CONSTANT = "DEFAULT_PRODUCT_CATEGORY_NAME"

#: 逐字形如 `new Item(KEY_CONST, "…", "anchor(", true|false)`
_ITEM_RE = re.compile(
    r"new\s+Item\(\s*(\w+)\s*,\s*\"(?:[^\"\\]|\\.)*\"\s*,\s*\"([^\"]+)\"\s*,\s*(true|false)\s*\)")
_STRING_CONST_RE = re.compile(r'public\s+static\s+final\s+String\s+(\w+)\s*=\s*"([^"]*)"')
#: 链路里的种子协作者接收者（锚 `productCategorySeedService.seedDefaultCategory` 的接收者部分）。
#: 命名约定 = `*Seed*Service`（见 `OnboardingInitialData` 的「约定」段）—— 覆盖面**故意收窄**：
#: 全仓还有 `redisTemplate` / `smsService` 这类与「开租必需初始数据」无关的协作者，
#: 宽松判据会把它们误判成「未登记的种子」。
_SEED_RECEIVER_RE = re.compile(r"\b([a-z][A-Za-z0-9]*Seed[A-Za-z0-9]*Service)\s*\.")


# ────────────────────────────────────── 解析工具

def _java_code_only(text: str) -> str:
    """剥掉注释与字符串**内容**，只留代码（防「注释里提一句」把判据喂绿）。

    顺序要紧：先块注释，再字符串/字符字面量，最后行注释 —— 否则 URL 里的 `//` 会被当成行注释。
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', text)
    text = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", text)
    return re.sub(r"//[^\n]*", " ", text)


def _method_body(code: str, signature: str) -> str | None:
    """按签名找到方法体（大括号配平）—— 判据要的是「方法体内引用了哪些键」，不是「全文提过没」。"""
    i = code.find(signature)
    if i < 0:
        return None
    j = code.find("{", i)
    if j < 0:
        return None
    depth = 0
    for k in range(j, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return code[j:k + 1]
    return None


def parse_checklist(checklist_text: str) -> list[dict]:
    """从**真值源**解析清单（不复制一份到判据里）。

    解析不到任何条目 ⇒ 抛 AssertionError（fail-closed：格式漂移不许静默变绿）。
    """
    constants = dict(_STRING_CONST_RE.findall(checklist_text))
    m = re.search(re.escape(CHECKLIST_FIELD) + r"\s*=\s*List\.of\((.*?)\);", checklist_text, re.DOTALL)
    assert m, (
        f"`{CHECKLIST.name}` 里找不到 `{CHECKLIST_FIELD} = List.of(...);` —— 必需初始数据清单被删/改名了？"
        "（本判据的真值源就是它；清单空了 ⇒ 本判据 fail-closed 判红）")
    field = m.group(1)
    items = []
    for key_const, anchor, enforced in _ITEM_RE.findall(field):
        key = constants.get(key_const)
        assert key, (f"清单条目引用了未定义的键常量 `{key_const}` —— 键必须是 "
                     f"`{CHECKLIST.name}` 里的 `public static final String` 常量（进报错文案与台账）")
        items.append({"key": key, "key_const": key_const, "anchor": anchor,
                      "enforced": enforced == "true"})
    assert items, (
        f"`{CHECKLIST_FIELD}` 解析出 0 条 —— 要么清单被清空，要么条目形态不再是 "
        '`new Item(KEY_CONST, "描述", "接收者.方法(", true|false)`（后者请同批更新本判据）')
    return items


def parse_default_name(checklist_text: str) -> str:
    m = re.search(re.escape(DEFAULT_NAME_CONSTANT) + r'\s*=\s*"([^"]*)"', checklist_text)
    assert m, (f"`{CHECKLIST.name}` 里找不到 `{DEFAULT_NAME_CONSTANT} = \"…\";` —— "
               "默认值的单一来源被删/改名了？（判据 5 靠它现取字面量）")
    return m.group(1)


# ────────────────────────────────────── 判据本体（纯函数：真语料 + 变异语料共用）

def _squash(text: str) -> str:
    """去掉所有空白 —— 锚只认「接收者.方法」这段标识符链，换行与缩进不该让判据判红。"""
    return re.sub(r"\s+", "", text)


def check_anchors_seeded(items: list[dict], onboarding_code: str) -> list[str]:
    """判据 1：清单每条的 seedAnchor 必须逐字出现在链路**代码**里（空白无关）。"""
    squashed = _squash(onboarding_code)
    return [f"清单项 `{it['key']}` 的播种锚 `{it['anchor']}` 未出现在 {ONBOARDING.name}（漏种）"
            for it in items if _squash(it["anchor"]) not in squashed]


def check_no_unregistered_seed_calls(items: list[dict], onboarding_code: str) -> list[str]:
    """判据 2：链路里的种子协作者接收者必须全部被清单认领（未登记即红）。"""
    registered = {it["anchor"].split(".")[0] for it in items}
    found = set(_SEED_RECEIVER_RE.findall(onboarding_code))
    return [f"{ONBOARDING.name} 里出现了未登记的种子协作者 `{r}` —— "
            "新增开租必需初始数据必须在 OnboardingInitialData.REQUIRED 里登记一条"
            "（或把该调用移出开租链路）" for r in sorted(found - registered)]


def check_postcondition_wired(items: list[dict], onboarding_code: str) -> list[str]:
    """判据 3：后置条件校验被调用，且 enforced 项的键在**校验方法体内**被引用。"""
    problems = []
    if POSTCONDITION_METHOD not in onboarding_code:
        return [f"{ONBOARDING.name} 里找不到后置条件校验 `{POSTCONDITION_METHOD}` —— "
                "入驻链路的后置条件元守卫被摘掉了（漏种会退回静默）"]
    body = _method_body(onboarding_code, f"private void {POSTCONDITION_METHOD}")
    if body is None:
        return [f"找不到 `private void {POSTCONDITION_METHOD}…)` 的方法体 —— 改名了？"
                "（改名请同批更新本判据的 POSTCONDITION_METHOD 常量）"]
    for it in items:
        if it["enforced"] and it["key_const"] not in body:
            problems.append(
                f"必需初始数据 `{it['key']}`（enforced）在后置条件校验 `{POSTCONDITION_METHOD}` 的方法体里"
                "没有任何检查 —— 该项缺席时开租不会红（= 静默产出不可用租户）")
    return problems


def check_ledger(items: list[dict], ledger: dict) -> list[str]:
    """判据 4：豁免台账双向对齐 + 条数只许缩短（现取比对）。"""
    problems = []
    best_effort = ledger.get("best_effort") or {}
    frozen = ledger.get("exemptions_frozen_count")
    assert isinstance(frozen, int), (
        f"`{LEDGER.name}` 缺 `exemptions_frozen_count`（整数）—— 没有冻结上限就没有「只许缩短」")
    keys = {it["key"] for it in items}
    for it in items:
        if it["enforced"]:
            continue
        entry = best_effort.get(it["key"])
        if not isinstance(entry, dict):
            problems.append(f"非 enforced 项 `{it['key']}` 未在 {LEDGER.name} 的 best_effort 里登记理由")
            continue
        for field in ("reason", "reopen_condition"):
            if not str(entry.get(field) or "").strip():
                problems.append(f"台账条目 `{it['key']}` 缺 `{field}`（豁免必须写明理由与重启条件）")
    for key in sorted(set(best_effort) - keys):
        problems.append(f"台账里 `{key}` 在清单中不存在 —— 删掉它（台账只许缩短，不许留陈旧条目）")
    if len(best_effort) > frozen:
        problems.append(f"豁免条数 {len(best_effort)} 超过冻结上限 {frozen} —— 台账**只许缩短**"
                        "（要新增豁免就必须在 PR 里显式抬上限并说明为什么这项不能是 enforced）")
    return problems


def check_single_source_of_default_name(default_name: str, main_java_texts: dict[str, str]) -> list[str]:
    """判据 5：默认分类名的字面量在 admin-api 主源码里恰出现一次（定义了它自己那一处）。"""
    literal = f'"{default_name}"'
    hits = sorted(rel for rel, text in main_java_texts.items() if literal in text)
    if len(hits) == 1:
        return []
    if not hits:
        return [f"默认分类名 `{literal}` 在 admin-api 主源码里**一次都没出现** —— "
                f"{DEFAULT_NAME_CONSTANT} 的取值被动态化了？默认值必须是可审计的字面量常量"]
    return [f"默认分类名 `{literal}` 出现在 {len(hits)} 处（须恰 1 处 = 定义处）：{hits} —— "
            "默认值要有单一来源，别处请引用 "
            f"`OnboardingInitialData.{DEFAULT_NAME_CONSTANT}`"]


# ────────────────────────────────────── 真语料夹具

def _main_java_texts() -> dict[str, str]:
    return {str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf-8")
            for p in sorted(SERVICE_DIR.rglob("*.java"))}


def _load() -> tuple[str, str, dict]:
    checklist_text = CHECKLIST.read_text(encoding="utf-8")
    onboarding_code = _java_code_only(ONBOARDING.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    return checklist_text, onboarding_code, ledger


# ────────────────────────────────────── 判据 1~5（真语料）

def test_required_seed_anchors_are_present_in_onboarding():
    """判据 1：清单里每一条的播种调用都真的在入驻链路里（#6295 的原始形态 = 这一条红）。"""
    checklist_text, onboarding_code, _ = _load()
    problems = check_anchors_seeded(parse_checklist(checklist_text), onboarding_code)
    assert not problems, "开租必需初始数据漏种：\n  " + "\n  ".join(problems)


def test_no_unregistered_seed_collaborators_in_onboarding():
    """判据 2：未登记即红。"""
    checklist_text, onboarding_code, _ = _load()
    problems = check_no_unregistered_seed_calls(parse_checklist(checklist_text), onboarding_code)
    assert not problems, "\n  ".join(problems)


def test_onboarding_postcondition_guard_is_wired():
    """判据 3：入驻后置条件元守卫接线在，且 enforced 项逐条被检查。"""
    checklist_text, onboarding_code, _ = _load()
    problems = check_postcondition_wired(parse_checklist(checklist_text), onboarding_code)
    assert not problems, "入驻后置条件校验不完整：\n  " + "\n  ".join(problems)


def test_exemption_ledger_is_double_sided_and_only_shrinks():
    """判据 4：豁免台账双向对齐 + 只许缩短。"""
    checklist_text, _, ledger = _load()
    problems = check_ledger(parse_checklist(checklist_text), ledger)
    assert not problems, "豁免台账不合规：\n  " + "\n  ".join(problems)


def test_default_category_name_has_a_single_source():
    """判据 5：默认分类名只有一个来源（字面量恰一处）。"""
    checklist_text, _, _ = _load()
    problems = check_single_source_of_default_name(parse_default_name(checklist_text), _main_java_texts())
    assert not problems, "\n  ".join(problems)


# ────────────────────────────────────── 判据 6：判别力自证（内存变异，不改盘上文件）

def test_guard_has_discriminating_power_on_mutated_corpus():
    """判据 6：六种坏形态各自判红 + 「只改注释」不红（守卫自身不许退化成恒绿）。"""
    checklist_text, onboarding_code, ledger = _load()
    items = parse_checklist(checklist_text)
    main_java = _main_java_texts()

    # ① 注释里写一句调用 ⇒ 判据 1 **不**该被喂绿（剥注释后锚不见了）
    raw_src = ONBOARDING.read_text(encoding="utf-8")
    commented = _java_code_only(
        raw_src.replace(items[0]["anchor"] + "(", "// " + items[0]["anchor"] + "("))
    assert check_anchors_seeded(items, commented), "把调用注释掉必须判红（注释不算种）"

    # ② 摘掉播种调用（#6295 的原始形态）⇒ 判据 1 红
    removed = onboarding_code.replace(items[0]["anchor"] + "(", "seededElsewhere(")
    assert check_anchors_seeded(items, removed), "摘掉播种调用必须判红"

    # ③ 新增未登记的种子协作者 ⇒ 判据 2 红
    extra = onboarding_code + "\n        tenantProfileSeedService.seedAll(tenant.getId());\n"
    assert check_no_unregistered_seed_calls(items, extra), "未登记的种子调用必须判红"

    # ④ 摘掉后置条件校验（调用 + 方法体）⇒ 判据 3 红
    no_guard = onboarding_code.replace(POSTCONDITION_METHOD, "noPostconditionCheck(")
    assert check_postcondition_wired(items, no_guard), "摘掉后置条件校验必须判红"
    # ④b 只摘掉 enforced 项的检查行 ⇒ 判据 3 仍要红
    enforced = [it for it in items if it["enforced"]][0]
    no_item_check = onboarding_code.replace(
        f"missing.add(OnboardingInitialData.{enforced['key_const']});", "// dropped")
    assert check_postcondition_wired(items, no_item_check), "删掉某一 enforced 项的检查行必须判红"

    # ⑤ 台账：少写理由 / 多出条目 / 超出冻结上限 ⇒ 判据 4 红
    assert check_ledger(items, {"best_effort": {}, "exemptions_frozen_count": 0}), \
        "非 enforced 项没登记理由必须判红"
    assert check_ledger(items, {"best_effort": {"ghost": {"reason": "x", "reopen_condition": "y"}},
                                "exemptions_frozen_count": 1}), "台账里的幽灵条目必须判红"
    assert check_ledger(items, {"best_effort": ledger["best_effort"] | {"extra": {
        "reason": "x", "reopen_condition": "y"}}, "exemptions_frozen_count": 1}), \
        "豁免条数超过冻结上限必须判红"

    # ⑥ 默认值再抄一份字面量 ⇒ 判据 5 红（单一来源被破坏）
    name = parse_default_name(checklist_text)
    duplicated = dict(main_java)
    duplicated["backend/admin-api/src/main/java/com/migao/admin/service/Copy.java"] = f'x = "{name}";\n'
    assert check_single_source_of_default_name(name, duplicated), "重复字面量必须判红"

    # ⑦ 反向对照：只改注释 ⇒ 五条判据全不红
    commented_everywhere = {
        "anchors": check_anchors_seeded(items, _java_code_only(
            ONBOARDING.read_text(encoding="utf-8") + "\n// " + items[0]["anchor"] + "\n")),
        "receivers": check_no_unregistered_seed_calls(items, _java_code_only(
            ONBOARDING.read_text(encoding="utf-8") + "\n// ghostSeedService.x()\n")),
        "postcondition": check_postcondition_wired(items, _java_code_only(
            ONBOARDING.read_text(encoding="utf-8") + "\n// " + POSTCONDITION_METHOD + ")\n")),
        "ledger": check_ledger(items, ledger),
        "single_source": check_single_source_of_default_name(name, main_java),
    }
    assert not any(commented_everywhere.values()), (
        "只改注释被误判成违规（判据被自己的文案喂红）："
        + ", ".join(k for k, v in commented_everywhere.items() if v))
