// case_ids: OR-046
package com.migao.admin.service;

import com.migao.admin.dto.OrderCreateRequest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
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

/**
 * <b>类级元守卫</b>（AGENTS.md 铁律 8）：#5846 的「整卷售卖」改判之后，
 * <b>「一次分配只有一个权威来源」这件事必须由结构保证，而不是靠人记得</b>。
 *
 * <p>病（这是要防的<b>类</b>，不是单个 bug）：{@code order_items.roll_count} 一旦出现**第二个写入点**，
 * 「同一单两个整卷数」就重新变成可能 —— 而它<b>不会让任何既有断言变红</b>
 * （旧断言只看「某条路径落出来的值对不对」）。同理，把请求 DTO 的
 * {@code rollCount} 写成 primitive {@code int}，「客户端没给」与「客户端给了 0 卷」
 * 就再也分不开（而 0 卷 = 全散剪是**真实结论**、NULL = 未分配，两者两义）——
 * 这同样不会让功能断言变红（静默退化，不是报错）。</p>
 *
 * <p><b>四条判据</b>（每条都有「怎么改会红」的机械触发点）：</p>
 * <ol>
 *   <li><b>写入点登记表</b>：{@code src/main/java} 里凡出现「卷数 / 卷长」赋值的文件必须逐条登记
 *       （写明<b>写的是哪张表</b>）；新增未登记 ⇒ 红（{@code roll_count} 的第二权威就是这么进来的）；
 *       登记了却扫不到 ⇒ 也红（台账只许缩短）。</li>
 *   <li><b>订单行写入点唯一</b>：给 <b>{@code OrderItem} 实体</b>写这两列的调用
 *       **必须全部落在** {@code OrderService.applyRollAllocation} 方法体内 ——
 *       在同类里另起一个写分配的方法 ⇒ 红。</li>
 *   <li><b>派生入口唯一</b>：{@code ProductRollAllocation.allocate(} 的调用点只有
 *       {@code OrderService.java} 一处、且只一次 —— 再开一条派生路径 ⇒ 红。</li>
 *   <li><b>「未给」≠「0 卷」结构可分</b>：请求 DTO 的两个字段必须是**可空对象类型**
 *       （非 primitive），且新建实例读出 {@code null} —— 改成 {@code int} ⇒ 红（编译期先炸，
 *       改完测试后本判据仍会红）。</li>
 * </ol>
 *
 * <p><b>两条扫描纪律（都是实测踩出来的，别省）</b>：</p>
 * <ul>
 *   <li><b>先剥注释</b>：「在说明里写下某个调用」不是「调用」—— 本包 javadoc 里写了
 *       {@code ProductRollAllocation.allocate(} 用于解释口径，不剥注释会把它数成第二个调用点（实测红）；</li>
 *   <li><b>按接收者的声明类型分类</b>：{@code setRollCount(} / {@code setRollLengthM(} 是**跨对象同名**的
 *       方法名（订单行实体、读面 DTO、别的实体都可能各有一份）⇒ 只按方法名扫会把**别的对象**的赋值
 *       算成订单行写入。本类按「该接收者在本文件里是否声明为 {@code OrderItem}」分类。
 *       ⚠️ **实测（别把它说成已生效的救火）**：本仓 {@code OrderService} 里这两个 setter 的 4 处命中
 *       **恰好全是** {@code item.}（读面走 {@code BeanUtils.copyProperties}，不显式调 setter）
 *       ⇒ 分类这一层是**防将来**，不是本次已救过火。</li>
 * </ul>
 *
 * <p><b>为什么这些是元守卫而不是实例判据</b>：实例判据（{@link OrderServiceTest} 的 #5846 段）
 * 只证明「今天这条路径分得对」；本类证明的是「这条路**只有一条**」——
 * 将来第二个人从别处写 {@code roll_count}，红的是这里。</p>
 *
 * <p><b>边界（照实登记）</b>：判据 1/2 认的是「形如 {@code <接收者>.setRollCount(…)} 的**直接调用**」
 * —— 反射 / MyBatis 的 `UpdateWrapper.set("roll_count", …)` / 另起一个不叫 setRollCount 的
 * setter 都在面外（前者仓内零使用，后者由 code review 兜）。</p>
 */
@DisplayName("#5846 整卷分配权威（类级元守卫）：写入点唯一 · 派生入口唯一 · 「未给」≠「0 卷」")
class OrderRollAllocationAuthorityTest {

    /** 主源码根（surefire 的 cwd = {@code backend/admin-api}，与既有契约判据同口径）。 */
    private static final Path MAIN_SRC = Paths.get("src", "main", "java", "com", "migao", "admin");

