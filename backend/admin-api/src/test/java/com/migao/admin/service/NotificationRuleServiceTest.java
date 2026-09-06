package com.migao.admin.service;
// case_ids: ST-004, ST-005

import com.migao.admin.dto.NotificationRuleDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SaveNotificationRuleRequest;
import com.migao.admin.entity.NotificationRule;
import com.migao.admin.entity.NotificationTemplate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.NotificationRuleMapper;
import com.migao.admin.mapper.NotificationTemplateMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * NotificationRuleService 单元测试 — 规则管理（issue #2965 补全）
 * 覆盖：分页查询、创建（模板存在性校验）、更新/删除的租户隔离与系统规则保护。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("NotificationRuleService 通知规则管理测试")
class NotificationRuleServiceTest {

    @Mock
    private NotificationRuleMapper ruleMapper;

    @Mock
    private NotificationTemplateMapper templateMapper;

    @InjectMocks
    private NotificationRuleService ruleService;

    private NotificationRule rule(long tenantId, String id, String eventType, String templateId) {
        return NotificationRule.builder()
                .id(id)
                .tenantId(tenantId)
                .eventType(eventType)
                .recipientType("user")
                .channels("internal")
                .enabled(true)
                .templateId(templateId)
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .build();
    }

    private SaveNotificationRuleRequest request(String eventType, String templateId) {
        SaveNotificationRuleRequest req = new SaveNotificationRuleRequest();
        req.setEventType(eventType);
        req.setTemplateId(templateId);
        return req;
    }

    // ======================== 分页查询 ========================

    @Test
    @DisplayName("queryRules — 返回本租户规则与系统规则")
    void queryRules_returnsTenantAndSystemRules() {
        // given
        Page<NotificationRule> page = new Page<>(1, 20);
        page.setTotal(2);
        page.setRecords(java.util.List.of(
                rule(1L, "rule-1", "order_created", "tpl-1"),
                rule(0L, "rule-sys-1", "order_status_changed", "tpl-sys-1")));
        when(ruleMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(page);
        when(templateMapper.selectById("tpl-1")).thenReturn(NotificationTemplate.builder().id("tpl-1").name("模板A").build());
        when(templateMapper.selectById("tpl-sys-1")).thenReturn(NotificationTemplate.builder().id("tpl-sys-1").name("模板B").build());

        // when
        PageResponse<NotificationRuleDTO> result = ruleService.queryRules(1, 20, 1L, null);

        // then
        assertThat(result.getTotal()).isEqualTo(2);
        assertThat(result.getItems()).hasSize(2);
        assertThat(result.getItems().get(0).getTemplateName()).isEqualTo("模板A");
    }

    // ======================== 创建 ========================

    @Test
    @DisplayName("createRule — 成功创建归属当前租户的规则")
    void createRule_success() {
        // given
        when(templateMapper.selectById("tpl-1")).thenReturn(
                NotificationTemplate.builder().id("tpl-1").name("新订单").build());
        when(ruleMapper.insert(any(NotificationRule.class))).thenAnswer(invocation -> {
            NotificationRule r = invocation.getArgument(0);
            r.setId("rule-new");
            return 1;
        });

        // when
        NotificationRuleDTO result = ruleService.createRule(1L, request("order_created", "tpl-1"));

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTenantId()).isEqualTo(1L);
        assertThat(result.getEventType()).isEqualTo("order_created");
        assertThat(result.getEnabled()).isTrue();
        verify(ruleMapper).insert(any(NotificationRule.class));
    }

    @Test
    @DisplayName("createRule — 事件类型为空被拒绝")
    void createRule_blankEventTypeRejected() {
        assertThatThrownBy(() -> ruleService.createRule(1L, request("", "tpl-1")))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(ruleMapper, never()).insert(any(NotificationRule.class));
    }

    @Test
    @DisplayName("createRule — 模板不存在被拒绝")
    void createRule_templateNotFoundRejected() {
        // given
        when(templateMapper.selectById("tpl-missing")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> ruleService.createRule(1L, request("order_created", "tpl-missing")))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(ruleMapper, never()).insert(any(NotificationRule.class));
    }

    // ======================== 更新 ========================

    @Test
    @DisplayName("updateRule — 更新本租户规则成功")
    void updateRule_success() {
        // given
        when(ruleMapper.selectById("rule-1")).thenReturn(rule(1L, "rule-1", "order_created", "tpl-1"));
        when(templateMapper.selectById("tpl-2")).thenReturn(
                NotificationTemplate.builder().id("tpl-2").name("模板B").build());
        when(ruleMapper.updateById(any(NotificationRule.class))).thenReturn(1);

        SaveNotificationRuleRequest req = request("order_created", "tpl-2");
        req.setEnabled(false);

        // when
        NotificationRuleDTO result = ruleService.updateRule(1L, "rule-1", req);

        // then
        assertThat(result.getTemplateId()).isEqualTo("tpl-2");
        assertThat(result.getEnabled()).isFalse();
        verify(ruleMapper).updateById(any(NotificationRule.class));
    }

    @Test
    @DisplayName("updateRule — 跨租户规则禁止修改")
    void updateRule_crossTenantRejected() {
        // given
        when(ruleMapper.selectById("rule-9")).thenReturn(rule(9L, "rule-9", "order_created", "tpl-1"));
        when(templateMapper.selectById("tpl-1")).thenReturn(
                NotificationTemplate.builder().id("tpl-1").name("模板A").build());

        // when & then
        assertThatThrownBy(() -> ruleService.updateRule(1L, "rule-9", request("order_created", "tpl-1")))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("PERMISSION_DENIED");
                });
        verify(ruleMapper, never()).updateById(any(NotificationRule.class));
    }

    @Test
    @DisplayName("updateRule — 系统规则禁止修改")
    void updateRule_systemRuleRejected() {
        // given
        when(ruleMapper.selectById("rule-sys-1")).thenReturn(rule(0L, "rule-sys-1", "order_created", "tpl-sys-1"));
        when(templateMapper.selectById("tpl-sys-1")).thenReturn(
                NotificationTemplate.builder().id("tpl-sys-1").name("系统模板").build());

        // when & then
        assertThatThrownBy(() -> ruleService.updateRule(1L, "rule-sys-1", request("order_created", "tpl-sys-1")))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
    }

    // ======================== 删除 ========================

    @Test
    @DisplayName("deleteRule — 本租户规则可删除")
    void deleteRule_success() {
        // given
        when(ruleMapper.selectById("rule-1")).thenReturn(rule(1L, "rule-1", "order_created", "tpl-1"));

        // when
        ruleService.deleteRule(1L, "rule-1");

        // then
        verify(ruleMapper).deleteById("rule-1");
    }

    @Test
    @DisplayName("deleteRule — 跨租户规则禁止删除")
    void deleteRule_crossTenantRejected() {
        // given
        when(ruleMapper.selectById("rule-9")).thenReturn(rule(9L, "rule-9", "order_created", "tpl-1"));

        // when & then
        assertThatThrownBy(() -> ruleService.deleteRule(1L, "rule-9"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("PERMISSION_DENIED");
                });
        verify(ruleMapper, never()).deleteById("rule-9");
    }

    @Test
    @DisplayName("deleteRule — 系统规则禁止删除")
    void deleteRule_systemRuleRejected() {
        // given
        when(ruleMapper.selectById("rule-sys-1")).thenReturn(rule(0L, "rule-sys-1", "order_created", "tpl-sys-1"));

        // when & then
        assertThatThrownBy(() -> ruleService.deleteRule(1L, "rule-sys-1"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(ruleMapper, never()).deleteById("rule-sys-1");
    }
}