#!/usr/bin/env python3
"""外部作者守卫 —— 陌生账号提交的代码不得进本仓（issue #8386；PR 作者面 #8393）。

PR 作者面（#8393）：PR 的**提交者**也必须命中 `pr_authors`（两名使用账号 + CI bot +
dependabot 已知例外）；`automerge.yml` 只 arm `auto_merge_logins`。dependabot 仍走既有
bot-safe 路径（仅 patch/minor）。

## 治的形态（真实发生过，不是假想）

外部账号 `llwand1`（非协作者）的 **fork PR #6897** 关闭未合并，但同日被**搬到同仓分支**
以 PR #6924 重开并 squash 合并 ⇒ 陌生账号写的代码进入 main；squash 之后 `git log` 里
**看不到原作者**（署名变成合并者），事后再查只能靠 GitHub API 的 PR 提交面。

`automerge.yml` 只排除 **fork PR** —— 而这条路径是**同仓分支**，在 GitHub 眼里与自研 PR 无异
⇒ 现有护栏对它完全无感。本脚本把「**PR 里的提交作者**」当判据：

1. 取 PR 的 head 仓库来源与提交列表（`GET /repos/{repo}/pulls/{n}` 与 `.../commits`）；
2. 逐个与 `.github/external-authorship-allow.json` 的白名单比对
   （账号精确匹配 / 邮箱精确匹配 / GitHub noreply 形态且登录名在白名单）；
3. 命中陌生账号或 fork 来源 ⇒ 打印具名清单、**解除已 arm 的 auto-merge**、打 `block/merge`，
   然后 `exit 1`（判红）。

## 三态口径

`0` 全部放行 / `1` 命中违规 / `2` 用法或白名单错误 / `3` **无法判定**（API 读不到、JSON 解析失败）。
`3` 明确**不是** `0`：调用方（CI job）按非零处理，并同样解除自动合并 —— 判不了就不许直接合。

## 边界（照实登记，别把「有守卫」读成「来源可证」）

- **判不了「内容来源」**：若有人把外部代码**用自己的身份重新提交**，作者面看不出任何异常
  （squash 之后更是如此）。本守卫堵的是**原样搬运提交**这条（也就是真实发生的那条）。
- **白名单是自证式的**：改 `git config user.email` 即可伪造 team 邮箱 —— 与仓库内所有
  identity 判据同族，不是安全边界，是**流程护栏**。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2
EXIT_UNDECIDABLE = 3

DEFAULT_ALLOW_FILE = ".github/external-authorship-allow.json"
PR_AUTHORS_KEY = "pr_authors"
BLOCK_LABEL = "block/merge"
NOREPLY_SUFFIX = "@users.noreply.github.com"


def load_allowlist(path: str | Path) -> tuple[set[str], set[str]]:
    """读白名单 → (logins, emails)。空名单 / 通配一律拒绝启动（fail-closed）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("白名单必须是 JSON 对象")
    logins = {str(x).strip().lower() for x in (data.get("logins") or []) if str(x).strip()}
    emails = {str(x).strip().lower() for x in (data.get("emails") or []) if str(x).strip()}
    if not logins:
        # 空名单 = 放行一切 ⇒ 那是最坏的「假绿」，宁可不起床
        raise ValueError("白名单 `logins` 为空 —— 空名单等于放行一切，拒绝启动")
    wildcards = sorted(x for x in (logins | emails) if "*" in x or "?" in x)
    if wildcards:
        raise ValueError(f"白名单不许通配：{wildcards}（通配 = 名单形同虚设）")
    return logins, emails


