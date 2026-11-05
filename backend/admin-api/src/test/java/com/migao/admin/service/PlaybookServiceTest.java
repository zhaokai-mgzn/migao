package com.migao.admin.service;

// case_ids: MC-222

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Playbook;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PlaybookMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 口径卡状态机测试（issue #8175 一期：落卡 → 审核 → 退役）。
 *
 * <p>三条不变式各有一组会红的判据：① 写面只落 draft（审核不可绕过）；② 状态迁移是 CAS
 * （影响 0 行 = 冲突，不许静默成功）；③ 每次迁移都留审计。</p>
 *
 * <p>另含条件语言的**写面校验**（判据 2 的另一半）：自由文本 / 未知算子 / 空条件一律 422，
 * 反例不可执行同样 422（判据 6：反例不许退化成注释）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("PlaybookService 口径卡状态机测试")
class PlaybookServiceTest {

    private static final String TRIGGER = "{\"field\":\"intent\",\"op\":\"in\",\"value\":[\"quote\"]}";
    private static final String COUNTER = "{\"field\":\"user_text\",\"op\":\"contains\",\"value\":\"零裁\"}";

    @InjectMocks
    private PlaybookService playbookService;

    @Mock
    private PlaybookMapper playbookMapper;
    @Mock
    private AuditLogService auditLogService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(7L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private Playbook draftBody() {
        return Playbook.builder()
                .triggerJson(TRIGGER)
                .correctText("报价默认按整卷走")
                .counterJson(COUNTER)
                .sourceSessionId("sess-1")
                .sourceTurn(3)
                .build();
    }

    @Nested
    @DisplayName("落卡：只落 draft（审核不可通过参数绕过）")
    class CreateDraft {

        @Test
        @DisplayName("请求里写 active 也没用 —— 落库状态由服务端钉死为 draft")
        void stateIsForcedToDraft() {
            Playbook body = draftBody();
            body.setState(PlaybookService.STATE_ACTIVE);

            Playbook created = playbookService.createDraft(body);

            assertThat(created.getState()).isEqualTo("draft");
            assertThat(created.getTenantId()).isEqualTo(7L);
            assertThat(created.getHits()).isEqualTo(0);
            ArgumentCaptor<Playbook> captor = ArgumentCaptor.forClass(Playbook.class);
            verify(playbookMapper).insert(captor.capture());
            assertThat(captor.getValue().getState()).isEqualTo("draft");
        }

        @Test
        @DisplayName("自由文本触发条件 ⇒ 422（判据 2：不许把不可判的口径写进库）")
        void freeTextTriggerIsRejected() {
            Playbook body = draftBody();
            body.setTriggerJson("整卷优先");

            assertThatThrownBy(() -> playbookService.createDraft(body))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("触发条件不可执行");
            verify(playbookMapper, never()).insert(any(Playbook.class));
        }

        @Test
        @DisplayName("反例不可执行 ⇒ 422（判据 6：反例不许退化成注释）")
        void unexecutableCounterIsRejected() {
            Playbook body = draftBody();
            body.setCounterJson("除非客户要零裁");

            assertThatThrownBy(() -> playbookService.createDraft(body))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("反例不可执行");
            verify(playbookMapper, never()).insert(any(Playbook.class));
        }

        @Test
        @DisplayName("按岗位生效却没指名岗位 ⇒ 422（否则静默变成全企业生效）")
        void roleScopeRequiresScopeRole() {
            Playbook body = draftBody();
            body.setScope("role");

            assertThatThrownBy(() -> playbookService.createDraft(body))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("必须指名岗位");
        }

        @Test
        @DisplayName("正解为空 ⇒ 422")
        void blankCorrectIsRejected() {
            Playbook body = draftBody();
            body.setCorrectText("  ");

            assertThatThrownBy(() -> playbookService.createDraft(body))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("正解");
        }
    }

    @Nested
    @DisplayName("状态迁移：CAS + 审计")
    class Transitions {

        @Test
        @DisplayName("审核通过：CAS 命中 1 行 ⇒ 返回 active 且留一条 activate 审计")
        void activateWritesAudit() {
            when(playbookMapper.activateIfDraft(eq("pb_1"), eq(7L), isNull(), any(OffsetDateTime.class)))
                    .thenReturn(1);
            Playbook after = Playbook.builder().id("pb_1").tenantId(7L).state("active")
                    .correctText("整卷优先").build();
            when(playbookMapper.selectOne(any())).thenReturn(after);

            Playbook result = playbookService.activate("pb_1");

            assertThat(result.getState()).isEqualTo("active");
            verify(auditLogService).recordLog(
                    eq(7L), isNull(), isNull(), eq("activate"), eq("playbook"), isNull(),
                    eq("pb_1"), eq("整卷优先"), any(), isNull(), isNull());
        }

        @Test
        @DisplayName("CAS 命中 0 行 ⇒ 冲突（不存在 / 跨租户 / 已被别人处置过），不是静默成功")
        void activateConflictWhenCasMisses() {
            when(playbookMapper.activateIfDraft(eq("pb_1"), eq(7L), isNull(), any(OffsetDateTime.class)))
                    .thenReturn(0);

            assertThatThrownBy(() -> playbookService.activate("pb_1"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("状态已变化");
            verify(auditLogService, never()).recordLog(
                    any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        }

        @Test
        @DisplayName("退役：CAS 命中 1 行 ⇒ retired 且留一条 retire 审计")
        void retireWritesAudit() {
            when(playbookMapper.retireIfActive(eq("pb_1"), eq(7L), isNull(), any(OffsetDateTime.class)))
                    .thenReturn(1);
            Playbook after = Playbook.builder().id("pb_1").tenantId(7L).state("retired")
                    .correctText("整卷优先").build();
            when(playbookMapper.selectOne(any())).thenReturn(after);

            Playbook result = playbookService.retire("pb_1");

            assertThat(result.getState()).isEqualTo("retired");
            verify(auditLogService).recordLog(
                    eq(7L), isNull(), isNull(), eq("retire"), eq("playbook"), isNull(),
                    eq("pb_1"), eq("整卷优先"), any(), isNull(), isNull());
        }
    }

    @Nested
    @DisplayName("条件语言写面校验（与 Python 读面同一张算子表）")
    class Conditions {

        @Test
        @DisplayName("合法条件零问题；组合条件递归校验")
        void validConditionsPass() {
            assertThat(PlaybookConditionValidator.validateJson(TRIGGER)).isEqualTo(List.of());
            assertThat(PlaybookConditionValidator.validateJson(
                    "{\"all\":[" + TRIGGER + ",{\"not\":{\"field\":\"role\",\"op\":\"exists\"}}]}"))
                    .isEqualTo(List.of());
        }

        @Test
        @DisplayName("自由文本 / 未知算子 / 空条件 / 类型不对 ⇒ 具名问题清单")
        void badConditionsAreNamed() {
            assertThat(PlaybookConditionValidator.validateJson("\"整卷优先\""))
                    .containsExactly("条件必须是 JSON 对象，实际是 STRING");
            assertThat(PlaybookConditionValidator.validateJson(""))
                    .containsExactly("条件是空对象");
            assertThat(PlaybookConditionValidator.validateJson(TRIGGER.replace("in", "类似")))
                    .anyMatch(p -> p.contains("未知算子 类似"));
            assertThat(PlaybookConditionValidator.validateJson(
                    "{\"field\":\"intent\",\"op\":\"in\",\"value\":\"quote\"}"))
                    .containsExactly("算子 in 的 value 必须是非空数组");
        }

        @Test
        @DisplayName("算子白名单恰为八项且顺序固定（Python 侧同表，对账判据守着）")
        void operatorWhitelistIsExact() {
            assertThat(PlaybookConditionValidator.OPS).containsExactly(
                    "eq", "ne", "in", "not_in", "contains", "not_contains", "exists", "not_exists");
        }
    }
}
