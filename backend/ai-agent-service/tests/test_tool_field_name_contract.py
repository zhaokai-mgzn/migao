"""
工具下发字段名 ↔ admin-api 请求类型字段契约（跨服务写请求边界）
# case_ids: AS-004, CU-004, CU-008

① 契约层（docs/testing/interaction-verification.md「① 契约层」）：确定性、零 LLM、
mock 客户端 + 静态解析 Java 源码 —— 拦「工具下发的字段名与 API 接收类型字段不一致」
这类**跨端字段丢失**缺陷（纯单测和 Gate 都抓不到：HTTP 200、无异常、数据不落库）。

背景（两类同源缺陷，本文件是该层的落地）：
- issue #3540（首个登记域）：ai-agent 下发 `{"status", "reason"}`，admin-api
  `dto/AfterSalesStatusUpdateRequest.java` 只声明 `status`/`remark`；
- issue #3551（本 PR 新增域）：ai-agent 下发 `{"name": ...}`，admin-api
  `entity/CustomerProfile.java` 没有 `name` 列（姓名存 `wechatNickname`）。
  两例的共同机制：Spring Boot 默认 ObjectMapper 忽略未知属性
  （FAIL_ON_UNKNOWN_PROPERTIES=false）→ 请求 200、部分字段落库、信息静默丢失、无任何报错。

② 服务层（本文件 v2 新增，issue #4115）：字段名 ⊆ 接收类型**还不够** ——
「字段名对得上、但服务层不落库」是同族的第二形态，且更隐蔽：
issue #4115 的 `CustomerService.updateCustomer` 用**非空拷贝白名单**逐个 `setXxx`，
`craftMode/craftProfile/defaultLogisticsType/defaultLogisticsCompany` 既在实体里声明、
又被工具列入可写字段并下发，**却不在白名单里** ⇒ `updateById(existing)` 落下旧值 ⇒
HTTP 200 + 数据静默丢失 + 工具回报「客户档案已更新：craftMode」。
只校验「key ⊆ 接收类型字段」抓不到它（**四个断言全绿，数据全丢**）。
故本文件现在**每条写契约都必须声明「服务层怎么算落库」**（`persist_source` + `persist_target`，
无默认值：漏填即报错，不是静默跳过），并断言 payload key ∈ 该服务方法真正落库的字段集合。

规则（新增/修改写工具时必须满足）：
  工具写请求 body 的每个 key，都必须能在目标的 Java **接收类型**中解析到同名字段
  （「接收类型字段」= 本类 ∪ `extends` 链上各级父类的字段，issue #4166）；
  **且该 key 必须属于目标服务方法真正落库的字段集合**（见 ②）；
  业务内容值必须落到该类型已声明字段上（禁止「多发一个别名字段」凑数，避免双写分叉）。
  改字段名时两端一起改（Java 类型 / 工具 payload），只改一端本测试即红。

## 如何新增一个域（增量登记步骤）

1. 在 `REGISTRY` 追加一条 `WriteContract`，填齐：
   - **工具/调用点**：`tool_module` + `client_method` + `endpoint` + `tool_kwargs`
     （`tool_kwargs` 要带上**会被下发**的业务内容字段，不是随便一个成功路径的入参）；
   - **接收类型**：`receiver_type` = admin-api 的请求 DTO **或**实体类名
     （Java 源码是「接收端可读键」的单一事实源，不维护第二份字段清单）；
   - **接收端可读键来源**：`receiver_key_source`（当前仅 `java-source`：静态解析
     `backend/admin-api/.../{receiver_type}.java` 的实例字段）；
   - **服务层落库判据（必填）**：`persist_source` ∈ `PERSIST_KEY_SOURCES`
     + `persist_target` = `"<ServiceClass>#<method>"`（该端点的服务实现方法）。
     这两项**无默认值**：新增写契约必须显式回答「服务层凭什么算落库」，
     漏填 ⇒ 查表失败显式报错；
   - **未映射键白名单**：`unmapped_key_allowlist` = {键: "理由（归属）"}，默认空。
     只有接收端确实尚未声明、但业务上合法的键才登记，并写清理由与归属人；
     空挂/过期的白名单会被本文件判红（逃逸口必须真实且最小）；
   - **业务内容值**：`content_value` = 必须落在接收端已声明字段上的那个值。
2. 若工具侧字段名与接收端不一致（如 `name` vs `wechatNickname`），**改工具侧下发 canonical 字段名**，
   不要新增别名/双写（口径见 #3540/#3545：别名会让实体绑定的其它未知键继续静默丢弃）。
3. 跑本文件即验证；不需要真实 LLM、不需要起服务（§16.1 的 L0/L1 层）。
"""
from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import BaseTool

_REPO_ROOT = Path(__file__).resolve().parents[3]
_JAVA_MAIN = _REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"

