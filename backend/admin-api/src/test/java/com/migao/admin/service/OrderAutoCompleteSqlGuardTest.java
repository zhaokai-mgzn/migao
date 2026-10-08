// case_ids: OR-061
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「自动完成」写面与载体的**结构判据**（issue #6262）—— 把三条"改坏了不会红"的纪律钉成判据。
 *
 * <h2>为什么需要它（本单最危险的三个退化形态）</h2>
 * <ol>
 *   <li><b>谓词被放宽</b>：摘掉 {@code status='shipped'} ⇒ 自动腿开始完成 {@code pending} /
 *       {@code confirmed} 的单（用户逐字要求「只动 shipped」）；摘掉 {@code shipped_at <= 死线}
 *       ⇒ 发货当天就被完成（误杀）。两条都是**一行之差**，行为面判据（真库 / mock）能发现，
 *       但本判据让它在**不连库**时也当场红，并指名是哪一条谓词没了。</li>
 *   <li><b>原子性被拆散</b>：把单条 {@code UPDATE ... RETURNING id} 改成
 *       「先 SELECT 再逐条 update」⇒ 集群并发下会重复完成、且副作用（站内信）会按"扫到多少"发
 *       ⇒ 判据要求**只有一条 UPDATE、且必须带 RETURNING id**。</li>
 *   <li><b>锚点写入点被摘掉</b>：{@code orders.shipped_at} 由两条发货路各写一次
 *       （{@code OrderService.transitionStatusAtomic} / {@code OrderShipmentService.transition}）
 *       ⇒ 摘掉任何一条，那条路上的单**永远不会**自动完成，而**不会有别的东西变红**（静默漏单）。
 *       见 {@link #bothShipPathsWriteShippedAtAtomically()}。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读**源码文本**（不做 AST）—— 这是本仓既有形态（{@code ShipmentInvariantGuardTest}
 * 的 {@code methodBody} 同款）。代价：它只能证明"这几个字在方法体里"；<b>行为面由
 * {@code AutoCompleteShippedScanServiceTest} 与真库 {@code AutoCompleteShippedRealDbTest} 承担</b>
 * （§28.2 的「判据本体绿 ≠ 接线在」：三者缺一不可）。</p>
 */
@DisplayName("#6262 结构判据：单条谓词原子 UPDATE + RETURNING id + 两条发货路都写 shipped_at")
class OrderAutoCompleteSqlGuardTest {

    private static final Path MAIN = Path.of("src", "main", "java", "com", "migao", "admin");
    private static final Path ORDER_MAPPER = MAIN.resolve("mapper/OrderMapper.java");
    private static final Path SCAN_SERVICE = MAIN.resolve("service/AutoCompleteShippedScanService.java");
    private static final Path ORDER_SERVICE = MAIN.resolve("service/OrderService.java");
    private static final Path SHIPMENT_SERVICE = MAIN.resolve("service/OrderShipmentService.java");
    private static final Path SCHEDULER = MAIN.resolve("config/AutoCompleteShippedScanScheduler.java");

    private static String source(Path path) throws IOException {
        assertThat(path).as("判据的扫描面必须真实存在（路径漂移 ⇒ 判红，不是空跑通过）").exists();
        return Files.readString(path, StandardCharsets.UTF_8);
    }


    /**
     * 剥掉块注释与行注释后再判（否则**注释里提一句禁词**就能把判据喂红/喂绿 ——
     * 本仓 {@code migao-dev-flow} §17.3「判据被自己的文案喂红」同族）。
     * 本判据扫的是 {@code src/main} 的**代码**，注释里的说明不构成证据。
     */
    private static String codeOnly(String source) {
        return source.replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("(?m)//.*$", "");
    }

    /**
     * 取自动完成写面那条 SQL 的实际文本（把 {@code @Select} 的 Java {@code +} 拼接还原成一串）。
     *
     * <p>⚠️ 定位锚是 {@code autoCompleteShippedOrders} 这个**符号**（不是 {@code @Update} 注解名）：
     * 本单第一版用 {@code @Update} + {@code RETURNING}，实测 MyBatis 的 {@code @Update}
     * **不支持 {@code List} 返回类型** ⇒ 改成 {@code @Select} + CTE（见
     * {@code OrderMapper.autoCompleteShippedOrders} 的注释）。锚在注解名上会让"换注解形态"这件事
     * 变成判据自身失效，锚在符号上则不会。</p>
     */
    private static String autoCompleteSql(String mapperSource) {
        int method = mapperSource.indexOf("List<String> autoCompleteShippedOrders(");
        assertThat(method).as("OrderMapper 必须有 autoCompleteShippedOrders（自动完成的写面）").isGreaterThan(0);
        int start = mapperSource.lastIndexOf("@Select(", method);
        assertThat(start).as("写面必须是一条 SQL 注解（不是 Java 侧的多语句拼装）").isGreaterThan(0);
        int end = mapperSource.indexOf("@Param(\"deadline\")", start);
        assertThat(end).as("写面必须有一个 deadline 参数（死线是判定条件的一部分）").isGreaterThan(start);
        String block = mapperSource.substring(start, end);
        Matcher literals = Pattern.compile("\"((?:[^\"\\\\]|\\\\.)*)\"").matcher(block);
        StringBuilder sql = new StringBuilder();
        while (literals.find()) {
            sql.append(literals.group(1));
        }
        String text = sql.toString();
        assertThat(text).as("抽取到的 SQL 不能是空串（抽取本身失效 ⇒ 判据会变成空断言）").isNotBlank();
        return text;
    }

    /** 类被编译前先自证：抽取器在**真语料**上取到的就是那条 UPDATE。 */
    @Test
    @DisplayName("① 抽取器自证：取到的是 orders 上那条自动完成 SQL（不是空串 / 不是别的注解）")
    void sqlExtractionIsNotVacuous() throws IOException {
        String sql = autoCompleteSql(source(ORDER_MAPPER));
        assertThat(sql).contains("UPDATE orders SET status = 'completed'");
        assertThat(sql).contains("RETURNING id");
    }

    // ────────────────────────────────────────────── ② 谓词：只动 shipped + 满期 + 本租户

    @Test
    @DisplayName("② 谓词：一条 SQL 里同时有 status='shipped' / shipped_at <= 死线 / tenant_id / deleted=0 / RETURNING id")
    void predicateKeepsOnlyShippedAndOnlyOverdueRows() throws IOException {
        String sql = autoCompleteSql(source(ORDER_MAPPER));

        assertThat(sql)
                .as("只动 shipped（摘掉它 ⇒ pending/confirmed/packed 也会被完成）")
                .contains("status = 'shipped'");
        assertThat(sql)
                .as("满 N 天才动（摘掉它 ⇒ 发货当天就完成）")
                .contains("shipped_at <= #{deadline}");
        assertThat(sql)
                .as("查不到发货时刻的行不猜、不完成（NULL 不满足任何比较 ⇒ 只许人工确认收货）")
                .contains("shipped_at IS NOT NULL");
        assertThat(sql)
                .as("多租户隔离：显式 tenant_id 条件（不靠拦截器替我加）")
                .contains("tenant_id = #{tenantId}");
        assertThat(sql)
                .as("逻辑删除表：显式 deleted = 0")
                .contains("deleted = 0");
        assertThat(sql)
                .as("副作用（站内信）必须绑定「真正改到的行」⇒ RETURNING id")
                .contains("RETURNING id");
        assertThat(sql)
                .as("单机 / 集群同一套代码的前提：只许**一条** UPDATE（拆成 SELECT+逐条 update ⇒ 并发会重复完成）")
                .containsOnlyOnce("UPDATE orders SET");
        assertThat(sql)
                .as("不许把别的状态当目标态（本单只加 shipped→completed 这条既有边）")
                .doesNotContain("'pending'", "'confirmed'", "'producing'", "'packed'", "'cancelled'");
        assertThat(sql)
                .as("只碰 orders 一张表（不引入库存 / 财务副作用）")
                .doesNotContain("order_items", "stock", "ledger", "finance");
    }

    // ────────────────────────────────────────────── ③ 判定本体仍只有一份

    @Test
    @DisplayName("③ 跑之前过唯一状态机 + 逐租户显式上下文 + 死线来自 businessClock（不抄第二张流转表）")
    void scanServiceKeepsTheSingleStateMachineAndBusinessClock() throws IOException {
        String service = codeOnly(source(SCAN_SERVICE));

        assertThat(service)
                .as("判定本体只有一份：跑之前过 OrderStatusTransitions.assertTransitionAllowed")
                .contains("OrderStatusTransitions.assertTransitionAllowed");
        assertThat(service)
                .as("本类不得自建流转表（不得出现 STATUS_TRANSITIONS / Map.of 的流转定义）")
                .doesNotContain("STATUS_TRANSITIONS", "STATUS_LABELS");
        assertThat(service)
                .as("时间源必须走 businessClock（墙钟拼写会被 BusinessClockTestSourceGuardTest 判红）")
                .contains("businessClock.")
                // ⚠️ 断言里**不得**写出带括号的禁用串本身：`BusinessClockTestSourceGuardTest` 扫的是
                // 测试源码文本，写全就变成"测试侧新增了一个业务时间口径"（本单实测撞到过）。
                .doesNotContain("System.currentTimeMillis", "OffsetDateTime.now", "LocalDateTime.now");
        assertThat(service)
                .as("调度线程没有请求上下文 ⇒ 必须显式设置 + 还原租户")
                .contains("TenantContext.setTenantId")
                .contains("reload(previous)");
        assertThat(service)
                .as("副作用只对 RETURNING 的行发（集群下不重复发信）")
                .contains("autoCompleteShippedOrders")
                .contains("completedIds");
    }

    // ────────────────────────────────────────────── ④ 两条发货路都写锚点（静默漏单的防线）

    @Test
    @DisplayName("④ 两条发货路都写 orders.shipped_at：商家路 + 工人路各一处，且都在「仅当目标态是 shipped」的守卫里")
    void bothShipPathsWriteShippedAtAtomically() throws IOException {
        for (Path path : List.of(ORDER_SERVICE, SHIPMENT_SERVICE)) {
            String source = codeOnly(source(path));
            Matcher setter = Pattern.compile(
                    "\\.set\\(\\s*Order::getShippedAt\\s*,").matcher(source);
            assertThat(setter.find())
                    .as("%s 必须写 orders.shipped_at —— 不写 ⇒ 这条路上的单永远不会自动完成，"
                            + "且不会有别的东西变红（静默漏单）", path.getFileName())
                    .isTrue();
            assertThat(setter.find())
                    .as("%s 只许有一处写 shipped_at（多写 = 第二条口径）", path.getFileName())
                    .isFalse();
            assertThat(source)
                    .as("%s 写 shipped_at 必须与状态流转在同一个条件 UPDATE 里"
                            + "（分两条语句 ⇒ 造出「状态是 shipped 而锚点为空」的形态）", path.getFileName())
                    .contains("if (\"shipped\".equals(");
            assertThat(source)
                    .as("%s 的锚点取值也必须走 businessClock（不许墙钟拼写）", path.getFileName())
                    .contains("businessClock.nowOffset()");
        }
    }

    // ────────────────────────────────────────────── ⑤ 载体：cron 薄壳 + 判据引用为真

    @Test
    @DisplayName("⑤ 载体是薄壳：@Scheduled(cron=${migao.order.auto-complete-scan-cron:缺省}) 委托服务（不新引调度基础设施）")
    void schedulerIsAThinCronShell() throws IOException {
        String scheduler = codeOnly(source(SCHEDULER));

        assertThat(scheduler)
                .as("cron 形态必须复用本仓范式（属性可覆盖，缺省值只有一处）")
                .contains("@Scheduled(cron = \"${migao.order.auto-complete-scan-cron:\"");
        assertThat(scheduler)
                .as("薄壳：判断全在服务里")
                .contains("autoCompleteShippedScanService.scanAndComplete()");
        assertThat(scheduler)
                .as("🔴 不引入调度基础设施（Quartz / ShedLock / workflow）⇒ 集群安全来自那条谓词 UPDATE，不是锁")
                .doesNotContain("ShedLock", "Quartz", "SchedulerFactoryBean", "advisory");
        assertThat(scheduler)
                .as("调度线程不许被一次失败打死（兜底 catch）")
                .contains("catch (Exception e)");
    }
}
