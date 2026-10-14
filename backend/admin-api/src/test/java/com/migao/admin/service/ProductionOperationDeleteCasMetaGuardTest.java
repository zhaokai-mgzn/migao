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
 *   <li><b>扫描器非空跑自证</b>：现取 service 里「写 {@code deleted} 列的调用点」（{@code .set(…::getDeleted, 1)}）
 *       必须含两条软删路径（{@code delete} / {@code deleteDetaching}）—— 候选集为空 / 少了核心对象
 *       ⇒ 先红（形态被改名不是「通过」，而是「判据失明」）。</li>
 *   <li><b>谓词完整性</b>：每个写 {@code deleted} 列的调用点，其**同一条链**上必须同时有
 *       {@code id} 谓词、{@code tenant_id} 谓词、{@code deleted = 0} 谓词（少任何一条 = 跨租户可写 /
 *       已软删的行被复活 / 全表扫描写）。</li>
 *   <li><b>CAS 必须显式写列</b>：SET 侧必须显式 {@code .set(…::getDeleted, 1)} 并保住审计字段
 *       {@code updated_at}（issue #4608：{@code setDeleted(1); updateById(...)} 会被 MP 从 SET 子句剔除
 *       ⇒ 静默 no-op）。</li>
 *   <li><b>抢删除权必须判「影响行数 0」</b>：每个行写调用必须处在 {@code if (… == 0)} 判定里
 *       —— #6936 的病根本体就是「有谓词但不看影响行数」。</li>
 *   <li><b>写路径未登记即红 + 台账不许给不存在的对象盖章</b>：现取「写 deleted 列的 service 方法」
 *       必须逐条登记在台账里；反向，台账里的每条 {@code method} 必须仍能被现取到（改名 ⇒ 红）。</li>
 *   <li><b>登记未被兑现即红</b>：{@code evidence} = {@code <仓库相对路径>::<可检索文本>}，
 *       左侧文件必须存在、右侧必须在该文件里<b>逐字出现</b> ⇒ 防「给不存在的保护盖章」。</li>
 *   <li><b>豁免台账只许缩短</b>：{@code unverified} 必须是冻结基线 {@code unverified_baseline} 的子集
 *       （新增豁免 ⇒ 红）；条数<b>现取</b>（读数打印在断言消息上）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>跑与真实源码<b>同一套</b>判定本体 ——
 *       「缺 {@code deleted = 0}」「缺 {@code tenant_id} 谓词」「有谓词但不判影响行数」
 *       「只留赋值不判 0 行」「软删写成无谓词 {@code updateById}」五种坏形态各自判红，
 *       合规语料判绿，只改注释不红。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST，同 {@code InboundOrderStatusCasMetaGuardTest} 的形态）。
 * 代价：它只能证明「这几个字在同一段链上」；<b>行为面由实例判据承担</b>：
 * {@code ProductionOperationDetachConcurrentTest}（#6936）—— 两者缺一不可。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账 {@code coverage_boundary} ——
 * ① 形态判据换措辞可绕过（真实防线仍是实例判据）；② 射程 = {@code ProductionOperationCommandService}
 * 的工序写面（别的模块 / 别的表不在本表射程）；③ 判不了「不改 {@code deleted} 列的写」（那不是本表的对象）；
 * ④ 本守卫<b>不</b>跑被它引用的实例判据（否则「未登记即红」会退化成全量套件再跑一遍）；
 * ⑤ 本守卫<b>不改</b>任何门禁的通过条件、不新增豁免；⑥ 与
 * {@code tests/unit_ci_workflows/test_logic_delete_write_shape.py}（#4608 的显式写列守卫）
 * <b>有意重叠</b>：那条只管「形态」（不得走 {@code updateById}），本条另管「三谓词 + 影响行数判定 + 未登记即红」。</p>
 */
@DisplayName("🧱 类级元守卫（#6936）：工序删除权的写路径必须落到 SQL 谓词（未登记即红）")
class ProductionOperationDeleteCasMetaGuardTest {

    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String SERVICE = MAIN + "/service/ProductionOperationCommandService.java";
    private static final String LEDGER_PATH =
            MODULE + "/src/test/resources/production-operation-delete-cas-ledger.json";

