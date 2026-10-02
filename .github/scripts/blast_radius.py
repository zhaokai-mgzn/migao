#!/usr/bin/env python3
"""变更射程 → 必跑具名判据（**单一数据源**，供文档与 growth_gate 提示共用）。

## 为什么有它（实证，不是臆测）

2026-10-02 这批并行开发给每个包下的硬约束是「**不跑全量套件**（`verify-all.sh` 各档不跑，
重活锁归集成侧）」。结果**四条 PR 全栽在同一处**，共 **17 条红**，形态完全相同 ——
**判据只存在于全量单测里，窄跑看不见**：

| PR | 红 | 缺的面 |
|---|---|---|
| #5961 | 7 | 复位族登记 · 写点登记 · 产出键/断言规格 · 产出键快照 |
| #5963 | 1 | state 必需字段期望 |
| #5965 | 5 | 工具见证集 · 核定权限码映射 · 工具门面导出 · RBAC 单一源清单与上限 · 死能力 meta-guard 扫面 |
| #5967 | 4 | 迁移指纹 · bootstrap 建库面 · 事件通道基线 · 台账销账 |

**根因**：这些判据**不在任何窄测试文件里**，`growth_gate` 与 cases 面门禁**都不覆盖**它们
⇒ 只跑窄测试的包在这些面上是**结构性盲的**。

**口径（逐字，本模块与文档共用）**：

> **「窄集」必须由「变更的射程」反推** —— 改了工具源码 ⇒ **所有扫工具源码的 meta 面都在射程内**；
> 不是靠回忆清单。

## 单一数据源与防漂移

本模块 = 数据源，`docs/wiki/Change-Blast-Radius.md` = 人读镜像。
漂移判据（两个方向，各自会红）：
- `tests/unit_ci_workflows/test_blast_radius_registry.py::test_every_face_is_reachable_by_some_path`
  —— 注册了却**永远匹配不到**任何仓内文件的面 ⇒ 红（提示会永远沉默）；
- 同文件 `::test_doc_mirrors_every_face` —— 文档里少一个面 / 多一个不存在的面 ⇒ 红；
- 同文件 `::test_every_probe_points_at_a_real_file` —— 命令里的具名判据文件在仓内**不存在** ⇒ 红
  （**不许凭印象写**，本 bundle 的硬要求）。

## 边界（照实登记）

- **只提示，不阻塞**：本模块**不改** `growth_gate` 的 `blocker_count` 语义（提示是 `warn` 级 / 独立段）。
- 覆盖不到：人在仓外（没跑 `growth_gate` 就直接开 PR）时提示不会出现；`glob` 只认路径形态，
  判不了「改动的语义射程」（如改了工具**行为**而没改文件路径）。
"""

#: 面 → 该面扫的具名判据（`tests/unit_ci_workflows/**` 与 `.github/scripts/**` 共用的一族）。
#: 每项 `paths` 是 `fnmatch` 形态的仓内相对路径 glob（`*` 跨 `/`，与 growth_gate 的豁免口径一致）。
FACES = [
    {
        "face": "tool",
        "paths": [
            "backend/ai-agent-service/app/tools/*.py",
            "backend/ai-agent-service/app/graph/skills/*.py",
        ],
        "why": "工具源码被 6 个 meta 面扫：注册器/门面导出、核定权限码、只读跨域见证、"
               "死能力死引用死绑定、与页面权限对账、skill 绑定面",
    },
    {
        "face": "state",
        "paths": ["backend/ai-agent-service/app/graph/state.py"],
        "why": "`AgentState` 是图的公共形状：加/删字段要同时改初始状态期望与图结构面",
    },
    {
        "face": "migration",
        "paths": [
            "backend/admin-api/src/main/resources/db/migration/*.sql",
            "backend/admin-api/src/main/resources/db/init/schema.sql",
        ],
        "why": "已发布迁移**内容冻结**（指纹账本）+ schema.sql 是 bootstrap 建库面 + "
               "两者都有「引用的表/列必须存在」的对账",
    },
    {
        "face": "batch",
        "paths": ["tests/unit_ci_workflows/case_machine_fail_channel_baseline.json"],
        "why": "批次台账写入点唯一 + 来源族列形状互斥（改基线快照要同批销账）",
    },
    {
        "face": "eval-fixture",
        "paths": [
            "tests/agent_eval/local_runner.py",
            "tests/agent_eval/output_keys_snapshot.json",
        ],
        "why": "夹具层：复位族（pre/post_clean）登记 · 写点处置表 · 产出键快照与断言规格",
    },
    {
        "face": "rbac",
        "paths": [
            "backend/ai-agent-service/rbac/*.json",
            "backend/ai-agent-service/rbac/*.py",
            "frontend/admin-web/src/config/menu.ts",
        ],
        "why": "权限/菜单码有四处源：单一源清单 == 生成物 == 现值，且与后端注解逐面钉住",
    },
    {
        "face": "casebook",
        "paths": [".github/cases/*.yml", ".github/templates/*.yml"],
        "why": "用例面是**生成物之源**：改源必须重渲染 + 验真值引用 + 过 YAML 严格性",
    },
    {
        "face": "web",
        "paths": [
            "frontend/admin-web/src/app/*.tsx",
            "frontend/admin-web/src/app/*/*.tsx",
            "frontend/admin-web/src/components/*.tsx",
        ],
        "why": "改 web 页面另有 UI 回退检测与多模态验收（`migao-dev-flow` §15.7）",
    },
]

