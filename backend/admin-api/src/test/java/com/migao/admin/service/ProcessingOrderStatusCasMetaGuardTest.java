// case_ids: MC-101

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
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issue #6955）：加工单状态迁移的写路径必须落到 SQL 谓词（CAS），未登记即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code ProcessingOrderStatusCasRaceRealDbTest}）只保证**这两个**入口在并发下拿得准：
 * {@code ProcessingOrderService#updateStatus} 与 {@code OrderService#cancelOrder} 的联动腿。
 * 而 #6955 的真实教训是<b>「同一份状态迁移权上有多个写面，只有一部分带 CAS」</b>：
 * <ul>
 *   <li>{@code updateStatus} 走「先读 status 过状态机、再 {@code updateById}（WHERE 仅主键 ⇒ 无谓词）」
 *       ⇒ 同一张加工单并发 {@code issue} + {@code cancel} **两个请求都 200**，终态由后写者决定
 *       （{@code issued} 与 {@code cancelled} 在状态机里互不可达 ⇒ 终态**必然**自相矛盾）；</li>
 *   <li>{@code OrderService#cancelOrder} 的联动作废腿**同样**无谓词 ⇒ 订单作废 × 加工单开工并发时
 *       出现「**订单 cancelled + 加工单 issued**」（订单已废、单还在产）。</li>
 * </ul>
 * 下一个人在**同族文件**新加一条状态迁移写路径、或给 mapper 加一条**无谓词**的状态写 SQL，
 * 没有任何东西会红 ⇒ 本守卫把「写路径清单 + 谓词完整性」钉成机械判据。
 *
 * <h2>射程（两条 service 文件 + 一条 mapper 文件，比 MC-100 宽一格）</h2>
 * {@code ProcessingOrderMapper} + {@code ProcessingOrderService} + {@code OrderService}
 * —— 第三者是**必须的**：本单的第二个写面就在那里（同文件里 {@code cancelOrder} 的加工单联动腿）。
 * 只扫 service+mapper 那一对的做法，恰恰会**漏掉本单一半的病**。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：现取「写 {@code processing_orders.status} 的 mapper SQL」必须含
 *       {@code markCompletedIfActive} / {@code markInProcessingIfFrom} / {@code markStatusIfFrom}；
 *       现取「两条 service 里写加工单状态列的方法」必须含 {@code updateStatus} 与 {@code cancelOrder}。
 *       候选集为空 / 少了核心对象 ⇒ 先红（形态被改名不是「通过」，而是「判据失明」）。</li>
 *   <li><b>mapper 状态写 SQL 必须带完整谓词</b>：凡 SET 侧写 {@code status} 的手写 {@code @Update}
 *       SQL，必须同时含 {@code tenant_id} 参数 + WHERE 侧 {@code status} 谓词 + {@code deleted = 0}
 *       —— 少任何一条 ⇒ 红（退回「无谓词写」= 本单的病根）。</li>
 *   <li><b>无谓词写即红（判据本体）</b>：现取的每个写路径方法体里**不得**出现
 *       {@code processingOrderMapper.updateById(} —— 状态迁移必须走条件更新 CAS。
 *       **实证过的隐蔽形态**：锚串留着（{@code if (false && …markStatusIfFrom(…) }）但真正落库换成
 *       {@code updateById} ⇒ 仍判红并具名。</li>
 *   <li><b>未登记即红 + 台账不许给不存在的对象盖章</b>：两条 service 的状态写路径必须逐条登记
 *       （{@code processing-order-status-cas-ledger.json} 的 {@code service_write_paths}），登记的
 *       {@code call_anchor} 必须**逐字**出现在该方法体里。</li>
 *   <li><b>登记未被兑现即红</b>：每条 {@code evidence} = {@code <仓库相对全路径>::<可检索文本>}，
 *       左侧文件必须存在、右侧必须在该文件里**逐字出现**（摘掉 CAS 调用 / 方法改名 ⇒ 红）。</li>
 *   <li><b>豁免台账只许缩短 + 不许空转</b>：{@code unverified} 必须是冻结基线
 *       {@code unverified_baseline} 的**子集**（新增豁免 ⇒ 红）；条数**现取**（读在断言消息上）；
 *       {@code entries} / {@code service_write_paths} 为空 ⇒ 红（fail-closed：「空」不等于「全部合规」）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>在内存里跑与真实源码<b>同一套</b>判定本体 ——
 *       「无谓词状态写」「缺 {@code deleted=0}」「缺 tenant 谓词」「未登记写路径」「锚留而落库无谓词」
 *       「台账未兑现」六种坏形态各自判红，合规语料判绿，<b>只加注释不红</b>。
 *       没有这条，「判据恒绿」与「判据有效」在结果列上长得一样。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST）—— 本仓既有形态（MC-100
 * {@code InboundOrderStatusCasMetaGuardTest} / {@code OrderAutoCompleteSqlGuardTest} /
 * {@code StockDeductionAndLedgerAtomicityMetaGuardTest} 同款）。代价：它只能证明「这几个字在方法体里」；
 * <b>行为面由真库并发判据承担</b>：{@code ProcessingOrderStatusCasRaceRealDbTest}（#6955）——
 * 两者缺一不可（{@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在）。</p>
 *
 * <p>⛔ <b>与 MC-100（入库单）/ PG-075（工序删除权）互不重叠</b>：三张表各自守自己的租户数据类型，
 * 既不互为副本、也互不重判（判据与台账都是各自独立的）。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账 {@code coverage_boundary} ——
 * ① 形态判据换措辞可绕过（真实防线仍是实例判据）；② 射程只到这三条文件；
 * ③ 判不了「拿 {@code updateById} 改**非状态**列」（那不是本表的对象）；
 * ④ 本守卫**不**跑被它引用的那条真库判据（否则「未登记即红」会退化成全量套件再跑一遍）；
 * ⑤ 本守卫**不改**任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6955）：加工单状态迁移写路径必须落到 SQL 谓词（未登记即红 + 豁免只许缩短）")
class ProcessingOrderStatusCasMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）；台账里的引用一律是**仓库相对全路径**。 */
    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String MAPPER_FILE = MAIN + "/mapper/ProcessingOrderMapper.java";
    private static final String SERVICE_FILE = MAIN + "/service/ProcessingOrderService.java";
    private static final String ORDER_SERVICE_FILE = MAIN + "/service/OrderService.java";
    private static final String LEDGER_PATH =
            MODULE + "/src/test/resources/processing-order-status-cas-ledger.json";

    /** 两条 service 文件（台账条目的 {@code file} 字段必须落在这两个之一）。 */
    private static final Map<String, String> SERVICE_FILES = Map.of(
            "backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java", SERVICE_FILE,
            "backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java", ORDER_SERVICE_FILE);

    // ── 形态（与台账 scan 段的声明逐字对应）

    /** 手写 update 注解的**取块**（到配对的 `)` 为止；SQL 自带括号 ⇒ 先取块再剥 Java 语法）。 */
    private static final Pattern UPDATE_ANNOTATION =
            Pattern.compile("@Update\\s*\\(((?:[^()]|\\([^()]*\\))*)\\)");
    /** 写面表名。 */
    private static final String TABLE = "processing_orders";
    /** 「状态列写」的**无谓词**形态（本单的病根）：整实体回写。 */
    private static final Pattern UNCONDITIONAL_UPDATE_BY_ID =
            Pattern.compile("processingOrderMapper\\.updateById\\(");
    /** 该 mapper 的条件更新写面（现取，不写死）：`processingOrderMapper.markXxx(`。 */
    private static final Pattern MAPPER_CAS_CALL = Pattern.compile("processingOrderMapper\\.(mark\\w+)\\(");
    /** 谓词 / 参数要求（issue #6955 的口径）。 */
    private static final Pattern TENANT_PARAM =
            Pattern.compile("#\\{\\s*tenantI?d\\s*\\}", Pattern.CASE_INSENSITIVE);
    /** WHERE 侧的 status 谓词（参数化 `status = #{fromStatus}` 或字面量 `status = 'x'` / `status IN (…)`）。 */
    private static final Pattern STATUS_PREDICATE =
            Pattern.compile("status\\s*(=\\s*(#\\{|')|IN\\s*\\()", Pattern.CASE_INSENSITIVE);
    private static final Pattern DELETED_PREDICATE =
            Pattern.compile("deleted\\s*=\\s*0", Pattern.CASE_INSENSITIVE);
    /** Java 控制结构关键字：`if (…) {` 在行形态上与「方法 + 体」同形，靠名字排除。 */
    private static final String MEMBER_INDENT = "    ";
    /** Java 控制结构关键字：`if (…) {` 在行形态上与「方法 + 体」同形，靠名字排除。 */
    private static final Set<String> CONTROL_KEYWORDS = Set.of(
            "if", "for", "while", "switch", "catch", "synchronized", "try", "do", "else", "return");

    private static final ObjectMapper JSON = new ObjectMapper();

    // ────────────────────────────────────────────── 判据 1~6：真语料

    @Test
    @DisplayName("扫描器非空跑自证：现取写 status 的 mapper SQL 与两条 service 的写路径必须含核心对象")
    void scannersAreNotBlind() throws IOException {
        List<String> mapperMethods = mapperStatusWrites(mapperText()).stream().map(MapperWrite::method).toList();
        List<String> servicePaths = new ArrayList<>();
        for (String file : List.of(SERVICE_FILE, ORDER_SERVICE_FILE)) {
            servicePaths.addAll(serviceStatusWritePaths(serviceText(file), file));
        }

        System.out.println("[READING MC-101 扫描器] 写 status 的 mapper 方法=" + mapperMethods
                + " service 写路径=" + servicePaths);
        assertThat(mapperMethods)
                .as("扫描器必须现取到写 status 的 mapper 手写 SQL（返回空集 = 判据失明，不是通过）")
                .contains("markCompletedIfActive", "markInProcessingIfFrom", "markStatusIfFrom");
        assertThat(servicePaths)
                .as("扫描器必须现取到两条 service 里写状态列的调用点（含 OrderService —— 本单第二个写面就在那里）")
                .contains("ProcessingOrderService#updateStatus", "OrderService#cancelOrder");
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
        System.out.println("[READING MC-101 谓词] 状态写面="
                + writes.stream().map(MapperWrite::method).toList() + " 违规=" + offenders);
        assertThat(offenders).as("状态迁移的写必须把判断与写入压进同一条语句（无谓词写 = #6955 的病根）")
                .isEmpty();
    }

    @Test
    @DisplayName("状态迁移写路径不得使用无谓词 updateById（必须走条件更新 CAS）")
    void noStatusWritePathUsesUnconditionalUpdateById() throws IOException {
        List<String> offenders = new ArrayList<>();
        for (String file : List.of(SERVICE_FILE, ORDER_SERVICE_FILE)) {
            String owner = ownerOf(file);
            offenders.addAll(serviceStatusWriteCandidates(serviceText(file)).stream()
                    .filter(m -> UNCONDITIONAL_UPDATE_BY_ID.matcher(m.body()).find())
                    .map(m -> owner + "#" + m.name())
                    .toList());
        }
        System.out.println("[READING MC-101 无谓词写] 现取候选方法="
                + allServiceWritePaths() + " 违规=" + offenders);
        assertThat(offenders)
                .as("状态迁移的写必须带谓词（#6955 的病根就是 updateStatus / cancelOrder 用了无谓词 updateById）")
                .isEmpty();
    }

    @Test
    @DisplayName("service 写路径未登记即红 + 台账不许给不存在的对象盖章 + 豁免只许缩短 + 不许空转")
    void serviceWritePathsAreRegisteredAndLedgerIsFaithful() throws IOException {
        JsonNode ledger = ledger();
        List<String> servicePaths = allServiceWritePaths();
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

        System.out.println("[READING MC-101 台账] 现取写路径=" + servicePaths + " 已登记=" + registered
                + " 未登记=" + unregistered + " 幽灵条目=" + ghosts
                + " mapper 条目=" + entries + " 豁免=" + unverified + "(基线 " + baseline + ")");
        assertThat(unregistered)
                .as("新增状态迁移写路径必须登记进台账 —— 未登记就是「下一个 #6955」")
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
                } else if (!Files.readString(file, StandardCharsets.UTF_8).contains(symbol)) {
                    broken.add(label + " 右侧锚在文件里找不到：" + symbol);
                }
            }
        }
        System.out.println("[READING MC-101 兑现] 断链=" + broken);
        assertThat(broken).as("evidence 必须逐字兑现（摘掉 CAS 调用 / 方法改名 ⇒ 当场红）").isEmpty();
    }

    // ────────────────────────────────────────────── 判据 7：合成语料判别力自证

    @Test
    @DisplayName("判别力自证（合成语料）：六种坏形态各自判红、合规语料判绿、只改注释不红")
    void guardHasDiscriminatingPower() {
        // 合规：与真源码同形的三条 CAS + 两条调用点（跨两条 service）
        String goodMapper = mapperCorpus(
                "int markCompletedIfActive(@Param(\"id\") String id);",
                "UPDATE processing_orders SET status = 'completed', completed_at = #{completedAt} "
                        + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
                        + "AND status IN ('generated','issued','in_processing','completed')",
                "int markInProcessingIfFrom(@Param(\"id\") String id);",
                "UPDATE processing_orders SET status = 'in_processing' WHERE id = #{id} "
                        + "AND tenant_id = #{tenantId} AND deleted = 0 AND status = #{fromStatus}",
                "int markStatusIfFrom(@Param(\"id\") String id);",
                "UPDATE processing_orders SET status = #{targetStatus}, updated_at = #{now} "
                        + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
                        + "AND status = #{fromStatus}");
        String goodService = serviceCorpus("ProcessingOrderService", "updateStatus",
                "processingOrderMapper.markStatusIfFrom(id, tenantId, current, target, null, null, null, null, null, null, null, now);")
                + serviceCorpus("OrderService", "cancelOrder",
                "processingOrderMapper.markStatusIfFrom(activePo.getId(), tenantId, \"generated\", \"cancelled\", null, null, null, null, null, now, reason, now);");
        Map<String, String> registered = new LinkedHashMap<>();
        registered.put("ProcessingOrderService#updateStatus", "processingOrderMapper.markStatusIfFrom(");
        registered.put("OrderService#cancelOrder", "processingOrderMapper.markStatusIfFrom(");

        assertThat(problems(goodMapper, goodService, registered))
                .as("合规语料判绿（否则本守卫是恒红噪声）").isEmpty();

        // 坏形态 ①：无谓词状态写（= #6955 的病根本体）
        // 坏形态 ①：无谓词状态写（= #6955 的病根本体）
        assertThat(problems(mapperCorpus("int markStatusIfFrom(@Param(\"id\") String id);",
                        "UPDATE processing_orders SET status = #{targetStatus} WHERE id = #{id}"),
                goodService, registered))
                .as("无谓词状态写必须判红").isNotEmpty();

        // 坏形态 ②：缺 deleted = 0（软删的单也能被写）
        assertThat(problems(mapperCorpus("int markStatusIfFrom(@Param(\"id\") String id);",
                        "UPDATE processing_orders SET status = #{targetStatus} WHERE id = #{id} "
                                + "AND tenant_id = #{tenantId} AND status = #{fromStatus}"),
                goodService, registered))
                .as("缺 deleted=0 必须判红").isNotEmpty();

        // 坏形态 ③：缺 tenant 谓词（跨租户可写）
        assertThat(problems(mapperCorpus("int markStatusIfFrom(@Param(\"id\") String id);",
                        "UPDATE processing_orders SET status = #{targetStatus} WHERE id = #{id} "
                                + "AND status = #{fromStatus} AND deleted = 0"),
                goodService, registered))
                .as("缺 tenant 谓词必须判红").isNotEmpty();

        // 坏形态 ④：缺 WHERE 侧 status 谓词（只有 SET 侧赋值 = 无条件迁移，正是本单病根）
        assertThat(problems(mapperCorpus("int markStatusIfFrom(@Param(\"id\") String id);",
                        "UPDATE processing_orders SET status = #{targetStatus} WHERE id = #{id} "
                                + "AND tenant_id = #{tenantId} AND deleted = 0"),
                goodService, registered))
                .as("缺 WHERE 侧 status 谓词必须判红").isNotEmpty();

        // 坏形态 ⑤：service 新加一条未登记的状态写路径
        assertThat(problems(goodMapper, goodService
                        + serviceCorpus("OrderService", "reopenOrder",
                        "processingOrderMapper.updateById(order);"), registered))
                .as("未登记的状态迁移写路径必须判红（这就是「只修一处」的复发形态）").isNotEmpty();

        // 坏形态 ⑤b：最隐蔽的一种 —— **锚串留着**（`if (false && …markStatusIfFrom(…)`），
        //            真正落库的换成无谓词 updateById ⇒ 必须仍然判红（实证：只判锚会被它骗过去）
        String anchorKeptButUnconditional = goodService + serviceCorpus("ProcessingOrderService", "updateStatus2",
                "if (false && processingOrderMapper.markStatusIfFrom(id, 1L, \"a\", \"b\", null, null, null, null, null, null, null, null) == 0) { }\n"
                        + "        processingOrderMapper.updateById(order);");
        assertThat(problems(goodMapper, anchorKeptButUnconditional, registered))
                .as("锚还在但真正落库的是无谓词 updateById ⇒ 必须判红（判据的主张本体是 CAS，不是锚）")
                .isNotEmpty();

        // 坏形态 ⑥：台账未兑现（CAS 调用被摘掉 / 改名）
        assertThat(problems(goodMapper,
                        goodService.replace("processingOrderMapper.markStatusIfFrom(",
                                "processingOrderMapper.someOtherWrite("), registered))
                .as("台账锚被摘掉必须判红").isNotEmpty();

        // 反向对照：只改注释 ⇒ 不红
        assertThat(problems(goodMapper,
                        "// 注释里提一句 processingOrderMapper.updateById(order)\n" + goodService, registered))
                .as("只加注释不得判红（否则守卫被自己的文案喂红）").isEmpty();

        // 🔴 扫描器鲁棒性自证（两条**实证过**的失明形态，见 membersWithBody 的 javadoc）：
        //   ① 跨行签名（收尾 `) {` 在续行上）：`updateStatus` 的真实签名就是这样 —— 只认「签名行含 `) {`」
        //      会把整个方法跳过、深度从此下沉一级 ⇒ 后面全部扫不到；② javadoc 里的**孤立 `{`**：
        //      花括号计数器把它当真代码 ⇒ 从此整体错位（真实文件第一处就在 `{@code route = [`）。
        String multiLineSignature = "public class Svc {\n"
                + "    @Transactional\n"
                + "    public void updateStatus(String rawId, Req req,\n"
                + "                             Long tenantId) {\n"
                + "        processingOrderMapper.markStatusIfFrom(rawId, tenantId);\n"
                + "    }\n}\n";
        Map<String, String> multiLineRegistered = new LinkedHashMap<>();
        multiLineRegistered.put("Svc#updateStatus", "processingOrderMapper.markStatusIfFrom(");
        assertThat(problems(goodMapper, multiLineSignature, multiLineRegistered))
                .as("跨行签名必须仍被扫到（否则整个方法被静默跳过 ⇒ 深度错位 ⇒ 后面的写路径全部漏判）")
                .isEmpty();
        assertThat(problems(goodMapper, multiLineSignature.replace(
                        "processingOrderMapper.markStatusIfFrom(rawId, tenantId);",
                        "processingOrderMapper.updateById(order);"), multiLineRegistered))
                .as("跨行签名的方法里落库换成无谓词 updateById ⇒ 必须判红（证明它真的被扫到了）")
                .isNotEmpty();
        assertThat(problems(goodMapper,
                        "/** 例：{@code route = [op for op in route} 半个花括号 */\n" + goodService, registered))
                .as("注释里的孤立 `{` 不得让深度错位（否则深度下沉、后续方法全部扫不到）")
                .isEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真源码与合成语料共用）

    /**
     * 一次判定：返回问题清单（空 = 合规）。真源码与合成语料走**同一套**判定本体。
     *
     * <p>{@code registered} 的键 = 写路径的 {@code <类>#<方法>}，值 = 该路径必须**逐字出现**的调用锚
     * （如 {@code processingOrderMapper.markStatusIfFrom(}）。「以 CAS 收口」这条主张只有在锚真的在
     * 方法体里时才成立 —— 退回无谓词 {@code updateById} ⇒ 锚消失 ⇒ 当场红。</p>
     *
     * <p>合成语料里 `public class A {…}` 与 `public class B {…}` 会被拼成同一段文本 ⇒ 判定本体必须
     * 用「方法名」而不是「类名」索引候选（台账键里的 {@code <类>#} 前缀只用于**报读可读性**，
     * 参与匹配的是去前缀后的方法名）。</p>
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
        for (MethodBody m : membersWithBody(serviceText)) {
            if (UNCONDITIONAL_UPDATE_BY_ID.matcher(m.body()).find()
                    || MAPPER_CAS_CALL.matcher(m.body()).find()) {
                candidates.put(bareMethod(m.name()), m);
            }
        }
        Set<String> registeredBare = registered.keySet().stream()
                .map(ProcessingOrderStatusCasMetaGuardTest::bareMethod).collect(Collectors.toSet());
        for (Map.Entry<String, MethodBody> e : candidates.entrySet()) {
            if (!registeredBare.contains(e.getKey())) {
                problems.add("service 未登记的状态写路径: " + e.getKey());
            }
            // 🔴 本守卫的**主张本体**：状态迁移必须走条件更新（CAS）。
            //    无谓词 updateById 即使「同时也调了 markXxx」也必须红 —— 否则只要把调用留着、
            //    真正落库的换成 updateById，判据就会被一句 `if (false && …)` 骗过去（#6928 实证过）。
            if (UNCONDITIONAL_UPDATE_BY_ID.matcher(e.getValue().body()).find()) {
                problems.add("状态写路径里出现了无谓词 updateById（必须走 CAS）: " + e.getKey());
            }
        }
        for (Map.Entry<String, String> r : registered.entrySet()) {
            MethodBody body = candidates.get(bareMethod(r.getKey()));
            if (body == null) {
                problems.add("台账给不存在的写路径盖章: " + r.getKey());
            } else if (r.getValue() != null && !body.body().contains(r.getValue())) {
                problems.add("写路径未兑现：主张的 " + r.getKey() + " 收口锚不在方法体里（" + r.getValue() + "）");
            }
        }
        return problems;
    }

    /** 台账键 / 读数键的形态是 {@code <类>#<方法>} ⇒ 参与匹配的一律是 {@code #} **之后**那一段。 */
    private static String bareMethod(String name) {
        int hash = name.indexOf('#');
        return hash < 0 ? name : name.substring(hash + 1);
    }

    /** 现取：mapper 里**在 SET 侧写 {@code status}** 的手写 SQL（方法名 + SQL 文本）。 */
    private static List<MapperWrite> mapperStatusWrites(String mapperText) {
        List<MapperWrite> out = new ArrayList<>();
        Matcher m = UPDATE_ANNOTATION.matcher(mapperText);
        while (m.find()) {
            String sql = toSql(m.group(1));
            String upper = sql.toUpperCase();
            if (!upper.contains("UPDATE " + TABLE.toUpperCase()) || !writesStatusColumn(sql)) {
                continue;
            }
            out.add(new MapperWrite(methodAfter(mapperText, m.end()), sql));
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
     * <p>⚠️ 实现口径（MC-100 踩过的坑，写在这里免得下一个人再踩）：**逐行扫描 + 花括号深度**，
     * 不靠「缩进 + 标识符 + 一对复杂正则」——后者曾把整个判据变成**静默失明**（候选集恒为空，
     * 而空集在结果列上看着像「通过」）。行扫描只看三条朴素事实：① 深度 == 1（类体顶层）；
     * ② 行首恰为 4 空格缩进（8/12 ⇒ 控制结构 / lambda）；③ 行内含 {@code ") {"}（签名收尾）
     * 且不是注释 / 注解行。名字取「第一个 `(` 之前的最后一段」。</p>
     */
    /**
     * 现取：{@code service} 文本里「类体顶层的方法 + 其方法体」。
     *
     * <p>⚠️ 实现口径（本判据踩过的两个坑，写在这里免得下一个人再踩）：</p>
     * <ol>
     *   <li><b>逐行扫描 + 花括号深度</b>，不靠「缩进 + 标识符 + 一对复杂正则」——后者曾把整个判据
     *       变成<b>静默失明</b>（候选集恒为空，而空集在结果列上看着像「通过」）。</li>
     *   <li>🔴 <b>必须支持跨行签名</b>（本判据**初版实测**踩到）：`updateStatus` 的签名是
     *       `public ProcessingOrderResponse updateStatus(String rawId, ProcessingOrderUpdateRequest req,`
     *       ⏎ `…Long tenantId, String operator) {` —— 收尾的 {@code ") {"} 落在**续行**上。
     *       只认「签名行含 `) {`」的写法会把**整个方法**跳过，而它的闭合花括号照样把深度减 1
     *       ⇒ 深度从此**下沉一级** ⇒ 后面所有方法全部扫不到；更坏的是「候选集非空但少了核心对象」，
     *       判据 1 若只检查别的对象就**照样绿**（这正是本单在 MC-101 上抓到的第二种失明形态）。
     *       ⇒ 改成**待定签名**状态机：见到「类体顶层 + 4 空格缩进 + `(` + 非注释/注解」先登记名字，
     *       到**第一个不深于类体的 `{`** 才正式开体、从花括号之后开始收正文。</li>
     *   <li>名字取「第一个 `(` 之前的最后一段」；控制结构关键字（{@code if}/{@code for}/…）不当签名。</li>
     * </ol>
     */
    private static List<MethodBody> membersWithBody(String text) {
        String clean = stripCommentsAndStrings(text);
        List<MethodBody> out = new ArrayList<>();
        int depth = 0;
        int baseDepth = 0;
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
                    if (body == null && pending != null && depth == baseDepth + 2) {
                        name = pending;
                        pending = null;
                        body = new StringBuilder();
                        activated = true;
                    }
                } else if (ch == '}') {
                    depth--;
                    if (depth == baseDepth + 1 && body != null) {
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
     * （如 {@code route = [op for op in route} 这类只有半个 `{` 的例子）⇒ 不剥就整体错位
     * ⇒ 后续方法全部扫不到（本判据初版实测，见 {@link #membersWithBody}）。</p>
     *
     * <p>为什么不直接上 AST / JavaParser：本仓既有形态是「读源码文本」，加解析器依赖会扩大本单的
     * 改动面与启动成本；一个 30 行的手写剥壳足够覆盖「注释 / 字面量里的括号」这一族
     * （判别力由 {@code guardHasDiscriminatingPower} 的「注释里的 `{`」用例自证）。</p>
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

    /** 现取：service 里**出现加工单状态列写**的方法（方法名 + 方法体）。 */
    private static List<MethodBody> serviceStatusWriteCandidates(String serviceText) {
        List<MethodBody> out = new ArrayList<>();
        for (MethodBody m : membersWithBody(serviceText)) {
            if (UNCONDITIONAL_UPDATE_BY_ID.matcher(m.body()).find()
                    || MAPPER_CAS_CALL.matcher(m.body()).find()) {
                out.add(m);
            }
        }
        return out;
    }

    /** 两条 service 文件的现取写路径清单（{@code <类>#<方法>}，报读与台账对账都用它）。 */
    private static List<String> allServiceWritePaths() throws IOException {
        List<String> out = new ArrayList<>();
        for (String file : List.of(SERVICE_FILE, ORDER_SERVICE_FILE)) {
            out.addAll(serviceStatusWritePaths(serviceText(file), file));
        }
        return out;
    }

    /** 现取：候选方法名清单（读数用；带 {@code <类>#} 前缀便于定位是哪个文件里漏登记了）。 */
    private static List<String> serviceStatusWritePaths(String serviceText, String file) {
        String owner = ownerOf(file);
        return serviceStatusWriteCandidates(serviceText).stream()
                .map(m -> owner + "#" + m.name()).toList();
    }

    /** 从仓库相对全路径取类名（台账 / 读数都用它，免得两处各写一份）。 */
    private static String ownerOf(String file) {
        String base = file.substring(file.lastIndexOf('/') + 1);
        return base.endsWith(".java") ? base.substring(0, base.length() - 5) : base;
    }

    private static String methodAfter(String text, int from) {
        Matcher m = Pattern.compile("\\s+(\\w+)\\s*\\(").matcher(text.substring(from));
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

    private static String serviceText(String file) throws IOException {
        return Files.readString(repoRoot().resolve(file), StandardCharsets.UTF_8);
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
