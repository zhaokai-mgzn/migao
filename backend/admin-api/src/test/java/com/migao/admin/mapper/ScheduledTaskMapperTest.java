// case_ids: AG-010
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.ScheduledTask;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.CALLS_REAL_METHODS;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * ScheduledTaskMapper 验证测试（V149，issue #6486 包 1）。
 *
 * <p>守的判据 = 三个查询方法的**口径**（它们把 where 条件只写一处 —— 扫描器与商家读面共用）：</p>
 * <ul>
 *   <li>{@code claimDueByTenant}（集群 P0-2）：<b>一条</b>语句 = 判定（{@code tenant_id} +
 *       {@code status='pending'} + {@code deleted=0} + {@code fire_at<=now}，有界 + {@code SKIP LOCKED}）
 *       + 占位（{@code status='firing'} + {@code claimed_by/claimed_at}）+ 取回（{@code RETURNING}）
 *       —— 少了 {@code status='pending'} ⇒ 已投递的行被**重领重投**；少了 {@code deleted=0} ⇒
 *       软删行被当成生效待办；少了 {@code LIMIT} ⇒ 一次扫描把全租户积压拉进内存；少了
 *       {@code SKIP LOCKED} ⇒ 输家阻塞在赢家行锁上（跨机房 RTT 下放大成串行点）；</li>
 *   <li>{@code markFiredIfClaimed} / {@code markFailedIfClaimed}：终态 CAS **必须**带
 *       {@code status='firing' AND claimed_by}（fencing token）—— 少了它 ⇒ 租约被回收后的僵尸实例
 *       会覆盖别人的投递结果；</li>
 *   <li>{@code reclaimStaleClaims}：跨租户 + <b>时效谓词</b>（{@code claimed_at < 死线}）⇒ 放回
 *       {@code pending} 并清空领取标记 —— 少了时效谓词 ⇒ 活实例的领取被误回收。</li>
 * </ul>
 * <p>{@code selectByDedupKey}：{@code tenant_id} + {@code dedup_key} + {@code deleted=0}
 * —— 少了 {@code tenant_id} 会跨租户串键；少了 {@code deleted=0} ⇒ 软删行占住幂等位（建单被误判「已存在」而静默不建）。</p>
 */
@DisplayName("ScheduledTaskMapper 验证（V149 / issue #6486 包 1）")
class ScheduledTaskMapperTest {

    private static final OffsetDateTime NOW = OffsetDateTime.parse("2026-10-07T12:00:00+08:00");

