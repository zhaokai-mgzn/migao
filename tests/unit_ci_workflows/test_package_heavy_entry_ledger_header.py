# case_ids: MC-012
r"""**台账首行的 schema 头** + 「缺头自愈」的判据（issue #7655）。

## 病灶（2026-10-24 现取读数）

`scripts/package-heavy-entry-ledger.sh` 写台账时，**首行**本应是 schema 头
（`_kind` = `migao.package-heavy-entry-ledger`）；而仓内
`tests/unit_ci_workflows/package_heavy_entry_ledger.jsonl` 的**首行是一条判定记录**。
`_ensure_header` 用 `head -1 | grep -q` 认头 ⇒ 不认 ⇒ `_die_undecidable`（exit 3）
⇒ **自 2026-10-17 起每一次角色判定（拒绝 / 放行）都记不上**（文件停在 9 行，
末条 `2026-10-17T10:32:38Z`），而调用方（`verify-all.sh`）并不因此中断 gate
⇒ 读数**静默消失**：事后「没记上」与「没发生」长得一模一样。

## 判据（三条，每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | **仓内台账首行必须是 schema 头**；其余每行都是带 `id/ts/role/decision` 四键的记录；2026-10-17 那 9 条历史记录**一行不少、顺序不变** | 首行是记录 ⇒ 红（这就是本单的自然红证）；有人「重排 / 删除」历史 ⇒ 红 |
| 2 | 仓内首行与**脚本写到空文件时的首行逐字节相同**（单一出处） | 改了脚本的 printf 却没同步数据（或反之）⇒ 两份口径漂开 ⇒ 红 |
| 3 | **缺头自愈**：喂一份「缺头但每行都是合法记录」的台账 ⇒ 追加成功、首行补成 schema 头、历史**一行不少且顺序不变**；再追加一次 ⇒ **只有一个头**（幂等） | 旧实现直接 exit 3 ⇒ 红；补头时重排 / 丢行 ⇒ 红；每次都补一个头 ⇒ 红 |
| 4 | **负控：不许把「不认识的账」当自己的账写** —— 首行不是头且**某行不是合法 JSON**（或合法 JSON 但缺键）⇒ 仍 **exit 3** + 原文案，且文件**一字未动** | 判据退化成「文件存在就补头」⇒ 往别人的账上写头 ⇒ 红 |

## 边界（照实登记，§19.1）

- 判据只认**逐行结构**（每行可解析 JSON 且四键齐全），**不看文件名 / 路径** —— 自愈的正当性来自
  「这份账的每一行都长得像本台账的记录」，不是「它放在这个路径下」；
- 本判据**不判**「并发自愈」这一形态：补头是「读→写临时文件→rename」，两个进程同时自愈的窄窗口里，
  一侧的追加可能落空（重启条件 = 观测到同一台账的并发自愈；届时再加锁，别提前造）；
- 判据**不碰**真锁 / 真台账以外的东西：① / ② 只**读**仓内台账；③ / ④ 全部落在 `tmp_path`
  （`hs.clean_env` 把 `MIGAO_PACKAGE_HEAVY_LEDGER` 收口到 `tmp_path`，结构上写不到真台账）。
"""

from __future__ import annotations

import json
from pathlib import Path

from unit_ci_workflows import heavy_entry_sandbox as hs

LEDGER_SH = str(hs.LEDGER_SH)
REPO_LEDGER = hs.DEFAULT_REAL_LEDGER
KIND = "migao.package-heavy-entry-ledger"
RECORD_KEYS = ("id", "ts", "role", "decision")

#: 2026-10-17 那 9 条历史记录（`id`，**文件顺序**）。台账是只追加的 ⇒ 既有行不会被合法地改写，
#: 新记录只会往后加 ⇒ 用「前缀相等」钉住历史（不许少一行、不许换序）。
HISTORICAL_IDS = [
    "1792230781.81018.30750",
    "1792230810.86120.18884",
    "1792230898.93665.29581",
    "1792228989.87005.19637",
    "1792229001.87113.8618",
    "1792229636.87620.3148",
    "1792230647.71392.20400",
    "1792231662.53616.24332",
    "1792233158.59439.23448",
]
#: 最后一条历史记录的时间戳（读数锚：整个 2026-10-17 之后**没有任何**判定被记上）
LAST_HISTORICAL_TS = "2026-10-17T10:32:38Z"


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _is_header(line: str) -> bool:
    """首行判定：**能解析的 JSON 对象**且 `_kind` 命中（不是「含某个子串」）。"""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return False
    return isinstance(obj, dict) and obj.get("_kind") == KIND


