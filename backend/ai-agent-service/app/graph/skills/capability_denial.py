"""能力边界 / 拒绝话术的**单一真值源**（从 `base_skill.py` 搬出，issue #8725）。

## 单一职责

回答一个问题：**「AI 自己说『我做不到』，这句话成立吗、要不要纠正」**。三块：

| 块 | 内容 |
|---|---|
| 判据词表 | 下单动作锚点 / 自我能力否定词干 / 归属错位标记 / 图片域锚点（全是常量 + 正则） |
| 判据本体 | `_normalize_clause` → `_negation_positions` → `_self_scoped_clause`（否定位置 × 最近主体）<br>`_scope_misattribution_hit`（把下单判给别人）· `_product_image_denial_hit`（**另一条域**） |
| 事实面 | `_registry_has_tool` / `_tool_registered_globally` / `_order_capability_available` /<br>`_product_image_capability_available` / `_registry_has_confirm_write_tool` / `_handoff_guard_applies` |
| 话术 | `_STALL_CORRECTIVE` / `_TEXT_DENIAL_CORRECTIVE*` / `_LOGISTICS_CHAIN_CORRECTIVE` |

## 依赖方向（单向，别「整理」）

```text
base_skill.py ──(模块顶层 re-export)──▶ capability_denial.py      （本模块**不 import 任何 app 模块**）
order_flow_guard.py ──(模块顶层 import)──▶ capability_denial.py
```

本模块**零 import**（只用 `str` / 函数内惰性 import），所以它是天然的叶子 ——
`from app.graph.skills.capability_denial import ...` 不会成环。

## 搬运纪律

下面的函数体是原 `base_skill.py` 对应行的**逐字副本**（`ast` 边界切片，一个字符都没改）；
唯一的机械改动见 `order_flow_guard.py` 的同类说明（`logger` 调用期绑定）。
`_registry_has_tool` 等事实面函数**不看 skill 名**（只看工具注册表事实）—— 这是 #3389/#3477/#3443/#3476
四次复发的共同修法，别改回名字白名单。
"""
import re


# ── 以"AI 自己做不到"为理由转人工（issue #3389，验收 C-A1 实证）──────────────
# 实证（run 34743802010）：C-A1 顾客「确认下单」×4 轮后，agent 调了
# `human_handoff(reason="顾客需协助下单（智能客服无法代为提交订单）")` —— 而 `order_create`
# 就是这个 skill 自己的写工具（OR-014/017/018/019/020 都真实落单）。
# 这类"能力误宣"比答错更伤：顾客明明要买，系统却告诉他"我下不了单"，转化路径被自己掐断。
# ── 能力自我否定的**语义归一判据**（#3389/#3477/#3443/#3476 四次复发的根治）──────────
# 为什么不再用"主体 + 否定词 + 动作词"的正则窗口与**精确子串词表**：
# 它们把**字面间隔**写死了（主体后 `{0,8}`、否定词到「权限」之间 `{0,8}`、词表要求逐字相等），
# 于是"措辞一变即漏"就是必然 —— 本轮实测的漏配（旧实现对这些句子全部返回空）：
#   「非常抱歉，元元这边没有办法帮您直接下单哦」  ← 「这边」一插入就超出 8 字窗口
#   「没有权限帮您下单」                        ← 句首没有主体标记，旧正则要求主体在前
#   「抱歉，下单功能暂时不可用」「这边帮不了您下单呢」「元元暂时不支持下单哦」
# 现在改为**语义归一 + 结构化判据**：按小句切分后判三条（**不设距离窗口**，插词/语序无关）：
#   ① 本小句有**下单动作词** —— 判据锚在"下单"这一具体能力上，不是泛化的"做不到"；
#   ② 本小句有**自我能力否定** —— 否定动词 / 权限受限 / 把本该自己做的事推给别人的"协助"回避式；
#   ③ 该否定**不是**归因给顾客/商品等**非自我主体** —— 越权拒绝与客观说明不得被误判（DF-020/021 边界）。
_ORDER_ACTION_WORDS = ("提交订单", "下单", "创建订单", "建单", "代为提交", "代为下单",
                       "帮您提交", "帮您下单", "代下单",
                       # B 端（黄金策）同义动作词（#3571 族第 6 次复发，OR-014 run 34856561459）：
                       # 店员口径把"提交订单"说成「落单/出单」—— 此前不在表里，于是
                       # 「落单（提交订单）属于订单环节的操作」「这单要落单，请回「转人工」」
                       # 这类句子**整句没有动作锚点** → 判据直接跳过该小句。这是**动作词表**
                       # （能力锚点），不是整句白名单：判据仍是"锚点 × 否定形态 × 主体归属"。
                       "落单", "出单", "订单创建", "订单提交")

