// case_ids: PG-018, PG-032, PG-035, PG-039
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProductionCraft;
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
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工序库 / 工艺路线只读消费者测试（issue #4116 P0-2；P2b / issue #4459 切新结构）。
 *
 * <p>锁四条：① 读的是**库**（按 tenant_id + deleted=0 + status=active 过滤，租户隔离/停用不可漏）；
 * ② 展示形态按**分组→排序位**稳定（工序目录）与**具名主线 + 适用帘种**（路线模板）；
 * ③ 新读面（{@code routeTemplateFor} / {@code defaultRouteTemplate} / {@code defaultCraft} /
 * {@code operationPositions} / {@code routeRules}）的**稳定排序**与**不猜**口径；
 * ④ 旧工序名 ↔ 逻辑工序名的**往返判据**（35 条逐条，issue #4459 §2① 的锁死方式）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionOperationQueryService 工序库/工艺路线只读消费者")
class ProductionOperationQueryServiceTest {

    private static final Long TENANT = 1L;

    /** 真值源 {@code routing.py}（**逐字解析**，Java 无法 import Python ⇒ 只能按文本比对）。 */
    private static final Path ROUTING_PY = Path.of("..", "ai-agent-service", "app", "production", "routing.py");

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

    /**
     * 初始化 MyBatis-Plus 的 TableInfo 缓存（同 OrderIdempotencyTest / ProcessingOrderServiceTest 的既有做法）：
     * 断言 `LambdaQueryWrapper.getSqlSegment()` 需要它 —— 否则报
     * 「MybatisPlus can not find lambda cache for this entity」（Standalone 单测无 MapperScan 缓存）。
     */
    @org.junit.jupiter.api.BeforeEach
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

    private ProductionOperation op(String id, String name, String group, String position,
                                   String unit, String price, boolean mustFinish, boolean startMarker,
                                   int sortOrder) {
        return ProductionOperation.builder()
                .id(id).tenantId(TENANT).name(name).groupName(group).position(position).unit(unit)
                .unitPrice(new BigDecimal(price)).isMustFinish(mustFinish).isStartMarker(startMarker)
                .sortOrder(sortOrder).status("active").deleted(0).build();
    }

    private ProductionRouteTemplate template(String id, String name, boolean isDefault,
                                             List<String> positions, List<String> mainline) {
        return ProductionRouteTemplate.builder()
                .id(id).tenantId(TENANT).name(name).isDefault(isDefault)
                .positions(positions).mainline(mainline).status("active").deleted(0).build();
    }

    /**
     * 带作用域的工序行（issue #4384 A1，V67）。
     *
     * <p>{@code scope} 的取值**只从库里来**：本 helper 允许逐行给不同值，正是为了用
     * 「注入法」证明读面**逐字取库**（写死常量 / 不读库 ⇒ 断言不跟着变 ⇒ 红）。</p>
     */
    private ProductionOperation opScope(String id, String name, String position, String unit, String scope) {
        return ProductionOperation.builder()
                .id(id).tenantId(TENANT).name(name).groupName("后道").position(position).unit(unit)
                .unitPrice(new BigDecimal("1.00")).isMustFinish(false).isStartMarker(false)
                .sortOrder(24).status("active").deleted(0).scope(scope).build();
    }

    // ══════════════════ 工序目录（issue #4116，本单不改口径）══════════════════