# 请求 DTO 实例字段：`private String remark;` / `private List<String> images;`
# / `private Integer page = 1;`（带初值的字段同样是 Jackson 可绑定字段，漏解析会误报「键被丢弃」）
# （排除 static 常量与 final 常量 / serialVersionUID）
_FIELD_RE = re.compile(
    r"^\s*private\s+(?!static\b)(?!final\b)[\w.<>,\[\]\s]+\s+(\w+)\s*(?:=[^;]*)?;", re.MULTILINE
)


def _balanced_brace_block(src: str, open_idx: int) -> str:
    """取 `{` 开始的整段配平代码块（内部类解析用）。"""
    depth = 0
    for i in range(open_idx, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx : i + 1]
    return src[open_idx:]


def _source_of_receiver_type(class_name: str, java_root: Path = _JAVA_MAIN) -> str | None:
    """定位接收类型的源码（**含类声明头**）：优先同名文件，其次**内部类**（无独立文件）。

    内部类形态真实存在：`SettingsController.java:323` 的
    `public static class ChangePasswordRequest` 就是 `PUT /api/admin/settings/password`
    的 `@RequestBody` 类型 —— 只按文件名找会解析不到（跨模块门禁曾因此报「接收类型无法解析」）。
    返回文本包含 `class X extends Y {` 的声明头：继承解析要从头部读 `extends`
    （只返回 `{...}` 类体会让父类静默消失 = 解析器退化成「无父类」）。
    """
    matches = sorted(java_root.rglob(f"{class_name}.java"))
    if matches:
        return matches[0].read_text(encoding="utf-8")
    pat = re.compile(rf"\b(?:class|record)\s+{re.escape(class_name)}\b[^{{;]*\{{")
    for path in sorted(java_root.rglob("*.java")):
        src = path.read_text(encoding="utf-8")
        m = pat.search(src)
        if m:
            brace = src.index("{", m.start())
            return src[m.start() : brace] + _balanced_brace_block(src, brace)
    return None


def _superclass_of(src: str, class_name: str) -> str | None:
    """取类声明里 `extends` 的父类名（无 `extends` / `record` → None）。

    只看类**声明头**（类名 → 类体 `{`），并先吃掉类自身的类型参数表：
    `class Repo<T extends Base> extends Impl` 的超类是 `Impl`，类型参数上界 `Base` 不是父类
    （吃错了会把无关类型的字段并进来 = 门禁被放宽）。
    """
    m = re.search(
        rf"\bclass\s+{re.escape(class_name)}\s*(?:<[^{{;]*?>)?\s*([^{{]*?)\{{", src, re.DOTALL
    )
    if not m:
        return None
    head = m.group(1).split("implements", 1)[0]  # 超类子句在 implements 之前
    em = re.search(r"\bextends\s+([\w.]+)", head)
    return em.group(1) if em else None


# java.lang 由编译器**隐式导入**（裸名父类不会出现在 import 里），故这几个语言级根类
# 可以在「仓库内无源码 + 无 import」的情况下合法出现。**这不是本仓库的类清单** ——
# com.migao 的父类一律按 Java 源码树解析（禁止在此登记任何本仓库类型）。
_IMPLICIT_JAVA_LANG_PARENTS = frozenset(
    {"Object", "Throwable", "Exception", "RuntimeException", "Error"}
)


def _is_external_parent(child_src: str, parent: str) -> bool:
    """父类是否来自仓库外（JDK / 第三方）—— 仓库外父类没有本仓库字段可并，链条就此终止。

    判据只用 Java 源码里**读得到的来源声明**（不维护第二份类型清单）：
    ① 全限定名且非 `com.migao`（`extends java.util.AbstractMap`）；
    ② 显式 `import <非 com.migao 包>.<Parent>;`；
    ③ 上述「java.lang 隐式导入」的语言级根类（`extends Object`，源码里没有 import 可依据）。
    三条都判不出 ⇒ 视为「本仓库类型被改名/删除/移出」→ 调用方**响亮报错**（禁止静默降级）。
    """
    if "." in parent and not parent.startswith("com.migao"):
        return True
    simple = parent.rsplit(".", 1)[-1]
    if re.search(
        rf"^\s*import\s+(?!com\.migao)[\w.]*\.{re.escape(simple)}\s*;", child_src, re.MULTILINE
    ):
        return True
    return simple in _IMPLICIT_JAVA_LANG_PARENTS


