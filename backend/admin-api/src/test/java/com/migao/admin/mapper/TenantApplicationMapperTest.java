// case_ids: MC-101, MC-102

package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.TenantApplication;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * TenantApplicationMapper 契约测试（企业入驻申请，issue #6954）。
 *
 * <h2>守什么</h2>
 * 审批权 / 驳回权的**原子闸**（CAS）是写进 {@code @Update} 注解里的<b>手写 SQL</b> ——
 * 它既不被编译器检查，也不被任何自动生成的 SQL 覆盖 ⇒ 谓词掉了、{@code deleted} 谓词被
 * 「照抄别的表的模板」加进来、审计列漏写，全都**静默**。本类把这几条钉成机械判据：
 *
 * <ol>
 *   <li><b>方法面</b>：{@code approveIfPending} / {@code rejectIfPending} 存在、返回 {@code int}
 *       （＝按**影响行数**判定，这是 CAS 的判定面本身）、{@code @Update} 在场；</li>
 *   <li><b>参数名</b>：{@code id} / {@code reviewerId} / {@code reviewedAt} / {@code reason}
 *       —— 它们必须与 SQL 里的 {@code #{…}} 逐字对得上（{@code @Param} 是唯一关联面）；</li>
 *   <li><b>状态迁移本体</b>：SET 侧直接写终态字面量（{@code status = 'approved'} /
 *       {@code 'rejected'}），不依赖调用方传进来的字符串（传错就写错，且 SQL 层看不出来）；</li>
 *   <li><b>CAS 谓词</b>：{@code WHERE} 段必须含 {@code #{id}} 与 {@code status = 'pending'}
 *       —— 少了它，并发下两个请求都能过（#6954 的形态）；</li>
 *   <li><b>审计列同句写入</b>：{@code reviewed_at} 与 {@code updated_at = NOW()} 必须在同一条语句里
 *       （手写 SQL 不经 {@code MyMetaObjectHandler} 的 {@code updateFill}）；</li>
 *   <li><b>🔴 负谓词</b>：整条 SQL **不得**出现 {@code deleted} —— {@code tenant_applications}
 *       <b>没有该列</b>（{@link ProductionMigrationSql#SCHEMA} 现取），照抄 #6928 / #6936 的
 *       三谓词模板会让这条 SQL 直接报错（{@code column "deleted" does not exist}）。
 *       本表「没有软删」这件事<b>不许</b>只活在注释里 —— 这一条是它的机械面。</li>
 * </ol>
 *
 * <p>⚠️ 行为面（并发下恰一个赢家）<b>不在本类</b>：由真库并发判据
 * {@code TenantApplicationReviewCasRaceRealDbTest}（MC-101）承担；本类只保证 SQL 的**形状**。
 * 两者缺一不可（{@code migao-dev-flow} §28.2）。</p>
 */
@DisplayName("TenantApplicationMapper 契约（入驻审批 CAS 的 SQL 形状，issue #6954）")
class TenantApplicationMapperTest {

    /** 本类核验的接线：mapper 的两条 CAS 写面 ⇄ 服务层审批链路的收口点。 */
    private static final String WIRING_UNDER_TEST =
            "backend/admin-api/src/main/java/com/migao/admin/mapper/TenantApplicationMapper.java::int approveIfPending(";

    private static final String TABLE = "tenant_applications";

    /** WHERE 之后的片段（谓词判定的唯一射程；`SET status='x'` 与谓词同形，见 MetaGuard 的同款坑）。 */
    /**
     * WHERE 之后的片段（谓词判定的唯一射程）。
     *
     * <p>⚠️ 不能用「要求 WHERE 前后都有空白」的写法：注解值被拼成一行后是
     * {@code … updated_at = NOW() WHERE id = #{id}} —— {@code WHERE} 前**恰好一个**空格，
     * 脆的写法会静默返回空串 ⇒ 「谓词判据」永远看不到 WHERE ⇒ **恒红或恒绿**。
     * 这里大小写不敏感直查（`\b` 保证不误命中列名里的 `where`）。</p>
     */
    private static final Pattern WHERE_CLAUSE =
            Pattern.compile("WHERE\\b.*$", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
    private static final Pattern PLACEHOLDER = Pattern.compile("#\\{\\s*(\\w+)\\s*\\}");
    /** 非列名的合法赋值左值（SQL 函数名）。 */
    private static final Set<String> NON_COLUMN_LHS = Set.of("now");
    /** 允许出现在这些 SQL 里的参数名（＝必须能在方法签名里逐字找到）。 */
    private static final Set<String> KNOWN_COLUMNS = Set.of(
            "id", "company_name", "contact_name", "phone", "business_license_url", "industry",
            "address", "description", "status", "reject_reason", "reviewed_by", "reviewed_at",
            "company_name_norm", "review_source", "risk_flags", "review_summary",
            "created_at", "updated_at");

    @Test
    @DisplayName("Mapper 继承 BaseMapper（保留既有 CRUD 面）+ 表名契约")
    void mapperExtendsBaseAndEntityMapsTable() {
        assertThat(BaseMapper.class).isAssignableFrom(TenantApplicationMapper.class);
        assertThat(TenantApplication.class.getAnnotation(
                com.baomidou.mybatisplus.annotation.TableName.class).value())
                .as("实体必须映射 tenant_applications 表").isEqualTo(TABLE);
    }

    @Test
    @DisplayName("两条 CAS 方法存在、返回 int（按影响行数判定）、带 @Update")
    void casMethodsExistAndReturnAffectedRows() {
        for (String name : List.of("approveIfPending", "rejectIfPending")) {
            Method m = casMethod(name);
            assertThat(m.getReturnType())
                    .as("%s 必须返回 int —— 影响行数是 CAS 的判定面（0 行 ⇒ 冲突）", name)
                    .isEqualTo(int.class);
            assertThat(m.getAnnotation(Update.class))
                    .as("%s 必须是手写 @Update SQL（CAS 的谓词只存在于 SQL 里）", name)
                    .isNotNull();
        }
    }

    @Test
    @DisplayName("参数名与 SQL 占位符逐字对齐（@Param 是唯一关联面）")
    void paramNamesMatchPlaceholders() {
        for (String name : List.of("approveIfPending", "rejectIfPending")) {
            Method m = casMethod(name);
            Set<String> declared = Arrays.stream(m.getParameters())
                    .map(p -> p.getAnnotation(Param.class))
                    .map(a -> a == null ? null : a.value())
                    .collect(Collectors.toSet());
            assertThat(declared)
                    .as("%s 的每个参数都必须标 @Param（否则 #{…} 关联靠编译期 -parameters，脆弱）", name)
                    .doesNotContainNull();
            assertThat(declared)
                    .as("%s 的参数名必须覆盖 SQL 的全部占位符 %s", name, placeholders(sqlOf(name)))
                    .containsAll(placeholders(sqlOf(name)));
        }
        assertThat(Arrays.stream(casMethod("approveIfPending").getParameters())
                .map(p -> p.getAnnotation(Param.class).value()).toList())
                .as("通过侧必须带上甄别元数据（review_* 三列与状态同一句写入）")
                .containsExactlyInAnyOrder("id", "reviewerId", "reviewedAt", "reviewSource",
                        "riskFlags", "reviewSummary");
        assertThat(Arrays.stream(casMethod("rejectIfPending").getParameters())
                .map(p -> p.getAnnotation(Param.class).value()).toList())
                .as("驳回侧必须带上驳回理由")
                .containsExactlyInAnyOrder("id", "reviewerId", "reason", "reviewedAt",
                        "reviewSource", "riskFlags", "reviewSummary");
    }

    @Test
    @DisplayName("SET 侧直接写终态字面量（不依赖调用方传状态字符串）")
    void setClauseWritesTerminalStatusLiterals() {
        assertThat(sqlOf("approveIfPending"))
                .as("通过侧的状态必须硬写 'approved'（传参写状态 ⇒ 传错就写错且 SQL 层看不出来）")
                .contains("status = 'approved'");
        assertThat(sqlOf("rejectIfPending"))
                .as("驳回侧的状态必须硬写 'rejected'").contains("status = 'rejected'");
        assertThat(sqlOf("approveIfPending"))
                .as("通过时 reject_reason 必须显式清空（同一张单被驳回后重审通过的语义）")
                .containsIgnoringCase("reject_reason = NULL");
        assertThat(sqlOf("rejectIfPending"))
                .as("驳回侧必须写 reject_reason（与状态同句）")
                .containsIgnoringCase("reject_reason = #{reason}");
    }

    @Test
    @DisplayName("🔴 CAS 谓词：WHERE 段必须含 #{id} + status = 'pending'")
    void whereClauseCarriesTheCasPredicate() {
        for (String name : List.of("approveIfPending", "rejectIfPending")) {
            String where = whereOf(sqlOf(name));
            assertThat(where)
                    .as("%s 的 WHERE 段必须含 #{id}（主键谓词）", name)
                    .contains("#{id}");
            assertThat(where)
                    .as("🔴 %s 的 WHERE 段必须含 status = 'pending' —— 少了它并发下两个请求都能过"
                            + "（issue #6954 的形态：建出两个租户）", name)
                    .contains("status = 'pending'");
        }
    }

    @Test
    @DisplayName("审计列与状态同一句写入（reviewed_at + updated_at = NOW()）")
    void auditColumnsWrittenInTheSameStatement() {
        for (String name : List.of("approveIfPending", "rejectIfPending")) {
            String sql = sqlOf(name);
            assertThat(sql)
                    .as("%s 必须写 reviewed_at（「谁在何时审结」不能与状态迁移分两次写）", name)
                    .contains("reviewed_at = #{reviewedAt}");
            assertThat(sql)
                    .as("%s 必须显式写 updated_at = NOW()（手写 SQL 不经 updateFill）", name)
                    .containsIgnoringCase("updated_at = NOW()");
        }
    }

    @Test
    @DisplayName("🔴 负谓词：SQL 与表定义都不得出现 deleted 列（本表没有软删语义）")
    void noDeletedColumnAnywhere() {
        for (String name : List.of("approveIfPending", "rejectIfPending")) {
            assertThat(sqlOf(name))
                    .as("🔴 %s 不得出现 deleted —— tenant_applications 没有该列，"
                            + "照抄 #6928/#6936 的三谓词模板会让这条 SQL 直接报错"
                            + "（column \"deleted\" does not exist）", name)
                    .doesNotContainIgnoringCase("deleted");
        }
        // 真值源：schema.sql 现取 —— 「本表没有 deleted」不许只活在注释里。
        // ⚠️ 不用 ProductionMigrationSql.assertTableColumns：它硬编码迁移 V49（两源口径），
        //    而 tenant_applications 不在 V49 里 ⇒ 会以「V49 缺表」误红（实测踩过）。
        String schemaBody = schemaBody();
        assertThat(schemaBody)
                .as("必须能现取到 tenant_applications 的 CREATE TABLE 体（取不到 = 判据失明）")
                .isNotNull();
        assertThat(schemaBody)
                .as("tenant_applications 的 CREATE TABLE 体不得出现 deleted（本表的谓词口径由此确定）")
                .doesNotContainIgnoringCase("deleted");
        for (String column : List.of("id", "company_name", "contact_name", "phone", "status",
                "reject_reason", "reviewed_by", "reviewed_at", "created_at", "updated_at")) {
            assertThat(hasColumn(schemaBody, column))
                    .as("tenant_applications 必须真的有列 %s（本判据用到的列一个都不能少）", column)
                    .isTrue();
        }
    }

    @Test
    @DisplayName("SQL 里出现的列名都在表定义里（写错列名 = 运行期才炸）")
    void everyColumnInSqlExistsInSchema() {
        String schemaBody = schemaBody();
        assertThat(schemaBody).as("取不到表体 = 判据失明").isNotNull();
        Set<String> declared = new java.util.LinkedHashSet<>(declaredColumns());
        assertThat(declared)
                .as("必须现取到 tenant_applications 的列集（CREATE TABLE 体 ∪ 后续 ADD COLUMN）——空集 = 判据失明")
                .isNotEmpty();

        for (String name : List.of("approveIfPending", "rejectIfPending")) {
            List<String> cols = sqlColumns(sqlOf(name));
            assertThat(cols).as("%s 的解析结果不能为空（空集 = 判据失明）", name).isNotEmpty();
            List<String> unknown = cols.stream().filter(c -> !KNOWN_COLUMNS.contains(c)).toList();
            assertThat(unknown)
                    .as("%s 的 SQL 里出现了不在申明列集里的列名（写错列名 = 运行期才炸）", name)
                    .isEmpty();
            List<String> notInSchema = cols.stream().filter(c -> !declared.contains(c)).toList();
            assertThat(notInSchema)
                    .as("%s 的 SQL 用到的列必须都在 tenant_applications 的 DDL 里真存在"
                            + "（CREATE TABLE 体 ∪ 后续 ALTER TABLE … ADD COLUMN）", name)
                    .isEmpty();
        }
    }

    // ────────────────────────────────────────────── DDL 解析（复用包内共用件）

    /** {@code tenant_applications} 的 CREATE TABLE 体（现取 schema.sql；表不存在 ⇒ null）。 */
    private static String schemaBody() {
        return ProductionMigrationSql.tableBody(
                ProductionMigrationSql.read(ProductionMigrationSql.SCHEMA), TABLE);
    }

    /**
     * 现取 {@code tenant_applications} 的**全部列** —— CREATE TABLE 体 ∪ 后续
     * {@code ALTER TABLE tenant_applications ADD COLUMN [IF NOT EXISTS] <col>} 段。
     *
     * <p>为什么必须并上 ADD COLUMN 段：{@code review_source} / {@code risk_flags} /
     * {@code review_summary} 是 V18 之后**追加**的列（schema.sql 的 ALTER 段），不在 CREATE TABLE 体里
     * ⇒ 只看表体会把「真实存在的列」误判成「写错列名」（本判据第一版实测踩到，报出这三个）。</p>
     */
    private static List<String> declaredColumns() {
        String schema = ProductionMigrationSql.read(ProductionMigrationSql.SCHEMA);
        Set<String> cols = new java.util.LinkedHashSet<>();
        Matcher inBody = Pattern.compile("(?m)^\\s{4}([a-z_]+)\\s+[a-zA-Z]")
                .matcher(schemaBody() == null ? "" : schemaBody());
        while (inBody.find()) {
            cols.add(inBody.group(1));
        }
        Matcher added = Pattern.compile(
                        "(?i)ALTER\\s+TABLE\\s+" + Pattern.quote(TABLE)
                                + "\\s+ADD\\s+COLUMN\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?([a-z_]+)")
                .matcher(schema);
        while (added.find()) {
            cols.add(added.group(1).toLowerCase());
        }
        return List.copyOf(cols);
    }

    /**
     * 表体里是否有这一列 —— 口径与 {@code ProductionMigrationSql.assertTableColumnsIn} **逐字相同**
     * （行首列名 + 至少一段空白 + 一个词），避免两处判定漂移。
     */
    private static boolean hasColumn(String tableBody, String column) {
        return Pattern.compile("(?m)^\\s*" + Pattern.quote(column) + "\\s+\\w").matcher(tableBody).find();
    }

    // ────────────────────────────────────────────── 反射 / SQL 解析

    private static Method casMethod(String name) {
        return Arrays.stream(TenantApplicationMapper.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("TenantApplicationMapper 缺少方法 " + name
                        + "（＝审批权的 CAS 闸被摘掉了；接线声明 = " + WIRING_UNDER_TEST + "）"));
    }

    /** 取 {@code @Update} 的值并还原成一行 SQL（多个字符串字面量 `+` 拼接）。 */
    private static String sqlOf(String methodName) {
        Update update = casMethod(methodName).getAnnotation(Update.class);
        assertThat(update).as("%s 必须有 @Update", methodName).isNotNull();
        return String.join(" ", update.value()).replaceAll("\\s+", " ").trim();
    }

    private static Set<String> placeholders(String sql) {
        Matcher m = PLACEHOLDER.matcher(sql);
        Set<String> out = new java.util.LinkedHashSet<>();
        while (m.find()) {
            out.add(m.group(1));
        }
        return out;
    }

    private static String whereOf(String sql) {
        Matcher m = WHERE_CLAUSE.matcher(sql);
        return m.find() ? m.group() : "";
    }

    /**
     * SQL 里出现的列名（SET 与 WHERE 两侧；排除占位符、SQL 关键字与函数名）。
     *
     * <p>口径说明：只认 {@code <标识符> =} 形态，并排除 {@code #{…}}（先把占位符换成 {@code ?}）
     * 与 {@code SET}/{@code WHERE} 两个关键字 —— {@code updated_at} 这类列名会同时出现在
     * {@code updated_at = #{reviewedAt}} 与 {@code updated_at = NOW()} 两处，去重后只报一次。</p>
     */
    private static List<String> sqlColumns(String sql) {
        String stripped = PLACEHOLDER.matcher(sql).replaceAll("?").replaceAll("(?i)\\bWHERE\\b", " ");
        Set<String> out = new java.util.LinkedHashSet<>();
        Matcher m = Pattern.compile("\\b([a-z_]{3,})\\s*=").matcher(stripped);
        while (m.find()) {
            String candidate = m.group(1).toLowerCase();
            if (!NON_COLUMN_LHS.contains(candidate)) {
                out.add(candidate);
            }
        }
        return List.copyOf(out);
    }

    @Test
    @DisplayName("接线声明指向真对象（WIRING_UNDER_TEST 的锚在 mapper 里逐字存在）")
    void wiringAnchorIsLive() {
        int sep = WIRING_UNDER_TEST.indexOf("::");
        assertThat(sep).as("接线声明形态必须是 <仓库相对路径>::<可检索文本>").isGreaterThan(0);
        assertThat(WIRING_UNDER_TEST.substring(sep + 2))
                .as("接线锚必须能在 mapper 源码里逐字找到（摘掉 approveIfPending ⇒ 本条与 casMethodsExistAndReturnAffectedRows 同时红）")
                .isEqualTo("int approveIfPending(");
        boolean found = Arrays.stream(TenantApplicationMapper.class.getDeclaredMethods())
                .anyMatch(m -> m.getName().equals("approveIfPending")
                        && m.getReturnType() == int.class);
        assertThat(found).as("approveIfPending 的签名必须与接线声明一致（int 返回）").isTrue();
    }

    /** 参数名（读数辅助；`Parameter` 仅在带 `@Param` 时有稳定名字）。 */
    @SuppressWarnings("unused")
    private static List<String> paramNames(String methodName) {
        return Arrays.stream(casMethod(methodName).getParameters())
                .map(Parameter::getName)
                .toList();
    }
}