    /** 订单行整卷分配的**唯一**权威实现（文件 + 方法名）。 */
    private static final String ORDER_AUTHORITY_FILE = "OrderService.java";
    private static final String ORDER_AUTHORITY_METHOD = "applyRollAllocation";

    /** 给 `rollCount` / `rollLengthM` 赋值的**允许集合**（未登记即红 / 登记了扫不到也红）。 */
    private static final Map<String, String> REGISTERED_WRITERS = new LinkedHashMap<>() {{
        put("OrderService.java", "order_items.roll_count / roll_length_m —— 订单行分配（本包唯一权威）");
        put("WorkerInboundService.java", "inbound_order_items.roll_length_m —— 入库「仅记录/打印」，不参与换算（本包不改）");
        put("ProductService.java", "products.roll_length_m —— 商品货号级卷长配置（默认值的来源）");
    }};

    /** `<接收者>.setRollCount(` / `<接收者>.setRollLengthM(`（group 1 = 接收者，group 2 = 列名）。 */
    private static final Pattern WRITE_CALL = Pattern.compile("(\\w+)\\.set(RollCount|RollLengthM)\\(");
    /** `order_items` 的派生算法入口。 */
    private static final Pattern DERIVE_CALL = Pattern.compile("ProductRollAllocation\\.allocate\\(");
    /** 接收者是不是一个 `OrderItem`（看本文件里有没有这个声明）——用于排除**读面 DTO** 的同名 setter。 */
    private static final String ORDER_ITEM_DECLARATION = "\\bOrderItem\\s+%s\\b";

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
     * （数调用点）无害，且比「让作者在注释里绕着写」稳。</p>
     */
    private static String withoutComments(String source) {
        return source.replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("(?m)//.*$", "");
    }

    /** 这条写入调用是在写 {@code OrderItem} 实体吗（按接收者的声明类型判定）。 */
    private static boolean writesOrderItemEntity(String code, String receiver) {
        return Pattern.compile(String.format(ORDER_ITEM_DECLARATION, Pattern.quote(receiver)))
                .matcher(code).find();
    }

