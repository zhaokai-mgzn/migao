// case_ids: CU-009, OR-045

package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * issue #7711 单元判据：**认人**（手机号 + openid 一起认）与**补空**（补空不覆盖）的编排契约。
 *
 * <p>SQL 字符串只断言「写了哪几列 / 写的是哪条行」；「已有值不被覆盖」的语义在
 * {@code CustomerProfileIdentityRealDbTest}（真 PG）里判 —— mock 上看不到 COALESCE 的行为，
 * 在这里假装判它就是空断言。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("7711 客户档案身份收敛 + 订单信息补空（单元）")
class CustomerProfileIdentityServiceTest {

    private static final Long TENANT = 1L;
    private static final String PHONE = "13600136000";
    private static final String OPENID = "openid-x";

    @Mock
    private CustomerProfileMapper customerProfileMapper;

    @Mock
    private JdbcTemplate jdbcTemplate;

    @InjectMocks
    private CustomerProfileIdentityService identityService;

    // ==================== 认人：建档 / 收敛 ====================

    @Test
    @DisplayName("两键全空 ⇒ 不建档（旧行为每次插一条匿名档案，正是双档案病灶）")
    void ensure_noIdentityKeys_doesNotCreate() {
        CustomerProfile result = identityService.ensure(TENANT, null, "  ", null, true);

        assertThat(result).isNull();
        verifyNoInteractions(customerProfileMapper, jdbcTemplate);
    }

    @Test
    @DisplayName("两键都没命中 ⇒ 建档：种子（昵称/渠道/订单数）落进 candidate")
    void ensure_createsWhenMissing() {
        when(customerProfileMapper.findFirstByPhone(TENANT, PHONE)).thenReturn(null);
        when(customerProfileMapper.insertIgnoreByPhone(any(CustomerProfile.class))).thenReturn(1);

        CustomerProfile created = identityService.ensure(TENANT, PHONE, null,
                new CustomerProfileIdentityService.ProfileSeed("李四", "order", 1), true);

        assertThat(created.getPhone()).isEqualTo(PHONE);
        assertThat(created.getSourceChannel()).isEqualTo("order");
        assertThat(created.getTotalOrders()).isEqualTo(1);
        ArgumentCaptor<CustomerProfile> inserted = ArgumentCaptor.forClass(CustomerProfile.class);
        verify(customerProfileMapper).insertIgnoreByPhone(inserted.capture());
        assertThat(inserted.getValue().getWechatNickname()).isEqualTo("李四");
        verify(customerProfileMapper, never()).touchLastActiveAt(anyLong(), anyString());
    }

    @Test
    @DisplayName("只收敛不新建（手机号绑定路径）⇒ 两键都没命中时返回 null、绝不插行")
    void ensure_createIfMissingFalse_neverInserts() {
        when(customerProfileMapper.findFirstByPhone(TENANT, PHONE)).thenReturn(null);
        when(customerProfileMapper.findFirstByOpenid(TENANT, OPENID)).thenReturn(null);

        assertThat(identityService.ensure(TENANT, PHONE, OPENID, null, false)).isNull();

        verify(customerProfileMapper, never()).insertIgnoreByPhone(any(CustomerProfile.class));
        verify(customerProfileMapper, never()).insertIgnoreByOpenid(any(CustomerProfile.class));
    }

    @Test
    @DisplayName("命中既有档案且缺 openid ⇒ 条件补 openid + 刷新最后活跃")
    void ensure_existingProfile_fillsMissingIdentity() {
        CustomerProfile existing = profile("cust-1", null, PHONE);
        when(customerProfileMapper.findFirstByPhone(TENANT, PHONE)).thenReturn(existing);
        when(customerProfileMapper.findFirstByOpenid(TENANT, OPENID)).thenReturn(null);

        identityService.ensure(TENANT, PHONE, OPENID, null, true);

        verify(jdbcTemplate).update(startsWith("UPDATE customer_profiles SET phone"),
                any(), eq(OPENID), eq("cust-1"), eq(TENANT));
        verify(customerProfileMapper).touchLastActiveAt(TENANT, "cust-1");
    }

