"""契约快照 ↔ admin-api 响应契约 的**单一登记面**（issue #5474）。

## 这个模块解决什么

`tests/contracts/snapshots/*.json` 是**线上响应的抓取缓存**：CI 里没有 admin-api，
`tests/contracts/conftest.py::_fetch` 抓不到就走回退，于是**快照就是判据的输入**。
2026-07-19 抓的那一批里，6 个在同族契约变更后**没人重抓**（`sortOrder→sort` 重命名、
`craftHint` 新增……），而**没有任何东西变红**——因为：
  ① 没有任何判据把「契约变更」与「快照刷新」连起来；
  ② 唯一沾边的 `test_contract_api.py` 在 CI 里**拿快照判快照**（自指，永不会红）。

本模块提供那份缺失的「当前契约」读数：**从 Java 源码解析响应 DTO 的线上键名**
（不维护第二份清单，与 `tests/test_tool_field_name_contract.py` 同口径；
类定位与继承链解析**直接复用**该文件，不复制第二份）。

## 口径（三条，都是刻意的）

1. **线上键名 = `@JsonProperty` 值，否则字段名**。注解**字段上 / getter 上都要认** ——
   `CustomerProfile` 的 `rScore/fScore/mScore` 就钉在 getter 上（issue #5459），
   只读字段会把它们误判成「契约里没有的键」（假红）。
2. **射程 = 条目（item）一层的键**，不递归进嵌套子树。`OrderListResponse.processingInfo`
   是 `Object`（自由形态的销售信息快照）、`CustomerProfile.tags/customFields` 同理 ⇒
   嵌套键**本来就没有静态契约**，强行比对只会产出假红。该边界在测试里显式登记。
3. **未登记的快照文件 ⇒ 红**（新增端点抓取必须同步登记，否则新面自动脱离射程）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from tests import test_tool_field_name_contract as _sibling

_REPO_ROOT = Path(__file__).resolve().parents[3]
_JAVA_MAIN = _REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "contracts" / "snapshots"
FINGERPRINT_PATH = Path(__file__).resolve().parent / "contracts" / "snapshot-contract-fingerprints.json"

#: 实例字段（不锚行首：`DashboardController.DashboardStatsResponse` 有**一行两个字段**的形态）。
#: 类型里用 `[ \t]` 而非 `\s`，避免跨行把下一个字段并进类型。
_FIELD_RE = re.compile(
    r"private[ \t]+(?!static\b)(?!final\b)"
    r"([A-Za-z_][\w.<>,\[\]]*(?:[ \t]+[A-Za-z_][\w.<>,\[\]]*)*)[ \t]+(\w+)[ \t]*(?:=[^;]*)?;"
)

#: `@JsonProperty("x")` 后紧接**字段声明**（`private Integer sortOrder;`）或**getter**
#: （`public Integer getRScore() { return rScore; }`）。getter 形态靠方法体 `return <field>;`
#: 回指字段 —— 不能按 JavaBeans 去首字母推，那正是 `getRScore()` → `rscore` 折叠的成因。
_JSONPROP_RE = re.compile(
    r'@JsonProperty\("([^"]+)"\)[ \t\r\n]*'
    r"(?:public|private|protected)?[ \t]*[\w.<>,\[\]]+[ \t]+(\w+)[ \t]*"
    r"(\(\s*\)\s*\{([^{}]*)\}|;)",
    re.DOTALL,
)
_RETURN_FIELD_RE = re.compile(r"return[ \t]+(\w+)[ \t]*;")

#: **计算型 getter**（无后备字段，Jackson 照样序列化）。`ProductResponse.getPrice()`
#: 就是这种形态（`price` 与 `basePrice` 同值，快照里两键都在）——
#: 只读字段的解析器会把它判成「契约里没有的键」= 假红。
_GETTER_RE = re.compile(r"public[ \t]+[\w.<>,\[\]]+[ \t]+(get[A-Z]\w*)[ \t]*\([ \t]*\)")


def _bean_property(getter: str) -> str:
    """`getPrice` → `price`；`getRScore` → `RScore`（Jackson/JavaBeans：前两字母都大写时**不去首字母**）。

    后者正是 `CustomerProfile` 需要 getter 上 `@JsonProperty` 显式钉名的原因（issue #5459）；
    带注解的 getter 由 `_JSONPROP_RE` 处理，本函数只兜**没有注解**的计算型 getter。
    """
    name = getter[3:]
    if len(name) >= 2 and name[0].isupper() and name[1].isupper():
        return name
    return name[:1].lower() + name[1:]


@dataclass(frozen=True)
class SnapshotContract:
    """一个快照的契约登记：条目 DTO + 是否是分页包装（`PageResponse` 的键也算契约）。"""

    item_dto: str
    page: bool = True
    #: 条目内**同族的子条目**字段（`children` 是递归的 `CategoryResponse`）
    nested: str | None = None


#: 端点快照 ↔ 响应 DTO。与 `admin-api` 的 controller 返回类型逐一对上：
#: `ApiResponse<PageResponse<X>>`（分页）/ `ApiResponse<List<X>>`（分类树）/ `ApiResponse<X>`（看板）。
REGISTRY: dict[str, SnapshotContract] = {
    "api_admin_products": SnapshotContract("ProductResponse"),
    "api_admin_orders": SnapshotContract("OrderListResponse"),
    "api_admin_customers": SnapshotContract("CustomerProfile"),
    "api_admin_after-sales": SnapshotContract("AfterSalesListResponse"),
    "api_admin_processing-items": SnapshotContract("ProcessingItemResponse"),
    "api_admin_categories_tree": SnapshotContract("CategoryResponse", page=False, nested="children"),
    "api_admin_dashboard_stats": SnapshotContract("DashboardStatsResponse", page=False),
}


@dataclass(frozen=True)
class WireKeys:
    """一个 DTO 的线上契约读数。"""

    dto: str
    #: 声明了 `@JsonProperty` 改名的字段：Java 字段名 → 线上键名（诊断用）
    renames: dict[str, str]
    keys: frozenset[str]
    #: **计算型 getter** 贡献的键（无后备字段，`ProductResponse.getPrice` 这类）
    computed: frozenset[str]


def declared_wire_keys(dto: str) -> WireKeys:
    """解析 `dto` 的线上键名集合（本类 ∪ `extends` 链上的父类）。

    类定位 / 继承链 / 父类越界判定**全部复用** `tests/test_tool_field_name_contract.py`
    （同一份 `_source_of_receiver_type` / `_superclass_of`）：本仓库已踩过
    「两套门禁各管一摊、口径漂移」的坑，不复制第二份解析器。
    """
    renames: dict[str, str] = {}
    field_names: set[str] = set()
    computed: set[str] = set()
    seen: list[str] = []
    current: str | None = dto
    while current is not None:
        assert current not in seen, f"{dto} 的 extends 链成环：{' → '.join([*seen, current])}"
        seen.append(current)
        src = _sibling._source_of_receiver_type(current, _JAVA_MAIN)
        assert src is not None, (
            f"响应 DTO {current} 在 admin-api Java 源码树里找不到（既无 {current}.java，"
            f"也无同名内部类）—— {current} 疑似改名/删除/移出仓库；"
            f"REGISTRY 的契约登记已失效，请同步更新 {__file__} 的 REGISTRY"
        )
        field_names |= {m.group(2) for m in _FIELD_RE.finditer(src)}
        annotated_getters: set[str] = set()
        for wire, ident, kind, body in _JSONPROP_RE.findall(src):
            if kind == ";":
                renames[ident] = wire
            else:
                annotated_getters.add(ident)
                returned = _RETURN_FIELD_RE.search(body or "")
                if returned:
                    renames[returned.group(1)] = wire
        for gm in _GETTER_RE.finditer(src):
            getter = gm.group(1)
            if getter == "getClass" or getter in annotated_getters:
                continue
            if re.search(r"@JsonIgnore\b", src[max(0, gm.start() - 200) : gm.start()]):
                continue
            computed.add(_bean_property(getter))
        current = _sibling._superclass_of(src, current)
    assert field_names, f"{dto} 未解析到任何字段（正则需适配 Java 形态；来源：{' → '.join(seen)}）"
    keys = frozenset(computed | {renames.get(name, name) for name in field_names})
    return WireKeys(dto=dto, renames=renames, keys=keys, computed=frozenset(computed))


def contract_keys(snapshot_name: str) -> frozenset[str]:
    """该快照对应的**当前**契约键集：条目 DTO ∪（分页时）`PageResponse`。"""
    spec = REGISTRY[snapshot_name]
    keys = set(declared_wire_keys(spec.item_dto).keys)
    if spec.page:
        keys |= declared_wire_keys("PageResponse").keys
    return frozenset(keys)


def current_fingerprint() -> dict[str, list[str]]:
    """全量契约指纹：快照名 → 排序后的契约键列表（**与抓取时刻无关，每跑一次现算**）。"""
    return {name: sorted(contract_keys(name)) for name in sorted(REGISTRY)}


def observed_item_keys(snapshot_name: str) -> set[str]:
    """快照里**条目一层**实际出现的键（union 过全部条目）。

    分页端点取 `data.items[]`；分类树取 `data` 列表并**递归** `children`
    （子分类是同一个 `CategoryResponse`，同族键必须一起看）；看板取 `data` 本身。
    """
    spec = REGISTRY[snapshot_name]
    data = json.loads((SNAPSHOT_DIR / f"{snapshot_name}.json").read_text(encoding="utf-8")).get("data")
    found: set[str] = set()

    def collect(node: object) -> None:
        if not isinstance(node, dict):
            return
        found.update(node.keys())
        if spec.nested:
            children = node.get(spec.nested)
            if isinstance(children, list):
                for child in children:
                    collect(child)

    if spec.page:
        items = data.get("items") if isinstance(data, dict) else None
        for item in items or []:
            collect(item)
    elif isinstance(data, list):
        for item in data:
            collect(item)
    else:
        collect(data)
    return found


def observed_contract_keys(snapshot_name: str) -> set[str]:
    """快照条目一层的键，**去掉分页包装键**后的形态（分类树/看板的条目就是 data 本身）。

    分页端点里 `data.items[]` 的键不含 `total/page/size/items`，因此这里不需要做减法；
    本函数只是给调用方一个语义命名的入口，避免测试里重复判断分页与否。
    """
    return observed_item_keys(snapshot_name)


def snapshot_files() -> list[str]:
    """磁盘上实际存在的快照名（不含 `.json`），按名排序。"""
    return sorted(p.stem for p in SNAPSHOT_DIR.glob("*.json"))


def write_fingerprint(captured_at: str | None = None) -> dict:
    """把**当前契约指纹**落到 sidecar —— **只在真实抓取成功时调用**。

    语义：这份读数回答「**这次抓取对应的是哪一版契约**」。它不描述抓到的数据，
    只描述**契约本身**（从 Java 源码现算），因此与「钉死某次抓取的字节」无关：
    数据天天在变不算过期，**契约键集变了才算**。
    """
    from datetime import datetime, timedelta, timezone

    stamp = captured_at or datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    payload = {
        "_note": (
            "抓取时刻的 admin-api 响应契约指纹（由 tests/contracts/conftest.py 在真实抓取成功时写出）。"
            "键集现算自 Java 源码 —— 数据变化不会让它过期，契约键集变化才会。"
            "判定见 tests/test_contract_snapshot_freshness.py；刷新 = 重跑一次真实抓取。"
        ),
        "captured_at": stamp,
        "contracts": current_fingerprint(),
    }
    FINGERPRINT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def read_fingerprint() -> dict | None:
    """读 sidecar；不存在返回 None（调用方必须显式处理「无指纹」，不得当绿）。"""
    if not FINGERPRINT_PATH.exists():
        return None
    return json.loads(FINGERPRINT_PATH.read_text(encoding="utf-8"))


RECAPTURE_COMMAND = (
    "cd backend/admin-api && SERVER_PORT=8081 ./mvnw spring-boot:run   # 8081 = conftest 写死的 ADMIN_API\n"
    "cd backend/ai-agent-service && .venv/bin/python -m pytest tests/contracts/ -v -s --no-cov"
)

#: 嵌套子树不在射程内（无静态契约可依）。显式登记，避免「看起来覆盖了其实没有」。
UNCHECKED_NESTED_SUBTREES = (
    "OrderListResponse.processingInfo（Object：销售信息快照，键由运行时数据决定）",
    "CustomerProfile.tags / customFields / craftProfile（Object）",
    "ProcessingItemResponse.options / values / default（Object / List<Object>）",
    "DashboardStatsResponse —— 全部字段均为原始类型，无嵌套",
)