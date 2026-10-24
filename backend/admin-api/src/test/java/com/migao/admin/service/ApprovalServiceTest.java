// case_ids: APP-001
package com.migao.admin.service;

import com.migao.admin.dto.ApprovalRequest;
import com.migao.admin.entity.Approval;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ApprovalMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 审批服务（issue #7374 段 1）—— 四态流转 + 单次消费 + 「不能自批」。
 *
 * <p>三个最贵的错法各有一格：</p>
 * <ol>
 *   <li>申请人自己批自己（审批就失去意义）；</li>
 *   <li>已驳回/已撤回的还能被通过（闸门形同虚设）；</li>
 *   <li>一条超授信审批放行两单（批一次用多次）。</li>
 * </ol>
 */
@DisplayName("审批服务：提交/裁决/撤回/消费 四条路径的边界")
class ApprovalServiceTest {

    private ApprovalMapper approvalMapper;
    private ApprovalService service;

    private static final ApprovalService.Operator APPLICANT =
            new ApprovalService.Operator("u-applicant", "申请人");
    private static final ApprovalService.Operator APPROVER =
            new ApprovalService.Operator("u-approver", "审批人");

    @BeforeEach
    void setUp() {
        // Lambda 缓存：`LambdaUpdateWrapper` 需要 MyBatis-Plus 的实体元数据（纯单测里没有容器 ⇒ 手工建一次）。
        // 踩过的坑：不建则抛 `MybatisPlus can not find lambda cache for this entity` —— 那不是业务失败。
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, ""), Approval.class);
        approvalMapper = Mockito.mock(ApprovalMapper.class);
        service = new ApprovalService(approvalMapper);
    }

    private static ApprovalRequest request(String type, String ref, String amount) {
        ApprovalRequest request = new ApprovalRequest();
        request.setTenantId(1L);
        request.setObjectType(type);
        request.setObjectRef(ref);
        request.setObjectLabel("客户张三");
        request.setAmount(amount == null ? null : new BigDecimal(amount));
        request.setReason("客户急单，先发货");
        return request;
    }

    private Approval stored(String id, String status, String by, String amount) {
        return Approval.builder()
                .id(id).tenantId(1L).objectType(Approval.TYPE_CREDIT_OVERRIDE)
                .objectRef("13800000000").status(status).requestedBy(by)
                .amount(amount == null ? null : new BigDecimal(amount))
                .build();
    }

    @Test
    @DisplayName("提交：初始 pending + 带上申请人（留痕从第一刻开始）")
    void submitStartsPending() {
        when(approvalMapper.selectList(any())).thenReturn(List.of());

        var view = service.submit(request(Approval.TYPE_CREDIT_OVERRIDE, "13800000000", "500"), APPLICANT);

        assertThat(view.getStatus()).isEqualTo(ApprovalState.PENDING);
        assertThat(view.getRequestedBy()).isEqualTo("u-applicant");
        assertThat(view.getRequestedAt()).isNotNull();
        Mockito.verify(approvalMapper).insert(any(Approval.class));
    }

    @Test
    @DisplayName("提交：类型必须是五类之一（新增一类要改迁移 + 改判据）")
    void unknownTypeIsRejected() {
        assertThatThrownBy(() -> service.submit(request("discount", "x", "1"), APPLICANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("审批类型");
    }

    @Test
    @DisplayName("提交：同一对象只允许一个待审（否则两个审批人各批一次，谁生效说不清）")
    void duplicatePendingIsRejected() {
        when(approvalMapper.selectList(any())).thenReturn(List.of(stored("a-1", ApprovalState.PENDING, "u-applicant", "500")));

        assertThatThrownBy(() -> service.submit(request(Approval.TYPE_CREDIT_OVERRIDE, "13800000000", "600"), APPLICANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("待审");
    }

    @Test
    @DisplayName("🔴 不能批自己提交的申请")
    void cannotSelfApprove() {
        when(approvalMapper.selectById("a-1")).thenReturn(stored("a-1", ApprovalState.PENDING, "u-applicant", "500"));

        assertThatThrownBy(() -> service.decide("a-1", true, "同意", APPLICANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("自己提交");
    }

    @Test
    @DisplayName("🔴 已驳回的不能再被通过（CAS 落空 ⇒ 409 语义，不覆盖别人的结论）")
    void cannotApproveAlreadyDecided() {
        when(approvalMapper.selectById("a-2")).thenReturn(stored("a-2", ApprovalState.REJECTED, "u-applicant", "500"));

        assertThatThrownBy(() -> service.decide("a-2", true, "改判", APPROVER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已驳回");
    }

    @Test
    @DisplayName("裁决：CAS 落空（别人先批了）⇒ 明确报错，不静默覆盖")
    void concurrentDecisionLosesCas() {
        when(approvalMapper.selectById("a-3")).thenReturn(stored("a-3", ApprovalState.PENDING, "u-applicant", "500"));
        when(approvalMapper.update(any(), any())).thenReturn(0);

        assertThatThrownBy(() -> service.decide("a-3", true, "同意", APPROVER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("被别人裁决");
    }

    @Test
    @DisplayName("撤回：只有申请人本人能撤回")
    void onlyApplicantCanWithdraw() {
        when(approvalMapper.selectById("a-4")).thenReturn(stored("a-4", ApprovalState.PENDING, "u-applicant", "500"));

        assertThatThrownBy(() -> service.withdraw("a-4", APPROVER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("本人");
    }

    @Test
    @DisplayName("🔴 消费：金额不覆盖本次超出额 ⇒ 不给（批 5000 不能过 8000 的单）")
    void consumeRequiresEnoughAmount() {
        when(approvalMapper.selectList(any()))
                .thenReturn(List.of(stored("a-5", ApprovalState.APPROVED, "u-applicant", "100")));

        assertThat(service.consume(Approval.TYPE_CREDIT_OVERRIDE, "13800000000",
                new BigDecimal("500"), null)).isNull();
        Mockito.verify(approvalMapper, Mockito.never()).update(any(), any());
    }

    @Test
    @DisplayName("消费：金额够且未用 ⇒ 标记已用并返回审批 id（单次）")
    void consumeMarksUsed() {
        when(approvalMapper.selectList(any()))
                .thenReturn(List.of(stored("a-6", ApprovalState.APPROVED, "u-applicant", "1000")));
        when(approvalMapper.update(any(), any())).thenReturn(1);

        String id = service.consume(Approval.TYPE_CREDIT_OVERRIDE, "13800000000",
                new BigDecimal("500"), "order-1");

        assertThat(id).isEqualTo("a-6");
    }

    @Test
    @DisplayName("消费：审批没写金额 ⇒ 视为不限额（可空字段不猜 0）")
    void nullAmountMeansUnlimited() {
        when(approvalMapper.selectList(any()))
                .thenReturn(List.of(stored("a-7", ApprovalState.APPROVED, "u-applicant", null)));
        when(approvalMapper.update(any(), any())).thenReturn(1);

        assertThat(service.consume(Approval.TYPE_CREDIT_OVERRIDE, "13800000000",
                new BigDecimal("999999"), null)).isEqualTo("a-7");
    }

    @Test
    @DisplayName("消费：没有可用的审批 ⇒ null（调用方据此拒绝，不是抛在服务层里）")
    void consumeWithoutApprovalReturnsNull() {
        when(approvalMapper.selectList(any())).thenReturn(List.of());
        assertThat(service.consume(Approval.TYPE_CREDIT_OVERRIDE, "13800000000",
                new BigDecimal("1"), null)).isNull();
    }
}
