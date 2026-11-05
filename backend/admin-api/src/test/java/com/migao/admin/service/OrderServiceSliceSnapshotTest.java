// case_ids: MC-199
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
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
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;

/**
 * {@link OrderService} 切片（issue #8191，P2-1c）的<b>行为快照</b>判据：同一组随机输入，
 * 拆分**前**（{@code origin/main}）录下的可观察行为记录，拆分**后**必须逐字节相同。
 *
 * <p><b>怎么录的</b>：本类先给全部门面协作者装上「记录型 Answer」——每次调用都带实参渲染进
 * {@code transcript}，再返回由随机种子决定的固定值；然后用 25 例种子随机数据驱动
 * {@code confirmPayment} / {@code restoreStockForReturn}，把「调用序列 + 返回值 + 异常类与话术」
 * 写成 {@code /order-slice/transcript.golden.txt}（**拆分前在 origin/main 上录制**）。</p>
 *
 * <p><b>为什么这条判据会红</b>：把 {@code OrderStockService} 的任何一行改动（分支、话术、金额口径、
 * 扣减/回补顺序、SKU 匹配回退顺序）都会改变调用序列或异常文本 ⇒ 与基线快照不等 ⇒ 红。
 * 录制与复算用的是**同一个测试文件**（拆分前后各跑一次），所以它比「拆分后仍绿」多一层时序证据。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderServiceSliceSnapshotTest test}；
 * 重新录制见类末 {@code orderslice.snapshot.write} 开关（只允许在拆分前的基线上用）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class OrderServiceSliceSnapshotTest {

    private static final String GOLDEN_RESOURCE = "/order-slice/transcript.golden.txt";
    private static final int CASES = 25;
    private static final long SEED = 20261104L;

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

    @InjectMocks
    private OrderService orderService;

    private final List<String> transcript = new ArrayList<>();

    private Order currentOrder;
    private List<OrderItem> currentItems = List.of();
    private Map<Long, ProductSku> skuById = Map.of();
    private List<ProductSku> skuRows = List.of();
    private Map<String, Object> deductRow;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(orderService, "businessClock",
                new BusinessClock(Clock.fixed(Instant.parse("2026-11-04T02:00:00Z"), ZoneOffset.UTC)));
        // Lambda 条件构造器需要实体 lambda 缓存（否则 MyBatis-Plus 抛「can not find lambda cache」），
        // 与 OrderServiceTest 同法；也保证 wrapper 的条件参数被渲染进快照。
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
        TableInfoHelper.initTableInfo(assistant, Product.class);
        wireAnswers();
    }

    @Test
    @DisplayName("行为快照：25 例种子随机输入的调用序列与结果，必须与拆分前录制的基线逐字节一致")
    void transcriptMatchesPreSplitBaseline() throws Exception {
        String actual = runCases();

        String write = System.getProperty("orderslice.snapshot.write", "");
        if (!write.isEmpty()) {
            Path out = Path.of(write);
            Files.writeString(out, actual, StandardCharsets.UTF_8);
            System.out.println("[#8191 快照] 已录制 " + actual.lines().count() + " 行 -> " + out);
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

    // ────────────────────────────────────────────── 随机用例

    private String runCases() {
        rendered.clear();
        Random rnd = new Random(SEED);
        for (int i = 0; i < CASES; i++) {
            transcript.clear();
            int variant = i % 5;
            String header;
            String outcome;
            try {
                header = driveVariant(variant, i, rnd);
                outcome = "OUTCOME OK";
            } catch (RuntimeException e) {
                header = "CASE " + i + " variant=" + variant;
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

    private final List<String> rendered = new ArrayList<>();

    private String driveVariant(int variant, int index, Random rnd) {
        String orderId = "order-" + index;
        switch (variant) {
            case 0 -> {
                // 确认支付：skuId 直查命中 + 库存充足 + 原子扣减成功
                currentOrder = order(orderId, "pending", new BigDecimal("1000.00"));
                long skuId = 100 + index;
                currentItems = List.of(item(orderId, "prod-" + (index % 3), "2.5", Map.of("skuId", skuId)));
                skuById = Map.of(skuId, sku(skuId, "prod-" + (index % 3), "2.8", "90.0"));
                deductRow = stockChangeRow("88.5", "86.0", "SKU-" + skuId);
                lifecycle().confirmPayment(orderId);
                return "CASE " + index + " variant=" + variant + " confirmPayment(skuId)";
            }
            case 1 -> {
                // 确认支付：无 skuId，走字符串族（colorName + 门幅归一化）回退
                currentOrder = order(orderId, "pending", new BigDecimal("520.00"));
                currentItems = List.of(item(orderId, "prod-1", "3.0",
                        Map.of("colorName", "米白", "doorWidth", "2.8米")));
                skuRows = List.of(sku(7L, "prod-1", "2.8", "40.0"));
                skuById = Map.of(7L, sku(7L, "prod-1", "2.8", "40.0"));
                deductRow = stockChangeRow("40.0", "37.0", "SKU-7");
                lifecycle().confirmPayment(orderId);
                return "CASE " + index + " variant=" + variant + " confirmPayment(keyFamily)";
            }
            case 2 -> {
                // 确认支付：声明了 SKU 身份却定位不到 ⇒ 必须显式拒绝（fail-closed）
                currentOrder = order(orderId, "pending", new BigDecimal("88.00"));
                currentItems = List.of(item(orderId, "prod-2", "1.0",
                        Map.of("skuCode", "NOPE", "colorName", "深灰", "doorWidth", "3.2")));
                skuRows = List.of();
                lifecycle().confirmPayment(orderId);
                return "CASE " + index + " variant=" + variant + " confirmPayment(unmatchable)";
            }
            case 3 -> {
                // 售后回补：skuId 命中 + 回补后读得到库存
                currentOrder = order(orderId, "completed", new BigDecimal("300.00"));
                long skuId = 40 + index;
                currentItems = List.of(item(orderId, "prod-0", "1.5", Map.of("skuId", skuId)));
                skuById = Map.of(skuId, sku(skuId, "prod-0", "2.8", "12.0"));
                orderService.restoreStockForReturn(orderId);
                return "CASE " + index + " variant=" + variant + " restoreStockForReturn(skuId)";
            }
            default -> {
                // 确认支付：库存不足（按真实米数比较，含 0.5 这种小数需求）
                currentOrder = order(orderId, "pending", new BigDecimal("45.00"));
                long skuId = 9 + index;
                currentItems = List.of(item(orderId, "prod-2", "0.5", Map.of("skuId", skuId)));
                skuById = Map.of(skuId, sku(skuId, "prod-2", "2.8", "0.2"));
                lifecycle().confirmPayment(orderId);
                return "CASE " + index + " variant=" + variant + " confirmPayment(insufficient)";
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
            rec("orderMapper.update", "<entity>", renderWrapper(inv.getArgument(1)), "->1");
            return 1;
        }).when(orderMapper).update(any(), any());

        doAnswer(inv -> {
            rec("processingOrderMapper.selectActiveByOrderId",
                    inv.getArgument(0), inv.getArgument(1), "->null");
            return null;
        }).when(processingOrderMapper).selectActiveByOrderId(any(), any());

        doAnswer(inv -> {
            rec("orderItemMapper.selectList", renderWrapper(inv.getArgument(0)),
                    "->" + currentItems.size() + " items");
            return currentItems;
        }).when(orderItemMapper).selectList(any());

        doAnswer(inv -> {
            ProductSku sku = skuById.get((Long) inv.getArgument(0));
            rec("productSkuMapper.selectById", inv.getArgument(0), "->" + renderSku(sku));
            return sku;
        }).when(productSkuMapper).selectById(any());

        doAnswer(inv -> {
            rec("productSkuMapper.selectList", renderWrapper(inv.getArgument(0)),
                    "->" + skuRows.size() + " rows");
            return skuRows;
        }).when(productSkuMapper).selectList(any());

        doAnswer(inv -> {
            rec("productSkuMapper.deductStock", inv.getArgument(0), inv.getArgument(1), inv.getArgument(2),
                    "->" + deductRow);
            return deductRow;
        }).when(productSkuMapper).deductStock(any(), any(), any());

        doAnswer(inv -> {
            rec("productSkuMapper.restoreStock", inv.getArgument(0), inv.getArgument(1), "->1");
            return 1;
        }).when(productSkuMapper).restoreStock(any(), any());

        doAnswer(inv -> {
            rec("productSkuMapper.increaseSalesCount", inv.getArgument(0), inv.getArgument(1));
            return null;
        }).when(productSkuMapper).increaseSalesCount(any(), any());

        doAnswer(inv -> {
            rec("productSkuMapper.decreaseSalesCount", inv.getArgument(0), inv.getArgument(1));
            return null;
        }).when(productSkuMapper).decreaseSalesCount(any(), any());

        doAnswer(inv -> {
            rec("productMapper.increaseSales", inv.getArgument(0), inv.getArgument(1), inv.getArgument(2), "->1");
            return 1;
        }).when(productMapper).increaseSales(any(), any(), any());

        doAnswer(inv -> {
            rec("productMapper.decreaseSales", inv.getArgument(0), inv.getArgument(1), inv.getArgument(2), "->1");
            return 1;
        }).when(productMapper).decreaseSales(any(), any(), any());

        doAnswer(inv -> {
            rec("stockLedgerService.record", inv.getArgument(0), inv.getArgument(1), inv.getArgument(2),
                    inv.getArgument(3), inv.getArgument(4), inv.getArgument(5), inv.getArgument(6),
                    inv.getArgument(7), inv.getArgument(8));
            return null;
        }).when(stockLedgerService).record(any(), any(), any(), any(), any(), any(), any(), any(), any());

        doAnswer(inv -> {
            rec("financeTransactionMapper.selectOne", renderWrapper(inv.getArgument(0)), "->null");
            return null;
        }).when(financeTransactionMapper).selectOne(any());

        doAnswer(inv -> {
            rec("financeTransactionMapper.insert", renderTxn(inv.getArgument(0)), "->1");
            return 1;
        }).when(financeTransactionMapper).insert(any(FinanceTransaction.class));
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
        if (value == null) {
            return "null";
        }
        if (value instanceof BigDecimal bd) {
            return bd.toPlainString();
        }
        return String.valueOf(value);
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
                + ",refund=" + plain(order.getRefundAmount()) + "}";
    }

    private static String renderSku(ProductSku sku) {
        if (sku == null) {
            return "null";
        }
        return "Sku{id=" + sku.getId()
                + ",product=" + sku.getProductId()
                + ",code=" + sku.getSkuCode()
                + ",color=" + sku.getColorId() + "/" + sku.getColorName()
                + ",width=" + sku.getDoorWidth()
                + ",stock=" + plain(sku.getStock()) + "}";
    }

    private static String renderTxn(Object value) {
        if (!(value instanceof FinanceTransaction txn)) {
            return render(value);
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

    private static String renderWrapper(Object value) {
        if (value instanceof com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?, ?, ?> wrapper) {
            Map<String, Object> params = new LinkedHashMap<>(wrapper.getParamNameValuePairs());
            StringBuilder sb = new StringBuilder("Wrapper{");
            params.entrySet().stream()
                    .sorted(Map.Entry.comparingByKey())
                    .forEach(e -> sb.append(e.getKey()).append('=').append(render(e.getValue())).append(';'));
            return sb.append('}').toString();
        }
        return render(value);
    }

    private static String plain(BigDecimal value) {
        return value == null ? "null" : value.toPlainString();
    }

    private static Order order(String id, String status, BigDecimal total) {
        return Order.builder()
                .id(id)
                .tenantId(1L)
                .orderNo("ORD-" + id)
                .status(status)
                .totalAmount(total)
                .actualAmount(total)
                .build();
    }

    private static OrderItem item(String orderId, String productId, String qty, Map<String, Object> info) {
        return OrderItem.builder()
                .id("item-" + orderId + "-" + productId)
                .tenantId(1L)
                .orderId(orderId)
                .productId(productId)
                .productName("商品-" + productId)
                .quantity(new BigDecimal(qty))
                .subtotal(new BigDecimal("99.00"))
                .processingInfo(new HashMap<>(info))
                .build();
    }

    private static ProductSku sku(Long id, String productId, String doorWidth, String stock) {
        return ProductSku.builder()
                .id(id)
                .productId(productId)
                .skuCode("SKU-" + id)
                .colorId(3L)
                .colorName("米白")
                .doorWidth(doorWidth)
                .stock(new BigDecimal(stock))
                .build();
    }

    private static Map<String, Object> stockChangeRow(String before, String after, String skuCode) {
        Map<String, Object> row = new HashMap<>();
        row.put("beforeQuantity", new BigDecimal(before));
        row.put("afterQuantity", new BigDecimal(after));
        row.put("skuCode", skuCode);
        return row;
    }

    /**
     * 门面**自己懒构造的那一份**生命周期实现点（issue #8681，P2-1e 第六批）：换的只是「谁被驱动」，
     * 同一条调用链、同一份协作者（Mapper / 库存 / 流水 / 时钟都是门面已装配的那几个）。
     */
    private OrderLifecycleService lifecycle() {
        return ReflectionTestUtils.invokeMethod(orderService, "lifecycleService");
    }

}
