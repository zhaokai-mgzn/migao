# case_ids: MC-012
"""`scripts/eval_closeout.py` —— 判定档「跑后收口核对」固化（issue #4258）。

## 为什么要固化（而不是继续手写 /tmp 脚本）

对 6~7 个 run 做收口核对时反复手写同一套逻辑（`35256153429` / `35264687083` / `35268148590` /
`35273366357` / `35274766286` / `35295494688` / `35308430491`），每次都要人工读 summary + 比对历史，
且**极易把「通过但被 fail-closed 阻塞」与「真失败」混读**（#4207 就是这类事故的登记）。
本文件守的是「读结论」这件事本身：**读错结论的代价与跑错一样大**。

## 与本文件无关的邻居（边界，避免重复造轮子）

`tests/agent_eval/acceptance_runner.py` 是**剧本式活体验收**（打线上端点抓 SSE/卡片）——
与「跑后产物收口」用途不同，两者互补；本脚本**不复制**它的任何逻辑，只消费它已经落盘的
`eval-summary-*.json` / run 步骤 JSON。

## 五组判据（每组都必须能红，见 PR 报告的红证表）

① **未评测必须判「未评测」并停**：抑制/取消的**留档步骤一旦跑了** ⇒ 直接判「本 run 未评测」，
   退出码 3（不是 0、不是 1），且**不得**继续做桶分解/逐条收口（未评测的 run 没有可分解的桶）。
   夹具两种形态都取**真实 run 的步骤形状**：抑制 = `34841093824`（整条 job `success`、`Run`/`判定`
   全 `skipped`、留档步骤 `success`）；取消 = `34855662092`（job `cancelled`、`判定` 仍是 `failure`
   —— 这是 #3761 之前的行为，**只靠"判定 skipped"抓不到**，必须同时看 job 结论）。
② **「通过但跨 run 复发」必须落 systemic，不得按「未通过列表」读成通过**：`score==1.0` 的
   放行条目只要带 `cross_run_recurrence`，在逐条收口里就是**未收口**（判据 = 阻塞桶成员身份，
   不是 `score<1`）。这正是 #4207 的口径（"未通过列表"会漏计）。
③ **桶分解必须覆盖每一个阻塞桶键（防漏桶）**：判据是**动态**的 ——
   `set(completion) - NON_BLOCKING_VERDICT_KEYS`，而不是写死桶名清单
   （#4245 正在并行新增 `case_asset_failures`；写死清单 ⇒ 它合并后必然漏桶）。
   本组**同时**用真实 `local_runner.completion_verdict` 的返回值锁一遍（跨模块、非自证）。
④ **`replayed=True` 计数**：以**证据原文出现次数**为准（历史口径 `0/11/10/7/12/8/0` 可复算），
   而不是"命中用例数"（实测 `35295494688` mibao 腿：3 条用例、4 次出现 ⇒ 两者必须分开报）。
⑤ **反向（防恒真/恒红）**：正常全绿 summary + 全 `success` 步骤 ⇒ 退出码 0，且
   **不得**打印「未评测」抬头、**不得**打印「判红」。

case_ids 口径：本测试属 **dev/CI 工具链**，与同族 `test_red_proof_guard.py`（#4260）、
`test_stranding_check.py`（#4065）、`test_dev_worktree_rebase.py`（#3972）沿用同一组 case id
（`MC-012`）—— 仓库没有「开发工具链」用例族，塞进行为用例库会污染覆盖矩阵（同族 PR 既有裁定）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "eval_closeout.py"

# append（**不是** insert）：只作兜底解析路径，避免遮蔽 site-packages 里的同名模块。
sys.path.append(str(REPO_ROOT / "scripts"))

import eval_closeout as ec  # noqa: E402

SHA = "d5bca2416b21d331cbfb42e4af63c6a6a307c583"
BASE_SHA = "78f83d81" + "0" * 32

#: 夹具里出现的**全部**阻塞桶（含 #4245 正在并行新增的 `case_asset_failures`）。
#: 这是**夹具**的桶清单，不是被测实现的清单 —— 实现必须动态枚举（见 ③）。
ALL_BUCKETS = (
    "deterministic_failures",
    "journey_failures",
    "systemic_recurrence",
    "restore_failures",
    "harness_incompatible_failures",
    "case_asset_failures",          # #4245（并行包）—— 防「写死桶名清单」漏桶
)


# ── 夹具构造（照真实 artifact 形状，见 /tmp 里下载的 run 35295494688）──────────────

def mk_case(cid, score=1.0, **extra):
    c = {"id": cid, "score": score, "classification": "pass" if score >= 1.0 else "reproducible",
         "pre_clean": []}
    c.update(extra)
    return c


def mk_summary(persona="mibao", cases=None, buckets=None, sha=SHA, ok=None, label=None):
    """一份 `eval-summary-<persona>.json`（键集照真实 artifact，只留被测实现消费的部分）。"""
    cases = list(cases if cases is not None else [mk_case("OR-010")])
    base = {k: [] for k in ALL_BUCKETS}
    base.update(buckets or {})
    total = len(cases)
    passed = sum(1 for c in cases if c.get("score", 0) >= 1.0)
    completion = {
        "ok": (not any(base.values())) if ok is None else ok,
        "reason": "夹具",
        **base,
        "flake_released": [],
        "total": total,
        "passed": passed,
        "failure_reasons": {},
    }
    return {
        "label": label or persona, "shard": "",
        "total": total, "passed": passed, "failed": total - passed, "avg_score": 0.0,
        "order_write_cases": 0, "write_cases_ok": 0,
        "cases": cases, "completion": completion, "cost": {},
        "run_key": {"sha": sha, "tier": "normal", "persona": persona},
    }


def _eval_steps(persona, *, run_step="success", verdict_step="success",
                suppress="skipped", cancel="skipped", job_conclusion="success",
                tier="normal", checkout="Checkout（手动/定时触发按触发时默认分支 HEAD 取代码）"):
    """一条评测腿的步骤（**名字逐字取自真实 run**，改名即夹具失真）。"""
    return {
        "name": f"{persona} 行为回归（独立栈 + 真实 LLM）",
        "conclusion": job_conclusion, "status": "completed",
        "steps": [
            {"name": "Set up job", "conclusion": "success", "status": "completed"},
            {"name": checkout, "conclusion": "success", "status": "completed"},
            {"name": "抑制判定（#3587/#3654/#3709：main 未动则跳过评测，留链接链）",
             "conclusion": "success", "status": "completed"},
            {"name": "Start local stack (docker-compose: PG + Redis + admin-api + ai-agent DEBUG)",
             "conclusion": "skipped" if run_step == "skipped" else "success", "status": "completed"},
            {"name": f"Run {persona} {tier}（真实 LLM）",
             "conclusion": run_step, "status": "completed"},
            {"name": "汇总打印（total/passed/avg_score/completion.ok）",
             "conclusion": run_step, "status": "completed"},
            {"name": "判定（completion_verdict：确定性失败=0 + 关键旅程全过）",
             "conclusion": verdict_step, "status": "completed"},
            {"name": "被抑制记录（#3587/#3654/#3709：本 run 未评测，结论由取代/后续 run 承担）",
             "conclusion": suppress, "status": "completed"},
            {"name": "被取消记录（#3761：run 被取消 ⇒ 未评测，不构成结论，不算失败）",
             "conclusion": cancel, "status": "completed"},
        ],
    }


def _report_steps(*, suppress="skipped", cancel="skipped"):
    """结论 job 的留档步骤（真实 run 里抑制/取消**也在这里留档**，两处都要查）。"""
    return {
        "name": "部署后回归结论（判定汇总 + 失败留痕）",
        "conclusion": "success", "status": "completed",
        "steps": [
            {"name": "结论打印（绿 run 也留档）", "conclusion": "success", "status": "completed"},
            {"name": "被抑制留档（#3587/#3709：本 run 未评测，结论档的链接链，非静默跳过）",
             "conclusion": suppress, "status": "completed"},
            {"name": "被取消留档（#3761：run 被取消 ⇒ 未评测、不建 issue、不判失败）",
             "conclusion": cancel, "status": "completed"},
        ],
    }


def mk_run(*legs, conclusion="success", event="workflow_dispatch", head_sha=SHA, extra_jobs=()):
    return {"conclusion": conclusion, "status": "completed", "headSha": head_sha, "event": event,
            "jobs": [*legs, _report_steps(), *extra_jobs]}


def mk_green_run():
    """一条腿的全绿步骤（⑤ 反例用）。"""
    return mk_run(_eval_steps("mibao"))


def run_cli(tmp_path, *args):
    """跑 CLI（**离线**：只喂本地 summary/步骤 JSON，绝不碰 gh / 网络）。"""
    proc = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, cwd=str(tmp_path))
    return proc


# ── ① 未评测（抑制 / 取消）⇒ 判「未评测」并停 ────────────────────────────────────

class TestNotEvaluated:
    def test_suppressed_run_is_not_a_verdict(self):
        """抑制留档步骤**跑了** ⇒ 未评测（真实 run 34841093824 的形状）。"""
        steps = mk_run(_eval_steps("mibao", run_step="skipped", verdict_step="skipped",
                                   suppress="success"),
                       _eval_steps("xiaobu", run_step="skipped", verdict_step="skipped",
                                   suppress="success"))
        steps["jobs"][-1] = _report_steps(suppress="success")
        res = ec.closeout([], steps, [], None)
        assert res["state"] == "not_evaluated", res
        assert "抑制" in res["state_reason"]
        out = ec.render(res)
        assert "本 run 未评测" in out
        assert "未评测" in out.splitlines()[0] or "未评测" in out[:400]
        # 未评测的 run 没有可分解的桶 ⇒ 后续三段必须停（不得打印"桶分解"结论行）
        assert "deterministic_failures=" not in out
        assert res["exit_code"] == 3

    def test_cancelled_run_is_not_a_verdict(self):
        """取消 ⇒ 未评测。夹具取真实 run 34855662092 的形状：**判定步骤仍是 failure**
        （#3761 之前的行为）⇒ 只靠"判定 skipped"抓不到，必须同时看 job 结论。"""
        steps = mk_run(_eval_steps("mibao", run_step="skipped", verdict_step="failure",
                                   job_conclusion="cancelled"),
                       _eval_steps("xiaobu", run_step="skipped", verdict_step="failure",
                                   job_conclusion="cancelled"),
                       conclusion="cancelled")
        res = ec.closeout([], steps, [], None)
        assert res["state"] == "not_evaluated", res
        assert "取消" in res["state_reason"]
        assert "本 run 未评测" in ec.render(res)
        assert res["exit_code"] == 3

    def test_cancelled_marker_step_alone_is_enough(self):
        """`被取消记录` 步骤跑了（job 结论已被后续事件覆盖成 success）也照样判未评测。"""
        steps = mk_run(_eval_steps("mibao", cancel="success"), conclusion="success")
        res = ec.closeout([], steps, [], None)
        assert res["state"] == "not_evaluated", res
        assert "取消" in res["state_reason"]

    def test_skipped_run_step_without_markers_is_not_evaluated(self):
        """兜底：没有留档步骤（老 run）时，`Run <persona>` 被 skipped 本身即未评测。"""
        steps = mk_run(_eval_steps("mibao", run_step="skipped", verdict_step="skipped"))
        res = ec.closeout([], steps, [], None)
        assert res["state"] == "not_evaluated", res
        assert res["exit_code"] == 3

    def test_missing_steps_is_undecidable_not_green(self):
        """拿不到步骤信息 ⇒ **无法判定**（3），绝不谎报通过（"看不了"≠"没问题"）。"""
        res = ec.closeout([mk_summary()], None, [], None)
        assert res["state"] == "unknown", res
        assert res["exit_code"] == 3
        assert "本 run 未评测" in ec.render(res)


