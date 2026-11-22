// case_ids: PR-017
package com.migao.admin.service;

import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductUpdateRequest;
import com.migao.admin.entity.Product;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 商品入参 DTO「**收了却不落库**」的类级元守卫（issue #9005，铁律 8）。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 本单的实例缺陷是「{@code ProductCreateRequest.doorWidths} 收下了，但 {@code products} 表没有对应列
 * ⇒ 无声丢弃，且 {@code GET /{id}} 也读不回」（2026-11-22 生产冒烟实测）。但**同一形态对
 * 两个商品入参 DTO 的每一个字段都成立**：只要有人给 DTO 加一个字段、忘了落库映射，
 * 就会**再一次**「200 创建成功、数据消失」，而没有任何东西会红 ——
 * 本仓上一轮同族缺陷是 {@code ProductCreateRequest.stock}（#7597 静默忽略），
 * 这一轮是 {@code doorWidths}（#9005）。两次都靠人肉发现，说明缺的是**类级对账**。
 *
 * <h2>判据（三方对账 ⇒ 未登记即红）</h2>
 * 对 {@link ProductCreateRequest} / {@link ProductUpdateRequest} 的**每一个实例字段**，必须命中三者之一：
 * <ol>
 *   <li><b>{@link Product} 实体同名列</b> ⇒ 由 {@code BeanUtils.copyProperties} 落 {@code products} 列
 *       （本判据同时反向核对：登记的字段**真的在实体上**，防止台账空转）；</li>
 *   <li><b>子表落点</b>（{@code colors} / {@code skus} → {@code product_colors} / {@code product_skus}；
 *       {@code brand} / {@code specifications} → {@code product_attributes}）；</li>
 *   <li><b>显式拒绝清单</b>（{@code REJECTED}）—— 收下但**有意不落库**的字段必须写明「不落库 + 怎么不静默」，
 *       且被判据 3 要求源码里真有那条收口。</li>
 * </ol>
 * 三者都不命中的字段 ⇒ 判红并**具名**（这就是 #9005 改前的形态）。
 *
 * <h2>红证（判别力自证）</h2>
 * 判据 4 往分类器里注入一个不存在的字段名（{@code ghostField}）⇒ 必须判红并点名；
 * 不注入 ⇒ 不报（反向对照）。判据 5 注入「登记了但实体上没有」的条目 ⇒ 同样判红（台账空转）。
 *
 * <h2>边界（如实登记）</h2>
 * <ul>
 *   <li>射程 = 两个**表单**入参 DTO。{@code dto/agent/AgentProductCreateRequest} 不在此列：
 *       它先被 {@code createProductForAgent} 翻译成 {@link ProductCreateRequest}，最终仍过本判据的对象；</li>
 *   <li>本判据证「**有落点**」，不证「落点写得对」—— 后者由行为面判据承担
 *       （{@code ProductDoorWidthsRoundTripRealDbTest} 真库往返 / {@code ProductCreateStockIgnoredTest} 拒绝语义）；</li>
 *   <li>{@code REJECTED} 的「源码里真有收口」是**文本扫描**（与 {@code ProductTextColumnAdmissionMetaGuardTest}
 *       同款取舍）：把收口换成常量 / 挪进别的方法名 ⇒ 扫不到会判红，这是**有意**的（判据必须可复算）。</li>
 * </ul>
 */
@DisplayName("商品入参 DTO 字段落库对账 · 类级元守卫（issue #9005）")
class ProductCreateRequestFieldPersistenceMetaGuardTest {

    private static final String PRODUCT_SERVICE_SOURCE =
            "backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java";

    /** 落**子表**的字段 → 落点（不是 products 列）。 */
    private static final Map<String, String> CHILD_TABLE = Map.of(
            "colors", "product_colors（ProductService.saveColorsAndSkus）",
            "skus", "product_skus（ProductService.saveColorsAndSkus）",
            "brand", "product_attributes（ProductService.saveProductAttributes）",
            "specifications", "product_attributes（ProductService.saveProductAttributes）");

