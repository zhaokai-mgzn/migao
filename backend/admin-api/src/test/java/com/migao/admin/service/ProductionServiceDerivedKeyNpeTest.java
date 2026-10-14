// case_ids: PG-059
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 实例判据（issue #6878）：**两级取值** `外层表.get(内层表.get(k))` 在「不可变空表 + 派生键为 null」
 * 上抛 NPE ⇒ 实例化工序 500。
 *
 * <h2>病灶（两条可达链，都在 {@code ProductionService}）</h2>
 * <ol>
 *   <li><b>站点 A</b>（{@code instantiate} 取套处）与 <b>站点 B</b>（{@code ensurePartTokens}）
 *       都把**派生值**当键：`外层表.get(内层表.get(id))`；</li>
 *   <li>{@code setByGroup} ← {@code ensureSetsFor(...)}，它在「分配器/套行读面未接线」或「加工单快照为空」时
 *       {@code return Map.of();} ⇒ **不可变空表**；</li>
 *   <li>{@code itemGroupKey} ← {@code itemIdToGroupKey(...)}，取值来自
 *       {@code orderItemMapper.selectList(... in(itemIds))} 后的 {@code windowGroupKeys(items)} ⇒
 *       该 id **查不到行**（行被删 / 跨租户 / payload 陈旧 / 快照缺 {@code craftLineId}）时结果里**没有它**
 *       ⇒ {@code get(id)} 返 {@code null}。</li>
 * </ol>
 * <p>三条同时成立 ⇒ {@code Map.of().get(null)} 抛 {@code NullPointerException}（Java 21 实跑：
 * {@code HashMap.get(null)} 只是返 null，**这正是隐藏点**）。</p>
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li>{@link #instantiateWithUnresolvableGroupKeyDoesNotBlowUp}：不可变空表 + id 查不到 + 非空 id
 *       ⇒ {@code instantiate} 不抛（修前 = 站点 A NPE 500）；</li>
 *   <li>{@link #partCodeStepWithUnresolvableGroupKeyDoesNotBlowUp}：同三条前提走站点 B 那条路
 *       ⇒ 不抛（修前 = 站点 B NPE 500）；</li>
 *   <li>{@link #everyDerivedKeySiteInTheRealTreeIsRegisteredAndNullGuarded}：真源码里**每一个**
 *       「外层表取值点的实参是派生键」的站点都必须登记 + 具名判空（未登记即红）；</li>
 *   <li>{@link #derivedKeyLedgerIsNotStaleAndTheRuleCatchesEveryBadForm}：台账不许陈旧 / 不许空转，
 *       且规则对四种坏形态（内联未判空 / 摘掉判空 / {@code getOrDefault} 顶替 / 判空错位）**逐条判红**，
 *       对合规形态**不报**（判别力自证）。</li>
 * </ol>
 *
 * <h2>为什么必须新起一条（#6219 那条类级守卫的盲区，现取读数）</h2>
 * {@link WorkerCuttingHeightNullProductIdTest} 的同族守卫是**变量级**的：它扫
 * {@code <变量> = <产出方>(...) ⇒ <变量>.get(...)}，且每个变量**只取首个命中**（窗口 200 行）。
 * 实测（本包改动前）该守卫 **6 测试全绿而缺陷在**，两处原因：
 * ① 站点 B 落在 200 行窗口之外 ⇒ **扫不到**；
 * ② 站点 A 守的是**变量本身**（里层键），而真正交给外层表的键是**派生值** ⇒ **外层无人守**。
 * 本判据把这一族关掉：**任何**「外层表取值的实参是派生键」（内联或先落局部变量）都必须登记并判空。
 *
 * <h2>未覆盖 / 边界（如实登记，§19.1）</h2>
 * ① 只认**同一行**的 `outer.get(...)`（外层取值的括号在本行内闭合）；跨行拆分的写法判不到（不做数据流分析）；
 * ② 认的「判空」= 实参/派生键/登记的 {@code keyExpression}/{@code keySource} 在读取点前 6 行内与
 *   {@code null} 比较，或读法本身是 {@code getOrDefault}/{@code containsKey}；
 * ③ 产出方清单（{@code PRODUCERS}）是**显式清单 + 自证**：全仓「方法与『返回 Map.of()』配对」的扫描
 *   要处理跨行方法声明（本批已在 #6219 那条守卫里补上），本类只关心喂给两级取值外层表的产出方
 *   ⇒ 清单里每个名字都必须在真源码里被调用（改名 / 删方法 ⇒ 当场红）。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#6878：两级取值 `外层表.get(内层表.get(k))` 在不可变空表 + 派生键 null 上不得 NPE")
class ProductionServiceDerivedKeyNpeTest {

    private static final Long TENANT = 6878L;
    private static final String ORDER_ID = "order-6878";
    private static final String PO_ID = "po-6878";
    private static final String PO_NO = "JG-20261014-6878";
    /** 有值 ⇒ {@code ensureQrToken} / {@code ensureShortCode} 两条码路径都早返回（与本判据无关）。 */
    private static final String QR_TOKEN = "qr-token-6878";
    private static final String SHORT_CODE = "7K3M9QP2";
    /** 非空部位 id：payload 真引用了这一行，但订单行查不到 ⇒ 组键为 null（前提 ②）。 */
    private static final String ITEM_ID = "oi-6878-cloth";

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProcessingSetPartTokenMapper setPartTokenMapper;
    /** 只是「非 null」这一个事实 —— 本类不触达它的任何方法。 */
    @Mock
    private com.migao.admin.mapper.ProcessingOrderSetMapper orderSetMapper;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        // 装配 = 「套行读面有值、**分配器为 null**」⇒ ensureSetsFor 走 `return Map.of();` 早返回分支。
        // 这正是生产上「套号分配切片未接线 / 快照为空」的形态（前提 ③）。
        ReflectionTestUtils.setField(service, "orderSetMapper", orderSetMapper);
        ReflectionTestUtils.setField(service, "setPartTokenMapper", setPartTokenMapper);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ────────────────────────── ① 站点 A：instantiate 取套处（修前红） ──────────────────────────

    @Test
    @DisplayName("🔴 站点 A：不可变空表 + 组键查不到 + 非空部位 id ⇒ instantiate 不抛 NPE")
    void instantiateWithUnresolvableGroupKeyDoesNotBlowUp() {
        stubThreePreconditions();
        // 部位码写面**不接线**：否则先撞站点 B（本类投的 setPartTokenMapper 非 null）⇒ 这条判据只钉站点 A。
        ReflectionTestUtils.setField(service, "setPartTokenMapper", null);

        Map<String, Object> out = service.instantiate(ORDER_ID, positionsBody(), TENANT);

        assertThat(out).as("实例化照常返回（修前在站点 A 的 `Map.of().get(null)` 上抛 NPE ⇒ 端点 500）")
                .containsKey("qr_token");
        org.mockito.Mockito.verify(positionOperationMapper, org.mockito.Mockito.times(1))
                .insert(any(ProcessingPositionOperation.class));
    }

    // ────────────────────────── ② 站点 B：ensurePartTokens（修前红） ──────────────────────────

    @Test
    @DisplayName("🔴 站点 B：同样三条前提 ⇒ 部位码那一步不抛 NPE（此前该处**完全没有**判空）")
    void partCodeStepWithUnresolvableGroupKeyDoesNotBlowUp() {
        stubThreePreconditions();
        // 部位码载体已接线 ⇒ ensurePartTokens 进入循环 ⇒ 站点 B 真被求值（修前在此 NPE）。
        Map<String, Object> out = service.instantiate(ORDER_ID, positionsBody(), TENANT);

        assertThat(out).as("部位码那一步不抛（修前 = `setByGroup.get(itemGroupKey.get(itemId))` "
                + "拿 null 索引不可变空表 ⇒ NullPointerException）").containsKey("qr_token");
        org.mockito.Mockito.verify(setPartTokenMapper, org.mockito.Mockito.never())
                .insertIgnoreConflict(any());
    }

    /**
     * 三条前提一次给全（issue #6878 的可达链）：
     * ① 部位行 id **非空**；② 订单行查不到（{@code selectList} 空 ⇒ 组键表里没有它）；
     * ③ {@code setByGroup} = {@code ensureSetsFor} 的 {@code Map.of()} 早返回分支（分配器未接线）。
     */
    private void stubThreePreconditions() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(po());
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of()); // 前提 ②：查不到行 ⇒ itemGroupKey 里没有该 id
        when(positionOperationMapper.selectList(any()))
                .thenReturn(List.<ProcessingPositionOperation>of()); // 无既有实例 ⇒ 不早返回
    }

    // ────────────────────────── ③ 类级守卫：真源码里未登记 / 未判空 ⇒ 红 ──────────────────────────

    @Test
    @DisplayName("🔴 真源码里每个『外层表取值的实参是派生键』的站点都必须登记 + 具名判空")
    void everyDerivedKeySiteInTheRealTreeIsRegisteredAndNullGuarded() throws IOException {
        Map<String, List<String>> sources = sourceLines();
        Map<String, DerivedKeyScanner.Site> sites = DerivedKeyScanner.scanSites(sources);


        // 非空跑自证（扫描面与形态都要自证，否则判据静默退化）
        assertThat(sources.keySet()).as("扫描面为空 ⇒ 目录搬走了").contains(
                "backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java");
        for (String producer : DerivedKeyScanner.PRODUCERS) {
            assertThat(DerivedKeyScanner.producersSeen(sources))
                    .as("产出方清单里的 " + producer + "() 在扫描面里一次都没被调用 ⇒ 清单陈旧或写错（fail-closed）")
                    .contains(producer);
        }

        List<String> offenders = new ArrayList<>();
        sites.forEach((key, site) -> {
            DerivedKeyScanner.LedgerRow row = DerivedKeyScanner.LEDGER.get(key);
            if (row == null) {
                offenders.add("【未登记的两级取值站点】" + key + "　`" + site.code() + "`　"
                        + "⇒ 外层表的键是**派生值**（`" + site.derivedKey() + "`），而 `Map.of().get(null)` 抛 NPE"
                        + "（issue #6878）。出口：派生键先落局部变量并判空"
                        + "（`String k = inner.get(id); k == null ? null : outer.get(k)`），再登记进 "
                        + DerivedKeyScanner.class.getSimpleName() + ".LEDGER。");
            } else if (!DerivedKeyScanner.nullGuarded(sources.get(site.path()), site, row)) {
                offenders.add("【派生键未显式判空】" + key + "　`" + site.code() + "`　⇒ 读取点前 "
                        + DerivedKeyScanner.GUARD_WINDOW + " 行内没有对**派生键**（`" + site.derivedKey()
                        + "`，或它的来源 `" + site.argument() + "`）的 `== null` 判空。"
                        + "出口：派生键先落局部变量再判空（⛔ 不许 `getOrDefault` 顶替 —— 不可变表的 "
                        + "`get(null)` 照样抛）。");
            }
        });
        // 台账不许陈旧（每条登记都必须对得上现取的一个真站点）
        for (String key : DerivedKeyScanner.LEDGER.keySet()) {
            if (!sites.containsKey(key)) {
                offenders.add("【台账条目已陈旧】" + key + " 登记的两级取值站点现取不存在 ⇒ 点位改了行号 / "
                        + "写法被换掉了，复核后更新台账（不许删条目消红）。");
            }
        }
        assertThat(offenders)
                .as("两级取值同族：未登记 / 已陈旧 / 未显式容忍空键的形态（issue #6878）。\n"
                        + "出口见每条后面的『出口：』。\n" + String.join("\n", offenders))
                .isEmpty();
    }

    @Test
    @DisplayName("🔴 台账不许空转；规则判别力自证：四种坏形态逐条判红、合规形态不报")
    void derivedKeyLedgerIsNotStaleAndTheRuleCatchesEveryBadForm() {
        // fail-closed：台账不许空转 + 键必须唯一（撞键 = 有站点被静默吞掉）
        assertThat(DerivedKeyScanner.LEDGER).as("台账清空 ⇒ 上面那条守卫退化成空跑（fail-closed）").isNotEmpty();
        assertThat(new LinkedHashSet<>(DerivedKeyScanner.LEDGER.keySet()))
                .as("台账键必须唯一（撞键 = 有站点被判据静默吞掉）")
                .hasSize(DerivedKeyScanner.LEDGER.size());
        for (Map.Entry<String, DerivedKeyScanner.LedgerRow> entry : DerivedKeyScanner.LEDGER.entrySet()) {
            assertThat(entry.getValue().note()).as(entry.getKey() + " 必须逐字写下登记面事实（空 note = 橡皮图章）")
                    .isNotBlank();
            assertThat(entry.getValue().keyExpression())
                    .as(entry.getKey() + " 必须逐字写下派生键表达式").isNotBlank();
        }

        // 判别力自证（内存夹具：形态自证 + 四种坏形态逐条判红 + 合规形态不报）
        Map<String, List<String>> fixture = derivedKeyFixture();
        Map<String, DerivedKeyScanner.Site> clean = DerivedKeyScanner.scanSites(fixture);
        assertThat(clean.values()).as("夹具自证：内联形态站点必须被扫到（并写下派生式原文）")
                .anySatisfy(site -> {
                    assertThat(site.path()).isEqualTo("g/Inline.java");
                    assertThat(site.line()).isEqualTo(6);
                    assertThat(site.derivedKey()).isEqualTo("itemGroupKey.get(itemId)");
                });
        assertThat(clean.values()).as("夹具自证：『派生键先落局部变量』形态必须被扫到")
                .anySatisfy(site -> {
                    assertThat(site.path()).isEqualTo("g/Local.java");
                    assertThat(site.line()).isEqualTo(6);
                    assertThat(site.derivedKey()).isEqualTo("itemGroupKey.get(itemId)");
                });
        assertThat(violations(fixture)).as("对照：合规形态（内联带判空 / 局部变量带判空）都不许报红").isEmpty();

        // 坏形态 A：内联、**没有**判空（改前站点的形状）⇒ 未登记 ⇒ 红
        assertThat(violations(fixtureWith("g/ProbeA.java",
                "        String set = setByGroup.get(itemGroupKey.get(itemId));")))
                .as("内联形态没有判空 ⇒ 必须报红").isNotEmpty();
        // 坏形态 B：局部变量形态、把判空**摘掉** ⇒ 登记在册但没判空 ⇒ 红
        assertThat(violations(fixtureWith("g/ProbeB.java",
                "        String set = setByGroup.get(itemKey);")))
                .as("局部变量形态摘掉判空 ⇒ 必须报红").isNotEmpty();
        // 坏形态 C：`getOrDefault` 顶替判空 ⇒ 红（不可变表的 `get(null)` 照样抛 —— 纪律被判据钉住）
        assertThat(violations(fixtureWith("g/ProbeC.java",
                "        String set = setByGroup.getOrDefault(itemKey, null);")))
                .as("`getOrDefault(key, null)` 顶替判空 ⇒ 必须报红").isNotEmpty();
        // 坏形态 D：判空错位（判的是**别的变量**）⇒ 红
        assertThat(violations(fixtureWith("g/ProbeD.java",
                "        String set = otherKey == null ? null : setByGroup.get(itemKey);")))
                .as("判空对象与键不一致（判空错位）⇒ 必须报红").isNotEmpty();
        // 好形态对照：同一个值改用与表可变性无关的读法（`getOrDefault(key, 默认值)`）⇒ 不报
        assertThat(violations(fixtureWith("g/ProbeE.java",
                "        String set = setByGroup.getOrDefault(itemKey, \"\");")))
                .as("`getOrDefault(key, 默认值)` 这一档与表可变性无关 ⇒ 不许报红").isEmpty();
    }

    // ────────────────────────── 夹具：两级取值的两形态 ──────────────────────────

    /**
     * 真语料的三形态夹具（写在内存里，逐字复刻 `ProductionService` 改前 / 改后的形状）。
     * 每个文件自带产出方声明（模拟真语料里那几个 `return Map.of();` 的方法），
     * 免得夹具写法本身把 `return Map.of()` 也扫成「未登记产出方」。
     */
    private static Map<String, List<String>> derivedKeyFixture() {
        Map<String, List<String>> out = new LinkedHashMap<>();
        out.put("g/Inline.java", fixtureFile("Inline",
                "        String set = itemId == null ? null : setByGroup.get(itemGroupKey.get(itemId));"));
        out.put("g/Local.java", fixtureFile("Local", null));
        return out;
    }

    /** 一个样板文件；{@code statement} 为 null ⇒ 用「派生键先落局部变量 + 判空」的默认形状。 */
    private static List<String> fixtureFile(String name, String statement) {
        List<String> lines = new ArrayList<>(List.of(
                "class " + name + " {",
                "    void run(String itemId) {",
                "        Map<String, String> setByGroup = ensureSetsFor();",
                "        Map<String, String> itemGroupKey = itemIdToGroupKey();",
                "        String itemKey = itemGroupKey.get(itemId);",
                "        String set = itemKey == null ? null : setByGroup.get(itemKey);",
                "    }",
                "    Map<String, String> ensureSetsFor() { return Map.of(); }",
                "    Map<String, String> itemIdToGroupKey() { return Map.of(); }",
                "}"));
        if (statement != null) {
            lines.set(5, statement);
        }
        return lines;
    }

    /** 把原夹具换成「某一行的语句被替换」的夹具（只保留被替换的那个文件，免得别处同类站点干扰）。 */
    private static Map<String, List<String>> fixtureWith(String path, String statement) {
        Map<String, List<String>> out = new LinkedHashMap<>();
        List<String> lines = new ArrayList<>(fixtureFile("Probe", null));
        lines.set(5, statement);
        out.put(path, lines);
        return out;
    }

    // ────────────────────────── ④ 判别力红证：三种注入在**真源码文本**上逐条判红 ──────────────────────────

    /**
     * 把 {@code ProductionService.java} 的**真源码文本**做三种注入，逐条要求判红 ——
     * 这是 PR 里「判据会红」的说法可执行化的那一半（另一半是夹具自证：不依赖真文件当前写法）。
     *
     * <p>只取该文件一份（不掺入同族其它文件），逐条断言「红在**这个**站点上」而不是「反正红了」。</p>
     */
    @Test
    @DisplayName("🔴 三种注入（摘判空 / getOrDefault 顶替 / 判空错位）在真源码文本上逐条判红")
    void theThreeInjectionsAreRedOnTheRealSourceText() throws IOException {
        String path = "backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java";
        Map<String, List<String>> real = sourceLines();
        List<String> lines = real.get(path);
        assertThat(lines).as("扫描面里必须真有 " + path).isNotNull();

        int siteA = 269;   // `ProcessingOrderSet set = derivedKey == null ? null : setByGroup.get(derivedKey);`
        int keyA = 268;    // `String derivedKey = spec.orderItemId() == null ? null : itemGroupKey.get(spec.orderItemId());`
        assertThat(lines.get(siteA - 1)).as("站点 A 行号自证").contains("setByGroup.get(derivedKey)");
        assertThat(lines.get(keyA - 1)).as("站点 A 派生键行号自证").contains("itemGroupKey.get(spec.orderItemId())");

        // 注入 A：**摘掉判空**（回到改前的内联形态）⇒ 派生键未判空 ⇒ 红
        assertThat(violationsOnRealSource(path, siteA,
                "            ProcessingOrderSet set = setByGroup.get(derivedKey);"))
                .as("注入 A（摘掉判空）⇒ 必须红在这条站点上")
                .anySatisfy(message -> assertThat(message).contains(path + "|setByGroup|" + siteA));

        // 注入 B：把 `getOrDefault(派生键, null)` 当判空顶替 ⇒ 红（不可变表照样抛）
        assertThat(violationsOnRealSource(path, siteA,
                "            ProcessingOrderSet set = setByGroup.getOrDefault(derivedKey, null);"))
                .as("注入 B（getOrDefault 顶替判空）⇒ 必须红在这条站点上")
                .anySatisfy(message -> assertThat(message).contains(path + "|setByGroup|" + siteA));

        // 注入 C：判空**错位**（判的是别的变量）⇒ 红
        assertThat(violationsOnRealSource(path, siteA,
                "            ProcessingOrderSet set = otherKey == null ? null : setByGroup.get(derivedKey);"))
                .as("注入 C（判空错位）⇒ 必须红在这条站点上")
                .anySatisfy(message -> assertThat(message).contains(path + "|setByGroup|" + siteA));
    }

    /** 在**真源码**副本上把某一行换掉，返回该文件里【登记在册但未判空】的报红（对象 = 该站点）。 */
    private static List<String> violationsOnRealSource(String path, int lineNo, String replacement)
            throws IOException {
        Map<String, List<String>> mutated = new LinkedHashMap<>();
        List<String> lines = new ArrayList<>(sourceLines().get(path));
        lines.set(lineNo - 1, replacement);
        mutated.put(path, lines);

        List<String> offenders = new ArrayList<>();
        DerivedKeyScanner.scanSites(mutated).forEach((key, site) -> {
            DerivedKeyScanner.LedgerRow row = DerivedKeyScanner.LEDGER.get(key);
            if (row == null) {
                offenders.add("【未登记的两级取值站点】" + key);
            } else if (!DerivedKeyScanner.nullGuarded(mutated.get(site.path()), site, row)) {
                offenders.add("【派生键未显式判空】" + key);
            }
        });
        return offenders;
    }

    /**
     * 只跑「未登记 / 未判空」两条出口的判定（夹具侧用 {@link DerivedKeyScanner#FIXTURE_LEDGER}），
     * 供判别力自证用 —— 与真源码那条守卫**同一套**扫描 + 判定实现。
     */
    private static List<String> violations(Map<String, List<String>> sources) {
        List<String> offenders = new ArrayList<>();
        DerivedKeyScanner.scanSites(sources).forEach((key, site) -> {
            DerivedKeyScanner.LedgerRow row = DerivedKeyScanner.FIXTURE_LEDGER.get(key);
            if (row == null) {
                offenders.add("【未登记的两级取值站点】" + key);
            } else if (!DerivedKeyScanner.nullGuarded(sources.get(site.path()), site, row)) {
                offenders.add("【派生键未显式判空】" + key);
            }
        });
        return offenders;
    }

    // ============================================================================
    // 两级取值扫描器（只读源码、零 LLM、零真库）
    // ============================================================================

    static final class DerivedKeyScanner {

        /** 判空回溯窗口（读取点之前多少行内要找对**派生键**的 `== null` 判空）。 */
        static final int GUARD_WINDOW = 6;

        /**
         * 外层表可以来自哪几个「返回空不可变表」的产出方。
         *
         * <p>显式清单 + 自证（改名 / 删方法 ⇒ 调用点自证当场红），理由见类 javadoc 的边界 ③。</p>
         */
        static final Set<String> PRODUCERS = Set.of("ensureSetsFor", "itemIdToGroupKey");

        /**
         * 台账（issue #6878）。**未登记即红**；判定口径逐条写在 {@code note} 里。
         *
         * <p>键 = {@code <仓库相对路径>|<外层变量>|<外层取值行号>} —— 同一个外层变量可以有多个取值点
         * （站点 A / 站点 B 就是），变量级键装不下两条，这正是旧判据「每个变量只取首个命中」的根因。</p>
         */
        static final Map<String, LedgerRow> LEDGER = Map.ofEntries(
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java|setByGroup|269",
                        new LedgerRow("setByGroup", "itemGroupKey.get(spec.orderItemId())", "spec.orderItemId()",
                                "站点 A（instantiate 取套处；issue #6878；外层取值在第 269 行，派生键第 268 行先落局部变量）。"
                                        + "**登记面事实**：交给 `setByGroup.get(...)` 的键是派生值 —— `derivedKey` ← "
                                        + "`itemGroupKey.get(spec.orderItemId())`；`itemGroupKey` ← `itemIdToGroupKey` ← "
                                        + "`orderItemMapper.selectList(... in(itemIds))` ⇒ 该 id 查不到行时结果里没有它 "
                                        + "⇒ 派生键为 null；`setByGroup` ← `ensureSetsFor` 的早返回分支 = 不可变空表 "
                                        + "`Map.of()` ⇒ `Map.of().get(null)` 抛 NPE。改前那句是直接把派生式内联在参数里"
                                        + "（只判了里层部位 id、外层无人守）。")),
                Map.entry("backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java|setByGroup|399",
                        new LedgerRow("setByGroup", "itemGroupKey.get(itemId)", "itemId",
                                "站点 B（ensurePartTokens；issue #6878；外层取值在第 399 行，派生键第 398 行先落局部变量）。"
                                        + "改前是 `setByGroup.get(itemGroupKey.get(itemId))` —— **完全没有判空**的单键读法；"
                                        + "旧变量级判据（#6219）每个变量只取首个命中 / 窗口 200 行 ⇒ 站点 B 整条扫不到"
                                        + "（它的盲区）。")));

        /**
         * **夹具侧**登记（不是生产面台账）：判别力自证用的两个样板登记在册，
         * 「摘掉判空 ⇒ 报【派生键未显式判空】」（而不是只剩「未登记」那一条出口）才真的被执行到。
         */
        static final Map<String, LedgerRow> FIXTURE_LEDGER = Map.ofEntries(
                Map.entry("g/Inline.java|setByGroup|6",
                        new LedgerRow("setByGroup", "itemGroupKey.get(itemId)", "itemId",
                                "夹具样板①（内联形态）：合规 = 派生键的源头（部位 id）已判空；摘掉即红。")),
                Map.entry("g/Local.java|setByGroup|6",
                        new LedgerRow("setByGroup", "itemGroupKey.get(itemId)", "itemId",
                                "夹具样板②（局部变量形态）：合规 = 派生键先落变量再判空；摘掉即红。")));

        /** 一条登记：派生键表达式（供报红时具名）+ 它的源头（对源头的判空同样算数）+ 登记面事实。 */
        record LedgerRow(String variable, String keyExpression, String keySource, String note) {
        }

        /**
         * 一个两级取值站点。
         *
         * @param line       外层取值那句的行号（键）
         * @param argument   外层取值括号里的实参原文（派生键的**使用**形态）
         * @param derivedKey 派生键的**来源**：{@code <内层表>.get(<键>)} 原文
         * @param code       该行源码（去注释/字符串后），报红时具名用
         */
        record Site(String path, int line, String outerVar, String argument, String derivedKey, String code) {
        }

        private DerivedKeyScanner() {
        }

        /** 扫出**所有**「外层表取值点的实参是派生键」的站点（两形态都认）。 */
        static Map<String, Site> scanSites(Map<String, List<String>> sources) {
            Map<String, Site> sites = new LinkedHashMap<>();
            Map<String, String> derivations = derivationsByVariable(sources);
            sources.forEach((path, rawLines) -> {
                List<String> lines = codeOnly(rawLines);
                Map<String, String> assignedFrom = assignedProducers(lines);
                for (int i = 0; i < lines.size(); i++) {
                    String line = lines.get(i);
                    Matcher getters = Pattern.compile("([A-Za-z_$][\\w$]*)\\s*\\.\\s*(get|getOrDefault)\\s*\\(")
                            .matcher(line);
                    while (getters.find()) {
                        String outerVar = getters.group(1);
                        if (!assignedFrom.containsKey(outerVar)) {
                            continue; // 外层表必须来自「返回空不可变表」的产出方
                        }
                        // ⚠️ 别把**内层**取值当成外层站点：`outer.get(inner.get(k))` 里 `inner.get(` 的括号
                        // 深度 > 0（它被包在别人的实参里），外层那句才是深度 0。
                        // 实测：不加这道闸，内联形态会被记成第二个「未登记站点」。
                        String argument = balancedArgument(line, getters.end() - 1);
                        if (argument == null || argument.isBlank()) {
                            continue; // 跨行 / 取不到实参 ⇒ 不猜
                        }
                        if ("getOrDefault".equals(getters.group(2))) {
                            // `getOrDefault(key, fallback)`：**键只是第一个实参**。整串拿去当键会让
                            // 派生式查表落空（实测：`itemKey, null` 查不到 ⇒ 站点被静默跳过）。
                            argument = firstArgument(argument);
                        }
                        // 派生键两形态，顺序很重要：
                        //  ① 【优先】附近某行先把它落成局部变量（`String k = inner.get(id);`）——
                        //     必须**先**找这一种：否则外层取值那句（`... k == null ? null : outer.get(k)`）
                        //     会被当成「k 的派生式」，得出的键写成 `outer.get(k)`（实测踩过）。
                        //  ② 同一行内联（`outer.get(inner.get(k))`）。
                        // 那句赋值在**同一行 / 上面 / 下面**都可能（声明顺序无保证）⇒ 查预建索引；
                        // 查不到才退回内联形态。⚠️ 不要在这里对每行都跑一遍 derivationOf：
                        // 那是 O(候选 × 文件行数)，实测把单次 run 拖到 200s（超时）。
                        String derivedKey = derivations.get(path + "|" + argument);
                        if (derivedKey == null && argument.contains(".get(")) {
                            derivedKey = argument; // 内联派生式
                        }
                        if (derivedKey == null) {
                            continue; // 实参不是派生键（普通变量 / 字面量）⇒ 不是本族形态
                        }
                        // `getOrDefault(派生键, 非 null 兜底)` 与表可变性无关（空键拿兜底，不抛）
                        // ⇒ 不需要判空、也不需要登记。`getOrDefault(派生键, null)` **不**豁免。
                        if (hasNonNullFallback(line, outerVar, argument)) {
                            continue;
                        }
                        // 同一张表的自取值不是「两级取值」形态 ⇒ 不是站点。这条闸挡两类误报（都实测过）：
                        //  ① `m.get(m.get(k))` 本身；
                        //  ② 外层取值那句**所在行**就是「派生键的赋值行」时（`String m = ... m.get(k)`），
                        //     找到的「派生式」其实是那句取值自身 ⇒ 会凭空多出一个 `m|行号` 站点。
                        if (innerTableOf(derivedKey).equals(outerVar)) {
                            continue;
                        }
                        String key = path + "|" + outerVar + "|" + (i + 1);
                        sites.putIfAbsent(key, new Site(path, i + 1, outerVar, argument, derivedKey, line.strip()));
                    }
                }
            });
            return sites;
        }

        /** 清单里**真被调用过**的产出方（自证清单不陈旧、不空转）。 */
        static Set<String> producersSeen(Map<String, List<String>> sources) {
            Set<String> seen = new LinkedHashSet<>();
            sources.values().forEach(rawLines -> {
                List<String> lines = codeOnly(rawLines);
                for (String line : lines) {
                    for (String producer : PRODUCERS) {
                        if (Pattern.compile("(?<![\\w$])" + Pattern.quote(producer) + "\\s*\\(")
                                .matcher(line).find()) {
                            seen.add(producer);
                        }
                    }
                }
            });
            return seen;
        }

        /**
         * **派生键**是否被显式判空（逐处执行，不读台账里手写的布尔值）。候选 = 实参 / 派生式 / 登记的
         * {@code keyExpression} / {@code keySource}；任一在读取点前 {@value #GUARD_WINDOW} 行内与
         * {@code null} 比较即算数。读法本身是 {@code getOrDefault} / {@code containsKey} ⇒ 直接算容忍。
         */
        static boolean nullGuarded(List<String> rawLines, Site site, LedgerRow row) {
            List<String> lines = codeOnly(rawLines);
            int idx = site.line() - 1;
            String line = lines.get(idx);
            CallStyle style = callStyle(line, site);
            if (style == CallStyle.ORDINARY) {
                // `getOrDefault(k, 非 null 的兜底)` —— 空键也拿兜底，与表可变性无关 ⇒ 豁免。
                return true;
            }
            // 判空候选（4 个）：
            //  ① 实参 —— `outer.get(k)` 里对 `k` 的判空；局部变量形态就靠这个；
            //  ② 派生式原文 —— 内联形态（`outer.get(inner.get(x))`）里对派生表达式的判空；
            //  ③ 派生式的键 —— `inner.get(x)` 里对 `x` 的判空（大于等于②的强度，也认）；
            //  ④ 台账登记的键表达式 —— 与②同物，防台账与代码写法微差。
            // ⛔ **不含** `row.keySource()`：它是里层查表自己的判空（`x == null ? null : inner.get(x)`），
            //    与「派生结果是否为 null」无关。实测教训：把 keySource 当候选 ⇒ 摘掉外层判空后，
            //    上面那句里层判空照样让判据判绿 —— 判据自己成了橡皮图章。
            // 注意 `getOrDefault(k, null)` 也要走这里：它**不**构成判空，但 k 本身若真被判过空也算数。
            for (String candidate : List.of(site.argument(), site.derivedKey(), derivedKeyOf(site.derivedKey()),
                    row.keyExpression())) {
                if (candidate != null && !candidate.isBlank() && hasNullComparison(lines, idx, candidate)) {
                    return true;
                }
            }
            return false;
        }

        /** 该行是不是 {@code <外层表>.getOrDefault(<派生键>, 非 null 兜底)}（这一档不需要判空）。 */
        private static boolean hasNonNullFallback(String line, String outerVar, String derivedKey) {
            String marker = outerVar + ".getOrDefault(";
            int at = line.indexOf(marker);
            if (at < 0) {
                return false;
            }
            String tail = line.substring(at + marker.length()).strip();
            return tail.startsWith(derivedKey) && !tail.replace(" ", "").startsWith(derivedKey + ",null");
        }

        /**
         * 这一处的取法：{@code .get(} 要求判空；{@code .getOrDefault(k, null)} 视同 {@code get}
         * （不可变表上照样抛）；只有 {@code .getOrDefault(k, 非 null 兜底)} 才与表可变性无关。
         *
         * <p>用纯字符串定位（不写正则）：本文件已在正则上踩过两次 ——
         * ① Java 字符串里 {@code \s} 被吞成非法转义；② 回溯把 {@code getOrDefault(} 也豁免掉。</p>
         */
        private static CallStyle callStyle(String line, Site site) {
            String marker = site.outerVar() + ".get";
            int at = line.indexOf(marker);
            while (at >= 0) {
                int after = at + marker.length();
                if (line.startsWith("OrDefault(", after)) {
                    String tail = line.substring(after + "OrDefault(".length()).strip();
                    boolean nullFallback = tail.startsWith(site.argument().strip() + ",")
                            && tail.replace(" ", "").startsWith(site.argument().strip().replace(" ", "") + ",null)");
                    if (!nullFallback) {
                        return CallStyle.ORDINARY;
                    }
                } else if (line.startsWith("(", after)) {
                    return CallStyle.REQUIRES_GUARD;
                }
                at = line.indexOf(marker, at + 1);
            }
            return CallStyle.REQUIRES_GUARD;
        }

        private enum CallStyle {
            /** `.get(` 与 `.getOrDefault(k, null)` —— 必须判空。 */
            REQUIRES_GUARD,
            /** `.getOrDefault(k, 非 null 兜底)` —— 与表可变性无关，豁免。 */
            ORDINARY
        }

        private static boolean hasNullComparison(List<String> lines, int idx, String expression) {
            for (int k = Math.max(0, idx - GUARD_WINDOW); k <= idx; k++) {
                if (Pattern.compile(Pattern.quote(expression) + "\\s*(==|!=)\\s*null"
                                + "|null\\s*(==|!=)\\s*" + Pattern.quote(expression))
                        .matcher(lines.get(k)).find()) {
                    return true;
                }
            }
            return false;
        }

        /** 变量名 → 「`变量 = 某产出方(...)`」的产出方名。 */
        private static Map<String, String> assignedProducers(List<String> lines) {
            Map<String, String> assigned = new LinkedHashMap<>();
            for (String line : lines) {
                for (String producer : PRODUCERS) {
                    // ⚠️ 只认「赋值号紧跟在变量名后」（可选 `某对象.` 前缀）：若允许「变量名与赋值号之间任意字符」，
                    // 行内多处 `=` 的语句会认错左值（实测：`Map<String,String> g = itemIdToGroupKey(...)` 被
                    // 认成别的变量 ⇒ 整条站点扫不到）。
                    Matcher assign = Pattern.compile("([A-Za-z_$][\\w$]*)\\s*=\\s*(?:[A-Za-z_$][\\w$]*\\.)?"
                            + Pattern.quote(producer) + "\\s*\\(").matcher(line);
                    if (assign.find()) {
                        assigned.put(assign.group(1), producer);
                    }
                }
            }
            return assigned;
        }

        /** 变量名 → 它的派生式原文（`k = inner.get(id)` 那一处）；没有 ⇒ 不在表里。 */
        private static Map<String, String> derivationsByVariable(Map<String, List<String>> sources) {
            Map<String, String> out = new LinkedHashMap<>();
            sources.forEach((path, rawLines) -> {
                for (String line : codeOnly(rawLines)) {
                    // 只认「**裸变量** = 某表.get(...)」：`head = row.get(x)` 这种不是本族形态
                    // （`head` 是别处传进来的参数，不是派生键），旧写法会把它当成 `head` 的派生式，
                    // 进而在别处把外层取值认成 `row.get(...)` 的站点（实测误报）。
                    Matcher assign = Pattern
                            .compile("(?<![\\w$.])([A-Za-z_$][\\w$]*)\\s*=\\s*[\\w$.]+\\s*\\.\\s*get\\s*\\(")
                            .matcher(line);
                    while (assign.find()) {
                        String derivation = derivationOf(line, assign.group(1));
                        if (derivation != null) {
                            out.putIfAbsent(path + "|" + assign.group(1), derivation);
                        }
                    }
                }
            });
            return out;
        }

        /** 派生式 {@code <内层表>.get(<键>)} 里的**键**原文；解析不出 ⇒ 空串。 */
        private static String derivedKeyOf(String derivedKey) {
            int getAt = derivedKey.indexOf(".get(");
            int close = derivedKey.lastIndexOf(')');
            return getAt < 0 || close <= getAt ? "" : derivedKey.substring(getAt + ".get(".length(), close).strip();
        }

        /** 派生式 {@code <内层表>.get(<键>)} 里的内层表名；解析不出 ⇒ 空串。 */
        private static String innerTableOf(String derivedKey) {
            int getAt = derivedKey.indexOf(".get(");
            if (getAt <= 0) {
                return "";
            }
            String head = derivedKey.substring(0, getAt);
            int dot = head.lastIndexOf('.');
            return dot < 0 ? head.strip() : head.substring(dot + 1).strip();
        }

        /** 多实参调用里的第一个实参（按顶层逗号切）。 */
        private static String firstArgument(String arguments) {
            int depth = 0;
            for (int p = 0; p < arguments.length(); p++) {
                char c = arguments.charAt(p);
                if (c == '(') {
                    depth++;
                } else if (c == ')') {
                    depth--;
                } else if (c == ',' && depth == 0) {
                    return arguments.substring(0, p).strip();
                }
            }
            return arguments.strip();
        }

        /** 取 `(keyStart)` 起配平的实参原文；该行内不闭合 ⇒ null。 */
        private static String balancedArgument(String line, int open) {
            if (open < 0 || open >= line.length() || line.charAt(open) != '(') {
                return null;
            }
            int depth = 0;
            for (int p = open; p < line.length(); p++) {
                char c = line.charAt(p);
                if (c == '(') {
                    depth++;
                } else if (c == ')' && --depth == 0) {
                    return line.substring(open + 1, p).strip();
                }
            }
            return null;
        }

        /**
         * 该行里有没有「{@code name = <某表>.get(<键>)}」这句赋值；有 ⇒ 返回 {@code <某表>.get(<键>)} 原文。
         *
         * <p>用 indexOf 定位（不吃正则回溯的坑）：先找 {@code name}「完整词」且**不是赋值左值**的出现，
         * 再看它后面同一行有没有 {@code 标识符 . get (}。命中即返回那个派生式原文（到第一个 `(` 为止）。</p>
         */
        private static String derivationOf(String line, String name) {
            for (int at = line.indexOf(name); at >= 0; at = line.indexOf(name, at + 1)) {
                if (at > 0 && (Character.isLetterOrDigit(line.charAt(at - 1)) || line.charAt(at - 1) == '_'
                        || line.charAt(at - 1) == '$')) {
                    continue; // 前半截是更长的标识符 ⇒ 不是它
                }
                int end = at + name.length();
                if (end < line.length() && (Character.isLetterOrDigit(line.charAt(end)) || line.charAt(end) == '_'
                        || line.charAt(end) == '$')) {
                    continue;
                }
                String tail = line.substring(end);
                int getAt = tail.indexOf(".get(");
                if (getAt < 0) {
                    continue;
                }
                int dot = tail.lastIndexOf('.', getAt);
                int innerStart = dot - 1;
                while (innerStart >= 0 && (Character.isLetterOrDigit(tail.charAt(innerStart))
                        || tail.charAt(innerStart) == '_' || tail.charAt(innerStart) == '$')) {
                    innerStart--;
                }
                innerStart++;
                if (innerStart >= dot) {
                    continue;
                }
                String innerTable = tail.substring(innerStart, dot);
                if (innerTable.equals(name)) {
                    continue; // 自指（`k = <条件> ? null : k.get(...)`）⇒ 不是「k 的派生式」
                }
                int keyStart = getAt + ".get(".length();
                int keyEnd = tail.indexOf('(', keyStart);
                if (keyEnd < 0) {
                    // 键不是方法调用（`inner.get(itemId)`）⇒ 取到第一个 `)` 为止
                    keyEnd = tail.indexOf(')', keyStart);
                    if (keyEnd < 0) {
                        keyEnd = tail.length();
                    }
                }
                return innerTable + ".get(" + tail.substring(keyStart, keyEnd) + ")";
            }
            return null;
        }

        /** 去注释 / 去字符串字面量后的源码行（否则扫描会命中注释与字符串里的示例文本）。 */
        private static List<String> codeOnly(List<String> lines) {
            List<String> out = new ArrayList<>(lines.size());
            for (String line : lines) {
                out.add(line.replaceAll("\"(\\\\.|[^\"\\\\])*\"", "\"\"").replaceAll("//.*$", ""));
            }
            return out;
        }
    }

    // ============================================================================
    // 夹具 / 源码面工具
    // ============================================================================

    /** 扫描面 = `src/main` ∪ `src/test`（测试里的两级取值同样是 NPE 风险，一并纳入）。 */
    private static Map<String, List<String>> sourceLines() throws IOException {
        Map<String, List<String>> out = new LinkedHashMap<>();
        Path root = repoRoot();
        for (String dir : List.of("backend/admin-api/src/main/java", "backend/admin-api/src/test/java")) {
            for (Path file : javaSources(root.resolve(dir))) {
                out.put(root.relativize(file).toString().replace('\\', '/'), Files.readAllLines(file));
            }
        }
        return out;
    }

    private static List<Path> javaSources(Path src) throws IOException {
        try (Stream<Path> walk = Files.walk(src)) {
            return walk.filter(p -> p.toString().endsWith(".java")).sorted(Comparator.naturalOrder()).toList();
        }
    }

    /** 与 {@code ProcessingInfoNullSafetyMetaGuardTest} 同款：从 surefire 的 cwd（模块目录）向上找仓库根。 */
    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位仓库根").isNotNull();
        return root;
    }

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20261014-6878");
        o.setStatus("producing");
        o.setDeleted(0);
        return o;
    }

    /** 两条码都已发过 ⇒ 两条码路径都早返回（本判据只钉「取套 / 部位码」那一步）。 */
    private ProcessingOrder po() {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setProcessingOrderNo(PO_NO);
        po.setQrToken(QR_TOKEN);
        po.setShortCode(SHORT_CODE);
        po.setStatus("in_processing");
        po.setDeleted(0);
        return po;
    }

    /** 一个部位一行工序；`order_item_id` **非空**（前提 ①）。 */
    private Map<String, Object> positionsBody() {
        Map<String, Object> op = new LinkedHashMap<>();
        op.put("operation", "精裁-布");
        op.put("group", "裁剪");
        op.put("unit", "米");
        op.put("qty", 10);
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("position_name", "布艺遮光帘A");
        position.put("order_item_id", ITEM_ID);
        position.put("position_kind", "布帘");
        position.put("operations", List.of(op));
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("positions", List.of(position));
        return body;
    }
}
