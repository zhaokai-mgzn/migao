"""
AI 智能客服系统 - 第三方物流轨迹查询缓存层

被缓存的事实（issue #6185）：`LogisticsTrackTool._call_logistics_api()`
（阿里云市场 `wuliu.market.alicloudapi.com/kdi`）**按次计费**。同一运单号会在短期内被
反复查询：

- 顾客追问「我的快递到哪了」/ 会话重放 / 多轮澄清；
- C 端「我的物流」是**逐单扇出**（每个在途订单一次第三方调用）。

⇒ 同一个运单号在几分钟内会**重复计费**，而轨迹本身一天只更新几次。

TTL 口径（用户 2026-10-03 裁定：分档，每档在原建议值上 +1 小时）：

| 轨迹状态 | TTL | 理由 |
|---|---|---|
| 已签收 / 已退回（终态） | 90 分钟 | 终态轨迹不再变化，长 TTL 无时效损失 |
| 运输中 / 派送中 | 65 分钟 | 在途仍在更新，取中档 |
| 异常 / 未知（兜底） | 60 分钟 | 兜底档 |
| API status=205（计费但无信息） | 120 秒 | 「刚发货查不到」会短时间内反复重查 |

**不缓存**：调用失败（超时 / 异常 / 其它非 0 状态）—— 不把故障状态钉住。

**本模块同时是「第三方响应 → 标准格式」解析与「轨迹 → 状态」推断的唯一实现**：
实时查询路径（`LogisticsTrackTool._transform_api_response` / `_infer_status_from_traces`）
只是薄转发。理由：两条路径各写一份解析，一旦漂移就会出现「实时查是已签收 / 命中缓存是在途」，
而 TTL 分档正建立在状态之上 ⇒ 分歧会静默改变缓存时长。

设计原则（与 `app/core/admin_api_cache.py` 同口径）：
- 任何 Redis 异常都不抛给上游，缓存层不能拖垮主流程；
- 命中即返回；未命中由调用方走第三方 API；
- 多租户隔离：key 带 tenant_id 前缀；
- 手机尾号（顺丰/中通/申通查询必需）以摘要入 key，不落明文。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from loguru import logger

import redis.asyncio as redis_async

from app.utils import redis_client as redis_module


KEY_PREFIX = "cache:logistics_trace:"

# ── 共享常量（Tool 层 re-export，见 app/tools/logistics_track.py）──

# 内部状态 → 中文文本
STATUS_TEXT_MAP = {
    "pending": "待发货",
    "picked": "已揽收",
    "in_transit": "运输中",
    "out_for_delivery": "派送中",
    "delivered": "已签收",
    "exception": "异常",
    "returned": "已退回",
}

# 中文物流状态关键词 → 内部状态
CN_STATUS_MAP = {
    "签收": "delivered",
    "已签收": "delivered",
    "签收人": "delivered",   # 如「送货上门，签收人：家门口」
    "送达": "delivered",     # 如「快件已送达（上门服务）」
    "派送成功": "delivered",  # 如「您的快件已派送成功（家门口）」
    "派送": "out_for_delivery",
    "派件": "out_for_delivery",
    "正在派送": "out_for_delivery",
    "揽收": "picked",
    "已揽收": "picked",
    "揽件": "picked",
    "退回": "returned",
    "退件": "returned",
    "异常": "exception",
    "问题件": "exception",
    "到达": "in_transit",
    "在途": "in_transit",
    "发往": "in_transit",
    "运输": "in_transit",
    "转运": "in_transit",
}

# 快递公司编码(大写) → 中文名称
COMPANY_NAME_MAP = {
    "SF": "顺丰速运",
    "SFEXPRESS": "顺丰速运",
    "YTO": "圆通速递",
    "YUNDA": "韵达快递",
    "STO": "申通快递",
    "ZTO": "中通快递",
    "EMS": "EMS",
    "JD": "京东物流",
    "JT": "极兔速递",
    "JITU": "极兔速递",  # 阿里云市场 kdi API 实际返回的极兔 code（JT 不被识别）
    "DB": "德邦快递",
    "BEST": "百世快递",
    "TTKDEX": "天天快递",
    "YOUZHENG": "中国邮政",
    "ANE": "安能物流",
    "ZJS": "宅急送",
    "DPEX": "DPEX",
    "FEDEX": "FedEx",
    "UPS": "UPS",
    "DHL": "DHL",
    "USPS": "USPS",
}

TTL_TERMINAL = 5400    # 90 分钟：已签收 / 已退回（终态轨迹不再变化）
TTL_TRANSIT = 3900     # 65 分钟：运输中 / 派送中 / 异常 / 未知（兜底）
TTL_NO_INFO = 120      # 2 分钟：API status=205（计费但无信息）

_TERMINAL_STATUSES = frozenset({"delivered", "returned"})


def ttl_for_status(status: Optional[str]) -> int:
    """按轨迹状态给出缓存 TTL（秒）。

    终态（已签收 / 已退回）走长 TTL；其余（在途 / 异常 / 未知）走兜底档。
    """
    if status in _TERMINAL_STATUSES:
        return TTL_TERMINAL
    return TTL_TRANSIT


def infer_status_from_traces(traces: list) -> str:
    """从物流轨迹推断当前状态（最新在前，最多看 3 条）

    轨迹为空时**不得**推断成终态 —— 刚发货的运单会被缓存 90 分钟。
    """
    if not traces:
        return "in_transit"
    for trace in traces[:3]:
        content = trace.get("content", "")
        for keyword, status in CN_STATUS_MAP.items():
            if keyword in content:
                return status
    return "in_transit"


def _hash_phone(phone_tail: Optional[str]) -> str:
    """手机尾号 → 短摘要（不落明文）"""
    if not phone_tail:
        return "none"
    return hashlib.sha256(str(phone_tail).encode("utf-8")).hexdigest()[:16]


def make_logistics_track_key(
    tenant_id: int,
    tracking_number: Optional[str],
    company_code: Optional[str],
    phone_tail: Optional[str],
) -> str:
    """缓存 key：租户 + 运单号 + 快递公司编码 + 手机尾号摘要

    手机尾号参与 key：顺丰/中通/申通需 `单号:尾号4位` 才能查到全量轨迹
    ⇒ 不同尾号可能得到不同结果，不能共用同一个缓存条目。
    """
    return (
        f"{KEY_PREFIX}{tenant_id}:{tracking_number or ''}:"
        f"{company_code or ''}:{_hash_phone(phone_tail)}"
    )


class LogisticsTraceCache:
    """第三方物流轨迹响应缓存（基于 Redis）

    - `get` 命中 ⇒ 返回标准格式（internal status）的轨迹数据，调用方**跳过**第三方 API；
    - `set` 只应由**成功**（或 status=205）的第三方响应调用 —— 失败不缓存。
    """

    def _get_client(self) -> Optional[redis_async.Redis]:
        """从全局连接池借一个 Redis 客户端；未初始化时返回 None。"""
        pool = redis_module.redis_pool
        if pool is None:
            return None
        return redis_async.Redis(connection_pool=pool)

    @staticmethod
    def _decode(api_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """第三方 API 响应 → 标准格式（与 `_transform_api_response` 逐字同构）

        `status=205`（无信息）**必须**映射成「成功 + 空轨迹」：它是「查到了、但暂无轨迹」，
        不是调用失败 —— 返回 None 会把调用方推给 mock 降级（假轨迹）。
        """
        result_data = api_result.get("result") or {}
        if not isinstance(result_data, dict):
            result_data = {}

        api_type = str(result_data.get("type") or "")
        company_name = COMPANY_NAME_MAP.get(api_type.upper(), "") or "未知快递"

        traces = []
        for item in result_data.get("list") or []:
            if not isinstance(item, dict):
                continue
            traces.append({
                "time": item.get("time", ""),
                "content": item.get("context") or item.get("status") or "",
            })

        status = infer_status_from_traces(traces)
        latest = traces[0] if traces else {
            "time": "",
            "content": "暂无物流信息",
        }

        return {
            "tracking_number": result_data.get("number") or "",
            "company": company_name,
            "status": status,
            "status_text": STATUS_TEXT_MAP.get(status, "未知"),
            "latest": latest,
            "traces": traces,
        }

    async def get(
        self,
        tenant_id: int,
        tracking_number: Optional[str],
        company_code: Optional[str],
        phone_tail: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        key = make_logistics_track_key(tenant_id, tracking_number, company_code, phone_tail)
        client = self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            if raw is None:
                return None
            cached = json.loads(raw)
            logger.info(
                f"[logistics-cache] HIT | tenant={tenant_id} "
                f"tracking_no={tracking_number} status={cached.get('status')}"
            )
            return cached
        except Exception as e:
            logger.warning(f"[logistics-cache] GET failed | key={key} error={e}")
            return None
        finally:
            try:
                await client.close()
            except Exception:
                pass

    async def set(
        self,
        tenant_id: int,
        tracking_number: Optional[str],
        company_code: Optional[str],
        phone_tail: Optional[str],
        api_result: Dict[str, Any],
    ) -> bool:
        """缓存第三方响应；返回是否写入成功。

        只应传入 **status ∈ {0, 205}** 的响应（调用失败由调用方拦住，不缓存）。
        """
        decoded = self._decode(api_result)
        if decoded is None:
            return False
        decoded["tracking_number"] = decoded["tracking_number"] or (tracking_number or "")

        ttl = TTL_NO_INFO if str(api_result.get("status")) == "205" else ttl_for_status(
            decoded["status"]
        )
        key = make_logistics_track_key(tenant_id, tracking_number, company_code, phone_tail)

        client = self._get_client()
        if client is None:
            return False
        try:
            await client.set(
                key, json.dumps(decoded, ensure_ascii=False, default=str), ex=ttl
            )
            logger.info(
                f"[logistics-cache] SET | tenant={tenant_id} tracking_no={tracking_number} "
                f"status={decoded['status']} ttl={ttl}s"
            )
            return True
        except Exception as e:
            logger.warning(f"[logistics-cache] SET failed | key={key} error={e}")
            return False
        finally:
            try:
                await client.close()
            except Exception:
                pass


_singleton: Optional[LogisticsTraceCache] = None


def get_logistics_trace_cache() -> LogisticsTraceCache:
    """获取全局 LogisticsTraceCache 单例"""
    global _singleton
    if _singleton is None:
        _singleton = LogisticsTraceCache()
    return _singleton
