package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 物流服务类
 * 处理物流信息的录入、查询和跟踪
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderLogisticsService extends ServiceImpl<OrderLogisticsMapper, OrderLogistics> {

    private final OrderLogisticsMapper orderLogisticsMapper;

    /**
     * 根据订单ID查询物流记录列表
     *
     * @param orderId 订单ID
     * @return 物流记录列表
     */
    public List<OrderLogistics> getByOrderId(String orderId) {
        return orderLogisticsMapper.selectByOrderId(orderId, TenantContext.getTenantId());
    }

    /**
     * 根据ID查询物流信息
     *
     * @param id 物流记录ID
     * @return 物流记录
     */
    public OrderLogistics getById(String id) {
        OrderLogistics logistics = orderLogisticsMapper.selectById(id);
        if (logistics == null) {
            throw BusinessException.notFound("物流记录");
        }
        return logistics;
    }

    /**
     * 创建物流信息（issue #7398：写面**收敛到** {@link OrderLogisticsWriter} 这唯一写入口）。
     *
     * <p><b>为什么不能直连 insert</b>：{@code order_logistics} 自 V165 起有部分唯一索引
     * {@code uk_order_logistics_tenant_order}（{@code (tenant_id, order_id) WHERE deleted = 0}）。
     * 原实现无条件直连插入 ⇒ 同一订单的第二次写入
     * （并发两次发货 / 双击 / 双端同时确认）撞索引，异常直接冒泡成 <b>5xx</b>。</p>
     *
     * <p>⇒ 改走 writer：已有该单物流行时**退化为更新那一行**（同一订单最终恰好 1 行，
     * 调用方不感知冲突、也不报错）—— 与商家发货页 / 工人端发货共用<b>同一份</b>冲突映射
     * （见 {@link OrderLogisticsWriter#upsert}）。</p>
     *
     * @param details 除承运商 / 运单号之外的发货字段（{@code null} = 本次请求没给）
     * @return 落库后**重新读出**的那一行（结果以表里的行为准，不把本次入参当成结果回吐）
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderLogistics createLogistics(String orderId, Long tenantId, String logisticsCompany, String trackingNo,
                                         OrderLogisticsWriter.ShippingDetails details) {
        OrderLogisticsWriter.upsert(orderLogisticsMapper, tenantId, orderId, logisticsCompany, trackingNo,
                details, () -> null);
        List<OrderLogistics> rows = orderLogisticsMapper.selectByOrderId(orderId, tenantId);
        if (rows == null || rows.isEmpty()) {
            // 刚刚写成功却读不到行 = 数据不一致（不是业务冲突）⇒ 显式失败，不返回一个假实体
            throw new IllegalStateException("物流写入后读不到记录: orderId=" + orderId);
        }
        log.info("创建物流信息成功: orderId={}, trackingNo={}", orderId, trackingNo);
        return rows.get(0);
    }

    /**
     * 更新物流信息
     *
     * @param id               物流记录ID
     * @param logisticsCompany 物流公司
     * @param trackingNo       快递单号
     * @param status           物流状态 (in_transit / delivered / returned)
     * @return 更新后的物流记录
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderLogistics updateLogistics(String id, String logisticsCompany, String trackingNo, String status) {
        OrderLogistics logistics = orderLogisticsMapper.selectById(id);
        if (logistics == null) {
            throw BusinessException.notFound("物流记录");
        }

        if (logisticsCompany != null) {
            logistics.setLogisticsCompany(logisticsCompany);
        }
        if (trackingNo != null) {
            logistics.setTrackingNo(trackingNo);
        }
        if (status != null) {
            if (!isValidLogisticsStatus(status)) {
                throw BusinessException.validationError("无效的物流状态: " + status);
            }
            logistics.setStatus(status);
            if ("delivered".equals(status)) {
                logistics.setDeliveredAt(OffsetDateTime.now());
            }
        }

        orderLogisticsMapper.backfillShippedAtIfAbsent(logistics.getOrderId(), logistics.getTenantId());
        orderLogisticsMapper.updateById(logistics);
        log.info("更新物流信息成功: id={}, status={}", id, status);
        return logistics;
    }

    /**
     * 查询物流跟踪信息
     * TODO: 集成第三方物流查询 API（如快递100、快递鸟等）
     *
     * @param trackingNo       快递单号
     * @param logisticsCompany 物流公司
     * @return 跟踪信息（当前返回占位数据）
     */
    public Object trackLogistics(String trackingNo, String logisticsCompany) {
        // TODO: 集成第三方物流查询 API
        // 1. 根据物流公司和快递单号调用第三方 API
        // 2. 解析返回的物流跟踪信息
        // 3. 缓存结果并返回
        log.info("查询物流跟踪信息: trackingNo={}, company={}", trackingNo, logisticsCompany);
        return null;
    }

    /**
     * 删除物流记录（逻辑删除）
     *
     * @param id 物流记录ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteLogistics(String id) {
        OrderLogistics logistics = orderLogisticsMapper.selectById(id);
        if (logistics == null) {
            throw BusinessException.notFound("物流记录");
        }
        // issue #6956 · 现象 C：判影响行数（并发双删只许一次成功；0 行 = 已被别人删掉）
        if (orderLogisticsMapper.deleteById(id) == 0) {
            throw BusinessException.notFound("物流记录");
        }
        log.info("删除物流记录成功: id={}", id);
    }

    /**
     * 给**缺发货时刻**的物流行补上**首次发货时刻**（issue #6276）。
     *
     * <p>口径与本表两个写入方（{@link OrderLogisticsWriter}、
     * {@code OrderController.updateLogistics}）共用**同一份**实现
     * （{@link OrderLogisticsMapper#backfillShippedAtIfAbsent}）—— 两个「读-改-写」写面都必须在
     * {@code updateById} 之前调它，否则 `shipped_at IS NULL` 的老行永远补不上。</p>
     *
     * @return 本次真正补到的行数（0 = 无需补 / 已经补过）
     */
    public int backfillShippedAtIfAbsent(String orderId, Long tenantId) {
        return orderLogisticsMapper.backfillShippedAtIfAbsent(orderId, tenantId);
    }

    /**
     * 校验物流状态是否有效
     */
    private boolean isValidLogisticsStatus(String status) {
        return "in_transit".equals(status)
                || "delivered".equals(status)
                || "returned".equals(status);
    }
}
