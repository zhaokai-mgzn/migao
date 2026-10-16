package com.migao.admin.service;

// case_ids: PG-073

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 真库判据（issue #5653）：结算单的**期间唯一性 + 作废重开 + 作废不改写**在真 PG 上成立。
 *
 * <p>为什么必须有这一条（与 mock 判据的分工）：{@link PieceworkSettlementServiceTest} 证明「服务层
 * 按什么顺序调什么」，而**用户看到的契约**落在 SQL 文本上 —— 部分唯一索引的谓词、{@code ON CONFLICT}
 * 的目标与谓词是否匹配（PG 冲突推断要求两者一致，写错就是 `there is no unique or exclusion
 * constraint matching the ON CONFLICT specification`）、{@code CAST(… AS jsonb)} 能不能吃下 JSON 串
 * —— 这三条**只有真库能判**（同族口径见 {@code PieceworkSettlementMapper} 的注记）。</p>
 *
 * <h2>核验的是哪一条主张（逐条可归因）</h2>
 * <ol>
 *   <li><b>迁移终态</b>：{@code V156} 的 DDL 在真 PG 上跑得通、两遍幂等，且
 *       {@code uk_piecework_settlements_active} 的谓词**逐字**是
 *       {@code voided_at IS NULL AND deleted = 0}（漏一条 ⇒ 作废后永远不能重开 / 软删行占位）；</li>
 *   <li><b>同期间同工人至多一张活跃单</b>：同一份 mapper SQL 插第二遍 ⇒ <b>0 行</b>
 *       （原子闸生效 = 服务层能给出具名 409 而不是 500）；</li>
 *   <li><b>作废后可以重开、旧行留痕</b>：作废（只置那一族三列）后同期间同工人可再插一行，
 *       且第一行的金额 / 期间 / 明细**一字未动**、{@code voided_at} 非空；</li>
 *   <li><b>跨月隔离</b>：同一工人另一个期间 ⇒ 不受影响（期间是唯一键成分）。</li>
 * </ol>
 *
 * <p>红证（注入式，真库）：把唯一索引谓词里的 {@code voided_at IS NULL} 去掉 ⇒ 判据 3 红
 * （作废后重开被唯一约束拒绝）；把 {@code ON CONFLICT} 的 {@code WHERE …} 谓词去掉 ⇒ 判据 2 红
 * （PG 报「no unique or exclusion constraint matching the ON CONFLICT specification」）。</p>
 */
@DisplayName("PieceworkSettlement 真库判据（#5653：期间唯一 / 作废重开 / 作废不改写）")
class PieceworkSettlementRealDbTest {

    private static PgCluster cluster;
    private static JdbcTemplate jdbc;
    /** 真 mapper（判据跑的是**仓内那份 SQL**，不是测试里另抄的一份 —— 抄一份 = 第二个会漂的真值源）。 */
    private static com.migao.admin.mapper.PieceworkSettlementMapper settlementMapper;
    private static org.apache.ibatis.session.SqlSession session;