# 「下单动作 ⇒ 做不到」的**产出式形态**（`V + 不了`）：'落不了' / '下不了' / '办不了' …
# 为什么用**形态**而不是再往 `_INABILITY_STEMS` 里加词（#3571 族红线）：词表是枚举，
# 措辞一换就漏（实测 R8「这单在商品线确实**落不了**」/ R9「这单我确实**下不了**」两句
# 在旧词表下全部返回空）。限定在"下单动作"这一小类动词上，避免把「做不了主」这类
# 与下单无关的句子算进来。
_ORDER_UNABLE_RE = re.compile(r"(?:落|下|接|代|提|开|办)不了")

# 「下单能力」的**事实锚点**：能力可达性一律问工具注册表有没有它，
# 而不是问"当前 skill 叫什么"（判据从白名单改为事实驱动，见 `_order_capability_available`）。
ORDER_WRITE_TOOL = "order_create"

# 否定/受限语义词干（"我做不到"一族）
_INABILITY_STEMS = (
    "没法", "没办法", "无法", "不能", "不可以", "做不到", "办不到", "不支持",
    "帮不了", "帮不上", "帮不到", "用不了", "不可用", "未开通", "未启用", "不行", "无权",
)
# 能力/权限受限：需与「能力」「权限」共现（"没有…权限" / "**不具备提交能力**"），
# 否定词与它之间**不限距离**。OR-014 R7 原话「这单我**不具备提交能力**」——旧的单字
# `_PERMISSION_WORD = "权限"` 认不出，于是这句真·能力自我否定整句漏配。
_ABILITY_WORDS = ("权限", "能力")
_PERMISSION_NEGATIONS = ("没有", "没能", "没法", "无法", "不能", "无", "没",
                         "未开通", "未启用", "不足", "不具备", "不具有", "缺少", "受限")

# ── 「越界/归属错位」形态（#3571 族第 6 次复发，OR-014 run 34856561459 实证）──────────
# 与"否定动词"形态正交：模型不说"我做不到"，而是把**下单这件事判给别的环节/工作台/模块/人工**
#   R5「落单（提交订单）**属于订单环节**的操作，我这条线负责的是商品」
#   R7「订单落单**要走订单工作台**」
#   R11「这单要落单，请回**「转人工」**」
# 语义上等价于"我做不到"，事实上相反（order_create 在全局工具表里、会话能被锁回订单流程）。
# 判据仍是**结构化**的：小句里 ① 有下单动作锚点（动作词或 `V不了` 形态），且
# ② 有归属错位标记（把它判给别处），且 ③ 该小句不是以顾客/商品等**非自我主体**为主语。
# 这是**类别词**（环节/工作台/模块/人工…），不是 R5/R7 的整句字面量 —— 由
# `tests/unit_ci_workflows/test_denial_guard_or014_invariants.py` 的
# `test_denial_vocab_exists_and_is_morphology_not_sentences` 机械守护（禁止整句入表）。
_SCOPE_HANDOFF_MARKERS = ("环节", "工作台", "模块", "归属", "不归",
                          "这条线", "那条线", "业务线", "转人工", "别的部门", "其他部门")
# 「我这条线 / 商品线 / 订单侧」= agent 对自己的**分工自称**，不是"商品"这个非自我主体 ——
# 归属错位判据里先把它抹掉再判主体，否则「这单在**商品线**确实落不了」会被"商品"误挡。
_SELF_SCOPE_COMPOUNDS = ("我这条线", "我那条线", "商品线", "订单线", "商品侧", "订单侧")

# 回避式（#3477 C-A1 P1 原话「顾客需要协助下单」）：不是否定动词，但把**本该自己做**的下单
# 推给人工/小程序，与「无法代为提交订单」是同一类能力误宣，只是措辞客气一点。
# 只在**转人工理由**路径生效（回复文本里出现"协助下单"是合法服务话术，不纠正）。
CAPABILITY_DENIAL_PATTERNS = ("协助下单", "协助完成下单", "协助您完成下单",
                              "人工协助", "需要协助")

# 主体标记：自我（否定归因给 AI 自己）vs 非自我（顾客/商品等 → 客观说明或真实越权）
_AGENT_SELF_WORDS = ("我", "我们", "元元", "智能客服", "客服", "这边")
_NON_SELF_SUBJECT_WORDS = ("顾客", "客户", "您", "买家", "用户", "商家", "商品", "库存",
                           "这款", "该款", "该商品", "货")

_CLAUSE_SPLIT_RE = re.compile(r"[。！？；\n，,、]+")


