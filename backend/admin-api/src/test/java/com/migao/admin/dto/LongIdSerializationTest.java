package com.migao.admin.dto;
// case_ids: OR-063

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Long 主键序列化精度（订单确认付款扣库存链路 + issue #6340 工人端拍照入库）。
 *
 * <p>product_skus.id / product_colors.id 为 BIGSERIAL，实际值已超过 JS 安全整数
 * 2^53（9007199254740992）。若以 JSON number 返回，前端 JS 解析会失真
 * （2093675370043592706 → 2093675370043592704）：
 * 订单创建后 processingInfo.skuId 失真 → 确认付款时 matchSkuId 查不到 SKU → 库存视为 0 件 → 拒绝确认支付。</p>
 *
 * <p>issue #6340 是同一族的第二个实例：工人端 {@code POST /api/worker/inbound/recognize} 把
 * {@code skuId} 按 JSON number 发出 ⇒ 页面 {@code JSON.parse} 当场吞掉末两位 ⇒ 回传建草稿时
 * 服务端报「商品明细第 1 项的 SKU 不属于该商品（或不存在）」。⇒ 这类保护是**逐字段**
 * 加 {@code @JsonSerialize(using = ToStringSerializer.class)}（仓内没有全局 Long→String 规则），
 * 所以「只点名两个 DTO」的断言拦不住新漏标。</p>
 *
 * <p><b>判据分两层</b>：① <b>实例层</b>（{@code idLikeFields_above2pow53_shouldSerializeAsString}）
 * 把本族 DTO 逐个跑真序列化，逐字段断言「字符串出参」；② <b>类级层</b>
 * （{@code everyIdLikeLongFieldInScopeMustBeAnnotated}）对<b>整族源文件现取</b>
 * 每一个「id 形态的 {@code Long} 字段」，缺注解即红（具名打印 文件:行 → 字段）——
 * 🔴 这一层才是「新漏标进不来」的机制，{@code REGISTERED_EXCEPTIONS} 是它**唯一**的出口，
 * 且**只许缩短**。</p>
 *
 * <p><b>边界（照实登记）</b>：类级层的射程 = {@code ID_LIKE_SCAN_SCOPE} 列出的文件
 * （= issue #6340 清点的同族 + {@code InboundLabelView}——同一读面的 {@code itemId}）。
 * 射程**之外**新增一个「雪花 id 出参但未加保护」的 DTO **不会**被本判据拦到：
 * 判据不做全包枚举（那会让既有业务 Long 成为噪声、把真信号埋掉）。扩射程 = 往
 * {@code ID_LIKE_SCAN_SCOPE} 加一行 + 同 PR 补注解（约束类判据必须同 PR 补齐被约束对象）。</p>
 *
 * <p>本类**只**判「出参序列化形态」：入参 DTO（{@code *Request} / {@code *Input}）不在射程内 ——
 * Jackson 能从字符串强转 {@code Long}，实测字符串入参可用（issue #6340 绿对照）。</p>
 */
class LongIdSerializationTest {

    private final ObjectMapper mapper = new ObjectMapper();

    /** 真实量级里的「本族实例」：全部 ≥ 2.1e18（> 2^53 = 9007199254740991） */
    private static final long REAL_WORKER_SKU_ID = 2106900122848247810L;

    private static final long REAL_ITEM_ID = 2097126615461462018L;

    private static final long REAL_PRODUCT_COLOR_ID = 2093675369993261000L;

    /**
     * 类级层的射程：**本族** DTO 源文件（仓库相对路径，从 {@code backend/admin-api} 上溯到仓库根）。
     *
     * <p>逐字取自 issue #6340 的源码面清点（5 个同族 DTO）+ {@code InboundLabelView}
     * （同一入库读面的 {@code itemId}，雪花号，同属「工人扫标签」链路）。</p>
     */
    private static final List<String> ID_LIKE_SCAN_SCOPE = List.of(
            "backend/admin-api/src/main/java/com/migao/admin/dto/WorkerInboundSkuMatch.java",
            "backend/admin-api/src/main/java/com/migao/admin/dto/WorkerInboundDraftView.java",
            "backend/admin-api/src/main/java/com/migao/admin/dto/InboundOrderResponse.java",
            "backend/admin-api/src/main/java/com/migao/admin/dto/InboundBatchView.java",
            "backend/admin-api/src/main/java/com/migao/admin/dto/OpeningImportReport.java",
            "backend/admin-api/src/main/java/com/migao/admin/dto/InboundLabelView.java");