#: `ai-agent-service` 的 pytest 解释器：**现取**（worktree 里 `.venv` 常缺 ⇒ 退回 PATH 上的 `python3`）。
#: 为什么现取：命令要「可复制」，写死一个本机不存在的路径 = 文档给了跑不通的命令（本 bundle 的硬要求之二）。
def agent_python(repo_root="."):
    import os
    venv = os.path.join(repo_root, "backend/ai-agent-service/.venv/bin/python")
    return venv if os.path.exists(venv) else "python3"


class Probe:
    """一条**可复制**的探针。

    `command` 从 `cwd` 逐字可执行；`judgement` = 该命令真正加载的**具名判据**（仓内相对路径，
    `""` = 命令本身即可执行、不入 pytest 判据面，如 UI 回退检测）；
    `source` = 与之对应的**命令实现**（`.sh` / `.py`），供防漂移判据核「这条命令真的存在」。
    """

    __slots__ = ("check", "command", "cwd", "judgement", "source")

    def __init__(self, check, judgement, agent_test=None, ci_test=None, raw=None, cwd=None,
                 repo_root=".", source=None):
        self.check = check
        self.judgement = judgement
        self.source = source
        if raw is not None:
            self.command = raw
            self.cwd = cwd or "."
            return
        if agent_test is not None:
            self.cwd = cwd or "."
            self.command = f"{agent_python(repo_root)} -m pytest {agent_test} -q"
            return
        self.cwd = cwd or "."
        self.command = f"python3 -m pytest {ci_test} -q"


#: `ai-agent-service` 的 pytest 探针：**从仓根**用**仓库相对全路径**跑。
#:
#: 为什么不写 `cd backend/ai-agent-service && pytest tests/x.py`：本仓有判据
#: （`tests/unit_ci_workflows/test_recomputable_command_paths.py`，M4）会逐字解析文档/注释里的
#: 「可复算命令」并核**它指涉的路径是否存在** ⇒ `cd` 之后写的相对路径**它解析不到**，会判红
#: （实测：本文件首版就是这么写的，`test_no_unregistered_stale_recomputable_paths` 4 failed）。
#: 全路径写法两边都成立：人能直接复制，判据也能核（且 pytest 的 rootdir 推断按 conftest 走）。
def _agent(repo_root, check, *tests, judgement=None):
    full = [f"backend/ai-agent-service/{t}" for t in tests]
    return Probe(check, judgement or full[0], agent_test=" ".join(full),
                 repo_root=repo_root)


def _ci(check, *tests, judgement=None):
    """`tests/unit_ci_workflows/**` 的 pytest 探针。"""
    return Probe(check, judgement or tests[0], ci_test=" ".join(tests))


