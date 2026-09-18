# case_ids: MC-012
"""`scripts/red_proof.py` —— 红证生成动作的缓存卫生 + 注入自证（issue #4260）。

守的这颗地雷（**夹具是真 python 解释器 + 真 `.pyc`**，不 mock 编译/缓存层：判据本体就是
「解释器会不会复用旧字节码」这件事，mock 掉等于把被测对象换成替身 ⇒ 红证变假绿）：

「注入缺陷 → 跑测试 → 应红 → 还原」这个**取红证的动作本身**会骗人：改前/改后**同字节长度**的文件在
**同一秒内**替换时，`.pyc` 头里的 `(mtime, size)` 与源文件**仍然一致** ⇒ 解释器**不重编译**、直接复用
旧 `.pyc` ⇒ **注入未生效**，而测试读到的是**旧行为**。后果是**假绿证**（把本来有效的护栏误判成
「不会红的空断言」而删掉/放宽）与**错归因**（把红归因给没生效的注入）。它出在**证据生成层** ——
这层是用来抓其它所有问题的，而 `migao-acceptance`「每条断言都要有红证」的可信度本身却无人保护。

用例分五组（每组都要有**判别力**，不是「跑通就算」）：

① **真复现**：真写 `.pyc` → 同秒同长度替换 → 新进程读到**旧值**；`clear_caches` 后读到新值。
   同时断言 `.pyc` 头与源 `(mtime, size)` **一致** ⇒ 证明「用 mtime/size 当判据」这条路本身无效。
② **注入自证 fail-closed**：内容指纹未变（no-op 注入）⇒ 必须报错，而不是静默继续跑测试
   （这正是「没生效」与「判据是空的」不可区分的那一步）。
③ **检出「运行时会复用旧 `.pyc`」**：同秒同长度注入后 `--no-clear` ⇒ CLI 必须**非零退出并点名 pyc**，
   而不是静默跑下去读到旧值（naive 流程在这里会拿到假绿证）。
④ **清缓存覆盖面**：`__pycache__` 之外必须覆盖 `sys.pycache_prefix`（**本机实测**：macOS 系统 python
   把 `.pyc` 写到 `~/Library/Caches/com.apple.python`，`rm -rf __pycache__` 在那里是**空操作**）+
   `.pytest_cache` / `.next/cache` / `node_modules/.vite` / `.tsbuildinfo` / `target/classes`。
⑤ **留痕 + 还原自证**：`injected` 输出必须含注入前后 **sha256 + 内容 diff**；`restored` 未还原即非零退出。

case_ids 口径：本测试属 **dev/CI 工具链**，与同族 `test_stranding_check.py`（#4065）、
`test_dev_worktree_rebase.py`（#3972）、`test_agent_presets_guard.py`（#3851）沿用同一组 case id
（`MC-012`）—— 仓库目前没有「开发工具链」用例族，本 PR **未新建**用例：塞进行为用例库会污染覆盖矩阵
（同族 PR 的既有裁定）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "red_proof.py"

# append（**不是** insert）：只作兜底解析路径，避免遮蔽 app/ 或 site-packages 里的同名模块。
sys.path.append(str(REPO_ROOT / "scripts"))

import red_proof  # noqa: E402

OLD_SRC = 'VALUE = "aaaa"\n'
NEW_SRC = 'VALUE = "bbbb"\n'          # 与 OLD_SRC **同字节长度** —— 本缺陷的确切形态
READ_CODE = ("import importlib.util as u;"
             "s=u.spec_from_file_location('probe_mod', {p!r});"
             "m=u.module_from_spec(s);s.loader.exec_module(m);print(m.VALUE)")


@pytest.fixture
def pyc_prefix(tmp_path_factory, monkeypatch):
    """把 `.pyc` 落点钉到 tmp（父进程 + 子进程同一处）。

    **本机默认落点在仓库外**（macOS 系统 python 的 `~/Library/Caches/com.apple.python`）：
    不钉住既会污染全局缓存，也会让「清 `__pycache__`」这类判据在测试里假绿。
    """
    d = tmp_path_factory.mktemp("pycache-prefix")
    monkeypatch.setattr(sys, "pycache_prefix", str(d), raising=False)
    return d


def _child_env(prefix: Path) -> dict:
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(prefix)}
    # 显式**允许**写字节码：本缺陷只在写 `.pyc` 时存在，继承 `PYTHONDONTWRITEBYTECODE=1`
    # 会让「真复现」用例变成假绿（前提自断言会先红，不会静默）。
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    return env


def _read_value(mod: Path, prefix: Path) -> str:
    """在**新进程**里 import 该模块并读 `VALUE`（缓存复用只在新进程里才可观测）。"""
    r = subprocess.run([sys.executable, "-c", READ_CODE.format(p=str(mod))],
                       capture_output=True, text=True, env=_child_env(prefix))
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _cli(*args: str, prefix: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, env=_child_env(prefix))


def _same_second_same_length_replace(path: Path, new_text: str) -> None:
    """同秒 + 同字节长度替换：显式把 mtime 钉回原值，让 `.pyc` 头继续「看起来有效」。"""
    old = path.stat()
    data = new_text.encode()
    assert len(data) == old.st_size, (len(data), old.st_size)
    path.write_bytes(data)
    os.utime(path, (old.st_atime, old.st_mtime))


def _manifest(tmp_path: Path, paths: list, prefix: Path) -> str:
    """调 CLI 记基线指纹（顺带覆盖 `fingerprint --json` 入口）。"""
    r = _cli("fingerprint", "--json", "--root", str(tmp_path), *[str(p) for p in paths],
             prefix=prefix)
    assert r.returncode == 0, r.stderr
    m = tmp_path / "manifest.json"
    m.write_text(r.stdout)
    return str(m)


class TestRealStalePycReproduction:
    """① 真复现：同秒同长度替换 ⇒ 解释器复用旧 `.pyc` ⇒ 读到旧值。"""

    def test_same_second_same_length_replace_is_masked_by_stale_pyc(self, tmp_path, pyc_prefix):
        mod = tmp_path / "probe_mod.py"
        mod.write_text(OLD_SRC)
        assert _read_value(mod, pyc_prefix) == "aaaa"

        pyc = Path(importlib.util.cache_from_source(str(mod)))
        assert pyc.exists()                                   # 前提自断言：没写 pyc 就不是本形态

        _same_second_same_length_replace(mod, NEW_SRC)
        assert mod.read_text() == NEW_SRC                     # 文件**确实**变了

        # 判据：`.pyc` 头里的 (mtime, size) 与源文件**仍然一致** ⇒ 「用 mtime/size 判新鲜度」无效
        assert red_proof._pyc_matches_source(pyc, mod) is True
        # ← 注入「未生效」：新进程读到的还是旧值
        assert _read_value(mod, pyc_prefix) == "aaaa"

        removed = red_proof.clear_caches(tmp_path)
        assert str(pyc) in [str(p) for p in removed]
        assert _read_value(mod, pyc_prefix) == "bbbb"         # ← 清缓存后才读到真值


class TestInjectionSelfProof:
    """② 注入自证：内容指纹必须变，且与声明一致 —— 否则 fail-closed。"""

    def test_fingerprint_is_content_based_not_mtime_based(self, tmp_path, pyc_prefix):
        f = tmp_path / "x.py"
        f.write_text(OLD_SRC)
        before = red_proof.content_fingerprint(f)
        _same_second_same_length_replace(f, NEW_SRC)          # 同秒 + 同长度
        after = red_proof.content_fingerprint(f)
        assert before != after                                # 指纹只看内容 ⇒ 免疫本缺陷
        assert before.startswith("sha256:")

    def test_unchanged_fingerprint_raises(self):
        fp = "sha256:" + "0" * 64
        with pytest.raises(red_proof.RedProofError) as e:
            red_proof.assert_injection_effective(fp, fp, True, label="mod.py")
        assert "未生效" in str(e.value)
        assert "mod.py" in str(e.value)

    def test_changed_fingerprint_passes(self):
        red_proof.assert_injection_effective("sha256:a", "sha256:b", True)

    def test_declared_expectation_mismatch_raises(self):
        with pytest.raises(red_proof.RedProofError) as e:
            red_proof.assert_injection_effective("sha256:a", "sha256:b", True,
                                                 expected_fp="sha256:c")
        assert "与声明不符" in str(e.value)

    def test_restore_check_raises_when_not_restored(self):
        with pytest.raises(red_proof.RedProofError) as e:
            red_proof.assert_injection_effective("sha256:a", "sha256:b", False)
        assert "未还原" in str(e.value)
        red_proof.assert_injection_effective("sha256:a", "sha256:a", False)

    def test_diff_summary_leaves_content_trace(self):
        d = red_proof.diff_summary(OLD_SRC, NEW_SRC, "probe_mod.py")
        assert "-VALUE" in d and "+VALUE" in d and '"aaaa"' in d and '"bbbb"' in d


class TestClearCachesCoverage:
    """④ 清缓存覆盖面（含 `sys.pycache_prefix` 这个本机实测的盲区）。"""

    def test_clears_python_js_and_jvm_artifacts(self, tmp_path, pyc_prefix):
        targets = [
            tmp_path / "__pycache__" / "a.cpython-311.pyc",
            tmp_path / ".pytest_cache" / "v" / "cache" / "lastfailed",
            tmp_path / ".mypy_cache" / "3.11" / "x.json",
            tmp_path / ".next" / "cache" / "webpack.pack",
            tmp_path / "node_modules" / ".vite" / "deps" / "x.js",
            tmp_path / "node_modules" / ".cache" / "babel.json",
            tmp_path / "target" / "classes" / "A.class",
            tmp_path / "app.tsbuildinfo",
            tmp_path / ".eslintcache",
            tmp_path / "stray.pyc",
        ]
        for t in targets:
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text("x")

        before = red_proof.cache_artifacts(tmp_path)
        assert len(before) >= len(targets)

        removed = red_proof.clear_caches(tmp_path)
        assert len(removed) >= len(targets)
        assert red_proof.cache_artifacts(tmp_path) == []
        for t in targets:
            assert t.exists() is False

    def test_clears_bytecode_outside_the_repo(self, tmp_path, pyc_prefix):
        """**本机实测的盲区**：`.pyc` 落在 `sys.pycache_prefix` 下（仓库外）时，
        `rm -rf __pycache__` 是空操作 ⇒ 必须按 `cache_from_source` 的真实落点清。"""
        mod = tmp_path / "outside_mod.py"
        mod.write_text(OLD_SRC)
        assert _read_value(mod, pyc_prefix) == "aaaa"
        pyc = Path(importlib.util.cache_from_source(str(mod)))
        assert pyc.exists()
        assert tmp_path not in pyc.parents          # 前提自断言：它确实在仓库/root 之外

        removed = red_proof.clear_caches(tmp_path)
        assert str(pyc) in [str(p) for p in removed]
        assert pyc.exists() is False


class TestCliRedProofFlow:
    """③⑤ CLI：检出「会复用旧 `.pyc`」+ 留痕 + 还原自证。"""

    def test_injected_refuses_when_stale_bytecode_would_be_reused(self, tmp_path, pyc_prefix):
        mod = tmp_path / "probe_mod.py"
        mod.write_text(OLD_SRC)
        assert _read_value(mod, pyc_prefix) == "aaaa"
        pyc = Path(importlib.util.cache_from_source(str(mod)))
        assert pyc.exists()
        manifest = _manifest(tmp_path, [mod], pyc_prefix)

        _same_second_same_length_replace(mod, NEW_SRC)
        r = _cli("injected", "--manifest", manifest, "--root", str(tmp_path), "--no-clear",
                 prefix=pyc_prefix)
        out = r.stdout + r.stderr
        assert r.returncode == 1                      # fail-closed，而不是静默跑下去
        assert "复用" in out
        assert str(pyc) in out                        # 点名到底是哪个产物会骗人

    def test_injected_clears_caches_and_leaves_hash_and_diff(self, tmp_path, pyc_prefix):
        mod = tmp_path / "probe_mod.py"
        mod.write_text(OLD_SRC)
        assert _read_value(mod, pyc_prefix) == "aaaa"
        pyc = Path(importlib.util.cache_from_source(str(mod)))
        assert pyc.exists()
        manifest = _manifest(tmp_path, [mod], pyc_prefix)
        before_fp = json.loads(Path(manifest).read_text())["files"][str(mod)]["sha256"]

        _same_second_same_length_replace(mod, NEW_SRC)
        r = _cli("injected", "--manifest", manifest, "--root", str(tmp_path), prefix=pyc_prefix)
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        assert before_fp in out                       # 留痕：注入前哈希
        assert red_proof.content_fingerprint(mod) in out   # 留痕：注入后哈希
        assert "-VALUE" in out and "+VALUE" in out    # 留痕：内容 diff（不是「改了 X 就跑红了」）
        assert pyc.exists() is False                  # 缓存已清
        assert _read_value(mod, pyc_prefix) == "bbbb"  # ← 现在读到的才是注入后的真值

    def test_injected_detects_noop_injection(self, tmp_path, pyc_prefix):
        """「同秒同长度」地写回**同样的字节** ⇒ 注入没落到文件上 ⇒ 必须报错（②的 CLI 面）。"""
        mod = tmp_path / "probe_mod.py"
        mod.write_text(OLD_SRC)
        manifest = _manifest(tmp_path, [mod], pyc_prefix)

        _same_second_same_length_replace(mod, OLD_SRC)
        r = _cli("injected", "--manifest", manifest, "--root", str(tmp_path), prefix=pyc_prefix)
        assert r.returncode == 1
        assert "未生效" in (r.stdout + r.stderr)

    def test_restored_requires_clean_working_tree(self, tmp_path, pyc_prefix):
        mod = tmp_path / "probe_mod.py"
        mod.write_text(OLD_SRC)
        manifest = _manifest(tmp_path, [mod], pyc_prefix)

        _same_second_same_length_replace(mod, NEW_SRC)
        r = _cli("restored", "--manifest", manifest, "--root", str(tmp_path), prefix=pyc_prefix)
        assert r.returncode == 1                      # 没还原就报错，不许当成功
        assert "未还原" in (r.stdout + r.stderr)

        _same_second_same_length_replace(mod, OLD_SRC)   # 真还原（同秒同长度）
        r = _cli("restored", "--manifest", manifest, "--root", str(tmp_path), prefix=pyc_prefix)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "已还原" in (r.stdout + r.stderr)

    def test_missing_manifest_is_tri_state_not_success(self, tmp_path, pyc_prefix):
        r = _cli("restored", "--manifest", str(tmp_path / "nope.json"), "--root", str(tmp_path),
                 prefix=pyc_prefix)
        assert r.returncode == 3                      # 「看不了」不得当「没问题」
