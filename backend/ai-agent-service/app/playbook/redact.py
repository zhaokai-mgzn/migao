"""口径卡候选的 **PII / 报价闸门**（issue #8175 边界；继承 #2815 并**加严**）。

## 为什么这里要再做一次（P1a 的抽取侧已经拦过一次）

`scripts/distill_agent_sessions.py` 的拦截在**抽取侧**，它回答的是「这段会话要不要抽」；
本模块在**落库侧**，回答的是「这一行要不要进口径卡」。两者不是重复：

- 落库侧的输入是**一个 JSON 文件**（人可以改、别的工具可以生成、旧版本可以产出），
  它**不受**抽取侧代码约束。只信上游 ⇒ 一份被改过的候选文件就能把手机号写进口径卡，
  而口径卡是**全企业进 system prompt** 的工件，污染面比一条记忆大得多；
- 口径卡比记忆**更严**：不能「脱敏后照发」—— 含隐私或具体报价的句子本身就是**不可复用**的
  （每次报价、每个地址都是「一单一议」），所以这里**整条拒绝**，不是打码。

## 复用（不复制第二份正则）

手机号 / 邮箱**直接复用** `app/utils/pii_mask.py` 的 `PHONE_RE` / `EMAIL_RE`
（#3379 的边界口径：`(?<!\\d)…(?!\\d)`，不啃订单号）。

## 加严（相对 #2815 的「英文 key 词根 + 值手机号/邮箱」）

1. 身份证（18 位）、座机、微信号/QQ 号；
2. 中文 PII 词根（手机号 / 电话 / 地址 / 收货人 / 联系人 / 微信 / 银行卡…）——
   #2815 的词根表是**英文**的（LLM 生成的 key），口径卡的正解是**中文自由文本**，需要中文词根；
3. **报价**（金额 + 货币/单位、价格词根）—— 报价一单一议，不许沉淀成全企业口径
   （issue #8175「PII / 报价不得进口径卡」）。

退出码 / 返回口径：`problems()` 返回**问题清单**（空 = 干净），`is_clean()` 是它的布尔壳。
两个函数都**永不抛异常**（调用点在落库路径上，抛出去会把「拦截」变成「整批失败」）。
"""

import re
from typing import Any, List

from app.utils.pii_mask import EMAIL_RE, PHONE_RE

#: 身份证（18 位，末位可为 X）—— 必须在手机号之外单独判：18 位不会被 11 位手机号正则吞掉
ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
#: 座机（区号 + 7~8 位，可带连字符）
LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")
#: 微信号 / QQ 号（带前缀才算：裸数字串可能是尺寸、米数、货号）
IM_RE = re.compile(r"(?:qq|微信|wechat|vx|v信)\s*(?:号)?\s*[:：]?\s*[1-9]\d{4,11}", re.IGNORECASE)

#: 中文 PII 词根（#2815 的英文词根表覆盖不到中文自由文本）
PII_ROOTS = (
    "手机号",
    "手机号码",
    "电话号码",
    "联系电话",
    "联系方式",
    "身份证",
    "收货地址",
    "详细地址",
    "收货人",
    "联系人",
    "银行卡",
    "开户行",
    "支付宝",
)

#: 报价形态（金额 + 货币/单位）与价格词根 —— 都算「不可沉淀的具体成交条件」
PRICE_RES = (
    re.compile(r"[¥￥]\s*\d+(?:\.\d+)?"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:元|块钱|块)(?:\s*[/每]\s*[米件套张平]|\s*(?:一米|一件|一套))?"),
    re.compile(r"\d+(?:\.\d+)?\s*万"),
    re.compile(r"(?:报价|价格|单价|总价|底价|成本价|折扣|优惠|返点|让利|毛利率|毛利)"),
)


def _hits(text: str) -> List[str]:
    """→ 命中的问题类别清单（去重、固定顺序 ⇒ 输出可逐字节复算）。"""
    problems: List[str] = []
    if PHONE_RE.search(text):
        problems.append("手机号")
    if EMAIL_RE.search(text):
        problems.append("邮箱")
    if ID_CARD_RE.search(text):
        problems.append("身份证")
    if LANDLINE_RE.search(text):
        problems.append("座机")
    if IM_RE.search(text):
        problems.append("微信号/QQ")
    for root in PII_ROOTS:
        if root in text:
            problems.append(f"PII 词根「{root}」")
            break
    for pattern in PRICE_RES:
        if pattern.search(text):
            problems.append("报价/金额")
            break
    return problems


def problems(text: Any) -> List[str]:
    """候选正文的拦截清单（空 = 可以进口径卡）。永不抛。"""
    if text is None:
        return []
    try:
        return _hits(str(text))
    except Exception:  # noqa: BLE001 — 落库路径上不许把「拦截」变成「整批崩」
        # 判不了就不许过：fail-closed 的返回不是空清单
        return ["拦截判定失败"]


def is_clean(text: Any) -> bool:
    """`problems(text)` 为空 ⇔ True。"""
    return not problems(text)
