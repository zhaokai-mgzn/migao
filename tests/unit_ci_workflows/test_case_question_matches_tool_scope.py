# case_ids: CU-003
"""用例**问句的取数面**必须与它期望的工具自洽（issue #8124；CU-003 的 `list_tags` 不自洽）。

## 病灶（现取读数，不是假说）

`CU-003` 的期望是 `customer_manage(action=list_tags)` —— 该 action 的取数面是
`GET /api/admin/customer-tags`（**全店标签目录**，不带 `customer_id`，见
`backend/ai-agent-service/app/tools/customer_manage.py` 的 `_list_tags`）。而改前问句问的是
「张三（手机号 13800138000）**都有哪些标签**？」—— 那是**某个客户自己的标签**，答案在
`detail` 返回的 `tags` 字段里。⇒ 问法与期望指向**两个不同的取数面**：B 端 normal 基线
run 40875358973 里 agent 合理地走 `list → detail`、`list_tags` 从未被调用，
用例恒红且**归因错误**（看起来像「agent 不会查标签」）。

## 为什么另开一个文件（不改 `test_eval_case_asset_truth.py`）

那条守卫 `TestCU003AssetIsSatisfiableAndNotRelaxed` 的射程是「只读形态 / 唯一指代 /
无写路径声明」，**看不见问句的取数面** —— 实测：把问句改回
「这个客户（手机号 13800138000）都有哪些标签？」后它 **30 passed 全绿**。
按 `migao-dev-flow` §23「修一个缺陷只修这一处 = 没修」，实例判据（会红）补在本文件；
原守卫**一字不动**（issue #8124 的裁定 B：不用守卫强度换覆盖）。

## 判据形态

零 LLM、纯静态。对**每一条**期望里含 `customer_manage(action=list_tags)` 的用例：
① 问句必须点明**全店范围**（店里 / 全店 / 店铺 / 标签目录 / 标签体系）；
② 问句**不得**把标签挂到某个客户身上（这个客户 / 该客户 / 此客户 / 他的标签 / 她的标签 /
   客户的标签 / 名下）—— 那是 `detail` 的取数面，不是 `list_tags` 的。
两条都配**注入式红证**（喂改前形态 ⇒ 必逐条报出）与**负控**（当前用例零违规；`detail`
用例不被误伤 —— 判据按 `expectations` 限定射程，不是「禁一切客户指代」的一刀切）。
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"

#: `list_tags` 的**全店范围**标记（问句要点明它问的是目录，不是一个客户）
STORE_SCOPE_MARKERS = ("店里", "全店", "店铺", "标签目录", "标签体系")

#: 把标签挂到某个客户身上的形态 —— 归 `customer_manage(action=detail)` 的取数面
CUSTOMER_SCOPE_MARKERS = ("这个客户", "该客户", "此客户", "他的标签", "她的标签",
                          "客户的标签", "名下")


def _expects_list_tags(case: dict) -> bool:
    """用例是否把 `customer_manage(action=list_tags)` 当期望（= 判据的射程）。"""
    for exp in case.get("expectations") or []:
        if not isinstance(exp, dict):
            continue
        args = exp.get("args") or {}
        if exp.get("tool") == "customer_manage" and args.get("action") == "list_tags":
            return True
    return False


def list_tags_question_violations(question: str) -> list:
    """**判据本体（纯函数）**：一条问句在「全店标签目录」取数面上的不自洽形态（空 = 自洽）。

    纯函数是为了让**注入式红证**能行使它（`migao-acceptance`：不会红的断言 = 空断言）。
    """
    out = []
    if not any(marker in question for marker in STORE_SCOPE_MARKERS):
        out.append(
            "问句没有点明**全店范围**（缺 店里 / 全店 / 店铺 / 标签目录 / 标签体系 之一）"
            f" ⇒ `list_tags` 答不上「哪些标签」是常态：{question!r}")
    hit = [marker for marker in CUSTOMER_SCOPE_MARKERS if marker in question]
    if hit:
        out.append(
            f"问句把标签挂到某个客户身上（命中 {hit}）—— 那是 `customer_manage(action=detail)` "
            f"的取数面，`list_tags` 答的是**全店目录**：{question!r}")
    return out


def _all_cases() -> list:
    """`(文件名, 用例 dict)` 全量（`cases/*.yml` 单一源，不读生成物）。"""
    out = []
    for path in sorted(CASES_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for case in doc.get("cases") or []:
            out.append((path.name, case))
    return out


def _case(cid: str):
    for fname, case in _all_cases():
        if case.get("id") == cid:
            return fname, case
    raise AssertionError(f"用例 {cid} 不在 `.github/cases/*.yml` 里 —— 判据的前提没了，不许静默跳过")


def test_cu003_question_is_the_store_catalog_question():
    """CU-003 的问句必须问**店里有哪些标签**（#8124 的实例判据）。"""
    _, case = _case("CU-003")
    question = str(case["user_inputs"][0])
    violations = list_tags_question_violations(question)
    assert violations == [], f"CU-003 的问句与它的 `list_tags` 期望不自洽：{violations}"


