# case_ids: MC-158
"""存量 `users.worker_pages` **不许回填追加页面键**（issue #8337 的用户裁定，2026-11-03）。

## 为什么要有这条守卫（裁定原文 + 两条理由）

issue #8337 给闭词表新增了 `inbound` / `reprint`（拍照入库 / 补打入库标签）。这两个键此前
「无键、恒显示」，于是最直觉的兼容做法是：**把两个键追加回存量非空 `worker_pages` 集**。
用户 2026-11-03 明确**否决**了这个做法，理由两条（照抄归档，别再发明第三条）：

1. **会反向打穿本单的判据 ③** —— 加回所有收窄集 ⇒ 车位工**重新**看得见入库/补打，
   等于「修了半天又修回去」；
2. **猜岗位 = 第二份会漂的真值** —— 靠「他以前看得见入库 ⇒ 他大概是仓管」推断岗位，
   是在代码里种一份没有真值源的默认值（同族先例：`WorkerPages.defaultPages()` 只许有一处）。

现行口径（本守卫保护的就是它）：**未收窄（`NULL`）= 零回退**（`defaultPages()` 已含两键）；
**收窄集 = 真值**（缺键即隐藏）；要开回来 = 管理员**显式**动作（面板勾上 ≤3 项 / 设岗位「仓管」自带三项）。
残余面如实登记：收窄只有管理员显式设过才会发生，处置是**两次点击**，不是数据损坏。

## 判据（两条 + 自证）

| # | 判据 | 回归时会怎么红 |
|---|---|---|
| 1 | `db/migration/**` 与 `db/migration-archive/**` 里**没有任何**对 `users.worker_pages` 的 **UPDATE**（数据回填的唯一形态） | 有人加一条 `UPDATE users SET worker_pages = worker_pages \\|\\| '["inbound"]'` ⇒ 具名报文件:行 |
| 2 | worker 包与 `WorkerAdminService` 里**没有**「读存量集 → 追加键 → 写回」的形态（`.add(INBOUND/REPRINT)` / `worker_pages \\|\\|` / `migrateLegacy` / `backfill`） | 有人写 `restrictedOrNull(...).add(WorkerPages.INBOUND)` ⇒ 具名报文件:行 |
| 3 | 判别力自证：两条谓词在**合成语料**上各自判红，且对**真语料**（本仓现状）为绿 | 谓词退化成恒真 / 恒假 ⇒ 红 |

## 边界（照实登记，§19.1）

① 判**源码形态**，判不了「有人绕到运维脚本 / 手工 SQL 去回填」（那不在本仓代码面）；
② `ALTER TABLE users ADD COLUMN` / `COMMENT ON COLUMN` 提到 `worker_pages` **不算**违规
（V152 就是这两句）—— 判的是**改写存量值的 UPDATE**；
③ 不改任何门禁的通过条件、不新增豁免；白名单**为空且必须为空**（要破例就改裁定，而不是加名单）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend" / "admin-api" / "src" / "main"
SQL_DIRS = [BACKEND / "resources" / "db" / "migration",
            BACKEND / "resources" / "db" / "migration-archive"]
JAVA_TARGETS = [
    BACKEND / "java" / "com" / "migao" / "admin" / "worker",
    BACKEND / "java" / "com" / "migao" / "admin" / "service" / "WorkerAdminService.java",
]

#: 白名单**必须为空**：要破例只能改 issue #8337 的裁定，不许在这里加名字。
BACKFILL_EXEMPTIONS: tuple[str, ...] = ()


def _strip_line_comments(sql: str) -> str:
    """去掉 `--` 行注释（保留行号对齐：逐行替换成空串，不做整段拼接）。

    🔴 必须有：迁移文件几乎都以注释开头（本仓每个迁移都有大段头注释）⇒ 不剥注释时
    「首个关键字是 UPDATE」的判定会被注释挡住 ⇒ 回填探针**静默变绿**（红证实测踩到）。
    """
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


def migration_backfill_violations(sql: str) -> list[str]:
    """SQL 语句级判定：含 `worker_pages` 的 **UPDATE** 语句 ⇒ 违规（V152 的 ALTER/COMMENT 不算）。"""
    problems: list[str] = []
    for statement in _strip_line_comments(sql).split(";"):
        lowered = statement.lower()
        if "worker_pages" not in lowered:
            continue
        # UPDATE 可能跨行（`UPDATE users\n  SET worker_pages = …`）⇒ 只看「首个关键字是 UPDATE」
        head = lowered.lstrip()
        is_update = re.match(r"update\s+\S+", head) is not None
        set_worker_pages = re.search(r"\bset\b[^;]*\bworker_pages\b", lowered, re.S) is not None
        if is_update and set_worker_pages:
            problems.append(statement.strip().splitlines()[0][:120])
    return problems


def java_backfill_violations(source: str) -> list[str]:
    """Java 形态判定：把页面键**追加**到存量集 / 写回存量的几种现实写法。"""
    patterns = [
        r"\.add\(\s*(?:WorkerPages\.)?(?:INBOUND|REPRINT)\s*\)",
        r"\.add\(\s*\"(?:inbound|reprint)\"\s*\)",
        r"worker_pages\s*\|\|",
        r"\bmigrateLegacy\w*\s*\(",
        r"\bbackfill\w*\s*\(",
    ]
    problems: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            line = source[: match.start()].count("\n") + 1
            problems.append(f"第 {line} 行命中 /{pattern}/：{match.group(0)}")
    return problems


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for directory in SQL_DIRS:
        if directory.is_dir():
            files.extend(sorted(directory.rglob("*.sql")))
    for target in JAVA_TARGETS:
        if target.is_dir():
            files.extend(sorted(target.rglob("*.java")))
        elif target.is_file():
            files.append(target)
    return files


def scan(files: list[Path]) -> list[str]:
    problems: list[str] = []
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in BACKFILL_EXEMPTIONS:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        found = (migration_backfill_violations(text) if path.suffix == ".sql"
                 else java_backfill_violations(text))
        problems.extend(f"{rel}: {item}" for item in found)
    return problems


def test_no_migration_and_no_service_layer_backfills_worker_pages() -> None:
    files = _iter_files()
    # 坐标自证：扫描面必须非空（否则本判据会退化成恒真）
    sql_files = [f for f in files if f.suffix == ".sql"]
    assert len(sql_files) >= 100, "迁移扫描面异常（找不到迁移文件）"
    # 坐标自证：既有那个**只做 DDL/COMMENT** 的迁移必须在扫描面里（否则扫错目录也会绿）
    assert any(f.name.startswith("V152__") for f in sql_files), "扫描面里没有 V152（worker_pages 的定义处）"
    assert any(f.suffix == ".java" for f in files), "Java 扫描面为空（WorkerPages / WorkerAdminService 未找到）"
    problems = scan(files)
    assert problems == [], (
        "发现「对存量 worker_pages 追加页面键」的写法 —— issue #8337 已裁定**禁止**：\n  "
        + "\n  ".join(problems)
        + "\n为什么禁止：① 会让车位工重新看得见入库/补打（反向打穿判据 ③）；"
          "② 猜岗位 = 第二份会漂的真值。正确出口 = 未收窄走 defaultPages() + 收窄按真值 + 管理员显式设岗位。"
    )


def test_the_predicates_are_discriminating() -> None:
    """判别力自证：合成语料上两条谓词**各自**判红；真语料为绿（同一份实现）。"""
    assert migration_backfill_violations(
        "UPDATE users SET worker_pages = worker_pages || '[\"inbound\"]'::jsonb\n"
        "  WHERE role = 'worker' AND worker_pages IS NOT NULL AND NOT (worker_pages ? 'inbound');"
    ), "UPDATE 回填形态未被识别 ⇒ 判据 1 是空断言"
    assert migration_backfill_violations(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS worker_pages JSONB;"
    ) == [], "把 DDL 误判成回填（V152 的合法形态被红 ⇒ 判据不可用）"
    assert java_backfill_violations(
        "stored = WorkerPages.normalizeStored(raw);\nstored.add(WorkerPages.INBOUND);\n"
    ), "读存量集再追加键的形态未被识别 ⇒ 判据 2 是空断言"
    assert java_backfill_violations("return WorkerPages.defaultPagesFor(position);") == [], (
        "把「按岗位带出默认菜单」（合法实现）误判成回填 ⇒ 判据不可用"
    )
    # 真语料（本仓现状）= 绿：与 test_no_migration_and_no_service_layer_backfills_worker_pages 同一份 scan()
    assert scan(_iter_files()) == []
