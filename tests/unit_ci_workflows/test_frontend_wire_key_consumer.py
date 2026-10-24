# case_ids: UI-115
"""读面 wire 键 ⇄ 前端消费键的**跨端类级守卫**（issue #7319）。

## 病根

`OrderDetailResponse.workOrderKind` 用 `@JsonProperty("work_order_kind")` 下发（冻结 snake_case），
而前端 `Order` 类型 / `lib/processing-order.ts::workOrderKindOf()` 读的是 camelCase
`workOrderKind`。两处**各自都有单测**，但**没有判据把「下发的键」与「被读的键」放在一起比**：

- 后端 `OrderDetailWorkSignalReadFaceTest` 只判 `@JsonProperty` 存在；
- 前端 40+ 条单测全部用 camelCase 夹具喂组件；
- 全前端没有 snake→camel 响应变换（`src/lib/request.ts` 只做 token / 401）。

⇒ 线上恒读到 `undefined`：生成作业单入口对**所有**订单都不出现，前端两处发货守卫恒放行，
而两边 CI 全绿。这就是本文件要机械判红的那一类。

## 判据（每条都会红，且具名）

| # | 判据 | 改回坏形态时 |
|---|---|---|
| C1 | 登记面：`read_face_json_key_ledger.json` 的 `workOrderKind -> work_order_kind` + `frozen_keys` | 摘登记 / 改 wire 键 ⇒ 红 |
| C2 | DTO 真的用 `@JsonProperty("work_order_kind")` 序列化 | 摘注解 ⇒ 红 |
| C3 | 消费面：helper 读 `order.work_order_kind`，且**不再**出现 `order.workOrderKind` | 改回 camelCase ⇒ 红 |
| C4 | 类型面：`Order` 接口声明 `work_order_kind`，不再声明 `workOrderKind` | 改回 camelCase ⇒ 红 |
| C5 | 类级：`frontend/admin-web/src/**` 无 `order.workOrderKind` 读取形态 | 任何新页面再写一份 ⇒ 红 |

## 边界（如实登记）

- 本文件只判**静态形态**（键名 / 读取点）；「页面真的出按钮」由
  `frontend/admin-web/tests/unit/components/OrderDetailShipGuard.test.tsx`（wire 形状夹具）与
  `frontend/admin-web/tests/unit/lib/processing-order.test.ts` 的逐值判据承担；
- 不判其它 read-face 键（它们各自在 `test_read_face_json_key_guard.py` 的登记面里）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "tests/unit_ci_workflows/read_face_json_key_ledger.json"
DTO = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/dto/OrderDetailResponse.java"
HELPER = REPO_ROOT / "frontend/admin-web/src/lib/processing-order.ts"
TYPES = REPO_ROOT / "frontend/admin-web/src/types/index.ts"
FRONTEND_SRC = REPO_ROOT / "frontend/admin-web/src"

WIRE_KEY = "work_order_kind"


def test_ledger_registers_the_wire_key():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    entry = ledger["classes"]["com.migao.admin.dto.OrderDetailResponse"]
    assert entry["keys"]["workOrderKind"] == WIRE_KEY
    assert WIRE_KEY in entry["frozen_keys"]


def test_dto_serializes_the_same_key():
    source = DTO.read_text(encoding="utf-8")
    assert f'@JsonProperty("{WIRE_KEY}")' in source


def test_helper_reads_the_wire_key():
    source = HELPER.read_text(encoding="utf-8")
    assert f"order.{WIRE_KEY}" in source
    assert "order.workOrderKind" not in source


def test_order_type_declares_the_wire_key():
    source = TYPES.read_text(encoding="utf-8")
    assert f"{WIRE_KEY}?:" in source
    assert "workOrderKind?:" not in source


def test_no_order_camelcase_reads_anywhere_in_frontend():
    pattern = re.compile(r"\border\??\.\s*workOrderKind\b")
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in FRONTEND_SRC.rglob("*")
        if path.suffix in {".ts", ".tsx"} and pattern.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == []
