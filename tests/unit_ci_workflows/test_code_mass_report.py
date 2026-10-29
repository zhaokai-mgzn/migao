# case_ids: MC-012
"""`scripts/code_mass_report.py` 的 L0 守卫 —— issue #8165（代码体量 / churn / 重复事实源报告）。

## 为什么给一个「报告型脚本」写判据

报告型脚本的失效形态**在控制台上都长得像一份正常报告**：

1. **静默空转**：注释解析悄悄命中 0 行 ⇒ 读成「这个仓库几乎没有注释」。真相可能是**解析器坏了**；
2. **空集谎报**：扫不到任何源码文件（root 写错 / 目录被排除）⇒ 打印「0 个文件」并 exit 0
   ⇒ 与「仓库很干净」不可区分（fail-closed 缺失）；
3. **顺手写盘**：为了「缓存」落个 json，从此报告不再是只读件；
4. **churn 降级被读成正常**：`git` 不可用时把 churn 记 0 ⇒ 大文件榜的交叉表看起来「没人动过」。

故本文件锁七件事（每条都能指出反例输入）：
① 三类注释解析**逐值精确**（Java `//` `/*` `*` / Python `#` 与三引号块 / TS `//` `/*` `*`）＋
   逻辑行恒等式 `逻辑 = 总行 − 注释 − 空行`；
② **判别力**：三类解析各删掉唯一那条注释 ⇒ 对应读数**变成 0**、其余读数不受污染（注入式红证）；
③ 空集 / 读不到 root ⇒ 退出码 `3`，且**不得**输出「0 个」当正常；
④ **只读自证**：跑完（两种输出形态）目录里文件集合与 mtime/size **逐项未变**，不新增任何文件；
⑤ churn：`--name-only` 解析精确计数；不可用时 `available=False` + 原因（**不谎报 0**），
   且**不因此**把退出码升成 `3`（三张表里只有它降级）；
⑥ 重复事实源登记表：副本一致 / 漂移（报位置）/ 缺副本 / 缺源 四种形态各自可判，且登记表**不许为空**；
⑦ 阈值：默认关闭 ⇒ exit 0；显式给阈值且超了 ⇒ exit 1（**报告型**，不拦合并）。

## 红证（注入式，跑在 `tmp_path` 自造样本上）

| 注入 | 期望（会红的断言） |
|---|---|
| 删掉 `Only.java` 的 `// 唯一注释` 行 | 该文件 comment `1 → 0`；`test_each_comment_parser_is_load_bearing[...java]` |
| 删掉 `app.py` 的 `# 唯一注释` 行 | 同上（Python `#` 分支） |
| 删掉 `only.ts` 的 `// 唯一注释` 行 | 同上（TS 分支） |
| 删掉 Python 三引号块 | docstring 的 comment 行数 `3 → 0`；`test_python_triple_quote_block_counts_as_comment` |
| root 只放 `.md` / root 不存在 | rc `3` + `status=undecidable`；两个 `*_is_undecidable` 用例 |
| 副本写错一个字符 | `identical=False` 且 `detail` 指到「第 1 行起不同」；`test_duplicate_registry...` |
| `--max-file-lines 3` 对 4 行文件 | rc `1` + flag 逐值相等；`test_threshold_is_opt_in` |

## 边界（照实登记，§19.1）

- 只判**行首**注释形态（行尾注释 / 字符串里的符号不细分）—— 那是模块 docstring 里写明的口径，
  本文件钉住的是「口径被实现」而不是「口径是否完美」；
- 不判真实仓库的体量数字（数字会前进，钉住就腐烂）⇒ 全部读数在 `tmp_path` 的已知样本上算；
- 不判「重复事实源该不该合并」—— 只判登记项**仍逐字节一致**；
- 不跑 `git`（夹具非 git 目录；churn 的实际取值属于报告读数，不属判据面）。
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
SCRIPT = REPO_ROOT / "scripts" / "code_mass_report.py"


def _load_report_module():
    spec = importlib.util.spec_from_file_location("code_mass_report_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPORT = _load_report_module()


def _run(root, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_json(root, *extra):
    proc = _run(root, "--json", "--no-churn", "--skip-registry", *extra)
    return proc, json.loads(proc.stdout)


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _layer(payload, dir_name):
    for row in payload["layers"]:
        if row["dir"] == dir_name:
            return row
    raise AssertionError(f"分层体量里没有目录 {dir_name!r}：{[r['dir'] for r in payload['layers']]}")


def _fixture(root):
    """已知行数 / 注释比例的样本：Java 块注释 + Python docstring + TS 块注释。"""
    _write(
        root,
        "src/Demo.java",
        "public class Demo {\n"
        "    // 行注释\n"
        "    /* 块注释\n"
        "     * 续行\n"
        "     */\n"
        "\n"
        "    int value = 1;\n"
        "}\n",
    )
    _write(
        root,
        "src/app.py",
        '"""模块 docstring。\n'
        "\n"
        "第二行。\n"
        '"""\n'
        "# 行注释\n"
        "\n"
        "value = 1\n",
    )
    _write(
        root,
        "web/widget.ts",
        "export const x = 1;\n"
        "// 行注释\n"
        "/* 块注释\n"
        " * 续行\n"
        " */\n"
        "\n"
        "export const y = 2;\n",
    )
    return root


