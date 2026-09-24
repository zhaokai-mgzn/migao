# case_ids: OR-033, DA-016, ON-003
"""契约快照 ↔ 当前 admin-api 响应契约 的**过期判据**（issue #5474）。

## 为什么需要这份判据（= issue #5474 的「问题 B」）

`tests/contracts/snapshots/*.json` 是**线上响应的抓取缓存**：CI 里没有 admin-api，
`tests/contracts/conftest.py::_fetch` 抓不到就走回退，于是**快照就是判据的输入**。
2026-07-19 那次抓的一批里，6 个在同族契约变更后**没人重抓**，而**没有任何东西变红**：

① **面外 = 永久免检**：没有任何判据把「契约变更」与「快照刷新」连起来。
   唯一沾边的 `test_contract_api.py` 只是**顺带**被 `AI_AGENT_TESTS="tests/"` 收进射程。
② 🔴 **判据的输入就是缓存**：在 CI 条件（无 admin-api）下实测
   `pytest tests/contracts/ -v -s` ⇒ **7 条回退、15 passed** ——
   夹具返回的是 `_load_snapshot(...)`，即**被测对象自己**。契约根本不在回路里，
   ⇒ 它**结构上不可能**因「admin-api 改了字段」而变红（自指判据）。
③ 即使真抓到线上，每条断言只查 1~3 个键（`id`/`name`/`price`）⇒ **新增字段天然不可见**。

## 本文件判两条**不同的**失效（两条都要有，缺一条就漏一族）

- **判据 1（快照 ↔ 现行契约，⊆）**：快照条目一层的键必须**都在**当前 DTO 声明的线上键里。
  抓的是**重命名/删除**族 —— 也是**会打断消费方**的那一族。红证实测：把 2026-07-19 的
  `api_admin_categories_tree.json` 放回来 ⇒ `sortOrder` 命中（当前契约里它是 `sort`）。
- **判据 2（抓取 ↔ 契约推进，≡ 指纹）**：`snapshot-contract-fingerprints.json` 记的是
  **抓取那一刻的契约键集**；它必须**等于**现在的契约键集。抓的是**新增**族
  （`craftHint` / `allowReturnRestock` / `customerAddress` 这类）——
  它们不会让 ⊆ 变红，但会让 CI 里所有「按字段取值」的判据**静默跳过**。

两条都**判契约、不判数据**：快照里的数值天天在变（`total` 4→784、看板数字每分钟都不同），
那不是过期；**键集**变了才是。判据也**不钉死任何具体键名** ——
「禁出现 `sortOrder`」那种写法今天能抓，明天换成别的重命名就抓不住（#5473 已登记该取舍）。

## 出口（真可行动）

重跑一次真实抓取（详见 `tests/contracts/conftest.py` 的端口陷阱：必须起在 **8081**）：

    %s

## 射程边界（照实登记，不粉饰）

- **不递归进嵌套子树**：`OrderListResponse.processingInfo`、`CustomerProfile.tags/customFields`
  等是 `Object`，其键由运行时数据决定，**本来就没有静态契约**；强行比对只会产出假红。
  完整清单见 `tests/contract_snapshot_registry.py::UNCHECKED_NESTED_SUBTREES`。
- 判据 2 在**契约键集**变化时要求重抓。这是刻意的：快照是 CI 的线上替身，
  契约推进后它就不再是替身了。代价是「改了响应 DTO 键集 ⇒ 必须本地重抓一次」。
""" % (
    "cd backend/admin-api && SERVER_PORT=8081 ./mvnw spring-boot:run\n"
    "    cd backend/ai-agent-service && .venv/bin/python -m pytest tests/contracts/ -v -s --no-cov"
)

from tests import contract_snapshot_registry as R


def _fmt_phantom(name: str, phantom: list[str]) -> str:
    spec = R.REGISTRY[name]
    wire = R.declared_wire_keys(spec.item_dto)
    hints = []
    for key in phantom:
        # 反查：这个键是不是被 @JsonProperty 改名后的旧名/新名？
        back = sorted(f for f, w in wire.renames.items() if w == key)
        hints.append(f"      · {key}" + (f"（当前契约里由 {back[0]} 声明为该名）" if back else ""))
    return (
        f"\n  ❌ {name}（DTO={spec.item_dto}）：快照里有 {len(phantom)} 个键"
        f"**不在当前契约里** —— 契约改过名/删过字段，而快照没重抓：\n"
        + "\n".join(hints)
        + f"\n      当前 {spec.item_dto} 的线上键：{sorted(wire.keys)}"
    )


