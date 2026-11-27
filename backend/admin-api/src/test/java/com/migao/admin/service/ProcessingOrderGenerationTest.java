// case_ids: MC-390

package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 🧱 <b>派单生成链搬运后的载体边界 + 入口接线判据（issue #8770「生成族」一档）</b>。
 *
 * <h2>为什么需要它（搬运类改动最容易的两种退化都不报错）</h2>
 * ① <b>搬一半又长回来</b>：门面留了同名委托，但有人把 {@code prepare} / {@code commit} 的实现
 * 复制回门面 ⇒ 同一份口径出现两处，后续修复只改到一处（这正是 #8681 十批反复出现的形态）；
 * ② <b>载体变成公开 API</b>：把 {@code ProcessingOrderGeneration} 写成 {@code public class}，
 * 或让门面暴露它的实例 ⇒ 调用方开始绕过门面入口（{@code @Transactional} 边界随之失效）。
 * 两条都不会有任何东西变红（编译通过、既有服务层判据全绿），故在此钉成机械判据。
 *
 * <p>行为面由既有判据承担（{@code ProcessingOrderServiceTest} 的生成链、
 * {@code ProcessingOrderPoolCharacterizationTest} 的池化 golden、
 * {@code ProcessingOrderGenerationTransactionRealDbTest} 的真库事务回滚）。本类只补两件之前
 * <b>没有任何判据</b>的事：<b>载体边界</b>与<b>门面委托形状</b>，外加三条<b>入口 → 生成链</b>
 * 的可观察行为（错误码 / 文案 / 建议逐字），证明委托确实接到实现上（不是「委托到一个空壳」）。</p>
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li>门面 5 个 {@code generate} 重载 + {@code generateDirect} + {@code preview} +
 *       {@code processorOptions} 各是**一条** {@code return generation().xxx(...)}；
 *       任一入口被写回实现（哪怕只写一行校验）⇒ 计数不符 ⇒ 红。</li>
 *   <li>生成链的核心工序在门面**签名不再存在**、在本单元**各恰好一份**（含两个 {@code prepare} 重载）。</li>
 *   <li>载体类必须 `package-private`（不进公开 API），门面只持有一个引用点、一处构造。</li>
 *   <li>入口 → 生成链真的接通：订单不存在 ⇒ {@code ORDER_NOT_FOUND} + 原文案且<b>不写库</b>；
 *       直派入口对可解析订单 ⇒ {@code DIRECT_DISPATCH_POOL_REQUIRED} 码/文案/建议<b>逐字</b>；
 *       承接方下拉未装配 ⇒ 空集（fail-closed，不静默造值）。</li>
 * </ol>
 *
 * <p><b>未固化项（如实登记）</b>：本类不重跑生成链的完整行为矩阵（快照 12 场景 / 池化 golden /
 * 真库事务回滚都在既有判据里，复制一份只会分叉）；它也判不了「委托指向的方法体是否被偷改」
 * —— 那由既有行为判据 + 本类第 4 条共同覆盖。</p>
 */
