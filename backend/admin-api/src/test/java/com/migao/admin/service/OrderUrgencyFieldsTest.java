// case_ids: PR-079
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.beans.BeanUtils;

import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 订单级「加急 / 客户要求到货日」（V120，issue #5177）的**改单四律**与 wire 契约。
 *
 * <h2>为什么这些判据必须存在（各自的红证形态）</h2>
 * <ol>
 *   <li><b>零联动（判据 1）</b>：{@code updateUrgency} 的 SET 子句里**只能**有这两列加时间戳。
 *       红证 = 顺手写一行 {@code status}/{@code priority} 之类的同步 ⇒ SET 白名单断言红。
 *       另有源码级断言：本方法体**不得**出现售后工单字样（用户裁定「加急不能跟售后工单绑定」）。</li>
 *   <li><b>三态语义</b>：{@code null} = 不改、{@code ""} = 清空、{@code YYYY-MM-DD} = 设值。
 *       红证 = 把 {@code ""} 也当「不改」⇒ 清空态断言红（界面显示已清空而库里还有日期）。</li>
 *   <li><b>fail-closed</b>：非法日期 / 全空白**显式拒绝**，且**一次 update 都不发**
 *       （红证 = 静默回落成清空 ⇒ 拒绝断言红，且「零写入」断言红）。</li>
 *   <li><b>wire 契约</b>：JSON 键必须是 {@code isUrgent}（不是 {@code urgent}）。
 *       红证 = 把 DTO 字段从 {@code Boolean} 改成原生 {@code boolean} ⇒ Lombok 的 getter 变成
 *       {@code isUrgent()} ⇒ Jackson 推出的属性名变 {@code urgent} ⇒ 前端读不到加急标记。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("#5177 订单加急/到货日：改单三态 + 只写两列 + fail-closed + wire 键名")
class OrderUrgencyFieldsTest {

    private static final String ORDER_ID = "order-5177";

    @InjectMocks
    private OrderService orderService;

    @Mock
    private OrderMapper orderMapper;

