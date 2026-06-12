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
     * 创建物流信息
     *
     * @param orderId          订单ID
     * @param tenantId         租户ID
     * @param logisticsCompany 物流公司
     * @param trackingNo       快递单号
     * @return 物流记录
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderLogistics createLogistics(String orderId, Long tenantId, String logisticsCompany, String trackingNo) {
        OrderLogistics logistics = OrderLogistics.builder()
                .tenantId(tenantId)
                .orderId(orderId)
                .logisticsCompany(logisticsCompany)
                .trackingNo(trackingNo)
                .status("in_transit")
                .shippedAt(OffsetDateTime.now())
                .build();

        orderLogisticsMapper.insert(logistics);
        log.info("创建物流信息成功: orderId={}, trackingNo={}", orderId, trackingNo);
        return logistics;
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
        orderLogisticsMapper.deleteById(id);
        log.info("删除物流记录成功: id={}", id);
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