# ── ② 「通过但跨 run 复发」必须落 systemic（不是"未通过列表"）──────────────────────

class TestRecurringReleasedIsNotPass:
    def _fixture(self):
        """OR-016：本轮 **score==1.0**（重试通过、台账放行），但跨 run 复发 ⇒ 未收口。"""
        case = mk_case("OR-016", 1.0, flake_released=True, classification="llm-noise",
                       cross_run_recurrence={"case_id": "OR-016", "fingerprint": "fp",
                                             "prior_runs": ["34916256903", "34923425338"],
                                             "prior_count": 2})
        return mk_summary("mibao", [case, mk_case("OR-010")],
                          buckets={"systemic_recurrence": ["OR-016"]})

    def test_recurring_released_case_is_unclosed(self):
        res = ec.closeout([self._fixture()], mk_green_run(), [], None)
        assert res["exit_code"] == 1, res
        row = {r["case_id"]: r for r in res["case_rows"]}["OR-016"]
        assert row["legs"]["mibao"]["state"] == "未收口", row
        assert "systemic_recurrence" in row["legs"]["mibao"]["buckets"], row

    def test_render_does_not_read_it_as_pass(self):
        out = ec.render(ec.closeout([self._fixture()], mk_green_run(), [], None))
        line = [l for l in out.splitlines() if "OR-016" in l]
        assert line, out
        assert all("已收口" not in l for l in line), line
        # 桶分解段必须点名 systemic_recurrence 与条数（按桶分解，不按"未通过列表"）
        assert "systemic_recurrence=1" in out, out
        # 而"未通过条数"（score<1）在这份夹具里是 0 —— 两者必须分开呈现
        assert "未通过条数=0" in out, out

    def test_score_below_one_alone_still_counts(self):
        """反向：真失败（score<1）也要进未收口 —— 别把判据写成"只认 systemic"。"""
        s = mk_summary("mibao", [mk_case("OR-029", 0.0)],
                       buckets={"deterministic_failures": ["OR-029"]})
        res = ec.closeout([s], mk_green_run(), [], None)
        row = {r["case_id"]: r for r in res["case_rows"]}["OR-029"]
        assert row["legs"]["mibao"]["state"] == "未收口"
        assert res["exit_code"] == 1