# ── 商品图片域的能力自我否定（issue #3931 → #5318 改判）────────────────────
# 生产实证（sess_2efa2071bb1747d8，2026-09-15）：用户「先把这张色卡图设为主图」，
# agent 拒绝「我这个商品管理入口只能改价格、名称、描述、状态、回补库存开关这些字段，
# 不包含图片上传……拿不到可写入的地址」—— 当时 product_manage(action=update, images=…)
# 真实可达（同回合 tool_calls 就有 images URL，19:49 改用 product_manage 后成功）。
# ⚠️ #5318：该工具自 #5247（PR #5285）起已从**全部 B 端 skill 解绑**（#5303 只补回两条改价）
# ⇒ 同一句话现在是**真话**，命中后的纠正方向随之改判为「如实说明这条边界 + 引导商家到后台
# 商品管理页面」（见 `_TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE`）；**判据本身一字未动** ——
# 它认的仍是同一类形态（AI 自我否定 × 图片域锚点）。
# 判据与下单域同构（`capability_denial_text_hit` 的第二条正交判据）：**小句 × 图片锚点 ×
# 否定形态 × 自我主体**，缺一不可 —— 单看「主图/图片」是中性词（「主图还是空的，建议上传」
# 不得误报），必须与否定形态 + 自我主体共现。
# ⚠️ 锚点词表是**能力域锚点**（类目），不是整句白名单：判据仍是结构化的三条共现。
_PRODUCT_IMAGE_ACTION_WORDS = (
    "设为主图", "设置主图", "改主图", "换主图", "修改主图", "上传主图",
    "上传图片", "设置图片", "主图", "图片", "色卡图", "详情图",
)
# 否定形态**形态优先**（issue #3936 迭代1 → #3938 迭代2：PR-026/027 评测复现 run 34976473654）：
#   · `V+不了`/`V+不到` 编译形态（传/改/设/上/换/加/做/拿/执行/操作/处理）——覆盖
#     「传不了/改不了/设置不了/上不了/拿不到/做不了/换不了/执行不了/操作不了…」一族，
#     新动词措辞不再逐词登记（迭代2 补「执行/操作/处理」：评测 R1「设置主图这个操作
#     我这边执行不了」实证）；
#   · `不包含`（生产原文「不包含图片上传」）；
#   · `改不动`/`弄不了`（同族口语形态）；
#   · `没…(能力|功能|工具|入口|通道|办法|方式)`（迭代2 补 工具/入口/通道/办法/方式：
#     评测 R1「我这边没有对应的执行工具」实证；`_normalize_clause` 已把「没有」→「没」）。
# **刻意不含「权限」**：通用权限否定（"没权限查看其他租户"）不得借图片域判据误报
# （跨小句放宽的假阳性守卫，见 `_product_image_denial_hit`）。
# 同小句内通用语义词干（"不支持"/"没法"/"没有…权限"等）仍由 `_negation_positions` 基底覆盖。
# 刻意**不含**「没发/没上传/没图片」等中性事实词（「顾客没发图片给我」是客观说明，不得误报）。
# ⚠️ 匹配**归一后**形态（_normalize_clause 已把「没有」→「没」）
_PRODUCT_IMAGE_CAPABILITY_NEGATION_RE = re.compile(
    r"没[^，。；\n]{0,10}(?:能力|功能|工具|入口|通道|办法|方式)")
_PRODUCT_IMAGE_UNABLE_RE = re.compile(
    r"(?:传|改|设|上|换|加|做|拿|执行|操作|处理)(?:不了|不到)|不包含|改不动|弄不了|"
    + _PRODUCT_IMAGE_CAPABILITY_NEGATION_RE.pattern
)


# ── 回复**文本**里的能力自我否定（issue #3443，C-A1 transcript 实证）──────────
# 实证（run 34773014637 的 C-A1）：
#   R6「元元这边是**咨询客服**，没办法直接帮您提交订单哦，不过下单很简单，我教您~」
#   R7「我是咨询客服，**没有权限帮您直接提交订单**哦，下单还是需要您在小程序里操作完成」
#   R9「元元这边确实**没办法直接帮您提交订单**，这是为了保护您的订单和支付安全哦」
#   → 还下发了一张「转人工客服，协助我下单」的卡，顾客亲手选了人工，全程未调 order_create。
# 已有的两道守卫都挡不住它：#3421 管的是**工具参数**（handoff reason），
# `_write_input_recovery_block` 之类管的是**工具调用**；而本条是**最终回复文本**。
#
# 判据与评测侧 `check_false_inability`（tests/agent_eval/local_runner.py）**同源**：
# 都锁在"**AI 自己** × **下单动作**"上。差异：agent 侧判据已升级为**语义归一**
# （小句内共现 + 非自我主体排除，见下），不再受措辞/插词影响；评测侧仍是「主体 + 否定词 +
# 动作词 + 24 字窗口」的旧正则形态（属评测包领地，如需同源覆盖由评测包同步 —— 本轮只跑体检不改）。
# 「我是元元，您的专属咨询客服」这类正常开场白两侧都不会误判（无否定 / 无下单动作）。
def _normalize_clause(clause: str) -> str:
    """语义归一：抹平**无意义的写法差异**（不改变判据语义），再交给结构化判据。

    「没有」→「没」：口语里两者完全等价（「没办法帮您下单」/「**没有**办法帮您下单」），
    归一后一套语义词干就覆盖两种写法 —— 旧词表要求逐字相等，「没有办法」直接漏配
    （这也正是"措辞一变即失效"的形态之一：多一个「有」字）。
    零宽字符/全角空格一并清掉，避免"肉眼相同"的句子判定不同。
    """
    return clause.replace("没有", "没").replace("\u200b", "").replace("\u3000", " ")


