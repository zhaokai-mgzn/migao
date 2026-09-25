# case_ids: OR-029, AS-006, CT-003
"""用例「罐头输入 ↔ 评测 seed 真值」的**常驻静态对账判据**（issue #4064；形态来源 OR-029 / #4015）。

## 为什么要常驻（缺陷类别，不是这一条用例）

OR-029 在 run 35233821582 的米宝腿恒红，真因**不是 agent 不行**：罐头输入里的 7 个字面量
在 `tests/agent_eval/fixtures/{xiaobu,mibao}_eval_seed.sql` 里 **0 命中** ⇒ 合格 agent 如实
指出「对不上」并停在澄清 ⇒ 期望链路**物理上走不完**（恒红）。改前的 7 个字面量逐字为：

    `2699-06` / `蓝灰色`（规格）· `穿杆孔加工` / `包边处理`（加工项）· `9599`（库存）
    · `赵凯` / `13456000919`（客户）

这类缺陷**静态就自相矛盾**，却只有真跑一次 LLM 才会暴露（成本高、发现晚，还会被误读成
「agent 不听话」）。#4053 只对齐了这一条用例，并随 PR 入库两个**一次性**证据脚本
（`acceptance/2026-09-18/or-029-fixture-align/{seed_truth,satisfiable}.py`）——
下一个新用例照旧可以写出与 seed 矛盾的专名/数值。本文件把它做成**零 LLM、秒级**的常驻判据。

## 判据（可解析面）

对 `.github/cases/*.yml` 每条用例，从**声明了具体字面量**的位置取值：
`user_inputs`（含 dict 轮的文本值）/ `namespaces` / `pre_clean` / `precondition`，
按**冻结的形状表**（`SPEC` / `CUSTOMER_WITH_PHONE` / `PHONE` / `STOCK` / `ITEM_LIST`）抽字面量，
再要求它在 seed 的**数据**文本里命中（注释行剔除 —— 命中注释是假绿）。

## 三态口径（缺一不可）

1. **命中 seed 数据文本** ⇒ 通过；
2. **有机器可读的「新值见证」** ⇒ 通过 —— 用例自己声明这个值是它引入的：
   `precondition[…].expect == 0`（声明「当前不存在」）· `pre_clean[*_remove]`（清理本用例自造的对象）
   · 或该字面量所在文本含冻结写动词表（`NEW_VALUE_VERBS`）里的词；
3. 其余 ⇒ **逐条点名** `用例 ID + 字段 + 字面量 + 两边`（期望 = seed 命中 / 实际 = 0 命中）。
   真值确缺的少数条目**显式登记**在 `case_seed_truth_ledger.json`：未登记即红、条目须活着
   （只许缩短）、且只允许出现在**已显式退役**（`skip_reason` 非空）的用例上。

判据只对「**写死的字面量**」生效 —— 以**运行时搜索**定位对象的用例（不写死名字）天然零命中
（红证③ 的正控反向钉住这一点）。

## 边界（如实登记，不静默跳过）

不可判定面在 `case_seed_truth_ledger.json` 的 `undecidable_classes` 里**逐类登记**并在
`undecidable_census()` 里**现取清单**：`data_checks` 的散文/算例数值（金额是派生量 —— 小计/合计/
组合价，seed 无对应真值列）· `role_code` / `finance_txn` 命名空间键（真值在 admin-api 迁移与
服务端返回，不在评测 seed 面）· `debug_permissions_effective` 的 `source`（权限码，不是 seed 实体）。
**新增未登记类 ⇒ 红**；已登记类归零（不再有被跳过的位置）⇒ 也红（台账只许缩短）。
"""
import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
FIXTURES_DIR = REPO_ROOT / "tests" / "agent_eval" / "fixtures"
SEED_SCRIPT = REPO_ROOT / "scripts" / "eval_stack_seed.sh"
LEDGER_PATH = Path(__file__).resolve().parent / "case_seed_truth_ledger.json"