def _records(lines: list[str]) -> list[dict]:
    return [json.loads(ln) for ln in lines if ln.strip()]


def _env(ledger: Path, ledger_id: str | None = None) -> dict:
    extra = {"MIGAO_PACKAGE_HEAVY_LEDGER": str(ledger)}
    if ledger_id:
        extra["MIGAO_ROLE_LEDGER_ID"] = ledger_id
    return hs.clean_env(ledger.parent, **extra)


def _append(ledger: Path, ledger_id: str, *, role="package", decision="override", why="判据"):
    return hs.run(["bash", LEDGER_SH, "append", role, decision, why], env=_env(ledger, ledger_id))


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 1~2：仓内台账（首行是头 + 历史一行不少 + 头与脚本单一出处）
# ══════════════════════════════════════════════════════════════════════════════════════

class TestRepoLedgerHasItsSchemaHeader:
    def test_repo_ledger_first_line_is_the_schema_header(self):
        """判据 1：首行 = schema 头；其余每行 = 四键记录；9 条历史**一行不少、顺序不变**。"""
        lines = _lines(REPO_LEDGER)
        assert lines, f"台账是空的：{REPO_LEDGER}"
        assert _is_header(lines[0]), (
            "台账首行不是 schema 头 ⇒ `_ensure_header` 会 exit 3 ⇒ 角色判定读数**静默消失**"
            f"（#7655）。实得首行：{lines[0][:160]!r}"
        )
        for no, line in enumerate(lines[1:], start=2):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"台账第 {no} 行不是合法 JSON：{line[:160]!r}") from exc
            missing = [k for k in RECORD_KEYS if k not in rec]
            assert not missing, f"台账第 {no} 行缺键 {missing}：{line[:160]!r}"
        recs = _records(lines[1:])
        assert [r["id"] for r in recs][:len(HISTORICAL_IDS)] == HISTORICAL_IDS, (
            "2026-10-17 那 9 条历史记录被改动 / 重排 / 删除（台账只追加，历史不许动）"
        )
        assert recs[len(HISTORICAL_IDS) - 1]["ts"] == LAST_HISTORICAL_TS, (
            f"历史末条的时间戳变了（应为 {LAST_HISTORICAL_TS}）：{recs[len(HISTORICAL_IDS) - 1]}"
        )

    def test_repo_header_is_the_same_source_as_what_the_script_writes(self, tmp_path):
        """判据 2：仓内首行必须与脚本写到**空文件**的首行**逐字节相同**（不许另写一份）。"""
        fresh = tmp_path / "fresh.jsonl"
        got = _append(fresh, "probe.7655.header")
        assert got.returncode == 0, f"空台账上追加就失败了：\n{got.stdout}\n{got.stderr}"
        assert _lines(fresh)[0] == _lines(REPO_LEDGER)[0], (
            "仓内首行与脚本 `printf` 的那一行不同源 —— 两份口径会各自漂：\n"
            f"脚本：{_lines(fresh)[0]}\n仓内：{_lines(REPO_LEDGER)[0]}"
        )


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 3：缺头但每行合法 ⇒ 自愈（补头 + 不丢历史 + 幂等）
# ══════════════════════════════════════════════════════════════════════════════════════