# ── ③ 桶分解覆盖每一个阻塞桶键（动态枚举，防漏桶）────────────────────────────────

class TestBucketCoverage:
    def test_blocking_buckets_are_derived_dynamically(self):
        s = mk_summary(buckets={k: [f"C-{i}"] for i, k in enumerate(ALL_BUCKETS)})
        completion = s["completion"]
        got = set(ec.blocking_buckets(completion))
        assert got == set(completion) - set(ec.NON_BLOCKING_VERDICT_KEYS), got

    def test_every_bucket_key_appears_in_output(self):
        """漏桶判据：`set(completion) - NON_BLOCKING` 里**每一个**键都要出现在输出里。"""
        s = mk_summary(buckets={k: [f"C-{i}"] for i, k in enumerate(ALL_BUCKETS)})
        out = ec.render(ec.closeout([s], mk_green_run(), [], None))
        missing = [k for k in ec.blocking_buckets(s["completion"]) if k not in out]
        assert not missing, f"桶分解漏了这些桶：{missing}\n{out}"

    def test_unknown_future_bucket_is_not_dropped(self):
        """#4245 之外再冒出新桶也必须被枚举（写死清单的实现在这里必红）。"""
        s = mk_summary(buckets={"brand_new_bucket_4245": ["X-1"]})
        out = ec.render(ec.closeout([s], mk_green_run(), [], None))
        assert "brand_new_bucket_4245=1" in out, out

    def test_real_completion_verdict_keys_are_all_covered(self):
        """跨模块锁：用**真实** `local_runner.completion_verdict` 的返回值当输入。

        非自证：桶清单来自被测系统的另一个实现（runner），本脚本只负责"一个都不许漏"。
        """
        sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
        try:
            import httpx  # noqa: F401
        except ImportError:                       # pragma: no cover
            stub = types.ModuleType("httpx")

            class _AsyncClient:
                def __init__(self, *a, **k):
                    raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

            stub.AsyncClient = _AsyncClient
            sys.modules.setdefault("httpx", stub)
        import local_runner as lr

        results = [
            {"case_id": "OR-029", "score": 0.0, "classification": "reproducible"},
            {"case_id": "OR-016", "score": 1.0, "classification": "llm-noise", "flake_released": True,
             "cross_run_recurrence": {"prior_count": 2, "prior_runs": ["1", "2"]}},
            {"case_id": "OR-010", "score": 1.0, "restore": ["PRECONDITION_NOT_RESTORED: price"]},
            {"case_id": "PG-013", "score": 0.0, "classification": "reproducible",
             "harness_incompatible": "harness_incompatible(form_fields_mismatch)"},
        ]
        verdict = lr.completion_verdict(results, lr.KEY_JOURNEYS_MIBAO)
        s = mk_summary("mibao", [mk_case("OR-010")])
        s["completion"] = verdict
        out = ec.render(ec.closeout([s], mk_green_run(), [], None))
        blocking = set(verdict) - set(ec.NON_BLOCKING_VERDICT_KEYS)
        assert blocking, verdict                       # 自证夹具真的触发了桶（否则本测试是空的）
        missing = [k for k in blocking if k not in out]
        assert not missing, f"真实 completion_verdict 的桶被漏掉：{missing}\n{out}"