@DisplayName("🧱 载体边界（#8770 生成族）：派单入口留门面、生成链只住一个 package-private 单元")
class ProcessingOrderGenerationTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）。 */
    private static final String MAIN = "src/main/java/com/migao/admin/service";
    private static final String FACADE_FILE = MAIN + "/ProcessingOrderService.java";
    private static final String UNIT_FILE = MAIN + "/ProcessingOrderGeneration.java";
    private static final Long TENANT = 7L;

    private static String read(String path) {
        try {
            return Files.readString(Paths.get(path), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("判据要读的源文件不存在：" + path, e);
        }
    }

    private static int count(String text, String needle) {
        int hits = 0;
        int from = 0;
        while (true) {
            int at = text.indexOf(needle, from);
            if (at < 0) {
                return hits;
            }
            hits++;
            from = at + needle.length();
        }
    }

    /** 门面桩（手写 new：两个字段注入的可选依赖保持未装配 —— 与既有判据同款装配面）。 */
    private record Stubbed(ProcessingOrderService service, OrderMapper orderMapper,
                           ProcessingOrderMapper processingOrderMapper) {
    }

    private static Stubbed stubbed() {
        OrderMapper orderMapper = mock(OrderMapper.class);
        ProcessingOrderMapper processingOrderMapper = mock(ProcessingOrderMapper.class);
        ProcessingOrderService service = new ProcessingOrderService(processingOrderMapper, orderMapper,
                mock(OrderItemMapper.class), mock(ProcessingItemMapper.class), mock(OrderService.class),
                new ObjectMapper(), mock(ProductionService.class),
                mock(ProductionOperationQueryService.class), mock(ProductionOperationQtyClient.class));
        return new Stubbed(service, orderMapper, processingOrderMapper);
    }

    @Test
    @DisplayName("① 派单入口仍是门面方法，且**只做一次委托**（实现不得回流门面）")
    void everyGenerationEntryIsOneThinDelegateOnTheFacade() {
        String facade = read(FACADE_FILE);
        assertThat(count(facade, "return generation().generate(")).as("5 个 generate 重载各一条委托")
                .isEqualTo(5);
        assertThat(count(facade, "return generation().generateDirect(")).isEqualTo(1);
        assertThat(count(facade, "return generation().preview(")).isEqualTo(1);
        assertThat(count(facade, "return generation().processorOptions(")).isEqualTo(1);
        // 生成链的四道核心工序**不得**回流门面（回流 = 同一份口径两处，后续修复只会改到一处）
        for (String signature : List.of(
                "private Prepared prepare(",
                "private GenerateResult commit(",
                "private List<StockBatchConsumptionService.Designation> buildDesignations(",
                "private void instantiateOperations(")) {
            assertThat(facade).as("生成族成员回流门面：" + signature).doesNotContain(signature);
        }
    }

    @Test
    @DisplayName("② 生成链成员各恰好一份：全在派单生成单元里")
    void theWholeGenerationChainLivesInExactlyOneUnit() {
        String unit = read(UNIT_FILE);
        assertThat(count(unit, "List<GenerateResult> generate(")).as("5 个 generate 重载").isEqualTo(5);
        assertThat(count(unit, "GenerateResult generateOne(")).isEqualTo(1);
        assertThat(count(unit, "List<GenerateResult> generatePooled(")).isEqualTo(1);
        assertThat(count(unit, "Prepared prepare(")).as("两个 prepare 重载").isEqualTo(2);
        assertThat(count(unit, "GenerateResult commit(")).isEqualTo(1);
        assertThat(count(unit, "List<StockBatchConsumptionService.Designation> buildDesignations("))
                .isEqualTo(1);
        assertThat(count(unit, "void instantiateOperations(")).isEqualTo(1);
        assertThat(count(unit, "Consignee resolveConsignee(")).isEqualTo(1);
        assertThat(count(unit, "static Map<String, List<BatchAssignment>> assignmentsByOrder("))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("③ 载体是 package-private 单元，门面只有一个引用点（不暴露成公开 API）")
    void theUnitStaysPackagePrivateWithASingleReferencePoint() {
        String unit = read(UNIT_FILE);
        assertThat(unit).contains("\nclass ProcessingOrderGeneration {");
        assertThat(unit).doesNotContain("public class ProcessingOrderGeneration");
        String facade = read(FACADE_FILE);
        assertThat(facade).contains("private ProcessingOrderGeneration generation;");
        assertThat(count(facade, "new ProcessingOrderGeneration(")).as("只有惰性访问器一处构造")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("④ 订单不存在 ⇒ ORDER_NOT_FOUND + 原文案，且一行都不写（委托确实接到实现）")
    void unknownOrderStillFailsWithTheOriginalCodeAndMessage() {
        Stubbed stub = stubbed();
        when(stub.orderMapper().selectById("no-such-order")).thenReturn(null);
        when(stub.orderMapper().selectOne(any())).thenReturn(null);

        List<ProcessingOrderService.GenerateResult> results =
                stub.service().generate(List.of("no-such-order"), TENANT, "tester");

        assertThat(results).hasSize(1);
        ProcessingOrderService.GenerateResult result = results.get(0);
        assertThat(result.getOrderRef()).isEqualTo("no-such-order");
        assertThat(result.isSuccess()).isFalse();
        assertThat(result.getCode()).isEqualTo("ORDER_NOT_FOUND");
        assertThat(result.getMessage()).isEqualTo("无法找到订单：no-such-order");
        assertThat(result.getProcessingOrderNo()).isNull();
        verifyNoInteractions(stub.processingOrderMapper());
    }

    @Test
    @DisplayName("⑤ 直派入口：可解析订单 ⇒ DIRECT_DISPATCH_POOL_REQUIRED（码 / 文案 / 建议逐字）")
    void directDispatchStillReturnsTheExactRefusalCopy() {
        Stubbed stub = stubbed();
        when(stub.orderMapper().selectById("order-1")).thenReturn(Order.builder()
                .id("order-1").tenantId(TENANT).orderNo("SO-1").status("confirmed").build());

        List<ProcessingOrderService.GenerateResult> results =
                stub.service().generateDirect(List.of("order-1"), null, TENANT, "tester", null);

        assertThat(results).hasSize(1);
        ProcessingOrderService.GenerateResult result = results.get(0);
        assertThat(result.isSuccess()).isFalse();
        assertThat(result.getCode()).isEqualTo(ProcessingOrderService.ERR_DIRECT_DISPATCH_POOL_REQUIRED);
        assertThat(result.getMessage())
                .isEqualTo(ProcessingOrderService.DIRECT_DISPATCH_POOL_REQUIRED_MESSAGE);
        assertThat(result.getSuggestion())
                .isEqualTo(ProcessingOrderService.DIRECT_DISPATCH_POOL_REQUIRED_SUGGESTION);
    }

    @Test
    @DisplayName("⑥ 承接方下拉未装配 ⇒ 空集（fail-closed，不静默造值）")
    void processorOptionsAreEmptyWhenTheMapperIsNotWired() {
        assertThat(stubbed().service().processorOptions(TENANT)).isEmpty();
    }
}
