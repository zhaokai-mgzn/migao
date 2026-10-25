// case_ids: APP-001
package com.migao.admin.service;

import com.migao.admin.entity.Approval;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.OrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 超授信闸门的**审批出口**（issue #7374，P1-2 段 1）—— issue 判据第一条：
 * 「未审批的超阈动作**写面直接拒绝**；审批通过后同一动作放行」。
 *
 * <p>三格：① 没有审批 ⇒ 拒（错误信息要指路「怎么申请」）；② 有已通过审批且金额够 ⇒ 放行并**消费**；
 * ③ 没有审批组件（切片上下文 / 老单测）⇒ 退回**改前行为**（超限即拒），绝不静默放行。</p>
 */
@DisplayName("超授信闸门：无审批即拒 / 有审批放行且消费 / 无组件退回改前行为")
class CreditApprovalGateTest {

    private CustomerProfileMapper customerProfileMapper;
    private OrderMapper orderMapper;
    private ApprovalService approvalService;
    private CustomerService service;

    @BeforeEach
    void setUp() {
        customerProfileMapper = Mockito.mock(CustomerProfileMapper.class);
        orderMapper = Mockito.mock(OrderMapper.class);
        approvalService = Mockito.mock(ApprovalService.class);
        service = new CustomerService(customerProfileMapper, null, null, null, null, orderMapper, null, null, null);

        CustomerProfile profile = new CustomerProfile();
        profile.setId("c-1");
        profile.setTenantId(1L);
        profile.setPhone("13800000000");
        profile.setCreditLimit(new BigDecimal("1000"));
        when(customerProfileMapper.findFirstByPhone(1L, "13800000000")).thenReturn(profile);
        // 已欠 800 ⇒ 本单 500 时超出 300
        when(orderMapper.selectOutstandingTotal(1L, "13800000000")).thenReturn(new BigDecimal("800"));
    }

    private void withApprovalService() {
        org.springframework.test.util.ReflectionTestUtils.setField(service, "approvalService", approvalService);
    }

    @Test
    @DisplayName("🔴 超限且没有审批 ⇒ 写面直接拒绝，且错误信息里有「怎么申请」的路径")
    void overLimitWithoutApprovalIsRejected() {
        withApprovalService();
        when(approvalService.consume(any(), any(), any(), any())).thenReturn(null);

        assertThatThrownBy(() -> service.assertWithinCreditOrApproved(1L, "13800000000", new BigDecimal("500")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("超出客户授信额度")
                .hasMessageContaining("credit_override");
    }

    @Test
    @DisplayName("超限但有已通过审批（金额覆盖超出额）⇒ 放行并返回审批 id（供事后回填去向）")
    void overLimitWithApprovalPassesAndConsumes() {
        withApprovalService();
        when(approvalService.consume(eq(Approval.TYPE_CREDIT_OVERRIDE), eq("13800000000"),
                eq(new BigDecimal("300")), any())).thenReturn("ap-1");

        String used = service.assertWithinCreditOrApproved(1L, "13800000000", new BigDecimal("500"));

        assertThat(used).as("放行必须带上「用的是哪条审批」").isEqualTo("ap-1");
        // 消费时用**超出额**（不是订单全额）—— 批 300 就够过这一单
        Mockito.verify(approvalService).consume(eq(Approval.TYPE_CREDIT_OVERRIDE), eq("13800000000"),
                eq(new BigDecimal("300")), any());
    }

    @Test
    @DisplayName("额度内 ⇒ 不查审批、不消费（不给正常单增加一次写）")
    void withinLimitNeverTouchesApprovals() {
        withApprovalService();

        assertThat(service.assertWithinCreditOrApproved(1L, "13800000000", new BigDecimal("100"))).isNull();
        Mockito.verify(approvalService, Mockito.never()).consume(any(), any(), any(), any());
    }

    @Test
    @DisplayName("没有审批组件（切片上下文 / 老单测）⇒ 退回改前行为：超限即拒，绝不静默放行")
    void withoutApprovalBeanBehavesAsBefore() {
        // 故意不注入 approvalService
        assertThatThrownBy(() -> service.assertWithinCreditOrApproved(1L, "13800000000", new BigDecimal("500")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("超出客户授信额度");
    }

    @Test
    @DisplayName("旧签名（void）仍可用：内部委托到带审批出口的那条 ⇒ 老调用点零改动")
    void legacySignatureStillWorks() {
        withApprovalService();
        service.assertWithinCredit(1L, "13800000000", new BigDecimal("100"));
        // 没抛 = 通过
    }
}