# ── ④ replayed=True 计数 ────────────────────────────────────────────────────────

class TestReplayedCount:
    def _fixture(self):
        c1 = mk_case("OR-011", 0.0, failures=[
            "output_verify[order_no] → order_create(replayed=True orderNo=20260918485580004 customerName=张三)",
            "db_verify[orders] → 命中 OR-010 的单（replayed=True）",
        ])
        c2 = mk_case("OR-014", 0.0, failures=[
            "output_verify[amount] → 168.0 != 198.0（replayed=True 回放了别人的单）",
        ])
        return mk_summary("mibao", [c1, c2, mk_case("OR-010")])

    def test_counts_occurrences_not_cases(self):
        """`35295494688` mibao 腿的真实形态：**3 条用例命中、4 次出现** ⇒ 两者必须分开报。"""
        got = ec.count_replayed(self._fixture())
        assert got["occurrences"] == 3, got
        assert got["case_ids"] == ["OR-011", "OR-014"], got

    def test_occurrence_count_is_strictly_greater_than_case_count(self):
        c = mk_case("OR-011", 0.0, failures=["replayed=True", "replayed=True"])
        got = ec.count_replayed(mk_summary("mibao", [c]))
        assert got["occurrences"] == 2 and got["case_ids"] == ["OR-011"], got

    def test_zero_when_absent_and_no_false_positive(self):
        got = ec.count_replayed(mk_summary("mibao", [mk_case("OR-010")]))
        assert got["occurrences"] == 0 and got["case_ids"] == [], got

    def test_render_reports_total_and_per_leg(self):
        out = ec.render(ec.closeout([self._fixture()], mk_green_run(), [], None))
        assert "replayed=True" in out
        assert "mibao=3" in out, out
        assert "合计=3" in out, out


