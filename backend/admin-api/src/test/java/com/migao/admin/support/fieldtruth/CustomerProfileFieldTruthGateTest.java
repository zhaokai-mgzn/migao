// case_ids: CU-002

package com.migao.admin.support.fieldtruth;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 实例判据：{@code customer_profiles} 的字段级真值声明必须与<b>源码写入点</b>和<b>读面遮蔽清单</b>一致
 * （issue #5362）。
 *
 * <p>要治的病：RFM / 统计列有 schema、有实体、有 Mapper、有读面，<b>唯独没有计算逻辑</b> ——
 * 于是 DB 列默认值（{@code DEFAULT 0} / {@code DEFAULT 30}）被读出来当成了真值
 * （「这个客户消费 0 元」）。同一形态会在别的表复发 ⇒ 类级元守卫见
 * {@code FieldTruthMetaGuardTest}，扫描的唯一实现在 {@link FieldTruthSourceScan}。
 *
 * <p>三份产物互相独立（合并任意两份 ⇒ 判据退化成自证）：① {@link CustomerProfileFieldTruth} 声明；
 * ② 源码扫描出的写入点；③ {@link CustomerProfileTruthMask} 的显式 {@code setXxx(null)} 行。
 */
class CustomerProfileFieldTruthGateTest {

    private static final FieldTruth.Declaration DECL = CustomerProfileFieldTruth.declaration();
    private static final String TABLE = CustomerProfileFieldTruth.TABLE;

    private static Map<String, List<FieldTruthSourceScan.WriteSite>> sites() {
        return FieldTruthSourceScan.writeSites(DECL.entity(), TABLE);
    }

    private static Set<String> masked() {
        return FieldTruthSourceScan.maskedFields(DECL.entity().getSimpleName());
    }

    // ==================== ① 声明完整性 ====================

    @Test
    @DisplayName("声明完整性：实体每个字段都必须登记「有真值/无真值 + 原因」")
    void declarationCoversEveryEntityField() {
        Set<String> entityFields = new TreeSet<>();
        for (Field field : DECL.entity().getDeclaredFields()) {
            if (!field.isSynthetic() && !Modifier.isStatic(field.getModifiers())) {
                entityFields.add(field.getName());
            }
        }
        assertThat(entityFields).as("反射结果为空说明判据面已失效").isNotEmpty();
        assertThat(DECL.declaredFields())
                .as("实体每个字段都必须有真值声明：漏登记的字段会静默回到「用列默认值冒充真值」的老路")
                .containsExactlyInAnyOrderElementsOf(entityFields);
        for (String field : DECL.declaredFields()) {
            assertThat(DECL.entry(field).reason())
                    .as("字段 %s 的声明必须写清原因/证据（「暂无」这类空话不算）", field)
                    .hasSizeGreaterThan(10);
        }
    }

    // ==================== ② 机械判据（真实产物上必须全绿） ====================

    @Test
    @DisplayName("判据：声明「有真值」⇒ 源码里有真值级写入点；声明「无真值」⇒ 未以真值形态暴露")
    void criterionIsGreenOnRealDeclaration() {
        assertThat(FieldTruthSourceScan.violations(DECL, sites(), masked()))
                .as("声明 ↔ 源码写入点 ↔ 遮蔽清单 三方必须一致（红 = 有一方已经漂移）")
                .isEmpty();
    }

    @Test
    @DisplayName("遮蔽清单与声明一一对应：无真值字段全置 null，有真值字段一个都不许被遮蔽")
    void maskMatchesDeclarationExactly() {
        Set<String> masked = masked();
        assertThat(masked)
                .as("遮蔽清单解析不得空转（解析失效 ⇒ 判据静默失去咬合力）")
                .isNotEmpty()
                .contains("rScore");
        assertThat(masked).containsExactlyInAnyOrderElementsOf(DECL.noTruthFields());
        assertThat(masked).doesNotContainAnyElementsOf(DECL.hasTruthFields());
        assertThat(DECL.noTruthFields())
                .as("同一张表里有真值/无真值必须并存：全表一刀切说明声明没做逐字段核实")
                .isNotEmpty();
        assertThat(DECL.hasTruthFields()).isNotEmpty();
    }

