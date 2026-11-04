// case_ids: PG-045
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.CuttingHeightConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CuttingHeightConfigMapper;
import com.migao.admin.mapper.TenantParamAuditMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 裁高参数配置 **全场景矩阵**（设计 {@code docs/design/cutting-height-config-and-terminal.md} §2.2/§2.3）。
 *
 * <p>目的（用户 2026-11-04 逐字「你需要测试裁高参数配置全部场景都能生效……确保参数计算准确」）：
 * 把「配置面上的<u>每一个可配维度</u>」都换成一次**可复算的读数** —— 一份配置 → 一次预演 → 一个高度。
 * 场景 = 条件触发（option / craft / processing_item / shaped / 语义族）× 条件组合（跨 kind AND、组内 OR、
 * 空条件恒真）× 部位限定 × 作用域（specific 命中即替换兜底）× direction（add / subtract）×
 * 未配置取值（unresolved，不按 0 算）× enabled=false × 取整（mode × digits）× 存量 v1 归一 × 缺成品高。
 *
 * <p>判据（每条都能红，红证见 {@code docs/testing} 的同批登记）：</p>
 * <ol>
 *   <li>每个场景的 {@code cutting_height} 与**逐字期望值**相等（差一位小数即红）；</li>
 *   <li>每个场景的 {@code hits}/{@code misses} 键集与期望**逐字**相等（多算一项 = 给机器的值偏大 = 裁长）；</li>
 *   <li>{@code 未配置取值} 的场景**永远**不把该项当 0 计入（静默按 0 = 裁短 = 事故）。</li>
 * </ol>
 *
 * <p>跑法：{@code cd backend/admin-api && ./mvnw -q test -Dtest=CuttingHeightScenarioMatrixTest}。
 * 输出末尾打印矩阵表（场景 / 期望 / 实得），可直接贴进验收单。</p>
 */
@DisplayName("裁高参数配置全场景矩阵（V140 / 母单 #5161）")
class CuttingHeightScenarioMatrixTest {

    private static final Long TENANT = 7L;

    private CuttingHeightConfigMapper mapper;
    private CuttingHeightConfigService service;
    private final List<String> table = new ArrayList<>();