def test_snapshot_item_keys_are_declared_in_current_contract():
    """判据 1：快照条目一层的每个键都必须能在**当前** Java 响应契约里找到出处。

    红证（实测）：`api_admin_categories_tree.json` 用 2026-07-19 的内容 ⇒
    `sortOrder` 不在 `CategoryResponse` 的键里（那条契约 2026-09-02 起是 `sort`）⇒ 红。
    """
    offenders = []
    for name in sorted(R.REGISTRY):
        phantom = sorted(R.observed_contract_keys(name) - R.contract_keys(name))
        if phantom:
            offenders.append(_fmt_phantom(name, phantom))
    assert not offenders, (
        "契约快照已与当前 admin-api 响应契约脱节（快照里有契约里没有的键）：\n"
        + "\n".join(offenders)
        + f"\n\n  出口 = 重跑一次真实抓取：\n    {R.RECAPTURE_COMMAND}\n"
    )


def test_snapshot_contract_fingerprint_is_current():
    """判据 2：抓取时刻记录的契约键集 == 现在的契约键集。

    红证：往任一登记 DTO 加一个字段（无需编译 Java）⇒ `current_fingerprint()` 变化 ⇒ 红。
    """
    recorded = R.read_fingerprint()
    assert isinstance(recorded, dict), (
        f"缺 `{R.FINGERPRINT_PATH.name}` —— 没有它就无法回答"
        "「这批快照对应的是哪一版契约」，判据 2 退化成不会红的空断言。"
        f"\n  出口 = 重跑一次真实抓取（抓取成功时会自动写出）：\n    {R.RECAPTURE_COMMAND}\n"
    )
    old = recorded.get("contracts") or {}
    now = R.current_fingerprint()
    drift = []
    for name in sorted(set(old) | set(now)):
        before, after = set(old.get(name, [])), set(now.get(name, []))
        if before != after:
            spec = R.REGISTRY.get(name)
            drift.append(
                f"      · {name}（DTO={spec.item_dto if spec else '已从 REGISTRY 移除'}）"
                f"  新增={sorted(after - before)}  消失={sorted(before - after)}"
            )
    assert not drift, (
        f"admin-api 响应契约自 {recorded.get('captured_at')} 那次抓取后已推进，"
        f"而快照没重抓（{len(drift)} 个端点的契约键集变了）：\n"
        + "\n".join(drift)
        + f"\n\n  出口 = 重跑一次真实抓取：\n    {R.RECAPTURE_COMMAND}\n"
    )


def test_every_snapshot_file_is_registered():
    """未登记即红：磁盘上新增的快照文件必须同步进 REGISTRY，否则它自动脱离射程。"""
    on_disk, registered = set(R.snapshot_files()), set(R.REGISTRY)
    unregistered = sorted(on_disk - registered)
    assert not unregistered, (
        f"快照文件未登记进 REGISTRY（会自动脱离本判据的射程）：{unregistered}\n"
        f"  请同步更新 {R.__file__} 的 REGISTRY（item_dto / page / nested）"
    )


def test_every_registry_entry_has_a_snapshot():
    """反向：登记了却读不到文件 ⇒ 判据对空气断言（静默空跑），必须响亮报错。"""
    missing = sorted(set(R.REGISTRY) - set(R.snapshot_files()))
    assert not missing, (
        f"REGISTRY 登记了快照但磁盘上没有对应文件：{missing}\n"
        f"  该端点会静默退出射程（看起来覆盖了，其实没有）"
    )


def test_parser_recognizes_known_java_shapes():
    """判据的前提自证（G7）：解析器真的认得出这三种线上键名形态。

    没有这条，`test_snapshot_item_keys_are_declared_in_current_contract` 可能因为
    「解析器什么都没解析出来」而**恒绿**（空断言）。三种形态都是**实测**存在的：
    `CategoryResponse` 的字段级 `@JsonProperty`、`ProductResponse.getPrice()` 的计算型 getter、
    `CustomerProfile` 的 getter 级 `@JsonProperty`（issue #5459）。
    """
    cat = R.declared_wire_keys("CategoryResponse")
    assert "sort" in cat.keys and "sortOrder" not in cat.keys, (
        f"CategoryResponse 的字段级 @JsonProperty(\"sort\") 未被识别：{sorted(cat.keys)}"
    )
    prod = R.declared_wire_keys("ProductResponse")
    assert "price" in prod.computed, (
        f"ProductResponse.getPrice() 的计算型 getter 未被识别（computed={sorted(prod.computed)}）"
    )
    cust = R.declared_wire_keys("CustomerProfile")
    assert "rScore" in cust.keys and "rscore" not in cust.keys, (
        f"CustomerProfile getter 级 @JsonProperty 未被识别：renames={cust.renames}"
    )