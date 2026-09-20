// case_ids: PG-020, PG-021
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionInstanceRepricingLog;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionInstanceRepricingLogMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * <b>未定价实例的显式补价路径</b>（issue #4709 C，P1）—— 只补 {@code NULL}、已有价一律不动、
 * 进度不清零、留痕可回滚。
 *
 * <h2>缺陷原形（红证①：改前「定价了也算不出钱」）</h2>
 * V90（#4696）之后三态可区分：未定价（实例 {@code unit_price IS NULL}）/ 价 0 / 有价。
 * 但商家事后在部位价目矩阵补价时，**已实例化**的旧单快照仍是 {@code NULL} ⇒ 报工快照落
 * {@code unpriced} ⇒ 计件合计里那批活**永远是 ¥0**（不是 0 元，是「算不出来」）；而
 * <b>重新实例化不是可用路径</b>：{@code OpSpec.signature()} 的 {@code num()} 是
 * {@code nz(value).stripTrailingZeros()} ⇒ {@code null} 与 {@code 0} 同签名（不触发），
 * {@code null → 非 0} 触发但会**软删重插 + 报工进度清零**（红线 ④）。
 *
 * <h2>判据（每条独立、注入式可红）</h2>
 * <ol>
 *   <li><b>红证①</b>：矩阵定价**不自动**传播到已实例化实例（实例仍 {@code NULL}）⇒ 报工落
 *       {@code unpriced}、合计为 0（「钱算不出来」）；补价后同一道工序的报工落
 *       {@code unit_price=当前矩阵价 + price_state=priced} ⇒ 合计**算得出来**；</li>
 *   <li><b>红线①反向护栏</b>：已有价的行（{@code > 0} 与 {@code 0}）**一个字段都不碰** ——
 *       服务层不调 {@code fillUnpricedUnitPrice}（本文件 {@code verify(never())}）+ SQL 谓词
 *       {@code AND unit_price IS NULL}（{@code ProcessingPositionOperationMapperTest} 结构判据）。
 *       注入「改写已有价」⇒ 两处各自红；</li>
 *   <li><b>价 0 ≠ 未定价</b>：{@code unit_price = 0} 的实例算「有价」⇒ 不进补价、也不进
 *       {@code still_unpriced}（两者同形 ⇒ 红）；</li>
 *   <li><b>进度/系数不清零</b>：本类物理上不持有报工表 Mapper（结构判据）+ 只调
 *       {@code fillUnpricedUnitPrice} 这一个写方法（SET 子句只含 {@code unit_price/updated_at}，
 *       见 Mapper 测试）；</li>
 *   <li><b>幂等</b>：第二次执行 {@code filled=0}、不产生新账行、实例行不再变化；</li>
 *   <li><b>留痕 + 可回滚</b>：每个被补价的行一行账（{@code batch_id} 同批）；回滚**只**还原
 *       账本里的行（商家自己定的价不在账本里 ⇒ 永远不动），且只在当前值仍等于账本记录的补价时
 *       （CAS）；重复回滚幂等；</li>
 *   <li><b>不猜部位</b>：存量行 {@code position_kind} 为空 ⇒ 取不到矩阵格 ⇒ 如实判「仍未定价」
 *       （猜部位会把别的部位的价补到这一行上）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("未定价实例的显式补价路径（issue #4709 C）")
class ProductionInstanceRepricingServiceTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-fabric";
    private static final String PO_ID = "po-fabric";

    @Mock
    private OrderMapper orderMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;
    @Mock
    private ProductionInstanceRepricingLogMapper repricingLogMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    private ProductionInstanceRepricingService repricing;
    private ProductionService production;

    /** 实例表的内存替身：补价/回滚就地改它 ⇒ 后面的报工/聚合能看到「落库后」的值。 */
    private final List<ProcessingPositionOperation> instances = new ArrayList<>();
    /** 部位价目矩阵的内存替身（{@code null} = 该格未定价）。 */
    private final List<ProductionOperationPosition> matrix = new ArrayList<>();
    /** 报工表的内存替身（捕获 insert 的行，供聚合读）。 */
    private final List<ProductionWorkLog> workLogs = new ArrayList<>();

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        ProductionOperationQueryService queryService = new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
        repricing = new ProductionInstanceRepricingService(orderMapper, processingOrderMapper,
                positionOperationMapper, queryService, repricingLogMapper);
        production = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);

        Order order = Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo("20260920201530002")
                .status("producing").deleted(0).build();
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);
        ProcessingOrder po = ProcessingOrder.builder().id(PO_ID).tenantId(TENANT).orderId(ORDER_ID)
                .processingOrderNo("JG-20260920-0001").status("generated").deleted(0).build();
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(po);
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(po);

        when(productionOperationPositionMapper.selectList(any())).thenAnswer(inv -> matrix);
        when(positionOperationMapper.selectList(any())).thenAnswer(inv -> instances);
        when(workLogMapper.selectList(any())).thenAnswer(inv -> workLogs);
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);

        // 实例表的两条 CAS 写路径的内存实现（**与 SQL 谓词同形**：谓词不成立 ⇒ 0 行）。
        // 真 SQL 的谓词由 ProcessingPositionOperationMapperTest 的结构判据守护（注入即红）。
        when(positionOperationMapper.fillUnpricedUnitPrice(anyString(), anyLong(), any(), any()))
                .thenAnswer(inv -> {
                    String id = inv.getArgument(0);
                    BigDecimal price = inv.getArgument(2);
                    for (ProcessingPositionOperation op : instances) {
                        if (Objects.equals(op.getId(), id)) {
                            if (op.getUnitPrice() != null) {
                                return 0;   // 已有价 ⇒ 谓词 `unit_price IS NULL` 不成立
                            }
                            op.setUnitPrice(price);
                            return 1;
                        }
                    }
                    return 0;
                });
        when(positionOperationMapper.revertFilledUnitPrice(anyString(), anyLong(), any(), any()))
                .thenAnswer(inv -> {
                    String id = inv.getArgument(0);
                    BigDecimal expected = inv.getArgument(2);
                    for (ProcessingPositionOperation op : instances) {
                        if (Objects.equals(op.getId(), id)
                                && op.getUnitPrice() != null
                                && op.getUnitPrice().compareTo(expected) == 0) {
                            op.setUnitPrice(null);
                            return 1;
                        }
                    }
                    return 0;
                });
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenAnswer(inv -> {
            workLogs.add(inv.getArgument(0));
            return 1;
        });
        // 报工路径按工序实例 id 取实例（ProductionService.report）
        when(positionOperationMapper.selectById(anyString())).thenAnswer(inv -> instances.stream()
                .filter(op -> Objects.equals(op.getId(), inv.getArgument(0)))
                .findFirst().orElse(null));
        when(repricingLogMapper.insert(any(ProductionInstanceRepricingLog.class))).thenAnswer(inv -> {
            ProductionInstanceRepricingLog row = inv.getArgument(0);
            row.setId("log-" + (ledger.size() + 1));   // 真实 MP 的 @TableId(ASSIGN_UUID) 替身
            ledger.add(row);
            return 1;
        });
        // 账本读面替身：**与 SQL 谓词同形**（`deleted = 0` + `rolled_back_at IS NULL`）
        // ⇒ 重复回滚读到 0 行（幂等）。谓词本身由 ProductionInstanceRepricingLogMapperTest 守护。
        when(repricingLogMapper.selectList(any())).thenAnswer(inv -> ledger.stream()
                .filter(row -> row.getRolledBackAt() == null)
                .toList());
        // 回滚留痕替身：同形于 `SET rolled_back_at ... WHERE rolled_back_at IS NULL`
        when(repricingLogMapper.markRolledBack(anyString(), anyLong(), any())).thenAnswer(inv -> {
            String id = inv.getArgument(0);
            for (ProductionInstanceRepricingLog row : ledger) {
                if (Objects.equals(row.getId(), id) && row.getRolledBackAt() == null) {
                    row.setRolledBackAt(inv.getArgument(2));
                    return 1;
                }
            }
            return 0;
        });
    }

    /** 补价账本的内存替身。 */
    private final List<ProductionInstanceRepricingLog> ledger = new ArrayList<>();

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /** 一道工序实例（{@code unitPrice = null} = 未定价；{@code positionKind = null} = V69 之前的存量行）。 */
    private static ProcessingPositionOperation instance(String id, String operationName, String positionKind,
                                                        BigDecimal unitPrice, String doneQty) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("遮光布料X").positionKind(positionKind).seq(1)
                .operationName(operationName).groupName("后道").unit("米")
                .qty(new BigDecimal("10.00")).unitPrice(unitPrice).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(false)
                .status("done").doneQty(new BigDecimal(doneQty)).deleted(0).build();
    }

    /** 矩阵格（{@code price = null} = 未定价）。 */
    private static ProductionOperationPosition cell(String logicalName, String position, String price) {
        return ProductionOperationPosition.builder()
                .id("cell-" + position + "-" + logicalName).tenantId(TENANT)
                .logicalName(logicalName).position(position)
                .unitPrice(price == null ? null : new BigDecimal(price))
                .applicable(true).status("active").deleted(0).build();
    }

    /** 一条报工请求体（与 UnpricedPieceworkReportTest 同形）。 */
    private static Map<String, Object> reportBody(String qty) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("qty", new BigDecimal(qty));
        body.put("qualified_qty", new BigDecimal(qty));
        body.put("worker_name", "张三");
        body.put("work_type", "normal");
        return body;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> unpricedBlock(Map<String, Object> report) {
        return (Map<String, Object>) report.get("unpriced");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rows(Map<String, Object> result, String key) {
        return (List<Map<String, Object>>) result.get(key);
    }

    // ══════════════════ 红证①：改前定价了也算不出钱，补价后算得出来 ══════════════════

    @Test
    @DisplayName("🔴 红证①：矩阵定价**不自动**传播到已实例化实例 ⇒ 报工落 unpriced、合计 0；补价后同一道工序的钱算得出来")
    void pricingAloneDoesNotPayTheOldOrderButRepricingDoes() {
        // 商家已在矩阵里给「打包 × 布料」定了价；「裁剪 × 布料」仍未定价
        matrix.add(cell("打包", "布料", "1.20"));
        matrix.add(cell("裁剪", "布料", null));
        instances.add(instance("op-pack", "打包", "布料", null, "0"));
        instances.add(instance("op-cut", "裁剪", "布料", null, "0"));

        // ① 定价**不自动**传播：实例快照仍是 NULL（这就是「钱算不出来」的机制）
        assertThat(instances.get(0).getUnitPrice())
                .as("矩阵定价只改矩阵；已实例化的旧单快照仍是 NULL（无自动补价路径）")
                .isNull();
        Map<String, Object> before = production.report(ORDER_ID, "op-pack", reportBody("3"), TENANT, null);
        assertThat(before.get("status")).isEqualTo("done");
        assertThat(workLogs.get(0).getUnitPrice()).as("改前：报工快照 null ⇒ 算不出钱").isNull();
        assertThat(workLogs.get(0).getPriceState()).isEqualTo("unpriced");
        assertThat((BigDecimal) production.piecework(ORDER_ID, TENANT).get("total"))
                .as("改前：那批活的计件合计是 0.00（不是「0 元工资」，是「算不出来」）")
                .isEqualByComparingTo("0.00");
        workLogs.clear();

        // ② 补价：只补矩阵里有价的那一道
        Map<String, Object> result = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);
        assertThat(result.get("filled")).isEqualTo(1);
        assertThat(result.get("still_unpriced")).isEqualTo(1);
        assertThat(instances.get(0).getUnitPrice()).as("补价后实例快照 = 当前矩阵价").isEqualByComparingTo("1.20");
        assertThat(instances.get(1).getUnitPrice()).as("矩阵格仍为 NULL ⇒ 如实保持未定价（不猜价）").isNull();

        // ③ 补价之后同一道工序的报工**算得出钱**：快照 = 补上的价、三态 = priced
        production.report(ORDER_ID, "op-pack", reportBody("3"), TENANT, null);
        assertThat(workLogs.get(0).getUnitPrice()).isEqualByComparingTo("1.20");
        assertThat(workLogs.get(0).getPriceState()).isEqualTo("priced");
        Map<String, Object> after = production.piecework(ORDER_ID, TENANT);
        assertThat((BigDecimal) after.get("total")).as("3 × ¥1.20 = ¥3.60 —— 钱算得出来了").isEqualByComparingTo("3.60");

        // ④ 仍未定价的那道工序照常报工 ⇒ 落 unpriced（不按 0 计件），并显式可见
        production.report(ORDER_ID, "op-cut", reportBody("3"), TENANT, null);
        Map<String, Object> report = production.piecework(ORDER_ID, TENANT);
        assertThat((BigDecimal) report.get("total")).as("未定价那笔**不得**按 0 计入").isEqualByComparingTo("3.60");
        assertThat((BigDecimal) unpricedBlock(report).get("qty")).isEqualByComparingTo("3");
    }

    // ══════════════════ 红线①：只补 NULL，已有价一律不动 ══════════════════

    @Test
    @DisplayName("🔴 红线①：只补 `unit_price IS NULL` 的行 —— 有价（>0）与价 0 的行**一次都不写**")
    void onlyNullRowsAreWrittenAndPricedRowsAreNeverTouched() {
        matrix.add(cell("打包", "布料", "1.20"));
        matrix.add(cell("裁剪", "布料", "9.99"));
        matrix.add(cell("质检", "布料", "9.99"));
        instances.add(instance("op-unpriced", "打包", "布料", null, "3"));
        instances.add(instance("op-priced", "裁剪", "布料", new BigDecimal("0.40"), "3"));
        instances.add(instance("op-zero", "质检", "布料", BigDecimal.ZERO, "3"));

        Map<String, Object> result = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);

        // 服务层判据：已有价的行**根本不进**写路径
        verify(positionOperationMapper, times(1))
                .fillUnpricedUnitPrice(eq("op-unpriced"), eq(TENANT), eq(new BigDecimal("1.20")), any());
        verify(positionOperationMapper, never())
                .fillUnpricedUnitPrice(eq("op-priced"), anyLong(), any(), any());
        verify(positionOperationMapper, never())
                .fillUnpricedUnitPrice(eq("op-zero"), anyLong(), any(), any());
        // 已有价的行值一字不动（内存替身 + 真实 SQL 的 `unit_price IS NULL` 谓词双重保证）
        assertThat(instances.get(1).getUnitPrice()).isEqualByComparingTo("0.40");
        assertThat(instances.get(2).getUnitPrice()).as("价 0 是**显式定价 0 元**，不是未定价").isEqualByComparingTo("0");
        assertThat(result.get("filled")).isEqualTo(1);
        assertThat(result.get("already_priced")).as("已有价的行如实计入「未动」").isEqualTo(2);
        assertThat(result.get("still_unpriced")).isEqualTo(0);
        assertThat(ledger).as("账本只记被补价的行 ⇒ 才有「可回滚」的判据").hasSize(1);
        assertThat(ledger.get(0).getPositionOperationId()).isEqualTo("op-unpriced");
        assertThat(ledger.get(0).getNewUnitPrice()).isEqualByComparingTo("1.20");
        assertThat(ledger.get(0).getRolledBackAt()).isNull();
    }

    @Test
    @DisplayName("反向护栏：价 0 的实例**不进** still_unpriced 清单（未定价 ≠ 0，两者同形 ⇒ 红）")
    void zeroPricedInstanceIsNotReportedAsUnpriced() {
        matrix.add(cell("质检", "布料", "9.99"));
        instances.add(instance("op-zero", "质检", "布料", BigDecimal.ZERO, "3"));

        Map<String, Object> result = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);

        assertThat(result.get("filled")).isEqualTo(0);
        assertThat(result.get("still_unpriced")).isEqualTo(0);
        assertThat(result.get("already_priced")).isEqualTo(1);
        assertThat(rows(result, "still_unpriced_operations")).isEmpty();
    }

    // ══════════════════ 红线②④：进度/系数/报工历史不可达（结构判据） ══════════════════

    @Test
    @DisplayName("🔴 红线②④：补价路径**物理上**不持有报工表 Mapper（结构判据：历史报工一字不动）")
    void repricingServiceCannotReachWorkLogs() {
        assertThat(Arrays.stream(ProductionInstanceRepricingService.class.getDeclaredFields())
                .map(Field::getType))
                .as("补价不得触碰 production_work_logs（unit_price/factor 历史值一字不动）")
                .doesNotContain(ProductionWorkLogMapper.class);
    }

    @Test
    @DisplayName("🔴 红线④：补价**不碰** done_qty / status / factor —— 只调一个写方法，且不动这些字段")
    void repricingNeverTouchesProgressOrFactor() {
        matrix.add(cell("打包", "布料", "1.20"));
        instances.add(instance("op-1", "打包", "布料", null, "3"));

        repricing.repriceUnpricedInstances(ORDER_ID, TENANT);

        // 唯一允许的实例表写方法 = fillUnpricedUnitPrice（其 SET 子句只含 unit_price/updated_at，
        // 见 ProcessingPositionOperationMapperTest 的结构判据）
        verify(positionOperationMapper, times(1))
                .fillUnpricedUnitPrice(anyString(), anyLong(), any(), any());
        verify(positionOperationMapper, never()).updateById(any(ProcessingPositionOperation.class));
        verify(positionOperationMapper, never()).update(any(), any());
        // 内存替身如实体现「落库后」的值：进度与系数一字未动
        assertThat(instances.get(0).getDoneQty()).isEqualByComparingTo("3");
        assertThat(instances.get(0).getStatus()).isEqualTo("done");
        assertThat(instances.get(0).getFactor()).isEqualByComparingTo("1");
    }

    // ══════════════════ 幂等 ══════════════════

    @Test
    @DisplayName("幂等：重复补价 ⇒ filled=0、不产生新账行、实例值不再变化")
    void repricingIsIdempotent() {
        matrix.add(cell("打包", "布料", "1.20"));
        instances.add(instance("op-1", "打包", "布料", null, "3"));

        Map<String, Object> first = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);
        Map<String, Object> second = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);

        assertThat(first.get("filled")).isEqualTo(1);
        assertThat(second.get("filled")).as("第二次没有可补的行").isEqualTo(0);
        assertThat(second.get("batch_id")).as("没有实际动作 ⇒ 不给批次号（免得回滚一个空批次）").isNull();
        assertThat(second.get("already_priced")).isEqualTo(1);
        assertThat(ledger).as("账本不得因重复调用而增长").hasSize(1);
        assertThat(instances.get(0).getUnitPrice()).isEqualByComparingTo("1.20");
    }

    // ══════════════════ 留痕 + 可回滚 ══════════════════

    @Test
    @DisplayName("可回滚：只还原账本里的行（商家自己定的价不在账本里 ⇒ 永远不动）+ 账行留痕")
    void rollbackRevertsOnlyLedgerRowsAndLeavesMerchantPricesAlone() {
        matrix.add(cell("打包", "布料", "1.20"));
        instances.add(instance("op-repriced", "打包", "布料", null, "3"));
        instances.add(instance("op-merchant", "裁剪", "布料", new BigDecimal("0.40"), "3"));

        Map<String, Object> repriced = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);
        String batchId = (String) repriced.get("batch_id");
        assertThat(batchId).isNotBlank();

        Map<String, Object> rolled = repricing.rollback(batchId, TENANT);

        assertThat(rolled.get("reverted")).isEqualTo(1);
        assertThat(rolled.get("skipped")).isEqualTo(0);
        verify(positionOperationMapper, times(1))
                .revertFilledUnitPrice(eq("op-repriced"), eq(TENANT), eq(new BigDecimal("1.20")), any());
        verify(positionOperationMapper, never())
                .revertFilledUnitPrice(eq("op-merchant"), anyLong(), any(), any());
        assertThat(instances.get(0).getUnitPrice()).as("回滚 ⇒ 回到未定价").isNull();
        assertThat(instances.get(1).getUnitPrice()).as("商家自己定的价不在账本里 ⇒ 永不被回滚")
                .isEqualByComparingTo("0.40");
        assertThat(ledger.get(0).getRolledBackAt()).as("账行留痕（rolled_back_at）").isNotNull();
    }

    @Test
    @DisplayName("回滚不覆盖后续改动：当前值 ≠ 账本记录的补价 ⇒ 不还原、不标记、如实计入 skipped")
    void rollbackSkipsRowsChangedAfterRepricing() {
        matrix.add(cell("打包", "布料", "1.20"));
        instances.add(instance("op-1", "打包", "布料", null, "3"));
        String batchId = (String) repricing.repriceUnpricedInstances(ORDER_ID, TENANT).get("batch_id");
        // 之后被别的动作改过（如商家在矩阵改价后又被人工调整）⇒ CAS 谓词不成立
        instances.get(0).setUnitPrice(new BigDecimal("2.50"));
        ledger.forEach(row -> row.setRolledBackAt(null));

        Map<String, Object> rolled = repricing.rollback(batchId, TENANT);

        assertThat(rolled.get("reverted")).isEqualTo(0);
        assertThat(rolled.get("skipped")).isEqualTo(1);
        assertThat(instances.get(0).getUnitPrice()).as("不覆盖后续改动").isEqualByComparingTo("2.50");
        verify(repricingLogMapper, never()).markRolledBack(anyString(), anyLong(), any());
    }

    @Test
    @DisplayName("回滚幂等：重复回滚 ⇒ reverted=0，实例行不再变化")
    void rollbackIsIdempotent() {
        matrix.add(cell("打包", "布料", "1.20"));
        instances.add(instance("op-1", "打包", "布料", null, "3"));
        String batchId = (String) repricing.repriceUnpricedInstances(ORDER_ID, TENANT).get("batch_id");
        repricing.rollback(batchId, TENANT);

        Map<String, Object> again = repricing.rollback(batchId, TENANT);

        assertThat(again.get("reverted")).isEqualTo(0);
        assertThat(again.get("skipped")).isEqualTo(0);
        assertThat(instances.get(0).getUnitPrice()).isNull();
    }

    // ══════════════════ 边界（如实登记，不猜） ══════════════════

    @Test
    @DisplayName("不猜部位：存量行缺 position_kind ⇒ 取不到矩阵格 ⇒ 如实判「仍未定价」")
    void legacyRowsWithoutPositionKindStayUnpriced() {
        matrix.add(cell("打包", "布料", "1.20"));
        instances.add(instance("op-legacy", "打包", null, null, "3"));

        Map<String, Object> result = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);

        assertThat(result.get("filled")).isEqualTo(0);
        assertThat(result.get("still_unpriced")).isEqualTo(1);
        assertThat(String.valueOf(result.get("hint"))).contains("/production/routings");
        verify(positionOperationMapper, never()).fillUnpricedUnitPrice(anyString(), anyLong(), any(), any());
    }

    @Test
    @DisplayName("无活跃加工单 ⇒ 空结果（不抛错、不伪造批次）")
    void orderWithoutProcessingOrderYieldsEmptyResult() {
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        Map<String, Object> result = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);

        assertThat(result.get("filled")).isEqualTo(0);
        assertThat(result.get("batch_id")).isNull();
        assertThat(String.valueOf(result.get("hint"))).isNotBlank();
    }

    @Test
    @DisplayName("跨租户订单 ⇒ 404（不越权补价）")
    void crossTenantOrderIsNotFound() {
        Order other = Order.builder().id(ORDER_ID).tenantId(999L).deleted(0).build();
        when(orderMapper.selectById(ORDER_ID)).thenReturn(other);

        assertThatThrownBy(() -> repricing.repriceUnpricedInstances(ORDER_ID, TENANT))
                .isInstanceOf(BusinessException.class);
    }

    @Test
    @DisplayName("缺批次号 ⇒ 422 可行动错误（不静默空回滚）")
    void rollbackWithoutBatchIdIsRejected() {
        assertThatThrownBy(() -> repricing.rollback("  ", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("批次");
    }

    @Test
    @DisplayName("账本行 ↔ 实体：补价只记 NULL→有价的行，且记的是补上的价（留痕可核对）")
    void ledgerRecordsWhatWasFilled() {
        matrix.add(cell("打包", "布料", "1.20"));
        matrix.add(cell("裁剪", "布料", "0.40"));
        instances.add(instance("op-1", "打包", "布料", null, "3"));
        instances.add(instance("op-2", "裁剪", "布料", null, "3"));

        Map<String, Object> result = repricing.repriceUnpricedInstances(ORDER_ID, TENANT);

        ArgumentCaptor<ProductionInstanceRepricingLog> captor =
                ArgumentCaptor.forClass(ProductionInstanceRepricingLog.class);
        verify(repricingLogMapper, times(2)).insert(captor.capture());
        assertThat(captor.getAllValues()).extracting(ProductionInstanceRepricingLog::getNewUnitPrice)
                .containsExactlyInAnyOrder(new BigDecimal("1.20"), new BigDecimal("0.40"));
        assertThat(captor.getAllValues()).extracting(ProductionInstanceRepricingLog::getBatchId)
                .as("一次动作 = 一个批次（回滚粒度）")
                .containsOnly((String) result.get("batch_id"));
        assertThat(captor.getAllValues()).extracting(ProductionInstanceRepricingLog::getProcessingOrderId)
                .containsOnly(PO_ID);
        assertThat(rows(result, "filled_operations")).hasSize(2);
    }
}
