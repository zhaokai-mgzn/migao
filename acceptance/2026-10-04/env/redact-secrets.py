#!/usr/bin/env python3
"""按值把「我们自己造的、但形似密钥」的东西从验收产物里脱敏掉（issue #6303 / 方法笔记 N9·N10）。

为什么需要（两轮血债）：
  ① 只按**结构化字段**（`"key": "…"`）脱敏 ⇒ 自由文本里的副本漏网（`幂等键 = X-Client-Request-Id: <值>`）；
  ② 只对**当时已知的值**脱敏 ⇒ 下一次跑探针又会**新造**一批键/JWT 落盘 ⇒ 提交后仍被 gitleaks 拦下（本文件因此诞生）。
⇒ 所以这里按**形态**扫全树：JWT、幂等键、`X-Client-Request-Id` 值、Authorization 头，一律按值做**确定性**占位
   （同值→同占位符，保留"同键/异键"的可读关系；不同值→不同占位符）。

用法：
  python3 acceptance/2026-10-04/env/redact-secrets.py            # 就地脱敏（幂等：已脱敏的不再动）
  python3 acceptance/2026-10-04/env/redact-secrets.py --check    # 只检查（有残留 ⇒ 退出码 1，供载体自检调用）
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # = acceptance/2026-10-04
EXTS = {'.json', '.md', '.log', '.txt', '.sh', '.mjs', '.xml', '.html'}
SKIP_NAMES = {'redact-secrets.py'}

# ── 形态（顺序有意义：JWT 先于通用长串）────────────────────────────────────────
PATTERNS = [
    # JWT：三段 base64url，点分隔（我们自己的会话 token）
    ('jwt', re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}')),
    # 幂等键：探针自造形态 `<前缀>-<8位日期><时分秒>-<随机>`
    ('idem', re.compile(r'\brace-sweep-key(?:-[a-z]+)?-\d{14}-[A-Za-z0-9]{4,}\b')),
    ('idem', re.compile(r'\blb-mut[A-Za-z0-9]{4,}-as\b')),
    ('idem', re.compile(r'\bprobe-[A-Za-z0-9]{4,}-\d{14}-[A-Za-z0-9]{4,}\b')),
    # 显式字段：任何 "key"/"clientRequestId"/"X-Client-Request-Id" 后面跟的长随机串
    ('idem', re.compile(r'("(?:key|clientRequestId|client_request_id)"\s*:\s*")([A-Za-z0-9_\-]{12,})(")')),
    ('idem', re.compile(r'(X-Client-Request-Id["\']?\s*[:=]\s*["\']?)([A-Za-z0-9_\-]{12,})')),
    # Authorization: Bearer <token>
    ('bearer', re.compile(r'(\bBearer\s+)([A-Za-z0-9._\-]{16,})')),
]


def placeholder(kind: str, value: str) -> str:
    h = hashlib.sha1(value.encode('utf-8')).hexdigest()[:6]
    tag = {'jwt': 'JWT', 'idem': 'IDEM-KEY', 'bearer': 'TOKEN'}.get(kind, 'SECRET')
    return f'<{tag}-{h}>'


def redact_text(text: str) -> tuple[str, int]:
    hits = 0
    for kind, rx in PATTERNS:
        if rx.groups >= 3:  # 带前后缀的字段形态：只换中间那组
            def sub3(m, kind=kind):
                nonlocal hits
                if m.group(2).startswith('<'):
                    return m.group(0)
                hits += 1
                return m.group(1) + placeholder(kind, m.group(2)) + m.group(3)
            text = rx.sub(sub3, text)
        elif rx.groups == 2:
            def sub2(m, kind=kind):
                nonlocal hits
                if m.group(2).startswith('<'):
                    return m.group(0)
                hits += 1
                return m.group(1) + placeholder(kind, m.group(2))
            text = rx.sub(sub2, text)
        else:
            def sub1(m, kind=kind):
                nonlocal hits
                hits += 1
                return placeholder(kind, m.group(0))
            text = rx.sub(sub1, text)
    return text, hits


def main() -> int:
    check_only = '--check' in sys.argv
    files = 0
    total = 0
    bad: list[str] = []
    for f in sorted(ROOT.rglob('*')):
        if not f.is_file() or f.suffix.lower() not in EXTS or f.name in SKIP_NAMES:
            continue
        try:
            text = f.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        new, hits = redact_text(text)
        if hits:
            files += 1
            total += hits
            rel = f.relative_to(ROOT.parent)
            bad.append(f'{rel} ({hits} 处)')
            if not check_only:
                f.write_text(new, encoding='utf-8')
    mode = '检查' if check_only else '脱敏'
    print(f'{"❌" if (check_only and total) else "✅"} {mode}：{files} 文件 / {total} 处'
          + ('（有明文凭据形态残留 ⇒ 判红）' if check_only and total else ''))
    for b in bad[:12]:
        print('   ·', b)
    return 1 if (check_only and total) else 0


if __name__ == '__main__':
    sys.exit(main())