@lru_cache(maxsize=None)
def _receiver_fields_from_java(
    class_name: str, java_root: Path = _JAVA_MAIN
) -> frozenset[str]:
    """解析 admin-api 接收类型（请求 DTO / 实体 / 内部类）的实例字段名。

    单一事实源 = Java 源码，不维护第二份清单。**字段 = 本类 ∪ `extends` 链上各级父类**
    （issue #4166）：父类字段同样是 Jackson 可绑定字段 —— #4162 把 `AgentOrderCreateRequest`
    收敛成 `extends OrderCreateRequest`（自身只剩 `clientRequestId`）后，只读子类源码的解析器
    把父类的 `customerName`/`items`/… 全判成「接收端读不到」→ 门禁假红（运行期并无数据丢失）。
    只剩子类字段 = 断言实现窄于它声称的契约（"接收端可读键"在 Java 语义里含继承字段）。

    继承链**有界且防环**：每一跳都必须是**不同的**可解析类，重复出现即环 ⇒ 显式报错
    （不会挂死）；父类解析不到时，仓库外类型（`_is_external_parent`）终止链条，其余
    按本文件既有口径**响亮报错**（改名/删除静默降级 = 父类字段凭空消失，本判据就再也
    咬不住「父类字段被删」这类真缺陷）。

    `java_root` 只为夹具注入（负控在临时 Java 树上行使同一份生产判据），生产路径用默认值。
    """
    if not java_root.is_dir():
        pytest.skip(f"admin-api Java 源码不存在（{java_root}），无法校验跨服务字段契约")
    fields: set[str] = set()
    seen: list[str] = []
    current: str | None = class_name
    child_src = ""
    while current is not None:
        assert current not in seen, (
            f"{class_name} 的 extends 链成环：{' → '.join([*seen, current])} —— "
            f"Java 不允许循环继承；继承解析必须在此终止（否则门禁挂死）"
        )
        seen.append(current)
        src = _source_of_receiver_type(current, java_root)
        if src is None:
            assert len(seen) > 1, (
                f"未找到接收类型 {class_name}（既无 {class_name}.java，也无同名内部类）——"
                f"REGISTRY 登记的契约类已改名/删除；请同步更新 {__file__} 的 REGISTRY"
            )
            assert _is_external_parent(child_src, current), (
                f"{class_name} 的父类 {current} 在仓库 Java 源码树里找不到，且源码里没有任何"
                f"「仓库外来源」声明（FQN / 非 com.migao import / java.lang 根类）——"
                f"父类疑似改名/删除/移出仓库。静默忽略会让继承字段凭空少算（与上面"
                f"「接收类型找不到」同口径，禁止静默降级）；继承链：{' → '.join(seen)}"
            )
            break
        fields |= set(_FIELD_RE.findall(src))
        child_src = src
        current = _superclass_of(src, current)
    assert fields, f"{class_name} 未解析到任何字段（正则需适配；来源源码片段如下）：\n{child_src[:400]}"
    return frozenset(fields)


# 「接收端可读键来源」注册表：新增来源时在此登记 resolver，未登记的来源在测试里会**显式报错**
# （而不是被静默跳过 —— 静默跳过正是本文件要消灭的那类失效）。
RECEIVER_KEY_SOURCES = {
    "java-source": _receiver_fields_from_java,
}


# ==================== ② 服务层「真正落库」判据（issue #4115） ====================
#
# 缺陷形态：payload key 在接收类型里声明得好好的，**服务层却不把它写进落库实体** ⇒
# HTTP 200 + 无异常 + 数据丢失 + 工具谎报成功。只解析接收类型（上面那层）永远抓不到。
# 因此新增第二层：**解析服务实现方法体内「落库实体上的 setter」**（单一事实源仍是 Java 源码）。

# Java 注释必须先剥掉：否则「注释掉一行 setXxx」仍会被正则命中 ⇒ 判据变成不会红的空断言
# （本文件的红证之一就是注释掉那 4 行后必须变红）。
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"(?<!:)//[^\n]*")


def _strip_java_comments(src: str) -> str:
    """剥掉 Java 行注释/块注释（`://` 保护的 URL 不会被误剥）。

    必须剥：`// existing.setCraftMode(...)` 若仍被当作「写入」，本层判据就永远不会红。
    """
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", src))


def _service_method_body(target: str) -> str:
    """取 `"<ServiceClass>#<method>"` 指定的**方法体**源码（含剥注释）。

    解析不到一律显式报错（改名/删除后必须来更新 REGISTRY，禁止静默跳过）。
    """
    class_name, _, method = target.partition("#")
    assert class_name and method, (
        f"persist_target 格式应为 '<ServiceClass>#<method>'，实际 {target!r}"
    )
    src = _source_of_receiver_type(class_name)
    assert src is not None, (
        f"未找到服务类 {class_name}（persist_target={target!r}）——"
        f"REGISTRY 登记的服务类已改名/删除；请同步更新 {__file__}"
    )
    src = _strip_java_comments(src)
    decl = re.search(
        rf"(?:public|protected|private)[^\n(]*\b{re.escape(method)}\s*\([^)]*\)\s*\{{", src
    )
    assert decl, (
        f"{class_name} 未找到方法声明 {method}(...)（persist_target={target!r}）—— "
        f"方法已改名/移动；请同步更新本文件的 REGISTRY"
    )
    return _balanced_brace_block(src, src.index("{", decl.start()))


