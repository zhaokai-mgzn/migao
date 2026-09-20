// case_ids: PP-011
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProcessingSetPartToken;
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

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 加工单工序读面：**一部位一码**（issue #4946；设计 {@code docs/design/set-code-and-scan-loop.md} §2.3
 * + {@code docs/design/worker-h5-scan-and-report.md} §1.2 / §1.3）。
 *
 * <h2>要治的病</h2>
 * 生产按**单个商品行**推进，而任务卡此前只有**加工单级**的 {@code qr_token}（一单一码）⇒
 * 工人扫到的码指不出「哪个部位」。数据层（{@code processing_set_part_tokens}，V92/V99）**早就有了**
 * —— 缺的只是**读面**：{@code GET /api/admin/production/orders/{orderId}/operations} 的每个部位
 * 必须带上**它自己**的码。
 *
 * <h2>契约（逐字，只加不改）</h2>
 * 每个 position 追加**恰好 3 个**键（键**恒在**，未知 ⇒ {@code null}）：
 * {@code part_token} / {@code part_short_code} / {@code scan_url = {稳定域名}/s/{短码}}；
 * 既有键（{@code position_name} / {@code order_item_id} / {@code position_kind} / {@code set_no} /
 * 规格键 / {@code operations}）与顶层 {@code qr_token} **一字不动**。
 *
 * <h2>每条判据都要能红（红证形态）</h2>
 * ① 三键未落 ⇒ 断言 ①/②/③ 必红（{@code containsEntry} 找不到键）；② 恒真假绿用
 * {@link #existingKeysAreUntouchedByTheThreeAdditions()} 的**前后对照**堵住（有码 / 无码两次读面里
 * 既有键逐值相同，且既有键集合 {@code containsExactly} ⇒ 新增键只能**追加**）；
 * ③ N+1 用 {@link #partTokenRowsAreReadInOneQuery()} 的查询次数 = 1 钉住。</p>
 *
 * <p><b>装配形态与既有测试一致</b>（10 处 {@code new ProductionService(...)} 不过 Spring）：
 * 可选协作者（部位码 mapper / 稳定域名）走 {@code ReflectionTestUtils.setField} 注入
 * —— 因此稳定域名取**内联默认值**（确定性），见
 * {@link #scanUrlUsesInlineDefaultBaseUrlAndTrimsTrailingSlash()}。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#4946 工序读面：每个部位带自己的码（part_token / part_short_code / scan_url）")
class ProductionServicePartCodeTest {

    private static final Long TENANT = 4946L;
    private static final String ORDER_ID = "order-4946";
    private static final String PO_ID = "po-4946";
    private static final String PO_NO = "JG-20260922-4946";
    private static final String QR_TOKEN = "order-level-qr-4946";
    private static final String ITEM_CLOTH = "oi-4946-cloth";
    private static final String ITEM_GAUZE = "oi-4946-gauze";
    private static final String ITEM_HEAD = "oi-4946-head";
    /** 部位码（32 位 UUID 去横线形态的**可辨识替身**；格式判据在迁移/打印侧，不在本测试）。 */
    private static final String PART_CODE_CLOTH = "pc-cloth-4946";
    private static final String PART_CODE_HEAD = "pc-head-4946";
    /** 人可读短码：8 位 Crockford Base32（设计 §1.4）。 */
    private static final String SHORT_CODE_CLOTH = "7K3M9QP2";
    private static final String SHORT_CODE_HEAD = "AB12CD34";
    private static final String STABLE_BASE = "https://app.migaozn.com";

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
    private ProcessingSetPartTokenMapper setPartTokenMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        ReflectionTestUtils.setField(service, "setPartTokenMapper", setPartTokenMapper);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(positionOperationMapper.selectList(any())).thenReturn(operations());
        when(workLogMapper.selectList(any())).thenReturn(List.of());
        when(setPartTokenMapper.selectList(any())).thenReturn(List.of());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ────────────────────────────────────────────── ① 有码部位

    @Test
    @DisplayName("① 有码部位 ⇒ 三键齐在且有值，scan_url 与 `{base}/s/<8 位短码>` 同形")
    void positionWithPartCodeCarriesTokenShortCodeAndScanUrl() {
        stubbedPartRows(partRow(ITEM_CLOTH, PART_CODE_CLOTH, SHORT_CODE_CLOTH));

        Map<String, Object> cloth = positionOf(service.getOperations(ORDER_ID, TENANT), ITEM_CLOTH);

        assertThat(cloth)
                .as("部位自己的码（一部位一码）必须出现在读面上")
                .containsEntry("part_token", PART_CODE_CLOTH)
                .containsEntry("part_short_code", SHORT_CODE_CLOTH);
        assertThat(String.valueOf(cloth.get("scan_url")))
                .as("印刷品上的二维码内容 = {稳定域名}/s/{短码}（设计 §1.2 / §1.3）")
                .isEqualTo(STABLE_BASE + "/s/" + SHORT_CODE_CLOTH)
                .matches("^https://app\\.migaozn\\.com/s/[0-9A-Z]{8}$");
    }

    // ────────────────────────────────────────────── ② 无码部位

    @Test
    @DisplayName("② 无码部位（该 order_item_id 没有行）⇒ 三键**齐在**且为 null（不编造）")
    void positionWithoutPartCodeHasAllThreeKeysNull() {
        stubbedPartRows(partRow(ITEM_CLOTH, PART_CODE_CLOTH, SHORT_CODE_CLOTH));

        Map<String, Object> gauze = positionOf(service.getOperations(ORDER_ID, TENANT), ITEM_GAUZE);

        assertThat(gauze)
                .as("键的**在场性恒定**（前端不必为「有没有这个键」写分支），值 = 未知")
                .containsKeys("part_token", "part_short_code", "scan_url")
                .containsEntry("part_token", null)
                .containsEntry("part_short_code", null)
                .containsEntry("scan_url", null);
    }

    // ────────────────────────────────────────────── ③ 撤销（行在但 token 为 NULL）

    @Test
    @DisplayName("③ 撤销（行在但 token = NULL）⇒ part_token / scan_url 为 null；short_code 仍在（哪张纸可辨识）")
    void revokedRowKeepsShortCodeButLosesTokenAndScanUrl() {
        stubbedPartRows(partRow(ITEM_HEAD, null, SHORT_CODE_HEAD));

        Map<String, Object> head = positionOf(service.getOperations(ORDER_ID, TENANT), ITEM_HEAD);

        assertThat(head)
                .as("撤销 = 置 NULL（设计 §1.3.1）；作废的纸印出来只会得到 410 ⇒ scan_url 也必须为 null"
                        + "（**不画假码**），而短码是「哪一张纸」、仍在")
                .containsEntry("part_token", null)
                .containsEntry("scan_url", null)
                .containsEntry("part_short_code", SHORT_CODE_HEAD);
    }

    // ────────────────────────────────────────────── ④ 前后对照：只加不改

    @Test
    @DisplayName("④ 只加不改：既有键与顶层 qr_token 在「有码 / 无码」两次读面里逐值相同")
    void existingKeysAreUntouchedByTheThreeAdditions() {
        stubbedPartRows(partRow(ITEM_CLOTH, PART_CODE_CLOTH, SHORT_CODE_CLOTH),
                partRow(ITEM_HEAD, null, SHORT_CODE_HEAD));
        Map<String, Object> withCodes = service.getOperations(ORDER_ID, TENANT);
        stubbedPartRows();
        Map<String, Object> withoutCodes = service.getOperations(ORDER_ID, TENANT);

        assertThat(withCodes.get("qr_token"))
                .as("顶层 qr_token（加工单级旧码）一字不动")
                .isEqualTo(QR_TOKEN)
                .isEqualTo(withoutCodes.get("qr_token"));

        List<Map<String, Object>> a = positionsOf(withCodes);
        List<Map<String, Object>> b = positionsOf(withoutCodes);
        assertThat(a).as("部位数量不因加键而变").hasSameSizeAs(b);
        for (int i = 0; i < a.size(); i++) {
            assertThat(existingKeysOf(a.get(i)))
                    .as("部位 " + i + " 的既有键必须逐值相同（新增键**只能追加**）")
                    .isEqualTo(existingKeysOf(b.get(i)));
        }

        // 具体值也钉一遍：防「两次读面都少键 / 都成了 null」的假绿
        Map<String, Object> cloth = a.get(0);
        assertThat(existingKeysOf(cloth))
                .containsEntry("position_name", "布艺遮光帘A")
                .containsEntry("order_item_id", ITEM_CLOTH)
                .containsEntry("position_kind", "布帘")
                .containsEntry("set_no", ITEM_CLOTH);
        assertThat(existingKeysOf(cloth).keySet())
                .as("既有键名与顺序一字不动；新增三键只在末尾追加")
                .containsExactly("position_name", "order_item_id", "position_kind", "set_no", "operations");
        assertThat(cloth.keySet())
                .as("三键确实**追加**在同一张 map 上（不是在断言里被过滤掉的幻觉）")
                .endsWith("part_token", "part_short_code", "scan_url");
    }

    // ────────────────────────────────────────────── ⑤ 单查询（不许 N+1）

    @Test
    @DisplayName("⑤ 单查询：本单的部位码行**一次**取回 —— 按部位逐个查 = N+1")
    void partTokenRowsAreReadInOneQuery() {
        stubbedPartRows(partRow(ITEM_CLOTH, PART_CODE_CLOTH, SHORT_CODE_CLOTH),
                partRow(ITEM_HEAD, null, SHORT_CODE_HEAD));

        service.getOperations(ORDER_ID, TENANT);

        verify(setPartTokenMapper, times(1)).selectList(any());
    }

    // ────────────────────────────────────────────── 边界：未接线 / 稳定域名

    @Test
    @DisplayName("边界：部位码 mapper 未接线（既有装配不过 Spring）⇒ 三键齐在为 null，不崩")
    void missingMapperWiringStillEmitsNullKeys() {
        ReflectionTestUtils.setField(service, "setPartTokenMapper", null);

        Map<String, Object> cloth = positionOf(service.getOperations(ORDER_ID, TENANT), ITEM_CLOTH);

        assertThat(cloth)
                .containsKeys("part_token", "part_short_code", "scan_url")
                .containsEntry("part_token", null)
                .containsEntry("scan_url", null);
    }

    @Test
    @DisplayName("边界：稳定域名取内联默认值（不引新域名）；配置带尾斜杠 ⇒ 不产出 `//`")
    void scanUrlUsesInlineDefaultBaseUrlAndTrimsTrailingSlash() {
        assertThat(ReflectionTestUtils.getField(service, "shortLinkBaseUrl"))
                .as("不经 Spring 装配 ⇒ 取内联默认值（确定性），故**不得**改成构造参数")
                .isEqualTo(STABLE_BASE);
        ReflectionTestUtils.setField(service, "shortLinkBaseUrl", STABLE_BASE + "/");
        stubbedPartRows(partRow(ITEM_CLOTH, PART_CODE_CLOTH, SHORT_CODE_CLOTH));

        assertThat(positionOf(service.getOperations(ORDER_ID, TENANT), ITEM_CLOTH).get("scan_url"))
                .isEqualTo(STABLE_BASE + "/s/" + SHORT_CODE_CLOTH);
    }

    // ────────────────────────────────────────────── ⑥ 撤销必须覆盖印刷品载体（#4946 增补）

    @Test
    @DisplayName("⑥ 撤销 ⇒ 每个部位的 part_token / scan_url 变 null（**同一个事务**里的第二次写）；短码仍在")
    void revokeInvalidatesEveryPrintedPartCode() {
        List<ProcessingSetPartToken> liveRows = new ArrayList<>(List.of(
                partRow(ITEM_CLOTH, PART_CODE_CLOTH, SHORT_CODE_CLOTH),
                partRow(ITEM_HEAD, PART_CODE_HEAD, SHORT_CODE_HEAD)));
        when(setPartTokenMapper.selectList(any())).thenAnswer(invocation -> List.copyOf(liveRows));
        when(setPartTokenMapper.revokeTokensByOrder(eq(PO_ID), eq(TENANT), any())).thenAnswer(invocation -> {
            liveRows.forEach(row -> row.setToken(null)); // 真库那条 UPDATE 的效果
            return liveRows.size();
        });
        when(processingOrderMapper.revokeQrToken(eq(PO_ID), eq(TENANT), any())).thenReturn(1);

        // 撤销前：每个部位都有自己的码（红证锚点 —— 若「撤销后为 null」在改前的任意形态下都成立，
        // 这条断言就不会红，那它也没测到任何东西）
        assertThat(positionOf(service.getOperations(ORDER_ID, TENANT), ITEM_CLOTH).get("part_token"))
                .isEqualTo(PART_CODE_CLOTH);

        Map<String, Object> revoked = service.revokeQrToken(ORDER_ID, TENANT);

        verify(setPartTokenMapper).revokeTokensByOrder(eq(PO_ID), eq(TENANT), any());
        assertThat(revoked)
                .as("既有响应形状一字不动（只加不改？本单连键都没加）")
                .containsOnlyKeys("order_id", "qr_token", "revoked")
                .containsEntry("qr_token", null)
                .containsEntry("revoked", true);

        Map<String, Object> after = service.getOperations(ORDER_ID, TENANT);
        for (String itemId : List.of(ITEM_CLOTH, ITEM_HEAD)) {
            assertThat(positionOf(after, itemId))
                    .as("印刷品载体必须一起作废 —— 否则界面说「已打印的旧码立即失效」是**假话**")
                    .containsEntry("part_token", null)
                    .containsEntry("scan_url", null);
        }
        assertThat(positionOf(after, ITEM_CLOTH))
                .as("short_code 是「哪一张纸」，不随撤销消失（/s/{短码} 见 token 为空 ⇒ 410）")
                .containsEntry("part_short_code", SHORT_CODE_CLOTH);
    }

    @Test
    @DisplayName("边界：部位码 mapper 未接线（既有装配不过 Spring）⇒ 撤销仍成功，不崩")
    void revokeWorksWithoutPartTokenWiring() {
        ReflectionTestUtils.setField(service, "setPartTokenMapper", null);
        when(processingOrderMapper.revokeQrToken(eq(PO_ID), eq(TENANT), any())).thenReturn(1);

        assertThat(service.revokeQrToken(ORDER_ID, TENANT))
                .containsEntry("revoked", true)
                .containsEntry("qr_token", null);
    }

    // ────────────────────────────────────────────── 夹具

    private void stubbedPartRows(ProcessingSetPartToken... rows) {
        when(setPartTokenMapper.selectList(any())).thenReturn(List.of(rows));
    }

    private ProcessingSetPartToken partRow(String orderItemId, String token, String shortCode) {
        return ProcessingSetPartToken.builder()
                .id("row-" + orderItemId).tenantId(TENANT).processingOrderId(PO_ID)
                .setId("set-4946").orderItemId(orderItemId).positionKind("布帘")
                .token(token).shortCode(shortCode).deleted(0)
                .build();
    }

    /** 一件三个部位（布帘 / 纱帘 / 帘头）——部位 = 一行 {@code order_items}。 */
    private List<ProcessingPositionOperation> operations() {
        return List.of(
                partOp("op-cloth", ITEM_CLOTH, "布帘", "布艺遮光帘A", 1),
                partOp("op-gauze", ITEM_GAUZE, "纱帘", "纱帘B", 2),
                partOp("op-head", ITEM_HEAD, "帘头", "帘头C", 3));
    }

    private ProcessingPositionOperation partOp(String id, String itemId, String kind, String name, int seq) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .orderItemId(itemId).positionKind(kind).positionName(name)
                .seq(seq).operationName("精裁-" + kind).groupName("裁剪").unit("米")
                .qty(new BigDecimal("10.00")).doneQty(BigDecimal.ZERO).qtySource("fabric_meters")
                .unitPrice(new BigDecimal("0.40")).isMustFinish(false).isStartMarker(false)
                .status("pending").deleted(0)
                .build();
    }

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20260922-4946");
        o.setStatus("producing");
        o.setDeleted(0);
        return o;
    }

    private ProcessingOrder processingOrder() {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setProcessingOrderNo(PO_NO);
        po.setQrToken(QR_TOKEN);
        po.setStatus("in_processing");
        po.setDeleted(0);
        return po;
    }

    /** 既有键（去掉新增三键）——用于「只加不改」的前后对照。 */
    private static Map<String, Object> existingKeysOf(Map<String, Object> position) {
        Map<String, Object> copy = new LinkedHashMap<>(position);
        copy.keySet().removeAll(List.of("part_token", "part_short_code", "scan_url"));
        return copy;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> positionsOf(Map<String, Object> result) {
        return (List<Map<String, Object>>) result.get("positions");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> positionOf(Map<String, Object> result, String orderItemId) {
        for (Map<String, Object> position : positionsOf(result)) {
            if (orderItemId.equals(position.get("order_item_id"))) {
                return position;
            }
        }
        throw new AssertionError("部位未出现在读面里: " + orderItemId);
    }
}
