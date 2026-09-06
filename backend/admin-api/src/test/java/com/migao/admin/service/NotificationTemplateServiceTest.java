package com.migao.admin.service;
// case_ids: ST-004, ST-005

import com.migao.admin.dto.NotificationRuleDTO;
import com.migao.admin.dto.NotificationTemplateDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SaveNotificationTemplateRequest;
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
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * NotificationTemplateService 单元测试 — 模板管理（issue #2965 补全）
 * 覆盖：分页查询（租户+系统模板）、创建、更新/删除的租户隔离与系统模板保护、引用完整性。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("NotificationTemplateService 通知模板管理测试")
class NotificationTemplateServiceTest {

    @Mock
    private NotificationTemplateMapper templateMapper;

    @Mock
    private NotificationRuleMapper ruleMapper;

    @InjectMocks
    private NotificationTemplateService templateService;

    private NotificationTemplate tenantTemplate(long tenantId, String id, String name) {
        return NotificationTemplate.builder()
                .id(id)
                .tenantId(tenantId)
                .name(name)
                .type("order")
                .channel("internal")
                .templateContent("模板内容{{v}}")
                .status("active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .build();
    }

    // ======================== 分页查询 ========================

    @Test
    @DisplayName("queryTemplates — 返回本租户模板与系统模板")
    void queryTemplates_returnsTenantAndSystemTemplates() {
        // given
        Page<NotificationTemplate> page = new Page<>(1, 20);
        page.setTotal(2);
        page.setRecords(List.of(
                tenantTemplate(1L, "tpl-1", "租户模板"),
                tenantTemplate(0L, "tpl-sys-1", "系统模板")));
        when(templateMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(page);

        // when
        PageResponse<NotificationTemplateDTO> result = templateService.queryTemplates(1, 20, 1L);

        // then
        assertThat(result.getTotal()).isEqualTo(2);
        assertThat(result.getItems()).hasSize(2);
        assertThat(result.getItems().get(1).getName()).isEqualTo("系统模板");
    }

    // ======================== 创建 ========================

    @Test
    @DisplayName("createTemplate — 成功创建归属当前租户的模板")
    void createTemplate_success() {
        // given
        SaveNotificationTemplateRequest request = new SaveNotificationTemplateRequest();
        request.setName("订单确认");
        request.setChannel("internal");
        request.setTemplateContent("您的订单{{orderNo}}已确认");

        when(templateMapper.insert(any(NotificationTemplate.class))).thenAnswer(invocation -> {
            NotificationTemplate t = invocation.getArgument(0);
            t.setId("tpl-new");
            return 1;
        });

        // when
        NotificationTemplateDTO result = templateService.createTemplate(1L, request);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getId()).isEqualTo("tpl-new");
        assertThat(result.getTenantId()).isEqualTo(1L);
        assertThat(result.getStatus()).isEqualTo("active");
        verify(templateMapper).insert(any(NotificationTemplate.class));
    }

    @Test
    @DisplayName("createTemplate — 模板内容为空被拒绝")
    void createTemplate_blankContentRejected() {
        // given
        SaveNotificationTemplateRequest request = new SaveNotificationTemplateRequest();
        request.setName("订单确认");
        request.setTemplateContent("   ");

        // when & then
        assertThatThrownBy(() -> templateService.createTemplate(1L, request))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(templateMapper, never()).insert(any(NotificationTemplate.class));
    }

    @Test
    @DisplayName("createTemplate — 模板名称为空被拒绝")
    void createTemplate_blankNameRejected() {
        // given
        SaveNotificationTemplateRequest request = new SaveNotificationTemplateRequest();
        request.setTemplateContent("内容");

        // when & then
        assertThatThrownBy(() -> templateService.createTemplate(1L, request))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(templateMapper, never()).insert(any(NotificationTemplate.class));
    }

    // ======================== 更新 ========================

    @Test
    @DisplayName("updateTemplate — 更新本租户模板成功")
    void updateTemplate_success() {
        // given
        NotificationTemplate existing = tenantTemplate(1L, "tpl-1", "旧模板名");
        when(templateMapper.selectById("tpl-1")).thenReturn(existing);
        when(templateMapper.updateById(any(NotificationTemplate.class))).thenReturn(1);

        SaveNotificationTemplateRequest request = new SaveNotificationTemplateRequest();
        request.setName("新模板名");
        request.setTemplateContent("新内容{{x}}");
        request.setChannel("internal");
        request.setStatus("disabled");

        // when
        NotificationTemplateDTO result = templateService.updateTemplate(1L, "tpl-1", request);

        // then
        assertThat(result.getName()).isEqualTo("新模板名");
        assertThat(result.getStatus()).isEqualTo("disabled");
        verify(templateMapper).updateById(any(NotificationTemplate.class));
    }

    @Test
    @DisplayName("updateTemplate — 系统模板(tenantId=0)禁止修改")
    void updateTemplate_systemTemplateRejected() {
        // given
        when(templateMapper.selectById("tpl-sys-1")).thenReturn(tenantTemplate(0L, "tpl-sys-1", "系统模板"));

        SaveNotificationTemplateRequest request = new SaveNotificationTemplateRequest();
        request.setName("改名");
        request.setTemplateContent("内容");

        // when & then
        assertThatThrownBy(() -> templateService.updateTemplate(1L, "tpl-sys-1", request))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(templateMapper, never()).updateById(any(NotificationTemplate.class));
    }

    @Test
    @DisplayName("updateTemplate — 跨租户模板禁止修改")
    void updateTemplate_crossTenantRejected() {
        // given
        when(templateMapper.selectById("tpl-9")).thenReturn(tenantTemplate(9L, "tpl-9", "他人模板"));

        SaveNotificationTemplateRequest request = new SaveNotificationTemplateRequest();
        request.setName("改名");
        request.setTemplateContent("内容");

        // when & then
        assertThatThrownBy(() -> templateService.updateTemplate(1L, "tpl-9", request))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("PERMISSION_DENIED");
                });
    }

    @Test
    @DisplayName("updateTemplate — 模板不存在")
    void updateTemplate_notFound() {
        // given
        when(templateMapper.selectById("nonexistent")).thenReturn(null);

        SaveNotificationTemplateRequest request = new SaveNotificationTemplateRequest();
        request.setName("改名");
        request.setTemplateContent("内容");

        // when & then
        assertThatThrownBy(() -> templateService.updateTemplate(1L, "nonexistent", request))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 删除 ========================

    @Test
    @DisplayName("deleteTemplate — 无规则引用的本租户模板可删除")
    void deleteTemplate_success() {
        // given
        when(templateMapper.selectById("tpl-1")).thenReturn(tenantTemplate(1L, "tpl-1", "模板"));
        when(ruleMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

        // when
        templateService.deleteTemplate(1L, "tpl-1");

        // then
        verify(templateMapper).deleteById("tpl-1");
    }

    @Test
    @DisplayName("deleteTemplate — 被通知规则引用的模板禁止删除")
    void deleteTemplate_referencedByRuleRejected() {
        // given
        when(templateMapper.selectById("tpl-1")).thenReturn(tenantTemplate(1L, "tpl-1", "模板"));
        when(ruleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(NotificationRule.builder().id("rule-1").templateId("tpl-1").build()));

        // when & then
        assertThatThrownBy(() -> templateService.deleteTemplate(1L, "tpl-1"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(templateMapper, never()).deleteById("tpl-1");
    }

    @Test
    @DisplayName("deleteTemplate — 系统模板禁止删除")
    void deleteTemplate_systemTemplateRejected() {
        // given
        when(templateMapper.selectById("tpl-sys-1")).thenReturn(tenantTemplate(0L, "tpl-sys-1", "系统模板"));

        // when & then
        assertThatThrownBy(() -> templateService.deleteTemplate(1L, "tpl-sys-1"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(templateMapper, never()).deleteById("tpl-sys-1");
    }
}