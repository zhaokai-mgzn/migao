// case_ids: AG-010
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.ScheduledTask;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

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
 *   <li>{@code selectDueByTenant}：{@code tenant_id} + {@code status='pending'} + {@code deleted=0}
 *       + {@code fire_at <= now}，且**有界**（{@code LIMIT}）—— 少了 {@code deleted=0} ⇒
 *       软删行被当生效待办（投递一条已取消的提醒）；少了 {@code status='pending'} ⇒
 *       {@code fired} 行被**重投**（疲劳控制失效）；少了 {@code LIMIT} ⇒ 一次扫描把全租户
 *       积压拉进内存；</li>
 *   <li>{@code selectByDedupKey}：{@code tenant_id} + {@code dedup_key} + {@code deleted=0}
 *       —— 少了 {@code tenant_id} 会跨租户串键；少了 {@code deleted=0} ⇒ 软删行占住幂等位
 *       （建单被误判「已存在」而静默不建）。</li>
 * </ul>
 */
@DisplayName("ScheduledTaskMapper 验证（V149 / issue #6486 包 1）")
class ScheduledTaskMapperTest {

    private static final OffsetDateTime NOW = OffsetDateTime.parse("2026-10-07T12:00:00+08:00");

    /**
     * LambdaQueryWrapper 的列名解析要走 MyBatis-Plus 的 TableInfo 缓存 —— 纯单测里没有 MP 运行时
     * ⇒ 不初始化会抛「can not find lambda cache for this entity」，断言会退化成**错误**而不是结论
     * （既有先例：WorkerPageConfigMapperTest / CuttingHeightConfigMapperTest）。
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
    @DisplayName("selectDueByTenant：pending + deleted=0 + fire_at<=now，且**有界**（LIMIT）")
    @SuppressWarnings("unchecked")
    void selectDueByTenantFiltersPendingNotDeletedDueAndBounded() {
        ScheduledTaskMapper mapper = mock(ScheduledTaskMapper.class, CALLS_REAL_METHODS);
        // 捕获实际下发的 wrapper（不用 `verify(captor)`：`when(...)` 本身也是一次调用，
        // verify 会因「调用 2 次」而红 —— 那是测试写法问题，不是被测行为问题）
        AtomicReference<Wrapper<ScheduledTask>> captured = new AtomicReference<>();
        when(mapper.selectList(any())).thenAnswer(inv -> {
            captured.set(inv.getArgument(0));
            return List.of();
        });

        mapper.selectDueByTenant(20L, NOW, 37);

        Wrapper<ScheduledTask> wrapper = captured.get();
        assertThat(wrapper).as("selectDueByTenant 必须下发查询条件").isNotNull();
        String sql = wrapper.getSqlSegment();
        assertThat(sql).as("租户维：不跨租户").contains("tenant_id");
        assertThat(sql).as("只扫待投递：fired 不得重投（疲劳控制）").contains("status");
        assertThat(sql).as("软删行不是生效待办").contains("deleted");
        assertThat(sql).as("到期判定：fire_at <= now").contains("fire_at");
        assertThat(sql).as("紧急度排序：越早到期越先投").containsIgnoringCase("order by");
        // 🔴 有界：一次扫描不许把全租户积压拉进内存（超出的下轮再投，不丢只延后）。
        // 用反射读 `AbstractWrapper.lastSql`：MP **没有**把 `.last(...)` 的内容暴露进
        // `getSqlSegment()`，也没有 public getter（`getLastSql()` 在 3.5.16 上不存在）——
        // 反射是唯一能机械读到 LIMIT 的口径。
        assertThat(readLastSql(wrapper)).as("必须带 LIMIT（有界）")
                .containsIgnoringCase("limit").contains("37");
        // 参数值逐值：租户 20 + deleted 0 + status 'pending' + 到期时刻
        assertThat(((AbstractWrapper<?, ?, ?>) wrapper).getParamNameValuePairs().values())
                .contains(20L, 0, "pending", NOW);
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

    /** 读 `AbstractWrapper.lastSql`（MP 只把它存在受保护字段里，无 public getter）。 */
    private static String readLastSql(Wrapper<ScheduledTask> wrapper) {
        try {
            java.lang.reflect.Field f = AbstractWrapper.class.getDeclaredField("lastSql");
            f.setAccessible(true);
            Object lastSql = f.get(wrapper);
            return lastSql == null ? "" : lastSql.toString();
        } catch (ReflectiveOperationException e) {
            throw new AssertionError("读不到 lastSql（MyBatis-Plus 版本变了？同步本判据）", e);
        }
    }
}