    /** 软删写点：{@code .set(ProductionXxx::getDeleted, 1)}。 */
    private static final Pattern SET_DELETED =
            Pattern.compile("\\.set\\(\\s*Production\\w+::getDeleted\\s*,\\s*1\\s*\\)");
    /** SET 侧必须保住审计字段。 */
    private static final Pattern SET_UPDATED_AT =
            Pattern.compile("\\.set\\(\\s*Production\\w+::getUpdatedAt\\s*,");
    /** 谓词：{@code .eq(ProductionXxx::getId, …)}。 */
    private static final Pattern EQ_ID = Pattern.compile("\\.eq\\(\\s*Production\\w+::getId\\s*,");
    /** 谓词：租户。 */
    private static final Pattern EQ_TENANT = Pattern.compile("\\.eq\\(\\s*Production\\w+::getTenantId\\s*,");
    /** 谓词：{@code deleted = 0}。 */
    private static final Pattern EQ_DELETED_ZERO = Pattern.compile("\\.eq\\(\\s*Production\\w+::getDeleted\\s*,\\s*0\\s*\\)");
    /** 行写调用（条件更新的锚）。 */
    private static final Pattern ROW_WRITE = Pattern.compile("\\w*[Mm]apper\\.update\\s*\\(");
    /** 「影响行数 == 0」判定。 */
    private static final Pattern ROW_COUNT_GUARD = Pattern.compile("==\\s*0\\s*\\)");
    /** 无谓词写（WHERE 仅主键）—— #4608 的静默 no-op 形态。 */
    private static final Pattern UNCONDITIONAL_BY_ID = Pattern.compile("\\w*[Mm]apper\\.updateById\\s*\\(");
    /** 顶层方法体：4 空格缩进 + **修饰符开头** + `) {` 收尾（修饰符必需 —— 否则 `if (…) {` 会被当成方法头）。 */
    private static final Pattern METHOD_HEAD = Pattern.compile(
            "^ {4}(?:public|private|protected|static|final|default|synchronized|abstract)\\b[^\\n]*\\([^;{]*\\)\\s*\\{\\s*$");
    /** 从方法头里取方法名。 */
    private static final Pattern METHOD_NAME =
            Pattern.compile("(\\w+)\\s*\\([^;{]*\\)\\s*\\{\\s*$");
    /** 控制结构关键字（与方法头同形，靠名字排除）。 */
    private static final List<String> CONTROL_KEYWORDS =
            List.of("if", "for", "while", "switch", "catch", "synchronized", "try", "do");
    /** 「行写调用 + 其后的判定」窗口（覆盖多行 lambda 链，实测 ~340 字符）。 */
    private static final int GUARD_WINDOW = 600;

    // ────────────────────────────────────────────── 判据 1~4：真语料

    @Test
    @DisplayName("扫描器非空跑自证 + 软删写点必须带 id/tenant_id/deleted=0 三谓词 + 显式写列 + 判影响行数")
    void softDeleteWritesCarryTheFullPredicate() throws IOException {
        String service = serviceText();
        List<WriteSite> sites = deleteWriteSites(service);
        List<String> methods = sites.stream().map(WriteSite::method).toList();
        List<String> offenders = new ArrayList<>();
        for (WriteSite s : sites) {
            List<String> missing = new ArrayList<>();
            if (!EQ_ID.matcher(s.chain()).find()) {
                missing.add("id 谓词");
            }
            if (!EQ_TENANT.matcher(s.chain()).find()) {
                missing.add("tenant_id 谓词");
            }
            if (!EQ_DELETED_ZERO.matcher(s.chain()).find()) {
                missing.add("deleted = 0 谓词");
            }
            if (!SET_UPDATED_AT.matcher(s.chain()).find()) {
                missing.add("updated_at 审计列");
            }
            if (!missing.isEmpty()) {
                offenders.add(s.method() + " 缺 " + missing);
            }
        }
        System.out.println("[READING PG-075 写点] 写 deleted 列的方法=" + methods
                + " 违规=" + offenders + " 未判影响行数=" + unguardedWriteMethods(service));

        assertThat(methods)
                .as("扫描器必须现取到写 deleted 列的 service 方法（空集 = 判据失明，不是通过）；实测=" + methods)
                .contains("delete", "deleteDetaching");
        assertThat(offenders)
                .as("写 deleted 列的条件更新必须带 id + tenant_id + deleted=0 三谓词，并保住 updated_at")
                .isEmpty();
        assertThat(unguardedWriteMethods(service))
                .as("行写调用必须判「影响行数 == 0」（有谓词但不判 = 并发下多个请求都进写侧 = #6936 病根）")
                .isEmpty();
    }

    // ────────────────────────────────────────────── 判据 5~7：台账