def test_every_list_tags_case_is_on_the_catalog_side():
    """**类级元守卫**：凡期望 `list_tags` 的用例，问句都得落在全店目录这一侧。

    新增一条 `list_tags` 用例却问「某个客户有哪些标签」⇒ 当场红（不必等下一次真跑评测）。
    """
    in_scope = [(fname, case) for fname, case in _all_cases() if _expects_list_tags(case)]
    assert in_scope, (
        "没扫到任何期望 `list_tags` 的用例 ⇒ 本判据**空跑**（空结果不是通过）；"
        "若该 action 已从用例库消失，删掉本文件要连同这条一起处置")

    bad = []
    for fname, case in in_scope:
        inputs = case.get("user_inputs") or [""]
        for violation in list_tags_question_violations(str(inputs[0])):
            bad.append(f"{fname}::{case['id']} → {violation}")
    assert bad == [], "这些 `list_tags` 用例的问句答不上它们期望的取数面：\n" + "\n".join(bad)


def test_guard_goes_red_on_the_pre_fix_and_injected_questions():
    """**红证（注入式）**：改前形态与 #8124 的注入形态都必须逐条报出。

    这是「判据不是恒真断言」的证据；同时给**负控**（当前问句零违规，判据不是恒红噪音）。
    """
    # 红证 ① 改前形态（问某个客户自己的标签，且没有全店范围）
    pre_fix = "张三（手机号 13800138000）都有哪些标签？"
    got = list_tags_question_violations(pre_fix)
    assert len(got) == 1 and "全店范围" in got[0], got

    # 红证 ② issue #8124 通报的注入形态（把问句改回「这个客户有哪些标签」）
    injected = "这个客户（手机号 13800138000）都有哪些标签？"
    got = list_tags_question_violations(injected)
    assert len(got) == 2, f"注入形态没有被逐项报出（红证无判别力）：{got}"
    assert any("这个客户" in v for v in got), got

    # 负控：当前问句必须零违规（否则判据是「永远红」的噪音，同样没有判别力）
    _, case = _case("CU-003")
    assert list_tags_question_violations(str(case["user_inputs"][0])) == [], (
        "负控失败：当前 CU-003 的问句被判违规")


def test_the_scan_is_scoped_to_list_tags_cases():
    """射程自证：判据只裁 `list_tags` 用例 —— `detail` 用例（CU-004）**不在**射程内。

    否则这条守卫会退化成「禁一切客户指代」的一刀切，把问客户详情的用例一起判红。
    """
    in_scope = {case["id"] for _, case in _all_cases() if _expects_list_tags(case)}
    assert "CU-003" in in_scope, in_scope
    assert "CU-004" not in in_scope, (
        "CU-004 的期望是 `action=detail`，被当成 `list_tags` 用例 ⇒ 判据射程错了")
