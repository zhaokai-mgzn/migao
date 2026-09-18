# case_ids: MC-012
"""迁移不可变护栏：已发布迁移的**内容指纹账本**（issue #4235 判据 2）。

## 为什么需要它（缺陷形态 = 「CI 全绿、功能静默缺失」）

`MigrationRunner` 的台账 `schema_migrations` 按**文件名**记：

```java
if (applied.contains(filename)) continue;   // 已应用的迁移整份 skip
```

⇒ 往**已应用**的迁移（如 `V54__seed_production_operations.sql`）里加行，整份被跳过 ——
**存量环境永远拿不到**，而任何静态守卫（三源逐行比对）反而会因此转绿。
「迁移一旦应用即不可变」是本仓的工程规则，但**此前零护栏**：改 V54 不会让任何东西变红。

## 判据形态（为什么是「账本」而不是「比 git 历史」）

🔴 **硬约束**：本文件跑在 CI job `ci workflow helper unit tests`（`pr-check.yml`）里，该 job 用
`actions/checkout@v7` 的**默认 `fetch-depth: 1`** —— **没有 git 历史、也没有 `origin/main`**。
「比对 `origin/main` 上该文件的 blob hash」在本地能跑、在 CI 上只能 skip（= **没跑**，而 skip
看起来像绿）。故采用**仓内账本**：`migration_fingerprints.json` = `{文件名: 内容 sha256}`，
与 git 无关、与 DB 无关、`fetch-depth` 无关。

账本 = 「已发布（= 已登记）」的机械代理：**凡在账本里的文件，内容逐字节冻结**。
双向可红（三条各自独立，互不掩盖）：

| 形态 | 判据 | 后果 |
|---|---|---|
| 改一个字符 / 加一行（已登记文件） | `test_registered_migrations_are_byte_identical` | 红（含基线/当前指纹对照） |
| 新增迁移**未登记** | `test_ledger_covers_every_migration_on_disk` | 红 + 打印重生成命令（**不静默通过**） |
| 账本条目对应的文件**消失** | `test_no_ledger_entry_points_to_a_vanished_file` | 红（防「删文件 / 删账本 = 绕过」） |

## 新增迁移时怎么走（唯一合法路径）

1. 新增 `V<下一个空闲号>__xxx.sql`（**不要**改任何已登记文件）；
2. 跑一次重生成命令，它会**只新增**未登记文件的条目：
   `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger`
3. 把新迁移 + 账本一起提交。

⚠️ 重生成命令**拒绝**覆盖已登记条目的指纹：真出现「已登记文件被改」时它非零退出并点名文件
（那是要**回滚改动**，不是"刷新一下就好"）。确需改一条已发布迁移（如版本号让号改名）时，
必须**手工**编辑账本条目 —— 手改会出现在 PR diff 里，可被评审看见。

## 自证（防「仓库绿只是空跑」）

`test_audit_detects_injected_drift` 用注入式夹具证明三向判据都**会**红（改 / 增 / 删各一例）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"

LEDGER_REGEN_CMD = ("python3 tests/unit_ci_workflows/"
                    "test_migration_immutability.py --write-ledger")

_VERSION_RE = re.compile(r"^V(\d+)__")


def version_key(name: str):
    """迁移文件名 → 排序键（`MigrationRunner` 同款：版本号**数值**序，不是字典序）。"""
    match = _VERSION_RE.match(Path(name).name)
    return (int(match.group(1)) if match else 1 << 30, Path(name).name)


def fingerprint(path: Path) -> str:
    """文件内容的 sha256（**只用内容**：mtime / size 不参与，见 issue #4260）。"""
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scan_disk(migration_dir: Path = MIGRATION_DIR) -> dict:
    """磁盘上的迁移文件 → 内容指纹（按版本号数值序，便于账本 diff 稳定）。"""
    paths = sorted(Path(migration_dir).glob("V*.sql"), key=lambda p: version_key(p.name))
    return {p.name: fingerprint(p) for p in paths}