    /**
     * 豁免台账（**只许缩短**）：射程内被判定为「可以按 JSON number 出参」的 id 形态 Long 字段。
     *
     * <p>目前**空** —— 即「一处都不许」。写入一条 = 明确声明「这个雪花 id 允许丢精度」，
     * 必须同时写清理由并接受评审（<b>空 = 最强状态，不要为了消红而加行</b>）。</p>
     */
    private static final List<String> REGISTERED_EXCEPTIONS = List.of();

    /** id 形态的字段名：{@code id} / {@code *Id} / {@code *ID}（{@code valid} 这种不算） */
    private static final Pattern ID_LIKE_FIELD = Pattern.compile("^(id|.*(Id|ID))$");

    /** 源码面「{@code private Long <name>…;}」一行（带泛型 / 初始化也命中；取最后一段做字段名） */
    private static final Pattern LONG_FIELD_LINE =
            Pattern.compile("^\\s*private\\s+(Long|long)\\s+(.+?);\\s*$");

    /** 注解形态（与 {@link ProductSkuResponse} 的既有写法同款） */
    private static final Pattern TO_STRING_SERIALIZER = Pattern.compile(
            "@JsonSerialize\\s*\\(\\s*using\\s*=\\s*ToStringSerializer\\.class\\s*\\)");

    private static Path repoRoot() {
        return Paths.get("..", "..").toAbsolutePath().normalize();
    }

    // ─────────────────────────────────────────────────────────────────────
    // ① 实例层：本族 DTO 逐个跑真序列化
    // ─────────────────────────────────────────────────────────────────────

    static Stream<Arguments> idLikeInstances() {
        WorkerInboundSkuMatch match = new WorkerInboundSkuMatch();
        match.setSkuId(REAL_WORKER_SKU_ID);
        match.setProductName("探针布");
        match.setStock(new BigDecimal("58.5"));

        WorkerInboundDraftView.Line line = new WorkerInboundDraftView.Line();
        line.setSkuId(REAL_WORKER_SKU_ID);
        line.setQuantity(new BigDecimal("60.5"));

        InboundOrderResponse.Item item = new InboundOrderResponse.Item();
        item.setId(REAL_ITEM_ID);
        item.setSkuId(REAL_WORKER_SKU_ID);
        item.setQuantity(new BigDecimal("60.5"));

        InboundBatchView batch = new InboundBatchView();
        batch.setId(REAL_ITEM_ID);
        batch.setSkuId(REAL_WORKER_SKU_ID);
        batch.setQuantity(new BigDecimal("60.5"));

        OpeningImportReport.Row row = new OpeningImportReport.Row();
        row.setSkuId(REAL_WORKER_SKU_ID);
        row.setQuantity(new BigDecimal("60.5"));

        InboundLabelView label = new InboundLabelView();
        label.setItemId(REAL_ITEM_ID);

        return Stream.of(
                Arguments.of("WorkerInboundSkuMatch", match,
                        new String[] {"skuId"}, new long[] {REAL_WORKER_SKU_ID}),
                Arguments.of("WorkerInboundDraftView.Line", line,
                        new String[] {"skuId"}, new long[] {REAL_WORKER_SKU_ID}),
                Arguments.of("InboundOrderResponse.Item", item,
                        new String[] {"id", "skuId"}, new long[] {REAL_ITEM_ID, REAL_WORKER_SKU_ID}),
                Arguments.of("InboundBatchView", batch,
                        new String[] {"id", "skuId"}, new long[] {REAL_ITEM_ID, REAL_WORKER_SKU_ID}),
                Arguments.of("OpeningImportReport.Row", row,
                        new String[] {"skuId"}, new long[] {REAL_WORKER_SKU_ID}),
                Arguments.of("InboundLabelView", label,
                        new String[] {"itemId"}, new long[] {REAL_ITEM_ID}));
    }

    @ParameterizedTest(name = "{0} 的雪花 id 字段应以字符串序列化")
    @MethodSource("idLikeInstances")
    @DisplayName("本族 DTO：id 形态字段超过 2^53 应以字符串序列化（issue #6340）")
    void idLikeFields_above2pow53_shouldSerializeAsString(
            String label, Object dto, String[] declaredIds, long[] expectedValues) throws Exception {
        String json = mapper.writeValueAsString(dto);
        for (int i = 0; i < declaredIds.length; i++) {
            String field = declaredIds[i];
            long value = expectedValues[i];
            assertTrue(json.contains("\"" + field + "\":\"" + value + "\""),
                    label + "." + field + " 是雪花号（" + value + " > 2^53）⇒ 必须以字符串序列化，实际: " + json);
            // 反向：不得同时以 bare number 形态出现
            assertTrue(!json.contains("\"" + field + "\":" + value),
                    label + "." + field + " 仍以 JSON number 出参 ⇒ JS 精度丢失，实际: " + json);
        }
    }