    @Test
    @DisplayName("两键各命中不同行 ⇒ 合并：引用迁移 → 删较晚那条 → 最后补身份键")
    void ensure_twoRowsForSamePerson_merges() {
        CustomerProfile keeper = profile("cust-a", null, PHONE);
        keeper.setWechatNickname("李四");
        CustomerProfile loser = profile("cust-b", OPENID, null);
        when(customerProfileMapper.findFirstByPhone(TENANT, PHONE)).thenReturn(keeper);
        when(customerProfileMapper.findFirstByOpenid(TENANT, OPENID)).thenReturn(loser);
        CustomerProfile merged = profile("cust-a", OPENID, PHONE);
        when(customerProfileMapper.selectById("cust-a")).thenReturn(merged);

        CustomerProfile result = identityService.ensure(TENANT, PHONE, OPENID, null, false);

        assertThat(result.getId()).as("keeper = 最早注册那条（与 findFirst* 同序）").isEqualTo("cust-a");
        assertThat(result.getWechatOpenid()).isEqualTo(OPENID);
        verify(customerProfileMapper).deleteById("cust-b");
        // 五张引用面全部改挂到 keeper
        verify(jdbcTemplate).update(contains("UPDATE sessions SET customer_id = ?"),
                eq("cust-a"), eq(TENANT), eq("cust-b"));
        verify(jdbcTemplate).update(contains("UPDATE agent_sessions SET customer_id = ?"),
                eq("cust-a"), eq(TENANT), eq("cust-b"));
        verify(jdbcTemplate).update(contains("UPDATE after_sales_tickets SET customer_id = ?"),
                eq("cust-a"), eq(TENANT), eq("cust-b"));
        verify(jdbcTemplate).update(contains("UPDATE customer_segment_members SET customer_id = ?"),
                eq("cust-a"), eq(TENANT), eq("cust-b"));
        verify(jdbcTemplate).update(contains("UPDATE customer_sku_prices SET customer_id = ?"),
                eq("cust-a"), eq(TENANT), eq("cust-b"));
        // 顺序即安全顺序：先删 loser 再补身份键（否则撞 V167 部分唯一索引）
        InOrder inOrder = inOrder(customerProfileMapper, jdbcTemplate);
        inOrder.verify(customerProfileMapper).deleteById("cust-b");
        inOrder.verify(jdbcTemplate).update(startsWith("UPDATE customer_profiles SET phone"),
                any(), eq(OPENID), eq("cust-a"), eq(TENANT));
    }

    // ==================== 补空：订单信息进档案 ====================

    @Test
    @DisplayName("档案收货/物流全空 ⇒ 写一次，覆盖五列（收货人/电话/地址/物流方式/物流公司）")
    void fillOrderContact_writesOnceWhenBlank() {
        CustomerProfile blank = CustomerProfile.builder().id("cust-1").tenantId(TENANT).build();

        identityService.fillOrderContact(blank, TENANT, "李四", PHONE, "浙江省杭州市", "express", "顺丰");

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).update(sql.capture(), any(), any(), any(), any(), any(), any(), any());
        assertThat(sql.getValue())
                .contains("default_receiver_name", "default_receiver_phone", "default_receiver_address",
                        "default_logistics_type", "default_logistics_company")
                .contains("COALESCE(NULLIF(BTRIM(");
    }

    @Test
    @DisplayName("档案五列都已有值 ⇒ 一次写库都不发生（订单是高频路径）")
    void fillOrderContact_allPresent_skips() {
        CustomerProfile filled = CustomerProfile.builder()
                .id("cust-1")
                .tenantId(TENANT)
                .defaultReceiverName("王五")
                .defaultReceiverPhone("13900139000")
                .defaultReceiverAddress("客服手工维护的地址")
                .defaultLogisticsType("car")
                .defaultLogisticsCompany("德邦")
                .build();

        identityService.fillOrderContact(filled, TENANT, "李四", PHONE, "浙江省杭州市", "express", "顺丰");

        verifyNoInteractions(jdbcTemplate);
    }

    @Test
    @DisplayName("订单没填物流（null）⇒ 物流两列不参与补空，只补确实有值的列")
    void fillOrderContact_nullLogistics_stillFillsContact() {
        CustomerProfile blank = CustomerProfile.builder().id("cust-1").tenantId(TENANT).build();

        identityService.fillOrderContact(blank, TENANT, "李四", PHONE, "浙江省杭州市", null, null);

        verify(jdbcTemplate).update(startsWith("UPDATE customer_profiles SET default_receiver_name"),
                eq("李四"), eq(PHONE), eq("浙江省杭州市"), eq(null), eq(null), eq("cust-1"), eq(TENANT));
    }

    @Test
    @DisplayName("profile 为 null（理论上不会发生）⇒ 静默跳过，不抛错")
    void fillOrderContact_nullProfile_skips() {
        identityService.fillOrderContact(null, TENANT, "李四", PHONE, "地址", "express", "顺丰");

        verifyNoInteractions(jdbcTemplate);
    }

    private static CustomerProfile profile(String id, String openid, String phone) {
        return CustomerProfile.builder()
                .id(id)
                .tenantId(TENANT)
                .wechatOpenid(openid)
                .phone(phone)
                .vipLevel("normal")
                .customerStatus("active")
                .lifecycleStage("new")
                .totalOrders(0)
                .totalConsumption(BigDecimal.ZERO)
                .registeredAt(OffsetDateTime.now())
                .build();
    }
}
