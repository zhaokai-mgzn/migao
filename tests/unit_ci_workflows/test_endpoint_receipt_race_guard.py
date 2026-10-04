# case_ids: MC-082
"""**端点级判据的类级元守卫**（issue #6318，铁律 8）。

## 这一类缺陷长什么样（本单的形态：**服务级绿、端点级红**）

`#6301` 的修复带了一份真库并发判据 `BatchStocktakeConcurrentRealDbTest` —— 它调的是**服务方法**，
断言「服务层不抛异常 / 回执行 1 applied + 5 replayed」。用户看到的契约却**不在那一层**：
异常 → HTTP 状态的映射住 `GlobalExceptionHandler`，回执体住 `data.lines[].status`。
两层之间任何一处走偏（异常没被消解、异常没被映射、回执没改状态），
**服务级判据照旧全绿，而端点上仍是 5 个 500**（`#6318` 复现到的 `[200,500,500,500,500,500]`）。

⇒ 对「冲突在 mapper 内以原子写（`ON CONFLICT`）消解」的写入点，**它的契约是回执语义** ⇒
必须有一条**端点级**判据（HTTP 状态 + 回执体，且能被注入式红证打成 5xx）。
**只修这一处 = 没修**：全仓还有若干同类写入点，本判据把「未登记就进不来」钉住。

## 判据（六条，全部可归因）

| # | 判什么 | 会怎么红 |
|---|---|---|
| 1 | **未登记即红**：现取的「mapper 内 `ON CONFLICT` 原子闸」写入点必须逐条出现在台账（`sites` 或 `deferred`） | 新增一处这样的写入点而没登记 ⇒ **具名**报出该写入点 / 表 |
| 2 | **登记即须属实（双向）**：台账里的每条都必须在**现取集合**里 | 台账给不存在（或已改名 / 已摘掉闸）的写入点盖章 ⇒ 红 |
| 3 | **端点必须现取存在**：`sites` 里声明的 `endpoint`（`"POST /api/..."`）必须是控制器里**真有的**写映射 | 端点被改名 / 写错 / 删掉 ⇒ 红 |
| 4 | **判据必须在场且是端点级**：`criterion` 的 `文件::符号` 必须逐字存在，且该文件里有端点驱动标记（`MockMvc`） | 只挂一份服务级判据来充数 / 符号被改名 / 文件被删 ⇒ 红 |
| 5 | **deferred 必须写明理由**；`case_ids` 必须在 `.github/cases/` 里存在 | 把未建的判据塞进 deferred 且不写理由 ⇒ 红；用例号查无此例 ⇒ 红 |
| 6 | **fail-closed**：现取集合为空 / 台账 `sites` 为空 ⇒ 红 | 有人改坏扫描口径或清空台账「消红」⇒ 当场红（判据自己失效必须自曝） |

## 边界（照实登记，§19.1）

- 只裁**原子闸族**（`handling` 指向 mapper 文件且该文件里有 `ON CONFLICT`）。服务侧
  `catch (DuplicateKeyException)` 的那一族**不在射程内**（它们的对外语义各不相同：有的是
  「返回既有单号」、有的是「忽略」—— 统一要求端点级判据是业务口径，不是形态学能裁的）；
- 「端点」判定是**形态学**的：只认 `@RequestMapping(类) + @Post/Put/Patch/DeleteMapping(方法)`
  的**单字符串**写法；注解数组（`{"/a","/b"}`）、无参映射、以及非 admin-api 模块的控制器**不在射程内**；
- 「判据是端点级的」用 `MockMvc` 这个**驱动标记**判 —— 它判不了「那条判据真的断言了状态码」
  （行为面靠判据自己；本表另外登记了 `red_proof`，但**没有**机械判据去跑它）；
- 它**不**判「某个写入点该不该有幂等键」（业务口径），也不为 `deferred` 的存量缺口背书。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code as _java_code  # noqa: E402

MAIN_JAVA = REPO_ROOT / "backend/admin-api/src/main/java"
CONTROLLER_DIR = MAIN_JAVA / "com/migao/admin/controller"
UNIQUE_LEDGER = REPO_ROOT / "tests/unit_ci_workflows/unique_write_ledger.json"
LEDGER = REPO_ROOT / "tests/unit_ci_workflows/endpoint_receipt_race_ledger.json"
CASES_DIR = REPO_ROOT / ".github/cases"

NONE = "none"
ENDPOINT_DRIVER_MARKER = "MockMvc"   # 端点级判据的**驱动标记**（真 MockMvc 栈）
_CONFLICT_GATE = "ON CONFLICT"

#: 控制器上的类级前缀与方法级写映射（**只认单字符串写法**，见覆盖边界）
_CLASS_MAPPING = re.compile(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]+)"')
_METHOD_MAPPING = re.compile(r'@(Post|Put|Patch|Delete)Mapping\s*\(\s*(?:value\s*=\s*)?"([^"]+)"')


def java_code(text: str) -> str:
    """剥掉 Java 注释与字符串字面量（复用判据面的**唯一一份**实现）。"""
    return _java_code(text)


# ══════════════════════════════════════════════════════════════════════════════
# 一、现取（真值源）
# ══════════════════════════════════════════════════════════════════════════════


def atomic_gate_sites(unique_sites: dict, read) -> dict[str, dict[str, str]]:
    """**现取**「冲突在 mapper 内以 `ON CONFLICT` 原子写消解」的写入点。

    @param unique_sites `tests/unit_ci_workflows/unique_write_ledger.json` 的 `sites`
    @param read         `(仓库相对路径) -> str | None`（找不到返回 None）
    """
    out: dict[str, dict[str, str]] = {}
    for site, info in unique_sites.items():
        handling = info.get("handling")
        if not handling or handling == NONE:
            continue
        if "/mapper/" not in handling or not handling.endswith(".java"):
            continue
        text = read(handling)
        if text is None or _CONFLICT_GATE not in java_code(text):
            continue
        out[site] = {"table": info.get("table", "?"), "handling": handling}
    return out


def write_endpoints(sources: dict[str, str]) -> set[str]:
    """**现取**控制器里的写端点（`"POST /api/admin/..."` 形态）。"""
    out: set[str] = set()
    for text in sources.values():
        code = java_code(text)
        found = _CLASS_MAPPING.search(code)
        base = found.group(1) if found else ""
        for match in _METHOD_MAPPING.finditer(code):
            out.add(f"{match.group(1).upper()} {base}{match.group(2)}")
    return out


def case_ids_in_case_library() -> set[str]:
    """`.github/cases/*.yml` 里登记的用例 id（用例库 = 唯一真源）。"""
    ids: set[str] = set()
    for path in CASES_DIR.glob("*.yml"):
        for match in re.finditer(r"^\s*-\s*id:\s*([A-Z]+-\d+)\s*$", path.read_text(encoding="utf-8"),
                                 re.M):
            ids.add(match.group(1))
    return ids


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据本体（纯函数：输入语料 ⇒ 具名问题清单）
# ══════════════════════════════════════════════════════════════════════════════


def problems(ledger: dict, gated: dict, endpoints: set[str], read, case_ids: set[str],
             files: dict[str, str] | None = None) -> list[str]:
    """把「台账 × 现取语料」判成**具名问题清单**（空 = 绿）。"""
    files = files or {}
    out: list[str] = []
    sites = ledger.get("sites") or {}
    deferred = ledger.get("deferred") or {}

    # 判据 6：fail-closed —— 判据自己失效必须自曝，不许静默绿
    if not gated:
        out.append("fail-closed: 现取的「mapper 内原子闸（ON CONFLICT）」写入点集合为**空** ⇒ "
                   "扫描口径已坏或唯一真值源被搬走（拒绝静默绿）")
    if not sites:
        out.append("fail-closed: 台账 `sites` 为空 ⇒ 「已有端点级判据」的登记面失效（拒绝静默绿）")
    if not case_ids:
        out.append("fail-closed: `.github/cases/*.yml` 里一条用例 id 都扫不到 ⇒ 用例面扫描口径已坏"
                   "（否则「case_ids 未登记」这条判据会被静默关掉）")

    # 判据 1：未登记即红
    for site in sorted(gated):
        if site not in sites and site not in deferred:
            out.append(f"未登记即红: `{site}`（表 {gated[site]['table']}）写带唯一约束的表、且冲突在 "
                       f"mapper 内以 ON CONFLICT 消解 —— 它的对外契约是**回执语义** ⇒ 必须有端点级判据"
                       f"（或写进 deferred 并给出理由）")

    # 判据 2：登记即须属实（双向）
    for site in sorted(set(sites) | set(deferred)):
        if site not in gated:
            out.append(f"台账给不存在的闸盖章: `{site}` —— 现取集合里没有这个「mapper 内 ON CONFLICT」"
                       f"写入点（改名 / 摘掉闸 / 移出唯一约束表 ⇒ 台账只许缩短）")

    # 判据 3/4/5：sites 逐条核实
    for site, entry in sorted(sites.items()):
        endpoint = entry.get("endpoint")
        if endpoint not in endpoints:
            out.append(f"端点不存在: `{site}` 声称 `{endpoint}` —— 控制器里现取不到这个写映射"
                       f"（改名 / 写错 / 已删）")
        criterion = entry.get("criterion") or ""
        if "::" not in criterion:
            out.append(f"判据登记形态不对: `{site}` → `{criterion}`（要写成 `<仓库相对路径>::<符号>`）")
        else:
            path, symbol = criterion.split("::", 1)
            text = files.get(path, read(path))
            if text is None:
                out.append(f"判据文件不存在: `{site}` → `{path}`")
            else:
                if symbol not in text:
                    out.append(f"判据符号不在文件里: `{site}` → `{criterion}`")
                if ENDPOINT_DRIVER_MARKER not in java_code(text):
                    out.append(f"判据不是端点级: `{site}` → `{path}` 里没有 `{ENDPOINT_DRIVER_MARKER}` "
                               f"（服务级判据不能替端点级契约背书 —— 这正是 #6318 的病）")
        declared = str(entry.get("case_ids") or "").strip()
        if not declared:
            out.append(f"缺 case_ids: `{site}`（新增/登记的判据必须挂用例号）")
        else:
            for cid in [c.strip() for c in declared.split(",") if c.strip()]:
                if case_ids and cid not in case_ids:
                    out.append(f"case_ids 未在用例库登记: `{site}` → {cid}（`.github/cases/*.yml` 是唯一真源）")

    # 判据 5：deferred 必须写明理由
    for site, entry in sorted(deferred.items()):
        if not str(entry.get("reason") or "").strip():
            out.append(f"deferred 必须写明理由: `{site}`（未建的判据不许静默挂着）")
        if not str(entry.get("restart_condition") or "").strip():
            out.append(f"deferred 必须写明重启条件: `{site}`（什么条件下补上端点级判据）")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、真语料上的判据
# ══════════════════════════════════════════════════════════════════════════════


def _read(rel: str) -> str | None:
    path = REPO_ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else None


def _real_problems() -> tuple[list[str], dict, dict, set[str]]:
    unique = json.loads(UNIQUE_LEDGER.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gated = atomic_gate_sites(unique.get("sites") or {}, _read)
    endpoints = write_endpoints(
        {str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf-8")
         for p in sorted(CONTROLLER_DIR.glob("*.java"))})
    return problems(ledger, gated, endpoints, _read, case_ids_in_case_library()), ledger, gated, endpoints


def test_every_atomic_gate_site_is_registered_with_an_endpoint_level_criterion():
    """判据 1~6 合并：现取的原子闸写入点 ⇄ 台账双向相等，且每条 `sites` 的端点级判据真的在场。"""
    found, ledger, gated, endpoints = _real_problems()
    print(f"[#6318 元守卫] 现取原子闸写入点 = {len(gated)} 条；台账 sites = {len(ledger.get('sites') or {})}、"
          f"deferred = {len(ledger.get('deferred') or {})}；现取写端点 = {len(endpoints)} 个")
    for site in sorted(gated):
        print(f"  · {site}（表 {gated[site]['table']}）")
    assert not found, "端点级判据台账与现取语料不一致：\n  - " + "\n  - ".join(found)


def test_the_stocktake_site_is_covered_at_the_endpoint_level():
    """#6318 那一处（`stock_batch_consumptions` 的盘点原子闸）必须在 `sites` 里、且判据是端点级。"""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    site = ("backend/admin-api/src/main/java/com/migao/admin/service/"
            "StockBatchConsumptionService.java::consumptionMapper")
    assert site in (ledger.get("sites") or {}), (
        f"#6318：`{site}` 必须登记在 sites（它是「服务级绿、端点级红」的本体）")
    entry = ledger["sites"][site]
    assert entry.get("level") == "endpoint", "该写入点的契约是回执语义 ⇒ 判据必须在端点级"
    for key in ("criterion", "red_proof", "case_ids"):
        assert entry.get(key), f"#6318：`{site}` 缺 `{key}`（判据 / 红证 / 用例号都要能追）"


