# case_ids: PR-010, PR-011, OR-014
"""评测 harness 的**写操作**清点表（issue #3807 的「同类扫描」交付物）。

## 为什么要把它做成可执行的登记表，而不是一段报告

`#3807` 的病灶不是"某一行写错了字段名"，而是**一整类**：

> 一次"看起来把共享状态复位了"的写操作，其实**静默空转**（或静默失败），
> 而 harness 的文案/结论照旧宣称它成功了 ⇒ 后续用例读到被污染的状态，
> 归因却指向 agent 行为（"agent 没做"）。

`restore_product` 发 `{"price": …}`（DTO 只认 `basePrice`）正是这一类的一个实例。
只修一个实例，这个类还会长回来。故本文件把 harness 里**全部**写调用清点成登记表：

1. 扫描 `tests/agent_eval/local_runner.py` 里所有 `await <client>.<patch|put|post|delete>(…)`；
2. 每条必须有**处置说明**（已校验响应 / 已回读 / 未校验 + 理由 + issue 号）；
3. 新增或删除任一写调用 ⇒ **本文件先红**（强制作者回答"这条写操作怎么算成功"）。

## 现存清点（2026-09-15 复核 e2a094a1）

| 位置 | 写操作 | 是否可见 | 判定 |
|---|---|---|---|
| `restore_product` | PATCH 商品价 | 状态码 + **回读值** | ✅ #3807 已修（本 PR 红证：翻转 `PRODUCT_PRICE_FIELD` ⇒ 红） |
| `_end_session` | PUT 关闭会话 | `status_code >= 400` 打印 | ✅ 失败不改用例结论（只影响记忆 flush），可接受 |
| `_eval_remove_users` | DELETE 员工 | `status_code < 300` 才计数 | ✅ |
| `_run_pre_clean_action` ×4 | PUT 下架 / DELETE 商品（`product_remove`、`product_dedupe`） | **未取响应** | ⚠️ **未校验**（见下"为什么本轮不顺手改"） |
| `_run_pre_clean_action` | PUT 员工回 active（`employee_reactivate`） | **未取响应** | ⚠️ **未校验**（同上） |
| `_run_pre_clean_action` | DELETE 客户标签（`customer_tag_remove`） | **未取响应** | ⚠️ **未校验**（同上） |
| `_run_pre_clean_action` | DELETE 用户长期记忆 | `status_code >= 300` 或 `success is False` | ✅ |
| `login` / `get_or_create_session` ×2 | POST 登录 / 建会话 | 响应体**必须**被解析（拿不到 token/session_id 即抛错） | ✅ 隐式校验（缺值不可能继续） |

### 为什么本轮的 ⚠️ 三条只登记、不顺手改（诚实标注，不粉饰）

它们**确实**属于同一类（写失败不可见 ⇒ 归因错人），但改法不是"加一行 readback"那么中性：

- `product_remove` / `customer_tag_remove` 是**清理型**（`_PRECLEAN_CLEANUP_TYPES`）：
  回读失败若走 `_PRECONDITION_NOT_APPLIED` 会被 `_classify_preclean_message` 降级成
  `_PRECLEAN_NOOP: … 的目标不存在（…）` —— 文案与事实**相反**（"目标不存在" vs
  "删了没删掉"）。要正确表达得新增一族消息（`_PRECLEAN_NOOP` 之外）。
- `product_dedupe` / `employee_reactivate` 是**准备型**：回读失败会走
  `_PRECONDITION_NOT_APPLIED` ⇒ **阻塞**。这与 #3781 的设计一致（准备型未应用必须进结论），
  但它会**新增阻塞红**，且"重复商品删不掉"在部分用例上并不影响 agent 成功
  ⇒ 属"改门禁语义"的独立改动，需要自己的红证与影响面评估，不该夹在本单里顺手做。

⇒ 本 PR 的处理：**登记 + 让"类"不再静默生长**（本守卫）+ 在 PR body 里如实列出，
留给后续独立单。**不**把未验证的改动说成已验证。
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"

# 写调用：`await c.patch(` / `await client.delete(` / `await c.put(` / `await c.post(`
WRITE_CALL = re.compile(r"await\s+\w+\.(patch|put|post|delete)\(")
DEF_LINE = re.compile(r"^(?:async )?def (\w+)")

# 处置登记表：key = (所在函数, HTTP 方法, 该函数内第 n 次该方法的调用)
# value = 处置说明。**未校验**的条目必须写明理由 + issue 号（下方 `_UNVERIFIED_OK` 约束）。
DISPOSITIONS = {
    ("restore_product", "patch", 1):
        "**已校验**：status_code >= 300 记账 + 回读值比对（#3807；"
        "`test_eval_product_restore.py` 用翻转 PRODUCT_PRICE_FIELD 做红证）",
    ("_end_session", "put", 1):
        "已校验：status_code >= 400 打印告警；失败只影响记忆 flush、不改用例结论",
    ("_eval_remove_users", "delete", 1):
        "已校验：status_code < 300 才计入 removed",
    ("_run_pre_clean_action", "put", 1):
        "未校验（product_remove 下架商品）：同类扫描登记，见本文件 docstring「为什么本轮不顺手改」"
        "（issue #3807 的类，独立单处理）",
    ("_run_pre_clean_action", "delete", 1):
        "未校验（product_remove 删除商品）：同上，独立单处理（issue #3807）",
    ("_run_pre_clean_action", "put", 2):
        "未校验（product_dedupe 下架重复商品）：准备型 ⇒ 加回读会新增阻塞红，需独立红证"
        "（issue #3807）",
    ("_run_pre_clean_action", "delete", 2):
        "未校验（product_dedupe 删除重复商品）：同上（issue #3807）",
    ("_run_pre_clean_action", "put", 3):
        "未校验（employee_reactivate 回 active）：已有前置查询断言目标存在；写结果未回读"
        "（issue #3807）",
    ("_run_pre_clean_action", "delete", 3):
        "已校验（user_memories_clear）：status_code >= 300 或 body.success is False 即报"
        "「清理长期记忆失败」",
    ("_run_pre_clean_action", "delete", 4):
        "未校验（customer_tag_remove 删标签）：清理型，同上独立单处理（issue #3807）",
    ("login", "post", 1):
        "已校验（隐式）：必须解析出 token，拿不到即抛错 —— 缺值不可能继续",
    ("get_or_create_session", "post", 1):
        "已校验（隐式）：必须解析出 session_id，拿不到即抛错",
    ("get_or_create_session", "post", 2):
        "已校验（隐式）：同上（重建会话分支）",
}

# 未校验≠放任：这些条目必须带 issue 号，否则"未校验"会变成默认选项。
UNVERIFIED_MARK = "未校验"
ISSUE_REF = re.compile(r"#\d{3,}")


def write_sites() -> list:
    """扫描 runner 源码 → `[(func, method, nth)]`（纯静态，零网络/零 LLM）。"""
    sites, counts, func = [], {}, "?"
    for ln in RUNNER_PATH.read_text(encoding="utf-8").split("\n"):
        d = DEF_LINE.match(ln)
        if d:
            func = d.group(1)
        w = WRITE_CALL.search(ln)
        if w:
            key = (func, w.group(1))
            counts[key] = counts.get(key, 0) + 1
            sites.append((func, w.group(1), counts[key]))
    return sites


def test_scan_is_not_vacuous():
    """前提：扫描真的看到了写调用（否则下面的登记表比对是空断言）。"""
    sites = write_sites()
    assert len(sites) >= 10, f"只扫到 {len(sites)} 处写调用 —— 扫描正则失效（守卫会静默空跑）"
    assert ("restore_product", "patch", 1) in sites, "连 #3807 本体都没扫到 —— 扫描不可信"


def test_every_write_site_has_a_disposition():
    """**核心**：每一处写调用都必须被显式处置（新增/删除即红）。"""
    sites = set(write_sites())
    known = set(DISPOSITIONS)
    new = sorted(sites - known)
    gone = sorted(known - sites)
    assert new == [], (
        "新增了未登记的写操作 —— 请回答「这条写操作怎么算成功、失败是否可见」（#3807 的类）：\n  "
        + "\n  ".join(f"{f}.{m} 第 {n} 次" for f, m, n in new))
    assert gone == [], (
        "登记表里有已不存在的写操作（代码搬走了/删了）—— 请同步登记表，别让它变成过期文件：\n  "
        + "\n  ".join(f"{f}.{m} 第 {n} 次" for f, m, n in gone))


def test_unverified_sites_carry_a_reason_and_an_issue():
    """「未校验」不许裸奔：必须有理由 + issue 号（否则它会变成默认选项）。"""
    bad = []
    for key, why in DISPOSITIONS.items():
        if UNVERIFIED_MARK in why and not ISSUE_REF.search(why):
            bad.append(f"{key}: {why}")
    assert bad == [], "以下未校验写操作没有登记 issue（将来无人处理）：\n  " + "\n  ".join(bad)


def test_the_3807_site_is_actually_verified():
    """#3807 本体必须**真的**是"已校验"档：改回"未校验"即红（防止修复被静默回退）。"""
    assert "已校验" in DISPOSITIONS[("restore_product", "patch", 1)]
    src = RUNNER_PATH.read_text(encoding="utf-8")
    i = src.index("async def restore_product")
    body = src[i:src.index("\nasync def ", i + 10)]
    assert "status_code" in body, "restore_product 不再看响应状态（#3807 复发）"
    assert "回读" in body and "PRECONDITION_NOT_RESTORED" in body, (
        "restore_product 不再回读校验 / 不再用可见标记（#3807 复发：复位空转又变静默）")
