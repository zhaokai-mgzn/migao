// case_ids: PR-122
package com.migao.admin.service;

import com.migao.admin.dto.ProductColorInput;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductSkuInput;
import com.migao.admin.dto.ProductUpdateRequest;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 商品 / SKU 文本入参**长度准入**的类级元守卫（issue #6302，铁律 8）。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 本单的实例缺陷是「{@code products.sku_code} 无长度准入 ⇒ 31 个字符 ⇒ PG 报
 * {@code value too long for type character varying(30)} ⇒ 500」。但**同一形态对
 * {@code products} / {@code product_skus} / {@code product_colors} 的每一列 varchar 都成立** ——
 * 只修货号这一处，下一个人在 {@code door_width} / {@code color_name} / {@code unit} 上会**原样再犯**，
 * 而没有任何东西会红。本守卫把「**DTO 字段 ⇄ 真库列长度 ⇄ 写面收口**」变成机械三方对账：
 * 新增一个 DTO 字段却没登记、登记了却没 PD 侧真实长度、或收了长度却没在写面收口 ⇒ **当场红并具名**。
 *
 * <h2>三方对账（判据 1）</h2>
 * <ol>
 *   <li><b>真值源 = 现取</b>：真 PG 上跑 {@code schema.sql} 终态，读
 *       {@code information_schema.columns.character_maximum_length}（**不许照抄 issue 的 30**，
 *       也**不许**读仓内 DDL 文本 —— 那与库的真实终态可能漂移）；</li>
 *   <li><b>登记面 = 本文件 {@link #registry()}</b>：四个商品入参 DTO 的**每一个 String 字段**
 *       必须登记，并给出它落哪张表的哪一列（或写明为什么不落 varchar 列）；</li>
 *   <li><b>收口面 = ProductService 的 {@code ColumnTextLength.requireWithinOrNull(...)} 调用点**
 *       （文本扫描，取 {@code get字段()} + 上限字面量 的成对读数）。</li>
 * </ol>
 * ⇒ {@code GATED} 条目要求「列在真库存在、且**收口上限 == 现取列长度**」：**列长度改了而调用点没改
 * ⇒ LENGTH-DRIFT 红**；调用了别的字段、或上限写成了 300（照抄 issue 的 30 是同一个坑的另一面）⇒ 红。
 *
 * <h2>可行动出口</h2>
 * 判红信息**具名**（哪个 DTO 字段 / 哪张表哪列 / 现取长度多少 / 缺哪种收口 + 可复制命令），出口两条：
 * ① 在对应写面加一行 {@code ColumnTextLength.requireWithinOrNull(getter, <现取列长度>, "…")}
 * 并在本文件登记为 {@code GATED}；② 确实不引入新输入源 ⇒ 登记为 {@code NO_COLUMN}（写理由）。
 * **豁免（{@code EXEMPT}，有界列却无收口）只许缩短**：冻结上限 = {@link #FROZEN_EXEMPT_BASELINE}，
 * 条数**现取**（判据 1/9 现场打印）。
 *
 * <h2>红证（判别力自证，判据 4~10 在内存里各注入一种坏形态）</h2>
 * 新增 DTO 字段未登记 / 台账条目空转（字段被删或改名）/ 有界列被登记成「无界」/
 * 收口调用被删 / 收口上限与现取列长度不一致 / 豁免条数长过冻结上限 / 扫描面为空 ⇒ 各自判红；
 * 同一夹具**不注入 ⇒ 不报**（判据 3，反向对照）。
 *
 * <h2>边界（如实登记，§19.1）</h2>
 * <ul>
 *   <li>射程 = 四个 DTO 的 {@code String} 字段（{@code ProductCreateRequest} / {@code ProductUpdateRequest} /
 *       {@code ProductSkuInput} / {@code ProductColorInput}）。**不覆盖**：Excel 导入的私有
 *       {@code ImportedRow}、agent 的 {@code AgentProductCreateRequest}（它们的超长值由
 *       {@code ProductService} 的同一批收口拦住 —— 行为面判据见
 *       {@code ProductSkuCodeLengthAdmissionTest} 判据 5）、前端 / ai-agent / mini-app。</li>
 *   <li>收口面是**文本扫描**（{@code get字段()} + 数字字面量），不解析 Java 语法：把长度换成常量 /
 *       变量 ⇒ 扫不到（会判 GATE-MISSING）。这是**有意**的取舍（判据必须可复算、不靠运行时反射）。</li>
 *   <li>「只许缩短」的机械半边 = {@code EXEMPT 条数 ≤ 冻结上限}；**判不了**「有人把冻结上限改大」
 *       —— 那落在 diff 评审里（与本仓既有台账同族边界）。</li>
 *   <li>本守卫**不跑**被它点名的那些测试（否则等于把全量套件再跑一遍）；
 *       「那段收口真的在运行时执行」由行为面判据承担（判据 5 的路径覆盖）。</li>
 * </ul>
 */
@DisplayName("商品文本列长度准入 · 类级元守卫（issue #6302）")
class ProductTextColumnAdmissionMetaGuardTest {

    private static final String PRODUCT_SERVICE_SOURCE =
            "backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java";

    /** 真值源 = 仓内 schema 终态（在真 PG 上跑一遍，再从 information_schema 现取列长度）。 */
    private static final String SCHEMA_SOURCE =
            "backend/admin-api/src/main/resources/db/init/schema.sql";

    /** 收口判据的文本锚（不写行号：行号会漂移）。 */
    private static final String GATE_MARKER = "ColumnTextLength.requireWithinOrNull(";

    /**
     * 收口调用扫描器：`ColumnTextLength.requireWithinOrNull(<任何>.getXxx(), <数字>, "…")`。
     * 只认「成套的取字段 + 数字上限」形态（变量/常量上限扫不到 ⇒ 判 GATE-MISSING，见类注释的边界）。
     */
    private static final Pattern GATE_CALL = Pattern.compile(
            "ColumnTextLength\\.requireWithinOrNull\\(\\s*[\\w.]*get(\\w+)\\(\\)\\s*,\\s*(\\d+)\\s*,");

    /**
     * 豁免台账的**冻结上限**（只许缩短）：本包落库时为 **0** —— 四个商品入参 DTO 的每一个有界文本字段
     * 都在写面收了长度（无一处例外）。将来新增字段若既无收口又无正当理由，只能进 {@code EXEMPT}
     * ⇒ **当场红**（判据 9）。
     */
    private static final int FROZEN_EXEMPT_BASELINE = 0;

    // ════════════════════════════ 台账（逐字段登记）════════════════════════════

    /** 该 DTO 字段与库列的关系。 */
    enum Kind {
        /** 落有界 varchar 列 ⇒ **必须**在写面过 {@code ColumnTextLength.requireWithinOrNull}，且上限 == 现取列长度。 */
        GATED,
        /** 落 TEXT（无长度上限）⇒ 无长度可违反（登记时核「现取长度确为 NULL」）。 */
        UNBOUNDED_TEXT,
        /** 不落这三张表的 varchar 列（如 brand 落 product_attributes）⇒ 写理由。 */
        NO_COLUMN,
        /** 落有界列却**无**收口 —— 债务，必须带跟进 issue 号，且条数只许缩短。 */
        EXEMPT
    }

    /** 台账条目：`<DTO>::<字段>` ⇒ 落哪张表哪列 + 关系。 */
    record Binding(Class<?> dto, String field, Kind kind, String table, String column, String note) {
    }

    private static Binding gated(Class<?> dto, String field, String table, String column) {
        return new Binding(dto, field, Kind.GATED, table, column,
                "写面过 ColumnTextLength（上限 = 现取列长度）");
    }

    private static Binding unbounded(Class<?> dto, String field, String table, String column) {
        return new Binding(dto, field, Kind.UNBOUNDED_TEXT, table, column, "TEXT 列，无长度上限");
    }

    private static Binding noColumn(Class<?> dto, String field, String note) {
        return new Binding(dto, field, Kind.NO_COLUMN, null, null, note);
    }

    /**
     * **字段台账**：四个商品入参 DTO 的**全部 String 字段**（未登记即红 —— 判据 1 的 UNREGISTERED）。
     *
     * <p>沿革：本包落库时 {@code EXEMPT = 0}（现取读数打印在判据 1）。</p>
     */
    private static List<Binding> registry() {
        List<Binding> r = new ArrayList<>();

        // ── ProductCreateRequest / ProductUpdateRequest → products ────────────────
        for (Class<?> dto : List.of(ProductCreateRequest.class, ProductUpdateRequest.class)) {
            r.add(gated(dto, "name", "products", "name"));                          // varchar(255)
            r.add(gated(dto, "skuCode", "products", "sku_code"));                    // varchar(30) ← 本单靶心
            r.add(gated(dto, "unit", "products", "unit"));                          // varchar(32)
            r.add(gated(dto, "pricingType", "products", "pricing_type"));            // varchar(30)
            r.add(gated(dto, "categoryId", "products", "category_id"));              // varchar(64)
            r.add(unbounded(dto, "description", "products", "description"));         // TEXT
            r.add(gated(dto, "mainImage", "products", "main_image"));                // varchar(512)
            r.add(gated(dto, "knowledgeBaseId", "products", "knowledge_base_id"));   // varchar(64)
            r.add(gated(dto, "status", "products", "status"));                       // varchar(32)
            r.add(noColumn(dto, "brand",
                    "brand 落 product_attributes（本表的品牌字典），不是 products 的列 ⇒ 无 varchar 上限"));
        }

        // ── ProductSkuInput → product_skus ───────────────────────────────────────
        r.add(gated(ProductSkuInput.class, "skuCode", "product_skus", "sku_code"));       // varchar(50)
        r.add(gated(ProductSkuInput.class, "doorWidth", "product_skus", "door_width"));   // varchar(20)
        r.add(gated(ProductSkuInput.class, "colorName", "product_skus", "color_name"));   // varchar(64)

        // ── ProductColorInput → product_colors ───────────────────────────────────
        r.add(gated(ProductColorInput.class, "colorName", "product_colors", "color_name"));         // varchar(30)
        r.add(gated(ProductColorInput.class, "mainColorHex", "product_colors", "main_color_hex")); // varchar(7)
        r.add(unbounded(ProductColorInput.class, "colorImageUrl", "product_colors", "color_image_url")); // TEXT
        r.add(gated(ProductColorInput.class, "remark", "product_colors", "remark"));               // varchar(30)

        return r;
    }

    // ════════════════════════════ 判据 1~2：真库 + 真实树 ════════════════════════════

    @Test
    @DisplayName("判据1：DTO 字段 ⇄ 现取 information_schema ⇄ 写面收口 三方对齐（未登记即红）")
    void everyProductTextFieldIsGatedAgainstItsLiveColumn() throws Exception {
        Map<String, Integer> live = liveLengths();
        Map<String, Set<String>> dtoFields = dtoStringFields();
        Map<String, Set<Integer>> gates = gatePairs(productServiceSource());

        List<String> violations = validate(live, registry(), gates, dtoFields);

        System.out.println("[#6302 元守卫] 现取 products/product_skus/product_colors 有界文本列 = "
                + live.entrySet().stream().filter(e -> e.getValue() != null).count() + " 列");
        System.out.println("[#6302 元守卫] 现取关键列长度：" + live.get("products.sku_code") + " (products.sku_code) / "
                + live.get("product_skus.sku_code") + " (product_skus.sku_code) / "
                + live.get("product_skus.door_width") + " (product_skus.door_width) / "
                + live.get("product_colors.color_name") + " (product_colors.color_name)");
        System.out.println("[#6302 元守卫] 登记字段 = " + registry().size() + " 条；EXEMPT 现取 = "
                + registry().stream().filter(b -> b.kind() == Kind.EXEMPT).count()
                + "（冻结上限 " + FROZEN_EXEMPT_BASELINE + "）");
        System.out.println("[#6302 元守卫] 写面收口读数 = " + gates);

        assertThat(violations)
                .as("商品文本列长度准入台账有 %d 条违规（未登记 / 空转 / 缺收口 / 与现取列长度不一致）",
                        violations.size())
                .isEmpty();
    }

    @Test
    @DisplayName("判据2（真库边界读数）：products.sku_code 现取 varchar(30) —— 30 字符落库成功、31 字符 PG 报 value too long")
    void realDbBoundaryReadingMatchesLiveColumn() throws Exception {
        Integer len = liveLengths().get("products.sku_code");
        assertThat(len)
                .as("现取 products.sku_code 的 character_maximum_length（issue 转述的 30 必须**现取复核**）")
                .isNotNull()
                .isEqualTo(30);

        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES "
                    + "(6302, 'acc-6302', 'acc-6302') ON CONFLICT DO NOTHING");
            // 边界：恰好 = 列上限 ⇒ 落库成功（修前实测 len=30 → 200 的库侧对应读数）
            st.execute("INSERT INTO products (id, tenant_id, name, sku_code) VALUES "
                    + "('p-6302-ok', 6302, '遮光窗帘布', '" + "A".repeat(len) + "')");
        }

        // 超 1 个字符 ⇒ PG 报错（**这是修前 500 的来源**）。判 SQLState 而不是英文文案：
        // 本机 PG 的 message 是**本地化**的（实测「对于可变字符类型来说，值太长了(30)」），
        // 而 issue 的服务端栈是英文（`value too long for type character varying(30)`）——
        // 两者是同一个错误码 22001（string_data_right_truncation）。
        Throwable tooLong = org.assertj.core.api.Assertions.catchThrowable(() -> {
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.execute("INSERT INTO products (id, tenant_id, name, sku_code) VALUES "
                        + "('p-6302-bad', 6302, '遮光窗帘布', '" + "A".repeat(len + 1) + "')");
            }
        });
        assertThat(tooLong)
                .as("超长写入在 PG 侧的表现（应用层准入必须拦在它之前）")
                .isInstanceOf(java.sql.SQLException.class);
        assertThat(((java.sql.SQLException) tooLong).getSQLState())
                .as("22001 = string_data_right_truncation（value too long for type character varying(%d)）", len)
                .isEqualTo("22001");
        assertThat(tooLong.getMessage()).contains(String.valueOf(len));
    }

    // ════════════════════════════ 判据 3~10：判别力自证（内存注入）════════════════════════════

    /** 干净夹具：一条 GATED + 一条 NO_COLUMN（无 EXEMPT —— 冻结上限已到 0，夹具留 EXEMPT 会自证假红）。 */
    private static List<Binding> cleanRegistry() {
        return List.of(
                gated(ProductSkuInput.class, "skuCode", "product_skus", "sku_code"),
                noColumn(ProductSkuInput.class, "id", "无库列"));
    }

    private static Map<String, Set<String>> cleanDtoFields() {
        Map<String, Set<String>> m = new TreeMap<>();
        m.put("ProductSkuInput", new TreeSet<>(Set.of("skuCode", "id")));
        return m;
    }

    private static Map<String, Integer> cleanLive() {
        Map<String, Integer> m = new TreeMap<>();
        m.put("product_skus.sku_code", 50);
        return m;
    }

    private static Map<String, Set<Integer>> cleanGates() {
        Map<String, Set<Integer>> m = new TreeMap<>();
        m.put("SkuCode", new TreeSet<>(Set.of(50)));
        return m;
    }

    @Test
    @DisplayName("判据3：夹具不注入 ⇒ 零违规（证明红由注入引起，不是夹具本身红）")
    void cleanFixtureHasNoViolation() {
        assertThat(validate(cleanLive(), cleanRegistry(), cleanGates(), cleanDtoFields())).isEmpty();
    }

    @Test
    @DisplayName("判据4：DTO 新增字段**未登记** ⇒ 具名红")
    void redproofUnregisteredDtoField() {
        Map<String, Set<String>> fields = cleanDtoFields();
        fields.put("ProductSkuInput", new TreeSet<>(Set.of("skuCode", "id", "newColumn")));

        assertThat(validate(cleanLive(), cleanRegistry(), cleanGates(), fields))
                .anySatisfy(v -> assertThat(v).contains("UNREGISTERED").contains("ProductSkuInput#newColumn"));
    }

    @Test
    @DisplayName("判据5：台账条目**空转**（字段被删/改名）⇒ 红")
    void redproofStaleLedgerEntry() {
        Map<String, Set<String>> fields = cleanDtoFields();
        fields.put("ProductSkuInput", new TreeSet<>(Set.of("id")));

        assertThat(validate(cleanLive(), cleanRegistry(), cleanGates(), fields))
                .anySatisfy(v -> assertThat(v).contains("STALE-REGISTRY").contains("ProductSkuInput#skuCode"));
    }

    @Test
    @DisplayName("判据6：有界列被登记成「无界」（TEXT）⇒ 红（拿无界当挡箭牌 = 未准入）")
    void redproofBoundedColumnRegisteredAsUnbounded() {
        List<Binding> reg = List.of(
                unbounded(ProductSkuInput.class, "skuCode", "product_skus", "sku_code"),
                noColumn(ProductSkuInput.class, "id", "无库列"));

        assertThat(validate(cleanLive(), reg, cleanGates(), cleanDtoFields()))
                .anySatisfy(v -> assertThat(v).contains("KIND-MISMATCH").contains("product_skus.sku_code"));
    }

    @Test
    @DisplayName("判据7：写面收口被删 ⇒ 红（登记未被兑现）")
    void redproofGateRemoved() {
        // 收口面非空（别的位置还有收口）但**这个字段**没有 ⇒ 判 GATE-MISSING（不是 SCAN-EMPTY）
        Map<String, Set<Integer>> gates = new TreeMap<>();
        gates.put("DoorWidth", new TreeSet<>(Set.of(20)));

        assertThat(validate(cleanLive(), cleanRegistry(), gates, cleanDtoFields()))
                .anySatisfy(v -> assertThat(v).contains("GATE-MISSING").contains("getSkuCode"));
    }

    @Test
    @DisplayName("判据8：收口上限与**现取列长度**不一致（如照抄 issue 把 50 写成 30，或 DDL 改了没跟）⇒ 红")
    void redproofGateLengthDrift() {
        Map<String, Set<Integer>> gates = cleanGates();
        gates.put("SkuCode", new TreeSet<>(Set.of(30)));   // 现取列长度是 50

        assertThat(validate(cleanLive(), cleanRegistry(), gates, cleanDtoFields()))
                .anySatisfy(v -> assertThat(v).contains("LENGTH-DRIFT").contains("50").contains("30"));
    }

    @Test
    @DisplayName("判据9：豁免条数长过冻结上限 ⇒ 红（豁免只许缩短）")
    void redproofExemptGrowth() {
        List<Binding> reg = new ArrayList<>(cleanRegistry());
        reg.set(0, new Binding(ProductSkuInput.class, "skuCode", Kind.EXEMPT, null, null, "缺口（跟单 #6302）"));

        assertThat(validate(cleanLive(), reg, cleanGates(), cleanDtoFields()))
                .anySatisfy(v -> assertThat(v).contains("EXEMPT-GREW"));
    }

    @Test
    @DisplayName("判据9'：豁免不写理由 / 不带 issue 号 ⇒ 红")
    void redproofExemptWithoutIssueOrReason() {
        List<Binding> reg = new ArrayList<>(cleanRegistry());
        reg.set(0, new Binding(ProductSkuInput.class, "skuCode", Kind.EXEMPT, null, null, " "));

        assertThat(validate(cleanLive(), reg, cleanGates(), cleanDtoFields()))
                .anySatisfy(v -> assertThat(v).contains("EXEMPT-WITHOUT-REASON"));
    }

    @Test
    @DisplayName("判据10：扫描面为空（发现规则失效）⇒ fail-closed 红")
    void redproofEmptyScanFailsClosed() {
        assertThat(validate(cleanLive(), cleanRegistry(), new TreeMap<>(), new TreeMap<>()))
                .anySatisfy(v -> assertThat(v).contains("SCAN-EMPTY"));
    }

    @Test
    @DisplayName("判据11：收口扫描器有牙 —— 真源码里认得出成套调用，抹掉则认不出")
    void scannerHasTeeth() {
        String source = "request.setSkuCode(ColumnTextLength.requireWithinOrNull(request.getSkuCode(), 30, \"商品货号 skuCode\"));";
        assertThat(gatePairs(source))
                .as("成套调用（getter + 数字上限）必须被扫出来")
                .containsEntry("SkuCode", new TreeSet<>(Set.of(30)));
        assertThat(gatePairs(source.replace(GATE_MARKER, "someOtherGate(")))
                .as("收口被换成别的东西 ⇒ 扫不到（判据 1 会判 GATE-MISSING，不是静默通过）")
                .isEmpty();
    }

    // ════════════════════════════ 发现 + 校验（纯函数，可注入）════════════════════════════

    /** 校验（纯函数，便于内存注入红证）：返回**违规清单**（空 = 通过）。 */
    static List<String> validate(Map<String, Integer> liveLengths,
                                 List<Binding> registry,
                                 Map<String, Set<Integer>> gatePairs,
                                 Map<String, Set<String>> dtoFields) {
        List<String> violations = new ArrayList<>();
        if (dtoFields.isEmpty() || gatePairs.isEmpty()) {
            violations.add("SCAN-EMPTY：发现规则没扫到 DTO 字段 / 写面收口 ⇒ 守卫在空跑（fail-closed）");
            return violations;
        }

        // ① DTO 字段未登记即红
        for (Map.Entry<String, Set<String>> e : dtoFields.entrySet()) {
            for (String field : e.getValue()) {
                boolean registered = registry.stream()
                        .anyMatch(b -> b.dto().getSimpleName().equals(e.getKey()) && b.field().equals(field));
                if (!registered) {
                    violations.add("UNREGISTERED：DTO 字段未登记到长度台账 ⇒ " + e.getKey() + "#" + field
                            + "（出口：登记为 GATED 并在写面加 ColumnTextLength 收口，或写明为什么不落 varchar 列）");
                }
            }
        }

        // ② 台账不许空转（登记的字段必须真在 DTO 里）
        for (Binding b : registry) {
            String key = b.dto().getSimpleName();
            if (!dtoFields.getOrDefault(key, Set.of()).contains(b.field())) {
                violations.add("STALE-REGISTRY：台账条目已不被扫到（字段被删/改名 ⇒ 同步台账）⇒ "
                        + key + "#" + b.field());
            }
        }

        // ③ 逐条核「列长度 / 收口 / 上限一致」
        for (Binding b : registry) {
            String id = b.dto().getSimpleName() + "#" + b.field();
            switch (b.kind()) {
                case GATED -> {
                    String key = b.table() + "." + b.column();
                    Integer live = liveLengths.get(key);
                    if (live == null) {
                        violations.add("COLUMN-NOT-FOUND：登记的表列在**现取** information_schema 里没有"
                                + "（或它不是有界 varchar）⇒ " + id + " → " + key
                                + "（可复制命令：psql \\d " + b.table() + "）");
                        break;
                    }
                    Set<Integer> admitted = gatePairs.getOrDefault(cap(b.field()), Set.of());
                    if (admitted.isEmpty()) {
                        violations.add("GATE-MISSING：有界列却扫不到写面收口 ⇒ " + id + " → " + key
                                + "（现取列长度 " + live + "）；出口：在写面加 "
                                + "ColumnTextLength.requireWithinOrNull(<x>." + "get" + cap(b.field())
                                + "(), " + live + ", \"…\")");
                    } else if (!admitted.contains(live)) {
                        violations.add("LENGTH-DRIFT：写面收口上限与**现取**列长度不一致 ⇒ " + id + " → " + key
                                + "（现取列长度 " + live + "，收口上限 " + new TreeSet<>(admitted) + "）"
                                + "；照抄 issue / 抄旧 DDL 就会踩这一条");
                    }
                }
                case UNBOUNDED_TEXT -> {
                    String key = b.table() + "." + b.column();
                    Integer live = liveLengths.get(key);
                    if (live != null) {
                        violations.add("KIND-MISMATCH：登记为 TEXT（无上限）但现取列有长度上限 ⇒ " + id + " → "
                                + key + "（character_maximum_length = " + live + "）⇒ 必须改为 GATED 并收口");
                    }
                }
                case NO_COLUMN -> {
                    if (b.note() == null || b.note().isBlank()) {
                        violations.add("EXEMPT-WITHOUT-REASON：NO_COLUMN 条目必须写理由 ⇒ " + id);
                    }
                }
                case EXEMPT -> {
                    if (b.note() == null || b.note().isBlank()) {
                        violations.add("EXEMPT-WITHOUT-REASON：豁免条目必须写理由 ⇒ " + id);
                    }
                    if (b.note() == null || !b.note().matches("(?s).*#\\d{3,}.*")) {
                        violations.add("EXEMPT-WITHOUT-ISSUE：豁免条目必须带跟进 issue 号 ⇒ " + id);
                    }
                }
            }
        }

        // ④ 豁免只许缩短（条数现取）
        long exempt = registry.stream().filter(b -> b.kind() == Kind.EXEMPT).count();
        if (exempt > FROZEN_EXEMPT_BASELINE) {
            violations.add("EXEMPT-GREW：豁免条数现取 = " + exempt + "，冻结上限 = " + FROZEN_EXEMPT_BASELINE
                    + "（豁免只许缩短；新增文本入参请落在写面收口上，不要塞进台账）");
        }
        return violations;
    }

    /** 收口扫描：`getter（首字母大写） → {上限字面量}`。 */
    static Map<String, Set<Integer>> gatePairs(String source) {
        Map<String, Set<Integer>> pairs = new TreeMap<>();
        Matcher m = GATE_CALL.matcher(source);
        while (m.find()) {
            pairs.computeIfAbsent(m.group(1), k -> new TreeSet<>()).add(Integer.parseInt(m.group(2)));
        }
        return pairs;
    }

    /** 四个商品入参 DTO 的 String 字段（反射现取，不硬编码字段清单）。 */
    static Map<String, Set<String>> dtoStringFields() {
        Map<String, Set<String>> found = new TreeMap<>();
        for (Class<?> dto : List.of(ProductCreateRequest.class, ProductUpdateRequest.class,
                ProductSkuInput.class, ProductColorInput.class)) {
            Set<String> fields = new TreeSet<>();
            for (Field f : dto.getDeclaredFields()) {
                if (f.getType() == String.class && !Modifier.isStatic(f.getModifiers())) {
                    fields.add(f.getName());
                }
            }
            found.put(dto.getSimpleName(), fields);
        }
        return found;
    }

    private static String cap(String field) {
        return Character.toUpperCase(field.charAt(0)) + field.substring(1);
    }

    private static String productServiceSource() throws IOException {
        return Files.readString(repoRoot().resolve(PRODUCT_SERVICE_SOURCE));
    }

    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(SCHEMA_SOURCE))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 %s（守卫的真值源 = 仓库里的 schema 终态）", SCHEMA_SOURCE).isNotNull();
        return root;
    }

    // ════════════════════════════ 真 PG（现取 information_schema）════════════════════════════

    private static PgCluster cluster;
    private static DataSource dataSource;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(Files.readString(repoRoot().resolve(SCHEMA_SOURCE)));
        }
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    /** 现取列长度：`表.列 → character_maximum_length`（TEXT = null）。 */
    private static Map<String, Integer> liveLengths() throws Exception {
        Map<String, Integer> lengths = new TreeMap<>();
        String sql = "SELECT table_name, column_name, character_maximum_length FROM information_schema.columns "
                + "WHERE table_schema = 'public' "
                + "AND table_name IN ('products', 'product_skus', 'product_colors')";
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            while (rs.next()) {
                int len = rs.getInt(3);
                // 🔴 `wasNull()` 必须在**任何**其它 getter 之前读：后续 `rs.getString(...)` 会把它重置成 false
                // （本判据第一版就踩了这一条 —— 结果是 TEXT 列被读成 0，三条 KIND-MISMATCH 假红）。
                boolean unbounded = rs.wasNull();
                String key = rs.getString(1) + "." + rs.getString(2);
                lengths.put(key, unbounded ? null : len);
            }
        }
        assertThat(lengths).as("现取不到列元数据 ⇒ 守卫会静默空跑").isNotEmpty();
        return lengths;
    }
}
