// case_ids: MC-100

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
 * 🧱 <b>类级元守卫（issue #6928）：入库单状态迁移的写路径必须落到 SQL 谓词（CAS），未登记即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code InboundOrderCancelRaceRealDbTest}）只保证 {@code InboundOrderService#cancel}
 * 这**一个**入口在并发下与 {@code #post} 互斥。而 #6928 的真实教训是
 * <b>「同一个状态迁移权上有两个写面，只有一个带 CAS」</b>：{@code #post} 走条件更新（{@code markPosted}），
 * {@code #cancel} 走「先读 status 判 draft、再 {@code updateById}（WHERE 仅主键 ⇒ 无谓词）」⇒ 两者
 * 不互斥，窗口里 post 抢到过账权并提交（库存 +N、台账 1 行），cancel 随后把该单覆写成 cancelled
 * —— 库存与入库台账静默留存（账实不符、无任何 4xx）。下一个人在**同文件新加一条状态迁移写路径**、
 * 或给 mapper 加一条**无谓词**的状态写 SQL，没有任何东西会红 ⇒ 本守卫把「写路径清单 + 谓词完整性」
 * 钉成机械判据。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：现取「写 {@code inbound_orders.status} 的 mapper SQL」必须包含
 *       {@code markPosted} 与 {@code markCancelled}；现取「service 里写状态列的调用点」必须包含
 *       {@code post} 与 {@code cancel}。候选集为空 / 少了核心对象 ⇒ 先红
 *       （形态被改名不是「通过」，而是「判据失明」）。</li>
 *   <li><b>mapper 状态写 SQL 必须带完整谓词</b>：凡在 SET 侧写 {@code status} 的手写 {@code @Update}
 *       SQL，必须同时含 {@code tenant_id} 参数、{@code status = 'draft'} 谓词、{@code deleted = 0}
 *       —— 少任何一条 ⇒ 红（退回「无谓词写」= 本单的病根）。</li>
 *   <li><b>service 写路径未登记即红</b>：任何方法体里出现「写状态列的调用」（{@code inboundOrderMapper.updateById(}
 *       或 {@code inboundOrderMapper.mark*(}）却不登记 ⇒ 红。</li>
 *   <li><b>台账不许给不存在的对象盖章</b>：每条 {@code entries[]} / {@code service_write_paths[]} 的
 *       {@code method} 必须仍能在现取候选集里找到（改名 / 删除 ⇒ 红）。</li>
 *   <li><b>登记未被兑现即红</b>：{@code evidence} = {@code <仓库相对路径>::<可检索文本>}，
 *       左侧文件必须存在、右侧必须在该文件里<b>逐字出现</b> ⇒ 防「给不存在的保护盖章」
 *       （摘掉 CAS 调用 / 方法改名 ⇒ 红）。</li>
 *   <li><b>豁免台账只许缩短</b>：{@code unverified} 必须是冻结基线 {@code unverified_baseline}
 *       的<b>子集</b>（新增豁免 ⇒ 红）；条数<b>现取</b>（不写死在测试代码里，读数打印在断言消息上）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>在内存里跑与真实源码<b>同一套</b>判定本体 ——
 *       「无谓词状态写」「缺 {@code deleted=0}」「缺 tenant 谓词」「未登记写路径」「台账未兑现」
 *       五种坏形态各自判红，合规语料判绿。没有这条，「判据恒绿」与「判据有效」在结果列上长得一样。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST）—— 本仓既有形态（{@code OrderAutoCompleteSqlGuardTest} /
 * {@code StockDeductionAndLedgerAtomicityMetaGuardTest} 同款）。代价：它只能证明「这几个字在方法体里」；
 * <b>行为面由真库并发判据承担</b>：{@code InboundOrderCancelRaceRealDbTest}（#6928）与
 * {@code InboundPostConcurrentRealDbTest}（#6237）—— 三者缺一不可
 * （{@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在）。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账 {@code coverage_boundary} ——
 * ① 形态判据换措辞可绕过（真实防线仍是各自的实例判据）；② 射程只到
 * {@code InboundOrderService} + {@code InboundOrderMapper} 这一对文件（别的租户数据类型的
 * 状态迁移不在本表射程）；③ 判不了「拿 {@code updateById} 改**非状态**列」（那不是本表的对象）；
 * ④ 本守卫<b>不</b>跑被它引用的那条真库判据（否则「未登记即红」会退化成全量套件再跑一遍）；
 * ⑤ 本守卫<b>不改</b>任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6928）：入库单状态迁移写路径必须落到 SQL 谓词（未登记即红 + 豁免只许缩短）")
class InboundOrderStatusCasMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）；台账里的引用一律是**仓库相对全路径**。 */
    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String MAPPER_FILE = MAIN + "/mapper/InboundOrderMapper.java";
    private static final String SERVICE_FILE = MAIN + "/service/InboundOrderService.java";
    private static final String LEDGER_PATH =
            MODULE + "/src/test/resources/inbound-order-status-cas-ledger.json";

    // ── 形态（与台账 scan 段的声明逐字对应）

    /** 手写 update 注解的**取块**（到配对的 `)` 为止；SQL 自带括号 ⇒ 先取块再剥 Java 语法）。 */
    private static final Pattern UPDATE_ANNOTATION =
            Pattern.compile("@Update\\s*\\(((?:[^()]|\\([^()]*\\))*)\\)");
    /** 写面表名。 */
    private static final String TABLE = "inbound_orders";
    /** 「状态列写」的两种调用形态。 */
    private static final Pattern INBOUND_UPDATE_BY_ID =
            Pattern.compile("inboundOrderMapper\\.updateById\\(");
    /** 该 mapper 的手写状态迁移写面（现取，不写死）：`inboundOrderMapper.markXxx(`。 */
    private static final Pattern MAPPER_CAS_CALL = Pattern.compile("inboundOrderMapper\\.(mark\\w+)\\(");
    /** 谓词 / 参数要求（issue #6928 的口径）。 */
    private static final Pattern TENANT_PARAM =
            Pattern.compile("#\\{\\s*tenantI?d\\s*\\}", Pattern.CASE_INSENSITIVE);
    private static final Pattern DRAFT_PREDICATE =
            Pattern.compile("status\\s*=\\s*'draft'", Pattern.CASE_INSENSITIVE);
    private static final Pattern DELETED_PREDICATE =
            Pattern.compile("deleted\\s*=\\s*0", Pattern.CASE_INSENSITIVE);
    /** 方法体收尾形态（`… ) {`）：真方法的长签名可跨行 ⇒ 判「签名行」时只看「出现 `) {`」。 */
    private static final String BODY_OPEN = ") {";
    /** 类体顶层的缩进（4 空格）；嵌套块（控制结构 / lambda）更深 ⇒ 靠它把方法从体内区分出来。 */
    private static final String MEMBER_INDENT = "    ";
    /** Java 控制结构关键字：`if (…) {` 在行形态上与「方法 + 体」同形，靠名字排除。 */
    private static final Set<String> CONTROL_KEYWORDS = Set.of(
            "if", "for", "while", "switch", "catch", "synchronized", "try", "do", "else", "return");

    private static final ObjectMapper JSON = new ObjectMapper();

    // ────────────────────────────────────────────── 判据 1~6：真语料

    @Test
    @DisplayName("扫描器非空跑自证：现取写 status 的 mapper SQL 与 service 写路径必须包含核心对象")
    void scannersAreNotBlind() throws IOException {
        List<String> mapperMethods = mapperStatusWrites(mapperText()).stream().map(MapperWrite::method).toList();
        List<String> servicePaths = serviceStatusWritePaths(serviceText());

        System.out.println("[READING MC-100 扫描器] 写 status 的 mapper 方法=" + mapperMethods
                + " service 写路径=" + servicePaths);
        assertThat(mapperMethods)
                .as("扫描器必须现取到写 status 的 mapper 手写 SQL（返回空集 = 判据失明，不是通过）")
                .contains("markPosted", "markCancelled");
        assertThat(servicePaths)
                .as("扫描器必须现取到 service 里写状态列的调用点（返回空集 = 判据失明，不是通过）")
                .contains("post", "cancel");
    }

    @Test
    @DisplayName("mapper 状态写 SQL 必须带完整谓词（tenant_id + status='draft' + deleted=0）")
    void everyStatusWriteCarriesTheFullPredicate() throws IOException {
        List<MapperWrite> writes = mapperStatusWrites(mapperText());
        List<String> offenders = new ArrayList<>();
        for (MapperWrite w : writes) {
            List<String> missing = new ArrayList<>();
            if (!TENANT_PARAM.matcher(w.sql()).find()) {
                missing.add("tenant_id 参数");
            }
            if (!DRAFT_PREDICATE.matcher(w.sql()).find()) {
                missing.add("status='draft' 谓词");
            }
            if (!DELETED_PREDICATE.matcher(w.sql()).find()) {
                missing.add("deleted=0 谓词");
            }
            if (!missing.isEmpty()) {
                offenders.add(w.method() + " 缺 " + missing);
            }
        }
        System.out.println("[READING MC-100 谓词] 状态写面="
                + writes.stream().map(MapperWrite::method).toList() + " 违规=" + offenders);
        assertThat(offenders).as("状态迁移的写必须把判断与写入压进同一条语句（无谓词写 = #6928 的病根）")
                .isEmpty();
    }

    @Test
    @DisplayName("service 写路径未登记即红 + 台账不许给不存在的对象盖章 + 豁免只许缩短")
    void serviceWritePathsAreRegisteredAndLedgerIsFaithful() throws IOException {
        JsonNode ledger = ledger();
        List<String> servicePaths = serviceStatusWritePaths(serviceText());
        Map<String, String> registered = new LinkedHashMap<>();
        for (JsonNode e : ledger.get("service_write_paths")) {
            registered.put(e.get("method").asText(), e.get("call_anchor").asText());
        }
        Set<String> registeredBare = registered.keySet().stream()
                .map(InboundOrderStatusCasMetaGuardTest::bareMethod)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        List<String> unregistered = servicePaths.stream().filter(p -> !registeredBare.contains(p)).toList();
        List<String> ghosts = registeredBare.stream()
                .filter(r -> !servicePaths.contains(r)).toList();
        int unverified = ledger.get("unverified").size();
        int baseline = ledger.get("unverified_baseline").asInt();

        System.out.println("[READING MC-100 台账] 现取写路径=" + servicePaths + " 已登记=" + registered
                + " 未登记=" + unregistered + " 幽灵条目=" + ghosts
                + " 豁免=" + unverified + "(基线 " + baseline + ")");
        assertThat(unregistered)
                .as("新增状态迁移写路径必须登记进台账 —— 未登记就是「下一个 #6928」")
                .isEmpty();
        assertThat(ghosts).as("台账不许给不存在的写路径盖章（改名 / 删除 ⇒ 红）").isEmpty();
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
        System.out.println("[READING MC-100 兑现] 断链=" + broken);
        assertThat(broken).as("evidence 必须逐字兑现（摘掉 CAS 调用 / 方法改名 ⇒ 当场红）").isEmpty();
    }

    @Test
    @DisplayName("状态迁移写路径不得使用无谓词 updateById（必须走条件更新 CAS）")
    void noStatusWritePathUsesUnconditionalUpdateById() throws IOException {
        List<String> offenders = serviceStatusWriteCandidates(serviceText()).stream()
                .filter(m -> INBOUND_UPDATE_BY_ID.matcher(m.body()).find())
                .map(MethodBody::name)
                .toList();
        System.out.println("[READING MC-100 无谓词写] 现取候选方法=" + serviceStatusWritePaths(serviceText())
                + " 违规=" + offenders);
        assertThat(offenders)
                .as("状态迁移的写必须带谓词（#6928 的病根就是 cancel 用了无谓词 updateById）")
                .isEmpty();
    }

    // ────────────────────────────────────────────── 判据 7：合成语料判别力自证

    @Test
    @DisplayName("判别力自证（合成语料）：五种坏形态各自判红、合规语料判绿")
    void guardHasDiscriminatingPower() {
        // 合规：与真源码同形的两条 CAS + 两条调用点
        String goodMapper = mapperCorpus(
                "int markPosted(@Param(\"id\") String id);",
                "UPDATE inbound_orders SET status = 'posted', posted_at = #{postedAt}, posted_by = #{operator}, "
                        + "updated_at = NOW() WHERE id = #{id} AND tenant_id = #{tenantId} "
                        + "AND status = 'draft' AND deleted = 0",
                "int markCancelled(@Param(\"id\") String id);",
                "UPDATE inbound_orders SET status = 'cancelled', cancelled_at = #{cancelledAt}, "
                        + "cancelled_by = #{operator}, cancelled_reason = #{reason}, updated_at = NOW() "
                        + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'draft' AND deleted = 0");
        String goodService = serviceCorpus("post",
                "inboundOrderMapper.markPosted(order.getId(), tenantId, operator, now);")
                + serviceCorpus("cancel",
                "inboundOrderMapper.markCancelled(order.getId(), tenantId, operator, reason, now);");
        Map<String, String> registered = new LinkedHashMap<>();
        registered.put("post", "inboundOrderMapper.markPosted(");
        registered.put("cancel", "inboundOrderMapper.markCancelled(");

        assertThat(problems(goodMapper, goodService, registered))
                .as("合规语料判绿（否则本守卫是恒红噪声）").isEmpty();

        // 坏形态 ①：无谓词状态写（= #6928 的病根本体）
        assertThat(problems(mapperCorpus("int markCancelled(@Param(\"id\") String id);",
                        "UPDATE inbound_orders SET status = 'cancelled' WHERE id = #{id}"),
                goodService, registered))
                .as("无谓词状态写必须判红").isNotEmpty();

        // 坏形态 ②：缺 deleted = 0（软删的单也能被写）
        assertThat(problems(mapperCorpus("int markPosted(@Param(\"id\") String id);",
                        "UPDATE inbound_orders SET status = 'posted' WHERE id = #{id} AND tenant_id = #{tenantId} "
                                + "AND status = 'draft'"),
                goodService, registered))
                .as("缺 deleted=0 必须判红").isNotEmpty();

        // 坏形态 ③：缺 tenant 谓词（跨租户可写）
        assertThat(problems(mapperCorpus("int markPosted(@Param(\"id\") String id);",
                        "UPDATE inbound_orders SET status = 'posted' WHERE id = #{id} AND status = 'draft' "
                                + "AND deleted = 0"),
                goodService, registered))
                .as("缺 tenant 谓词必须判红").isNotEmpty();

        // 坏形态 ④：service 新加一条未登记的状态写路径
        assertThat(problems(goodMapper, goodService + serviceCorpus("reopen",
                        "inboundOrderMapper.updateById(order);"), registered))
                .as("未登记的状态迁移写路径必须判红（这就是「只修一处」的复发形态）").isNotEmpty();

        // 坏形态 ④b：最隐蔽的一种 —— **锚串留着**（`if (false && …markCancelled(…)`），
        //            真正落库的换成无谓词 updateById ⇒ 必须仍然判红（实证：只判锚会被它骗过去）
        String anchorKeptButUnconditional = goodService.replace(
                "inboundOrderMapper.markCancelled(",
                "inboundOrderMapper.markCancelled(") + serviceCorpus("cancel2",
                "if (false && inboundOrderMapper.markCancelled(id, 1L, \"op\", \"r\", null) == 0) { }\n"
                        + "        inboundOrderMapper.updateById(order);");
        assertThat(problems(goodMapper, anchorKeptButUnconditional, registered))
                .as("锚还在但真正落库的是无谓词 updateById ⇒ 必须判红（判据的主张本体是 CAS，不是锚）")
                .isNotEmpty();

        // 坏形态 ⑤：台账未兑现（CAS 调用被摘掉 / 改名）
        assertThat(problems(goodMapper,
                        goodService.replace("inboundOrderMapper.markCancelled(",
                                "inboundOrderMapper.someOtherWrite("), registered))
                .as("台账锚被摘掉必须判红").isNotEmpty();

        // 反向对照：只改注释 ⇒ 不红
        assertThat(problems(goodMapper,
                        "// 注释里提一句 inboundOrderMapper.updateById(order)\n" + goodService, registered))
                .as("只加注释不得判红（否则守卫被自己的文案喂红）").isEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真源码与合成语料共用）

    /**
     * 一次判定：返回问题清单（空 = 合规）。真源码与合成语料走**同一套**判定本体。
     *
     * <p>{@code registered} 的键 = 写路径的方法名（可带 {@code <类>#} 前缀），值 = 该路径必须**逐字出现**
     * 的调用锚（如 {@code inboundOrderMapper.markCancelled(}）。「以 `markXxx` 收口」这条主张只有在
     * 锚真的在方法体里时才成立 —— 退回无谓词 {@code updateById} ⇒ 锚消失 ⇒ 当场红。</p>
     */
    private static List<String> problems(String mapperText, String serviceText,
                                         Map<String, String> registered) {
        List<String> problems = new ArrayList<>();
        for (MapperWrite w : mapperStatusWrites(mapperText)) {
            if (!TENANT_PARAM.matcher(w.sql()).find()
                    || !DRAFT_PREDICATE.matcher(w.sql()).find()
                    || !DELETED_PREDICATE.matcher(w.sql()).find()) {
                problems.add("mapper 状态写缺谓词: " + w.method());
            }
        }
        Map<String, MethodBody> candidates = new LinkedHashMap<>();
        for (MethodBody m : serviceStatusWriteCandidates(serviceText)) {
            candidates.put(m.name(), m);
        }
        Set<String> registeredNames = registered.keySet().stream()
                .map(InboundOrderStatusCasMetaGuardTest::bareMethod)
                .collect(Collectors.toSet());
        for (Map.Entry<String, MethodBody> e : candidates.entrySet()) {
            if (!registeredNames.contains(e.getKey())) {
                problems.add("service 未登记的状态写路径: " + e.getKey());
            }
            // 🔴 本守卫的**主张本体**：状态迁移必须走条件更新（CAS）。
            //    无谓词 updateById 即使「同时也调了 markXxx」也必须红 —— 否则只要把调用留着、
            //    真正落库的换成 updateById，判据就会被一句 `if (false && …)` 骗过去（实证过）。
            if (INBOUND_UPDATE_BY_ID.matcher(e.getValue().body()).find()) {
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

    /** 台账里的写路径形态是 {@code <类>#<方法>} ⇒ 与现取的方法名比较前先归一。 */
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
     * <p>⚠️ 实现口径（本判据踩过的坑，写在这里免得下一个人再踩）：**逐行扫描 + 花括号深度**，
     * 不靠「缩进 + 标识符 + 一对复杂正则」——后者曾把整个判据变成**静默失明**（候选集恒为空，
     * 而空集在结果列上看着像「通过」）。行扫描只看三条朴素事实：① 深度 == 1（类体顶层）；
     * ② 行首恰为 4 空格缩进（8/12 ⇒ 控制结构 / lambda）；③ 行内含 {@code ") {"}（签名收尾）
     * 且不是注释 / 注解行。名字取「第一个 `(` 之前的最后一段」。</p>
     */
    private static List<MethodBody> membersWithBody(String text) {
        List<MethodBody> out = new ArrayList<>();
        int depth = 0;
        String name = null;
        StringBuilder body = null;
        for (String raw : text.replace("\r", "").split("\n", -1)) {
            String trimmed = raw.strip();
            boolean signatureLine = depth == 1
                    && raw.startsWith(MEMBER_INDENT) && !raw.startsWith(MEMBER_INDENT + " ")
                    && trimmed.contains(BODY_OPEN) && trimmed.contains("(")
                    && !trimmed.startsWith("*") && !trimmed.startsWith("//") && !trimmed.startsWith("@");
            if (signatureLine) {
                String head = trimmed.substring(0, trimmed.indexOf('('));
                int sp = head.lastIndexOf(' ');
                String candidate = (sp < 0 ? head : head.substring(sp + 1)).strip();
                if (!candidate.isEmpty() && !CONTROL_KEYWORDS.contains(candidate)) {
                    name = candidate;
                    body = new StringBuilder();
                }
            } else if (body != null) {
                body.append(raw).append('\n');
            }
            for (int i = 0; i < raw.length(); i++) {
                char ch = raw.charAt(i);
                if (ch == '{') {
                    depth++;
                } else if (ch == '}') {
                    depth--;
                    if (depth == 1 && body != null) {
                        out.add(new MethodBody(name, body.toString()));
                        body = null;
                        name = null;
                    }
                }
            }
        }
        return out;
    }

    /** 现取：service 里**出现状态列写**的方法（方法名 + 方法体）。 */
    private static List<MethodBody> serviceStatusWriteCandidates(String serviceText) {
        List<MethodBody> out = new ArrayList<>();
        for (MethodBody m : membersWithBody(serviceText)) {
            if (INBOUND_UPDATE_BY_ID.matcher(m.body()).find() || MAPPER_CAS_CALL.matcher(m.body()).find()) {
                out.add(m);
            }
        }
        return out;
    }

    /** 现取：候选方法名清单（读数用）。 */
    private static List<String> serviceStatusWritePaths(String serviceText) {
        return serviceStatusWriteCandidates(serviceText).stream().map(MethodBody::name).toList();
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

    private static String serviceCorpus(String method, String methodBody) {
        return "public class X {\n    public void " + method + "(String id) {\n        "
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
