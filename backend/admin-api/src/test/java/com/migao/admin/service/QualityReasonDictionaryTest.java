// case_ids: MC-181
package com.migao.admin.service;

import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.QualityCheck;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.QualityCheckMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 不合格**原因字典**（issue #7197 的 ①）—— 判据逐条对应施工单 ①-a ~ ①-c。
 *
 * <p><b>病（坐标现取）</b>：{@code quality_inspections.reason} 是**自由文本**
 * （「布面污渍」/「脏」/「污渍」会被算成三个不同原因）⇒ 缺陷 Top 分布 / 帕累托在结构上算不了。
 * 修法 = 「**必选字典项**（可统计的原因键）+ 自由补充（可空）」，且**存量不清洗**。</p>
 *
 * <p>🔴 <b>判据</b>：
 * <ol>
 *   <li><b>①-a 新记录没选字典项 ⇒ 拒</b>：判定 ≠ 合格且 {@code reason_code} 缺失 / 空白 ⇒ 422，
 *       文案**点名该选哪个字段 + 列全六项可选原因**，且**零写入**；重点负控：**只填了自由文本**
 *       也必须拒（自由文本不能顶替字典项 —— 那正是这条修法要堵的口子）；</li>
 *   <li><b>①-a' 字典外的 code ⇒ 拒</b>（不静默降级成自由文本、不猜最接近的一项）；</li>
 *   <li><b>①-b 字典项全集覆盖</b>：每一项都有**真实用处** —— 中文名非占位 / 非 code 回显 / 两两不同，
 *       且**每一项都能真的落库读回**（没有「登记了但用不了」的项），「其它」是最后一项，
 *       录入面（{@link QualityReasonDictionary#options()}）与校验面读**同一份**；</li>
 *   <li><b>①-c 存量老记录不被清洗</b>（负控）：{@code reason_code} 为 {@code null} 的老行，
 *       {@code reason} **逐字原样**读出、{@code reason_label} 为 {@code null}，且读面**零写入**
 *       （不猜归类、不回填、不改写）。</li>
 * </ol>
 *
 * <p>⚠️ <b>边界（如实登记）</b>：本判据判「字典项存在且可用 + 新旧可区分」，**判不了**
 * 「这六项是不是车间真正最常见的六类」—— 那是业务口径（issue #7197 的「按租户可配」属后续切片）。
 * ①-d 的红证是**注入式**的（把 {@code QualityCheckService} 里那段字典校验摘掉 ⇒ ①-a 当场转红），
 * 注入方式与读数写在 PR body，**不**常驻注入。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("不合格原因字典（issue #7197 ①）：必选字典项 + 存量不清洗")
class QualityReasonDictionaryTest {

    private static final Long TENANT = 1L;
    private static final String ITEM_ID = "item-curtain-1";
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";
    private static final String INSPECTOR_ID = "user-inspector-1";
    private static final String INSPECTOR_NAME = "质检员小李";
    private static final OffsetDateTime AT = OffsetDateTime.parse("2026-11-03T10:30:00+08:00");

    @Mock
    private QualityCheckMapper qualityInspectionMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private ProcessingOrderSetMapper processingOrderSetMapper;

    private QualityCheckService service;
    /** 真落库的行（不是 mock 的入参断言 —— 用它逐值核对「落的是什么」）。 */
    private final List<QualityCheck> inserted = new ArrayList<>();

    @BeforeEach
    void setUp() {
        inserted.clear();
        service = new QualityCheckService(qualityInspectionMapper, orderItemMapper, processingOrderMapper,
                orderMapper, new com.fasterxml.jackson.databind.ObjectMapper());
        ReflectionTestUtils.setField(service, "processingOrderSetMapper", processingOrderSetMapper);
        when(orderItemMapper.selectById(ITEM_ID)).thenReturn(OrderItem.builder()
                .id(ITEM_ID)
                .tenantId(TENANT)
                .orderId(ORDER_ID)
                .productName("布艺遮光帘A 米白")
                .deleted(0)
                .build());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT))
                .thenReturn(ProcessingOrder.builder().id(PO_ID).tenantId(TENANT).orderId(ORDER_ID).build());
        when(qualityInspectionMapper.insert(any(QualityCheck.class))).thenAnswer(invocation -> {
            inserted.add(invocation.getArgument(0));
            return 1;
        });
    }

    /** 员工端录入（套号 / 工人身份不参与本文件的判据）。 */
    private Map<String, Object> createWith(String result, String reason, String reasonCode) {
        return service.create(TENANT, ITEM_ID, result, reason, reasonCode,
                INSPECTOR_ID, INSPECTOR_NAME, QualityCheckService.INSPECTOR_EMPLOYEE, AT, null, null);
    }

    @Test
    @DisplayName("①-a 判定≠合格且未选字典项 ⇒ 具名 422（列全可选原因）且零写入")
    void newRecordWithoutDictionaryCodeIsRejected() {
        // 重点负控：**只填了自由文本**也算「没选」—— 自由文本不能顶替字典项
        assertThatThrownBy(() -> createWith("rework", "缝线开裂", null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不合格原因字典")
                .hasMessageContaining("返工")
                // 具名：说清该选哪个 —— 文案里必须有全部六项
                .hasMessageContaining("布面污渍")
                .hasMessageContaining("布料破洞")
                .hasMessageContaining("色差")
                .hasMessageContaining("尺寸不符")
                .hasMessageContaining("走线不良")
                .hasMessageContaining("其它");
        assertThat(inserted).as("缺字典项不许静默落库（自由文本不能顶替字典项）").isEmpty();
        verify(qualityInspectionMapper, never()).insert(any(QualityCheck.class));

        // 空串 / 全空白与 null 同一形态（前端清空后提交不能被当成「选了」）
        for (String blank : new String[]{"", "   "}) {
            assertThatThrownBy(() -> createWith("scrap", "布面污渍", blank))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("不合格原因字典")
                    .hasMessageContaining("报废");
        }
        assertThat(inserted).isEmpty();
    }

    @Test
    @DisplayName("①-a' 字典外的 code ⇒ 具名 422（不静默降级成自由文本）")
    void unknownDictionaryCodeIsRejected() {
        assertThatThrownBy(() -> createWith("rework", "脏", "dirty"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不合格原因字典")
                .hasMessageContaining("dirty")
                .hasMessageContaining("布面污渍");
        assertThat(inserted).isEmpty();
        verify(qualityInspectionMapper, never()).insert(any(QualityCheck.class));
    }

    @Test
    @DisplayName("①-b 字典项全集覆盖：每一项都是真实原因（非占位）、两两不同、都能落库读回")
    void everyDictionaryItemIsRealAndUsable() {
        Map<String, String> items = QualityReasonDictionary.items();
        assertThat(items).as("字典不许空转").isNotEmpty();

        Set<String> labels = new LinkedHashSet<>();
        for (Map.Entry<String, String> entry : items.entrySet()) {
            String code = entry.getKey();
            String label = entry.getValue();
            // 真实原因：非空、不与 code 同形（回显 = 占位）、不是调试词
            assertThat(label).as("字典项 %s 必须有中文原因", code).isNotBlank();
            assertThat(label).as("字典项 %s 的原因不能是占位/调试词", code)
                    .doesNotContainPattern("占位|TODO|TBD|待定|示例|xxx|XXX")
                    .isNotEqualTo(code);
            assertThat(labels.add(label)).as("两个字典项不许给出同一个原因（%s）", label).isTrue();

            // 可用：真的能落库 + 读回归属同一项（没有「登记了但用不了」）
            Map<String, Object> view = createWith("rework", null, code);
            assertThat(inserted).as("字典项 %s 必须能落库", code).hasSize(1);
            QualityCheck row = inserted.get(0);
            assertThat(row.getReasonCode()).isEqualTo(code);
            assertThat(view).containsEntry("reason_code", code)
                    .containsEntry("reason_label", label);
            inserted.clear();
        }

        // 「其它」是兜底项：必须在最后（界面按钮顺序 = 本表顺序）
        List<String> codes = new ArrayList<>(items.keySet());
        assertThat(codes.get(codes.size() - 1)).isEqualTo(QualityReasonDictionary.OTHER);

        // 录入面读的是**同一份**（不另造会漂的第二张表）
        List<Map<String, Object>> options = QualityReasonDictionary.options();
        assertThat(options).hasSize(items.size());
        for (int i = 0; i < options.size(); i++) {
            assertThat(options.get(i)).containsEntry("code", codes.get(i))
                    .containsEntry("label", items.get(codes.get(i)));
        }
    }

    @Test
    @DisplayName("①-b' 判为合格时字典项可空；给了字典外的值仍拒（取值域只有一份）")
    void passRecordDoesNotRequireDictionaryCode() {
        Map<String, Object> view = createWith("pass", null, null);
        assertThat(inserted).hasSize(1);
        assertThat(inserted.get(0).getReasonCode()).isNull();
        assertThat(view.get("reason_code")).isNull();
        assertThat(view.get("reason_label")).isNull();

        assertThatThrownBy(() -> createWith("pass", null, "not-a-real-code"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不合格原因字典");
        assertThat(inserted).hasSize(1);
    }

    @Test
    @DisplayName("①-c 存量老记录不被清洗：reason 逐字原样、无字典项、读面零写入（负控）")
    void legacyFreeTextReasonIsNotCleaned() {
        QualityCheck legacy = QualityCheck.builder()
                .id("qi-old-1")
                .tenantId(TENANT)
                .processingOrderId(PO_ID)
                .orderItemId(ITEM_ID)
                .inspectionResult("scrap")
                // 老写法：自由文本（不清洗 = 不回填 reason_code、不改写这句）
                .reason("  脏 污渍（2026-10 老写法）  ")
                .inspectedAt(AT)
                .deleted(0)
                .build();
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(legacy));

        List<Map<String, Object>> rows = service.list(TENANT, null, ITEM_ID);

        assertThat(rows).hasSize(1);
        Map<String, Object> view = rows.get(0);
        assertThat(view.get("reason")).isEqualTo("  脏 污渍（2026-10 老写法）  ");
        assertThat(view.get("reason_code")).as("存量行不回填字典项（不猜归类）").isNull();
        assertThat(view.get("reason_label")).as("未归类 ⇒ 不给中文标签（不许把自由文本冒充字典项）").isNull();
        // 负控：读面一个字都没写（没有回填 / 没有归一化）
        verify(qualityInspectionMapper, never()).insert(any(QualityCheck.class));
        verify(qualityInspectionMapper, never()).updateById(any(QualityCheck.class));
        assertThat(inserted).isEmpty();

        // 新旧可区分：同一条读面里，新记录带 reason_code、老记录不带
        createWith("rework", "脏 污渍", "fabric_stain");
        assertThat(inserted).hasSize(1);
        assertThat(inserted.get(0).getReasonCode()).isEqualTo("fabric_stain");
        assertThat(inserted.get(0).getReason()).isEqualTo("脏 污渍");
    }

    @Test
    @DisplayName("①-c' 录入面把字典真下发（接线：GET /reasons 端点 + 权限码与录入面同码）")
    void dictionaryIsExposedThroughTheController() throws Exception {
        java.lang.reflect.Method method =
                com.migao.admin.controller.QualityCheckController.class.getMethod("reasons");
        assertThat(method.getAnnotation(org.springframework.web.bind.annotation.GetMapping.class).value())
                .as("字典读面的端点路径").containsExactly("/reasons");
        com.migao.admin.security.RequirePermission permission =
                method.getAnnotation(com.migao.admin.security.RequirePermission.class);
        assertThat(permission).as("能录判定的人才知道有哪些原因可录").isNotNull();
        assertThat(permission.value()).isEqualTo("production:inspect");
    }
}
