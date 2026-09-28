package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 发货单（issue #5648）—— 对应表 {@code order_shipments}。
 *
 * <p><b>它是什么</b>：一次「工人拍照/手工生成发货单」动作的**服务端留痕** ——
 * 谁（{@code packed_by_worker_*} / {@code shipped_by_worker_*}）、何时（{@code packed_at} /
 * {@code shipped_at}）、哪张单（{@code order_id} / {@code order_no} / {@code shipment_no}）、
 * 照片引用（{@code photo_refs}）与识别留痕（{@code recognition}）。</p>
 *
 * <p><b>为什么与 {@link OrderLogistics} 分开</b>：{@code order_logistics} 是**物流面**
 * （公司 / 单号 / 轨迹），本表是**发货事实面**（照了什么、发了多少、谁经手）。
 * 两者基数不同（一次发货一条物流、一张发货单 N 条明细），合并会让「发了多少」没有落点
 * —— 那正是本单要修的洞（少发/错发不可核）。</p>
 *
 * <p>{@code unpacked_*} 三列 = 撤销打包的留痕（issue #5648 裁定：打包打错了**可撤销**，
 * 但撤销必须带理由 + 留痕 —— 涉责任的动作不留白）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "order_shipments", autoResultMap = true)
public class OrderShipment {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderId;

    private String orderNo;

    /** 发货单号（人可读，纸面/对账用） */
    private String shipmentNo;

    /** 来源：{@code worker_photo}（工人拍照识别生成）/ {@code worker}（工人手工）/ {@code admin}（商家侧） */
    private String source;

    /** 照片引用（已上传图片的 URL 列表）；无照片 ⇒ 空数组，绝不编造路径 */
    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object photoRefs;

    /** 识别留痕：vision 返回的**原样**字段表（逐格 value/source/reason） */
    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object recognition;

    private String packedByWorkerId;

    private String packedByWorkerName;

    private OffsetDateTime packedAt;

    private String shippedByWorkerId;

    private String shippedByWorkerName;

    private OffsetDateTime shippedAt;

    private String trackingNo;

    private String logisticsCompany;

    /** 幂等键（{@code X-Client-Request-Id}）：同键重放不再记明细、不再流转状态 */
    private String clientRequestId;

    private OffsetDateTime unpackedAt;

    private String unpackedByWorkerId;

    private String unpackedByWorkerName;

    /** 撤销打包理由（必填）—— 打包是车间物理动作，撤销必须说清为什么 */
    private String unpackReason;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