    /**
     * LambdaQueryWrapper 的列名解析要走 MyBatis-Plus 的 TableInfo 缓存 —— 纯单测里没有 MP 运行时
     * ⇒ 不初始化会抛「can not find lambda cache for this entity」，断言会退化成**错误**而不是结论
     * （既有先例：CuttingHeightConfigMapperTest）。
     */
    @BeforeAll
    static void initTableInfo() {
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""), ScheduledTask.class);
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由租户拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(ScheduledTaskMapper.class))
                .as("ScheduledTaskMapper should extend BaseMapper<ScheduledTask>")
                .isTrue();
    }

    @Test
    @DisplayName("claimDueByTenant：一条语句完成判定+占位+取回（pending / deleted=0 / 到期 / 有界 / SKIP LOCKED / RETURNING firing）")
    void claimDueByTenantIsOneAtomicStatement() throws Exception {
        Method m = ScheduledTaskMapper.class.getMethod("claimDueByTenant",
                Long.class, OffsetDateTime.class, int.class, String.class);
        String sql = annotationSql(m);
        String upper = sql.toUpperCase();

        assertThat(upper).as("必须是写面（UPDATE）—— 改前的前半段是普通 SELECT，无任何占位")
                .contains("UPDATE SCHEDULED_TASKS");
        assertThat(upper).as("且仍然只有**一条**语句（CTE 内 UPDATE + SELECT 同一事务）")
                .contains("WITH PICKED AS");
        assertThat(sql).as("领取条件：只领 pending（fired 不得重投）").contains("status = 'pending'");
        assertThat(sql).as("软删行不是生效待办").contains("deleted = 0");
        assertThat(sql).as("到期判定 fire_at <= now").contains("fire_at <= #{now}");
        assertThat(sql).as("有界（疲劳控制）：一次不把全租户积压拉进内存")
                .containsIgnoringCase("LIMIT #{limit}");
        assertThat(sql).as("输家不阻塞：SKIP LOCKED（跨机房 RTT 下不变成串行点）")
                .containsIgnoringCase("FOR UPDATE SKIP LOCKED");
        assertThat(sql).as("占位 = firing + 领取者/时刻（同一行只有一个实例领得到）")
                .contains("status = 'firing'")
                .contains("claimed_by = #{claimedBy}")
                .contains("claimed_at = #{now}");
        assertThat(upper).as("只回本次真领到的行（副作用绑定「真正改了行」）").contains("RETURNING");
        assertThat(sql).as("租户条件**显式**写出（不靠拦截器替我加）").contains("tenant_id = #{tenantId}");
        assertThat(m.getAnnotation(InterceptorIgnore.class))
                .as("定制 SQL 必须标 @InterceptorIgnore（显式 tenant_id 已写）").isNotNull();
    }

    @Test
    @DisplayName("markFired/markFailed：终态 CAS 带 status='firing' + claimed_by（fencing token，防僵尸覆盖）")
    void terminalCasIsFencedByClaimOwner() throws Exception {
        Method fired = ScheduledTaskMapper.class.getMethod("markFiredIfClaimed",
                String.class, Long.class, String.class, OffsetDateTime.class);
        Method failed = ScheduledTaskMapper.class.getMethod("markFailedIfClaimed",
                String.class, Long.class, String.class, OffsetDateTime.class);

        String firedSql = annotationSql(fired);
        assertThat(firedSql).as("终态 = fired").contains("status = 'fired'");
        assertThat(firedSql).as("只改「我领到且仍在 firing」的行").contains("status = 'firing'")
                .contains("claimed_by = #{claimedBy}");
        assertThat(firedSql).as("租户条件显式").contains("tenant_id = #{tenantId}");

        String failedSql = annotationSql(failed);
        assertThat(failedSql).as("失败终态 = failed（不留在 pending 反复重投）").contains("status = 'failed'");
        assertThat(failedSql).as("同样带 fencing 谓词").contains("status = 'firing'")
                .contains("claimed_by = #{claimedBy}");
    }

    @Test
    @DisplayName("reclaimStaleClaims：跨租户 + 时效谓词（claimed_at < 死线）⇒ 放回 pending 并清空领取标记")
    void reclaimStaleClaimsIsTimePredicated() throws Exception {
        Method m = ScheduledTaskMapper.class.getMethod("reclaimStaleClaims",
                OffsetDateTime.class, OffsetDateTime.class);
        String sql = annotationSql(m);

        assertThat(sql).as("回收对象 = 超时的 firing").contains("status = 'firing'");
        assertThat(sql).as("时效谓词：领取还新鲜 ⇒ 0 行（活实例不被误回收）")
                .contains("claimed_at < #{staleBefore}");
        assertThat(sql).as("放回 pending，等下一轮重新领取").contains("status = 'pending'");
        assertThat(sql).as("清空领取标记（否则僵尸 token 还在）")
                .contains("claimed_by = NULL").contains("claimed_at = NULL");
        assertThat(m.getAnnotation(InterceptorIgnore.class))
                .as("回收跑在无租户上下文的调度线程上 ⇒ 必须标 @InterceptorIgnore")
                .isNotNull();
    }

    @Test
    @DisplayName("selectByDedupKey：按 (tenant_id, dedup_key, deleted=0) 查 —— 不跨租户、软删行不占位")
    @SuppressWarnings("unchecked")
    void selectByDedupKeyFiltersTenantKeyAndNotDeleted() {
        ScheduledTaskMapper mapper = mock(ScheduledTaskMapper.class, CALLS_REAL_METHODS);
        AtomicReference<Wrapper<ScheduledTask>> captured = new AtomicReference<>();
        when(mapper.selectOne(any())).thenAnswer(inv -> {
            captured.set(inv.getArgument(0));
            return null;
        });

        assertThat(mapper.selectByDedupKey(20L, "u-1:follow_up:1791500000")).isNull();

        Wrapper<ScheduledTask> wrapper = captured.get();
        assertThat(wrapper).as("selectByDedupKey 必须下发查询条件").isNotNull();
        String sql = wrapper.getSqlSegment();
        assertThat(sql).as("租户维：不同租户的同名键不得互相命中").contains("tenant_id");
        assertThat(sql).as("幂等键维").contains("dedup_key");
        assertThat(sql).as("软删行不占幂等位（否则建单被静默跳过）").contains("deleted");
        assertThat(((AbstractWrapper<?, ?, ?>) wrapper).getParamNameValuePairs().values())
                .contains(20L, 0, "u-1:follow_up:1791500000");
    }

    @Test
    @DisplayName("selectByTenant：status 缺省时**不**加状态条件（读面看全部）")
    @SuppressWarnings("unchecked")
    void selectByTenantSkipsStatusWhenNull() {
        ScheduledTaskMapper mapper = mock(ScheduledTaskMapper.class, CALLS_REAL_METHODS);
        AtomicReference<Wrapper<ScheduledTask>> captured = new AtomicReference<>();
        when(mapper.selectList(any())).thenAnswer(inv -> {
            captured.set(inv.getArgument(0));
            return List.of();
        });

        mapper.selectByTenant(20L, null, 200);

        String sql = captured.get().getSqlSegment();
        assertThat(sql).contains("tenant_id").contains("deleted");
        assertThat(sql).as("缺省 status ⇒ 不按状态过滤（全量读面）").doesNotContain("status");
    }

    /** 读 {@code @Select}/{@code @Update} 的 SQL 文本（静态口径判据用；多段字符串按空格拼）。 */
    private static String annotationSql(Method m) {
        String[] parts = m.isAnnotationPresent(Select.class)
                ? m.getAnnotation(Select.class).value()
                : m.getAnnotation(Update.class).value();
        return String.join(" ", parts);
    }
}
