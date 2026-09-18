package com.migao.admin.service;

// case_ids: PG-036

import com.migao.admin.config.IndustryCodes;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductionSeedTemplateInfo;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPriceVersion;
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

    private static final Long TENANT = 42L;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
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
            assertThat(curtain.getOperationCount()).isEqualTo(35);
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
                    productionOptionRoutingMapper, productionOptionFactorMapper, priceVersionMapper);
        }

        @Test
        @DisplayName("套用成功：35 工序 + 9 路线 + 16 选项映射 + 1 系数，逐条带 source")
        void apply_createsAllSeedRows() {
            when(productionOperationMapper.selectList(any())).thenReturn(List.of());
            when(productionRoutingMapper.selectList(any())).thenReturn(List.of());
            when(productionOptionRoutingMapper.selectList(any())).thenReturn(List.of());
            when(productionOptionFactorMapper.selectList(any())).thenReturn(List.of());

            Map<String, Object> result = service.applyTemplate(TENANT, IndustryCodes.CURTAIN);

            assertThat(result.get("templateId")).isEqualTo("curtain");
            assertThat(result.get("applied")).isEqualTo(true);
            assertThat(result.get("created_operations")).isEqualTo(35);
            assertThat(result.get("created_routings")).isEqualTo(9);
            assertThat(result.get("skipped")).isEqualTo(0);

            ArgumentCaptor<ProductionOperation> opCaptor = ArgumentCaptor.forClass(ProductionOperation.class);
            verify(productionOperationMapper, times(35)).insert(opCaptor.capture());
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

            ArgumentCaptor<ProductionRouting> rtCaptor = ArgumentCaptor.forClass(ProductionRouting.class);
            verify(productionRoutingMapper, times(9)).insert(rtCaptor.capture());
            assertThat(rtCaptor.getAllValues())
                    .allSatisfy(rt -> assertThat(rt.getSource())
                            .isIn(ProductionSeedTemplateService.ROUTING_SOURCES));
            assertThat(rtCaptor.getAllValues().get(0).getOperations())
                    .isEqualTo(List.of("精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
                            "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货"));
            verify(productionOptionRoutingMapper, times(16)).insert(any(ProductionOptionRouting.class));
            verify(productionOptionFactorMapper, times(1)).insert(any(ProductionOptionFactor.class));
        }

        @Test
        @DisplayName("幂等：连续套用两次，第二次全 skipped、零 insert（行数不变）")
        void apply_isIdempotentOnSecondCall() {
            // 用**调用计数**桩模拟「第一次调用时库是空的、之后库里已有全部种子行」——
            // 不用 `reset()` + 重新 `when()`：实测该写法在本环境**不可靠**（第二次 apply 仍读到
            // 空库 ⇒ 重插 9 条路线 + 16 条选项映射，而真实库里会撞
            // uk_production_routings_tenant_type_craft 等部分唯一索引）。计数桩让「第二次看到的
            // 库状态」由测试自己确定，判据不依赖 Mockito 的重桩行为。
            AtomicInteger opCalls = new AtomicInteger();
            AtomicInteger rtCalls = new AtomicInteger();
            AtomicInteger optCalls = new AtomicInteger();
            AtomicInteger faCalls = new AtomicInteger();
            when(productionOperationMapper.selectList(any())).thenAnswer(inv ->
                    opCalls.getAndIncrement() == 0 ? List.of() : existingOperations());
            when(productionRoutingMapper.selectList(any())).thenAnswer(inv ->
                    rtCalls.getAndIncrement() == 0 ? List.of() : existingRoutings());
            when(productionOptionRoutingMapper.selectList(any())).thenAnswer(inv ->
                    optCalls.getAndIncrement() == 0 ? List.of() : existingOptionRoutings());
            when(productionOptionFactorMapper.selectList(any())).thenAnswer(inv ->
                    faCalls.getAndIncrement() == 0 ? List.of() : existingOptionFactors());

            Map<String, Object> first = service.applyTemplate(TENANT, IndustryCodes.CURTAIN);
            assertThat(first.get("created_operations")).isEqualTo(35);
            assertThat(first.get("created_routings")).isEqualTo(9);

            Map<String, Object> second = service.applyTemplate(TENANT, IndustryCodes.CURTAIN);

            assertThat(second.get("created_operations")).as("第二次不得再插工序（幂等）").isEqualTo(0);
            assertThat(second.get("created_routings")).as("第二次不得再插路线（幂等）").isEqualTo(0);
            assertThat(second.get("created_options")).isEqualTo(0);
            assertThat(second.get("created_option_factors")).isEqualTo(0);
            assertThat(second.get("skipped"))
                    .as("第二次全部跳过：35 工序 + 9 路线 + 16 选项映射 + 1 系数")
                    .isEqualTo(35 + 9 + 16 + 1);
            verify(productionOperationMapper, times(35)).insert(any(ProductionOperation.class));
            verify(productionRoutingMapper, times(9)).insert(any(ProductionRouting.class));
            verify(productionOptionRoutingMapper, times(16)).insert(any(ProductionOptionRouting.class));
            verify(productionOptionFactorMapper, times(1)).insert(any(ProductionOptionFactor.class));
        }

        @Test
        @DisplayName("部分存在：只补缺的那些（不重复插入已存在的工序/路线）")
        void apply_onlyInsertsMissing() {
            when(productionOperationMapper.selectList(any())).thenReturn(existingOperations());
            when(productionRoutingMapper.selectList(any())).thenReturn(List.of());
            when(productionOptionRoutingMapper.selectList(any())).thenReturn(List.of());
            when(productionOptionFactorMapper.selectList(any())).thenReturn(List.of());

            Map<String, Object> result = service.applyTemplate(TENANT, IndustryCodes.CURTAIN);

            assertThat(result.get("created_operations")).isEqualTo(0);
            assertThat(result.get("created_routings")).isEqualTo(9);
            assertThat(result.get("skipped")).isEqualTo(35);
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
                    productionOptionRoutingMapper, productionOptionFactorMapper, priceVersionMapper);

            store.asTenant(42L);
            Map<String, Object> first = service.applyTemplate(42L, IndustryCodes.CURTAIN);
            store.asTenant(77L);
            Map<String, Object> second = service.applyTemplate(77L, IndustryCodes.CURTAIN);

            assertThat(first.get("applied")).isEqualTo(true);
            assertThat(second.get("applied"))
                    .as("第二个租户套用必须同样成功 —— 撞主键的形态在这里变红")
                    .isEqualTo(true);
            assertThat(store.operationIdsOf(42L)).as("42 号租户落库工序数 = 模板工序数")
                    .hasSize(35);
            assertThat(store.operationIdsOf(77L)).hasSize(35);
            assertThat(store.operationNamesOf(42L)).isEqualTo(templateOperationNames());
            assertThat(store.operationNamesOf(77L)).isEqualTo(templateOperationNames());
            assertThat(store.operationIdsOf(42L))
                    .as("两租户的 id 集合必须**不相交**（复用模板 id / 跨租户确定性 id 都会相交或撞主键）")
                    .doesNotContainAnyElementsOf(store.operationIdsOf(77L));
            assertThat(store.routingIdsOf(42L)).hasSize(9);
            assertThat(store.routingIdsOf(77L)).hasSize(9);
            assertThat(store.routingIdsOf(42L)).doesNotContainAnyElementsOf(store.routingIdsOf(77L));
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
            when(productionRoutingMapper.selectList(any())).thenReturn(List.of());
            when(productionOptionRoutingMapper.selectList(any())).thenReturn(List.of());
            when(productionOptionFactorMapper.selectList(any())).thenReturn(List.of());

            Map<String, Object> result = service.applyTemplate(TENANT, "布艺纺织");

            assertThat(result.get("applied")).isEqualTo(true);
            assertThat(result.get("created_operations")).isEqualTo(35);
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
        /** 1 号租户已占用的种子 id（V54/V56 的真实值）—— 模拟「主键已被占用」。 */
        private final Set<String> takenIds = new LinkedHashSet<>(
                List.of("op-v54-01", "op-v54-30", "op-v56-05", "rt-v54-01", "rt-v58-03"));

        @SuppressWarnings("unchecked")
        void wire(ProductionOperationMapper opMapper, ProductionRoutingMapper rtMapper,
                  ProductionOptionRoutingMapper optionMapper, ProductionOptionFactorMapper factorMapper,
                  ProductionOperationPriceVersionMapper priceMapper) {
            when(opMapper.selectList(any())).thenAnswer(inv ->
                    operations.values().stream()
                            .filter(o -> o.getDeleted() != null && o.getDeleted() == 0)
                            .filter(o -> currentTenant.equals(o.getTenantId()))
                            .toList());
            when(rtMapper.selectList(any())).thenAnswer(inv ->
                    routings.values().stream()
                            .filter(r -> currentTenant.equals(r.getTenantId()))
                            .toList());
            when(optionMapper.selectList(any())).thenReturn(List.of());
            when(factorMapper.selectList(any())).thenReturn(List.of());

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
            when(rtMapper.insert(any(ProductionRouting.class))).thenAnswer(inv -> {
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
            when(optionMapper.insert(any(ProductionOptionRouting.class))).thenReturn(1);
            when(factorMapper.insert(any(ProductionOptionFactor.class))).thenReturn(1);
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