#: 面 → 探针清单。`check` = 这张登记面在**人话里**是什么（提示里逐条打印）。
#: 是**函数**不是常量：解释器路径要按 `repo_root` **现取**（见 `agent_python`）。
def probes_by_face(repo_root="."):
    return {

    "tool": [
        _agent(repo_root, "工具门面导出 / 注册器契约", "tests/test_tools_registry.py"),
        _agent(repo_root, "核定权限码映射（工具 ↔ 码）", "tests/test_tool_permission_codes.py"),
        _agent(repo_root, "只读跨域共享见证集",
               "tests/test_readonly_cross_domain_sharing.py"),
        _ci("死能力 meta-guard（死引用/死守卫/死绑定）",
            "tests/unit_ci_workflows/test_dead_capability_meta_guard.py"),
        _ci("Agent 功能权限 ≡ 页面权限（四源对账）",
            "tests/unit_ci_workflows/test_agent_permission_parity.py"),
        _agent(repo_root, "skill 配置与工具绑定面", "tests/test_skill_config_registry.py"),
    ],
    "state": [
        _agent(repo_root, "初始状态必需字段期望", "tests/test_agent_state.py"),
        _agent(repo_root, "图的 state 形状与节点接线", "tests/test_graph_state.py"),
    ],
    "migration": [
        _ci("迁移内容指纹冻结 + 未登记即红",
            "tests/unit_ci_workflows/test_migration_immutability.py"),
        _ci("迁移引用的表/列在 schema 里存在",
            "tests/unit_ci_workflows/test_migration_references_exist_in_schema.py"),
    ],
    "batch": [
        _ci("批次台账写入点唯一 + 来源族列形状互斥",
            "tests/unit_ci_workflows/test_batch_stocktake_write_point.py"),
        _ci("事件通道基线快照", "tests/unit_ci_workflows/test_case_machine_fail_channel.py"),
        _ci("写点处置表（新增/删除写调用先红）",
            "tests/unit_ci_workflows/test_eval_write_site_dispositions.py"),
    ],
    "eval-fixture": [
        _ci("复位族（pre/post_clean）登记与阶段一致性",
            "tests/unit_ci_workflows/test_eval_preclean_registry.py"),
        _ci("产出键可生产 + 推导钉死 + 快照",
            "tests/unit_ci_workflows/test_assertion_specs_wellformed.py"),
    ],
    "rbac": [
        _ci("RBAC 单一源清单 == 生成物 == 现值",
            "tests/unit_ci_workflows/test_rbac_single_source_manifest.py"),
        _ci("菜单三源同构 + 岗位码面",
            "tests/unit_ci_workflows/test_agent_permission_parity.py"),
    ],
    "casebook": [
        _ci("用例 YAML 严格性", "tests/unit_ci_workflows/test_cases_yaml_strictness.py"),
        _ci("用例 → 生成物域映射覆盖", "tests/unit_ci_workflows/test_render_cases_domain_map.py"),
        Probe("重渲染两端生成物 + 复算新鲜度（**禁手改生成物**）", "",
              raw="python3 .github/render_cases.py --cases .github/cases "
                  "--out-eval tests/agent_eval/eval_cases.py "
                  "--out-md docs/testing/mibao-verification-cases.md && "
                  "git diff --exit-code tests/agent_eval/eval_cases.py "
                  "docs/testing/mibao-verification-cases.md",
              source=".github/render_cases.py"),
        Probe("真值引用完整性（fail-closed，rc 必须 0）", "",
              raw="python3 .github/truths.py check --templates .github/templates --cases .github/cases",
              source=".github/truths.py"),
    ],
    "web": [
        Probe("UI 回退检测（neutral token vs origin/main）", "",
              raw="./check-ui-regression.sh", source="check-ui-regression.sh"),
    ],
}


def _matches(path, pattern):
    """`*` 跨 `/` 的 glob 匹配（与 growth_gate 的豁免口径同款，见 `is_exempt`）。"""
    import fnmatch
    return fnmatch.fnmatch(path, pattern)


def hit_faces(paths, faces=None):
    """变更文件 → 命中的射程面（保序、去重）；`paths` 为仓内相对路径。

    返回 `[{"face", "why", "paths"}]`，只含**至少一条**变更路径落在该面 `paths` 里的面。
    """
    faces = FACES if faces is None else faces
    out, seen = [], set()
    for entry in faces:
        for path in paths:
            if any(_matches(path, pat) for pat in entry["paths"]):
                if entry["face"] not in seen:
                    seen.add(entry["face"])
                    out.append({k: entry[k] for k in ("face", "why", "paths")})
                break
    return out


def probes_for(face, repo_root="."):
    """某面的探针清单（未登记的 face ⇒ 空列表，调用方自己决定怎么报）。"""
    return list(probes_by_face(repo_root).get(face, []))


def render_hint(hits, repo_root="."):
    """把命中的面渲染成**控制台/step summary** 上的非阻塞提示（`""` = 无命中）。

    形态（逐字，判据 `test_growth_gate_blast_radius.py` 按此解析）：
    首行 `⚠️ 变更射程提示（非阻塞，不计入 blocker）` + 逐面一条 + 该面探针各一行命令。
    """
    if not hits:
        return ""
    table = probes_by_face(repo_root)
    lines = ["", "## ⚠️ 变更射程提示（非阻塞，不计入 blocker）", "",
             f"你的变更射程命中了 **{len(hits)} 个面** ⇒ 疑似还欠下面这几张登记面"
             "（**窄跑看不见**，判据都在全量单测里）：", ""]
    for h in hits:
        lines.append(f"### · `{h['face']}` — {h['why']}")
        lines.append("")
        for p in table.get(h["face"], []):
            cmd = f"{p.command}" if p.cwd in (None, ".") else f"cd {p.cwd} && {p.command}"
            lines.append(f"- **{p.check}**")
            lines.append("")
            lines.append("  ```bash")
            lines.append(f"  {cmd}")
            lines.append("  ```")
        lines.append("")
    lines.append("> 口径：**「窄集」必须由「变更的射程」反推** —— 改了工具源码 ⇒ "
                 "**所有扫工具源码的 meta 面都在射程内**；不是靠回忆清单。")
    lines.append("> 全表见 `docs/wiki/Change-Blast-Radius.md`。本段**不阻塞合并**"
                 "（`blocker_count` 语义不变）。")
    return "\n".join(lines)