def load_ledger(path: Path = LEDGER) -> dict:
    """读账本 → {文件名: 指纹}；账本缺失/结构不对 ⇒ 抛 `AssertionError`（fail-closed）。"""
    path = Path(path)
    assert path.is_file(), (
        f"迁移指纹账本缺失：{path}（判据 2 因此**没跑** —— 「没跑」不得读成「通过」）。\n"
        f"  重生成：{LEDGER_REGEN_CMD}")
    data = json.loads(path.read_text(encoding="utf-8"))
    migrations = data.get("migrations")
    assert isinstance(migrations, dict) and migrations, (
        f"账本结构不对（缺非空 `migrations` 映射）：{path}")
    return migrations


def audit(registered: dict, on_disk: dict) -> dict:
    """纯函数：三向差异 —— 改（modified）/ 增（unregistered）/ 删（missing）。

    纯函数化是为了能用注入式夹具证明「它会红」（否则「仓库绿」可能只是空断言）。
    """
    return {
        "modified": sorted((n for n, fp in registered.items()
                            if n in on_disk and on_disk[n] != fp), key=version_key),
        "unregistered": sorted((n for n in on_disk if n not in registered), key=version_key),
        "missing": sorted((n for n in registered if n not in on_disk), key=version_key),
    }


def _diff_detail(names, registered, on_disk) -> str:
    """红的时候点名 + 给基线/当前指纹（别只丢一句 assert）。"""
    lines = []
    for name in names:
        lines.append(f"    · {name}\n        账本 {registered.get(name, '（无条目）')}"
                     f"\n        磁盘 {on_disk.get(name, '（文件不存在）')}")
    return "\n".join(lines)


# ── 判据（三条各自独立：改 / 增 / 删）──

def test_ledger_covers_every_migration_on_disk():
    """**增**：磁盘上每个迁移都必须在账本里（新增迁移必须显式登记，不静默通过）。"""
    registered, on_disk = load_ledger(), scan_disk()
    report = audit(registered, on_disk)
    assert report["unregistered"] == [], (
        "磁盘上出现**未登记**的迁移文件（判据 2 的账本没有跟上）：\n"
        + _diff_detail(report["unregistered"], registered, on_disk) + "\n"
        f"  新增迁移是合法的 —— 登记它（**只新增条目**，不会覆盖已登记指纹）：\n"
        f"    {LEDGER_REGEN_CMD}")


def test_registered_migrations_are_byte_identical():
    """**改**：已登记（= 已发布）迁移的内容**逐字节冻结** —— 改一个字符即红。"""
    registered, on_disk = load_ledger(), scan_disk()
    report = audit(registered, on_disk)
    assert report["modified"] == [], (
        "已登记迁移的内容被修改（迁移不可变：改已应用迁移 = 存量环境永远拿不到，"
        "而 CI 会全绿）：\n" + _diff_detail(report["modified"], registered, on_disk) + "\n"
        "  → 回滚对该文件的改动，把增量内容写成**新迁移**（`V<下一个空闲号>__...sql`）；\n"
        "  → 确需变更一条已发布迁移（如版本号让号改名）时，**手工**改账本条目并在 PR 里说明。")


def test_no_ledger_entry_points_to_a_vanished_file():
    """**删**：账本条目必须对应真实存在的文件（防「删文件 / 删账本条目 = 绕过」）。"""
    registered, on_disk = load_ledger(), scan_disk()
    report = audit(registered, on_disk)
    assert report["missing"] == [], (
        "账本里有条目、磁盘上却没有该迁移文件：\n"
        + _diff_detail(report["missing"], registered, on_disk) + "\n"
        "  → 文件被误删就恢复它；确需删除/改名迁移时，**手工**删改账本条目并在 PR 里说明。")


def test_ledger_is_wellformed():
    """账本自身形状：条目值必须是 `sha256:<64 hex>`（防手抄/截断的假指纹恒不匹配）。"""
    registered = load_ledger()
    bad = sorted((n for n, fp in registered.items()
                  if not re.fullmatch(r"sha256:[0-9a-f]{64}", fp)), key=version_key)
    assert bad == [], f"账本条目不是合法 sha256 指纹：{bad}"
    assert len(registered) > 1, "账本只有 0~1 条 ⇒ 覆盖面退化（正常应覆盖整条迁移链）"


