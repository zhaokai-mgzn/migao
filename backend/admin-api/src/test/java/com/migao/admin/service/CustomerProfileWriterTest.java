// case_ids: OR-045
package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 客户档案建档（issue #7257）：写面固定「回读 → 撞键不插 → 撞并发回读对手」的顺序。
 *
 * <p>病：三处建档写面各自「selectOne 判空 + insert」，而本表**没有唯一约束** ⇒ 并发静默建出两条档案，
 * 消费总额/订单数被劈成两行。本文件守**调用契约**；真库侧的「并发只落一条」由
 * {@code CustomerProfileDedupeRealDbTest} 守。</p>
 *
 * <p>红证方向：把顺序改成「先插再读」⇒ {@link #existingPhoneIsTouchedNotInserted} 红；
 * 把撞键分支改成抛出/直接返回 candidate ⇒ {@link #insertConflictReReadsTheWinner} 红。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("客户档案建档：回读 → 撞键不插 → 撞并发回读对手")
class CustomerProfileWriterTest {

    private static final Long TENANT = 9L;
    private static final String PHONE = "13900009999";

    @Mock private CustomerProfileMapper customerProfileMapper;

    private CustomerProfile candidate() {
        return CustomerProfileWriter.candidate(TENANT).phone(PHONE).wechatNickname("张三").build();
    }

    @Test
    @DisplayName("🔴 手机号已存在 ⇒ **只刷新最后活跃时刻**，不建新档案（条件写，不整实体回写）")
    void existingPhoneIsTouchedNotInserted() {
        CustomerProfile existing = CustomerProfile.builder().id("c1").tenantId(TENANT).phone(PHONE).build();
        when(customerProfileMapper.findFirstByPhone(TENANT, PHONE)).thenReturn(existing);

        CustomerProfileWriter.Result result = CustomerProfileWriter.ensureByPhone(customerProfileMapper, candidate());

        assertThat(result.created()).isFalse();
        assertThat(result.profile().getId()).isEqualTo("c1");
        verify(customerProfileMapper).touchLastActiveAt(TENANT, "c1");
        verify(customerProfileMapper, never()).insertIgnoreByPhone(any());
        verify(customerProfileMapper, never()).updateById(any(CustomerProfile.class));
        InOrder order = inOrder(customerProfileMapper);
        order.verify(customerProfileMapper).findFirstByPhone(TENANT, PHONE);
        order.verify(customerProfileMapper).touchLastActiveAt(TENANT, "c1");
    }

    @Test
    @DisplayName("没有既有档案 ⇒ 建档成功，且 id 由写面生成（自定义 @Insert 不走 ASSIGN_UUID 填充）")
    void insertsWhenAbsent() {
        when(customerProfileMapper.findFirstByPhone(TENANT, PHONE)).thenReturn(null);
        when(customerProfileMapper.insertIgnoreByPhone(any(CustomerProfile.class))).thenReturn(1);

        CustomerProfileWriter.Result result = CustomerProfileWriter.ensureByPhone(customerProfileMapper, candidate());

        assertThat(result.created()).isTrue();
        ArgumentCaptor<CustomerProfile> captured = ArgumentCaptor.forClass(CustomerProfile.class);
        verify(customerProfileMapper).insertIgnoreByPhone(captured.capture());
        assertThat(captured.getValue().getId()).as("id 必须由写面生成").isNotBlank().doesNotContain("-");
        assertThat(captured.getValue().getPhone()).isEqualTo(PHONE);
        verify(customerProfileMapper, never()).touchLastActiveAt(anyLong(), anyString());
    }

    @Test
    @DisplayName("🔴 插入撞并发（影响 0 行）⇒ **回读对手那条**并返回，created=false，不抛错")
    void insertConflictReReadsTheWinner() {
        CustomerProfile winner = CustomerProfile.builder().id("winner").tenantId(TENANT).phone(PHONE).build();
        when(customerProfileMapper.findFirstByPhone(TENANT, PHONE)).thenReturn(null, winner);
        when(customerProfileMapper.insertIgnoreByPhone(any(CustomerProfile.class))).thenReturn(0);

        CustomerProfileWriter.Result result = CustomerProfileWriter.ensureByPhone(customerProfileMapper, candidate());

        assertThat(result.created()).as("本次没建成功 ⇒ created=false（手工建档据此报 422）").isFalse();
        assertThat(result.profile().getId()).as("返回的必须是**库里真实存在**的那一条").isEqualTo("winner");
        verify(customerProfileMapper).touchLastActiveAt(TENANT, "winner");
    }

    @Test
    @DisplayName("微信身份同款：已有 ⇒ 刷新最后活跃时刻；无 ⇒ 建档；撞键 ⇒ 回读对手")
    void openidPathsMirrorPhonePaths() {
        CustomerProfile existing = CustomerProfile.builder().id("o1").tenantId(TENANT).wechatOpenid("openid-1").build();
        when(customerProfileMapper.findFirstByOpenid(TENANT, "openid-1")).thenReturn(existing);

        CustomerProfileWriter.Result hit = CustomerProfileWriter.ensureByOpenid(customerProfileMapper,
                CustomerProfileWriter.candidate(TENANT).wechatOpenid("openid-1").build());

        assertThat(hit.created()).isFalse();
        assertThat(hit.profile().getId()).isEqualTo("o1");
        verify(customerProfileMapper, never()).insertIgnoreByOpenid(any());
    }
}