#: 装载 seed 的**唯一实现**（issue #3563）里点名的两个 fixture —— 判据真值与考场数据栈同源。
SEED_FILES = ("xiaobu_eval_seed.sql", "mibao_eval_seed.sql")

# ── 字面量形状表（冻结：改表 = 改判据射程，必须连同红证一起改）──────────────────
#: 规格/色号：`2699-03暖米色`（改前形态 `2699-06 蓝灰色` 同样命中 ⇒ 必被对账）。
SPEC = re.compile(r"(?<![\d-])(\d{4}-\d{2})\s*([\u4e00-\u9fa5]{1,8})")
#: 「姓名（手机号）」——客户名的**唯一可解析锚点**（散文里的裸姓名静态不可判，登记在册）。
CUSTOMER_WITH_PHONE = re.compile(r"([\u4e00-\u9fa5]{2,4})\s*[（(]\s*(1[3-9]\d{9})\s*[)）]")
PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
#: 库存：seed 有**真值列**（`products.stock` / `product_skus.stock`）的唯一数值类。
STOCK = re.compile(r"库存\s*(\d+)")
#: 自由文本里的商品名：**不可判定**（只用于 census，**不**参与对账）——
#: 中文没有词边界，品类后缀锚点会把前一个动词一起吞进来（实测误报「搜遮光窗帘」「看看这个面料」
#: 「分类选窗帘」）⇒ 自由文本商品名一律登记在册；结构化的商品名声明（`namespaces` /
#: `pre_clean.product_keyword` / `precondition.source`）仍在**面内**。
PRODUCT_NAME = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:面料|窗帘|窗纱|布艺|纱帘|遮光布)")
#: 加工项列举：`加工项：打孔、韩褶、定型`（也含 `加工项=名字 ¥8/米` 的确认轮回述形态）。
ITEM_LIST = re.compile(r"加工项\s*[：:=]\s*([^｜|。;；\n]+)")
#: 列表项的**名字**：取前导中文/字母串（把 `¥12/米`、`（按 10 米计…）` 这类价格/口径尾巴切掉），
#: 且至少 2 字（切掉 `/` 切分产生的单字残渣，如单位「米」）。
ITEM_NAME = re.compile(r"^([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9]{1,11})")
#: 金额：只用于**统计不可判定面**（不是对账口径 —— 金额是派生量，见边界段）。
MONEY = re.compile(r"[¥￥]\s*\d")

#: 冻结写动词表：用例在同一段文本里声明「这个值是本用例引入的新值」⇒ 不要求已在 seed。
NEW_VALUE_VERBS = ("新建", "创建", "开个", "开账号", "新客服", "改成", "换号",
                   "录入", "下单", "添加", "补充")

#: 命名空间键：在判据面内 / 显式登记为不可判定类（真值不在评测 seed 面）。
NS_IN_SCOPE = ("product_name", "customer_phone", "customer_name", "employee_name",
               "employee_phone", "category", "order_no", "tag_name")
NS_UNDECIDABLE = ("role_code", "finance_txn")
#: `precondition.source` 不是 seed 实体（是权限码）的类型 ⇒ 显式登记。
PRECONDITION_UNDECIDABLE = ("debug_permissions_effective",)
#: `pre_clean` 里可作「对象名」的键。
PRE_CLEAN_NAME_KEYS = ("product_keyword", "customer_keyword", "employee_name",
                       "order_no", "tag_name")
#: 台账里 `cls` 的允许取值（**只许收紧**：新增取值必须同时给出判据与红证）。
REGISTERED_CLASSES = ("retired_missing_truth",)

LEDGER = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _norm(text):
    return re.sub(r"\s+", "", str(text))


def seed_data_text():
    """两个 fixture 的**数据**文本（注释行剔除、空白归一）—— 本文件唯一的真值口径。

    ⚠️ 命中「**注释行**」不算命中：注释里的旧名（#4572 改名后的历史名）在真库里根本不存在
    ⇒ 算命中就是假绿。判据读的就是 `scripts/eval_stack_seed.sh` 装载的那两个文件。
    """
    lines = []
    for name in SEED_FILES:
        for line in (FIXTURES_DIR / name).read_text(encoding="utf-8").splitlines():
            if not line.strip().startswith("--"):
                lines.append(line)
    return _norm("\n".join(lines))