    @Test
    @DisplayName("业务数值（库存）保持 number：不得被 id 保护牵连成字符串")
    void stock_shouldStayNumber() throws Exception {
        WorkerInboundSkuMatch match = new WorkerInboundSkuMatch();
        match.setSkuId(REAL_WORKER_SKU_ID);
        match.setStock(new BigDecimal("100"));

        String json = mapper.writeValueAsString(match);
        assertTrue(json.contains("\"stock\":100"), "库存应保持 number: " + json);
        assertTrue(json.contains("\"skuId\":\"" + REAL_WORKER_SKU_ID + "\""),
                "skuId 应为字符串: " + json);
    }

    @Test
    @DisplayName("ProductSkuResponse.id/colorId 超过 2^53 应以字符串序列化")
    void productSkuId_above2pow53_shouldSerializeAsString() throws Exception {
        ProductSkuResponse sku = new ProductSkuResponse();
        sku.setId(2093675370043592706L);
        sku.setProductId("p-001");
        sku.setColorId(REAL_PRODUCT_COLOR_ID);
        sku.setDoorWidth("2.8米");
        sku.setPrice(new BigDecimal("88.00"));
        sku.setStock(BigDecimal.valueOf(100));

        String json = mapper.writeValueAsString(sku);
        // id 必须原样可读回（字符串形式），否则 JS 端精度丢失
        assertTrue(json.contains("\"id\":\"2093675370043592706\""),
            "Long id 超过 2^53 应以字符串序列化，实际: " + json);
        assertTrue(json.contains("\"colorId\":\"" + REAL_PRODUCT_COLOR_ID + "\""),
            "colorId 超过 2^53 应以字符串序列化，实际: " + json);
        // 普通数字字段（库存/价格）保持数值类型，不受影响
        assertTrue(json.contains("\"stock\":100"), "库存应保持 number: " + json);
    }

    @Test
    @DisplayName("ProductColorResponse.id 超过 2^53 应以字符串序列化")
    void productColorId_above2pow53_shouldSerializeAsString() throws Exception {
        ProductColorResponse color = new ProductColorResponse();
        color.setId(REAL_PRODUCT_COLOR_ID);
        color.setProductId("p-001");
        color.setColorName("验收米白");

        String json = mapper.writeValueAsString(color);
        assertTrue(json.contains("\"id\":\"" + REAL_PRODUCT_COLOR_ID + "\""),
            "ProductColor.id 超过 2^53 应以字符串序列化，实际: " + json);
    }

    // ─────────────────────────────────────────────────────────────────────
    // ② 类级层：射程内「id 形态的 Long 字段」缺注解即红（新漏标进不来）
    // ─────────────────────────────────────────────────────────────────────

    /** 源码面一处「id 形态 Long 字段缺 @JsonSerialize」的命中 */
    private record UnannotatedField(String file, int line, String fieldName) {
    }

    /** 现取射程内所有「id 形态 Long 字段缺注解」的位置（源码面 —— 能具名到 文件:行） */
    private static List<UnannotatedField> unannotatedIdLikeLongFields() throws IOException {
        List<UnannotatedField> hits = new ArrayList<>();
        Path root = repoRoot();
        for (String rel : ID_LIKE_SCAN_SCOPE) {
            Path file = root.resolve(rel);
            assertTrue(Files.isRegularFile(file),
                    "射程文件不存在（路径漂移 ⇒ 这不是「通过」）：" + rel + "（" + file + "）");
            List<String> lines = Files.readAllLines(file, StandardCharsets.UTF_8);
            for (int i = 0; i < lines.size(); i++) {
                Matcher m = LONG_FIELD_LINE.matcher(lines.get(i));
                if (!m.find()) continue;
                String name = m.group(2).trim().split("[\\s=]")[0];
                if (!ID_LIKE_FIELD.matcher(name).matches()) continue;
                if (hasToStringSerializerAbove(lines, i)) continue;
                hits.add(new UnannotatedField(rel, i + 1, name));
            }
        }
        return hits;
    }

    /** 字段声明**紧上方**（跳过空行）是否有 ToStringSerializer 注解 */
    private static boolean hasToStringSerializerAbove(List<String> lines, int fieldLineIdx) {
        for (int i = fieldLineIdx - 1; i >= 0; i--) {
            String line = lines.get(i).trim();
            if (line.isEmpty()) continue;
            if (TO_STRING_SERIALIZER.matcher(line).find()) return true;
            // 块注释 / 单行注释 / 别的注解 / 上一句代码 ⇒ 都不是本字段的序列化注解
            return false;
        }
        return false;
    }