def _snapshot(root):
    """目录树的内容指纹：文件集合 + 每个条目的 mode/size/mtime_ns（只读自证用）。"""
    entries = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            stat = path.stat()
            entries[str(path.relative_to(root))] = (stat.st_mode, stat.st_size, stat.st_mtime_ns)
    return entries


def test_layers_count_comment_blank_and_logic_exactly(tmp_path):
    payload = _run_json(_fixture(tmp_path))[1]

    src = _layer(payload, "src")
    assert src == {
        "dir": "src",
        "files": 2,
        "total": 15,
        "comment": 8,
        "blank": 3,
        "logic": 4,
    }, "Java 块注释 / Python docstring 的计数口径变了"

    web = _layer(payload, "web")
    assert web == {
        "dir": "web",
        "files": 1,
        "total": 7,
        "comment": 4,
        "blank": 1,
        "logic": 2,
    }, "TS 块注释的计数口径变了"

    totals = payload["totals"]
    assert (totals["total"], totals["comment"], totals["blank"], totals["logic"]) == (22, 12, 4, 6)
    assert totals["logic"] == totals["total"] - totals["comment"] - totals["blank"]
    assert payload["status"] == "ok"
    assert payload["scanned_files"] == 3


# 每类各造**恰好一条**注释：删掉它 ⇒ 该类注释读数必须变成 0（注入式红证）。
MINIMAL_CASES = {
    "java": ("Only.java", "// 唯一注释\n\nclass A {}\n"),
    "python": ("app.py", "# 唯一注释\n\nvalue = 1\n"),
    "ts": ("only.ts", "// 唯一注释\n\nlet value = 1;\n"),
}


@pytest.mark.parametrize("kind", sorted(MINIMAL_CASES))
def test_each_comment_parser_is_load_bearing(tmp_path, kind):
    name, text = MINIMAL_CASES[kind]
    path = _write(tmp_path, f"src/{name}", text)

    payload = _run_json(tmp_path)[1]
    intact = _layer(payload, "src")
    assert (intact["total"], intact["comment"], intact["blank"], intact["logic"]) == (3, 1, 1, 1)

    comment_line = text.splitlines()[0]
    path.write_text("\n".join(line for line in text.splitlines() if line != comment_line) + "\n")

    mutated = _layer(_run_json(tmp_path)[1], "src")
    assert mutated["comment"] == 0, f"{kind} 的注释解析不读内容（删掉唯一注释后仍 > 0）"
    assert (mutated["total"], mutated["comment"], mutated["blank"], mutated["logic"]) == (2, 0, 1, 1)
    assert mutated != intact, "删掉注释行后读数没变 ⇒ 该解析分支不是承重的"


def test_python_triple_quote_block_counts_as_comment(tmp_path):
    path = _write(
        tmp_path,
        "pkg/mod.py",
        '"""docstring 第一行\n'
        "第二行\n"
        '"""\n'
        "value = 1\n",
    )
    before = _layer(_run_json(tmp_path)[1], "pkg")
    assert (before["total"], before["comment"], before["blank"], before["logic"]) == (4, 3, 0, 1)

    path.write_text("value = 1\n")
    after = _layer(_run_json(tmp_path)[1], "pkg")
    assert (after["comment"], after["logic"], after["total"]) == (0, 1, 1)

    # 单行三引号也要算注释（开块与收块在同一行 ⇒ 不得进入「块内」状态污染后续行）
    _write(tmp_path, "single/single.py", '"""一行 docstring"""\nvalue = 2\n')
    single = _layer(_run_json(tmp_path)[1], "single")
    assert (single["total"], single["comment"], single["logic"]) == (2, 1, 1)


def test_empty_source_set_is_undecidable_not_zero(tmp_path):
    _write(tmp_path, "README.md", "# 没有源码\n")

    proc = _run(tmp_path, "--json", "--no-churn", "--skip-registry")
    assert proc.returncode == 3, "空集必须 fail-closed，不得当正常"
    payload = json.loads(proc.stdout)
    assert payload["status"] == "undecidable"
    assert "layers" not in payload, "无法判定时不许带一张「0 个文件」的表"
    assert "源码文件集合为空" in payload["reason"]

    text_proc = _run(tmp_path, "--no-churn", "--skip-registry")
    assert text_proc.returncode == 3
    assert "无法判定" in text_proc.stdout
    assert "✅" not in text_proc.stdout, "无法判定却打印了正常结论"


def test_missing_root_is_undecidable(tmp_path):
    missing = tmp_path / "nope"
    proc = _run(missing, "--json", "--no-churn", "--skip-registry")
    assert proc.returncode == 3
    payload = json.loads(proc.stdout)
    assert payload["status"] == "undecidable"
    assert "工作树读不到" in payload["reason"]


