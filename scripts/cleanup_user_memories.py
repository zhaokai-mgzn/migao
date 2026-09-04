#!/usr/bin/env python3
"""
user_memories 存量清理脚本（C 端长期记忆专项，issue #2815）

背景：user_memories 表现有 733 行（20 用户）中：
- 13.1%（96 行）含 PII（key 变体绕过滤 + context 明文手机号/地址）——合规 P0
- 84.7%（621 行）为 dev/test 用户噪音（dev_user / user_admin_001 / user_superadmin / 评测账号）
- 44+ 行为会话态一次性数据错配（order_count / pending / intent / color_removed 等）

清理规则（幂等）：
1. 先整表备份到 user_memories_bak_YYYYMMDD（同库新表，可回滚）
2. 删除 dev/test 用户行（白名单 user_id）
3. 删除 PII 行：key 词根匹配（phone/mobile/address/name/contact/wechat/id_card/idcard/qr）
   或 value 含手机号/邮箱正则
4. 删除会话态一次性 key 行（order_count/pending/intent/status/total/removed 等词根，白名单外）
5. 剩余行回填 agent_type='xiaobu'（存量默认归属 C 端；B 端本期不落库）

用法（在 migao 仓库根目录）：
  ./scripts/cleanup_user_memories.py            # dry-run：只统计不删除
  ./scripts/cleanup_user_memories.py --apply    # 执行：备份 + 删除 + 回填

环境：DATABASE_URL 取自 backend/ai-agent-service/.env（postgresql+asyncpg://）
"""
import argparse
import asyncio
import os
import re
import sys
from datetime import datetime

import asyncpg

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_REPO_ROOT, "backend", "ai-agent-service", ".env")


def _load_db_url() -> str:
    if os.environ.get("DATABASE_URL"):
        url = os.environ["DATABASE_URL"]
    else:
        url = ""
        if os.path.exists(_ENV_PATH):
            for line in open(_ENV_PATH):
                if line.startswith("DATABASE_URL="):
                    url = line.strip().split("=", 1)[1].strip()
    if not url:
        sys.exit("DATABASE_URL 未找到（backend/ai-agent-service/.env 或环境变量）")
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ── 清理规则（与 memory-system-assessment.md §3.2 一致）──

# dev/test 用户（开发与评测账号，非真实消费者）
DEV_TEST_USERS = frozenset({
    "dev_user", "user_admin_001", "user_superadmin",
    "cust_deepl_eval_01", "cust_reg_001", "cust_reg_002",
})

# PII key 词根（LLM 自由生成 key 的变体拦截，覆盖 40+ 变体）
_PII_KEY_PATTERN = re.compile(
    r"phone|mobile|address|email|name|contact|wechat|id_?card|idcard|qq|"
    r"province|city|district|detail_info|recipient|deliver|postal|zip",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# 会话态一次性 key 词根（不应进长期记忆；curtain_style/color/budget 等偏好词根白名单外）
_TRANSIENT_KEY_PATTERN = re.compile(
    r"intent|pending|status|count|total|amount|subtotal|ticket|removed|"
    r"logistics|duplicate|attempt|format|correction|mismatch|update|"
    r"change|request|note|reason|order_id|order_no|order_number|order_ids",
    re.IGNORECASE,
)
# 明确保留的偏好词根（不误删）
_KEEP_KEY_PATTERN = re.compile(
    r"style|color|shade|budget|price_target|window_size|window_width|window_height|"
    r"curtain_length|fold|install|processing_style|purchase_unit|repurchase",
    re.IGNORECASE,
)


def _is_pii(row) -> bool:
    key = str(row.get("key", "") or "")
    value = str(row.get("value", "") or "")
    context = str(row.get("context", "") or "")
    if _PII_KEY_PATTERN.search(key):
        return True
    if _PHONE_RE.search(value) or _EMAIL_RE.search(value):
        return True
    if _PHONE_RE.search(context):  # context 明文手机号/邮箱（extractor.py 曾写原始消息）
        return True
    return False


def _is_transient(row) -> bool:
    key = str(row.get("key", "") or "")
    if _KEEP_KEY_PATTERN.search(key):
        return False
    return bool(_TRANSIENT_KEY_PATTERN.search(key))


async def main(apply: bool) -> None:
    conn = await asyncpg.connect(_load_db_url())
    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM user_memories")
        rows = await conn.fetch("SELECT id, user_id, key, value, context FROM user_memories")
        print(f"存量总数: {total}")

        dev = [r for r in rows if r["user_id"] in DEV_TEST_USERS]
        pii = [r for r in rows if not r["user_id"] in DEV_TEST_USERS and _is_pii(dict(r))]
        transient = [
            r for r in rows
            if not r["user_id"] in DEV_TEST_USERS and not _is_pii(dict(r))
            and _is_transient(dict(r))
        ]
        keep = [r for r in rows if r not in dev and r not in pii and r not in transient]
        print(f"  dev/test 待删: {len(dev)}")
        print(f"  PII 待删: {len(pii)}")
        print(f"  会话态待删: {len(transient)}")
        print(f"  保留（回填 xiaobu）: {len(keep)}")
        if not apply:
            print("\n[dry-run] 未执行任何修改。加 --apply 执行（会先备份到 user_memories_bak_*）")
            return

        # 1. 备份
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = f"user_memories_bak_{stamp}"
        await conn.execute(f"CREATE TABLE {bak} AS SELECT * FROM user_memories")
        print(f"[apply] 已备份 -> {bak}")

        # 2. 删除（按 id 精确删，幂等）
        delete_ids = [r["id"] for r in (dev + pii + transient)]
        if delete_ids:
            # 分批（PG 参数上限 ~32767）
            for i in range(0, len(delete_ids), 5000):
                chunk = delete_ids[i:i + 5000]
                await conn.execute(
                    "DELETE FROM user_memories WHERE id = ANY($1::varchar[])",
                    chunk,
                )
            print(f"[apply] 已删除 {len(delete_ids)} 行")
        else:
            print("[apply] 无待删行")

        # 3. 回填 agent_type（存量默认 C 端）
        await conn.execute("UPDATE user_memories SET agent_type = 'xiaobu'")
        print("[apply] 已回填 agent_type='xiaobu'")

        after = await conn.fetchval("SELECT COUNT(*) FROM user_memories")
        print(f"[apply] 清理后总数: {after}（原 {total}）")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="user_memories 存量清理（dry-run 默认）")
    parser.add_argument("--apply", action="store_true", help="执行清理（含备份）")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