def load_pr_authors(path: str | Path) -> set[str]:
    """读 PR 作者白名单 → set。空名单 / 通配一律拒绝启动（fail-closed）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("白名单必须是 JSON 对象")
    authors = {str(x).strip().lower() for x in (data.get(PR_AUTHORS_KEY) or []) if str(x).strip()}
    if not authors:
        raise ValueError(f"白名单 `{PR_AUTHORS_KEY}` 为空 —— 空名单等于放行一切，拒绝启动")
    wildcards = sorted(x for x in authors if "*" in x or "?" in x)
    if wildcards:
        raise ValueError(f"白名单不许通配：{wildcards}（通配 = 名单形同虚设）")
    return authors


def noreply_login(email: str, logins: set[str]) -> str | None:
    """GitHub noreply 邮箱 → 命中白名单的登录名（`123+login@` / `login@` 两种形态）。"""
    if not email.endswith(NOREPLY_SUFFIX):
        return None
    local = email[: -len(NOREPLY_SUFFIX)]
    login = local.split("+", 1)[1] if "+" in local else local
    return login if login.lower() in logins else None


def classify(commits: list[dict], logins: set[str], emails: set[str]) -> list[dict]:
    """把提交分成「放行 / 违规」。返回违规清单（空 = 全部放行）。"""
    violations: list[dict] = []
    for commit in commits:
        sha = str(commit.get("sha") or "")[:9]
        login = str(((commit.get("author") or {}).get("login") or "")).strip()
        author = (commit.get("commit") or {}).get("author") or {}
        name = str(author.get("name") or "").strip()
        email = str(author.get("email") or "").strip().lower()
        if login and login.lower() in logins:
            continue
        if email and email in emails:
            continue
        if email and noreply_login(email, logins):
            continue
        violations.append(
            {
                "sha": sha or "(无 sha)",
                "login": login or "(未关联 GitHub 账号)",
                "name": name or "(未署名)",
                "email": email or "(空邮箱)",
            }
        )
    return violations


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def fetch_head_repo(repo: str, pr: int) -> str:
    result = _gh(["api", f"repos/{repo}/pulls/{pr}", "--jq", '.head.repo.full_name // ""'])
    if result.returncode != 0:
        raise RuntimeError(f"gh api 取 head 仓库失败：{(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout.strip()


def fetch_pr_author(repo: str, pr: int) -> str:
    result = _gh(["api", f"repos/{repo}/pulls/{pr}", "--jq", '.user.login // ""'])
    if result.returncode != 0:
        raise RuntimeError(f"gh api 取 PR 作者失败：{(result.stderr or result.stdout).strip()[:300]}")
    login = result.stdout.strip()
    if not login:
        raise RuntimeError("PR 作者为空（gh api 返回空 login）")
    return login


def fetch_commits(repo: str, pr: int) -> list[dict]:
    result = _gh(
        [
            "api",
            f"repos/{repo}/pulls/{pr}/commits?per_page=100",
            "--paginate",
            "--jq",
            ".[] | @json",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api 取提交列表失败：{(result.stderr or result.stdout).strip()[:300]}")
    commits: list[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            commits.append(json.loads(line))
        except json.JSONDecodeError as exc:  # pragma: no cover - 防御式
            raise RuntimeError(f"提交列表 JSON 解析失败：{exc}") from exc
    return commits


def remediate(repo: str, pr: int) -> list[str]:
    """解除已 arm 的自动合并 + 打人工闸标签。两步都用 `|| true` 语义：判红由退出码承担。"""
    notes: list[str] = []
    disarm = _gh(["pr", "merge", str(pr), "-R", repo, "--disable-auto"])
    notes.append(f"解除 auto-merge：{'成功' if disarm.returncode == 0 else '跳过（未 arm 或无权限）'}")
    label = _gh(["pr", "edit", str(pr), "-R", repo, "--add-label", BLOCK_LABEL])
    notes.append(f"打 {BLOCK_LABEL} 标签：{'成功' if label.returncode == 0 else '失败（无权限或标签不存在）'}")
    return notes


def _print_violations(violations: list[dict], reason: str) -> None:
    print(f"❌ {reason}")
    print(f"{'sha':<11}{'账号':<26}{'邮箱':<48}署名")
    for v in violations:
        print(f"{v['sha']:<11}{v['login']:<26}{v['email']:<48}{v['name']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拦截陌生账号 / fork 来源的 PR（issue #8386 / #8393）")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int, help="PR 号")
    parser.add_argument("--allow-file", default=DEFAULT_ALLOW_FILE)
    parser.add_argument("--commits-json", help="离线夹具：直接读该 JSON（判据用，不走网络）")
    parser.add_argument("--head-repo", help="离线夹具：PR head 仓库 full_name")
    parser.add_argument("--pr-author", help="离线夹具：PR 作者的 login（判据用，不走网络）")
    parser.add_argument("--no-remediate", action="store_true", help="只报告、不解除 auto-merge / 不打标签")
    args = parser.parse_args(argv)

    try:
        logins, emails = load_allowlist(args.allow_file)
        pr_authors = load_pr_authors(args.allow_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"❌ 无法读取白名单 {args.allow_file}：{exc}")
        return EXIT_USAGE

    try:
        head_repo = args.head_repo if args.head_repo is not None else fetch_head_repo(args.repo, args.pr)
        pr_author = (
            args.pr_author.strip()
            if args.pr_author is not None
            else fetch_pr_author(args.repo, args.pr)
        )
        if args.commits_json:
            commits = json.loads(Path(args.commits_json).read_text(encoding="utf-8"))
        else:
            commits = fetch_commits(args.repo, args.pr)
    except Exception as exc:  # noqa: BLE001 - 三态：读不到 = 无法判定
        print(f"⛔ 无法判定（exit {EXIT_UNDECIDABLE}，**不得当 0 读**）：{exc}")
        if not args.no_remediate:
            for note in remediate(args.repo, args.pr):
                print(f"   · {note}")
        return EXIT_UNDECIDABLE

    violations: list[dict] = []
    reasons: list[str] = []
    if pr_author.lower() not in pr_authors:
        violations.append({"sha": "-", "login": pr_author, "name": "(PR 作者)", "email": "-"})
        reasons.append(f"PR 作者 `{pr_author}` 不在白名单（{PR_AUTHORS_KEY}）")
    if head_repo and head_repo.lower() != args.repo.lower():
        reasons.append(f"PR 来自 fork（{head_repo}），本仓不接受 fork PR 的代码直接合并")
        violations.append({"sha": "-", "login": "(fork)", "name": "-", "email": "-"})
    else:
        commit_violations = classify(commits, logins, emails)
        if commit_violations:
            reasons.append(f"{len(commit_violations)} 个提交的作者不在白名单（{args.allow_file}）")
            violations.extend(commit_violations)

    if not violations:
        print(
            f"✅ PR 作者 `{pr_author}` 与全部 {len(commits)} 个提交的作者都在白名单内"
            f"（{args.allow_file}）"
        )
        return EXIT_OK

    _print_violations(violations, "；".join(reasons) or "命中白名单拦截")
    if not args.no_remediate:
        for note in remediate(args.repo, args.pr):
            print(f"   · {note}")
    return EXIT_VIOLATION


if __name__ == "__main__":
    sys.exit(main())
