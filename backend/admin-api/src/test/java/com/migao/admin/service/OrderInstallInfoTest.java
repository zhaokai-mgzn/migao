// case_ids: OR-055, OR-046
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * 安装信息的**载体形状 + 归一/准入 + 读侧收敛**（issue #7856）。
 *
 * <h3>用户口径（2026-10-26 逐字）</h3>
 * <p>「订单，水洗唛，成品出库单，发货联上还缺了一个信息，窗帘的安装位置，是卧室还是阳台，还有客户要求
 * 我们备注窗帘未来安装给哪个小区」｜「这些水洗唛，入库单，发货联标签都要加上帘种，和安装信息」｜
 * 对落库载体的当场裁定：「不能作为订单基础字段吧？」</p>
 *
 * <h3>本类钉的四件事（每条都会红）</h3>
 * <ol>
 *   <li><b>零迁移</b>：{@code orders} / {@code order_items} 都没有安装信息列，且 migration 目录里
 *       **没有任何**提到安装信息的迁移 —— 改回「加一列」的形态 ⇒ 判据 1 红；</li>
 *   <li><b>实体不上列</b>：{@code Order} / {@code OrderItem} 都没有同名字段 —— 真值只在
 *       {@code order_items.processing_info}（已登记 JSONB，与 {@code formulaText} / {@code remark} 同层）；</li>
 *   <li><b>归一 + 准入</b>：去首尾空白、内部换行/制表折叠为**一个**空格（纸面单行打印）；
 *       空白 ⇒ {@code null}（不落键）；超长（安装小区 40 字 / 安装位置 12 字）⇒ <b>422</b>；</li>
 *   <li><b>读侧收敛</b>：订单级「安装小区」取该单明细里**第一条非空**（写侧扇出到每行同值；
 *       存量/半扇出数据仍能读回一个值，不猜、不拼占位）。</li>
 * </ol>
 */
class OrderInstallInfoTest {

    private static final Path MODULE = Paths.get("").toAbsolutePath();
    private static final Path SCHEMA_SQL = MODULE.resolve("src/main/resources/db/init/schema.sql");
    private static final Path MIGRATION_DIR = MODULE.resolve("src/main/resources/db/migration");

    // ──────────────────────────── ① 载体形状：不加列、不写迁移 ────────────────────────────

    @Test
    @DisplayName("🔴 #7856 零迁移：orders / order_items 都没有安装信息列（改回加列 ⇒ 红）")
    void installInfoIsNotAColumnAnywhere() throws IOException {
        String schema = Files.readString(SCHEMA_SQL, StandardCharsets.UTF_8);

        assertThat(tableColumns(schema, "orders"))
                .as("orders 仍是 24 列：用户裁定「不能作为订单基础字段」⇒ 不许加列")
                .doesNotContain("install_community", "install_room")
                .hasSize(24);
        assertThat(tableColumns(schema, "order_items"))
                .as("order_items 已 32 列（超列预算的具名例外，schema_health_ledger 有 override）⇒ 更不许再加")
                .doesNotContain("install_community", "install_room");

        assertThat(migrationsMentioningInstallInfo())
                .as("零迁移：migration 目录里不许出现「给安装信息加列」的迁移（写回来 ⇒ 本判据红）")
                .isEmpty();
    }

    @Test
    @DisplayName("🔴 #7856 实体不上列：Order / OrderItem 都没有安装信息字段（真值在 processing_info）")
    void installInfoIsNotAnEntityField() {
        assertThat(fieldNames(Order.class))
                .as("订单表不加列 ⇒ 实体也不许有这两个字段（有字段就必然要列）")
                .doesNotContain("installCommunity", "installRoom");
        assertThat(fieldNames(OrderItem.class))
                .as("order_items 不加列 ⇒ 实体也不许有；两个信息都只走 JSONB 顶层键")
                .doesNotContain("installCommunity", "installRoom");
    }

    // ──────────────────────────── ② 归一 + 准入 ────────────────────────────

    @Test
    @DisplayName("#7856 归一：去首尾空白 + 内部换行/制表折叠为一个空格；空白 ⇒ 不落键")
    void normalizeTrimsAndCollapsesInnerWhitespace() {
        assertThat(OrderInstallInfo.normalizeCommunity("  春江花园 3栋\n2单元\t502 "))
                .as("内部换行折叠成**一个**空格（50×70 标签只有一行）")
                .isEqualTo("春江花园 3栋 2单元 502");
        assertThat(OrderInstallInfo.normalizeCommunity("   "))
                .as("空白 = 未填 ⇒ null（不落键；否则快照里会出现一个空字符串，读侧分不清「没填」）")
                .isNull();
        assertThat(OrderInstallInfo.normalizeCommunity(null)).isNull();
        assertThat(OrderInstallInfo.normalizeRoom("主卧\n")).isEqualTo("主卧");
        assertThat(OrderInstallInfo.normalizeCommunity("春".repeat(OrderInstallInfo.COMMUNITY_MAX_LENGTH)))
                .as("40 字是合法上界（等于上限不算超）")
                .hasSize(40);
        assertThat(OrderInstallInfo.normalizeRoom("主卧")).isEqualTo("主卧");
    }