# ── ⑤ 反向：全绿 ⇒ 退出码 0，且不得打印「未评测」抬头 / 「判红」────────────────────

class TestGreenRunStaysGreen:
    def test_all_green_is_exit_zero_without_false_header(self):
        steps = mk_run(_eval_steps("mibao"), _eval_steps("xiaobu"))
        res = ec.closeout([mk_summary("mibao"), mk_summary("xiaobu")], steps, [], None)
        assert res["state"] == "evaluated", res
        assert res["exit_code"] == 0, res
        out = ec.render(res)
        assert "未评测" not in out, out
        assert "判红" not in out, out
        assert "✅" in out

    def test_empty_buckets_are_still_enumerated(self):
        """全绿时也要把桶逐个列成 0（否则"桶分解"这一段在绿 run 上是空的 = 不可复核）。"""
        out = ec.render(ec.closeout([mk_summary()], mk_green_run(), [], None))
        for k in ALL_BUCKETS:
            assert f"{k}=0" in out, f"绿 run 缺桶行 {k}\n{out}"


# ── CLI（离线三态 + 不碰 gh）────────────────────────────────────────────────────

class TestCli:
    def test_green_summary_exit_zero(self, tmp_path):
        (tmp_path / "eval-summary-mibao.json").write_text(
            json.dumps(mk_summary("mibao"), ensure_ascii=False), encoding="utf-8")
        (tmp_path / "steps.json").write_text(json.dumps(mk_green_run()), encoding="utf-8")
        p = run_cli(tmp_path, "--summary", tmp_path / "eval-summary-mibao.json",
                    "--steps-json", tmp_path / "steps.json")
        assert p.returncode == 0, p.stdout + p.stderr
        assert "未评测" not in p.stdout

    def test_red_summary_exit_one(self, tmp_path):
        s = mk_summary("mibao", [mk_case("OR-029", 0.0)],
                       buckets={"deterministic_failures": ["OR-029"]})
        (tmp_path / "eval-summary-mibao.json").write_text(json.dumps(s, ensure_ascii=False),
                                                          encoding="utf-8")
        (tmp_path / "steps.json").write_text(json.dumps(mk_green_run()), encoding="utf-8")
        p = run_cli(tmp_path, "--summary", tmp_path / "eval-summary-mibao.json",
                    "--steps-json", tmp_path / "steps.json")
        assert p.returncode == 1, p.stdout + p.stderr
        assert "判红" in p.stdout

    def test_suppressed_summary_exit_three(self, tmp_path):
        steps = mk_run(_eval_steps("mibao", run_step="skipped", verdict_step="skipped",
                                   suppress="success"))
        steps["jobs"][-1] = _report_steps(suppress="success")
        (tmp_path / "steps.json").write_text(json.dumps(steps), encoding="utf-8")
        p = run_cli(tmp_path, "--summary", tmp_path / "eval-summary-mibao.json",
                    "--steps-json", tmp_path / "steps.json")
        assert p.returncode == 3, p.stdout + p.stderr
        assert "本 run 未评测" in p.stdout

    def test_directory_summary_is_expanded(self, tmp_path):
        d = tmp_path / "post-deploy-eval-mibao"
        d.mkdir()
        (d / "eval-summary-mibao.json").write_text(json.dumps(mk_summary("mibao")),
                                                   encoding="utf-8")
        (d / "agent-eval-flakes.json").write_text("[]", encoding="utf-8")
        (tmp_path / "steps.json").write_text(json.dumps(mk_green_run()), encoding="utf-8")
        p = run_cli(tmp_path, "--summary", d, "--steps-json", tmp_path / "steps.json")
        assert p.returncode == 0, p.stdout + p.stderr

    def test_nested_artifact_directory_is_expanded(self, tmp_path):
        """`gh run download <id> -D <dest>` 把每个 artifact 解到 `<dest>/<name>/` **子目录**下。

        只 glob 顶层的实现会得到「0 个产物 ⇒ 无法判定」（实测 `--run 35256153429` 的形态）
        —— 运行时入口因此**恒不可用**，而它看起来"只是没跑出结论"。
        """
        nested = tmp_path / "dest" / "post-deploy-eval-mibao"
        nested.mkdir(parents=True)
        (nested / "eval-summary-mibao.json").write_text(json.dumps(mk_summary("mibao")),
                                                        encoding="utf-8")
        (tmp_path / "steps.json").write_text(json.dumps(mk_green_run()), encoding="utf-8")
        p = run_cli(tmp_path, "--summary", tmp_path / "dest",
                    "--steps-json", tmp_path / "steps.json")
        assert p.returncode == 0, p.stdout + p.stderr

    def test_missing_summary_file_is_undecidable(self, tmp_path):
        (tmp_path / "steps.json").write_text(json.dumps(mk_green_run()), encoding="utf-8")
        p = run_cli(tmp_path, "--summary", tmp_path / "nope.json",
                    "--steps-json", tmp_path / "steps.json")
        assert p.returncode == 3, p.stdout + p.stderr

    def test_json_mode_is_machine_readable(self, tmp_path):
        (tmp_path / "eval-summary-mibao.json").write_text(json.dumps(mk_summary("mibao")),
                                                          encoding="utf-8")
        (tmp_path / "steps.json").write_text(json.dumps(mk_green_run()), encoding="utf-8")
        p = run_cli(tmp_path, "--summary", tmp_path / "eval-summary-mibao.json",
                    "--steps-json", tmp_path / "steps.json", "--json")
        assert p.returncode == 0, p.stdout + p.stderr
        data = json.loads(p.stdout)
        assert data["state"] == "evaluated" and data["exit_code"] == 0

    def test_offline_only_no_gh_subprocess(self, tmp_path, monkeypatch):
        """离线入口**不得**调用 gh（单测绝不打 GitHub API）。"""
        calls = []
        monkeypatch.setattr(ec.subprocess, "run",
                            lambda *a, **k: calls.append(a) or pytest.fail("离线入口调用了外部命令"))
        monkeypatch.setattr(ec.subprocess, "check_output",
                            lambda *a, **k: calls.append(a) or pytest.fail("离线入口调用了外部命令"))
        (tmp_path / "eval-summary-mibao.json").write_text(json.dumps(mk_summary("mibao")),
                                                          encoding="utf-8")
        (tmp_path / "steps.json").write_text(json.dumps(mk_green_run()), encoding="utf-8")
        rc = ec.main(["--summary", str(tmp_path / "eval-summary-mibao.json"),
                      "--steps-json", str(tmp_path / "steps.json")])
        assert rc == 0 and calls == []