def _strings(value):
    """dict 轮里除控制键（`auto_select` / `images`）外的所有文本值（罐头输入的实体）。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ("auto_select", "images"):
                continue
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def extract_literals(case):
    """→ [(field, kind, literal, context_text)]；只取**声明了具体字面量**的位置。

    纯函数（判据不写在断言里，才能被注入式红证行使）。
    """
    out = []
    for index, turn in enumerate(case.get("user_inputs") or []):
        field = f"user_inputs[{index}]"
        for text in _strings(turn):
            for match in SPEC.finditer(text):
                out.append((field, "spec", _norm(match.group(0)), text))
            for match in CUSTOMER_WITH_PHONE.finditer(text):
                out.append((field, "customer_name", _norm(match.group(1)), text))
            for match in PHONE.finditer(text):
                out.append((field, "phone", match.group(1), text))
            for match in STOCK.finditer(text):
                out.append((field, "stock", match.group(1), text))
            for match in ITEM_LIST.finditer(text):
                for part in re.split(r"[、,，+/]", match.group(1)):
                    found = ITEM_NAME.match(_norm(part).lstrip("（("))
                    if found:
                        out.append((field, "item", found.group(1), text))
    for index, claim in enumerate(case.get("namespaces") or []):
        key, _, value = str(claim).partition(":")
        if value and key in NS_IN_SCOPE:
            out.append((f"namespaces[{index}]", f"ns:{key}", _norm(value), ""))
    for index, spec in enumerate(case.get("pre_clean") or []):
        if not isinstance(spec, dict):
            continue
        for key in PRE_CLEAN_NAME_KEYS:
            if spec.get(key):
                out.append((f"pre_clean[{index}].{key}",
                            f"pre_clean:{spec.get('type')}", _norm(spec[key]), ""))
    for index, spec in enumerate(case.get("precondition") or []):
        if not isinstance(spec, dict) or spec.get("type") in PRECONDITION_UNDECIDABLE:
            continue
        if spec.get("source"):
            out.append((f"precondition[{index}].source",
                        f"precondition:{spec.get('type')}", _norm(spec["source"]), ""))
    return out


def new_value_witness(case, literal, context):
    """该字面量是否有**机器可读**的「用例自建/新值」见证 → 见证名（`""` = 没有）。

    只有三类见证（全部来自**用例自己的声明**，不是外部豁免清单）：
    `expect=0`（声明当前不存在）· `*_remove`（清理本用例自造的对象）· 所在文本含写动词。
    """
    for spec in case.get("precondition") or []:
        if isinstance(spec, dict) and _norm(spec.get("source")) == literal \
                and spec.get("expect") == 0:
            return f"precondition[{spec.get('type')}].expect=0"
    for spec in case.get("pre_clean") or []:
        if isinstance(spec, dict) and str(spec.get("type", "")).endswith("_remove"):
            if literal in {_norm(v) for v in spec.values() if isinstance(v, str)}:
                return f"pre_clean[{spec.get('type')}]"
    text = context or " ".join(_strings(case.get("user_inputs") or []))
    for verb in NEW_VALUE_VERBS:
        if verb in text:
            return f"verb:{verb}"
    return ""


def adjudicate(cases, seed_text):
    """纯函数：→ {"backed", "introduced", "unbacked", "declared"}（元素为 dict）。"""
    backed, introduced, unbacked = [], [], []
    for case in cases:
        case_id = case.get("id")
        for field, kind, literal, context in extract_literals(case):
            entry = {"case_id": case_id, "field": field, "kind": kind, "literal": literal}
            if literal in seed_text:
                backed.append(dict(entry, witness="seed"))
                continue
            witness = new_value_witness(case, literal, context)
            if witness:
                introduced.append(dict(entry, witness=witness))
            else:
                unbacked.append(dict(entry, witness=""))
    return {"backed": backed, "introduced": introduced, "unbacked": unbacked,
            "declared": backed + introduced + unbacked}


def undecidable_census(cases):
    """现取：被**显式登记为不可判定**而跳过的位置清单（`scope` = 台账里的登记键）。

    它存在的唯一目的是「不许静默跳过」—— 每个未参与对账的位置都必须落在一个已登记类里。
    """
    out = []
    for case in cases:
        case_id = case.get("id")
        for index, check in enumerate(case.get("data_checks") or []):
            text = str(check)
            for kind, pattern in (("money", MONEY), ("stock", STOCK), ("spec", SPEC)):
                if pattern.search(text):
                    out.append({"case_id": case_id, "field": f"data_checks[{index}]",
                                "scope": f"data_checks.{kind}"})
        for index, turn in enumerate(case.get("user_inputs") or []):
            if any(PRODUCT_NAME.search(text) for text in _strings(turn)):
                out.append({"case_id": case_id, "field": f"user_inputs[{index}]",
                            "scope": "user_inputs.product_name"})
        for index, claim in enumerate(case.get("namespaces") or []):
            key = str(claim).partition(":")[0]
            if key in NS_UNDECIDABLE:
                out.append({"case_id": case_id, "field": f"namespaces[{index}]",
                            "scope": f"namespaces.key:{key}"})
        for index, spec in enumerate(case.get("precondition") or []):
            if isinstance(spec, dict) and spec.get("type") in PRECONDITION_UNDECIDABLE \
                    and spec.get("source"):
                out.append({"case_id": case_id, "field": f"precondition[{index}].source",
                            "scope": f"precondition.type:{spec.get('type')}"})
    return out


def load_case_dicts():
    cases = []
    for path in sorted(CASES_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        cases.extend(doc.get("cases") or [])
    return cases


def _fmt(entries):
    """报红用的逐条清单：点名 `用例 ID + 字段 + 类别 + 字面量 + 两边`。"""
    return " ；".join(
        f"{e['case_id']} · {e['field']} · {e['kind']} · 「{e['literal']}」"
        f" —— seed 数据文本 {e.get('status', '0 命中')}" for e in entries)


def _key(entry):
    return (entry["case_id"], entry["field"], entry["literal"])


ALL_CASES = load_case_dicts()
SEED_TEXT = seed_data_text()
REGISTERED = {_key(e) for e in LEDGER["unbacked_entries"]}
DECLARED_SCOPES = {c["scope"] for c in LEDGER["undecidable_classes"]}


# ── ① 前提：真值在哪一侧（防静默空跑）────────────────────────────────────────
class TestSeedTruthPremise:
    def test_the_fixtures_read_are_the_ones_the_eval_stack_loads(self):
        """判据的「真值」与考场的「数据栈」必须同源 —— 断言对象 = 装载脚本自己点名的文件。

        `scripts/eval_stack_seed.sh` 是评测栈种子的**单一实现**（issue #3563：三个 workflow
        曾各写一份且互不相等）⇒ 判据不得另立一份 seed 名单。
        """
        script = SEED_SCRIPT.read_text(encoding="utf-8")
        for name in SEED_FILES:
            assert f"$FIXTURES/{name}" in script, (
                f"装载脚本没有引用 {name} ⇒ 本判据读的 fixture 可能已不是考场真值源：{name}")

    def test_seed_data_text_holds_the_truths_the_criterion_requires(self):
        """前提成立：seed 数据文本真的解析出来了，且含对齐后的 OR-029 真值。"""
                # 现取（2026-09-25，origin/main@f4f7d9070）：17872 字符；下限只作「解析失效」探测。
        assert len(SEED_TEXT) > 15000, f"seed 数据文本只有 {len(SEED_TEXT)} 字符（解析失效？）"
        for literal in ("2699系列雪尼尔窗帘面料", "2699-03暖米色", "打孔", "韩褶", "定型",
                        "1000", "13800138000", "遮光窗帘"):
            assert literal in SEED_TEXT, f"seed 数据文本里没有 {literal}（判据前提失效）"

    def test_comment_lines_are_not_counted_as_truth(self):
        """注释不是数据：只在注释行里出现的词不得算「seed 里能命中」（否则假绿）。"""
        raw = (FIXTURES_DIR / "mibao_eval_seed.sql").read_text(encoding="utf-8")
        comments = [line for line in raw.splitlines() if line.strip().startswith("--")]
        data_lines = [line for line in raw.splitlines() if not line.strip().startswith("--")]
        assert comments, "本前提失效：fixture 里没有注释行可演示"
        comment_only = [token for token in ("has_processing", "product_processing_items",
                                            "纳米圈打孔", "韩式波浪折边")
                        if token in _norm("\n".join(comments))
                        and token not in _norm("\n".join(data_lines))]
        assert comment_only, "注释剔除没有可演示的对象（判据前提失效）"
        for token in comment_only:
            assert token not in SEED_TEXT, f"注释里的 {token} 被当成了 seed 真值"

    def test_the_pre_fix_literals_are_absent_from_the_seed(self):
        """前提：改前的 7 个字面量在 seed 里**确实** 0 命中（红证①的判别力前提）。"""
        for literal in ("2699-06", "蓝灰色", "穿杆孔加工", "包边处理", "9599",
                        "赵凯", "13456000919"):
            assert literal not in SEED_TEXT, f"{literal} 竟在 seed 里 ⇒ 红证①的前提失效"


# ── ② 核心不变式：声明了具体字面量 ⇒ 必须在 seed 里成立（或已登记）─────────────
class TestDeclaredLiteralsAreBackedByTheSeed:
    def test_no_declared_literal_is_unbacked_without_registration(self):
        """**核心判据**：罐头输入/声明里写死的专名与数值，必须在 seed 真值里成立。

        不成立 ⇒ 合格 agent 会如实指出「对不上」并停在澄清 ⇒ 期望链路**物理上走不完**
        （OR-029 恒红形态）。红时逐条点名 `用例 ID + 字段 + 字面量 + 两边`。
        """
        result = adjudicate(ALL_CASES, SEED_TEXT)
        found = {_key(e) for e in result["unbacked"]}
        undeclared = sorted(found - REGISTERED)
        assert undeclared == [], (
            "这些用例声明了具体字面量、seed 数据文本 0 命中、且无任何「新值见证」⇒ 结构性不可满足"
            "（OR-029 / #4015 恒红形态，issue #4064）。两边：期望 = seed 数据文本命中；实际 = 0 命中。"
            "逐条：" + _fmt([{"case_id": c, "field": f, "kind": "—", "literal": lit}
                             for c, f, lit in undeclared]))

    def test_the_census_is_reported_not_silently_skipped(self):
        """读数自证（防「绿了但没跑」）：三态计数非零，且种子被真正读了。"""
        result = adjudicate(ALL_CASES, SEED_TEXT)
        census = undecidable_census(ALL_CASES)
        print(f"用例 {len(ALL_CASES)} 条 · 可解析 {len(result['declared'])} 条"
              f"（命中 seed {len(result['backed'])} / 新值见证 {len(result['introduced'])}"
              f" / 已登记 {len(result['unbacked'])}）· 不可判定 {len(census)} 条")
        assert len(result["backed"]) > 150, len(result["backed"])
        assert len(result["introduced"]) > 0, "新值见证一条都没有 ⇒ 见证机制可能整体失效"
        assert census, "不可判定面归零 ⇒ 分类表可能整体失效"


# ── ③ 红证①：改前的 OR-029 罐头输入（逐字）必须被点名 ────────────────────────
class TestPreFixOr029IsCaught:
    """判别力证明：喂**修复前**的语料（不是"仓库当下恰有该缺陷"式真值主张）。

    语料 = PR #4053 **之前** `origin/main` 上 OR-029 的 4 轮 `user_inputs` 逐字原文
    （`git show 9b12e1d7:.github/cases/order.yml`；锚点 = 该 PR 的 base sha）。
    """

    PRE_FIX_INPUTS = [
        "录订单 赵凯（13456000919）｜ 2699系列雪尼尔窗帘面料 · 2699-06 蓝灰色 · 散剪 · 2.8米 · 10 米"
        " ｜ 加工项：韩式波浪折边、穿杆孔加工、包边处理",
        "1. 2699系列雪尼尔窗帘面料｜¥23.8/米｜库存 9599",
        "已有客户",
        "确认：加工项=韩式波浪折边 ¥12/米、穿杆孔加工 ¥4/米、包边处理 ¥10/米（按 10 米计约 ¥260）；"
        "商品=2699系列雪尼尔窗帘面料；客户=赵凯（13456000919）· 已有客户；数量=10 米；"
        "规格=2699-06 蓝灰色 · 散剪 · 2.8米；面料单价=¥23.8/米（面料小计 ¥238）；"
        "预估合计=约 ¥498（以系统结算为准）",
    ]
    PRE_FIX_CASE = {
        "id": "OR-029",
        "user_inputs": PRE_FIX_INPUTS,
        "namespaces": ["customer_phone:13456000919", "product_name:2699系列雪尼尔窗帘面料"],
        "precondition": [{"type": "product_count_for_keyword",
                          "source": "2699系列雪尼尔窗帘面料", "expect": 1}],
        "pre_clean": [{"type": "product_dedupe",
                       "product_keyword": "2699系列雪尼尔窗帘面料", "price": 23.8}],
    }
    #: 改前语料里 seed 0 命中的 7 个字面量（红证必须逐条点名）。
    PRE_FIX_LITERALS = ("2699-06", "蓝灰色", "穿杆孔加工", "包边处理", "9599",
                        "赵凯", "13456000919")

    def test_every_pre_fix_literal_is_reported_with_both_sides(self):
        """改前形态 ⇒ 必红；报出内容必须**逐字含两边**（字面量 + seed 侧 0 命中）。"""
        result = adjudicate([self.PRE_FIX_CASE], SEED_TEXT)
        message = _fmt(result["unbacked"])
        for literal in self.PRE_FIX_LITERALS:
            assert literal in message, (
                f"改前语料里的「{literal}」没有被点名 ⇒ 判据对 OR-029 形态无判别力。"
                f"实报：{message}")
        assert "seed 数据文本 0 命中" in message, message
        assert result["unbacked"], "改前语料竟然全绿 ⇒ 判据恒绿（空断言）"
        assert result["introduced"] == [], (
            f"改前语料的字面量被误判成「用例自建的新值」⇒ 红证被见证机制吃掉：{result['introduced']}")

    def test_aligned_to_seed_truth_is_green(self):
        """反向（防把判据写成「凡引用皆红」）：同一批输入改成 seed 真值 ⇒ 一条都不报。"""
        aligned = dict(self.PRE_FIX_CASE, user_inputs=[
            "录订单 张三（13800138000）｜ 2699系列雪尼尔窗帘面料 · 2699-03暖米色 · 散剪 · 2.8米"
            " · 10 米 ｜ 加工项：打孔、韩褶、定型",
            "1. 2699系列雪尼尔窗帘面料｜¥23.8/米｜库存 1000",
            "已有客户",
            "确认：加工项=打孔、韩褶、定型；商品=2699系列雪尼尔窗帘面料；"
            "客户=张三（13800138000）· 已有客户；数量=10 米；规格=2699-03暖米色 · 散剪 · 2.8米",
        ], namespaces=["customer_phone:13800138000", "product_name:2699系列雪尼尔窗帘面料"])
        result = adjudicate([aligned], SEED_TEXT)
        assert result["unbacked"] == [], (
            f"对齐到 seed 真值后仍然报红 ⇒ 判据不可满足（改数据也过不了）：{_fmt(result['unbacked'])}")
        assert len(result["backed"]) >= 6, result["backed"]

    def test_the_live_or029_in_the_library_is_green(self):
        """改后必绿：**仓库当下**的 OR-029（#4053 已对齐）零未命中。"""
        live = [case for case in ALL_CASES if case.get("id") == "OR-029"]
        assert live, "用例库里没有 OR-029（判据对象消失）"
        assert adjudicate(live, SEED_TEXT)["unbacked"] == []


