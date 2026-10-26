// case_ids: PG-018, PG-046
package com.migao.admin.mapper;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 类级守卫（issue #7874）：mapper 注解 SQL 里 **`CONCAT(` 的参数必须显式 `CAST(… AS text)`**。
 *
 * <h2>为什么这条形态会炸（2026-10-26 生产事故）</h2>
 * 生产连接串带 {@code stringtype=unspecified}（{@code application.yml}）⇒ 字符串参数以
 * <b>UNSPECIFIED</b> 类型下发；PostgreSQL 的 {@code CONCAT} 是 {@code VARIADIC "any"}
 * ⇒ 解析期无法推断参数类型 ⇒ {@code ERROR: could not determine data type of parameter $N}
 * ⇒ 整条请求 500。**与传什么值无关**（哪怕关键词是常量），所以任何一个命中都不该被当成
 * 「偶发」。反例见 {@code ProductionWorkLogMapper#countPackerLogs}（#7847 把它放进了扫码主路径，
 * 工人端「扫码即报工」100% 不可用）。
 *
 * <h2>为什么判据取「注解值」而不是「源码文本」</h2>
 * 取 {@code @Select}/{@code @Update}/… 的**实际 SQL 值**：① 那就是运行时真正执行的串；
 * ② 注释 / javadoc 里**提及**这条形态（本类与 mapper 的说明里就有）不会被喂成假红 ——
 * 同族教训见 `tests/unit_ci_workflows/test_lpapi_open_printer_contract.py` 的反向对照。
 *
 * <h2>射程与边界（照实登记，§19.1）</h2>
 * <ul>
 *   <li>射程 = {@code com.migao.admin.mapper} 下全部 {@code *Mapper} 接口的注解 SQL
 *       （本仓没有 XML mapper；{@code ${}} 拼接与 QueryWrapper 不在其中）；</li>
 *   <li>{@code LIKE '%' || #{kw} || '%'} 形态**不在本守卫内**：PostgreSQL 对 {@code unknown || unknown}
 *       会按字符串类别解析成 {@code text || text}（本机真库验证；{@code InboundOrderQueryMapper} 等已在生产长期使用）—— 判不了的不硬造判据；</li>
 *   <li>不判「cast 成什么类型对不对」（那是语义，不是形态），只判**有没有显式 cast**。</li>
 * </ul>
 */
@DisplayName("类级守卫 #7874：CONCAT 里的 #{…} 参数必须显式 CAST（PostgreSQL 无法推断类型）")
class MapperConcatParamTypeGuardTest {

    /** 反空跑锚点：扫不到足够多的 mapper / SQL ⇒ 判红（防「扫了个空目录 = 全绿」）。 */
    private static final int MIN_MAPPERS = 50;
    private static final int MIN_SQL_STATEMENTS = 20;

    @Test
    @DisplayName("全部 mapper 注解 SQL：CONCAT( 里不得出现**未 CAST**的 #{…} 参数")
    void noUntypedParameterInsideConcat() {
        List<Class<?>> mappers = mapperTypes();
        assertThat(mappers)
                .as("必须真的扫到 mapper 接口（反空跑：源码目录搬走/解析失效时不得静默变绿）")
                .hasSizeGreaterThanOrEqualTo(MIN_MAPPERS);

        List<String> statements = new ArrayList<>();
        List<String> violations = new ArrayList<>();
        for (Class<?> mapper : mappers) {
            for (String sql : annotatedSql(mapper)) {
                statements.add(sql);
                for (String offending : untypedConcatParams(sql)) {
                    violations.add(mapper.getSimpleName() + " → " + offending);
                }
            }
        }

        assertThat(statements)
                .as("必须真的读到注解 SQL（反空跑锚点）")
                .hasSizeGreaterThanOrEqualTo(MIN_SQL_STATEMENTS);

        assertThat(violations)
                .as("以下 SQL 把参数直接塞进 CONCAT：PostgreSQL + stringtype=unspecified 下解析期必炸"
                        + "（could not determine data type of parameter $N）；修法 = 显式 CAST(#{param} AS text)"
                        + "，判据 = ProductionWorkLogMapperRealDbTest（真库）")
                .isEmpty();
    }

    @Test
    @DisplayName("判别力自证：未 CAST 的形态判红、已 CAST 的形态放行、纯字面量 CONCAT 不误报")
    void ruleHasDiscriminatingPower() {
        assertThat(untypedConcatParams(
                "SELECT COUNT(1) FROM t WHERE name ILIKE CONCAT('%', #{keyword}, '%')"))
                .as("事故形态（#7874 改前）必须判红")
                .hasSize(1);
        assertThat(untypedConcatParams(
                "SELECT COUNT(1) FROM t WHERE name ILIKE CONCAT('%', CAST(#{keyword} AS text), '%')"))
                .as("修后形态必须放行")
                .isEmpty();
        assertThat(untypedConcatParams("SELECT CONCAT(a, '-', b) FROM t"))
                .as("没有参数 ⇒ 不误报")
                .isEmpty();
        assertThat(untypedConcatParams(
                "SELECT CONCAT(CAST(#{a} AS text), CAST(#{b} AS text)) FROM t"))
                .as("多个参数全部 CAST ⇒ 放行")
                .isEmpty();
        assertThat(untypedConcatParams(
                "SELECT CONCAT(CAST(#{a} AS text), #{b}) FROM t"))
                .as("只 CAST 一个 ⇒ 另一个仍然判红（不得只看第一个）")
                .hasSize(1);
    }

    // ── 规则 ────────────────────────────────────────────────────────────────

    /**
     * 找出 SQL 里每一个 {@code CONCAT(…)} 生效域中**未被 {@code CAST(… AS text)} 包裹**的 {@code #{…}} 参数。
     *
     * @return 违规片段（整段 {@code CONCAT(…)}）；空 = 合规
     */
    static List<String> untypedConcatParams(String sql) {
        List<String> violations = new ArrayList<>();
        int cursor = 0;
        while (true) {
            int start = sql.indexOf("CONCAT(", cursor);
            if (start < 0) {
                return violations;
            }
            int argsStart = start + "CONCAT(".length();
            int depth = 1;
            int i = argsStart;
            while (i < sql.length() && depth > 0) {
                char c = sql.charAt(i++);
                if (c == '(') {
                    depth++;
                } else if (c == ')') {
                    depth--;
                }
            }
            // 括号不配对的串（拼接中的半截 SQL）也照原文判定，不静默跳过
            int end = depth == 0 ? i : sql.length();
            String call = sql.substring(start, end);
            String withoutCasts = call.replaceAll(
                    "(?i)CAST\\(\\s*#\\{[^}]*}\\s+AS\\s+text\\s*\\)", "");
            if (withoutCasts.contains("#{")) {
                violations.add(call);
            }
            cursor = end;
        }
    }

    // ── 取数 ────────────────────────────────────────────────────────────────

    /** `com.migao.admin.mapper` 下全部 mapper 接口（真类，取注解值用）。 */
    private static List<Class<?>> mapperTypes() {
        Path dir = mapperSourceDir();
        List<Class<?>> types = new ArrayList<>();
        try (Stream<Path> files = Files.list(dir)) {
            for (Path file : files.filter(p -> p.getFileName().toString().endsWith("Mapper.java")).toList()) {
                String source = Files.readString(file);
                String simpleName = file.getFileName().toString().replace(".java", "");
                if (!source.contains("interface " + simpleName)) {
                    continue;
                }
                types.add(Class.forName("com.migao.admin.mapper." + simpleName));
            }
        } catch (Exception e) {
            throw new AssertionError("扫描 mapper 源码失败（" + dir + "）：" + e.getMessage(), e);
        }
        return types;
    }

    /** 源码目录：从工作目录往上找（`mvnw test` 的 cwd = 模块目录；IDE 里可能更靠上）。 */
    private static Path mapperSourceDir() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        Path relative = Paths.get("src/main/java/com/migao/admin/mapper");
        while (root != null) {
            if (Files.isDirectory(root.resolve(relative))) {
                return root.resolve(relative);
            }
            if (Files.isDirectory(root.resolve("backend/admin-api").resolve(relative))) {
                return root.resolve("backend/admin-api").resolve(relative);
            }
            root = root.getParent();
        }
        throw new AssertionError("定位不到 mapper 源码目录（src/main/java/com/migao/admin/mapper）");
    }

    /** 一个 mapper 接口上全部注解 SQL（{@code @Select} / {@code @Update} / {@code @Delete} / {@code @Insert}）。 */
    private static List<String> annotatedSql(Class<?> mapperType) {
        List<String> sql = new ArrayList<>();
        for (Method method : mapperType.getDeclaredMethods()) {
            for (Annotation annotation : method.getAnnotations()) {
                if (annotation instanceof Select select) {
                    sql.addAll(List.of(select.value()));
                } else if (annotation instanceof Update update) {
                    sql.addAll(List.of(update.value()));
                } else if (annotation instanceof Delete delete) {
                    sql.addAll(List.of(delete.value()));
                } else if (annotation instanceof Insert insert) {
                    sql.addAll(List.of(insert.value()));
                }
            }
        }
        return sql;
    }
}
