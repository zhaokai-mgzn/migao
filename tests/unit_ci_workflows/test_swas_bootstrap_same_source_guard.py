# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml。）
"""`deploy/scripts/swas-deploy-ci.sh` bootstrap 的**部署脚本与镜像 tag 同源**守卫 —— issue #5120。

## 缺陷（#5083 修掉的那一层之上，又高了一层）

`deploy/swas/deploy.sh` **内部**的配置（compose / nginx）已按镜像 tag 同源
（`config_ref_for_tag` ⇒ `CONFIG_REF_RESOLVED`，取不到即 fail-closed），
但 **bootstrap 自己**此前仍无条件以 `refs/heads/main` 下载 **`deploy.sh` 本身**
（本文件落地前 `deploy/scripts/swas-deploy-ci.sh` 里那句 codeload URL）⇒
回滚到旧 tag 时是「**旧镜像 + 旧配置 + 新部署脚本**」，与被 #5083 修掉的那层**同一形态**
（未定义行为、而且**不报错、不告警**）。

## 本文件锁什么（4 条验收判据，每条都有能**单独**变红的注入式红证）

1. **同源**：`sha-<hex>` tag ⇒ 取该 commit 的那份 `deploy.sh`；且渲染结果里**绝不出现**
   `refs/heads/main`。行为级：构造「main 已前进」夹具（main 那份与 sha 那份**内容不同**）⇒
   断言实际装到服务器上的**不是** main 那份。
2. **回滚**：给定旧 `IMAGE_TAG`（回滚 tag 与本次不同）⇒ ref 按**回滚 tag** 重新推导，
   取到的是**该 tag** 对应的 `deploy.sh`（不是本次那份、更不是 main 那份）。
3. **取不到 ⇒ fail-closed**：空 tag ⇒ `render_bootstrap` **非零退出且不产出任何命令**；
   行为级：ref 在远端不存在（404）⇒ 取源码的 `&&` 链**中止**（非零），**不装任何 `deploy.sh`**。
4. **护栏不削弱**：下载 tarball 的 curl 必须仍带 `-f`（4xx/5xx ⇒ 硬失败）与重试预算。

另有一条**漂移锁**：CI 侧那份推导（`bootstrap_tag_to_sha` / `bootstrap_ref_for_tag`）与
`deploy/swas/deploy.sh` 的 `tag_to_sha` / `config_ref_for_tag` **逐字相等**（只允许函数名不同）。
为什么不直接复用：**鸡生蛋** —— 那两份函数所在的 `deploy.sh` 正是 bootstrap 要**下载**的东西，
下载完成前它不存在于服务器上，无从 source。故本文件用漂移锁保证「第二份」不可能静默走样。

## 反空跑锚点

脚本读不到 / 函数解析不出 / `BOOTSTRAP` 解析不出 ⇒ **显式失败**（不是"通过"）。
判据本体读的是**脚本当前文本**，不是"与某个历史版本等值"。
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"

# CI 侧要装配进桩环境的三个函数（顺序即依赖顺序）
CI_FUNCS = ("bootstrap_tag_to_sha", "bootstrap_ref_for_tag", "render_bootstrap")

# 漂移锁的名字对照：CI 侧 → deploy.sh 侧。**只允许名字不同**，函数体必须逐字相等。
NAME_MAP = {
    "bootstrap_tag_to_sha": "tag_to_sha",
    "bootstrap_ref_for_tag": "config_ref_for_tag",
}

# 三份**内容互不相同**的 deploy.sh：用来判「到底取到了哪一份」
MAIN_TREE = "MAIN_DEPLOY_SH"   # refs/heads/main 那份（= 旧行为取到的）
SHA_TREE = "SHA_DEPLOY_SH"     # sha-abc1234 那份（= 本次部署应当取到的）
OLD_TREE = "OLD_DEPLOY_SH"     # sha-def5678 那份（= 回滚应当取到的）

REF_RE = re.compile(r"tar\.gz/(\S+) -o")
CURL_FLAGS_RE = re.compile(r"curl (\S+) --retry")

# 桩 curl：按 URL 里的 ref 提供**内容不同**的仓库树；ref 不存在时忠实模拟真 curl ——
# 带 `-f` ⇒ exit 22（404 硬失败）；不带 `-f` ⇒ exit 0 + 错误页正文。
CURL_STUB = """#!/usr/bin/env bash
set -euo pipefail
url=""; out=""; force=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift 2 ;;
    --retry|--retry-delay|--connect-timeout|--max-time) shift 2 ;;
    -*) case "$1" in *f*) force=1 ;; esac; shift ;;
    *) url=$1; shift ;;
  esac
