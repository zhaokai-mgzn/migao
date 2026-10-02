// case_ids: PR-007, PR-009, PR-010, PR-014
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.agent.AgentProductUpdateRequest;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.catchThrowable;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.atLeast;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 改前价（{@code before_price}）的**服务端回查**（issue #5317，涉钱面）。
 *
 * <h2>病灶</h2>
 * #5303 的护栏证明的是「<b>模型声称</b>改前是多少」（{@code before_price} 由模型从
 * {@code product_detail} 带回、服务端从不核对）⇒ 它只防「漏填」，不防「填错」。
 * 口径**照抄 #5314 的批次核对**（不另立第二套）：与 DB 当前值<b>按值核对</b>
 * （数字不比字符串写法），不符即拒绝。
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>按值比对</b>：{@code 10.0} 与 {@code 10.00} 是同一个价；不符 / 非法数字 / 当前值
 *       缺失 ⇒ false（fail-closed）；非价格字段按字面比对。</li>
 *   <li><b>单条商品级改价</b>：{@code beforePrice} 与 DB 当前 {@code base_price} 不符
 *       ⇒ <b>422</b> 且**零写**（一个 HTTP 都不发）。</li>
 *   <li><b>单条 SKU 改价</b>：与匹配到的 SKU 当前价不符 ⇒ 422 且零写。</li>
 *   <li><b>口径同源（L0 静态不变式）</b>：{@code sameValue} 在 admin-api main 源码里
 *       **只有一处定义**（{@code AgentWriteValues}），批次与单条两处调用点都引用它 ——
 *       防「批次严、单条松」的两处投影（{@code migao-dev-flow} §17.3）。</li>
 *   <li><b>跨语言同口径（issue #5414）</b>：Agent 侧（Python）的按值核对与本类的
 *       {@code sameValue} **跑同一份语料**
 *       （{@code backend/admin-api/src/test/resources/agent-write-values-corpus.json}）——
 *       两侧各自的测试都判它，任一侧改口径必有一侧红。</li>
 * </ol>
 *
 * <h2>边界（如实登记）</h2>
 * <ul>
 *   <li>{@code beforePrice} <b>缺席</b>时不核对（口径与 #5314 的 {@code oldValue} 一致：
 *       缺席 = 调用方没声明，工具层 {@code price_preview_required} 已 fail-closed 挡住无预览写）；
 *       服务端**不**因缺席而放行一次「声明可信」的假象 —— 它核对的永远只是「声明过的值」。</li>
 *   <li>前端行内改价端点（{@code PATCH /skus/{skuId}}，admin-web 在用）不带改前价 ⇒ 不属本判据面。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("改前价服务端回查（issue #5317）—— 口径与批次同源")
class AgentWriteValuesTest {

    private static final Long TENANT = 1L;
    private static final String P1 = "prod-001";

    @InjectMocks
    private ProductService productService;

    @Mock
    private ProductMapper productMapper;

    @Mock
    private ProductSkuMapper productSkuMapper;

    @Mock
    private com.migao.admin.mapper.ProductColorMapper productColorMapper;

    // `updateProduct` 的其余依赖（判据 1.5 会真的走进该路径 ⇒ 缺一个就 NPE 在**没跑到被测分支**前）。
    @Mock
    private com.migao.admin.mapper.ProductAttributeMapper productAttributeMapper;

    @Mock
    private com.migao.admin.mapper.CategoryMapper categoryMapper;

