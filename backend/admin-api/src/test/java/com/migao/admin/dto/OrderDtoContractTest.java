// case_ids: OR-008, OR-016
package com.migao.admin.dto;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import java.io.IOException;
import java.lang.annotation.Annotation;
import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 订单创建 DTO 契约（issue #4089 · A17 订单 DTO 收敛）——**分歧集合必须为空**。
 *
 * <p><b>判据（issue #4089 裁定）</b>：agent 路径与人工路径共用同一个 create request 类型；
 * 「两套 DTO 的分歧集合 = 空」；凡「agent 侧更严」的约束保留在**同一类型**上，不是第二套注解集。</p>
 *
 * <p><b>本类为什么不是散文断言</b>：它把 issue 清单里逐条实测的 13 处分歧（D1~D13）做成
 * **可复算判据**，每条都有一个"改了就会红"的判定点：</p>
 * <ol>
 *   <li><b>① 13 行处置矩阵</b>（{@code divergenceRows}，数据驱动）：issue 清单的每一处
 *       （D1~D13）各一行，收敛项带**收敛判据**（不满足即红），未收敛项带**登记文本**
 *       （与 {@link #REGISTERED_DIVERGENCES} 逐字相等，缺失/改写即红）；</li>
 *   <li><b>② 单一 DTO</b>：{@code AgentOrderCreateRequest} 只允许声明 {@code clientRequestId}
 *       （幂等键，非业务字段），明细类型必须就是 {@link OrderCreateRequest.OrderItemRequest}，
 *       旧 {@code AgentOrderItem} 不得复活；</li>
 *   <li><b>③ 跨语言 wire 契约</b>：Java DTO 与 ai-agent 工具 schema（唯一生产者）的**字段集合**
 *       逐字相等 —— 源码级解析 {@code order_create.py} 的 {@code parameters}，不是抄一份期望值；</li>
 *   <li><b>④ 登记完整性</b>：13 = 收敛项 + {@link #REGISTERED_DIVERGENCES}，且每条登记都有
 *       Python 侧事实的原子复核（{@code pythonAcceptsAtomic}）；</li>
 *   <li><b>⑤ 校验双写</b>：同一份 payload 驱动**同一个 Validator** 跑两条 DTO：不合法的输入
 *       两侧必须给出**同一组字段 + 同一条文案**（"单一来源"的机器判据），合法输入必须零违规。</li>
 * </ol>
 *
 * <p><b>本类不做什么</b>：不测 Service 行为（另有 {@code AgentOrderServiceTest} /
 * {@code OrderIdempotencyTest} / {@code AgentOrderCreateValidationTest}）；不改 ai-agent 的
 * LLM 契约（Python 侧刻意比服务端更严的提示性约束见 {@link #REGISTERED_DIVERGENCES}）。</p>
 *
 * <p>Python schema 解析：{@code order_create.py} 的 {@code parameters} 是**带注释的 Python dict
 * 字面量**，故先剥掉顶层注释行再当 JSON 读；读不到/读歪 → 断言红（不静默跳过）。</p>
 */
@DisplayName("订单创建 DTO 契约：两套定义的分歧集合必须为空（issue #4089）")
class OrderDtoContractTest {

    /** ai-agent 工具 schema 的位置（唯一生产者；从测试工作目录 backend/admin-api 上溯到仓库根） */
    private static final Path ORDER_CREATE_PY =
            Paths.get("..", "..", "backend", "ai-agent-service", "app", "tools", "order_create.py")
                    .toAbsolutePath().normalize();

    private static final ObjectMapper JSON = new ObjectMapper();

    private static final Validator VALIDATOR;
    static {
        try (ValidatorFactory factory = Validation.buildDefaultValidatorFactory()) {
            VALIDATOR = factory.getValidator();
        }
    }

    /** Bean Validation 文案（两套 DTO 共用同一类型 ⇒ 这里断的是"同一来源"而不是"两边都写了") */
    private static final String MSG_PHONE_BLANK = "客户电话不能为空";
    private static final String MSG_PHONE_PATTERN = "手机号格式不正确，请输入11位中国大陆手机号";
    private static final String MSG_ITEMS_EMPTY = "订单明细不能为空";
    private static final String MSG_NAME_BLANK = "商品名称不能为空";
    private static final String MSG_QTY_NULL = "数量不能为空";
    private static final String MSG_QTY_MIN = "数量不能小于 1";
    private static final String MSG_PRICE_NULL = "单价不能为空";
    private static final String MSG_PRICE_POSITIVE = "单价必须大于 0";
    private static final String MSG_SUBTOTAL_NULL = "小计不能为空";
    private static final String MSG_SUBTOTAL_POSITIVE = "小计必须大于 0";

    // ─────────────────────────────────────────────────────────────────────
    // ① 13 处分歧逐条处置矩阵（issue #4089 清单的机器化形态）
    //    每行 = 一处分歧：`probe` 是**收敛判据**（不满足即红），`nonConvergence` 非空时
    //    改为断言"该处未收敛必须有登记"—— 数据驱动，13 行必须齐（见 accountedDivergenceCodes）。
    // ─────────────────────────────────────────────────────────────────────

    /** 一处分歧的处置（records：Java 21） */
    private record DivergenceRow(String code, String title, Runnable probe, String nonConvergence) {
    }

    static Stream<Arguments> divergenceRows() {
        Class<?> shared = OrderCreateRequest.class;
        Class<?> item = OrderCreateRequest.OrderItemRequest.class;
        Class<?> agent = AgentOrderCreateRequest.class;

        List<DivergenceRow> rows = List.of(
                new DivergenceRow("D1 skuCode 位置",
                        "顶层死字段 → 只在 processingInfo（工具不发、库存键族不读）", () -> {
                    assertThat(allFieldNames(agent))
                            .as("D1：agent wire 不得再声明顶层 skuCode（唯一生产者从不填它；"
                                    + "服务端取价/库存两条路径都从 processingInfo 解析）")
                            .doesNotContain("skuCode");
                    assertThat(allFieldNames(item)).doesNotContain("skuCode");
                }, null),
                new DivergenceRow("D2 colorName 位置", "同 D1", () -> {
                    assertThat(allFieldNames(agent)).as("D2：agent wire 不得再声明顶层 colorName").doesNotContain("colorName");
                    assertThat(allFieldNames(item)).doesNotContain("colorName");
                }, null),
                new DivergenceRow("D3 subtotal 必填性",
                        "agent 侧可选 vs 表单侧必填 → 单一类型上必填（工具侧 required 本就必传）", () -> {
                    assertThat(constraint(item, "subtotal", "NotNull"))
                            .as("D3：`小计不能为空` 必须写在共享明细类型上（agent 侧不再可选）")
                            .isNotNull();
                }, null),
                new DivergenceRow("D4 subtotal 语义",
                        "Python=含加工费 / Java 强制改写为不含 → 服务端重算口径单点拥有", () -> {
                    // DTO 层无可判据：D4 的两侧差异在 **Service 的金额算法**（createOrder 强制
                    // subtotal = unitPrice × quantity 后落 order_items.subtotal），不是 wire 契约。
                    // 收敛后果由 Service 测试锁：AgentOrderServiceTest 的「小计按原值重算」用例。
                    assertThat(allFieldNames(item))
                            .as("D4 收敛口径：明细只有**一个** subtotal 字段（不存在第二套口径字段）")
                            .contains("subtotal");
                }, null),
                new DivergenceRow("D5 subtotal 边界", "@Positive（>0）单一来源", () -> {
                    assertThat(constraint(item, "subtotal", "Positive"))
                            .as("D5：边界 `小计必须大于 0` 必须写在共享明细类型上")
                            .isNotNull();
                }, null),
                new DivergenceRow("D6 width/height 边界",
                        "只有 Python 有 min 0 → 服务端同口径补 @DecimalMin(0)", () -> {
                    // Java 侧曾比 Python **更松**（裸 BigDecimal）：负尺寸会进面积/单价数学。
                    // 收敛方向只能是收紧 Java（Python 侧不得放宽，它是唯一生产者的安检）。
                    assertThat(constraintValue(item, "width", "DecimalMin", "value"))
                            .as("D6：宽度非负必须由共享类型承受（Python schema 是 minimum: 0）")
                            .isEqualTo("0");
                    assertThat(constraintValue(item, "height", "DecimalMin", "value"))
                            .as("D6：高度同上").isEqualTo("0");
                }, null),
                new DivergenceRow("D7 productName 非空",
                        "只有 Python 有 minLength=1 → 共享类型 @NotBlank", () -> {
                    assertThat(constraint(item, "productName", "NotBlank"))
                            .as("D7：空商品名无法在列表/对账里定位商品，必须由共享类型挡住")
                            .isNotNull();
                }, null),
                new DivergenceRow("D8 sellingMethod 枚举",
                        "服务端已归一化（更严的一侧在 Python）→ 登记不收敛", null,
                        "Java：DTO 零约束；库存路径 SkuNotation.normalizeSellingMethod 归一化中文标签/变体"
                                + "（#3621） → Python 更严：enum[bulk_cut,full_roll] 且本地拒绝变体"
                                + " → 依据：收敛需**放宽 Python**（降唯一生产者安检）或给服务端加一套只对"
                                + " Python 生效的注解（= 新的第二套定义），两者都被 issue 裁定排除"),
                new DivergenceRow("D9 pricingMethod 枚举", "服务端不消费该键（单侧安全冗余）→ 登记不收敛", null,
                        "Java：extractProcessingItems 只取 id/name/unitPrice/quantity，pricingMethod 完全不读"
                                + " → Python 更严：enum[per_meter,per_set,fixed,per_area] + 本地拒绝"
                                + " → 依据：给服务端加一个**从不读**的字段的约束 = 凭空发明校验，"
                                + "且日后有人读它时注解会与算法脱节"),
                new DivergenceRow("D10 processingInfo 容器结构", "容器结构校验点在生产侧 → 登记不收敛", null,
                        "Java：Object 零结构约束（且兼容 JSON 字符串形态）"
                                + " → Python：完整嵌套 schema → 依据：服务端只把 processingInfo 透传落库，"
                                + "同一条内容在服务端没有算法消费其结构；把嵌套 schema 复制成 Java 注解="
                                + "第二套定义（正是本单要消灭的形态）"),
                new DivergenceRow("D11 processingItems[] 多出的键",
                        "多出 unit/pricingMethod/subtotal 被忽略（无害）→ 登记不收敛", null,
                        "Java：消费 id/name/unitPrice/quantity；Python 声明 7 键（多 unit/pricingMethod/subtotal）"
                                + " → 依据：多余键被服务端忽略（无害且向前兼容）；删它们=降低工具侧可读性，"
                                + "加它们=服务端凭空约束（同 D9）"),
                new DivergenceRow("D12 processingFee=Σ明细 自洽",
                        "两侧代码都不交叉校验（服务端按明细求和）→ 登记不收敛 + 跟单", null,
                        "Java：sumProcessingFee 只按 processingItems 求和，processingFee 字段不参与"
                                + " → Python：工具描述要求自洽、代码不校验 → 依据：这是 issue 清单里的"
                                + "**独立缺陷**（服务端金额算法口径），修它要动 OrderService 的金额路径"
                                + "与工具层，超出『DTO 收敛』本单；#4089 已把它列为待办（D12 优先项）"),
                new DivergenceRow("D13 规格键族不相交",
                        "ID 族 vs 字符串族 → 共享字段集合逐字相等（wire 层零差异）", () -> {
                    // D13 的根源在 product_detail 不透传 color_id（另一侧文件，不在本单范围）；
                    // 本单能且只能收敛的是 **wire 字段集合**：两侧不许各声明一半（见 ② WireContract）。
                    Set<String> expected = new TreeSet<>(allFieldNames(OrderCreateRequest.class));
                    expected.add("clientRequestId");
                    assertThat(allFieldNames(agent)).containsExactlyInAnyOrderElementsOf(expected);
                }, null));

        return rows.stream().map(r -> Arguments.of(r.code(), r.title(), r.probe(), r.nonConvergence()));
    }

    @ParameterizedTest(name = "{0} —— {1}")
    @MethodSource("divergenceRows")
    @DisplayName("13 处分歧逐条处置（收敛判据 / 未收敛登记）")
    void divergenceDisposition(String code, String title, Runnable probe, String nonConvergence) {
        if (nonConvergence == null) {
            probe.run();
        } else {
            assertThat(REGISTERED_DIVERGENCES)
                    .as("%s 未收敛 ⇒ 必须在 REGISTERED_DIVERGENCES 里逐条登记（含两侧事实与依据）", code)
                    .containsKey(code);
            assertThat(REGISTERED_DIVERGENCES.get(code))
                    .as("%s 的登记必须写明两侧事实与依据，不许空话", code)
                    .isEqualTo(nonConvergence)
                    .contains("Java：").contains("依据：");
        }
    }


    // ─────────────────────────────────────────────────────────────────────
    // ② 单一 DTO：agent 侧不许再有第二套定义（D1/D2/D7 的结构性判据）
    // ─────────────────────────────────────────────────────────────────────

    @Nested
    @DisplayName("② 单一 DTO：agent 路径与人工路径共用同一 create request 类型")
    class SingleDto {

        @Test
        @DisplayName("AgentOrderCreateRequest 必须继承 OrderCreateRequest（不是平行定义）")
        void agentRequestIsSubtypeOfSharedRequest() {
            assertThat(OrderCreateRequest.class.isAssignableFrom(AgentOrderCreateRequest.class))
                    .as("issue #4089 裁定：两条路径共用同一个 create request 类型（agent 侧只允许收紧）")
                    .isTrue();
        }

        @Test
        @DisplayName("第二条定义（旧 AgentOrderItem）不得复活，字段只允许再加幂等键")
        void agentRequestDeclaresNoSecondDefinition() {
            assertThat(declaredFieldNames(AgentOrderCreateRequest.class))
                    .as("agent 侧只允许声明幂等键（服务端从请求头注入）；再声明 customerName/productName"
                            + "/subtotal 等业务字段 = 第二条 wire 定义复活，两条路径又会漂移")
                    .containsExactly("clientRequestId");
            assertThat(Arrays.stream(AgentOrderCreateRequest.class.getDeclaredClasses())
                    .map(Class::getSimpleName).collect(Collectors.toList()))
                    .as("AgentOrderCreateRequest 不得再内嵌第二套明细类型（旧 AgentOrderItem）")
                    .isEmpty();
            assertThat(returnTypeName(AgentOrderCreateRequest.class, "getItems"))
                    .as("明细必须是共享类型 List<OrderItemRequest>（旧 AgentOrderItem 的 getItems 返回类型）")
                    .isEqualTo("java.util.List<com.migao.admin.dto.OrderCreateRequest$OrderItemRequest>");
        }

        @Test
        @DisplayName("D7：items 非空 + 元素级约束级联，都写在共享类型上")
        void itemsConstraintsOnSharedType() {
            assertThat(constraint(OrderCreateRequest.class, "items", "NotEmpty"))
                    .as("`items@NotEmpty` 必须写在共享类型上；agent 侧单独写一遍 = 第二套注解集")
                    .isNotNull();
            assertThat(constraint(OrderCreateRequest.class, "items", "Valid"))
                    .as("items 必须 @Valid，否则元素级约束不级联（负数量/负单价会绕过）")
                    .isNotNull();
        }

        @Test
        @DisplayName("V1：手机号约束（正则 + 非空）在共享类型上只有一处")
        void phoneConstraintSingleSourced() {
            assertThat(constraint(OrderCreateRequest.class, "customerPhone", "NotBlank")).isNotNull();
            assertThat(constraintValue(OrderCreateRequest.class, "customerPhone", "Pattern", "regexp"))
                    .as("手机号正则只有这一处（Service 层不再另写一份逐字段判定）")
                    .isEqualTo("^1[3-9]\\d{9}$");
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // ③ D13：Java wire 契约 ↔ 唯一生产者（ai-agent 工具 schema）字段集合逐字相等
    // ─────────────────────────────────────────────────────────────────────

    @Nested
    @DisplayName("③ 跨语言 wire 契约（源码级解析 order_create.py，不是抄期望值）")
    class WireContract {

        /** Python schema 键 ↔ Java 字段（唯一一处映射表；snake_case↔camelCase 是语言约定，不计分歧） */
        private final Map<String, String> fieldMap = new LinkedHashMap<>();

        WireContract() {
            fieldMap.put("customer_name", "customerName");
            fieldMap.put("customer_phone", "customerPhone");
            fieldMap.put("customer_address", "customerAddress");
            fieldMap.put("remark", "remark");
            fieldMap.put("items", "items");
            // 明细级（Python 键 → Java 字段）
            fieldMap.put("product_name", "productName");
            fieldMap.put("product_id", "productId");
            fieldMap.put("quantity", "quantity");
            fieldMap.put("unit_price", "unitPrice");
            fieldMap.put("subtotal", "subtotal");
            fieldMap.put("width", "width");
            fieldMap.put("height", "height");
            fieldMap.put("processing_info", "processingInfo");
        }

        @Test
        @DisplayName("D13：顶层字段集合逐字相等（白名单=已登记的单侧字段，登记外零差异）")
        void topLevelFieldSetsAreIdentical() throws IOException {
            Set<String> py = pythonTopLevelKeys();
            Set<String> javaKeys = fieldMap.entrySet().stream()
                    .filter(e -> allFieldNames(AgentOrderCreateRequest.class).contains(e.getValue()))
                    .map(Map.Entry::getKey).collect(Collectors.toCollection(LinkedHashSet::new));

            assertDivergenceFree("D13/wire-顶层", py, javaKeys, REGISTERED_SINGLE_SIDED_FIELDS.keySet(),
                    allFieldNames(AgentOrderCreateRequest.class));
        }

        @Test
        @DisplayName("单侧字段必须登记（白名单外出现「只有一侧有」的字段 ⇒ 红）")
        void singleSidedFieldsMustBeRegistered() throws IOException {
            Set<String> py = pythonTopLevelKeys();
            Set<String> javaWireKeys = allFieldNames(AgentOrderCreateRequest.class).stream()
                    .filter(f -> !"clientRequestId".equals(f))
                    .collect(Collectors.toCollection(LinkedHashSet::new));
            Set<String> pyAsJavaNames = fieldMap.entrySet().stream()
                    .filter(e -> py.contains(e.getKey()))
                    .map(Map.Entry::getValue)
                    .collect(Collectors.toCollection(LinkedHashSet::new));

            Set<String> onlyJava = new TreeSet<>(javaWireKeys);
            onlyJava.removeAll(pyAsJavaNames);
            Set<String> onlyPy = new TreeSet<>(py);
            onlyPy.removeAll(fieldMap.entrySet().stream()
                    .filter(e -> javaWireKeys.contains(e.getValue()))
                    .map(Map.Entry::getKey)
                    .collect(Collectors.toCollection(LinkedHashSet::new)));

            Set<String> unregisteredJava = new TreeSet<>(onlyJava);
            unregisteredJava.removeAll(REGISTERED_SINGLE_SIDED_FIELDS.keySet());
            assertThat(unregisteredJava)
                    .as("出现**未登记**的 Java 单侧字段（工具 schema 里没有）⇒ 先回答"
                            + "『它是不是又一套定义』再登记；不许默默放过")
                    .isEmpty();

            Set<String> unregisteredPy = new TreeSet<>(onlyPy);
            unregisteredPy.removeAll(REGISTERED_SINGLE_SIDED_FIELDS.keySet());
            assertThat(unregisteredPy)
                    .as("出现**未登记**的 Python 单侧字段（服务端 DTO 不认它）⇒ 必须在此登记")
                    .isEmpty();

            Set<String> allSingleSided = new TreeSet<>(onlyJava);
            allSingleSided.addAll(onlyPy);
            Set<String> stale = new TreeSet<>(REGISTERED_SINGLE_SIDED_FIELDS.keySet());
            stale.removeAll(allSingleSided);
            assertThat(stale)
                    .as("登记表里有**已不单侧**（或已删除/已改名）的条目 ⇒ 白名单腐化，必须同步删掉")
                    .isEmpty();
            assertThat(REGISTERED_SINGLE_SIDED_FIELDS.values())
                    .as("每条单侧字段登记必须写明依据（为什么只能单侧），不许只写一个名字")
                    .allSatisfy(v -> assertThat(v).contains("只有").contains("服务端").hasSizeGreaterThan(30));
        }

        @Test
        @DisplayName("D13：明细字段集合逐字相等（Java 多声明 = 死字段；Java 少声明 = 工具发来的值被丢弃）")
        void itemFieldSetsAreIdentical() throws IOException {
            Set<String> py = pythonItemKeys();
            Set<String> javaKeys = fieldMap.entrySet().stream()
                    .filter(e -> allFieldNames(OrderCreateRequest.OrderItemRequest.class).contains(e.getValue()))
                    .map(Map.Entry::getKey).collect(Collectors.toCollection(LinkedHashSet::new));

            assertDivergenceFree("D13/wire-明细", py, javaKeys, Set.of(),
                    allFieldNames(OrderCreateRequest.OrderItemRequest.class));
        }

        @Test
        @DisplayName("D13：Python `required` 与 Java 约束同口径（工具必填的字段服务端也必须必填）")
        void requiredFlagMatchesConstraint() throws IOException {
            JsonNode item = pythonItemSchema();
            List<String> pyRequired = new ArrayList<>();
            item.path("required").forEach(n -> pyRequired.add(n.asText()));

            assertThat(pyRequired)
                    .as("Python 强制 LLM 填的字段，服务端必须同样必填（否则工具侧白拦、服务端仍可落空值）")
                    .contains("product_name", "quantity", "unit_price", "subtotal");
            assertThat(constraint(OrderCreateRequest.OrderItemRequest.class, "productName", "NotBlank")).isNotNull();
            assertThat(constraint(OrderCreateRequest.OrderItemRequest.class, "quantity", "NotNull")).isNotNull();
            assertThat(constraint(OrderCreateRequest.OrderItemRequest.class, "unitPrice", "NotNull")).isNotNull();
            assertThat(constraint(OrderCreateRequest.OrderItemRequest.class, "subtotal", "NotNull")).isNotNull();
        }
    }

    /**
     * 单侧字段登记（issue #4089 清单 §2 同口径）：只在**一条路径**出现的字段，不是"两套定义的分歧"，
     * 但必须登记 —— 否则下一轮又会当成新发现重查一遍。
     *
     * <p>登记内容 = 字段 → 为什么只能单侧（依据）。{@code assertNoUnregisteredSingleSidedField} 保证
     * 白名单外的"单侧字段"一律判红（新增一个只有人工路径有的字段 ⇒ 必须在此登记）。</p>
     */
    private static final Map<String, String> REGISTERED_SINGLE_SIDED_FIELDS = new LinkedHashMap<>();
    static {
        REGISTERED_SINGLE_SIDED_FIELDS.put("actualAmount",
                "实收款（人工收银场景）：**只有 Java 侧**有 —— B 端店员线下收款时录入，与 discountAmount"
                        + " 一起参与『应收-优惠≈实收』校验（OrderService.createOrder）；ai-agent 工具不采集"
                        + "实收款，故工具 schema 无此键；服务端对 agent 路径恒按 totalAmount 记账");
        REGISTERED_SINGLE_SIDED_FIELDS.put("discountAmount",
                "优惠金额：**只有 Java 侧**有，同 actualAmount 的单侧性（人工议价/折扣录入）；"
                        + "agent 工具不传它 —— agent 路径的议价走后台改价口径（#4037 F22），"
                        + "故服务端无从校验该字段，工具 schema 也无此键");
        REGISTERED_SINGLE_SIDED_FIELDS.put("userId",
                "下单用户 ID：**只有 Java 侧**有（C 端数据隔离绑定真实用户）；ai-agent 工具不传它 —— "
                        + "服务端由 ServiceTokenFilter 从请求头 X-User-Id 透传并**覆盖**客户端传值，"
                        + "故它在 agent 的 wire 上是死字段（登记见 issue #4089 清单 §2）");
        REGISTERED_SINGLE_SIDED_FIELDS.put("sms_code",
                "短信验证码：**只有 ai-agent 工具侧**有这道闸（customer 角色下单前必须过 SMS，"
                        + "见 order_create._verify_sms_code）；服务端 DTO 没有这个概念，"
                        + "故它是「客户端严格、服务端无此闸」的形态 —— 要么产品裁定下沉到服务端"
                        + "（改 OrderCreateRequest + 下单流程），要么维持单侧；本单只登记，"
                        + "不擅自给服务端加一道工具侧已在做的闸（那是第二套定义）");
    }

    /**
     * issue #4089 清单里**刻意不收敛**的跨语言差异（D8~D12），键 = 矩阵行 code（逐字一致）。
     *
     * <p>为什么不收敛：这几处的"更严"一侧在 **Python 工具/技能层**（LLM 契约的提示性约束 +
     * 本地 fail-closed 校验），而服务端要么**不消费**该字段、要么**已归一化**、要么压根不做该
     * 交叉校验 —— 收敛它们要么给服务端加一套只对 Python 生效的注解（= 新的第二套定义，
     * 正是本单要消灭的形态），要么放宽 Python 侧（= 降低唯一生产者的安检强度）。
     * 两者都被 issue 裁定排除，故**逐条登记 + 原子复核**（见 {@code pythonAcceptsAtomic}）。</p>
     */
    private static final Map<String, String> REGISTERED_DIVERGENCES = new LinkedHashMap<>();
    static {
        REGISTERED_DIVERGENCES.put("D8 sellingMethod 枚举",
                "Java：DTO 零约束；库存路径 SkuNotation.normalizeSellingMethod 归一化中文标签/变体"
                        + "（#3621） → Python 更严：enum[bulk_cut,full_roll] 且本地拒绝变体"
                        + " → 依据：收敛需**放宽 Python**（降唯一生产者安检）或给服务端加一套只对"
                        + " Python 生效的注解（= 新的第二套定义），两者都被 issue 裁定排除");
        REGISTERED_DIVERGENCES.put("D9 pricingMethod 枚举",
                "Java：extractProcessingItems 只取 id/name/unitPrice/quantity，pricingMethod 完全不读"
                        + " → Python 更严：enum[per_meter,per_set,fixed,per_area] + 本地拒绝"
                        + " → 依据：给服务端加一个**从不读**的字段的约束 = 凭空发明校验，"
                        + "且日后有人读它时注解会与算法脱节");
        REGISTERED_DIVERGENCES.put("D10 processingInfo 容器结构",
                "Java：Object 零结构约束（且兼容 JSON 字符串形态）"
                        + " → Python：完整嵌套 schema → 依据：服务端只把 processingInfo 透传落库，"
                        + "同一条内容在服务端没有算法消费其结构；把嵌套 schema 复制成 Java 注解="
                        + "第二套定义（正是本单要消灭的形态）");
        REGISTERED_DIVERGENCES.put("D11 processingItems[] 多出的键",
                "Java：消费 id/name/unitPrice/quantity；Python 声明 7 键（多 unit/pricingMethod/subtotal）"
                        + " → 依据：多余键被服务端忽略（无害且向前兼容）；删它们=降低工具侧可读性，"
                        + "加它们=服务端凭空约束（同 D9）");
        REGISTERED_DIVERGENCES.put("D12 processingFee=Σ明细 自洽",
                "Java：sumProcessingFee 只按 processingItems 求和，processingFee 字段不参与"
                        + " → Python：工具描述要求自洽、代码不校验 → 依据：这是 issue 清单里的"
                        + "**独立缺陷**（服务端金额算法口径），修它要动 OrderService 的金额路径"
                        + "与工具层，超出『DTO 收敛』本单；#4089 已把它列为待办（D12 优先项）");
    }

    // ─────────────────────────────────────────────────────────────────────
    // ④ 未收敛项：登记必须完整（13 = 收敛 + 登记），且登记不是空话
    // ─────────────────────────────────────────────────────────────────────

    @Nested
    @DisplayName("④ 未收敛项：登记必被断言，不得静默消失")
    class RegisteredDivergences {

        @Test
        @DisplayName("清单里的 13 处必须逐条有处置：收敛进单一 DTO 或在此登记")
        void everyDivergenceIsAccountedFor() {
            List<String> accounted = divergenceRows().map(a -> (String) a.get()[0]).toList();
            assertThat(accounted)
                    .as("13 行矩阵必须齐（D1~D13），漏一行 = 有一处分歧没人管")
                    .hasSize(13)
                    .contains("D1 skuCode 位置", "D13 规格键族不相交");

            List<String> registered = divergenceRows()
                    .filter(a -> a.get()[3] != null)
                    .map(a -> (String) a.get()[0]).toList();
            assertThat(registered)
                    .as("未收敛集合必须与 REGISTERED_DIVERGENCES 逐条对齐（不许只在矩阵里说「已登记」）")
                    .containsExactlyInAnyOrderElementsOf(REGISTERED_DIVERGENCES.keySet());
        }

        @Test
        @DisplayName("登记不是空话：逐条用 Python 侧事实原子复核")
        void pythonAcceptsAtomic() {
            // D8：中文变体「散剪」被 Python 侧拒绝（服务端反而归一化）—— 证明"更严的一侧在 Python"
            assertThat(pythonEnumAccepts("sellingMethod", "散剪"))
                    .as("D8 复核：若 Python 侧开始接受变体，则『Python 更严』这条登记失效 → 本行红")
                    .isFalse();
            assertThat(pythonEnumAccepts("sellingMethod", "bulk_cut")).isTrue();
            // D9：pricingMethod 白名单存在且 per_piece 不在其中（服务端完全不读该键）
            assertThat(pythonEnumAccepts("pricingMethod", "per_piece")).isFalse();
            assertThat(pythonEnumAccepts("pricingMethod", "per_meter")).isTrue();
        }

        @Test
        @DisplayName("D6 复核：收敛后 Java 侧确实有了 min 0（Python 侧事实不再单侧存在）")
        void d6TightenedOnJavaSide() {
            assertThat(constraint(OrderCreateRequest.OrderItemRequest.class, "width", "DecimalMin"))
                    .as("D6 已收敛：服务端不得再裸 BigDecimal（负尺寸会进面积/单价数学）")
                    .isNotNull();
            assertThat(constraint(OrderCreateRequest.OrderItemRequest.class, "height", "DecimalMin")).isNotNull();
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // ⑤ 校验双写消除：同一 payload 跑同一个 Validator，两侧结论必须一致
    // ─────────────────────────────────────────────────────────────────────

    /**
     * 「校验双写」的机器判据：同一份**不合法** payload，人工路径 DTO 与 agent 路径 DTO
     * 必须由 Bean Validation 给出**同一组属性 + 同一条文案**。
     *
     * <p>红证（收敛前）：同一份 payload 在 agent 侧**一条约束都没有**（{@code items} 无
     * {@code @NotEmpty}、{@code AgentOrderItem} 字段零注解）⇒ agent 侧集合为空、人工侧有
     * ⇒ 本组红，而 Service 层必须另写一遍逐字段判定才拦得住（= 双写）。</p>
     */
    @Nested
    @DisplayName("⑤ 校验双写消除：两侧不合法的输入给出同一组字段 + 同一条文案")
    class ValidationSingleSourced {

        @Test
        @DisplayName("items 为空：人工路径 @NotEmpty 拦住 ⇒ agent 路径必须同一条文案（不许只有 service 拦）")
        void emptyItemsRejectedBySharedType() {
            OrderCreateRequest form = new OrderCreateRequest();
            form.setCustomerName("张三");
            form.setCustomerPhone("13800138000");
            form.setItems(List.of());

            AgentOrderCreateRequest agent = new AgentOrderCreateRequest();
            agent.setCustomerName("张三");
            agent.setCustomerPhone("13800138000");
            agent.setItems(List.of());

            assertSameViolations(form, agent, "items", MSG_ITEMS_EMPTY);
        }

        @Test
        @DisplayName("单价为负：两侧同一条「单价必须大于 0」")
        void negativeUnitPriceRejectedBySharedType() {
            assertSameViolations(
                    formRequest(new BigDecimal("3"), new BigDecimal("-168")),
                    agentRequest(new BigDecimal("3"), new BigDecimal("-168")),
                    "items[0].unitPrice", MSG_PRICE_POSITIVE);
        }

        @Test
        @DisplayName("手机号非法：两侧同一条「手机号格式不正确…」（V1 正则只有一处）")
        void invalidPhoneRejectedBySharedType() {
            OrderCreateRequest form = new OrderCreateRequest();
            form.setCustomerName("张三");
            form.setCustomerPhone("12345");
            form.setItems(List.of());
            AgentOrderCreateRequest agent = new AgentOrderCreateRequest();
            agent.setCustomerName("张三");
            agent.setCustomerPhone("12345");
            agent.setItems(List.of());

            Set<String> formPhone = messagesOf(VALIDATOR.validate(form), "customerPhone");
            assertThat(formPhone)
                    .as("人工路径 DTO 的注解必须真的执行")
                    .containsExactly(MSG_PHONE_PATTERN);
            assertThat(messagesOf(VALIDATOR.validate(agent), "customerPhone"))
                    .as("agent 路径 DTO 必须给出**同一组**结论（同一类型 ⇒ 同一来源）")
                    .isEqualTo(formPhone);
        }

        @Test
        @DisplayName("缺 subtotal：两侧同一条「小计不能为空」（D3 收敛后的可判定后果）")
        void missingSubtotalRejectedOnBothPaths() {
            OrderCreateRequest form = new OrderCreateRequest();
            form.setCustomerName("张三");
            form.setCustomerPhone("13800138000");
            form.setItems(List.of(item(new BigDecimal("3"), new BigDecimal("168"), null)));

            AgentOrderCreateRequest agent = new AgentOrderCreateRequest();
            agent.setCustomerName("张三");
            agent.setCustomerPhone("13800138000");
            agent.setItems(List.of(item(new BigDecimal("3"), new BigDecimal("168"), null)));

            assertSameViolations(form, agent, "items[0].subtotal", MSG_SUBTOTAL_NULL);
        }

        @Test
        @DisplayName("R2 负例 · wire 形态：ai-agent 工具实际发出的 payload（浮点 number）反序列化后零违规")
        void legalWirePayloadFromToolDeserializesAndValidates() throws IOException {
            // 形态取自 order_create.execute 的实际构造：全 camelCase + 数值是 JSON number
            // （Python float，如 504.0）—— 若 Jackson 因小数形态构造不出 BigDecimal、
            // 或共享类型的约束把工具的真实 payload 挡掉，本用例立刻红。
            String wire = """
                    {
                      "customerName": "张三",
                      "customerPhone": "13800138000",
                      "customerAddress": "上海市浦东新区 xx 路 1 号",
                      "remark": "周末送",
                      "items": [
                        {"productName": "遮光窗帘", "productId": "11111111-2222-3333-4444-555555555555",
                         "quantity": 3.0, "unitPrice": 168.0, "subtotal": 504.0,
                         "width": 2.8, "height": 3.0,
                         "processingInfo": {"colorName": "米白", "sellingMethod": "bulk_cut",
                           "doorWidth": "2.8米", "processingFee": 24.0,
                           "processingItems": [{"id": "p1", "name": "打孔", "unitPrice": 8.0,
                                                "quantity": 3.0, "pricingMethod": "per_set"}]}}
                      ]
                    }
                    """;
            AgentOrderCreateRequest parsed = JSON.readValue(wire, AgentOrderCreateRequest.class);

            assertThat(parsed.getItems().get(0).getSubtotal())
                    .as("JSON 小数 504.0 必须落成 BigDecimal（不是拒绝 / 不是精度异常）")
                    .isEqualByComparingTo(new BigDecimal("504"));
            assertThat(VALIDATOR.validate(parsed))
                    .as("工具真实 payload 必须零违规（收敛不得把唯一生产者挡在门外）")
                    .isEmpty();
        }

        @Test
        @DisplayName("R2 负例：合法 agent payload（含 P15 幂等键字段）零违规 —— 不许把合法输入拦掉")
        void legalAgentPayloadHasNoViolations() {
            AgentOrderCreateRequest legal = new AgentOrderCreateRequest();
            legal.setCustomerName("张三");
            legal.setCustomerPhone("13800138000");
            legal.setCustomerAddress("杭州市余杭区 xx 路 1 号");
            legal.setRemark("客户要求周末送");
            legal.setClientRequestId("req-key-p15");
            OrderCreateRequest.OrderItemRequest item = item(new BigDecimal("3"), new BigDecimal("168"),
                    new BigDecimal("504"));
            item.setProductId("11111111-2222-3333-4444-555555555555");
            item.setWidth(new BigDecimal("2.8"));
            item.setHeight(new BigDecimal("3"));
            item.setProcessingInfo(Map.of("sellingMethod", "bulk_cut", "doorWidth", "2.8米",
                    "colorName", "米白", "processingFee", new BigDecimal("24"),
                    "processingItems", List.of(Map.of("id", "p1", "name", "打孔", "unitPrice",
                            new BigDecimal("8"), "quantity", new BigDecimal("3")))));
            legal.setItems(List.of(item));

            assertThat(VALIDATOR.validate(legal))
                    .as("合法 agent 下单 payload 必须零违规（收敛不得把正常输入挡在门外）")
                    .isEmpty();
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // 辅助
    // ─────────────────────────────────────────────────────────────────────

    /** 明细构造（类型 = 共享明细类型；红拷贝里会被替换成旧的第二套类型） */
    private static OrderCreateRequest.OrderItemRequest item(BigDecimal quantity, BigDecimal unitPrice,
                                                           BigDecimal subtotal) {
        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setProductName("遮光窗帘");
        item.setQuantity(quantity);
        item.setUnitPrice(unitPrice);
        item.setSubtotal(subtotal);
        return item;
    }

    private static OrderCreateRequest formRequest(BigDecimal quantity, BigDecimal unitPrice) {
        OrderCreateRequest req = new OrderCreateRequest();
        req.setCustomerName("张三");
        req.setCustomerPhone("13800138000");
        req.setItems(List.of(item(quantity, unitPrice, new BigDecimal("504"))));
        return req;
    }

    private static AgentOrderCreateRequest agentRequest(BigDecimal quantity, BigDecimal unitPrice) {
        AgentOrderCreateRequest req = new AgentOrderCreateRequest();
        req.setCustomerName("张三");
        req.setCustomerPhone("13800138000");
        req.setItems(List.of(item(quantity, unitPrice, new BigDecimal("504"))));
        return req;
    }

    /** 两条路径的违规集合必须逐字相等（属性路径 + 文案都相等 = 单一来源） */
    private static void assertSameViolations(OrderCreateRequest form, AgentOrderCreateRequest agent,
                                             String expectedProperty, String expectedMessage) {
        Map<String, Set<String>> formViolations = violationMap(VALIDATOR.validate(form));
        Map<String, Set<String>> agentViolations = violationMap(VALIDATOR.validate(agent));

        assertThat(formViolations)
                .as("人工路径必须由 Bean Validation 拦住（这是唯一来源）")
                .containsEntry(expectedProperty, Set.of(expectedMessage));
        assertThat(agentViolations)
                .as("agent 路径必须给出**同一组**违规（收敛前：手工 new 使注解失效 ⇒ 这里为空，"
                        + "Service 只好再写一遍逐字段判定 = 校验双写）")
                .isEqualTo(formViolations);
    }

    /**
     * 已登记的分歧必须能机械复算：两侧集合的对称差 = 登记集合（不是「我看了代码觉得没事」）。
     *
     * @param registered    已登记的单侧字段（Python 键名）；只在 {@code javaWireFields} 里出现
     *                      且同名登记项（camelCase ↔ snake_case 已映射）也视作已登记
     * @param javaWireFields Java 侧实际字段名集合（用于把登记项映射回 Python 键名）
     */
    private static void assertDivergenceFree(String label, Set<String> py, Set<String> java,
                                            Set<String> registered, Set<String> javaWireFields) {
        Set<String> registeredAsJava = registered.stream()
                .filter(javaWireFields::contains)
                .collect(Collectors.toCollection(LinkedHashSet::new));

        Set<String> onlyPy = new TreeSet<>(py);
        onlyPy.removeAll(java);
        onlyPy.removeAll(registered);

        Set<String> onlyJava = new TreeSet<>(java);
        onlyJava.removeAll(py);
        onlyJava.removeAll(registeredAsJava);

        assertThat(onlyPy)
                .as("%s：只存在于 ai-agent 工具 schema 的字段（服务端会静默丢弃它们）", label)
                .isEmpty();
        assertThat(onlyJava)
                .as("%s：只存在于 Java DTO 的字段（声明了但唯一生产者不填的死字段）", label)
                .isEmpty();
    }

    private static Set<String> declaredFieldNames(Class<?> type) {
        return Arrays.stream(type.getDeclaredFields())
                .filter(f -> !f.isSynthetic())
                .map(Field::getName)
                .collect(Collectors.toCollection(LinkedHashSet::new));
    }

    /** 方法返回类型的泛型全名（用于断言 getItems 的返回类型 = 共享明细类型） */
    private static String returnTypeName(Class<?> type, String methodName) {
        for (java.lang.reflect.Method m : type.getMethods()) {
            if (m.getName().equals(methodName) && m.getParameterCount() == 0) {
                return m.getGenericReturnType().getTypeName();
            }
        }
        throw new AssertionError(type.getSimpleName() + " 找不到方法 " + methodName + "()");
    }

    private static Set<String> allFieldNames(Class<?> type) {
        Set<String> names = new LinkedHashSet<>();
        for (Class<?> c = type; c != null && c != Object.class; c = c.getSuperclass()) {
            names.addAll(declaredFieldNames(c));
        }
        return names;
    }

    private static Field field(Class<?> type, String name) {
        for (Class<?> c = type; c != null && c != Object.class; c = c.getSuperclass()) {
            for (Field f : c.getDeclaredFields()) {
                if (f.getName().equals(name)) {
                    return f;
                }
            }
        }
        return null;
    }

    private static Annotation constraint(Class<?> type, String fieldName, String annotationSimpleName) {
        Field f = field(type, fieldName);
        if (f == null) {
            return null;
        }
        return Arrays.stream(f.getAnnotations())
                .filter(a -> a.annotationType().getSimpleName().equals(annotationSimpleName))
                .findFirst().orElse(null);
    }

    private static String constraintValue(Class<?> type, String fieldName,
                                          String annotationSimpleName, String attribute) {
        Annotation a = constraint(type, fieldName, annotationSimpleName);
        assertThat(a).as("@%s 必须存在于 %s.%s 上", annotationSimpleName, type.getSimpleName(), fieldName)
                .isNotNull();
        try {
            Object v = a.annotationType().getMethod(attribute).invoke(a);
            return String.valueOf(v);
        } catch (ReflectiveOperationException e) {
            throw new AssertionError("读取注解属性失败: " + annotationSimpleName + "." + attribute, e);
        }
    }

    private static Map<String, Set<String>> violationMap(Set<? extends ConstraintViolation<?>> violations) {
        Map<String, Set<String>> map = new LinkedHashMap<>();
        violations.stream()
                .sorted((a, b) -> a.getPropertyPath().toString().compareTo(b.getPropertyPath().toString()))
                .forEach(v -> map.computeIfAbsent(v.getPropertyPath().toString(),
                        k -> new TreeSet<>()).add(v.getMessage()));
        return map;
    }

    private static Set<String> messagesOf(Set<? extends ConstraintViolation<?>> violations, String prefix) {
        return violations.stream()
                .filter(v -> v.getPropertyPath().toString().startsWith(prefix))
                .map(ConstraintViolation::getMessage)
                .collect(Collectors.toCollection(TreeSet::new));
    }

    // ── Python schema 解析（源码级，读不到即红）────────────────────────────

    /** {@code order_create.py} 的 {@code parameters} 顶层 properties 的键集合 */
    private static Set<String> pythonTopLevelKeys() throws IOException {
        return keysOf(pythonSchema().path("properties"));
    }

    private static Set<String> pythonItemKeys() throws IOException {
        return keysOf(pythonItemSchema().path("properties"));
    }

    private static JsonNode pythonItemSchema() throws IOException {
        return pythonSchema().path("properties").path("items").path("items");
    }

    private static Set<String> keysOf(JsonNode node) {
        Set<String> keys = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(keys::add);
        return keys;
    }

    /**
     * 从 {@code order_create.py} 里取出工具 schema（与运行时**同一份源码**，不做手工转换）。
     *
     * <p>取法与失败语义：把源码交给 **CPython 自己的解析器**（{@code ast.parse}），
     * 定位 {@code class ...:} 作用域里的 {@code parameters = {...}} 字面量，再用
     * {@code ast.literal_eval} 求值后转 JSON。这样 schema 里的注释、隐式字符串拼接
     * （{@code "a" "b"}）、括号包裹的拼接表达式、尾随逗号**全部由语言本身处理** ——
     * 手写转换器在这几种形态上实测反复出错（会把 `"a"\n"b"` 误判成拼接、把字符串里的
     * `#` 当注释），而"判据工具自己不可靠"比没有判据更糟。</p>
     *
     * <p>Python 不可用 / 解析失败 ⇒ **断言红**（判据不得静默空跑）。</p>
     */
    private static JsonNode pythonSchema() throws IOException {
        assertThat(Files.exists(ORDER_CREATE_PY))
                .as("找不到 ai-agent 工具 schema：%s（工作目录须为 backend/admin-api）", ORDER_CREATE_PY)
                .isTrue();

        Path script = Files.createTempFile("order-dto-schema", ".py");
        Files.writeString(script, PY_EXTRACT_SCHEMA, StandardCharsets.UTF_8);
        try {
            Process process = new ProcessBuilder(pythonExecutable(), script.toString(),
                    ORDER_CREATE_PY.toString())
                    .redirectErrorStream(true).start();
            String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            boolean finished = process.waitFor(120, java.util.concurrent.TimeUnit.SECONDS);
            int exit = finished ? process.exitValue() : -1;
            assertThat(exit)
                    .as("用 CPython 的 ast 解析 order_create.py 的 parameters 失败（exit=%s）：%s", exit, output)
                    .isZero();

            JsonNode node = JSON.readTree(output);
            assertThat(node.path("properties").isObject())
                    .as("解析出的 schema 缺 properties —— schema 结构变了（不要静默降级为通过）")
                    .isTrue();
            return node;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssertionError("解析 Python schema 被中断", e);
        } finally {
            Files.deleteIfExists(script);
        }
    }

    /** 优先用仓库 venv 的 python3（与 ai-agent 运行时同解释器），退回系统 python3 */
    private static String pythonExecutable() {
        Path venv = Paths.get("..", "..", "backend", "ai-agent-service", ".venv", "bin", "python3")
                .toAbsolutePath().normalize();
        return Files.isExecutable(venv) ? venv.toString() : "python3";
    }

    /**
     * 抽 schema 的 CPython 脚本：用 {@code ast} 解析源码（语言自带的解析器），
     * 取模块级 class 里的 {@code parameters} 字面量后 {@code literal_eval} → JSON。
     */
    private static final String PY_EXTRACT_SCHEMA = String.join("\n",
            "import ast, json, sys",
            "tree = ast.parse(open(sys.argv[1], encoding='utf-8').read())",
            "value = None",
            "for node in ast.walk(tree):",
            "    if isinstance(node, ast.Assign):",
            "        for t in node.targets:",
            "            if isinstance(t, ast.Name) and t.id == 'parameters':",
            "                value = ast.literal_eval(node.value)",
            "if value is None:",
            "    raise SystemExit('order_create.py 里找不到 parameters 赋值')",
            "print(json.dumps(value, ensure_ascii=False))");

    /** 用 Python 3 复算某个 enum 约束是否接受给定取值（登记项 D8/D9 的原子复核） */
    private static boolean pythonEnumAccepts(String container, String value) {
        try {
            JsonNode props = pythonSchema().path("properties").path("items").path("items")
                    .path("properties").path("processing_info").path("properties");
            JsonNode enumNode = container.equals("pricingMethod")
                    ? props.path("processingItems").path("items").path("properties").path(container)
                    : props.path(container);
            assertThat(enumNode.path("enum").isArray())
                    .as("Python schema 里 %s 必须仍是 enum（否则 D8/D9 登记口径需更新）", container)
                    .isTrue();
            for (JsonNode n : enumNode.path("enum")) {
                if (n.asText().equals(value)) {
                    return true;
                }
            }
            return false;
        } catch (IOException e) {
            throw new AssertionError("复核 Python enum 失败", e);
        }
    }
}