done
ref=${url##*/tar.gz/}
key=$(printf '%s' "$ref" | tr '/' '_')
trees="$(cd "$(dirname "$0")/.." && pwd)/trees"
if [ ! -d "$trees/$key/repo" ]; then
  if [ "$force" -eq 1 ]; then
    echo "curl: (22) The requested URL returned error: 404" >&2
    exit 22
  fi
  printf '<html>404 Not Found</html>' > "$out"
  exit 0
fi
tar czf "$out" -C "$trees/$key" repo
"""


# ── 解析层（解析失败一律**显式失败**，绝不静默空跑）─────────────────────────────

def read_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def extract_func_body(text: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}$", text, re.M | re.S)
    if not m:
        raise AssertionError(f"解析不出函数 {name} —— 判据不能空跑")
    return m.group(1)


def extract_func(text: str, name: str) -> str:
    return f"{name}() {{\n{extract_func_body(text, name)}}}"


def extract_bootstrap_assignment(text: str) -> str:
    m = re.search(r'^BOOTSTRAP=".*"$', text, re.M)
    if not m:
        raise AssertionError("解析不出 BOOTSTRAP 赋值 —— 判据不能空跑")
    return m.group(0)


def build_harness(script_text: str, dest: Path) -> Path:
    """把脚本里**真实的** BOOTSTRAP 与三个函数装配成一个可独立运行的渲染器。

    `REGISTRY_SETUP` 是 CI 侧展开的兄弟变量（与真脚本同形）⇒ 这里补空串。
    """
    dest.mkdir(parents=True, exist_ok=True)
    parts = [
        "set -euo pipefail",
        "REGISTRY_SETUP=''",
        "IMAGE_TAG=${3:-latest}",
        extract_bootstrap_assignment(script_text),
    ]
    parts += [extract_func(script_text, n) for n in CI_FUNCS]
    # 与 `deploy_attempt` 同形：tag+ref 由 `render_bootstrap` 渲染，许可占位符**就地**渲染
    parts.append('out=$(render_bootstrap "$1") || exit $?')
    parts.append('printf %s "${out//__ALLOW_DOWNGRADE__/$2}"')
    harness = dest / "harness.sh"
    harness.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return harness


def render(harness: Path, tag: str, allow: str = "0", image_tag: str = "latest"):
    return subprocess.run(
        ["bash", str(harness), tag, allow, image_tag],
        capture_output=True, text=True, check=False,
    )


def ref_of(bootstrap_text: str) -> str:
    m = REF_RE.search(bootstrap_text)
    return m.group(1) if m else ""


def curl_flags(bootstrap_text: str) -> str:
    m = CURL_FLAGS_RE.search(bootstrap_text)
    return m.group(1) if m else ""


# ── 行为级夹具（桩 curl + 三棵内容不同的树）────────────────────────────────────

def _write_tree(trees: Path, ref: str, content: str) -> None:
    d = trees / ref.replace("/", "_") / "repo" / "deploy" / "swas"
    d.mkdir(parents=True, exist_ok=True)
    (d / "deploy.sh").write_text(content, encoding="utf-8")


def write_trees(tmp: Path) -> Path:
    trees = tmp / "trees"
    _write_tree(trees, "refs/heads/main", MAIN_TREE)
    _write_tree(trees, "abc1234", SHA_TREE)
    _write_tree(trees, "def5678", OLD_TREE)
    return trees


def _write_stub_curl(tmp: Path) -> Path:
    stub = tmp / "stub"
    stub.mkdir(parents=True, exist_ok=True)
    exe = stub / "curl"
    exe.write_text(CURL_STUB, encoding="utf-8")
    os.chmod(exe, 0o755)
    return stub


def fetch_segment(bootstrap_text: str, dest: Path) -> str:
    """取出渲染结果里**真实的**「取源码 → 装 deploy.sh」那段 `&&` 链（到 `bash` 之前）。

    唯一的测试期改写：把绝对安装目录 `/opt/migao-deploy` 换到沙箱（保证本地可跑、不写系统路径）。
    """
    start = bootstrap_text.index("SRC=$(mktemp -d)")
    end = bootstrap_text.index("&& bash ")
    return bootstrap_text[start:end].replace("/opt/migao-deploy", str(dest))


def run_fetch(script_text: str, tmp: Path, tag: str, image_tag: str):
    """跑**真实的**取源码段 ⇒ 返回 (退出码, 实际装上的 deploy.sh 内容)。"""
    harness = build_harness(script_text, tmp)
    rendered = render(harness, tag, "0", image_tag)
    if rendered.returncode != 0:
        raise AssertionError(f"渲染失败（tag={tag}）: {rendered.stderr}")
    stub = _write_stub_curl(tmp)
    dest = tmp / "opt" / "migao-deploy"
    env = dict(os.environ, PATH=f"{stub}{os.pathsep}{os.environ['PATH']}")
    proc = subprocess.run(
        ["bash", "-c", fetch_segment(rendered.stdout, dest)],
        capture_output=True, text=True, check=False, env=env,
    )
    installed = dest / "deploy.sh"
    body = installed.read_text(encoding="utf-8") if installed.exists() else ""
    return proc.returncode, body


# ── 4 条判据（纯函数，返回 bool ⇒ 注入式红证可复用同一条判据）──────────────────

def crit_same_source(script_text: str, tmp: Path) -> bool:
    """判据 1（同源）：`sha-<hex>` ⇒ ref = 该 commit；渲染结果里没有 `refs/heads/main`。"""
    r = render(build_harness(script_text, tmp), "sha-abc1234", "0", "sha-abc1234")
    if r.returncode != 0:
        return False
    return ref_of(r.stdout) == "abc1234" and "refs/heads/main" not in r.stdout


def crit_fetched_is_not_main(script_text: str, tmp: Path) -> bool:
    """判据 1（同源，行为级）：main 已前进 ⇒ 装上的**不是** main 那份。"""
    write_trees(tmp)
    rc, body = run_fetch(script_text, tmp, "sha-abc1234", "sha-abc1234")
    return rc == 0 and body == SHA_TREE and body != MAIN_TREE


def crit_rollback_gets_own_ref(script_text: str, tmp: Path) -> bool:
    """判据 2（回滚）：旧 IMAGE_TAG ⇒ ref 按**回滚 tag** 重推，取到该 tag 的 deploy.sh。"""
    r = render(build_harness(script_text, tmp), "sha-def5678", "1", "sha-abc1234")
    if r.returncode != 0 or ref_of(r.stdout) != "def5678":
        return False
    write_trees(tmp)
    rc, body = run_fetch(script_text, tmp, "sha-def5678", "sha-abc1234")
    return rc == 0 and body == OLD_TREE and body != SHA_TREE


def crit_fail_closed(script_text: str, tmp: Path) -> bool:
    """判据 3（取不到 ⇒ fail-closed）：空 tag ⇒ 非零退出 + 不产出任何命令。"""
    r = render(build_harness(script_text, tmp), "", "0", "latest")
    return r.returncode != 0 and r.stdout.strip() == ""


def crit_fetch_404_fails_closed(script_text: str, tmp: Path) -> bool:
    """判据 3（行为级）：ref 在远端不存在 ⇒ 取源码链中止，**不装任何 deploy.sh**。"""
    write_trees(tmp)
    rc, body = run_fetch(script_text, tmp, "sha-9999999", "sha-9999999")
    return rc != 0 and body == ""


def crit_curl_guard_intact(script_text: str, tmp: Path) -> bool:
    """判据 4（护栏不削弱）：curl 仍带 `-f`（404 ⇒ 硬失败）+ 重试预算仍在。"""
    r = render(build_harness(script_text, tmp), "sha-abc1234", "0", "sha-abc1234")
    if r.returncode != 0:
        return False
    flags = curl_flags(r.stdout)
    return flags.startswith("-") and "f" in flags and "--retry 3" in r.stdout


def _normalize_names(body: str) -> str:
    """把 CI 侧的函数名全部换回 `deploy.sh` 侧的名字（**只允许名字不同**，函数体必须逐字相等）。"""
    for ci_name, ref_name in NAME_MAP.items():
        body = body.replace(ci_name, ref_name)
    return body


def crit_derivation_matches_deploy_sh(ci_text: str) -> bool:
    """漂移锁：CI 侧推导与 `deploy/swas/deploy.sh` 的口径**逐字相等**（只允许函数名不同）。"""
    deploy_text = DEPLOY_SH.read_text(encoding="utf-8")
    for ci_name, ref_name in NAME_MAP.items():
        ci_body = _normalize_names(extract_func_body(ci_text, ci_name))
        if ci_body != extract_func_body(deploy_text, ref_name):
            return False
    return True


# ── 反空跑锚点 ────────────────────────────────────────────────────────────────

def test_script_and_functions_are_parseable():
    t = read_script()
    for name in CI_FUNCS:
        assert f"{name}() {{" in t, f"脚本里找不到 {name}"
    assert "__BOOTSTRAP_REF__" in t, "BOOTSTRAP 里没有 ref 占位符 ⇒ 判据会空跑"


def test_missing_function_fails_loudly():
    with pytest.raises(AssertionError):
        extract_func_body(read_script(), "no_such_function")


def test_missing_bootstrap_fails_loudly():
    with pytest.raises(AssertionError):
        extract_bootstrap_assignment("#!/bin/bash\necho hi\n")


def test_no_main_based_deploy_sh_url_remains():
    """bootstrap 取 `deploy.sh` 的 URL 里不得再有 `tar.gz/refs/heads/main`（#5120 的直接形态）。"""
    assert "tar.gz/refs/heads/main" not in read_script()


# ── 4 条判据在**真实脚本**上必须全绿 ──────────────────────────────────────────

def test_same_source(tmp_path):
    assert crit_same_source(read_script(), tmp_path), "bootstrap 的 ref 不是按 tag 推导出来的"


def test_fetched_deploy_sh_is_not_main(tmp_path):
    assert crit_fetched_is_not_main(read_script(), tmp_path), "main 已前进时取到了 main 那份 deploy.sh"


def test_rollback_fetches_the_old_tag_deploy_sh(tmp_path):
    assert crit_rollback_gets_own_ref(read_script(), tmp_path), "回滚没有按回滚 tag 重新推导 ref"


def test_unresolvable_tag_fails_closed(tmp_path):
    assert crit_fail_closed(read_script(), tmp_path), "空 tag 没有 fail-closed（可能静默回落 main）"


def test_fetch_404_fails_closed(tmp_path):
    assert crit_fetch_404_fails_closed(read_script(), tmp_path), "ref 404 时没有中止，或装上了别的东西"


def test_curl_guard_is_intact(tmp_path):
    assert crit_curl_guard_intact(read_script(), tmp_path), "curl 的 -f / 重试预算被削弱了"


def test_derivation_matches_deploy_sh_verbatim():
    assert crit_derivation_matches_deploy_sh(read_script()), "CI 侧推导与 deploy.sh 的口径漂移了"


# ── 注入式红证：每条判据都必须能**单独**变红 ──────────────────────────────────

def test_injected_dropped_f_flag_turns_guard_red(tmp_path):
    """判据 4 的红证：去掉 `-f`（404 也算成功）⇒ 判据 4 红，其余判据仍绿。"""
    mutated = read_script().replace("curl -fsSL", "curl -sSL")
    assert mutated != read_script(), "变异没生效 ⇒ 红证空跑"
    assert not crit_curl_guard_intact(mutated, tmp_path), "去掉 -f 后判据 4 没红"
    assert crit_same_source(mutated, tmp_path), "去掉 -f 不应影响判据 1"


def test_injected_main_ref_turns_guard_red(tmp_path):
    """判据 1 的红证：把 ref 占位符换回 `refs/heads/main` ⇒ 判据 1（静态 + 行为级）都红。"""
    mutated = read_script().replace("tar.gz/__BOOTSTRAP_REF__", "tar.gz/refs/heads/main")
    assert mutated != read_script(), "变异没生效 ⇒ 红证空跑"
    assert not crit_same_source(mutated, tmp_path), "回落 main 后判据 1 没红"
    assert not crit_fetched_is_not_main(mutated, tmp_path), "回落 main 后装上的就是 main 那份，判据没红"
    assert crit_curl_guard_intact(mutated, tmp_path), "回落 main 不应影响判据 4"


def test_injected_frozen_ref_turns_rollback_criterion_red(tmp_path):
    """判据 2 的红证：ref 只用**本次** tag 推导（回滚不重推）⇒ 判据 2 红，判据 1 仍绿。"""
    mutated = read_script().replace(
        'ref=$(bootstrap_ref_for_tag "$tag")', 'ref=$(bootstrap_ref_for_tag "$IMAGE_TAG")'
    )
    assert mutated != read_script(), "变异没生效 ⇒ 红证空跑"
    assert not crit_rollback_gets_own_ref(mutated, tmp_path), "回滚 ref 冻结后判据 2 没红"
    assert crit_same_source(mutated, tmp_path), "回滚 ref 冻结不应影响判据 1"


def test_injected_removed_fail_closed_turns_criterion_red(tmp_path):
    """判据 3 的红证：删掉空 ref 的 fail-closed 闸 ⇒ 判据 3 红。"""
    mutated = read_script().replace('  [ -n "$ref" ] || return 1\n', "")
    assert mutated != read_script(), "变异没生效 ⇒ 红证空跑"
    assert not crit_fail_closed(mutated, tmp_path), "删掉 fail-closed 闸后判据 3 没红"
    assert crit_curl_guard_intact(mutated, tmp_path), "删 fail-closed 不应影响判据 4"


def test_injected_derivation_drift_turns_drift_lock_red():
    """漂移锁的红证：把 CI 侧 `sha-` 的长度阈值改掉 ⇒ 漂移锁红。"""
    mutated = read_script().replace('if [ "${#t}" -ge 7 ]', 'if [ "${#t}" -ge 3 ]')
    assert mutated != read_script(), "变异没生效 ⇒ 红证空跑"
    assert not crit_derivation_matches_deploy_sh(mutated), "口径漂移后漂移锁没红"
