#!/usr/bin/env python3
"""本轮（2026-10-04）三线产物的**协议合规机械自检**（只读、零 LLM）。

⚠️ 本判据自身必须**先过红证**：`--selftest` 会用一份**故意违规**的样本跑，
   检测不到违规就判红（退出码 1）。首版曾产出 19 条**假红**（否定语境的关键字命中 /
   `red_proof` 字段名 / `falseRed` 命名 / `run.log` 名 / 脚本路径引用），已逐条修。

判据：
  C1 声明被测构建点，且**区分**「部署台账声称」与「行为实测」（本轮实测 = de614623d）；
  C2 **不得自我验收**：禁用措辞**在否定语境里不算命中**（如「不自我验收声明：不下『验收通过』」）；
  C3 counts 四态齐全（`false_red`/`falseRed` 均可）、skip 不得折算成 pass；
  C4 每条 finding 必须带**证据引用**（`out/**` 或仓库路径）与**红证/负对照**（字段 `red_proof`/`redProof` 或关键字）；
  C5 有「未覆盖」章节（无 skip 也要显式写）；
  C6 有运行日志（`out/run.log` 或 `out/run-all.log`）；
  C7 README §3.1 四态表里引用的数字，必须与**各线产物**逐年对上（③ = 三段 replay 求和）；
     数字漂移是复核反复抓到的形态（手抄读数 ⇒ 报告与 JSON 悄悄分家）⇒ 把它变成机械判据。
     红证：`--selftest` 第 3 段故意把 README 的数字写成 999 ⇒ C7 必须红；改回真值 ⇒ 必须绿。

⚠️ **已知盲区（GLM 复核 O5 点出，如实登记、不冒充已覆盖）**：本检查器**不校验**
① 正文结论与 `counts` 的一致性（如报告表格与 JSON 计数不符）—— **2026-10-04 起 C7 覆盖其中「§3.1 四态表」这一块**，
   其余正文（各线 REPORT 的叙述数字）仍不在射程；
② `evidence` 指向文件的**内容**与结论是否一致（只查文件存在）；
③ 同一现象在文中两处给出不同数字；
④ 判据是否恒绿（这要靠各线自己的红证 + 复核裁判）。
四条的现行承接面 = 三线 REPORT 的红证章 + GLM 交叉复核（见 `acceptance/2026-10-04/review/`）。

C8 = 入库前**不得残留明文凭据形态**（JWT/幂等键/Bearer），口径复用 `env/redact-secrets.py`；
     红证：`--selftest` 塞一枚假幂等键 ⇒ C8 必红；撤掉 ⇒ 必不红。
退出码：0 全过 / 1 有违规 / 3 无法判定。用法：python3 verify-evidence.py [--selftest]
"""
from __future__ import annotations
import json, re, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LINES = ["worker-miniapp-sweep", "aftersales-refund-sweep", "race-sweep"]
BANNED = ["验收通过", "交付完成", "已达标", "评测 OK", "评测通过"]
NEG = ("不", "未", "禁", "勿", "无", "非", "拒绝", "不得", "永不", "没有", "尚未")
RED_KEYS = ("red_proof", "redProof", "红证", "red_evidence", "negative_control",
            "willRed", "will_red", "redProofRef", "negativeControl", "falseGreenExposure",
            # 线③ 的字段族（GLM 复核发现自检器首版未认 ⇒ 报过 4 条假红）
            "would_red", "wouldRed", "discriminating_control", "discriminatingControl")
RED_HINTS = ["红证", "负对照", "故意写坏", "判别性", "会红", "反例", "空断言"]
PATH_RE = re.compile(r"[\w./\-]+\.(json|png|log|md|java|mjs|js|sh|ts|tsx|py|yml|yaml)")


def self_accept_hits(text: str):
    """行级否定豁免：整行含否定标记（不/未/禁/勿/…）⇒ 该行是在**声明不下结论**，不算命中。
    首版按「命中词前 16 字符」判上下文 ⇒ 引号列表情形漏判（『不下「A / B / C」』里的 B、C 前 16 字符无否定词）。"""
    for i, line in enumerate(text.splitlines(), 1):
        if any(n in line for n in NEG):
            continue
        for w in BANNED:
            if w in line:
                yield i, w, line.strip()[:110]