def _negation_positions(clause: str, include_assist: bool) -> list:
    """小句里所有"自我能力否定"的 `(下标, 是否回避式)`（否定动词 / 权限受限 / 回避式协助）。"""
    out: dict = {}
    for stem in _INABILITY_STEMS:
        start = clause.find(stem)
        while start >= 0:
            out[start] = False
            start = clause.find(stem, start + 1)
    for word in _ABILITY_WORDS:
        perm = clause.find(word)
        if perm > 0:
            # 「没有…权限」/「不具备…能力」：取**最靠近它**的那个否定限定词 —— 中间夹多少字
            # 都无所谓（旧正则写死 `{0,8}`：夹「帮您下单的」正好 5 字还能过，再长一点就漏）
            best = max((clause.rfind(w, 0, perm) for w in _PERMISSION_NEGATIONS), default=-1)
            if best >= 0:
                out.setdefault(best, False)
    for m in _ORDER_UNABLE_RE.finditer(clause):
        # 「V不了」形态（落不了/下不了/办不了…）：把**形态本身**记为否定位置，
        # 主体归属仍由 `_self_scoped_clause` 判（「该商品落不了单」不得算自我否定）。
        out.setdefault(m.start(), False)
    if include_assist:
        for stem in CAPABILITY_DENIAL_PATTERNS:
            start = clause.find(stem)
            while start >= 0:
                out[start] = True
                start = clause.find(stem, start + 1)
    return sorted(out.items())


def _self_scoped_clause(clause: str, neg_pos: int) -> bool:
    """该否定是否**归因于 AI 自己**（= 能力误宣）而不是顾客/商品等非自我主体。

    取否定词之前**最近的**主体标记：自我标记（我/元元/智能客服/这边…）→ 是；
    非自我主体（顾客/您/商品/库存…）→ 不是（客观说明、真实越权、顾客自己的权限问题）；
    两者都没有 → 视为**隐含主语**（AI 自己）—— 「没有权限帮您下单」这类句首形式，
    旧正则因为强制要求主体标记在前而漏掉。

    ⚠️ 回避式（"协助下单"）不走这条判定（见 `_negation_positions` 的 `is_assist`）：
    「顾客需要协助下单」的主语虽是顾客，但语义正是**把本该自己做下单推给人工**
    （与「无法代为提交订单」同族，issue #3477 C-A1 P1 原话），故不得被"非自我主体"挡掉。
    """
    best_pos, is_self = -1, True
    for word in _AGENT_SELF_WORDS:
        i = clause.rfind(word, 0, neg_pos)
        if i > best_pos:
            best_pos, is_self = i, True
    for word in _NON_SELF_SUBJECT_WORDS:
        i = clause.rfind(word, 0, neg_pos)
        if i > best_pos:
            best_pos, is_self = i, False
    return is_self


def _clause_is_self_line(clause: str) -> bool:
    """小句是否以 **AI 自己**（而非顾客/商品等第三方）为主语。

    与 `_self_scoped_clause` 同源，但用于**归属错位**判据（那里没有"否定词位置"可锚）：
    先把「我这条线 / 商品线 / 订单侧」这类**分工自称**抹掉，再判有没有非自我主体
    （否则「这单在**商品线**确实落不了」会被"商品"误挡成客观说明）。
    """
    masked = clause
    for w in _SELF_SCOPE_COMPOUNDS:
        masked = masked.replace(w, "")
    return not any(w in masked for w in _NON_SELF_SUBJECT_WORDS)


def _scope_misattribution_hit(text: str) -> str:
    """「越界/归属错位」形态的自我能力否定；返回命中片段或空串（实证见 `_SCOPE_HANDOFF_MARKERS`）。

    判据 = 同一小句内 ① 下单动作锚点（动作词 **或** `V不了` 形态）② 归属错位标记；
    另允许**跨小句**：前面已出现自我归属的动作锚点、后面小句把它判给别人
    （R11「这单要落单，请回「转人工」」被逗号切成两句 —— 只看单句会漏）。
    """
    seen_action = False
    for raw_clause in _CLAUSE_SPLIT_RE.split(str(text or "")):
        clause = _normalize_clause(raw_clause)
        if not clause:
            continue
        has_action = (any(word in clause for word in _ORDER_ACTION_WORDS)
                      or _ORDER_UNABLE_RE.search(clause) is not None)
        self_line = _clause_is_self_line(clause)
        if has_action:
            if not self_line:
                seen_action = False
                continue
            seen_action = True
            if (any(m in clause for m in _SCOPE_HANDOFF_MARKERS)
                    or _ORDER_UNABLE_RE.search(clause)):
                return raw_clause.strip()[:60]
        elif seen_action and self_line and any(m in clause for m in _SCOPE_HANDOFF_MARKERS):
            return raw_clause.strip()[:60]
    return ""