    @Test
    @DisplayName("类级：射程内每一个 id 形态的 Long 字段都必须有 ToStringSerializer（未登记即红）")
    void everyIdLikeLongFieldInScopeMustBeAnnotated() throws IOException {
        List<String> unregistered = unannotatedIdLikeLongFields().stream()
                .filter(h -> !REGISTERED_EXCEPTIONS.contains(h.file() + "::" + h.fieldName()))
                .map(h -> h.file() + ":" + h.line() + " → " + h.fieldName())
                .toList();
        assertTrue(unregistered.isEmpty(),
                "射程内这些雪花 id 字段没有 @JsonSerialize(using = ToStringSerializer.class) ⇒ "
                        + "JSON number 出参会丢精度（issue #6340 / #5904）。要么补注解，要么登记进 "
                        + "LongIdSerializationTest.REGISTERED_EXCEPTIONS（并写理由）：\n"
                        + String.join("\n", unregistered));
    }

    @Test
    @DisplayName("类级元判据：豁免台账不许空转（登记了却已带注解 ⇒ 红，台账只许缩短）")
    void registeredExceptionsMustStillBeReal() throws IOException {
        List<UnannotatedField> hits = unannotatedIdLikeLongFields();
        List<String> stale = REGISTERED_EXCEPTIONS.stream()
                .filter(entry -> hits.stream().noneMatch(h -> (h.file() + "::" + h.fieldName()).equals(entry)))
                .toList();
        assertTrue(stale.isEmpty(),
                "豁免台账里这些条目已无对应的「缺注解命中」—— 台账只许缩短，陈旧条目会让守卫悄悄放宽：\n"
                        + String.join("\n", stale));
    }

    @Test
    @DisplayName("类级反空跑：射程必须非空、文件必须真读到、注解必须真在读面上")
    void scopeMustBeNonEmptyAndAnnotationReallyDetected() throws IOException {
        assertTrue(ID_LIKE_SCAN_SCOPE.size() >= 6, "射程被清空 ⇒ 反空跑判红");
        // 反空跑：射程内至少有 8 个「已带注解的 id 形态字段」被真读到
        // （少一个都说明抽取口径漂了 —— 那时「未登记即红」会退化成假绿）
        int annotated = 0;
        Path root = repoRoot();
        for (String rel : ID_LIKE_SCAN_SCOPE) {
            List<String> lines = Files.readAllLines(root.resolve(rel), StandardCharsets.UTF_8);
            for (int i = 0; i < lines.size(); i++) {
                Matcher m = LONG_FIELD_LINE.matcher(lines.get(i));
                if (!m.find()) continue;
                String name = m.group(2).trim().split("[\\s=]")[0];
                if (ID_LIKE_FIELD.matcher(name).matches() && hasToStringSerializerAbove(lines, i)) annotated++;
            }
        }
        assertTrue(annotated >= 8,
                "射程内只抽到 " + annotated + " 个带注解的 id 形态字段（预期 ≥ 8）⇒ 抽取口径已漂移");
    }

    @Test
    @DisplayName("判别力自证：注解被摘掉 / 注解错位 / 非 id 形态 —— 抽取器必须各自给出正确判定")
    void extractorDetectsBothBadShapes() {
        // ① 缺注解 ⇒ 命中
        List<String> missing = List.of("    private Long skuId;");
        assertTrue(!hasToStringSerializerAbove(missing, 0) && ID_LIKE_FIELD.matcher("skuId").matches(),
                "抽取器认不出「缺注解的 id 形态 Long」⇒ 它是个空断言");

        // ② 带注解 ⇒ 不命中
        List<String> annotated = List.of(
                "    @JsonSerialize(using = ToStringSerializer.class)",
                "    private Long skuId;");
        assertTrue(hasToStringSerializerAbove(annotated, 1),
                "抽取器认不出「已带注解」⇒ 会把合规代码判红（假红）");

        // ③ 注解在**别的字段**上 ⇒ 不命中（不许把上一行的注解算给下一行）
        List<String> wrongNeighbour = List.of(
                "    @JsonSerialize(using = ToStringSerializer.class)",
                "    private Long id;",
                "    private Long skuId;");
        assertTrue(!hasToStringSerializerAbove(wrongNeighbour, 2),
                "抽取器把相邻字段的注解算给了下一个字段 ⇒ 漏判（假绿）");

        // ④ 非 id 形态 ⇒ 不构成命中（负控）
        assertTrue(!ID_LIKE_FIELD.matcher("quantity").matches()
                        && !ID_LIKE_FIELD.matcher("valid").matches(),
                "负控：quantity / valid 不是 id 形态");
    }
}