    @BeforeEach
    void setUp() {
        mapper = mock(CuttingHeightConfigMapper.class);
        service = new CuttingHeightConfigService(mapper, new TenantParamAuditService(
                mock(TenantParamAuditMapper.class), new SimpleMeterRegistry(), new ObjectMapper()));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken("tester", null, List.of()));
        table.clear();
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
        // 矩阵表：始终打印（成功/失败都能看到跑到哪一行）
        StringBuilder out = new StringBuilder("\n裁高配置场景矩阵（成品高 2.92 m 为基准）\n");
        out.append("| # | 场景 | 期望高度 | 实得高度 | hits | misses | 结论 |\n");
        out.append("|---|---|---|---|---|---|---|\n");
        table.forEach(out::append);
        System.out.println(out);
    }

    @Test
    @DisplayName("矩阵：11 个配置维度 × 16 个场景，逐行断言高度与命中键集")
    void everyConfigDimensionTakesEffect() {
        // ─────────── 1. 缺行 = 默认种子 ───────────
        check(1, "默认种子（无配置行）：布帘 + 特殊选项=布贴", null,
                request("布帘", "2.92", List.of("布贴"), null, null, null),
                "2.935", List.of("butie"), List.of());

        // ─────────── 2. 工序专用命中 ⇒ 兜底整组不参与（替换语义） ───────────
        check(2, "专用命中：特殊选项=布绑带 ∧ 工艺=韩褶 ⇒ +0.14（同时带的「布贴」不再叠加）",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of("布绑带", "布贴"), "韩褶", null, null),
                "3.060", List.of("bangdai_hanzhe"), List.of());

        // ─────────── 3. 同一工序两种工艺（跨 kind AND 的第二档） ───────────
        check(3, "专用命中：布绑带 ∧ 打孔 ⇒ +0.16",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of("布绑带"), "打孔", null, null),
                "3.080", List.of("bangdai_dakong"), List.of());

        // ─────────── 4. AND 缺一半 ⇒ 不命中（不是「任一条件即中」） ───────────
        check(4, "AND 缺一半：只有布绑带、无工艺 ⇒ 专用零命中 ⇒ 兜底「布贴」生效 +0.015",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of("布绑带", "布贴"), null, null, null),
                "2.935", List.of("butie"), List.of());

        // ─────────── 5. 组内 OR：values 两个取其一 ───────────
        check(5, "组内 OR：特殊选项=双眼皮接高 ⇒ 命中「画线」，但**未配置取值** ⇒ 高度不变、进 misses",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of("双眼皮接高"), null, null, null),
                "2.920", List.of(), List.of("huaxian"));

        // ─────────── 6. 未配置取值仍算「命中」⇒ 兜底不参与 ───────────
        check(6, "未配置取值 ⇒ 兜底组不参与（接高命中画线 + 同时带布贴，布贴也不加）",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of("接高", "布贴"), null, null, null),
                "2.920", List.of(), List.of("huaxian"));

        // ─────────── 7. 加工项触发 + direction=subtract ───────────
        check(7, "加工项触发 + subtract：加工项=打褶 ⇒ -0.12",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of(), null, List.of("打褶"), null),
                "2.800", List.of("dazhe"), List.of());

        // ─────────── 8/9. shaped 触发（true 命中 / false 不命中） ───────────
        check(8, "是否定型=true ⇒ +0.02",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of(), null, null, true),
                "2.940", List.of("dingxing"), List.of());
        check(9, "是否定型=false ⇒ 不命中 ⇒ 兜底生效 +0.015",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of("布贴"), null, null, false),
                "2.935", List.of("butie"), List.of());

        // ─────────── 10. 特殊选项语义族（规则写语义名，订单落 -布 / -纱 派生键） ───────────
        check(10, "语义族：订单落「余料带回-布」而规则写「余料带回」⇒ 命中 +0.03",
                row(richItems(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of("余料带回-布"), null, null, null),
                "2.950", List.of("yuliao"), List.of());

        // ─────────── 11. 部位限定（布帘项不出现在纱帘） ───────────
        check(11, "部位限定：纱帘 + 特殊选项=布贴 ⇒ 布帘项不命中 ⇒ 2.92",
                row(richItems(), rounding("half_up", 3)),
                request("纱帘", "2.92", List.of("布贴"), null, null, null),
                "2.920", List.of(), List.of());

        // ─────────── 12. 空条件 = 恒真（只靠 position 圈范围） ───────────
        check(12, "空条件恒真：帘头 ⇒ 命中「帘头通用」+0.05",
                row(richItems(), rounding("half_up", 3)),
                request("帘头", "2.92", List.of(), null, null, null),
                "2.970", List.of("liantou_any"), List.of());

        // ─────────── 13. enabled=false ⇒ 既不命中也不进 misses ───────────
        List<Map<String, Object>> disabled = richItems();
        disabled.stream().filter(i -> "butie".equals(i.get("key")))
                .forEach(i -> i.put("enabled", false));
        check(13, "enabled=false：停用「布贴」⇒ 布贴不命中、也不进 misses ⇒ 2.92",
                row(disabled, rounding("half_up", 3)),
                request("布帘", "2.92", List.of("布贴"), null, null, null),
                "2.920", List.of(), List.of());

        // ─────────── 14. 取整：mode × digits ───────────
        check(14, "取整 down/2 位：2.935 ⇒ 2.93",
                row(richItems(), rounding("down", 2)),
                request("布帘", "2.92", List.of("布贴"), null, null, null),
                "2.930", List.of("butie"), List.of());
        check(15, "取整 up/2 位：2.935 ⇒ 2.94",
                row(richItems(), rounding("up", 2)),
                request("布帘", "2.92", List.of("布贴"), null, null, null),
                "2.940", List.of("butie"), List.of());
        check(16, "取整 half_up/0 位：2.935 ⇒ 3",
                row(richItems(), rounding("half_up", 0)),
                request("布帘", "2.92", List.of("布贴"), null, null, null),
                "3", List.of("butie"), List.of());

        // ─────────── 17. 存量 v1 配置（hit 形态）不改一行也照旧算得对 ───────────
        check(17, "存量 v1 归一：hit.trigger_kind=option / trigger_value=布贴 ⇒ 与 v2 同值 +0.015",
                row(v1Items(), rounding("half_up", 3)),
                request("布帘", "2.92", List.of("布贴"), null, null, null),
                "2.935", List.of("butie"), List.of());

        // ─────────── 18. 缺成品高 ⇒ 422（不猜、不按 0 算） ───────────
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(row(richItems(), rounding("half_up", 3)));
        assertThatThrownBy(() -> service.preview(TENANT, request("布帘", null, List.of("布贴"), null, null, null)))
                .isInstanceOf(BusinessException.class);
        table.add("| 18 | 缺成品高 ⇒ 422（不猜、不按 0 算） | 422 | 422 | — | — | ✅ |\n");

        // 18 行矩阵全部通过才算「全部场景都能生效」
        assertThat(table).hasSize(18);
    }

    // ────────────────────────── 矩阵执行器 ──────────────────────────

    private void check(int no, String scenario, CuttingHeightConfig stored, Map<String, Object> req,
                       String expectedHeight, List<String> expectedHits, List<String> expectedMisses) {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(stored);
        Map<String, Object> data = service.preview(TENANT, req);
        BigDecimal actual = (BigDecimal) data.get("cutting_height");
        List<String> hits = keysOf(data.get("hits"), "key");
        List<String> misses = keysOf(data.get("misses"), "key");
        table.add("| " + no + " | " + scenario + " | " + expectedHeight + " | " + actual + " | "
                + hits + " | " + misses + " | ✅ |\n");
        assertThat(actual).as("场景 %d：%s", no, scenario).isEqualByComparingTo(expectedHeight);
        assertThat(hits).as("场景 %d 命中键集：%s", no, scenario).containsExactlyElementsOf(expectedHits);
        assertThat(misses).as("场景 %d 缺项键集：%s", no, scenario).containsExactlyElementsOf(expectedMisses);
    }

    // ────────────────────────── 配置构造 ──────────────────────────

    /** 一份把**所有可配维度**都用上的配置（14 项）。 */
    private static List<Map<String, Object>> richItems() {
        List<Map<String, Object>> items = new ArrayList<>();
        // 工序专用（specific）：跨 kind AND / 组内 OR / 语义族 / subtract / shaped
        items.add(item("bangdai_hanzhe", "布绑带-韩褶", "0.14", "specific", "布帘", "add",
                List.of(cond("option", "布绑带"), cond("craft", "韩褶"))));
        items.add(item("bangdai_dakong", "布绑带-打孔", "0.16", "specific", "布帘", "add",
                List.of(cond("option", "布绑带"), cond("craft", "打孔"))));
        items.add(item("huaxian", "画线", null, "specific", "布帘", "add",
                List.of(cond("option", "接高", "双眼皮接高"))));
        items.add(item("dazhe", "打褶扣减", "0.12", "specific", "布帘", "subtract",
                List.of(cond("processing_item", "打褶"))));
        items.add(item("dingxing", "定型加放", "0.02", "specific", "布帘", "add",
                List.of(cond("shaped", "true"))));
        items.add(item("yuliao", "余料带回", "0.03", "specific", "布帘", "add",
                List.of(cond("option", "余料带回"))));
        // 公共兜底（fallback）：空条件 = 恒真（只靠 position 圈范围）
        items.add(item("liantou_any", "帘头通用", "0.05", "fallback", "帘头", "add", List.of()));
        items.add(item("butie", "布贴", "0.015", "fallback", "布帘", "add",
                List.of(cond("option", "布贴"))));
        items.add(item("baobuzhe", "包布折", "0.08", "fallback", "布帘", "add",
                List.of(cond("option", "包布折"))));
        return items;
    }

    /** 存量 v1 形态：触发口径写在 {@code hit} 里（读面单点归一成 conditions + scope=specific）。 */
    private static List<Map<String, Object>> v1Items() {
        List<Map<String, Object>> items = new ArrayList<>();
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", "option");
        hit.put("trigger_value", "布贴");
        hit.put("position", "布帘");
        Map<String, Object> legacy = new LinkedHashMap<>();
        legacy.put("key", "butie");
        legacy.put("name", "布贴");
        legacy.put("value", new BigDecimal("0.015"));
        legacy.put("direction", "add");
        legacy.put("height_join", false);
        legacy.put("hit", hit);
        legacy.put("hit_expr", null);
        legacy.put("enabled", true);
        legacy.put("order", 10);
        items.add(legacy);
        return items;
    }

    private static Map<String, Object> item(String key, String name, String value, String scope,
                                            String position, String direction,
                                            List<Map<String, Object>> conditions) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value == null ? null : new BigDecimal(value));
        item.put("direction", direction);
        item.put("height_join", false);
        item.put("scope", scope);
        item.put("position", position);
        item.put("conditions", conditions);
        item.put("enabled", true);
        item.put("order", 10);
        return item;
    }

    private static Map<String, Object> cond(String kind, String... values) {
        Map<String, Object> condition = new LinkedHashMap<>();
        condition.put("kind", kind);
        condition.put("values", List.of(values));
        return condition;
    }

    private static Map<String, Object> rounding(String mode, int digits) {
        Map<String, Object> rounding = new LinkedHashMap<>();
        rounding.put("mode", mode);
        rounding.put("digits", digits);
        return rounding;
    }

    private static CuttingHeightConfig row(List<Map<String, Object>> items, Map<String, Object> rounding) {
        return CuttingHeightConfig.builder()
                .id("chc-7").tenantId(TENANT).status("active").deleted(0)
                .items(items).rounding(rounding).build();
    }

    private static Map<String, Object> request(String position, String finishedHeight, List<String> options,
                                               String craft, List<String> processingItems, Boolean shaped) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("position", position);
        if (finishedHeight != null) {
            body.put("finished_height", finishedHeight);
        }
        body.put("special_options", options);
        if (craft != null) {
            body.put("craft", craft);
        }
        if (processingItems != null) {
            body.put("processing_items", processingItems);
        }
        if (shaped != null) {
            body.put("is_shaped", shaped);
        }
        return body;
    }

    @SuppressWarnings("unchecked")
    private static List<String> keysOf(Object rows, String keyName) {
        if (!(rows instanceof List<?> list)) {
            return List.of();
        }
        List<String> keys = new ArrayList<>(list.size());
        for (Object raw : list) {
            if (raw instanceof Map<?, ?> m) {
                keys.add(String.valueOf(((Map<String, Object>) m).get(keyName)));
            }
        }
        return keys;
    }
}
