# case_ids: MC-012
"""迁移版本号唯一性守卫（issue #3812）。

## 背景

`db/migration/` 下已先后出现 **3 组同号迁移**（V29 / V33 / V45）—— 最近一次是
`V45__add_order_logistics_shipper_name.sql` 与 `V45__widen_order_items_quantity_to_decimal.sql`
并存（线上库 `schema_migrations` 两条都已记录，所以**今天没炸**）。

`MigrationRunner` 的排序键是**版本号数值**（`Comparator.comparingInt(MigrationRunner::sortKey)`），
同号两条之间的执行顺序因此由 **classpath 扫描顺序**决定 —— 该类 javadoc 自述
「`getResources` 返回顺序取决于 classpath 扫描（JAR 内 zip 遍历序），**曾实测返回逆序**」。
两组/三组当前都是互不依赖的 ALTER，所以没炸；但「顺序不确定」本身是**潜伏缺陷**，
其爆发形态正是 issue #3270：排序/幂等约定被破坏 → schema 与代码长期脱节 → 查询 500 →
工具熔断 → 评测被污染。

## 本测试的形态（仓库既有范式，见 migao-dev-flow §14.5）

**登记表 + 陈旧即红**，不是「仓库当下恰好没有重复」的真值主张：

1. 判据**纯函数化** ⇒ 用**注入式夹具**证明它会红（否则「仓库绿」可能只是空断言）；
2. 存量重复版本号**显式登记**（burn-down，issue #3813）⇒ 增量一律拦截、存量不阻塞流水线；
3. 登记条目**已不再重复** ⇒ 红，且报错直接指向行动（「请删条目」）—— 防白名单变垃圾场。

## 出问题时怎么修

后合入的那个文件改名到**下一个空闲版本号**（约定：后合入者让号）。改名安全口径见 issue #3812：
`MigrationRunner` 仅以文件名判「已执行」（`applied.contains(filename)`），**不校验已记录文件是否仍存在**；
新号首跑为 `ADD COLUMN IF NOT EXISTS` 之类的幂等空操作。

⚠️ **禁止**为了「让 CI 绿」往 `KNOWN_DUPLICATE_VERSIONS` 加新条目 —— 那是把门禁变摆设。
"""
import re
from pathlib import Path

MIGRATION_DIR = (
    Path(__file__).resolve().parents[2]
    / "backend"
    / "admin-api"
    / "src"
    / "main"
    / "resources"
    / "db"
    / "migration"
)

# 存量同号迁移（burn-down 登记，见 issue #3813）：修一条删一条。
# 当前为 V29 ×2 / V33 ×2（均先于 #3812 存在）；V45 已由 #3812 改名让号。
KNOWN_DUPLICATE_VERSIONS = {"V29", "V33"}

_VERSION_RE = re.compile(r"^(V\d+)__")


def scan_duplicate_versions(filenames):
    """版本号 → 该号下的文件名列表（仅返回出现 >1 次的）。纯函数，便于注入式红证。"""
    grouped = {}
    for name in filenames:
        base = Path(name).name
        m = _VERSION_RE.match(base)
        if m:
            grouped.setdefault(m.group(1), []).append(base)
    return {v: sorted(fs) for v, fs in grouped.items() if len(fs) > 1}


def stale_baseline_entries(baseline, duplicates):
    """登记了、但当下已不重复的版本号 —— 销账未删，报错应指向「请删条目」。"""
    return sorted(v for v in baseline if v not in duplicates)


# ============== 注入式红证：判据必须能报出坏数据 ==============


def test_reports_injected_duplicate():
    """注入两个同号迁移 → 必须报出（证明下面的仓库断言不是空断言）。"""
    dup = scan_duplicate_versions(
        ["V45__a.sql", "V45__b.sql", "V46__c.sql", "README.md", "notes.txt"]
    )
    assert set(dup) == {"V45"}, dup
    assert dup["V45"] == ["V45__a.sql", "V45__b.sql"]


def test_no_false_positive_when_versions_unique():
    """版本号互不重复时不得误报（防恒红）。"""
    assert scan_duplicate_versions(["V44__a.sql", "V45__b.sql", "V46__c.sql"]) == {}


def test_stale_baseline_detected():
    """销账未删（清单里有、仓库里已不重复）→ 必须报出，且指向「删条目」。"""
    assert stale_baseline_entries(
        {"V45", "V29"}, {"V29": ["V29__a.sql", "V29__b.sql"]}
    ) == ["V45"]


def test_stale_baseline_quiet_when_all_present():
    """清单条目全部仍重复 → 不得误报。"""
    assert stale_baseline_entries({"V29"}, {"V29": ["V29__a.sql", "V29__b.sql"]}) == []


# ============== 仓库真实状态 ==============


def test_migration_files_follow_version_naming():
    """防空跑 + 命名约定：目录里每个 .sql 都必须能被 `V<n>__` 解析。

    若路径写错（目录不存在/空），本测试先红 —— 避免「什么都没扫到」却绿着通过。
    """
    assert MIGRATION_DIR.is_dir(), f"迁移目录不存在：{MIGRATION_DIR}"
    files = sorted(p.name for p in MIGRATION_DIR.glob("*.sql"))
    assert len(files) >= 20, f"迁移文件数异常（{len(files)}）—— 路径对吗？{MIGRATION_DIR}"

    unmatched = [f for f in files if not _VERSION_RE.match(f)]
    assert not unmatched, f"文件名不符合 V<n>__ 约定：{unmatched}"


def test_repo_has_no_unregistered_duplicate_versions():
    """新增同号迁移一律拦截；存量登记放行；登记销账未删即红。"""
    files = sorted(p.name for p in MIGRATION_DIR.glob("*.sql"))
    duplicates = scan_duplicate_versions(files)

    unregistered = sorted(v for v in duplicates if v not in KNOWN_DUPLICATE_VERSIONS)
    assert not unregistered, (
        "发现未登记的同号迁移："
        + "; ".join(f"{v} → {duplicates[v]}" for v in unregistered)
        + "。处置：后合入者改名到下一个空闲版本号（改名安全口径见 issue #3812）；"
        "禁止往 KNOWN_DUPLICATE_VERSIONS 加新条目来放行。"
    )

    stale = stale_baseline_entries(KNOWN_DUPLICATE_VERSIONS, duplicates)
    assert not stale, (
        f"登记已销账但条目未删：{stale} —— 该版本号已不再重复，"
        "请从 KNOWN_DUPLICATE_VERSIONS 删除对应条目（burn-down 见 issue #3813）"
    )