    /**
     * 收下但**有意不落库**的字段 → 「怎么不静默」（必须给出机制，不许写「忽略」）。
     * 条目只许在「该字段确实被显式收口」时新增；当前仅一条。
     */
    private static final Map<String, String> REJECTED = Map.of(
            "stock", "建品不建立库存（issue #7597 / 用户裁定 2026-10-24：库存只由真实单据产生）；"
                    + "非 0 ⇒ 422 显式拒绝（issue #9006，收口 = ProductService.requireNoInitialStockOnCreate）");

    /** 判据 3 的扫描锚：{@code REJECTED} 字段的收口必须在 ProductService 源码里真的存在。 */
    private static final Map<String, String> REJECTION_ANCHORS = Map.of(
            "stock", "requireNoInitialStockOnCreate");

    // ══════════════════════════════════ 判据 1：字段全覆盖

    @Test
    @DisplayName("判据1：两个商品入参 DTO 的每个字段都有落点或已登记拒绝 —— 未登记即红并具名")
    void everyFieldHasAPersistenceHome() {
        assertFieldsRegistered(fieldNames(ProductCreateRequest.class), "ProductCreateRequest");
        assertFieldsRegistered(fieldNames(ProductUpdateRequest.class), "ProductUpdateRequest");
    }

    // ══════════════════════════════════ 判据 2：台账不空转

    @Test
    @DisplayName("判据2：实体映射面登记的字段**真的在 Product 上**（字段被改名/删除 ⇒ 判红，不许静默失效）")
    void entityMappedFieldsReallyExistOnEntity() {
        Set<String> entityFields = fieldNames(Product.class);
        List<String> missing = new ArrayList<>();
        for (String field : fieldNames(ProductCreateRequest.class)) {
            if (!CHILD_TABLE.containsKey(field) && !REJECTED.containsKey(field) && !entityFields.contains(field)) {
                missing.add(field);
            }
        }
        assertThat(missing)
                .as("这些 DTO 字段既不在 Product 实体、也不在子表落点、也没登记为显式拒绝 ⇒ 会被无声丢弃：%s", missing)
                .isEmpty();

        // 反向：子表落点 / 拒绝清单里的键必须是 DTO 真有的字段（防台账越长越像垃圾场）
        List<String> stale = new ArrayList<>();
        for (String key : CHILD_TABLE.keySet()) {
            if (!fieldNames(ProductCreateRequest.class).contains(key)) {
                stale.add("CHILD_TABLE/" + key);
            }
        }
        for (String key : REJECTED.keySet()) {
            if (!fieldNames(ProductCreateRequest.class).contains(key)) {
                stale.add("REJECTED/" + key);
            }
        }
        assertThat(stale)
                .as("登记表里有 DTO 上已不存在的字段（台账空转）⇒ 请删掉这些条目：%s", stale)
                .isEmpty();
    }

    // ══════════════════════════════════ 判据 3：拒绝面必须真的收口（不静默）

    @Test
    @DisplayName("判据3：登记为「显式拒绝」的字段，源码里必须有对应收口（否则就是又一个静默忽略）")
    void rejectedFieldsHaveRealChokepoints() throws IOException {
        String source = Files.readString(repoRoot().resolve(PRODUCT_SERVICE_SOURCE), StandardCharsets.UTF_8);
        for (Map.Entry<String, String> entry : REJECTED.entrySet()) {
            String field = entry.getKey();
            String anchor = REJECTION_ANCHORS.get(field);
            assertThat(anchor)
                    .as("REJECTED.%s 必须登记收口锚（REJECTION_ANCHORS），否则判据扫不到任何东西", field)
                    .isNotNull();
            assertThat(source)
                    .as("登记为「显式拒绝」的 %s 在 ProductService 里找不到收口 `%s` —— "
                            + "那它实际仍是**静默忽略**（issue #9006 的病灶形态）", field, anchor)
                    .contains(anchor);
            assertThat(source)
                    .as("收口必须在建品执行体里真的被调用（只声明不调用 = 空转）")
                    .contains(anchor + "(request.getStock())");
        }
    }