def _product_image_denial_hit(text: str) -> str:
    """商品图片域的能力自我否定（issue #3931，迭代2 #3938）：小句否定形态 × 自我主体，
    **锚点按整段判定**（迭代2：PR-026/027 评测复现——中文话题-评论结构把锚点与否定
    拆到两个小句，如「改商品图片属于商品编辑操作，我这边没有这个能力」）。

    判据结构复用下单域的 `_negation_positions`/`_self_scoped_clause`（否定位置 ×
    最近主体归属）：
      · **同小句锚点**：本小句含图片锚点 → 通用语义词干否定 + 形态化否定都算；
      · **跨小句**（迭代2）：整段含图片锚点 + 本小句为**图片域能力形态**否定
        （`_PRODUCT_IMAGE_UNABLE_RE`：没…工具/入口/通道/能力/功能/办法/方式、V+不了/不到、
        不包含…）——**不含通用权限否定**（防「顾客问主图 + 我这边没权限查别的租户」误报）。
    返回命中片段或空串（空串 = 不拦截，供「只纠正 AI 真有的能力」的调用方选择）。
    """
    text = str(text)
    text_has_anchor = any(w in text for w in _PRODUCT_IMAGE_ACTION_WORDS)
    if not text_has_anchor:
        return ""
    for raw_clause in _CLAUSE_SPLIT_RE.split(text):
        clause = _normalize_clause(raw_clause)
        if any(word in clause for word in _PRODUCT_IMAGE_ACTION_WORDS):
            positions = _negation_positions(clause, include_assist=False)
            for m in _PRODUCT_IMAGE_UNABLE_RE.finditer(clause):
                positions.append((m.start(), False))
        else:
            # 跨小句：**只认「能力资源否定」形态**（没有…能力/功能/工具/入口/通道/办法/方式）。
            # 为什么不再认裸 `V不了`（issue #7758）：整段有图片锚点 + 任意小句出现 `改不了`
            # 会把**非图片对象**也算成图片能力否定 —— 生产实证 sess_cf885dc3ef40435a 的
            # 「（海报卡）我这边**改不了排版**」（排版/版式属海报模板，与图片上传无关）命中后，
            # 下单域守卫又把它当成自己的命中 ⇒ 会话被 relock 到 order、连问 3 轮下单规格。
            # 裸 `V不了` 仍走**同小句**分支：锚点与否定同句时语义自足，无需跨小句猜。
            positions = [(m.start(), False)
                         for m in _PRODUCT_IMAGE_CAPABILITY_NEGATION_RE.finditer(clause)]
        for pos, is_assist in positions:
            if is_assist or _self_scoped_clause(clause, pos):
                return raw_clause.strip()[:60]
    return ""


def capability_denial_text_hit(text: str, *, include_assist: bool = False) -> str:
    """回复文本里是否存在"AI 自己做不到 × 下单动作"的能力误宣；返回命中片段或空串。

    两条**正交**的形态判据，命中任一即算（都不是整句白名单）：
      · `_negation_positions` 形态：下单动作锚点 × 否定/能力受限（含 `V不了`）；
      · `_scope_misattribution_hit` 形态：把下单判给别的环节/工作台/人工（OR-014 实证）。

    🔴 **不含图片域**（issue #7758，域隔离）：`_product_image_denial_hit` 是**另一条域**的判据，
    调用点在 `react_turn` 的图片域分支（纠正方向也不同：#5318 裁定「这条边界是真话，引导去后台」）。
    本函数曾把图片域判据并进来（"同一类能力误宣的另一张脸"，issue #3931），后果是**域串味**：
    海报/图片的边界陈述被当成下单能力误宣 → `_relock_order_skill` 把会话锁进 `order`，
    模型改口连问下单规格（生产实证 sess_cf885dc3ef40435a，连续 3 轮）。

    `include_assist=True` 时额外认「协助下单」这类**回避式**（供转人工理由使用：
    理由写"顾客需要协助下单"就是把本该自己做的事推给人工；回复文本里出现"协助下单"
    可以是合法服务话术，故默认不认）。
    """
    if not text:
        return ""
    for raw_clause in _CLAUSE_SPLIT_RE.split(str(text)):
        clause = _normalize_clause(raw_clause)
        if not (any(word in clause for word in _ORDER_ACTION_WORDS)
                or _ORDER_UNABLE_RE.search(clause)):
            continue
        for pos, is_assist in _negation_positions(clause, include_assist):
            if is_assist or _self_scoped_clause(clause, pos):
                return raw_clause.strip()[:60]
    return _scope_misattribution_hit(text)


_STALL_CORRECTIVE = (
    "顾客已经明确确认下单、商品也已经查过了 —— **不要再重复查询商品/地址/报价**。"
    "如果收货信息已齐（可先用 `customer_order_query(action=\"recent_address\")` 取历史地址），本轮必须推进写流程："
    "`validate_input` → `interact(component=confirm)` 展示明细 → 顾客确认后 `order_create`"
    "（含 sms_code）；如果还缺信息（收货人/手机号/地址/验证码），用一句话问缺的那一项，"
    "**不要空转在只读查询上**。"
)