    @BeforeAll
    static void startCluster() throws Exception {
        cluster = PgCluster.startOrAbort();
        jdbc = new JdbcTemplate(cluster.dataSource());
        jdbc.execute("CREATE TABLE IF NOT EXISTS tenants (id BIGINT PRIMARY KEY)");
        jdbc.execute("INSERT INTO tenants (id) VALUES (1), (2) ON CONFLICT DO NOTHING");
        // 迁移 DDL 逐字来自活迁移文件（不手抄第二份 —— 抄一份就会各自漂移）
        for (String statement : migrationStatements()) {
            jdbc.execute(statement);
        }
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new org.apache.ibatis.mapping.Environment(
                "settlement-redb", new org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory(),
                cluster.dataSource()));
        configuration.addMapper(com.migao.admin.mapper.PieceworkSettlementMapper.class);
        // 实体必须进 MP 的 TableInfo 注册表：`@TableId(ASSIGN_UUID)` 的主键生成发生在**语句执行前**，
        // 而 MybatisParameterHandler 按实体类查 TableInfo ⇒ 只 addMapper 不注册时 id 恒 null、
        // 真库报主键 NOT NULL（本机实测抓到过 —— 这一条判据就是为了钉住它）
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, "");
        assistant.setCurrentNamespace("migao.piecework.settlement.test");
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                assistant, com.migao.admin.entity.PieceworkSettlement.class);
        session = new com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder()
                .build(configuration).openSession(true);
        settlementMapper = session.getMapper(com.migao.admin.mapper.PieceworkSettlementMapper.class);
    }

    @AfterAll
    static void stopCluster() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    @Test
    @DisplayName("🔴 迁移终态：唯一索引谓词逐字含 voided_at IS NULL 与 deleted = 0（漏一条即产品级故障）")
    void uniqueIndexPredicateIsExactlyAsDeclared() {
        String indexDef = jdbc.queryForObject(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'uk_piecework_settlements_active'",
                String.class);
        assertThat(indexDef).isNotNull();
        assertThat(indexDef).contains("UNIQUE");
        assertThat(indexDef).contains("voided_at IS NULL");
        assertThat(indexDef).contains("deleted = 0");
        // 两遍幂等（迁移可重复执行是 MigrationRunner 的硬要求）
        for (String statement : migrationStatements()) {
            jdbc.execute(statement);
        }
        assertThat(jdbc.queryForObject(
                "SELECT count(*) FROM pg_indexes WHERE indexname = 'uk_piecework_settlements_active'",
                Integer.class)).isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 原子闸：同一期间同工人插第二遍 ⇒ 0 行（不是抛异常 ⇒ 端点得到具名 409，不是 500）")
    void secondActiveInsertIsAbsorbedByTheAtomicGate() {
        jdbc.update("DELETE FROM piecework_settlements");
        assertThat(insertActive(1L, "2026-10", "张三", "7.40")).isEqualTo(1);
        assertThat(insertActive(1L, "2026-10", "张三", "7.40")).isZero();
        assertThat(jdbc.queryForObject(
                "SELECT count(*) FROM piecework_settlements WHERE tenant_id = 1", Integer.class)).isEqualTo(1);
        // 另一个工人 / 另一个租户 / 另一个期间各自由通过（唯一性是「租户 × 期间 × 工人」三元组）
        assertThat(insertActive(1L, "2026-10", "李四", "3.00")).isEqualTo(1);
        assertThat(insertActive(2L, "2026-10", "张三", "7.40")).isEqualTo(1);
        assertThat(insertActive(1L, "2026-09", "张三", "7.40")).isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 作废 + 重开：作废只改那一族三列，旧行金额/期间/明细一字未动，且同期间可再生成")
    void voidKeepsTheSnapshotAndAllowsRegeneration() {
        jdbc.update("DELETE FROM piecework_settlements");
        assertThat(insertActive(1L, "2026-10", "张三", "7.40")).isEqualTo(1);

        String activeId = jdbc.queryForObject("SELECT id FROM piecework_settlements "
                + "WHERE tenant_id = 1 AND period = '2026-10' AND worker_name = '张三'", String.class);
        int voided = jdbc.update("UPDATE piecework_settlements SET voided_at = NOW(), voided_by = ?, "
                        + "void_reason = ?, updated_at = NOW() "
                        + "WHERE id = ? AND tenant_id = ? AND deleted = 0 AND voided_at IS NULL",
                "user-owner-001", "单价录错，重开", activeId, 1L);
        assertThat(voided).isEqualTo(1);
        // 重复作废 = 幂等空操作（CAS 谓词）—— 服务层据此给具名 409，不谎报成功
        assertThat(jdbc.update("UPDATE piecework_settlements SET voided_at = NOW() "
                + "WHERE id = ? AND tenant_id = ? AND deleted = 0 AND voided_at IS NULL",
                activeId, 1L)).isZero();

        Map<String, Object> before = jdbc.queryForMap(
                "SELECT total_amount, period, worker_name, line_items::text AS li, voided_at, voided_by "
                        + "FROM piecework_settlements WHERE id = ?", activeId);
        assertThat(((BigDecimal) before.get("total_amount")).toPlainString()).isEqualTo("7.40");
        assertThat(before.get("period")).isEqualTo("2026-10");
        assertThat(before.get("worker_name")).isEqualTo("张三");
        assertThat(before.get("voided_at")).isNotNull();
        assertThat(before.get("voided_by")).isEqualTo("user-owner-001");
        assertThat((String) before.get("li")).contains("精裁");

        // 旧行仍在（留痕）+ 同期间同工人可以重开一张
        assertThat(jdbc.queryForObject(
                "SELECT count(*) FROM piecework_settlements WHERE tenant_id = 1", Integer.class)).isEqualTo(1);
        assertThat(insertActive(1L, "2026-10", "张三", "9.90")).isEqualTo(1);
        // 排序键用 id（UUID，确定性）：**不能**按插入顺序读 —— 同期间两张行在表里的物理顺序
        // 不保证（本机实测：单独跑本类通过、与其它类同批跑时顺序翻转 ⇒ 位置断言假红）
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, total_amount, voided_at FROM piecework_settlements "
                        + "WHERE tenant_id = 1 AND period = '2026-10' AND worker_name = '张三' ORDER BY id");
        assertThat(rows).hasSize(2);
        List<Map<String, Object>> live = rows.stream()
                .filter(r -> r.get("voided_at") == null).toList();
        List<Map<String, Object>> voidedRows = rows.stream()
                .filter(r -> r.get("voided_at") != null).toList();
        assertThat(live).as("重开的那张必须生效中").hasSize(1);
        assertThat(((BigDecimal) live.get(0).get("total_amount")).toPlainString()).isEqualTo("9.90");
        assertThat(voidedRows).as("旧单必须仍在（作废不物理删）").hasSize(1);
        assertThat(((BigDecimal) voidedRows.get(0).get("total_amount")).toPlainString()).isEqualTo("7.40");
    }

    @Test
    @DisplayName("🔴 真映射：mapper 真走一遍 —— id 落库 / line_items 反序列化成 List / voidActive 不改写快照")
    void mapperRoundTripKeepsTheSnapshotColumns() {
        jdbc.update("DELETE FROM piecework_settlements");
        java.time.OffsetDateTime now = java.time.OffsetDateTime.now();
        com.migao.admin.entity.PieceworkSettlement row = com.migao.admin.entity.PieceworkSettlement.builder()
                .tenantId(1L)
                .period("2026-10")
                .workerName("张三")
                .totalAmount(new BigDecimal("7.40"))
                .lineItems(java.util.List.of(new com.migao.admin.dto.PieceworkSettlementLine(
                        "精裁", new BigDecimal("10.00"), new BigDecimal("4.00"))))
                .generatedBy("user-owner-001")
                .generatedAt(now)
                .createdAt(now)
                .updatedAt(now)
                .build();
        row.setDeleted(0);
        assertThat(settlementMapper.insertActiveIfAbsent(row,
                "[{\"operation\":\"精裁\",\"qty\":10.00,\"amount\":4.00}]")).isEqualTo(1);
        // ① id 由 MP 在语句执行前生成（生产路径依赖它 —— 没有它真库直接 NOT NULL 失败）
        assertThat(row.getId()).as("ASSIGN_UUID 必须在 insert 前赋值").isNotBlank();

        // ② 读回：JSONB 列反序列化成 List（不是 PGobject / 不是字符串）
        com.migao.admin.entity.PieceworkSettlement back = settlementMapper.selectById(row.getId());
        assertThat(back).isNotNull();
        assertThat(back.getTotalAmount().toPlainString()).isEqualTo("7.40");
        assertThat(back.getLineItems()).as("line_items 必须过 JacksonTypeHandler 落成 List")
                .isNotNull().hasSize(1);
        assertThat(back.getLineItems().get(0).getOperation()).isEqualTo("精裁");
        assertThat(back.getLineItems().get(0).getAmount().toPlainString()).isEqualTo("4.00");

        // ③ voidActive：CAS 命中一次，第二次 0（幂等空操作）
        assertThat(settlementMapper.voidActive(row.getId(), 1L, "user-owner-001", "单价录错，重开", now))
                .isEqualTo(1);
        assertThat(settlementMapper.voidActive(row.getId(), 1L, "user-owner-001", "再来一次", now)).isZero();

        // ④ 作废后：行仍在（逻辑删没被触发）、快照列一字未动、留痕三件套在场
        com.migao.admin.entity.PieceworkSettlement voided = settlementMapper.selectById(row.getId());
        assertThat(voided).as("作废不是删除：行必须仍在").isNotNull();
        assertThat(voided.getVoidedAt()).isNotNull();
        assertThat(voided.getVoidedBy()).isEqualTo("user-owner-001");
        assertThat(voided.getVoidReason()).isEqualTo("单价录错，重开");
        assertThat(voided.getTotalAmount().toPlainString()).isEqualTo("7.40");
        assertThat(voided.getPeriod()).isEqualTo("2026-10");
        assertThat(voided.getWorkerName()).isEqualTo("张三");
        assertThat(voided.getLineItems()).hasSize(1);
        assertThat(voided.getGeneratedBy()).isEqualTo("user-owner-001");
    }

    /**
     * 逐字执行**活迁移文件**里的语句 —— 剥掉 `BEGIN/COMMIT`，并按**顶层**分号切句
     * （`DO $$ … $$` 里的分号不是语句分隔符：直接 `split(";")` 会把 PL/pgSQL 块切碎，
     * 真库报 `Unterminated dollar quote`；本机实测踩过一次）。
     */
    private static List<String> migrationStatements() {
        Path file = Paths.get("src/main/resources/db/migration/V156__create_piecework_settlements.sql");
        assertThat(Files.isRegularFile(file))
                .as("活迁移文件不在（迁移被改名 / 搬走 ⇒ 判据必须当场红，不许静默跳过）：%s", file)
                .isTrue();
        String sql;
        try {
            sql = Files.readString(file);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
        StringBuilder body = new StringBuilder();
        for (String line : sql.split("\n")) {
            String trimmed = line.strip();
            if (trimmed.startsWith("--") || trimmed.equalsIgnoreCase("BEGIN;")
                    || trimmed.equalsIgnoreCase("COMMIT;")) {
                continue;
            }
            body.append(line).append('\n');
        }
        List<String> statements = new java.util.ArrayList<>();
        StringBuilder current = new StringBuilder();
        int dollarBlock = 0;
        for (int i = 0; i < body.length(); i++) {
            char ch = body.charAt(i);
            if (ch == '$' && i + 1 < body.length() && body.charAt(i + 1) == '$') {
                dollarBlock = dollarBlock == 0 ? 1 : 0;
                current.append("$$");
                i++;
                continue;
            }
            if (ch == ';' && dollarBlock == 0) {
                statements.add(current.toString().strip());
                current.setLength(0);
                continue;
            }
            current.append(ch);
        }
        if (!current.toString().isBlank()) {
            statements.add(current.toString().strip());
        }
        return statements.stream().filter(s -> !s.isEmpty()).toList();
    }

    /** 走**真 mapper** 插一行（返回值语义 = 1 本次真的落了 / 0 已有活跃单被原子闸吸收）。 */
    private static int insertActive(Long tenantId, String period, String worker, String amount) {
        java.time.OffsetDateTime now = java.time.OffsetDateTime.now();
        com.migao.admin.entity.PieceworkSettlement row = com.migao.admin.entity.PieceworkSettlement.builder()
                .tenantId(tenantId)
                .period(period)
                .workerName(worker)
                .totalAmount(new BigDecimal(amount))
                .lineItems(java.util.List.of(new com.migao.admin.dto.PieceworkSettlementLine(
                        "精裁", new BigDecimal("10.00"), new BigDecimal("4.00"))))
                .generatedBy("user-owner-001")
                .generatedAt(now)
                .createdAt(now)
                .updatedAt(now)
                .build();
        row.setDeleted(0);
        return settlementMapper.insertActiveIfAbsent(row,
                "[{\"operation\":\"精裁\",\"qty\":10.00,\"amount\":4.00}]");
    }
}
