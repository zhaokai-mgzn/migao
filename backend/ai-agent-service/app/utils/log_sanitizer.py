# app/utils/log_sanitizer.py
import re


class LogSanitizer:
    """日志敏感信息过滤工具"""

    # 手机号（中国大陆）
    _PHONE_PATTERN = re.compile(r'1[3-9]\d{9}')
    # 邮箱
    _EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    # 敏感参数名
    SENSITIVE_KEYS = frozenset({
        'password', 'api_key', 'apikey', 'api-key', 'token', 'secret',
        'access_key', 'secret_key', 'authorization', 'credential',
    })

    @staticmethod
    def mask_phone(phone: str) -> str:
        """手机号脱敏：保留前3后4"""
        if phone and len(phone) >= 7:
            return phone[:3] + '****' + phone[-4:]
        return '****'

    @staticmethod
    def mask_text(text: str) -> str:
        """对文本中的敏感信息进行脱敏"""
        # 手机号脱敏
        text = LogSanitizer._PHONE_PATTERN.sub(
            lambda m: m.group()[:3] + '****' + m.group()[-4:], text
        )
        # 邮箱脱敏
        text = LogSanitizer._EMAIL_PATTERN.sub(
            lambda m: m.group()[:2] + '***@' + m.group().split('@')[1], text
        )
        return text

    @staticmethod
    def filter_params(params: dict) -> dict:
        """过滤字典中的敏感参数值"""
        if not params:
            return params
        filtered = {}
        for k, v in params.items():
            if k.lower() in LogSanitizer.SENSITIVE_KEYS:
                filtered[k] = '***'
            elif isinstance(v, str):
                filtered[k] = LogSanitizer.mask_text(v)
            else:
                filtered[k] = v
        return filtered
