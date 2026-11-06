# case_ids: MC-340
"""口径卡的 PII / 报价闸门（issue #8175 边界；继承 #2815 并加严）。

三条口径各自有红证：
1. **复用**：手机号 / 邮箱用的是 `app/utils/pii_mask.py` 的**同一批对象**（`is` 比较）——
   在自己的模块里抄一份就会漂移（一处加边界、另一处没加）；
2. **加严**：中文 PII 词根（联系人 / 地址 / 身份证 / 座机 / 微信）与**报价**（`¥128` / `128 元` /
   报价·单价·折扣）—— #2815 的词根表是英文的（LLM 生成的 key），口径卡的正解是中文自由文本；
3. **fail-closed**：判不了 ⇒ **不许过**（返回非空清单），不是返回「干净」。
"""

from app.playbook import redact
from app.utils import pii_mask


def test_phone_and_email_regexes_are_reused_not_copied():
    """复用判据：闸门用的是 `pii_mask` 的**同一批对象**（抄一份就会漂移）。"""
    assert redact.PHONE_RE is pii_mask.PHONE_RE
    assert redact.EMAIL_RE is pii_mask.EMAIL_RE
    assert redact.problems("打 13800138000") == ["手机号"]
    assert redact.problems("发到 a@b.co") == ["邮箱"]


def test_price_forms_are_all_rejected():
    """报价的三种形态（金额+单位 / 货币符号 / 价格词根）都要挡。"""
    for text in ("整卷报价 128 元", "整卷 ¥128", "整卷按单价走", "整卷打九折"):
        assert "报价/金额" in redact.problems(text), text


def test_chinese_pii_word_roots_are_rejected():
    """中文 PII 词根（#2815 的英文词根覆盖不到的那一类）。"""
    for text in ("联系人填店主", "地址按客户填的走", "身份证核对", "座机 010-12345678", "加微信 12345678"):
        assert redact.problems(text), text


def test_clean_correction_passes():
    """反向对照：普通口径不带隐私 / 报价 ⇒ 干净（否则整个管道只会产 0 条）。"""
    assert redact.problems("不对，我们按整卷算") == []
    assert redact.is_clean("不对，我们按整卷算")


def test_judgement_failure_is_fail_closed(monkeypatch):
    """判不了 ⇒ **不许过**（返回非空清单），不是静默当「干净」。"""
    def boom(_text):
        raise RuntimeError("正则炸了")

    monkeypatch.setattr(redact, "_hits", boom)
    assert redact.problems("任何文本") == ["拦截判定失败"]
