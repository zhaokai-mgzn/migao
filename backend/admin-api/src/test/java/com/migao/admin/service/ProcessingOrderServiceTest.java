package com.migao.admin.service;
// case_ids: PG-001, PG-002, PG-003, PG-004, PG-005, PG-006, PG-007, PG-008, PG-011, PG-018, UI-030

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 加工单服务单元测试（issue #3340）
 * 覆盖：生成（快照五要素 + options + 无销售价）、幂等、状态机、取消联动、租户隔离。
 */
@ExtendWith(MockitoExtension.class)
class ProcessingOrderServiceTest {

    private static final Long TENANT = 1L;

    @InjectMocks
    private ProcessingOrderService processingOrderService;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    @Mock
    private ProcessingItemMapper processingItemMapper;

    @Mock
    private OrderService orderService;

    @Mock
    private ProductionService productionService;

    /** issue #4116 全链路用例（生成 → 实例化）用：真实 ProductionService 的 DB 层依赖 */
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;

    @Mock
    private ProductionWorkLogMapper workLogMapper;

    /** 报工幂等键服务（issue #4116 §5-1）：本用例只走实例化、不触发报工 ⇒ 只需一个可用桩 */
    @Mock
    private ClientRequestIdService clientRequestIdService;

    /** 工序来源（issue #4116 切库）：生成加工单必须能读到工序库，故每个生成用例都要打桩 */
    @Mock
    private ProductionOperationQueryService productionOperationQueryService;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    // ── 工序库（V54 种子）桩 ─────────────────────────────────────────
    //
    // 切库后（issue #4116 用户裁定）工序来源 = production_routings + production_operations
    // ⇒ 生成加工单必须先能读到库。下列常量**逐字抄自 V54__seed_production_operations.sql**
    // （rt-v54-01 / rt-v54-02 的工序序列 + 对应工序行的分组/单位/单价/is_must_finish/is_start_marker），
    // 所以「实例 = 库」的断言是真比对，而不是拿一份平行真值自证。
    // 列序：工序 / 分组 / 单位 / 单价 / is_must_finish / is_start_marker

    /** rt-v54-01 布帘×韩褶 —— 11 道（行业 ERP 实证走线）。 */
    private static final String[][] V54_BULIAN_HANZHE = {
            {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
            {"布三边", "车位", "米", "0.4", "false", "false"},
            {"韩褶-布", "车位", "折", "0.4", "false", "false"},
            {"上车布-布", "车位", "米", "0.5", "false", "false"},
            {"熨烫-布", "后道", "米", "0.35", "false", "false"},
            {"定型-布", "后道", "米", "0.4", "false", "false"},
            {"复烫-布", "后道", "米", "0.35", "false", "false"},
            {"布帘车被", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /** rt-v54-02 布帘×打孔 —— 10 道。 */
    private static final String[][] V54_BULIAN_DAKONG = {
            {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
            {"布三边", "车位", "米", "0.4", "false", "false"},
            {"打孔-布", "车位", "孔", "0.15", "false", "false"},
            {"熨烫-布", "后道", "米", "0.35", "false", "false"},
            {"定型-布", "后道", "米", "0.4", "false", "false"},
            {"复烫-布", "后道", "米", "0.35", "false", "false"},
            {"布帘车被", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /**
     * 工序库桩：把 V54 的两条路线装进 findRouting；未登记的键返回 null
     * （= 库里没有该路线 ⇒ 走默认路线兜底，仍没有才 fail-closed）。
     */
    private void stubLibrary() {
        when(productionOperationQueryService.findRouting(eq(TENANT), anyString(), anyString()))
                .thenAnswer(inv -> v54Route(inv.getArgument(1), inv.getArgument(2)));
    }

    /** V54 库路线的形态（与 ProductionOperationQueryService.findRouting 的返回同构）。 */
    private static Map<String, Object> v54Route(String curtainType, String craft) {
        String[][] steps = switch (curtainType + "×" + craft) {
            case "布帘×韩褶" -> V54_BULIAN_HANZHE;
            case "布帘×打孔" -> V54_BULIAN_DAKONG;
            default -> null;
        };
        if (steps == null) {
            return null;
        }
        List<Map<String, Object>> operations = new ArrayList<>();
        int seq = 1;
        for (String[] step : steps) {
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("seq", seq++);
            view.put("operation", step[0]);
            view.put("group", step[1]);
            view.put("unit", step[2]);
            view.put("unit_price", new BigDecimal(step[3]));
            view.put("is_must_finish", Boolean.valueOf(step[4]));
            view.put("is_start_marker", Boolean.valueOf(step[5]));
            operations.add(view);
        }
        Map<String, Object> route = new LinkedHashMap<>();
        route.put("curtain_type", curtainType);
        route.put("craft", craft);
        route.put("operation_count", operations.size());
        route.put("missing_operations", List.of());
        route.put("operations", operations);
        return route;
    }

    /** 空库桩（V54 种子未执行 / 全软删）：findRouting 恒 null，routingKeys 为空。 */
    private void stubEmptyLibrary() {
        when(productionOperationQueryService.findRouting(eq(TENANT), anyString(), anyString())).thenReturn(null);
        when(productionOperationQueryService.routingKeys(TENANT)).thenReturn(List.of());
    }

    /** 「生成加工单 → 真链路实例化」的装配：真实 ProductionService + 真实 ProcessingOrderService。 */
    private ProcessingOrderService realChainService() {
        return new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, objectMapper,
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                        clientRequestIdService),
                productionOperationQueryService);
    }

    /** 生成前置桩（订单 + 明细 + 无既有加工单 + 插入回填主键），三条 #4116 链路用例共用。 */
    private void stubGenerate(List<OrderItem> items) {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(items);
        java.util.concurrent.atomic.AtomicReference<ProcessingOrder> poRef =
                new java.util.concurrent.atomic.AtomicReference<>();
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenAnswer(inv -> poRef.get());
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder inserted = inv.getArgument(0);
            inserted.setId("po-001");
            poRef.set(inserted);
            return 1;
        });
    }

    private Order confirmedOrder;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);

        confirmedOrder = Order.builder()
                .id("order-001")
                .tenantId(TENANT)
                .orderNo("ORD-20260912-0001")
                .status("confirmed")
                .customerName("张三")
                .customerPhone("13800138000")
                .build();
    }