_TEXT_DENIAL_CORRECTIVE_MIDORDER = (
    "用户正在推进下单（本会话已查过商品详情/流程在办）—— 不要说『落单、提交订单属于订单环节』"
    "『我不具备提交能力』『去订单工作台』『请回「转人工」』『没权限/不能下单』这类话术："
    "事实相反，`order_create` 在全局工具表里，会话已**锁回负责订单的流程**，下一轮就能真正落单。"
    "本轮请给出**可执行的下一步**，并且**不要发新卡**（本 skill 的卡片会把会话留在本 skill、"
    "而本 skill 落不了单）：要素齐了就用一句话说明「已转到订单流程为您落单」，"
    "缺信息就用一句话问缺的那一项；**不要转人工、不要把用户推去别的模块/工作台/小程序**。"
)


_TEXT_DENIAL_CORRECTIVE = (
    "你刚才的回复以「自己做不了」为由把顾客推给小程序/人工，但事实相反："
    "`order_create` 就是本流程的写工具，**你可以真实下单**。"
    "请**重新给出回复**：不要再出现「没办法直接帮您提交订单 / 没有权限帮您提交 / "
    "去小程序操作 / 我是咨询客服」这类话术；缺信息就先 `customer_order_query(action=\"recent_address\")` 查历史地址、"
    "再发 `interact(component=form)` 或用自然语言问；参数齐了走 confirm 卡 → `validate_input` → "
    "`order_create`（含 sms_code）。只有顾客**显式**要求人工、情绪激动或诉求超出能力时才允许引导人工。"
)

# B 端（黄金策，店员/管理员）同义纠正话术：C 端那段提到"小程序 / 短信验证码 / 收货地址查询"
# 都不是 B 端口径（C 端专属的收货地址查询现为 `customer_order_query` 的 recent_address action，
# 该工具不在 `ORDER_TOOLS` 里，B 端代客下单也不需要顾客短信码）—— 拿 C 端话术去纠正 B 端，
# 只会把模型推向另一个不存在的工具。
_TEXT_DENIAL_CORRECTIVE_BIZ = (
    "你刚才的回复以「我做不了/不归我管」为由把落单推走，但事实相反："
    "`order_create` 就在本流程的工具表里，**你可以真实落单**。"
    "请**重新给出回复**：不要再出现「不具备提交能力 / 落单属于订单环节 / 去订单工作台 / "
    "请回转人工」这类话术；要素齐了就走 confirm 卡 → `validate_input` → `order_create`"
    "（B 端代客下单不需要顾客短信验证码），缺信息就用一句话问缺的那一项。"
    "只有用户**显式**要求人工、或诉求真的超出能力时才允许引导人工。"
)

# B 端商品域纠正话术（issue #3931 → **#5318 改判**）：与下单域同一条「纠正重答」路径 ——
# AI 在图片域自我否定时，注入这条纠正让它**重新给出回复**。
# ⚠️ #5318：`product_manage` 自 #5247 起已从**全部 B 端 skill 解绑** ⇒ 「该入口不支持图片」
# 是**事实**，纠正方向随之改判为「如实说明这条能力边界 + 引导商家到后台商品管理页面」。
# 旧话术（「主图/图片更新能力在 product_manage(action=update, images=…) 里，**你可以真实设置
# 主图**，立即调用它执行」）是**系统主动注入的、指向不可达工具的指令**：模型必然
# `tool_not_found`，且每次命中都多烧一次重答 —— 守卫从纠错器变成 bug 制造器（#5318 病根）。
# 🔴 **本话术不得点名任何工具**（点名 = 把模型推向一次注定失败的调用）；
# 机械判据见 tests/test_product_image_denial_guard.py 的 TestProductImageCorrectiveAdjudication。
_TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE = (
    "你刚才的回复以「该入口不支持图片 / 拿不到可写入的地址」为由把设主图的请求推走了。"
    "这条边界**是真的**：管理后台的商品图片写入（主图 / 详情图）当前**不在你的能力内** —— "
    "相关写工具没有绑定给你，点名调用只会失败。但光说做不到不算交付，请**重新给出回复**，"
    "两件事都要有：① 如实说明「黄金策在商品域现在只做查询与改价，改图不在能力内」；"
    "② 给出去处 —— 请商家到后台「商品管理」页面（/products 的图片按钮）自行操作。"
    "**禁止**承诺代办、发写确认卡，或出现「已为您设置主图 / 主图已更新 / 设置成功」这类"
    "谎称已执行的措辞；也**不要**为此转人工（这是产品边界，不是人工能代的活）。"
)


def _stall_has_progress(tool_calls: list) -> bool:
    """本轮是否**实质推进**了写流程（有写/校验调用，或 interact 在等顾客回答）。

    供「确认却不动手」纠正使用：模型在顾客确认后仍反复查商品/地址（OR-024 首跑 9 轮）
    属于**空转** —— 没有 validate_input/order_create 也没有 interact，等于在原地打转。
    """
    names = {str((tc or {}).get("name") or "") for tc in (tool_calls or [])}
    return bool(names & {"validate_input", "order_create", "interact"})


