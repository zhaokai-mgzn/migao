// case_ids: RG-001
package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.AuditLog;
import com.migao.admin.mapper.AuditLogMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * AuditLogService 单元测试。
 *
 * 字段语义（issue #4071 裁定 ①）：{@code action} = 动作**动词**，
 * 工具名另置 {@code tool_name}（迁移 V52）—— 本文件锁定该映射真的落到实体上。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AuditLogService 审计日志服务测试")
class AuditLogServiceTest {

    @Mock
    private AuditLogMapper auditLogMapper;

    @InjectMocks
    private AuditLogService auditLogService;

    @Test
    @DisplayName("recordLog — 创建 AuditLog 并插入")
    void recordLog_createsAndInserts() {
        when(auditLogMapper.insert(any(AuditLog.class))).thenReturn(1);

        auditLogService.recordLog(1L, "user-1", "admin",
                "login", "user", null, "user-1", "管理员",
                "details", "127.0.0.1", "Mozilla/5.0");

        verify(auditLogMapper).insert(any(AuditLog.class));
    }

    @Test
    @DisplayName("recordLog — action 落动词、toolName 落工具名（两者分列，不混）")
    void recordLog_keepsActionAndToolNameSeparate() {
        when(auditLogMapper.insert(any(AuditLog.class))).thenReturn(1);

        auditLogService.recordLog(1L, "u-1", null,
                "update_status", "agent_tool", "order_manage", null, null,
                null, null, null);

        ArgumentCaptor<AuditLog> captor = ArgumentCaptor.forClass(AuditLog.class);
        verify(auditLogMapper).insert(captor.capture());
        AuditLog row = captor.getValue();
        assertThat(row.getAction()).isEqualTo("update_status");
        assertThat(row.getToolName()).isEqualTo("order_manage");
        assertThat(row.getAction()).isNotEqualTo(row.getToolName());
    }

    @Test
    @DisplayName("recordLog (简化版) — 调用完整版 recordLog")
    void recordLog_simple_delegates() {
        when(auditLogMapper.insert(any(AuditLog.class))).thenReturn(1);

        auditLogService.recordLog(1L, "user-1", "admin",
                "update", "product", null, "prod-1", "商品A");

        verify(auditLogMapper).insert(any(AuditLog.class));
    }

    @Test
    @DisplayName("getAuditLogPage — 返回分页结果")
    void getAuditLogPage_returnsPageResponse() {
        AuditLog log = AuditLog.builder()
                .id("1")
                .tenantId(1L)
                .action("login")
                .resourceType("user")
                .build();

        Page<AuditLog> page = new Page<>(1, 10);
        page.setTotal(1);
        page.setRecords(List.of(log));
        when(auditLogMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(page);

        PageResponse<AuditLog> result = auditLogService.getAuditLogPage(
                1, 10, "login", null, null, null, null, 1L);

        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getAction()).isEqualTo("login");
    }

    @Test
    @DisplayName("getAuditLogPage — 支持操作类型筛选")
    void getAuditLogPage_filtersByAction() {
        when(auditLogMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(new Page<>(1, 10));

        PageResponse<AuditLog> result = auditLogService.getAuditLogPage(
                1, 10, "delete", null, null, null, null, 1L);

        assertThat(result.getItems()).isEmpty();
    }

    @Test
    @DisplayName("getResourceLogs — 返回指定资源的操作日志")
    void getResourceLogs_returnsLogs() {
        AuditLog log = AuditLog.builder()
                .id("1")
                .resourceType("product")
                .resourceId("prod-1")
                .build();
        Page<AuditLog> page = new Page<>(1, 10);
        page.setTotal(1);
        page.setRecords(List.of(log));
        when(auditLogMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(page);

        PageResponse<AuditLog> result = auditLogService.getResourceLogs(
                "product", "prod-1", 1, 10);

        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getResourceType()).isEqualTo("product");
    }
}
