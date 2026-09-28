// case_ids: PR-113
package com.migao.admin.migration;

import com.migao.admin.service.WorkerShortLinkService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 入库标签迁移契约（V134，issue #5052 P2）。
 *
 * <p>写法沿用同目录 {@code InboundOrderMigrationTest}：直接断言迁移 SQL 文本 ——
 * 本仓的 {@code MigrationRunner} 按**文件名**记台账（已应用的文件整份跳过）⇒ 迁移写错了
 * **永远不会再执行**、也永远不会变红，文本级判据是这里唯一能提前发现问题的位置。</p>
 *
 * <h3>五条判据（每条都对着一个真实缺陷形态）</h3>
 * <ol>
 *   <li><b>幂等 + 显式事务</b>：{@code MigrationRunner} 要求所有迁移可重复执行；
 *       不显式 {@code BEGIN/COMMIT} 会留下半完成态；</li>
 *   <li><b>三个部分唯一索引</b>（照 {@code uk_set_part_tokens_short_code} 范式）：
 *       短码全局唯一（公开入口没有租户上下文 ⇒ 跨租户也必须唯一）、留档码唯一（已撤销的码永不复发）、
 *       一行一标签 —— 少一个都等于码空间没有兜底；</li>
 *   <li><b>撤销语义的结构不变量</b>：{@code ck_inbound_labels_code_exactly_one} 钉「活码与留档码
 *       恰有一个非空」（只置 NULL 不留档 ⇒ 撤销会被读成「不存在」）；</li>
 *   <li><b>码形状由 DB 兜底，且与 Java 侧字母表**机械等价**</b>（同一真值两处投影，必须可判等价）；
 *       正则字符类里不得出现 {@code I/L/O/U}；</li>
 *   <li><b>终态同步</b>：{@code db/init/schema.sql} 必须体现同一终态（建库脚本是基线契约），
 *       且本迁移**绝不**碰 {@code processing_set_part_tokens}（两个码空间）。</li>
 * </ol>
 */
@DisplayName("入库标签迁移契约（V134）：部分唯一索引 / 撤销不变量 / 码形状与字母表等价")
class InboundLabelMigrationTest {

    private static final String V134 = "backend/admin-api/src/main/resources/db/migration/"
            + "V134__create_inbound_labels.sql";
    private static final String SCHEMA_SQL = "backend/admin-api/src/main/resources/db/init/schema.sql";

