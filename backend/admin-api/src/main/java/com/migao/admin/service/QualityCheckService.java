package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.QualityCheck;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.QualityCheckMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 质检记录（**成品帘级**）—— issue #5652 的第一刀。
 *
 * <p>🔴 <b>口径（用户 2026-10-16 逐字裁定，本类不得偏离）</b>：
 * ① <b>颗粒度 =「是按成品帘来检查的」</b>—— 一条记录 = <b>一件成品帘</b>
 * （{@code orderItemId} 级）：不逐工序、不逐工序完工检；
 * ② <b>录入者 =「B 独立质检员」</b>—— 判定由质检员录入（权限面 = 端点上的
 * {@code @RequirePermission}，本类不重复判权限）；报工人<b>只报数量</b>；
 * ③ <b>判定 ≠ 合格 ⇒ 原因必填</b>—— 缺原因 = 422 具名报错，<b>绝不静默存</b>。</p>
 *
 * <p>🔴 <b>两套口径并存、互不覆盖</b>（本单红线）：报工（{@code ProductionWorkLog}）是
 * <b>数量事实</b>，本类是<b>质检判定</b>。本类<b>不</b>读写任何报工行、<b>不</b>重算
 * {@code qty}/{@code qualifiedQty}；质检也<b>不</b>参与计件（返工/报废不计件是报工侧
 * {@code workType} 的既有口径，本单一个字都没碰）—— 本类只落**一张新表**。</p>
 *
 * <p>租户隔离：写入落 {@code tenantId}（由调用方从 {@code TenantContext} 取），读取由
 * {@code TenantLineInnerInterceptor} 注入租户谓词；跨租户的成品帘 ⇒ <b>404</b>
 * （与「不存在」逐字同一形态，不泄露存在性）。</p>
 */
@Service
@RequiredArgsConstructor
public class QualityCheckService {

    /** 表名（读面按 id 反查时用；不新造第二份字符串常量在别处）。 */
    public static final String TABLE = "quality_inspections";

    /**
     * 质检三态（<b>成品帘判定</b>）：{@code pass} 合格 / {@code rework} 返工 / {@code scrap} 报废。
     *
     * <p>取值形态<b>复用</b>报工侧既有习惯（小写 ASCII 单词），但语义面<b>各自独立</b> ——
     * 报工的 {@code work_type} 说的是「这一笔报的是什么货」，本判定说的是「这一件成品帘判了什么」。
     * 两处<b>不</b>互相引用、<b>不</b>互相改写（用户裁定的「两套口径并存」）。</p>
     */
    public static final Set<String> RESULTS = Set.of("pass", "rework", "scrap");

    /** 判为合格时允许原因为空后的文案锚（供报错文案复用）。 */
    private static final String REASON_REQUIRED =
            "质检判定为「%s」时必须填写不合格原因（判定 ≠ 合格 ⇒ 原因必填）";

    private final QualityCheckMapper qualityInspectionMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProcessingOrderMapper processingOrderMapper;

