// case_ids: AR-004
package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.OrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 客户域数据范围（issue #7372 段 2）—— 用户 2026-10-21 亲口裁定的口径：
 * 「加『客户负责人』字段，未指派的按『有单的客户』兜底」。
 *
 * <p>三条边界各自对应一个真实风险：</p>
 * <ol>
 *   <li><b>未指派 + 我出过单 ⇒ 可见</b>：存量客户全是未指派，若无兜底，业务员上线当天看不见任何客户
 *       —— 看起来像数据丢了。</li>
 *   <li><b>已指派给别人 ⇒ 不可见（哪怕我出过单）</b>：指派是明确的业务决定，不能被「出过单」覆盖，
 *       否则客户永远抢不回来。</li>
 *   <li><b>越权 = 不存在</b>：详情返回与「不存在」同一个 404，不泄露「这个客户存在」。</li>
 * </ol>
 */
@DisplayName("客户数据范围：负责人 / 未指派兜底 / 指派优先 / 越权=不存在")
class CustomerDataScopeTest {

    private CustomerProfileMapper customerProfileMapper;
    private OrderMapper orderMapper;
    private com.migao.admin.mapper.SessionMapper sessionMapper;
    private CustomerService service;

    @BeforeEach
    void setUp() {
        customerProfileMapper = Mockito.mock(CustomerProfileMapper.class);
        orderMapper = Mockito.mock(OrderMapper.class);
        // 详情读面会顺带取「最近会话」等旁路数据（mock 默认返回空列表即可）
        sessionMapper = Mockito.mock(com.migao.admin.mapper.SessionMapper.class);
        when(sessionMapper.selectList(any())).thenReturn(java.util.List.of());
        service = new CustomerService(customerProfileMapper, null, null, null, null, orderMapper, sessionMapper, null);
    }

    private CustomerProfile profile(String id, String owner, String phone) {
        CustomerProfile p = new CustomerProfile();
        p.setId(id);
        p.setTenantId(1L);
        p.setOwnerUserId(owner);
        p.setPhone(phone);
        return p;
    }

    @Test
    @DisplayName("自己是负责人 ⇒ 可见")
    void ownerSeesOwnCustomer() {
        when(customerProfileMapper.selectById("c1")).thenReturn(profile("c1", "u-1", "13800000001"));
        assertThat(service.getCustomerDetail("c1", "u-1")).containsKey("profile");
    }

    @Test
    @DisplayName("未指派 + 我出过单 ⇒ 可见（存量兜底，否则业务员看不见任何客户）")
    void unassignedWithMyOrderIsVisible() {
        when(customerProfileMapper.selectById("c2")).thenReturn(profile("c2", null, "13800000002"));
        when(orderMapper.selectCount(any())).thenReturn(2L);
        assertThat(service.getCustomerDetail("c2", "u-1")).containsKey("profile");
    }

    @Test
    @DisplayName("未指派 + 我没出过单 ⇒ 不可见（不是「所有未指派都给我看」）")
    void unassignedWithoutMyOrderIsInvisible() {
        when(customerProfileMapper.selectById("c3")).thenReturn(profile("c3", null, "13800000003"));
        when(orderMapper.selectCount(any())).thenReturn(0L);
        assertThatThrownBy(() -> service.getCustomerDetail("c3", "u-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("客户");
    }

    @Test
    @DisplayName("🔴 已指派给别人 ⇒ 不可见，哪怕我出过单（指派是业务决定，不能被兜底覆盖）")
    void assignedToOtherWinsOverMyOrders() {
        when(customerProfileMapper.selectById("c4")).thenReturn(profile("c4", "u-2", "13800000004"));
        assertThatThrownBy(() -> service.getCustomerDetail("c4", "u-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("客户");
        // 且**不该**去查单（指派已给出答案 ⇒ 多查一次是白花）
        Mockito.verify(orderMapper, Mockito.never()).selectCount(any());
    }

    @Test
    @DisplayName("租户级（范围 owner = null）⇒ 全部可见，零回归")
    void tenantScopeSeesEverything() {
        when(customerProfileMapper.selectById("c5")).thenReturn(profile("c5", "u-2", "13800000005"));
        assertThat(service.getCustomerDetail("c5", null)).containsKey("profile");
        assertThat(service.getCustomerDetail("c5")).containsKey("profile");
    }

    @Test
    @DisplayName("没有手机号的未指派客户 ⇒ 不可见（没有可归属的键，不猜）")
    void unassignedWithoutPhoneIsInvisible() {
        when(customerProfileMapper.selectById("c6")).thenReturn(profile("c6", null, null));
        assertThatThrownBy(() -> service.getCustomerDetail("c6", "u-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("客户");
    }

    @Test
    @DisplayName("指派负责人：写入走实体 setter + updateById（唯一写点，字段真值判据按 setter 识别）")
    void assignOwnerWritesThroughSetter() {
        CustomerProfile profile = profile("c7", null, "13800000007");
        when(customerProfileMapper.selectById("c7")).thenReturn(profile);
        when(customerProfileMapper.updateById(org.mockito.ArgumentMatchers.<CustomerProfile>any())).thenReturn(1);

        service.assignOwner("c7", "  u-9  ");

        Mockito.verify(customerProfileMapper).updateById(Mockito.argThat((CustomerProfile row) ->
                "u-9".equals(row.getOwnerUserId())));
    }

    @Test
    @DisplayName("撤回指派：传空 ⇒ 回到未指派（null 是业务态，不是被抹掉）")
    void clearOwnerFallsBackToUnassigned() {
        CustomerProfile profile = profile("c8", "u-1", "13800000008");
        when(customerProfileMapper.selectById("c8")).thenReturn(profile);
        when(customerProfileMapper.updateById(org.mockito.ArgumentMatchers.<CustomerProfile>any())).thenReturn(1);

        service.assignOwner("c8", "   ");

        Mockito.verify(customerProfileMapper).updateById(Mockito.argThat((CustomerProfile row) ->
                row.getOwnerUserId() == null));
    }

    @Test
    @DisplayName("指派到不存在的客户 ⇒ 404（不是静默成功）")
    void assignToMissingCustomerIsNotFound() {
        when(customerProfileMapper.selectById("nope")).thenReturn(null);
        assertThatThrownBy(() -> service.assignOwner("nope", "u-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("客户");
    }
}
