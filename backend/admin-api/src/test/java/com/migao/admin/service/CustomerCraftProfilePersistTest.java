// case_ids: CU-004, CU-008

package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 客户工艺画像 / 常用物流的**落库**契约（issue #4115，P0）。
 *
 * 缺陷形态（修前）：工具 {@code customer_manage(action=update)} 把
 * {@code craftMode/craftProfile/defaultLogisticsType/defaultLogisticsCompany} 列入可写字段并下发，
 * admin-api `CustomerService.updateCustomer` 的非空拷贝白名单里**没有这 4 列** ⇒
 * `updateById(existing)` 落下的是旧值 ⇒ HTTP 200 + 数据静默丢失 + 工具回报「客户档案已更新：craftMode」。
 * 单测/契约测试都抓不到（接口签名、字段名、返回码全部"正确"）。
 *
 * 本文件因此**不断言 setter 被调用**，而是断言**交给 Mapper 落库的实体内容**（效果层证据）：
 * 把 4 行 setXxx 注释掉，本文件必须变红。
 */
@ExtendWith(MockitoExtension.class)
class CustomerCraftProfilePersistTest {

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
                .id("cust-craft-001")
                .tenantId(1L)
                .wechatNickname("测试客户")
                .phone("13800138000")
                .craftMode("standard")
                .defaultLogisticsType("express")
                .defaultLogisticsCompany("顺丰")
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

    @Test
    @DisplayName("更新客户档案 - 工艺画像与常用物流 4 列必须真的进入落库实体（修前全部丢失）")
    void updateCustomer_PersistsCraftProfileAndLogistics() {
        // given: 工具下发的 payload（= customer_manage WRITABLE_FIELDS 里的 4 个 key）
        Map<String, Object> craftProfile = Map.of("openCount", 2, "isShaped", true);
        CustomerProfile updateData = CustomerProfile.builder()
                .craftMode("economy")
                .craftProfile(craftProfile)
                .defaultLogisticsType("logistics")
                .defaultLogisticsCompany("四季安")
                .build();

        when(customerProfileMapper.selectById("cust-craft-001")).thenReturn(existing);
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);

        // when
        CustomerProfile result = customerService.updateCustomer("cust-craft-001", updateData);

        // then: 落库实体（而非返回值）逐列断言 —— 修前这里全是旧值
        CustomerProfile persisted = capturedPersisted();
        assertThat(persisted.getCraftMode())
                .as("craftMode 必须落库（修前：非空拷贝白名单漏了这列 ⇒ 静默丢失）")
                .isEqualTo("economy");
        assertThat(persisted.getCraftProfile())
                .as("craftProfile JSON 必须落库")
                .isEqualTo(craftProfile);
        assertThat(persisted.getDefaultLogisticsType())
                .as("defaultLogisticsType 必须落库")
                .isEqualTo("logistics");
        assertThat(persisted.getDefaultLogisticsCompany())
                .as("defaultLogisticsCompany 必须落库")
                .isEqualTo("四季安");
        // 返回值即落库实体（工具/接口回报是以它为准的）
        assertThat(result.getCraftMode()).isEqualTo("economy");
        assertThat(result.getDefaultLogisticsCompany()).isEqualTo("四季安");
    }

    @ParameterizedTest(name = "craftMode={0} 合法值落库")
    @ValueSource(strings = {"standard", "economy", "self_quoted"})
    @DisplayName("更新客户档案 - craftMode 三个枚举值均可落库")
    void updateCustomer_ValidCraftModesPersisted(String craftMode) {
        CustomerProfile updateData = CustomerProfile.builder().craftMode(craftMode).build();

        when(customerProfileMapper.selectById("cust-craft-001")).thenReturn(existing);
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);

        customerService.updateCustomer("cust-craft-001", updateData);

        assertThat(capturedPersisted().getCraftMode()).isEqualTo(craftMode);
    }

    @Test
    @DisplayName("更新客户档案 - 4 列为空时不覆盖既有值（保持非空拷贝语义）")
    void updateCustomer_NullCraftFieldsKeepExistingValues() {
        // given: 既有档案已有工艺画像与物流偏好，本次只改手机号
        existing.setCraftProfile(Map.of("openCount", 3));
        CustomerProfile updateData = CustomerProfile.builder().phone("13900139000").build();

        when(customerProfileMapper.selectById("cust-craft-001")).thenReturn(existing);
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);

        // when
        customerService.updateCustomer("cust-craft-001", updateData);

        // then: 未下发的 4 列保持原值，下发的手机号生效（null 不覆盖）
        CustomerProfile persisted = capturedPersisted();
        assertThat(persisted.getPhone()).isEqualTo("13900139000");
        assertThat(persisted.getCraftMode()).isEqualTo("standard");
        assertThat(persisted.getCraftProfile()).isEqualTo(Map.of("openCount", 3));
        assertThat(persisted.getDefaultLogisticsType()).isEqualTo("express");
        assertThat(persisted.getDefaultLogisticsCompany()).isEqualTo("顺丰");
    }

    @Test
    @DisplayName("更新客户档案 - 非法 craftMode 被拒（400 + 可行动建议，且不落库）")
    void updateCustomer_InvalidCraftMode_Rejected() {
        // given: 非法枚举 + 一个合法字段（验证「不部分写入」）
        CustomerProfile updateData = CustomerProfile.builder()
                .phone("13900139000")
                .craftMode("xxx")
                .build();

        when(customerProfileMapper.selectById("cust-craft-001")).thenReturn(existing);

        // when & then: 显式拒绝（不是静默吞、不是落库存未知模式）
        assertThatThrownBy(() -> customerService.updateCustomer("cust-craft-001", updateData))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(bex.getHttpStatus())
                            .as("可行动的 400（不要让调用方按 5xx/异常处理）")
                            .isEqualTo(400);
                    assertThat(bex.getMessage()).contains("craftMode").contains("xxx");
                    assertThat(bex.getSuggestion())
                            .as("建议必须列出全部合法值，LLM 才能自修复")
                            .contains("standard").contains("economy").contains("self_quoted")
                            .contains("craftMode");
                });

        // 效果层：异常路径下整条更新不落库（无部分写入 = 无「部分成功」的假象）
        verify(customerProfileMapper, never()).updateById(any(CustomerProfile.class));
        assertThat(existing.getCraftMode())
                .as("非法值不得落到既有实体（更不得落库为未知模式）")
                .isEqualTo("standard");
    }

    @ParameterizedTest(name = "craftMode={0} 非法值被拒")
    @ValueSource(strings = {"xxx", "STANDARD", "省料", "economy;"})
    @DisplayName("更新客户档案 - 非法 craftMode 变体一律被拒（含大小写/中文/尾随字符）")
    void updateCustomer_InvalidCraftModeVariants_Rejected(String craftMode) {
        CustomerProfile updateData = CustomerProfile.builder().craftMode(craftMode).build();

        when(customerProfileMapper.selectById("cust-craft-001")).thenReturn(existing);

        assertThatThrownBy(() -> customerService.updateCustomer("cust-craft-001", updateData))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("craftMode");

        verify(customerProfileMapper, never()).updateById(any(CustomerProfile.class));
    }
}