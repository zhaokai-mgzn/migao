# case_ids: PP-023
"""PP-023 的前置夹具：评测栈 tenant 1 **必须**有一行 `craft_calc_configs`（issue #8300）。

## 为什么需要这条判据（真跑实测，不是推测）

run `41270943560`（B 端 normal，main `dc18a5542`）PP-023 首跑 trace：

```
R1 craft_calc_config_query(source=default config{})   ← 评测栈没有配置行，引擎默认值取不到
R2 craft_calc_config_update → unknown_config_key      ← 于是 hem_margin 被判成"未知键"，fail-closed
```

评测栈**不起 craft-calc 引擎** ⇒ `CraftCalcConfigService#get` 的「缺行 ⇒ 取引擎默认值」分支
只能回 `config{}`。没有这一行，PP-023 的「查真值 → 改前改后确认 → 点卡才写」永远不可达。

## 本文件钉什么（每条都会红）

| 判据 | 内容 | 怎么红 |
|---|---|---|
| a | `mibao_eval_seed.sql` 有 `INSERT INTO craft_calc_configs`，且带 `tenant_id = 1` 的 `WHERE NOT EXISTS` 幂等守卫 | 删掉整段 ⇒ 红 |
| b | 有把 `hem_margin` 归一回 `0.3` 的 `UPDATE`（上一跑 restore 失败兜底） | 删掉 UPDATE ⇒ 红 |
| c | 有 `DO $$ … $$` 自检块，且 `RAISE EXCEPTION` 在（缺行/值漂移 ⇒ 注入步当场红） | 删掉自检 ⇒ 红 |
| d | Phase 7 段**在**种子文件里、且在文件末尾的「遗留 TODO」注释块**之前**（防止加到注释里空转） | 挪进注释 ⇒ 红 |
"""
from pathlib import Path

SEED = (Path(__file__).resolve().parents[1] / "agent_eval" / "fixtures"
        / "mibao_eval_seed.sql")


def _sql() -> str:
    return SEED.read_text(encoding="utf-8")


def test_seed_inserts_a_craft_calc_config_row_idempotently():
    """a：插入语句在，且是幂等形态（`WHERE NOT EXISTS` 守 tenant 1 的活行）。"""
    sql = _sql()
    assert "INSERT INTO craft_calc_configs" in sql, (
        "种子缺 craft_calc_configs 插入 ⇒ 评测栈 tenant 1 没有算料口径行，PP-023 必红")
    tail = sql.split("INSERT INTO craft_calc_configs", 1)[1][:400]
    assert "WHERE NOT EXISTS" in tail, (
        "插入不是幂等形态（缺 WHERE NOT EXISTS）⇒ 同一栈连跑两次会撞唯一索引")
    assert "tenant_id = 1" in tail, "插入没锚 tenant 1（评测栈租户）"


def test_seed_normalises_hem_margin_to_declared_value():
    """b：`hem_margin` 归一回声明值 0.3（PP-023 的「改前」= 0.3，且给 crash 过的栈兜底）。"""
    sql = _sql()
    block = [ln for ln in sql.splitlines()
             if "SET hem_margin" in ln or "hem_margin = 0.3" in ln]
    assert block, "种子缺 hem_margin = 0.3 的归一行 ⇒ 上一跑 restore 失败后终态不确定"


def test_seed_selfcheck_fails_closed():
    """c：有 `DO $$` 自检 + `RAISE EXCEPTION`（缺行/值漂移 ⇒ 注入步当场红，不许静默过）。"""
    sql = _sql()
    start = sql.find("INSERT INTO craft_calc_configs")
    assert start >= 0
    tail = sql[start:]
    do_block = tail.split("DO $$", 1)
    assert len(do_block) == 2, "craft_calc_configs 段缺 DO $$ 自检块"
    assert "RAISE EXCEPTION" in do_block[1].split("$$;", 1)[0], (
        "自检块没有 RAISE EXCEPTION ⇒ 缺行时只打印 NOTICE、用例静默红，不 fail-closed")
    assert "craft_calc_configs" in do_block[1].split("$$;", 1)[0], (
        "自检块没查 craft_calc_configs（判据跑在别的表上 = 空转）")


def test_phase_seven_block_sits_before_the_legacy_todo_comment():
    """d：Phase 7 段在「遗留 TODO」注释块之前（否则等于把 SQL 写进注释里，永不执行）。"""
    sql = _sql()
    insert_at = sql.find("INSERT INTO craft_calc_configs")
    todo_at = sql.find("#3496 / #3519")   # ASCII 锚：遗留 TODO 注释块的工单号（#6802 同族守卫）
    assert insert_at >= 0, "找不到 craft_calc_configs 段"
    assert todo_at >= 0, "找不到「遗留 TODO」注释块（本判据的锚点漂了，需要更新判据）"
    assert insert_at < todo_at, (
        "craft_calc_configs 段跑到「遗留 TODO」注释之后 ⇒ 可能被写进注释，实际不执行")