    /**
     * 录入一条质检记录（成品帘级）。
     *
     * @param tenantId   当前租户（调用方从 {@code TenantContext} 取，**不**从 body 取）
     * @param orderItemId 一件成品帘（{@code order_items.id}）—— 质检的**唯一**颗粒度
     * @param result     质检三态之一（{@code pass}/{@code rework}/{@code scrap}）
     * @param reason     不合格原因：判定 ≠ {@code pass} 时必填
     * @param inspectorId   检验人 id（服务端从 {@code SecurityContext} 解）
     * @param inspectorName 检验人展示名
     * @param inspectedAt   检验时刻（调用方取业务时钟单点 {@code BusinessClock}）
     * @return 逐字段可读的记录视图（判定/原因/检验人/时刻/成品帘）
     */
    public Map<String, Object> create(Long tenantId, String orderItemId, String result, String reason,
                                      String inspectorId, String inspectorName, OffsetDateTime inspectedAt) {
        if (!StringUtils.hasText(orderItemId)) {
            throw BusinessException.validationError("order_item_id 必填：质检的颗粒度是**一件成品帘**，缺它无法落记录");
        }
        String normalized = result == null ? null : result.trim();
        if (normalized == null || !RESULTS.contains(normalized)) {
            throw BusinessException.validationError(
                    "inspection_result 仅支持 pass/rework/scrap（合格/返工/报废），收到："
                            + (result == null ? "null" : result));
        }
        // 🔴 判定 ≠ 合格 ⇒ 原因必填（本单判据 4：缺原因必须**具名报错**，不许静默存）
        String trimmedReason = reason == null ? null : reason.trim();
        if (!"pass".equals(normalized) && !StringUtils.hasText(trimmedReason)) {
            throw BusinessException.validationError(
                    String.format(REASON_REQUIRED, label(normalized)),
                    List.of(BusinessException.detail("reason", "判定为「" + label(normalized) + "」时必须说明原因")),
                    "请填写不合格原因（如：布面污渍 / 尺寸偏差 / 缝线开裂）后再提交");
        }

        OrderItem item = resolveOrderItem(tenantId, orderItemId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(item.getOrderId(), tenantId);
        if (po == null) {
            throw BusinessException.validationError(
                    "该成品帘所属订单尚无活跃加工单，无法质检（质检对象必须是加工中的成品帘）");
        }

        QualityCheck row = QualityCheck.builder()
                .tenantId(tenantId)
                .processingOrderId(po.getId())
                .orderItemId(orderItemId)
                .positionName(item.getProductName())
                .inspectorId(inspectorId)
                .inspectorName(inspectorName)
                .inspectionResult(normalized)
                .reason(trimmedReason)
                .inspectedAt(inspectedAt)
                .deleted(0)
                .build();
        qualityInspectionMapper.insert(row);
        return view(row);
    }

    /**
     * 质检记录读面（按加工单 / 成品帘过滤，时间倒序）。
     *
     * <p>同一件成品帘允许多条（返工后重检）⇒ 读面把**逐条**给出（含 {@code inspected_at}），
     * **不**替客户端挑「当前判定」：那是展示口径，前端按时间序取第一条即可，
     * 服务端不制造第二份聚合。</p>
     */
    public List<Map<String, Object>> list(Long tenantId, String processingOrderId, String orderItemId) {
        LambdaQueryWrapper<QualityCheck> q = new LambdaQueryWrapper<QualityCheck>()
                .eq(QualityCheck::getTenantId, tenantId)
                .eq(QualityCheck::getDeleted, 0)
                .orderByDesc(QualityCheck::getInspectedAt)
                .orderByDesc(QualityCheck::getCreatedAt);
        if (StringUtils.hasText(processingOrderId)) {
            q.eq(QualityCheck::getProcessingOrderId, processingOrderId);
        }
        if (StringUtils.hasText(orderItemId)) {
            q.eq(QualityCheck::getOrderItemId, orderItemId);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (QualityCheck row : qualityInspectionMapper.selectList(q)) {
            out.add(view(row));
        }
        return out;
    }

    /**
     * 定位一件成品帘（三重校验：存在 + 同租户 + 未软删）。
     *
     * <p>跨租户与不存在<b>给出同一个 404</b>（逐字同一形态）—— 403 等于承认「这个 id 存在，
     * 只是不给你看」（与发货读面同款纪律）。</p>
     */
    private OrderItem resolveOrderItem(Long tenantId, String orderItemId) {
        OrderItem item = orderItemMapper.selectById(orderItemId);
        if (item == null || !tenantId.equals(item.getTenantId())
                || (item.getDeleted() != null && item.getDeleted() != 0)) {
            throw BusinessException.notFound("成品帘");
        }
        return item;
    }

    /** 逐字段可读的记录视图（**缺值不渲染假数据**：null 原样为 null，不折 0 / 不写 undefined）。 */
    private Map<String, Object> view(QualityCheck row) {
        Map<String, Object> v = new LinkedHashMap<>();
        v.put("id", row.getId());
        v.put("order_item_id", row.getOrderItemId());
        v.put("processing_order_id", row.getProcessingOrderId());
        v.put("position_name", row.getPositionName());
        v.put("result", row.getInspectionResult());
        v.put("result_label", label(row.getInspectionResult()));
        v.put("reason", row.getReason());
        v.put("inspector_id", row.getInspectorId());
        v.put("inspector_name", row.getInspectorName());
        v.put("inspected_at", row.getInspectedAt());
        return v;
    }

    /** 三态的中文标签（展示用；未知值如实回 null，不猜）。 */
    private String label(String result) {
        if (result == null) {
            return null;
        }
        return switch (result) {
            case "pass" -> "合格";
            case "rework" -> "返工";
            case "scrap" -> "报废";
            default -> null;
        };
    }
}