    // ==================== ③ 注入式红证（改判 ⇒ 判据必须变红） ====================

    @Test
    @DisplayName("红证①：无真值字段改判成有真值 ⇒ 判据点名变红（源码里没有真值级写入点）")
    void injectionFlipNoTruthToHasTruthTurnsRed() {
        for (String field : List.of("rScore", "avgOrderValue", "lastOrderAt",
                "totalConsumption", "nextPurchasePredictionDays", "lifecycleStage")) {
            FieldTruth.Declaration flipped = flip(field, FieldTruth.HAS_TRUTH);
            // 遮蔽清单同步去掉该字段（与改判后的声明自洽）⇒ 只剩「源码里有没有写它」这一条判据
            Set<String> consistentMask = new TreeSet<>(masked());
            consistentMask.remove(field);
            assertThat(FieldTruthSourceScan.violations(flipped, sites(), consistentMask))
                    .as("把 %s 改判成「有真值」而源码里没有真值级写入点 ⇒ 判据必须变红", field)
                    .hasSize(1)
                    .allMatch(v -> v.startsWith(field + " ") && v.contains("没有真值级写入点"));
        }
    }

    @Test
    @DisplayName("红证②：有真值字段改判成无真值 ⇒ 判据点名变红（源码里确实在写它）")
    void injectionFlipHasTruthToNoTruthTurnsRed() {
        for (String field : List.of("vipLevel", "phone", "tags", "lastActiveAt", "registeredAt")) {
            FieldTruth.Declaration flipped = flip(field, FieldTruth.NO_TRUTH);
            // 遮蔽清单同步加上该字段（自洽）⇒ 只剩「源码里在写它」这一条判据
            Set<String> consistentMask = new TreeSet<>(masked());
            consistentMask.add(field);
            assertThat(FieldTruthSourceScan.violations(flipped, sites(), consistentMask))
                    .as("把 %s 改判成「无真值」但源码里存在真值级写入点 ⇒ 判据必须变红", field)
                    .hasSize(1)
                    .allMatch(v -> v.startsWith(field + " ") && v.contains("存在真值级写入点"));
        }
    }

    @Test
    @DisplayName("红证③：遮蔽清单漏一行 / 多一行 ⇒ 判据点名变红（暴露面不许漂移）")
    void injectionMaskDriftTurnsRed() {
        Set<String> missing = new TreeSet<>(masked());
        missing.remove("totalConsumption");
        assertThat(FieldTruthSourceScan.violations(DECL, sites(), missing))
                .as("声明「无真值」却漏遮蔽 ⇒ 页面与 Agent 会把 DB 默认的 0 当成「消费 0 元」")
                .anyMatch(v -> v.startsWith("totalConsumption ") && v.contains("未在读面遮蔽"));

        Set<String> extra = new TreeSet<>(masked());
        extra.add("vipLevel");
        assertThat(FieldTruthSourceScan.violations(DECL, sites(), extra))
                .as("把「有真值」字段也遮蔽 ⇒ 真值被抹成未知（本单不是整表一刀切）")
                .anyMatch(v -> v.startsWith("vipLevel ") && v.contains("却被遮蔽类置 null"));
    }

    @Test
    @DisplayName("红证④：声明漏掉实体字段 ⇒ 判据点名变红（新增字段不得静默溜过）")
    void injectionMissingFieldTurnsRed() {
        FieldTruth.Declaration reduced = mutate(DECL, "rScore", null);
        assertThat(FieldTruthSourceScan.violations(reduced, sites(), masked()))
                .as("漏登记的字段必须被点名（否则新字段一出生就没有真值声明）")
                .anyMatch(v -> v.contains("未声明字段") && v.contains("rScore"));
    }

