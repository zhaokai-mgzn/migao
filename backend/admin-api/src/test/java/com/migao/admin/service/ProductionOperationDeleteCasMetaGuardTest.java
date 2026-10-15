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
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
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
    /** 写面本体（mapper 侧）：工序矩阵行的**软删写面**在这里，PG-075 的射程必须覆盖它（issue #6956 · 洞 B）。 */
    private static final String POSITION_MAPPER = MAIN + "/mapper/ProductionOperationPositionMapper.java";
    private static final String LEDGER_PATH =
            MODULE + "/src/test/resources/production-operation-delete-cas-ledger.json";

    /** 软删写点（两种现取形态）：① 内联链 `.set(Production…::getDeleted, 1)`；② 写面本体（mapper 侧）`…Mapper.softDelete(`。 */
    private static final Pattern SET_DELETED = Pattern.compile(
            "\\.set\\(\\s*Production\\w*::getDeleted\\s*,\\s*1\\s*\\)|\\w*[Mm]apper\\.softDelete\\s*\\(");
    /** 写面本体调用（谓词在另一个文件里 ⇒ 谓词完整性由 mapper 侧判据核，不在本侧核）。 */
    private static final Pattern PRIMITIVE_CALL = Pattern.compile("\\w*[Mm]apper\\.softDelete\\s*\\(");
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
    /**
     * 签名归一（issue #6956 · 洞 B）：类体顶层、以**修饰符**开头的行 = 可能的签名起点 ——
     * 旧实现逐行全匹配 {@code ^ {4}(修饰符)…\) \{…$} ⇒ **签名跨行**的方法整个取不到
     * （实证：{@code cascadeSoftDeleteCells} 的签名跨两行 ⇒ 写点从现取集里消失）。
     */
    private static final Pattern MEMBER_HEAD_START = Pattern.compile(
            "^ {4}(?:public|private|protected|static|final|default|synchronized|abstract|native|strictfp)\\b");
    /** 归一后的签名行（{@link #METHOD_HEAD} 同款，但作用于「多行签名并成一行」的结果）。 */
    private static final Pattern METHOD_HEAD_NORMALIZED = Pattern.compile(
            "^ {4}(?:public|private|protected|static|final|default|synchronized|abstract|native|strictfp)\\b"
                    + "[^\\n]*\\([^;{]*\\)\\s*\\{\\s*$");
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
        List<String> offenders = predicateOffenders(sites);
        System.out.println("[READING PG-075 写点] 写 deleted 列的方法=" + methods
                + " 违规=" + offenders + " 未判影响行数=" + unguardedWriteMethods(service, writeFacePrimitivesFromLedger()));

        assertThat(methods)
                .as("扫描器必须现取到写 deleted 列的 service 方法（空集 = 判据失明，不是通过）；实测=" + methods)
                .contains("delete", "deleteDetaching");
        // 🔴 冻结锚（issue #6956 · 洞 B）：**签名跨行**的级联软删必须在现取集里 ——
        //    修前它整个取不到（「签名必须一行收尾」）⇒ 该写点无人认领。少收集一个方法**不是通过**，是失明。
        assertThat(methods)
                .as("换行签名的级联软删方法必须在现取集里（洞 B 的冻结锚；少了它 = 归一化失效）")
                .contains("cascadeSoftDeleteCells");
        // 🔴 射程扩到**写面本体**（mapper 侧）：矩阵行软删写面必须被现取到（修前它在本表射程外）。
        List<String> mapperSites = deleteWriteSites(positionMapperText()).stream()
                .map(WriteSite::method).toList();
        System.out.println("[READING PG-075 写面本体] mapper 侧写点=" + mapperSites);
        assertThat(mapperSites)
                .as("写面本体（mapper 侧 `ProductionOperationPositionMapper::softDelete`）必须在射程内"
                        + "（它不是 service 文本，修前完全在射程外）")
                .contains("softDelete");
        assertThat(offenders)
                .as("写 deleted 列的条件更新必须带 id + tenant_id + deleted=0 三谓词，并保住 updated_at")
                .isEmpty();
        // 🔴 写面本体（mapper 侧）的谓词完整性：与 service 侧**同一套**判定本体、同一套口径。
        List<String> mapperOffenders = predicateOffenders(deleteWriteSites(positionMapperText()));
        System.out.println("[READING PG-075 写面本体谓词] mapper 侧违规=" + mapperOffenders);
        assertThat(mapperOffenders)
                .as("写面本体必须是**带完整三谓词 + 保住 updated_at** 的条件更新"
                        + "（它不是 service 文本；修前本表射程到不了这里 = 洞 B 的另一半）")
                .isEmpty();
        assertThat(unguardedWriteMethods(service, writeFacePrimitivesFromLedger()))
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
        assertThat(paths)
                .as("换行签名的级联软删方法必须在现取集里（issue #6956 · 洞 B 的冻结锚）")
                .contains("cascadeSoftDeleteCells");
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

        // 🔴 洞 B 的两条核心反转对照（issue #6956）：**同一语义、只增一个换行** ——
        //    旧实现逐行全匹配「签名一行收尾」⇒ 该方法的整个方法体取不到（写点静默消失）。
        String wrapped = multilineSignatureCorpus("cascadeSoftDeleteCells", cascadeCorpus());
        System.out.println("[READING PG-075 换行签名语料] 现取=" + serviceDeleteWriteMethods(wrapped)
                + " 问题清单=" + problems(wrapped));
        assertThat(methodsOf(wrapped))
                .as("换行签名的方法必须被收集（修前：现取集里没有它 —— 整个方法体从未被看见）")
                .contains("cascadeSoftDeleteCells");
        assertThat(problems(wrapped))
                .as("换行签名 + 合规写点 ⇒ 不红（换行本身不是罪：判红来自「写点/谓词」，不是「换行」）").isEmpty();
        // 🔴 洞 B 的核心反转对照：**同一语义、只增一个换行** —— 换行签名 + 无谓词写点 ⇒ 必红
        //    （修前：现取集里根本没有这个方法 ⇒ `problems()` 恒为「无问题」）
        assertThat(problems(multilineSignatureCorpus("cascadeSoftDeleteCells", bareCas())))
                .as("换行签名 + 无谓词写点（缺 deleted = 0）⇒ 必须判红；"
                        + "修前该读数恒为「无问题」（整个方法体从未被收集）").isNotEmpty();
        // 反向对照：把同一个无谓词写点放进**单行签名** ⇒ 同样必红（证明差异只在「换行」，不在写点本身）
        assertThat(problems(serviceCorpus("cascadeSoftDeleteCells", bareCas())))
                .as("同一写点放进单行签名同样必红（单变量对照：唯一的变量是「签名是否跨行」）").isNotEmpty();

        // 洞 B 第二条：**写面本体在另一个文件**（mapper 侧）也必须被现取到。
        //   ⚠️ `problems()` 的语义边界：它对**传进来的每段文本**取「写 deleted 列的调用点」并验谓词 ——
        //   service 文本里是内联链（谓词都在同一链上），mapper 侧是写面本体自身（同一个口径）。
        assertThat(problems(mapperSoftDeleteCorpus(
                ".eq(ProductionOperationPosition::getId, id)\n"
                        + "                .eq(ProductionOperationPosition::getTenantId, tenantId)\n"
                        + "                .set(ProductionOperationPosition::getDeleted, 1)\n"
                        + "                .set(ProductionOperationPosition::getUpdatedAt, updatedAt)));")))
                .as("写面本体（mapper 侧）缺 deleted = 0 谓词 ⇒ 必须判红（修前该文件完全在射程外）")
                .isNotEmpty();
        assertThat(problems(mapperSoftDeleteCorpus(
                ".eq(ProductionOperationPosition::getId, id)\n"
                        + "                .eq(ProductionOperationPosition::getTenantId, tenantId)\n"
                        + "                .eq(ProductionOperationPosition::getDeleted, 0)\n"
                        + "                .set(ProductionOperationPosition::getDeleted, 1)\n"
                        + "                .set(ProductionOperationPosition::getUpdatedAt, updatedAt)));")))
                .as("写面本体谓词齐全 ⇒ 判绿（写面本体**有意**不判自己返回的行数，那是调用方的活）").isEmpty();

        // 反向对照：只改注释 ⇒ 不红
        assertThat(problems(good.replace("删工序", "删工序（注释微调）")))
                .as("只改注释不得判红").isEmpty();
    }

    /** 现取的方法名清单（读数 / 断言用）。 */
    private static List<String> methodsOf(String text) {
        return serviceDeleteWriteMethods(text);
    }

    // ────────────────────────────────────────────── 判定本体（真语料与合成语料共用）

    /** 一处「写 deleted 列」的调用点：方法名 + 该软删写点之后 700 字符的链（谓词与判定都在这一段里）。 */
    private record WriteSite(String method, String chain, boolean primitive) {
    }

    private static final int CHAIN = 700;
    /** 写点**之前**要一起看的窗口（三谓词在 `.set(getDeleted, 1)` 之前 ⇒ 只看后面等于看不见谓词）。 */
    private static final int CHAIN_BACK = 600;

    /**
     * 判定本体：返回问题清单（空 = 合规）。合成语料与真语料**跑同一套**。
     *
     * <p>🔴 射程（issue #6956 · 洞 B）：传进来的文本**既可以是 service、也可以是 mapper** ——
     * 写面本体（{@code ProductionOperationPositionMapper::softDelete}）在 mapper 文件里，
     * 只扫 service 就等于把「判断与写入压进同一条语句」这条主张的**一半**留在射程外。</p>
     */
    private static List<String> problems(String text) {
        List<String> out = new ArrayList<>();
        for (WriteSite s : deleteWriteSites(text)) {
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
        for (String m : unguardedWriteMethods(text, writeFacePrimitivesFromLedger())) {
            out.add("service " + m + " 行写不判影响行数（0 行 ⇒ 必须 fail-closed）");
        }
        for (String m : methodsUsingUnconditionalUpdateById(text)) {
            out.add("service " + m + " 软删写成无谓词 updateById（WHERE 仅主键 ⇒ 并发下不互斥）");
        }
        return out;
    }

    /** 谓词完整性违规清单（service 侧与 mapper 侧**共用同一套**口径）。 */
    private static List<String> predicateOffenders(List<WriteSite> sites) {
        List<String> offenders = new ArrayList<>();
        for (WriteSite s : sites) {
            if (s.primitive()) {
                continue;
            }
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
        return offenders;
    }

    /** 现取「写 deleted 列的调用点」（写点前后 [-CHAIN_BACK, +CHAIN] 视为同一条链：谓词在写点之前）。 */
    private static List<WriteSite> deleteWriteSites(String text) {
        List<WriteSite> out = new ArrayList<>();
        for (String name : methodNames(text)) {
            String body = methodBody(text, name);
            Matcher m = SET_DELETED.matcher(body);
            int first = -1;
            int last = -1;
            while (m.find()) {
                if (first < 0) {
                    first = m.start();
                }
                last = m.end();
            }
            if (first < 0) {
                continue;
            }
            // 🔴 一条**链**= 该方法内全部写点的合并窗口（issue #6956：一个方法里调两次写面时，
            //    固定窗口会把靠后的那次切在半截 —— 谓词落在窗口外 ⇒ 假红）。
            //    谓词在写点**之前**（LambdaUpdateWrapper 的 `.eq(…).set(…)` 链）⇒ 窗口向前也留足。
            int from = Math.max(0, first - CHAIN_BACK);
            int to = Math.min(body.length(), last + CHAIN);
            // `primitive` = 该写点是**写面本体调用**（`…Mapper.softDelete(`）：谓词在**另一个文件**里
            // （由「写面本体谓词判据」直接核），故它**不**在本侧验谓词 —— 只验「未登记即红 / 判 0 行」。
            out.add(new WriteSite(name, body.substring(from, to),
                    PRIMITIVE_CALL.matcher(body.substring(first, last)).find()));
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

    /**
     * 行写调用**不判**「影响行数 == 0」的方法（#6936 病根本体）。
     *
     * <p>🔴 例外（issue #6956 · 洞 B）：**写面本体**（同方法体里也有软删写点的方法，如 mapper 侧的
     * {@code softDelete(…)}）**有意不在这里判** —— 它的契约就是「返回受影响行数，由调用方判 0 行」
     * （该判定由 {@code cascadeSoftDeleteCells} 承担，是**另一个**被登记的方法），在写面本体上再要求一次
     * 「判 0 行」等于要求一个返回行数的原语自己判自己的返回值（做不到，只会把判据变成恒红噪声）。</p>
     */
    private static List<String> unguardedWriteMethods(String text, Set<String> writeFacePrimitives) {
        List<String> out = new ArrayList<>();
        for (String name : methodNames(text)) {
            String body = methodBody(text, name);
            if (writeFacePrimitives.contains(name)) {
                continue;
            }
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

    /**
     * 台账里声明的**写面本体**（{@code call_anchor} 形如 {@code …Mapper.softDelete(} 的 entries）——
     * 它们是「返回受影响行数、由调用方判 0 行」的原语，**有意不在本体上判 0 行**（issue #6956 · 洞 B：
     * 射程扩到 mapper 侧之后，这条边界必须显式登记，否则守卫会对原语自身恒红）。
     */
    private static Set<String> writeFacePrimitivesFromLedger() {
        Set<String> out = new LinkedHashSet<>();
        try {
            for (var e : ledger().get("write_face_primitives")) {
                out.add(e.get("method").asText());
            }
        } catch (IOException e) {
            throw new IllegalStateException("台账不可读 ⇒ 写面本体清单无法现取", e);
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

    /** 顶层方法名（4 空格缩进 + 修饰符 + `) {` 收尾；控制结构关键字排除）——**签名跨行也取到**。 */
    private static List<String> methodNames(String text) {
        List<String> out = new ArrayList<>();
        for (NormalizedLine line : normalizedLines(text)) {
            if (!line.head() || !METHOD_HEAD.matcher(line.effective()).matches()) {
                continue;
            }
            Matcher name = METHOD_NAME.matcher(line.effective().trim());
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

    /**
     * 签名归一（issue #6956 · 洞 B）：把**类体顶层的多行签名**并成一行（{@code effective}），
     * 其余行原样；同时标出「这一行是不是签名头」（{@code head}）。
     *
     * <p>旧实现逐行全匹配 {@code ^ {4}(修饰符)…\) \{…$} ⇒ 签名跨行的 {@code cascadeSoftDeleteCells}
     * 整个取不到（写点静默消失）。归一只看「括号是否配平」这一条朴素事实，不要求签名在同一行收尾；
     * {@code if (…)} / {@code for (…)} 之类控制结构靠「必须由修饰符开头」+ 控制关键字排除。</p>
     */
    private static List<NormalizedLine> normalizedLines(String text) {
        String[] raw = text.replace("\r", "").split("\n", -1);
        List<NormalizedLine> out = new ArrayList<>();
        int[] range = new int[2];
        int i = 0;
        while (i < raw.length) {
            String first = raw[i];
            int end = i;
            if (MEMBER_HEAD_START.matcher(first).find()) {
                int parens = countOf(first, '(') - countOf(first, ')');
                for (int j = i + 1; j < raw.length && parens > 0; j++) {
                    parens += countOf(raw[j], '(') - countOf(raw[j], ')');
                    if (parens <= 0) {
                        if (raw[j].contains(") {")) {
                            end = j;
                        }
                        break;
                    }
                }
            }
            if (end > i) {
                // ⚠️ **首行的原始缩进必须留住**（METHOD_HEAD / METHOD_NAME 都以 `^ {4}` 为锚）——
                // 全 strip 会把归一后的签名变成顶格 ⇒ 所有多行签名反而被判「不是方法头」。
                StringBuilder joined = new StringBuilder(raw[i]);
                for (int k = i + 1; k <= end; k++) {
                    joined.append(' ').append(raw[k].strip());
                }
                range[0] = i;
                range[1] = end;
                for (int k = i; k <= end; k++) {
                    out.add(new NormalizedLine(k == i, joined.toString(), range));
                }
            } else {
                range = new int[]{i, i};
                out.add(new NormalizedLine(true, first, range));
            }
            i = end + 1;
        }
        return out;
    }

    private static int countOf(String s, char c) {
        int n = 0;
        for (int i = 0; i < s.length(); i++) {
            if (s.charAt(i) == c) {
                n++;
            }
        }
        return n;
    }

    /**
     * 归一后的一行：{@code head} = 它是不是（归一后）的签名头；{@code effective} = 归一后的内容；
     * {@code range} = 它覆盖的原始行区间（{@code [start, end]}，用于拼方法体时**不重复计行**）。
     */
    private record NormalizedLine(boolean head, String effective, int[] range) {
    }

    /** 方法体 = 从签名行到下一个顶层签名行（或文件末尾）——**归一后**的签名才算，多行签名也在内。 */
    private static String methodBody(String text, String name) {
        List<NormalizedLine> lines = normalizedLines(text);
        int start = -1;
        for (int i = 0; i < lines.size(); i++) {
            NormalizedLine line = lines.get(i);
            if (!line.head() || !METHOD_HEAD.matcher(line.effective()).matches()) {
                continue;
            }
            Matcher m = METHOD_NAME.matcher(line.effective().trim());
            if (m.find() && m.group(1).equals(name)) {
                start = i;
                break;
            }
        }
        if (start < 0) {
            return "";
        }
        StringBuilder body = new StringBuilder(lines.get(start).effective()).append('\n');
        int i = start + 1;
        while (i < lines.size()) {
            NormalizedLine line = lines.get(i);
            if (line.head() && METHOD_HEAD.matcher(line.effective()).matches()) {
                break;
            }
            // 归一化的多行签名只是被**并进**了它自己的起点行（range()[0]），不重复计行；
            // 其余每行都是正文（旧实现同款口径：方法体 = 从签名到下一个顶层签名之间的全部文本）。
            if (i == line.range()[0]) {
                body.append(line.effective()).append('\n');
            }
            i++;
        }
        return body.toString();
    }

    // ────────────────────────────────────────────── 语料读面

    private static String serviceText() throws IOException {
        return Files.readString(repoRoot().resolve(SERVICE), StandardCharsets.UTF_8);
    }

    /** 写面本体（mapper 侧）文本 —— issue #6956 · 洞 B：射程必须覆盖它。 */
    private static String positionMapperText() throws IOException {
        return Files.readString(repoRoot().resolve(POSITION_MAPPER), StandardCharsets.UTF_8);
    }

    /** 合成 service 方法（形态与真源码同款：4 空格缩进的 `) {` 收尾）。 */
    private static String serviceCorpus(String method, String body) {
        return "    public Map<String, Object> " + method + "(String id, Long tenantId) {\n"
                + "        " + body + "\n        return null;\n    }\n\n";
    }

    /** 合成 service 方法 —— **签名跨两行**（洞 B 的病灶形态，逐字抄真源码 `cascadeSoftDeleteCells` 的断行位置）。 */
    private static String multilineSignatureCorpus(String method, String body) {
        return "public class X {\n    private int " + method + "(Long tenantId, List<Object> matchingCells,\n"
                + "                                       OffsetDateTime now) {\n        "
                + body + "\n        return 0;\n    }\n}\n";
    }

    /** 合规的**级联软删**形态（= 真源码 `cascadeSoftDeleteCells` 的调用侧 + 矩阵行软删写面的谓词）。 */
    private static String cascadeCorpus() {
        return "if (productionOperationPositionMapper.softDelete(row.getId(), tenantId, now) == 0) {\n"
                + "            // softDelete 是写面本体：id / tenant_id / deleted = 0 / updated_at 都在它自己那条链上\n"
                + "            .eq(ProductionOperationPosition::getId, row.getId())\n"
                + "            .eq(ProductionOperationPosition::getTenantId, tenantId)\n"
                + "            .eq(ProductionOperationPosition::getDeleted, 0)\n"
                + "            .set(ProductionOperationPosition::getDeleted, 1)\n"
                + "            .set(ProductionOperationPosition::getUpdatedAt, now)) == 0) {\n"
                + "            throw BusinessException.conflict(\"并发\", \"重试\");\n        }";
    }

    /** 合成 mapper 语料：**写面本体在 mapper 文件里**（洞 B 的另一半：只扫 service 永远看不见它）。 */
    private static String mapperSoftDeleteCorpus(String chain) {
        return "public interface X {\n"
                + "    /** 软删矩阵行。 */\n"
                + "    default int softDelete(String id, Long tenantId, OffsetDateTime updatedAt) {\n"
                + "        return update(null, new LambdaUpdateWrapper<ProductionOperationPosition>()\n"
                + "                " + chain + "\n"
                + "    }\n}\n";
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