    @BeforeEach
    void setUp() {
        // LambdaUpdateWrapper 的 lambda → 列名解析需要 Order 的 TableInfo（生产里由 MP 启动时装载）
        MybatisConfiguration conf = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(conf, ""), Order.class);
        // lenient：源码级/wire 两条判据不用 mapper ⇒ 严格模式会把这条 setup 当成多余打桩
        Order existing = Order.builder().id(ORDER_ID).tenantId(1L).orderNo("ORD-5177-0001")
                .status("confirmed").isUrgent(false).build();
        org.mockito.Mockito.lenient().when(orderMapper.selectById(ORDER_ID)).thenReturn(existing);
    }

    @Test
    @DisplayName("🔴 判据1/6 改单只写「那两列 + 时间戳」——SET 子句里不得出现任何金额/状态/售后字段")
    void updateUrgencyWritesOnlyTheTwoOwnColumns() {
        orderService.updateUrgency(ORDER_ID, true, "2026-10-01");

        ArgumentCaptor<LambdaUpdateWrapper<Order>> captor = captorOfWrapper();
        verify(orderMapper).update(isNull(), captor.capture());
        String sqlSet = captor.getValue().getSqlSet();

        assertThat(sqlSet).as("两列都必须进 SET（否则改单静默无效）")
                .contains("is_urgent").contains("required_delivery_date");
        assertThat(sqlSet).as("时间戳也要更新（否则列表读到的 updated_at 是陈旧的）")
                .contains("updated_at");
        assertThat(sqlSet)
                .as("🔴 零联动 / 不损失客户：SET 里**不得**出现对客金额、订单状态或售后工单的任何列")
                .doesNotContain("total_amount").doesNotContain("actual_amount")
                .doesNotContain("discount_amount").doesNotContain("refund_amount")
                .doesNotContain("status").doesNotContain("priority");
    }

    @Test
    @DisplayName("🔴 判据1 源码级零联动：updateUrgency 方法体不得出现售后工单/priority 字样")
    void updateUrgencyHasNoSharedSourceWithAfterSalesTicket() throws Exception {
        String body = methodBody(orderServiceSource(), "public void updateUrgency(");
        assertThat(body).as("方法体必须被真正截取到（否则这条断言是空跑）")
                .contains("Order::getRequiredDeliveryDate").contains("Order::getIsUrgent");
        assertThat(body.toLowerCase())
                .as("🔴 用户裁定「加急不能跟售后工单绑定，得在订单上直接做」⇒ "
                        + "本方法不得读写售后工单、不得出现 priority（红证 = 接上同一来源即红）")
                .doesNotContain("ticket").doesNotContain("priority").doesNotContain("aftersales")
                .doesNotContain("after_sales");
        // 另一个方向：Order 实体本身不得长出 priority 字段（否则「订单直接做」会漂成售后的别名）
        assertThat(java.util.Arrays.stream(Order.class.getDeclaredFields()).map(Field::getName))
                .as("Order 实体不得有 priority 字段（订单加急与售后 priority 是两个事实）")
                .doesNotContain("priority");
    }

    @Test
    @DisplayName("改单三态：null = 不改 / \"\" = 清空（真的能清）/ 日期 = 设值")
    void updateUrgencyTriState() {
        // ① 只改加急 ⇒ 到货日不进 SET（否则「只改加急」会顺手把到货日抹掉）
        orderService.updateUrgency(ORDER_ID, true, null);
        ArgumentCaptor<LambdaUpdateWrapper<Order>> first = captorOfWrapper();
        verify(orderMapper).update(isNull(), first.capture());
        assertThat(first.getValue().getSqlSet()).contains("is_urgent")
                .as("未传的字段不改（用户没表达过的意图不该被实现）").doesNotContain("required_delivery_date");

        // ② 空串 = 清空：必须在 SET 里出现该列（MyBatis-Plus 的 NOT_NULL 策略会跳过 null 字段
        //    ⇒ 走 updateById 永远清不掉，这正是本方法用显式 set 的理由）
        orderService.updateUrgency(ORDER_ID, null, "");
        ArgumentCaptor<LambdaUpdateWrapper<Order>> second = captorOfWrapper();
        verify(orderMapper, org.mockito.Mockito.times(2)).update(isNull(), second.capture());
        assertThat(second.getValue().getSqlSet())
                .as("🔴 清空态必须真的写这一列（null 值也要进 SET）").contains("required_delivery_date");
        assertThat(second.getValue().getParamNameValuePairs().values())
                .as("清空写下去的确实是 null").containsNull();
    }

    @Test
    @DisplayName("🔴 fail-closed：非法日期 / 全空白串 ⇒ 显式拒绝，且**一次 update 都不发**")
    void malformedOrBlankDateIsRejectedWithoutAnyWrite() {
        assertThatThrownBy(() -> orderService.updateUrgency(ORDER_ID, null, "2026/10/01"))
                .as("斜杠格式不得静默回落（回落成清空 = 静默丢数据）")
                .isInstanceOf(BusinessException.class).hasMessageContaining("到货日格式不正确");
        assertThatThrownBy(() -> orderService.updateUrgency(ORDER_ID, null, "  "))
                .as("⚠️ 全空白串不是「清空」：它更像误输入 ⇒ 拒绝（只有空串才是明确的清空）")
                .isInstanceOf(BusinessException.class).hasMessageContaining("到货日格式不正确");
        assertThatThrownBy(() -> orderService.updateUrgency(ORDER_ID, null, "2026-13-45"))
                .as("不存在的日期同样拒绝").isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> orderService.updateUrgency(ORDER_ID, null, null))
                .as("两个字段都不传 ⇒ 显式拒绝（静默 200 会让调用方以为改动生效了）")
                .isInstanceOf(BusinessException.class).hasMessageContaining("至少要传一个");

        verify(orderMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("🔴 wire 契约：JSON 键名是 isUrgent（原生 boolean 会让它变成 urgent，前端读不到）")
    void wireKeysAreIsUrgentAndIsoDate() throws Exception {
        // 🔴 线格式的前提**读真值源**（`application.yml`），不是在测试里自选一个格式再自证：
        // Spring Boot 关掉 `WRITE_DATES_AS_TIMESTAMPS` 才会把 LocalDate 出成 "2026-10-01"，
        // 否则前端拿到的是数组 [2026,10,1]（形状完全不同）。谁把它打开 ⇒ 这条断言先红。
        String applicationYml = Files.readString(repoRoot()
                .resolve("backend/admin-api/src/main/resources/application.yml"));
        assertThat(applicationYml)
                .as("线格式前提：`write-dates-as-timestamps: false`（否则到货日在 wire 上是数组）")
                .contains("write-dates-as-timestamps: false");

        ObjectMapper json = new ObjectMapper().findAndRegisterModules()
                .disable(com.fasterxml.jackson.databind.SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        OrderDetailResponse resp = new OrderDetailResponse();
        resp.setIsUrgent(true);
        resp.setRequiredDeliveryDate(LocalDate.of(2026, 10, 1));

        String payload = json.writeValueAsString(resp);
        assertThat(payload).as("🔴 前端/契约读的键是 isUrgent（不是 urgent）")
                .contains("\"isUrgent\":true");
        assertThat(payload).as("到货日按 YYYY-MM-DD 出线（不是时间戳、不是数组）")
                .contains("\"requiredDeliveryDate\":\"2026-10-01\"");

        // 实体 → DTO 的同名拷贝（列表/详情两条读面都靠 BeanUtils，不另立第二份取值口径）
        Order order = Order.builder().id(ORDER_ID).isUrgent(true)
                .requiredDeliveryDate(LocalDate.of(2026, 10, 1)).build();
        OrderDetailResponse copied = new OrderDetailResponse();
        BeanUtils.copyProperties(order, copied);
        assertThat(copied.getIsUrgent()).as("实体 → DTO 必须逐值带出（否则列表角标永远不亮）").isTrue();
        assertThat(copied.getRequiredDeliveryDate()).isEqualTo(LocalDate.of(2026, 10, 1));
    }

    @Test
    @DisplayName("判据2 缺省不变：建单 DTO 的两个字段必须是**可空包装类型**（未传 ⇒ 不写列 ⇒ 落默认）")
    void createRequestFieldsAreNullableWrappers() throws Exception {
        assertThat(OrderCreateRequest.class.getDeclaredField("isUrgent").getType())
                .as("🔴 必须是 Boolean：原生 boolean 的 Jackson 键会变成 `urgent`，且无法表达「未传」")
                .isEqualTo(Boolean.class);
        assertThat(OrderCreateRequest.class.getDeclaredField("requiredDeliveryDate").getType())
                .as("必须是 LocalDate（可空）—— 未传 ⇒ 不写列 ⇒ NULL = 未指定，不猜")
                .isEqualTo(LocalDate.class);

        // 未设置时两字段为 null ⇒ MyBatis-Plus 默认 NOT_NULL 策略下**不进 INSERT** ⇒ 落列默认
        OrderCreateRequest request = new OrderCreateRequest();
        assertThat(request.getIsUrgent()).as("缺省不加急").isNull();
        assertThat(request.getRequiredDeliveryDate()).as("缺省未指定到货日").isNull();
    }

    // ─────────────────────────────────────────── 夹具

    @SuppressWarnings("unchecked")
    private static ArgumentCaptor<LambdaUpdateWrapper<Order>> captorOfWrapper() {
        return ArgumentCaptor.forClass(LambdaUpdateWrapper.class);
    }

    private static String orderServiceSource() throws Exception {
        return Files.readString(repoRoot()
                .resolve("backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java"));
    }

    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位仓库根").isNotNull();
        return root;
    }

    /** 截取 `signature` 起、到下一个「顶格 `}`」为止的方法体（4 空格缩进 = 类内方法）。 */
    private static String methodBody(String source, String signature) {
        int start = source.indexOf(signature);
        assertThat(start).as("必须能定位方法：" + signature).isNotNegative();
        int end = source.indexOf("\n    }\n", start);
        assertThat(end).as("必须能定位方法体结束（否则断言会读到整份文件 = 假绿）").isNotNegative();
        return source.substring(start, end);
    }
}