def test_run_is_read_only(tmp_path):
    _fixture(tmp_path)
    before = _snapshot(tmp_path)

    assert _run(tmp_path, "--json", "--no-churn", "--skip-registry").returncode == 0
    assert _run(tmp_path, "--no-churn", "--skip-registry").returncode == 0

    after = _snapshot(tmp_path)
    assert set(after) == set(before), "跑报告时新建/删除了文件（只读约束破了）"
    assert after == before, "跑报告时改动了既有文件（size/mtime 变了）"
    assert not (tmp_path / "__pycache__").exists()


def test_churn_parser_counts_commits_and_degrade_does_not_flip_exit_code(tmp_path):
    counts = REPORT.parse_name_only("src/a.py\nsrc/b.py\n\nsrc/a.py\n\nsrc/c.py\n")
    assert dict(counts) == {"src/a.py": 2, "src/b.py": 1, "src/c.py": 1}

    _fixture(tmp_path)
    payload = _run_json(tmp_path)[1]
    assert payload["status"] == "ok", "churn 降级不得把报告变成无法判定/异常"
    assert payload["churn"]["available"] is False
    assert payload["churn"]["reason"].startswith("未计算（--no-churn）")
    assert all(row["churn"] is None for row in payload["largest"]), "churn 不可用时不许谎报 0"

    direct = REPORT.build_report(tmp_path, churn_commits=0, with_registry=False)
    assert direct["churn"]["available"] is False
    assert direct["status"] == "ok"


def test_duplicate_registry_detects_drift_missing_copy_and_missing_source(tmp_path):
    registry = (
        {
            "fact": "示例事实源",
            "source": "a/source.ts",
            "copies": ("b/copy.ts", "b/vanished.ts"),
            "why": "样本",
        },
        {
            "fact": "源也缺失的登记项",
            "source": "a/absent.ts",
            "copies": ("b/other.ts",),
            "why": "样本",
        },
    )
    _write(tmp_path, "a/source.ts", "export const X = 1;\n")
    _write(tmp_path, "b/copy.ts", "export const X = 1;\n")

    results = REPORT.check_duplicates(tmp_path, registry)
    assert [item["identical"] for item in results] == [True, False, False]
    assert results[0]["detail"] == ""
    assert results[1]["copy_exists"] is False
    assert results[1]["detail"] == "副本缺失"
    assert results[2]["source_exists"] is False
    assert results[2]["detail"] == "源文件缺失"

    _write(tmp_path, "b/copy.ts", "export const X = 2;\n")
    drifted = REPORT.check_duplicates(tmp_path, registry)[0]
    assert drifted["identical"] is False
    assert drifted["detail"].startswith("第 1 行起不同")

    payload = REPORT.build_report(tmp_path, churn_commits=0, registry=registry)
    kinds = sorted(flag["kind"] for flag in payload["flags"])
    assert kinds == ["duplicate_drift", "duplicate_missing", "duplicate_missing"]
    assert payload["status"] == "flagged"
    assert REPORT.exit_code_for(payload) == 1


def test_registry_is_not_empty_and_repo_relative():
    assert len(REPORT.REGISTRY) > 0, "登记表被清空 ⇒ 重复源核对退化成空跑"
    for item in REPORT.REGISTRY:
        assert item["fact"], "登记项必须写明事实源"
        assert item["why"], "登记项必须写明为什么登记（评审面）"
        assert item["copies"], f"{item['source']} 没有任何副本 ⇒ 该条永远恒绿"
        for rel in (item["source"], *item["copies"]):
            assert not Path(rel).is_absolute(), f"登记表必须是仓库相对路径：{rel}"
            assert ".." not in Path(rel).parts, f"登记表不许越出仓库根：{rel}"


def test_threshold_is_opt_in(tmp_path):
    _write(tmp_path, "src/big.java", "class A {}\n" * 4)

    ok_proc, ok_payload = _run_json(tmp_path)
    assert ok_proc.returncode == 0, "默认不设阈值 ⇒ 平常跑必须 exit 0"
    assert ok_payload["flags"] == []

    proc, payload = _run_json(tmp_path, "--max-file-lines", "3")
    assert proc.returncode == 1
    assert payload["status"] == "flagged"
    assert payload["flags"] == [
        {"kind": "file_lines", "path": "src/big.java", "value": 4, "threshold": 3}
    ]

    dir_proc, dir_payload = _run_json(tmp_path, "--max-dir-lines", "3")
    assert dir_proc.returncode == 1
    assert dir_payload["flags"] == [
        {"kind": "dir_lines", "dir": "src", "value": 4, "threshold": 3}
    ]

    table = _run(tmp_path, "--no-churn", "--skip-registry", "--max-file-lines", "3")
    assert table.returncode == 1
    assert "不拦合并" in table.stdout, "阈值项必须显式声明是报告型"