# ── ④ 红证②（R2 负例）：运行时搜索定位对象的用例不得被误判 ────────────────────
class TestRuntimeSearchCasesAreNotFlagged:
    RUNTIME_CASE = {
        "id": "XX-900",
        "user_inputs": ["帮我找一下最便宜的窗帘", "第一个", "它还有货吗"],
        "namespaces": [],
        "pre_clean": [],
        "precondition": [],
    }

    def test_a_case_that_locates_objects_at_runtime_is_green(self):
        """负例：不写死名字（靠运行时搜索定位）⇒ 判据无对象可判 ⇒ 不得红。"""
        assert adjudicate([self.RUNTIME_CASE], SEED_TEXT)["unbacked"] == []

    def test_a_product_name_absent_from_the_seed_goes_red(self):
        """任务要求的红证：**输入引用 seed 里不存在的商品名** ⇒ 必红并点名字段与两边值。

        注入语料走用例库的既有约定（点名商品必须同时声明 `namespaces` / `precondition`）
        —— 自由文本商品名不参与对账（中文无词边界，见 `PRODUCT_NAME` 的登记理由）。
        """
        injected = {
            "id": "XX-901",
            "user_inputs": ["帮我查一下 星空梦幻遮光窗帘 的价格，还有几米库存"],
            "namespaces": ["product_name:星空梦幻遮光窗帘"],
            "precondition": [{"type": "product_count_for_keyword",
                              "source": "星空梦幻遮光窗帘", "expect": 1}],
        }
        result = adjudicate([injected], SEED_TEXT)
        reported = {entry["literal"] for entry in result["unbacked"]}
        assert reported == {"星空梦幻遮光窗帘"}, reported
        fields = {entry["field"] for entry in result["unbacked"]}
        assert fields == {"namespaces[0]", "precondition[0].source"}, fields
        message = _fmt(result["unbacked"])
        assert "星空梦幻遮光窗帘" in message and "seed 数据文本 0 命中" in message, message
        # 负控：把同一个商品换成 seed 里有的名字 ⇒ 判据不报（不是「凡点名皆红」）
        healthy = dict(injected, user_inputs=["帮我查一下 遮光窗帘 的价格，还有几米库存"],
                       namespaces=["product_name:遮光窗帘"],
                       precondition=[{"type": "product_count_for_keyword",
                                      "source": "遮光窗帘", "expect": 1}])
        assert adjudicate([healthy], SEED_TEXT)["unbacked"] == []

    def test_the_same_shape_goes_red_once_a_name_is_hardcoded(self):
        """负例的**正控**（防「负例=空断言」）：同一形态写死一个 seed 里没有的专名 ⇒ 照旧红。"""
        poisoned = dict(self.RUNTIME_CASE, user_inputs=["我要 2699-06 蓝灰色 的窗帘，还有货吗"])
        result = adjudicate([poisoned], SEED_TEXT)
        assert result["unbacked"], "写死了不存在的专名却不报 ⇒ 判据对「写死」这一半没有判别力"
        assert "2699-06蓝灰色" in _fmt(result["unbacked"]), _fmt(result["unbacked"])


