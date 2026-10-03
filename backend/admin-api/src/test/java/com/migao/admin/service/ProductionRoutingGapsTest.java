// case_ids: PP-014
package com.migao.admin.service;

import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 「路线缺口」清单的**消费面 + 可达性**判据（issue #6104；用例 PP-014 的缺口区）。
 *
 * <p>三个缺陷形态（真实读数见 issue #6104 / acceptance 2026-10-03 的 F3）：</p>
 * <ol>
 *   <li><b>误报</b>：消费面只算**活跃主线**，漏了**活跃适用条件的 {@code operation}** ⇒
 *       租户 20 上 22 条缺口中 20 条其实正被规则消费（{@code 韩褶-布} 由
 *       {@code craft=韩褶 → insert 韩褶} 产出，派工实测就在加工单里）；</li>
 *   <li><b>有害建议</b>：note 一律建议「把它加进某条路线」—— 对**条件工序**照着做就是
 *       把它变成**无条件工序**（每张单都出现），直接改计件工资；</li>
 *   <li><b>反向漏报</b>：{@code 裁剪-纱} 挂在「布料工序路线」（{@code positions=["布料"]}）上，
 *       而该部位解析出的变体是 {@code 裁剪-布} ⇒ **任何单都取不到**，却被算成「已挂路线」
 *       从清单里静默消失。</li>
 * </ol>
 *
 * <p>夹具按**租户 20 的真实形态**搭（模板两条 / 规则不限部位 / 工序存变体名），
 * 归一走的仍是既有 {@code normalizeOperationName}。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#6104 路线缺口：消费面 = 活跃主线 ∪ 活跃适用条件；挂了路线但不可达不得静默")
class ProductionRoutingGapsTest {