def _registry_has_tool(registry, name: str) -> bool:
    """当前 skill 的工具子集里有没有这个工具（**事实**，不看 skill 名）。"""
    if registry is None:
        return False
    try:
        return registry.get_tool(name) is not None
    except Exception:
        return False


# ── 订单 → 物流链收口（issue #3799）──────────────────────────────────────────
# 实证（run 34873715194 的 OR-013 R2，SHA 30527b73）：
#   顾客「那用我最近一笔订单的订单号查一下物流」→ 模型 `order_query` 拿到真实订单号后
#   **把订单信息当交付物回复**，`logistics_track` 从未被调用（`tools=['order_query']`），
#   顾客要的轨迹一个字都没给 —— 推理链只走了一半。同 run 的 OR-005 一轮内走完同一链，
#   证明工具可用、链本身可行 ⇒ 这是**交付标准**缺失，不是能力缺失。
# 为什么在代码层收口：提示词/few-shot 只能提高概率（本次是「客户当场看」的场景），
# 而"顾客要物流 ⇒ 拿到订单号必须继续查轨迹"是**确定性**的交付标准。
# 判据**全部是事实**，不看顾客话术关键词（禁"含『物流』字样就调工具"式硬绑）：
#   ① 本轮**意图事实** = 物流查询（路由器已算出的 `intent_result.intent`）；
#   ② 本 skill 工具集里**真有** `logistics_track`（C 端用元元的 customer_logistics_track，不适用）；
#   ③ 本回合 `order_query` **成功返回过真实订单号**（`order_nos` 非空——没有订单号时
#      正确行为是问顾客要订单号，不是硬调）；
#   ④ 本回合**从未尝试**过 `logistics_track`（模型自己没走完这一步）。
# 命中后只做一件事：注入一条纠正并让循环继续（**有界一次**），**不代跑工具、不放宽任何守卫**。
_LOGISTICS_CHAIN_CORRECTIVE = (
    "【订单→物流链未完成】顾客要的是**物流轨迹**，而你本轮只查到订单号就准备结束回复。"
    "订单号只是查询轨迹的**入参**，不是交付物 —— 顾客要的「到哪了/什么状态」你还没给。"
    "本轮**立即**调用 logistics_track(order_id='{order_no}') 查这笔订单的轨迹，"
    "再把工具返回的状态/轨迹如实回复给顾客。"
    "若工具返回「该订单尚未发货」「未找到该订单」，**那也是**这条链的有效结果，照实说明即可"
    "（同样必须真调用工具，不要凭订单状态猜）。禁止只回复订单号或订单信息。"
)


def _logistics_chain_incomplete(
    *, intent_name: str, registry, order_nos: list, executed_tools) -> bool:
    """订单→物流链是否**只走了一半**（纯函数，判据全是事实；见上方说明）。"""
    return bool(
        intent_name == "logistics_track"
        and order_nos
        and "logistics_track" not in (executed_tools or set())
        and _registry_has_tool(registry, "logistics_track")
    )


def _logistics_chain_corrective(order_nos: list) -> str:
    """生成链收口纠正文本（用**工具刚返回的真实订单号**举例，不让模型自己猜）。"""
    return _LOGISTICS_CHAIN_CORRECTIVE.format(
        order_no=str(order_nos[0]) if order_nos else "")


def _order_write_tool_here(registry=None) -> bool:
    """本 skill 的工具子集里有没有下单写工具（= 模型**当下手里就有**下单能力）。

    旧实现写成 `_has_order_write_tool(skill_name, registry)`，硬编码
    `skill_name != "customer_order" → False` —— **skill 名字面量白名单**：
    会话被 choice 卡锁在别的 skill（#3477 C-A1 实测 `customer_product`）、B 端 `order`
    skill、或将来任何新 skill 只要含 `order_create`，都会被判成"没有能力"。
    四次复发（#3389→#3477→#3443→#3476）的共同机制就是这一类白名单。现在只读**工具注册表事实**。
    """
    return _registry_has_tool(registry, ORDER_WRITE_TOOL)


def _tool_registered_globally(name: str) -> bool:
    """**全局**工具注册表里有没有这个工具（= 产品/本部署是否具备该能力）。

    全局注册表是"能力事实"的权威来源；本 skill 的子集只是**本轮**可见的工具。
    """
    try:
        from app.tools.registry import get_tool_registry
        return get_tool_registry().get_tool(name) is not None
    except Exception:
        return False