# ── ⑤ 台账：未登记即红、条目须活着、只许缩短 ─────────────────────────────────
class TestRegistrationLedgerShrinksOnly:
    def test_registered_entries_are_exactly_the_live_unbacked_ones(self):
        """两个方向都钉：台账不得含**已失效**条目（只许缩短），未命中项不得**无登记**。"""
        found = {_key(e) for e in adjudicate(ALL_CASES, SEED_TEXT)["unbacked"]}
        stale = sorted(REGISTERED - found)
        assert stale == [], (
            "台账条目已失效（真值补齐 / 字段改名 / 用例删除）⇒ 必须从 "
            f"tests/unit_ci_workflows/case_seed_truth_ledger.json 删除（只许缩短）：{sorted(stale)}")
        assert sorted(found - REGISTERED) == [], sorted(found - REGISTERED)

    def test_registered_entries_are_confined_to_retired_cases(self):
        """**真值缺失的登记只许落在已显式退役的用例上** —— 活跃用例的未命中一律必须修数据/改用例。

        这就是「不许为了让判据变绿而登记」的机械边界：活跃用例根本没有登记出口。
        """
        by_id = {case.get("id"): case for case in ALL_CASES}
        for entry in LEDGER["unbacked_entries"]:
            assert entry.get("cls") in REGISTERED_CLASSES, entry
            assert str(entry.get("reason") or "").strip(), entry
            case = by_id.get(entry["case_id"])
            assert case, f"台账指向不存在的用例：{entry}"
            assert str(case.get("skip_reason") or "").strip(), (
                f"台账登记了**活跃**用例 {entry['case_id']} 的未命中项 ⇒ 没有真值缺失可登记，"
                f"必须修用例/seed（issue #4064 硬约束 R4）：{entry}")

    def test_the_ledger_has_no_declared_class_it_does_not_use(self):
        """已登记类必须仍有被跳过的位置（否则它是死登记 ⇒ 删掉，只许缩短）。"""
        census = undecidable_census(ALL_CASES)
        live = {entry["scope"] for entry in census}
        assert DECLARED_SCOPES - live == set(), sorted(DECLARED_SCOPES - live)


