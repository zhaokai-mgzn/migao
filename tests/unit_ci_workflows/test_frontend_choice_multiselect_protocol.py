# case_ids: UI-043, CH-030
"""前端 ChoiceCard「多选协议接线」普查 —— issue #3947 的类级视角（让同类进不来）。

## 病根（一类缺陷，不是一个缺陷）

后端 `interact(multiSelect=true)` 在卡载荷里下发四个字段
（`backend/ai-agent-service/app/tools/interact.py`：`multiSelect` / `multiSelectSubmitPrefix` /
`multiSelectSubmitLabel` / `multiSelectSkipLabel`），AI 侧
`backend/ai-agent-service/app/graph/nodes.py` 的 `_card_accepts_answer` 正是按
`multiSelectSubmitPrefix` 前缀识别「这张卡的答卡轮」。**接线是三层，任一层断开都静默退回单选**：

| 层 | 断开的形态 | 断后的现象 |
|---|---|---|
| ① 类型声明 | `src/types/index.ts` 不声明这四个字段 | 组件拿不到字段 |
| ② store 透传 | SSE 回调里**白名单式**重建对象、漏字段 | 卡永远拿到 `undefined` ⇒ 点一个即锁卡（#3947 实测形态） |
| ③ 组件消费 | 组件不读 `multiSelect`，点击即 `onAction` | 卡题写着「可多选」而实际只能选一项 |

**三层可以同时「各自都是绿的」**：既有用例直接把 `multiSelect` 塞进组件 props 调用 ⇒
②断了也全绿（这正是 #3947 在真实小程序上存活的原因）。故本判据按**接线**普查，而不是按组件行为。

## 判据（四层，逐条带红证形态）

1. **普查集合冻结**：`frontend/*/src/components/cards/ChoiceCard.tsx` 的**现取**集合必须逐字等于
   本文件冻结的 `EXPECTED_PACKAGES` ⇒ 新前端包（未登记）即红、包改名/删除也红；
2. **每包三层接线齐全**：卡源码与 store 源码各引用**全部四个**字段；
3. **射程自证**：普查面 ≥2 个包（两边一起收窄 ⇒ 红）+ 每包 `tests/*choice-card*.test.tsx`
   里必须有引用 `multiSelect` 的判据（覆盖该协议的包内行为判据）；
4. **未覆盖面台账只许缩短**：`frontend_choice_multiselect_ledger.json` 条数 ≤ 冻结上限
   （现取 0），每条须有 `face`/`reason`/`owner`/`issue`，且已被覆盖的面不得留在台账里。

## 红证（实跑，任选其一）

```bash
# ① 删掉 store 里的 multiSelect 透传（②层断线）⇒ 判红
# ② 把 EXPECTED_PACKAGES 收窄成一个包 ⇒ 射程自证判红
python3 -m pytest tests/unit_ci_workflows/test_frontend_choice_multiselect_protocol.py -q
```

## 有意不做的（照实登记，不是「已覆盖」）

- **不**检查组件行为（勾选/提交/锁卡）—— 那由各包 `tests/*choice-card*.test.tsx` 的行为判据负责，
  本文件只保证「协议被接上」；
- **不**覆盖 `frontend/admin-web`（它用 vitest + `InteractiveMessage.tsx`，多选协议在本单之前就已
  完整实现，且其判据面另有 CI job）；
- 字面量匹配不认识「字段名拼接而成」或「从配置读」的写法（假绿方向，不会误伤）。
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
CARD_REL = "src/components/cards/ChoiceCard.tsx"
STORE_REL = "src/store/chatStore.ts"
CARD_GLOB = f"*/{CARD_REL}"

#: 冻结的普查集合（**两边一起收窄也逃不掉**：现取必须等于本常量，新包须连同本判据一起登记）
EXPECTED_PACKAGES = ("bmini-app", "mini-app")

#: 四个协议字段（`interact.py` 在 multiSelect=true 时**必然**下发；缺一个就是断线）
PROTOCOL_FIELDS = (
    "multiSelect",
    "multiSelectSubmitPrefix",
    "multiSelectSubmitLabel",
    "multiSelectSkipLabel",
)

LEDGER_PATH = Path(__file__).with_name("frontend_choice_multiselect_ledger.json")
#: 未覆盖面台账的**现取**上限（只许缩短）：两个包都已接线 ⇒ 0 条
UNCOVERED_FACE_CAP = 0


def _card_packages() -> list:
    """现取：带 ChoiceCard 的前端包名（相对 `frontend/`）。"""
    return sorted(p.relative_to(FRONTEND).parts[0] for p in FRONTEND.glob(CARD_GLOB))


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _ledger() -> dict:
    """台账（缺文件 ⇒ fail-closed 抛错，**不是**静默跳过）。"""
    if not LEDGER_PATH.exists():
        raise AssertionError(
            f"多选协议未覆盖面台账不存在：{LEDGER_PATH} —— 本判据 fail-closed（缺台账 = 覆盖面无人管）"
        )
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def test_census_matches_frozen_package_set():
    discovered = _card_packages()
    assert discovered == list(EXPECTED_PACKAGES), (
        "带 ChoiceCard 的前端包集合与冻结声明不一致（新包须连同本判据一起登记，"
        f"不得静默收窄或扩张）：现取={discovered} 冻结={list(EXPECTED_PACKAGES)}"
    )


def test_census_covers_both_personas():
    discovered = _card_packages()
    assert len(discovered) >= 2, (
        f"ChoiceCard 普查面只剩 {discovered} —— 射程被收窄到单点（C 端/B 端同族缺陷会漏掉一侧）"
    )


def test_each_card_consumes_full_multiselect_protocol():
    missing = {}
    for pkg in EXPECTED_PACKAGES:
        src = _read(f"frontend/{pkg}/{CARD_REL}")
        absent = [f for f in PROTOCOL_FIELDS if f not in src]
        if absent:
            missing[pkg] = absent
    assert not missing, (
        "ChoiceCard 未消费完整多选协议（点一个即锁卡 = 多选意图被吞）："
        f"{missing} —— 见 issue #3947"
    )


def test_each_store_passes_multiselect_through():
    missing = {}
    for pkg in EXPECTED_PACKAGES:
        src = _read(f"frontend/{pkg}/{STORE_REL}")
        absent = [f for f in PROTOCOL_FIELDS if f not in src]
        if absent:
            missing[pkg] = absent
    assert not missing, (
        "SSE onInteractive 的字段白名单吞掉了多选字段（卡永远拿到 undefined ⇒ 静默退回单选）："
        f"{missing} —— 见 issue #3947"
    )


def test_each_package_has_protocol_judgement():
    missing = {}
    for pkg in EXPECTED_PACKAGES:
        files = sorted((REPO_ROOT / "frontend" / pkg / "tests").glob("*choice-card*.test.tsx"))
        hit = [p.name for p in files if "multiSelect" in p.read_text(encoding="utf-8")]
        if not hit:
            missing[pkg] = [p.name for p in files]
    assert not missing, (
        f"包内没有引用 multiSelect 的判据（协议无人守）：{missing}"
    )


def test_uncovered_ledger_only_shrinks_without_stale_entries():
    faces = _ledger().get("uncovered_faces", [])
    assert isinstance(faces, list), f"台账 uncovered_faces 必须是数组：{faces}"
    assert len(faces) <= UNCOVERED_FACE_CAP, (
        f"未覆盖面台账只许缩短：现取 {len(faces)} 条 > 冻结上限 {UNCOVERED_FACE_CAP} 条"
        f"（新增未覆盖面须同时抬上限并在 PR body 登记理由）：{faces}"
    )
    for entry in faces:
        for key in ("face", "reason", "owner", "issue"):
            assert str(entry.get(key, "")).strip(), f"台账条目缺 {key}：{entry}"
        assert str(entry["face"]) not in EXPECTED_PACKAGES, (
            f"台账条目 {entry['face']} 其实已接线 ⇒ 陈旧，应删除"
        )