    @Test
    @DisplayName("🔴 #7856 超长 ⇒ 422（安装小区 40 字 / 安装位置 12 字），文案说清上限与当前长度")
    void overlongValuesAreRejectedWith422() {
        BusinessException community = (BusinessException) catchThrowable(
                () -> OrderInstallInfo.normalizeCommunity("春".repeat(OrderInstallInfo.COMMUNITY_MAX_LENGTH + 1)));
        assertThat(community).isNotNull();
        assertThat(community.getHttpStatus()).as("422（本仓字段校验的统一形态）").isEqualTo(422);
        assertThat(community.getMessage()).contains("安装小区不能超过 40 个字");

        BusinessException room = (BusinessException) catchThrowable(
                () -> OrderInstallInfo.normalizeRoom("主卧次卧客厅阳台书房儿童房衣帽间走廊玄关"));
        assertThat(room).isNotNull();
        assertThat(room.getHttpStatus()).isEqualTo(422);
        assertThat(room.getMessage()).contains("安装位置不能超过 12 个字");
    }

    // ──────────────────────────── ③ 读侧收敛 / 取值 ────────────────────────────

    @Test
    @DisplayName("#7856 读侧收敛：取第一条**非空**（缺键 / 空白都不算），全缺 ⇒ null（不拼占位）")
    void firstCommunityTakesFirstNonBlank() {
        ObjectMapper mapper = new ObjectMapper();
        List<OrderItem> items = List.of(
                item("i1", Map.of("installRoom", "主卧")),
                item("i2", Map.of("installCommunity", "   ")),
                item("i3", Map.of("installCommunity", " 春江花园 ")),
                item("i4", Map.of("installCommunity", "别的小区")));

        assertThat(OrderInstallInfo.firstCommunity(items, mapper))
                .as("第一条非空 ⇒ 「 春江花园 」（去空白），不是最后的「别的小区」")
                .isEqualTo("春江花园");
        assertThat(OrderInstallInfo.firstCommunity(List.of(item("i5", null)), mapper))
                .as("全缺 ⇒ null（存量单 / 扇出之前落的单）")
                .isNull();
        assertThat(OrderInstallInfo.firstCommunity(List.of(), mapper)).isNull();
    }

    @Test
    @DisplayName("#7856 processing_info 是 JSON 字符串形态时同样能取值（自定义 @Select 路径）")
    void valueOfToleratesJsonString() {
        ObjectMapper mapper = new ObjectMapper();
        String raw = "{\"installRoom\":\"阳台\",\"installCommunity\":\"春江花园\"}";

        assertThat(OrderInstallInfo.valueOf(raw, OrderInstallInfo.KEY_INSTALL_ROOM, mapper)).isEqualTo("阳台");
        assertThat(OrderInstallInfo.valueOf(raw, OrderInstallInfo.KEY_INSTALL_COMMUNITY, mapper)).isEqualTo("春江花园");
        assertThat(OrderInstallInfo.valueOf("不是 JSON", OrderInstallInfo.KEY_INSTALL_ROOM, mapper))
                .as("坏形态 ⇒ null（不得让整单读面 500）")
                .isNull();
    }

    // ──────────────────────────── 夹具 ────────────────────────────

    private static OrderItem item(String id, Map<String, Object> installKeys) {
        return OrderItem.builder()
                .id(id)
                .processingInfo(installKeys == null ? null : new LinkedHashMap<>(installKeys))
                .build();
    }

    private static List<String> fieldNames(Class<?> type) {
        return Arrays.stream(type.getDeclaredFields()).map(java.lang.reflect.Field::getName).toList();
    }

    /** 建库脚本里某张表的列名（按建表语句逐行解析；{@code CONSTRAINT} / 注释行不算列）。 */
    private static List<String> tableColumns(String schema, String table) {
        String head = "CREATE TABLE " + table + " (";
        int start = schema.indexOf(head);
        assertThat(start).as("建库脚本里必须有 %s 建表语句（否则本判据在空跑）", table).isGreaterThanOrEqualTo(0);
        int end = schema.indexOf(");", start);
        assertThat(end).as("%s 建表语句必须闭合", table).isGreaterThan(start);
        List<String> columns = new ArrayList<>();
        for (String line : schema.substring(start + head.length(), end).split("\n")) {
            String trimmed = line.trim();
            if (trimmed.isEmpty() || trimmed.startsWith("--") || trimmed.startsWith("CONSTRAINT")
                    || trimmed.startsWith("PRIMARY") || trimmed.startsWith("FOREIGN")
                    || trimmed.startsWith("UNIQUE")) {
                continue;
            }
            columns.add(trimmed.split("\\s+")[0]);
        }
        return columns;
    }

    /** migration 目录里提到安装信息的迁移（正常应为空 —— 本单是**零迁移**的单）。 */
    private static List<String> migrationsMentioningInstallInfo() throws IOException {
        try (Stream<Path> files = Files.list(MIGRATION_DIR)) {
            return files.filter(path -> path.getFileName().toString().endsWith(".sql"))
                    .filter(path -> {
                        String sql = readQuietly(path);
                        return sql.contains("install_community") || sql.contains("installCommunity")
                                || sql.contains("install_room") || sql.contains("installRoom");
                    })
                    .map(path -> path.getFileName().toString())
                    .sorted()
                    .toList();
        }
    }

    private static String readQuietly(Path path) {
        try {
            return Files.readString(path, StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }
}