    @Test
    @DisplayName("判据不得空转：写入点集合为空 ⇒ 所有「有真值」字段都必须被判红")
    void criterionIsNotVacuous() {
        List<String> violations = FieldTruthSourceScan.violations(DECL, Map.of(), masked());
        assertThat(violations)
                .as("扫描不到写入点却全绿 = 判据空转（本文件要消灭的失效形态）")
                .isNotEmpty();
        assertThat(violations.stream().filter(v -> v.contains("没有真值级写入点")).count())
                .as("每个「有真值」字段都必须被点名")
                .isEqualTo(DECL.hasTruthFields().size());
    }

    // ==================== ④ 解析器自身的牙口 ====================

    @Test
    @DisplayName("SQL 写入点解析：@Update / XML mapper 的 SET 列必须能识别（否则真值会被误判成「零写入」）")
    void sqlSetClauseIsParsed() {
        assertThat(FieldTruthSourceScan.propertiesFromSetClause(
                "total_consumption = total_consumption + ?, updated_at = NOW() WHERE id = ?"))
                .containsExactly("totalConsumption", "updatedAt");
        assertThat(FieldTruthSourceScan.propertiesFromSetClause("total_orders = ?"))
                .containsExactly("totalOrders");
    }

    @Test
    @DisplayName("写入点分类：常量占位 ≠ 真值级写入（`.totalOrders(0)` 不得算作「有真值」）")
    void constantSeedIsNotTruthGrade() {
        assertThat(FieldTruthSourceScan.kindOf("0")).isEqualTo(FieldTruthSourceScan.Kind.CONSTANT);
        assertThat(FieldTruthSourceScan.kindOf("1")).isEqualTo(FieldTruthSourceScan.Kind.CONSTANT);
        assertThat(FieldTruthSourceScan.kindOf("BigDecimal.ZERO")).isEqualTo(FieldTruthSourceScan.Kind.CONSTANT);
        assertThat(FieldTruthSourceScan.kindOf("\"new\"")).isEqualTo(FieldTruthSourceScan.Kind.CONSTANT);
        assertThat(FieldTruthSourceScan.kindOf("null")).isEqualTo(FieldTruthSourceScan.Kind.CONSTANT);
        assertThat(FieldTruthSourceScan.kindOf("OffsetDateTime.now()")).isEqualTo(FieldTruthSourceScan.Kind.DERIVED);
        assertThat(FieldTruthSourceScan.kindOf("profile.getPhone()")).isEqualTo(FieldTruthSourceScan.Kind.DERIVED);
        assertThat(FieldTruthSourceScan.kindOf("sourceChannel != null ? sourceChannel : \"wechat_mini\""))
                .isEqualTo(FieldTruthSourceScan.Kind.DERIVED);
    }

    @Test
    @DisplayName("注释掉的 setter 不得算作写入点（否则判据永远不会红）")
    void commentedOutSettersAreNotWriteSites() {
        String src = "class X {\n"
                + "  void m() { CustomerProfile p = null;\n"
                + "    p.setPhone(\"1\");\n"
                + "    // p.setTotalOrders(0);\n"
                + "  }\n"
                + "}\n";
        assertThat(FieldTruthSourceScan.stripComments(src)).doesNotContain("setTotalOrders");
        assertThat(FieldTruthSourceScan.stripComments(src)).contains("setPhone");
    }

    // ==================== 小工具 ====================

    private static FieldTruth.Declaration flip(String field, FieldTruth truth) {
        FieldTruth.Entry entry = DECL.entry(field);
        assertThat(entry).as("注入点字段 %s 必须在声明里", field).isNotNull();
        return mutate(DECL, field, new FieldTruth.Entry(truth, entry.reason()));
    }

    private static FieldTruth.Declaration mutate(FieldTruth.Declaration base, String field,
                                                 FieldTruth.Entry entry) {
        Map<String, FieldTruth.Entry> fields = new java.util.LinkedHashMap<>(base.fields());
        if (entry == null) {
            fields.remove(field);
        } else {
            fields.put(field, entry);
        }
        return new FieldTruth.Declaration(base.entity(), base.table(), fields);
    }
}