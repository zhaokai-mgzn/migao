"""
QA Growth Gate fail-closed 守卫（issue #3631）。

growth_gate.py 的 --check-weak 分支在「读文件失败/路径不存在/解析异常」时曾静默
返回「0 处弱断言」并 exit 0（fail-open 假绿）——路径不可读 ≠ 无弱断言，
「断言空转」「扫描器空转」同一家族。本测试锁定修复后的语义：

- 路径不存在 / 传入目录 / 坏 UTF-8 → 必须报错并 exit 非零（fail-closed）；
- 文件存在且真无弱断言 → 保持 0 处 + exit 0（正常语义不回退）；
- 真弱断言 → 仍检出并 exit 1（检测能力不回退）；
- get_changed_files：git diff 失败 → 返回 None（fail-closed，扫描空转 ≠ 无变更）。

⚠️ 本文件自身会被 CI 的 --check-weak 扫描（新增测试文件），因此正文不得出现
字面弱断言模式（is not None 等存在性断言/恒真断言/空 pass），弱断言样本一律
拼接构造。
"""
# case_ids: MC-012
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"


def _load_gate():
    """从 .github/growth_gate.py 加载被测模块（零依赖，importlib 文件加载）。"""
    spec = importlib.util.spec_from_file_location("growth_gate_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_check_weak(gate, *paths):
    """调 growth_gate.main() 的 --check-weak 分支，返回退出码。"""
    return gate.main(["--check-weak", "--files", *paths])


# ── ① fail-closed：扫描失败必须非零，绝不允许「0 处弱断言」假绿 ──

def test_missing_file_fails_closed(tmp_path, capsys):
    """路径不存在 → exit 非零，且不得打印误导性的「0 处弱断言」。"""
    gate = _load_gate()
    missing = tmp_path / "does_not_exist.py"
    rc = _run_check_weak(gate, str(missing))
    out, err = capsys.readouterr()
    assert rc != 0, "路径不存在必须 exit 非零（fail-closed）"
    assert "0 处弱断言" not in out, "不得打印「0 处弱断言」假绿"
    assert "::error::" in err or "❌" in err, "必须输出明确错误"


def test_directory_fails_closed(tmp_path, capsys):
    """传入目录（IsADirectoryError）→ exit 非零，同样不许假绿。"""
    gate = _load_gate()
    rc = _run_check_weak(gate, str(tmp_path))
    out, _ = capsys.readouterr()
    assert rc != 0, "目录路径必须 exit 非零（fail-closed）"
    assert "0 处弱断言" not in out


def test_bad_utf8_fails_closed(tmp_path, capsys):
    """存在但编码异常的样本 → exit 非零（干净报错，不是裸 traceback）。"""
    gate = _load_gate()
    bad = tmp_path / "bad_utf8_test.py"
    bad.write_bytes(b"\xff\xfe\x00 bad utf8 \xff")
    rc = _run_check_weak(gate, str(bad))
    assert rc != 0, "编码异常必须 exit 非零（fail-closed）"
    out, err = capsys.readouterr()
    assert "Traceback" not in err, "应给干净报错而非裸 traceback"


# ── ② 正常语义不回退 ──

def test_clean_file_zero_and_exit_zero(tmp_path, capsys):
    """文件存在且真无弱断言 → 0 处 + exit 0（正常语义保留）。"""
    gate = _load_gate()
    f = tmp_path / "clean_test.py"
    f.write_text("def test_x():\n    assert result == 3\n")
    rc = _run_check_weak(gate, str(f))
    out, _ = capsys.readouterr()
    assert rc == 0, "真无弱断言必须 exit 0"
    assert "0 处弱断言" in out


def test_weak_assert_still_detected(tmp_path, capsys):
    """真弱断言仍检出并 exit 1（检测能力不回退）。样本拼接构造，避免本文件被扫。"""
    gate = _load_gate()
    weak_line = "assert x is " + "not None"
    f = tmp_path / "weak_test.py"
    f.write_text("def test_x():\n    " + weak_line + "\n")
    rc = _run_check_weak(gate, str(f))
    out, _ = capsys.readouterr()
    assert rc == 1, "真弱断言必须 exit 1"
    assert "1 处弱断言" in out


# ── ③ 真实 CLI 契约（sys.exit(main()) 端到端）──

def test_cli_subprocess_missing_file_nonzero(tmp_path):
    """真实 CLI：--check-weak 指向不存在路径必须非零退出。"""
    missing = tmp_path / "nope.py"
    r = subprocess.run(
        [sys.executable, str(GATE_PY), "--check-weak", "--files", str(missing)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert r.returncode != 0, "真实 CLI 路径不存在必须非零退出（fail-closed）"
    assert "0 处弱断言" not in r.stdout


# ── ④ 同类 fail-open：get_changed_files 扫描空转 ──

def test_get_changed_files_fail_closed(monkeypatch):
    """git diff 失败 → 返回 None（fail-closed），不允许返回空清单当「无变更」放行。"""
    gate = _load_gate()

    def boom(*a, **k):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(gate.subprocess, "run", boom)
    assert gate.get_changed_files("origin/main") is None


def test_main_base_mode_fails_closed_on_git_error(monkeypatch):
    """--base 模式 git diff 失败 → main() 非零退出（fail-closed）。"""
    gate = _load_gate()

    def boom(*a, **k):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(gate.subprocess, "run", boom)
    rc = gate.main(["--base", "origin/main"])
    assert rc != 0, "扫描失败必须让门禁非零退出（fail-closed）"
