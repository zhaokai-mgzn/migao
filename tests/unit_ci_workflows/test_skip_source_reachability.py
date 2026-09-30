# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012。）
r"""**类级元守卫**：部署腿「skip / 去重」判据的**真值来源**必须登记，且必须**真的可命中**（issue #5814）。

## 病（本 PR 自己踩到，且**没有任何东西会变红**）

三条 `deploy-*.yml` 的 `Skip if already built (schedule reconcile)` 步里，「该 commit 已构建过 ⇒ 秒退」
这条判据，改前的**唯一**真值来源是**外部探针** `docker manifest inspect "$IMAGE"`（ACR）。
C′（服务器侧构建）**不再推 ACR** ⇒ 该探针**恒不成立** ⇒ `skip` 恒为 `false`
⇒ **每次 cron 都完整构建 + 完整部署**（3 条腿 × 3 次/小时 = **9 次全量重部署/小时**，与代码有没有改动无关）。

🔴 **而承重判据 `test_sync_leg_still_builds_when_last_run_is_recoverable` 当时是绿的** ——
它只桩了「结论分支」，**前提（镜像缺失）是恒真的**，所以行为翻了个面也照样通过。
⇒ 这是「判据的前提随环境漂移」的实例（铁律 8「不会红的判据 = 空断言」、铁律 9「main 侧没有守护」）。

## 本判据

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | 语料与台账非空（反空跑） | 扫不到被登记的腿 / 台账空 ⇒ 红 |
| 2 | 每条登记的臂，其 `anchor` 必须在**每条腿**的 skip 步正文里逐字存在 | 臂被删/改形 ⇒ 红（陈旧登记） |
| 3 | 🔴 **至少一臂在当前架构（C′）下可命中**（`reachable_under_c_prime=true`） | 全部标 false、或 C′ 那一臂被删掉 ⇒ 红（= skip 恒 false ⇒ churn 循环） |
| 4 | 每条可命中的臂必须给出 `firing_proof`（`文件::测试名`），且该测试**真的存在** | 声称有证明却没有 ⇒ 红（防「声明存在 ≠ 可达」） |
| 5 | 🔴 **未登记即红**：腿正文里出现的**外部探针**（`docker manifest inspect` / `curl` / `gh api`）必须被某条臂登记 | 新接一个外部探针面却不登记 ⇒ 红 |
| 6 | 台账 ⇄ `external_probe_markers` **双向**（标记集不许偷偷缩小） | 把标记删掉以避开判据 5 ⇒ 红 |
| 7 | `coverage_boundary` 逐条有 `face`+`reason`+`recompute` | 删掉任一条 ⇒ 红 |

## 判定方式是确定的（零网络、零时钟）

只读仓内文件（`.github/workflows/deploy-*.yml` + 本目录台账 JSON）⇒ 同一份代码任何时刻同一读数。
**不绑 `origin/main`**（CI 的 pr-check 是 `fetch-depth: 1`，取不到）。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
LEDGER_PATH = Path(__file__).with_name("skip_source_ledger.json")


def load_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def skip_step_body(leg: str, job: str, step_name: str) -> str:
    """取出该腿 skip 步的 `run` 正文（判据只看**真文本**）。"""
    doc = yaml.safe_load((WORKFLOWS / leg).read_text(encoding="utf-8"))
    for step in doc["jobs"][job]["steps"]:
        if step.get("name") == step_name:
            body = step.get("run")
            assert body, f"{leg}: skip 步没有 run 正文（判据已过期）"
            return body
    raise AssertionError(f"{leg}: 找不到 skip 步 `{step_name}`（判据已过期）")


def registered_problems(ledger: dict, bodies: dict[str, str]) -> list[str]:
    """纯函数：把判据 1~6 重算成问题清单（供红证注入参数化调用）。"""
    v: list[str] = []
    legs, arms = ledger.get("legs") or [], ledger.get("arms") or []
    if not legs or not arms:
        v.append("反空跑：台账缺 legs / arms（空集不是通过）")
    # 2. 每条臂的 anchor 必须在每条腿里逐字存在
    for arm in arms:
        for leg in legs:
            if arm["anchor"] not in bodies.get(leg, ""):
                v.append(f"{leg}: 登记的臂 `{arm['id']}` 锚点不存在（陈旧登记）：{arm['anchor'][:60]!r}")
    # 3. 至少一臂在 C′ 下可命中
    reachable = [a for a in arms if a.get("reachable_under_c_prime")]
    if len(reachable) < int(ledger.get("min_reachable_under_c_prime", 1)):
        v.append(
            "没有**可命中**的臂（全部 reachable_under_c_prime=false）⇒ `skip` 会恒为 false "
            "⇒ 每次 cron 都完整构建+部署（C′ 的 churn 循环）"
        )
    # 4. 可命中的臂必须有真的 firing_proof
    for arm in reachable:
        proof = str(arm.get("firing_proof") or "")
        if not proof:
            v.append(f"臂 `{arm['id']}` 声明可命中却没有 `firing_proof`（声称有证明才算数）")
            continue
        rel, _, test_name = proof.partition("::")
        f = REPO / rel
        if not f.is_file():
            v.append(f"臂 `{arm['id']}` 的 firing_proof 指向不存在的文件：{rel}")
        elif test_name and f"def {test_name}(" not in f.read_text(encoding="utf-8"):
            v.append(f"臂 `{arm['id']}` 的 firing_proof 测试名不存在：{test_name}")
    # 5/6. 未登记的外部探针 ⇒ 红
    markers = ledger.get("external_probe_markers") or []
    if not markers:
        v.append("反空跑：`external_probe_markers` 为空（判据 5 会退化成空断言）")
    for leg in legs:
        body = bodies.get(leg, "")
        for marker in markers:
            if marker in body and not any(marker in a["anchor"] for a in arms):
                v.append(f"{leg}: 外部探针 `{marker.strip()}` 未登记到任何臂（未登记即红）")
    # 7. coverage_boundary 逐条齐备
    for entry in ledger.get("coverage_boundary") or []:
        if not (entry.get("face") and entry.get("reason") and entry.get("recompute")):
            v.append(f"coverage_boundary 条目缺 face/reason/recompute：{entry!r}")
    if not (ledger.get("coverage_boundary") or []):
        v.append("反空跑：coverage_boundary 为空")
    return v


def _bodies(ledger: dict) -> dict[str, str]:
    return {
        leg: skip_step_body(leg, ledger["job_name"], ledger["step_name"])
        for leg in ledger["legs"]
    }


def test_real_ledger_and_legs_are_clean():
    """前提：真语料先绿（否则红证分不清是注入还是存量）。"""
    ledger = load_ledger()
    assert registered_problems(ledger, _bodies(ledger)) == []


def test_ledger_red_proofs():
    """注入式红证：5 类坏形态各能单独变红 + 「只加注释 ⇒ 不红」对照。"""
    ledger = load_ledger()
    bodies = _bodies(ledger)
    base = registered_problems(ledger, bodies)
    assert base == [], f"前提：真语料先绿，实得 {base}"

    import copy

    # ① 删掉 C′ 那一臂的锚点（模拟「臂被删/改形」）⇒ 判据 2 红
    broken = copy.deepcopy(ledger)
    bodies1 = dict(bodies)
    arm = next(a for a in broken["arms"] if a["id"] == "same_sha_success")
    for leg in broken["legs"]:
        bodies1[leg] = bodies[leg].replace(arm["anchor"], "if false; then")
    assert arm["anchor"] not in bodies1[broken["legs"][0]], "注入未生效"
    assert registered_problems(broken, bodies1), "删掉 C′ 臂的锚点后没红 ⇒ 判据 2 是空断言"

    # ② 把所有臂标成不可命中 ⇒ 判据 3 红（= skip 恒 false ⇒ churn 循环）
    broken2 = copy.deepcopy(ledger)
    for a in broken2["arms"]:
        a["reachable_under_c_prime"] = False
    assert registered_problems(broken2, bodies), "全部臂标成不可命中却没红 ⇒ 判据 3 是空断言"

    # ③ 伪造 firing_proof（指向不存在的测试名）⇒ 判据 4 红
    broken3 = copy.deepcopy(ledger)
    next(a for a in broken3["arms"] if a["id"] == "same_sha_success")["firing_proof"] = (
        "tests/unit_ci_workflows/test_deploy_breaker_allowlist.py::test_this_does_not_exist"
    )
    assert registered_problems(broken3, bodies), "伪造 firing_proof 却没红 ⇒ 判据 4 是空断言"

    # ④ 往腿正文里塞一个**未登记**的外部探针 ⇒ 判据 5 红（未登记即红）
    bodies4 = dict(bodies)
    bodies4[ledger["legs"][0]] = bodies[ledger["legs"][0]] + '\ncurl -fsS https://example.com/x\n'
    assert registered_problems(ledger, bodies4), "塞入未登记的外部探针却没红 ⇒ 判据 5 是空断言"

    # ⑤ 台账里把标记集清空（以避开判据 5）⇒ 判据 5/6 红
    broken5 = copy.deepcopy(ledger)
    broken5["external_probe_markers"] = []
    assert registered_problems(broken5, bodies), "清空 external_probe_markers 却没红 ⇒ 标记集可被绕过"

    # ⑥ 对照读数：**只加注释** ⇒ 不红
    bodies6 = dict(bodies)
    bodies6[ledger["legs"][0]] = bodies[ledger["legs"][0]] + (
        "\n# 注释：这里提到 docker manifest inspect 与同 sha 的 run 结论，但都不是命令\n"
    )
    assert registered_problems(ledger, bodies6) == [], "只加注释就判红 ⇒ 判据误吃说明文字（假红）"


def test_coverage_boundary_is_registered():
    """覆盖边界逐条有 face + reason + recompute（删掉任一条 ⇒ 红）。"""
    ledger = load_ledger()
    boundary = ledger.get("coverage_boundary") or []
    assert len(boundary) >= 4, f"覆盖边界只登记了 {len(boundary)} 条（本形态至少 4 条，现取）"
    for entry in boundary:
        assert entry.get("face") and entry.get("reason") and entry.get("recompute"), entry
