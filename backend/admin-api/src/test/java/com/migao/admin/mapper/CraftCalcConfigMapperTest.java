package com.migao.admin.mapper;

// case_ids: OR-041

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.CraftCalcConfig;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.CALLS_REAL_METHODS;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * CraftCalcConfigMapper 验证测试（issue #4528 = 包 E）。
 *
 * <p>守的判据 = {@code selectActiveByTenant} 的**查询口径**（这是读面与算料注入面**共用**的那一处，
 * 两处各写一遍 where 条件迟早漏掉 {@code deleted = 0} ⇒ 软删行被当成生效配置 ⇒ 静默用错口径算钱）：</p>
 * <ul>
 *   <li>租户维：{@code tenant_id = <本租户>}（**不跨租户**）；</li>
 *   <li>软删维：{@code deleted = 0}（红证：去掉该条件 ⇒ 本用例红）。</li>
 * </ul>
 */
@DisplayName("CraftCalcConfigMapper 验证（issue #4528）")
class CraftCalcConfigMapperTest {

    /**
     * LambdaQueryWrapper 的列名解析要走 MyBatis-Plus 的 TableInfo 缓存 —— 纯单测里没有 MP 运行时
     * ⇒ 不初始化会抛「can not find lambda cache for this entity」，断言会退化成**错误**而不是结论
     * （既有先例：KnowledgeCandidateMapperTest / ProductionRoutingReadServiceTest）。
     */
    @BeforeAll
    static void initTableInfo() {
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""), CraftCalcConfig.class);
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由租户拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(CraftCalcConfigMapper.class))
                .as("CraftCalcConfigMapper should extend BaseMapper<CraftCalcConfig>")
                .isTrue();
    }

    @Test
    @DisplayName("selectActiveByTenant：按 (tenant_id, deleted=0) 查，命中 ⇒ 返回该行")
    @SuppressWarnings("unchecked")
    void selectActiveByTenantFiltersTenantAndNotDeleted() {
        CraftCalcConfigMapper mapper = mock(CraftCalcConfigMapper.class, CALLS_REAL_METHODS);
        CraftCalcConfig row = CraftCalcConfig.builder()
                .id("ccc-7").tenantId(7L).perFoldSingle(new BigDecimal("0.5")).deleted(0).build();
        // 捕获实际下发的 wrapper（不用 `verify(captor)`：`when(...)` 本身也是一次调用，
        // verify 会因「调用 2 次」而红 —— 那是测试写法问题，不是被测行为问题）
        java.util.concurrent.atomic.AtomicReference<Wrapper<CraftCalcConfig>> captured =
                new java.util.concurrent.atomic.AtomicReference<>();
        when(mapper.selectOne(any())).thenAnswer(inv -> {
            captured.set(inv.getArgument(0));
            return row;
        });

        CraftCalcConfig found = mapper.selectActiveByTenant(7L);

        assertThat(found).isSameAs(row);
        Wrapper<CraftCalcConfig> wrapper = captured.get();
        assertThat(wrapper).as("selectActiveByTenant 必须下发查询条件").isNotNull();
        assertThat(wrapper.getSqlSegment()).contains("tenant_id").contains("deleted");
        // 参数值逐值：租户 7 + deleted 0（少了任一个 ⇒ 要么串租户、要么把软删行当生效配置）
        // `getParamNameValuePairs` 在 `AbstractWrapper` 上（`Wrapper` 只是接口），故按实现类读
        com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?> impl =
                (com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?>) wrapper;
        assertThat(impl.getParamNameValuePairs().values())
                .as("查询参数：%s", impl.getParamNameValuePairs())
                .contains(7L, 0);
    }

    @Test
    @DisplayName("selectActiveByTenant：无行 ⇒ null（调用方据此走「引擎默认值」分支，不是造一份默认值）")
    void selectActiveByTenantReturnsNullWhenAbsent() {
        CraftCalcConfigMapper mapper = mock(CraftCalcConfigMapper.class, CALLS_REAL_METHODS);
        when(mapper.selectOne(any())).thenReturn(null);

        assertThat(mapper.selectActiveByTenant(9L)).isNull();
    }
}