def _order_capability_available(registry=None, *, order_in_progress: bool = False) -> bool:
    """下单能力是否**可达**（=「我做不了下单」这句话是否为**假**）。

    · 本 skill 直接可写（工具就在手上）→ 可达，与 skill 名无关；
    · 本 skill 子集没有该工具、但**顾客在办下单流程**且**全局具备该能力**
      → 会话会被锁回下单流程（`_relock_order_skill`），能力在**会话层可达**。

    两条缺一不可（防过度纠正）：只按全局判（生产里几乎恒真）会把越权/真不可达的诉求也放过；
    只按状态判会在工具根本没注册的环境里声称"你可以下单"。
    """
    if _order_write_tool_here(registry):
        return True
    return bool(order_in_progress) and _tool_registered_globally(ORDER_WRITE_TOOL)


# 图片写入能力**曾经**的工具名（issue #3931）。⚠️ #5318：自 #5247（PR #5285）起它已从
# **全部 B 端 skill 解绑**（#5303 只补回 `product_update` / `sku_update` 两条改价）
# ⇒ 生产里 `_product_image_capability_available` 恒为 False、「该入口不支持图片」就是**事实**。
# 本常量只用于**读这个事实**，绝不出现在任何注入给模型的话术里（点名 = 把模型推向
# 一次注定失败的调用）。
PRODUCT_IMAGE_WRITE_TOOL = "product_manage"


def _product_image_capability_available(registry=None) -> bool:
    """商品主图/图片更新能力是否**可达**（=「该入口不支持图片」这句话是否为**假**）。

    判据取自**工具注册表事实**（issue #3931）：当前 skill 的工具子集里有
    `product_manage` 且其参数 schema 含 images/detail_images —— 与
    `_order_capability_available` 同源的事实驱动（不写死 skill 名/工具清单）。

    ⚠️ #5318 后的用法 = **取反**：能力**确实不在手里**（今天恒真）才是注入纠正的前提，
    且纠正内容是「如实说明 + 引导商家到后台商品管理页面」，不是把模型推向已解绑的工具。
    """
    tool = None
    if registry is not None:
        try:
            tool = registry.get_tool(PRODUCT_IMAGE_WRITE_TOOL)
        except Exception:
            tool = None
    if tool is None:
        return False
    params = getattr(tool, "parameters", None)
    if not isinstance(params, dict):
        return False
    props = params.get("properties")
    if not isinstance(props, dict):
        return False
    return any(k in props for k in ("images", "detail_images"))


def _registry_has_confirm_write_tool(registry=None) -> bool:
    """本 skill 是否有「需确认的写工具」= **业务办理型流程**（此时转人工可能是在放弃流程）。

    取代旧的 `skill_name in ("customer_order", "customer_aftersales")` 白名单：
    判据取自**工具属性**（destructive / requires_confirmation，与确认门禁同源）。
    新增 skill 只要声明了写工具就**自动**纳入守卫，无需改任何名字清单
    （由 `tests/test_capability_denial_guard.py` 的 L0 不变式锁定）。
    """
    if registry is None:
        return False
    try:
        return any(getattr(t, "destructive", False) or getattr(t, "requires_confirmation", False)
                   for t in registry.get_all_tools())
    except Exception:
        return False


def _handoff_guard_applies(registry=None, *, order_in_progress: bool = False,
                           denial_reason_hit: str = "") -> bool:
    """转人工守卫是否适用（取代 `skill_name in ("customer_order", "customer_aftersales")`）。

    三类**事实/状态**，任一成立即适用 —— 与 skill 名字面量无关：
      · 理由本身就是能力误宣（`denial_reason_hit` 非空）：任何 skill 都拦（#3389，本已跨 skill）；
      · 顾客在办下单（`order_in_progress`）：跨 skill 拦（#3477 C-A1，会话被卡在 customer_product）；
      · 本 skill 有需确认写工具（业务办理型流程）：白名单的**事实等价物**（CH-012 依赖此支）。
    """
    return bool(denial_reason_hit) or bool(order_in_progress) or \
        _registry_has_confirm_write_tool(registry)


def _capability_denial_reason(args: dict) -> str:
    """转人工的 reason/summary 是否是「AI 自己做不到」的能力误宣；返回命中片段或空串。

    复用**同一个**语义归一判据（`capability_denial_text_hit`，单一事实源，避免
    agent 侧两套词表漂移），并额外认「协助下单」这类**回避式**措辞（issue #3477：
    理由写"顾客需要协助下单"就是把本该自己做的下单推给人工）。
    只认明确的**自我能力否定**措辞（顾客显式诉求/情绪/正常业务理由都不在此列，
    因为"非自我主体"的否定会被 `_self_scoped_clause` 排除），避免把
    "顾客要求人工核价"这类正确转人工拦成故障。

    ⚠️ `reason` 与 `summary` **分别**判定（不拼接）：两者是模型写的两个独立字段，
    拼在一起会让前一个字段的主体（如「顾客需协助」）串到后一个字段的否定上，
    把「无法代为提交订单」误判成"非自我主体"而漏配（既有测试
    `TestCapabilityDenialInHandoffReason::test_summary_field_scanned` 即此形）。
    """
    for field in ((args or {}).get("reason"), (args or {}).get("summary")):
        hit = capability_denial_text_hit(str(field or ""), include_assist=True)
        if hit:
            return hit
    return ""
