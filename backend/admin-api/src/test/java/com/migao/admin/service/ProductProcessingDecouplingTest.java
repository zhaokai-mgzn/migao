package com.migao.admin.service;

// case_ids: PR-005, PR-019
// 商品 ↔ 加工项彻底解耦（issue #4371，用户裁定 2026-09-19）：
// 加工项是**店铺全目录**，由用户在加工项目录里独立选择；生产路线由「安装方式 + 商品」经
// `app/production/routing.py` 的 `ROUTINGS[(部位,工艺)]` 决定 ⇒ 加工项**不应**由商品持有，
// 也不应由商品分类过滤。

import com.migao.admin.dto.ProcessingItemQueryRequest;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.dto.ProductUpdateRequest;
import com.migao.admin.dto.agent.AgentProductCreateRequest;
import com.migao.admin.entity.Product;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「商品 ↔ 加工项」解耦的**契约级回归防线**（issue #4371）。
 *
 * <p><b>这是本单的判红锚点</b>：解耦的正确性没有「跑一次就看得出来」的运行期表现
 * —— 删掉的字段如果被谁加回来，Spring/Jackson 会**静默接受**（未知字段忽略、
 * 缺字段用默认值），既有测试全部照绿。所以本文件不测行为，只测**契约形状**：
 * 用 {@link java.lang.reflect} 遍历**声明字段 + 声明方法**，任何一处复活
 * 都立刻判红。</p>
 *
 * <p><b>红证（怎么写就怎么红）</b>：</p>
 * <ol>
 *   <li>把 {@code ProductResponse.processingItems} 加回来 ⇒
 *       {@link #productResponseMustNotExposeProcessingItems()} 红；</li>
 *   <li>把 {@code Product.hasProcessing} 加回来 ⇒
 *       {@link #productEntityMustNotHaveHasProcessing()} 红
 *       （V66 已 DROP 该列，实体再持有它 = 运行时 {@code column does not exist}）；</li>
 *   <li>把 {@code ProcessingItemQueryRequest.applicableProductCategoryId} 加回来 ⇒
 *       {@link #processingItemQueryMustNotFilterByProductCategory()} 红；</li>
 *   <li>删掉 V66 里任一条 DDL ⇒ {@link #migrationV66PinsTheThreeDdlStatements()} 红
 *       （迁移是交付物本身，不是「顺便改的 SQL」）。</li>
 * </ol>
 *
 * <p>断言同时覆盖字段与访问器（Lombok {@code @Data} 生成 {@code getXxx/setXxx}）：
 * 只查字段会漏掉「字段删了但手写 getter 还在」的形态；只查方法会漏掉
 * 「私有字段 + 反射赋值」的形态。两者都要。</p>
 */
@DisplayName("商品↔加工项解耦契约（issue #4371）")
class ProductProcessingDecouplingTest {

    /** V66 迁移（迁移不可变，见 issue #4235：本文件只读它，不生成它）。 */
    private static final String V66 =
            "backend/admin-api/src/main/resources/db/migration/V66__decouple_product_processing_items.sql";

    // ── 反射工具 ──────────────────────────────────────────────────────────

    /** 声明字段名（含私有；不含继承来的，DTO 全是本类声明）。 */
    private static List<String> declaredFieldNames(Class<?> type) {
        List<String> names = new ArrayList<>();
        for (Field f : type.getDeclaredFields()) {
            names.add(f.getName());
        }
        return names;
    }

    /** 声明方法名（含私有/合成；用于抓 Lombok 生成的 getter/setter 与手写访问器）。 */
    private static List<String> declaredMethodNames(Class<?> type) {
        List<String> names = new ArrayList<>();
        for (Method m : type.getDeclaredMethods()) {
            names.add(m.getName());
        }
        return names;
    }

    /**
     * 断言「字段名 / 访问器名」两侧都不存在 {@code banned}。
     * 访问器按 JavaBean 命名判定：{@code getFoo} / {@code setFoo} / {@code isFoo}
     * （首字母大写）——不做模糊包含，避免把 {@code processingItemsTotal} 这类
     * 无关名字误判成命中。
     */
    private static void assertNoFieldOrAccessor(Class<?> type, String banned) {
        String cap = Character.toUpperCase(banned.charAt(0)) + banned.substring(1);
        List<String> accessors = List.of("get" + cap, "set" + cap, "is" + cap);

        assertThat(declaredFieldNames(type))
                .as("%s 不得再声明字段 %s（商品↔加工项解耦，issue #4371）", type.getSimpleName(), banned)
                .doesNotContain(banned);

        List<String> hits = new ArrayList<>();
        for (String name : declaredMethodNames(type)) {
            if (accessors.contains(name)) {
                hits.add(name);
            }
        }
        assertThat(hits)
                .as("%s 不得再有 %s 的访问器（字段删了但访问器复活同样算解耦回退）",
                        type.getSimpleName(), banned)
                .isEmpty();
    }

    // ── ① 请求侧：商品建/改请求不得再携带加工项 ──────────────────────────

    @Test
    @DisplayName("AgentProductCreateRequest 无 processingItemIds / processingItemConfigs")
    void agentCreateRequestMustNotCarryProcessingItems() {
        assertNoFieldOrAccessor(AgentProductCreateRequest.class, "processingItemIds");
        assertNoFieldOrAccessor(AgentProductCreateRequest.class, "processingItemConfigs");
        // 加工项配置子对象（AgentProcessingItemConfig）随字段一起退场：
        // 留着它 = 下一个人以为「还能传自定义加工价」，只是没人读
        assertThat(Arrays.stream(AgentProductCreateRequest.class.getDeclaredClasses())
                .map(Class::getSimpleName))
                .as("AgentProductCreateRequest 不得再有加工项配置内部类")
                .doesNotContain("AgentProcessingItemConfig");
    }

    @Test
    @DisplayName("ProductCreateRequest / ProductUpdateRequest 无 processingItemConfigs")
    void formRequestsMustNotCarryProcessingItemConfigs() {
        assertNoFieldOrAccessor(ProductCreateRequest.class, "processingItemConfigs");
        assertNoFieldOrAccessor(ProductUpdateRequest.class, "processingItemConfigs");
    }

    // ── ② 响应侧：商品详情/列表不得回填加工项 ────────────────────────────

    @Test
    @DisplayName("ProductResponse 无 processingItems / processingItemConfigs")
    void productResponseMustNotExposeProcessingItems() {
        assertNoFieldOrAccessor(ProductResponse.class, "processingItems");
        assertNoFieldOrAccessor(ProductResponse.class, "processingItemConfigs");
    }

    // ── ③ 实体侧：products.has_processing 列已被 V66 删除 ────────────────

    @Test
    @DisplayName("Product 实体无 hasProcessing（V66 已 DROP 该列）")
    void productEntityMustNotHaveHasProcessing() {
        assertNoFieldOrAccessor(Product.class, "hasProcessing");
    }

    // ── ④ 加工项目录侧：不再按商品分类过滤 ──────────────────────────────

    @Test
    @DisplayName("ProcessingItemQueryRequest 无 applicableProductCategoryId")
    void processingItemQueryMustNotFilterByProductCategory() {
        assertNoFieldOrAccessor(ProcessingItemQueryRequest.class, "applicableProductCategoryId");
    }

    // ── ⑤ 迁移本身是交付物：V66 的三条 DDL 必须在 ───────────────────────

    /**
     * 钉住 V66 的三条 DDL。理由：迁移是**交付物**，不是「顺便改的 SQL」——
     * 少了任一条，Java 侧删字段/删表就变成「代码说没有、库说还有」的静默漂移
     * （实体不再读写该列 ⇒ 谁也不会因此变红）。
     */
    @Test
    @DisplayName("V66 迁移包含三条解耦 DDL")
    void migrationV66PinsTheThreeDdlStatements() throws Exception {
        Path file = repoRoot().resolve(V66);
        assertThat(Files.isRegularFile(file))
                .as("V66 迁移文件必须存在：%s", V66)
                .isTrue();
        String sql = Files.readString(file, StandardCharsets.UTF_8);

        assertThat(sql).contains("DROP TABLE IF EXISTS product_processing_items");
        assertThat(sql).contains("DROP COLUMN IF EXISTS has_processing");
        assertThat(sql).contains("DROP COLUMN IF EXISTS applicable_product_categories");
    }

    /** 仓库根 = 逐级上溯到含 `backend/admin-api/.../db/migration` 的那一层（同既有迁移测试口径）。 */
    private static Path repoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库根目录");
    }
}
