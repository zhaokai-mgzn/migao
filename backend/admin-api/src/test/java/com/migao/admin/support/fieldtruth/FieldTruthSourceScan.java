package com.migao.admin.support.fieldtruth;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.SortedMap;
import java.util.SortedSet;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * 「字段真值」判据的<b>静态扫描唯一实现</b>（issue #5362）—— 实例判据与类级元守卫共用本类，
 * <b>禁止另写第二份</b>（第二份必然漂移，§17.3）。
 *
 * <p>三类输入：
 * <ol>
 *   <li><b>源码写入点</b>：setter（只认实体类型的变量）/ builder 链 / SQL {@code UPDATE … SET}
 *       （{@code @Update} 注解与 XML mapper）/ 框架生成（{@code @TableId}、{@code @TableField(fill=…)}、
 *       {@code @TableLogic}、{@code @Version}）；实参是常量（{@code 0} / {@code BigDecimal.ZERO} /
 *       {@code "new"} / {@code null}）的写法记为 {@link Kind#CONSTANT} —— 占位值不证明「有人算过」；</li>
 *   <li><b>schema 列默认值</b>：{@code db/init/schema.sql} 里该列的 {@code DEFAULT} 是否是<b>常量</b>
 *       （{@code DEFAULT NOW()} / {@code CURRENT_TIMESTAMP} 这类由数据库算出真值的默认值不算）；</li>
 *   <li><b>病征</b>：{@code 列有常量默认值} ∧ {@code 源码没有任何真值级写入点}
 *       —— 这正是「schema 在、实体在、读面在，唯独没有计算逻辑，于是 0/30 被当成真值」的形态。</li>
 * </ol>
 *
 * <p>实体/表名/源码根都是参数（不是常量）⇒ 判据对**任意一张表**都成立，
 * 元守卫的夹具注入（临时 Java 树 + 第二张表）行使的就是本类的生产代码路径。
 */
final class FieldTruthSourceScan {

    enum Kind {
        /** 框架生成（{@code @TableId} / {@code @TableField(fill=…)} / {@code @TableLogic} / {@code @Version}）。 */
        FRAMEWORK,
        /** 真值级：值来自数据 / 请求 / 时间。 */
        DERIVED,
        /** 常量占位 / 建档种子（{@code 0}、{@code BigDecimal.ZERO}、{@code "new"}）。 */
        CONSTANT
    }

    record WriteSite(String file, int line, Kind kind, String text) {
        @Override
        public String toString() {
            return file + " 行 " + line + " [" + kind + "] " + text;
        }
    }

    static final Path REPO_ROOT = repoRoot();
    static final Path JAVA_MAIN = REPO_ROOT.resolve("backend/admin-api/src/main/java");
    static final Path RESOURCES_MAIN = REPO_ROOT.resolve("backend/admin-api/src/main/resources");
    static final Path SCHEMA = RESOURCES_MAIN.resolve("db/init/schema.sql");
    static final Path ENTITY_DIR = JAVA_MAIN.resolve("com/migao/admin/entity");
    /** 遮蔽清单的命名约定：实体 {@code X} 的遮蔽类 = {@code XTruthMask}（同包）。 */
    static final Path SUPPORT_DIR = JAVA_MAIN.resolve("com/migao/admin/support/fieldtruth");

    private static final Pattern SETTER = Pattern.compile("(\\w+)\\.set([A-Z]\\w*)\\s*\\(");
    private static final Pattern BUILDER_CALL = Pattern.compile("\\.(\\w+)\\s*\\(");
    private static final Pattern ANNOTATED_FIELD = Pattern.compile(
            "((?:@[\\w.]+(?:\\s*\\([^)]*\\))?\\s*)+)private\\s+(?!static)(?!final)[\\w.<>,\\[\\]]+\\s+(\\w+)\\s*(?:=[^;]*)?;");
    private static final Pattern TABLE_NAME = Pattern.compile("@TableName\\(\\s*(?:value\\s*=\\s*)??\"(\\w+)\"");
    private static final Pattern MASK_CALL = Pattern.compile("\\w+\\.set([A-Z]\\w*)\\s*\\(\\s*null\\s*\\)");
    private static final Pattern CONSTANT_ARG = Pattern.compile(
            "-?\\d+(\\.\\d+)?[LlFfDd]?|\"[^\"]*\"|null|true|false|BigDecimal\\.(ZERO|ONE|TEN)");
    private static final Pattern DB_COMPUTED_DEFAULT = Pattern.compile(
            "(?i)default\\s+(now\\s*\\(\\s*\\)|current_timestamp\\w*|gen_random_uuid\\s*\\(\\s*\\))");

    private static final Map<Path, String> SOURCE_CACHE = new HashMap<>();
    private static List<Path> javaFiles;
    private static List<Path> xmlFiles;

    private FieldTruthSourceScan() {
    }

    // ==================== 判据本体 ====================

    /**
     * 三方一致性判据：声明 ↔ 源码写入点 ↔ 遮蔽清单。返回违规描述（空 = 通过）。
     *
     * @param decl         字段级声明（实体来自 {@code decl.entity()}，反射校验完整性）
     * @param sites        该实体各字段的写入点（{@link #writeSites}）
     * @param maskedFields 读面遮蔽清单（{@link #maskedFields}）
     */
    static List<String> violations(FieldTruth.Declaration decl,
                                   Map<String, List<WriteSite>> sites,
                                   Set<String> maskedFields) {
        List<String> out = new ArrayList<>();
        Set<String> declared = decl.declaredFields();
        for (Field field : decl.entity().getDeclaredFields()) {
            if (field.isSynthetic() || Modifier.isStatic(field.getModifiers())) {
                continue;
            }
            if (!declared.contains(field.getName())) {
                out.add("未声明字段 " + field.getName()
                        + "：实体新增字段必须登记「有真值/无真值 + 原因」—— 漏登记正是本单要消灭的「无声明」");
            }
        }
        for (String field : declared) {
            List<WriteSite> all = sites.getOrDefault(field, List.of());
            List<WriteSite> truthGrade = all.stream().filter(s -> s.kind() != Kind.CONSTANT).toList();
            List<WriteSite> derived = all.stream().filter(s -> s.kind() == Kind.DERIVED).toList();
            if (decl.truthOf(field) == FieldTruth.HAS_TRUTH) {
                if (truthGrade.isEmpty()) {
                    out.add(field + " 声明「有真值」，但源码里没有真值级写入点（只找到常量占位或零写入）："
                            + describe(all));
                }
                if (maskedFields.contains(field)) {
                    out.add(field + " 声明「有真值」却被遮蔽类置 null —— 真值被抹成未知");
                }
            } else {
                if (!derived.isEmpty()) {
                    out.add(field + " 声明「无真值」，但源码里存在真值级写入点：" + describe(derived));
                }
                if (!maskedFields.contains(field)) {
                    out.add(field + " 声明「无真值」但未在读面遮蔽（遮蔽类里缺 `set"
                            + Character.toUpperCase(field.charAt(0)) + field.substring(1)
                            + "(null)`）⇒ 会以真值形态暴露（DB 列默认值 / 建档种子常量被当成真数据）");
                }
            }
        }
        return out;
    }

    private static String describe(List<WriteSite> sites) {
        return sites.isEmpty() ? "（零写入点）"
                : sites.stream().map(WriteSite::toString).collect(Collectors.joining("; "));
    }

    // ==================== ① 源码写入点 ====================

    /** 该实体各字段的写入点（键 = Java 属性名）。 */
    static Map<String, List<WriteSite>> writeSites(Class<?> entity, String table) {
        return writeSites(entity, table, JAVA_MAIN, RESOURCES_MAIN);
    }

    static Map<String, List<WriteSite>> writeSites(Class<?> entity, String table,
                                                   Path javaRoot, Path resourcesRoot) {
        String simple = entity.getSimpleName();
        Set<String> fields = entityFields(entity);
        Pattern typeBinding = Pattern.compile("\\b" + Pattern.quote(simple) + "\\s+(\\w+)\\s*[=;,:)]");
        Pattern builder = Pattern.compile(Pattern.quote(simple) + "\\s*\\.\\s*builder\\s*\\(\\s*\\)");
        Pattern sqlUpdate = Pattern.compile("(?i)\\bupdate\\s+" + Pattern.quote(table) + "\\s+set\\s+([^\"]*)");
        Map<String, List<WriteSite>> sites = new HashMap<>();

        for (Path path : javaSources(javaRoot)) {
            String raw = source(path);
            if (!raw.contains(simple)) {
                continue;
            }
            String src = stripComments(raw);
            String file = REPO_ROOT.relativize(path).toString();
            Set<String> vars = new LinkedHashSet<>();
            Matcher binding = typeBinding.matcher(src);
            while (binding.find()) {
                vars.add(binding.group(1));
            }
            if (!vars.isEmpty()) {
                Matcher setter = SETTER.matcher(src);
                while (setter.find()) {
                    if (!vars.contains(setter.group(1))) {
                        continue;
                    }
                    String property = decap(setter.group(2));
                    if (fields.contains(property)) {
                        add(sites, property, new WriteSite(file, lineOf(src, setter.start()),
                                kindOf(argAt(src, setter.end() - 1)), setter.group()));
                    }
                }
            }
            Matcher builderHit = builder.matcher(src);
            while (builderHit.find()) {
                int build = src.indexOf(".build()", builderHit.end());
                String chain = src.substring(builderHit.start(),
                        build > 0 ? build : Math.min(src.length(), builderHit.start() + 4000));
                Matcher call = BUILDER_CALL.matcher(chain);
                while (call.find()) {
                    if (fields.contains(call.group(1))) {
                        add(sites, call.group(1), new WriteSite(file, lineOf(src, builderHit.start()),
                                kindOf(argAt(chain, call.end() - 1)), "." + call.group(1)));
                    }
                }
            }
            Matcher sql = sqlUpdate.matcher(src);
            while (sql.find()) {
                for (String property : propertiesFromSetClause(sql.group(1))) {
                    if (fields.contains(property)) {
                        add(sites, property, new WriteSite(file, lineOf(src, sql.start()),
                                Kind.DERIVED, "SQL UPDATE … SET（@Update / 字符串）"));
                    }
                }
            }
        }

        // XML mapper：当前实体无 XML 写法，但解析器保留 —— 将来改用 XML 时不会被误判成「零写入」（假红）
        for (Path path : xmlSources(resourcesRoot)) {
            String src = source(path);
            Matcher sql = sqlUpdate.matcher(src);
            while (sql.find()) {
                for (String property : propertiesFromSetClause(sql.group(1))) {
                    if (fields.contains(property)) {
                        add(sites, property, new WriteSite(REPO_ROOT.relativize(path).toString(),
                                lineOf(src, sql.start()), Kind.DERIVED, "XML mapper UPDATE … SET"));
                    }
                }
            }
        }

        frameworkWriteSites(simple, javaRoot).forEach((field, list) -> list.forEach(s -> add(sites, field, s)));
        return sites;
    }

    /** 框架生成写入点：实体注解即可判定（{@code @TableId} / {@code @TableField(fill=…)} / {@code @TableLogic} / {@code @Version}）。 */
    static Map<String, List<WriteSite>> frameworkWriteSites(String entitySimpleName, Path javaRoot) {
        Map<String, List<WriteSite>> sites = new HashMap<>();
        Path entity = findSource(entitySimpleName + ".java", javaRoot);
        if (entity == null) {
            return sites;
        }
        String src = stripComments(source(entity));
        Matcher matcher = ANNOTATED_FIELD.matcher(src);
        while (matcher.find()) {
            String annotations = matcher.group(1);
            boolean frameworkWritten = annotations.contains("@TableId")
                    || (annotations.contains("@TableField") && annotations.contains("FieldFill."))
                    || annotations.contains("@TableLogic")
                    || annotations.contains("@Version");
            if (frameworkWritten) {
                add(sites, matcher.group(2), new WriteSite(REPO_ROOT.relativize(entity).toString(),
                        lineOf(src, matcher.start()), Kind.FRAMEWORK, annotations.trim()));
            }
        }
        return sites;
    }

    // ==================== ② schema 列默认值 / ③ 病征 ====================

    /** 列的 schema 事实：类型 + DEFAULT 子句（{@code null} = 无默认值）。 */
    record ColumnDef(String type, String defaultClause) {
        /** 常量默认值：{@code DEFAULT NOW()} / {@code CURRENT_TIMESTAMP} 这类由数据库算出真值的不算。 */
        boolean constantDefault() {
            return defaultClause != null && !DB_COMPUTED_DEFAULT.matcher(defaultClause).find();
        }

        /**
         * 数值列 —— {@code 0} / {@code 0.00} 这类常量默认值最容易被读成「量值为零」（「消费 0 元」）。
         *
         * <p>文本列（{@code VARCHAR DEFAULT 'active'} / {@code 'manual'}）是**枚举/配置种子**，
         * 与「用一个 0 冒充测出来的量值」不是同一类，故不入病征（避免造出错误真相模型）。
         */
        boolean numeric() {
            String upper = type == null ? "" : type.toUpperCase();
            return upper.startsWith("INTEGER") || upper.startsWith("BIGINT") || upper.startsWith("SMALLINT")
                    || upper.startsWith("NUMERIC") || upper.startsWith("DECIMAL")
                    || upper.startsWith("REAL") || upper.startsWith("DOUBLE");
        }
    }

    static Map<String, ColumnDef> columnDefs(String table) {
        return columnDefs(table, SCHEMA);
    }

    /** 表 → 列 → {@link ColumnDef}（表不存在 ⇒ 空表，调用方须显式处理「解析不到」）。 */
    static Map<String, ColumnDef> columnDefs(String table, Path schema) {
        String text = source(schema);
        Matcher matcher = Pattern.compile(
                "(?is)create\\s+table\\s+(?:if\\s+not\\s+exists\\s+)?" + Pattern.quote(table) + "\\s*\\(")
                .matcher(text);
        if (!matcher.find()) {
            return Map.of();
        }
        int depth = 0;
        int end = -1;
        for (int i = matcher.end() - 1; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '(') {
                depth++;
            } else if (c == ')') {
                depth--;
                if (depth == 0) {
                    end = i;
                    break;
                }
            }
        }
        Map<String, ColumnDef> defs = new LinkedHashMap<>();
        for (String line : text.substring(matcher.end(), end > 0 ? end : text.length()).split("\n")) {
            String body = line.split("--")[0].trim();
            if (body.endsWith(",")) {
                body = body.substring(0, body.length() - 1).trim();
            }
            Matcher name = Pattern.compile("^(\\w+)\\s+[A-Za-z]").matcher(body);
            if (!name.find() || Set.of("primary", "unique", "constraint", "foreign", "check")
                    .contains(name.group(1).toLowerCase())) {
                continue;
            }
            String type = "";
            String[] tokens = body.split("\\s+");
            for (int i = 1; i < tokens.length; i++) {
                if (Set.of("DEFAULT", "NOT", "NULL", "PRIMARY", "UNIQUE", "REFERENCES",
                        "CHECK", "CONSTRAINT", "GENERATED").contains(tokens[i].toUpperCase())) {
                    break;
                }
                type = type.isEmpty() ? tokens[i] : type + " " + tokens[i];
            }
            Matcher clause = Pattern.compile("(?i)\\bdefault\\s+(.+)$").matcher(body);
            defs.put(name.group(1).toLowerCase(),
                    new ColumnDef(type, clause.find() ? clause.group(1).trim() : null));
        }
        return defs;
    }

    /**
     * 病征：列有<b>常量</b>默认值 ∧ 源码没有任何真值级写入点 ∧ 未被任何声明覆盖（{@code covered}）。
     *
     * <p>返回 {@code "table.field"} 集合 —— 元守卫的存量台账按它逐条对账（涨跌都红）。
     */
    static SortedSet<String> diseaseShape(Class<?> entity, String table, Set<String> coveredFields,
                                          Path javaRoot, Path resourcesRoot, Path schema) {
        Map<String, ColumnDef> defs = columnDefs(table, schema);
        Map<String, List<WriteSite>> sites = writeSites(entity, table, javaRoot, resourcesRoot);
        SortedSet<String> out = new TreeSet<>();
        for (String field : entityFields(entity)) {
            ColumnDef def = defs.get(snake(field));
            if (coveredFields.contains(field) || def == null || !def.constantDefault() || !def.numeric()) {
                continue;
            }
            boolean truthGrade = sites.getOrDefault(field, List.of()).stream()
                    .anyMatch(site -> site.kind() != Kind.CONSTANT);
            if (!truthGrade) {
                out.add(table + "." + field);
            }
        }
        return out;
    }

    /** 仓库内全部 {@code @TableName} 实体：{@code table → FQN}（表名缺省 = 类名蛇形）。 */
    static SortedMap<String, String> entitiesByTable() {
        SortedMap<String, String> out = new TreeMap<>();
        for (Path path : javaSources(ENTITY_DIR)) {
            String raw = source(path);
            if (!raw.contains("@TableName") && !raw.contains("@TableId")) {
                continue;
            }
            String simple = path.getFileName().toString().replace(".java", "");
            Matcher declared = TABLE_NAME.matcher(raw);
            String table = declared.find() ? declared.group(1) : snake(simple);
            out.put(table, "com.migao.admin.entity." + simple);
        }
        return out;
    }

    static Class<?> entityClass(String fqn) {
        try {
            return Class.forName(fqn);
        } catch (ClassNotFoundException e) {
            throw new IllegalStateException("实体类加载失败（台账/声明已漂移）：" + fqn, e);
        }
    }

    static Set<String> entityFields(Class<?> entity) {
        Set<String> fields = new TreeSet<>();
        for (Field field : entity.getDeclaredFields()) {
            if (!field.isSynthetic() && !Modifier.isStatic(field.getModifiers())) {
                fields.add(field.getName());
            }
        }
        return fields;
    }

    // ==================== 遮蔽清单 ====================

    /** 遮蔽清单 = 遮蔽类里的显式 {@code setXxx(null)} 行（源码文本，独立于声明）。 */
    static Set<String> maskedFields(String entitySimpleName) {
        return maskedFields(SUPPORT_DIR.resolve(entitySimpleName + "TruthMask.java"));
    }

    static Set<String> maskedFields(Path maskFile) {
        if (!Files.isRegularFile(maskFile)) {
            // 未实装 ⇒ 空集：判据会把每个「无真值」字段判红（响亮，不静默放行）
            return Set.of();
        }
        Set<String> masked = new TreeSet<>();
        Matcher matcher = MASK_CALL.matcher(stripComments(source(maskFile)));
        while (matcher.find()) {
            masked.add(decap(matcher.group(1)));
        }
        return masked;
    }

    // ==================== 解析小工具 ====================

    static Set<String> propertiesFromSetClause(String clause) {
        String body = clause;
        int where = body.toLowerCase().indexOf(" where ");
        if (where >= 0) {
            body = body.substring(0, where);
        }
        Set<String> properties = new LinkedHashSet<>();
        for (String assignment : body.split(",")) {
            int eq = assignment.indexOf('=');
            if (eq <= 0) {
                continue;
            }
            String column = assignment.substring(0, eq).trim().replace("\"", "").replace("`", "");
            if (!column.isEmpty() && !column.contains(" ")) {
                properties.add(snakeToCamel(column));
            }
        }
        return properties;
    }

    /** 实参分类：常量占位（{@code 0} / {@code BigDecimal.ZERO} / {@code "new"} / {@code null}）不算真值级写入。 */
    static Kind kindOf(String arg) {
        String value = arg.trim();
        if (value.isEmpty()) {
            return Kind.DERIVED;
        }
        return CONSTANT_ARG.matcher(value).matches() ? Kind.CONSTANT : Kind.DERIVED;
    }

    /** 剥注释：注释掉的 setter 不得算作写入点（否则判据永远不会红）。 */
    static String stripComments(String src) {
        return src.replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("(?<!:)//[^\n]*", "");
    }

    private static String argAt(String src, int openParen) {
        int depth = 0;
        for (int i = openParen; i < src.length(); i++) {
            char c = src.charAt(i);
            if (c == '(') {
                depth++;
            } else if (c == ')') {
                depth--;
                if (depth == 0) {
                    return src.substring(openParen + 1, i);
                }
            }
        }
        return "";
    }

    private static void add(Map<String, List<WriteSite>> sites, String field, WriteSite site) {
        sites.computeIfAbsent(field, key -> new ArrayList<>()).add(site);
    }

    private static String decap(String beanName) {
        return beanName.substring(0, 1).toLowerCase() + beanName.substring(1);
    }

    private static String snakeToCamel(String column) {
        StringBuilder out = new StringBuilder();
        for (String part : column.toLowerCase().split("_")) {
            if (!part.isEmpty()) {
                out.append(out.isEmpty() ? part : part.substring(0, 1).toUpperCase() + part.substring(1));
            }
        }
        return out.toString();
    }

    static String snake(String property) {
        return property.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase();
    }

    private static int lineOf(String src, int index) {
        int line = 1;
        for (int i = 0; i < index && i < src.length(); i++) {
            if (src.charAt(i) == '\n') {
                line++;
            }
        }
        return line;
    }

    private static List<Path> javaSources(Path root) {
        if (root.equals(JAVA_MAIN)) {
            if (javaFiles == null) {
                javaFiles = walk(root, ".java");
            }
            return javaFiles;
        }
        return walk(root, ".java");
    }

    private static List<Path> xmlSources(Path root) {
        if (root.equals(RESOURCES_MAIN)) {
            if (xmlFiles == null) {
                xmlFiles = walk(root, ".xml");
            }
            return xmlFiles;
        }
        return walk(root, ".xml");
    }

    private static List<Path> walk(Path root, String suffix) {
        if (!Files.isDirectory(root)) {
            return List.of();
        }
        try (Stream<Path> paths = Files.walk(root)) {
            return paths.filter(p -> p.toString().endsWith(suffix)).sorted().toList();
        } catch (IOException e) {
            throw new UncheckedIOException("源码树不可读：" + root, e);
        }
    }

    /** 读取源码（缓存）—— 供判据 / 元守卫直接行使。 */
    static String readSource(Path path) {
        return source(path);
    }

    private static String source(Path path) {
        return SOURCE_CACHE.computeIfAbsent(path, p -> {
            try {
                return Files.readString(p, StandardCharsets.UTF_8);
            } catch (IOException e) {
                throw new UncheckedIOException("读取失败：" + p, e);
            }
        });
    }

    static Path findSource(String fileName, Path javaRoot) {
        for (Path path : javaSources(javaRoot)) {
            if (path.getFileName().toString().equals(fileName)) {
                return path;
            }
        }
        return null;
    }

    private static Path repoRoot() {
        Path current = Paths.get("").toAbsolutePath();
        while (current != null && !Files.isDirectory(current.resolve("backend/admin-api"))) {
            current = current.getParent();
        }
        if (current == null) {
            throw new IllegalStateException("找不到仓库根（backend/admin-api 不存在）：判据不可空转");
        }
        return current;
    }
}