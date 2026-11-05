// case_ids: MC-243
package com.migao.admin.service;

import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.dto.OrderContentUpdateRequest;
import com.migao.admin.dto.OrderCreateRequest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * <b>类级元守卫</b>（AGENTS.md 铁律 8；issue #8681，P2-1e 第九批）：「<b>共享部件不许复制第二份</b>」。
 *
 * <p>这条一直是 issue #8681 里<b>登记而未固化</b>的缺口（前八批都写着「同批应补，本批登记为未固化项」），
 * 本批把它落成判据。</p>
 *
 * <h3>病（要防的<b>类</b>，不是单个 bug）</h3>
 * <p>建单 / 改单 / Agent 三条写单路径共用同一份「明细装配 · 取价 · 总额 · 库存前置」。这批代码从门面
 * 搬进 {@link OrderSharedParts} 之后，「复用」靠的是<b>大家传同一个实例</b>；而<b>复制</b>同样能编译通过、
 * 同样能让今天的用例变绿 —— 代价随后才到期，且到期时<b>没有任何断言会红</b>：</p>
 * <ul>
 *   <li>第二个 {@code ProcessingFeeCalculator.attach(} 调用点 ⇒ 加工费构成从某一条路径上<b>静默消失</b>
 *       （读面读存量，所以「改单后加工费构成丢失」不会报错）；</li>
 *   <li>第二个 {@code orderItemMapper.insert(} 循环 ⇒ 改单不再重算 V111 整卷分配 / V63 行要素物化；</li>
 *   <li>第二个 {@code feesFor(} 取价 ⇒ 同一张单在建单与改单上<b>两个总额</b>（涉钱面，且不会有异常）。</li>
 * </ul>
 *
 * <h3>四条判据（每条都能机械地红）</h3>
 * <ol>
 *   <li><b>实现点登记表双向相等</b>：每个共享部件的**特征调用**（装配 / 取价 / 构成挂载 / 组合同步 /
 *       总额 / 库存前置）只允许出现在登记的承载文件里 —— <b>新增未登记 ⇒ 红</b>（第二份就是这么进来的）、
 *       <b>登记了却扫不到 ⇒ 也红</b>（台账只许缩短）。</li>
 *   <li><b>入口名不许在别处另起实现</b>：{@code assertItemAmountsValid} / {@code priceItems} /
 *       {@code computeItemsTotal} / {@code syncProcessingFeeCombinations} / {@code persistOrderItems} /
 *       {@code normalizeInstallRooms} / {@code generateOrderNo} 这七个<b>声明</b>只允许在
 *       {@link OrderSharedParts} 里存在一份（换文件重写一份 ⇒ 红并具名）。</li>
 *   <li><b>第三参只能是共享部件</b>：{@link OrderCreationService#createOrder} /
 *       {@code createOrderForAgent}、{@link OrderEntityWriteService#updatePendingOrderContent}、
 *       {@link OrderLifecycleService#updateOrderStatus} / {@code cancelOrder} 的第三参类型必须是
 *       {@link OrderSharedParts}，且<b>不许留 {@link OrderService} 兼容重载</b>（留了就是第二份口径）。</li>
 *   <li><b>门面实例不许再当参数传</b>：{@code src/main} 里不允许出现「形参类型是 {@code OrderService}」的
 *       方法 —— 那正是本批拆掉的形态；它一旦回来，共享部件就重新经门面传播。</li>
 * </ol>
 *
 * <h3>扫描纪律（都是实测踩出来的，别省）</h3>
 * <ul>
 *   <li><b>先剥注释</b>：「在说明里写下某个调用」不是「调用」。负控 = 在别的服务里加一行同串<b>注释</b>
 *       ⇒ 必须<b>不红</b>（本类有该负控的单测形态，见 PR body 的红证表）。</li>
 *   <li><b>只扫主源码</b>：判据的对象是「谁能写生产代码」，{@code src/test} 的替身与断言不在面内。</li>
 * </ul>
 *
 * <p><b>边界（照实登记）</b>：判据 1/2 认的是**已登记的具名调用 / 声明**；有人用别的 API 手搓一份
 * 等价物（不出现这些具名符号）在面外 —— 那一类靠 code review 与实例判据兜（本类<b>不</b>声称覆盖它）。
 * 判据 3/4 是**反射 + 源码**双面：反射认签名，源码认「形参声明」这一形态。</p>
 */
@DisplayName("#8681 P2-1e 第九批：共享部件不许复制第二份（实现点唯一 · 第三参唯一 · 门面不再当参数）")
class OrderSharedPartsSingleImplementationTest {

    /** 主源码根（surefire 的 cwd = {@code backend/admin-api}，与既有契约判据同口径）。 */
    private static final Path MAIN_SRC = Paths.get("src", "main", "java", "com", "migao", "admin");

    /** 共享部件的**唯一**承载文件。 */
    private static final String PARTS = "OrderSharedParts.java";

    /**
     * 共享部件的**特征调用** → 允许出现的文件集合（登记表）。
     *
     * <p>为什么是「调用特征」而不是「方法名」：第二份口径通常是<b>复制方法体</b>过来的，
     * 复制出来的方法可能改名；但<b>它内部的那些调用</b>跑不掉（不调它们就等于没实现这件事）。</p>
     *
     * <p>两条登记为**两个**文件，理由具名：{@code validateStockSufficientFor*} 的**实现**在
     * {@link OrderStockService}（唯一），共享部件里那一份是**转发**（同一语义的第二个入口，
     * 但不会分叉 —— 它只有一行委派）。</p>
     */
    private static final Map<String, Set<String>> REGISTERED_CALL_SITES = new LinkedHashMap<>();

    /**
     * 只允许在共享部件里**声明**一次的方法名（复制第二份 ⇒ 红并具名）。
     *
     * <p>{@code generateOrderNo} <b>不在</b>本集合里：{@code ProcessingOrderService} 有一个同名但语义
     * 完全不同（{@code JG-…} 加工单号）的发号器 —— 按名字判会误红。它的唯一性改由上面的
     * {@code ORDER_SEQ.incrementAndGet(} 调用点判据钉住。</p>
     */
    private static final Set<String> SINGLE_DECLARATION_METHODS = new TreeSet<>(Set.of(
            "assertItemAmountsValid",
            "priceItems",
            "computeItemsTotal",
            "syncProcessingFeeCombinations",
            "persistOrderItems",
            "normalizeInstallRooms"));

    static {
        Set<String> only = new TreeSet<>(Set.of(PARTS));
        REGISTERED_CALL_SITES.put("ProcessingFeeCalculator.attach(", only);
        REGISTERED_CALL_SITES.put("OrderLineCraftFields.materialize(", only);
        REGISTERED_CALL_SITES.put("OrderInstallInfo.normalizeRoom(", only);
        REGISTERED_CALL_SITES.put("ProcessingFeeCalculator.FEE_SOURCE_MANUAL.equals(", only);
        REGISTERED_CALL_SITES.put("orderItemMapper.insert(", only);
        REGISTERED_CALL_SITES.put("ProductRollAllocation.resolve(", only);
        REGISTERED_CALL_SITES.put("void applyRollAllocation(", only);
        // 订单号的 9 位后缀（5 位随机 + 4 位原子序列）—— 具名登记为「唯一发号器」。
        // ⚠️ 不按方法名 `generateOrderNo` 判：`ProcessingOrderService` 有一个**同名的加工单号**发号器
        // （`JG-…`，语义完全不同）⇒ 按名字判会把它误判成第二份口径（实测红过）。
        REGISTERED_CALL_SITES.put("ORDER_SEQ.incrementAndGet(", only);
        REGISTERED_CALL_SITES.put("BigDecimal resolveItemSubtotal(", only);
        REGISTERED_CALL_SITES.put("void validateStockSufficientForRequest(",
                new TreeSet<>(Set.of(PARTS, "OrderStockService.java")));
        REGISTERED_CALL_SITES.put("void validateStockSufficientForItems(",
                new TreeSet<>(Set.of(PARTS, "OrderStockService.java")));
    }

    /** 三个服务（含生命周期）里第三参是共享部件的入口：类 → 方法名。 */
    private static final Map<String, Set<String>> SHARED_PARTS_ENTRIES = new LinkedHashMap<>();

    static {
        SHARED_PARTS_ENTRIES.put(OrderCreationService.class.getSimpleName(),
                new TreeSet<>(Set.of("createOrder", "createOrderForAgent")));
        SHARED_PARTS_ENTRIES.put(OrderEntityWriteService.class.getSimpleName(),
                new TreeSet<>(Set.of("updatePendingOrderContent")));
        SHARED_PARTS_ENTRIES.put(OrderLifecycleService.class.getSimpleName(),
                new TreeSet<>(Set.of("updateOrderStatus", "cancelOrder")));
    }

    /** 「形参类型是门面实例」的签名形态（本批拆掉的正是它）。 */
    private static final Pattern FACADE_PARAMETER = Pattern.compile("\\bOrderService\\s+\\w+\\s*[,)]");

    /** 文件名 → 源码（剥注释前）。 */
    private static Map<String, String> mainSources() throws IOException {
        try (Stream<Path> walk = Files.walk(MAIN_SRC)) {
            return walk.filter(p -> p.toString().endsWith(".java"))
                    .collect(Collectors.toMap(
                            p -> p.getFileName().toString(),
                            p -> {
                                try {
                                    return Files.readString(p, StandardCharsets.UTF_8);
                                } catch (IOException e) {
                                    throw new IllegalStateException(e);
                                }
                            },
                            (a, b) -> a,
                            TreeMap::new));
        }
    }

    /**
     * 剥掉注释：**说明里提到某个调用不算调用**。
     *
     * <p>⚠️ 朴素实现（不做词法分析）⇒ 字符串字面量里的 `//` 也会被截断；对本类的用途
     * （数调用点 / 声明点）无害，且比「让作者在注释里绕着写」稳。</p>
     */
    private static String withoutComments(String source) {
        return source.replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("(?m)//.*$", "");
    }

    /** 命中某个字面量的文件 → 命中次数（**剥注释后**）。 */
    private static Map<String, Integer> callSites(Map<String, String> sources, String literal) {
        Map<String, Integer> hits = new TreeMap<>();
        sources.forEach((file, text) -> {
            String code = withoutComments(text);
            int count = 0;
            int from = 0;
            while ((from = code.indexOf(literal, from)) >= 0) {
                count++;
                from += literal.length();
            }
            if (count > 0) {
                hits.put(file, count);
            }
        });
        return hits;
    }

    /** 某个方法名在哪些文件里被**声明**（`<返回类型> name(` 或 `void name(` 形态，剥注释后）。 */
    private static Map<String, Integer> declarationSites(Map<String, String> sources, String methodName) {
        Pattern decl = Pattern.compile("(?m)^\\s+(?:public |private |protected |static |final )*"
                + "[\\w<>,\\[\\] .]+?\\s+" + Pattern.quote(methodName) + "\\(");
        Map<String, Integer> hits = new TreeMap<>();
        sources.forEach((file, text) -> {
            Matcher m = decl.matcher(withoutComments(text));
            int count = 0;
            while (m.find()) {
                count++;
            }
            if (count > 0) {
                hits.put(file, count);
            }
        });
        return hits;
    }

    // ─────────────────────────────────────────── 判据 1

    @Test
    @DisplayName("判据 1·实现点登记表双向相等：第二份共享部件（新增承载文件）⇒ 红；登记了扫不到 ⇒ 也红")
    void sharedPartImplementationsLiveInTheRegisteredFiles() throws IOException {
        Map<String, String> sources = mainSources();

        Map<String, Set<String>> actual = new LinkedHashMap<>();
        REGISTERED_CALL_SITES.keySet().forEach(marker ->
                actual.put(marker, new TreeSet<>(callSites(sources, marker).keySet())));

        assertThat(actual)
                .as("共享部件的实现点不许出现第二份（真值源 = backend/admin-api/src/main/java/com/migao/admin/service/%s；"
                        + "表里每一条都必须是「剥掉注释后」的实测命中集）", PARTS)
                .isEqualTo(REGISTERED_CALL_SITES);
    }

    // ─────────────────────────────────────────── 判据 2

    @Test
    @DisplayName("判据 2·七个共享部件入口只允许在 OrderSharedParts 里声明一份（换文件复制 ⇒ 红并具名）")
    void sharedPartMethodsAreDeclaredOnlyOnce() throws IOException {
        Map<String, String> sources = mainSources();

        Map<String, Set<String>> actual = new LinkedHashMap<>();
        SINGLE_DECLARATION_METHODS.forEach(name ->
                actual.put(name, new TreeSet<>(declarationSites(sources, name).keySet())));

        assertThat(actual)
                .as("共享部件入口的声明点必须恰好是 %s 一份 —— 在别的服务里另起同名实现就是第二份口径", PARTS)
                .isEqualTo(SINGLE_DECLARATION_METHODS.stream()
                        .collect(Collectors.toMap(n -> n, n -> (Set<String>) new TreeSet<>(Set.of(PARTS)),
                                (a, b) -> a, LinkedHashMap::new)));
    }

    // ─────────────────────────────────────────── 判据 3

    @Test
    @DisplayName("判据 3·第三参只能是共享部件：五个入口收 OrderSharedParts，且**没有**门面兼容重载")
    void entriesTakeTheSharedPartsInstanceAndOnlyThat() throws Exception {
        assertSharedPartsEntry(OrderCreationService.class, "createOrder",
                new Class<?>[] {OrderCreateRequest.class, Long.class, OrderSharedParts.class},
                new Class<?>[] {OrderCreateRequest.class, Long.class, OrderService.class});
        assertSharedPartsEntry(OrderCreationService.class, "createOrderForAgent",
                new Class<?>[] {AgentOrderCreateRequest.class, Long.class, OrderSharedParts.class},
                new Class<?>[] {AgentOrderCreateRequest.class, Long.class, OrderService.class});
        assertSharedPartsEntry(OrderEntityWriteService.class, "updatePendingOrderContent",
                new Class<?>[] {String.class, OrderContentUpdateRequest.class, OrderSharedParts.class},
                new Class<?>[] {String.class, OrderContentUpdateRequest.class, OrderService.class});
        assertSharedPartsEntry(OrderLifecycleService.class, "updateOrderStatus",
                new Class<?>[] {String.class, String.class, OrderSharedParts.class},
                new Class<?>[] {String.class, String.class, OrderService.class});
        assertSharedPartsEntry(OrderLifecycleService.class, "cancelOrder",
                new Class<?>[] {String.class, String.class, OrderSharedParts.class},
                new Class<?>[] {String.class, String.class, OrderService.class});
    }

    private static void assertSharedPartsEntry(Class<?> owner, String name,
                                               Class<?>[] sharedPartsSignature, Class<?>[] facadeSignature) {
        assertThatCode(() -> owner.getMethod(name, sharedPartsSignature))
                .as("%s#%s 的第三参必须是共享部件实例（真值源 = backend/admin-api/src/main/java/com/migao/admin/service/%s）",
                        owner.getSimpleName(), name, PARTS)
                .doesNotThrowAnyException();
        assertThatThrownBy(() -> owner.getMethod(name, facadeSignature))
                .as("%s#%s 不许保留「门面实例」的兼容重载（留了就是第二份口径）", owner.getSimpleName(), name)
                .isInstanceOf(NoSuchMethodException.class);
    }

    // ─────────────────────────────────────────── 判据 4

    @Test
    @DisplayName("判据 4·门面实例不许再当参数传：src/main 里没有「形参类型 = OrderService」的方法")
    void theFacadeIsNeverPassedAsAParameter() throws IOException {
        Map<String, String> sources = mainSources();

        Map<String, Integer> offenders = new TreeMap<>();
        sources.forEach((file, text) -> {
            if ("OrderService.java".equals(file)) {
                return;   // 类自身不在面内（它不把自己的实例当参数传）
            }
            Matcher m = FACADE_PARAMETER.matcher(withoutComments(text));
            int count = 0;
            while (m.find()) {
                count++;
            }
            if (count > 0) {
                offenders.put(file, count);
            }
        });

        assertThat(offenders)
                .as("门面实例一旦重新作为参数出现，共享部件就会经门面传播 ⇒ 必须改用 OrderSharedParts")
                .isEmpty();
    }

    /** 反射自检：判据 3 的方法必须真的存在（防止 `getMethod` 名字写错时判据静默变空）。 */
    @Test
    @DisplayName("判据 0·判据 3 的五个入口真的在（防「名字写错 ⇒ 判据恒绿」）")
    void guardItselfReferencesRealEntries() throws Exception {
        int found = 0;
        for (String owner : SHARED_PARTS_ENTRIES.keySet()) {
            for (String name : SHARED_PARTS_ENTRIES.get(owner)) {
                Method[] methods = Class.forName("com.migao.admin.service." + owner).getMethods();
                String expected = owner;
                for (Method m : methods) {
                    if (m.getName().equals(name)) {
                        found++;
                        assertThat(m.getDeclaringClass().getSimpleName()).isEqualTo(expected);
                    }
                }
            }
        }
        assertThat(found).as("五个入口必须逐个找到（找不到 ⇒ 判据 3 会恒绿）。登记表 = %s", SHARED_PARTS_ENTRIES)
                .isEqualTo(5);
    }
}
