// case_ids: MC-201
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.PrintLogMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;

/**
 * {@link OrderService} 生命周期族切片（issue #8191，P2-1d）的<b>行为快照</b>判据：同一组输入，
 * 拆分**前**（{@code origin/main} 的 2,268 行门面）录下的可观察行为记录，拆分**后**必须逐字节相同。
 *
 * <p><b>怎么录的</b>：给全部门面协作者装上「记录型 Answer」——每次调用都把实参渲染进
 * {@code transcript}，再用 23 例固定输入驱动取消 / 退款 / 发货 / 状态流转四族的**每一条分支**
 * （含 6 条拒绝路径），把「调用序列 + 返回值 + 异常类与话术」写成
 * {@code /order-lifecycle/transcript.golden.txt}（**拆分前在 origin/main 上录制**）。</p>
 *
 * <p><b>为什么这条判据会红</b>：改任何一个分支、异常话术、状态写面顺序、事务内的副作用顺序、
 * 退款金额口径、发货方式白名单，都会改变调用序列或异常文本 ⇒ 与基线快照不等 ⇒ 红。
 * 录制与复算用的是**同一个测试文件**（拆分前后各跑一次），所以它比「拆分后仍绿」多一层时序证据。</p>
 *
 * <p><b>时间戳为什么可复算</b>：{@code businessClock} 用冻结时钟钉住 ⇒ 它写出的三个锚点渲染成
 * {@code @businessClock}；业务代码里两处既有的墙钟拼写（并发探针时刻 / 退款时刻）渲染成
 * {@code @wallClock}（只证明「来源是墙钟」，不把当时那一秒写进基线 —— 那会让基线永远不可复算）。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderLifecycleSliceSnapshotTest test}；
 * 重新录制见类内 {@code orderlifecycle.snapshot.write} 开关（只允许在拆分前的基线上用）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class OrderLifecycleSliceSnapshotTest {

    private static final String GOLDEN_RESOURCE = "/order-lifecycle/transcript.golden.txt";
    private static final int CASES = 23;
    private static final Instant FROZEN = Instant.parse("2026-11-04T02:00:00Z");

    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private OrderLogisticsMapper orderLogisticsMapper;
    @Mock
    private CustomerService customerService;
    @Mock
    private ProductMapper productMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private FinanceTransactionMapper financeTransactionMapper;
    @Mock
    private NotificationService notificationService;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private UserService userService;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private StockLedgerService stockLedgerService;
    @Mock
    private ProcessingFeeCalculator processingFeeCalculator;
    @Mock
    private ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;
    @Mock
    private PrintLogMapper printLogMapper;
    @Mock
    private StockBatchConsumptionService stockBatchConsumptionService;

    @InjectMocks
    private OrderService orderService;

    private final List<String> transcript = new ArrayList<>();
    private final List<String> rendered = new ArrayList<>();

    private Order currentOrder;
    private List<OrderItem> currentItems = List.of();
    private ProcessingOrder activePo;
    private List<OrderLogistics> existingLogistics = List.of();
    private int updateRows = 1;
    private int poRows = 1;
    private int shipDetailRows = 1;

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        ReflectionTestUtils.setField(orderService, "businessClock",
                new BusinessClock(Clock.fixed(FROZEN, ZoneOffset.UTC)));
        // 批次回补访问器是**字段注入**（`cancelOrder` 经门面调用它）⇒ 手工装配（同 OrderServiceTest 的先例）
        ReflectionTestUtils.setField(orderService, "stockBatchConsumptionService", stockBatchConsumptionService);
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
        TableInfoHelper.initTableInfo(assistant, Product.class);
        TableInfoHelper.initTableInfo(assistant, OrderLogistics.class);
        wireAnswers();
    }

    @Test
    @DisplayName("行为快照：23 例固定输入下的调用序列 / 返回值 / 异常话术，必须与拆分前录制的基线逐字节一致")
    void transcriptMatchesPreSplitBaseline() throws Exception {
        String actual = runCases();

        String write = System.getProperty("orderlifecycle.snapshot.write", "");
        if (!write.isEmpty()) {
            Path out = Path.of(write);
            Files.createDirectories(out.getParent());
            Files.writeString(out, actual, StandardCharsets.UTF_8);
            System.out.println("[#8191 生命周期快照] 已录制 " + actual.lines().count() + " 行 -> " + out);
            return;
        }

        String golden;
        try (InputStream in = getClass().getResourceAsStream(GOLDEN_RESOURCE)) {
            assertThat(in).as("基线快照必须存在：" + GOLDEN_RESOURCE).isNotNull();
            golden = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
        assertThat(actual.lines().count()).as("快照行数（用例数变动 ⇒ 重录或补用例）").isEqualTo(golden.lines().count());
        assertThat(actual).as("拆分前后的可观察行为必须逐字节一致（差异 ⇒ 拆分改了行为）").isEqualTo(golden);
    }

    // ────────────────────────────────────────────── 用例驱动

    private String runCases() {
        rendered.clear();
        for (int i = 0; i < CASES; i++) {
            transcript.clear();
            String header;
            String outcome;
            try {
                header = driveVariant(i);
                outcome = "OUTCOME OK";
            } catch (RuntimeException e) {
                header = "CASE " + i + " " + headerOf(i);
                outcome = "OUTCOME ERR " + e.getClass().getSimpleName() + " :: " + e.getMessage();
            }
            StringBuilder sb = new StringBuilder(header).append('\n');
            for (String line : transcript) {
                sb.append("  ").append(line).append('\n');
            }
            sb.append("  ").append(outcome).append('\n');
            rendered.add(sb.toString());
        }
        return String.join("", rendered);
    }

    private static String headerOf(int index) {
        return "variant=" + index;
    }

    private String driveVariant(int index) {
        String orderId = "order-" + index;
        switch (index) {
            case 0 -> {
                // 取消：已确认 + 无加工单 ⇒ 回补库存 + 补记退款流水
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "1000.00", "1000.00");
                orderService.cancelOrder(orderId, "客户不要了");
                return "CASE " + index + " cancelOrder(confirmed)";
            }
            case 1 -> {
                // 取消：待付款 + 无加工单 ⇒ 无库存/流水副作用
                currentOrder = order(orderId, OrderStatusTransitions.PENDING, "520.00", "520.00");
                orderService.cancelOrder(orderId, null);
                return "CASE " + index + " cancelOrder(pending)";
            }
            case 2 -> {
                // 取消：生产中 + 加工单仍是 generated ⇒ CAS 作废 + 批次回补 + 回补库存 + 退款流水
                currentOrder = order(orderId, OrderStatusTransitions.PRODUCING, "800.00", "800.00");
                activePo = processingOrder(orderId, "generated");
                poRows = 1;
                orderService.cancelOrder(orderId, "客户改主意");
                return "CASE " + index + " cancelOrder(producing+po generated)";
            }
            case 3 -> {
                // 取消：加工单已发出 ⇒ 显式拒绝（要求先处理加工单）
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "300.00", "300.00");
                activePo = processingOrder(orderId, "issued");
                orderService.cancelOrder(orderId, "不要了");
                return "CASE " + index + " cancelOrder(po issued)";
            }
            case 4 -> {
                // 取消：加工单 CAS 抢不到（0 行）⇒ 409 冲突话术
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "300.00", "300.00");
                activePo = processingOrder(orderId, "generated");
                poRows = 0;
                orderService.cancelOrder(orderId, "不要了");
                return "CASE " + index + " cancelOrder(po cas lost)";
            }
            case 5 -> {
                // 取消：已发货 ⇒ 当前状态不允许取消
                currentOrder = order(orderId, OrderStatusTransitions.SHIPPED, "100.00", "100.00");
                orderService.cancelOrder(orderId, null);
                return "CASE " + index + " cancelOrder(shipped)";
            }
            case 6 -> {
                // 退款：部分退款（金额带两位小数）
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "600.00", "600.00");
                orderService.refundOrder(orderId, new BigDecimal("30.00"), "少发一件");
                return "CASE " + index + " refundOrder(partial)";
            }
            case 7 -> {
                // 退款：null = 全额退（封顶实收）
                currentOrder = order(orderId, OrderStatusTransitions.SHIPPED, "450.00", "450.00");
                orderService.refundOrder(orderId, null, null);
                return "CASE " + index + " refundOrder(full)";
            }
            case 8 -> {
                // 退款：待付款不可退款
                currentOrder = order(orderId, OrderStatusTransitions.PENDING, "450.00", "450.00");
                orderService.refundOrder(orderId, new BigDecimal("10.00"), "误下");
                return "CASE " + index + " refundOrder(pending)";
            }
            case 9 -> {
                // 退款：金额超过实收 ⇒ 显式拒绝
                currentOrder = order(orderId, OrderStatusTransitions.PRODUCING, "200.00", "200.00");
                orderService.refundOrder(orderId, new BigDecimal("500.00"), "多退");
                return "CASE " + index + " refundOrder(over)";
            }
            case 10 -> {
                // 发货：已确认 + 物流发货 ⇒ 记物流 + 原子流转 shipped
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "900.00", "900.00");
                shipDetailRows = 1;
                OrderService.OrderShipmentOutcome outcome =
                        orderService.shipWithLogistics(orderId, "SF1234567890", "顺丰");
                transcript.add("RETURN transitioned=" + outcome.transitioned()
                        + " result=" + renderMap(outcome.result()));
                return "CASE " + index + " shipWithLogistics(logistics)";
            }
            case 11 -> {
                // 发货：已发货状态只补记物流（不流转）
                currentOrder = order(orderId, OrderStatusTransitions.SHIPPED, "900.00", "900.00");
                shipDetailRows = 1;
                OrderService.OrderShipmentOutcome outcome =
                        orderService.shipWithLogistics(orderId, "YT0001", "圆通");
                transcript.add("RETURN transitioned=" + outcome.transitioned()
                        + " result=" + renderMap(outcome.result()));
                return "CASE " + index + " shipWithLogistics(already shipped)";
            }
            case 12 -> {
                // 发货：无需物流（shippingMethod=none）⇒ 运单号/承运商允许为空
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "900.00", "900.00");
                shipDetailRows = 1;
                OrderService.OrderShipmentOutcome outcome = orderService.shipWithLogistics(
                        orderId, "", "", new OrderLogisticsWriter.ShippingDetails("张三", "express", "none"));
                transcript.add("RETURN transitioned=" + outcome.transitioned()
                        + " result=" + renderMap(outcome.result()));
                return "CASE " + index + " shipWithLogistics(noLogistics)";
            }
            case 13 -> {
                // 发货：发货方式白名单外的值 ⇒ 422 显式拒绝
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "900.00", "900.00");
                orderService.shipWithLogistics(orderId, "SF1", "顺丰",
                        new OrderLogisticsWriter.ShippingDetails(null, null, "airdrop"));
                return "CASE " + index + " shipWithLogistics(bad method)";
            }
            case 14 -> {
                // 发货：待付款不可发货
                currentOrder = order(orderId, OrderStatusTransitions.PENDING, "900.00", "900.00");
                orderService.shipWithLogistics(orderId, "SF1", "顺丰");
                return "CASE " + index + " shipWithLogistics(pending)";
            }
            case 15 -> {
                // 发货：承运商缺失且无既有物流档案 ⇒ 422
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "900.00", "900.00");
                orderService.shipWithLogistics(orderId, "SF1", "   ");
                return "CASE " + index + " shipWithLogistics(no company)";
            }
            case 16 -> {
                // 发货：承运商缺失但客户档案已有常用物流 ⇒ 取既有值兜底
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "900.00", "900.00");
                existingLogistics = List.of(logistics(orderId, "德邦"));
                shipDetailRows = 1;
                OrderService.OrderShipmentOutcome outcome = orderService.shipWithLogistics(orderId, "DB1", null);
                transcript.add("RETURN transitioned=" + outcome.transitioned()
                        + " result=" + renderMap(outcome.result()));
                return "CASE " + index + " shipWithLogistics(company fallback)";
            }
            case 17 -> {
                // 状态流转：已确认 → 生产中（无库存副作用的原子流转）
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "700.00", "700.00");
                currentOrder.setUserId("user-7");
                orderService.updateOrderStatus(orderId, OrderStatusTransitions.PRODUCING);
                return "CASE " + index + " updateOrderStatus(confirmed->producing)";
            }
            case 18 -> {
                // 状态流转：已确认 → 取消（走 cancelOrder 路径）
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "700.00", "700.00");
                orderService.updateOrderStatus(orderId, OrderStatusTransitions.CANCELLED);
                return "CASE " + index + " updateOrderStatus(confirmed->cancelled)";
            }
            case 19 -> {
                // 状态流转：含加工项却无完成作业单 ⇒ 发货守卫拦截
                currentOrder = order(orderId, OrderStatusTransitions.CONFIRMED, "700.00", "700.00");
                currentItems = List.of(processingItem(orderId));
                orderService.updateOrderStatus(orderId, OrderStatusTransitions.SHIPPED);
                return "CASE " + index + " updateOrderStatus(shipped blocked)";
            }
            case 20 -> {
                // 状态流转：待付款 → 已确认（走 confirmPayment 路径）
                currentOrder = order(orderId, OrderStatusTransitions.PENDING, "260.00", "260.00");
                orderService.updateOrderStatus(orderId, OrderStatusTransitions.CONFIRMED);
                return "CASE " + index + " updateOrderStatus(pending->confirmed)";
            }
            case 21 -> {
                // 确认支付：直接入口（收款流水 + 状态锚点）
                currentOrder = order(orderId, OrderStatusTransitions.PENDING, "180.00", "180.00");
                orderService.confirmPayment(orderId);
                return "CASE " + index + " confirmPayment";
            }
            default -> {
                // 加工单作废回退：生产中 → 已确认（**回退边**，不得写支付时刻）
                currentOrder = order(orderId, OrderStatusTransitions.PRODUCING, "180.00", "180.00");
                orderService.revertProducingToConfirmed(orderId, "作业单作废");
                return "CASE " + index + " revertProducingToConfirmed";
            }
        }
    }

    // ────────────────────────────────────────────── 记录型协作者

    private void wireAnswers() {
        doAnswer(inv -> {
            rec("orderMapper.selectById", inv.getArgument(0), renderOrder(currentOrder));
            return currentOrder;
        }).when(orderMapper).selectById(any());

        doAnswer(inv -> {
            rec("orderMapper.update", "<entity>", renderWrapper(inv.getArgument(1)), "->" + updateRows);
            return updateRows;
        }).when(orderMapper).update(any(), any());

        doAnswer(inv -> {
            rec("processingOrderMapper.selectActiveByOrderId", inv.getArgument(0), inv.getArgument(1),
                    "->" + renderPo(activePo));
            return activePo;
        }).when(processingOrderMapper).selectActiveByOrderId(any(), any());

        doAnswer(inv -> {
            rec("processingOrderMapper.markStatusIfFrom", inv.getArgument(0), inv.getArgument(1),
                    inv.getArgument(2), inv.getArgument(3), render(inv.getArgument(9)),
                    inv.getArgument(10), render(inv.getArgument(11)), "->" + poRows);
            return poRows;
        }).when(processingOrderMapper).markStatusIfFrom(any(), any(), any(), any(), any(), any(), any(),
                any(), any(), any(), any(), any());

        doAnswer(inv -> {
            rec("processingOrderMapper.selectById", inv.getArgument(0), "->" + renderPo(activePo));
            return activePo;
        }).when(processingOrderMapper).selectById(any());

        doAnswer(inv -> {
            rec("orderItemMapper.selectList", renderWrapper(inv.getArgument(0)),
                    "->" + currentItems.size() + " items");
            return currentItems;
        }).when(orderItemMapper).selectList(any());

        doAnswer(inv -> {
            rec("orderLogisticsMapper.updateShippingDetails", inv.getArgument(0), inv.getArgument(1),
                    inv.getArgument(2), inv.getArgument(3), inv.getArgument(4), inv.getArgument(5),
                    inv.getArgument(6), "->" + shipDetailRows);
            return shipDetailRows;
        }).when(orderLogisticsMapper).updateShippingDetails(any(), any(), any(), any(), any(), any(), any());

        doAnswer(inv -> {
            rec("orderLogisticsMapper.selectByOrderId", inv.getArgument(0), inv.getArgument(1),
                    "->" + existingLogistics.size() + " rows");
            return existingLogistics;
        }).when(orderLogisticsMapper).selectByOrderId(any(), any());

        doAnswer(inv -> {
            rec("orderLogisticsMapper.insert", renderLogistics(inv.getArgument(0)), "->1");
            return 1;
        }).when(orderLogisticsMapper).insert(any(OrderLogistics.class));

        doAnswer(inv -> {
            rec("userService.resolveCurrentUserDisplayName", "->张三");
            return "张三";
        }).when(userService).resolveCurrentUserDisplayName();

        doAnswer(inv -> {
            rec("notificationService.triggerByEvent", inv.getArgument(0), inv.getArgument(1),
                    renderMap(inv.getArgument(2)));
            return null;
        }).when(notificationService).triggerByEvent(any(), anyString(), any());

        doAnswer(inv -> {
            rec("financeTransactionMapper.selectOne", renderWrapper(inv.getArgument(0)), "->null");
            return null;
        }).when(financeTransactionMapper).selectOne(any());

        doAnswer(inv -> {
            rec("financeTransactionMapper.insert", renderTxn(inv.getArgument(0)), "->1");
            return 1;
        }).when(financeTransactionMapper).insert(any(FinanceTransaction.class));

        doAnswer(inv -> {
            rec("stockBatchConsumptionService.reverse", inv.getArgument(0), inv.getArgument(1),
                    inv.getArgument(2), inv.getArgument(3), "->1");
            return 1;
        }).when(stockBatchConsumptionService).reverse(any(), any(), any(), any());
    }

    private void rec(String method, Object... args) {
        StringBuilder sb = new StringBuilder(method).append('(');
        for (int i = 0; i < args.length; i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(render(args[i]));
        }
        transcript.add(sb.append(')').toString());
    }

    private static String render(Object value) {
        if (value instanceof OffsetDateTime odt) {
            return odt.toInstant().equals(FROZEN) ? "@businessClock" : "@wallClock";
        }
        return renderPlain(value);
    }

    private static String renderPlain(Object value) {
        if (value == null) {
            return "null";
        }
        if (value instanceof BigDecimal bd) {
            return bd.toPlainString();
        }
        if (value instanceof Map<?, ?> map) {
            return renderMap(map);
        }
        if (value instanceof com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?> wrapper) {
            return renderWrapper(wrapper);
        }
        return String.valueOf(value);
    }

    private static String renderMap(Object value) {
        if (!(value instanceof Map<?, ?> map)) {
            return renderPlain(value);
        }
        StringBuilder sb = new StringBuilder("Map{");
        map.entrySet().stream()
                .sorted(Map.Entry.comparingByKey((a, b) -> String.valueOf(a).compareTo(String.valueOf(b))))
                .forEach(e -> sb.append(e.getKey()).append('=').append(renderPlain(e.getValue())).append(';'));
        return sb.append('}').toString();
    }

    private static String renderWrapper(Object value) {
        if (value instanceof com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?> wrapper) {
            Map<String, Object> params = new LinkedHashMap<>(wrapper.getParamNameValuePairs());
            StringBuilder sb = new StringBuilder("Wrapper{");
            params.entrySet().stream()
                    .sorted(Map.Entry.comparingByKey())
                    .forEach(e -> sb.append(e.getKey()).append('=').append(render(e.getValue())).append(';'));
            return sb.append('}').toString();
        }
        return renderPlain(value);
    }

    private static String renderOrder(Order order) {
        if (order == null) {
            return "null";
        }
        return "Order{id=" + order.getId()
                + ",tenant=" + order.getTenantId()
                + ",no=" + order.getOrderNo()
                + ",status=" + order.getStatus()
                + ",total=" + plain(order.getTotalAmount())
                + ",actual=" + plain(order.getActualAmount())
                + ",refund=" + plain(order.getRefundAmount())
                + ",user=" + order.getUserId() + "}";
    }

    private static String renderPo(ProcessingOrder po) {
        if (po == null) {
            return "null";
        }
        return "Po{id=" + po.getId()
                + ",no=" + po.getProcessingOrderNo()
                + ",status=" + po.getStatus() + "}";
    }

    private static String renderLogistics(Object value) {
        if (!(value instanceof OrderLogistics logistics)) {
            return renderPlain(value);
        }
        return "Logistics{orderId=" + logistics.getOrderId()
                + ",company=" + logistics.getLogisticsCompany()
                + ",tracking=" + logistics.getTrackingNo()
                + ",shipper=" + logistics.getShipperName()
                + ",type=" + logistics.getLogisticsType()
                + ",method=" + logistics.getShippingMethod()
                + ",status=" + logistics.getStatus()
                + ",shippedAt=" + render(logistics.getShippedAt()) + "}";
    }

    private static String renderTxn(Object value) {
        if (!(value instanceof FinanceTransaction txn)) {
            return renderPlain(value);
        }
        return "Txn{no=" + txn.getTransactionNo()
                + ",orderId=" + txn.getOrderId()
                + ",orderNo=" + txn.getOrderNo()
                + ",type=" + txn.getType()
                + ",amount=" + plain(txn.getAmount())
                + ",status=" + txn.getStatus()
                + ",operator=" + txn.getOperator()
                + ",remark=" + txn.getRemark() + "}";
    }

    private static String plain(BigDecimal value) {
        return value == null ? "null" : value.toPlainString();
    }

    // ────────────────────────────────────────────── 夹具

    private static Order order(String id, String status, String total, String actual) {
        return Order.builder()
                .id(id)
                .tenantId(1L)
                .orderNo("ORD-" + id)
                .status(status)
                .totalAmount(new BigDecimal(total))
                .actualAmount(new BigDecimal(actual))
                .build();
    }

    private static ProcessingOrder processingOrder(String orderId, String status) {
        return ProcessingOrder.builder()
                .id("po-" + orderId)
                .tenantId(1L)
                .orderId(orderId)
                .processingOrderNo("JG-" + orderId)
                .status(status)
                .build();
    }

    private static OrderLogistics logistics(String orderId, String company) {
        return OrderLogistics.builder()
                .tenantId(1L)
                .orderId(orderId)
                .logisticsCompany(company)
                .trackingNo("OLD-1")
                .build();
    }

    private static OrderItem processingItem(String orderId) {
        Map<String, Object> info = new HashMap<>();
        info.put("processingItems", List.of(Map.of("id", "p1", "name", "裁剪", "quantity", 1)));
        return OrderItem.builder()
                .id("item-" + orderId)
                .tenantId(1L)
                .orderId(orderId)
                .productId("prod-1")
                .productName("商品-1")
                .quantity(new BigDecimal("1.0"))
                .subtotal(new BigDecimal("700.00"))
                .processingInfo(info)
                .build();
    }
}
