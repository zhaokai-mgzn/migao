package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.AuditLog;
import com.migao.admin.mapper.AuditLogMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;

/**
 * 审计日志服务类
 * 记录和查询系统操作审计日志
 *
 * TODO: 提供 AOP 注解方式记录日志（如 @AuditLog 注解）
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AuditLogService extends ServiceImpl<AuditLogMapper, AuditLog> {

    private final AuditLogMapper auditLogMapper;

    /**
     * 记录审计日志
     *
     * @param tenantId     租户ID
     * @param userId       操作人ID
     * @param userName     操作人名称
     * @param action       操作类型（create/update/delete/login/logout/assign等）
     * @param resourceType 资源类型（product/order/ticket/ai_config/employee等）
     * @param resourceId   资源ID
     * @param resourceName 资源名称
     * @param details      操作详情
     * @param ipAddress    IP地址
     * @param userAgent    User-Agent
     */
    public void recordLog(Long tenantId, String userId, String userName,
                          String action, String resourceType, String resourceId,
                          String resourceName, Object details,
                          String ipAddress, String userAgent) {
        AuditLog auditLog = AuditLog.builder()
                .tenantId(tenantId)
                .userId(userId)
                .userName(userName)
                .action(action)
                .resourceType(resourceType)
                .resourceId(resourceId)
                .resourceName(resourceName)
                .actionDetails(details)
                .ipAddress(ipAddress)
                .userAgent(userAgent)
                .build();

        auditLogMapper.insert(auditLog);
        log.debug("记录审计日志: action={}, resourceType={}, resourceId={}", action, resourceType, resourceId);
    }

    /**
     * 异步记录审计日志（不阻塞主业务流程）
     */
    @Async
    public void recordLogAsync(Long tenantId, String userId, String userName,
                               String action, String resourceType, String resourceId,
                               String resourceName, Object details,
                               String ipAddress, String userAgent) {
        try {
            recordLog(tenantId, userId, userName, action, resourceType,
                    resourceId, resourceName, details, ipAddress, userAgent);
        } catch (Exception e) {
            log.error("异步记录审计日志失败: action={}, resourceType={}, resourceId={}",
                    action, resourceType, resourceId, e);
        }
    }

    /**
     * 记录简化的审计日志（无IP和UA信息）
     *
     * @param tenantId     租户ID
     * @param userId       操作人ID
     * @param userName     操作人名称
     * @param action       操作类型
     * @param resourceType 资源类型
     * @param resourceId   资源ID
     * @param resourceName 资源名称
     */
    public void recordLog(Long tenantId, String userId, String userName,
                          String action, String resourceType,
                          String resourceId, String resourceName) {
        recordLog(tenantId, userId, userName, action, resourceType,
                resourceId, resourceName, null, null, null);
    }

    /**
     * 分页查询审计日志
     *
     * @param page         页码
     * @param size         每页大小
     * @param action       操作类型筛选
     * @param resourceType 资源类型筛选
     * @param userId       操作人ID筛选
     * @param startTime    开始时间
     * @param endTime      结束时间
     * @param tenantId     租户ID
     * @return 分页响应
     */
    public PageResponse<AuditLog> getAuditLogPage(long page, long size,
                                                   String action, String resourceType,
                                                   String userId, OffsetDateTime startTime,
                                                   OffsetDateTime endTime, Long tenantId) {
        LambdaQueryWrapper<AuditLog> wrapper = new LambdaQueryWrapper<>();

        // 操作类型筛选
        if (StringUtils.hasText(action)) {
            wrapper.eq(AuditLog::getAction, action);
        }

        // 资源类型筛选
        if (StringUtils.hasText(resourceType)) {
            wrapper.eq(AuditLog::getResourceType, resourceType);
        }

        // 操作人筛选
        if (StringUtils.hasText(userId)) {
            wrapper.eq(AuditLog::getUserId, userId);
        }

        // 时间范围筛选
        if (startTime != null) {
            wrapper.ge(AuditLog::getCreatedAt, startTime);
        }
        if (endTime != null) {
            wrapper.le(AuditLog::getCreatedAt, endTime);
        }

        wrapper.orderByDesc(AuditLog::getCreatedAt);

        Page<AuditLog> logPage = new Page<>(page, size);
        Page<AuditLog> resultPage = auditLogMapper.selectPage(logPage, wrapper);

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(),
                resultPage.getSize(), resultPage.getRecords());
    }

    /**
     * 查询指定资源的操作日志
     *
     * @param resourceType 资源类型
     * @param resourceId   资源ID
     * @param page         页码
     * @param size         每页大小
     * @return 分页响应
     */
    public PageResponse<AuditLog> getResourceLogs(String resourceType, String resourceId,
                                                   long page, long size) {
        LambdaQueryWrapper<AuditLog> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AuditLog::getResourceType, resourceType)
                .eq(AuditLog::getResourceId, resourceId)
                .orderByDesc(AuditLog::getCreatedAt);

        Page<AuditLog> logPage = new Page<>(page, size);
        Page<AuditLog> resultPage = auditLogMapper.selectPage(logPage, wrapper);

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(),
                resultPage.getSize(), resultPage.getRecords());
    }
}