    @Test
    @DisplayName("写路径未登记即红 + 台账不许给不存在的对象盖章 + 登记必须兑现 + 豁免只许缩短")
    void serviceWritePathsAreRegisteredAndLedgerIsFaithful() throws IOException {
        List<String> paths = serviceDeleteWriteMethods(serviceText());
        List<String> ledgerMethods = ledgerMethods();

        System.out.println("[READING PG-075 台账] 现取写路径=" + paths + " 已登记=" + ledgerMethods);

        assertThat(paths)
                .as("扫描器必须现取到写 deleted 列的 service 方法（空集 = 判据失明）")
                .contains("delete", "deleteDetaching");
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
    @DisplayName("判别力自证（合成语料）：五种坏形态各自判红、合规语料判绿")
    void guardHasDiscriminatingPower() {
        String good = serviceCorpus("delete", guardedCas()) + serviceCorpus("deleteDetaching", guardedCas());

        System.out.println("[READING PG-075 语料] 合规语料问题清单=" + problems(good));
        assertThat(problems(good)).as("合规语料判绿（否则本守卫是恒红噪声）").isEmpty();

        // 坏形态 ①：缺 deleted = 0 谓词（已软删的行可被再抢删除权）
        assertThat(problems(serviceCorpus("delete", guardedCas().replace(
                ".eq(ProductionOperation::getDeleted, 0)\n", ""))))
                .as("缺 deleted = 0 谓词必须判红").isNotEmpty();

        // 坏形态 ②：缺 tenant_id 谓词（跨租户可写）
        assertThat(problems(serviceCorpus("delete", guardedCas().replace(
                ".eq(ProductionOperation::getTenantId, tenantId)\n", ""))))
                .as("缺 tenant_id 谓词必须判红").isNotEmpty();

        // 坏形态 ③：谓词齐、但不判影响行数（= #6936 病根本体）
        assertThat(problems(serviceCorpus("delete", bareCas())))
                .as("有谓词但不判影响行数（没人看 0 行）⇒ 必须判红").isNotEmpty();

        // 坏形态 ④：最隐蔽的一种 —— 赋值留着、`if (… == 0)` 判定被删
        assertThat(problems(serviceCorpus("delete", "int rows = " + bareCas())))
                .as("只留赋值不判 0 行 ⇒ 必须判红（判据的主张本体是判定，不是调用）").isNotEmpty();

        // 坏形态 ⑤：软删写成无谓词 updateById（= #4608 静默 no-op 形态）
        assertThat(problems(serviceCorpus("delete",
                ".set(ProductionOperation::getDeleted, 1)));\n"
                        + "        productionOperationMapper.updateById(op);")))
                .as("软删走无谓词 updateById 必须判红").isNotEmpty();

        // 坏形态 ⑥：缺 updated_at 审计列
        assertThat(problems(serviceCorpus("delete", guardedCas().replace(
                ".set(ProductionOperation::getUpdatedAt, now))", ")"))))
                .as("缺 updated_at 审计列必须判红").isNotEmpty();

        // 反向对照：只改注释 ⇒ 不红
        assertThat(problems(good.replace("删工序", "删工序（注释微调）")))
                .as("只改注释不得判红").isEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真语料与合成语料共用）

    /** 一处「写 deleted 列」的调用点：方法名 + 该软删写点之后 700 字符的链（谓词与判定都在这一段里）。 */
    private record WriteSite(String method, String chain) {
    }

    private static final int CHAIN = 700;
    /** 写点**之前**要一起看的窗口（三谓词在 `.set(getDeleted, 1)` 之前 ⇒ 只看后面等于看不见谓词）。 */
    private static final int CHAIN_BACK = 600;

    /** 判定本体：返回问题清单（空 = 合规）。合成语料与真语料**跑同一套**。 */
    private static List<String> problems(String serviceText) {
        List<String> out = new ArrayList<>();
        for (WriteSite s : deleteWriteSites(serviceText)) {
            if (!EQ_ID.matcher(s.chain()).find()) {
                out.add("service " + s.method() + " 缺 id 谓词");
            }
            if (!EQ_TENANT.matcher(s.chain()).find()) {
                out.add("service " + s.method() + " 缺 tenant_id 谓词");
            }
            if (!EQ_DELETED_ZERO.matcher(s.chain()).find()) {
                out.add("service " + s.method() + " 缺 deleted = 0 谓词");
            }
            if (!SET_UPDATED_AT.matcher(s.chain()).find()) {
                out.add("service " + s.method() + " 缺 updated_at 审计列");
            }
        }
        for (String m : unguardedWriteMethods(serviceText)) {
            out.add("service " + m + " 行写不判影响行数（0 行 ⇒ 必须 fail-closed）");
        }
        for (String m : methodsUsingUnconditionalUpdateById(serviceText)) {
            out.add("service " + m + " 软删写成无谓词 updateById（WHERE 仅主键 ⇒ 并发下不互斥）");
        }
        return out;
    }

    /** 现取「写 deleted 列的调用点」（写点前后 [-CHAIN_BACK, +CHAIN] 视为同一条链：谓词在写点之前）。 */
    private static List<WriteSite> deleteWriteSites(String text) {
        List<WriteSite> out = new ArrayList<>();
        for (String name : methodNames(text)) {
            String body = methodBody(text, name);
            Matcher m = SET_DELETED.matcher(body);
            while (m.find()) {
                int from = Math.max(0, m.start() - CHAIN_BACK);
                int to = Math.min(body.length(), m.end() + CHAIN);
                out.add(new WriteSite(name, body.substring(from, to)));
            }
        }
        return out;
    }

    /** 现取「写 deleted 列的 service 方法名」。 */
    private static List<String> serviceDeleteWriteMethods(String text) {
        List<String> out = new ArrayList<>();
        for (WriteSite s : deleteWriteSites(text)) {
            if (!out.contains(s.method())) {
                out.add(s.method());
            }
        }
        return out;
    }

    /** 行写调用**不判**「影响行数 == 0」的方法（#6936 病根本体）。 */
    private static List<String> unguardedWriteMethods(String text) {
        List<String> out = new ArrayList<>();
        for (String name : methodNames(text)) {
            String body = methodBody(text, name);
            Matcher call = ROW_WRITE.matcher(body);
            while (call.find()) {
                int end = Math.min(body.length(), call.end() + GUARD_WINDOW);
                if (!ROW_COUNT_GUARD.matcher(body.substring(call.start(), end)).find()) {
                    out.add(name);
                }
            }
        }
        return out;
    }

    /** 用了无谓词 {@code updateById} 的软删方法（同方法体里也出现软删写点）。 */
    private static List<String> methodsUsingUnconditionalUpdateById(String text) {
        List<String> out = new ArrayList<>();
        for (String name : methodNames(text)) {
            String body = methodBody(text, name);
            if (UNCONDITIONAL_BY_ID.matcher(body).find() && SET_DELETED.matcher(body).find()) {
                out.add(name);
            }
        }
        return out;
    }

    /** 顶层方法名（4 空格缩进 + 修饰符 + `) {` 收尾；控制结构关键字排除）。 */
    private static List<String> methodNames(String text) {
        List<String> out = new ArrayList<>();
        for (String line : text.split("\n")) {
            if (!METHOD_HEAD.matcher(line).matches()) {
                continue;
            }
            Matcher name = METHOD_NAME.matcher(line.trim());
            if (!name.find()) {
                continue;
            }
            String n = name.group(1);
            if (!CONTROL_KEYWORDS.contains(n) && !out.contains(n)) {
                out.add(n);
            }
        }
        return out;
    }

    /** 方法体 = 从签名行到下一个顶层签名行（或文件末尾）。 */
    private static String methodBody(String text, String name) {
        String[] lines = text.split("\n", -1);
        int start = -1;
        for (int i = 0; i < lines.length; i++) {
            if (!METHOD_HEAD.matcher(lines[i]).matches()) {
                continue;
            }
            Matcher m = METHOD_NAME.matcher(lines[i].trim());
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

    private static String serviceText() throws IOException {
        return Files.readString(repoRoot().resolve(SERVICE), StandardCharsets.UTF_8);
    }

    /** 合成 service 方法（形态与真源码同款：4 空格缩进的 `) {` 收尾）。 */
    private static String serviceCorpus(String method, String body) {
        return "    public Map<String, Object> " + method + "(String id, Long tenantId) {\n"
                + "        " + body + "\n        return null;\n    }\n\n";
    }

    /** 合规的抢删除权形态：三谓词 + 显式写列 + 判影响行数（与真源码逐字同款，只是缩进进了一级）。 */
    private static String guardedCas() {
        return "if (productionOperationMapper.update(null, new LambdaUpdateWrapper<ProductionOperation>()\n"
                + "                .eq(ProductionOperation::getId, id)\n"
                + "                .eq(ProductionOperation::getTenantId, tenantId)\n"
                + "                .eq(ProductionOperation::getDeleted, 0)\n"
                + "                .set(ProductionOperation::getDeleted, 1)\n"
                + "                .set(ProductionOperation::getUpdatedAt, now)) == 0) {\n"
                + "            throw BusinessException.conflict(\"并发\", \"重试\");\n        }";
    }

    /** 坏形态：谓词齐但不判影响行数。 */
    private static String bareCas() {
        return "productionOperationMapper.update(null, new LambdaUpdateWrapper<ProductionOperation>()\n"
                + "                .eq(ProductionOperation::getId, id)\n"
                + "                .eq(ProductionOperation::getTenantId, tenantId)\n"
                + "                .eq(ProductionOperation::getDeleted, 0)\n"
                + "                .set(ProductionOperation::getDeleted, 1));";
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
