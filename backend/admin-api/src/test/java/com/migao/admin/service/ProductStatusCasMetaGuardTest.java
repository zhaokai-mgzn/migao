// case_ids: MC-115

package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issue #6961）：商品状态迁移的写路径必须落到 SQL 谓词（CAS），未登记即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code ProductStatusCasRaceRealDbTest}）只保证**这四条**入口在并发下拿得准：
 * {@code updateProductStatus} / {@code updateProductForAgent} / {@code batchOnShelf} /
 * {@code batchOffShelf}。而 #6961 的真实教训是<b>「同一份状态迁移权上有四个写面，全都无谓词」</b>：
 * <ul>
 *   <li>四条入口都是「先 {@code selectById} 读旧 status 过状态机（{@code STATUS_TRANSITIONS}），
 *       再 {@code updateById}（WHERE 仅主键 ⇒ <b>无谓词</b>）」⇒ 并发 on/off_sale
 *       <b>两个请求都 200</b>，终态由后写者决定；</li>
 *   <li>{@code updateProduct} 是另一半病（T2b <b>整实体回写</b>）：显式
 *       {@code product.setStatus(originalStatus)} + {@code updateById(product)} ⇒ 改品字段会把
 *       <b>读到的旧 status 一起写回</b>，静默回滚并发的状态迁移。</li>
 * </ul>
 * 下一个人在<b>同族文件</b>新加一条状态迁移写路径、或把某条 CAS 退回无谓词 {@code updateById}，
 * 没有任何东西会红 ⇒ 本守卫把「写路径清单 + 谓词完整性 + CAS 调用锚」钉成机械判据。
 *
 * <h2>射程（一条 mapper + 一条 service）</h2>
 * {@code ProductMapper} + {@code ProductService} —— 本单四条入口与 T2b 形态**都在**这两条文件里
 * （`grep -n "setStatus\\|updateStatusIfFrom" ProductService.java` 现取自证）。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：现取「写 {@code products.status} 的 mapper SQL」必须含
 *       {@code updateStatusIfFrom}；现取「service 里写商品状态列的方法」必须含那四条入口。
 *       候选集为空 / 少了核心对象 ⇒ 先红（形态被改名不是「通过」，而是「判据失明」）。</li>
 *   <li><b>mapper 状态写 SQL 必须带完整谓词</b>：凡 SET 侧写 {@code status} 的手写 {@code @Update}
 *       SQL，必须同时含 {@code tenant_id} 参数 + WHERE 侧 {@code status} 谓词 + {@code deleted = 0}
 *       —— 少任何一条 ⇒ 红（退回「无谓词写」= 本单的病根）。</li>
 *   <li><b>无谓词写即红（判据本体）</b>：现取的每个写路径方法体里**不得**出现
 *       {@code productMapper.updateById(} —— 状态迁移必须走条件更新 CAS。
 *       **实证过的隐蔽形态**：锚串留着（{@code if (false && …updateStatusIfFrom(…)）但真正落库换成
 *       {@code updateById} ⇒ 仍判红并具名。</li>
 *   <li><b>未登记即红 + 台账不许给不存在的对象盖章</b>：service 的状态写路径必须逐条登记
 *       （{@code product-status-cas-ledger.json} 的 {@code service_write_paths}），登记的
 *       {@code call_anchor} 必须**逐字**出现在该方法体里（幽灵条目 ⇒ 红）。</li>
 *   <li><b>登记未被兑现即红</b>：每条 {@code evidence} = {@code <仓库相对全路径>::<可检索文本>}，
 *       左侧文件必须存在、右侧必须在该文件里**逐字出现**（摘掉 CAS 调用 / 方法改名 ⇒ 红）。</li>
 *   <li><b>豁免台账只许缩短 + 不许空转</b>：{@code unverified} 条数 ≤ {@code unverified_baseline}
 *       且条数**现取**（读在断言消息上）；{@code entries} / {@code service_write_paths} 为空 ⇒ 红
 *       （fail-closed：「空」不等于「全部合规」）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>在内存里跑与真实源码<b>同一套</b>判定本体 ——
 *       「无谓词状态写」「缺 {@code deleted=0}」「缺 tenant 谓词」「缺 WHERE 侧 status 谓词」
 *       「未登记写路径」「锚留而落库无谓词」「台账未兑现」七种坏形态各自判红，合规语料判绿，
 *       <b>只加注释不红</b>。没有这条，「判据恒绿」与「判据有效」在结果列上长得一样。</li>
 * </ol>
 *
 * <h3>🔴 去谓词 / 去行数判定各自的红证（§23 G3 的「判别力自证」）</h3>
 * 判据 2/3 在合成语料上**各有一条**定向注入：去掉 WHERE 侧 status 谓词 ⇒ 判据 2 红；
 * 把行写换回 {@code updateById} ⇒ 判据 3 红（两者都不是「顺手一起红」）。
 * <b>判不了「0 行之后不 fail-closed」</b>（那是实例判据 PG-084 的靶心，本守卫读的是源码文本）。
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST）—— 本仓既有形态（MC-100
 * {@code InboundOrderStatusCasMetaGuardTest} / MC-104 {@code ProcessingOrderStatusCasMetaGuardTest} 同款）。
 * 代价：它只能证明「这几个字在方法体里」；<b>行为面由真库并发判据承担</b>：
 * {@code ProductStatusCasRaceRealDbTest}（#6961）—— 两者缺一不可（{@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在）。</p>
 *
 * <p>⛔ <b>与 MC-100（入库单）/ PG-075（工序删除权）/ MC-102（入驻审核）/ MC-104（加工单）/ #6220 的
 * 售后多副作用守卫互不重叠</b>：各自守自己那张表 / 那个形态的写路径，既不互为副本、也互不重判
 * （判据与台账都是各自独立的）—— 本单一个字都没动它们。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账 {@code coverage_boundary} ——
 * ① 形态判据换措辞可绕过（真实防线仍是实例判据）；② 射程只到这两条文件；
 * ③ 判不了「拿 {@code updateById} / wrapper 改**非状态**列」（那不是本表的对象）；
 * ④ 本守卫**不**跑被它引用的那条真库判据（否则「未登记即红」会退化成全量套件再跑一遍）；
 * ⑤ 本守卫**不改**任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6961）：商品状态迁移写路径必须落到 SQL 谓词（未登记即红 + 豁免只许缩短）")
class ProductStatusCasMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）；台账里的引用一律是**仓库相对全路径**。 */
    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String MAPPER_FILE = MAIN + "/mapper/ProductMapper.java";
    private static final String SERVICE_FILE = MAIN + "/service/ProductService.java";
    private static final String LEDGER_PATH =
            MODULE + "/src/test/resources/product-status-cas-ledger.json";

    /** 本单四条状态迁移入口 + T2b 的宿主方法 + 状态迁移收口（扫描器必须现取到它们，否则判据失明）。 */
    private static final List<String> CORE_WRITE_PATHS = List.of(
            "ProductService#updateProductStatus",
            "ProductService#updateProductForAgent",
            "ProductService#batchOnShelf",
            "ProductService#batchOffShelf",
            "ProductService#applyStatusTransition");

    // ── 形态（与台账 scan 段的声明逐字对应）

    /** 写面表名。 */
    private static final String TABLE = "products";
    /** `@Update` 注解的分块边界（**取块到下一处注解为止** —— SQL 自带括号，按括号配对的取块会被截断）。 */
    private static final Pattern UPDATE_ANNOTATION_SPLIT = Pattern.compile("@Update\\s*\\(");
    /** 「状态列写」的**无谓词**形态（本单的病根）：整实体回写。 */
    private static final Pattern UNCONDITIONAL_UPDATE_BY_ID =
            Pattern.compile("productMapper\\.updateById\\(");
    /**
     * 「写商品状态列」的**写路径锚**（现取，不写死方法名）：调用状态迁移收口，或直接调 mapper 的条件更新。
     * **这两条恰好圈住本单的四个入口 + 收口本身**：`doCreateProduct` / `upsertImportedProduct` 那种
     * 「new 一个实体 → 写 status → insert」是**建品**语义、不在本表射程；`updateProductRecommended` /
     * `adjustStockForAgent` 的 `updateById` 只写**非状态**列 ⇒ 不是状态写路径。
     */
    private static final Pattern STATUS_WRITE_ANCHOR =
            Pattern.compile("applyStatusTransition\\(|productMapper\\.updateStatusIfFrom\\(");
    /**
     * T2b 的**不变量**（与台账 `invariants` 段逐字对应）：
     * `<宿主方法> :: <必须逐字出现的锚> :: <该方法体内必须为空的正则>`。
     * 宿主方法不写状态列，所以它**不是**状态写路径；它的保护由本不变量单独承担。
     */
    private static final List<String> T2B_HOST_METHODS =
            List.of("updateProduct", "updateProductRecommended", "adjustStockForAgent");
    private static final String T2B_NO_STATUS_WRITE_ANCHOR = "product.setStatus(null)";
    private static final Pattern T2B_FORBIDDEN = Pattern.compile("productMapper\\.updateById\\(");
    /** 谓词 / 参数要求（issue #6961 的口径）。 */
    private static final Pattern TENANT_PARAM =
            Pattern.compile("#\\{\\s*tenantI?d\\s*\\}", Pattern.CASE_INSENSITIVE);
    /** WHERE 侧的 status 谓词（参数化 `status = #{fromStatus}` 或字面量 `status = 'x'` / `status IN (…)`）。 */
    private static final Pattern STATUS_PREDICATE =
            Pattern.compile("status\\s*(=\\s*(#\\{|')|IN\\s*\\()", Pattern.CASE_INSENSITIVE);
    private static final Pattern DELETED_PREDICATE =
            Pattern.compile("deleted\\s*=\\s*0", Pattern.CASE_INSENSITIVE);
    /** 类体顶层成员行的缩进（4 空格；8/12 ⇒ 控制结构 / lambda）。 */
    private static final String MEMBER_INDENT = "    ";
    /** Java 控制结构关键字：`if (…) {` 在行形态上与「方法 + 体」同形，靠名字排除。 */
    private static final List<String> CONTROL_KEYWORDS = List.of(
            "if", "for", "while", "switch", "catch", "synchronized", "try", "do", "else", "return");

    private static final ObjectMapper JSON = new ObjectMapper();

    // ────────────────────────────────────────────── 判据 1~6：真语料

    @Test
    @DisplayName("扫描器非空跑自证：现取写 status 的 mapper SQL 与 service 写路径必须含核心对象")
    void scannersAreNotBlind() throws IOException {
        List<String> mapperMethods = mapperStatusWrites(mapperText()).stream()
                .map(MapperWrite::method).toList();
        List<String> servicePaths = serviceWritePaths(serviceText(), SERVICE_FILE);

        System.out.println("[READING MC-115 扫描器] 写 status 的 mapper 方法=" + mapperMethods
                + " service 写路径=" + servicePaths);
        assertThat(mapperMethods)
                .as("扫描器必须现取到写 status 的 mapper 手写 SQL（返回空集 = 判据失明，不是通过）")
                .contains("updateStatusIfFrom");
        assertThat(servicePaths)
                .as("扫描器必须现取到 service 里写商品状态列的方法（少一个核心对象 = 判据失明，不是通过）")
                .containsAll(CORE_WRITE_PATHS);
        // 改品宿主**不写状态列** ⇒ 它不在状态写路径里（它的保护 = 台账 invariants，见判据 3）
        assertThat(servicePaths)
                .as("`updateProduct` 不写状态列 ⇒ 不该被当成状态写路径（否则台账会被迫把改品也登记上去）")
                .doesNotContain("ProductService#updateProduct");
    }

    @Test
    @DisplayName("T2b 不变量：整实体回写的宿主必须证明「不写陈旧状态列」，且台账 invariants 逐条兑现")
    void t2bHostsDoNotWriteStaleStatusColumn() throws IOException {
        String service = serviceText();
        Path root = repoRoot();
        List<String> broken = new ArrayList<>();
        List<String> unanchored = new ArrayList<>();
        List<String> allForbidden = new ArrayList<>();
        List<String> hostsInLedger = new ArrayList<>();
        for (JsonNode inv : ledger().get("invariants")) {
            String method = inv.get("method").asText();
            String host = bareMethod(method);
            String evidence = inv.get("evidence").asText();
            String anchor = inv.get("anchor").asText();
            // forbidden_anchor 允许显式 null：那表示「本条无独立禁用锚」（判别力全由 anchor 承担），
            // 不是漏登记 —— 台账里逐条写明了理由（forbidden_why）。
            JsonNode forbiddenNode = inv.get("forbidden_anchor");
            String forbidden = forbiddenNode == null || forbiddenNode.isNull() ? null : forbiddenNode.asText();
            hostsInLedger.add(host);
            allForbidden.add(host + "::" + (forbidden == null ? "(无独立禁用锚)" : forbidden));
            int sep = evidence.indexOf("::");
            Path file = root.resolve(evidence.substring(0, sep));
            String symbol = evidence.substring(sep + 2);
            if (!Files.exists(file)) {
                broken.add("invariants " + method + " 左侧文件不存在：" + evidence.substring(0, sep));
            } else if (!normalize(Files.readString(file, StandardCharsets.UTF_8)).contains(normalize(symbol))) {
                broken.add("invariants " + method + " 的锚在文件里找不到：" + normalize(symbol));
            }
            // 逐方法核：① 该宿主确实存在（否则台账给不存在的对象盖章）；② 命中否定锚；
            //               ③ 体内不得出现禁用锚（无谓词整实体回写 = T2b 病根形态）。
            boolean found = false;
            for (MethodBody m : membersWithBody(service)) {
                if (!host.equals(bareMethod(m.name()))) {
                    continue;
                }
                found = true;
                // 归一化空白后比对（缩进 / 换行形态不参与判定，判的是「这两句之间的保护句在不在」）
                String bodyNormalized = normalize(m.body());
                String anchorNormalized = normalize(anchor);
                String forbiddenNormalized = forbidden == null ? null : normalize(forbidden);
                if (!bodyNormalized.contains(anchorNormalized)) {
                    unanchored.add(method + " 缺「自己负责的写面」锚 `" + anchorNormalized + "`");
                }
                // 🔴 判别力本体：**紧邻前一句**必须是那条保护句（status 置 null ⇒ 不进 SET）。
                // 判据的取块器以含 `{` 的那一行**开体** ⇒ 保护句自己若正好在开体行上，它不在 body 里；
                // 故同时接受「锚那行里含保护句」（与锚同行）与「锚的紧邻前一句是保护句」两种形态。
                String preLine = inv.get("pre_line") == null ? null : inv.get("pre_line").asText();
                if (preLine != null && !bodyNormalized.contains(normalize(preLine))) {
                    unanchored.add(method + " 缺保护句 `" + normalize(preLine) + "`（紧邻在 `"
                            + anchorNormalized + "` 之前）");
                }
                // 禁用锚显式缺省（= null）时本条只判 anchor：那两条宿主的判别力全在 anchor 上
                // （摘掉保护句 ⇒ anchor 失配）。两侧都归一化后才比，否则 `A B` 与 `A B ` 会被判不等
                // ⇒ 自证假绿（真源码 / 合成语料都实测过）。
                if (forbiddenNormalized != null && bodyNormalized.contains(forbiddenNormalized)) {
                    unanchored.add(method + " 体内出现禁用锚（无谓词整实体回写）：`" + forbiddenNormalized + "`");
                }
            }
            if (!found) {
                unanchored.add("台账给不存在的宿主盖章：" + method);
            }
        }
        // 反向自证：真语料里那三个宿主必须真的存在（否则本条判据在空跑 —— 「绿了但没跑」）
        List<String> live = t2bHostMethods(service);
        System.out.println("[READING MC-115 T2b] 现取宿主=" + live + " 台账宿主=" + hostsInLedger
                + " 禁用锚=" + allForbidden + " 违规=" + unanchored + " 台账断链=" + broken);
        assertThat(live).as("真语料里必须现取到那三个整实体回写宿主（扫不到 = 判据失明，不是通过）")
                .containsAll(T2B_HOST_METHODS);
        assertThat(hostsInLedger).as("台账 invariants 必须逐条覆盖全部 T2b 宿主（未登记 ⇒ 红）")
                .containsAll(T2B_HOST_METHODS);
        assertThat(unanchored).as("T2b 宿主必须以否定锚证明不写陈旧状态列，且不得有无谓词整实体回写")
                .isEmpty();
        assertThat(broken).as("台账 invariants 的 evidence 必须逐字兑现").isEmpty();
        assertThat(service).as("真语料里必须有那个否定锚（否则本条判据在空跑）")
                .contains(T2B_NO_STATUS_WRITE_ANCHOR);
    }

    @Test
    @DisplayName("mapper 状态写 SQL 必须带完整谓词（tenant_id 参数 + status 谓词 + deleted=0）")
    void everyStatusWriteCarriesTheFullPredicate() throws IOException {
        List<MapperWrite> writes = mapperStatusWrites(mapperText());
        List<String> offenders = new ArrayList<>();
        for (MapperWrite w : writes) {
            List<String> missing = new ArrayList<>();
            if (!TENANT_PARAM.matcher(w.sql()).find()) {
                missing.add("tenant_id 参数");
            }
            if (!STATUS_PREDICATE.matcher(whereClause(w.sql())).find()) {
                missing.add("WHERE 侧 status 谓词");
            }
            if (!DELETED_PREDICATE.matcher(w.sql()).find()) {
                missing.add("deleted=0 谓词");
            }
            if (!missing.isEmpty()) {
                offenders.add(w.method() + " 缺 " + missing);
            }
        }
        System.out.println("[READING MC-115 谓词] 状态写面="
                + writes.stream().map(MapperWrite::method).toList() + " 违规=" + offenders);
        assertThat(offenders).as("状态迁移的写必须把判断与写入压进同一条语句（无谓词写 = #6961 的病根）")
                .isEmpty();
    }

    @Test
    @DisplayName("状态迁移写路径不得使用无谓词 updateById（必须走条件更新 CAS）")
    void noStatusWritePathUsesUnconditionalUpdateById() throws IOException {
        List<String> offenders = new ArrayList<>();
        for (MethodBody m : serviceCandidates(serviceText())) {
            if (UNCONDITIONAL_UPDATE_BY_ID.matcher(m.body()).find()) {
                offenders.add("ProductService#" + m.name());
            }
        }
        System.out.println("[READING MC-115 无谓词写] 现取候选方法=" + serviceWritePaths(serviceText(), SERVICE_FILE)
                + " 违规=" + offenders);
        assertThat(offenders)
                .as("状态迁移的写必须带谓词（#6961 的病根就是四条入口 + updateProduct 用了无谓词 updateById）")
                .isEmpty();
    }

    @Test
    @DisplayName("service 写路径未登记即红 + 台账不许给不存在的对象盖章 + 豁免只许缩短 + 不许空转")
    void serviceWritePathsAreRegisteredAndLedgerIsFaithful() throws IOException {
        JsonNode ledger = ledger();
        List<String> servicePaths = serviceWritePaths(serviceText(), SERVICE_FILE);
        Map<String, String> registered = new LinkedHashMap<>();
        for (JsonNode e : ledger.get("service_write_paths")) {
            registered.put(e.get("method").asText(), e.get("call_anchor").asText());
        }
        List<String> unregistered = servicePaths.stream()
                .filter(p -> !registered.containsKey(p)).toList();
        List<String> ghosts = registered.keySet().stream()
                .filter(r -> !servicePaths.contains(r)).toList();
        int unverified = ledger.get("unverified").size();
        int baseline = ledger.get("unverified_baseline").asInt();
        int entries = ledger.get("entries").size();

        System.out.println("[READING MC-115 台账] 现取写路径=" + servicePaths + " 已登记=" + registered
                + " 未登记=" + unregistered + " 幽灵条目=" + ghosts
                + " mapper 条目=" + entries + " 豁免=" + unverified + "(基线 " + baseline + ")");
        assertThat(unregistered)
                .as("新增状态迁移写路径必须登记进台账 —— 未登记就是「下一个 #6961」")
                .isEmpty();
        assertThat(ghosts).as("台账不许给不存在的写路径盖章（改名 / 删除 ⇒ 红）").isEmpty();
        assertThat(entries).as("台账不许空转：mapper 条目为 0 ⇒ 红（「空」不等于「全部合规」）").isPositive();
        assertThat(unverified).as("豁免台账只许缩短（新增豁免必须走 issue + 重启条件）")
                .isLessThanOrEqualTo(baseline);
    }

    @Test
    @DisplayName("登记未被兑现即红：每条 evidence 锚必须在它声称的文件里逐字出现")
    void everyEvidenceAnchorIsLive() throws IOException {
        JsonNode ledger = ledger();
        Path root = repoRoot();
        List<String> broken = new ArrayList<>();
        for (String section : List.of("entries", "service_write_paths")) {
            for (JsonNode e : ledger.get(section)) {
                String anchor = e.get("evidence").asText();
                int sep = anchor.indexOf("::");
                String label = section + " " + e.get("method").asText();
                if (sep <= 0) {
                    broken.add(label + " evidence 形态不是 <path>::<anchor>：" + anchor);
                    continue;
                }
                Path file = root.resolve(anchor.substring(0, sep));
                String symbol = anchor.substring(sep + 2);
                if (!Files.exists(file)) {
                    broken.add(label + " 左侧文件不存在：" + anchor.substring(0, sep));
                } else if (!normalize(Files.readString(file, StandardCharsets.UTF_8)).contains(normalize(symbol))) {
                    // 归一化比对：锚可能跨行（源码换行 / 缩进变化不该让台账假红）
                    broken.add(label + " 右侧锚在文件里找不到：" + normalize(symbol));
                }
            }
        }
        System.out.println("[READING MC-115 兑现] 断链=" + broken);
        assertThat(broken).as("evidence 必须逐字兑现（摘掉 CAS 调用 / 方法改名 ⇒ 当场红）").isEmpty();
    }

    @Test
    @DisplayName("判别力自证（真语料注入）：注入孔存在且生产恒 0 —— 防止红证装置静默腐烂")
    void guardMutationHoleIsWiredAndDisabledInProduction() throws IOException {
        String service = serviceText();
        int branches = countOf(service, "GUARD_MUTATION");
        System.out.println("[READING MC-115 注入孔] 生产读数=" + ProductService.guardMutationForTest()
                + " 注入分支出现次数=" + branches);
        assertThat(ProductService.guardMutationForTest())
                .as("生产路径必须恒 0（未设 `-Dmigao.guard.mutation` ⇒ 零影响）")
                .isZero();
        assertThat(branches).as("守卫判别力的注入锚必须存在（常量声明 + 读数方法 + 4 处注入分支 = 6）")
                .isEqualTo(6);
        // ⚠️ 如实登记：本守卫**判不了**「注入孔本身被写成恒真」这类篡改（要读注入代码的语义）；
        //    它的作用是把「红证怎么重放」钉成可检索的锚 + 把生产读数钉成 0。
        assertThat(service).as("注入孔必须显式声明生产默认值 0")
                .contains("Integer.getInteger(\"migao.guard.mutation\", 0)");
    }

    // ────────────────────────────────────────────── 判据 7：合成语料判别力自证

    @Test
    @DisplayName("判别力自证（合成语料）：七种坏形态各自判红、合规语料判绿、只改注释不红")
    void guardHasDiscriminatingPower() {
        // 合规：与真源码同形的 CAS + 五条调用点
        String goodMapper = mapperCorpus(
                "int updateStatusIfFrom(@Param(\"id\") String id);",
                "UPDATE products SET status = #{targetStatus}, edited_by = #{editedBy}, updated_at = #{editedAt} "
                        + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
                        + "AND ((#{fromStatus} IS NULL AND status IS NULL) OR status = #{fromStatus})");
        String goodService = serviceCorpus("ProductService", "updateProductStatus",
                "productMapper.updateStatusIfFrom(id, tenantId, current, target, editedBy, now);")
                + serviceCorpus("ProductService", "updateProductForAgent",
                "applyStatusTransition(latest, request.getStatus(), id, tenantId);")
                + serviceCorpus("ProductService", "batchOnShelf",
                "if (productMapper.updateStatusIfFrom(id, tenantId, currentStatus, currentStatus == null,\n                \"on_sale\", who, now) == 0) { }")
                + serviceCorpus("ProductService", "batchOffShelf",
                "if (productMapper.updateStatusIfFrom(id, tenantId, currentStatus, currentStatus == null,\n                \"off_sale\", who, now) == 0) { }")
                // 改品宿主：**不写状态列** ⇒ 它进不了状态写路径候选（不在 registered 里）——
                // 这正是「有意不写状态列」与「漏登记」的区别；它的保护由 T2b 不变量判据承担。
                + serviceCorpus("ProductService", "updateProduct",
                "product.setStatus(null);\n        productMapper.update(null, ownedColumns(product));");
        Map<String, String> registered = new LinkedHashMap<>();
        registered.put("ProductService#updateProductStatus", "productMapper.updateStatusIfFrom(");
        registered.put("ProductService#updateProductForAgent", "applyStatusTransition(");
        registered.put("ProductService#batchOnShelf", "productMapper.updateStatusIfFrom(");
        registered.put("ProductService#batchOffShelf", "productMapper.updateStatusIfFrom(");

        assertThat(problems(goodMapper, goodService, registered))
                .as("合规语料判绿（否则本守卫是恒红噪声）").isEmpty();

        // 坏形态 ①：无谓词状态写（= #6961 的病根本体）
        assertThat(problems(mapperCorpus("int updateStatusIfFrom(@Param(\"id\") String id);",
                        "UPDATE products SET status = #{targetStatus} WHERE id = #{id}"),
                goodService, registered))
                .as("无谓词状态写必须判红").isNotEmpty();

        // 坏形态 ②：缺 deleted = 0（软删的商品也能被上架）
        assertThat(problems(mapperCorpus("int updateStatusIfFrom(@Param(\"id\") String id);",
                        "UPDATE products SET status = #{targetStatus} WHERE id = #{id} "
                                + "AND tenant_id = #{tenantId} AND status = #{fromStatus}"),
                goodService, registered))
                .as("缺 deleted=0 必须判红").isNotEmpty();

        // 坏形态 ③：缺 tenant 谓词（跨租户可写）
        assertThat(problems(mapperCorpus("int updateStatusIfFrom(@Param(\"id\") String id);",
                        "UPDATE products SET status = #{targetStatus} WHERE id = #{id} "
                                + "AND status = #{fromStatus} AND deleted = 0"),
                goodService, registered))
                .as("缺 tenant 谓词必须判红").isNotEmpty();

        // 坏形态 ④（🔴 去谓词定向注入）：缺 WHERE 侧 status 谓词 = 无条件迁移，正是本单病根
        assertThat(problems(mapperCorpus("int updateStatusIfFrom(@Param(\"id\") String id);",
                        "UPDATE products SET status = #{targetStatus} WHERE id = #{id} "
                                + "AND tenant_id = #{tenantId} AND deleted = 0"),
                goodService, registered))
                .as("去谓词注入：缺 WHERE 侧 status 谓词必须判红").isNotEmpty();

        // 坏形态 ⑤：service 新加一条未登记的状态写路径
        assertThat(problems(goodMapper, goodService
                        + serviceCorpus("ProductService", "restoreShelf",
                        "productMapper.updateStatusIfFrom(id, 1L, current, current == null,\n                \"on_sale\", who, now);"), registered))
                .as("未登记的状态迁移写路径必须判红（这就是「只修一处」的复发形态）").isNotEmpty();

        // 坏形态 ⑤b（🔴 去行数判定定向注入）：最隐蔽的一种 —— **锚串留着**
        // （`if (false && …updateStatusIfFrom(…)`），真正落库的换成无谓词 updateById
        String anchorKeptButUnconditional = goodService + serviceCorpus("ProductService", "updateProductStatus2",
                "if (false && productMapper.updateStatusIfFrom(id, 1L, \"a\", \"b\", null, null) == 0) { }\n"
                        + "        productMapper.updateById(product);");
        assertThat(problems(goodMapper, anchorKeptButUnconditional, registered))
                .as("锚还在但真正落库的是无谓词 updateById ⇒ 必须判红（判据的主张本体是 CAS，不是锚）")
                .isNotEmpty();

        // 坏形态 ⑥：台账未兑现（CAS 调用被摘掉 / 改名）
        assertThat(problems(goodMapper,
                        goodService.replace("productMapper.updateStatusIfFrom(",
                                "productMapper.someOtherWrite("), registered))
                .as("台账锚被摘掉必须判红").isNotEmpty();

        // 反向对照：只改注释 ⇒ 不红
        assertThat(problems(goodMapper,
                        "// 注释里提一句 productMapper.updateById(product)\n" + goodService, registered))
                .as("只加注释不得判红（否则守卫被自己的文案喂红）").isEmpty();

        // 🔴 扫描器鲁棒性自证（MC-104 实证过的两种失明形态）：
        //   ① 跨行签名（收尾 `) {` 在续行上）：真实源码里 `updateProductForAgent` 就是这样；
        //   ② javadoc 里的**孤立 `{`**：花括号计数器把它当真代码 ⇒ 从此整体错位。
        String multiLineSignature = "public class Svc {\n"
                + "    @Transactional\n"
                + "    public void updateProductStatus(String id, String status,\n"
                + "                             Long tenantId) {\n"
                + "        productMapper.updateStatusIfFrom(id, tenantId, current, status, who, now);\n"
                + "    }\n}\n";
        Map<String, String> multiLineRegistered = new LinkedHashMap<>();
        multiLineRegistered.put("Svc#updateProductStatus", "productMapper.updateStatusIfFrom(");
        assertThat(problems(goodMapper, multiLineSignature, multiLineRegistered))
                .as("跨行签名必须仍被扫到（否则整个方法被静默跳过 ⇒ 深度错位 ⇒ 后面的写路径全部漏判）")
                .isEmpty();
        assertThat(problems(goodMapper, multiLineSignature.replace(
                        "productMapper.updateStatusIfFrom(id, tenantId, current, status, who, now);",
                        "productMapper.updateById(product);"), multiLineRegistered))
                .as("跨行签名的方法里落库换成无谓词 updateById ⇒ 必须判红（证明它真的被扫到了）")
                .isNotEmpty();
        assertThat(problems(goodMapper,
                        "/** 例：{@code STATUS_TRANSITIONS.put(\"on_sale\", List.of(\"off_sale\")) 半个花括号} */\n"
                                + goodService, registered))
                .as("注释里的孤立 `{` 不得让深度错位（否则深度下沉、后续方法全部扫不到）")
                .isEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真源码与合成语料共用）

    /**
     * 一次判定：返回问题清单（空 = 合规）。真源码与合成语料走**同一套**判定本体。
     *
     * <p>{@code registered} 的键 = 写路径的 {@code <类>#<方法>}，值 = 该路径必须**逐字出现**的调用锚
     * （如 {@code productMapper.updateStatusIfFrom(}）。「以 CAS 收口」这条主张只有在锚真的在方法体里时
     * 才成立 —— 退回无谓词 {@code updateById} ⇒ 锚消失 ⇒ 当场红。</p>
     *
     * <p>合成语料里 `public class A {…}` 会被拼成同一段文本 ⇒ 判定本体必须用「方法名」而不是「类名」
     * 索引候选（台账键里的 {@code <类>#} 前缀只用于**报读可读性**，参与匹配的是去前缀后的方法名）。</p>
     */
    private static List<String> problems(String mapperText, String serviceText,
                                         Map<String, String> registered) {
        List<String> problems = new ArrayList<>();
        for (MapperWrite w : mapperStatusWrites(mapperText)) {
            if (!TENANT_PARAM.matcher(w.sql()).find()
                    || !STATUS_PREDICATE.matcher(whereClause(w.sql())).find()
                    || !DELETED_PREDICATE.matcher(w.sql()).find()) {
                problems.add("mapper 状态写缺谓词: " + w.method());
            }
        }
        Map<String, MethodBody> candidates = new LinkedHashMap<>();
        for (MethodBody m : serviceCandidates(serviceText)) {
            candidates.put(bareMethod(m.name()), m);
        }
        // 📌 T2b（本单另一半病 = 整实体回写）的**不变量**不在这里判：它只对「宿主方法确实存在」的
        //    **真语料**成立（合成语料没有那三个宿主）⇒ 由专项判据
        //    `t2bHostsDoNotWriteStaleStatusColumn` 承担（见该判据的断言）。
        List<String> registeredBare = registered.keySet().stream()
                .map(ProductStatusCasMetaGuardTest::bareMethod).toList();
        for (Map.Entry<String, MethodBody> e : candidates.entrySet()) {
            if (!registeredBare.contains(e.getKey())) {
                problems.add("service 未登记的状态写路径: " + e.getKey());
            }
            // 🔴 本守卫的**主张本体**：状态迁移必须走条件更新（CAS）。
            //    无谓词 updateById 即使「同时也调了 updateStatusIfFrom」也必须红 —— 否则只要把调用留着、
            //    真正落库的换成 updateById，判据就会被一句 `if (false && …)` 骗过去（#6928 实证过）。
            if (UNCONDITIONAL_UPDATE_BY_ID.matcher(e.getValue().body()).find()) {
                problems.add("状态写路径里出现了无谓词 updateById（必须走 CAS）: " + e.getKey());
            }
        }
        for (Map.Entry<String, String> r : registered.entrySet()) {
            MethodBody body = candidates.get(bareMethod(r.getKey()));
            if (body == null) {
                problems.add("台账给不存在的写路径盖章: " + r.getKey());
            } else if (r.getValue() != null && !normalize(body.body()).contains(normalize(r.getValue()))) {
                problems.add("写路径未兑现：主张的 " + r.getKey() + " 收口锚不在方法体里（" + r.getValue() + "）");
            }
        }
        return problems;
    }

    /** 现取：真语料里存在的 T2b 宿主方法（**整实体回写形态**的持有者）。 */
    private static List<String> t2bHostMethods(String serviceText) {
        List<String> out = new ArrayList<>();
        for (MethodBody m : membersWithBody(serviceText)) {
            if (T2B_HOST_METHODS.contains(bareMethod(m.name()))) {
                out.add(bareMethod(m.name()));
            }
        }
        return out;
    }

    /** 子串出现次数（读数用）。 */
    private static int countOf(String text, String needle) {
        int n = 0;
        int i = text.indexOf(needle);
        while (i >= 0) {
            n++;
            i = text.indexOf(needle, i + needle.length());
        }
        return n;
    }

    /**
     * 空白归一化（台账锚 vs 方法体的比对口径）：缩进 / 换行 / 连续空格不参与判定。
     *
     * <p>两个坑都要躲：① **不归一化** ⇒ 源码换一次缩进（或把调用拆成两行）就假红；
     * ② **只 trim 一侧** ⇒ `A B` 与 `A B ` 判不等，于是「锚 == 禁用锚」那条自证会**假绿**
     * （本判据初版实测踩到，是 `guardHasDiscriminatingPower` 的合规语料红暴露的）。</p>
     */
    private static String normalize(String text) {
        return text.replaceAll("\\s+", " ").trim();
    }

    /** 台账键 / 读数键的形态是 {@code <类>#<方法>} ⇒ 参与匹配的一律是 {@code #} **之后**那一段。 */
    private static String bareMethod(String name) {
        int hash = name.indexOf('#');
        return hash < 0 ? name : name.substring(hash + 1);
    }

    /** 现取：mapper 里**在 SET 侧写 {@code status}** 的手写 SQL（方法名 + SQL 文本）。 */
    private static List<MapperWrite> mapperStatusWrites(String mapperText) {
        List<MapperWrite> out = new ArrayList<>();
        // ⚠️ 分块口径 = 「从 `@Update(` 到下一处 `@Update(`」，**不按括号配对取块** —— 本守卫的 SQL 里
        // 自带括号（`((#{fromStatus} IS NULL AND status IS NULL) OR status = #{fromStatus})`），
        // 按括号配对取块会**整条截断** ⇒ mapper 候选集恒为空（= 判据失明，且空集在结果列上看着像「通过」）。
        // 表名用 `TABLE`（"products"）判定（不用 `UPDATE products`：SQL 常量里这两段分属相邻字符串，
        // 剥掉引号后中间是空格，恰好仍在同一段文本里 —— 实跑自证）。
        for (String chunk : UPDATE_ANNOTATION_SPLIT.split(mapperText)) {
            String sql = toSql(chunk);
            String upper = sql.toUpperCase();
            if (!upper.contains("UPDATE " + TABLE.toUpperCase()) || !writesStatusColumn(sql)) {
                continue;
            }
            out.add(new MapperWrite(methodNameAfterAnnotation(chunk), sql));
        }
        return out;
    }

    /** 把 Java 注解值（可能跨行、由多个字符串字面量 `+` 拼接）还原成一行 SQL。 */
    private static String toSql(String annotationValue) {
        return annotationValue.replace("\"", "").replace("+", " ").replaceAll("\\s+", " ").trim();
    }

    /** WHERE 侧片段（谓词判定只看它 —— 免得被 SET 侧的 `status = …` 赋值骗过去）。 */
    private static String whereClause(String sql) {
        String upper = sql.toUpperCase();
        int where = upper.indexOf(" WHERE ");
        return where < 0 ? "" : sql.substring(where);
    }

    /** SET 侧是否写 {@code status}（只看 {@code SET … WHERE} 之间的片段，避免被 WHERE 里的 status 谓词骗到）。 */
    private static boolean writesStatusColumn(String sql) {
        String upper = sql.toUpperCase();
        int set = upper.indexOf(" SET ");
        int where = upper.indexOf(" WHERE ");
        String setClause = upper.substring(set < 0 ? 0 : set, where < 0 ? upper.length() : where);
        return Pattern.compile("(^|,|\\s)STATUS\\s*=").matcher(setClause).find();
    }

    /**
     * 现取：{@code service} 文本里「类体顶层的方法 + 其方法体」。
     *
     * <p>⚠️ 实现口径（MC-104 踩过的两个坑，写在这里免得下一个人再踩）：</p>
     * <ol>
     *   <li><b>逐行扫描 + 花括号深度</b>，不靠「缩进 + 标识符 + 一对复杂正则」——后者曾把整个判据
     *       变成<b>静默失明</b>（候选集恒为空，而空集在结果列上看着像「通过」）。</li>
     *   <li>🔴 <b>必须支持跨行签名</b>：`updateProductForAgent` 的签名收尾 `) {` 落在**续行**上；
     *       只认「签名行含 `) {`」会把整个方法跳过、而它的闭合花括号照样把深度减 1 ⇒ 深度从此**下沉**。
     *       ⇒ 用**待定签名**状态机：见到「类体顶层 + 4 空格缩进 + `(` + 非注释/注解」先登记名字，
     *       到第一个不深于类体的 `{` 才正式开体。</li>
     *   <li>名字取「第一个 `(` 之前的最后一段」；控制结构关键字不当签名。</li>
     * </ol>
     */
    private static List<MethodBody> membersWithBody(String text) {
        String clean = stripCommentsAndStrings(text);
        List<MethodBody> out = new ArrayList<>();
        int depth = 0;
        String name = null;
        String pending = null;
        StringBuilder body = null;
        for (String raw : clean.replace("\r", "").split("\n", -1)) {
            String trimmed = raw.strip();
            if (body == null && depth == 1
                    && raw.startsWith(MEMBER_INDENT) && !raw.startsWith(MEMBER_INDENT + " ")
                    && trimmed.contains("(")
                    && !trimmed.startsWith("*") && !trimmed.startsWith("//") && !trimmed.startsWith("@")) {
                String head = trimmed.substring(0, trimmed.indexOf('('));
                int sp = head.lastIndexOf(' ');
                String candidate = (sp < 0 ? head : head.substring(sp + 1)).strip();
                if (!candidate.isEmpty() && !CONTROL_KEYWORDS.contains(candidate)) {
                    pending = candidate;
                }
            }
            boolean activated = false;
            for (int i = 0; i < raw.length(); i++) {
                char ch = raw.charAt(i);
                if (ch == '{') {
                    depth++;
                    if (body == null && pending != null && depth == 2) {
                        name = pending;
                        pending = null;
                        body = new StringBuilder();
                        activated = true;
                    }
                } else if (ch == '}') {
                    depth--;
                    if (depth == 1 && body != null) {
                        out.add(new MethodBody(name, body.toString()));
                        body = null;
                        name = null;
                    }
                }
            }
            if (body != null && !activated) {
                body.append(raw).append('\n');
            }
        }
        return out;
    }

    /**
     * 剥掉块注释 / 行注释 / 字符串字面量 / 文本块（**保留行结构**：非换行字符变空格，换行原样留下）。
     *
     * <p>为什么必须剥：花括号深度扫描要的只是「真代码里的括号」。javadoc 里常见被截断的代码片段
     * ⇒ 不剥就整体错位 ⇒ 后续方法全部扫不到（MC-104 初版实测）。</p>
     */
    static String stripCommentsAndStrings(String src) {
        StringBuilder out = new StringBuilder(src.length());
        int i = 0;
        int n = src.length();
        while (i < n) {
            char c = src.charAt(i);
            if (src.startsWith("/*", i)) {
                int j = src.indexOf("*/", i + 2);
                j = j < 0 ? n : j + 2;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (src.startsWith("//", i)) {
                int j = src.indexOf('\n', i);
                j = j < 0 ? n : j;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (src.startsWith("\"\"\"", i)) {
                int j = src.indexOf("\"\"\"", i + 3);
                j = j < 0 ? n : j + 3;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (c == '"' || c == '\'') {
                int j = i + 1;
                while (j < n) {
                    if (src.charAt(j) == '\\') {
                        j += 2;
                        continue;
                    }
                    if (src.charAt(j) == c) {
                        j++;
                        break;
                    }
                    j++;
                }
                appendBlanks(out, src, i, Math.min(j, n));
                i = Math.min(j, n);
            } else {
                out.append(c);
                i++;
            }
        }
        return out.toString();
    }

    /** 把 {@code [from, to)} 逐字符写成空格，**换行原样保留**（行号与缩进判定都依赖它）。 */
    private static void appendBlanks(StringBuilder out, String src, int from, int to) {
        for (int k = from; k < to; k++) {
            out.append(src.charAt(k) == '\n' ? '\n' : ' ');
        }
    }

    /** 现取：service 里**出现商品状态列写**的方法（方法名 + 方法体）。 */
    private static List<MethodBody> serviceCandidates(String serviceText) {
        List<MethodBody> out = new ArrayList<>();
        for (MethodBody m : membersWithBody(serviceText)) {
            if (STATUS_WRITE_ANCHOR.matcher(m.body()).find()) {
                out.add(m);
            }
        }
        return out;
    }

    /** service 的现取写路径清单（{@code <类>#<方法>}，报读与台账对账都用它）。 */
    private static List<String> serviceWritePaths(String serviceText, String file) {
        String owner = ownerOf(file);
        return serviceCandidates(serviceText).stream()
                .map(m -> owner + "#" + m.name()).collect(Collectors.toList());
    }

    /** 从仓库相对全路径取类名（台账 / 读数都用它，免得两处各写一份）。 */
    private static String ownerOf(String file) {
        String base = file.substring(file.lastIndexOf('/') + 1);
        return base.endsWith(".java") ? base.substring(0, base.length() - 5) : base;
    }

    /**
     * 该写面的方法名 = **注解之后第一段字符串常量**（SQL 字面量）结束之后第一个 `名字(`。
     *
     * <p>⚠️ 不能直接用「文本里第一个 `名字(`」：SQL 字面量里本来就有 `COALESCE(` / `GREATEST(`
     * （实测第一次就是这么错取成 `AND` 的）⇒ 必须跳过 SQL 字面量再取。</p>
     */
    private static String methodNameAfterAnnotation(String chunk) {
        int i = 0;
        int n = chunk.length();
        while (i < n && chunk.charAt(i) != '"') {
            i++;
        }
        while (i < n) {
            if (chunk.charAt(i) == '\\') {
                i += 2;
                continue;
            }
            if (chunk.charAt(i) == '"') {
                i++;
                break;
            }
            i++;
        }
        Matcher m = Pattern.compile("\\s+(\\w+)\\s*\\(").matcher(chunk.substring(Math.min(i, n)));
        return m.find() ? m.group(1) : "<unknown>";
    }

    private record MapperWrite(String method, String sql) {
    }

    private record MethodBody(String name, String body) {
    }

    // ────────────────────────────────────────────── 语料构造（合成判据用）

    /** 合成 mapper 语料：`(方法签名, SQL)` 交替传入。 */
    private static String mapperCorpus(String... signatureAndSqlPairs) {
        StringBuilder sb = new StringBuilder("public interface X {\n");
        for (int i = 0; i + 1 < signatureAndSqlPairs.length; i += 2) {
            sb.append("    @Update(\"").append(signatureAndSqlPairs[i + 1]).append("\")\n")
                    .append("    ").append(signatureAndSqlPairs[i]).append("\n");
        }
        return sb.append("}\n").toString();
    }

    private static String serviceCorpus(String owner, String method, String methodBody) {
        return "public class " + owner + " {\n    public void " + method + "(String id) {\n        "
                + methodBody + "\n    }\n}\n";
    }

    // ────────────────────────────────────────────── 语料读取

    private static String mapperText() throws IOException {
        return Files.readString(repoRoot().resolve(MAPPER_FILE), StandardCharsets.UTF_8);
    }

    private static String serviceText() throws IOException {
        return Files.readString(repoRoot().resolve(SERVICE_FILE), StandardCharsets.UTF_8);
    }

    private static JsonNode ledger() throws IOException {
        return JSON.readTree(Files.readString(repoRoot().resolve(LEDGER_PATH), StandardCharsets.UTF_8));
    }

    /** 仓根（Surefire 的工作目录 = {@code backend/admin-api}，向上找到台账所在层）。 */
    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(LEDGER_PATH))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 " + LEDGER_PATH).isNotNull();
        return root;
    }
}
