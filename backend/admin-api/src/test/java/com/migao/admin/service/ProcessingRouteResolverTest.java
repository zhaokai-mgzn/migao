// case_ids: MC-245
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * {@link ProcessingRouteResolver}（issue #8725 第二档切出来的「路线解析」单元）的定点判据。
 *
 * <p>它钉的是切片**最容易切坏**的两件事：派生链的**优先级**（显式字段 &gt; 受控来源 &gt; 存量信号）
 * 与 `fail-closed` 的**可行动文案**（没有它，切完只剩一句「取不到路线」，
 * 商家不知道该去哪儿建路线 —— 那正是 #4116 之前的状态）。</p>
 */
@DisplayName("路线解析单元：派生链优先级 + fail-closed 可行动文案（issue #8725 切片）")
class ProcessingRouteResolverTest {

    private static final Long TENANT = 1L;

    private ProductionOperationQueryService query;
    private ProcessingRouteResolver resolver;

    @BeforeEach
    void setUp() {
        query = mock(ProductionOperationQueryService.class);
        resolver = new ProcessingRouteResolver(query);
    }

    @Test
    @DisplayName("显式两维齐全 ⇒ direct，且**一次查询都不发**（订单真值优先于任何派生）")
    void deriveRouteKeyTakesExplicitColumnsVerbatim() {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("curtainType", "纱帘");
        entry.put("craft", "打孔");

        ProcessingRouteResolver.RouteKey key = resolver.deriveRouteKey(entry, TENANT);

        assertThat(key.curtainType()).isEqualTo("纱帘");
        assertThat(key.craft()).isEqualTo("打孔");
        assertThat(key.source()).isEqualTo("direct");
        verifyNoInteractions(query);
    }

    @Test
    @DisplayName("售卖形态 = 布料 ⇒ 部位维直读 `布料`（不走窗帘派生链），工艺取该租户默认")
    void deriveRouteKeyForFabricSaleLineUsesFabricPosition() {
        when(query.defaultCraft(TENANT)).thenReturn("韩褶");
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("saleForm", "布料");

        ProcessingRouteResolver.RouteKey key = resolver.deriveRouteKey(entry, TENANT);

        assertThat(key.curtainType()).isEqualTo("布料");
        assertThat(key.craft()).isEqualTo("韩褶");
        assertThat(key.source()).isEqualTo("direct");
    }

    @Test
    @DisplayName("只给部位 ⇒ partial；该租户没有默认工艺 ⇒ craft 保持 null（**不**回落常量「韩褶」）")
    void deriveRouteKeyLeavesCraftNullWhenTenantHasNoDefaultCraft() {
        when(query.routeSignals(TENANT)).thenReturn(List.of());
        when(query.defaultCraft(TENANT)).thenReturn(null);
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("curtainType", "布帘");

        ProcessingRouteResolver.RouteKey key = resolver.deriveRouteKey(entry, TENANT);

        assertThat(key.curtainType()).isEqualTo("布帘");
        assertThat(key.craft()).isNull();
        assertThat(key.source()).isEqualTo("partial");
    }

    @Test
    @DisplayName("两维全缺 + 无信号表 ⇒ default，部位回落常量「布帘」而工艺仍缺（不许猜工艺）")
    void deriveRouteKeyFallsBackToDefaultCurtainTypeOnly() {
        when(query.routeSignals(TENANT)).thenReturn(List.of());
        when(query.defaultCraft(TENANT)).thenReturn(null);

        ProcessingRouteResolver.RouteKey key = resolver.deriveRouteKey(new LinkedHashMap<>(), TENANT);

        assertThat(key.curtainType()).isEqualTo("布帘");
        assertThat(key.craft()).isNull();
        assertThat(key.source()).isEqualTo("default");
    }

    @Test
    @DisplayName("连默认路线模板都没有 ⇒ fail-closed，且建议**指到具体页面**（不是「取不到路线」）")
    void resolveRouteFailsClosedWithActionableSuggestion() {
        when(query.routeTemplateFor(TENANT, "布帘")).thenReturn(null);
        when(query.defaultRouteTemplate(TENANT)).thenReturn(null);
        when(query.routingKeys(TENANT)).thenReturn(List.of());
        when(query.defaultCraft(TENANT)).thenReturn("韩褶");
        ProcessingRouteResolver.RouteKey key =
                new ProcessingRouteResolver.RouteKey("布帘", "韩褶", "direct");
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("productName", "遮光帘A");

        assertThatThrownBy(() -> resolver.resolveRoute(
                key, TENANT, entry, List.of(), List.of(), Map.of()))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException be = (BusinessException) thrown;
                    assertThat(be.getCode()).isEqualTo("PRODUCTION_ROUTING_NOT_FOUND");
                    assertThat(be.getSuggestion()).contains("企业基础设置 → 工艺路线");
                    assertThat(be.getMessage()).contains("布帘×韩褶");
                });
    }

    @Test
    @DisplayName("部位维只认受控枚举（主布 / 配布边 / 纱）；未知取值 ⇒ null，**不猜**成布帘")
    void positionOfComponentRoleMapsControlledEnumOnly() {
        assertThat(ProcessingRouteResolver.positionOfComponentRole(Map.of("componentRole", "纱")))
                .isEqualTo("纱帘");
        assertThat(ProcessingRouteResolver.positionOfComponentRole(Map.of("componentRole", "主布")))
                .isEqualTo("布帘");
        assertThat(ProcessingRouteResolver.positionOfComponentRole(Map.of("componentRole", "配布边")))
                .isEqualTo("布帘");
        assertThat(ProcessingRouteResolver.positionOfComponentRole(Map.of("componentRole", "外帘")))
                .isNull();
        assertThat(ProcessingRouteResolver.positionOfComponentRole(Map.of())).isNull();
    }
}
