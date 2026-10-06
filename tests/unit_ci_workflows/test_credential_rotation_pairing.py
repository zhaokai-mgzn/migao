# case_ids: MC-085
"""类级元守卫（issue #6432 铁律 8）：**「只能建、不能救」的口令死角**进不来。

病（#6432）：管理员在「工人档案」里建号时能设 PIN，但**建完就再也拿不到** ——
PIN 落库是 BCrypt 哈希（不可逆），列表与视图面又显式脱敏 ⇒ 工人忘记 PIN 时管理员
**无路可走**（只能删号重建，而重建会把报工记到两个身份上、两个身份各拿一份工资账）。
同族的「员工」侧早就有 `resetPassword`，工人侧漏了 ⇒ 用户报障「管理员查不到工人的 PIN」。
这就是本判据要拦的形态：**新增一个「建号即设口令」的能力面，必须同时给它一条重置出口**。

判据（每条都会**具名**报出是哪个 client、缺哪个方法）：
  1. **零命中 ⇒ 红**（fail-closed）：扫描面一个「建号即设口令」的能力面都找不到
     ⇒ 判据自己失效了（选择器漂了），不许静默绿。
  2. **未配对即红**：某 client 暴露了 `create*`（其入参类型含 `password` / `pin` 字段）却
     **没有**同族的 `reset|change|update` + `Password|Pin` 方法，且不在豁免台账里 ⇒ 红。
  3. **陈旧即红 / 超预算即红**（台账只许缩短）：豁免条目对应的 client 不存在、或它其实已经配对了
     （陈留即红）、或条目数 > `frozen_max_entries` ⇒ 红。
  4. **判别力自证**：四种坏形态在**内存语料**上各自判红，另有一条**对照** ——
     配对语料 + 空台账 ⇒ **不红**（判据不许被自己的文案喂红）。

⚠️ 边界（如实登记，§19.1）：判据只认 `frontend/admin-web/src/lib/api.ts` 的**对象字面量 client**
（`export const X = { … }`，顶格 `}` 收口）与 `frontend/admin-web/src/types/index.ts` 的**顶层
interface 字段**；经变量间接构造的请求体、行内 `{ pin }` 字面量、其它端（小程序 / H5）的 api 封装
**不在射程内**；也判不了「重置口有没有接权限码 / 有没有接 UI」（那是 `@RequirePermission` 与页面测试的事）。
**本判据不为存量条目的安全性背书**，只裁新增。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_PATH = REPO_ROOT / "frontend" / "admin-web" / "src" / "lib" / "api.ts"
TYPES_PATH = REPO_ROOT / "frontend" / "admin-web" / "src" / "types" / "index.ts"
LEDGER_PATH = Path(__file__).resolve().parent / "credential_rotation_pairing_ledger.json"

# 「建号即设口令」的凭据字段名（命中任一即算：员工侧 password / 工人侧 pin）
CREDENTIAL_FIELDS = frozenset({"password", "pin"})
# 重置面：resetPassword / resetWorkerPin / changePassword / updatePassword …
ROTATION_RE = re.compile(r"^(?:reset|change|update)[A-Za-z]*(?:Password|Pin)$")
# 建号面：createEmployee / createWorker / create…
CREATE_PREFIX = "create"


def parse_interface_fields(types_src: str) -> dict[str, set[str]]:
    """`export interface X { … }` ⇒ {X: {字段名}}（按行做花括号配对，不用贪婪正则）。"""
    fields: dict[str, set[str]] = {}
    current: str | None = None
    for line in types_src.splitlines():
        if current is None:
            m = re.match(r"export interface (\w+) \{", line)
            if m:
                current = m.group(1)
                fields[current] = set()
            continue
        if line.startswith("}"):
            current = None
            continue
        m = re.match(r"\s*(\w+)\??\s*:", line)
        if m:
            fields[current].add(m.group(1))
    return fields


def parse_clients(api_src: str) -> dict[str, dict[str, str]]:
    """`export const X = { … }` ⇒ {X: {方法名: 签名}}；顶格 `}` 收口，块外内容不进面。"""
    clients: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in api_src.splitlines():
        if current is None:
            m = re.match(r"export const (\w+) = \{", line)
            if m:
                current = m.group(1)
                clients[current] = {}
            continue
        if line.startswith("}"):
            current = None
            continue
        m = re.match(r"\s+(?:async )?(\w+):\s*\((.*)", line)
        if m:
            clients[current][m.group(1)] = m.group(2)
    return clients


def credential_creators(client: dict[str, str], fields: dict[str, set[str]]) -> list[str]:
    """该 client 里「建号即设口令」的方法名（入参类型含 password / pin 字段）。"""
    out: list[str] = []
    for name, signature in client.items():
        if not name.startswith(CREATE_PREFIX):
            continue
        for type_name in re.findall(r":\s*([A-Z]\w*)", signature):
            if fields.get(type_name, set()) & CREDENTIAL_FIELDS:
                out.append(name)
                break
    return out


def problems(clients: dict[str, dict[str, str]], fields: dict[str, set[str]], ledger: dict) -> list[str]:
    """纯函数：语料 + 台账 → 问题清单（空 = 通过）。所有分支都**具名**。"""
    out: list[str] = []

    budget = ledger.get("frozen_max_entries")
    if not isinstance(budget, int):
        out.append("台账缺 `frozen_max_entries`（冻结上限）—— 判据无法判「只许缩短」⇒ 红")

    creators: dict[str, list[str]] = {
        name: found
        for name, client in clients.items()
        if (found := credential_creators(client, fields))
    }
    if not creators:
        out.append(
            "零命中（fail-closed）：扫描面找不到任何「建号即设口令」的 client"
            " —— 选择器漂了 / api.ts 结构变了 ⇒ 判据自己失效，不许静默绿"
        )

    unpaired: dict[str, list[str]] = {}
    for name, found in creators.items():
        has_rotation = any(ROTATION_RE.match(method) for method in clients[name])
        if not has_rotation:
            unpaired[name] = found

    entries = ledger.get("entries", [])
    if isinstance(budget, int) and len(entries) > budget:
        out.append(f"台账超预算：{len(entries)} 条 > frozen_max_entries={budget} ⇒ 红（只许缩短）")

    exempt: set[str] = set()
    for entry in entries:
        name = entry.get("client", "")
        exempt.add(name)
        if not entry.get("reason", "").strip():
            out.append(f"台账条目缺 `reason`（豁免必须写明理由）：{name or '<空 client>'}")
        if name not in clients:
            out.append(f"陈旧台账条目：client {name!r} 不在扫描面（被删 / 改名）⇒ 请删条目")
            continue
        if name not in unpaired:
            out.append(
                f"陈旧台账条目：client {name!r} 其实是**配对**的（已有重置面）⇒ 请删条目"
            )

    for name, found in unpaired.items():
        if name in exempt:
            continue
        out.append(
            f"未配对：{name} 暴露了建号即设口令的方法 {found}，却没有任何 "
            "reset/change/update + Password/Pin 方法 ⇒ 管理员建完就拿不到口令"
            "（工人忘记只能删号重建）。补一条重置出口，或在台账里登记豁免 + 理由"
        )
    return out


def load() -> tuple[dict[str, dict[str, str]], dict[str, set[str]], dict]:
    clients = parse_clients(API_PATH.read_text(encoding="utf-8"))
    fields = parse_interface_fields(TYPES_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return clients, fields, ledger


def test_real_repo_passes() -> None:
    clients, fields, ledger = load()
    assert problems(clients, fields, ledger) == []


def test_real_repo_actually_sees_the_pairing() -> None:
    """对照读数（防「选择器漂了还能绿」）：工人与员工两条口令面都必须被扫出来且配对。"""
    clients, fields, _ = load()
    creators = {name: credential_creators(client, fields) for name, client in clients.items()}
    creators = {name: found for name, found in creators.items() if found}

    assert "createWorker" in creators.get("workerApi", []), "工人建号面必须被扫出来（issue #6432 的病灶）"
    assert "createEmployee" in creators.get("employeeApi", []), "员工建号面必须被扫出来"
    assert any(ROTATION_RE.match(m) for m in clients["workerApi"]), "工人侧必须存在重置面"
    assert any(ROTATION_RE.match(m) for m in clients["employeeApi"]), "员工侧必须存在重置面"


# ---------- 判别力自证（内存语料；判据本身退化成绿 ⇒ 这里红） ----------

_API = """
export const workerApi = {
  createWorker: (data: WorkerFormData) =>
    request.post('/api/admin/workers', data),
%(worker_rotation)s}