    // ══════════════════════════════════ 判据 4/5：判别力自证（注入即红）

    @Test
    @DisplayName("判据4（判别力自证）：注入一个没有落点的字段 ⇒ 必须判红并点名（否则判据 1 是空跑）")
    void classifierHasTeeth() {
        Set<String> injected = new LinkedHashSet<>(fieldNames(ProductCreateRequest.class));
        injected.add("ghostField");

        assertThatThrownBy(() -> assertFieldsRegistered(injected, "ProductCreateRequest"))
                .as("未登记的字段必须判红（#9005 改前的 doorWidths 就是这种形态）")
                .isInstanceOf(AssertionError.class)
                .hasMessageContaining("ghostField");
    }

    @Test
    @DisplayName("判据5（判别力自证）：实体映射面登记了、实体上却没有的字段 ⇒ 同样判红（台账空转也有牙）")
    void staleEntityMappingIsRed() {
        Map<String, String> ledger = new LinkedHashMap<>();
        ledger.put("ghostField", "Product 实体同名列");
        assertThatThrownBy(() -> assertLedgerEntriesExist(ledger, fieldNames(Product.class)))
                .as("台账条目指向实体上不存在的字段 ⇒ 判红（防「登记即通过」）")
                .isInstanceOf(AssertionError.class)
                .hasMessageContaining("ghostField");
    }

    // ══════════════════════════════════ 分类器（判据本体，可被注入测试）

    /** 每个字段必须命中：实体同名列 / 子表落点 / 显式拒绝清单；否则**具名判红**。 */
    private static void assertFieldsRegistered(Set<String> dtoFields, String dtoSimpleName) {
        Set<String> entityFields = fieldNames(Product.class);
        List<String> unexplained = new ArrayList<>();
        for (String field : dtoFields) {
            boolean mappedToEntity = entityFields.contains(field);
            boolean mappedToChild = CHILD_TABLE.containsKey(field);
            boolean explicitlyRejected = REJECTED.containsKey(field);
            if (!mappedToEntity && !mappedToChild && !explicitlyRejected) {
                unexplained.add(field);
            }
        }
        assertThat(unexplained)
                .as("%s 的这些字段**没有任何落点**：既不在 Product 实体、也不在子表落点、也没登记为显式拒绝 "
                        + "⇒ 会被 API 收下后无声丢弃（issue #9005 的病灶形态）。出口二选一："
                        + "① 加列 + 实体/DTO/响应映射（迁移 + 回读判据）；"
                        + "② 在 ProductService 入口显式拒绝（422）并登记到本文件 REJECTED/REJECTION_ANCHORS", unexplained)
                .isEmpty();
    }

    private static void assertLedgerEntriesExist(Map<String, String> ledger, Set<String> entityFields) {
        List<String> stale = new ArrayList<>();
        for (String key : ledger.keySet()) {
            if (!entityFields.contains(key)) {
                stale.add(key);
            }
        }
        assertThat(stale)
                .as("这些登记条目在实体上不存在（tautology 台账 / 字段被改名）⇒ 判红：%s", stale)
                .isEmpty();
    }

    private static Set<String> fieldNames(Class<?> type) {
        Set<String> names = new TreeSet<>();
        for (Field field : type.getDeclaredFields()) {
            if (field.isSynthetic() || Modifier.isStatic(field.getModifiers())) {
                continue;
            }
            names.add(field.getName());
        }
        return names;
    }

    private static Path repoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/java/com/migao/admin"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库根目录（backend/admin-api/src/main/java/com/migao/admin 不存在）");
    }

    @SuppressWarnings("unused")
    private static List<String> describe(Set<String> fields) {
        return Arrays.asList(fields.toArray(new String[0]));
    }
}