# ══════════════════════════════════════════════════════════════════════════════
# 四、判别力自证（内存坏语料 ⇒ 必须具名判红；对照语料 ⇒ 不许红）
# ══════════════════════════════════════════════════════════════════════════════


_GOOD = {
    "sites": {
        "svc/A.java::mapperA": {
            "table": "t_a",
            "endpoint": "POST /api/x",
            "criterion": "test/EndpointTest.java::caseA",
            "case_ids": "MC-999",
        }
    },
    "deferred": {},
}
_GOOD_GATED = {"svc/A.java::mapperA": {"table": "t_a", "handling": "mapper/MapperA.java"}}
_GOOD_FILES = {
    "test/EndpointTest.java": "class EndpointTest { MockMvc mvc; void caseA() {} }",
    "mapper/MapperA.java": "ON CONFLICT DO NOTHING",
}


def _pr(ledger=_GOOD, gated=_GOOD_GATED, endpoints=None, files=None, case_ids=None) -> list[str]:
    return problems(ledger, gated, endpoints if endpoints is not None else {"POST /api/x"},
                    lambda rel: (files if files is not None else _GOOD_FILES).get(rel),
                    case_ids if case_ids is not None else {"MC-999"},
                    files=files if files is not None else _GOOD_FILES)


def test_injected_bad_corpora_are_named():
    """判别力自证：坏形态各自**具名**判红；对照语料**不红**。"""
    # 对照：好语料不许红
    assert _pr() == [], f"对照语料不该判红，却得到 {_pr()}"

    # 坏形态 ①：新增未登记的原子闸写入点
    extra = dict(_GOOD_GATED)
    extra["svc/B.java::mapperB"] = {"table": "t_b", "handling": "mapper/MapperB.java"}
    got = _pr(gated=extra)
    assert any("未登记即红" in p and "svc/B.java::mapperB" in p for p in got), got

    # 坏形态 ②：台账给不存在的闸盖章
    got = _pr(ledger={"sites": {}, "deferred": {"svc/Ghost.java::m": {"reason": "x", "restart_condition": "y"}}})
    assert any("台账给不存在的闸盖章" in p and "svc/Ghost.java::m" in p for p in got), got

    # 坏形态 ③：端点现取不到
    bad = json.loads(json.dumps(_GOOD))
    bad["sites"]["svc/A.java::mapperA"]["endpoint"] = "POST /api/does-not-exist"
    got = _pr(ledger=bad)
    assert any("端点不存在" in p for p in got), got

    # 坏形态 ④：判据文件不存在 / 符号不在 / 不是端点级（服务级冒充）
    got = _pr(files={"mapper/MapperA.java": "ON CONFLICT"})
    assert any("判据文件不存在" in p for p in got), got
    bad = json.loads(json.dumps(_GOOD))
    bad["sites"]["svc/A.java::mapperA"]["criterion"] = "test/EndpointTest.java::caseMissing"
    assert any("判据符号不在文件里" in p for p in _pr(ledger=bad)), "符号缺失必须判红"
    service_level = {"test/ServiceTest.java": "class ServiceTest { void caseA() {} }"}
    bad = json.loads(json.dumps(_GOOD))
    bad["sites"]["svc/A.java::mapperA"]["criterion"] = "test/ServiceTest.java::caseA"
    got = _pr(ledger=bad, files={**service_level, "mapper/MapperA.java": "ON CONFLICT"})
    assert any("判据不是端点级" in p for p in got), got

    # 坏形态 ⑤：deferred 不写理由 / 不写重启条件 / case_ids 查无此例
    got = _pr(ledger={"sites": _GOOD["sites"], "deferred": {"svc/B.java::m": {"table": "t_b"}}},
              gated={**_GOOD_GATED, "svc/B.java::m": {"table": "t_b", "handling": "mapper/MapperB.java"}})
    assert any("deferred 必须写明理由" in p for p in got), got
    assert any("deferred 必须写明重启条件" in p for p in got), got
    got = _pr(case_ids={"XX-001"})
    assert any("case_ids 未在用例库登记" in p for p in got), got

    # 坏形态 ⑥：fail-closed（现取空 / 台账 sites 空 / 用例库扫描空）
    got = _pr(gated={})
    assert any("fail-closed" in p and "集合为**空**" in p for p in got), got
    got = _pr(ledger={"sites": {}, "deferred": {}})
    assert any("fail-closed" in p and "`sites` 为空" in p for p in got), got
    got = _pr(case_ids=set())
    assert any("用例面扫描口径已坏" in p for p in got), got
