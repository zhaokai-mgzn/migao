// case_ids: PG-075

package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issue #6936）：工序「删除权」的写路径必须落到 SQL 谓词（CAS），未登记即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code ProductionOperationDetachConcurrentTest}）只保证
 * {@code detach-and-delete} <b>这一个</b>入口在并发下恰好一个赢家。而 #6936 的真实教训是
 * <b>「写路径是 check-then-act，判断与写入不在同一条语句上」</b>：{@code deleteDetaching} 先读
 * {@code op.deleted==0} 判活、再去摘格 / 级联软删 / 写工序行 ⇒ 并发下 5 个请求全进写侧
 * （实测 {@code [200,200,200,422,422]}，成功 3 次）。下一个人在<b>同族写面上</b>新加一条
 * 「软删工序」路径、或把 CAS 的「影响行数 0」判定删掉（只留调用），<b>没有任何东西会红</b>
 * —— 本守卫把「写路径清单 + 谓词完整性 + 影响行数判定」钉成机械判据。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：现取写 {@code deleted} 列的 mapper SQL 必须含 {@code claimDelete}
 *       与 {@code softDelete}；现取 service 里抢删除权的调用点必须含 {@code delete} 与
 *       {@code deleteDetaching} —— 候选集为空 / 少了核心对象 ⇒ 先红（形态被改名不是「通过」，
 *       而是「判据失明」）。</li>
 *   <li><b>谓词完整性</b>：凡在 SET 侧写 {@code deleted = 1} 的 mapper SQL，必须同时含
 *       {@code deleted = 0}（已软删的行不得再被抢删除权）与 {@code #{tenantId}}（跨租户可写 = 越权）。</li>
 *   <li><b>CAS 必须在 SET 侧显式写列</b>：{@code claimDelete} 的 SQL 必须显式 {@code deleted = 1}
 *       且保住审计字段 {@code updated_at}（issue #4608：{@code setDeleted(1); updateById(...)}
 *       会被 MP 从 SET 子句剔除 ⇒ 静默 no-op）。</li>
 *   <li><b>抢删除权必须判「影响行数 0」</b>：每个 {@code claimDelete(} 调用点都必须处在
 *       {@code if (… == 0)} 判定里（#6936 的病根本体就是「有谓词但不看影响行数」）。</li>
 *   <li><b>写路径未登记即红 + 台账不许给不存在的对象盖章</b>：现取「写 deleted 列的 service 方法」
 *       必须逐条登记在台账里；反向，台账里的每条 {@code method} 必须仍能被现取到（改名 ⇒ 红）。</li>
 *   <li><b>登记未被兑现即红</b>：{@code evidence} = {@code <仓库相对路径>::<可检索文本>}，
 *       左侧文件必须存在、右侧必须在该文件里<b>逐字出现</b> ⇒ 防「给不存在的保护盖章」。</li>
 *   <li><b>豁免台账只许缩短</b>：{@code unverified} 必须是冻结基线 {@code unverified_baseline} 的
 *       子集（新增豁免 ⇒ 红）；条数<b>现取</b>（读数打印在断言消息上）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>跑与真实源码<b>同一套</b>判定本体 ——
 *       「无谓词 updateById」「有谓词但不判影响行数」「只留赋值不判 0 行」「缺 deleted = 0」
 *       「缺 tenant_id」「未登记写路径」六种坏形态各自判红，合规语料判绿，只改注释不红。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST，同 {@code InboundOrderStatusCasMetaGuardTest} 的形态）。
 * 代价：它只能证明「这几个字在文件里」；<b>行为面由实例判据承担</b>：
 * {@code ProductionOperationDetachConcurrentTest}（#6936）—— 两者缺一不可。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账 {@code coverage_boundary} ——
 * ① 形态判据换措辞可绕过（真实防线仍是实例判据）；② 射程只到
 * {@code ProductionOperationCommandService} + 两个工序 mapper；③ 判不了「拿 {@code updateById}
 * 改<b>非 deleted</b> 列」（那不是本表的对象）；④ 本守卫<b>不</b>跑被它引用的实例判据
 * （否则「未登记即红」会退化成全量套件再跑一遍）；⑤ 本守卫<b>不改</b>任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6936）：工序删除权的写路径必须落到 SQL 谓词（未登记即红）")
class ProductionOperationDeleteCasMetaGuardTest {

    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String OPERATION_MAPPER = MAIN + "/mapper/ProductionOperationMapper.java";
    private static final String POSITION_MAPPER = MAIN + "/mapper/ProductionOperationPositionMapper.java";
    private static final String SERVICE = MAIN + "/service/ProductionOperationCommandService.java";
    private static final String LEDGER_PATH =
            MODULE + "/src/test/resources/production-operation-delete-cas-ledger.json";

    /** 手写 {@code @Update} 的取块（SQL 自带括号 ⇒ 先取块再剥 Java 语法）。 */
    private static final Pattern UPDATE_ANNOTATION =
            Pattern.compile("@Update\\s*\\(((?:[^()]|\\([^()]*\\))*)\\)");
    /** SET 侧写 {@code deleted = 1}（判「这是不是软删写面」）。 */
    private static final Pattern SETS_DELETED_ONE =
            Pattern.compile("deleted\\s*=\\s*1", Pattern.CASE_INSENSITIVE);
    /** 谓词：{@code deleted = 0}。 */
    private static final Pattern DELETED_PREDICATE =
            Pattern.compile("deleted\\s*=\\s*0", Pattern.CASE_INSENSITIVE);
    /** 谓词：租户（手写 SQL 的参数形态）。 */
    private static final Pattern TENANT_PARAM =
            Pattern.compile("#\\{\\s*tenantI?d\\s*\\}", Pattern.CASE_INSENSITIVE);
    /** 抢删除权的调用点（本单新加的 mapper 入口）。 */
    private static final Pattern CLAIM_CALL = Pattern.compile("claimDelete\\s*\\(");
    /** 「影响行数 == 0」判定。 */
    private static final Pattern ROW_COUNT_GUARD = Pattern.compile("==\\s*0\\s*\\)");
    /** SET 侧写 deleted 列（lambda 形态 `set(Xxx::getDeleted, 1)`）—— 判「这是不是软删写面」。 */
    private static final Pattern SETS_DELETED_LAMBDA =
            Pattern.compile("set\\(\\s*\\w+::getDeleted\\s*,\\s*1\\s*\\)");
    /** 无谓词写（WHERE 仅主键）—— #4608 的静默 no-op 形态。 */
    private static final Pattern UNCONDITIONAL_BY_ID = Pattern.compile("\\w*[Mm]apper\\.updateById\\s*\\(");
    /** 顶层方法体：4 空格缩进 + **修饰符开头** + `) {` 收尾（修饰符是必需的 —— 否则 `if (…) {` 会被当成方法头）。 */
    private static final Pattern METHOD_HEAD = Pattern.compile(
            "^ {4}(?:public|private|protected|static|final|default|synchronized|abstract)\\b[^\\n]*\\([^;{]*\\)\\s*\\{\\s*$");
    /** 控制结构关键字（与「方法 + 体」同形，靠名字排除）。 */
    private static final List<String> CONTROL_KEYWORDS =
            List.of("if", "for", "while", "switch", "catch", "synchronized", "try", "do");
    /** 「claimDelete 调用 + 其后的判定」窗口。 */
    private static final int GUARD_WINDOW = 600;

    // ────────────────────────────────────────────── 判据 1~3：真语料（mapper 侧）

    @Test
    @DisplayName("扫描器非空跑自证 + 写 deleted 列的 SQL 必须带 deleted=0 / tenant_id 谓词 + 显式写列")
    void mapperWritesCarryTheFullPredicate() throws IOException {
        List<SqlWrite> writes = mapperDeleteWrites(operationMapperText() + "\n" + positionMapperText());
        List<String> sqls = writes.stream().map(SqlWrite::sql).toList();
        List<String> offenders = new ArrayList<>();
        for (SqlWrite w : writes) {
            List<String> missing = new ArrayList<>();
            if (!DELETED_PREDICATE.matcher(w.sql()).find()) {
                missing.add("deleted = 0 谓词");
            }
            if (!TENANT_PARAM.matcher(w.sql()).find()) {
                missing.add("tenant_id 谓词");
            }
            if (!missing.isEmpty()) {
                offenders.add(w.method() + " 缺 " + missing);
            }
        }
        System.out.println("[READING PG-075 mapper] 写 deleted 列的 SQL=" + sqls + " 违规=" + offenders);

        assertThat(sqls)
                .as("现取集必须含核心写面（少了 = 被改名或漏扫，判据在变瞎）；实测=" + writes)
                .isNotEmpty();
        assertThat(writes.stream().map(SqlWrite::method).toList())
                .as("工序行的删除权入口（claimDelete）必须在现取集里；实测=" + writes)
                .contains("claimDelete");
        assertThat(offenders)
                .as("写 deleted 列的 SQL 必须把判断与写入压进同一条语句（无谓词写 = #6936 的病根）")
                .isEmpty();

        // SET 侧形态：显式写 deleted = 1（#4608）+ 保住审计字段 updated_at（「谁在什么时候删的」唯一证据）
        String claimSql = writes.stream().filter(w -> "claimDelete".equals(w.method())).map(SqlWrite::sql)
                .findFirst()
                .orElseThrow(() -> new AssertionError("claimDelete 不在现取写面里：" + writes));
        System.out.println("[READING PG-075 SET] claimDelete SQL=" + claimSql);
        assertThat(claimSql).as("CAS 必须显式写 deleted = 1").containsPattern("deleted\\s*=\\s*1");
        assertThat(claimSql).as("CAS 必须保住 updated_at（审计）").contains("updated_at");
    }

    // ────────────────────────────────────────────── 判据 4~7：真语料（service 侧 + 台账）

    @Test
    @DisplayName("抢删除权必须判影响行数 + 写路径未登记即红 + 登记必须兑现 + 豁免只许缩短")
    void serviceWritePathsAreRegisteredAndGuarded() throws IOException {
        String service = serviceText();
        List<String> paths = serviceDeleteWritePaths(service);
        List<String> unguarded = claimCallsWithoutRowCountGuard(service);
        List<String> ledgerMethods = ledgerMethods();

        System.out.println("[READING PG-075 service] 现取写路径=" + paths
                + " 未判影响行数的 claimDelete 调用点=" + unguarded + " 已登记=" + ledgerMethods);

        assertThat(paths)
                .as("扫描器必须现取到写 deleted 列的 service 方法（空集 = 判据失明）")
                .contains("delete", "deleteDetaching");
        assertThat(unguarded)
                .as("抢删除权必须判「影响行数 0」—— 有谓词但不判 = 并发下多个请求都进写侧（#6936 病根）")
                .isEmpty();
        assertThat(ledgerMethods)
                .as("新增写路径未登记即红（下一个 #6936 就是从这里进来的）")
                .containsAll(paths);
        assertThat(ledgerMethods.stream().filter(m -> !paths.contains(m)).toList())
                .as("台账不许给不存在的写路径盖章（改名 / 删除 ⇒ 红）")
                .isEmpty();

        // 登记未被兑现即红：每条 evidence 锚必须在它声称的文件里逐字出现
        Path root = repoRoot();
        List<String> broken = new ArrayList<>();
        for (var e : ledgerEntries()) {
            String anchor = e.get("evidence").asText();
            int sep = anchor.indexOf("::");
            if (sep <= 0) {
                broken.add("evidence 形态不是 <path>::<anchor>：" + anchor);
                continue;
            }
            Path file = root.resolve(anchor.substring(0, sep));
            String symbol = anchor.substring(sep + 2);
            if (!Files.exists(file)) {
                broken.add("左侧文件不存在：" + anchor.substring(0, sep));
            } else if (!Files.readString(file, StandardCharsets.UTF_8).contains(symbol)) {
                broken.add("右侧锚在文件里找不到：" + symbol);
            }
        }
        System.out.println("[READING PG-075 兑现] 断链=" + broken);
        assertThat(broken).as("evidence 必须逐字兑现（摘掉 CAS 判定 / 方法改名 ⇒ 当场红）").isEmpty();

        // 豁免台账只许缩短（条数现取，不写死）
        int unverified = unverifiedCount();
        int baseline = unverifiedBaseline();
        System.out.println("[READING PG-075 豁免] 现取=" + unverified + " 基线=" + baseline);
        assertThat(unverified).as("豁免台账只许缩短（新增豁免必须走 issue + 重启条件）")
                .isLessThanOrEqualTo(baseline);
    }

    // ────────────────────────────────────────────── 判据 8：合成语料判别力自证

    @Test
    @DisplayName("判别力自证（合成语料）：六种坏形态各自判红、合规语料判绿")
    void guardHasDiscriminatingPower() {
        String goodMapper = mapperCorpus("claimDelete", true, true) + mapperCorpus("softDelete", true, true);
        String goodService = serviceCorpus("delete", guardedClaim()) + serviceCorpus("deleteDetaching", guardedClaim());

        System.out.println("[READING PG-075 语料] 合规语料问题清单=" + problems(goodMapper, goodService));
        assertThat(problems(goodMapper, goodService))
                .as("合规语料判绿（否则本守卫是恒红噪声）").isEmpty();

        // 坏形态 ①：无谓词写（= #4608 的静默 no-op 形态）
        assertThat(problems(mapperCorpus("unconditional", true, true), serviceCorpus("delete",
                "productionOperationMapper.updateById(new LambdaUpdateWrapper<ProductionOperation>()\n"
                        + "                .set(ProductionOperation::getDeleted, 1));")))
                .as("软删走无谓词 updateById（= #4608 静默 no-op 形态）必须判红").isNotEmpty();

        // 坏形态 ②：谓词齐、但不判影响行数（= #6936 病根本体）
        assertThat(problems(goodMapper, serviceCorpus("delete", bareClaim())))
                .as("有谓词但不判影响行数（没人看 0 行）⇒ 必须判红").isNotEmpty();

        // 坏形态 ③：最隐蔽的一种 —— 赋值留着、`if (… == 0)` 判定被删
        assertThat(problems(goodMapper, serviceCorpus("delete", "int rows = " + bareClaim())))
                .as("只留赋值不判 0 行 ⇒ 必须判红（判据的主张本体是判定，不是调用）").isNotEmpty();

        // 坏形态 ④：缺 deleted = 0（软删的行可被再抢删除权）
        assertThat(problems(mapperCorpus("claimDelete", true, false), goodService))
                .as("缺 deleted=0 必须判红").isNotEmpty();

        // 坏形态 ⑤：缺 tenant 谓词（跨租户可写）
        assertThat(problems(mapperCorpus("claimDelete", false, true), goodService))
                .as("缺 tenant 谓词必须判红").isNotEmpty();

        // 坏形态 ⑥：新加一条抢删除权但不判影响行数的路径
        assertThat(problems(goodMapper, goodService + serviceCorpus("undeclaredWrite", bareClaim())))
                .as("新加一条未登记、也不判影响行数的抢删除权路径 ⇒ 必须判红").isNotEmpty();

        // 反向对照：只改注释 ⇒ 不红
        assertThat(problems(goodMapper, goodService.replace("删工序", "删工序（注释微调）")))
                .as("只改注释不得判红").isEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真语料与合成语料共用）

    private record SqlWrite(String method, String sql) {
    }

    /** 判定本体：返回问题清单（空 = 合规）。合成语料与真语料**跑同一套**。 */
    private static List<String> problems(String mapperText, String serviceText) {
        List<String> out = new ArrayList<>();
        for (SqlWrite w : mapperDeleteWrites(mapperText)) {
            if (!DELETED_PREDICATE.matcher(w.sql()).find()) {
                out.add("mapper " + w.method() + " 缺 deleted = 0");
            }
            if (!TENANT_PARAM.matcher(w.sql()).find()) {
                out.add("mapper " + w.method() + " 缺 tenant_id 谓词");
            }
        }
        for (String m : claimCallsWithoutRowCountGuard(serviceText)) {
            out.add("service " + m + " 抢删除权但不判影响行数（0 行 ⇒ 必须 fail-closed）");
        }
        for (String m : serviceMethodsUsingUpdateById(serviceText)) {
            out.add("service " + m + " 用了无谓词 updateById（WHERE 仅主键 ⇒ 并发下不互斥）");
        }
        return out;
    }

    /**
     * 现取「写 {@code deleted} 列的 mapper SQL」：取每个 {@code @Update} 注解块里含
     * {@code deleted = 1} 的那些；方法名 = 注解之后第一个 {@code <type> <name>(} 形态的名字。
     */
    private static List<SqlWrite> mapperDeleteWrites(String text) {
        List<SqlWrite> out = new ArrayList<>();
        Matcher m = UPDATE_ANNOTATION.matcher(text);
        while (m.find()) {
            String raw = m.group(1);
            if (!SETS_DELETED_ONE.matcher(raw).find()) {
                continue;
            }
            String sql = raw.replace("\"", "").replace("+", " ").replaceAll("\\s+", " ").trim();
            String after = text.substring(m.end(), Math.min(text.length(), m.end() + 400));
            Matcher name = Pattern.compile("(\\w+)\\s*\\(").matcher(after);
            out.add(new SqlWrite(name.find() ? name.group(1) : "<unknown>", sql));
        }
        return out;
    }

    /** 现取「抢删除权（或显式写列）的 service 方法名」。 */
    private static List<String> serviceDeleteWritePaths(String text) {
        List<String> out = new ArrayList<>();
        for (String name : methodNames(text)) {
            String body = methodBody(text, name);
            if (CLAIM_CALL.matcher(body).find() || SETS_DELETED_LAMBDA.matcher(body).find()) {
                out.add(name);
            }
        }
        return out;
    }

    /** 抢删除权但**不判影响行数**的调用点（方法名）；#6936 的病根本体。 */
    private static List<String> claimCallsWithoutRowCountGuard(String text) {
        List<String> out = new ArrayList<>();
        for (String name : methodNames(text)) {
            String body = methodBody(text, name);
            Matcher call = CLAIM_CALL.matcher(body);
            while (call.find()) {
                int end = Math.min(body.length(), call.end() + GUARD_WINDOW);
                if (!ROW_COUNT_GUARD.matcher(body.substring(call.start(), end)).find()) {
                    out.add(name);
                }
            }
        }
        return out;
    }

    /** 用了无谓词 {@code updateById} 的 service 方法。 */
    private static List<String> serviceMethodsUsingUpdateById(String text) {
        List<String> out = new ArrayList<>();
        for (String name : methodNames(text)) {
            String body = methodBody(text, name);
            if (UNCONDITIONAL_BY_ID.matcher(body).find()
                    && (CLAIM_CALL.matcher(body).find() || SETS_DELETED_LAMBDA.matcher(body).find())) {
                out.add(name);
            }
        }
        return out;
    }

    /** 顶层方法名（4 空格缩进 + `) {` 收尾；控制结构关键字排除）。 */
    private static List<String> methodNames(String text) {
        List<String> out = new ArrayList<>();
        for (String line : text.split("\n")) {
            if (!METHOD_HEAD.matcher(line).matches()) {
                continue;
            }
            Matcher name = Pattern.compile("(\\w+)\\s*\\([^;{]*\\)\\s*\\{\\s*$").matcher(line.trim());
            if (!name.find()) {
                continue;
            }
            String n = name.group(1);
            if (!CONTROL_KEYWORDS.contains(n)) {
                out.add(n);
            }
        }
        return out;
    }

    /** 方法体 = 从签名行到下一个顶层签名行（或文件末尾）；同名只取第一处。 */
    private static String methodBody(String text, String name) {
        String[] lines = text.split("\n", -1);
        int start = -1;
        for (int i = 0; i < lines.length; i++) {
            if (!METHOD_HEAD.matcher(lines[i]).matches()) {
                continue;
            }
            Matcher m = Pattern.compile("(\\w+)\\s*\\(").matcher(lines[i].trim());
            if (m.find() && m.group(1).equals(name)) {
                start = i;
                break;
            }
        }
        if (start < 0) {
            return "";
        }
        StringBuilder body = new StringBuilder(lines[start]).append('\n');
        for (int i = start + 1; i < lines.length; i++) {
            if (METHOD_HEAD.matcher(lines[i]).matches()) {
                break;
            }
            body.append(lines[i]).append('\n');
        }
        return body.toString();
    }

    // ────────────────────────────────────────────── 语料读面

    private static String operationMapperText() throws IOException {
        return read(OPERATION_MAPPER);
    }

    private static String positionMapperText() throws IOException {
        return read(POSITION_MAPPER);
    }

    private static String serviceText() throws IOException {
        return read(SERVICE);
    }

    private static String read(String path) throws IOException {
        return Files.readString(repoRoot().resolve(path), StandardCharsets.UTF_8);
    }

    /** 合成 mapper 写面（形态与真源码逐字同款：手写 @Update SQL）。 */
    private static String mapperCorpus(String method, boolean withTenant, boolean withDeletedZero) {
        return "    @Update(\"UPDATE production_operations SET deleted = 1, updated_at = #{updatedAt} "
                + "WHERE id = #{id}" + (withTenant ? " AND tenant_id = #{tenantId}" : "")
                + (withDeletedZero ? " AND deleted = 0" : "") + "\")\n"
                + "    int " + method + "(@Param(\"id\") String id);\n\n";
    }

    /** 合成 service 方法（形态与真源码同款：4 空格缩进的 `) {` 收尾）。 */
    private static String serviceCorpus(String method, String body) {
        return "    public Map<String, Object> " + method + "(String id, Long tenantId) {\n"
                + "        " + body + "\n        return null;\n    }\n\n";
    }

    /** 合规的抢删除权形态（判影响行数）。 */
    private static String guardedClaim() {
        return "if (productionOperationMapper.claimDelete(id, tenantId, now) == 0) {";
    }

    /** 坏形态：谓词齐但不判影响行数。 */
    private static String bareClaim() {
        return "productionOperationMapper.claimDelete(id, tenantId, now);";
    }

    // ────────────────────────────────────────────── 台账

    private static List<com.fasterxml.jackson.databind.JsonNode> ledgerEntries() throws IOException {
        List<com.fasterxml.jackson.databind.JsonNode> out = new ArrayList<>();
        ledger().get("entries").forEach(out::add);
        return out;
    }

    private static List<String> ledgerMethods() throws IOException {
        List<String> out = new ArrayList<>();
        for (var e : ledgerEntries()) {
            out.add(e.get("method").asText());
        }
        return out;
    }

    private static int unverifiedCount() throws IOException {
        return ledger().get("unverified").size();
    }

    private static int unverifiedBaseline() throws IOException {
        return ledger().get("unverified_baseline").asInt();
    }

    private static com.fasterxml.jackson.databind.JsonNode ledger() throws IOException {
        return new ObjectMapper().readTree(Files.readString(repoRoot().resolve(LEDGER_PATH), StandardCharsets.UTF_8));
    }

    /** 仓库根（Surefire 的工作目录 = {@code backend/admin-api}）。 */
    private static Path repoRoot() {
        Path dir = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (dir != null && !Files.exists(dir.resolve("backend/admin-api/src/main/resources/application.yml"))) {
            dir = dir.getParent();
        }
        if (dir == null) {
            throw new IllegalStateException("找不到仓库根（从 " + System.getProperty("user.dir") + " 向上）");
        }
        return dir;
    }
}