    @Test
    @DisplayName("工序目录：按分组聚合，组内保留库给的排序（sort_order 升序）")
    void catalogGroupsOperationsByGroup() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-v54-01", "精裁-布", "裁剪", "布帘", "米", "0.40", false, true, 1),
                op("op-v54-02", "精裁-纱", "裁剪", "纱帘", "米", "0.40", false, true, 2),
                op("op-v54-07", "韩褶-布", "车位", "布帘", "折", "0.40", false, false, 7),
                op("op-v54-25", "外帘装袋", "后道", "外帘", "套", "1.00", true, false, 25)));

        Map<String, Object> result = service().catalog(TENANT);

        assertThat(result.get("total")).isEqualTo(4);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> groups = (List<Map<String, Object>>) result.get("groups");
        assertThat(groups).extracting(g -> g.get("group")).containsExactly("裁剪", "车位", "后道");

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> tailoring = (List<Map<String, Object>>) groups.get(0).get("operations");
        // issue #4642 判据改钉新真值（**不是放宽**）：catalog 的 `name` 是**读时归一后的逻辑名**
        // ⇒ 库行 `精裁-布` / `精裁-纱` 都返回 `精裁`（**顺序与条数一字不变**，只换显示口径）。
        // 库口径原名仍可核：`library_name` 逐行保留旧名。
        assertThat(tailoring).extracting(o -> o.get("name")).containsExactly("精裁", "精裁");
        assertThat(tailoring).extracting(o -> o.get("library_name")).containsExactly("精裁-布", "精裁-纱");
        assertThat(tailoring.get(0).get("unit")).isEqualTo("米");
        assertThat((BigDecimal) tailoring.get(0).get("unit_price")).isEqualByComparingTo("0.40");
        assertThat(tailoring.get(0).get("is_start_marker")).isEqualTo(true);
        assertThat(tailoring.get(0).get("is_must_finish")).isEqualTo(false);

        // 组内排序/停用/软删/租户隔离都压在 SQL 条件里（不是内存过滤）
        ArgumentCaptor<LambdaQueryWrapper<ProductionOperation>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(productionOperationMapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment())
                .as("只读消费者必须按 tenant_id + deleted=0 + status=active 过滤")
                .contains("tenant_id").contains("deleted").contains("status");
    }

    @Test
    @DisplayName("工序目录为空（库未种子/全停用）⇒ total=0 且 groups 空数组，不是错误态")
    void catalogWithoutSeedReturnsEmptyGroups() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service().catalog(TENANT);

        assertThat(result.get("total")).isEqualTo(0);
        assertThat((List<?>) result.get("groups")).isEmpty();
    }

    // ══════════════════ 路线模板（P2b：具名主线 + 适用帘种）══════════════════

    @Test
    @DisplayName("路线模板列表：主线**有序**（排序不是展示细节而是语义）+ 适用帘种 + 默认标记")
    void routingsExposeOrderedMainline() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-v70-01", "窗帘工序路线（默认）", true,
                        List.of("布帘", "纱帘", "帘头"), List.of("精裁", "三边", "熨烫"))));

        Map<String, Object> result = service().routings(TENANT);

        assertThat(result.get("total")).isEqualTo(1);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.get("routings");
        assertThat(items.get(0).get("name")).isEqualTo("窗帘工序路线（默认）");
        assertThat(items.get(0).get("is_default")).isEqualTo(true);
        assertThat(items.get(0).get("positions")).asString().isEqualTo(List.of("布帘", "纱帘", "帘头").toString());
        // 顺序 = 主线数组顺序（路线是**有序**序列）
        assertThat(items.get(0).get("mainline")).asString().isEqualTo(List.of("精裁", "三边", "熨烫").toString());

        ArgumentCaptor<LambdaQueryWrapper<ProductionRouteTemplate>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(productionRouteTemplateMapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment())
                .as("只读消费者必须按 tenant_id + deleted=0 + status=active 过滤")
                .contains("tenant_id").contains("deleted").contains("status");
    }

    @Test
    @DisplayName("JSONB 反序列化非 List 形态（脏数据）⇒ 主线为空而不是抛错（展示层不得被单条脏数据打挂）")
    void malformedMainlineDoesNotThrow() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-bad", "坏路线", false, null, null)));

        Map<String, Object> result = service().routings(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.get("routings");
        assertThat((List<?>) items.get(0).get("mainline")).isEmpty();
        assertThat((List<?>) items.get(0).get("positions")).isEmpty();
    }

    // ══════════════════ 读面「读时归一」（issue #4632）══════════════════
    //
    // 病根：写面（#4618）已做到「保存时归一为逻辑名」，但**存量**主线若在旧前端时代存过变体名
    // （`精裁-布`），读面原样返回 ⇒ 「工艺路线」tab 的主线 chip 上仍渲染旧名（违反 goal 判据）。
    // 修法 = 在 `templateView`（读写面共用的展示形态）返回前逐项走**既有** `normalizeOperationName`：
    // 读时归一、**不写库**、不改写面语义（两处同一份实现，不新造第二份映射）。

    /**
     * 读面归一的**主判据**（issue #4632）：存量变体名 ⇒ 逻辑工序名。
     *
     * <p>一条断言同时锁三条边界：① **自定义名原样**（{@code 测试22} 归一后等于自身 ⇒ 不得被抹成空
     * 或别的名字）；② **顺序不变**（主线序列的顺序是计件/完工判定的输入）；③ **重复不去重**
     * （{@code 精裁-布} 与 {@code 精裁} 是同一道工序各排一次 ⇒ 归一后仍是两项 —— 判重是**写面**
     * 护栏的事，读面去重会让「库里有几道」与「界面显示几道」永久对不上）。</p>
     *
     * <p>红证（修复前实测）：本断言得 {@code ["精裁-布", "布三边", "测试22", "精裁"]}。</p>
     */
    @Test
    @DisplayName("存量主线读时归一：变体名 ⇒ 逻辑名（自定义名原样 / 顺序与重复一字不变，issue #4632）")
    void routingsNormalizeLegacyVariantNamesOnRead() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-legacy", "存量路线", true, List.of("布帘"),
                        List.of("精裁-布", "布三边", "测试22", "精裁"))));

        Map<String, Object> result = service().routings(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.get("routings");
        assertThat(items.get(0).get("mainline"))
                .as("读面归一：变体名 ⇒ 逻辑名；自定义名原样；顺序不变；不去重"
                        + "（去重/排序会改计件与完工判定的输入）")
                .isEqualTo(List.of("精裁", "三边", "测试22", "精裁"));
    }

    /**
     * 「**同一份**归一实现」判据（issue #4632 验收判据 5）：读面逐项的结果必须等于
     * {@link ProductionOperationQueryService#normalizeOperationName} 逐项的结果 —— 读面自己另抄
     * 一份映射表时本断言与 {@link #logicalNameTableMatchesTruthSource()} 会**一起**红
     * （抄的那份不会跟真值源走）。
     */
    @Test
    @DisplayName("读面归一与写面同一份实现：逐项等于 normalizeOperationName（不新造第二份映射）")
    void readFaceNormalizationUsesTheSingleExistingImplementation() {
        ProductionOperationQueryService service = service();
        List<String> raw = new java.util.ArrayList<>(LEGACY_NAMES);
        raw.add("测试22");
        raw.add("罗马帘穿杆");
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-same", "同源路线", true, List.of("布帘"), raw)));

        Map<String, Object> result = service().routings(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.get("routings");
        assertThat(items.get(0).get("mainline"))
                .as("读面必须逐项走 normalizeOperationName（另抄一份表 ⇒ 与真值源判据一起红）")
                .isEqualTo(raw.stream().map(service::normalizeOperationName).toList());
    }

    /** 幂等判据（issue #4632）：逻辑名再归一仍是自身，否则同一道工序读两次得到两个名字。 */
    @Test
    @DisplayName("读面归一幂等：35 条旧名逐条（精裁-布 ⇒ 精裁 ⇒ 精裁）")
    void readFaceNormalizationIsIdempotent() {
        ProductionOperationQueryService service = service();
        List<String> notIdempotent = new java.util.ArrayList<>();
        for (String legacy : LEGACY_NAMES) {
            String logical = service.normalizeOperationName(legacy);
            if (!logical.equals(service.normalizeOperationName(logical))) {
                notIdempotent.add(legacy + " ⇒ " + logical);
            }
        }
        assertThat(notIdempotent)
                .as("归一必须幂等（不幂等 ⇒ chip 上的名字会随读写次数漂移）")
                .isEmpty();
    }

    /** 反向护栏（issue #4632）：**只归一能归一的** —— 未登记的自定义工序名原样返回。 */
    @Test
    @DisplayName("读面归一不误伤自定义名：测试22 / 罗马帘穿杆 原样返回；空主线仍是空数组")
    void readFaceNormalizationKeepsCustomNamesVerbatim() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-custom", "自定义路线", false, List.of("布帘"),
                        List.of("测试22", "罗马帘穿杆")),
                template("rt-empty", "空主线路线", false, List.of("布帘"), List.of())));

        Map<String, Object> result = service().routings(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.get("routings");
        assertThat(items.get(0).get("mainline"))
                .as("未登记的名字归一后等于自身 ⇒ 原样返回（不得变空、不得变成别的工序）")
                .isEqualTo(List.of("测试22", "罗马帘穿杆"));
        assertThat((List<?>) items.get(1).get("mainline")).isEmpty();
    }

    @Test
    @DisplayName("routeTemplateFor：按**适用帘种**命中；没有该部位的模板 ⇒ null（不猜、不回落）")
    void routeTemplateForMatchesPositions() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-v70-01", "窗帘工序路线（默认）", true,
                        List.of("布帘", "纱帘"), List.of("精裁", "三边"))));

        assertThat(service().routeTemplateFor(TENANT, "布帘")).isNotNull();
        assertThat(service().routeTemplateFor(TENANT, "纱帘")).isNotNull();
        assertThat(service().routeTemplateFor(TENANT, "帘头"))
                .as("帘头不在 positions 里 ⇒ null（「兜底到默认模板」是调用方的策略，不是库的语义）")
                .isNull();
        assertThat(service().routeTemplateFor(TENANT, null)).isNull();
    }

    @Test
    @DisplayName("#4563 路线命中 tie-break：**先建者优先**（is_default DESC → created_at ASC → id ASC）—— 只按 id 排会让新建路线**静默顶掉**种子")
    void routeTemplatesOrderTieBreakIsCreatedAtFirst() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-v79-01", "布料工序路线", false, List.of("布料"), List.of("配料", "打包"))));

        service().routeTemplates(TENANT);

        ArgumentCaptor<LambdaQueryWrapper<ProductionRouteTemplate>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(productionRouteTemplateMapper).selectList(captor.capture());
        // 归一空白与逗号，便于断言「顺序」
        String sql = captor.getValue().getSqlSegment().toLowerCase()
                .replaceAll("\\s+", " ").replaceAll("\\s*,\\s*", ", ");
        assertThat(sql).as("排序第一键仍是「默认优先」（既有语义不动）").contains("is_default desc");
        // 注入：把 `created_at` 那一键删掉（退回 `is_default DESC, id ASC`）⇒ 下面两条红
        assertThat(sql).as("第二键必须是 `created_at`（先建者优先）").contains("created_at");
        int orderBy = sql.indexOf("order by");
        assertThat(orderBy).as("SQL 里应有 ORDER BY（本判据的前提）").isGreaterThanOrEqualTo(0);
        String orderTail = sql.substring(orderBy);
        assertThat(orderTail.indexOf("created_at"))
                .as("`created_at` 必须排在 `id` **之前** —— 顺序错了等于没修（新建路线仍会顶掉种子）")
                .isGreaterThanOrEqualTo(0);
        assertThat(orderTail.indexOf("created_at"))
                .isLessThan(orderTail.lastIndexOf(" id"));

        // 反向自证（**不是空断言**）：本修法要防的正是下面这个事实 ——
        // 新建路线的 id 是 UUID，其十六进制首字符小于种子 id 的 `r` ⇒ 只按 id 排时**新建的在前**。
        assertThat("a1b2c3d4-0000-0000-0000-000000000000".compareTo("rt-v79-01"))
                .as("UUID id 排在小写 `rt-…` 种子 id 之前 ⇒ 只按 id 排 = 新建路线静默顶掉种子（#4563 的机制）")
                .isNegative();
    }

    @Test
    @DisplayName("defaultRouteTemplate：按 is_default 命中；没有默认 ⇒ null（调用方 T3 fail-closed）")
    void defaultRouteTemplatePicksTheDefaultFlag() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                template("rt-a", "路线甲", false, List.of("布帘"), List.of("精裁")),
                template("rt-b", "路线乙", true, List.of("纱帘"), List.of("三边"))));

        ProductionRouteTemplate hit = service().defaultRouteTemplate(TENANT);

        assertThat(hit).isNotNull();
        assertThat(hit.getName()).as("判据是 is_default，不是「第一条」").isEqualTo("路线乙");
    }

    @Test
    @DisplayName("defaultRouteTemplate：库里一条路线都没有 ⇒ null（不静默取常量 布帘×韩褶）")
    void defaultRouteTemplateIsNullOnEmptyLibrary() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        assertThat(service().defaultRouteTemplate(TENANT)).isNull();
    }

    @Test
    @DisplayName("defaultCraft：按 is_default 命中；没有默认工艺 ⇒ null（**不写死常量 韩褶**，issue #4459）")
    void defaultCraftPicksTheDefaultFlag() {
        when(productionCraftMapper.selectList(any())).thenReturn(List.of(
                ProductionCraft.builder().id("pc-1").tenantId(TENANT).name("打孔")
                        .isDefault(false).status("active").deleted(0).build(),
                ProductionCraft.builder().id("pc-2").tenantId(TENANT).name("四爪钩")
                        .isDefault(true).status("active").deleted(0).build()));

        assertThat(service().defaultCraft(TENANT))
                .as("判据是 is_default（商家可配），不是常量 韩褶").isEqualTo("四爪钩");
    }

    @Test
    @DisplayName("defaultCraft：没有默认工艺 ⇒ null（调用方 T3 fail-closed，不静默取常量）")
    void defaultCraftIsNullWhenAbsent() {
        when(productionCraftMapper.selectList(any())).thenReturn(List.of());
        assertThat(service().defaultCraft(TENANT)).isNull();
    }

    // ══════════════════ 新读面：规则表 / 部位价目 / 稳定排序 ══════════════════

    @Test
    @DisplayName("routeRules：只取活跃行，**按 (priority, id) 稳定排序**（规则顺序敏感 ⇒ 派生必须确定）")
    void routeRulesAreOrderedByPriorityThenId() {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());

        service().routeRules(TENANT);

        ArgumentCaptor<LambdaQueryWrapper<ProductionRouteRule>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(productionRouteRuleMapper).selectList(captor.capture());
        String sql = captor.getValue().getSqlSegment();
        assertThat(sql).contains("tenant_id").contains("deleted").contains("status");
        assertThat(sql).as("排序必须确定（priority 升序、同序按 id）—— 否则同一张单两次生成得到不同工序序列")
                .contains("priority").contains("id");
    }

    @Test
    @DisplayName("operationPositions：只取活跃行，按 (logical_name, position) 稳定排序")
    void operationPositionsAreOrderedStably() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        service().operationPositions(TENANT);

        ArgumentCaptor<LambdaQueryWrapper<ProductionOperationPosition>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(productionOperationPositionMapper).selectList(captor.capture());
        String sql = captor.getValue().getSqlSegment();
        assertThat(sql).contains("tenant_id").contains("deleted").contains("status");
        assertThat(sql).contains("logical_name").contains("position");
    }

    @Test
    @DisplayName("只读边界：本类的每个读面都只走 SELECT（无 insert/update/delete 调用）")
    void queryServiceIsReadOnly() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());
        when(productionCraftMapper.selectList(any())).thenReturn(List.of());

        service().catalog(TENANT);
        service().routings(TENANT);
        service().routeTemplateFor(TENANT, "布帘");
        service().defaultRouteTemplate(TENANT);
        service().defaultCraft(TENANT);
        service().operationPositions(TENANT);
        service().routeRules(TENANT);
        service().operationsByName(TENANT);

        verify(productionOperationMapper, org.mockito.Mockito.never()).insert(any(ProductionOperation.class));
        verify(productionOperationMapper, org.mockito.Mockito.never()).deleteById(any(String.class));
        verify(productionRouteTemplateMapper, org.mockito.Mockito.never())
                .insert(any(ProductionRouteTemplate.class));
        verify(productionRouteTemplateMapper, org.mockito.Mockito.never()).deleteById(any(String.class));
        // 读时归一（issue #4632）**不得**变成「读时回填」：读面走过的路径里对库只有 SELECT。
        verify(productionOperationMapper, org.mockito.Mockito.never())
                .updateById(any(ProductionOperation.class));
        verify(productionRouteTemplateMapper, org.mockito.Mockito.never())
                .updateById(any(ProductionRouteTemplate.class));
    }

    // ══════════════════ variantNameOf：39 条旧名的**往返判据**（issue #4459 §2①）══════════════════

    /**
     * 判据（**锁死方式**，issue #4459 §2①）：对 39 条旧名逐条
     * {@code variantNameOf(normalizeOperationName(name), position(name)) == name}。
     *
     * <p>这条往返判据是「新结构的逻辑名 ↔ 工序库的旧变体名」映射的**唯一**可失败判据：
     * 少一条、多一条、后缀规则改了（`-布`/`-纱`/`-帘`）都会红。</p>
     *
     * <p>部位的推导是**测试侧**的事（生产侧只从库/订单取部位）：名字带 {@code -布}/{@code -纱}
     * 后缀的直接读后缀；不规则名（{@code 布三边}/{@code 纱三边}/{@code 布帘车被}/{@code 帘头制作}）
     * 按真值源的表逐条给出。</p>
     */
    @Test
    @DisplayName("variantNameOf 往返判据：39 条旧名逐条可逆（改后缀规则/加减一条即红）")
    void variantNameOfRoundTripsAllLegacyNames() {
        Map<String, String> logicalNames = logicalNamePairs();
        // 🔴 issue #4937：35 → **39** 条（新增 4 道纱帘变体；见
        // `logicalNameTableMatchesTruthSource` 的注释）
        assertThat(logicalNames).as("真值源有 39 条旧名").hasSize(39);

        Map<String, Map<String, Object>> catalog = new LinkedHashMap<>();
        logicalNames.keySet().forEach(name -> catalog.put(name, Map.of()));

        ProductionOperationQueryService service = service();
        List<String> failures = new java.util.ArrayList<>();
        for (Map.Entry<String, String> entry : logicalNames.entrySet()) {
            String legacy = entry.getKey();
            String logical = entry.getValue();
            String position = positionOfLegacyName(legacy);
            if (position == null) {
                continue;
            }
            String back = service.variantNameOf(logical, position, catalog);
            if (!legacy.equals(back)) {
                failures.add(legacy + "(" + position + ") ⇒ " + back);
            }
        }
        assertThat(failures)
                .as("逆映射必须逐条复现旧名：<逻辑名><部位后缀>（布帘→-布/纱帘→-纱/帘头→-帘）"
                        + " → 帘头回落 -布 → 裸逻辑名")
                .isEmpty();
    }

    @Test
    @DisplayName("variantNameOf：库里没有该变体 ⇒ null（**不猜**，由调用方 fail-closed 指名报缺）")
    void variantNameOfReturnsNullWhenVariantAbsent() {
        assertThat(service().variantNameOf("精裁", "布帘", Map.of("韩褶-布", Map.of())))
                .as("库里没有 精裁-布 ⇒ null（不回落裸逻辑名、不猜别的部位）")
                .isNull();
    }

    @Test
    @DisplayName("variantNameOf：帘头回落布帘变体（V54 的 帘头×平幔 路线逐字引用 精裁-布/布三边）")
    void variantNameOfFallsBackToClothVariantForCurtainHead() {
        Map<String, Map<String, Object>> catalog = Map.of("精裁-布", Map.of(), "布三边", Map.of());

        assertThat(service().variantNameOf("精裁", "帘头", catalog))
                .as("帘头没有 -帘 变体 ⇒ 回落 -布（否则帘头路线在真库里一道工序都解析不出来）")
                .isEqualTo("精裁-布");
        assertThat(service().variantNameOf("三边", "帘头", catalog)).isEqualTo("布三边");
    }

    @Test
    @DisplayName("variantNameOf：部位无关的工序回落裸逻辑名（帘头制作/外帘打卷…）")
    void variantNameOfFallsBackToBareLogicalName() {
        Map<String, Map<String, Object>> catalog = Map.of("帘头制作", Map.of(), "外帘打卷", Map.of());

        assertThat(service().variantNameOf("帘头制作", "帘头", catalog)).isEqualTo("帘头制作");
        assertThat(service().variantNameOf("外帘打卷", "布帘", catalog)).isEqualTo("外帘打卷");
    }

    @Test
    @DisplayName("normalizeOperationName：35 条已登记；未登记的名字**原样返回**（商家自建工序不得 500）")
    void normalizeOperationNameIsIdentityForUnknownNames() {
        assertThat(service().normalizeOperationName("精裁-布")).isEqualTo("精裁");
        assertThat(service().normalizeOperationName("布三边")).isEqualTo("三边");
        assertThat(service().normalizeOperationName("布帘车被")).isEqualTo("车被");
        assertThat(service().normalizeOperationName("商家自建工序")).as("未登记 ⇒ 原样返回").isEqualTo("商家自建工序");
        assertThat(service().normalizeOperationName(null)).isNull();
    }

    // ══════════════════ 与真值源（routing.py）的同源判据 ══════════════════

    /**
     * 判据：Java 侧的「旧名 → 逻辑名」表与真值源 {@code routing.py::_LOGICAL_NAME_PAIRS}
     * **逐条双向一致**（少一条/多一条/映射不同都红）。
     *
     * <p>为什么按文本解析而不是抄一份断言常量：抄一份常量只能证明「我抄的和我想的一样」，
     * 不能证明「我和真值源一样」—— 而 Java 无法 import Python，文本解析是唯一可失败的同源判据
     * （既有先例：{@code ProductionRouteSignalMigrationTest} 逐字解析 {@code routing.py} 的 frozenset）。</p>
     */
    @Test
    @DisplayName("同源判据：旧名→逻辑名表与 routing.py::_LOGICAL_NAME_PAIRS 逐条双向一致")
    void logicalNameTableMatchesTruthSource() throws IOException {
        assertThat(Files.exists(ROUTING_PY))
                .as("找不到真值源 %s —— 锚点变了，请同步本判据", ROUTING_PY.toAbsolutePath())
                .isTrue();
        String py = Files.readString(ROUTING_PY);
        // ⚠️ 用 lastIndexOf：`_LOGICAL_NAME_PAIRS` 在 docstring 里也被提到过（首次出现不是定义处）
        int pairsAt = py.indexOf("_LOGICAL_NAME_PAIRS: List[tuple]");
        int namesAt = py.indexOf("OPERATION_LOGICAL_NAMES: Dict", pairsAt);
        // ⚠️ 真值源有**两段**：`_LOGICAL_NAME_PAIRS`（35 条多行有序对）+ `withSheerVariants`
        // 函数里的**单行** `dict(...)` 调用（issue #4937 的 4 条纱帘变体）。
        // ⇒ 两段一起解析（多行形态 + 单行形态），否则只读到 35 条而「运行期表 = 39 条」判据会红。
        Matcher matcher = Pattern.compile("\\n\\s*\\(\"([^\"]+)\",\\s*\"([^\"]+)\"\\),")
                .matcher(py.substring(pairsAt, namesAt));
        Matcher inline = Pattern.compile("\\(\"([^\"]+-纱)\",\\s*\"([^\"]+)\"\\)")
                .matcher(py);
        Map<String, String> fromPython = new LinkedHashMap<>();
        while (matcher.find()) {
            fromPython.put(matcher.group(1), matcher.group(2));
        }
        while (inline.find()) {
            fromPython.putIfAbsent(inline.group(1), inline.group(2));
        }
        // 🔴 issue #4937：真值源增加了 **4 条纱帘变体**（`熨烫-纱`/`定型-纱`/`复烫-纱`/`车被-纱`
        // —— `applicable` 过滤退场后它们会进纱帘路线，必须能解析回逻辑名）⇒ 35 → **39** 条。
        assertThat(fromPython)
                .as("真值源里应解析出 39 条有序对（35 条冻结段 + issue #4937 的 4 条纱帘变体）")
                .hasSize(39);
        // ⚠️ 比对**全表**（39 条）：Java 侧的运行期表 = 冻结的 35 条段
        // （`logicalNamePairs()`）+ 4 条纱帘变体段（`withSheerVariants(...)`，见生产代码注释）
        // ⇒ 两段合起来必须与真值源逐条一致。**不许**只比前 35 条：那会让新增的 4 条
        // **完全没有同源判据**（漂移不会红）。
        assertThat(logicalNamePairs())
                .as("Java 侧的「旧名 → 逻辑名」表必须与真值源逐条一致"
                        + "（改一处不改另一处 ⇒ 本判据红）")
                .isEqualTo(fromPython);
    }

    /** 旧工序名 → 逻辑工序名（从**生产代码**读：{@code normalizeOperationName} 的行为即本表的投影）。 */
    private Map<String, String> logicalNamePairs() {
        Map<String, String> names = new LinkedHashMap<>();
        for (String legacy : LEGACY_NAMES) {
            names.put(legacy, service().normalizeOperationName(legacy));
        }
        return names;
    }

    /** **39** 条旧工序名（真值源 {@code OPERATION_LOGICAL_NAMES} 的键集，逐条写出）。 */
    private static final List<String> LEGACY_NAMES = List.of(
            "精裁-布", "精裁-纱", "裁剪-布", "裁剪-纱", "布三边", "纱三边", "韩褶-布", "韩褶-纱",
            "上车布-布", "上车布-纱", "打孔-布", "打孔-纱", "拼1次-布", "拼2次-布", "拼3次-布",
            "花边-布", "铅坠-布", "接高-布", "帘头制作", "熨烫-布", "定型-布", "复烫-布",
            "布帘车被", "外帘打卷", "外帘装袋", "质检", "外帘发货", "绑带-布", "抱枕", "腰靠垫",
            "绑带-纱", "logo条-布", "立边-布", "扣环-布", "防翘扣-布",
            // issue #4937：4 道纱帘变体（见 `logicalNameTableMatchesTruthSource` 的注释）
            "熨烫-纱", "定型-纱", "复烫-纱", "车被-纱");

    /** 旧名的**部位**（测试侧推导：带后缀的直接读后缀；不规则名按真值源的表逐条给出）。 */
    private static String positionOfLegacyName(String legacy) {
        if (legacy.endsWith("-布")) {
            return "布帘";
        }
        if (legacy.endsWith("-纱")) {
            return "纱帘";
        }
        return switch (legacy) {
            case "布三边", "布帘车被" -> "布帘";
            case "纱三边" -> "纱帘";
            case "帘头制作" -> "帘头";
            // 部位无关的工序（外帘打卷/装袋/发货、质检、抱枕、腰靠垫）：往返判据对任意部位都成立
            // （它们走「裸逻辑名」那一档）⇒ 取一个代表部位即可。
            default -> "布帘";
        };
    }
}