def _null_copy_setters_from_body(body: str) -> frozenset[str]:
    """从（已剥注释的）方法体取「落库实体上的 setter 属性名」集合。

    锚点是 `updateById(<实体变量>)` 的那个实体变量 —— 只有写在它身上的 `setXxx`
    才会随该次更新落库；服务方法里的其它 setter（分页对象、wrapper 等）不计入。
    抽成纯函数：`test_persist_parser_ignores_commented_out_setters` 直接行使它
    （测试跑的是**生产判据本身**，不是测试里另抄一份正则）。
    """
    entity_vars = re.findall(r"\.updateById\(\s*(\w+)\s*\)", body)
    assert entity_vars, (
        "方法体内未找到 `updateById(<实体变量>)` —— 该服务方法不落库或落库方式已变，"
        "本判据无法判定落库集合（禁静默放行）：请改用其它 persist_source 或修正 persist_target"
    )
    keys: set[str] = set()
    for var in dict.fromkeys(entity_vars):
        keys |= {_decap(p) for p in re.findall(rf"\b{re.escape(var)}\.set(\w+)\s*\(", body)}
    return frozenset(keys)


def _persisted_keys_via_null_copy(target: str) -> frozenset[str]:
    """**效果级**判据：属性是否经「落库实体的 setter」写入（见 `_null_copy_setters_from_body`）。"""
    keys = _null_copy_setters_from_body(_service_method_body(target))
    assert keys, (
        f"{target} 解析到落库实体但没有 `setXxx(` —— 解析器需适配"
        f"（否则本判据会把全部字段判红）"
    )
    return keys


def _persisted_keys_via_request_read(target: str) -> frozenset[str]:
    """**必要条件级**判据（弱于 null-copy）：属性是否被服务方法读取（`<形参>.getXxx()`）。

    用于「条件写入 + 字段改名」的路径（如实测 AS-004：请求字段 `remark` 经分支写进
    `closeReason`/`internalNotes`，无法用「字段名 = 实体 setter」的集合表达）。
    它只能证明字段**被消费**（不再被整份丢弃），不证明无条件落库 ——
    新登记域优先用 `java-service-null-copy`。
    """
    body = _service_method_body(target)
    return frozenset(_decap(p) for p in re.findall(r"\b\w+\.get([A-Z]\w*)\s*\(\s*\)", body))


# 「服务层落库判据来源」注册表（与接收端同口径：未登记来源显式报错，禁止静默跳过）
PERSIST_KEY_SOURCES = {
    "java-service-null-copy": _persisted_keys_via_null_copy,
    "java-service-request-read": _persisted_keys_via_request_read,
}


def find_unpersisted_keys(
    payload: Mapping[str, Any], persisted: frozenset[str], allowlisted: set[str]
) -> list[str]:
    """payload 里「接收类型已声明、但服务层不会落库」的键（本文件的核心判据）。

    抽成纯函数是为了让「判据不能空转」可被单测直接行使（见
    `test_persist_judgement_has_teeth`）：若它退化成恒返回空集，那条测试立即红。
    """
    return sorted(set(payload) - set(persisted) - allowlisted)


def _decap(bean_name: str) -> str:
    """JavaBean 访问器名 → 属性名（`setCraftMode`/`getCraftMode` → `craftMode`）。

    契约比对的是 JSON 属性名（工具 payload 的 key），而源码里出现的是 `set<Prop>`/`get<Prop>`，
    不还原首字母大小写就会把 `Phone` 与 `phone` 当成两个键（判据会误报全红）。
    """
    return bean_name[:1].lower() + bean_name[1:]


@dataclass(frozen=True)
class WriteContract:
    """一条「工具调用点 → admin-api 写端点」的字段契约登记（字段含义见文件头步骤 1）。"""

    tool_module: str          # 工具模块（app.tools.xxx）
    tool_kwargs: dict         # execute 参数（须含要落库的业务内容字段）
    client_method: str        # admin api client 方法：post / put / patch
    endpoint: str             # 期望的 admin-api 路径（工具调用点）
    receiver_type: str        # 接收端 Java 类型（请求 DTO 或实体）
    content_value: str        # 必须落到「接收端已声明字段」上的业务内容值
    # 服务层落库判据：来源 + `"<ServiceClass>#<method>"`。
    # **无默认值** —— 新增写契约必须显式回答「服务层凭什么算落库」（漏填 = 报错，不是跳过）。
    persist_source: str
    persist_target: str
    receiver_key_source: str = "java-source"   # 接收端可读键来源（见 RECEIVER_KEY_SOURCES）
    # 未映射键 → 「理由（归属）」：仅当接收端尚未声明该键、且业务上确属合法时登记
    unmapped_key_allowlist: Mapping[str, str] = field(default_factory=dict)