def finding_flags(f: dict, root: Path | None = None):
    """返回 (有证据引用, 红证/负对照, 引用文件是否真实存在)。
    C4b（GLM 复核 O5 新增）：证据里出现的 out/<file>.json 必须在磁盘上存在 —— 只判"写了路径"是空断言。"""
    blob = json.dumps(f, ensure_ascii=False)
    ev = str(f.get("evidence") or "") + " " + str(f.get("evidence_ref") or "")
    has_ev = bool(PATH_RE.search(ev)) or bool(PATH_RE.search(blob))
    has_red = any(k in f and f[k] for k in RED_KEYS) or any(h in blob for h in RED_HINTS)
    missing = []
    if root is not None:
        for m in set(re.findall(r"out/[\w./\-]+\.(?:json|log|png)", blob + " " + ev)):
            if not any(cand.exists() for cand in (root / m, root / "out" / Path(m).name)):
                missing.append(m)
    return has_ev, has_red, missing


def _counts_of(path: Path):
    if not path.exists():
        return None
    try:
        c = (json.loads(path.read_text(encoding="utf-8")).get("counts") or {})
    except Exception:
        return None
    return {k: c.get(k) for k in ("pass", "fail", "skip")}


def _race_counts(root: Path):
    """线③ 的 after 读数没有单一 SUMMARY，按三段 replay 求和（probe-write/idem/cross）。"""
    tot = {"pass": 0, "fail": 0, "skip": 0}
    seen = False
    for p in sorted((root / "replay-postdeploy" / "race").glob("probe-*-summary.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        c = raw.get("counts") or raw      # 线③ 的 per-suite summary 把计数放**顶层**，线①② 放在 counts 下
        seen = True
        for k in tot:
            tot[k] += (c.get(k) or 0)
    return tot if seen else None


def check_readme_counts(root: Path):
    """C7：README §3.1 引用的数字必须与产物一致。
    只认**含 `pass ` 的那一行**（射程表也有 `| ① …` 开头的行，按首个匹配会误判 —— 那是假红）。"""
    viol, unjudgeable = [], []
    rp = root / "README.md"
    if not rp.exists():
        return viol, unjudgeable          # 无 README（自检样本）⇒ 不适用，不报 unjudgeable
    text = rp.read_text(encoding="utf-8", errors="replace")
    src = {
        "①": ("replay-postdeploy/worker/SUMMARY.json",
              lambda: _counts_of(root / "replay-postdeploy" / "worker" / "SUMMARY.json")),
        "②": ("replay-postdeploy/aftersales/SUMMARY.json",
              lambda: _counts_of(root / "replay-postdeploy" / "aftersales" / "SUMMARY.json")),
        "③": ("replay-postdeploy/race/probe-*-summary.json（三段求和）", lambda: _race_counts(root)),
    }
    for marker, (label, get) in src.items():
        rows = [ln for ln in text.splitlines()
                if re.match(rf"^\|\s*{marker}", ln) and "pass " in ln]
        if not rows:
            viol.append(f"README: C7 找不到「{marker}」的四态表行（含 pass 的那一行）")
            continue
        row = rows[0]
        c = get()
        if not c:
            unjudgeable.append(f"README: C7 缺「{marker}」的数据源 {label} ⇒ 无法对账")
            continue
        want = f"pass {c['pass']} / fail {c['fail']} / skip {c['skip']}"
        if want not in row:
            viol.append(f"README: C7 「{marker}」行数字与产物不符 ⇒ 期望含「{want}」；实际行：{row.strip()[:110]}")
    return viol, unjudgeable


def check(lines, root: Path):
    viol, unjudgeable = [], []
    for line in lines:
        d = root / line
        rep = d / "REPORT.md"
        if not rep.exists():
            unjudgeable.append(f"{line}: 缺 REPORT.md"); continue
        text = rep.read_text(encoding="utf-8", errors="replace")

        # C1 构建点（区分台账声称 vs 行为实测）
        if not re.search(r"de614623d|行为实测", text, re.I):
            viol.append(f"{line}: C1 未声明**行为实测**构建点（部署台账声称 ≠ 实测，见 #6294）")
        # C2 自我验收（否定语境豁免）
        for ln, w, snippet in self_accept_hits(text):
            viol.append(f"{line}: C2 REPORT.md:{ln} 非否定语境出现「{w}」⇒ {snippet}")
        # C5 未覆盖章节
        if not re.search(r"未覆盖", text):
            viol.append(f"{line}: C5 无「未覆盖」章节（无 skip 也要显式写「无」）")
        # C6 运行日志
        if not ((d / "out" / "run.log").exists() or (d / "out" / "run-all.log").exists()):
            unjudgeable.append(f"{line}: 缺 out/run.log 与 out/run-all.log（空跑形态 ⇒ 不构成结论）")

        summ = d / "out" / "SUMMARY.json"
        if not summ.exists():
            unjudgeable.append(f"{line}: 缺 out/SUMMARY.json"); continue
        try:
            s = json.loads(summ.read_text(encoding="utf-8"))
        except Exception as exc:
            unjudgeable.append(f"{line}: SUMMARY.json 解析失败: {exc}"); continue
        c = s.get("counts") or {}
        for k in ("pass", "fail", "skip"):
            if not isinstance(c.get(k), int) or c.get(k) < 0:
                viol.append(f"{line}: C3 counts.{k} 缺失或非法（{c.get(k)!r}）")
        if not isinstance(c.get("false_red", c.get("falseRed")), int):
            viol.append(f"{line}: C3 counts 缺 false_red/falseRed")
        if isinstance(c.get("pass"), int) and "skip" not in c:
            viol.append(f"{line}: C3 有 pass 却无 skip 键 ⇒ 疑似把 skip 折算成 pass")
        for i, f in enumerate(s.get("findings") or []):
            has_ev, has_red, missing = finding_flags(f, d)
            tag = f.get("id") or f.get("title", "?")
            if not has_ev:
                viol.append(f"{line}: C4 findings[{i}]（{tag}）无证据路径引用")
            if not has_red:
                viol.append(f"{line}: C4 findings[{i}]（{tag}）无红证/负对照（字段或关键字）")
            for m in missing:
                viol.append(f"{line}: C4b findings[{i}]（{tag}）证据文件不存在：{m}")

    # C5'（盲区登记，不作判红依据）：本检查器**测不到**的形态见文件头 docstring
    # C7（README 数字 ↔ 产物对账）
    rv, ru = check_readme_counts(root)
    viol += rv
    unjudgeable += ru
    # C8（入库前：不得有明文凭据形态）
    viol += check_no_plaintext_secrets(root)
    return viol, unjudgeable


def _load_redactor():
    """口径唯一来源 = env/redact-secrets.py（它同时是就地脱敏器）⇒ 两处不会漂移。"""
    import importlib.util
    p = Path(__file__).resolve().parent / "env" / "redact-secrets.py"
    spec = importlib.util.spec_from_file_location("redact_secrets", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check_no_plaintext_secrets(root: Path) -> list[str]:
    """C8：验收产物里**不得残留明文凭据形态**（JWT / 幂等键 / Bearer 长串）。

    为什么放在这里而不是只靠 CI：gitleaks 是**事后**阻塞（且只扫提交区间），
    实测栽过两轮 —— ① 只按结构化字段脱敏 ⇒ 自由文本副本漏网；② 只清**当时已知**的值 ⇒ 下一次探针又新造一批。
    ⇒ 把「入库前自检」做成常驻判据：提交前跑一次就知道，而不是等 CI 红。
    """
    try:
        rs = _load_redactor()
    except Exception as exc:                     # fail-closed：载不进脱敏器 ⇒ 无法判定，不许当绿
        return [f"C8 无法判定：脱敏器不可载入（{exc}）"]
    out: list[str] = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in rs.EXTS or f.name in rs.SKIP_NAMES:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        _, hits = rs.redact_text(text)
        if hits:
            out.append(f"C8 明文凭据形态残留 {hits} 处：{f.relative_to(root.parent)}"
                       f"（跑 `python3 acceptance/2026-10-04/env/redact-secrets.py` 就地脱敏）")
    return out


def selftest() -> int:
    """红证：故意违规样本必须被判红；合规范本必须判绿。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad = root / "worker-miniapp-sweep"; (bad / "out").mkdir(parents=True)
        (bad / "REPORT.md").write_text("本包验收通过。\n未覆盖：无\n", encoding="utf-8")
        (bad / "out" / "SUMMARY.json").write_text(json.dumps(
            {"counts": {"pass": 1, "fail": 0}, "findings": [{"id": "X", "title": "无证据无红证"}]}), encoding="utf-8")
        v, _ = check(["worker-miniapp-sweep"], root)
        expect = ["C1", "C2", "C3", "C4"]
        missing = [e for e in expect if not any(e in x for x in v)]
        if missing:
            print(f"❌ 自检红证失败：故意违规样本未被判红（漏判 {missing}）"); return 1
        # C8 红证：塞一枚"形似密钥"的幂等键 ⇒ C8 必须红；撤掉 ⇒ 必须不再有 C8 项
        leaky = bad / "out" / "leaky.json"
        leaky.write_text('{"key": "race-sweep-key-20261004000000-abcdef"}', encoding="utf-8")
        v2, _ = check(["worker-miniapp-sweep"], root)
        if not any("C8" in x for x in v2):
            print("❌ 自检红证失败：明文凭据形态未被 C8 判红（空断言）"); return 1
        leaky.unlink()
        v3, _ = check(["worker-miniapp-sweep"], root)
        if any("C8" in x for x in v3):
            print("❌ 自检红证失败：撤掉明文后 C8 仍红（误报）"); return 1
        good = root / "aftersales-refund-sweep"; (good / "out").mkdir(parents=True)
        (good / "REPORT.md").write_text(
            "行为实测 = de614623d；不自我验收：不下「验收通过」类结论。\n未覆盖：无\n", encoding="utf-8")
        (good / "out" / "run.log").write_text("ok\n", encoding="utf-8")
        (good / "out" / "x.json").write_text('{"ok":true}', encoding="utf-8")   # C4b：证据文件必须真实存在
        (good / "out" / "SUMMARY.json").write_text(json.dumps({
            "counts": {"pass": 1, "fail": 0, "skip": 0, "falseRed": 0},
            "findings": [{"id": "F1", "evidence": "out/x.json", "red_proof": "注入式红证：改坏后必红"}]}), encoding="utf-8")
        v2, u2 = check(["aftersales-refund-sweep"], root)
        if v2 or u2:
            print(f"❌ 自检假红：合规范本被判违规/无法判定 {v2} {u2}"); return 1

        # 第 3 段：C7 红证（README 数字与产物必须对上；这里故意写 999）
        (root / "README.md").write_text(
            "| ① 工人端 | API | pass 999 / fail 0 / skip 0 | 数字是错的 |\n"
            "| ② 售后 | API | pass 2 / fail 0 / skip 0 |\n"
            "| ③ 并发 | API | pass 3 / fail 0 / skip 0 |\n", encoding="utf-8")
        for sub, cnt in (("worker", 1), ("aftersales", 2)):
            d = root / "replay-postdeploy" / sub; d.mkdir(parents=True, exist_ok=True)
            (d / "SUMMARY.json").write_text(json.dumps(
                {"counts": {"pass": cnt, "fail": 0, "skip": 0}}), encoding="utf-8")
        d = root / "replay-postdeploy" / "race"; d.mkdir(parents=True, exist_ok=True)
        (d / "probe-write-summary.json").write_text(json.dumps(
            {"counts": {"pass": 3, "fail": 0, "skip": 0}}), encoding="utf-8")
        v3, _ = check_readme_counts(root)
        if not any("C7" in x and "①" in x for x in v3):
            print(f"❌ 自检红证失败：C7 未抓到 README 与产物不符（999 ≠ 1）⇒ {v3}"); return 1
        (root / "README.md").write_text(
            "| ① 工人端 | API | pass 1 / fail 0 / skip 0 |\n"
            "| ② 售后 | API | pass 2 / fail 0 / skip 0 |\n"
            "| ③ 并发 | API | pass 3 / fail 0 / skip 0 |\n", encoding="utf-8")
        v4, u4 = check_readme_counts(root)
        if v4 or u4:
            print(f"❌ 自检假红：C7 在数字一致时仍报 {v4} {u4}"); return 1
        print("✅ 自检红证通过：违规样本判红（C1/C2/C3/C4）· 合规范本判绿（否定语境未误伤）"
              "· C7 抓到数字漂移（999≠1）且改回真值即绿")
        return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    viol, unjudgeable = check(LINES, ROOT)
    print("== 协议合规自检（2026-10-04 三线） ==")
    for ln in LINES: print(f"  · {ln}")
    if viol:
        print(f"\n❌ 违规 {len(viol)} 条：")
        for v in viol: print(f"   - {v}")
    if unjudgeable:
        print(f"\n⚠️ 无法判定 {len(unjudgeable)} 条：")
        for u in unjudgeable: print(f"   - {u}")
    if not viol and not unjudgeable:
        print("\n✅ 八条机械判据全过（**不构成验收结论**）")
    sys.exit(1 if viol else (3 if unjudgeable else 0))
