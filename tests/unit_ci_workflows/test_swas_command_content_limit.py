# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。
#   本包不新建用例族。）
r"""SWAS `RunCommand` 各腿的**命令内容契约** —— issue #6124 的**类级元守卫**。

## 治的形态（实测，不是推断）

SWAS `RunCommand` 的 `CommandContent` 有**大小墙**（官方：base64 后 ≤ 16 KB）。而把**远端执行体
整份内联**进命令内容（`$(cat "$REMOTE_SCRIPT")` 那一族写法）会让命令内容**随远端脚本一起长**：

| 腿 | 修前命令内容 | 距 16384 |
|---|---|---|
| C 端 H5（`deploy/scripts/c-end-h5-publish-ci.sh`） | **20377** 字节 | **已越限** ⇒ run `37075737625` 云上 `400 CmdContent.ExceedLimit` |
| bmini H5（`deploy/scripts/bmini-h5-publish-ci.sh`） | ≈ **10.8 KB** | ~5.5 KB |
| worker H5（`deploy/scripts/swas-h5-publish-ci.sh`） | ≈ **9.2 KB** | ~7 KB |

失败形态的恶劣之处**不在错误本身，而在它出现的位置**：只在**发布那一刻**（云 API 前）爆，PR 里
什么都看不见 ⇒ 潜伏期极长，期间线上产物**静默陈旧**（C 端因此陈旧 33 天，`app.migaozn.com/js/app.js`
的 `Last-Modified` 停在 2026-08-30）。

`#6095` 修了 C 端那一条（改成「命令内容只留极小引导」），`#6124` 修另两条 ⇒ **本文件是这一类
缺陷的元守卫**：它不判「哪一条腿修没修」，判的是「**这类形态还能不能进来**」。

## 判据（全部只看**活代码行** —— 整行注释不算，否则讲课的注释会把自己判红）

| # | 判什么 | 回归时会怎么红 |
|---|---|---|
| 1 | **射程机械可判**：`deploy/scripts/**/*.sh` 里含活行 `--command-content`、且文件名出现在某个 `.github/workflows/*.yml` 的 = CI 腿 | —— （射程规则本体，见 `_scope_paths()`） |
| 2 | **未登记即红 / 台账不许盖章**：射程集合 ⇄ 台账 `legs[].path` **双向相等** | 新增一条发布腿没登记 ⇒ 红；台账写了不存在的脚本 ⇒ 红 |
| 3 | **字节前置断言在位**：每腿活行里必须有 `COMMAND_CONTENT_LIMIT_BYTES=` 赋值 **与** `-ge "$COMMAND_CONTENT_LIMIT_BYTES"` 的比较 | 有人把「本机判红」那道闸删掉（超限又变成云上一个 400）⇒ 红 |
| 4 | **上限出处**：每腿活行里必须有官方文档 URL（`api-swas-open-2020-06-01-runcommand`） | 「16 KB」变成一个没有出处的魔数 ⇒ 红 |
| 5 | **闸值与台账一致**：每腿 `COMMAND_CONTENT_LIMIT_BYTES=${…:-<N>}` 的默认值 == 台账 `limit_bytes`，且台账的值只许是那一个保守值 | 有人把闸值悄悄改大（例如 64 KB）⇒ 红 |
| 6 | **不许内联**：任何腿的活行里不许出现**未转义**的命令替换 `cat`（把仓内文件内容拼进命令内容） | 内联写法回来 ⇒ 红 |
| 7 | **判别力自证**：2/3/4/5/6 每种坏形态在内存里各判红一次；**只改注释 ⇒ 不红**（对照读数） | 判据退化成恒真/恒假（空断言）⇒ 红 |
| 8 | **台账 fail-closed**：字段齐备且 `legs` 非空 | 有人清空台账「消红」⇒ 红 |

## 边界（照实登记，别把「登记了」读成「治住了」）

- **本文件只判结构**（登记 / 形态 / 出处 / 不许内联）。**读数层**（真跑组装段、真实字节数、
  解耦读数、超限注入、取不到执行体 fail-closed）在各腿自己的判据文件里 ——
  那才是「命令内容真的只有几百字节」的证据：
  `tests/unit_ci_workflows/test_c_end_h5_hosting.py` · `test_worker_h5_hosting.py` ·
  `test_bmini_h5_hosting.py`（各有一个 `TestCommandContentLimit`）。
- **射程不含人跑的一次性向导**（`deploy/scripts/wx-mini-test-env-setup.sh` 也有 `--command-content`，
  但它不被任何 workflow 调用）—— 理由**机械可判**，且它若被接进 workflow 就自动进射程、**未登记即红**。
  逐条见台账 `coverage_boundary`。
- **不判**各腿 env 前缀的语义齐全性、也不判远端脚本的发布逻辑正确性（各有各的判据）。
- **不判线上**：本机没有 SWAS / aliyun CLI ⇒ 云侧真正的上限只是**文档 + 本仓既有实测**的保守取值。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEDGER_REL = "tests/unit_ci_workflows/swas_command_content_legs_ledger.json"
SCRIPTS_DIR_REL = "deploy/scripts"
WORKFLOWS_DIR_REL = ".github/workflows"
#: 「这条脚本是 CI 腿」的机械标记（命令内容进 SWAS）
SCOPE_MARKER = "--command-content"
#: 每腿必须有的三样（形态 + 出处）
LIMIT_ASSIGN_RE = re.compile(r"^COMMAND_CONTENT_LIMIT_BYTES=\$\{[A-Z0-9_]*:-(\d+)\}$", re.M)
LIMIT_COMPARE = '-ge "$COMMAND_CONTENT_LIMIT_BYTES"'
LIMIT_SOURCE_URL = "api-swas-open-2020-06-01-runcommand"
#: 「把仓内文件内容拼进命令内容」的命令替换（**未转义**才算 —— `\$(cat …)` 是**远端**求值，
#: 与本条无关；deploy 腿的 BOOTSTRAP 模板里就有一处 `\$(cat …)`，那是远端读 marker 文件）
INLINE_CAT_RE = re.compile(r"(?<!\\)\$\(\s*cat\s")
#: 台账与判据共同钉住的那一个保守闸值（三者中最保守；出处见台账 `limit_source_note`）
EXPECTED_LIMIT_BYTES = 16384
LEDGER_REQUIRED_KEYS = ("schema", "issue", "judged_by", "scope_rule", "limit_bytes",
                        "limit_source", "legs", "coverage_boundary")
LEG_REQUIRED_KEYS = ("id", "path", "what", "command_content_source", "bootstrap_mode",
                     "byte_guard_since", "ref_kind")


# ── 口径件（**单一实现**：红证喂**变异后**的文本进同一条判据，不另写第二份）────────────

def _live_lines(text: str) -> list[str]:
    """只保留**非整行注释**的行（口径与 test_c_end_h5_hosting.py::_live_lines 逐字一致）。

    为什么需要它：本文件必须能**引用被判红的串**（否则讲课的注释会把自己判红）——
    实测自伤：注释里逐字写那句内联写法就让判据在真语料上判红。
    代价（照实登记）：**整行注释掉的**内联写法不报 —— 但那行不会执行，不是本条要拦的对象。
    """
    return [raw for raw in text.splitlines() if raw.strip() and not raw.lstrip().startswith("#")]


def _scope_paths(scripts: dict[str, str], workflows: str) -> list[str]:
    """射程 = 含活行 `--command-content` 且**文件名出现在某个 workflow 里**的脚本（仓库相对路径，已排序）。"""
    return sorted(
        rel for rel, text in scripts.items()
        if any(SCOPE_MARKER in line for line in _live_lines(text))
        and Path(rel).name in workflows
    )


def _leg_problems(leg: dict, src: str) -> list[str]:
    """单腿的形态判据（3/4/5/6）。`src` 可注入 ⇒ 红证喂变异文本进**同一条**判定。"""
    rel = leg.get("path", "<无 path>")
    live = _live_lines(src)
    problems: list[str] = []

    m = LIMIT_ASSIGN_RE.search("\n".join(live))
    if not m:
        problems.append(
            f"`{rel}` 活行里没有 `COMMAND_CONTENT_LIMIT_BYTES=${{…:-<N>}}` 赋值 —— "
            "命令内容超限又只能在云上冒一个 `SDKError 400`（本机看不见）"
        )
    elif int(m.group(1)) != leg.get("limit_bytes_expected"):
        problems.append(
            f"`{rel}` 的闸值默认值 {m.group(1)} ≠ 台账 `limit_bytes` {leg.get('limit_bytes_expected')} "
            "—— 闸值被悄悄改大（或台账与代码漂移）"
        )
    if not any(LIMIT_COMPARE in line for line in live):
        problems.append(
            f"`{rel}` 活行里没有 `{LIMIT_COMPARE}` 这条比较 —— 字节读数组装出来了却没人判它"
        )
    if not any(LIMIT_SOURCE_URL in line for line in live):
        problems.append(
            f"`{rel}` 活行里没有给出上限的**出处**（官方文档 URL 含 `{LIMIT_SOURCE_URL}`）"
            " —— 「16 KB」会退化成一个没有出处的魔数"
        )
    for line in live:
        if INLINE_CAT_RE.search(line):
            problems.append(
                f"`{rel}` 的活行里有**未转义**的命令替换 `cat`（把仓内文件内容拼进命令内容）："
                f"`{line.strip()[:160]}` —— 这正是 #6095/#6124 的病根（命令内容随远端脚本一起长）"
            )
    return problems


def _problems(ledger: dict, scripts: dict[str, str], workflows: str) -> list[str]:
    """类级判定**本体**（纯函数；红证在内存里构造，不必改真文件）。"""
    problems: list[str] = []

    for key in LEDGER_REQUIRED_KEYS:
        if key not in ledger:
            problems.append(f"台账缺字段 `{key}`（fail-closed：字段齐备才谈得上判定）")
    legs = ledger.get("legs") or []
    if not legs:
        problems.append("台账 `legs` 为空 —— 空台账 = 这条元守卫退化成空断言（fail-closed）")

    if ledger.get("limit_bytes") != EXPECTED_LIMIT_BYTES:
        problems.append(
            f"台账 `limit_bytes` = {ledger.get('limit_bytes')!r} ≠ {EXPECTED_LIMIT_BYTES} "
            "—— 上限出处（官方 base64 后 ≤16 KB）与既有实测（43.8~50.7 KB 即被拒）取的是**最保守**值，"
            "不许悄悄放宽"
        )
    if LIMIT_SOURCE_URL not in str(ledger.get("limit_source", "")):
        problems.append(f"台账 `limit_source` 不是官方文档 URL（应含 `{LIMIT_SOURCE_URL}`）")

    scope = _scope_paths(scripts, workflows)
    registered = [leg.get("path") for leg in legs]
    for rel in scope:
        if rel not in registered:
            problems.append(
                f"`{rel}` 是**射程内**的 CI 腿（含活行 `{SCOPE_MARKER}` 且被 workflow 调用）却没登记"
                f"在 {LEDGER_REL} —— 未登记即红"
            )
    for rel in registered:
        if rel not in scope:
            problems.append(
                f"台账登记了 `{rel}`，但它不在现取射程里（脚本不存在 / 不再含 `{SCOPE_MARKER}` / "
                "不再被任何 workflow 调用）—— 台账不许给不存在的对象盖章"
            )

    for leg in legs:
        for key in LEG_REQUIRED_KEYS:
            if not leg.get(key):
                problems.append(f"台账条目 `{leg.get('id', '<无 id>')}` 缺字段 `{key}`")
        rel = leg.get("path")
        if rel in scripts:
            leg_ctx = dict(leg, limit_bytes_expected=ledger.get("limit_bytes"))
            problems.extend(_leg_problems(leg_ctx, scripts[rel]))
    return problems


def _load_ledger() -> dict:
    return json.loads((REPO / LEDGER_REL).read_text(encoding="utf-8"))


def _repo_scripts() -> dict[str, str]:
    return {
        p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((REPO / SCRIPTS_DIR_REL).rglob("*.sh"))
    }


def _repo_workflows() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted((REPO / WORKFLOWS_DIR_REL).glob("*.yml"))
    )


# ── 真语料：对照读数 ────────────────────────────────────────────────────────────

def test_real_repo_has_no_problems():
    """对照读数：**真语料**上一条问题都不许有（下面每条红证都以它为基线）。"""
    problems = _problems(_load_ledger(), _repo_scripts(), _repo_workflows())
    assert problems == [], "SWAS 命令内容契约被判红：\n" + "\n".join(f"  · {p}" for p in problems)


def test_scope_is_not_empty_and_contains_the_four_known_legs():
    """射程不许空（空射程 ⇒ 上面那条判据变成恒真）—— 并钉住四条已知腿。"""
    scope = _scope_paths(_repo_scripts(), _repo_workflows())
    assert {"deploy/scripts/swas-deploy-ci.sh",
            "deploy/scripts/swas-h5-publish-ci.sh",
            "deploy/scripts/bmini-h5-publish-ci.sh",
            "deploy/scripts/c-end-h5-publish-ci.sh"} <= set(scope), f"射程少了已知腿：{scope}"
    # 人跑的一次性向导**不在**射程（它不被任何 workflow 调用）—— 这条是上面那条的对照面
    assert "deploy/scripts/wx-mini-test-env-setup.sh" not in scope, (
        "人跑的向导进了射程 ⇒ 射程规则（被 workflow 调用）没生效"
    )


def test_each_leg_actually_guards_bytes_before_any_cloud_call(tmp_path):
    """读数层之外的**相邻形态**：断言必须出现在发起云调用**之前**（同一腿内的相对位置）。

    只判「有那几行」不够 —— 有人可以把断言挪到 `RunCommand` **之后**（那时已经晚了）。
    """
    wf_call = re.compile(r'^\s*--command-content\s+"\$', re.M)
    expect = re.compile(r'-ge "\$COMMAND_CONTENT_LIMIT_BYTES"', re.M)
    for leg in _load_ledger()["legs"]:
        src = (REPO / leg["path"]).read_text(encoding="utf-8")
        gu = expect.search(src)
        wf = wf_call.search(src)
        assert gu, f"`{leg['path']}` 找不到「超限即判红」的比较"
        assert wf, f"`{leg['path']}` 找不到 `--command-content` 的调用点"
        assert gu.start() < wf.start(), (
            f"`{leg['path']}` 的字节前置断言出现在云调用**之后**（位置 {gu.start()} > {wf.start()}）"
            " —— 那时命令内容已经发出去了，判红也拦不住"
        )


# ── 判别力自证（注入式红证）─────────────────────────────────────────────────────

def _mutated(**kw) -> list[str]:
    """在**真语料**上注入一处变异，返回判定结果（红证与对照读数共用同一条判定本体）。"""
    ledger = _load_ledger()
    scripts = _repo_scripts()
    workflows = _repo_workflows()
    leg0 = ledger["legs"][0]["path"]
    if "add_leg" in kw:
        scripts["deploy/scripts/zz-new-h5-publish-ci.sh"] = (
            "#!/bin/bash\nexport H5_SUBDIR=z\n"
            "aliyun swas-open run-command --command-content \"$COMMAND_CONTENT\"\n"
        )
        workflows += "\nbash deploy/scripts/zz-new-h5-publish-ci.sh\n"
    if "drop_entry" in kw:
        ledger["legs"] = [x for x in ledger["legs"] if x["path"] != leg0]
    if "drop_guard" in kw:
        scripts[leg0] = scripts[leg0].replace(LIMIT_COMPARE, "-ge 0")
    if "drop_source" in kw:
        scripts[leg0] = scripts[leg0].replace(LIMIT_SOURCE_URL, "example.com/no-source")
    if "widen_limit" in kw:
        scripts[leg0] = scripts[leg0].replace(":-16384}", ":-65536}")
    if "inline" in kw:
        target = ledger["legs"][1]["path"]
        scripts[target] = scripts[target].replace(
            "$REMOTE_FETCH\"", '$(cat "$REMOTE_SCRIPT")"', 1)
    if "empty_ledger" in kw:
        ledger["legs"] = []
    if "comment_only" in kw:
        scripts[leg0] = "# 讲课注释：曾经写成 leak=$(cat \"$REMOTE_SCRIPT\") 那样\n" + scripts[leg0]
    return _problems(ledger, scripts, workflows)


def test_unregistered_new_leg_turns_red():
    """坏形态 ①：新增一条射程内、没登记的发布腿 ⇒ 未登记即红。"""
    problems = _mutated(add_leg=True)
    assert any("zz-new-h5-publish-ci.sh" in p and "未登记即红" in p for p in problems), problems


def test_dropping_a_registry_entry_turns_red():
    """坏形态 ②：把某条腿从台账里删掉（想让判定少判一条）⇒ 红。"""
    assert any("未登记即红" in p for p in _mutated(drop_entry=True))


def test_removing_the_byte_guard_turns_red():
    """坏形态 ③：删掉「超限即判红」那道闸 ⇒ 红（这是本类缺陷最直接的回退形态）。"""
    assert any("这条比较" in p for p in _mutated(drop_guard=True))


def test_removing_the_limit_source_turns_red():
    """坏形态 ④：删掉上限的出处 ⇒ 红（16 KB 不该是无出处的魔数）。"""
    assert any("出处" in p for p in _mutated(drop_source=True))


def test_widening_the_limit_turns_red():
    """坏形态 ⑤：把闸值悄悄放宽（16384 → 65536）⇒ 红。"""
    assert any("闸值" in p for p in _mutated(widen_limit=True))


def test_inlining_the_remote_body_again_turns_red():
    """坏形态 ⑥：把「内联远端执行体」的旧写法放回**活行** ⇒ 红（这是 #6095/#6124 的病根本身）。"""
    problems = _mutated(inline=True)
    assert any("未转义" in p and "cat" in p for p in problems), problems


def test_empty_ledger_turns_red():
    """坏形态 ⑦：清空台账「消红」⇒ 红（fail-closed）。"""
    assert any("legs` 为空" in p for p in _mutated(empty_ledger=True))


def test_comment_only_edit_does_not_turn_red():
    """对照读数：**只改注释**（注释里逐字写出内联写法）⇒ **不红**。

    这条是「判据不许被自己的讲课文案喂红」的机械载体 —— 没有它，上面那条 `inline` 红证
    可能只是因为判据在**注释**上判红（那就成了另一种空断言）。
    """
    assert _mutated(comment_only=True) == [], (
        "整行注释里的内联写法被判红 ⇒ 判据没有区分「引用」与「使用」（讲课材料天然要引用这些串）"
    )