REGISTRY: tuple[WriteContract, ...] = (
    # AS-004「更新工单状态 - 关闭」：关闭原因必须经 `remark` 下发
    # （Java 侧 `updateTicketStatus` 用 request.getRemark() 写入 closeReason）——issue #3540
    # 落库判据用 request-read：该路径是**条件写入 + 字段改名**（remark → closeReason/internalNotes），
    # 「字段名 = 实体 setter」的集合表达不出来（口径见 _persisted_keys_via_request_read）。
    WriteContract(
        tool_module="app.tools.after_sales_manage",
        tool_kwargs={
            "action": "update_status",
            "ticket_id": "t1",
            "status": "closed",
            "reason": "客户取消订单",
        },
        client_method="put",
        endpoint="/api/admin/after-sales/t1/status",
        receiver_type="AfterSalesStatusUpdateRequest",
        content_value="客户取消订单",
        persist_source="java-service-request-read",
        persist_target="AfterSalesTicketService#updateTicketStatus",
    ),
    # CU-004「更新客户资料」：姓名必须经 `wechatNickname` 下发
    # （`CustomerProfile` 无 `name` 列 → 下发 `name` 被静默丢弃 = 米宝谎报「已更新客户姓名」，issue #3551）
    WriteContract(
        tool_module="app.tools.customer_manage",
        tool_kwargs={
            "action": "update",
            "customer_id": "c1",
            "data": {"name": "李四", "phone": "13900001111"},
        },
        client_method="put",
        endpoint="/api/admin/customers/c1",
        receiver_type="CustomerProfile",
        content_value="李四",
        persist_source="java-service-null-copy",
        persist_target="CustomerService#updateCustomer",
    ),
    # M2-D「更新客户工艺画像与常用物流」（issue #3984，V47）：
    # craftMode/craftProfile/defaultLogisticsType/defaultLogisticsCompany 为 CustomerProfile 新列。
    # **issue #4115**：这 4 列此前「实体已声明 + 工具可写 + 服务层拷贝白名单漏了」⇒
    # 下发即静默丢弃 + 工具谎报成功；本契约的服务层判据就是把它钉死的（修前本用例必须红）。
    WriteContract(
        tool_module="app.tools.customer_manage",
        tool_kwargs={
            "action": "update",
            "customer_id": "c1",
            "data": {
                "craftMode": "economy",
                "craftProfile": {"openCount": 2, "isShaped": True},
                "defaultLogisticsType": "logistics",
                "defaultLogisticsCompany": "四季安",
            },
        },
        client_method="put",
        endpoint="/api/admin/customers/c1",
        receiver_type="CustomerProfile",
        content_value="economy",
        persist_source="java-service-null-copy",
        persist_target="CustomerService#updateCustomer",
    ),
)


def _tool_instance(module_name: str) -> BaseTool:
    """取模块内注册的 BaseTool 子类实例（与 test_tool_schema_signature_contract 同口径）。"""
    mod = importlib.import_module(module_name)
    for obj in vars(mod).values():
        if (
            inspect.isclass(obj)
            and obj.__module__ == mod.__name__
            and issubclass(obj, BaseTool)
            and isinstance(getattr(obj, "name", None), str)
            and obj.name
        ):
            return obj()
    raise AssertionError(f"{module_name} 未定义有效的 BaseTool 子类")


