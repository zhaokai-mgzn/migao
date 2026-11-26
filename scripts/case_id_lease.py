#!/usr/bin/env python3
"""case_id_lease.py — 「号段预占」的**写面**（issue #9090）：一次动作 = 独占一个号（+ 可选 claim）。

## 为什么写面单列在这里（而不是给 `next_case_id.py` 加个 `--write`）

`scripts/next_case_id.py` 的价值有一半来自**结构性只读**（判据
`test_next_case_id_allocator.py::read_only_problems` 把「源码里不得出现写文件 API」钉死）。
把写面塞进它会当场推翻那条判据。⇒ 写面单列，**号怎么算仍只有一处**：
本文件 `import next_case_id`，语料怎么读、号怎么选全部复用它的函数（不另写一把尺子）。

## 两层互斥（缺一层都只保住一半）

| 层 | 机制 | 保什么 | 保不住什么 |
|---|---|---|---|
| **同机** | 租约文件 `O_CREAT \\| O_EXCL`（`~/.migao-case-id-leases/`，机器级、不入库） | 同一台机器上的**所有** worktree / 克隆（两个进程同时创建同一路径，内核保证恰好一个成功） | 另一台机器上的并行包 |
| **跨机** | 把号发布成 **git ref**：`refs/tags/case-lease/<前缀>-<号>`（`git push` 一次） | 「同一个号只能被发布一次」—— git 服务器的 ref 唯一性是**原子判定**，不需要任何常驻服务 | 远端不可达时（下面第 ③ 条：**出声**，本地独占仍成立） |

被拒（`! [rejected]` / `! [remote rejected]` / up-to-date）⇒ **别人先占了** ⇒ 撤回自己的本地租约、**顺延**一号重试
⇒ `reserve` 返回的号**必然**与任何已发布的号不同。

## 租约台账在哪、为什么不入库

`MIGAO_CASE_ID_LEASE_DIR`（默认 `~/.migao-case-id-leases`）—— **机器级**：
① 覆盖同一台机器上的所有 worktree / 克隆；② 不入库 ⇒ 不会变成第二份「并行包都去改同一个文件」的冲突源
（那正是本单要消掉的东西）。跨机器面 = 上面那层 **git ref** + `.github/cases/claims/**`（`--pr` 顺手写的）。

## 口径（四条）

1. **租约只增不删**（本地层）：一个被放弃的号会一直占着 —— 它只让尾部前进一位，不误伤任何人；
   回收需要人判「这个号是不是真的弃了」，本工具**不**做（无人值守的删除不安全）。
2. **远端 ref 删不掉不影响正确性**：它只是「这个号发布过」的占位；合并后可以用
   `git push origin --delete case-lease/<号>` 收尾，不删也不会错（号只增不减）。
3. **`--pr` 幂等**：同一 PR 重跑 ⇒ 打印**已登记**的那个号，不新占号（否则号白白泄漏）。
4. **看不到就 fail-closed / 说不清就出声**：语料或本地 ref 读不到、租约目录不可写 ⇒ `exit 3`（不给号）；
   远端不可达（离线 / 无远端 / 权限不足）⇒ **照常给号**但在输出里明说「跨机互斥不保证」
   （离线是并行包的正常工作条件，不能拿它把本地开发卡死；但**绝不**假装跨机成立）。

## 三态退出码（与 `next_case_id.py` 同口径）

| 码 | 含义 |
|---|---|
| `0` | 拿到号（`--pr` 时 claim 已落盘；跨机层见输出里的「已发布 / 跨机互斥不保证」） |
| `2` | 用法错误（前缀形态不合法 / `--pr` 与 `--title` 不配套） |
| `3` | **无法判定** ⇒ 不给号（语料读不到 / 本地 ref 取不到 / 租约目录不可写） |
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import next_case_id as nci  # noqa: E402 —— 取号口径的**单一实现**（本文件不另写一份）

#: 租约目录的注入点（与 `NCI_MAIN_REF` / `NCI_GH_BIN` 同先例；判据用临时目录）。
LEASE_DIR_ENV = "MIGAO_CASE_ID_LEASE_DIR"
#: 机器级默认位置（不入库；跨 worktree / 跨克隆共用）。
DEFAULT_LEASE_DIR = Path.home() / ".migao-case-id-leases"
#: claim 台账（入库；跨机器的**第二道**收口面）。
CLAIMS_REL = Path(".github") / "cases" / "claims"
#: 跨机层的注入点：`0` ⇒ 不发布到远端（判据隔离 / 真离线）。默认发布。
PUBLISH_ENV = "MIGAO_CASE_ID_LEASE_PUBLISH"
#: 跨机仲裁用的 ref 命名空间（**tag** —— GitHub 只接受 `refs/heads/*` / `refs/tags/*` 这类常规命名空间，
#: 自造的 `refs/case-lease/*` 会被拒成 `deny updating a hidden ref`）。
PUBLISH_REF_PREFIX = "refs/tags/case-lease/"
#: 顺延重试的上限（撞车时；正常只撞 1~2 次）。
MAX_TRIES = 200


def lease_dir() -> Path:
    raw = (os.environ.get(LEASE_DIR_ENV) or "").strip()
    return Path(raw) if raw else DEFAULT_LEASE_DIR


def today() -> str:
    return date.today().isoformat()


def publish_ref(cid: str) -> str:
    """该号的跨机占位 ref（`refs/tags/case-lease/<前缀>-<号>`）。"""
    return f"{PUBLISH_REF_PREFIX}{cid}"


def atomic_create(path: Path, body: str) -> None:
    """**同机独占**：`O_CREAT|O_EXCL` ⇒ 并发下恰好一个进程成功（其余拿到 `FileExistsError`）。"""
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, body.encode("utf-8"))
    finally:
        os.close(fd)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """跑一条 `git`（本文件是**写面**：不受 `next_case_id.py` 的只读白名单约束）。"""
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


def publish_state(repo: Path, cid: str) -> tuple[str, str]:
    """把号发布成远端 ref ⇒ `(state, detail)`；state ∈ `published` / `taken` / `unpublished`。

    · `published`：这次**新建**了那个 ref ⇒ 号归我（跨机互斥**成立**）；
    · `taken`：ref 已存在（被拒 / non-FF / up-to-date）⇒ 别人（或我上一次）先发布过 ⇒ 调用方**顺延**；
    · `unpublished`：没有远端 / 网络或权限不可用 ⇒ **本地独占成立、跨机不保证**（调用方必须出声）。
    """
    if (os.environ.get(PUBLISH_ENV) or "").strip() == "0":
        return "unpublished", f"{PUBLISH_ENV}=0（按注入关闭发布）"
    if _git(repo, "remote", "get-url", "origin").returncode != 0:
        return "unpublished", "本仓没有 `origin` 远端"
    p = _git(repo, "push", "--porcelain", "origin", f"HEAD:{publish_ref(cid)}")
    out = (p.stdout or "") + (p.stderr or "")
    if "new tag" in out or "new reference" in out:
        return "published", publish_ref(cid)
    if "[rejected]" in out or "[remote rejected]" in out or "already exists" in out:
        return "taken", _last_line(out)
    if p.returncode == 0:                       # up-to-date ⇒ 该 ref 已经存在（不是「这次新建」）
        return "taken", "该 ref 已存在（up-to-date）"
    return "unpublished", _last_line(out) or f"git push rc={p.returncode}"


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""


def reserve(prefix: str, occupied: dict[str, set[int]], directory: Path | None = None,
            create=atomic_create, note: str = "", repo: Path | None = None,
            publish: bool = True) -> tuple[int, str]:
    """取号 ⇒（号, 跨机状态）；被拒/撞车则**顺延**。

    `occupied` 由调用方给（= main ∪ 本工作区 ∪ 既有租约）—— 本函数不自己读语料，
    这样判据能在**内存**里喂单变量对照（`create` 注入）。
    """
    directory = Path(directory) if directory is not None else lease_dir()
    directory.mkdir(parents=True, exist_ok=True)
    root = Path(repo) if repo is not None else Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip() or ".")
    number = nci.allocate({prefix: occupied.get(prefix, set())}, [prefix])[prefix]
    for _ in range(MAX_TRIES):
        cid = f"{prefix}-{number:03d}"
        path = directory / f"{cid}.json"
        body = json.dumps({"id": cid, "at": today(), "note": note},
                          ensure_ascii=False, indent=2) + "\n"
        try:
            create(path, body)
        except FileExistsError:
            number += 1
            continue
        state, detail = publish_state(root, cid) if publish else ("unpublished", "publish=False")
        if state == "taken":
            # 别人先占了 ⇒ 撤回**我们自己刚建的**租约（否则本机会永远占着一个用不上的号）
            try:
                path.unlink()
            except OSError:
                pass
            number += 1
            continue
        return number, state if state != "unpublished" else "unpublished"
    raise RuntimeError(f"顺延 {MAX_TRIES} 次仍被占 ⇒ 候选集与租约/远端 ref 自相矛盾（拒绝给号）")


def find_claim(root: Path, pr: int) -> str:
    """该 PR 已登记的 claim（文件名里的 CASE_ID）；没有 ⇒ 空串。"""
    directory = Path(root) / CLAIMS_REL
    for p in sorted(directory.glob(f"{pr}-*.json")) if directory.is_dir() else []:
        parts = p.stem.split("-", 1)
        if len(parts) == 2 and parts[1]:
            return parts[1]
    return ""


def write_claim(root: Path, pr: int, cid: str, title: str) -> Path:
    """落 claim（字段最小集 = `test_case_id_claims.py::REQUIRED_FIELDS`）。已存在 ⇒ 不覆盖。"""
    path = Path(root) / CLAIMS_REL / f"{pr}-{cid}.json"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"id": cid, "pr": pr, "title": title.strip(), "claimed_at": today()},
                      ensure_ascii=False, indent=2) + "\n"
    path.write_text(body, encoding="utf-8")
    return path


def current_occupied() -> dict[str, set[int]]:
    """**离线**候选集：main（本地 ref）∪ 本工作区（含未提交）∪ 既有租约。不读 GitHub。"""
    ref = os.environ.get("NCI_MAIN_REF") or "origin/main"
    main_src, _blobs = nci.read_main(ref)
    return nci.merge_ids(main_src.ids, nci.read_worktree().ids, nci.read_leases().ids)


def render(cid: str, root: Path, claim: Path | None, state: str) -> str:
    """人可复算的证据行（租约位置 + 跨机层读数 + 下一步），不只打印一个数字。"""
    ref = os.environ.get("NCI_MAIN_REF") or "origin/main"
    out = [f"🔒 已独占：{cid}",
           f"   同机：{lease_dir()}（机器级台账，不入库 ⇒ 不会成为并行包的第二个冲突源）",
           f"   候选来源：main({ref}) · 本工作区 · 既有租约（**离线**，不读 GitHub）"]
    if state == "published":
        out.append(f"   跨机：已发布 {publish_ref(cid)}（git ref 唯一性 = 跨机仲裁；"
                   f"收尾可 `git push origin --delete case-lease/{cid}`，不删也不会错）")
    else:
        out.append(f"   ⚠️ 未发布到远端 ⇒ **跨机互斥不保证**（同机独占成立）")
    if claim is not None:
        out.append(f"   claim：{claim.relative_to(root)}（跨机器收口面；判据 = "
                   f"`tests/unit_ci_workflows/test_case_id_claims.py`）")
    out.append(f"   下一步：测试文件头写 `# case_ids: {cid}`、用例块写 `- id: {cid}`")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="case_id_lease.py",
        description="号段预占（离线；同机 = O_EXCL，跨机 = git ref 唯一性）：写面 = 本文件，号 = next_case_id.py",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("reserve", help="独占一个号（可顺带落 claim；默认把号发布成远端 ref）")
    rp.add_argument("prefix", help="用例前缀（如 MC / UI / BM）")
    rp.add_argument("--pr", type=int, default=None,
                    help="本 PR 号（给了 ⇒ 顺带写 `.github/cases/claims/<PR>-<号>.json`；同一 PR 重跑幂等）")
    rp.add_argument("--title", default="", help="本 PR 的用例标题（与 `--pr` 配套；claim 的必填字段）")
    args = ap.parse_args(argv)

    prefix = args.prefix.upper()
    if not nci.PREFIX_RE.match(prefix):
        print(f"❌ 前缀形态不合法：{args.prefix!r}（要 2~4 个大写字母，如 MC / UI / BM）",
              file=sys.stderr)
        return 2
    if (args.pr is None) != (not args.title.strip()):
        print("❌ `--pr` 与 `--title` 必须**配套**给：claim 的最小字段集是 "
              "`id` / `pr` / `title` / `claimed_at`（缺一个判据 1 就红）", file=sys.stderr)
        return 2

    try:
        root = Path(nci.git(["rev-parse", "--show-toplevel"]).strip())
        if args.pr is not None:
            existing = find_claim(root, args.pr)
            if existing:
                print(f"🔒 已独占：{existing}（本 PR 已在 claim 台账里登记 ⇒ 幂等：不新占号）")
                print(f"   claim：{(CLAIMS_REL / f'{args.pr}-{existing}.json').as_posix()}")
                return 0
        number, state = reserve(prefix, current_occupied(), note=f"branch={root.name}", repo=root)
        cid = f"{prefix}-{number:03d}"
        claim = write_claim(root, args.pr, cid, args.title) if args.pr is not None else None
        print(render(cid, root, claim, state))
        return 0
    except nci.Undecidable as exc:
        print("❌ 无法判定 ⇒ 不给号")
        print(f"   原因：{exc}")
        print("   出口：① 确认当前目录在 migao 的 git 工作树里；② 本地没有 `origin/main` 时给 "
              "`NCI_MAIN_REF=HEAD`；③ 都不行 ⇒ 不要凭「我看到的最大号 + 1」取号（那正是撞号的成因）")
        return 3
    except (OSError, RuntimeError) as exc:
        print("❌ 无法判定 ⇒ 不给号")
        print(f"   原因：{exc.__class__.__name__}: {exc}")
        print(f"   出口：`{LEASE_DIR_ENV}=<一个可写目录>` 重跑（判据用临时目录就是这么注入的）")
        return 3


if __name__ == "__main__":
    sys.exit(main())
