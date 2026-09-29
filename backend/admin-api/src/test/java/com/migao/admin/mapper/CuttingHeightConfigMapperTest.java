package com.migao.admin.mapper;

// case_ids: PG-045

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.CuttingHeightConfig;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.CALLS_REAL_METHODS;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * CuttingHeightConfigMapper 验证测试（V140，母单 #5161）。
 *
 * <p>守的判据 = {@code selectActiveByTenant} 的**查询口径**（读面与预演面**共用**的那一处；
 * 两处各写一遍 where 条件迟早漏掉 {@code deleted = 0} ⇒ 软删行被当成生效配置 ⇒ 静默用错口径裁高）：</p>
 * <ul>
 *   <li>租户维：{@code tenant_id = <本租户>}（**不跨租户**）；</li>
 *   <li>软删维：{@code deleted = 0}（红证：去掉该条件 ⇒ 本用例红）。</li>
 * </ul>
 */
@DisplayName("CuttingHeightConfigMapper 验证（V140 / 母单 #5161）")
class CuttingHeightConfigMapperTest {

    /**
     * LambdaQueryWrapper 的列名解析要走 MyBatis-Plus 的 TableInfo 缓存 —— 纯单测里没有 MP 运行时
     * ⇒ 不初始化会抛「can not find lambda cache for this entity」，断言会退化成**错误**而不是结论
     * （既有先例：CraftCalcConfigMapperTest / KnowledgeCandidateMapperTest）。
     */
    @BeforeAll
    static void initTableInfo() {
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""), CuttingHeightConfig.class);
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由租户拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(CuttingHeightConfigMapper.class))
                .as("CuttingHeightConfigMapper should extend BaseMapper<CuttingHeightConfig>")
                .isTrue();
    }

    @Test
    @DisplayName("selectActiveByTenant：按 (tenant_id, deleted=0) 查，命中 ⇒ 返回该行")
    @SuppressWarnings("unchecked")
    void selectActiveByTenantFiltersTenantAndNotDeleted() {
        CuttingHeightConfigMapper mapper = mock(CuttingHeightConfigMapper.class, CALLS_REAL_METHODS);
        CuttingHeightConfig row = CuttingHeightConfig.builder()
                .id("chc-7").tenantId(7L).status("active").deleted(0).build();
        // 捕获实际下发的 wrapper（不用 `verify(captor)`：`when(...)` 本身也是一次调用，
        // verify 会因「调用 2 次」而红 —— 那是测试写法问题，不是被测行为问题）
        java.util.concurrent.atomic.AtomicReference<Wrapper<CuttingHeightConfig>> captured =
                new java.util.concurrent.atomic.AtomicReference<>();
        when(mapper.selectOne(any())).thenAnswer(inv -> {
            captured.set(inv.getArgument(0));
            return row;
        });

        assertThat(mapper.selectActiveByTenant(7L)).isSameAs(row);

        Wrapper<CuttingHeightConfig> wrapper = captured.get();
        assertThat(wrapper).as("selectActiveByTenant 必须下发查询条件").isNotNull();
        assertThat(wrapper.getSqlSegment()).contains("tenant_id").contains("deleted");
        // 参数值逐值：租户 7 + deleted 0（少了任一个 ⇒ 要么串租户、要么把软删行当生效配置）
        // `getParamNameValuePairs` 在 `AbstractWrapper` 上（`Wrapper` 只是接口），故按实现类读
        com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?> impl =
                (com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?>) wrapper;
        assertThat(impl.getParamNameValuePairs().values()).contains(7L, 0);
    }

    @Test
    @DisplayName("无活跃行 ⇒ null（读面据此回默认种子 + source='default'）")
    @SuppressWarnings("unchecked")
    void selectActiveByTenantReturnsNullWhenAbsent() {
        CuttingHeightConfigMapper mapper = mock(CuttingHeightConfigMapper.class, CALLS_REAL_METHODS);
        when(mapper.selectOne(any(Wrapper.class))).thenReturn(null);

        assertThat(mapper.selectActiveByTenant(8L)).isNull();
    }
}
