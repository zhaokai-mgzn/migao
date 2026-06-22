package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.*;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * CustomerService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class CustomerServiceTest {

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

    private CustomerProfile testProfile;
    private CustomerTag testTag;

    @BeforeEach
    void setUp() {
        testProfile = CustomerProfile.builder()
                .id("cust-001")
                .tenantId(1L)
                .wechatOpenid("openid_123")
                .wechatNickname("测试客户")
                .phone("13800138000")
                .vipLevel("normal")
                .customerStatus("active")
                .lifecycleStage("new")
                .sourceChannel("wechat_mini")
                .totalOrders(0)
                .totalConsumption(BigDecimal.ZERO)
                .registeredAt(OffsetDateTime.now())
                .build();

        testTag = CustomerTag.builder()
                .id("tag-001")
                .tenantId(1L)
                .name("VIP客户")
                .color("#FF0000")
                .tagType("manual")
                .hitCount(0)
                .build();
    }

    // ======================== 客户列表查询测试 ========================

    @Test
    @DisplayName("分页查询客户列表 - 默认分页")
    void getCustomerPage_DefaultPagination() {
        // given
        Page<CustomerProfile> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testProfile));
        mockPage.setTotal(1);

        when(customerProfileMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // when
        PageResponse<CustomerProfile> result = customerService.getCustomerPage(1, 20, null, null, null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getWechatNickname()).isEqualTo("测试客户");
    }

    @Test
    @DisplayName("分页查询客户列表 - 带筛选条件")
    void getCustomerPage_WithFilters() {
        // given
        Page<CustomerProfile> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(testProfile));
        mockPage.setTotal(1);

        when(customerProfileMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // when
        PageResponse<CustomerProfile> result = customerService.getCustomerPage(
                1, 10, "wechat_mini", "normal", "测试", 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
        verify(customerProfileMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("分页查询客户列表 - 空结果")
    void getCustomerPage_EmptyResult() {
        // given
        Page<CustomerProfile> emptyPage = new Page<>(1, 20);
        emptyPage.setRecords(List.of());
        emptyPage.setTotal(0);

        when(customerProfileMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(emptyPage);

        // when
        PageResponse<CustomerProfile> result = customerService.getCustomerPage(1, 20, null, null, null, 1L);

        // then
        assertThat(result.getTotal()).isEqualTo(0);
        assertThat(result.getItems()).isEmpty();
    }

    // ======================== 客户详情测试 ========================

    @Test
    @DisplayName("查询客户详情 - 成功")
    void getCustomerDetail_Success() {
        // given
        when(customerProfileMapper.selectById("cust-001")).thenReturn(testProfile);
        when(customerTagMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testTag));
        when(orderMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(sessionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

        // when
        Map<String, Object> detail = customerService.getCustomerDetail("cust-001");

        // then
        assertThat(detail).isNotNull();
        assertThat(detail).containsKey("profile");
        assertThat(detail).containsKey("tags");
        assertThat(detail).containsKey("orders");
        assertThat(detail).containsKey("sessions");
        assertThat(detail.get("profile")).isEqualTo(testProfile);
    }

    @Test
    @DisplayName("查询客户详情 - 客户不存在")
    void getCustomerDetail_NotFound() {
        // given
        when(customerProfileMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> customerService.getCustomerDetail("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 更新客户档案测试 ========================

    @Test
    @DisplayName("更新客户档案 - 成功")
    void updateCustomer_Success() {
        // given
        CustomerProfile updateData = CustomerProfile.builder()
                .phone("13900139000")
                .wechatNickname("新昵称")
                .vipLevel("vip1")
                .build();

        when(customerProfileMapper.selectById("cust-001")).thenReturn(testProfile);
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);

        // when
        CustomerProfile result = customerService.updateCustomer("cust-001", updateData);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getPhone()).isEqualTo("13900139000");
        assertThat(result.getWechatNickname()).isEqualTo("新昵称");
        assertThat(result.getVipLevel()).isEqualTo("vip1");
        verify(customerProfileMapper).updateById(any(CustomerProfile.class));
    }

    @Test
    @DisplayName("更新客户档案 - 客户不存在")
    void updateCustomer_NotFound() {
        // given
        CustomerProfile updateData = CustomerProfile.builder().phone("13900139000").build();
        when(customerProfileMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> customerService.updateCustomer("nonexistent", updateData))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("更新客户档案 - 仅更新非空字段")
    void updateCustomer_PartialUpdate() {
        // given
        CustomerProfile updateData = CustomerProfile.builder()
                .gender("male")
                .regionProvince("广东")
                .build();

        when(customerProfileMapper.selectById("cust-001")).thenReturn(testProfile);
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);

        // when
        CustomerProfile result = customerService.updateCustomer("cust-001", updateData);

        // then
        assertThat(result.getGender()).isEqualTo("male");
        assertThat(result.getRegionProvince()).isEqualTo("广东");
        // 原有字段保持不变
        assertThat(result.getPhone()).isEqualTo("13800138000");
    }

    // ======================== 标签管理测试 ========================

    @Test
    @DisplayName("创建客户标签 - 成功")
    void createTag_Success() {
        // given
        CustomerTag newTag = CustomerTag.builder()
                .name("新标签")
                .tenantId(1L)
                .color("#00FF00")
                .build();

        when(customerTagMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(customerTagMapper.insert(any(CustomerTag.class))).thenReturn(1);

        // when
        CustomerTag result = customerService.createTag(newTag);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("新标签");
        assertThat(result.getTagType()).isEqualTo("manual");
        assertThat(result.getHitCount()).isEqualTo(0);
        verify(customerTagMapper).insert(any(CustomerTag.class));
    }

    @Test
    @DisplayName("创建客户标签 - 名称已存在")
    void createTag_DuplicateName() {
        // given
        CustomerTag newTag = CustomerTag.builder()
                .name("VIP客户")
                .tenantId(1L)
                .build();

        when(customerTagMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testTag);

        // when & then
        assertThatThrownBy(() -> customerService.createTag(newTag))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("标签名称已存在");
    }

    @Test
    @DisplayName("删除客户标签 - 成功")
    void deleteTag_Success() {
        // given
        when(customerTagMapper.selectById("tag-001")).thenReturn(testTag);
        when(customerTagMapper.deleteById("tag-001")).thenReturn(1);

        // when
        customerService.deleteTag("tag-001");

        // then
        verify(customerTagMapper).deleteById("tag-001");
    }

    @Test
    @DisplayName("删除客户标签 - 标签不存在")
    void deleteTag_NotFound() {
        // given
        when(customerTagMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> customerService.deleteTag("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 创建客户档案测试 ========================

    @Test
    @DisplayName("创建客户档案 - 成功，设置默认值")
    void createCustomer_Success() {
        // given
        CustomerProfile newProfile = CustomerProfile.builder()
                .tenantId(1L)
                .wechatNickname("新客户")
                .phone("13900139000")
                .sourceChannel("wechat_mini")
                .build();

        when(customerProfileMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(customerProfileMapper.insert(any(CustomerProfile.class))).thenAnswer(invocation -> {
            CustomerProfile p = invocation.getArgument(0);
            p.setId("cust-new");
            return 1;
        });

        // when
        CustomerProfile result = customerService.createCustomer(newProfile);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getId()).isEqualTo("cust-new");
        assertThat(result.getVipLevel()).isEqualTo("normal");
        assertThat(result.getCustomerStatus()).isEqualTo("active");
        assertThat(result.getLifecycleStage()).isEqualTo("new");
        assertThat(result.getTotalOrders()).isEqualTo(0);
        assertThat(result.getTotalConsumption()).isEqualByComparingTo(java.math.BigDecimal.ZERO);
        verify(customerProfileMapper).insert(any(CustomerProfile.class));
    }

    @Test
    @DisplayName("创建客户档案 - 手机号重复")
    void createCustomer_DuplicatePhone() {
        // given
        CustomerProfile newProfile = CustomerProfile.builder()
                .tenantId(1L)
                .phone("13800138000")
                .wechatNickname("新客户")
                .build();

        when(customerProfileMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProfile);

        // when & then
        assertThatThrownBy(() -> customerService.createCustomer(newProfile))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("该手机号已存在客户档案");
    }

    // ======================== 从会话创建客户测试 ========================

    @Test
    @DisplayName("从会话创建客户 - 新客户，自动创建")
    void createFromSession_NewCustomer() {
        // given: openid 不存在
        when(customerProfileMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(customerProfileMapper.insert(any(CustomerProfile.class))).thenAnswer(invocation -> {
            CustomerProfile p = invocation.getArgument(0);
            p.setId("cust-session-new");
            return 1;
        });

        // when
        CustomerProfile result = customerService.createFromSession(1L, "openid_new", "新客户昵称", "wechat_mini");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getWechatOpenid()).isEqualTo("openid_new");
        assertThat(result.getWechatNickname()).isEqualTo("新客户昵称");
        assertThat(result.getSourceChannel()).isEqualTo("wechat_mini");
        assertThat(result.getVipLevel()).isEqualTo("normal");
        verify(customerProfileMapper).insert(any(CustomerProfile.class));
    }

    @Test
    @DisplayName("从会话创建客户 - 已存在，更新最后活跃时间")
    void createFromSession_ExistingCustomer() {
        // given: openid 已存在
        when(customerProfileMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProfile);
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);

        // when
        CustomerProfile result = customerService.createFromSession(1L, "openid_123", null, null);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getId()).isEqualTo("cust-001");
        verify(customerProfileMapper).updateById(any(CustomerProfile.class));
        verify(customerProfileMapper, never()).insert(any(CustomerProfile.class));
    }

    // ======================== 从订单创建客户测试 ========================

    @Test
    @DisplayName("从订单创建客户 - 新客户，自动建档")
    void createFromOrder_NewCustomer() {
        // given: 手机号不存在
        when(customerProfileMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(customerProfileMapper.insert(any(CustomerProfile.class))).thenAnswer(invocation -> {
            CustomerProfile p = invocation.getArgument(0);
            p.setId("cust-order-new");
            return 1;
        });

        // when
        CustomerProfile result = customerService.createFromOrder(1L, "李四", "13600136000", "浙江省杭州市");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getPhone()).isEqualTo("13600136000");
        assertThat(result.getSourceChannel()).isEqualTo("order");
        assertThat(result.getTotalOrders()).isEqualTo(1);
        assertThat(result.getAgentNotes()).contains("首单收货地址：");
        verify(customerProfileMapper).insert(any(CustomerProfile.class));
    }

    @Test
    @DisplayName("从订单创建客户 - 手机号为空，跳过建档")
    void createFromOrder_EmptyPhone() {
        // when: 手机号为空
        CustomerProfile result = customerService.createFromOrder(1L, "王五", "", "地址");

        // then
        assertThat(result).isNull();
        verify(customerProfileMapper, never()).insert(any(CustomerProfile.class));
        verify(customerProfileMapper, never()).selectOne(any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("从订单创建客户 - 手机号已存在，刷新活跃时间")
    void createFromOrder_ExistingCustomer() {
        // given: 手机号已存在
        when(customerProfileMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProfile);
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);

        // when
        CustomerProfile result = customerService.createFromOrder(1L, null, "13800138000", null);

        // then
        assertThat(result).isNotNull();
        verify(customerProfileMapper).updateById(any(CustomerProfile.class));
        verify(customerProfileMapper, never()).insert(any(CustomerProfile.class));
    }
}
