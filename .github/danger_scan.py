#!/usr/bin/env python3
"""danger_scan.py — PR 破坏性变更检测（安全门禁，fail-closed）

检测 PR（origin/main...HEAD）中的破坏性变更：
- BLOCK：新增/删除 workflow 文件、修改 workflow 且新增 secrets 引用（workflow 可携带 secrets 执行）
- BLOCK：已发布数据库迁移被修改/删除（迁移不可变，MigrationRunner 按序执行）；新增迁移命名非法
- BLOCK：修改 docs/sql/schema*.sql（表结构参考）但未同时新增迁移文件（DDL 与迁移脱节）
- WARN：批量删除文件（>=30）、修改生产部署文件、修改 workflow（无新增 secrets）

## 删除 workflow 的**人工确认通道**（`DANGER_ACK_DELETE`，#4295）

删除 workflow 会 BLOCK，但护栏文案说的是「需人工确认」—— 而**确认必须有落点**，
否则在 `enforce_admins=true` 的仓库里「删除任何 workflow」在机制上都不可能通过
（#4288 实测：`gh pr merge --admin` 被 GraphQL 拒、UI 也不提供绕过入口）。

故补一条**可留痕**的确认通道（不改无确认时的行为，逐字仍是 BLOCK）：

- `DANGER_ACK_DELETE`：逗号分隔的、**已被显式确认**可删除的 workflow 路径；`*` 表示全部。
- `DANGER_ACK_BY` / `DANGER_ACK_URL`：确认人登录名与确认评论链接（写进 JSON 留痕）。
- 取值由 `pr-check.yml` 的「Resolve workflow-deletion acks」步骤在**运行期**读 PR 评论得出：
  只有**仓库 owner** 自己发的、含 `/danger-ack delete-workflow <path>`（或 `... all`）的评论才算。
  ⚠️ 用评论而不是 label：#4288 实测 `gh run rerun` 复用**原始事件载荷**（label 快照是旧的）
  ⇒ label 方案重跑不生效；评论在运行期读 API，故 rerun 也能拿到最新确认。
- **fail-closed**：取不到评论 / API 失败 / 非 owner ⇒ 该变量为空 ⇒ 仍 BLOCK。

## 已发布迁移被**重写**的人工确认通道（`DANGER_ACK_MIGRATION`，#4936）

「迁移不可变」判据只看 **git 状态（M/D）**，**不认指纹账本** ⇒ 经维护者裁定的合并重写
（#4936：5 条**从未在任何环境成功应用过**的迁移 V102~V106 合并为单条 V102）**结构性过不了 CI**
（本地实测 5 处 blocker），而既有确认通道只覆盖 workflow 删除。故补一条**同形**的通道，
但 ack **不足以**放行 —— 必须同时过**四道**交叉校验（否则就是「把护栏换成开关」）：

- marker：`/danger-ack rewrite-migration <V###>`（或 `... all`），**只有仓库 owner** 的评论算数。
- `DANGER_ACK_MIGRATION` / `DANGER_ACK_MIGRATION_BY` / `DANGER_ACK_MIGRATION_URL`：
  已确认的版本号（逗号分隔）/ 确认人 / 确认评论链接。取值同样由 `--resolve-acks` 在运行期
  从 PR 评论解析（**改动清单由脚本自己 `git diff --diff-filter=MD` 算**，不依赖新环境变量）。
- **交叉校验**（`verify_migration_acks()`；scan 模式**重跑一遍**，不只信环境变量）：
  ① `tests/unit_ci_workflows/migration_fingerprints.json` 必须**同批**被修改（diff 状态 `M`）；
  ② 修改型：账本里该文件名的 sha256 必须等于**磁盘当前** sha256（自己算，不信账本）；
  ③ 删除型：账本里**不得**还留着该文件名（须同批删除）；
  ④ ack 与改动集合一一对应（ack 了没改的版本不算数；改了没 ack 的照旧 BLOCK，逐个报）。
- **fail-closed**：无 ack / 非 owner / 评论读取失败 / 账本没改 / 哈希不符 ⇒ 照旧 BLOCK，
  且无 ack 时的行为与补通道前**逐字相同**。

用法（由 pr-check 的 danger-scan job 调用）：
    python3 .github/danger_scan.py
输出：danger-scan-result.json（JSON）+ 控制台报告；存在 blocker 时 exit 1。
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

BASE = os.environ.get("DANGER_BASE", "origin/main")
BULK_DELETE_THRESHOLD = 30

# 迁移文件的**两个**载体目录（issue #5243）：历史链（V1 … V114）整链归档到
# `migration-archive/`（只读、逐字节冻结，账本 = migration_fingerprints.json），
# `migration/` 此后只放**未来的**增量迁移。**两个都要扫** —— 只看归档 ⇒
# 「已发布迁移只增不改 / 不得破坏性 DDL」的判定对**将来**失效；只看活目录 ⇒
# 今天扫不到任何文件（门禁空转 = 假绿）。**判据强度一字未改**，只是扫描面变成两个目录。
MIGRATION_DIRS = (
    "backend/admin-api/src/main/resources/db/migration-archive",
    "backend/admin-api/src/main/resources/db/migration",
)
#: 活目录（新迁移该放这儿 —— 提示文案用）
LIVE_MIGRATION_DIR = MIGRATION_DIRS[1]
#: 兼容既有引用（= 归档目录；账本与测试都以它为锚）
MIGRATION_DIR = MIGRATION_DIRS[0]
SCHEMA_FILES = ("backend/admin-api/src/main/resources/db/init/schema.sql", "docs/sql/archive/schema_full.sql")
MIGRATION_RE = re.compile(r"^V\d+__.*\.sql$")

# workflow 目录（**整目录**为扫描范围，不再写 `*.yml` glob）。
# 为什么（2026-09-17 实测的免检口子）：原 scope 写死 `.github/workflows/*.yml`，而 Actions
# **同时**识别 `.yaml` —— 新增一个 `.github/workflows/evil.yaml` 不在任何一条扫描线里
# （workflow 变更、批量删除、部署文件三条判定都看不到它）⇒ danger_scan 报
# 「✅ 0 blocker / 0 warning」而安全审查该拦的东西**根本没进视野**。
# 故按目录取全量，再用「Actions 实际会执行的后缀」过滤 —— 这是「workflow 文件」的定义，
# 不是白名单；未识别的后缀（如 README.md）不属于可执行 workflow，不参与判定。
WORKFLOW_DIR = ".github/workflows"
WORKFLOW_SUFFIXES = (".yml", ".yaml")

SECRET_REF_RE = re.compile(r"secrets\.([A-Za-z0-9_]+)")


def strip_comment(line):
    """剥离 YAML / shell 的**行内注释**，返回该行的「代码部分」（issue #5268）。

    根因（本函数存在的唯一理由）：secrets 判据原先有两把**不同源**的尺子 ——
    前置筛选用子串 `"secrets." in l`、真正判定用 `SECRET_REF_RE`。注释里写通配点
    `secrets.*`（或完整 secret 名）时子串命中、正则不命中 ⇒ `_truly_new_secret_lines()`
    里 `added_refs` 为空集，而旧条件 `if added_refs and added_refs <= removed_refs`
    因**左侧空集短路为假** ⇒ 该注释行被当成「真新增」⇒ BLOCK 合并。
    现场（PR #5266 / commit f472f5fa1）：那句注释本身在说明「没有新增 secrets」。
    owner 裁定：**注释里写完整 secret 名也不算风险** ⇒ 判据一律建立在剥掉注释后的代码文本上。

    启发式（与边界，逐条写明）：
      · `#` 在**行首**（允许前导空白）或**前面是空白字符**时 = 注释起点，其后整体丢弃 ——
        与 YAML / shell 的实际规则同形（`foo#bar`（`#` 前无空白）两门语言都不算注释起点；
        shell 的参数展开 `${VAR#prefix}` 同理不会被误剥）。
      · **引号内**（单/双引号）的 `#` **不是**注释起点：`run: echo "#${{ secrets.X }}"` 的 `#`
        在双引号内 ⇒ 该行的真引用**必须仍然被检出**（朴素 `line.split("#")[0]` 会把这一行
        剥成 `run: echo "` ⇒ 真引用漏检，属**放宽真检**，判据④用注入式红证钉住）。
      · 双引号内 `\\` 转义下一个字符（YAML / shell 同此）；单引号内 `\\` 是字面量、不转义。
      · **边界（有意取舍，不是完整 YAML 解析）**：① 不做块标量（`|` / `>`）状态机 ——
        块标量正文里的 `#` 按同一条空白规则处理；② 引号未闭合（如正文里的孤立单引号 `it's`）
        ⇒ 保守地**不剥**该行 ⇒ 判定偏严；③ 只处理单行注释，不做跨行字符串判定。
        ①②③ 全都朝向「不放宽真检」（多看一眼 vs. 漏检），与门禁 fail-closed 的方向一致。
    """
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2  # 双引号内转义下一个字符
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
        i += 1
    return line

# ── 删除 workflow 的确认 marker（#4295）────────────────────────────────────────
# 判据必须落在**这个纯函数**上，而不是 workflow 里的字符串匹配：
# 首版把判据写成「脚本里含 user.login 且含 DANGER_OWNER」—— 红证实测**不红**
# （同一脚本另一条取 ACK_URL 的 gh api 也含这两个词，把 owner 过滤整条删掉照样绿）。
# 空断言形态（`migao-acceptance`）：断言的东西不是"决定放行的那个表达式"。
ACK_MARKER = "/danger-ack delete-workflow"

# ── 已发布迁移被**重写**的确认 marker（#4936）──────────────────────────────────
# 与删除 workflow **同形**（同源 owner / 同源评论读取 / 同源 fail-closed），但 ack 本身
# 不足以放行 —— 放行还要过 `verify_migration_acks()` 的交叉校验（见模块 docstring）。
MIGRATION_ACK_MARKER = "/danger-ack rewrite-migration"
# 已发布迁移的内容指纹账本（issue #4235）：`{文件名: "sha256:..."}`。
# 本通道要求它与迁移改动**同批更新** —— 否则 `test_migration_immutability.py` 那条独立
# 护栏仍会判红（两条门禁必须一致：不能一条绿、一条红）。
LEDGER_PATH = "tests/unit_ci_workflows/migration_fingerprints.json"
# 账本/迁移文件的读取锚点 = **仓库根**（由本文件位置反推，与 cwd 无关）：
# 判据落点的文件必须真能被读到，否则「读不到账本」会被静默读成「账本没问题」。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MIGRATION_ACK_RE = re.compile(re.escape(MIGRATION_ACK_MARKER) + r"\s+([Vv]\d+|all)\b")
_MIGRATION_VERSION_RE = re.compile(r"[Vv](\d+)")


def migration_version(path_or_token):
    """文件名 / 版本 token → 规范化版本号（`V102`；`v102`、`V0102` 亦归一）。无版本 ⇒ None。"""
    name = str(path_or_token or "").rsplit("/", 1)[-1]
    m = _MIGRATION_VERSION_RE.match(name)
    return f"V{int(m.group(1))}" if m else None


def parse_delete_acks(comments, owner, deleted_paths):
    """从 PR 评论里解析「已确认可删除」的 workflow 路径。纯函数。

    规则（只有 owner 本人发的评论算数）：
      · `/danger-ack delete-workflow <path>` —— 确认**该路径**；
      · `/danger-ack delete-workflow all`   —— 一次确认**全部**（展开为 deleted_paths）。

    Args:
        comments: PR 评论对象列表（REST `/issues/{n}/comments` 的形状，可含 `user.login`/`body`/`html_url`）
        owner:    确认人登录名；**只有**该账号的评论被采信（其他人评论一律忽略）
        deleted_paths: 本次被删除的 workflow 路径列表

    Returns:
        (acked_paths: set[str], via_url: str) —— via_url 是**最后一条**采信评论的链接（留痕用）；
        无命中时返回 (set(), "")。
    """
    bodies, last_url = [], ""
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        if ((c.get("user") or {}).get("login") or "") != owner or not owner:
            continue
        body = c.get("body") or ""
        bodies.append(body)
        last_url = c.get("html_url") or last_url
    if not bodies:
        return set(), ""

    acked = set()
    all_acked = any(f"{ACK_MARKER} all" in b for b in bodies)
    for path in deleted_paths or []:
        if all_acked or any(f"{ACK_MARKER} {path}" in b for b in bodies):
            acked.add(path)
    return acked, (last_url if acked else "")


def ack_env_lines(acked, owner, via_url):
    """把解析结果格式化成可直接 `>> $GITHUB_ENV` 的行（空 ⇒ danger_scan 仍 BLOCK）。"""
    return [
        f"DANGER_ACK_DELETE={','.join(sorted(acked))}",
        f"DANGER_ACK_BY={owner if acked else ''}",
        f"DANGER_ACK_URL={via_url if acked else ''}",
    ]


def parse_migration_acks(comments, owner, changed_migrations):
    """从 PR 评论里解析「已确认可重写」的迁移版本号。纯函数。

    规则（只有 owner 本人发的评论算数，与 `parse_delete_acks` 同源）：
      · `/danger-ack rewrite-migration V102` —— 确认**该版本**（大小写不敏感：`v102` 亦算）；
      · `/danger-ack rewrite-migration all`  —— 一次确认 `changed_migrations` 的**全部**版本。

    ⚠️ ack **不等于**放行：本函数只负责解析；放行还要过 `verify_migration_acks()` 的交叉校验。

    Args:
        comments: PR 评论对象列表（REST `/issues/{n}/comments` 形状，含 `user.login`/`body`/`html_url`）
        owner:    确认人登录名；**只有**该账号的评论被采信
        changed_migrations: 本次被修改/删除的迁移文件路径列表（`all` 展开为它们的版本号集合）

    Returns:
        (acked_versions: set[str], via_url: str) —— 版本号已规范化为 `V###`；
        无命中时返回 (set(), "")。
    """
    versions = {}
    for path in changed_migrations or []:
        v = migration_version(path)
        if v:
            versions[v] = path
    bodies, last_url = [], ""
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        if ((c.get("user") or {}).get("login") or "") != owner or not owner:
            continue
        bodies.append(c.get("body") or "")
        last_url = c.get("html_url") or last_url
    if not bodies:
        return set(), ""

    tokens = {m.group(1) for b in bodies for m in _MIGRATION_ACK_RE.finditer(b)}
    if any(t.lower() == "all" for t in tokens):
        acked = set(versions)
    else:
        acked = {migration_version(t) for t in tokens} & set(versions)
    return acked, (last_url if acked else "")


def migration_ack_env_lines(acked, owner, via_url):
    """迁移 ack → `>> $GITHUB_ENV` 行（与 `ack_env_lines` 同形；独立函数以免动既有三行的形状）。"""
    return [
        f"DANGER_ACK_MIGRATION={','.join(sorted(acked))}",
        f"DANGER_ACK_MIGRATION_BY={owner if acked else ''}",
        f"DANGER_ACK_MIGRATION_URL={via_url if acked else ''}",
    ]


def verify_migration_acks(acked_versions, migration_changes, ledger_changed,
                          ledger_entries, disk_hashes):
    """**交叉校验**（本通道的灵魂）：ack 不足以放行。纯函数。

    ack 只证明「维护者点了头」，**不**证明指纹账本跟上了。四条判据（任一不满足 ⇒ 该版本不放行）：

    ① **账本同批更新**：`LEDGER_PATH` 本次 diff 必须是 `M` —— 否则 ack 只是口头授权，
       而 `tests/unit_ci_workflows/test_migration_immutability.py` 那条独立护栏仍会因
       「已登记文件被改」判红（两条门禁必须一致）。
    ② **账本与磁盘一致**（仅修改型）：账本里该文件名的 sha256 必须**等于磁盘当前 sha256**
       （自己算，不信账本）—— 防「ack 了但忘了登记新指纹」。
    ③ **删除型**：账本里**不得**还留着该文件名（须同批删掉账本条目）。
    ④ **一一对应**：ack 了本次没改的版本 ⇒ 不算数（不放行任何东西，也不报错）。

    Args:
        acked_versions:    `parse_migration_acks()` 的结果（规范化版本号集合）
        migration_changes: `[(status, path)]`（`_git_name_status` 形状）
        ledger_changed:    账本本次是否被修改（`M`）
        ledger_entries:    账本内容 `{文件名: "sha256:..."}`；**None ⇒ 读不到 ⇒ fail-closed**
                           （与 `{}`「账本里没有条目」严格区分，§19.1 同族）
        disk_hashes:       磁盘当前指纹 `{文件名: "sha256:..."}`（调用方算好，便于注入测试）

    Returns:
        (granted_versions: set[str], problems_by_version: dict[str, str])
    """
    granted, problems = set(), {}
    changed = {}
    for status, path in migration_changes or []:
        v = migration_version(path)
        if v and status[0] in ("M", "D"):
            changed.setdefault(v, (status[0], path))
    entries = ledger_entries if isinstance(ledger_entries, dict) else None
    for v in sorted(acked_versions or []):
        if v not in changed:
            continue  # ④ 本次没改的版本：ack 不算数（不报错，也不放行任何东西）
        status, path = changed[v]
        name = path.rsplit("/", 1)[-1]
        if not ledger_changed:
            problems[v] = f"ack 必须与指纹账本同批更新 —— {LEDGER_PATH} 本次 diff 状态不是 M"
            continue
        if entries is None:
            problems[v] = f"无法读取指纹账本 {LEDGER_PATH}（fail-closed，不得按「账本没问题」放行）"
            continue
        if status == "D":
            if name in entries:
                problems[v] = f"已 ack 删除，但账本仍留有该文件名 {name} —— 须同批删除账本条目"
                continue
        else:
            ledger_fp = entries.get(name)
            disk_fp = (disk_hashes or {}).get(name)
            if not ledger_fp:
                problems[v] = f"账本无 {name} 条目 ⇒ 先跑 --write-ledger 登记新指纹"
                continue
            if not disk_fp:
                problems[v] = f"无法读取磁盘上的 {name}（fail-closed）"
                continue
            if ledger_fp != disk_fp:
                problems[v] = (f"账本哈希与磁盘不符 ⇒ 先跑 --write-ledger 登记新指纹"
                               f"（账本 {ledger_fp} / 磁盘 {disk_fp}）")
                continue
        granted.add(v)
    return granted, problems


def _repo_file(rel_path):
    """仓内相对路径 → 绝对路径（锚在**仓库根**，与 cwd 无关）。"""
    return REPO_ROOT / rel_path


def _sha256_of(rel_path):
    """仓内文件的 sha256（内容指纹，与账本 `fingerprint()` 同形）；读不到 ⇒ ""（fail-closed）。"""
    try:
        return "sha256:" + hashlib.sha256(_repo_file(rel_path).read_bytes()).hexdigest()
    except Exception:
        return ""


def _read_ledger_entries():
    """读指纹账本 → {文件名: 指纹}；读不到 / 结构不对 ⇒ None（fail-closed）。"""
    try:
        entries = json.loads(_repo_file(LEDGER_PATH).read_text(encoding="utf-8")).get("migrations")
    except Exception as exc:  # noqa: BLE001 —— 任何异常都必须 fail-closed
        print(f"⚠️ 迁移指纹账本读取失败（{exc}）⇒ 迁移 ack 交叉校验 fail-closed", file=sys.stderr)
        return None
    return entries if isinstance(entries, dict) else None


def _git_name_status_all_migrations():
    """两个载体目录的迁移变更清单；**任一目录取证失败 ⇒ `None`**（fail-closed）。"""
    out = []
    for d in MIGRATION_DIRS:
        changes = _git_name_status(d + "/*.sql")
        if changes is None:
            return None
        out.extend(changes)
    return out


def _blob_sha256_at_base(rel_path, base=BASE):
    """`<base>:<rel_path>` 的 blob sha256；取不到 ⇒ `None`（**fail-closed**：判不了「同一份内容」）。

    用 **merge-base 的 blob** 而不是账本指纹：账本可能没被同批重生成，
    那样「是不是同一份内容」的判据就会跟着账本一起腐烂。
    """
    try:
        proc = subprocess.run(["git", "show", f"{base}:{rel_path}"],
                              capture_output=True, check=False)
    except Exception:  # noqa: BLE001 —— 取证失败一律 fail-closed（不得当成「内容相同」）
        return None
    if proc.returncode != 0:
        return None
    return "sha256:" + hashlib.sha256(proc.stdout).hexdigest()


def split_migration_moves(migration_changes, base=BASE):
    """把 `D` 拆成「**逐字节一致的归档移动**」与「真删除」。**纯函数**（便于注入式自证）。

    ## 为什么需要它（issue #5243 实测）

    迁移链整链归档是一次 `git mv`（116 条，内容逐字节未变），但 `_git_name_status` 是
    **按目录分片**跑的：

      · 片 = `migration-archive/*.sql` ⇒ 那些路径在 base 上不存在 ⇒ 全部报 **`A`**；
      · 片 = `migration/*.sql` ⇒ HEAD 上只剩活目录那几条 ⇒ 全部报 **`D`**。

    git **配不出** old↔new（旧路径被第二片的 pathspec 滤掉了）⇒ 纯搬家被读成「116 条已发布迁移被删除」。
    实测：116 处 blocker，整条 PR 被卡死。**但并没有任何内容被改写** —— 用 ack 放行 116 次「删除」，
    在审计上等于「owner 批准删除已发布迁移」，是**错误先例**。

    ## 判据（**同时**满足才认作搬家，否则照旧算真删除 ⇒ blocker）

      ① 该 `D` 路径的文件名在**另一个**迁移载体目录里存在；
      ② 那份文件的内容与 **merge-base 上原路径的 blob** sha256 **逐字节相同**。

    ⇒ 改内容再搬（哈希不符）= **重写已发布迁移** ⇒ 照旧 BLOCK；删掉且无同名归档件 = 真删除 ⇒ 照旧 BLOCK。

    Returns:
        `(kept, moves)`：`kept` = 仍按原判据处理的 `[(status, path)]`（含 `M` / `A` / **真删除**）；
        `moves` = `[(status, old_path, new_path)]`（已确认是同一份文件的搬家）。
    """
    kept, moves = [], []
    for status, path in migration_changes or []:
        if status[0] != "D":
            kept.append((status, path))
            continue
        name = path.rsplit("/", 1)[-1]
        counterpart = None
        for d in MIGRATION_DIRS:
            if path.startswith(d + "/"):
                continue  # 同一个载体目录内部的重名不算搬家
            cand = f"{d}/{name}"
            if _repo_file(cand).is_file():
                counterpart = cand
                break
        if counterpart and _sha256_of(counterpart) == _blob_sha256_at_base(path, base):
            moves.append((status, path, counterpart))
        else:
            kept.append((status, path))
    return kept, moves


def _changed_migration_paths():
    """本次被**修改/删除**的迁移文件路径；取证失败 ⇒ `[]`（= 无可确认项）。

    与 workflow 侧不同：本通道**不新增环境变量**承载这份清单 —— `--resolve-acks` 自己算，
    少一个「调用方忘了传 ⇒ 静默永不确认」的失效面。
    """
    changes = _git_name_status_all_migrations()
    if changes is None:
        return []
    # ⚠️ issue #5243：**搬家不算改动**（见 `split_migration_moves`）—— 否则一次整链归档
    # 会要求 owner 逐个 ack 116 次「删除」，在审计上留下「批准删除已发布迁移」的错误先例。
    # 真改写 / 真删除仍照旧进这份清单（通道原样保留）。
    kept, _moves = split_migration_moves(changes)
    return [p for s, p in kept if s[0] in ("M", "D")]


def resolve_acks_main():
    """`--resolve-acks` 模式：读评论 JSON → 打印 GITHUB_ENV 行（由 pr-check 的 ack 步骤调用）。

    fail-closed：文件缺失 / JSON 非法 / owner 为空 ⇒ 打印空 DANGER_ACK_DELETE（仍 BLOCK）。
    """
    owner = os.environ.get("DANGER_OWNER", "").strip()
    deleted = [p.strip() for p in os.environ.get("DANGER_DELETED_WORKFLOWS", "").split(",") if p.strip()]
    comments = []
    path = os.environ.get("DANGER_COMMENTS_JSON", "")
    try:
        with open(path) as f:
            raw = json.load(f)
        # `gh api --paginate --slurp` 产出「页数组的数组」；单页时也可能就是评论数组
        if isinstance(raw, list) and raw and isinstance(raw[0], list):
            comments = [c for page in raw for c in page]
        elif isinstance(raw, list):
            comments = raw
    except Exception as exc:  # noqa: BLE001 —— 任何异常都必须 fail-closed
        print(f"⚠️ 评论 JSON 读取失败（{exc}）⇒ fail-closed", file=sys.stderr)
        comments = []
    owner_n = sum(
        1 for c in comments
        if isinstance(c, dict) and ((c.get("user") or {}).get("login") or "") == owner and owner
    )
    acked, via = parse_delete_acks(comments, owner, deleted)
    for line in ack_env_lines(acked, owner, via):
        print(line)
    # 迁移重写通道（#4936）：改动清单由脚本自己算（不依赖新环境变量）
    changed_migrations = _changed_migration_paths()
    mig_acked, mig_via = parse_migration_acks(comments, owner, changed_migrations)
    for line in migration_ack_env_lines(mig_acked, owner, mig_via):
        print(line)
    # **心跳**（§18.6「环境静默即缺陷」）：本通道的静默失效形态是「读不到评论 ⇒ 永远不放行」，
    # 命令行恒打「评论总数 / owner 评论数」——owner 评论数长期为 0 就能立刻看出通道没用上，
    # 而不是等到有人要重写迁移才发现（fail-closed 的反面是红得无声无息）。
    print(
        f"── 评论总数={len(comments)} / owner({owner or '未设置'}) 评论数={owner_n}"
        f" / 待确认={len(deleted)} / 已确认={sorted(acked) or '（无）'} ──",
        file=sys.stderr,
    )
    print(
        f"── 迁移 ack：待确认={len(changed_migrations)} / 已确认={sorted(mig_acked) or '（无）'}"
        f" / 交叉校验（账本同批更新 + 哈希一致）在 scan 模式**重跑** ──",
        file=sys.stderr,
    )


def _truly_new_secret_lines(added_lines, removed_lines):
    """从 diff 的 added/removed 行中筛出「真正新增」的 secrets 引用行。

    修复（issue #2949 实证）：把 workflow 里已有的 secrets 引用行从一处移到另一处
    （如 admin-api 的 docker login 从 build 步骤拆为独立 login 步骤）时，
    git diff 显示为「删除一行 + 新增一行」，但引用的 secrets 标识符集合相同——
    这是移动而非新增，不应 BLOCK 合并。

    修复（issue #5268，owner 裁定「注释一律不算风险，哪怕写了完整 secret 名」）：判据一律
    建立在 `strip_comment()` 剥掉注释后的**代码文本**上，且与前置筛选
    （`_secret_ref_diff_lines`）**同源**（都用 `SECRET_REF_RE`）。修前两把尺子不同源
    （筛选=子串 / 判定=正则）⇒ 注释里的 `secrets.*` 通过了筛选却拿不到 added_refs，
    而 `if added_refs and added_refs <= removed_refs` 因左侧空集短路为假 ⇒ 注释行进 blockers。

    判定（剥注释后）：
      · `added_refs` 为空集 ⇒ **跳过**（注释行 / 无真引用 ⇒ 注释一律不进 blockers，#5268）；
      · 某新增行引用的每个 secret 名都已在删除行中出现过 → 移动，跳过（#2949 口径**一字未动**）；
      · 若引用了删除行中不存在的 secret 名（或删除行无 secret）→ 真新增，保留。
    保守策略：新增行若混入一个真新 secret（其余为移动），整行保留待人工审查。
    返回值给的是**原始 diff 行**（含注释），保证 blocker 文案里的证据不被改写。
    """
    removed_refs = set()
    for line in removed_lines:
        removed_refs.update(SECRET_REF_RE.findall(strip_comment(line)))
    truly_new = []
    for line in added_lines:
        added_refs = set(SECRET_REF_RE.findall(strip_comment(line)))
        if not added_refs:
            continue  # 剥注释后没有真引用 ⇒ 注释行不算新增（issue #5268）
        if added_refs <= removed_refs:
            continue  # 引用的 secret 都是移动过来的，非新增（issue #2949）
        truly_new.append(line)
    return truly_new


def analyze(workflow_changes, wf_new_secrets, deleted_files, deploy_files, migration_changes, schema_changes, trusted_actor=False, delete_acked=frozenset(),
            migration_acked=frozenset(), migration_ack_by="", migration_ack_url="",
            ledger_changed=False, ledger_entries=None, disk_hashes=None):
    """纯函数：对变更清单做安全判定。返回 (blockers, warnings)。

    Args:
        workflow_changes: [(status, path)]，status ∈ A/M/D/R
        wf_new_secrets:   {path: [新增的含 secrets 的 diff 行]}
        deleted_files:    删除的文件路径列表
        deploy_files:     deploy/ 或 scripts 下被改动的文件列表
        migration_changes: db/migration/*.sql 的 [(status, path)]
        schema_changes:    docs/sql/schema*.sql 的 [(status, path)]
        delete_acked:     **已被显式确认**可删除的 workflow 路径集合（`"*"` = 全部）。
                          为空 ⇒ 删除 workflow 一律 BLOCK（与 #4295 之前**逐字相同**）。
        migration_acked:  **已被显式确认**可重写的迁移版本号集合（如 `{"V102"}`）。
                          为空 ⇒ 修改/删除迁移一律 BLOCK（与 #4936 之前**逐字相同**）。
        migration_ack_by / migration_ack_url: 确认人与确认评论链接（写进 WARN 文案留痕）。
        ledger_changed:   指纹账本本次是否被修改（`M`）—— ack 的必要前提之一。
        ledger_entries:   账本内容；None ⇒ 读不到 ⇒ fail-closed。
        disk_hashes:      磁盘当前指纹；由调用方算好（便于注入测试）。
                          后四项一起喂给 `verify_migration_acks()`（交叉校验的唯一判据源）。
    """
    blockers = []
    warnings = []

    for status, path in workflow_changes:
        if status == "A":
            if trusted_actor:
                warnings.append(f"新增 workflow 文件 {path}（维护者添加，仍建议人工复核）")
            else:
                blockers.append(f"新增 workflow 文件 {path} —— 需人工安全审查（workflow 可携带 secrets 执行）")
        elif status == "D":
            if path in delete_acked or "*" in delete_acked:
                # 已由维护者显式确认（见模块 docstring 的确认通道）——降级为 WARN 并留痕。
                warnings.append(f"删除 workflow 文件 {path}（**已由维护者显式确认**，见 danger-scan-result.json 的 acks）")
            else:
                blockers.append(
                    f"删除 workflow 文件 {path} —— 需人工确认"
                    f"（维护者评论 `/danger-ack delete-workflow {path}` 后重跑本检查；"
                    "或 `/danger-ack delete-workflow all` 一次确认全部）"
                )
        elif status[0] in ("M", "R"):
            new_sec = wf_new_secrets.get(path, [])
            real_sec = [l for l in new_sec if "secrets.GITHUB_TOKEN" not in l]
            if real_sec:
                blockers.append(
                    f"{path} 新增 {len(real_sec)} 处非内置 secrets 引用 —— 需人工审查：{real_sec[0].strip()[:80]}"
                )
            else:
                warnings.append(f"修改 workflow {path} —— 建议人工复核")

    # ---- 迁移不可变（R1）：已发布迁移只增不改；新增迁移命名须 V{n}__desc.sql ----
    # R100 豁免（issue #3812 让号场景）：git 对「纯改名」报 status R100（相似度 100%）。
    # 后合入者撞号时按「后合入者让号」约定 rename 到下一个空闲版本号（V45__x → V46__x）：
    #   · SQL 内容零变化（git 判定相似度 100%）—— 不是「修改已发布迁移」；
    #   · 线上 schema_migrations 保留旧文件名记录（历史事实不改写），新名首跑为幂等空操作
    #     （如 ADD COLUMN IF NOT EXISTS），改名安全（MigrationRunner 仅以文件名判已执行）。
    # 判据收紧（防让号豁免变成改迁移的口子）：只有 status == "R100" 才豁免；
    # rename 但内容有变化（R0xx）＝修改已发布迁移，照旧 BLOCK（fail-closed，§19.1 同族）。
    new_migrations = [p for s, p in migration_changes if s == "A"]
    # 迁移重写确认通道（#4936）：ack **不足以**放行 —— 先过交叉校验（账本同批更新 + 哈希一致）。
    # 判据落在这个纯函数上（同 #4295 的教训：判据不许落在「决定放行的那个表达式」之外）。
    migration_granted, ack_problems = verify_migration_acks(
        migration_acked, migration_changes, ledger_changed, ledger_entries, disk_hashes)
    for status, path in migration_changes:
        name = path.rsplit("/", 1)[-1]
        if status == "A":
            if not MIGRATION_RE.match(name):
                blockers.append(
                    f"新增迁移文件名非法 {path} —— 必须为 V{{n}}__desc.sql（MigrationRunner 按文件名排序执行）"
                )
        elif status == "R100":
            if not MIGRATION_RE.match(name):
                blockers.append(
                    f"迁移改名后文件名非法 {path} —— 必须为 V{{n}}__desc.sql（MigrationRunner 按文件名排序执行）"
                )
            else:
                warnings.append(
                    f"迁移纯改名（让号）{path} —— R100 内容零变化（issue #3812 后合入者让号），"
                    f"新名首跑应为幂等空操作；请人工确认"
                )
        elif status[0] in ("M", "D") and migration_version(path) in migration_granted:
            # 已由维护者显式确认 **且** 交叉校验通过 —— 降级为 WARN 并留痕。
            warnings.append(
                f"已发布迁移被修改/删除 {path}（**已由维护者显式确认**，确认人 "
                f"{migration_ack_by or '(unknown)'}，见 {migration_ack_url or '(unknown)'}；"
                f"账本哈希一致：{LEDGER_PATH} 同批更新）—— 见 danger-scan-result.json 的 acks"
            )
        else:
            msg = (
                f"已发布迁移被修改/删除 {path} —— 迁移不可变（MigrationRunner 按序执行，"
                f"改动会导致线上 DB 与代码脱节），只能新增 V{{n+1}}__ 迁移"
            )
            v = migration_version(path)
            if v in ack_problems:
                msg += f"（已 ack 但交叉校验未通过：{ack_problems[v]}）"
            blockers.append(msg)

    # ---- DDL 与迁移同步（R2）：改表结构参考必须伴随迁移 ----
    # 豁免 A（comment_only）：schema 文件只改**注释/文档**（新增行里没有任何 DDL 语句）。
    #   背景（issue #3270 实证假 blocker）：给 schema_full.sql 加废弃标注（纯注释）也被判
    #   「改了表结构未加迁移」—— 规则本意是「结构变更需迁移」，注释不改变结构。
    #   判定前剥掉行尾 `--` 注释，避免注释里提到 CREATE TABLE 被误当成 DDL。
    # 豁免 B（bootstrap_alignment）：schema.sql 只**补齐**迁移链已创建的表（bootstrap 对齐），
    #   而非新增/修改表结构 —— 此时**不应**新建迁移（迁移链才是 schema 事实源，再建迁移是反向漂移）。
    #   判定：diff 里新增的 CREATE TABLE 表名全部能在现有迁移文件中找到定义。
    #   背景（issue #3270 三次踩坑）：schema.sql 与迁移链双源漂移，补表对齐是修复而非变更。
    _ddl_re = re.compile(
        r"\b(?:CREATE|ALTER|DROP|RENAME)\s+(?:TABLE|COLUMN|INDEX|CONSTRAINT|VIEW|SEQUENCE|TYPE)\b",
        re.I,
    )
    comment_only = False
    bootstrap_alignment = False
    if schema_changes and not new_migrations:
        added_tables = set()
        added_ddl_lines = []
        # fail-closed：diff 拿不到（BASE 错/非 git 仓库/无变更）时**不得**据此判定
        # "只是注释" —— 否则门禁会被静默绕过（安全门禁的失效方向必须是"报错"而非"放行"）。
        diff_ok = True
        added_line_seen = False
        for f in schema_changes:
            diff = ""
            try:
                proc = subprocess.run(
                    ["git", "diff", BASE, "--", f],
                    capture_output=True, text=True, check=False)
                if proc.returncode == 0:
                    diff = proc.stdout
                else:
                    diff_ok = False
            except Exception:
                diff_ok = False
            for line in diff.splitlines():
                if not line.startswith("+") or line.startswith("+++"):
                    continue  # 只看新增行（`+++` 是文件头）
                added_line_seen = True
                body = re.sub(r"--.*$", "", line[1:])  # 剥行尾注释再判定
                if _ddl_re.search(body):
                    added_ddl_lines.append(body.strip())
                m = re.match(
                    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.]+)",
                    body.strip(), re.I)
                if m:
                    added_tables.add(m.group(1).lower())
        # 只有「diff 读取成功 + 确实看到新增行 + 无任何 DDL」才认定纯注释改动
        comment_only = diff_ok and added_line_seen and not added_ddl_lines
        if added_tables:
            try:
                mig_files = "".join(
                    subprocess.run(["git", "ls-files", d], capture_output=True, text=True,
                                   check=False).stdout
                    for d in MIGRATION_DIRS)
            except Exception:
                mig_files = ""
            all_migration_sql = ""
            for mf in mig_files.split():
                try:
                    all_migration_sql += pathlib.Path(mf).read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
            known = {m.group(1).lower() for m in re.finditer(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.]+)",
                all_migration_sql, re.I)}
            if added_tables and added_tables <= known:
                bootstrap_alignment = True

    if schema_changes and not new_migrations and not bootstrap_alignment and not comment_only:
        blockers.append(
            f"修改了表结构参考 {SCHEMA_FILES[0]}/{SCHEMA_FILES[1]} 但未新增迁移文件 —— "
            f"请新增 {LIVE_MIGRATION_DIR}/V{{n}}__xxx.sql 并保证幂等（IF NOT EXISTS / ADD COLUMN IF NOT EXISTS）"
        )
    elif comment_only:
        warnings.append(
            "schema 文件仅改动注释/文档（新增行无 DDL）—— 非结构变更，无需迁移"
        )
    elif bootstrap_alignment:
        warnings.append(
            f"schema.sql 仅补齐迁移链已存在的表（bootstrap 对齐，非结构变更）—— 无需新迁移"
        )

    if len(deleted_files) >= BULK_DELETE_THRESHOLD:
        warnings.append(f"本次删除 {len(deleted_files)} 个文件（>= {BULK_DELETE_THRESHOLD}）—— 请确认是有意清理")

    if deploy_files:
        warnings.append(f"修改生产部署文件 {len(deploy_files)} 个：{deploy_files[0]} 等 —— 部署链路变更需谨慎")

    return blockers, warnings


def _git_name_status(scope):
    """返回 `git diff --name-status <BASE>...HEAD -- <scope>` 的 [(status, path)]。

    **fail-closed（本次收紧）**：取证失败返回 **None**，与「本次确实无变更」（返回 `[]`）
    严格区分。旧实现（无 returncode 判定 + 裸 `except` → `[]`）把两者收敛成同一件事，
    于是 BASE 配错 / 无共同祖先 / 非 git 仓库 / 超时都会让 **整个安全门禁**退化成
    「0 变更、0 blocker、✅ PASSED」—— 而本文件 docstring 自己声称 fail-closed，
    schema 分支也已按同一原则改过（见 `_ddl` 段的注释与 `test_git_diff_failure_fails_closed`）。
    失效方向对安全门禁只能是「报错」，不能是「放行」。
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--name-status", f"{BASE}...HEAD", "--", scope],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        print(f"::error:: danger_scan 取证失败（{BASE}...HEAD -- {scope}）: {e}", file=sys.stderr)
        return None
    if out.returncode != 0:
        detail = (out.stderr or "").strip().splitlines()
        print(f"::error:: danger_scan 取证失败（{BASE}...HEAD -- {scope}，退出码 {out.returncode}）: "
              f"{detail[0] if detail else '（git 未输出 stderr）'}", file=sys.stderr)
        return None
    result = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            # 完整 status（rename 是 R100/R062 等含相似度，A/M/D 为单字符）
            # 调用方按 status[0] 取大类、按 status == "R100" 判纯改名（issue #3812）
            result.append((parts[0], parts[-1]))
    return result


def _workflow_changes():
    """workflow 目录内的变更 [(status, path)]；取证失败 → None（fail-closed）。"""
    changes = _git_name_status(WORKFLOW_DIR)
    if changes is None:
        return None
    return [(s, p) for s, p in changes if p.endswith(WORKFLOW_SUFFIXES)]


def _secret_ref_diff_lines(diff_lines):
    """从 `git diff` 输出里挑出「**代码文本**含 secrets 引用」的增/删行（纯函数）。

    前置筛选与判定**同源**（issue #5268）：都先 `strip_comment()`、再走 `SECRET_REF_RE`。
    修前筛选用子串 `"secrets." in l`，与判定用的正则**不是一把尺子** —— 注释里的
    `secrets.*`（子串命中、正则不命中）因此能溜进判定面，被当作「真新增」。
    抽成纯函数的理由：这行就是「同源」判据的落点，而 `_workflow_new_secrets()` 要跑
    `git diff` ⇒ 判据必须能**直测**，否则它在单测里不可达（等于没判据）。
    """
    added = [l for l in diff_lines if l.startswith("+") and SECRET_REF_RE.search(strip_comment(l))]
    removed = [l for l in diff_lines if l.startswith("-") and SECRET_REF_RE.search(strip_comment(l))]
    return added, removed


def _workflow_new_secrets(paths):
    """对修改的 workflow 提取新增的 secrets 引用行（移动/重排不算新增，issue #2949）。

    取证失败 → **None**（fail-closed）：拿不到某条 workflow 的 diff 时，「没看到新 secrets」
    与「无法判断有没有新 secrets」是两件事 —— 后者若当成前者，等于给安全审查开一条
    「让 git diff 失败即可放行」的路（与 `_git_name_status` 同族，见其 docstring）。
    """
    secrets_by_path = {}
    for status, path in paths:
        if status[0] in ("M", "R"):
            try:
                out = subprocess.run(
                    ["git", "diff", f"{BASE}...HEAD", "--", path],
                    capture_output=True, text=True, timeout=30,
                )
            except Exception as e:
                print(f"::error:: danger_scan 无法读取 {path} 的 secrets diff: {e}", file=sys.stderr)
                return None
            if out.returncode != 0:
                print(f"::error:: danger_scan 无法读取 {path} 的 secrets diff（退出码 "
                      f"{out.returncode}）", file=sys.stderr)
                return None
            lines = out.stdout.splitlines()
            added, removed = _secret_ref_diff_lines(lines)
            truly_new = _truly_new_secret_lines(added, removed)
            if truly_new:
                secrets_by_path[path] = truly_new
    return secrets_by_path


def main():
    # 取证先行（fail-closed）：三条扫描线任一拿不到变更清单 ⇒ 不判定、直接 blocker。
    # 绝不允许「取证失败」被读成「没有破坏性变更」——那正是安全门禁的假绿形态。
    blockers = []
    all_changes = _git_name_status(".")
    if all_changes is None:
        blockers.append(
            f"无法获取变更清单（git diff {BASE}...HEAD）—— 安全门禁取证失败，"
            f"不得按「无变更」放行。请确认 {BASE} 存在且与 HEAD 有共同祖先"
            f"（CI: `git fetch origin main`；本地: DANGER_BASE 指向真实 ref）"
        )
        all_changes = []
    workflow_paths = _workflow_changes()
    if workflow_paths is None:
        blockers.append(
            f"无法获取 workflow 变更清单（{WORKFLOW_DIR}）—— 安全门禁取证失败，同上"
        )
        workflow_paths = []
    wf_new_secrets = _workflow_new_secrets(workflow_paths)
    if wf_new_secrets is None:
        blockers.append(
            "无法读取 workflow 的 secrets diff —— 安全门禁取证失败，不得按「无新增 secrets」放行"
        )
        wf_new_secrets = {}

    deleted_files = [p for s, p in all_changes if s == "D"]
    deploy_files = [p for s, p in all_changes if s[0] in ("M", "A", "R") and
                    (p.startswith("deploy/") or "/deploy/" in p)]
    raw_migration_changes = _git_name_status_all_migrations()
    if raw_migration_changes is None:
        blockers.append(
            "无法获取迁移文件变更清单 —— 安全门禁取证失败（「迁移只增不改」判定未执行，"
            "不得按「无迁移变更」放行）"
        )
        raw_migration_changes = []
    # 逐字节一致的**归档搬家**（issue #5243）不是「重写已发布迁移」⇒ 从判定面摘出 + 单独报告。
    # 改内容再搬 / 删掉且无同名归档件 ⇒ 留在 migration_changes 里，照旧 BLOCK（判据强度不变）。
    migration_changes, archived_moves = split_migration_moves(raw_migration_changes)
    schema_changes = [p for s, p in all_changes if p in SCHEMA_FILES]

    trusted = os.environ.get("DANGER_TRUSTED_ACTOR", "").lower() in ("1", "true", "yes")
    # 删除 workflow 的人工确认通道（#4295）：由 pr-check 的 ack 步骤在运行期从 PR 评论解析得出。
    # 未设置/解析失败 ⇒ 空集合 ⇒ 删除一律 BLOCK（fail-closed，与补通道前逐字相同）。
    delete_acked = frozenset(
        p.strip() for p in os.environ.get("DANGER_ACK_DELETE", "").split(",") if p.strip()
    )
    ack_by = os.environ.get("DANGER_ACK_BY", "").strip()
    ack_url = os.environ.get("DANGER_ACK_URL", "").strip()
    # 迁移重写的人工确认通道（#4936）：由 pr-check 的 ack 步骤注入（`DANGER_ACK_MIGRATION=<V###,...>`）。
    # ⚠️ **不能只信环境变量**：账本是否同批更新、账本哈希是否等于磁盘 —— 在这里**重跑**一遍
    # 交叉校验（环境变量只是「有人 ack 过」的线索，不是放行依据）。
    migration_acked = frozenset(
        v for v in (migration_version(t)
                    for t in os.environ.get("DANGER_ACK_MIGRATION", "").split(","))
        if v
    )
    migration_ack_by = os.environ.get("DANGER_ACK_MIGRATION_BY", "").strip()
    migration_ack_url = os.environ.get("DANGER_ACK_MIGRATION_URL", "").strip()
    ledger_changed = any(p == LEDGER_PATH and s[0] == "M" for s, p in all_changes)
    ledger_entries = _read_ledger_entries() if migration_acked else None
    disk_hashes = {}
    if migration_acked:
        for status, path in migration_changes:
            if status[0] == "M":
                disk_hashes[path.rsplit("/", 1)[-1]] = _sha256_of(path)
    # analyze 内部会再算一次（同一纯函数、同一输入 ⇒ 结果必然一致）；这里算一次只为写 acks 留痕。
    migration_granted, _ = verify_migration_acks(
        migration_acked, migration_changes, ledger_changed, ledger_entries, disk_hashes)
    for _status, _old, _new in archived_moves:
        print(f"ℹ️ 迁移已归档（内容逐字节一致，非重写）：{_old} → {_new}")
    if archived_moves:
        print(f"ℹ️ 共 {len(archived_moves)} 条迁移已归档（内容逐字节一致，非重写）—— 不计入 blocker")

    a_blockers, warnings = analyze(
        workflow_paths, wf_new_secrets, deleted_files, deploy_files,
        migration_changes, schema_changes, trusted_actor=trusted,
        delete_acked=delete_acked,
        migration_acked=migration_acked, migration_ack_by=migration_ack_by,
        migration_ack_url=migration_ack_url, ledger_changed=ledger_changed,
        ledger_entries=ledger_entries, disk_hashes=disk_hashes,
    )
    blockers = blockers + a_blockers

    # 留痕：谁确认了哪些删除 / 哪些迁移重写、确认凭据在哪 —— 让「人工确认」可追溯
    # （不是"说确认就确认"）。迁移条目多一个 `version` 键，据此可与删除条目区分。
    acks = [
        {"path": p, "by": ack_by or "(unknown)", "via": ack_url or "(unknown)"}
        for p in sorted(delete_acked)
    ]
    path_by_version = {migration_version(p): p for s, p in migration_changes if migration_version(p)}
    acks += [
        {"version": v, "path": path_by_version.get(v, ""),
         "by": migration_ack_by or "(unknown)", "via": migration_ack_url or "(unknown)"}
        for v in sorted(migration_granted)
    ]

    result = {
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
        "acks": acks,
    }
    with open("danger-scan-result.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    for b in blockers:
        print(f"❌ {b}")
    for w in warnings:
        print(f"⚠️ {w}")
    if blockers:
        print(f"🔒 danger-scan: {len(blockers)} 处 blocker，阻塞合并")
        sys.exit(1)
    print(f"✅ danger-scan: {len(blockers)} blocker / {len(warnings)} warning")
    sys.exit(0)


if __name__ == "__main__":
    if "--resolve-acks" in sys.argv[1:]:
        resolve_acks_main()
    else:
        main()
