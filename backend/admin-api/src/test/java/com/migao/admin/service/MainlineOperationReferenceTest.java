// case_ids: PG-018
package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「**主线引用的工序必须在工序库里存在**」—— **运行时读面**口径（issue #4707，三处口径的第三处）。
 *
 * <h3>本类回答的问题</h3>
 * 前两处口径是**静态**的（`bootstrap` = `docs/sql/schema.sql`、`迁移链终态` = 聚合全部种子迁移），
 * 见 {@code tests/unit_ci_workflows/test_v91_baseline_operations_backfill.py}。
 * 它们只能证明「库里**有**这一行」；**能不能被实例化路径取到**由本类证明 ——
 * 判据直接用生产代码 {@link ProductionOperationQueryService#variantNameOf}
 * （`ProcessingOrderService.buildRoute` 调的就是它，**不另写一份推导**）。
 *
 * <h3>为什么必须有它（真库实测，2026-09-20，PG 18.3 / 阿里云 RDS）</h3>
 * <ul>
 *   <li><b>租户 20 / 21</b>：`production_operations` **0 行**，而矩阵 84 格 + 窗帘主线 9 道
 *       ⇒ 布帘 9/9、帘头 6/6、纱帘 5/5 **逐道悬空** ⇒ 窗帘单 fail-closed 422
 *       （修法 = `V91` 补种基线工序；本类在**库行齐了之后**继续守「解析得出来」）；</li>
 *   <li><b>全部租户（含健康租户 1 号）</b>：`V88`（#4676）把布料主线改成 `["裁剪","打包"]`
 *       并种下**保命格** `裁剪 × 布料`（`applicable = TRUE`），但 `裁剪` 的变体表里
 *       **只有 布帘 / 纱帘** ⇒ {@code variantNameOf("裁剪","布料",…)} 返回 {@code null}
 *       ⇒ **纯布料单 fail-closed 422**。保命格只过了第一道闸（矩阵键存在），
 *       **第二道闸（变体解析）没人守** —— 本类就是那道闸。</li>
 * </ul>
 *
 * <h3>为什么目录取自 {@code seed.json}</h3>
 * `resources/production-templates/curtain/seed.json` 是**开租播种终态**（与 `V54 ∪ V56 ∪ V79`
 * 的迁移链终态、与 `schema.sql` 的 bootstrap 终态逐项一致，三源收敛由
 * `test_production_catalog_seed.py` 守）⇒ 在 Java 侧读它，等于用**真值源的库行集**喂运行时解析。
 *
 * <h3>⚠️ 本类的边界（如实登记）</h3>
 * 它守「**解析得出来**」（fail-closed 的第一层），**不**守「矩阵格是否 `applicable`」
 * （那是 `V88` ④ / `V89` ② 与 `ProductionSeedTemplateService.FABRIC_KEEP_APPLICABLE_LOGICAL`
 * 的范围，由 Python 侧静态判据守）。两条一起才等于「实例化真的出得来 N 道」。
 */
class MainlineOperationReferenceTest {

    /**
     * 规范窗帘主线（**10 道**）= `V88`/`V89` 之后的终态
     * （`ProductionSeedTemplateService.ROUTE_MAINLINE_STEPS` / `schema.sql` 逐字一致）。
     */
    private static final List<String> CURTAIN_MAINLINE = List.of(
            "精裁", "三边", "熨烫", "定型", "复烫", "车被",
            "外帘打卷", "打包", "外帘装袋", "外帘发货");

    /** 窗帘路线模板的适用帘种（`V71`/`V72`/`V89` 种子：三部位共用一条主线）。 */
    private static final List<String> CURTAIN_POSITIONS = List.of("布帘", "纱帘", "帘头");

    /**
     * 布料主线（**2 道**）= `V88` ③ 的终态（`裁剪` 取代退场的 `配料`）。
     *
     * <p>⚠️ 与 `ai-agent` 的 `routing.py::FABRIC_MAINLINE_STEPS`（仍是 `["配料","打包"]`）**不同源**
     * —— 这是 issue #4701（P1）已登记的跨单冲突，**本类不碰 ai-agent**，按 Java 侧终态钉住。</p>
     */
    private static final List<String> FABRIC_MAINLINE = List.of("裁剪", "打包");

    /** 第 4 个部位（布料单专用）。 */
    private static final String FABRIC_POSITION = "布料";

    /** `V88`（#4676）退场的逻辑工序 —— **不得**出现在任何主线里。 */
    private static final List<String> RETIRED_LOGICAL_NAMES = List.of("配料");

    /** 运行时解析入口（`variantNameOf` 只读静态逆索引 + 传入目录 ⇒ 其余依赖可为 null）。 */
    private static ProductionOperationQueryService service() {
        return new ProductionOperationQueryService(null, null, null, null, null, null);
    }

    /**
     * 开租播种终态目录（`seed.json` 的 37 行，**去掉** `V88` 已退场的 `配料` ⇒ 36 行）
     * 按名索引 —— 形态与 {@code ProductionOperationQueryService.operationsByName} 的返回一致。
     */
    private static Map<String, Map<String, Object>> catalog() {
        Map<String, Map<String, Object>> views = new LinkedHashMap<>();
        for (JsonNode node : seedOperations()) {
            String name = node.path("name").asText();
            if (RETIRED_LOGICAL_NAMES.contains(name)) {
                continue;   // V88 已退场 ⇒ 运行时目录里没有它
            }
            Map<String, Object> meta = new LinkedHashMap<>();
            meta.put("group", node.path("group").asText("其他"));
            meta.put("unit", node.path("unit").asText("米"));
            meta.put("unit_price", new java.math.BigDecimal(node.path("unit_price").asText("0")));
            meta.put("is_must_finish", node.path("is_must_finish").asBoolean(false));
            meta.put("is_start_marker", node.path("is_start_marker").asBoolean(false));
            meta.put("scope", node.path("scope").asText("position"));
            views.put(name, meta);
        }
        return views;
    }

    private static List<JsonNode> seedOperations() {
        try (InputStream in = new ClassPathResource(
                "production-templates/curtain/seed.json").getInputStream()) {
            JsonNode root = new ObjectMapper().readTree(in);
            List<JsonNode> rows = new ArrayList<>();
            root.path("operations").forEach(rows::add);
            assertThat(rows).as("seed.json 的 operations 段为空 ⇒ 判据会空跑").isNotEmpty();
            return rows;
        } catch (Exception e) {
            throw new IllegalStateException("读不到 production-templates/curtain/seed.json", e);
        }
    }

    // ══════════════════════════ ① 窗帘主线（10 道 × 3 部位）══════════════════════════

    @Test
    @DisplayName("PG-018 窗帘主线 10 道：每道至少在一个适用部位上可解析（空工序库 ⇒ 全红）")
    void everyCurtainMainlineStepResolvesForAtLeastOneTemplatePosition() {
        Map<String, Map<String, Object>> catalog = catalog();
        List<String> dangling = new ArrayList<>();
        for (String step : CURTAIN_MAINLINE) {
            boolean resolved = false;
            for (String position : CURTAIN_POSITIONS) {
                if (service().variantNameOf(step, position, catalog) != null) {
                    resolved = true;
                    break;
                }
            }
            if (!resolved) {
                dangling.add(step);
            }
        }
        assertThat(dangling)
                .as("主线引用的工序必须能在该租户工序库里解析到（悬空 ⇒ buildRoute 进 missing_operations ⇒ 422）")
                .isEmpty();
    }

    /**
     * ⚠️ **为什么这里按「至少一个适用部位」而不是「逐部位」判**（口径边界，照实登记）：
     * 运行时 `buildRoute` 的 `missing_operations` **只对矩阵格 `applicable = TRUE` 的 (逻辑名, 部位)
     * 生效** —— 矩阵格 `applicable = FALSE`（「该部位明确不做」）会在**取变体之前**被静默滤掉。
     * 例：`纱帘 × 熨烫/定型/复烫/车被` 在规范矩阵里是 `FALSE` ⇒ 纱帘单里本来就没有这四道，
     * 它们解析不出来**不是缺陷**（逐部位判会**假红**）。
     * ⇒ 逐格口径由**静态面**守（`tests/unit_ci_workflows/test_v91_baseline_operations_backfill.py`
     * 的 `test_canonical_matrix_applicable_cells_all_resolve_at_runtime`：解析本类的
     * `variantNames()` 与 `ProductionSeedTemplateService.CANONICAL_POSITION_PRICES` 逐格比对），
     * 本类守「**解析路径本身通**」。
     */
    @Test
    @DisplayName("PG-018 口径边界自证：`纱帘 × 熨烫` 解析不出但**不是**缺陷（矩阵格 FALSE ⇒ 静默滤掉）")
    void nonApplicablePositionStepsAreNotDangling() {
        Map<String, Map<String, Object>> catalog = catalog();
        assertThat(service().variantNameOf("熨烫", "纱帘", catalog))
                .as("库中只有 `熨烫-布`（布帘变体）⇒ 纱帘部位解析不出 —— 这是矩阵格 FALSE 的预期结果")
                .isNull();
        assertThat(service().variantNameOf("熨烫", "布帘", catalog)).isEqualTo("熨烫-布");
    }

    // ══════════════════════════ ② 布料主线（2 道 × 布料）═════════════════════════════

    @Test
    @DisplayName("PG-018 布料主线 2 道（裁剪/打包）× 布料逐道可解析（V88 保命格的第二道闸）")
    void fabricMainlineResolvesForFabricPosition() {
        Map<String, Map<String, Object>> catalog = catalog();
        List<String> dangling = new ArrayList<>();
        for (String step : FABRIC_MAINLINE) {
            if (service().variantNameOf(step, FABRIC_POSITION, catalog) == null) {
                dangling.add(step);
            }
        }
        assertThat(dangling)
                .as("布料主线 `裁剪` 只过了矩阵格那道闸（V88 ④ 保命格），"
                        + "变体解析这道闸必须也过 —— 否则**健康租户的纯布料单也 422**")
                .isEmpty();
    }

    @Test
    @DisplayName("PG-018 布料两道解析到承载元数据的库行：裁剪 → 裁剪-布 / 打包 → 裸名 打包")
    void fabricStepsResolveToTheExpectedLibraryRows() {
        Map<String, Map<String, Object>> catalog = catalog();
        assertThat(service().variantNameOf("裁剪", FABRIC_POSITION, catalog))
                .as("`裁剪` 的库行只有 裁剪-布 / 裁剪-纱 ⇒ 布料部位必须显式回落到 裁剪-布")
                .isEqualTo("裁剪-布");
        assertThat(service().variantNameOf("打包", FABRIC_POSITION, catalog))
                .as("`打包` 是**部位无关**的裸名工序（套级），四部位共用同一行")
                .isEqualTo("打包");
    }

    // ══════════════════════════ ③ 退场口径 ══════════════════════════

    @Test
    @DisplayName("PG-018 V88 退场的 `配料` 不在任何主线里（种回来 = 停止条件 S6）")
    void retiredLogicalNameIsInNoMainline() {
        for (String retired : RETIRED_LOGICAL_NAMES) {
            assertThat(CURTAIN_MAINLINE).doesNotContain(retired);
            assertThat(FABRIC_MAINLINE).doesNotContain(retired);
        }
    }

    // ══════════════════════════ ④ 注入式红证：判据是**承重**的 ══════════════════════════

    @Test
    @DisplayName("PG-018 红证：把 `裁剪` 的库行摘掉 ⇒ 判据必红（证明上一组断言不是空断言）")
    void droppingTheCuttingOperationMakesTheGuardRed() {
        Map<String, Map<String, Object>> broken = new LinkedHashMap<>(catalog());
        broken.keySet().removeIf(name -> name.startsWith("裁剪-"));
        assertThat(service().variantNameOf("裁剪", FABRIC_POSITION, broken))
                .as("库里没有 `裁剪` 的任何库行 ⇒ 必须返回 null（不猜）")
                .isNull();
        assertThat(service().variantNameOf("裁剪", "布帘", broken)).isNull();
        // 反证：其余主线工序不受影响 ⇒ 红是**定位到 `裁剪` 这一道**的，不是整体崩
        assertThat(service().variantNameOf("打包", FABRIC_POSITION, broken)).isEqualTo("打包");
    }

    @Test
    @DisplayName("PG-018 红证：把 `外帘装袋` 的库行摘掉 ⇒ 窗帘主线必红（注入一条悬空引用）")
    void droppingPackingIntoBagOperationMakesTheCurtainMainlineRed() {
        Map<String, Map<String, Object>> broken = new LinkedHashMap<>(catalog());
        broken.remove("外帘装袋");
        List<String> dangling = new ArrayList<>();
        for (String step : CURTAIN_MAINLINE) {
            boolean resolved = false;
            for (String position : CURTAIN_POSITIONS) {
                if (service().variantNameOf(step, position, broken) != null) {
                    resolved = true;
                    break;
                }
            }
            if (!resolved) {
                dangling.add(step);
            }
        }
        assertThat(dangling)
                .as("注入一条悬空引用后，判据必须能指名报出它（且只报它）")
                .containsExactly("外帘装袋");
    }

    @Test
    @DisplayName("PG-018 红证：工序库为空（租户 20/21 的真库形态）⇒ 窗帘主线 10 道全红")
    void emptyCatalogMakesTheWholeCurtainMainlineRed() {
        List<String> dangling = new ArrayList<>();
        for (String step : CURTAIN_MAINLINE) {
            boolean resolved = false;
            for (String position : CURTAIN_POSITIONS) {
                if (service().variantNameOf(step, position, new LinkedHashMap<>()) != null) {
                    resolved = true;
                    break;
                }
            }
            if (!resolved) {
                dangling.add(step);
            }
        }
        assertThat(dangling)
                .as("空工序库 = 真库实测的租户 20/21 形态 ⇒ 每一道都解析不出来（这才是 422 的成因）")
                .containsExactlyElementsOf(CURTAIN_MAINLINE);
    }
}
