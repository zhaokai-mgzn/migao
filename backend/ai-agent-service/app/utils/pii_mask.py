"""面向顾客文本的 PII 脱敏（issue #3379）。

为什么单列一个模块，而不是直接用 `LogSanitizer.mask_text`：
`mask_text` 是**日志**用的，手机号正则是 `1[3-9]\\d{9}`（无边界）——
用它处理**给顾客看的文本**会把订单号里的连续数字也啃掉：实测
`订单号 20260913027050006` 中的 `13027050006` 正好 11 位且形如手机号
→ 被脱敏成 `2026 130****0006`，**订单号被毁**（顾客拿不到单号）。

故本模块的手机号正则加**数字边界**（`(?<!\\d)…(?!\\d)`）：只脱敏**独立**的手机号，
不碰订单号/验证码/长数字串。邮箱同理（本地部分可能含点号，整体匹配即可）。

用途：C 端（顾客）可见文本的输出层收敛 —— 不改工具返回、不改工具参数，
避免"写入路径拿到脱敏号码"（`order_create` 必须拿真号码）。
"""
import re

# 独立手机号（中国大陆）：前后不能再有数字，避免吃掉订单号里的数字片段
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 邮箱：本地部分/域名
_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def mask_phone(match: "re.Match[str]") -> str:
    num = match.group()
    return num[:3] + "****" + num[-4:]


def mask_pii(text: str) -> str:
    """脱敏独立手机号与邮箱；订单号/验证码等数字串保持不变。"""
    if not text:
        return text
    out = _PHONE.sub(mask_phone, str(text))
    out = _EMAIL.sub(lambda m: m.group()[:2] + "***@" + m.group().split("@")[-1], out)
    return out
