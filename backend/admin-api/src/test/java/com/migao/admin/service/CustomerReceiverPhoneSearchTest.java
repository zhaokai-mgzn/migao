// case_ids: CU-001, CU-009

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.*;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 客户列表关键词搜索必须能命中「默认收货电话」（issue #4436，跟随 #4419）。
 *
 * 缺陷形态（修前）：发货页按**订单收货电话**反查客户档案，而后端 keyword 只 LIKE
 * `wechat_nickname` / `phone`（**账户手机号**）—— 客户档案的「默认收货电话」
 * （`default_receiver_phone`，V70）不在搜索列里 ⇒ 收货电话 ≠ 账户手机号的客户
 * **查不到** ⇒ 常用物流方式/公司静默带不出（回退默认值、不报错，用户以为"录了没用上"）。
 *
 * 本文件断言的是**交给 Mapper 的 wrapper 的 SQL 段**（效果层证据，与 OrderServiceTest
 * 的 `getSqlSegment()` 同口径）：把新增的那一行 `or().like(defaultReceiverPhone)` 删掉，
 * 本文件必须变红。
 */
@ExtendWith(MockitoExtension.class)
class CustomerReceiverPhoneSearchTest {

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

    @BeforeAll
    static void initTableInfo() {
        // 纯单测环境需手动初始化 MP 实体元数据（否则 LambdaQueryWrapper 无法解析列名；
        // 与 KnowledgeCardMapperTest 同一处置）
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, CustomerProfile.class);
    }

    /** 跑一次列表查询并返回交给 Mapper 的 wrapper。 */
    private LambdaQueryWrapper<CustomerProfile> wrapperFor(String keyword) {
        when(customerProfileMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(new Page<>(1, 10));
        customerService.getCustomerPage(1, 10, null, null, keyword, 1L);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<LambdaQueryWrapper<CustomerProfile>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(customerProfileMapper).selectPage(any(Page.class), captor.capture());
        return captor.getValue();
    }

    @Test
    @DisplayName("关键词搜索同时匹配 微信昵称 / 账户手机号 / 默认收货电话（修前缺第三列）")
    void keywordSearchCoversReceiverPhone() {
        String sql = wrapperFor("13700137000").getSqlSegment();

        assertThat(sql)
                .as("原有两列不得回归（关键词搜索的基本盘）")
                .contains("wechat_nickname")
                .contains("phone");
        assertThat(sql)
                .as("默认收货电话必须可搜 —— 否则「收货电话≠账户手机号」的客户在发货页反查不到，"
                        + "常用物流静默带不出（issue #4436）")
                .contains("default_receiver_phone");
    }

    @Test
    @DisplayName("关键词搜索绑定值 = 用户输入的关键词（三列共用同一个值）")
    void keywordSearchBindsKeywordValue() {
        LambdaQueryWrapper<CustomerProfile> wrapper = wrapperFor("西湖区");
        String sql = wrapper.getSqlSegment();

        assertThat(sql).contains("wechat_nickname").contains("phone").contains("default_receiver_phone");
        assertThat(wrapper.getParamNameValuePairs().values())
                .as("关键词必须作为**参数值**绑定（LIKE 会包 %，故按包含判定），不是拼进 SQL 字面量")
                .anyMatch(v -> String.valueOf(v).contains("西湖区"));
    }

    @Test
    @DisplayName("无关键词时不加 like 条件（不得把空串当成通配搜索）")
    void blankKeywordAddsNoLikeCondition() {
        String sql = wrapperFor("   ").getSqlSegment();

        assertThat(sql == null ? "" : sql)
                .as("空白关键词应视为未提供 ⇒ 不产生任何 like 条件")
                .doesNotContain("wechat_nickname")
                .doesNotContain("default_receiver_phone");
    }
}