# ── ⑥ 不可判定面：显式登记 + 现取清单（不许静默跳过）────────────────────────
class TestUndecidableSurfaceIsRegistered:
    def test_every_skipped_position_belongs_to_a_registered_class(self):
        """面外不是安全区：每个未参与对账的位置都必须落在一个**已登记类**里，且清单可现取。"""
        census = undecidable_census(ALL_CASES)
        undeclared = sorted({entry["scope"] for entry in census} - DECLARED_SCOPES)
        assert undeclared == [], (
            "这些位置被本判据跳过却没有登记（静默跳过 = 面外当安全区）："
            f"{undeclared}；现取清单见 undecidable_census()，登记见 case_seed_truth_ledger.json")

    def test_the_undecidable_census_is_printed_for_review(self):
        """打印未命中清单（本仓口径：写得下就要写得出来，不是靠人记得去看）。"""
        census = undecidable_census(ALL_CASES)
        by_scope = {}
        for entry in census:
            by_scope.setdefault(entry["scope"], []).append(entry)
        lines = [f"不可判定面现取 {len(census)} 条 / 登记 {len(DECLARED_SCOPES)} 类："]
        for scope in sorted(by_scope):
            names = ", ".join(f"{e['case_id']}:{e['field']}" for e in by_scope[scope][:6])
            lines.append(f"  · {scope} × {len(by_scope[scope])}（{names} …）")
        report = "\n".join(lines)
        print(report)
        assert len(by_scope) == len(DECLARED_SCOPES), report


if __name__ == "__main__":       # 复算读数（零 LLM、不连库）：python <本文件>
    _result = adjudicate(ALL_CASES, SEED_TEXT)
    _census = undecidable_census(ALL_CASES)
    print(f"用例 {len(ALL_CASES)} 条 · 可解析 {len(_result['declared'])} 条"
          f"（命中 seed {len(_result['backed'])} / 新值见证 {len(_result['introduced'])}"
          f" / 已登记 {len(_result['unbacked'])}）· 不可判定 {len(_census)} 条")
    print("未命中且无见证（应为空或全在台账内）：")
    for _entry in _result["unbacked"]:
        print("  " + _fmt([_entry]))