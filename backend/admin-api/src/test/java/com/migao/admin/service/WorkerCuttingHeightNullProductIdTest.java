// case_ids: PG-059
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.CuttingHeightConfig;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductAttribute;
import com.migao.admin.mapper.CuttingHeightConfigMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.TenantParamAuditMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 类级判据（issue #6219）：**明细 {@code product_id} 为空**时，裁高读面不得 500。
 *
 * <h2>病灶（逐字）</h2>
 * {@code WorkerCuttingHeightService.positionRow} 曾写
 * {@code row.put("brand", item == null ? null : brands.get(item.getProductId()))}，
 * 而 {@code brands(...)} 在「没有任何明细带非空 product_id」时 {@code return Map.of();}（**不可变空表**）。
 * <b>JDK 语义</b>（Java 21 实跑）：{@code Map.of().get(null)} ⇒ {@code NullPointerException}；
 * {@code Map.of("k","v").get(null)} ⇒ NPE；{@code new LinkedHashMap<>().get(null)} ⇒ {@code null}。
 * ⇒ {@code order_items.product_id IS NULL} 时该端点 **500 INTERNAL_ERROR**，
 * 而该方法 javadoc 的设计意图恰是「缺 ⇒ {@code null}，**不猜**」—— 空值本应被容忍。
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>实例</b>：明细 {@code product_id} 为空 ⇒ {@link WorkerCuttingHeightService#read} 不得抛 NPE，
 *       且该行 {@code brand == null}（红证 = 修前 {@code return Map.of();} 那一版）；</li>
 *   <li><b>回归对照</b>：{@code product_id} 非空 ⇒ 行为**逐字不变** —— 属性存在 ⇒ 取属性值；
 *       属性缺失 ⇒ {@code null}（修前修后必须同读数）；</li>
 *   <li><b>同族守卫（未登记即红）</b>：{@code src/main} 内「返回**空不可变表**的方法」必须登记在
 *       {@link Ledger} 里，且其调用方的**索引读取点**也必须登记并写明「键是否可能为 null」——
 *       新增一个没登记的这类方法 / 调用点 ⇒ 当场红并具名。</li>
 * </ol>
 *
 * <h2>未覆盖 / 边界（如实登记）</h2>
 * 守卫只认「{@code return Map.of();} / {@code return Collections.emptyMap();}」这一族的**方法名**
 * （用大括号配平定位外层方法，不是"同一常量池"），以及调用方「{@code X = m(...)} ⇒ {@code X.get(k)}」
 * 这一形态；变量被跨行重赋 / 结果作实参传递后再索引的写法**判不到**（不做数据流分析）。
 * 台账的「键是否可能为 null」是**逐处人工判定**的结论，不是静态推断。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("类级判据 #6219：明细 product_id 为空 ⇒ 裁高读面不 500（不可变表 get(null) 抛 NPE）")
class WorkerCuttingHeightNullProductIdTest {

    private static final Long TENANT = 7L;
    private static final String ORDER_ID = "order-1";
    private static final String TOKEN = "7K3M9QP2";

    @Mock
    private ProductionScanService productionScanService;
    @Mock
    private CuttingHeightConfigMapper cuttingHeightConfigMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingOrderSetMapper processingOrderSetMapper;
    @Mock
    private ProductAttributeMapper productAttributeMapper;

    private WorkerCuttingHeightService service;

    @BeforeEach
    void setUp() {
        // **真** CuttingHeightConfigService（命中与取整的唯一实现）+ mock mapper（同既有测试口径）
        CuttingHeightConfigService configService = new CuttingHeightConfigService(cuttingHeightConfigMapper,
                new TenantParamAuditService(org.mockito.Mockito.mock(TenantParamAuditMapper.class),
                        new SimpleMeterRegistry(), new ObjectMapper()));
        service = new WorkerCuttingHeightService(productionScanService, configService, orderItemMapper,
                orderMapper, processingOrderMapper, processingOrderSetMapper, productAttributeMapper);
    }

    // ────────────────────────── ① 实例判据（修前红） ──────────────────────────

    @Test
    @DisplayName("🔴 明细 product_id 为空 ⇒ read() 不抛 NPE，且该行 brand=null（修前 = Map.of().get(null) ⇒ NPE）")
    void nullProductIdYieldsNullBrandInsteadOfNpe() {
        stubScan(scanView());
        stubOrderLine(List.of(cloth(null)));
        stubSupportRows(null);
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(config());

        Map<String, Object> out = service.read(TOKEN, TENANT);

        List<Map<String, Object>> positions = positionsOf(out);
        assertThat(positions).as("两部位都在（一个部位缺品牌不拖垮整屏）").hasSize(2);
        assertThat(positions.get(0))
                .as("缺 product_id ⇒ brand 如实为 null（不猜、不崩）；修前这里抛 NullPointerException ⇒ 端点 500")
                .containsEntry("brand", null);
        // 该行其余键照常给出 ⇒ 证明修的是「品牌这一层」，不是把整行吞掉
        assertThat(positions.get(0)).containsEntry("product_name", "全遮光布窗帘");
        assertThat((BigDecimal) positions.get(0).get("cutting_height")).isEqualByComparingTo("3.028");
    }

    @Test
    @DisplayName("🔴 全部明细 product_id 均为空 ⇒ brands() 走空集分支，仍不抛 NPE（空集分支的形态本身）")
    void allProductIdsNullStillReturnsOneScreen() {
        stubScan(scanView());
        stubOrderLine(List.of(cloth(null), gauze(null)));
        stubSupportRows(null);
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(config());

        Map<String, Object> out = service.read(TOKEN, TENANT);

        assertThat(positionsOf(out)).extracting(r -> r.get("brand")).containsExactly(null, null);
    }

    // ────────────────────────── ② 回归对照（非空 product_id 行为逐字不变） ──────────────────────────

    @Test
    @DisplayName("对照①：product_id 非空 + 品牌属性存在 ⇒ brand 取属性值（逐字不变）")
    void nonNullProductIdStillReadsBrandAttribute() {
        stubScan(scanView());
        stubOrderLine(List.of(cloth("p-cloth"), gauze(null)));
        stubSupportRows(null);
        when(productAttributeMapper.selectList(any())).thenReturn(List.of(
                ProductAttribute.builder().tenantId(TENANT).productId("p-cloth")
                        .attrKey("brand").attrValue("米高").build()));
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(config());

        Map<String, Object> out = service.read(TOKEN, TENANT);

        assertThat(positionsOf(out).get(0)).containsEntry("brand", "米高");
        assertThat(positionsOf(out).get(1)).containsEntry("brand", null);
    }

    @Test
    @DisplayName("对照②：product_id 非空但**品牌属性缺失** ⇒ brand=null（既有语义，不造值）")
    void nonNullProductIdWithoutAttributeStillYieldsNull() {
        stubScan(scanView());
        stubOrderLine(List.of(cloth("p-cloth"), gauze(null)));
        stubSupportRows(null);
        when(productAttributeMapper.selectList(any())).thenReturn(List.of()); // 没有任何 brand 属性行
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(config());

        Map<String, Object> out = service.read(TOKEN, TENANT);

        assertThat(positionsOf(out).get(0)).containsEntry("brand", null);
    }

    // ────────────────────────── ③ 同族守卫：未登记即红 ──────────────────────────

    @Test
    @DisplayName("🔴 同族守卫：src/main 内『返回空不可变表的方法』+ 其索引调用点必须全部登记（未登记即红）")
    void everyEmptyImmutableMapProducerAndItsIndexSiteIsRegistered() throws IOException {
        Path srcMain = repoRoot().resolve("backend/admin-api/src/main/java");
        List<Path> sources = javaSources(srcMain);
        assertThat(sources).as("普查面为空 ⇒ 本判据是空跑（源码目录搬走了？）").isNotEmpty();

        // ① 「方法体里含 `return Map.of();` / `return Collections.emptyMap();`」的方法名
        Set<String> producers = new LinkedHashSet<>();
        for (Path file : sources) {
            for (MethodBody body : methodBodies(Files.readAllLines(file))) {
                if (EMPTY_IMMUTABLE_RETURN.matcher(body.text()).find()) {
                    producers.add(body.name());
                }
            }
        }
        // 非空跑自证：本形态在真语料上确实存在（改名 / 搬家 ⇒ 先在这里红，而不是静默退化）
        assertThat(producers)
                .as("真语料里一个『返回空不可变表』的方法都没有 ⇒ 扫描实现失效（常量改名 / 目录搬走）")
                .isNotEmpty();

        List<String> offenders = new ArrayList<>();

        // R1-a 未登记的方法 ⇒ 红（新写一个 `return Map.of();` 的方法，没人给它登记索引面）
        for (String producer : producers) {
            if (!Ledger.PRODUCERS.containsKey(producer)) {
                offenders.add("【未登记的产出方】" + producer + "() 返回空不可变表 ⇒ 它的调用方一旦用空键索引"
                        + "就会 NPE 500（issue #6219）。出口：空集改返回 `LinkedHashMap`/`Collections.emptyMap`，"
                        + "或在 " + Ledger.class.getSimpleName() + ".PRODUCERS 登记并写明索引点。");
            }
        }

        // ② 调用点：`X = m(...)` ⇒ 后续 `X.get(...)` / `X.getOrDefault(...)`（同文件 / 跨文件）
        Set<String> indexSites = new LinkedHashSet<>();
        for (Path file : sources) {
            List<String> lines = codeOnlyLines(Files.readAllLines(file));
            String rel = repoRoot().relativize(file).toString().replace('\\', '/');
            for (int i = 0; i < lines.size(); i++) {
                for (String producer : producers) {
                    Matcher assign = Pattern
                            .compile("([A-Za-z_$][\\w$]*)\\s*=\\s*(?:[A-Za-z_$][\\w$]*\\.)?" + Pattern.quote(producer) + "\\s*\\(")
                            .matcher(lines.get(i));
                    if (!assign.find()) {
                        continue;
                    }
                    String variable = assign.group(1);
                    for (int j = i; j < Math.min(lines.size(), i + 200); j++) {
                        if (Pattern.compile("\\b" + Pattern.quote(variable) + "\\s*\\.\\s*(get|getOrDefault)\\s*\\(")
                                .matcher(lines.get(j)).find()) {
                            indexSites.add(rel + "|" + producer + "|" + variable + "|" + (j + 1));
                            break;
                        }
                    }
                }
            }
        }
        assertThat(indexSites)
                .as("『返回空不可变表的方法』的索引调用点一处都没扫到 ⇒ 判据退化（扫描实现失效）")
                .isNotEmpty();

        for (String site : indexSites) {
            String[] parts = site.split("\\|", 4);
            String rel = parts[0];
            String producer = parts[1];
            String variable = parts[2];
            int line = Integer.parseInt(parts[3]);
            String key = rel + "|" + variable;
            List<String> lines = codeOnlyLines(Files.readAllLines(repoRoot().resolve(rel)));

            Ledger.IndexSite registered = Ledger.INDEX_SITES.get(key);
            // R1-b 未登记的调用点 ⇒ 红（新调用方没登记，守不住「键是否可能为 null」）
            if (registered == null) {
                offenders.add("【未登记的索引调用点】" + rel + ":" + line + "（变量 " + variable
                        + " ← " + producer + "()）⇒ 不可变表的 `get(null)` 抛 NPE；出口：登记进 "
                        + Ledger.class.getSimpleName() + ".INDEX_SITES，逐字写下键表达式与判定依据。");
                continue;
            }
            // R2 台账条目必须仍指到真对象（对不上 ⇒ 红：防「清空/改写台账消红」与陈旧条目）
            if (!registered.variable().equals(variable) || !registered.producer().equals(producer)
                    || !registered.line().equals(line)) {
                offenders.add("【台账条目已陈旧】" + key + " 登记的是 " + registered.producer() + "()/第"
                        + registered.line() + " 行，现取是 " + producer + "()/第" + line + " 行 ⇒ 复核后更新台账。");
                continue;
            }

            if (registered.verdict() == Ledger.Verdict.KEY_NULLABLE_TRACKED_ELSEWHERE) {
                // 存量、本包文件族外 ⇒ 判据不在此处红；承载体 = 独立 issue + note 里的复算命令
                continue;
            }
            String keyExpression = registered.keyExpression();
            if (!siteToleratesNullKey(lines, line - 1, variable, registered)) {
                offenders.add("【空键索引未显式容忍】" + rel + ":" + line + "  `" + variable + ".get("
                        + keyExpression + ")`　登记判定=" + registered.verdict()
                        + "（keySource=`" + registered.keySource() + "`）⇒ 读法不是 getOrDefault/containsKey，"
                        + NULL_GUARD_WINDOW + " 行内也没有对**键表达式**（或其 `keySource`）的 `== null` 判空。"
                        + "出口：显式短路（`k == null ? null : m.get(k)`）、改 `getOrDefault`，"
                        + "或（键**确**非空时）登记 Verdict.KEY_PROVABLY_NON_NULL 并逐字写明依据。");
            }
        }

        assertThat(offenders)
                .as("不可变表 get(null) 同族：未登记 / 已陈旧 / 未显式容忍空键的形态（issue #6219）。\n"
                        + "出口见每条后面的『出口：』。\n" + String.join("\n", offenders))
                .isEmpty();
    }

    /**
     * 去注释 / 去字符串字面量后的源码行。
     *
     * <p>🔴 必须做：否则扫描会命中**注释与字符串里的示例文本**（实证：本文件那句
     * 「`brands.get(null)` 在不可变表上抛 NPE」的**说明性注释**被当成索引调用点 ⇒
     * 台账被钉在注释上、真正的调用点反而没人守）。</p>
     */
    private static List<String> codeOnlyLines(List<String> lines) {
        List<String> out = new ArrayList<>(lines.size());
        for (String line : lines) {
            out.add(line.replaceAll("\"(\\\\.|[^\"\\\\])*\"", "\"\"").replaceAll("//.*$", ""));
        }
        return out;
    }

    /**
     * 该索引点是否**容忍空键**。判定**逐处执行**（不读台账里手写的布尔值）：
     *
     * <ol>
     *   <li>读法本身与表可变性无关 ⇒ 容忍：{@code getOrDefault(} / {@code containsKey(}；</li>
     *   <li>读取点之前 {@value #NULL_GUARD_WINDOW} 行内对**键表达式**（或其 {@code keySource}）显式判空 ⇒ 容忍；</li>
     *   <li>台账声明键来源**确**非空（{@code KEY_PROVABLY_NON_NULL}，依据逐字写在 keySource/note）⇒ 容忍。</li>
     * </ol>
     *
     * <p>🔴 第 3 条是**有意**的出口：静态判不了「某个局部变量的值是否可为 null」，所以「确非空」只能由
     * 登记面承担；但出口必须写明依据，且该条目的 line/keySource 仍受「台账不许陈旧」约束。</p>
     */
    private static boolean siteToleratesNullKey(List<String> lines, int idx, String variable,
                                                Ledger.IndexSite site) {
        if (site.verdict() == Ledger.Verdict.KEY_PROVABLY_NON_NULL) {
            return true;
        }
        String line = lines.get(idx);
        if (Pattern.compile("\\b" + Pattern.quote(variable) + "\\s*\\.\\s*(getOrDefault|containsKey)\\s*\\(")
                .matcher(line).find()) {
            return true;
        }
        for (String candidate : List.of(site.keyExpression(), site.keySource())) {
            if (candidate.isBlank()) {
                continue;
            }
            for (int k = Math.max(0, idx - NULL_GUARD_WINDOW); k <= idx; k++) {
                if (Pattern.compile(Pattern.quote(candidate) + "\\s*(==|!=)\\s*null"
                                + "|null\\s*(==|!=)\\s*" + Pattern.quote(candidate))
                        .matcher(lines.get(k)).find()) {
                    return true;
                }
            }
        }
        return false;
    }

    /** 判别力自证：守卫的实体清单（台账）自身不许空转 —— 清了台账「消红」⇒ 当场红。 */
    @Test
    @DisplayName("🔴 台账不许空转：PRODUCERS / INDEX_SITES 非空，索引点的产出方必须自己也登记")
    void ledgerIsNotEmptied() {
        assertThat(Ledger.PRODUCERS).as("台账清空 ⇒ 上面那条守卫退化成空跑（fail-closed）").isNotEmpty();
        assertThat(Ledger.INDEX_SITES).as("台账清空 ⇒ 上面那条守卫退化成空跑（fail-closed）").isNotEmpty();
        assertThat(Ledger.PRODUCERS.keySet()).as("索引点的产出方必须自己也在 PRODUCERS 里")
                .contains("brands", "itemsOf", "costSkusByProduct");
        assertThat(Ledger.INDEX_SITES.values())
                .as("每条索引点登记都必须写明判定依据（空 note = 橡皮图章）")
                .allSatisfy(site -> assertThat(site.note()).isNotBlank());
    }

    // ============================================================ 台账（同族实体清单）

    /**
     * 同族实体清单（issue #6219）。**未登记即红**；判定口径逐条写在 {@code note} 里。
     *
     * <p>射程（如实登记）：只覆盖「{@code return Map.of();} / {@code return Collections.emptyMap();} 的**方法**
     * ⇒ 其调用方索引该结果」这一形态。⚠️ 本表**不**把 {@code Collections.emptyMap()} 当危险源 ——
     * 实跑读数（Java 21）：{@code Collections.emptyMap().get(null)} ⇒ {@code null}（**不抛**），
     * 只有 {@code Map.of()} / {@code Map.copyOf()} 抛 NPE。</p>
     */
    static final class Ledger {

        /** 方法名 → 判定（及关键位置，便于复核）。13 处 = 现取普查读数。 */
        static final Map<String, String> PRODUCERS = Map.ofEntries(
                Map.entry("brands", "本单病灶（WorkerCuttingHeightService）｜空集分支已改返回 LinkedHashMap"),
                Map.entry("itemsOf", "WorkerCuttingHeightService｜调用点自己判 `itemId == null` 短路"),
                Map.entry("costSkusByProduct", "DailyBriefingService｜调用点用 getOrDefault（与表可变性无关）"),
                Map.entry("sumRefundByOrder", "FinanceService｜调用点 getOrDefault(o.getId(), ZERO)"),
                Map.entry("snapshotProcessingSignatures", "OrderShipGuard｜调用点用 containsKey（不抛 NPE 的读法）"),
                Map.entry("getItemCountMap", "ProcessingCategoryService｜调用点 getOrDefault(c.getId(), 0L)"),
                Map.entry("getCategoryNameMap", "ProcessingItemService｜调用点 get(<可能为 null 的 categoryId>)，见台账 INDEX_SITES"),
                Map.entry("loadOrders", "ProcessingOrderService｜调用点 get(po.getOrderId())，见台账 INDEX_SITES"),
                Map.entry("specByItemIdOf", "ProductionScanService｜调用点自己判 `specByItemId == null` 短路"),
                Map.entry("itemIdToGroupKey", "ProductionService｜键 `spec.orderItemId()` 由调用点三元短路"),
                Map.entry("partTokensByItemId", "ProductionService｜现取无索引调用点（存量）"),
                Map.entry("assignmentsOf", "StockBatchConsumptionService｜现取无索引调用点（工人端读面待接）"),
                Map.entry("snapshotSkus", "StockLedgerService｜现取无索引调用点（存量）"));

        /**
         * 索引调用点台账：键 = {@code <仓库相对路径>|<变量>}。
         *
         * <p>每条**逐字**写下键表达式与判定依据 —— 判据会用它**执行**容忍判定（不读手写布尔值），
         * 所以「调用点把判空删掉」当场红。</p>
         */
        static final Map<String, IndexSite> INDEX_SITES = Map.ofEntries(
                // ── 本单：修完必须继续容忍空键（否则本单的判据当场红） ──
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/WorkerCuttingHeightService.java|brands",
                        new IndexSite("brands", "brands", "productId", "item.getProductId()", 153, Verdict.KEY_NULLABLE,
                                "本单病灶：product_id 可为空（存量明细）⇒ 已显式短路 + 空集改可变表（双重）")),
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/WorkerCuttingHeightService.java|items",
                        new IndexSite("items", "itemsOf", "itemId", "entry.get(\"order_item_id\")", 141, Verdict.KEY_NULLABLE,
                                "itemId 来自扫描结果可能为 null ⇒ `itemId == null ? null : items.get(itemId)` 短路")),
                // ── 存量：读法本身与表可变性无关（getOrDefault / containsKey） ──
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/DailyBriefingService.java|skusByProduct",
                        new IndexSite("skusByProduct", "costSkusByProduct", "line.getProductId()", "line.getProductId()", 975,
                                Verdict.READ_IS_NULL_TOLERANT, "getOrDefault(line.getProductId(), List.of()) ⇒ 空键安全")),
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/FinanceService.java|refundMap",
                        new IndexSite("refundMap", "sumRefundByOrder", "o.getId()", "o.getId()", 323,
                                Verdict.KEY_PROVABLY_NON_NULL,
                                "键 = Order.getId()（已注入参数非空）⇒ 键来源确非空；读取点另有 getOrDefault 兜底")),
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/OrderShipGuard.java|snapshot",
                        new IndexSite("snapshot", "snapshotProcessingSignatures", "row.getKey()", "row.getKey()", 157,
                                Verdict.READ_IS_NULL_TOLERANT, "containsKey(row.getKey()) ⇒ 空键安全")),
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/ProcessingCategoryService.java|itemCountMap",
                        new IndexSite("itemCountMap", "getItemCountMap", "c.getId()", "c.getId()", 50,
                                Verdict.READ_IS_NULL_TOLERANT, "getOrDefault(c.getId(), 0L) ⇒ 空键安全")),
                // ── 存量：get + 可能为 null 的键 ⇒ 由调用点显式短路（本包不改这些文件，仅登记） ──
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/ProductionScanService.java|specByItemId",
                        new IndexSite("specByItemId", "specByItemIdOf", "op.getOrderItemId()", "op.getOrderItemId()", 591,
                                Verdict.KEY_NULLABLE,
                                "调用点已 `specByItemId == null ? null : ...get(op.getOrderItemId())` 短路")),
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java|itemGroupKey",
                        new IndexSite("itemGroupKey", "itemIdToGroupKey", "spec.orderItemId()", "spec.orderItemId()", 261,
                                Verdict.KEY_NULLABLE,
                                "调用点已 `spec.orderItemId() == null ? null : setByGroup.get(...)` 短路")),
                // ── 存量同族风险点（本包文件族外，**不顺手改**）：键可能为 null 且本文件内无处置。
                //    承载体 = 独立 issue #6226（主会话按 origin/main 逐字复核开单）⇒ 本判据不在此红，
                //    但条目仍受「未登记即红 / 台账不许陈旧」约束。──
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/ProcessingItemService.java|categoryNameMap",
                        new IndexSite("categoryNameMap", "getCategoryNameMap", "item.getCategoryId()", "item.getCategoryId()", 72,
                                Verdict.KEY_NULLABLE_TRACKED_ELSEWHERE,
                                "存量同族 ⇒ 已转 issue #6226。形态：Map.of() 空集 + 非空分支 Collectors.toMap"
                                        + "（HashMap），两条分支都拒 null 键")),
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java|categoryNameMap",
                        new IndexSite("categoryNameMap", "getCategoryNameMap", "product.getCategoryId()", "product.getCategoryId()", 254,
                                Verdict.KEY_NULLABLE_TRACKED_ELSEWHERE,
                                "同上（另一调用点）⇒ 已转 issue #6226。对照：ProductService 自己的同名方法用 new HashMap<>()")),
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java|orders",
                        new IndexSite("orders", "loadOrders", "po.getOrderId()", "po.getOrderId()", 3661,
                                Verdict.KEY_NULLABLE_TRACKED_ELSEWHERE,
                                "存量同族 ⇒ 已转 issue #6226：po.getOrderId() 可为空，非空分支是 HashMap ⇒ 同样 NPE")));

        private Ledger() {
        }

        /** 一个索引调用点的登记。{@code line} 用于「台账不许陈旧」与容忍判定窗口。 */
        record IndexSite(String variable, String producer, String keyExpression, String keySource,
                         Integer line, Verdict verdict, String note) {
        }

        /** 判定分类（枚举而非布尔：三种处置形态在源码里语义不同，且布尔在 .as() 里读不出结论）。 */
        enum Verdict {
            /** 读法本身与表可变性无关（getOrDefault / containsKey）⇒ 空键安全。 */
            READ_IS_NULL_TOLERANT,
            /** 键可能为 null，但**读取点已显式短路**（或键来源自身确非空）⇒ 安全。 */
            KEY_NULLABLE,
            /** 键来源**确**非空（依据逐字写在 keySource/note）⇒ 不要求读取点判空。 */
            KEY_PROVABLY_NON_NULL,
            /** 键可能为 null 且**本文件里**无显式处置：存量、本包文件族外 ⇒ 已转独立 issue（不在本判据里红）。 */
            KEY_NULLABLE_TRACKED_ELSEWHERE
        }
    }

    // ============================================================ 夹具

    /** 扫码解析结果（部位级）：两部位（布帘扫到的 / 纱帘），与既有 PG-045 夹具同形。 */
    private static Map<String, Object> scanView() {
        Map<String, Object> scanned = new LinkedHashMap<>();
        scanned.put("order_item_id", "it-cloth");
        scanned.put("position_kind", "布帘");
        scanned.put("position_name", "布帘");
        Map<String, Object> cloth = new LinkedHashMap<>();
        cloth.put("order_item_id", "it-cloth");
        cloth.put("position_kind", "布帘");
        cloth.put("position_name", "布帘");
        cloth.put("remark", "左窗");
        Map<String, Object> gauze = new LinkedHashMap<>();
        gauze.put("order_item_id", "it-gauze");
        gauze.put("position_kind", "纱帘");
        gauze.put("position_name", "纱帘");
        Map<String, Object> cutPlan = new LinkedHashMap<>();
        cutPlan.put("order_item_id", "it-cloth");
        cutPlan.put("fabric_meters", new BigDecimal("8.10"));

        Map<String, Object> overview = new LinkedHashMap<>();
        overview.put("positions", List.of(cloth, gauze));
        overview.put("cut_plan", List.of(cutPlan));

        Map<String, Object> view = new LinkedHashMap<>();
        view.put("granularity", "set_position");
        view.put("order_id", ORDER_ID);
        view.put("processing_order_no", "JG20260929001");
        view.put("set_no", "1");
        view.put("set_index", 1);
        view.put("position", scanned);
        view.put("set_overview", overview);
        view.put("needs_selection", List.of());
        return view;
    }

    /** 布帘明细行；{@code productId} 可为 null（本单的触发条件）。 */
    private static OrderItem cloth(String productId) {
        OrderItem cloth = new OrderItem();
        cloth.setId("it-cloth");
        cloth.setTenantId(TENANT);
        cloth.setOrderId(ORDER_ID);
        cloth.setProductId(productId);
        cloth.setProductName("全遮光布窗帘");
        cloth.setWidth(new BigDecimal("3.500"));
        cloth.setHeight(new BigDecimal("2.700"));
        cloth.setCraft("韩褶");
        cloth.setCurtainType("布帘");
        cloth.setOpenCount(2);
        cloth.setCuttingMode("定高买宽");
        cloth.setFullness(new BigDecimal("2.0"));
        cloth.setIsShaped(true);
        cloth.setProcessingInfo(Map.of(
                "specialOptions", List.of("加线", "画线"),
                "processingItems", List.of(Map.of("name", "包边"))));
        return cloth;
    }

    private static OrderItem gauze(String productId) {
        OrderItem gauze = new OrderItem();
        gauze.setId("it-gauze");
        gauze.setTenantId(TENANT);
        gauze.setOrderId(ORDER_ID);
        gauze.setProductId(productId);
        gauze.setProductName("幻影纱");
        gauze.setHeight(new BigDecimal("2.400"));
        gauze.setCurtainType("纱帘");
        gauze.setProcessingInfo(Map.of("specialOptions", List.of("包纱折")));
        return gauze;
    }

    /** 与既有 PG-045 夹具同值（四项相加 3.0275 ⇒ 取整三位 3.028）。 */
    private static CuttingHeightConfig config() {
        List<Map<String, Object>> items = new ArrayList<>();
        items.add(cfgItem("jiaxian", "加线", "0.0625", hit("option", "加线", "布帘")));
        items.add(cfgItem("butie", "布贴", "0.015", hit("craft", "韩褶", null)));
        items.add(cfgItem("jiagao", "加高拼接", "0.2", hit("shaped", "true", null)));
        items.add(cfgItem("baobian", "包边", "0.05", hit("processing_item", "包边", null)));
        items.add(cfgItem("shahe", "纱折", "0.08", hit("option", "包纱折", "纱帘")));
        items.add(cfgItem("huaxian", "画线", null, hit("option", "画线", null)));
        return CuttingHeightConfig.builder()
                .tenantId(TENANT)
                .items(items)
                .rounding(Map.of("mode", "half_up", "digits", 3))
                .build();
    }

    private static Map<String, Object> cfgItem(String key, String name, String value, Map<String, Object> hit) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value == null ? null : new BigDecimal(value));
        item.put("direction", "add");
        item.put("height_join", false);
        item.put("hit", hit);
        item.put("hit_expr", null);
        item.put("enabled", true);
        return item;
    }

    private static Map<String, Object> hit(String kind, String value, String position) {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", kind);
        hit.put("trigger_value", value);
        hit.put("position", position);
        return hit;
    }

    private void stubScan(Map<String, Object> view) {
        when(productionScanService.resolve(TOKEN, null, TENANT)).thenReturn(view);
    }

    private void stubOrderLine(List<OrderItem> items) {
        when(orderItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(items);
    }

    /** 表头/套数查询（与本判据无关，给最小骨架即可）。 */
    private void stubSupportRows(Void unused) {
        when(orderMapper.selectOne(any())).thenReturn(com.migao.admin.entity.Order.builder()
                .id(ORDER_ID).tenantId(TENANT).orderNo("SO20260929001").customerName("张女士").build());
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(
                ProcessingOrder.builder().id("po-1").tenantId(TENANT).orderId(ORDER_ID).build()));
        when(processingOrderSetMapper.selectCount(any())).thenReturn(3L);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> positionsOf(Map<String, Object> out) {
        return (List<Map<String, Object>>) out.get("positions");
    }

    // ============================================================ 源码面工具（与 #5550 元守卫同款）

    /** 空键容忍判定的回溯窗口（读取点之前多少行内要找对键表达式的 `== null` 判空）。 */
    private static final int NULL_GUARD_WINDOW = 6;

    private static final Pattern EMPTY_IMMUTABLE_RETURN =
            Pattern.compile("return\\s+(Map\\.of\\(\\)|Collections\\.emptyMap\\(\\))\\s*;");

    private record MethodBody(String name, String text) {
    }

    /** 用大括号配平界定**方法体**（不是「往上找最近的方法名」—— 那会命中 `if` / `catch`）。 */
    private static List<MethodBody> methodBodies(List<String> lines) {
        List<MethodBody> out = new ArrayList<>();
        int i = 0;
        while (i < lines.size()) {
            Matcher decl = METHOD_DECL.matcher(lines.get(i));
            if (!decl.find()) {
                i++;
                continue;
            }
            int depth = braceDelta(lines.get(i));
            StringBuilder body = new StringBuilder(lines.get(i));
            int j = i;
            while (depth > 0 && j + 1 < lines.size()) {
                j++;
                body.append('\n').append(lines.get(j));
                depth += braceDelta(lines.get(j));
            }
            out.add(new MethodBody(decl.group(1), body.toString()));
            i = j + 1;
        }
        return out;
    }

    private static final Pattern METHOD_DECL = Pattern.compile(
            "^\\s*(?:(?:public|protected|private|static|final|synchronized|abstract|default|native)\\s+)+"
                    + "(?:<[^>]*>\\s*)?[\\w.<>\\[\\],\\s?]+?\\s+([A-Za-z_$][\\w$]*)\\s*\\([^;{]*\\)"
                    + "\\s*(?:throws\\s[\\w.,\\s]+)?\\{");

    /** 大括号配平（去掉字符串字面量与行注释，避免注释里的括号干扰）。 */
    private static int braceDelta(String line) {
        String stripped = line.replaceAll("\"(\\\\.|[^\"\\\\])*\"", "\"\"").replaceAll("//.*$", "");
        int delta = 0;
        for (int k = 0; k < stripped.length(); k++) {
            char c = stripped.charAt(k);
            if (c == '{') {
                delta++;
            } else if (c == '}') {
                delta--;
            }
        }
        return delta;
    }

    private static List<Path> javaSources(Path srcMain) throws IOException {
        try (Stream<Path> walk = Files.walk(srcMain)) {
            return walk.filter(p -> p.toString().endsWith(".java")).sorted(Comparator.naturalOrder()).toList();
        }
    }

    /** 与 {@code ProcessingInfoNullSafetyMetaGuardTest} 同款：从 surefire 的 cwd（模块目录）向上找仓库根。 */
    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位仓库根").isNotNull();
        return root;
    }
}