    // ── 快照构建工具 ──────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> processingInfo(String colorName) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingFee", 6.0);
        info.put("colorName", colorName);
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", "2.8米");
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p1");
        p.put("name", "打孔");
        p.put("unitPrice", 3.0);
        p.put("quantity", 2);
        p.put("unit", "米");
        procs.add(p);
        info.put("processingItems", procs);
        return info;
    }

    private OrderItem orderItemWithProcessing(String colorName) {
        return OrderItem.builder()
                .id("item-1")
                .tenantId(TENANT)
                .orderId("order-001")
                .productName("布艺遮光帘A")
                .quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5"))
                .height(new BigDecimal("2.8"))
                .processingInfo(processingInfo(colorName))
                .build();
    }

    private OrderItem orderItemWithoutProcessing() {
        return OrderItem.builder()
                .id("item-2")
                .tenantId(TENANT)
                .orderId("order-001")
                .productName("现货成品")
                .quantity(BigDecimal.valueOf(1))
                .processingInfo(new HashMap<String, Object>())
                .build();
    }

    // ── 切库用例的订单明细（部位/工艺信号各不同）──────────────────────

    /** 布帘·韩褶订单：加工项名「韩褶-布」= 部位(布帘)×工艺(韩褶) 两个信号都在。 */
    private OrderItem orderItemHanzhe(String colorName) {
        return processedItem("item-1", "布艺遮光帘A", colorName, List.of(
                Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")));
    }

    /** 同上，但加工项目录里多一个**库里不存在**的自定义加工项（切库负例①的判别物）。 */
    private OrderItem orderItemHanzheWithCustomProcessingItem(String colorName) {
        return processedItem("item-1", "布艺遮光帘A", colorName, List.of(
                Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折"),
                Map.of("id", "p2", "name", "加工项目录自定义项", "unitPrice", 9.0, "quantity", 2, "unit", "米")));
    }

    /** 帘头订单：派生键 帘头×平幔 —— V54 里有这条路线（rt-v54-06），但本用例桩里**没有**它 ⇒ 验默认路线回落。 */
    private OrderItem orderItemLiTou(String colorName) {
        return processedItem("item-1", "布艺帘头A", colorName, List.of(
                Map.of("id", "p3", "name", "帘头制作", "unitPrice", 2.0, "quantity", 1, "unit", "个")));
    }

    /** 无任何派生信号（加工项名/商品名/销售方式都不含 部位/工艺 关键字）⇒ 全落默认。 */
    private OrderItem orderItemWithoutRouteSignal() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("processingItems", List.of(Map.of("id", "p9", "name", "工序甲", "unit", "米")));
        return OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId("order-001")
                .productName("遮光成品X").quantity(BigDecimal.valueOf(2))
                .processingInfo(info).build();
    }

    private OrderItem processedItem(String itemId, String productName, String colorName,
                                    List<Map<String, Object>> procs) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingFee", 6.0);
        info.put("colorName", colorName);
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", "2.8米");
        info.put("processingItems", new ArrayList<>(procs));
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId("order-001")
                .productName(productName).quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo(info).build();
    }

    /** 脏数据：加工项缺名称（#4116 的防御分支——不得因脏数据阻断加工单生成） */
    private OrderItem orderItemWithNamelessProcessing() {
        Map<String, Object> info = new LinkedHashMap<>();
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p9");
        p.put("unit", "米");
        p.put("quantity", 1);
        procs.add(p);
        info.put("processingItems", procs);
        return OrderItem.builder()
                .id("item-9")
                .tenantId(TENANT)
                .orderId("order-001")
                .productName("布艺遮光帘B")
                .quantity(BigDecimal.valueOf(1))
                .processingInfo(info)
                .build();
    }

    private ProcessingOrder po(String id, String status) {
        return ProcessingOrder.builder()
                .id(id)
                .tenantId(TENANT)
                .orderId("order-001")
                .processingOrderNo("JG-20260912-0001")
                .status(status)
                .itemsSnapshot(buildSnapshotPayload())
                .build();
    }

    private List<Map<String, Object>> buildSnapshotPayload() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("productName", "布艺遮光帘A");
        entry.put("quantity", 2);
        entry.put("colorName", "米白");
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p1");
        p.put("name", "打孔");
        procs.add(p);
        entry.put("processingItems", procs);
        snapshot.add(entry);
        return snapshot;
    }

    // ── PG-001 生成成功 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-001 已确认含加工项订单 → 生成加工单 + 订单联动 producing")
    void generateSuccess() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        ProcessingItem pi = ProcessingItem.builder().id("p1").name("打孔").unit("米").options(List.of("四爪钩")).build();
        when(processingItemMapper.selectById("p1")).thenReturn(pi);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results).hasSize(1);
        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(results.get(0).getProcessingOrderNo()).startsWith("JG-");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(captor.capture());
        ProcessingOrder inserted = captor.getValue();
        assertThat(inserted.getStatus()).isEqualTo("generated");
        assertThat(inserted.getTenantId()).isEqualTo(TENANT);
        assertThat(inserted.getOrderId()).isEqualTo("order-001");
        assertThat(inserted.getTemplateVersion()).isEqualTo(1);

        // 快照五要素 + options + 无销售价
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> snapshot = (List<Map<String, Object>>) inserted.getItemsSnapshot();
        assertThat(snapshot).hasSize(1);
        Map<String, Object> entry = snapshot.get(0);
        assertThat(entry.get("productName")).isEqualTo("布艺遮光帘A");
        assertThat(entry.get("colorName")).isEqualTo("米白");
        assertThat(entry.get("sellingMethod")).isEqualTo("散剪");
        assertThat(entry.get("doorWidth")).isEqualTo("2.8米");
        assertThat(entry).doesNotContainKey("price");
        assertThat(entry).doesNotContainKey("salesPrice");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> procs = (List<Map<String, Object>>) entry.get("processingItems");
        assertThat(procs).hasSize(1);
        assertThat(procs.get(0).get("options")).isEqualTo(List.of("四爪钩"));

        // 联动：订单 confirmed → producing
        verify(orderService).updateOrderStatus("order-001", "producing");
    }

    // ── issue #4116（P0 断链第一环）：生成加工单即实例化工序 → qr_token 非空 ──
    //
    // 病灶：POST /api/admin/production/orders/{id}/instantiate 全仓零调用者 ⇒
    // processing_position_operations 恒空 ⇒ qr_token 恒 null ⇒ 任务卡只出「二维码待生成」占位
    // ⇒ 工人扫码报工不可达。修法：加工单落行后自动实例化（本用例的断言即端到端判据）。
    //
    // ── issue #4116「切库」第二半（用户裁定「现在就切」）──
    // 工序来源从**加工项目录**改为**工序库**（production_routings + production_operations）。
    // 下列用例即该切换的判据：① 实例与库逐条一致（负例 R2）；② 库取不到 ⇒ 显式失败且不回退
    // 加工项目录、不落半成品；③ is_must_finish 读库（末道「外帘发货」在库里是 false）。
    // 三条各有红证（见 PR body 的红证表：改回加工项目录 / 删库路线 / 改回末道必完 ⇒ 均必红）。

    @Test
    @DisplayName("#4116 切库 R2：布帘·韩褶订单 → 工序实例与工序库**逐条一致**（seq/工序/分组/单位/单价/必完）")
    void generateInstantiatesOperationsVerbatimFromOperationLibrary() {
        // 真实 ProductionService（只 mock DB 层 Mapper）：断言"生成→读库→实例化→token"真链路，
        // 而不是"调了一次 productionService.instantiate"（效果层，非调用层）
        ProcessingOrderService service = realChainService();
        stubLibrary();
        stubGenerate(List.of(orderItemHanzhe("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = service.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();

        // ① 工序实例 = 库路线 rt-v54-01（布帘×韩褶）**逐条**：一位不差、一行不多不少
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        List<ProcessingPositionOperation> instances = opCaptor.getAllValues();
        assertThat(instances).extracting(ProcessingPositionOperation::getSeq)
                .containsExactly(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11);
        for (int i = 0; i < V54_BULIAN_HANZHE.length; i++) {
            ProcessingPositionOperation instance = instances.get(i);
            String[] row = V54_BULIAN_HANZHE[i];
            String where = "第 " + (i + 1) + " 道（" + row[0] + "）";
            assertThat(instance.getOperationName()).as(where + " 工序名").isEqualTo(row[0]);
            assertThat(instance.getGroupName()).as(where + " 分组").isEqualTo(row[1]);
            assertThat(instance.getUnit()).as(where + " 单位").isEqualTo(row[2]);
            assertThat(instance.getUnitPrice()).as(where + " 单价").isEqualByComparingTo(row[3]);
            assertThat(instance.getIsMustFinish()).as(where + " 必完标记").isEqualTo(Boolean.valueOf(row[4]));
            assertThat(instance.getIsStartMarker()).as(where + " 开始标记").isEqualTo(Boolean.valueOf(row[5]));
            assertThat(instance.getPositionName()).as(where + " 部位").isEqualTo("布艺遮光帘A 米白");
            assertThat(instance.getProcessingOrderId()).isEqualTo("po-001");
            assertThat(instance.getStatus()).isEqualTo("pending");
        }
        // 必完工序**唯一** = 库里标了 is_must_finish 的「外帘装袋」（第 10 道）；
        // 末道「外帘发货」（第 11 道）在库里是 false ⇒ 这一行就是「末道必完」临时口径的反证
        assertThat(instances).filteredOn(ProcessingPositionOperation::getIsMustFinish)
                .extracting(ProcessingPositionOperation::getOperationName).containsExactly("外帘装袋");
        assertThat(instances.get(10).getOperationName()).isEqualTo("外帘发货");
        assertThat(instances.get(10).getIsMustFinish())
                .as("末道工序不得被无条件标必完（is_must_finish 读库 = false）").isFalse();

        // ② 应做数量：库路线不给数量 ⇒ 退化为该部位订单数量（2）；缺值兜底 1，绝不落 0
        assertThat(instances).allSatisfy(instance -> assertThat(instance.getQty()).isEqualByComparingTo("2"));

        // ③ qr_token 必须真落到加工单（任务卡二维码取值来源 = qr_token，非空才不走占位分支）
        ArgumentCaptor<ProcessingOrder> tokenCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(tokenCaptor.capture());
        assertThat(tokenCaptor.getValue().getId()).isEqualTo("po-001");
        assertThat(tokenCaptor.getValue().getQrToken()).matches("[0-9a-f]{32}");
    }

    @Test
    @DisplayName("#4116 切库负例①：取路线改回加工项目录 ⇒ 本用例必红（加工项名不再进工序实例）")
    void operationsComeFromLibraryNotFromProcessingItemCatalog() {
        // 判据形态：加工项目录里放一个**库里没有**的工序名（「加工项目录自定义项」），
        // 断言它**不得**出现在实例里；而实例的工序名必须全在库路线内。
        // 若有人把取路线改回加工项目录，本断言立即红（红证①）。
        stubLibrary();
        stubGenerate(List.of(orderItemHanzheWithCustomProcessingItem("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(java.util.Arrays.stream(V54_BULIAN_HANZHE).map(r -> r[0]).toList())
                .doesNotContain("加工项目录自定义项");
    }

    @Test
    @DisplayName("#4116 切库负例②：工序库取不到路线 ⇒ fail-closed 中止生成（不回退加工项目录、不落半成品）")
    void generateFailsClosedWhenOperationLibraryHasNoRoute() {
        stubEmptyLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        // 可见性①：接口错误码 + 原文 message（不是「静默走了旧路径」）
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_ROUTING_NOT_FOUND);
        assertThat(results.get(0).getMessage()).contains("工序库").contains("不回退加工项目录");
        // 可见性②：可行动 suggestion（说出库里现状 + 补救入口）
        assertThat(results.get(0).getSuggestion())
                .contains("V54__seed_production_operations.sql")
                .contains("/api/admin/production/routings");
        // 不落半成品：一行不写、订单状态不动（否则会留下「有加工单、无工序、无 qr_token」的孤儿态）
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
        verify(productionService, never()).instantiate(anyString(), any(), anyLong());
    }

    @Test
    @DisplayName("#4116 切库负例②b：路线引用的工序在库中无活跃行 ⇒ 同样 fail-closed（指名报缺）")
    void generateFailsClosedWhenRouteCitesMissingOperation() {
        // 库里这条路线存在，但「幽灵工序」在 production_operations 里没有行
        Map<String, Object> broken = v54Route("布帘", "韩褶");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) broken.get("operations");
        steps.add(new LinkedHashMap<>(Map.of("seq", 12, "operation", "幽灵工序")));
        broken.put("missing_operations", List.of("幽灵工序"));
        when(productionOperationQueryService.findRouting(eq(TENANT), anyString(), anyString())).thenReturn(broken);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_OPERATION_NOT_FOUND);
        assertThat(results.get(0).getMessage()).contains("幽灵工序");
        assertThat(results.get(0).getSuggestion()).contains("/api/admin/production/operations-catalog");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("#4116 切库取法：派生键库里没有 ⇒ 回落默认路线 布帘×韩褶（帘头×平幔 → 布帘×韩褶）")
    void generateFallsBackToDefaultRouteWhenDerivedKeyAbsentFromLibrary() {
        // 桩里只有 布帘×韩褶 / 布帘×打孔 两条；订单派生 帘头×平幔 ⇒ 库里查不到 ⇒ 必须回落默认路线
        stubLibrary();
        stubGenerate(List.of(orderItemLiTou("米白")));
        when(processingItemMapper.selectById("p3")).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(productionOperationQueryService).findRouting(TENANT, "帘头", "平幔");
        verify(productionOperationQueryService).findRouting(TENANT, "布帘", "韩褶");
        // 实例 = 默认路线 rt-v54-01（11 道），不是空实例、也不是别的路线
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(
                        java.util.Arrays.stream(V54_BULIAN_HANZHE).map(row -> row[0]).toList());
    }

    @Test
    @DisplayName("#4116 切库取法：全无派生信号 ⇒ 直接用默认键 布帘×韩褶")
    void generateUsesDefaultKeyWhenNoSignalMatches() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithoutRouteSignal()));
        when(processingItemMapper.selectById("p9")).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(productionOperationQueryService).findRouting(TENANT, "布帘", "韩褶");
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .contains("韩褶-布");
    }

    @Test
    @DisplayName("#4116 切库取法：加工项名派生部位×工艺（打孔-布 ⇒ 布帘×打孔，10 道路线）")
    void generateDerivesRouteKeyFromProcessingItemName() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithProcessing("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("打孔").unit("米").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // 派生键命中 布帘×打孔 ⇒ 取 rt-v54-02（10 道），**不**回落到默认路线（11 道）
        verify(productionOperationQueryService).findRouting(TENANT, "布帘", "打孔");
        verify(productionOperationQueryService, never()).findRouting(TENANT, "布帘", "韩褶");
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_DAKONG.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(
                        java.util.Arrays.stream(V54_BULIAN_DAKONG).map(row -> row[0]).toList());
        assertThat(opCaptor.getAllValues().get(2).getUnit()).isEqualTo("孔");
        assertThat(opCaptor.getAllValues().get(2).getUnitPrice()).isEqualByComparingTo("0.15");
    }

    @Test
    @DisplayName("#4116 加工项无名称（脏数据）→ 不再影响工序来源，仍按默认路线实例化且不阻断生成")
    void generateWithNamelessProcessingItemStillInstantiates() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithNamelessProcessing()));

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(results.get(0).getProcessingOrderNo()).startsWith("JG-");
        // 切库后工序来源不再是加工项名 ⇒「缺名称」只剩「少了一个派生信号」的含义，
        // 落默认路线（布帘×韩褶）而不是**静默跳过实例化**（旧行为会留下无工序、无 qr_token 的加工单）
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length))
                .insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4116 切库后幂等：库派生 payload 重放实例化 ⇒ 一行不写、qr_token 复用（#4116 §4 不回退）")
    void libraryDerivedPayloadReplayIsIdempotentAndKeepsQrToken() {
        // ① 先抓住**真实的**库派生 payload（走 @InjectMocks 的 mock ProductionService 便于捕获；
        //    库桩与真实实现同构，见 V54_* 常量）
        stubLibrary();
        stubGenerate(List.of(orderItemHanzhe("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        ArgumentCaptor<Map<String, Object>> bodyCaptor = ArgumentCaptor.forClass(Map.class);
        verify(productionService).instantiate(eq("order-001"), bodyCaptor.capture(), eq(TENANT));
        Map<String, Object> payload = bodyCaptor.getValue();

        // ② 用同一 payload 在**真实** ProductionService 上重放两次：DB 层用「会记住插入」的桩，
        //    这样第二次的幂等比较面对的是真落库形态（签名比较 ⇒ 相等一行不写）
        List<ProcessingPositionOperation> stored = new ArrayList<>();
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenAnswer(inv -> {
            stored.add(inv.getArgument(0));
            return 1;
        });
        when(positionOperationMapper.selectList(any())).thenAnswer(inv -> stored);
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder patch = inv.getArgument(0);
            ProcessingOrder current = processingOrderMapper.selectActiveByOrderId("order-001", TENANT);
            if (patch.getQrToken() != null && current != null) {
                current.setQrToken(patch.getQrToken());
            }
            return 1;
        });
        ProductionService real = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, clientRequestIdService);

        Map<String, Object> first = real.instantiate("order-001", payload, TENANT);
        int afterFirst = stored.size();
        Map<String, Object> second = real.instantiate("order-001", payload, TENANT);

        assertThat(afterFirst).isEqualTo(V54_BULIAN_HANZHE.length);
        assertThat(stored).as("重放同一库路线 ⇒ 不新增行、旧实例不软删").hasSize(afterFirst);
        verify(positionOperationMapper, never()).update(isNull(), any());
        assertThat(second.get("operation_count")).isEqualTo(afterFirst);
        assertThat(second.get("qr_token")).isEqualTo(first.get("qr_token"));
        assertThat((String) first.get("qr_token")).matches("[0-9a-f]{32}");
    }

    // ── PG-002 幂等 ────────────────────────────────────────────────

    @Test
    @DisplayName("PG-002 已有活跃加工单 → 重复生成拒绝")
    void generateDuplicateRejected() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT))
                .thenReturn(po("po-1", "generated"));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("已有加工单");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
    }

    // ── PG-003 无加工项 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-003 无加工项订单 → 拒绝生成")
    void generateWithoutProcessingRejected() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithoutProcessing()));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("无加工项");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    // ── PG-004 未确认订单 ──────────────────────────────────────────

    @Test
    @DisplayName("PG-004 pending 订单 → 拒绝生成")
    void generatePendingOrderRejected() {
        Order pending = Order.builder()
                .id("order-pending").tenantId(TENANT).orderNo("ORD-P")
                .status("pending").build();
        when(orderMapper.selectById("order-pending")).thenReturn(pending);

        var results = processingOrderService.generate(List.of("order-pending"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("不允许生成加工单");
    }

    @Test
    @DisplayName("订单号解析：selectById 未命中时按订单号查询")
    void generateResolveByOrderNo() {
        stubLibrary();
        when(orderMapper.selectById("ORD-20260912-0001")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        var results = processingOrderService.generate(List.of("ORD-20260912-0001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(orderService).updateOrderStatus("order-001", "producing");
    }

    // ── PG-005/006 状态机 ──────────────────────────────────────────

    @Test
    @DisplayName("PG-005 issue/start/complete 主链流转")
    void updateStatusMainChain() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");
        issue.setProcessor("朝阳加工厂");
        issue.setExpectedDeliveryDate(LocalDate.of(2026, 9, 20));
        processingOrderService.updateStatus("po-1", issue, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("issued");
        assertThat(captor.getValue().getProcessor()).isEqualTo("朝阳加工厂");
        assertThat(captor.getValue().getExpectedDeliveryDate()).isEqualTo(LocalDate.of(2026, 9, 20));
        assertThat(captor.getValue().getIssuedAt()).isNotNull();

        // start
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "issued"));
        ProcessingOrderUpdateRequest start = new ProcessingOrderUpdateRequest();
        start.setAction("start");
        processingOrderService.updateStatus("po-1", start, TENANT, "u1");
        verify(processingOrderMapper, times(2)).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("in_processing");
        assertThat(captor.getValue().getInProcessingAt()).isNotNull();

        // complete：订单保持 producing（不自动 shipped）
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "in_processing"));
        ProcessingOrderUpdateRequest complete = new ProcessingOrderUpdateRequest();
        complete.setAction("complete");
        processingOrderService.updateStatus("po-1", complete, TENANT, "u1");
        verify(processingOrderMapper, times(3)).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("completed");
        verify(orderService, never()).updateOrderStatus(eq("order-001"), eq("shipped"));
    }

    @Test
    @DisplayName("PG-006 非法流转拒绝（generated→completed）")
    void updateStatusIllegalTransitionRejected() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));

        ProcessingOrderUpdateRequest complete = new ProcessingOrderUpdateRequest();
        complete.setAction("complete");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", complete, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许从");
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
    }

    // ── PG-007/008 取消 ────────────────────────────────────────────

    // ── issue #3901：发加工交期禁止过去日期 ──────────────────────────

    @Test
    @DisplayName("issue 传过去交期 → validationError「交付日期不能早于今天」（#3901）")
    void issueRejectsPastDeliveryDate() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");
        issue.setExpectedDeliveryDate(LocalDate.now().minusDays(1));

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", issue, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("交付日期不能早于今天");
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("issue 交期为今天/未来/空 → 正常流转（#3901）")
    void issueAllowsTodayFutureOrNullDeliveryDate() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        // 今天
        ProcessingOrderUpdateRequest today = new ProcessingOrderUpdateRequest();
        today.setAction("issue");
        today.setExpectedDeliveryDate(LocalDate.now());
        processingOrderService.updateStatus("po-1", today, TENANT, "u1");

        // 未来
        ProcessingOrderUpdateRequest future = new ProcessingOrderUpdateRequest();
        future.setAction("issue");
        future.setExpectedDeliveryDate(LocalDate.now().plusDays(7));
        processingOrderService.updateStatus("po-1", future, TENANT, "u1");

        // 空（交期可选）
        ProcessingOrderUpdateRequest empty = new ProcessingOrderUpdateRequest();
        empty.setAction("issue");
        processingOrderService.updateStatus("po-1", empty, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper, times(3)).updateById(captor.capture());
        assertThat(captor.getAllValues().get(0).getExpectedDeliveryDate()).isEqualTo(LocalDate.now());
        assertThat(captor.getAllValues().get(1).getExpectedDeliveryDate()).isEqualTo(LocalDate.now().plusDays(7));
        assertThat(captor.getAllValues().get(2).getExpectedDeliveryDate()).isNull();
    }

    @Test
    @DisplayName("PG-007 取消（generated）→ 加工单 cancelled + 订单 producing→confirmed 回退")
    void cancelGeneratedRevertsOrder() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        Order producing = Order.builder().id("order-001").tenantId(TENANT).status("producing").build();
        when(orderMapper.selectById("order-001")).thenReturn(producing);

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setReason("加工方排期冲突");
        processingOrderService.updateStatus("po-1", cancel, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("cancelled");
        assertThat(captor.getValue().getCancelledReason()).isEqualTo("加工方排期冲突");
        verify(orderService).revertProducingToConfirmed(eq("order-001"), anyString());
    }

    @Test
    @DisplayName("PG-008 取消必填原因")
    void cancelRequiresReason() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", cancel, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须填写原因");
    }

    @Test
    @DisplayName("completed 冻结：取消被拒")
    void cancelCompletedFrozen() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "completed"));

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setReason("测试");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", cancel, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许从");
    }

    // ── PG-011 租户隔离 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-011 跨租户加工单解析 → notFound")
    void tenantIsolation() {
        // 其它租户数据：resolve 条件带 tenant_id，selectOne 返回 null → notFound
        when(processingOrderMapper.selectOne(any())).thenReturn(null);

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");

        assertThatThrownBy(() -> processingOrderService.updateStatus("JG-OTHER-0001", issue, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("加工单");
    }

    // ── 查询 ───────────────────────────────────────────────────────

    @Test
    @DisplayName("详情返回：快照解析 + 订单信息回填")
    void detailAssemblesResponse() {
        ProcessingOrder po = po("po-1", "issued");
        po.setProcessor("朝阳加工厂");
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getOrderNo()).isEqualTo("ORD-20260912-0001");
        assertThat(resp.getCustomerName()).isEqualTo("张三");
        assertThat(resp.getStatus()).isEqualTo("issued");
        assertThat(resp.getItems()).hasSize(1);
        assertThat(resp.getItems().get(0).getProductName()).isEqualTo("布艺遮光帘A");
        assertThat(resp.getItems().get(0).getColorName()).isEqualTo("米白");
        assertThat(resp.getItems().get(0).getProcessingItems()).hasSize(1);
    }

    // ── 验收复核修复（PR #3345）：生成竞态/并发重复 ──────────────────

    @Test
    @DisplayName("验收实战回归：快照为 JSON 字符串（自定义 @Select 形态）→ 详情仍能解析出条目")
    void detailWithJsonStringSnapshot() {
        ProcessingOrder po = po("po-1", "generated");
        po.setItemsSnapshot("[{\"productName\":\"布艺遮光帘A\",\"colorName\":\"米白\","
                + "\"processingItems\":[{\"id\":\"p1\",\"name\":\"打孔\"}]}]");
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getItems()).hasSize(1);
        assertThat(resp.getItems().get(0).getProductName()).isEqualTo("布艺遮光帘A");
        assertThat(resp.getItems().get(0).getColorName()).isEqualTo("米白");
        assertThat(resp.getItems().get(0).getProcessingItems()).hasSize(1);
    }

    @Test
    @DisplayName("验收实战回归：processingInfo 为 JSON 字符串（自定义 @Select 形态）→ 仍能生成加工单")
    void generateWithJsonStringProcessingInfo() {
        stubLibrary();
        OrderItem item = OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId("order-001")
                .productName("布艺遮光帘A").quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo("{\"processingFee\":30,\"colorName\":\"米白\","
                        + "\"processingItems\":[{\"id\":\"p1\",\"name\":\"打孔\",\"unitPrice\":3,\"quantity\":10,\"unit\":\"米\"}]}")
                .build();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingItemMapper.selectById("p1")).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(captor.capture());
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> snapshot = (List<Map<String, Object>>) captor.getValue().getItemsSnapshot();
        assertThat(snapshot).hasSize(1);
        assertThat(snapshot.get(0).get("colorName")).isEqualTo("米白");
    }

    @Test
    @DisplayName("复核修复 P2①：并发重复生成（DuplicateKeyException）→ 订单状态回退 + 幂等失败结果")
    void generateConcurrentDuplicateRollsBackOrder() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class)))
                .thenThrow(new org.springframework.dao.DuplicateKeyException("uk_processing_orders_active"));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("已生成");
        // 联动先发生、落库失败 → 订单回退 confirmed（无孤儿态）
        verify(orderService).updateOrderStatus("order-001", "producing");
        verify(orderService).revertProducingToConfirmed(eq("order-001"), anyString());
    }

    @Test
    @DisplayName("复核修复 P2②：落库失败（非重复）→ 状态回退 + 异常传播（整批回滚）")
    void generateInsertFailureRollsBackAndPropagates() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class)))
                .thenThrow(new RuntimeException("db down"));

        assertThatThrownBy(() -> processingOrderService.generate(List.of("order-001"), TENANT, "u1"))
                .isInstanceOf(RuntimeException.class);
        verify(orderService).revertProducingToConfirmed(eq("order-001"), anyString());
    }
}
