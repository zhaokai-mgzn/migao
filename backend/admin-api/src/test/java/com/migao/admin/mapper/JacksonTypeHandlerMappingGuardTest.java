// case_ids: PG-056
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import org.apache.ibatis.mapping.MappedStatement;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.HashSet;
import java.util.Set;

import static com.migao.admin.mapper.MapperTypeHandlerAssertions.boundJsonbProperties;
import static com.migao.admin.mapper.MapperTypeHandlerAssertions.configurationWithAllMappers;
import static com.migao.admin.mapper.MapperTypeHandlerAssertions.scan;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 **#4865 防再犯守卫（类级 / 真 MyBatis 映射）**：凡「返回带 {@code JacksonTypeHandler} 字段的实体」
 * 的 statement，其 ResultMap **必须真的绑上该类型处理器**。
 *
 * <p>本类是**全仓类级**判据（扫 {@code com.migao.admin.mapper} 包下全部接口）；判据本体与逐 mapper 的
 * {@code *MapperTest} 共用 {@link MapperTypeHandlerAssertions}（**单一出处**，不各写一份口径）。</p>
 *
 * <h2>被钉住的不变量</h2>
 * MyBatis-Plus 的 {@code @TableName(autoResultMap = true)} **只对 BaseMapper 的内置方法生效**：
 * 手写 {@code @Select} 若不显式 {@code @ResultMap("mybatis-plus_<Entity>")}（或 {@code @Results} 声明处理器），
 * 生成的是一条**内联 ResultMap（无任何类型处理器）** ⇒ JSONB 列以 **JSON 字符串**落到
 * {@code Object} 字段上 ⇒ 所有 {@code instanceof List} / {@code instanceof Map} 判据**静默为假**
 * （不抛异常、不报错，只是空）。
 *
 * <h2>实测代价（为什么值得一条类级守卫）</h2>
 * 同一根因在本仓**复发过两次**：issue #3340（{@code order_items.processing_info} 以字符串返回
 * ⇒ buildSnapshot 恒空；当时只改调用方 + 加 {@code instanceof String} 兜底，映射没修）与
 * issue #4865（{@code processing_orders.items_snapshot} 同样以字符串返回 ⇒ 套号分配跳过 ⇒
 * **部位码/短码永不产出**）。⇒ 只修一个方法不够，必须钉住**这一类**。
 *
 * <h2>红证（判据不许恒真）</h2>
 * 把任一 {@code @ResultMap} 删掉（= 回到「未绑 resultMap」的形态）⇒ 本判据**必红**
 * （打印 {@code statement → 未绑处理器的属性}）。反向自证见
 * {@link #guardActuallyInspectsTheStatementItMustProtect()}。
 */
@DisplayName("#4865 类级守卫：JSONB 字段的 JacksonTypeHandler 必须在真实 ResultMap 上生效")
class JacksonTypeHandlerMappingGuardTest {

    private static final String SNAPSHOT_STATEMENT =
            "com.migao.admin.mapper.ProcessingOrderMapper.selectActiveByOrderId";
    private static final String SNAPSHOT_PROPERTY = "itemsSnapshot";

    @Test
    @DisplayName("凡返回带 JSONB 字段实体的 statement，都必须绑上它的类型处理器")
    void everyJsonbEntityStatementBindsItsTypeHandler() {
        MybatisConfiguration configuration = configurationWithAllMappers();
        MapperTypeHandlerAssertions.Report report = scan(configuration);

        assertThat(report.inspectedStatements())
                .as("判据不许恒真：必须真的扫到「返回 JSONB 实体」的 statement（0 条 ⇒ 本判据什么都没保证）")
                .isGreaterThan(0);
        assertThat(report.violations())
                .as("手写 select 返回带 JacksonTypeHandler 字段的实体时必须绑 resultMap（否则 JSONB 列落成"
                        + "字符串 ⇒ instanceof 判据静默为假，issue #3340 / #4865 同根因）。违规清单：\n  "
                        + String.join("\n  ", report.violations()))
                .isEmpty();
    }

    @Test
    @DisplayName("反向自证：本判据确实覆盖 #4865 的那个 statement 与那个属性")
    void guardActuallyInspectsTheStatementItMustProtect() {
        MybatisConfiguration configuration = configurationWithAllMappers();
        MappedStatement statement = configuration.getMappedStatement(SNAPSHOT_STATEMENT);

        assertThat(statement.getResultMaps())
                .as("该 statement 必须用的是实体 ResultMap（而不是 Map/内联无处理器形态）")
                .anySatisfy(resultMap -> assertThat(resultMap.getType().getSimpleName()).isEqualTo("ProcessingOrder"));
        Set<String> bound = new HashSet<>();
        statement.getResultMaps().forEach(resultMap -> bound.addAll(boundJsonbProperties(resultMap)));
        assertThat(bound)
                .as("items_snapshot 的类型处理器必须真的挂在这条 statement 上（否则守卫覆盖不到本缺陷）")
                .contains(SNAPSHOT_PROPERTY);
    }
}