@pytest.mark.parametrize(
    "contract", REGISTRY, ids=lambda c: f"{c.tool_module.split('.')[-1]}:{c.tool_kwargs['action']}"
)
async def test_write_payload_keys_declared_in_api_dto(contract, admin_tool_context):
    """工具写请求 body 的字段名 ⊆ 接收类型字段名 **且** ⊆ 服务层真正落库的字段集合。

    修复前（issue #3540）：payload={"status","reason"}，DTO 字段={"status","remark"} → `reason` 丢失；
    修复前（issue #3551）：payload={"name"}，`CustomerProfile` 无 `name` → 姓名丢失；
    修复前（issue #4115）：payload 的 4 个 key **全部**能对上 `CustomerProfile` 字段，
    但 `CustomerService.updateCustomer` 的非空拷贝白名单里没有它们 ⇒ 同样 200 + 静默丢失。
    三例都是 HTTP 200 + 数据不落库 + 调用方以为成功，本测试红。
    """
    tool = _tool_instance(contract.tool_module)
    client = AsyncMock()
    setattr(client, contract.client_method, AsyncMock(return_value={"success": True}))

    with patch(f"{contract.tool_module}.get_admin_api_client", return_value=client):
        result = await tool.execute(context=admin_tool_context, **contract.tool_kwargs)

    assert result.success is True, f"工具执行失败：{result.error} / {result.message}"

    call = getattr(client, contract.client_method).call_args
    assert call.args[0] == contract.endpoint, f"写端点漂移：{call.args[0]}"
    payload = call.kwargs["json_data"]

    resolver = RECEIVER_KEY_SOURCES.get(contract.receiver_key_source)
    assert resolver, (
        f"未实现的接收端可读键来源 {contract.receiver_key_source!r}"
        f"（已登记：{sorted(RECEIVER_KEY_SOURCES)}）—— 未登记来源必须显式报错，禁止静默跳过"
    )
    receiver_fields = resolver(contract.receiver_type)
    declared = set(receiver_fields)

    # 白名单是「接收端尚未声明但仍合法」的逃逸口：必须写理由，且不得空挂/过期
    for key, reason in contract.unmapped_key_allowlist.items():
        assert reason and reason.strip(), (
            f"{contract.receiver_type} 的 unmapped_key_allowlist[{key!r}] 缺理由/归属 —— "
            f"逃逸口必须可追溯（理由（归属人/issue））"
        )
    allowlisted = set(contract.unmapped_key_allowlist)
    stale = sorted((allowlisted & declared) | (allowlisted - set(payload)))
    assert not stale, (
        f"{contract.receiver_type} 的 unmapped_key_allowlist 已过期/空挂：{stale}"
        f"（已声明字段无需白名单；白名单里的键必须真的出现在 payload 里）"
    )

    dropped = sorted(set(payload) - declared - allowlisted)
    assert not dropped, (
        f"{contract.tool_module} action={contract.tool_kwargs['action']} 下发字段 {dropped} "
        f"未在 {contract.receiver_type} 中声明（该类型字段：{sorted(declared)}）"
        f" → admin-api 静默丢弃（Spring 默认忽略未知属性，HTTP 200 但数据不落库）。"
        f"改工具侧下发 canonical 字段名；若该键确属接收端未声明的合法字段，"
        f"请在 REGISTRY 的 unmapped_key_allowlist 登记「理由（归属）」"
    )

    # ② 服务层：字段名对得上还不够 —— 该键必须真的被服务实现写进落库实体（issue #4115）
    persist_resolver = PERSIST_KEY_SOURCES.get(contract.persist_source)
    assert persist_resolver, (
        f"未实现的服务层落库判据来源 {contract.persist_source!r}"
        f"（已登记：{sorted(PERSIST_KEY_SOURCES)}）—— 未登记来源必须显式报错，禁止静默跳过"
    )
    persisted = persist_resolver(contract.persist_target)
    not_persisted = find_unpersisted_keys(payload, persisted, allowlisted)
    assert not not_persisted, (
        f"{contract.tool_module} action={contract.tool_kwargs['action']} 下发字段 {not_persisted} "
        f"虽在 {contract.receiver_type} 中声明，但 {contract.persist_target} **不会把它们写进落库实体**"
        f"（该服务方法真正落库的字段：{sorted(persisted)}）"
        f" → HTTP 200 + 数据静默丢失 + 工具回报「已更新」（issue #4115 的缺陷形态）。"
        f"治法：把字段纳入服务层的非空拷贝白名单（保持既有「null 不覆盖」语义），"
        f"或改工具侧不下发该键 —— 不要靠「工具说写了」当作落库证据"
    )

    carriers = sorted(
        k for k, v in payload.items() if v == contract.content_value and k in declared
    )
    assert carriers, (
        f"业务内容 {contract.content_value!r} 未落到 {contract.receiver_type} 的任何已声明字段上，"
        f"实际 payload={payload}"
    )


def test_receiver_parser_is_not_vacuous():
    """哨兵自身不能空转：解析器必须只返回 Java 类型声明的列。

    `CustomerProfile` 的姓名列是 `wechatNickname`（无 `name`）—— 这既是本域登记的依据，
    也是「解析器若退化成"什么都返回"则本文件失去拦截力」的自检（#3551）。
    """
    fields = _receiver_fields_from_java("CustomerProfile")
    assert "wechatNickname" in fields
    assert "name" not in fields, "CustomerProfile 没有 name 列，解析器/断言口径已漂移"


# ==================== ② 判据自身的牙口（不能空转 / 不会静默失效） ====================


def test_persist_judgement_has_teeth():
    """判据必须咬得住「接收类型已声明、服务层不落库」的字段（issue #4115 的固化红例）。

    红证②的文件化形态：`lifecycleStage` 是 `CustomerProfile` 已声明列（第一层判据放行），
    但不在 `CustomerService.updateCustomer` 的拷贝白名单里（第二层判据必须判红）——
    若 `find_unpersisted_keys` 某天退化成恒返回空集，本用例立即红（不会静默变空断言）。
    """
    declared = _receiver_fields_from_java("CustomerProfile")
    assert "lifecycleStage" in declared, (
        "样例字段必须是被接收类型**已声明**的列 —— 否则它只能证明第一层判据，"
        "证明不了「扩了第二层判据」的价值（本用例的存在意义）"
    )

    persisted = _persisted_keys_via_null_copy("CustomerService#updateCustomer")
    payload = {"lifecycleStage": "mature", "phone": "13900001111"}

    # 第一层判据对它是绿的（字段名确实对得上 ⇒ 旧口径抓不到 = #4115 缺陷形态）
    assert set(payload) <= set(declared)
    # 第二层判据必须红，且点名到字段
    not_persisted = find_unpersisted_keys(payload, persisted, set())
    assert not_persisted == ["lifecycleStage"], (
        f"「接口已声明但服务层不落库」的字段必须被判红，实际 {not_persisted}；"
        f"服务层落库集合={sorted(persisted)}"
    )