export const employeeApi = {
  createEmployee: (data: EmployeeFormData) =>
    request.post('/api/admin/users', data),
  resetPassword: (id: string, data: ResetPasswordParams) =>
    request.put(`/api/admin/users/${id}/reset-password`, data),
}
"""
_TYPES = """
export interface WorkerFormData {
  workerNo: string
  pin: string
}

export interface EmployeeFormData {
  name: string
  password?: string
}
"""
_ROTATION = """
  resetWorkerPin: (id: string, pin?: string) =>
    request.put(`/api/admin/workers/${id}/pin`, pin ? { pin } : {}),
"""


def _corpus(worker_rotation: str = _ROTATION):
    return parse_clients(_API % {"worker_rotation": worker_rotation}), parse_interface_fields(_TYPES)


def _empty_ledger() -> dict:
    return {"frozen_max_entries": 0, "entries": []}


def test_discriminates_unpaired_client() -> None:
    """坏形态 ①：工人侧没有重置面 ⇒ 具名红（#6432 的改前形态）。"""
    clients, fields = _corpus(worker_rotation="")
    found = problems(clients, fields, _empty_ledger())
    assert any("workerApi" in p and "未配对" in p for p in found), found


def test_discriminates_stale_ledger_entry() -> None:
    """坏形态 ②：台账给一个**已经配对**的 client 盖章 ⇒ 陈旧即红。"""
    clients, fields = _corpus()
    ledger = {"frozen_max_entries": 1, "entries": [{"client": "workerApi", "reason": "占位"}]}
    found = problems(clients, fields, ledger)
    assert any("陈旧" in p for p in found), found


def test_discriminates_ledger_budget() -> None:
    """坏形态 ③：台账超预算 ⇒ 红（只许缩短）。"""
    clients, fields = _corpus(worker_rotation="")
    ledger = {
        "frozen_max_entries": 0,
        "entries": [{"client": "workerApi", "reason": "存量缺口"}],
    }
    found = problems(clients, fields, ledger)
    assert any("超预算" in p for p in found), found


def test_discriminates_empty_corpus() -> None:
    """坏形态 ④：语料空 ⇒ 零命中即红（fail-closed，不许静默绿）。"""
    found = problems({}, {}, _empty_ledger())
    assert any("零命中" in p for p in found), found


def test_paired_corpus_is_green() -> None:
    """对照：配对语料 + 空台账 ⇒ **不红**（判据不许被自己的文案喂红）。"""
    clients, fields = _corpus()
    assert problems(clients, fields, _empty_ledger()) == []


def test_ledger_is_wellformed_and_shrink_only() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert ledger["frozen_max_entries"] == 0
    assert ledger["entries"] == []