    private static Path findRepoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        return null;
    }

    private static String read(String relative) throws IOException {
        Path root = findRepoRoot();
        if (root == null) {
            throw new IOException("找不到仓库根目录: " + relative);
        }
        return Files.readString(root.resolve(relative), StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("V134 在活目录里，且显式 BEGIN/COMMIT 包事务（幂等 DDL）")
    void v133WrapsInExplicitTransactionAndIsIdempotent() throws IOException {
        String sql = read(V134);
        assertThat(sql).contains("BEGIN;").contains("COMMIT;");
        assertThat(sql.indexOf("BEGIN;")).isLessThan(sql.indexOf("COMMIT;"));
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS inbound_labels");
        assertThat(sql).contains("CREATE UNIQUE INDEX IF NOT EXISTS");
        assertThat(sql).doesNotContain("ADD COLUMN IF NOT EXISTS");
    }

    @Test
    @DisplayName("🔴 部分唯一索引齐备：有效码唯一（活码 + 留档码 + 交叉）/ 一行一标签，谓词都带 deleted = 0")
    void v133DeclaresTheThreePartialUniqueIndexes() throws IOException {
        String sql = read(V134);
        assertThat(sql).contains("uk_inbound_labels_code").contains("uk_inbound_labels_item");
        // 🔴 码唯一建在**有效码**上：两个分列索引在 PG 里兜不住「撤销后的码被重新发一次」
        //    （NULL 从不与 NULL 冲突 ⇒ short_code 索引对留档列零约束力；真库判据抓到过这一形态）
        assertThat(sql).contains("ON inbound_labels (COALESCE(short_code, revoked_code))");
        assertThat(sql).contains("WHERE deleted = 0;");
        assertThat(sql).doesNotContain("uk_inbound_labels_revoked_code");
        assertThat(sql).contains("ON inbound_labels (tenant_id, inbound_item_id)\n    WHERE deleted = 0");
        String schema = read(SCHEMA_SQL);
        for (String index : new String[] {"uk_inbound_labels_code", "uk_inbound_labels_item"}) {
            assertThat(schema).as("建库脚本必须体现同一终态：%s", index).contains(index);
        }
    }

    @Test
    @DisplayName("🔴 撤销语义是**结构不变量**：ck_inbound_labels_code_exactly_one（不是靠调用方记得）")
    void v133PinsTheRevocationInvariant() throws IOException {
        String sql = read(V134);
        assertThat(sql).contains("ck_inbound_labels_code_exactly_one");
        assertThat(sql).contains("CHECK ((short_code IS NULL) <> (revoked_code IS NULL))");
        // 撤销 = 短码置 NULL + 原码留档（缺任一半，扫码就分不出 410 与 404）
        assertThat(sql).contains("COMMENT ON COLUMN inbound_labels.revoked_code");
    }

    @Test
    @DisplayName("🔴 码形状正则与 Java 侧字母表**机械等价**（字符类里不得出现 I/L/O/U）")
    void theDbCodeShapeIsMechanicallyEquivalentToTheJavaAlphabet() throws IOException {
        String sql = read(V134);
        Matcher m = Pattern.compile("\\^\\[([^\\]]+)\\]\\{8\\}\\$").matcher(sql);
        assertThat(m.find()).as("V134 里必须有一条 8 位码形状正则").isTrue();
        Set<Character> dbAlphabet = expandCharClass(m.group(1));

        Set<Character> javaAlphabet = new LinkedHashSet<>();
        for (char c : WorkerShortLinkService.ALPHABET.toCharArray()) {
            javaAlphabet.add(c);
        }
        assertThat(dbAlphabet).isEqualTo(javaAlphabet);
        assertThat(dbAlphabet).doesNotContain('I', 'L', 'O', 'U');
        assertThat(WorkerShortLinkService.CODE_LENGTH).isEqualTo(8);
        assertThat(sql).contains("ck_inbound_labels_code_shape");
    }

    @Test
    @DisplayName("🔴 两个码空间不串：V134 绝不碰 processing_set_part_tokens（也不建第二套 token）")
    void v133NeverTouchesTheReportShortLinkTable() throws IOException {
        // 🔴 负向断言只看 **SQL 语句**（剥掉 `--` 行注释）：迁移的注释里**必须**能写清
        //    「为什么不复用 /s/ 那张表」—— 把说明文字当判据对象会让判据逼人不许解释。
        String sql = stripSqlComments(read(V134));
        assertThat(sql).doesNotContain("processing_set_part_tokens");
        assertThat(sql).doesNotContain("/w/");
        assertThat(sql).doesNotContain("token VARCHAR");
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS inbound_labels");
    }

    @Test
    @DisplayName("迁移带 fail-closed 停止条件（DO 块）：缺表 / 缺索引 / 缺约束 ⇒ 当场 RAISE")
    void v133FailsClosedWithStopConditions() throws IOException {
        String sql = read(V134);
        assertThat(sql).contains("DO $$").contains("RAISE EXCEPTION")
                .contains("inbound_labels 表未建立")
                .contains("部分唯一索引未齐")
                .contains("两条 CHECK 未齐");
        // 可回滚（登记在注释里，不落码 —— 本仓迁移无 down 机制）
        assertThat(sql).contains("回滚 SQL");
    }

    // ============================================================ 工具

    /** 剥掉 SQL 的 `--` 行注释（判据只看语句；注释是解释，不是实现）。 */
    private static String stripSqlComments(String sql) {
        StringBuilder sb = new StringBuilder();
        for (String line : sql.split("\n", -1)) {
            int idx = line.indexOf("--");
            sb.append(idx >= 0 ? line.substring(0, idx) : line).append('\n');
        }
        return sb.toString();
    }

    /** 展开正则字符类（支持 {@code a-z} 区间与单字符）—— 用来把 DB 的口径与 Java 的口径**逐值**比。 */
    private static Set<Character> expandCharClass(String classBody) {
        Set<Character> chars = new LinkedHashSet<>();
        for (int i = 0; i < classBody.length(); i++) {
            char c = classBody.charAt(i);
            if (i + 2 < classBody.length() && classBody.charAt(i + 1) == '-') {
                char end = classBody.charAt(i + 2);
                for (char x = c; x <= end; x++) {
                    chars.add(x);
                }
                i += 2;
            } else {
                chars.add(c);
            }
        }
        return chars;
    }
}