    private static final Long TENANT = 20L;

    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    private ProductionOperationQueryService service() {
        return new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                productionRouteRuleMapper, productionOperationPositionMapper, productionCraftMapper,
                productionRouteSignalMapper);
    }

    /** MyBatis-Plus 的 TableInfo 缓存（同 ProductionOperationQueryServiceTest 的既有做法）。 */
    @BeforeEach
    void initTableInfoCache() {
        com.baomidou.mybatisplus.core.MybatisConfiguration conf =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(conf, "");
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, ProductionOperation.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, ProductionRouteTemplate.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant,
                ProductionOperationPosition.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant,
                ProductionRouteRule.class);
    }

    // ────────────────────────── 夹具 ──────────────────────────

    private ProductionOperation op(String id, String name, int sortOrder) {
        return ProductionOperation.builder()
                .id(id).tenantId(TENANT).name(name).groupName("车位").position("布帘").unit("米")
                .unitPrice(new BigDecimal("0.40")).isMustFinish(false).isStartMarker(false)
                .sortOrder(sortOrder).status("active").deleted(0).build();
    }

    private ProductionRouteTemplate template(String id, String name, boolean isDefault,
                                             List<String> positions, List<String> mainline) {
        return ProductionRouteTemplate.builder()
                .id(id).tenantId(TENANT).name(name).isDefault(isDefault)
                .positions(positions).mainline(mainline).status("active").deleted(0).build();
    }

    private ProductionRouteRule rule(String id, String triggerValue, String position, String action,
                                     String operation, int priority) {
        return ProductionRouteRule.builder()
                .id(id).tenantId(TENANT).triggerKind("craft").triggerValue(triggerValue)
                .position(position).action(action).operation(operation).priority(priority)
                .status("active").deleted(0).build();
    }

    /** 租户 20 的形态：两条活跃模板 + 规则**不限部位**（真实读数是 {@code position: null}）。 */
    private void stubTenant20Shape() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-v72-20", "窗帘工序路线（默认）", true, List.of("布帘", "纱帘", "帘头"),
                        List.of("精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "打包",
                                "外帘装袋", "外帘发货")),
                template("rt-v79-20", "布料工序路线", false, List.of("布料"), List.of("裁剪", "打包"))));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-v93-20-01", "韩褶", null, "insert", "韩褶", 10),
                rule("rr-v93-20-02", "韩褶", null, "insert", "上车布", 20),
                rule("rr-v93-20-14", "加花边", null, "insert", "花边", 140),
                rule("rr-v93-20-07", "穿杆", null, "remove", "定型", 70)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-01", "韩褶-布", 1),
                op("op-02", "韩褶-纱", 2),
                op("op-03", "上车布-布", 3),
                op("op-04", "花边-布", 4),
                op("op-05", "精裁-布", 5),
                op("op-06", "裁剪-布", 6),
                op("op-07", "裁剪-纱", 7),
                op("op-08", "质检", 8),
                op("op-09", "腰靠垫", 9),
                op("op-10", "测试22", 10)));
        when(productionRouteSignalMapper.selectList(any())).thenReturn(List.of());
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> entries(Map<String, Object> gaps, String key) {
        return (List<Map<String, Object>>) gaps.get(key);
    }

    private static List<String> names(List<Map<String, Object>> entries) {
        return entries.stream().map(entry -> String.valueOf(entry.get("name"))).toList();
    }

    private static List<String> notes(List<Map<String, Object>> entries) {
        return entries.stream().map(entry -> String.valueOf(entry.get("note"))).toList();
    }

    // ────────────────────────── 判据 ──────────────────────────

    @Test
    @DisplayName("判据1 缺口集合 = 活跃主线 ∪ 活跃适用条件都未消费的工序（由规则消费的**不得**再算缺口）")
    void gapSetIsExactlyWhatNoActiveConsumerOwns() {
        stubTenant20Shape();

        Map<String, Object> gaps = service().routingGaps(TENANT);
        List<Map<String, Object>> unrouted = entries(gaps, "unrouted_operations");

        // 真值：只有 质检 / 腰靠垫（有意挂起）+ 商家自建「测试22」没有被任何消费方引用
        assertThat(names(unrouted)).containsExactlyInAnyOrder("质检", "腰靠垫", "测试22");
        assertThat(gaps.get("unrouted_operation_total")).isEqualTo(3);
        assertThat(gaps.get("pending_confirmation_total")).isEqualTo(2);
        // 🔴 反向护栏（旧实现的误报形态）：这 4 道的逻辑名都在活跃规则里 ⇒ 一条都不许进缺口
        assertThat(names(unrouted)).doesNotContain("韩褶", "上车布", "花边", "裁剪");
        assertThat(unrouted).allSatisfy(entry ->
                assertThat(entry.get("reason")).isEqualTo("no_consumer"));
    }

    @Test
    @DisplayName("判据2 「已挂路线但不可达」必须可见：裁剪-纱 进 unreachable_operations 且带显式说明")
    void unreachableOperationStaysVisible() {
        stubTenant20Shape();

        Map<String, Object> gaps = service().routingGaps(TENANT);
        List<Map<String, Object>> unreachable = entries(gaps, "unreachable_operations");

        // 裁剪 挂在「布料工序路线」（positions=["布料"]）上，而该部位解析出的变体是 裁剪-布
        assertThat(names(unreachable)).containsExactly("裁剪");
        assertThat(unreachable.get(0).get("library_name")).isEqualTo("裁剪-纱");
        assertThat(unreachable.get(0).get("reason")).isEqualTo("unreachable");
        assertThat(gaps.get("unreachable_operation_total")).isEqualTo(1);
        // 显式区分：note 必须说清「引用得到、但按部位取不到」，不得只说「挂起」把漏报藏回去
        assertThat(String.valueOf(unreachable.get(0).get("note"))).contains("部位 × 路线");
        assertThat(unreachable.get(0).get("pending_confirmation")).isEqualTo(true);
        // 可达的那一道（裁剪-布）与「在规则里可达」的工序都不进任何清单
        assertThat(names(unreachable)).doesNotContain("裁剪-布", "韩褶", "上车布", "花边");
        assertThat(names(entries(gaps, "unrouted_operations"))).doesNotContain("裁剪");
    }

    @Test
    @DisplayName("判据3 note 建议不得有害：由规则消费的工序**绝不**再出现「加进某条路线」")
    void ruleConsumedOperationNeverGetsTheAddToRouteAdvice() {
        // 规则消费 + **不可达**（insert 立边 限部位 布料，而立边只有布帘变体）—— 这一格
        // 正是「照旧建议加进路线」最危险的地方：加的是条件工序，代价是每张单都出。
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-v79-20", "布料工序路线", false, List.of("布料"), List.of("裁剪", "打包"))));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-01", "加立边", "布料", "insert", "立边", 240)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(op("op-01", "立边-布", 1)));
        when(productionRouteSignalMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> gaps = service().routingGaps(TENANT);
        List<Map<String, Object>> unrouted = entries(gaps, "unrouted_operations");
        List<Map<String, Object>> unreachable = entries(gaps, "unreachable_operations");

        // 它由规则消费 ⇒ 不是「没人消费」的缺口；但它取不到 ⇒ 必须在 unreachable 里可见
        assertThat(names(unrouted)).isEmpty();
        assertThat(names(unreachable)).containsExactly("立边");
        assertThat(notes(unrouted)).noneMatch(note -> note.contains("加进某条路线"));
        assertThat(notes(unreachable)).noneMatch(note -> note.contains("加进某条路线"));
        assertThat(String.valueOf(unreachable.get(0).get("note"))).contains("任何加工单都取不到它");
    }

    @Test
    @DisplayName("判据3b note 建议仍然可行动：**没有**任何消费方的工序照旧提示加进路线或停用")
    void trulyUnroutedOperationKeepsActionableAdvice() {
        stubTenant20Shape();

        List<Map<String, Object>> unrouted = entries(service().routingGaps(TENANT), "unrouted_operations");
        Map<String, Object> selfBuilt = unrouted.stream()
                .filter(entry -> "测试22".equals(entry.get("name"))).findFirst().orElseThrow();
        assertThat(String.valueOf(selfBuilt.get("note")))
                .contains("没有任何活跃路线或适用条件消费它")
                .contains("加进某条路线");
    }
}