    @Mock
    private StockLedgerService stockLedgerService;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Product.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductSku.class);
    }

    private Product productWithPrice(String basePrice) {
        return Product.builder()
                .id(P1).tenantId(TENANT).name("遮光窗帘").status("on_sale")
                .basePrice(basePrice == null ? null : new BigDecimal(basePrice))
                .build();
    }

    private ProductSku skuWithPrice(String price) {
        return ProductSku.builder()
                .id(2001L).tenantId(TENANT).productId(P1)
                .colorName("米白").doorWidth("2.8")
                .price(price == null ? null : new BigDecimal(price))
                .stock(BigDecimal.valueOf(500)).skuCode("EVAL-BLK-28-米白").build();
    }

    private AgentProductUpdateRequest priceUpdate(String beforePrice) {
        AgentProductUpdateRequest req = new AgentProductUpdateRequest();
        req.setBasePrice(new BigDecimal("199.00"));
        if (beforePrice != null) {
            req.setBeforePrice(new BigDecimal(beforePrice));
        }
        return req;
    }

    /** 只给 `stock` 的部分更新（批量库存调整 `inventory_stock` 走的形态）。 */
    private AgentProductUpdateRequest stockUpdate(String stock) {
        AgentProductUpdateRequest req = new AgentProductUpdateRequest();
        req.setStock(new BigDecimal(stock));
        return req;
    }

    // ═══════════════ 判据 1.5：库存写必须落到 SKU（issue #5950 的红证）═══════════════

    /**
     * 只给 `stock` 的部分更新（批量库存调整走的形态）必须落到 **SKU 级**。
     *
     * <h2>病灶（红证 = 摘掉修复 ⇒ {@code stockOnlyUpdateReachesSkus} 必红）</h2>
     * `updateProduct` 的「改价落到 SKU」分支只认 {@code basePrice}
     * （`} else if (request.getBasePrice() != null) {`），而 `products.stock` 是
     * <b>派生冗余列</b>（唯一权威 = SKU 级，issue #4038），`getProductById` 又把响应里的
     * `stock` 覆盖成 SKU 汇总 ⇒ 只带 stock 的部分更新会「播放成功、回读旧值」
     * （与 #3743 假成功同型）。红色读数（修前）：`productSkuMapper.update(...)` 调用 **0 次**。
     *
     * <h2>桩面为什么只有这些</h2>
     * `updateProduct` 的依赖图很大；本组只铺**该路径真正会走到**的桩（selectById / 价格回查
     * selectOne / 库存同步 selectList + update），其余走 Mockito 默认值（`isBlank` 假 /
     * 集合默认空）—— 路径在「无颜色无 skus、图片为空、状态不变」这一支，不触发 SKU 重建
     * （那条分支的既有用例见 `ProductServiceTest`）。
     */
    @Nested
    @DisplayName("判据 1.5 —— 只给 stock 的部分更新必须落到 SKU 级（否则回读仍是旧库存）")
    class StockUpdateReachesSkus {

        @Test
        @DisplayName("修后：stock 落到 SKU 级并回写派生列 ⇒ 详情回读 = 新库存")
        void stockOnlyUpdateReachesSkus() {
            when(productMapper.selectOne(any(LambdaQueryWrapper.class)))
                    .thenReturn(productWithPrice("168.00"));
            when(productMapper.selectById(P1)).thenReturn(productWithPrice("168.00"));
            ProductSku sku = skuWithPrice("168.00");
            sku.setStock(new BigDecimal("1500.0"));
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku));

            productService.updateProductForAgent(P1, stockUpdate("1200.0"), TENANT);

            ArgumentCaptor<ProductSku> patch = ArgumentCaptor.forClass(ProductSku.class);
            verify(productSkuMapper).update(patch.capture(), any(LambdaQueryWrapper.class));
            assertThat(patch.getValue().getStock()).as("SKU 级被置为改后库存")
                    .isEqualByComparingTo("1200.0");
            // 派生列回写（`products.stock` = Σ SKU）+ 主更新 = 2 次（#4038：只写派生列 = 假成功）
            verify(productMapper, atLeast(2)).updateById(any(Product.class));
        }

        @Test
        @DisplayName("🔴 库存变更**必须落账**（#4157 的纪律）：摘掉 snapshot/record ⇒ 本条红")
        void stockChangeIsLedgeredAtTheExistingChokepoint() {
            when(productMapper.selectOne(any(LambdaQueryWrapper.class)))
                    .thenReturn(productWithPrice("168.00"));
            when(productMapper.selectById(P1)).thenReturn(productWithPrice("168.00"));
            ProductSku sku = skuWithPrice("168.00");
            sku.setStock(new BigDecimal("1500.0"));
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku));
            // 快照服务是替身 ⇒ 手工给它一份「变更前」快照（真实实现读的是 DB，本判据只看
            // **时序与入参**：快照必须发生在写之前、并把变更前的值交给落账比对）。
            ProductSku beforeSnapshot = skuWithPrice("168.00");
            beforeSnapshot.setStock(new BigDecimal("1500.0"));
            when(stockLedgerService.snapshotSkus(any())).thenReturn(Map.of(2001L, beforeSnapshot));

            productService.updateProductForAgent(P1, stockUpdate("1200.0"), TENANT);

            // 收口 = 变更前快照 + 变更后按实际值比对落账（既有唯一实现，不新造第二套）
            verify(stockLedgerService).snapshotSkus(any());
            ArgumentCaptor<Map<Long, ProductSku>> before = ArgumentCaptor.forClass(Map.class);
            verify(stockLedgerService).recordChangesAgainstSnapshot(
                    eq(TENANT), before.capture(), eq(StockLedger.REASON_MANUAL), isNull(),
                    contains("批量库存调整"));
            assertThat(before.getValue()).as("快照必须取自**变更前**（否则 delta 恒 0 ⇒ 台账没有真行）")
                    .containsKey(2001L);
            assertThat(before.getValue().get(2001L).getStock())
                    .as("快照里是变更前的值 1500 —— 落账依据是它")
                    .isEqualByComparingTo("1500.0");
        }
    }

    // ═══════════════ 判据 1：共享实现的按值比对 ═══════════════

    @Nested
    @DisplayName("判据 1 —— 按值比对（数字不比字符串写法）")
    class ValueComparison {

        @Test
        @DisplayName("10.0 / 10.00 / 10 是同一个价（写法不同不算不符）")
        void numericFormsAreEquivalent() {
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_BASE_PRICE, "10.0", "10.00"))
                    .isTrue();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_BASE_PRICE, "10", "10.000"))
                    .isTrue();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_BASE_PRICE, "168.00", "168"))
                    .isTrue();
        }

        @Test
        @DisplayName("真的不符 ⇒ false（编造改前价必被拦）")
        void mismatchIsFalse() {
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_BASE_PRICE, "168", "199"))
                    .isFalse();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_BASE_PRICE, "168.01", "168.00"))
                    .isFalse();
        }

        @Test
        @DisplayName("非法数字 / 当前值缺失 ⇒ false（fail-closed，不得为「没法比对」放行）")
        void unparsableOrMissingIsFalse() {
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_BASE_PRICE, "一百六十八", "168"))
                    .isFalse();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_BASE_PRICE, "168", null))
                    .isFalse();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_BASE_PRICE, null, "168"))
                    .isFalse();
        }

        @Test
        @DisplayName("非价格字段（status）按字面比对（不含数字语义）")
        void statusIsComparedLiterally() {
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_STATUS, "on_sale", "on_sale"))
                    .isTrue();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_STATUS, "off_sale", "on_sale"))
                    .isFalse();
        }

        @Test
        @DisplayName("库存（issue #5950）与价格同属**十进制数量列** ⇒ 按值比对，不按字符串写法")
        void stockIsComparedByNumericValue() {
            assertThat(AgentWriteValues.FIELD_STOCK).as("库存字段词 = 逐条写的同一个词")
                    .isEqualTo("stock");
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_STOCK, "1200.0", "1200.00"))
                    .as("10.0 与 10.00 是同一个库存")
                    .isTrue();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_STOCK, "800.5", "800.5"))
                    .isTrue();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_STOCK, "800.5", "800.6"))
                    .as("0.1 米粒度上真的不同 ⇒ 拒")
                    .isFalse();
            assertThat(AgentWriteValues.sameValue(AgentWriteValues.FIELD_STOCK, "800", null))
                    .as("一侧缺失 ⇒ fail-closed")
                    .isFalse();
        }

        @Test
        @DisplayName("判据 5·跨语言：与 Python 侧（Agent 确认面）**共用同一份语料**（issue #5414）")
        void sharedCorpusWithThePythonSide() throws Exception {
            JsonNode root;
            try (InputStream in = getClass()
                    .getResourceAsStream("/agent-write-values-corpus.json")) {
                assertThat(in).as("跨语言语料缺失（Agent 侧与本类共用它，缺了判据就名不副实）")
                        .isNotNull();
                root = new ObjectMapper().readTree(in);
            }
            JsonNode cases = root.get("cases");
            assertThat(cases).as("语料 cases 缺失").isNotNull();
            assertThat(cases.size()).as("语料为空 ⇒ 判据空转，宁可红").isGreaterThanOrEqualTo(10);

            List<String> mismatches = new ArrayList<>();
            for (JsonNode c : cases) {
                String field = c.get("field").asText();
                String given = textOrNull(c.get("given"));
                String current = textOrNull(c.get("current"));
                boolean expected = c.get("expect").asBoolean();
                boolean actual = AgentWriteValues.sameValue(field, given, current);
                if (actual != expected) {
                    mismatches.add(field + " given=" + given + " current=" + current
                            + " 期望=" + expected + " 实测=" + actual);
                }
            }
            assertThat(mismatches).as("与 Python 侧共用语料的判决不符（跨语言口径漂移）").isEmpty();
        }

        private static String textOrNull(JsonNode node) {
            return node == null || node.isNull() ? null : node.asText();
        }
    }

    // ═══════════════ 判据 2：单条商品级改价的服务端回查 ═══════════════

    @Nested
    @DisplayName("判据 2 —— 商品级：beforePrice 与 DB 当前价不符 ⇒ 422 且零写")
    class SingleProductPrice {

        @Test
        @DisplayName("不符 ⇒ 422（VALIDATION_ERROR），且一次写都不发生")
        void mismatchIsRejectedWith422() {
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(productWithPrice("168.00"));

            assertThatThrownBy(() -> productService.updateProductForAgent(P1, priceUpdate("999.00"), TENANT))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("改前价")
                    .satisfies(ex -> assertThat(((BusinessException) ex).getHttpStatus()).isEqualTo(422));
            verify(productMapper, never()).updateById(any(Product.class));
        }

        @Test
        @DisplayName("与当前价同值（写法不同 168 vs 168.00）⇒ **不**触发改前价拒绝")
        void matchingValueDoesNotTriggerTheRecheck() {
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(productWithPrice("168.00"));

            // 及格线之后的写入路径本测试不铺桩（那属于 updateProduct 的既有用例）——
            // 判据只看一件事：放行与否由「**不符**」决定，而不是由「有没有带改前价」决定。
            Throwable thrown = catchThrowable(
                    () -> productService.updateProductForAgent(P1, priceUpdate("168"), TENANT));

            if (thrown instanceof BusinessException be) {
                assertThat(be.getMessage()).as("同值被误判为不符 = 判据误伤合法输入").doesNotContain("改前价");
            }
        }

        @Test
        @DisplayName("DB 当前价为空而模型声明了改前价 ⇒ 拒绝（不可核对时 fail-closed）")
        void nullCurrentPriceIsRejected() {
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(productWithPrice(null));

            assertThatThrownBy(() -> productService.updateProductForAgent(P1, priceUpdate("168"), TENANT))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("改前价");
            verify(productMapper, never()).updateById(any(Product.class));
        }

        @Test
        @DisplayName("beforePrice 缺席 ⇒ 不做比对（口径与批次 oldValue 缺席一致）")
        void absentBeforePriceSkipsTheRecheck() {
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(productWithPrice("168.00"));

            Throwable thrown = catchThrowable(
                    () -> productService.updateProductForAgent(P1, priceUpdate(null), TENANT));

            if (thrown instanceof BusinessException be) {
                assertThat(be.getMessage()).doesNotContain("改前价");
            }
        }
    }

    // ═══════════════ 判据 3：单条 SKU 改价的服务端回查 ═══════════════

    @Nested
    @DisplayName("判据 3 —— SKU 级：beforePrice 与匹配到的 SKU 当前价不符 ⇒ 422 且零写")
    class SingleSkuPrice {

        @Test
        @DisplayName("不符 ⇒ 422，且不落库")
        void mismatchIsRejected() {
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(skuWithPrice("168.00")));

            assertThatThrownBy(() -> productService.updateSkuPrice(
                    P1, "米白", "2.8", new BigDecimal("150.00"), new BigDecimal("999.00"), TENANT))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("改前价");
            verify(productSkuMapper, never()).updateById(any(ProductSku.class));
        }

        @Test
        @DisplayName("与当前价同值（写法不同）⇒ 放行并落库")
        void equivalentValueIsAccepted() {
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(skuWithPrice("168.00")));
            when(productSkuMapper.updateById(any(ProductSku.class))).thenReturn(1);

            productService.updateSkuPrice(
                    P1, "米白", "2.8", new BigDecimal("150.00"), new BigDecimal("168"), TENANT);

            verify(productSkuMapper).updateById(any(ProductSku.class));
        }

        @Test
        @DisplayName("beforePrice 缺席 ⇒ 不做比对（既有调用点零影响）")
        void absentBeforePriceSkips() {
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(skuWithPrice("168.00")));
            when(productSkuMapper.updateById(any(ProductSku.class))).thenReturn(1);

            productService.updateSkuPrice(P1, "米白", "2.8", new BigDecimal("150.00"), null, TENANT);

            verify(productSkuMapper).updateById(any(ProductSku.class));
        }
    }

    // ═══════════════ 判据 4：口径同源（L0 静态不变式） ═══════════════

    @Nested
    @DisplayName("判据 4 —— 口径同源：单条与批次是同一实现（防两处投影）")
    class SingleSource {

        private static final String SERVICE_PKG = "src/main/java/com/migao/admin/service/";

        /** 定位被测源码（兼容从仓库根或模块目录运行 surefire） */
        private Path sourceFile(String name) {
            Path dir = Path.of(System.getProperty("user.dir")).toAbsolutePath();
            while (dir != null) {
                for (Path candidate : List.of(
                        dir.resolve(SERVICE_PKG).resolve(name),
                        dir.resolve("backend/admin-api").resolve(SERVICE_PKG).resolve(name))) {
                    if (Files.exists(candidate)) {
                        return candidate;
                    }
                }
                dir = dir.getParent();
            }
            throw new IllegalStateException("找不到 " + name + "（静态不变式无法校验）");
        }

        /** 去掉行注释后的代码行（静态不变式只看代码，防判据被自己的文案喂绿） */
        private List<String> codeLines(String name) throws Exception {
            List<String> out = new ArrayList<>();
            for (String raw : Files.readAllLines(sourceFile(name))) {
                out.add(raw.split("//", 2)[0]);
            }
            return out;
        }

        @Test
        @DisplayName("sameValue 在 main 源码里只有一处定义（唯一实现）")
        void comparatorHasASingleDefinition() throws Exception {
            List<String> definitions = new ArrayList<>();
            try (var walk = Files.walk(sourceFile("AgentWriteValues.java").getParent())) {
                for (Path path : walk.filter(p -> p.toString().endsWith(".java")).toList()) {
                    for (String line : Files.readAllLines(path)) {
                        if (line.split("//", 2)[0].matches(".*\\bboolean\\s+sameValue\\s*\\(.*")) {
                            definitions.add(path.getFileName() + ": " + line.trim());
                        }
                    }
                }
            }
            assertThat(definitions)
                    .as("价格核对出现了第二份实现（= 同一语义两处投影，§17.3）")
                    .hasSize(1);
            assertThat(definitions.get(0)).contains("AgentWriteValues.java");
        }

        @Test
        @DisplayName("批次（#5314）与单条改价（#5317）都引用共享实现")
        void bothPathsCallTheSharedComparator() throws Exception {
            List<String> batch = codeLines("AgentBatchService.java");
            List<String> product = codeLines("ProductService.java");

            assertThat(batch.stream().anyMatch(l -> l.contains("AgentWriteValues.sameValue(")))
                    .as("批次路径没有走共享实现（又立了第二套口径）")
                    .isTrue();
            assertThat(product.stream().filter(l -> l.contains("AgentWriteValues.sameValue(")).count())
                    .as("单条改价的两条路径（商品级 + SKU 级）必须都走共享实现")
                    .isGreaterThanOrEqualTo(2);
        }

        @Test
        @DisplayName("两个服务里不得再留本地的改前值比对（自己再比一遍 = 第二套口径）")
        void noLocalPriceComparisonLeft() throws Exception {
            // 形态判据 = `compareTo(...)` 且操作数是**声明的改前值**（beforePrice / oldValue）；
            // 与 ZERO 的合法性校验（"改后价不能为负"）不算 —— 那是另一件事。
            for (String name : List.of("AgentBatchService.java", "ProductService.java")) {
                List<String> offenders = codeLines(name).stream()
                        .filter(l -> l.contains("compareTo("))
                        .filter(l -> l.contains("beforePrice") || l.contains("getOldValue()")
                                || l.contains("oldValue"))
                        .toList();
                assertThat(offenders).as(name + " 里还有本地的改前值比对").isEmpty();
            }
        }
    }
}