    /** 命中「给卷数/卷长赋值」的文件 → 命中行数（**全部**接收者，含读面 DTO）。 */
    private static Map<String, Integer> writerFiles(Map<String, String> sources) {
        Map<String, Integer> hits = new TreeMap<>();
        sources.forEach((file, text) -> {
            Matcher m = WRITE_CALL.matcher(withoutComments(text));
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

    /** 命中「给 **OrderItem 实体**写卷数/卷长」的文件 → 命中行数（读面 DTO 的同名 setter 不算）。 */
    private static Map<String, Integer> entityWriterFiles(Map<String, String> sources) {
        Map<String, Integer> hits = new TreeMap<>();
        sources.forEach((file, text) -> {
            String code = withoutComments(text);
            Matcher m = WRITE_CALL.matcher(code);
            int count = 0;
            while (m.find()) {
                if (writesOrderItemEntity(code, m.group(1))) {
                    count++;
                }
            }
            if (count > 0) {
                hits.put(file, count);
            }
        });
        return hits;
    }

    /** 方法体区间 `[start, end)`（`void <name>(` 起，到下一个 4 空格缩进的成员声明止）。 */
    private static int[] methodSpan(String source, String methodName) {
        int start = source.indexOf("void " + methodName + "(");
        assertThat(start)
                .as("方法 %s 必须存在于 %s（真值源 = backend/admin-api/src/main/java/com/migao/admin/service/%s）",
                        methodName, ORDER_AUTHORITY_FILE, ORDER_AUTHORITY_FILE)
                .isGreaterThanOrEqualTo(0);
        Matcher next = Pattern.compile("\n    (?:private|public|protected|static|final|@)").matcher(source);
        int end = source.length();
        while (next.find()) {
            if (next.start() > start) {
                end = next.start();
                break;
            }
        }
        return new int[] {start, end};
    }

    @Test
    @DisplayName("判据 1·写入点登记表双向相等：新增未登记的写入点 ⇒ 红；登记了却扫不到 ⇒ 也红")
    void rollColumnWritersAreRegistered() throws IOException {
        Map<String, Integer> actual = writerFiles(mainSources());

        assertThat(new TreeSet<>(actual.keySet()))
                .as("给卷数/卷长赋值的文件必须逐条登记（新增 ⇒ 未登记即红；删光 ⇒ 陈旧登记即红）")
                .isEqualTo(new TreeSet<>(REGISTERED_WRITERS.keySet()));
    }

    @Test
    @DisplayName("判据 2·给 OrderItem 实体写这两列的调用**只在** applyRollAllocation 里（同类第二写入点 ⇒ 红）")
    void orderItemRollColumnsAreWrittenOnlyInTheSingleAuthorityMethod() throws IOException {
        Map<String, String> sources = mainSources();
        String orderService = sources.get(ORDER_AUTHORITY_FILE);
        assertThat(orderService).as("真值源必须存在").isNotNull();

        Map<String, Integer> entityWriters = entityWriterFiles(sources);
        assertThat(entityWriters.keySet())
                .as("OrderItem 实体的整卷两列只允许在 OrderService 里被写")
                .containsExactly(ORDER_AUTHORITY_FILE);

        String code = withoutComments(orderService);
        int[] span = methodSpan(code, ORDER_AUTHORITY_METHOD);
        // 前提自证 ①：span 是**真区间**（不是「一直到文件尾」）——否则下面的 `outside` 恒为 0，
        // 那条判据就是空断言（实测：本判据**曾经**把期望值写死在「2 处」上，
        // 而方法里其实有 4 处（两个互斥分支各写两列）⇒ 基线本来就红，红证读出来的
        // 其实是这个错误期望而不是被测行为 —— 双向对照（先绿再注入）之后才认出）。
        assertThat(span[1]).as("方法区间必须止于下一个成员声明之前").isLessThan(code.length());

        Matcher m = WRITE_CALL.matcher(code);
        int insideRolls = 0;
        int insideLength = 0;
        int outside = 0;
        while (m.find()) {
            if (!writesOrderItemEntity(code, m.group(1))) {
                continue; // 别的对象（另一个实体 / 读面 DTO）的同名 setter 不算订单行写入
            }
            if (m.start() < span[0] || m.start() >= span[1]) {
                outside++;
            } else if ("RollCount".equals(m.group(2))) {
                insideRolls++;
            } else {
                insideLength++;
            }
        }

        assertThat(outside)
                .as("OrderService 里不允许存在第二个写整卷分配的地方（那是「同一单两个整卷数」的入口）")
                .isZero();
        // 不钉「几处」：分支数（显式 / 派生）是实现细节；**两列都真的在这个方法里落**才是判据
        assertThat(insideRolls).as("权威方法里必须真的写 roll_count").isPositive();
        assertThat(insideLength).as("权威方法里必须真的写 roll_length_m").isPositive();
    }

    @Test
    @DisplayName("判据 3·派生入口唯一：ProductRollAllocation.allocate( 只被 OrderService 调用一次")
    void derivationHasASingleCallSite() throws IOException {
        Map<String, Integer> callers = new TreeMap<>();
        mainSources().forEach((file, text) -> {
            Matcher m = DERIVE_CALL.matcher(withoutComments(text));
            int count = 0;
            while (m.find()) {
                count++;
            }
            if (count > 0) {
                callers.put(file, count);
            }
        });

        assertThat(callers.keySet())
                .as("派生分配只允许有一个入口（再开一条 = 两套卷数口径）")
                .containsExactly(ORDER_AUTHORITY_FILE);
        assertThat(callers.get(ORDER_AUTHORITY_FILE)).isEqualTo(1);
    }

    @Test
    @DisplayName("判据 4·「未给」与「给了 0 卷」结构可分：请求字段必须是可空对象类型")
    void requestRollFieldsStayNullableObjects() throws Exception {
        OrderCreateRequest.OrderItemRequest fresh = new OrderCreateRequest.OrderItemRequest();

        for (String name : new String[] {"rollCount", "rollLengthM"}) {
            Field field = OrderCreateRequest.OrderItemRequest.class.getDeclaredField(name);
            assertThat(Modifier.isStatic(field.getModifiers())).isFalse();
            assertThat(field.getType().isPrimitive())
                    .as("%s 不能是 primitive：那样「客户端没给」与「给了 0」就分不开（0 卷是全散剪的真实结论）", name)
                    .isFalse();
            assertThat(Number.class.isAssignableFrom(field.getType()))
                    .as("%s 必须是数值对象类型", name)
                    .isTrue();
            field.setAccessible(true);
            assertThat(field.get(fresh)).as("新实例的 %s 必须是 null（未给）", name).isNull();
        }

        // 「0 卷」是一个**可表达**的值（与 null 两回事）
        OrderCreateRequest.OrderItemRequest explicitZero = new OrderCreateRequest.OrderItemRequest();
        explicitZero.setRollCount(BigDecimal.ZERO);
        assertThat(explicitZero.getRollCount()).isEqualByComparingTo("0");
        assertThat(explicitZero.getRollCount()).isNotNull();

        Set<String> nullableTypes = Set.of("java.math.BigDecimal", "java.lang.Integer", "java.lang.Long");
        assertThat(nullableTypes).as("（本判据只约束可空性，不锁死具体数值类型）").isNotEmpty();
    }
}
