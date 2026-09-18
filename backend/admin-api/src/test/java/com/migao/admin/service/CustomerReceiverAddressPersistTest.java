// case_ids: CU-009

package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 客户默认收货信息（收货人姓名 / 电话 / 详细地址）的**落库**契约（issue #4419）。
 *
 * 缺陷形态（修前）：客户管理页与米宝都能"填"收货信息，但 {@code customer_profiles} 里
 * **根本没有这三列**，{@code CustomerService.updateCustomer} 也没有对应的非空拷贝
 * ⇒ 下发后 HTTP 200 + 数据无处可落 = 「录入了但查不到」。
 * 与 issue #4115 的 craftMode 一族同形（工具/页面可写 + 服务层静默丢弃）。
 *
 * 本文件因此**不断言 setter 被调用**，而是断言**交给 Mapper 落库的实体内容**（效果层证据）：
 * 把三行 setXxx 删掉，本文件必须变红。
 */
@ExtendWith(MockitoExtension.class)
class CustomerReceiverAddressPersistTest {

    @InjectMocks
    private CustomerService customerService;

    @Mock
    private CustomerProfileMapper customerProfileMapper;

    @Mock
    private CustomerTagMapper customerTagMapper;

    @Mock
    private CustomerSegmentMapper customerSegmentMapper;

    @Mock
    private CustomerSegmentMemberMapper customerSegmentMemberMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private SessionMapper sessionMapper;

    @Mock
    private SessionMessageMapper sessionMessageMapper;

    private CustomerProfile existing;

    @BeforeEach
    void setUp() {
        existing = CustomerProfile.builder()
                .id("cust-recv-001")
                .tenantId(1L)
                .wechatNickname("张三")
                .phone("13800138000")
                .defaultReceiverName("张三")
                .defaultReceiverPhone("13800138000")
                .defaultReceiverAddress("浙江省杭州市西湖区文三路1号1幢101室")
                .totalOrders(0)
                .totalConsumption(BigDecimal.ZERO)
                .registeredAt(OffsetDateTime.now())
                .build();
    }

    private CustomerProfile capturedPersisted() {
        ArgumentCaptor<CustomerProfile> captor = ArgumentCaptor.forClass(CustomerProfile.class);
        verify(customerProfileMapper).updateById(captor.capture());
        return captor.getValue();
    }

    private void givenExisting() {
        when(customerProfileMapper.selectById("cust-recv-001")).thenReturn(existing);
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);
    }

    @Test
    @DisplayName("更新客户档案 - 收货人姓名/电话/详细地址三列必须真的进入落库实体（修前无处可落）")
    void updateCustomer_PersistsDefaultReceiverFields() {
        // given: 客户管理页「收货信息」卡片 / 米宝 customer_manage(update) 下发的 payload
        CustomerProfile updateData = CustomerProfile.builder()
                .defaultReceiverName("李四")
                .defaultReceiverPhone("13900139000")
                .defaultReceiverAddress("浙江省杭州市余杭区文一西路969号")
                .build();

        givenExisting();

        // when
        CustomerProfile result = customerService.updateCustomer("cust-recv-001", updateData);

        // then: 落库实体（而非返回值）逐列断言 —— 修前这三列在实体上都不存在
        CustomerProfile persisted = capturedPersisted();
        assertThat(persisted.getDefaultReceiverName())
                .as("收货人姓名必须落库（修前：customer_profiles 无此列 ⇒ 录了查不到）")
                .isEqualTo("李四");
        assertThat(persisted.getDefaultReceiverPhone())
                .as("收货人电话必须落库")
                .isEqualTo("13900139000");
        assertThat(persisted.getDefaultReceiverAddress())
                .as("收货详细地址必须落库")
                .isEqualTo("浙江省杭州市余杭区文一西路969号");
        // 返回值即落库实体（接口/工具回报以它为准，不得谎报）
        assertThat(result.getDefaultReceiverAddress()).isEqualTo("浙江省杭州市余杭区文一西路969号");
    }

    @Test
    @DisplayName("更新客户档案 - 三列为 null 时不覆盖既有收货信息（保持非空拷贝语义）")
    void updateCustomer_NullReceiverFieldsKeepExistingValues() {
        // given: 既有档案已有收货信息，本次只改备注
        CustomerProfile updateData = CustomerProfile.builder().agentNotes("老客户，走物流专线").build();

        givenExisting();

        // when
        customerService.updateCustomer("cust-recv-001", updateData);

        // then: 未下发的三列保持原值
        CustomerProfile persisted = capturedPersisted();
        assertThat(persisted.getAgentNotes()).isEqualTo("老客户，走物流专线");
        assertThat(persisted.getDefaultReceiverName()).isEqualTo("张三");
        assertThat(persisted.getDefaultReceiverPhone()).isEqualTo("13800138000");
        assertThat(persisted.getDefaultReceiverAddress()).isEqualTo("浙江省杭州市西湖区文三路1号1幢101室");
    }

    @Test
    @DisplayName("更新客户档案 - 空白字符串不得把已录收货地址清空（防误清，与既有列同口径）")
    void updateCustomer_BlankReceiverFieldsDoNotWipeExisting() {
        CustomerProfile updateData = CustomerProfile.builder()
                .defaultReceiverName("   ")
                .defaultReceiverPhone("")
                .defaultReceiverAddress(" ")
                .build();

        givenExisting();

        customerService.updateCustomer("cust-recv-001", updateData);

        CustomerProfile persisted = capturedPersisted();
        assertThat(persisted.getDefaultReceiverName())
                .as("空白姓名不得覆盖既有收货人（清空语义未定义 ⇒ 一律不覆盖，issue #4419）")
                .isEqualTo("张三");
        assertThat(persisted.getDefaultReceiverPhone()).isEqualTo("13800138000");
        assertThat(persisted.getDefaultReceiverAddress())
                .as("空白地址不得把已录地址抹掉")
                .isEqualTo("浙江省杭州市西湖区文三路1号1幢101室");
    }

    @Test
    @DisplayName("更新客户档案 - 只改地址不动收货人姓名（三列互相独立）")
    void updateCustomer_AddressOnlyUpdateDoesNotTouchReceiverName() {
        CustomerProfile updateData = CustomerProfile.builder()
                .defaultReceiverAddress("江苏省苏州市吴中区越溪街道1号")
                .build();

        givenExisting();

        customerService.updateCustomer("cust-recv-001", updateData);

        CustomerProfile persisted = capturedPersisted();
        assertThat(persisted.getDefaultReceiverAddress()).isEqualTo("江苏省苏州市吴中区越溪街道1号");
        assertThat(persisted.getDefaultReceiverName()).isEqualTo("张三");
        assertThat(persisted.getDefaultReceiverPhone()).isEqualTo("13800138000");
    }
}
