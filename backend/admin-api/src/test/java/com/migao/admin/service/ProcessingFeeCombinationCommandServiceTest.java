package com.migao.admin.service;

// case_ids: PG-040

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.entity.ProcessingFeeCombinationVersion;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationVersionMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 加工费组合定价**写面护栏 + 归一化 + 版本账 + 缺口视图**（issue #4386，P1）
 *
 * <h2>为什么每条判据都要有红证</h2>
 * 用户裁定（2026-09-19）：「选配完的一个商品**只会收取一种加工费**，然后根据米算出这个商品的加工费」
 * 「这个加工费组合是要**系统根据选配结果自己计算**的，**不可能**是用户直接告诉」。
 * ⇒ 本表是**下单侧唯一取价源**：一条坏组合（空组合 / 引用不存在的加工项 / 同一组合两个价）
 * 会让系统在匹配时**取到错价或取不到价**，而错价直接进订单金额 ⇒ 五条护栏缺任何一条，
 * 坏数据都能静默落库。
 *
 * <h2>为什么归一化必须有独立判据</h2>
 * 「韩褶+打孔+定型」与「定型+打孔+韩褶」是**同一笔钱**。若按书写顺序存 key，
 * 商家两次录入会建出**两行**，下单匹配时命中哪一行取决于扫描顺序 ⇒ 同一份选配
 * 在两次下单拿到两个价（不可复现的定价）。故归一化必须是**确定性 + 与书写顺序无关**的。
 *
 * <h2>错误形状（冻结契约，与 #4308 同口径）</h2>
 * 护栏失败 = HTTP **422** + {@code error.details:[{field,message}]} **逐条**理由；
 * 撞唯一键（同一组合重复定价）= HTTP **409**。前端按**真实信封**读
 * （{@code error.details[].message}），不读不存在的 {@code error_messages}。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("加工费组合定价写面（issue #4386）")
class ProcessingFeeCombinationCommandServiceTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProcessingFeeCombinationMapper combinationMapper;
    @Mock
    private ProcessingFeeCombinationVersionMapper versionMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private OrderItemMapper orderItemMapper;

    private ProcessingFeeCombinationCommandService service;
    private ProcessingFeeQueryService queryService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // 读面用**真实对象**（只 mock Mapper）：写面响应形态 = 列表项形态（同一份 combinationView），
        // 用 mock 会让「返回更新后的组合」退化成断言桩（同 #4308 的 routingView 处置）。
        queryService = new ProcessingFeeQueryService(
                combinationMapper, processingItemMapper, orderItemMapper);
        service = new ProcessingFeeCombinationCommandService(
                combinationMapper, versionMapper, processingItemMapper, queryService);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── 夹具 ──────────────────────────────────────────────────────────────

    private static ProcessingItem item(String name) {
        return ProcessingItem.builder().id("pi-" + name).tenantId(TENANT).name(name)
                .categoryId("cat-1").pricingMethod("per_meter").unitPrice(new BigDecimal("8"))
                .unit("米").status("active").deleted(0).build();
    }

    /** 加工项目录：韩褶 / 打孔 / 定型 / 四爪钩（后者用于「引用不存在」的反例）。 */
    private void stubCatalog() {
        when(processingItemMapper.selectList(any())).thenReturn(List.of(
                item("韩褶"), item("打孔"), item("定型")));
    }

    private static ProcessingFeeCombination combination(String id, String key, String price) {
        return ProcessingFeeCombination.builder().id(id).tenantId(TENANT)
                .compositionKey(key).unitPrice(new BigDecimal(price))
                .status("active").sortOrder(0).deleted(0).build();
    }

    private static Map<String, Object> body(Object... kv) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            map.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return map;
    }

    private static List<String> detailFields(BusinessException e) {
        return e.getDetails() == null ? List.of()
                : e.getDetails().stream().map(ApiResponse.ErrorDetail::getField).toList();
    }

    private static List<String> detailMessages(BusinessException e) {
        return e.getDetails() == null ? List.of()
                : e.getDetails().stream().map(ApiResponse.ErrorDetail::getMessage).toList();
    }

    // ══════════════════ 判据 1：同一组合不重复定价 ⇒ 409 ══════════════════

    @Test
    @DisplayName("判据 1：同一 composition_key 建两次 ⇒ 第二次 409（否则撞 DB 唯一键变 500）")
    void duplicateCompositionIsRejectedWithConflict() {
        stubCatalog();
        // 库里已有「打孔+韩褶」（归一化后的 key —— 与本次请求的书写顺序相反）
        when(combinationMapper.selectList(any()))
                .thenReturn(List.of(combination("c1", "打孔+韩褶", "12.00")));

        assertThatThrownBy(() -> service.createCombination(
                body("items", List.of("韩褶", "打孔"), "unit_price", "15.00"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).as("撞唯一键 = 409（不是 422、更不是 500）").isEqualTo(409);
                    assertThat(be.getCode()).isEqualTo("CONFLICT");
                    assertThat(be.getSuggestion()).as("失败必须可行动（说清去哪改哪一行）").isNotBlank();
                });
        verify(combinationMapper, never()).insert(any(ProcessingFeeCombination.class));
    }

    // ══════════════════ 判据 2：归一化确定性（与书写顺序无关）══════════════════

    @Test
    @DisplayName("判据 2a：`韩褶+打孔+定型` 与 `定型+打孔+韩褶` 归一为**同一个 key**（确定性、与顺序无关）")
    void compositionKeyIsOrderIndependent() {
        // 归一化口径 = trim → 丢空 → 去重 → 按 **Unicode 码点升序** → `+` 连接。
        // 码点真值（勿凭「读起来顺」猜顺序）：定 U+5B9A < 打 U+6253 < 韩 U+97E9
        // ⇒ 规范序是「定型+打孔+韩褶」；下面**故意**用三种书写顺序，全部必须落到同一个 key。
        assertThat(ProcessingFeeCombinationCommandService.compositionKey(List.of("韩褶", "打孔", "定型")))
                .isEqualTo("定型+打孔+韩褶");
        assertThat(ProcessingFeeCombinationCommandService.compositionKey(List.of("定型", "打孔", "韩褶")))
                .as("换个书写顺序必须是同一个 key —— 否则同一笔钱建出两行，取价取决于扫描顺序")
                .isEqualTo("定型+打孔+韩褶");
        assertThat(ProcessingFeeCombinationCommandService.compositionKey(List.of("打孔", "定型", "韩褶")))
                .isEqualTo("定型+打孔+韩褶");
        // 空白/重复不得改变 key（归一化是幂等的）
        assertThat(ProcessingFeeCombinationCommandService.compositionKey(List.of(" 定型 ", "打孔", "韩褶", "韩褶")))
                .isEqualTo("定型+打孔+韩褶");
    }

    @Test
    @DisplayName("判据 2b：落库的 composition_key 是**归一化后**的值（不是请求里的书写顺序）")
    void storedCompositionKeyIsNormalized() {
        stubCatalog();
        when(combinationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.createCombination(
                body("items", List.of("定型", "打孔", "韩褶"), "unit_price", "18.00"), TENANT);

        ArgumentCaptor<ProcessingFeeCombination> inserted =
                ArgumentCaptor.forClass(ProcessingFeeCombination.class);
        verify(combinationMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getCompositionKey())
                .as("落库值必须是归一化 key（注入：改成 String.join(请求顺序) ⇒ 本断言红）")
                .isEqualTo("定型+打孔+韩褶");
        assertThat(result.get("composition_key")).isEqualTo("定型+打孔+韩褶");
        assertThat(result.get("items")).isEqualTo(List.of("定型", "打孔", "韩褶"));
    }

    @Test
    @DisplayName("判据 2c：归一化后相同 ⇒ 409（把顺序当 key 的实现会在这里建出第二行）")
    void reorderedRequestHitsDuplicateGuard() {
        stubCatalog();
        when(combinationMapper.selectList(any()))
                .thenReturn(List.of(combination("c1", "定型+打孔+韩褶", "18.00")));

        assertThatThrownBy(() -> service.createCombination(
                body("items", List.of("定型", "打孔", "韩褶"), "unit_price", "20.00"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
        verify(combinationMapper, never()).insert(any(ProcessingFeeCombination.class));
    }

    // ══════════════════ 判据 3：护栏理由逐条可见（422 + details[]）══════════════════

    @Test
    @DisplayName("判据 3a：空组合 ⇒ 422 + details[field=items]（空组合是死数据：永远匹配不到任何选配）")
    void emptyCompositionIsRejected() {
        assertThatThrownBy(() -> service.createCombination(
                body("items", List.of(), "unit_price", "12.00"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(be.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(detailFields(be)).contains("items");
                    assertThat(detailMessages(be)).allSatisfy(m -> assertThat(m).isNotBlank());
                });
        verify(combinationMapper, never()).insert(any(ProcessingFeeCombination.class));
    }

    @Test
    @DisplayName("判据 3b：组合内特征名重复 ⇒ 422（`韩褶+韩褶` 与 `韩褶` 归一后同 key ⇒ 静默两个价）")
    void duplicateFeatureNameIsRejected() {
        stubCatalog();
        assertThatThrownBy(() -> service.createCombination(
                body("items", List.of("韩褶", "打孔", "韩褶"), "unit_price", "12.00"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields(be)).contains("items[2]");
                });
        verify(combinationMapper, never()).insert(any(ProcessingFeeCombination.class));
    }

    @Test
    @DisplayName("判据 3c：特征名在加工项目录中不存在/已停用 ⇒ 422 逐条指名（一次报全，不是报第一条就返回）")
    void unknownFeatureNamesAreAllReported() {
        stubCatalog();
        assertThatThrownBy(() -> service.createCombination(
                body("items", List.of("韩褶", "四爪钩", "库里没有的", ""), "unit_price", "12.00"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields(be))
                            .as("逐条一次报全：两条不存在的特征各自一条理由（field 指出第几位）")
                            .containsExactlyInAnyOrder("items[1]", "items[2]", "items[3]");
                    assertThat(detailMessages(be)).anySatisfy(m -> assertThat(m).contains("四爪钩"));
                });
        verify(combinationMapper, never()).insert(any(ProcessingFeeCombination.class));
    }

    @Test
    @DisplayName("判据 3d：unit_price < 0 / 非数值 / 缺失 ⇒ 422 + details[field=unit_price]（加工费是钱，不得为负）")
    void unitPriceGuards() {
        stubCatalog();
        for (Object bad : List.of("-1", "abc", "")) {
            assertThatThrownBy(() -> service.createCombination(
                    body("items", List.of("韩褶", "打孔"), "unit_price", bad), TENANT))
                    .as("unit_price=%s 必须被拒", bad)
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> {
                        BusinessException be = (BusinessException) e;
                        assertThat(be.getHttpStatus()).isEqualTo(422);
                        assertThat(detailFields(be)).contains("unit_price");
                    });
        }
        assertThatThrownBy(() -> service.createCombination(
                body("items", List.of("韩褶", "打孔")), TENANT))
                .as("unit_price 缺失 ⇒ 拒（不得静默按 0 落库）")
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("unit_price"));
        verify(combinationMapper, never()).insert(any(ProcessingFeeCombination.class));
    }

    @Test
    @DisplayName("判据 3e：unit_price = 0 合法（商家可把某组合做成免费）；source 只认 实证/推算/占位待确认")
    void zeroPriceAllowedAndSourceVocabularyEnforced() {
        stubCatalog();
        when(combinationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.createCombination(
                body("items", List.of("韩褶", "打孔"), "unit_price", "0"), TENANT);
        assertThat(result.get("unit_price")).isEqualTo(new BigDecimal("0"));

        assertThatThrownBy(() -> service.createCombination(
                body("items", List.of("韩褶", "定型"), "unit_price", "12", "source", "随便写的"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("source"));
    }

    // ══════════════════ 判据 5：版本账（改一次单价 ⇒ 落一行）══════════════════

    @Test
    @DisplayName("判据 5a：改一次单价 ⇒ processing_fee_combination_versions 落一行（记变更后值 + 键冗余）")
    void priceChangeAppendsVersionRow() {
        ProcessingFeeCombination existing = combination("c1", "韩褶+打孔", "12.00");
        when(combinationMapper.selectById("c1")).thenReturn(existing);

        Map<String, Object> result = service.updateCombination(
                "c1", body("unit_price", "15.50"), TENANT);

        ArgumentCaptor<ProcessingFeeCombinationVersion> version =
                ArgumentCaptor.forClass(ProcessingFeeCombinationVersion.class);
        verify(versionMapper).insert(version.capture());
        assertThat(version.getValue().getCombinationId()).isEqualTo("c1");
        assertThat(version.getValue().getCompositionKey())
                .as("键冗余存：组合行被停用/改名后历史账仍答得出「当时是哪一组」")
                .isEqualTo("韩褶+打孔");
        assertThat(version.getValue().getUnitPrice()).isEqualByComparingTo("15.50");
        assertThat(result.get("unit_price")).isEqualTo(new BigDecimal("15.50"));
    }

    @Test
    @DisplayName("判据 5b：同价重复提交 = 幂等空操作（不追加无意义的版本行，沿用 #4308 口径）")
    void samePriceIsIdempotentNoop() {
        when(combinationMapper.selectById("c1")).thenReturn(combination("c1", "韩褶+打孔", "12.00"));

        service.updateCombination("c1", body("unit_price", "12.00"), TENANT);

        verify(combinationMapper).updateById(any(ProcessingFeeCombination.class));
        verify(versionMapper, never()).insert(any(ProcessingFeeCombinationVersion.class));
    }

    @Test
    @DisplayName("新建组合 ⇒ 首行版本账（使「当前价 = 最新版本行」对新组合同样成立）")
    void createAppendsFirstVersionRow() {
        stubCatalog();
        when(combinationMapper.selectList(any())).thenReturn(List.of());

        service.createCombination(body("items", List.of("韩褶", "打孔"), "unit_price", "12.00"), TENANT);

        verify(versionMapper).insert(any(ProcessingFeeCombinationVersion.class));
    }

    @Test
    @DisplayName("停用 = 软删语义（status=disabled 保留行）：删了就没法回答「昨天这个组合什么价」")
    void disableKeepsRow() {
        when(combinationMapper.selectById("c1")).thenReturn(combination("c1", "韩褶+打孔", "12.00"));

        Map<String, Object> result = service.disableCombination("c1", TENANT);

        ArgumentCaptor<ProcessingFeeCombination> updated =
                ArgumentCaptor.forClass(ProcessingFeeCombination.class);
        verify(combinationMapper).updateById(updated.capture());
        assertThat(updated.getValue().getStatus()).isEqualTo("disabled");
        assertThat(updated.getValue().getDeleted()).as("不物理删：行要留着可回溯").isEqualTo(0);
        assertThat(result.get("status")).isEqualTo("disabled");
    }

    @Test
    @DisplayName("跨租户 / 不存在的组合 ⇒ 404（不泄漏别的租户的组合存在性）")
    void unknownCombinationIsNotFound() {
        when(combinationMapper.selectById("cx")).thenReturn(null);
        assertThatThrownBy(() -> service.updateCombination("cx", body("unit_price", "1"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));
    }

    // ══════════════════ 判据 4：缺口可见（未定价组合）══════════════════

    @Test
    @DisplayName("判据 4a：缺口 = 订单里**实际出现过**、但库里查不到价的组合（含出现次数与出处）")
    void gapsListUnpricedCombinationsSeenInOrders() {
        when(combinationMapper.selectList(any()))
                .thenReturn(List.of(combination("c1", "打孔+韩褶", "12.00")));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem("韩褶", "打孔"),            // 已定价 ⇒ 不进缺口
                orderItem("定型", "打孔", "韩褶"),     // 未定价 ⇒ 进缺口
                orderItem("韩褶", "打孔", "定型"),     // 同一个组合（书写顺序不同）⇒ 合并计数
                orderItem("定型")));                  // 另一个未定价组合

        Map<String, Object> gaps = queryService.feeGaps(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) gaps.get("unpriced_combinations");
        assertThat(rows).extracting(r -> r.get("composition_key"))
                .as("已定价的不出现；两个未定价组合各一行（归一化后合并计数）")
                .containsExactlyInAnyOrder("定型+打孔+韩褶", "定型");
        assertThat(rows).filteredOn(r -> "定型+打孔+韩褶".equals(r.get("composition_key")))
                .singleElement()
                .satisfies(r -> {
                    assertThat(r.get("items")).isEqualTo(List.of("定型", "打孔", "韩褶"));
                    assertThat(r.get("order_count"))
                            .as("归一化后合并计数（两行订单写的是同一个组合，是同一笔钱）").isEqualTo(2);
                    assertThat(String.valueOf(r.get("note"))).isNotBlank();
                });
        assertThat(gaps.get("unpriced_combination_total")).isEqualTo(2);
    }

    @Test
    @DisplayName("判据 4b：没有任何订单 ⇒ 缺口为空集（不是 null、不是异常；空集也是可读结论）")
    void gapsEmptyWhenNoOrders() {
        when(combinationMapper.selectList(any())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> gaps = queryService.feeGaps(TENANT);

        assertThat(gaps.get("unpriced_combinations")).isEqualTo(List.of());
        assertThat(gaps.get("unpriced_combination_total")).isEqualTo(0);
    }

    @Test
    @DisplayName("判据 4c：列表读面只回活跃行（停用的组合不得参与匹配）")
    void listReturnsOnlyActive() {
        when(combinationMapper.selectList(any())).thenReturn(List.of(
                combination("c1", "韩褶+打孔", "12.00")));

        Map<String, Object> list = queryService.combinations(TENANT);

        assertThat(list.get("total")).isEqualTo(1);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) list.get("combinations");
        assertThat(rows).singleElement().satisfies(r -> {
            assertThat(r.get("composition_key")).isEqualTo("韩褶+打孔");
            assertThat(r.get("items")).isEqualTo(List.of("韩褶", "打孔"));
            assertThat(r.get("unit_price")).isEqualTo(new BigDecimal("12.00"));
        });
    }

    // ── 订单行夹具：processing_info = {processingItems:[{name,unitPrice,quantity},…]}（OrderService 同口径）──

    private static OrderItem orderItem(String... names) {
        List<Map<String, Object>> items = new java.util.ArrayList<>();
        for (String name : names) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", "pi-" + name);
            entry.put("name", name);
            entry.put("unitPrice", new BigDecimal("9.5"));
            entry.put("quantity", new BigDecimal("12.3"));
            items.add(entry);
        }
        return OrderItem.builder().id("oi-" + String.join("-", names)).tenantId(TENANT)
                .orderId("o1").processingInfo(Map.of("processingItems", items)).build();
    }
}
