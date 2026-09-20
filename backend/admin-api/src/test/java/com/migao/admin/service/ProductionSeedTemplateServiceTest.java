package com.migao.admin.service;

// case_ids: PG-036

import com.migao.admin.config.IndustryCodes;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductionSeedTemplateInfo;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionCraft;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.ProductionOptionFactor;
import com.migao.admin.entity.ProductionOptionRouting;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionOptionFactorMapper;
import com.migao.admin.mapper.ProductionOptionRoutingMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.dao.DuplicateKeyException;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * ProductionSeedTemplateService 单测（issue #4361 交付物 2/3）
 *
 * <p>覆盖三条机器可判的验收判据：</p>
 * <ol>
 *   <li><b>幂等</b>：连续套用两次，工序/路线行数不变（第二次全 skipped、零 insert）；</li>
 *   <li><b>{@code other} 行业不落任何生产行</b>，且返回**显式原因**（不静默空库）；</li>
 *   <li><b>模板缺失</b> ⇒ 显式失败（404），不是静默空库。</li>
 * </ol>
 *
 * <p>另钉两件本单的诚实性核心：<b>套用出来的每道工序都带 {@code source}</b>
 * （{@code 占位待确认} / {@code 推算}），以及<b>单价逐字等于模板</b>（不许在套用路径上
 * "顺手修正"数据 —— #4343 的修正要等客户确认）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ProductionSeedTemplateService 生产种子模板（issue #4361）")
class ProductionSeedTemplateServiceTest {

    @InjectMocks
    private ProductionSeedTemplateService service;

    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRoutingMapper productionRoutingMapper;
    @Mock
    private ProductionOptionRoutingMapper productionOptionRoutingMapper;
    @Mock
    private ProductionOptionFactorMapper productionOptionFactorMapper;
    @Mock
    private ProductionOperationPriceVersionMapper priceVersionMapper;
    // ── 新结构（P2b，issue #4459 §1④）：开租必须种「默认路线 + 默认工艺」 ──
    @Mock
    private com.migao.admin.mapper.ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private com.migao.admin.mapper.ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private com.migao.admin.mapper.ProductionCraftMapper productionCraftMapper;