# ── 自证（防「仓库绿只是空跑」）──

def test_audit_detects_injected_drift():
    """注入式夹具：三向判据**都会**红 —— 否则上面三条的绿是**空断言**。"""
    baseline = {"V54__seed_production_operations.sql": "sha256:" + "a" * 64,
                "V58__seed_sheer_curtain_routings.sql": "sha256:" + "b" * 64}
    same = dict(baseline)
    assert audit(baseline, same) == {"modified": [], "unregistered": [], "missing": []}, \
        "未注入时审计必须全空（否则账本永远红）"

    # ① 改一个字符（往已应用迁移里加一行/改一个值）
    edited = dict(baseline)
    edited["V54__seed_production_operations.sql"] = "sha256:" + "c" * 64
    assert audit(baseline, edited)["modified"] == ["V54__seed_production_operations.sql"], \
        "「已登记迁移被改」读不出来 ⇒ 判据 2 是空断言"

    # ② 新增一个**新**迁移文件并登记 ⇒ 审计全空（= 合法路径，绿）
    with_new = dict(baseline)
    with_new["V60__seed_brand_new_operations.sql"] = "sha256:" + "d" * 64
    assert audit(with_new, with_new) == {"modified": [], "unregistered": [], "missing": []}, \
        "新增迁移 + 登记指纹后必须绿（否则「加新迁移」没有合法路径）"

    # ③a 新增迁移**未登记** ⇒ 红（且必须点名文件，便于给出重生成命令）
    assert audit(baseline, with_new)["unregistered"] == ["V60__seed_brand_new_operations.sql"], \
        "「磁盘上多出未登记迁移」读不出来 ⇒ 判据 2 的 fail-loud 是空断言"

    # ③b 删掉账本里某条却仍存在该文件 ⇒ 该文件变成「未登记」⇒ 红（防「删账本=绕过」）
    pruned = {n: fp for n, fp in baseline.items()
              if n != "V58__seed_sheer_curtain_routings.sql"}
    assert audit(pruned, baseline)["unregistered"] == ["V58__seed_sheer_curtain_routings.sql"], \
        "删掉账本条目即绕过的形态没被挡住"

    # ③c 账本条目对应的文件消失 ⇒ 红
    assert audit(baseline, {"V54__seed_production_operations.sql": baseline[
        "V54__seed_production_operations.sql"]})["missing"] == [
        "V58__seed_sheer_curtain_routings.sql"], \
        "「账本条目对应文件消失」读不出来"


# ── 账本重生成入口（唯一新增条目的合法路径；不覆盖已登记指纹）──

def write_ledger(path: Path = LEDGER) -> int:
    """重生成账本：**只新增**未登记条目；已登记文件被改 / 文件消失 ⇒ 拒绝并非零退出。"""
    path = Path(path)
    on_disk = scan_disk()
    registered = load_ledger(path) if path.exists() else {}
    report = audit(registered, on_disk)
    if report["modified"] or report["missing"]:
        print("❌ 拒绝重生成账本：重生成**不是**「改已发布迁移」的橡皮图章。", file=sys.stderr)
        for label, names in (("已登记文件被改（回滚改动，改走新迁移）", report["modified"]),
                             ("账本条目对应文件消失（恢复文件，或手工删条目）", report["missing"])):
            if names:
                print(f"  · {label}：{names}", file=sys.stderr)
        return 1
    added = report["unregistered"]
    payload = {
        "note": ("已发布迁移的内容指纹账本（issue #4235）。"
                 f"新增迁移后跑：{LEDGER_REGEN_CMD}（只新增条目，不覆盖已登记指纹）"),
        "migrations": {name: on_disk[name] for name in sorted(on_disk, key=version_key)},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 账本已写出：{path}（共 {len(on_disk)} 条；本次新增 {len(added)} 条）")
    for name in added:
        print(f"  · 新增登记 {name}  {on_disk[name]}")
    return 0


if __name__ == "__main__":
    if "--write-ledger" in sys.argv[1:]:
        sys.exit(write_ledger())
    print(f"用法：python3 {Path(__file__).name} --write-ledger", file=sys.stderr)
    sys.exit(2)
