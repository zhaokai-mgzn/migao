"""口径卡的**读面唯一入口**（issue #8175）。

## 为什么这里**一条缓存都没有**（判据 5：退役立即生效）

「退役之后还能被检索到」只有一种成因：把读结果粘在了进程内的某个容器里
（模块级 dict / `lru_cache` / 请求外的作用域单例）。退役是一次**库内状态变更**，
进程无从感知 —— 所以本模块的做法是**不缓存**：每个 B 端回合现取一次。

代价是每回合多一条 SQL（`(tenant_id, state)` 上有索引 ⇒ 走索引扫描）；
收益是「退役」与「可见性」之间**没有时间窗**，也不需要任何失效广播。
真要缓存时，必须先有一条会红的判据（同一进程内 retire 后立刻读不到），
否则「加了缓存」这件事本身没有任何东西看得见。

## 租户隔离是**两层**，不是一层

SQL 里 `WHERE tenant_id = :tenant_id` 是第一层（正确的做法）；
`list_active` 在应用层**再滤一次**（`tenant_id` / `state` / `scope`）是第二层。
第二层不是多余的：它把「SQL 写错一个字」「有人换了一个不带租户条件的查询」
这类**静默越权**变成「读不到」（fail-closed），而不是「读到别人的口径」——
口径会直接进 system prompt，越权即等于把别家的经营规则灌进本家的对话。
"""

import json
from typing import Any, Dict, List, Optional

from loguru import logger

#: 唯一进任何出口的状态（判据 1 / 5）
STATE_ACTIVE = "active"
STATE_DRAFT = "draft"
STATE_RETIRED = "retired"
ALL_STATES = (STATE_DRAFT, STATE_ACTIVE, STATE_RETIRED)

SCOPE_TENANT = "tenant"
SCOPE_ROLE = "role"
ALL_SCOPES = (SCOPE_TENANT, SCOPE_ROLE)

#: 列顺序与 `_row_to_playbook` **逐位对应**（改一处必须同改另一处）
_COLUMNS = (
    "id",
    "tenant_id",
    "scope",
    "scope_role",
    "trigger_json",
    "correct_text",
    "counter_json",
    "source_session_id",
    "source_turn",
    "hits",
    "state",
    # P2：冲突消解（`conflict_key`）与生命周期（衰减/退役）的唯一输入面
    "conflict_key",
    "activated_at",
    "created_at",
    "last_hit_at",
)

_SELECT_ACTIVE_SQL = """
SELECT {columns}
FROM playbooks
WHERE tenant_id = :tenant_id AND state = 'active'
ORDER BY created_at ASC, id ASC
LIMIT 200
""".format(
    columns=", ".join(_COLUMNS)
)

#: 命中计数：**只加不减** + 显式租户列 + 与 `last_hit_at` 同批写（衰减/退役的数据面）
_RECORD_HITS_SQL = """
UPDATE playbooks
SET hits = hits + 1, last_hit_at = NOW(), updated_at = NOW()
WHERE tenant_id = :tenant_id AND id IN :ids
"""


def _parse_condition(raw: Any) -> Any:
    """把库里的条件文本解析成条件对象。

    **解析失败返回 None**（而不是抛）：`None` 不是可执行条件 ⇒ 该卡在所有出口被排除
    （fail-closed）。绝不把「解析不了的东西」当成「无条件生效」。
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _row_to_playbook(row: Any) -> Dict[str, Any]:
    values = list(row)
    raw = dict(zip(_COLUMNS, values))
    return {
        "id": raw["id"],
        "tenant_id": raw["tenant_id"],
        "scope": raw["scope"],
        "scope_role": raw["scope_role"],
        "trigger": _parse_condition(raw["trigger_json"]),
        "correct": raw["correct_text"],
        "counter": _parse_condition(raw["counter_json"]),
        "source": {
            "session_id": raw["source_session_id"],
            "turn": raw["source_turn"],
        },
        "hits": raw["hits"],
        "state": raw["state"],
        # 冲突消解用：P1 落库面打的标记；读面**不单独信任它**（见 identity.group_key）
        "conflict_key": raw["conflict_key"],
        # 衰减 / 退役的时间锚点（`last_hit_at` > `activated_at` > `created_at`）
        "activated_at": raw["activated_at"],
        "created_at": raw["created_at"],
        "last_hit_at": raw["last_hit_at"],
    }


class PlaybookStore:
    """读口径卡。**无缓存**（见模块 docstring）。"""

    def __init__(self, db_session: Any = None):
        self._db = db_session

    async def _get_session(self) -> Any:
        if self._db is not None:
            return self._db
        from app.utils.database import AsyncSessionLocal

        return AsyncSessionLocal()

    async def list_active(
        self, tenant_id: int, role: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """取本租户**已审核生效**的口径卡（含适用范围为「全企业」的与命中本岗位的）。

        Args:
            tenant_id: 租户 ID（**必填**；为 0 / 空 ⇒ 直接空列表，绝不查全表）
            role: 当前会话人的岗位（`scope='role'` 的卡按它过滤；None ⇒ 只取全企业卡）
        """
        if not tenant_id:
            logger.warning("[playbook] list_active 缺少 tenant_id ⇒ 空列表（fail-closed）")
            return []
        async with await self._get_session() as db:
            from sqlalchemy import text

            result = await db.execute(text(_SELECT_ACTIVE_SQL), {"tenant_id": tenant_id})
            rows = result.fetchall()
        playbooks: List[Dict[str, Any]] = []
        for row in rows:
            pb = _row_to_playbook(row)
            # 第二层过滤（fail-closed）：SQL 层之外再守一次，见模块 docstring
            if pb["tenant_id"] != tenant_id:
                continue
            if pb["state"] != STATE_ACTIVE:
                continue
            if not self._scope_applies(pb, role):
                continue
            playbooks.append(pb)
        if playbooks:
            logger.debug(
                f"[playbook] loaded {len(playbooks)} active | tenant={tenant_id} role={role or '-'}"
            )
        return playbooks

    async def record_hits(self, tenant_id: int, playbook_ids: Optional[List[Any]]) -> int:
        """给**本轮真的命中**的卡 +1 次命中（`hits` / `last_hit_at` 同批写）。

        - 空清单 / 无租户 ⇒ 一条 SQL 都不发（别把「没命中」写成一次空更新）；
        - 租户条件**写在 SQL 里**：一次 B 端回合不许给别家的卡加命中；
        - `hits = hits + 1` 而不是 `hits = 1`：这是累计量，覆盖会把它抹平。
        """
        ids = [str(pid) for pid in (playbook_ids or []) if pid]
        if not tenant_id or not ids:
            return 0
        from sqlalchemy import bindparam, text

        stmt = text(_RECORD_HITS_SQL).bindparams(bindparam("ids", expanding=True))
        async with await self._get_session() as db:
            await db.execute(stmt, {"tenant_id": int(tenant_id), "ids": ids})
            await db.commit()
        return len(ids)

    @staticmethod
    def _scope_applies(playbook: Dict[str, Any], role: Optional[str]) -> bool:
        scope = playbook.get("scope")
        if scope == SCOPE_TENANT:
            return True
        if scope == SCOPE_ROLE:
            # 不知道岗位 ⇒ 只按全企业口径走（**不猜**：猜错就是把某岗位的规则发给所有人）
            return bool(role) and playbook.get("scope_role") == role
        return False  # 未知 scope ⇒ 不用（不是「当 tenant 用」）