def test_persist_parser_ignores_commented_out_setters():
    """注释掉的 `setXxx` 不得算作落库（否则「注释掉 4 行 setXxx」的红证会假绿）。

    用合成源码行使解析器（真源码在 #4115 的红证里被实际注释过）：
    只写 `setPhone` 的行计入，被 `//` 注释掉的 `setCraftMode` 行不计入。
    """
    snippet = (
        "class Demo {\n"
        "    public void updateCustomer(String id, Profile profile) {\n"
        "        Profile existing = mapper.selectById(id);\n"
        "        existing.setPhone(profile.getPhone());\n"
        "        // existing.setCraftMode(profile.getCraftMode());\n"
        "        mapper.updateById(existing);\n"
        "    }\n"
        "}\n"
    )
    stripped = _strip_java_comments(snippet)
    written = _null_copy_setters_from_body(stripped)
    assert written == {"phone"}, f"注释掉的 setter 不得计入落库集合，实际 {sorted(written)}"
    assert "setCraftMode" not in stripped


# ==================== ③ 继承解析（`extends` 链）的牙口（issue #4166） ====================
#
# 「接收端可读键」在 Java 语义里含**继承字段**（Jackson 照常绑定父类字段），解析器必须跟随
# `extends` —— 但跟随一旦写宽（无条件并集 / 认错父类 / 环上死循环），门禁就会被**静默放宽**，
# 比假红更糟。下面五条用**注入式夹具**（临时 Java 源码树）行使**同一份生产判据**
# （`_receiver_fields_from_java` 的 `java_root` 参数），各自都有一个能让它变红的注入方向。


def _java_fixture_tree(root: Path, files: Mapping[str, str]) -> Path:
    """在临时目录铺一棵最小 Java 源码树（夹具注入点：解析器按 `java_root` 读它）。"""
    for name, src in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
    return root


def _child_fixture(order_create_body: str) -> dict[str, str]:
    """`#4162` 那对类型的最小复刻：子类只声明 `clientRequestId`，其余字段在父类。"""
    return {
        "com/migao/admin/dto/OrderCreateRequest.java": (
            "package com.migao.admin.dto;\n"
            "public class OrderCreateRequest {\n"
            f"{order_create_body}"
            "}\n"
        ),
        "com/migao/admin/dto/agent/AgentOrderCreateRequest.java": (
            "package com.migao.admin.dto.agent;\n"
            "import com.migao.admin.dto.OrderCreateRequest;\n"
            "public class AgentOrderCreateRequest extends OrderCreateRequest {\n"
            "    private String clientRequestId;\n"
            "}\n"
        ),
    }


_CHILD = "AgentOrderCreateRequest"
_PARENT_FIELDS = (
    "    private String customerName;\n"
    "    private String customerPhone;\n"
    "    private String remark;\n"
)


def test_parser_follows_extends_chain(tmp_path):
    """负控①：`extends` 真的被跟随 —— 键从父类搬到子类，解析结果**逐字不变**（并集）。

    红的方向（修复前 #4166 的真身）：只读子类源码 ⇒ 父类字段读不到。
    """
    both_in_parent = _receiver_fields_from_java(
        _CHILD, _java_fixture_tree(tmp_path / "a", _child_fixture(_PARENT_FIELDS))
    )
    assert both_in_parent == {"clientRequestId", "customerName", "customerPhone", "remark"}, (
        f"父类字段必须并入接收端可读键，实际 {sorted(both_in_parent)}"
    )

    # 「把键从父类搬到子类」：父/子哪个位置声明都算已声明 ⇒ 结果集不变
    moved = _receiver_fields_from_java(
        _CHILD,
        _java_fixture_tree(
            tmp_path / "b",
            _child_fixture(_PARENT_FIELDS.replace("    private String customerName;\n", ""))
            | {
                "com/migao/admin/dto/agent/AgentOrderCreateRequest.java": (
                    "package com.migao.admin.dto.agent;\n"
                    "import com.migao.admin.dto.OrderCreateRequest;\n"
                    "public class AgentOrderCreateRequest extends OrderCreateRequest {\n"
                    "    private String clientRequestId;\n"
                    "    private String customerName;\n"
                    "}\n"
                )
            },
        ),
    )
    assert moved == both_in_parent, (
        f"键从父类搬到子类后结果集必须不变（继承是并集），实际 {sorted(moved)}"
    )


def test_type_parameter_bound_is_not_mistaken_for_a_parent(tmp_path):
    """类自身的 `<T extends Y>` 不得被当成父类：认错会**把无关类型的字段并进来**（门禁被放宽）。

    红的方向：解析类声明头时不吃掉类型参数表 ⇒ `Generic` 并进 `Bound` 的字段、漏掉真父类 `Impl`。
    """
    root = _java_fixture_tree(
        tmp_path,
        {
            "Bound.java": "public class Bound {\n    private String boundOnly;\n}\n",
            "Impl.java": "public class Impl {\n    private String implOnly;\n}\n",
            "Generic.java": "public class Generic<T extends Bound> extends Impl {\n"
            "    private String own;\n}\n",
            "BoundOnly.java": "public class BoundOnly<T extends Bound> {\n    private String own;\n}\n",
        },
    )
    assert _receiver_fields_from_java("Generic", root) == {"own", "implOnly"}, (
        "`class Generic<T extends Bound> extends Impl` 的父类是 Impl，类型参数上界 Bound 不是父类"
    )
    assert _receiver_fields_from_java("BoundOnly", root) == {"own"}, (
        "没有 extends 的泛型类不得凭空多出类型参数上界的字段"
    )