class TestHeaderlessLedgerIsSelfHealed:
    def test_valid_records_are_kept_and_the_header_is_prepended(self, tmp_path):
        """判据 3：首行缺头但每行都是合法记录 ⇒ 追加成功、补头、历史一行不少且顺序不变。"""
        body = [ln for ln in _lines(REPO_LEDGER) if not _is_header(ln)]
        assert len(body) >= len(HISTORICAL_IDS), f"仓内记录不足 9 条：{len(body)}"
        ledger = tmp_path / "headerless.jsonl"
        ledger.write_text("\n".join(body) + "\n", encoding="utf-8")
        before = _records(body)
        refused = sum(1 for r in before if r["decision"] == "refused")
        override = sum(1 for r in before if r["decision"] == "override")

        got = _append(ledger, "probe.7655.heal")
        assert got.returncode == 0, (
            "缺头但每行都是合法记录 ⇒ 应自愈后追加成功（旧实现 exit 3 = 读数静默消失）：\n"
            f"{got.stdout}\n{got.stderr}"
        )
        lines = _lines(ledger)
        assert _is_header(lines[0]), f"自愈后首行仍不是 schema 头：{lines[0][:160]!r}"
        assert lines[1:1 + len(body)] == body, "历史记录必须一行不少、顺序不变（自愈只补首行）"
        assert len(lines) == len(body) + 2, f"自愈后行数 {len(lines)} ≠ 历史 {len(body)} + 头 + 新记录"
        new = json.loads(lines[-1])
        assert new["id"] == "probe.7655.heal" and new["decision"] == "override", new

        counted = hs.run(["bash", LEDGER_SH, "count"], env=_env(ledger))
        assert counted.returncode == 0, counted.stderr
        assert f"refused={refused}" in counted.stdout, f"补头后拒绝计数变了：{counted.stdout!r}"
        assert f"override={override + 1}" in counted.stdout, f"补头后放行计数变了：{counted.stdout!r}"

    def test_second_append_does_not_add_a_second_header(self, tmp_path):
        """判据 3（幂等）：自愈后**再追加一次** ⇒ 只有**一个**头，两条记录都在、顺序不变。"""
        body = [ln for ln in _lines(REPO_LEDGER) if not _is_header(ln)]
        ledger = tmp_path / "twice.jsonl"
        ledger.write_text("\n".join(body) + "\n", encoding="utf-8")
        first = _append(ledger, "probe.7655.a")
        second = _append(ledger, "probe.7655.b")
        assert first.returncode == 0 and second.returncode == 0, (
            f"{first.stdout}{first.stderr}\n{second.stdout}{second.stderr}"
        )
        lines = _lines(ledger)
        assert sum(1 for ln in lines if _is_header(ln)) == 1, f"补了不止一个头：{len(lines)} 行"
        assert lines[1:1 + len(body)] == body, "第二次追加动了历史记录"
        tail = [json.loads(ln)["id"] for ln in lines[1 + len(body):]]
        assert tail == ["probe.7655.a", "probe.7655.b"], f"新记录顺序不对：{tail}"


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 4：负控 —— 「不认识的账」仍然 exit 3，且**一字不动**
# ══════════════════════════════════════════════════════════════════════════════════════

class TestUnrecognizedLedgerStillRefuses:
    def _assert_refused_and_untouched(self, ledger: Path, before: str) -> None:
        got = _append(ledger, "probe.7655.negative")
        assert got.returncode == 3, (
            f"不合格的账必须 exit 3（不得当 0 读），实得 {got.returncode}：\n{got.stdout}\n{got.stderr}"
        )
        assert "拒绝往一份不认识的账上追加" in got.stderr, f"拒绝文案变了：{got.stderr!r}"
        assert ledger.read_text(encoding="utf-8") == before, "不合格的账被写了 —— 不许补头、不许追加"

    def test_unparseable_line_keeps_exit_three(self, tmp_path):
        """判据 4：首行不是头且**某行不是合法 JSON** ⇒ exit 3 + 文件一字未动。"""
        ledger = tmp_path / "not-json.jsonl"
        before = json.dumps({"id": "x.1", "ts": "2026-10-24T00:00:00Z", "role": "package",
                             "decision": "refused"}, ensure_ascii=False) + "\n这不是 JSON\n"
        ledger.write_text(before, encoding="utf-8")
        self._assert_refused_and_untouched(ledger, before)

    def test_record_missing_a_required_key_keeps_exit_three(self, tmp_path):
        """判据 4（另一半）：合法 JSON 但**缺 `role`** ⇒ 同样 exit 3（结构不对就不是本台账）。"""
        ledger = tmp_path / "no-role.jsonl"
        before = json.dumps({"id": "x.2", "ts": "2026-10-24T00:00:00Z",
                             "decision": "refused"}, ensure_ascii=False) + "\n"
        ledger.write_text(before, encoding="utf-8")
        self._assert_refused_and_untouched(ledger, before)