    private static final Long TENANT = 42L;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        stubEmptyNewStructure();
    }

    /**
     * 新结构三表 + 工艺词表「空库」桩（各用例按需覆盖）。
     *
     * <p>lenient：负向用例（行业不匹配 ⇒ 不套用）根本不会走到它们 ⇒ 不被走的桩不该判失败。</p>
     */
    /**
     * 让工序库「insert 后可见」（Mockito 桩不会自动回读）：真实路径里 planPositions/planRouteTemplates
     * 读的是**刚插入**的工序库 ⇒ 桩必须把 insert 累积起来给 selectList 回读，否则
     * 「逻辑工序名集合」恒为空 ⇒ 主线/价目/规则全被过滤 ⇒ 假红。
     */
    private List<ProductionOperation> wireOperationLibrary() {
        List<ProductionOperation> store = new ArrayList<>();
        when(productionOperationMapper.selectList(any())).thenAnswer(inv -> store);
        when(productionOperationMapper.insert(any(ProductionOperation.class))).thenAnswer(inv -> {
            ProductionOperation op = inv.getArgument(0);
            if (op.getId() == null) {
                op.setId("op-" + store.size());
            }
            store.add(op);
            return 1;
        });
        return store;
    }

    private void stubEmptyNewStructure() {
        lenient().when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        lenient().when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());
        lenient().when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        lenient().when(productionCraftMapper.selectList(any())).thenReturn(List.of());
        lenient().when(productionRouteTemplateMapper.insert(
                org.mockito.ArgumentMatchers.<ProductionRouteTemplate>any())).thenReturn(1);
        lenient().when(productionOperationPositionMapper.insert(
                org.mockito.ArgumentMatchers.<com.migao.admin.entity.ProductionOperationPosition>any()))
                .thenReturn(1);
        lenient().when(productionRouteRuleMapper.insert(
                org.mockito.ArgumentMatchers.<com.migao.admin.entity.ProductionRouteRule>any())).thenReturn(1);
        lenient().when(productionCraftMapper.insert(
                org.mockito.ArgumentMatchers.<ProductionCraft>any())).thenReturn(1);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ══════════════════════ 目录 ══════════════════════

    @Nested
    @DisplayName("listTemplates — 模板目录")
    class ListTemplates {

        @Test
        @DisplayName("返回 curtain 模板（读真实模板文件）：35 工序 / 9 路线 / 16 选项映射")
        void listTemplates_returnsCurtainTemplate() {
            List<ProductionSeedTemplateInfo> templates = service.listTemplates();

            assertThat(templates).isNotEmpty();
            ProductionSeedTemplateInfo curtain = templates.stream()
                    .filter(t -> "curtain".equals(t.getTemplateId()))
                    .findFirst().orElse(null);
            assertThat(curtain).as("应包含 curtain 布艺模板").isNotNull();
            assertThat(curtain.getIndustry()).isEqualTo(IndustryCodes.CURTAIN);
            assertThat(curtain.getName()).contains("布艺");
            assertThat(curtain.getVersion()).isEqualTo(1);
            assertThat(curtain.getOperationCount()).isEqualTo(37);
            assertThat(curtain.getRoutingCount()).isEqualTo(9);
            assertThat(curtain.getOptionCount()).isEqualTo(16);
        }

        @Test
        @DisplayName("目录项 industry 恒属受控词表（模板键 = 受控 code，不是自由文本）")
        void listTemplates_industryIsControlledCode() {
            for (ProductionSeedTemplateInfo info : service.listTemplates()) {
                assertThat(IndustryCodes.VOCABULARY)
                        .as("模板 industry 必须是受控 code，否则按 industry 查模板会静默落空")
                        .contains(info.getIndustry());
            }
        }
    }

    // ══════════════════════ 套用：正向 ══════════════════════

    @Nested
    @DisplayName("applyTemplate — 一键套用")
    class ApplyTemplate {

        /**
         * 显式清桩 —— **实测必需**：Mockito 的 {@code @Nested} 内外层共享同一批
         * {@code @Mock} 实例，而 {@code MockitoExtension} 的自动清桩在嵌套类之间**不可靠**
         * （实测：外层/兄弟嵌套的 {@code selectList} 桩会漏进本类，让「第二个租户」读到
         * 上一个租户的行 —— 那正是本类要照出的形态，若不清桩会变成假红/假绿）。
         * 每个用例自己重新声明它需要的桩，判据才只依赖自己的前置。
         */
        @BeforeEach
        void resetMappers() {
            reset(productionOperationMapper, productionRoutingMapper,
                    productionOptionRoutingMapper, productionOptionFactorMapper, priceVersionMapper,
                    productionRouteTemplateMapper, productionOperationPositionMapper,
                    productionRouteRuleMapper, productionCraftMapper);
            stubEmptyNewStructure();
        }

        @Test
        @DisplayName("套用成功：35 工序 + 9 路线 + 16 选项映射 + 1 系数，逐条带 source")
        void apply_createsAllSeedRows() {
            wireOperationLibrary();

            Map<String, Object> result = service.applyTemplate(TENANT, IndustryCodes.CURTAIN);

            assertThat(result.get("templateId")).isEqualTo("curtain");
            assertThat(result.get("applied")).isEqualTo(true);
            assertThat(result.get("created_operations")).isEqualTo(37);
            assertThat(result.get("skipped")).isEqualTo(0);

            ArgumentCaptor<ProductionOperation> opCaptor = ArgumentCaptor.forClass(ProductionOperation.class);
            verify(productionOperationMapper, times(37)).insert(opCaptor.capture());
            // 每道工序都必须带 source（provenance 可见 = 本单的诚实性核心）
            assertThat(opCaptor.getAllValues())
                    .allSatisfy(op -> assertThat(op.getSource())
                            .as("工序 %s 套用后 source 为空 ⇒ provenance 不可见", op.getName())
                            .isIn(ProductionSeedTemplateService.OPERATION_SOURCES));
            // 单价逐字等于模板（不许在套用路径上"顺手修正" —— #4343 要等客户确认）
            ProductionOperation first = opCaptor.getAllValues().get(0);
            assertThat(first.getName()).isEqualTo("精裁-布");
            assertThat(first.getUnitPrice()).isEqualByComparingTo(new BigDecimal("0.40"));
            assertThat(first.getTenantId()).isEqualTo(TENANT);
            assertThat(first.getStatus()).isEqualTo("active");
            assertThat(first.getDeleted()).isZero();

            // 🔴 P0（issue #4459 §1④）：消费路径已切新结构 ⇒ 开租必须同时种
            // 「默认路线模板 + 默认工艺 + 部位价目 + 规则表」，否则该租户零默认 ⇒ 建单全 fail-closed
            ArgumentCaptor<ProductionRouteTemplate> rtCaptor =
                    ArgumentCaptor.forClass(ProductionRouteTemplate.class);
            // issue #4529：开租种**两条**基础路线（窗帘默认 + 布料）⇒ 恰一条 is_default
            verify(productionRouteTemplateMapper, times(2)).insert(rtCaptor.capture());
            ProductionRouteTemplate template = rtCaptor.getAllValues().stream()
                    .filter(t -> Boolean.TRUE.equals(t.getIsDefault())).findFirst().orElseThrow();
            assertThat(template.getIsDefault()).as("恰一条默认路线（缺它 ⇒ 建单 fail-closed）").isTrue();
            assertThat(template.getTenantId()).isEqualTo(TENANT);
            assertThat(template.getName()).isNotBlank();
            assertThat((List<?>) template.getMainline())
                    .as("主线必须非空（空主线 ⇒ 实例化零工序）").isNotEmpty();
            assertThat((List<?>) template.getPositions()).asString()
                    .isEqualTo(List.of("布帘", "纱帘", "帘头").toString());

            ArgumentCaptor<ProductionCraft> craftCaptor = ArgumentCaptor.forClass(ProductionCraft.class);
            verify(productionCraftMapper, times(1)).insert(craftCaptor.capture());
            assertThat(craftCaptor.getValue().getIsDefault())
                    .as("恰一条默认工艺（缺 craft 的订单取它；不得写死常量）").isTrue();

            // 部位价目：规范矩阵 ∩ 该租户工序库 —— **116 行**（issue #4676 改判）。
            // 改前 120（30 逻辑工序 × 4 部位，issue #4529）；V88 让 `配料` 退场
            // ⇒ 开租播种也不再种 `配料 × 4 部位` 这 4 行（120 − 4 = 116）。
            // ⚠️ 规范矩阵常量 `CANONICAL_POSITION_PRICES` **仍是 120 行**（与
            // `routing.py::_POSITION_PRICE_ROWS` 逐行同值、被
            // `test_routing_model_p2_consumers.py::test_seed_service_canonical_matrix_matches_truth_source`
            // 冻结）⇒ 退场只在**播种这一层**显式过滤，不改常量。本判据是**计数**，不是放宽：
            // 少/多一行都红（`times(116)` 是精确匹配）。
            ArgumentCaptor<com.migao.admin.entity.ProductionOperationPosition> positionCaptor =
                    ArgumentCaptor.forClass(com.migao.admin.entity.ProductionOperationPosition.class);
            verify(productionOperationPositionMapper, times(116)).insert(positionCaptor.capture());
            List<com.migao.admin.entity.ProductionOperationPosition> seededPositions =
                    positionCaptor.getAllValues();
            assertThat(seededPositions.stream()
                    .map(com.migao.admin.entity.ProductionOperationPosition::getLogicalName).distinct()
                    .toList())
                    .as("退场工序 `配料` 不得出现在开租播种的矩阵里（issue #4676；S6 的活路径）")
                    .doesNotContain("配料");
            assertThat(seededPositions.stream()
                    .filter(p -> "裁剪".equals(p.getLogicalName()) && "布料".equals(p.getPosition()))
                    .map(com.migao.admin.entity.ProductionOperationPosition::getApplicable).toList())
                    .as("保命格 `裁剪 × 布料` 必须 `applicable=TRUE`（否则新租户的布料单只剩 `打包` ⇒ S1）")
                    .containsExactly(true);
            assertThat(seededPositions.stream()
                    .filter(p -> "打包".equals(p.getLogicalName()))
                    .map(com.migao.admin.entity.ProductionOperationPosition::getPosition).toList())
                    .as("`打包` 的 4 格一格不少（交付工序绝不能用「删格」处理，issue #4676 ⑦）")
                    .containsExactlyInAnyOrder("布帘", "布料", "纱帘", "帘头");
            // 规则表：工艺变体 10 + 特殊选项 16 + 加工项触发 3（issue #4577）+ 计件系数档 1 = 30
            // （逐条按该租户工序库过滤）
            ArgumentCaptor<com.migao.admin.entity.ProductionRouteRule> ruleCaptor =
                    ArgumentCaptor.forClass(com.migao.admin.entity.ProductionRouteRule.class);
            verify(productionRouteRuleMapper, times(30)).insert(ruleCaptor.capture());
            // 加工项触发规则逐值（与 V84 迁移 / docs/sql/schema.sql 三源同值；`拼接`/`双眼皮` 不建行）
            assertThat(ruleCaptor.getAllValues().stream()
                    .filter(r -> "processing_item".equals(r.getTriggerKind()))
                    .map(r -> r.getTriggerValue() + "→" + r.getOperation() + "@" + r.getAfterOperation())
                    .toList())
                    .as("恰 3 条 processing_item 规则（花边/扣环/接高），`拼接`/`双眼皮` 刻意不建行")
                    .containsExactly("花边→花边@三边", "扣环→扣环@三边", "接高→接高@精裁");
            // 旧两表**不再写入**（P2b 起它们已退场：活跃行由 V73 软删）
            verify(productionRoutingMapper, never()).insert(org.mockito.ArgumentMatchers.<ProductionRouting>any());
            verify(productionOptionRoutingMapper, never()).insert(org.mockito.ArgumentMatchers.<ProductionOptionRouting>any());
            verify(productionOptionFactorMapper, never()).insert(org.mockito.ArgumentMatchers.<ProductionOptionFactor>any());
        }

        @Test
        @DisplayName("开租播种落库的 scope 逐行等于迁移链终态（issue #4715：外帘三道必须 set，落 position ⇒「布+纱」各付两次）")
        void apply_seedsScopeMatchingMigrationChainTerminalState() {
            wireOperationLibrary();

            service.applyTemplate(TENANT, IndustryCodes.CURTAIN);

            ArgumentCaptor<ProductionOperation> opCaptor = ArgumentCaptor.forClass(ProductionOperation.class);
            verify(productionOperationMapper, times(37)).insert(opCaptor.capture());
            Map<String, String> seeded = opCaptor.getAllValues().stream()
                    .collect(Collectors.toMap(ProductionOperation::getName, ProductionOperation::getScope,
                            (a, b) -> a, LinkedHashMap::new));

            // 🔴 本单的核心：`scope='set'` 的语义是「**一单一套一次，不按部位展开**」。
            // 模板缺 `scope` ⇒ `planOperations` 的 `asText("position")` 兜底成**部位级**
            // ⇒ 一樘「布帘 + 纱帘」订单里这三道**各实例化 2 次、各付两次**（#4408 双付家族）。
            assertThat(seeded)
                    .as("开租播种必须与 V67 ∪ V79 的迁移链终态**逐行同 scope** —— 分裂 ⇒ 同一道工序在"
                            + "「开租租户」与「存量租户」上行为不同，且没有任何东西会因此变红")
                    .containsEntry("外帘打卷", "set")
                    .containsEntry("外帘装袋", "set")
                    .containsEntry("外帘发货", "set")
                    .containsEntry("打包", "set");
            assertThat(seeded).hasSize(37);
            assertThat(seeded.values())
                    .as("scope 取值必须 ⊆ 闭词表 {position, set}（与写面校验同口径）")
                    .allSatisfy(scope -> assertThat(scope).isIn("position", "set"));
            // 反向护栏：部位级工序**不得**被误标成套级（多标 ⇒ 该道工序在「布+纱」单里少做一次 = 少发工资）
            assertThat(seeded)
                    .as("部位变体（布帘/纱帘各一道）必须仍是 position")
                    .containsEntry("韩褶-布", "position")
                    .containsEntry("韩褶-纱", "position");
            assertThat(seeded.entrySet().stream().filter(e -> "set".equals(e.getValue()))
                    .map(Map.Entry::getKey).sorted().toList())
                    .as("终态套级集合 = V67 三道 + V79 的 打包（恰好这四个，漏标/多标都红）")
                    .containsExactlyInAnyOrder("打包", "外帘打卷", "外帘装袋", "外帘发货");
        }

        @Test
        @DisplayName("幂等：连续套用两次，第二次全 skipped、零 insert（行数不变）")
        void apply_isIdempotentOnSecondCall() {
            // 用**调用计数**桩模拟「第一次调用时库是空的、之后库里已有全部种子行」——
            // 不用 `reset()` + 重新 `when()`：实测该写法在本环境**不可靠**（第二次 apply 仍读到
            // 空库 ⇒ 重插 9 条路线 + 16 条选项映射，而真实库里会撞
            // uk_production_routings_tenant_type_craft 等部分唯一索引）。计数桩让「第二次看到的
            // 库状态」由测试自己确定，判据不依赖 Mockito 的重桩行为。
            // 新结构：insert 后可见（否则第二次仍读到空库 ⇒ 重插默认路线/工艺/价目/规则）
            List<ProductionRouteTemplate> templateStore = new ArrayList<>();
            List<ProductionCraft> craftStore = new ArrayList<>();
            List<com.migao.admin.entity.ProductionOperationPosition> positionStore = new ArrayList<>();
            List<com.migao.admin.entity.ProductionRouteRule> ruleStore = new ArrayList<>();
            lenient().when(productionRouteTemplateMapper.selectList(any())).thenAnswer(inv -> templateStore);
            lenient().when(productionRouteTemplateMapper.insert(
                    org.mockito.ArgumentMatchers.<ProductionRouteTemplate>any())).thenAnswer(inv -> {
                templateStore.add(inv.getArgument(0));
                return 1;
            });
            lenient().when(productionCraftMapper.selectList(any())).thenAnswer(inv -> craftStore);
            lenient().when(productionCraftMapper.insert(
                    org.mockito.ArgumentMatchers.<ProductionCraft>any())).thenAnswer(inv -> {
                craftStore.add(inv.getArgument(0));
                return 1;
            });
            lenient().when(productionOperationPositionMapper.selectList(any())).thenAnswer(inv -> positionStore);
            lenient().when(productionOperationPositionMapper.insert(
                    org.mockito.ArgumentMatchers.<com.migao.admin.entity.ProductionOperationPosition>any()))
                    .thenAnswer(inv -> {
                        positionStore.add(inv.getArgument(0));
                        return 1;
                    });
            lenient().when(productionRouteRuleMapper.selectList(any())).thenAnswer(inv -> ruleStore);
            lenient().when(productionRouteRuleMapper.insert(
                    org.mockito.ArgumentMatchers.<com.migao.admin.entity.ProductionRouteRule>any()))
                    .thenAnswer(inv -> {
                        ruleStore.add(inv.getArgument(0));
                        return 1;
                    });
            AtomicInteger opCalls = new AtomicInteger();
            when(productionOperationMapper.selectList(any())).thenAnswer(inv ->
                    opCalls.getAndIncrement() == 0 ? List.of() : existingOperations());

            Map<String, Object> first = service.applyTemplate(TENANT, IndustryCodes.CURTAIN);
            assertThat(first.get("created_operations")).isEqualTo(37);
            assertThat(first.get("created_routings")).as("恰两条基础路线（窗帘默认 + 布料，issue #4529）")
                    .isEqualTo(2);
            assertThat(first.get("created_crafts")).as("恰一条默认工艺").isEqualTo(1);
            assertThat((int) first.get("created_positions")).isGreaterThan(0);

            Map<String, Object> second = service.applyTemplate(TENANT, IndustryCodes.CURTAIN);

            assertThat(second.get("created_operations")).as("第二次不得再插工序（幂等）").isEqualTo(0);
            assertThat(second.get("created_routings")).as("第二次不得再插路线模板（幂等）").isEqualTo(0);
            assertThat(second.get("created_crafts")).as("第二次不得再插默认工艺（幂等）").isEqualTo(0);
            assertThat(second.get("created_positions")).as("第二次不得再插部位价目（幂等）").isEqualTo(0);
            assertThat(second.get("created_route_rules")).as("第二次不得再插规则（幂等）").isEqualTo(0);
            assertThat(second.get("skipped"))
                    .as("第二次全部跳过：37 工序 + 2 路线模板（窗帘默认 + 布料，issue #4529）"
                            + " + 16 选项映射 + 1 系数档")
                    .isEqualTo(37 + 2 + 16 + 1);
            verify(productionOperationMapper, times(37)).insert(any(ProductionOperation.class));
            verify(productionRouteTemplateMapper, times(2)).insert(
                    org.mockito.ArgumentMatchers.<ProductionRouteTemplate>any());
            verify(productionCraftMapper, times(1)).insert(
                    org.mockito.ArgumentMatchers.<ProductionCraft>any());
            // 旧两表**不再写入**（P2b 起已退场）
            verify(productionRoutingMapper, never()).insert(
                    org.mockito.ArgumentMatchers.<ProductionRouting>any());
            verify(productionOptionRoutingMapper, never()).insert(
                    org.mockito.ArgumentMatchers.<ProductionOptionRouting>any());
            verify(productionOptionFactorMapper, never()).insert(
                    org.mockito.ArgumentMatchers.<ProductionOptionFactor>any());
        }

        @Test
        @DisplayName("部分存在：只补缺的那些（不重复插入已存在的工序/路线）")
        void apply_onlyInsertsMissing() {
            when(productionOperationMapper.selectList(any())).thenReturn(existingOperations());

            Map<String, Object> result = service.applyTemplate(TENANT, IndustryCodes.CURTAIN);

            assertThat(result.get("created_operations")).isEqualTo(0);
            assertThat(result.get("created_routings"))
                    .as("P2b：新结构里「路线」= 两条基础模板（窗帘默认 + 布料，issue #4529）").isEqualTo(2);
            assertThat(result.get("skipped")).isEqualTo(37);
        }

        @Test
        @DisplayName("按 templateId 套用（写面端点路径）：未知 templateId ⇒ 404 显式失败")
        void applyById_unknownTemplateFailsLoudly() {
            assertThatThrownBy(() -> service.industryOfTemplate("no-such-template"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("模板");
            verify(productionOperationMapper, never()).insert(any(ProductionOperation.class));
        }

        @Test
        @DisplayName("🔴 落库 id **不得**沿用模板 id：两个租户各套用一次都成功且 id 集合不相交")
        void applyGeneratesFreshIdsForEveryTenant() {
            // 模板 id（op-v54-01 / rt-v54-01 …）是**模板内的稳定键**，而 production_operations.id
            // 是**全局主键**且 1 号租户已占用 ⇒ 原样插库会撞主键，**第二个租户必崩**。
            // 本用例用一个模拟「全局主键唯一 + (tenant_id, name) 部分唯一索引」的假库来照这个形态：
            // ① 复用模板 id ⇒ 第二个租户插入时抛 DuplicateKeyException（红）；
            // ② 复用跨租户的确定性 id（如 op-t42-1）⇒ 第二个租户的 id 与第一个相交（红）。
            GlobalKeyFakeStore store = new GlobalKeyFakeStore();
            store.wire(productionOperationMapper, productionRoutingMapper,
                    productionOptionRoutingMapper, productionOptionFactorMapper, priceVersionMapper,
                    productionRouteTemplateMapper, productionOperationPositionMapper,
                    productionRouteRuleMapper, productionCraftMapper);

            store.asTenant(42L);
            Map<String, Object> first = service.applyTemplate(42L, IndustryCodes.CURTAIN);
            store.asTenant(77L);
            Map<String, Object> second = service.applyTemplate(77L, IndustryCodes.CURTAIN);

            assertThat(first.get("applied")).isEqualTo(true);
            assertThat(second.get("applied"))
                    .as("第二个租户套用必须同样成功 —— 撞主键的形态在这里变红")
                    .isEqualTo(true);
            assertThat(store.operationIdsOf(42L)).as("42 号租户落库工序数 = 模板工序数")
                    .hasSize(37);
            assertThat(store.operationIdsOf(77L)).hasSize(37);
            assertThat(store.operationNamesOf(42L)).isEqualTo(templateOperationNames());
            assertThat(store.operationNamesOf(77L)).isEqualTo(templateOperationNames());
            assertThat(store.operationIdsOf(42L))
                    .as("两租户的 id 集合必须**不相交**（复用模板 id / 跨租户确定性 id 都会相交或撞主键）")
                    .doesNotContainAnyElementsOf(store.operationIdsOf(77L));
            // P2b：路线 = 一条具名模板（不再是 9 条展开快照）⇒ 断言「每租户恰一条默认模板」
            assertThat(store.templateIdsOf(42L)).as("42 号租户恰两条基础路线模板（窗帘默认 + 布料）")
                    .hasSize(2);
            assertThat(store.templateIdsOf(77L)).hasSize(2);
            assertThat(store.templateIdsOf(42L))
                    .as("两租户的模板 id 必须**不相交**（复用模板 id 会撞主键）")
                    .doesNotContainAnyElementsOf(store.templateIdsOf(77L));
            // 幂等：对已套用过的租户再套一次 ⇒ 零新增（行数不变）
            int before = store.operationIdsOf(42L).size();
            store.asTenant(42L);
            service.applyTemplate(42L, IndustryCodes.CURTAIN);
            assertThat(store.operationIdsOf(42L)).as("重复套用不得产生第二份").hasSize(before);
        }
    }

    // ══════════════════════ 套用：负向（不静默） ══════════════════════

    @Nested
    @DisplayName("不套用的情形必须显式")
    class ExplicitSkip {

        @Test
        @DisplayName("other 行业 ⇒ 不落任何生产行 + 显式原因（不静默空库）")
        void otherIndustry_appliesNothingWithReason() {
            Map<String, Object> result = service.applyTemplate(TENANT, IndustryCodes.OTHER);

            assertThat(result.get("applied")).isEqualTo(false);
            assertThat(result.get("created_operations")).isEqualTo(0);
            assertThat(result.get("created_routings")).isEqualTo(0);
            assertThat(result.get("skipped")).isEqualTo(0);
            assertThat((String) result.get("reason"))
                    .as("other 行业必须给出**可读原因**：静默返回空结果会被读成「模板套用成功了但库是空的」")
                    .isNotBlank()
                    .contains(IndustryCodes.OTHER);
            verifyNoInteractions(productionOperationMapper);
            verifyNoInteractions(productionRoutingMapper);
            verifyNoInteractions(productionOptionRoutingMapper);
            verifyNoInteractions(productionOptionFactorMapper);
        }

        @Test
        @DisplayName("自由文本行业（未归一）⇒ 先归一为受控 code 再决定：布艺纺织 仍套用 curtain")
        void freeTextIndustry_isNormalizedFirst() {
            when(productionOperationMapper.selectList(any())).thenReturn(List.of());

            Map<String, Object> result = service.applyTemplate(TENANT, "布艺纺织");

            assertThat(result.get("applied")).isEqualTo(true);
            assertThat(result.get("created_operations")).isEqualTo(37);
        }

        @Test
        @DisplayName("未知行业（词表外）⇒ other 语义：不落行 + 原因里点名原值（可追查）")
        void unknownIndustry_namesTheRawValueInReason() {
            Map<String, Object> result = service.applyTemplate(TENANT, "家居建材");

            assertThat(result.get("applied")).isEqualTo(false);
            assertThat((String) result.get("reason")).contains("家居建材");
            verifyNoInteractions(productionOperationMapper);
        }

        @Test
        @DisplayName("null 行业 ⇒ other 语义：不落行 + 显式原因")
        void nullIndustry_appliesNothing() {
            Map<String, Object> result = service.applyTemplate(TENANT, null);

            assertThat(result.get("applied")).isEqualTo(false);
            assertThat((String) result.get("reason")).isNotBlank();
            verifyNoInteractions(productionOperationMapper);
        }
    }

    // ══════════════════════ 假库（模拟真实插入 + 唯一约束） ══════════════════════

    /**
     * 「全局主键唯一 + {@code (tenant_id, name)} 部分唯一索引」的假库。
     *
     * <p><b>为什么不能只用裸 mock</b>：裸 mock 的 {@code insert} 是空操作 ⇒
     * 「把模板 id 原样当落库 id」这个缺陷**照不出来**（两个租户都"成功"）。
     * 本类在 {@code insert} 里真做约束检查：
     * ① id 全局重复（含 1 号租户已占用的 {@code op-v54-01}）⇒ 抛
     * {@link DuplicateKeyException}，与真实 PG 主键冲突同形态；
     * ② {@code (tenant_id, name)} 重复 ⇒ 同样抛（对齐 V49 的部分唯一索引）；
     * ③ 顺带行使 {@code IdType.ASSIGN_UUID}（单测环境没有 MyBatis-Plus 拦截器，
     * 真跑时由框架填 id）⇒ 断言「落库 id 非空且跨租户不相交」。</p>
     */
    static final class GlobalKeyFakeStore {

        private final Map<String, ProductionOperation> operations = new LinkedHashMap<>();
        private final Map<String, ProductionRouting> routings = new LinkedHashMap<>();
        private final Map<String, ProductionRouteTemplate> templates = new LinkedHashMap<>();
        /** 1 号租户已占用的种子 id（V54/V56 的真实值）—— 模拟「主键已被占用」。 */
        private final Set<String> takenIds = new LinkedHashSet<>(
                List.of("op-v54-01", "op-v54-30", "op-v56-05", "rt-v54-01", "rt-v58-03"));

        @SuppressWarnings("unchecked")
        void wire(ProductionOperationMapper opMapper, ProductionRoutingMapper rtMapper,
                  ProductionOptionRoutingMapper optionMapper, ProductionOptionFactorMapper factorMapper,
                  ProductionOperationPriceVersionMapper priceMapper,
                  com.migao.admin.mapper.ProductionRouteTemplateMapper templateMapper,
                  com.migao.admin.mapper.ProductionOperationPositionMapper positionMapper,
                  com.migao.admin.mapper.ProductionRouteRuleMapper ruleMapper,
                  com.migao.admin.mapper.ProductionCraftMapper craftMapper) {
            when(templateMapper.selectList(any())).thenAnswer(inv ->
                    templates.values().stream()
                            .filter(t -> currentTenant.equals(t.getTenantId()))
                            .toList());
            when(templateMapper.insert(
                    org.mockito.ArgumentMatchers.<ProductionRouteTemplate>any())).thenAnswer(inv -> {
                ProductionRouteTemplate t = inv.getArgument(0);
                if (t.getId() == null) {
                    t.setId(java.util.UUID.randomUUID().toString());
                }
                templates.put(t.getId(), t);
                return 1;
            });
            when(positionMapper.selectList(any())).thenReturn(List.of());
            when(ruleMapper.selectList(any())).thenReturn(List.of());
            when(craftMapper.selectList(any())).thenReturn(List.of());
            when(positionMapper.insert(
                    org.mockito.ArgumentMatchers.<com.migao.admin.entity.ProductionOperationPosition>any()))
                    .thenReturn(1);
            when(ruleMapper.insert(
                    org.mockito.ArgumentMatchers.<com.migao.admin.entity.ProductionRouteRule>any()))
                    .thenReturn(1);
            when(craftMapper.insert(
                    org.mockito.ArgumentMatchers.<ProductionCraft>any())).thenReturn(1);
            when(opMapper.selectList(any())).thenAnswer(inv ->
                    operations.values().stream()
                            .filter(o -> o.getDeleted() != null && o.getDeleted() == 0)
                            .filter(o -> currentTenant.equals(o.getTenantId()))
                            .toList());

            when(opMapper.insert(any(ProductionOperation.class))).thenAnswer(inv -> {
                ProductionOperation op = inv.getArgument(0);
                // 模拟 ASSIGN_UUID（单测无 MyBatis-Plus 拦截器）
                if (op.getId() == null) {
                    op.setId(java.util.UUID.randomUUID().toString());
                }
                if (takenIds.contains(op.getId())) {
                    throw new DuplicateKeyException(
                            "duplicate key value violates unique constraint \"production_operations_pkey\""
                                    + " (id=" + op.getId() + ")");
                }
                boolean sameName = operations.values().stream().anyMatch(existing ->
                        existing.getDeleted() != null && existing.getDeleted() == 0
                                && existing.getTenantId().equals(op.getTenantId())
                                && existing.getName().equals(op.getName()));
                if (sameName) {
                    throw new DuplicateKeyException(
                            "duplicate key value violates unique constraint "
                                    + "\"uk_production_operations_tenant_name\" (tenant_id="
                                    + op.getTenantId() + ", name=" + op.getName() + ")");
                }
                takenIds.add(op.getId());
                operations.put(op.getId(), op);
                return 1;
            });
            // lenient：P2b 起旧两表**不再写入**（活跃行由 V73 软删）⇒ 这三个桩备而不用
            lenient().when(rtMapper.insert(any(ProductionRouting.class))).thenAnswer(inv -> {
                ProductionRouting rt = inv.getArgument(0);
                if (rt.getId() == null) {
                    rt.setId(java.util.UUID.randomUUID().toString());
                }
                if (takenIds.contains(rt.getId())) {
                    throw new DuplicateKeyException("duplicate key: production_routings_pkey");
                }
                takenIds.add(rt.getId());
                routings.put(rt.getId(), rt);
                return 1;
            });
            lenient().when(optionMapper.insert(any(ProductionOptionRouting.class))).thenReturn(1);
            lenient().when(factorMapper.insert(any(ProductionOptionFactor.class))).thenReturn(1);
            when(priceMapper.insert(any(ProductionOperationPriceVersion.class))).thenReturn(1);
        }

        List<String> operationIdsOf(Long tenantId) {
            return operations.values().stream()
                    .filter(o -> tenantId.equals(o.getTenantId()))
                    .map(ProductionOperation::getId)
                    .toList();
        }

        List<String> operationNamesOf(Long tenantId) {
            return operations.values().stream()
                    .filter(o -> tenantId.equals(o.getTenantId()))
                    .map(ProductionOperation::getName)
                    .toList();
        }

        List<String> templateIdsOf(Long tenantId) {
            return templates.values().stream()
                    .filter(t -> tenantId.equals(t.getTenantId()))
                    .map(ProductionRouteTemplate::getId)
                    .toList();
        }

        List<String> routingIdsOf(Long tenantId) {
            return routings.values().stream()
                    .filter(r -> tenantId.equals(r.getTenantId()))
                    .map(ProductionRouting::getId)
                    .toList();
        }

        /**
         * 当前「会话」的租户 —— 调用 {@link #wire} 之后、每次 {@code applyTemplate} 之前显式设置。
         *
         * <p><b>为什么假库必须尊重租户过滤</b>：不这么做就造出一个比生产更宽松的假库 ——
         * {@code selectList} 把所有租户的行都返回 ⇒ 第二个租户套用时「已存在」判据命中**别的租户**
         * 的行 ⇒ 该租户一条都插不进去，而假库还报「成功」（假绿）。实测踩过：
         * 这正是本用例最初照不出主键冲突的原因。</p>
         *
         * <p>不从 wrapper 里抠 tenantId：单测环境没有 MyBatis-Plus 的 TableInfo 缓存
         * （{@code getSqlSegment()} 抛「can not find lambda cache」），而
         * {@code getParamNameValuePairs()} 在本环境实测为空 map ⇒ 抠不出来。
         * 显式设置反而让「这次查询属于哪个租户」在测试里可读。</p>
         */
        private Long currentTenant = -1L;

        void asTenant(Long tenantId) {
            this.currentTenant = tenantId;
        }
    }

    // ══════════════════════ 桩数据 ══════════════════════

    private static List<ProductionOperation> existingOperations() {
        List<ProductionOperation> rows = new ArrayList<>();
        for (String name : templateOperationNames()) {
            rows.add(ProductionOperation.builder().id("op-" + name).tenantId(TENANT).name(name)
                    .status("active").deleted(0).build());
        }
        return rows;
    }

    private static List<ProductionRouting> existingRoutings() {
        List<ProductionRouting> rows = new ArrayList<>();
        for (String[] key : templateRoutingKeys()) {
            rows.add(ProductionRouting.builder().id("rt-" + key[0] + key[1]).tenantId(TENANT)
                    .curtainType(key[0]).craft(key[1]).status("active").deleted(0).build());
        }
        return rows;
    }

    private static List<ProductionOptionRouting> existingOptionRoutings() {
        List<ProductionOptionRouting> rows = new ArrayList<>();
        int i = 0;
        for (String[] key : templateOptionRoutingKeys()) {
            rows.add(ProductionOptionRouting.builder().id("opt-rt-" + (++i)).tenantId(TENANT)
                    .optionName(key[0]).operationName(key[1]).afterOperation(key[2])
                    .status("active").deleted(0).build());
        }
        return rows;
    }

    private static List<ProductionOptionFactor> existingOptionFactors() {
        List<ProductionOptionFactor> rows = new ArrayList<>();
        int i = 0;
        for (String[] key : templateOptionFactorKeys()) {
            rows.add(ProductionOptionFactor.builder().id("opt-fa-" + (++i)).tenantId(TENANT)
                    .optionName(key[0]).operationName("NULL".equals(key[1]) ? null : key[1])
                    .factor(new BigDecimal("1.7")).deleted(0).build());
        }
        return rows;
    }

    /**
     * 模板里的工序名 / 路线键（**读真实模板文件**，不写死第二份清单 ——
     * 写死即制造「测试绿而模板已漂移」的静默面）。
     */
    private static com.fasterxml.jackson.databind.JsonNode templateJson() {
        try (java.io.InputStream in = new org.springframework.core.io.ClassPathResource(
                "production-templates/curtain/seed.json").getInputStream()) {
            return new com.fasterxml.jackson.databind.ObjectMapper().readTree(in);
        } catch (java.io.IOException e) {
            throw new IllegalStateException("读取生产种子模板失败", e);
        }
    }

    private static List<String> templateOperationNames() {
        List<String> names = new ArrayList<>();
        templateJson().path("operations").forEach(node -> names.add(node.path("name").asText()));
        return names;
    }

    private static List<String[]> templateRoutingKeys() {
        List<String[]> keys = new ArrayList<>();
        templateJson().path("routings").forEach(node -> keys.add(new String[]{
                node.path("curtain_type").asText(), node.path("craft").asText()}));
        return keys;
    }

    private static List<String[]> templateOptionRoutingKeys() {
        List<String[]> keys = new ArrayList<>();
        templateJson().path("option_routings").forEach(node -> keys.add(new String[]{
                node.path("option_name").asText(), node.path("operation_name").asText(),
                node.path("after_operation").asText()}));
        return keys;
    }

    private static List<String[]> templateOptionFactorKeys() {
        List<String[]> keys = new ArrayList<>();
        templateJson().path("option_factors").forEach(node -> keys.add(new String[]{
                node.path("option_name").asText(),
                node.path("operation_name").isNull() ? "NULL" : node.path("operation_name").asText()}));
        return keys;
    }
}