def test_deleting_a_parent_field_turns_the_gate_red(tmp_path):
    """负控②（关键）：父类**真删字段** ⇒ 该键必须从可读集合里消失、门禁重新判红。

    这是「没有把继承解析写成恒绿」的判据：payload ⊆ 接收端可读键（与
    `test_tool_payload_backend_contract._violations` 同一条集合判据）在删字段后必须不成立。
    若继承解析退化成「一律放行」（父类解析失败也照收 / 认错父类）本用例立即红。
    """
    root = _java_fixture_tree(tmp_path, _child_fixture(_PARENT_FIELDS))
    payload = {"clientRequestId", "customerName", "customerPhone", "remark"}

    declared = _receiver_fields_from_java(_CHILD, root)
    assert payload <= declared, f"夹具基线本就该绿，缺 {sorted(payload - declared)}"

    # 注入删除：父类源码里去掉 `private String customerName;`
    parent_without_name = _PARENT_FIELDS.replace("    private String customerName;\n", "")
    (root / "com/migao/admin/dto/OrderCreateRequest.java").write_text(
        "package com.migao.admin.dto;\n"
        "public class OrderCreateRequest {\n"
        + parent_without_name
        + "}\n",
        encoding="utf-8",
    )
    _receiver_fields_from_java.cache_clear()  # 同一 (类名, root) 已缓存 → 甩掉才能读到新源码
    declared_after = _receiver_fields_from_java(_CHILD, root)

    assert declared_after == declared - {"customerName"}, (
        f"父类删字段后必须少掉该键，实际 {sorted(declared_after)}"
    )
    assert sorted(payload - declared_after) == ["customerName"], (
        "父类字段被删必须让「payload ⊆ 接收端可读键」重新判红（否则继承解析把门禁放宽了）"
    )


@pytest.mark.timeout(10)
def test_cyclic_extends_raises_instead_of_hanging(tmp_path):
    """负控③：自引用 / 成环的 `extends` 必须**显式报错**，不得挂死。

    去掉环检测后本用例红：自引用会**无限循环**（实测栈停在 `_source_of_receiver_type`
    反复读同一份源码）而拿不到 AssertionError；`@pytest.mark.timeout(10)` 是硬兜底 ——
    解析退化成无界循环时 10s 超时红，而不是拖到全局 `--timeout=120`。
    """
    self_ref = _java_fixture_tree(
        tmp_path / "self", {"Loop.java": "public class Loop extends Loop {\n    private String a;\n}\n"}
    )
    with pytest.raises(AssertionError, match="成环"):
        _receiver_fields_from_java("Loop", self_ref)

    ring = _java_fixture_tree(
        tmp_path / "ring",
        {
            "A.java": "public class A extends B {\n    private String a;\n}\n",
            "B.java": "public class B extends A {\n    private String b;\n}\n",
        },
    )
    with pytest.raises(AssertionError, match="A → B → A"):
        _receiver_fields_from_java("A", ring)


def test_unresolvable_parent_is_loud_unless_it_is_repo_external(tmp_path):
    """父类解析不到的两种语义（issue #4166 第 3 条）：仓库外 ⇒ 无字段可并；疑似改名 ⇒ 响亮报错。

    - 仓库外（JDK / 第三方）有**源码里的来源声明**可依据（FQN / 非 com.migao import /
      java.lang 隐式根类）⇒ 只收本类字段；
    - 本仓库类型的改名/删除**没有任何来源声明**可依据 ⇒ 报错。静默按「无父类」放行
      会让父类字段凭空少算（负控② 那类真缺陷就再也咬不住）。
    """
    external = _java_fixture_tree(
        tmp_path / "external",
        {
            "Fqn.java": "public class Fqn extends java.util.AbstractMap<String, String> {\n"
            "    private String own;\n}\n",
            "Root.java": "public class Root extends Object {\n    private String own;\n}\n",
            "ThirdParty.java": "import org.springframework.web.filter.OncePerRequestFilter;\n"
            "public class ThirdParty extends OncePerRequestFilter {\n    private String own;\n}\n",
        },
    )
    for name in ("Fqn", "Root", "ThirdParty"):
        assert _receiver_fields_from_java(name, external) == {"own"}, (
            f"{name} 的父类在仓库外 ⇒ 没有本仓库字段可并，只收本类字段"
        )

    renamed = _java_fixture_tree(
        tmp_path / "renamed",
        {"Child.java": "public class Child extends BaseEntity {\n    private String own;\n}\n"},
    )
    with pytest.raises(AssertionError, match="BaseEntity"):
        _receiver_fields_from_java("Child", renamed)
