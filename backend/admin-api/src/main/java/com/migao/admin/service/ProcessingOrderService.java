package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 加工单服务（issue #3340，设计文档 docs/design/processing-order-design.md）
 *
 * 核心职责：
 * 1. 生成加工单（快照固化五要素 + options，不含销售价），**不**联动订单状态；
 * 2. 加工单状态机（generated→issued→in_processing→completed | cancelled），非法迁移拒绝；
 * 3. 发加工（issue）联动订单 confirmed→producing（**唯一时点**，issue #4305：用户裁定
 *    「发加工 = 订单进入生产中」，时点从「生成加工单」挪到「发加工」）；
 * 4. 取消联动（issued 及之后取消 → 订单 producing→confirmed 回退；generated 取消时订单
 *    本就 confirmed ⇒ 回退自然不触发）；
 * 5. 订单侧联动（shipped 守卫 / 订单取消自动作废）由 OrderService 完成。
 *
 * <h2>工序来源（issue #4116 用户裁定「现在就切」；P2b / issue #4459 切到新结构）</h2>
 * 生成加工单时的工序实例化读**工序库的新结构**：
 * {@code production_route_templates}（具名主线）+ {@code production_route_rules}（工艺/选项触发的
 * 增删与计件系数）+ {@code production_operation_positions}（部位价目与适用性）
 * + {@code production_operations}（分组/单位/必完标记/作用域），经
 * {@link ProductionOperationQueryService} 的新读面读出。
 * 加工项目录（快照的 {@code processingItems}）**不再是**工序真值源。
 * 取不到路线模板/工序 ⇒ fail-closed 中止生成（{@link #ERR_ROUTING_NOT_FOUND} /
 * {@link #ERR_OPERATION_NOT_FOUND} + {@link #INCIDENT_ROUTING_UNRESOLVED} 日志），**不回退**旧路径。
 *
 * <h2>部位语义（issue #4354 起：显式字段优先，派生是**长期兜底**）</h2>
 * {@code processing_position_operations.position_name} 取「加工产物名[+色号]」（如「布艺遮光帘A 米白」），
 * 而工序库的路线是**按部位**索引的（布帘/纱帘/帘头）⇒ 部位必须单独取。
 * <p><b>一行 {@code order_items} = 一个部位（帘件）</b>（用户裁定 2026-09-19，issue #4387）：
 * 布 + 纱 = **两条明细行**，各成一个部位，靠 {@code craftLineId} 绑成**同一樘窗**（一个窗户）——
 * 樘窗是套级工序（#4384）与加工费樘窗级（#4386）的归属层级；配布边仍不独立成部位。</p>
 * 取法 = {@link #deriveRouteKey} 的三层链（issue #4452 起，第 2 层从「{@code contains} 猜文本」
 * 换成**受控来源**）：
 * <b>显式字段</b>（issue #4362 起 = {@code order_items} 的 craft spec **列**；issue #4354 起
 * {@code processing_info} 顶层同键是旧载体）&gt; <b>受控来源</b>（部位 ← {@code componentRole}
 * 受控枚举；工艺 ← 加工项显式声明 {@code processing_items.craft_hint}）&gt;
 * <b>存量单信号兜底</b>（{@link ProductionOperationQueryService#routeSignals}，**只在两维都缺时**
 * 才被读，且信号源只剩加工项名/options —— 商品名与销售方式已从判据里摘掉），
 * 三层的命中情况落 {@code processing_orders.route_source}（四/五态可观测）。
 * <p>⚠️ <b>存量兜底路径**不退场**</b>（用户裁定 2026-09-19「部位不是必填的」）：craft spec 列
 * **全部可空**、不设必填校验 ⇒ 存量的「没填部位/工艺的单」永远存在，信号映射表是它们的
 * **兜底面**（表**不删**）。但新单只要给出任一维（列值 / {@code componentRole} / {@code craft_hint}）
 * ⇒ **全程不读**该表。代码注释里旧表述「待订单侧补字段后连同信号表一起退场」**已作废**，
 * 不得再按它写回；同样作废的还有「加工项名/options/商品名/销售方式四段信号链」
 * 与「加工项比商品名权威」这条相对次序判据（商品名不再参与）。</p>
 * <p>⚠️ 部位名与路线键仍**不是**同一个语义层（前者是展示名、后者是索引键），
 * 不得把前者当成后者的真值。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingOrderService {

    private final ProcessingOrderMapper processingOrderMapper;
    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProcessingItemMapper processingItemMapper;
    private final OrderService orderService;
    private final ObjectMapper objectMapper;
    private final ProductionService productionService;
    /** 工序来源（issue #4116 切库）：工序实例的工序/单位/单价/必完标记全部读它。 */
    private final ProductionOperationQueryService productionOperationQueryService;
    /** 应做数量来源（issue #4208 接线）：算料引擎在 ai-agent，Java 侧只问不猜。 */
    private final ProductionOperationQtyClient productionOperationQtyClient;

    /**
     * 工序库查不到「部位×工艺」路线时的错误码（fail-closed）。
     * 可见位置：① 生成加工单的响应 `GenerateResult.message`（`success=false` 的原文）；
     * ② 服务层日志 `INCIDENT_PRODUCTION_ROUTING_UNRESOLVED`（incident 级，按此串检索）。
     */
    public static final String ERR_ROUTING_NOT_FOUND = "PRODUCTION_ROUTING_NOT_FOUND";

    /**
     * 路线引用的工序在工序库无活跃行时的错误码（fail-closed）。
     * 可见位置同 {@link #ERR_ROUTING_NOT_FOUND}。
     */
    public static final String ERR_OPERATION_NOT_FOUND = "PRODUCTION_OPERATION_NOT_FOUND";

    /** 切库失败的 incident 日志标记：`grep INCIDENT_PRODUCTION_ROUTING_UNRESOLVED` 即可捞全部中止事件。 */
    public static final String INCIDENT_ROUTING_UNRESOLVED = "INCIDENT_PRODUCTION_ROUTING_UNRESOLVED";

    /**
     * **T1**（信号全不命中 ⇒ 直接取默认路线键）的 incident 日志标记（V60，issue #4308）。
     * 这是最隐蔽的一层：迁移前**连 info 都没有** —— 罗马帘订单今天就走这条，且成功路径零痕迹。
     * `grep INCIDENT_PRODUCTION_ROUTE_DEFAULTED` 即可捞出全部「没人派生过」的加工单。
     */
    public static final String INCIDENT_ROUTE_DEFAULTED = "INCIDENT_PRODUCTION_ROUTE_DEFAULTED";

    /**
     * **T2**（派生键命中但工序库无该路线 ⇒ 回落默认路线）的 incident 日志标记（V60，issue #4308）。
     * 迁移前只 `log.info("…回落默认路线…")`，用户侧不可见；现在同时落
     * {@code processing_orders.route_source='missing_route'}（+ {@code route_requested_key}
     * = 派生出来却取不到路线的那个键），可从加工单详情 API 查出。
     */
    public static final String INCIDENT_ROUTE_FALLBACK = "INCIDENT_PRODUCTION_ROUTE_FALLBACK";

    /**
     * 默认**部位**（派生不出部位时的兜底）与默认**工艺**的**种子回填来源与文案措辞**。
     *
     * <p><b>⚠️ P2b（issue #4459 §1②）：二者已**退化为种子回填来源与文案措辞**，
     * 运行时**不再**作为回落目标</b>：</p>
     * <ul>
     *   <li>{@link #DEFAULT_CURTAIN_TYPE} —— 部位维仍用它兜底（部位没有「商户级默认」表，
     *       且它只决定「去取哪条路线模板」，取不到就 T2/T3，不改变工序内容）；</li>
     *   <li>{@link #DEFAULT_CRAFT} —— **运行时不再取它**：缺 {@code craft} 取该租户
     *       {@code production_crafts.is_default} 的默认工艺（商家可配）；查不到 ⇒ T3 fail-closed。
     *       常量保留给 ① V72 种子回填的取值口径 ② 缺口查询的文案措辞。</li>
     * </ul>
     *
     * <p>{@code public}（issue #4308）：缺口查询（{@code GET /production/routing-gaps}）要用
     * 同一对默认值算「某个信号单独命中时**会**派生出哪个键」—— 复制第二份默认值必然漂移。</p>
     */
    public static final String DEFAULT_CURTAIN_TYPE = "布帘";
    public static final String DEFAULT_CRAFT = "韩褶";

    /**
     * 售卖形态 → **布料基础路线**（issue #4529，包 F；用户裁定 2026-09-19）。
     *
     * <p>{@code processing_info.saleForm === '布料'}（前端 {@code SALE_FORM_FABRIC}，issue #4493
     * 起落库）⇒ 该行走**布料路线**：部位维 = {@link #FABRIC_POSITION}（第 4 个部位），
     * 主线 = {@code 配料 → 打包}（2 道）。</p>
     *
     * <p>⚠️ <b>缺键的存量单不得改变既有行为</b>（回归不变量）：判据是**逐字相等**的
     * {@code "布料"}，缺键 / 其它取值（含 {@code 成品帘}）一律走原派生链。</p>
     */
    public static final String SALE_FORM_FABRIC = "布料";
    /** 第 4 个部位（布料单专用）—— 与 {@code routing.py::FABRIC_POSITION} 逐字同源。 */
    public static final String FABRIC_POSITION = "布料";

    /**
     * 部位（帘种）与工艺的**派生来源**（V60，issue #4308）：租户级库表
     * {@code production_route_signals}，读面 = {@link ProductionOperationQueryService#routeSignals}。
     *
     * <p><b>为什么不再留常量表</b>：迁移前这里是两个 {@code String[][]} 常量
     * （{@code CURTAIN_TYPE_KEYWORDS} / {@code CRAFT_KEYWORDS}），而**加工项目录是商家可自定义的**
     * （POC 已建过「POC-加工工艺」这类名字）⇒ 商家每加一个自定义加工项，派生就多一分静默错配，
     * 改常量还要走研发发版。落库后商家可增删改（写面 =
     * {@code POST/PUT/DELETE /api/admin/production/route-signals}）。</p>
     *
     * <p><b>常量与库**不得并存**</b>：两份口径必然漂移，且漂移的那一份不会变红。
     * 种子（= 迁移前的常量表逐条）由 V60 迁移落库，逐条等价性由
     * {@code ProductionRouteSignalMigrationTest} 钉住。</p>
     */

    /**
     * 算料输入的透传白名单（键名与 ai-agent {@code routing.py} 的
     * {@code METER_KEYS/FOLD_KEYS/HOLE_KEYS/PANEL_KEYS/SET_KEYS} 同口径）：
     * 订单侧若已存算料输出就原样送过去，Java 侧**不发明数字**（见 {@link #calcInfo}）。
     *
     * <p>{@code per_panel_pleats} / {@code fullness} / {@code fullness_actual} 为 issue #4354 新增
     * （设计文档 §4.3）：它们是**展示/复核**用键（每片折数、理论/实际褶倍），算料端点按
     * {@code calc_info} 的自由字典读，多传不改变取值口径。</p>
     */
    private static final List<String> CALC_INFO_KEYS = List.of(
            "fabric_meters", "meters", "pleat_count", "holes", "panels", "set_count", "source",
            "per_panel_pleats", "fullness", "fullness_actual");

    /**
     * 加工单快照要固化的**算料输出**键（issue #4354，设计文档 §4.9）：订单侧下单时已落库的算料输出
     * 原样进快照 —— 加工单的固化真相里没有它，车间就少一个数（§4.3 的「生产为零」根因）。
     * 逐键 {@code copyIfPresent}：**缺键就缺**，Java 不造值。
     *
     * <p>{@code formula_text} = 可读**算料公式串**（issue #4555，用户 2026-09-19 裁定
     * 「算料公式要展示出来可以明确告知用料是如何计算出来的」+「C 端也要能看到」）：
     * 订单详情与 C 端报价卡已渲染（#4546），车间/任务卡纸面
     * （{@code ProcessingOrderBlock} / {@code TaskCardPrint}）此前**看不到** —— 缺的就是本键。
     * 串由 ai-agent 算料引擎产出、下单时原样落 {@code processing_info}，Java **只透传**、不自拼。</p>
     */
    private static final List<String> CALC_OUTPUT_SNAPSHOT_KEYS = List.of(
            "fabric_meters", "pleat_count", "per_panel_pleats", "panels", "holes",
            "fullness", "fullness_actual", "formula_text");

    /**
     * 算料输出的**取值键名**别名（快照键族 = snake_case，订单层 {@code processing_info} 里个别键 = camelCase）：
     * 只在这里登记一次，**不另立第二份口径**。
     *
     * <p>issue #4555 读码实测（**以代码事实为准**）：{@code copyIfPresent(from, to, key)} 的**取值键与落键键同名**，
     * 而算料公式串下单时落的是 camelCase {@code processing_info.formulaText}
     * （{@code orders/new/page.tsx} 把试算响应的 {@code formula_text} 原样搬进该键）；
     * 快照键族 / 响应 DTO（{@code @JsonProperty("formula_text")}）/ 三端展示映射
     * （{@code craft-display.ts} 同登记两个别名）都按 snake_case 读 ⇒ 两者**不同名**。
     * 若直接用键族名取值，会**恒取不到**（静默缺行，且没有任何东西会变红）。</p>
     */
    private static final Map<String, String> CALC_OUTPUT_SOURCE_KEY_ALIASES = Map.of(
            "formula_text", "formulaText");

    /**
     * 加工单快照要固化的**工艺规格**键（issue #4354，设计文档 §4.2 / §4.8）：
     * {@code processing_info} 顶层扁平键，订单侧下单时原样落库。
     *
     * <p>⚠️ 新键不加进这里就**不会进快照**（{@link #buildSnapshot} 逐键取）⇒
     * 「车间少一道活 / 少一个展示字段」，而快照是加工单的固化真相，事后补不回来。</p>
     */
    private static final List<String> CRAFT_SPEC_SNAPSHOT_KEYS = List.of(
            "curtainType", "craft", "cuttingMode", "openCount", "isShaped", "pleatSpacing",
            "hasPattern", "patternRepeat", "style", "room", "batchNo",
            "componentRole", "craftLineId", "metersSource", "processingMeters",
            // 售卖形态（issue #4529）：`saleForm === '布料'` ⇒ 选**布料基础路线**（第 4 部位）。
            // 与「部位/工艺」同一载体（`processing_info` 顶层，订单侧下单时原样落库）——
            // 不进白名单 ⇒ 派生链读不到它 ⇒ 布料单永远落窗帘路线。
            "saleForm");

    /**
     * {@code isShaped=false} 时从实例里剔除的工序（issue #4354，设计文档 §4.7）。
     * 与真值源 {@code routing.py::build_routing} 的 {@code route = [op for op in route
     * if op not in ("定型-布", "复烫-布")]} **逐字同款**（且都在条件工序插入**之前**剔除
     * —— 否则以这两道为锚点的条件工序会因锚点消失而落到末尾，与 Python 的落位不一致）。
     *
     * <p><b>P2b（issue #4459）：值是**逻辑工序名**</b>（{@code 定型} / {@code 复烫}）——
     * 新结构的序列元素就是逻辑名（主线 + 规则都归一为逻辑名）。新模型给 {@code shaped} 预留了
     * 规则触发类型但**不种行**（母单冻结：26 条 = 工艺 10 + 选项 16），故本开关仍是代码侧接线，
     * 与 {@code routing.py::build_route_v2} 的现状一致。</p>
     */
    private static final List<String> UNSHAPED_REMOVED_OPERATIONS = List.of("定型", "复烫");

    /** 配布边（§4.8）：**不独立成加工部位**的部件角色 —— 组内出现主布行时它被合并进去。 */
    private static final String COMPONENT_ROLE_EDGE = "配布边";

    /**
     * **套级**工序的作用域取值（`production_operations.scope`，V67 / issue #4384 A1）。
     *
     * <p>套级 = **每樘窗一次**（真值源 §8：「外帘是加工单打印行部位，**不是**路线键」）⇒
     * 实例化时同一樘窗（{@code craftGroupKey} 组）只落一次，而不是像部位级那样每个部位各落一次。</p>
     *
     * <p>⚠️ 这是**词表值**（库列注释冻结的两态之一），不是工序名白名单 —— 判据一律读
     * {@link #buildRoute} 从工序库带出的 `scope`（逐字取库）；
     * 硬编码 `外帘打卷/装袋/发货` 会让商家在工序库把某道改成部位级后**不生效**（第二份口径）。</p>
     */
    private static final String SCOPE_SET = "set";

    /** 部位（`curtainType`）取值「布帘」—— 樘窗的**主布行**（套级工序的承载体，同写侧 #4395 的代表行口径）。 */
    private static final String CURTAIN_TYPE_CLOTH = "布帘";

    /** 部位（`curtainType`）取值「纱帘」—— 纱是**独立部位**（`componentRole=纱` 的行）。 */
    private static final String CURTAIN_TYPE_SHEER = "纱帘";

    /**
     * **部件角色 → 部位**（V78，issue #4452）：受控枚举
     * （`order_create.py` 的工具 schema 里就是 enum：主布 / 配布边 / 纱）⇒ 它是**结构化输入**，
     * 不是「名词解释」。
     *
     * <p><b>为什么改走它</b>：旧派生链去**商品名**里 `contains '纱'` 判部位 —— 营销文案不是结构化输入，
     * 而受控枚举已经在手边（{@code isAbsorbedEdgeRow} 早就用它判「纱 = 独立部位」）。</p>
     *
     * <p>{@code 配布边} ⇒ 布帘：它是**不独立成部位**的部件（组内出现主布行时被吸收，
     * 见 {@link #isAbsorbedEdgeRow}），只有在组内没有主布行时才自成部位 ⇒ 此时它是**主布位**。</p>
     *
     * <p>⚠️ 未知取值 ⇒ **不猜**（返回 null，让该维落到缺维处理），不得默认成布帘：
     * 枚举以后扩值（如「帘头」）时，旧代码静默按布帘算就是错配。</p>
     */
    private static final Map<String, String> COMPONENT_ROLE_POSITIONS = Map.of(
            "纱", CURTAIN_TYPE_SHEER,
            "主布", CURTAIN_TYPE_CLOTH,
            COMPONENT_ROLE_EDGE, CURTAIN_TYPE_CLOTH);

    /** 加工单状态机（与 OrderService.STATUS_TRANSITIONS 同模式） */    private static final Map<String, Set<String>> STATUS_TRANSITIONS = Map.of(
            "generated", Set.of("issued", "cancelled"),
            "issued", Set.of("in_processing", "cancelled"),
            "in_processing", Set.of("completed", "cancelled"),
            "completed", Set.of(),
            "cancelled", Set.of()
    );

    private static final Map<String, String> STATUS_LABELS = Map.of(
            "generated", "已生成",
            "issued", "已发加工",
            "in_processing", "加工中",
            "completed", "加工完成",
            "cancelled", "已取消"
    );

    /** 加工单号序号（JG-YYYYMMDD-XXXX） */
    private static final java.util.concurrent.atomic.AtomicInteger PO_SEQ =
            new java.util.concurrent.atomic.AtomicInteger(ThreadLocalRandom.current().nextInt(1000, 9999));

    private static final DateTimeFormatter PO_DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    // ============================================================ 生成

    /**
     * 批量生成加工单（全事务；单个失败不影响已成功项结果返回，但整体回滚）。
     * 返回逐单结果（success/processingOrderNo/message）。
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, Long tenantId, String operator) {
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        List<GenerateResult> results = new ArrayList<>();
        for (String rawId : orderIds) {
            try {
                results.add(generateOne(rawId, tenantId, operator));
            } catch (BusinessException e) {
                results.add(GenerateResult.fail(rawId, e.getCode(), e.getMessage(), e.getSuggestion()));
            }
        }
        return results;
    }

    private GenerateResult generateOne(String rawId, Long tenantId, String operator) {
        Order order = resolveOrder(rawId, tenantId);
        if (order == null) {
            throw new BusinessException("ORDER_NOT_FOUND", "无法找到订单：" + rawId, 404);
        }
        // 仅已确认订单可生成加工单（pending 未付款 / 已取消不允许）
        if (!"confirmed".equals(order.getStatus())) {
            throw BusinessException.validationError(
                    String.format("订单 %s 当前状态 [%s] 不允许生成加工单，须为已确认", order.getOrderNo(), order.getStatus()));
        }
        List<OrderItem> items = loadOrderItems(order.getId(), tenantId);
        List<Map<String, Object>> snapshot = buildSnapshot(items, tenantId);
        if (snapshot.isEmpty()) {
            throw BusinessException.validationError("订单 " + order.getOrderNo() + " 无加工项，无需生成加工单");
        }
        // 幂等：同一订单最多一个非取消态加工单（DB 层另有 partial unique index 兜底）
        ProcessingOrder existing = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (existing != null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 已有加工单 " + existing.getProcessingOrderNo() + "，请勿重复生成");
        }

        // 工序实例 payload **在任何写库之前**解析（issue #4116 切库）：工序来源 = 工序库
        // （production_routings 的基准路线 + production_operations 的单位/单价/必完标记）。
        // 放在这里而不是插入之后，是因为 fail-closed 必须同时满足两件事：
        // ① 报出可行动的失败（错误码 + suggestion）；② **不落半成品** ——
        // generate() 逐单 catch BusinessException 后继续处理其余订单（异常不逸出事务边界 ⇒
        // 不会回滚），若先插加工单再解析，库为空时就会留下「有加工单、无工序、无 qr_token」
        // 的孤儿态：工人扫不了码、加工单列表看着正常，没人会发现工序库是空的。
        PositionPayload payload = buildPositionPayload(snapshot, tenantId);
        List<Map<String, Object>> positions = payload.positions();

        ProcessingOrder po = ProcessingOrder.builder()
                .tenantId(tenantId)
                .orderId(order.getId())
                .processingOrderNo(generateOrderNo())
                .status("generated")
                .itemsSnapshot(snapshot)
                .templateVersion(1)
                .generatedBy(operator)
                .generatedAt(OffsetDateTime.now())
                .printCount(0)
                // 路线可观测（V60，issue #4308 P1）：这张单**实际走了哪条路线**、**想走哪条**、
                // **怎么来的**，三列一起落库 —— 此前 RouteKey.source 只在「路线缺失」的 error
                // 日志里被读一次，成功路径零痕迹 ⇒ 错配无数据可查。
                .routeKey(payload.routeKey())
                .routeRequestedKey(payload.routeRequestedKey())
                .routeSource(payload.routeSource())
                .deleted(0)
                .build();

        // 生成**不**联动订单状态（issue #4305，用户裁定「发加工 = 订单进入生产中」）：
        // 订单 confirmed→producing 的时点已从「生成加工单」挪到「发加工」（见 updateStatus）。
        // 故此处不再有「联动先行 + 失败回退」那段 —— 订单状态在生成路径上全程不动，
        // 也就没有「producing 无加工单」的孤儿态可言（该孤儿态的成因随联动一并挪走）。
        // 并发重复生成仍由 partial unique index 兜底 → 转幂等错误（P2①）。
        try {
            processingOrderMapper.insert(po);
        } catch (org.springframework.dao.DuplicateKeyException e) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 加工单已生成（并发操作），请刷新后重试");
        }
        log.info("生成加工单: no={}, orderId={}, tenantId={}, operator={}",
                po.getProcessingOrderNo(), order.getId(), tenantId, operator);
        // 工序实例化（issue #4116，P0 断链第一环）：加工单落行后**立即**实例化工序。
        // 此前 instantiate 端点全仓零调用者 ⇒ 工序列表恒空 ⇒ qr_token 恒 null ⇒
        // 任务卡只出「二维码待生成」占位、工人扫码报工不可达。
        // 工序序列已在插入前解析完毕（见上方 positions）：库取不到 ⇒ 根本走不到这里，
        // 所以本行的失败只可能是 DB 层错误 —— 那种情况异常逸出 generateOne 并由外层逐单
        // catch 记账，同样不留「有加工单、无工序」的静默半成品（工序另可由
        // POST .../instantiate 手工补做）。
        instantiateOperations(order, po, positions, tenantId);
        return GenerateResult.ok(rawId, po.getProcessingOrderNo());
    }

    /**
     * 实例化工序（issue #4116 切库后：工序来源 = **工序库**，不再是加工项目录）。
     *
     * <p><b>工序来源（本包的核心变更；P2b 起为新结构）</b>：`production_route_templates`（主线）
     * + `production_route_rules`（规则）+ `production_operation_positions`（部位价目/适用性）
     * + `production_operations`（每道工序的分组/单位/必完标记/作用域），全部是**库里的行**，
     * 由 {@link ProductionOperationQueryService} 的新读面读出（见 {@link #buildRoute}）。加工项目录（快照里的
     * `processingItems`）自此刻起**只**用于①派生路线键的信号、②加工单快照本身的展示，
     * **不再**提供工序 —— 旧的「工序 = 加工项名」路径已删除，取不到库数据时**显式失败**，
     * 不回退（回退会让「切库」变成装饰性的：旧路径还在 ⇒ 库为空也没人发现）。</p>
     *
     * <p><b>取路线判据</b>（订单侧**没有**部位/帘种字段，故必须显式定义取法）：按可派生信号
     * 匹配 `curtain_type`/`craft`，优先级 = 加工项名 &gt; 加工项 options &gt; 商品名 &gt; 销售方式，
     * 命中即止；两类信号全不命中 ⇒ 该租户的**默认路线模板**（见 {@link #deriveRouteKey}
     * 与 {@link #resolveRoute}）。</p>
     *
     * <p><b>`is_must_finish` / `is_start_marker` 读库</b>：取 `production_operations` 的同名列
     * （V54 种子只把「外帘装袋」标为必完）。此前实例化用「每部位**末道**工序必完」的临时口径
     * （#4131）—— 那是"库里没有种子"时代的占位，与新口径是两套语义，已删除（末道「外帘发货」
     * 在库里 `is_must_finish=false`）。</p>
     */
    private void instantiateOperations(Order order, ProcessingOrder po,
                                       List<Map<String, Object>> positions, Long tenantId) {
        if (positions.isEmpty()) {
            log.warn("加工单无可用部位派生工序，跳过自动实例化（可用手工端点补做）: no={}, orderId={}",
                    po.getProcessingOrderNo(), order.getId());
            return;
        }
        productionService.instantiate(order.getId(), Map.of("positions", positions), tenantId);
    }

    /**
     * 实例化 payload：快照行 → 部位 → **工序库**里的基准工序序列 → **算料引擎**给出的应做数量。
     *
     * <p>部位名 = 加工产物名[+色号]（同行多套据此区分）—— 见类注释「部位语义」节：
     * 部位名落到产品名，而路线键由 {@link #deriveRouteKey} **直读**订单工艺规格（存量单才派生）。</p>
     *
     * <p><b>樘窗绑组（issue #4354 引入，issue #4387 语义扩展）</b>：{@code craftLineId} 标识
     * **同一樘窗（一个窗户）** —— 它是套级工序（#4384）与加工费樘窗级（#4386）的**归属层级**。
     * 部位 = {@code order_items} 行 = 一件帘（布帘 / 纱帘 / 帘头）⇒
     * **布行与纱行各自成部位**（同组不合并），只有 {@code componentRole=配布边} 的行
     * **不独立成部位**（否则一扇窗被算成两扇：折数/开数/幅数/工序/计件全部翻倍）。
     * 组内只有配布边行时它仍自成部位（不静默丢窗）。</p>
     *
     * <p><b>定型开关（issue #4354，设计文档 §4.7）</b>：{@code isShaped=false} ⇒ 从基准序列里
     * 剔除 {@link #UNSHAPED_REMOVED_OPERATIONS}（真值源 §10 登记的「唯一尚未接线」项），
     * 与 {@code routing.py::build_routing} 同序（在条件工序插入之前）。</p>
     *
     * <p><b>应做数量（qty，issue #4208）</b>：库路线只给单位/单价，不给数量；数量的唯一真值源是
     * 算料引擎（{@code routing.py::_qty_for}），由 {@link ProductionOperationQtyClient} 逐部位问取。
     * 此前退化为**该部位的订单数量**（走查实测：一张数量=3 的加工单，11 道工序全显示 3.00 ⇒
     * 「韩褶-布」显示 **3 折**）—— 那是本单要治的缺陷，**已删除该回退**：算料服务不可用 ⇒
     * {@link ProductionOperationQtyClient#ERR_OPERATION_QTY_UNAVAILABLE} fail-closed 中止生成，
     * 绝不静默用订单数量顶替。</p>
     *
     * <p><b>不落 0</b>：缺键兜底 1 由端点负责（应做 0 ⇒ 报工的 {@code done_qty ≥ qty} 恒真 ⇒ 假完工）。</p>
     *
     * <p><b>{@code qty_source}</b>（实例表新增列）：逐工序记录口径来源（键名 = 算料输出 /
     * {@code <键名>_x6} = 有依据的估算 / {@code fallback} = 真兜底），供页面与排查区分
     * 「算料输出」与「兜底」—— 兜底不再静默。</p>
     */
    @SuppressWarnings("unchecked")
    private PositionPayload buildPositionPayload(List<Map<String, Object>> snapshot, Long tenantId) {
        List<Map<String, Object>> positions = new ArrayList<>();
        // 与 positions **同序**：回填 qty/qty_source 时按位取，不靠部位名（同商品同色号的两行会重名）
        List<List<Map<String, Object>>> operationRows = new ArrayList<>();
        List<Map<String, Object>> request = new ArrayList<>();
        // 多部位 roll-up 用（V60）：逐部位记 (route_key, route_source)，最后取最需关注的一条
        List<RouteResolution> resolutions = new ArrayList<>();
        // 新结构读面（P2b，issue #4459）：规则表 / 部位价目 / 工序库都极小，**一次取回**本租户的
        // 全部活跃行，逐部位在内存里过滤 —— 避免「每道工序一次查询」的 N+1。
        // 规则表里历史遗留的 `action='factor'` 计件系数档**已无消费者**（issue #4589：系数退场），
        // 新迁移已把它们软删；本方法只按 `insert`/`remove` 构造序列。
        List<ProductionRouteRule> rules = productionOperationQueryService.routeRules(tenantId);
        List<ProductionOperationPosition> priceRows =
                productionOperationQueryService.operationPositions(tenantId);
        Map<String, Map<String, Object>> catalog =
                productionOperationQueryService.operationsByName(tenantId);
        // 樘窗绑组（issue #4354 引入，issue #4387 语义扩展）：组键 = `craftLineId`（缺省 ⇒ 本行 itemId ⇒ 各自成组）
        Set<String> groupsWithMainRow = groupsWithMainRow(snapshot);
        // 套级工序的承载体（issue #4384 A2）：每个樘窗组只挑一行（主布行）—— 见 setLevelKeeperItemIds
        Set<String> setLevelKeepers = setLevelKeeperItemIds(snapshot, groupsWithMainRow);
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>)) {
                continue;
            }
            if (isAbsorbedEdgeRow(entry, groupsWithMainRow)) {
                // 配布边行并入同组的主布部位 ⇒ **不独立成部位**（否则一扇窗被算成两扇：
                // 折数/开数/幅数/工序/计件全部翻倍）。该行自身的货号/米数仍在快照里可展示。
                continue;
            }
            // 本行是否承载所在樘窗的套级工序（= 该组的主布行）。
            // `itemId` 恒非空（`buildSnapshot` 无条件落 `order_items.id` = 主键）⇒ 用它做承载标识。
            boolean keepsSetLevel = setLevelKeepers.contains(str(entry.get("itemId")));
            RouteKey key = deriveRouteKey(entry, tenantId);
            RouteResolution resolution = resolveRoute(key, tenantId, entry, rules, priceRows, catalog);
            resolutions.add(resolution);
            Map<String, Object> route = resolution.route();
            List<Map<String, Object>> operations = new ArrayList<>();
            for (Map<String, Object> step : (List<Map<String, Object>>) route.get("operations")) {
                // 套级工序（issue #4384 A2）：同一樘窗只落一次（挂该组主布行的部位名）。
                // 判据 = 库里带出的 `scope`（逐字取库）——**不硬编码工序名**（商家改了库要生效）。
                if (!keepsSetLevel && SCOPE_SET.equals(str(step.get("scope")))) {
                    continue;
                }
                Map<String, Object> operation = new LinkedHashMap<>();
                // ⚠️ `operation` = **工人端快照名**（变体名 `精裁-布`）：历史数据与其它消费者仍要读它，
                // **一字不动**；**web 界面不得渲染该键**（issue #4621）—— 界面显示下面的
                // `logical_name` + `position`（读时派生、**不写库**）。
                operation.put("operation", step.get("operation"));
                // 显示名派生键**从路线步骤逐字带出**（不在此另推一份 ⇒ 不会与路线读面漂移）
                operation.put("logical_name", step.get("logical_name"));
                operation.put("position", step.get("position"));
                // 分组/单位/单价/必完/开始标记**逐字取库**（不猜、不补默认值）
                operation.put("group", step.get("group"));
                operation.put("unit", step.get("unit"));
                operation.put("unit_price", step.get("unit_price"));
                operation.put("is_must_finish", step.get("is_must_finish"));
                operation.put("is_start_marker", step.get("is_start_marker"));
                operations.add(operation);
            }
            // 定型接线（issue #4354，设计文档 §4.7）：`isShaped=false` ⇒ 剔除 定型 / 复烫
            // （真值源 §10 登记的「唯一尚未接线」项）。**严格布尔 false** 才生效，且必须在条件工序
            // 插入**之前** —— 与 routing.py::build_routing 逐字同序（否则以这两道为锚点的条件工序
            // 会因锚点消失而落到末尾，与 Python 的落位不一致）。
            // P2b（issue #4459）：判据从旧工序名（定型-布/复烫-布）换成**逻辑名**（定型/复烫）——
            // 新结构里序列元素就是逻辑名。新模型给 `shaped` 预留了规则触发类型但**不种行**，
            // 故本开关仍是代码侧接线（与 routing.py::build_route_v2 的现状一致）。
            if (Boolean.FALSE.equals(entry.get("isShaped"))) {
                // 判据用**逻辑名**比较：实例里的工序名是库里的**变体名**（定型-布/复烫-布），
                // 而新结构的序列元素是逻辑名（定型/复烫）⇒ 比较前先归一。
                operations.removeIf(operation -> UNSHAPED_REMOVED_OPERATIONS.contains(
                        productionOperationQueryService.normalizeOperationName(
                                String.valueOf(operation.get("operation")))));
            }
            // 特殊选项（issue #4230）/ 加工项（issue #4577）：插条件工序 → 重排 seq → 落计件系数
            List<String> options = specialOptions(entry);
            List<String> processingItems = processingItemNames(entry);
            // ⚠️ 部位取**实际使用路线**的部位（`route.curtain_type`），不是 `entry.curtainType`：
            // 派生路径下 entry 可能没有该键（存量单），而 T2 回落时实际部位是默认模板的部位
            // ⇒ 拿 entry 的值会让「逻辑名 → 变体名」解析不到（部位为 null）⇒ 条件工序误判为缺工序。
            String routePositionOfEntry = str(route.get("curtain_type"));
            if (!options.isEmpty() || !processingItems.isEmpty()) {
                insertConditionalOperations(operations, options, processingItems, rules, tenantId, entry,
                        catalog, routePositionOfEntry);
            }
            renumberSeq(operations);
            String productName = str(entry.get("productName"));
            String colorName = str(entry.get("colorName"));
            String positionName = productName == null ? "未命名部位"
                    : (colorName == null ? productName : productName + " " + colorName);
            Map<String, Object> position = new LinkedHashMap<>();
            position.put("position_name", positionName);
            // 主定位键（V69，issue #4388 / #4373 裁定）：`order_item_id` = 该快照行对应的 order_items 行，
            // `position_kind` = 可读定位（哪一件帘）。`position_name` 是**展示名**，同商品同色号的两个窗
            // 会同名 ⇒ 只有这一对键能唯一定位实例（读面分组、算料按行取、报工/计件归属都靠它）。
            position.put("order_item_id", str(entry.get("itemId")));
            position.put("position_kind", str(entry.get("curtainType")));
            position.put("operations", operations);
            positions.add(position);
            operationRows.add(operations);
            request.add(qtyRequest(entry, positionName, operations));
        }
        if (positions.isEmpty()) {
            return new PositionPayload(positions, null, null, null);
        }
        fillQty(positions, operationRows, request);
        RouteResolution worst = worstResolution(resolutions);
        return new PositionPayload(positions,
                worst == null ? null : worst.routeKey(),
                worst == null ? null : worst.routeRequestedKey(),
                worst == null ? null : worst.routeSource());
    }

    /**
     * 樘窗绑组（issue #4354 引入，issue #4387 语义扩展）：同一樘窗（一个窗户）的多行用
     * {@code craftLineId} 绑成一组；组键只用于判定**配布边行**是否可被吸收 ——
     * **不是**「组内只保留一个部位」（布行 + 纱行同组时各成一个部位，见
     * {@link #buildPositionPayload} 的「樘窗绑组」节）。
     *
     * <p><b>组键</b> = 本行 {@code craftLineId}；缺省 ⇒ 本行 {@code itemId}。
     * 后者让「配布边行填**主布行的行标识**」（order_create 工具描述教的形态）也能对齐 ——
     * 两个不同行的 {@code itemId} 天然不等 ⇒ **没有 {@code craftLineId} 的行永远各自成组**，
     * 即「缺键时行为逐字不变」（存量单兼容）。</p>
     *
     * @return 组内**存在**可作主布的行（有加工项且角色非 {@link #COMPONENT_ROLE_EDGE}）的组键集合
     */
    private static Set<String> groupsWithMainRow(List<Map<String, Object>> snapshot) {
        Set<String> groups = new LinkedHashSet<>();
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>) || isEdgeRow(entry)) {
                continue;
            }
            String groupKey = craftGroupKey(entry);
            if (groupKey != null) {
                groups.add(groupKey);
            }
        }
        return groups;
    }

    /**
     * 该行是否被同组的主布部位**吸收**（⇒ 不独立成部位）。
     *
     * <p>只吸收 {@code componentRole=配布边} 的行：{@code 纱} 是**独立部位**（纱帘），
     * 与主布同组时仍须各成部位。组内若只有配布边行（主布行缺加工项 / {@code craftLineId} 悬空），
     * 它**必须**自己成部位 —— 静默丢掉会让整扇窗没有工序（比双算更糟：工人拿不到工钱）。</p>
     */
    private static boolean isAbsorbedEdgeRow(Map<String, Object> entry, Set<String> groupsWithMainRow) {
        if (!isEdgeRow(entry)) {
            return false;
        }
        String groupKey = craftGroupKey(entry);
        return groupKey != null && groupsWithMainRow.contains(groupKey);
    }

    /** 是否「配布边」部件行（缺省角色视为主布 ⇒ 不是配布边，存量单兼容）。 */
    private static boolean isEdgeRow(Map<String, Object> entry) {
        return COMPONENT_ROLE_EDGE.equals(str(entry.get("componentRole")));
    }

    /** 绑组键：{@code craftLineId} 优先，缺省回落到本行 {@code itemId}（两者都缺 ⇒ null = 不参与绑组）。 */
    private static String craftGroupKey(Map<String, Object> entry) {
        String craftLineId = str(entry.get("craftLineId"));
        return craftLineId != null ? craftLineId : str(entry.get("itemId"));
    }

    /**
     * 套级工序（{@code scope='set'}）的**承载体**：每个樘窗组只挑一行（issue #4384 **A2**）。
     *
     * <p>挑法与写侧（#4395 的 {@code resolveWindowCraftLineIds}）**同口径**：组内**第一条
     * `curtainType=布帘`** 的行（= 主布行 —— §4.8 的 `craftLineId` 口径、§5.6 R-b 的加工费也落它）；
     * 组内没有布帘（纱 + 帘头）⇒ 取**组内首行**（不猜、不丢组：静默丢组会让整樘窗没有套级工序）。</p>
     *
     * <p>只考虑**会变成部位的行**：被吸收的配布边行与无加工项的行在实例化循环里被 {@code continue}
     * 跳过 ⇒ 它们不能承载套级工序（否则套级工序会落在不存在的部位上 = 静默丢失）。</p>
     *
     * <h2>为什么挂主布行，而不是新增一个「外帘」部位行（设计裁定）</h2>
     * <ol>
     *   <li><b>部位计数口径</b>：部位 = 一行 {@code order_items}（R-a）⇒ 新增「外帘」行会让
     *       `positions` 数变成「部位数 + 1」，订单/看板/加工单按部位数展示的地方全部对不上；</li>
     *   <li><b>存量单兼容</b>：新增行会让**每一个**单行樘窗（存量单的绝大多数）多一行 ⇒
     *       与判据「不属于樘窗组 / 单行自成一组 ⇒ 行为逐字不变」冲突；</li>
     *   <li><b>先例</b>：樘窗级的东西落该组**主布行**（§5.6 R-b：加工费按樘窗一条、落主布行）；</li>
     *   <li><b>真值源 §8 的「外帘是加工单<u>打印行部位</u>」是打印粒度要求</b> ⇒ 归 #4388
     *       （定位键 {@code (order_item_id, position_kind)} + 打印粒度）；本单边界明确排除定位键；</li>
     *   <li><b>工人扫码端仍看得到</b>：扫码/详情/报工读的是**工序行**，按 {@code position_name}
     *       分组（{@code ProductionService.buildPositions}）⇒ 套级工序挂在主布行部位名下照样可见可报工。</li>
     * </ol>
     *
     * @return 各组承载体行的 {@code itemId} 集合（空快照 / 全是被吸收行 ⇒ 空集）
     */
    private static Set<String> setLevelKeeperItemIds(List<Map<String, Object>> snapshot,
                                                     Set<String> groupsWithMainRow) {
        Map<String, List<Map<String, Object>>> byGroup = new LinkedHashMap<>();
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>) || isAbsorbedEdgeRow(entry, groupsWithMainRow)) {
                continue;
            }
            // 组键恒非空（`itemId` = order_items 主键，`buildSnapshot` 无条件落）⇒ 不存在「不参与绑组」的行；
            // 万一为空（脏快照）⇒ 该行自成一樘窗（键用行标识兜底），**不静默并组**。
            String groupKey = craftGroupKey(entry);
            byGroup.computeIfAbsent(groupKey == null ? "item:" + str(entry.get("itemId")) : groupKey,
                    k -> new ArrayList<>()).add(entry);
        }
        Set<String> keepers = new LinkedHashSet<>();
        for (List<Map<String, Object>> group : byGroup.values()) {
            Map<String, Object> keeper = group.stream()
                    .filter(row -> CURTAIN_TYPE_CLOTH.equals(str(row.get("curtainType"))))
                    .findFirst()
                    .orElse(group.get(0));
            String itemId = str(keeper.get("itemId"));
            if (itemId != null) {
                keepers.add(itemId);
            }
        }
        return keepers;
    }

    /** 多部位 roll-up：取最需关注的一条（{@link #severity}），同档取先出现者。 */
    private static RouteResolution worstResolution(List<RouteResolution> resolutions) {
        RouteResolution worst = null;
        for (RouteResolution resolution : resolutions) {
            if (worst == null || severity(resolution.routeSource()) > severity(worst.routeSource())) {
                worst = resolution;
            }
        }
        return worst;
    }

    /** 部位派生 payload + 落库用的路线键/来源（V60，issue #4308）。 */
    private record PositionPayload(List<Map<String, Object>> positions, String routeKey,
                                   String routeRequestedKey, String routeSource) {
    }

    // ============================================================ 特殊选项（issue #4230）

    /**
     * 本单携带的特殊选项（{@code processingInfo.specialOptions: string[]}，v1a 新增携带）。
     *
     * <p>归一化：只认字符串数组形态（前端/agent 写的就是数组），空白项丢弃、去重保序 ——
     * 重复选项不得把同一道条件工序插两次（插两次会让工人按两遍单价拿钱）。</p>
     */
    private static List<String> specialOptions(Map<String, Object> entry) {
        Object raw = entry.get("specialOptions");
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> options = new ArrayList<>(list.size());
        for (Object item : list) {
            String option = str(item);
            if (option != null && !options.contains(option)) {
                options.add(option);
            }
        }
        return options;
    }

    /**
     * 本单该行携带的**加工项名**（{@code processingInfo.processingItems[].name}，去重保序）。
     *
     * <p>`processing_item` 规则的触发键（issue #4577，用户裁定「加工项也触发工序」）。
     * 与 {@link #specialOptions} 同款归一：只认 Map 元素 + 非空名字，缺失/脏形态 ⇒ 不命中（不猜）。
     * 与真值源 {@code routing.py::_rule_triggers} 的 {@code position["processing_items"]} 同口径。</p>
     */
    private static List<String> processingItemNames(Map<String, Object> entry) {
        if (!(entry.get("processingItems") instanceof List<?> items)) {
            return List.of();
        }
        List<String> names = new ArrayList<>(items.size());
        for (Object raw : items) {
            if (raw instanceof Map<?, ?> item) {
                String name = str(item.get("name"));
                if (name != null && !names.contains(name)) {
                    names.add(name);
                }
            }
        }
        return names;
    }

    /**
     * 条件工序规则的触发判定（issue #4577）：**精确相等**，与 {@code buildRoute} /
     * {@code routing.py::_rule_triggers} 同口径。
     *
     * <p>{@code option} ⇒ 触发键 = 本单特殊选项名；{@code processing_item} ⇒ 触发键 = 该行
     * {@code processingInfo.processingItems[].name}（**不得**用 {@code contains} —— 错一个字就静默失效；
     * {@code contains} 只存在于存量信号兜底 {@code firstSignalMatch}，不在此处引入第二处）。</p>
     */
    private static boolean conditionalRuleTriggers(ProductionRouteRule rule, List<String> options,
                                                   List<String> processingItems) {
        String kind = rule.getTriggerKind();
        if ("option".equals(kind)) {
            return options.contains(rule.getTriggerValue());
        }
        if ("processing_item".equals(kind)) {
            return processingItems.contains(rule.getTriggerValue());
        }
        return false;
    }

    /**
     * 插入条件工序（issue #4230 验收判据 1；P2b 改读 {@code production_route_rules}）。
     *
     * <p>规则行的 {@code action='insert'} + {@code trigger_kind ∈ {option, processing_item}} ⇒ 把
     * {@code operation} 插到 {@code after_operation} 之后（issue #4577 起加工项也是触发键）。
     * 与真值源
     * {@code routing.py::build_route_v2} + {@code _insert_after} 同口径：
     * 锚点不在该部位路线中 ⇒ **追加到末尾**；同一锚点上的多个插入按 {@code (priority, id)}
     * 依次插在锚点之后 ⇒ 后插的在前（与 Python 的 {@code insert(idx+1, …)} 逐字同款）。</p>
     *
     * <p>工序元数据（分组/单位/单价/必完/开始标记）**逐字取库**（经
     * {@code variantNameOf} 把逻辑名换成该租户库里的变体名）；条件工序在工序库无活跃行 ⇒
     * fail-closed（{@link #ERR_OPERATION_NOT_FOUND}）—— 静默跳过会让「勾了却没加工序」
     * 在数据上消失，那正是本单要治的「设计过但从未接线」形态。</p>
     *
     * <p><b>唯一性 = 取代（issue #4577）</b>：目标逻辑工序**已在序列里** ⇒ <b>先移除旧位置、再按本条
     * 规则的锚点插入</b>（<b>取代</b>，不是"跳过"—— 跳过会让位置停留在先应用那条规则，而商家选特殊
     * 选项的意图是「按这个选项的工序来」；口径来源 = 用户 2026-09-19 原话「工序需要保证唯一…用特殊
     * 选项中的余料做绑带替代绑带这个工序…需要有这个前提」，前提 = **目标工序名相同**）。
     * 结果 = 该工序在序列里**恰好一行**（盲插会让工人按两遍/三遍单价拿钱，同族事故 #4523）。
     * 规则应用顺序仍由 {@code priority} 决定（特殊选项 110~260 > 工艺 10~100 ⇒ 特殊选项自然覆盖工艺）。</p>
     */
    private void insertConditionalOperations(List<Map<String, Object>> operations, List<String> options,
                                             List<String> processingItems, List<ProductionRouteRule> rules,
                                             Long tenantId, Map<String, Object> entry,
                                             Map<String, Map<String, Object>> catalog,
                                             String position) {
        List<ProductionRouteRule> applicable = new ArrayList<>();
        for (ProductionRouteRule rule : rules) {
            if (!"insert".equals(rule.getAction())
                    || !conditionalRuleTriggers(rule, options, processingItems)) {
                continue;
            }
            if (rule.getPosition() != null && !Objects.equals(rule.getPosition(), position)) {
                continue;   // 部位限定：不匹配本部位 ⇒ 不触发（与 build_route_v2 逐字同款）
            }
            applicable.add(rule);
        }
        if (applicable.isEmpty()) {
            return; // 选项未登记条件工序（纯系数选项 / 显式不计件选项）⇒ 路线不变，不是错误
        }
        // 读取侧已按 (priority, id) 排好；此处再显式排一次，不依赖调用方（确定性的承重点）
        applicable.sort(Comparator.comparing(
                        (ProductionRouteRule r) -> r.getPriority() == null ? 0 : r.getPriority())
                .thenComparing(r -> r.getId() == null ? "" : r.getId()));
        List<String> missing = new ArrayList<>();
        for (ProductionRouteRule rule : applicable) {
            String logicalName = rule.getOperation();
            String operationName = productionOperationQueryService.variantNameOf(logicalName, position, catalog);
            Map<String, Object> meta = operationName == null ? null : catalog.get(operationName);
            if (meta == null) {
                // ⚠️ 只报**逻辑名**，**不得**拼期望的库内变体名（issue #4647 / D3(b)）：该 hint 经
                // `message` / `suggestion` 进 422 响应体（接口响应可见），而变体名（`拼1次-布`）是
                // 工人端快照名 —— 拼进去就是同一处泄漏换了个出口（改前实测日志：
                // `缺工序=[拼1次（库中缺变体 拼1次-布 / 布拼1次 / 布帘拼1次 / 拼1次）]`）。
                // 可行动性靠**说清缺什么 + 去哪儿补**（部位在 `position` 里，已由外层日志/提示给出）。
                missing.add(logicalName + "（该工序在「" + position + "」部位缺库行 / 未建矩阵行）");
                continue;
            }
            Map<String, Object> operation = new LinkedHashMap<>();
            // ⚠️ `operation` = **工人端快照名**（变体名）：**web 界面不得渲染该键**（issue #4621）
            operation.put("operation", operationName);
            // 显示名派生键：规则里的 `operation` **就是逻辑名**（`production_route_rules.operation`
            // 与 OPERATION_LOGICAL_NAMES 的值域一致）⇒ 逐字带出，不再归一一次
            operation.put("logical_name", logicalName);
            operation.put("position", ProductionOperationQueryService.displayPosition(operationName, position));
            operation.putAll(meta);
            // 唯一性 = 取代（issue #4577）：目标工序已在序列里 ⇒ 先移除旧位置、再按本条规则的锚点插入
            operations.removeIf(existing -> Objects.equals(str(existing.get("operation")), operationName));
            int anchor = indexOfLogicalOperation(operations, rule.getAfterOperation());
            if (anchor < 0) {
                log.info("特殊选项「{}」的锚点工序「{}」不在该部位路线中，条件工序「{}」追加到末尾: productName={}",
                        rule.getTriggerValue(), rule.getAfterOperation(), operationName, entry.get("productName"));
                operations.add(operation);
            } else {
                operations.add(anchor + 1, operation);
            }
        }
        if (!missing.isEmpty()) {
            log.error("{} 特殊选项引用的条件工序在工序库无活跃行，生成加工单中止: tenantId={}, 缺工序={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, missing, entry.get("productName"));
            throw new BusinessException(ERR_OPERATION_NOT_FOUND,
                    String.format("特殊选项引用的条件工序 %s 在工序库中不存在，无法实例化工序", missing),
                    422,
                    String.format("请在工序库补上 %s（或停用引用它的特殊选项映射）；"
                                    + "工序库目录查看入口 GET /api/admin/production/operations-catalog",
                            String.join("、", missing)));
        }
    }

    /**
     * 锚点工序在**实例序列**中的下标；不在 ⇒ -1（调用方按真值源口径追加到末尾）。
     *
     * <p>锚点是**逻辑名**（规则表的 {@code after_operation}），而实例里的工序名是**变体名**
     * （{@code 精裁-布}）⇒ 比较前先把实例名归一为逻辑名（{@code normalizeOperationName}）。
     * 直接比变体名 ⇒ 锚点永远找不到 ⇒ 条件工序**静默全部追加到末尾**（顺序错 = 车间按错顺序干）。</p>
     */
    private int indexOfLogicalOperation(List<Map<String, Object>> operations, String logicalAnchor) {
        if (logicalAnchor == null) {
            return -1;
        }
        for (int i = 0; i < operations.size(); i++) {
            String name = operations.get(i).get("operation") == null
                    ? null : String.valueOf(operations.get(i).get("operation"));
            if (Objects.equals(productionOperationQueryService.normalizeOperationName(name), logicalAnchor)) {
                return i;
            }
        }
        return -1;
    }

    /**
     * 重排部位内序号（1..N）。
     *
     * <p>为什么必须重排：库路线的 seq 只覆盖**基准**工序，条件工序插进来后原序号会重复/断档；
     * 而 {@code seq} 是页面排序与「默认给下一道待做」派生的**唯一**顺序依据 ⇒ 序号重复/断档 =
     * 顺序显示/派生错。真值源同款：
     * {@code routing.py::instance_operations} 在插完条件工序后 `enumerate(route, start=1)`。</p>
     *
     * <p>⚠️ 改判（issue #4694，2026-09-20）：seq **不再是**报工顺序闸门的判据 —— 用户裁定
     * 「系统无需管理生产顺序」，原 {@code ProductionService.assertPredecessorsDone} 已删除
     * （报工不再按 seq 校验前道是否完成）。</p>
     *
     * <p>无特殊选项时结果与库路线逐值相同（路线 seq 本来就是 1..N）⇒ 不回归。</p>
     */
    private static void renumberSeq(List<Map<String, Object>> operations) {
        for (int i = 0; i < operations.size(); i++) {
            operations.get(i).put("seq", i + 1);
        }
    }

    /**
     * 算料请求体里的单个部位（与 ai-agent 端点冻结契约同构）。
     *
     * <p>{@code order_item_id}（V69，issue #4388）是**额外**键：端点模型（pydantic 默认 `extra` 忽略）
     * 不会因它报错，但**也不会回显** ⇒ 今天只用于「请求自描述 + 排查」（谁的数量是谁的），
     * 以及将来引擎回显后可改成按行匹配。**本单不改 ai-agent**（边界：Agent 层另单）。</p>
     */
    private Map<String, Object> qtyRequest(Map<String, Object> entry, String positionName,
                                           List<Map<String, Object>> operations) {
        List<String> names = new ArrayList<>(operations.size());
        for (Map<String, Object> operation : operations) {
            names.add(String.valueOf(operation.get("operation")));
        }
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("position_name", positionName);
        position.put("order_item_id", str(entry.get("itemId")));
        position.put("operations", names);
        position.put("calc_info", calcInfo(entry));
        return position;
    }

    /**
     * 算料输入（issue #4208 Java 接线；米数判据由 issue #4299 更正为**加工项** {@code pricingMethod}）。
     *
     * <p><b>三层字段别混</b>（#4299 真库实测钉死，见 {@code acceptance/2026-09-18/4299-db-distribution/FINDINGS.md}）：</p>
     * <ul>
     *   <li>{@code sellingMethod} = <b>售卖方式</b>（真库取值：{@code bulk_cut} / {@code 散剪} /
     *       {@code full_roll} / {@code 整卷} / {@code 散剪售卖} / {@code 散剪按米} / {@code 散剪·按米购买} /
     *       {@code 散剪(bulk_cut)} / {@code cut} / {@code 散剪（按米裁剪）} / 无）—— <b>不是数量口径的来源</b>；
     *       {@code per_meter} 在该字段里一次都没出现过 ⇒ 拿它当判据<b>永不命中</b>（#4299 的病根）。</li>
     *   <li>加工项 {@code pricingMethod} = <b>加工项计价方式</b>（{@code per_meter} / {@code per_set} /
     *       {@code fixed} / {@code per_area}…）—— <b>订单行数量口径由它决定</b>，故它是本方法的判据字段
     *       （可达面 68 条订单行里命中 67 条）。</li>
     *   <li>{@code products.pricing_type} = <b>商品</b>计价方式 —— 与订单行口径<b>不是同一层</b>：
     *       实测按它会漏 18/68 条（11 条商品缺失/软删 + 6 条 {@code pricing_type=fixed} 而其加工项仍按米）。</li>
     * </ul>
     * <p>{@code per_meter} 与「按米」是<b>加工项计价方式</b>的词汇，历史上被误当成售卖方式词表 ——
     * 同族混淆见前端展示表（{@code OrderDetail.tsx} / {@code OrderItemList.tsx} 把 {@code per_meter: '按米'}
     * 放进了 {@code sellingMethod} 的映射表）。</p>
     *
     * <p><b>取值</b>：命中时取<b>订单行</b> {@code quantity}（{@code OrderItem.quantity} javadoc：per_meter=米数），
     * <b>不</b>取加工项自己的 {@code quantity} —— 实测订单行 {@code 7e6f2a1c…} 订单数量 112.00
     * 而其 {@code per_meter} 加工项 quantity=1，取后者会让 112 米的单得到「应做 1 米」⇒ 报工上限 1 ⇒ 假完工。</p>
     *
     * <p><b>已知缺口（#4118，不是本方法缺陷）</b>：订单侧**从不落库算料输出** ⇒
     * {@code pleat_count}（折数）/ {@code panels}（幅）/ {@code set_count}（套）/ {@code holes}（孔）
     * 一律取不到 ⇒ 端点在缺键时兜底 1 并在 {@code qty_source} 标 {@code fallback}。
     * 真正修法是**下单时把算料输出落库**（#4118「实际褶倍算了就丢」），届时本方法只需把透传白名单
     * 扩到那几个键即可 —— 请勿把它当 bug 反复排查。</p>
     */
    private Map<String, Object> calcInfo(Map<String, Object> entry) {
        Map<String, Object> calc = new LinkedHashMap<>();
        // ① 订单侧若已存算料输出（键名与 routing.py 的 METER_KEYS/FOLD_KEYS/… 同口径）⇒ 原样透传
        for (String key : CALC_INFO_KEYS) {
            Object value = entry.get(key);
            if (value != null) {
                calc.put(key, value);
            }
        }
        // ② 加工项里有 per_meter ⇒ 订单行数量即米数（键名映射；其它计价方式**不**冒充米数）
        if (!calc.containsKey("fabric_meters") && hasPerMeterPricing(entry)) {
            Object quantity = entry.get("quantity");
            if (quantity != null) {
                calc.put("fabric_meters", quantity);
            }
        }
        return calc;
    }

    /**
     * 订单行的加工项里是否有一项按米计价（{@code pricingMethod == "per_meter"}）。
     *
     * <p>只看该单**实际选的加工项**（键名驼峰 {@code pricingMethod}，两个下单入口都这么写），
     * 不看售卖方式、也不看商品级 {@code pricing_type} —— 理由与实测数字见 {@link #calcInfo}。
     * {@code processingItems} 缺失 / 非 List / 元素非 Map 一律视为**不命中**（老数据与脏数据形态，不猜）。</p>
     */
    private static boolean hasPerMeterPricing(Map<String, Object> entry) {
        Object raw = entry.get("processingItems");
        if (!(raw instanceof List<?> items)) {
            return false;
        }
        for (Object item : items) {
            if (item instanceof Map<?, ?> proc && "per_meter".equals(str(proc.get("pricingMethod")))) {
                return true;
            }
        }
        return false;
    }

    /**
     * 用算料引擎的返回回填 {@code qty} 与 {@code qty_source}。
     *
     * <p>fail-closed 的三个细节：① 端点返回条数与请求不符 ⇒ 客户端已抛错（不在此处补位）；
     * ② 端点漏答某道工序（契约外形态）⇒ 同样抛错，**不**替它兜底 1 ——
     * 静默补值会让「算料服务没答」与「算料服务答了兜底 1」长得一模一样；
     * ③ <b>身份校验（issue #4388）</b>：条数相同 ≠ 对得上 —— 响应必须**指回请求里的那个部位**
     * （引擎契约是纯映射、保序；本断言把「靠数组位次对齐」从**隐含假设**变成**显式契约**）⇒
     * 一旦引擎重排/串位，是**显式失败**而不是把 A 窗的数量写到 B 窗上（静默错配 = 本仓最大失败模式）。</p>
     *
     * <p>⚠️ <b>已知边界（登记在 PR）</b>：引擎响应只回 {@code position_name}，**不回显行标识**
     * ⇒ **同名**部位之间仍无法靠身份区分（本断言对它们恒成立）。真正的按 {@code order_item_id}
     * 取值需要 ai-agent 端回显该键（属 Agent 侧改动，跟随单）。</p>
     */
    private void fillQty(List<Map<String, Object>> positions,
                         List<List<Map<String, Object>>> operationRows,
                         List<Map<String, Object>> request) {
        List<ProductionOperationQtyClient.PositionQty> resolved = productionOperationQtyClient.resolve(request);
        if (resolved.size() != positions.size()) {
            throw new BusinessException(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                    "算料服务返回的部位数（" + resolved.size() + "）与请求（" + positions.size() + "）不符，已中止生成加工单",
                    422,
                    "请确认 ai-agent-service 版本与 admin-api 契约一致后重新生成加工单");
        }
        for (int i = 0; i < positions.size(); i++) {
            ProductionOperationQtyClient.PositionQty answered = resolved.get(i);
            String requestedName = String.valueOf(request.get(i).get("position_name"));
            if (!requestedName.equals(answered.positionName())) {
                throw new BusinessException(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                        "算料服务返回的部位身份与请求不符（第 " + (i + 1) + " 个：请求「" + requestedName
                                + "」，响应「" + answered.positionName() + "」），已中止生成加工单（不静默错配）",
                        422,
                        "请确认 ai-agent-service 版本与 admin-api 契约一致后重新生成加工单");
            }
            for (Map<String, Object> operation : operationRows.get(i)) {
                String name = String.valueOf(operation.get("operation"));
                BigDecimal qty = answered.qtyByOperation().get(name);
                if (qty == null) {
                    throw new BusinessException(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                            "算料服务未返回工序「" + name + "」的应做数量，已中止生成加工单（不静默兜底）",
                            422,
                            "请确认 ai-agent-service 的算料端点已登记该工序的单位后重新生成加工单");
                }
                operation.put("qty", qty);
                operation.put("qty_source", answered.qtySourceByOperation().get(name));
            }
        }
    }

    /**
     * 取路线（**新结构**：主线 + 规则 + 部位适用性）+ 记来源（V60，issue #4308 三层回落语义逐层可观测）。
     *
     * <p><b>P2b 切换（issue #4459）</b>：路线来源从旧 {@code production_routings} 的
     * 「{@code (部位 × 工艺)} 展开快照」切到 {@code production_route_templates.mainline}
     * + {@code production_route_rules} + {@code production_operation_positions}。
     * 规则应用语义与真值源 {@code routing.py::build_route_v2} <b>逐字一致</b>
     * （见 {@link #buildRoute}）。</p>
     *
     * <ul>
     *   <li><b>T1</b> 信号全不命中 ⇒ 取该租户的**默认路线模板**，来源 {@code default}，
     *       记 {@link #INCIDENT_ROUTE_DEFAULTED}（warn 级 —— 迁移前这一层**连 info 都没有**）；</li>
     *   <li><b>T2</b> 派生键的部位**没有**路线模板 ⇒ 回落默认路线模板，来源降级 {@code missing_route}
     *       （**不并入 {@code partial}**：补救动作不同 —— T2 要「建/改路线」、只命中一维要「配信号」），
     *       记 {@link #INCIDENT_ROUTE_FALLBACK}；</li>
     *   <li><b>T3</b> 该租户**连默认路线模板都没有** / 路线引用的工序在库中缺行 ⇒
     *       **fail-closed 中止生成**（#4116 已落码，本单保持不动）。
     *       ⚠️ **绝不**回落到常量 {@code 布帘×韩褶} 或加工项目录。</li>
     * </ul>
     *
     * <p>来源与「实际使用的路线键」必须**同源返回**：分两次算必然漂移（记下来的键与实际实例化的
     * 工序对不上，等于白记）。</p>
     */
    @SuppressWarnings("unchecked")
    private RouteResolution resolveRoute(RouteKey key, Long tenantId, Map<String, Object> entry,
                                         List<ProductionRouteRule> rules,
                                         List<ProductionOperationPosition> priceRows,
                                         Map<String, Map<String, Object>> catalog) {
        String requestedKey = "default".equals(key.source()) ? null : key.curtainType() + "×" + key.craft();
        String usedKey = key.curtainType() + "×" + key.craft();
        String source = key.source();
        // 缺 `craft` 且该租户没有默认工艺（production_crafts.is_default）⇒ T3 fail-closed。
        // 绝不静默取常量 `韩褶`：工艺决定「插入哪道工序 + 计件系数」，猜错 = 算错工人工资。
        if (key.craft() == null) {
            log.error("{} 订单缺 `craft` 且该租户没有默认工艺，生成加工单中止（不回退常量 韩褶）: "
                            + "tenantId={}, 部位={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, key.curtainType(), entry.get("productName"));
            throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                    String.format("订单未给出工艺（craft），且该租户没有配置默认工艺，无法实例化工序"),
                    422,
                    "请在「工艺配置」把一条工艺设为默认（缺 craft 的订单取它），"
                            + "或在下单时给出工艺；查看入口 GET /api/admin/production/routings");
        }
        // T1：全无派生信号 ⇒ 直接取默认路线模板（**该租户的**默认，不是常量）
        if ("default".equals(source)) {
            log.warn("{} 订单无任何信号命中（componentRole / craft_hint / 存量信号表的加工项名·options），"
                            + "落默认路线 {}: tenantId={}, productName={}, 信号={}",
                    INCIDENT_ROUTE_DEFAULTED, usedKey, tenantId, entry.get("productName"), signals(entry));
        }
        // T2：派生出部位/工艺但该部位没有路线模板 ⇒ 回落默认路线模板
        ProductionRouteTemplate template =
                productionOperationQueryService.routeTemplateFor(tenantId, key.curtainType());
        // 实例化用的**部位**：命中部位自己的模板 ⇒ 用它；回落默认模板 ⇒ 用模板**自己适用**的部位
        // （否则「罗马帘」这类库里没有价目/工序的部位会让整条路线被适用性矩阵滤空 ⇒ 零工序）。
        String routePosition = key.curtainType();
        String routeCraft = key.craft();
        if (template == null) {
            log.warn("{} 部位「{}」没有可用的工艺路线模板，回落默认路线模板（来源 {} ⇒ missing_route）: "
                            + "tenantId={}, 想走的键={}, productName={}, 库中现有路线模板={}",
                    INCIDENT_ROUTE_FALLBACK, key.curtainType(), source,
                    tenantId, usedKey, entry.get("productName"),
                    productionOperationQueryService.routingKeys(tenantId));
            source = "missing_route";
            template = productionOperationQueryService.defaultRouteTemplate(tenantId);
            if (template != null) {
                routePosition = defaultPositionOf(template);
            }
            // 工艺维**一起回落**：派生出的工艺（如 平幔）属于「该部位没有的那条路线」，
            // 换到默认模板的部位上会插进该部位不做的工序（旧结构 T2 也是整键回落默认）。
            String fallbackCraft = productionOperationQueryService.defaultCraft(tenantId);
            routeCraft = fallbackCraft == null ? routeCraft : fallbackCraft;
        }
        if (template == null) {
            List<String> available = productionOperationQueryService.routingKeys(tenantId);
            log.error("{} 该租户没有默认工艺路线模板，生成加工单中止（不回退加工项目录、不回退常量路线）: "
                            + "tenantId={}, 需要={}, 库中现有路线模板={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, usedKey, available, entry.get("productName"));
            throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                    String.format("工序库缺少「%s」的工艺路线模板，且该租户没有默认路线，无法实例化工序"
                                    + "（工序来源为工序库，不回退加工项目录）", usedKey),
                    422,
                    String.format("请在「工艺配置 → 工艺路线」建一条路线并设为默认（当前库中路线模板 %s）；"
                                    + "若为空库，先确认 V71/V72 种子迁移已执行；"
                                    + "查看入口 GET /api/admin/production/routings",
                            available.isEmpty() ? "**为空**" : "有：" + String.join("、", available)));
        }
        Map<String, Object> route = buildRoute(template, routePosition, routeCraft, entry,
                rules, priceRows, catalog, tenantId);
        List<String> missing = (List<String>) route.get("missing_operations");
        if (missing != null && !missing.isEmpty()) {
            log.error("{} 工艺路线引用的工序在工序库无活跃行，生成加工单中止（不回退加工项目录）: "
                            + "tenantId={}, 路线={}, 缺工序={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, usedKey, missing, entry.get("productName"));
            throw new BusinessException(ERR_OPERATION_NOT_FOUND,
                    String.format("工艺路线「%s」引用的工序 %s 在工序库中不存在，无法实例化工序",
                            template.getName(), missing),
                    422,
                    String.format("请在工序库补上 %s（或改这条路线不再引用它们）；"
                                    + "工序库目录查看入口 GET /api/admin/production/operations-catalog",
                            String.join("、", missing)));
        }
        // `route_key` = **实际使用的那条路线的身份**。新结构里路线 = 具名模板（工艺已降为规则触发键）
        // ⇒ 用模板名而不是「部位×工艺」：后者在 T2 时描述的不是实际用的路线
        // （验收判据 6：「默认路线改为另一条 ⇒ 无信号订单实际使用键随之变」）。
        return new RouteResolution(route, template.getName(), requestedKey, source);
    }

    /**
     * **主线 + 规则 + 部位适用性** → 工序实例的基准序列（P2b，issue #4459）。
     *
     * <p>⚠️ <b>本方法是「怎么展开路线」的**唯一** Java 实现</b>，且必须与真值源
     * {@code routing.py::build_route_v2} <b>逐字一致</b>（顺序敏感）：</p>
     * <ol>
     *   <li>取主线（{@code template.mainline}，逻辑工序名）；</li>
     *   <li>按 {@code priority} <b>升序</b>应用规则（同 priority 按 id，读取侧已排好）：
     *       触发命中（工艺精确匹配 / 选项 ∈ 本单选项）+ 部位限定通过 ⇒
     *       {@code insert} 用 {@code after_operation} 定位（锚点不在序列中 ⇒ <b>追加末尾</b>，
     *       与 {@code _insert_after} 同款）；{@code remove} 直接删除该逻辑工序名。
     *       ⚠️ <b>{@code remove} 不先于 {@code insert}</b>：顺序完全由 {@code priority} 决定；</li>
     *   <li>按 {@code production_operation_positions.applicable} <b>滤掉该部位不做的工序</b>：
     *       键存在且 {@code false} ⇒ 「该部位明确不做」⇒ 静默滤掉；缺该 {@code (逻辑工序, 部位)} 行
     *       且名字**本身就是逻辑工序名** ⇒ 也滤掉（没有适用性行 = 没登记过，不猜）；
     *       ⚠️ 而名字**不是逻辑工序名**（变体名 / 别名，如 {@code 精裁-布}）⇒ 实例化按逻辑名建键
     *       永远查不到 ⇒ **必须可见**（进 {@code missing_operations}，见 issue #4609）。</li>
     * </ol>
     *
     * <p>工序元数据（分组/单位/单价/必完/开始标记/作用域）逐字取该租户的工序库行
     * （经 {@link ProductionOperationQueryService#variantNameOf} 换回变体名）；
     * 库中缺该变体、或主线里出现**不认识的名字** ⇒ 登记进 {@code missing_operations}
     * （由调用方 fail-closed，**不猜默认值**，也**不静默丢**）。</p>
     *
     * <p>单价取 {@code production_operation_positions.unit_price}（该部位价目），
     * 而不是工序库行的价 —— 新结构里价目是**按部位**的（P1 实证当前两侧逐字相同；
     * 分化后以价目表为准）。价目为 {@code null} 而 {@code applicable=true}（「没定价」）⇒
     * 退回工序库行价，避免把已定价的工序实例算成 0 元。</p>
     */
    private Map<String, Object> buildRoute(ProductionRouteTemplate template, String position, String craft,
                                           Map<String, Object> entry,
                                           List<ProductionRouteRule> rules,
                                           List<ProductionOperationPosition> priceRows,
                                           Map<String, Map<String, Object>> catalog,
                                           Long tenantId) {
        Map<String, BigDecimal> priceByLogical = new LinkedHashMap<>();
        Map<String, Boolean> applicableByLogical = new LinkedHashMap<>();
        for (ProductionOperationPosition row : priceRows) {
            if (!Objects.equals(row.getPosition(), position) || row.getLogicalName() == null) {
                continue;
            }
            priceByLogical.put(row.getLogicalName(), row.getUnitPrice());
            applicableByLogical.put(row.getLogicalName(), Boolean.TRUE.equals(row.getApplicable()));
        }

        List<String> sequence = new ArrayList<>();
        for (String step : stringList(template.getMainline())) {
            sequence.add(step);
        }
        List<String> options = specialOptions(entry);
        List<String> processingItems = processingItemNames(entry);
        // 顺序**必须**显式排一次（不依赖调用方）：与 routing.py::build_route_v2 的
        // `sorted(ROUTE_RULES, key=priority)` 逐字同口径 —— 规则应用顺序敏感
        // （`remove` 不先于 `insert`；锚点可用性由 priority 决定）。
        List<ProductionRouteRule> ordered = new ArrayList<>(rules);
        ordered.sort(Comparator.comparing(
                        (ProductionRouteRule r) -> r.getPriority() == null ? 0 : r.getPriority())
                .thenComparing(r -> r.getId() == null ? "" : r.getId()));
        for (ProductionRouteRule rule : ordered) {
            String kind = rule.getTriggerKind();
            if ("craft".equals(kind)) {
                if (!Objects.equals(rule.getTriggerValue(), craft)) {
                    continue;
                }
            } else if ("option".equals(kind)) {
                if (!options.contains(rule.getTriggerValue())) {
                    continue;
                }
            } else if ("processing_item".equals(kind)) {
                // 加工项触发（issue #4577，用户裁定「加工项也触发工序」）：触发键 = 该行
                // `processingInfo.processingItems[].name`，**精确相等**（与 craft/option 同款）。
                if (!processingItems.contains(rule.getTriggerValue())) {
                    continue;
                }
            } else {
                // `shaped` 是表结构预留的触发类型（V71/V72 无种子行、无消费路径）。
                // 静默跳过会让「规则已落库但永不生效」变成无人可见的黑洞 ⇒ 与真值源
                // routing.py::_rule_triggers 同款**显式失败**。
                throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                        String.format("工艺路线规则「%s」的触发类型「%s」尚未实现，无法实例化工序",
                                rule.getId(), kind),
                        422,
                        "请在「工艺配置 → 工艺路线」停用该规则，或联系研发实现该触发类型");
            }
            if (rule.getPosition() != null && !Objects.equals(rule.getPosition(), position)) {
                continue;
            }
            if ("insert".equals(rule.getAction())) {
                sequence = insertAfterLogical(sequence, rule.getOperation(), rule.getAfterOperation());
            } else if ("remove".equals(rule.getAction())) {
                String removed = rule.getOperation();
                sequence.removeIf(op -> Objects.equals(op, removed));
            }
            // action='factor' 不参与序列构造（#4589 起它也不再覆盖计件系数 —— 该档已无消费者，
            // 新迁移已把活跃行软删；此处保留分支语义：非 insert/remove 的动作不改序列）
        }

        List<Map<String, Object>> steps = new ArrayList<>();
        List<String> missing = new ArrayList<>();
        int seq = 1;
        for (String logicalName : sequence) {
            Boolean applicable = applicableByLogical.get(logicalName);
            if (applicable == null) {
                // 键不存在 = **两件事**，必须拆开（issue #4609，P0 静默丢工序）：
                // 改前这里与「该部位明确不做」共用一条 `continue` ⇒ 主线里存着**变体名**（`精裁-布`，
                // 老 bundle / 界面加过工序的存量路线）时也被静默滤掉 —— 商家加了工序、路线卡片上也看得见，
                // 但加工单里根本没有它，**没有任何报错**（工人少一道活、少拿一笔计件钱）。
                // 判据复用**同一份**归一表（`normalizeOperationName`，不新造第二份）：
                //  · 名字归一后**不等于自己** ⇒ 它是变体名 / 别名，实例化按逻辑名建键永远查不到
                //    ⇒ **必须可见**：进 `missing_operations`（调用方据此 fail-closed 并指名报缺）；
                //  · 名字本身就是逻辑工序名 ⇒ 只是该部位**没登记这一格**（未登记适用性）
                //    ⇒ 保持原语义滤掉（没有适用性行 = 没登记过，不猜）。
                if (!logicalName.equals(productionOperationQueryService.normalizeOperationName(logicalName))) {
                    missing.add(logicalName);
                }
                continue;
            }
            if (!applicable) {
                continue;   // 该部位**明确不做** ⇒ 静默滤掉（既有语义不变）
            }
            String variant = productionOperationQueryService.variantNameOf(logicalName, position, catalog);
            Map<String, Object> meta = variant == null ? null : catalog.get(variant);
            if (meta == null) {
                missing.add(logicalName);
                continue;
            }
            Map<String, Object> step = new LinkedHashMap<>();
            step.put("seq", seq++);
            step.put("operation", variant);
            // 工序显示名的读时派生（issue #4621）：`logical_name` + `position` 供 **web 界面**渲染
            // 「逻辑名 · 部位」；`operation` 是**工人端快照名**（变体名），**web 界面不得渲染该键**。
            step.put("logical_name", logicalName);
            step.put("position", ProductionOperationQueryService.displayPosition(variant, position));
            step.put("group", meta.get("group"));
            step.put("unit", meta.get("unit"));
            BigDecimal price = priceByLogical.get(logicalName);
            step.put("unit_price", price == null ? meta.get("unit_price") : price);
            step.put("is_must_finish", meta.get("is_must_finish"));
            step.put("is_start_marker", meta.get("is_start_marker"));
            step.put("scope", meta.get("scope"));
            steps.add(step);
        }

        Map<String, Object> route = new LinkedHashMap<>();
        route.put("route_template_id", template.getId());
        route.put("route_template_name", template.getName());
        route.put("curtain_type", position);
        route.put("craft", craft);
        route.put("operation_count", steps.size());
        route.put("missing_operations", missing);
        route.put("operations", steps);
        return route;
    }

    /**
     * 回落默认模板时用来实例化的**部位**：优先 {@link #DEFAULT_CURTAIN_TYPE}（V54 起的事实默认、
     * 也是旧结构回落目标的部位维），否则取模板声明的第一个部位。
     *
     * <p>为什么不直接用订单派生的部位：库里可能根本没有那个部位的价目/工序行（如商家自建信号
     * 「罗马帘」）⇒ 适用性矩阵会把整条主线滤空 ⇒ **零工序的加工单**（工人扫不了码、也不报错）。</p>
     */
    private static String defaultPositionOf(ProductionRouteTemplate template) {
        List<String> positions = stringList(template.getPositions());
        if (positions.contains(DEFAULT_CURTAIN_TYPE)) {
            return DEFAULT_CURTAIN_TYPE;
        }
        return positions.isEmpty() ? DEFAULT_CURTAIN_TYPE : positions.get(0);
    }

    /** 把 {@code operation} 插到 {@code after} 之后（锚点不在序列中 ⇒ 追加末尾，同 {@code _insert_after}）。
     *
     * <p><b>唯一性 = 取代（issue #4577）</b>：用户裁定 2026-09-19 原话「**工序需要保证唯一**，比如工艺
     * 带了绑带，特殊选项又选择余料做绑带，得用**特殊选项中的余料做绑带替代绑带这个工序**，余料做绑带的
     * 目标工序也是绑带就能替换，**需要有这个前提**」。⇒ 判据 = <b>目标工序名相同</b>（前提）；
     * 语义 = <b>先移除序列里已有的该工序，再按本条规则的锚点插入</b>（<b>取代</b>，不是"跳过"）——
     * 跳过会让位置停留在<b>先应用</b>那条规则（可能是工艺的锚点），而商家选特殊选项的意图是
     * 「按这个选项的工序来」。结果 = 该工序在序列里<b>恰好出现一次</b>（盲插会让工人按两遍单价拿钱，
     * 同族事故 #4523）。规则应用顺序仍由 {@code priority} 决定（顺序语义未动）。</p> */
    private static List<String> insertAfterLogical(List<String> route, String operation, String after) {
        route.removeIf(op -> Objects.equals(op, operation));
        int idx = after == null ? -1 : route.indexOf(after);
        if (idx < 0) {
            route.add(operation);
            return route;
        }
        route.add(idx + 1, operation);
        return route;
    }

    /** JSONB 列归一化为 {@code List<String>}（{@code JacksonTypeHandler} 反序列化后可能是 {@code List<?>}）。 */
    private static List<String> stringList(Object raw) {
        List<String> names = new ArrayList<>();
        if (raw instanceof List<?> list) {
            for (Object item : list) {
                if (item != null) {
                    names.add(String.valueOf(item));
                }
            }
        }
        return names;
    }

    /**
     * 路线键（`curtain_type` + `craft`）+ 来源：**显式字段 &gt; 受控来源 &gt; 存量单信号兜底**
     * （issue #4354 落码「直读优先」，issue #4362 把「显式字段」升级为 {@code order_items} 的
     * craft spec 列，issue #4452 把第 2 层从「`contains` 猜文本」换成**受控来源**）。
     *
     * <p><b>取法优先级（三层，issue #4452 冻结口径）</b>：</p>
     * <ol>
     *   <li><b>显式字段</b>（最高）—— 订单行写下的部位/工艺。载体有两者、**同源**：
     *       {@code order_items.curtain_type} / {@code craft} <b>列</b>（V63 / issue #4362，结构化落库）
     *       与 {@code processing_info} 顶层的同键（issue #4354 起的旧载体，存量单）；
     *       列非空时在 {@link #buildSnapshot} 里覆盖同键 ⇒ 两维都在 ⇒ 来源 {@code direct}
     *       （**此时全程不读** {@code production_route_signals}）；</li>
     *   <li><b>受控来源</b>（第 2 层，issue #4452 新增）—— 显式字段缺的那一维由**结构化字段**补齐：
     *       部位 ← {@code componentRole} 受控枚举（{@link #COMPONENT_ROLE_POSITIONS}：{@code 纱} ⇒ 纱帘，
     *       {@code 主布}/{@code 配布边} ⇒ 布帘）；工艺 ← 加工项的**显式声明**
     *       {@code processing_items.craft_hint}（{@link #craftHintOf}）。
     *       ⚠️ **不再** `contains` 加工项名 / 加工项 options —— 那些是**商家可自定义的自由文本**，
     *       把判据绑在研发改的关键词表上就是「名词解释」（{@code craft-routing-customization.md} §4 P2）；</li>
     *   <li><b>存量单信号兜底</b>（第 3 层，**两维都缺**时才轮到）—— 存量的**订单行**上没有 V63 列值
     *       也没有 {@code componentRole} / {@code craft_hint}（老数据形态），此时才读
     *       {@code production_route_signals} 兜底；信号源**只剩加工项名 / 加工项 options**
     *       （商品名与销售方式已从判据里摘掉 —— 营销文案不是结构化输入）。
     *       三层都不命中 ⇒ 两维取**该租户的默认**（部位常量 / 默认工艺，来源 {@code default}，T1）。</li>
     * </ol>
     * <p>只补齐一维 ⇒ 来源 {@code partial}（补救动作 = 把另一维填进订单，或让加工项声明它）。</p>
     *
     * <p><b>信号表是「存量单兜底」，不是长期判据</b>（issue #4452）：表**不删**（存量单仍需派生），
     * 但新单两维都缺时按既有四/五态 {@code route_source} **显式标注**（{@code default}/{@code partial}）
     * 并由 {@code GET /production/orders/routing-anomalies} 列出可行动清单，**不静默落默认**。</p>
     *
     * <p><b>⚠️ P2b：缺 {@code craft} 取「商户级默认工艺」，不再写死常量（issue #4459 §1②）</b>：
     * {@code production_crafts} 的 {@code is_default} 行是**商家可配**的（改默认工艺 ⇒ 后续订单
     * 插入的工序与计件系数随之变）；该租户**没有**默认工艺 ⇒ 返回 {@code null}，
     * 由 {@link #resolveRoute} 走 T3 fail-closed（错误码 + suggestion 指名去「工艺配置」设默认），
     * **绝不**静默取常量 {@code 韩褶}（商户只做打孔时会插错工序 + 算错计件系数 = 错发工资）。</p>
     *
     * <p><b>⚠️ 派生路径**不退场**（用户裁定 2026-09-19「部位不是必填的」）</b>：S1 的字段全部可空
     * ⇒「没填部位/工艺的单」永远存在 ⇒ 第 2/3 层与信号映射表是**长期**兜底，**不是**临时桥。
     * 代码注释里旧表述「待订单侧补字段后本方法连同信号表一起退场」**已作废**，不得再按它写回。
     * 第 3 层同样**不是**可删项：它是「商家自定义加工项」的兜底面（issue #4308 已做成商家可配）。</p>
     *
     * <p><b>⚠️ 信号表已降级为「存量单兜底」（issue #4452）</b>：它**只在两维都缺**时才被读
     * ⇒ 新单（带 V63 列值 / {@code componentRole} / {@code craft_hint} 任一）**全程不读**它。
     * 表**不删**（存量单仍需派生），但不再是「长期判据」。</p>
     *
     * <p><b>为什么不校验显式字段的值</b>：它是订单侧已落库的真值，Java 只读不猜、不归一
     * （错值/库里无该部位模板 ⇒ 由 {@link #resolveRoute} 的 T2 显式落 {@code missing_route}
     * 并记 incident 日志，绝不静默）。空白键（{@code " "}）视为**缺键**（{@code str} 会 trim）——
     * 否则会造出「{@code  ×韩褶}」这种不存在的键。</p>
     *
     * <p><b>来源四态（V60，issue #4308 冻结口径；落 {@code processing_orders.route_source}）</b>：
     * {@code derived} = 两维都由库中信号映射命中（**只剩存量单**会走到这里）；
     * {@code partial} = 只补齐一维；{@code default} = 两维全不命中（T1）。
     * **本方法只产出这三态 + issue #4354 新增的 {@code direct}**；
     * 第五态 {@code missing_route}（T2 = 部位无模板而回落默认模板）由 {@link #resolveRoute}
     * 在回落时引入 —— 否则「回落过」与「本来就没派生」在数据上长得一模一样，
     * 而前者是错配高发形态。</p>
     */
    private RouteKey deriveRouteKey(Map<String, Object> entry, Long tenantId) {
        // ① 两维都直读 ⇒ direct（**不查**信号映射表：订单侧的真值优先于任何派生）
        String directCurtainType = str(entry.get("curtainType"));
        String directCraft = str(entry.get("craft"));
        // ⓪ 售卖形态 = **布料** ⇒ 部位维直读为 `布料`（第 4 个部位），**不走**部位派生链
        //    （issue #4529）：`componentRole` 受控枚举与存量信号表都是「窗帘部位」的口径
        //    （主布/配布边/纱、布/纱/帘头…），用在布料单上必然错配成窗帘路线。
        //    工艺维对布料单无意义（布料主线只有 配料/打包）⇒ 仍取该租户默认工艺，仅为满足
        //    T3 的既有护栏（缺 `craft` 且无默认工艺 ⇒ fail-closed，本单不放宽该护栏）。
        if (SALE_FORM_FABRIC.equals(str(entry.get("saleForm")))) {
            String fabricCraft = directCraft != null
                    ? directCraft : productionOperationQueryService.defaultCraft(tenantId);
            return new RouteKey(FABRIC_POSITION, fabricCraft, "direct");
        }
        if (directCurtainType != null && directCraft != null) {
            return new RouteKey(directCurtainType, directCraft, "direct");
        }
        // ② 受控来源补齐缺的那一维（issue #4452）：部位 ← componentRole 枚举；工艺 ← 加工项声明列。
        String curtainType = directCurtainType != null ? directCurtainType : positionOfComponentRole(entry);
        // 加工项的工艺声明**无条件校验**（用户裁定 2026-09-19「工艺单值护栏」）：不能等
        // 「显式 craft 为空」才读它 —— 下单页会把派生出的 craft 显式写回（route_source=direct），
        // 那时本行会短路 ⇒ 护栏失效、两个不同声明被静默取第一个。
        String declaredCraft = craftHintOf(entry);
        String craft = directCraft != null ? directCraft : declaredCraft;
        // ③ 两维都缺 ⇒ **存量单**（老数据没有 V63 列 / componentRole / craft_hint）才读信号表兜底。
        //    信号源只剩加工项名/options（商品名与销售方式已摘掉，见 signals()）。
        //    ⚠️ 本分支的**条件**就是「不读信号表」的判据：新单只要给出一维，本行不执行。
        if (curtainType == null && craft == null) {
            List<ProductionRouteSignal> mappings = productionOperationQueryService.routeSignals(tenantId);
            if (!mappings.isEmpty()) {
                List<String> signals = signals(entry);
                curtainType = firstSignalMatch(signals, mappings, true);
                craft = firstSignalMatch(signals, mappings, false);
            }
        }
        // ⚠️ 来源必须在**默认值补齐之前**算：补齐后 `craft != null` 恒真 ⇒ T1 会被误判成 partial
        // （「没人派生过」与「只补齐一维」是两种不同的补救动作）。
        String source;
        if (curtainType != null && craft != null) {
            // 有一维来自订单行显式字段/受控来源 ⇒ 补救动作 = 把另一维填进订单
            // （与「两维都由信号表派生」的 derived 区分开）
            source = directCurtainType != null || directCraft != null ? "partial" : "derived";
        } else if (curtainType != null || craft != null) {
            source = "partial";
        } else {
            source = "default";
        }
        // 缺 `craft` 的兜底 = **该租户的默认工艺**（商家可配，issue #4459 §1②）。
        // 该租户没有默认工艺 ⇒ 保持 null，由 resolveRoute 走 T3 fail-closed（**不写死常量 韩褶**）。
        if (craft == null) {
            craft = productionOperationQueryService.defaultCraft(tenantId);
        }
        return new RouteKey(curtainType == null ? DEFAULT_CURTAIN_TYPE : curtainType, craft, source);
    }

    /**
     * 部位维的**受控来源**（issue #4452）：{@code componentRole} 受控枚举 → 部位名。
     *
     * <p>受控枚举值见 {@link #COMPONENT_ROLE_POSITIONS}（写侧 {@code order_create.py} 的 enum：
     * 主布 / 配布边 / 纱）。**未知取值返回 null**（不猜、不默认成布帘）—— 该维按缺维处理，
     * 由 {@code route_source} 显式标注并在异常订单清单里可见。</p>
     */
    private static String positionOfComponentRole(Map<String, Object> entry) {
        String role = str(entry.get("componentRole"));
        // 缺键（存量单）/ 未知取值 ⇒ null（**不猜**）：Map.of 也不接受 null 键
        return role == null ? null : COMPONENT_ROLE_POSITIONS.get(role);
    }

    /**
     * 工艺维的**显式声明**（issue #4452）：取本行加工项在 {@code processing_items.craft_hint}
     * 里声明的工艺（{@link #buildSnapshot} 从加工项目录带进快照的 {@code craftHint} 键）。
     *
     * <p>都不声明 ⇒ 返回 null（该维按缺维处理）。</p>
     *
     * <p><b>声明了 ≥2 个**不同**工艺 ⇒ fail-closed（422）</b>（用户裁定 2026-09-19：「工艺单值护栏：
     * 每个部位最多一个声明工艺的加工项，两个 ⇒ fail-closed」，否则同一单会派生出**两套工序**
     * —— 工人按两遍单价拿钱）。本方法**只认「不同」**：同一工艺被多个加工项声明（如「韩折」与
     * 「韩定+S钩」都声明韩褶）是**合法**的，不算冲突。</p>
     *
     * <p>为什么护栏落在这里而不是下单接口：路线键的工艺维**只在派生时**被消费（危害发生点），
     * 而下单接口不读加工项目录（读它要给 {@code OrderService} 引入目录依赖）。前端另有**同口径**
     * 的预防（勾第二个带工艺的加工项时自动取消前一个并提示）。</p>
     */
    @SuppressWarnings("unchecked")
    static String craftHintOf(Map<String, Object> entry) {
        if (!(entry.get("processingItems") instanceof List<?> items)) {
            return null;
        }
        List<String> hints = new ArrayList<>();
        for (Object raw : items) {
            if (raw instanceof Map<?, ?> item) {
                String hint = str(((Map<String, Object>) item).get("craftHint"));
                if (hint != null && !hints.contains(hint)) {
                    hints.add(hint);
                }
            }
        }
        if (hints.size() > 1) {
            // 错误码复用 ERR_ROUTING_NOT_FOUND：失败语义就是「这张单的工艺维定不下来 ⇒ 路线取不到」，
            // 不新增契约面（前端已按该码提示；见 docs/wiki/CONTRACT-LEDGER.md）。
            throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                    String.format("本行加工项声明了多个工艺（%s）—— 一张单只能有一个工艺，"
                            + "否则同一单会派生出两套工序", String.join(" / ", hints)),
                    422,
                    "请在订单里只保留一个带工艺的加工项（如「韩折」或「打孔」），其余取消勾选");
        }
        return hints.isEmpty() ? null : hints.get(0);
    }

    /**
     * 订单侧可派生信号，**顺序即推导链的第 2/3 层**（命中即止，外层先说话）：
     * <ol>
     *   <li><b>加工项推导</b>（issue #4362 冻结的第 2 层）：加工项**名**（加工项目录里工序名自带
     * **存量单兜底**信号（issue #4452 起**只剩加工项名 / 加工项 options**，命中即止）：
     * <ol>
     *   <li>加工项**名**（老订单行上工序名自带部位/工艺，如「韩褶-布」「打孔-纱」「帘头制作」）；</li>
     *   <li>加工项 **options**（如「四爪钩」）。</li>
     * </ol>
     *
     * <p>⚠️ <b>商品名与销售方式**已摘掉**</b>（issue #4452 交付判据 4）：它们是**营销文案**，
     * 不是结构化输入 —— 旧实现去商品名里 {@code contains '纱'} 判部位，正是本单要消灭的
     * 「名词解释」。同时「加工项比商品名权威」这个相对次序判据随之作废（商品名不再参与）。</p>
     *
     * <p>本方法**只在两维都缺时**被调用（见 {@link #deriveRouteKey}）⇒ 它不再参与新单的路线键。</p>
     */
    @SuppressWarnings("unchecked")
    private static List<String> signals(Map<String, Object> entry) {
        List<String> signals = new ArrayList<>();
        if (entry.get("processingItems") instanceof List<?> items) {
            for (Object raw : items) {
                if (raw instanceof Map<?, ?> item) {
                    String name = str(((Map<String, Object>) item).get("name"));
                    if (name != null) {
                        signals.add(name);
                    }
                }
            }
            for (Object raw : items) {
                if (raw instanceof Map<?, ?> item && item.get("options") instanceof List<?> options) {
                    for (Object option : options) {
                        if (option != null) {
                            signals.add(String.valueOf(option));
                        }
                    }
                }
            }
        }
        return signals;
    }

    /**
     * 第一个命中的映射值（信号**外层**、映射行**内层** —— 与迁移前的常量表扫描逐字同序：
     * 更权威的信号先说话；同一信号内按 {@code priority} 取位次最靠前的那条）。
     *
     * @param curtain true = 只扫帘种行（{@code curtain_type} 非空），false = 只扫工艺行
     */
    private static String firstSignalMatch(List<String> signals, List<ProductionRouteSignal> mappings, boolean curtain) {
        for (String signal : signals) {
            for (ProductionRouteSignal mapping : mappings) {
                String target = curtain ? mapping.getCurtainType() : mapping.getCraft();
                String keyword = mapping.getSignal();
                if (target != null && keyword != null && signal.contains(keyword)) {
                    return target;
                }
            }
        }
        return null;
    }

    /**
     * 路线键 + 来源（{@code direct} 两维直读订单工艺规格 / {@code derived} 两维都由信号映射命中 /
     * {@code partial} 只命中或只直读一维 / {@code default} 全不命中 —— **本 record 只产出这四态**，
     * 第五态 {@code missing_route} 由 {@link #resolveRoute} 在「键在库中无路线而回落」时引入）。
     */
    private record RouteKey(String curtainType, String craft, String source) {
    }

    /**
     * 一次路线解析的结果：**实际使用**的路线 + **派生出来想用**的键 + 来源（V60，issue #4308）。
     * 三者必须同源返回 —— 分两次算必然漂移（「用的路线」与「记下来的键」对不上就白记了）。
     *
     * @param routeKey          实际使用的路线键（= 派生出来的那个；T1 时 = 布帘×该租户默认工艺）
     * @param routeRequestedKey 想用的路线键（派生/直读出来的那个）；两维全不命中（source=default）时 null
     * @param routeSource       direct / derived / partial / missing_route / default
     */
    private record RouteResolution(Map<String, Object> route, String routeKey,
                                   String routeRequestedKey, String routeSource) {
    }

    /**
     * 部位派生的**多部位 roll-up**（V60，issue #4308 冻结口径）：{@code processing_orders} 只有单值
     * {@code route_key} / {@code route_requested_key} / {@code route_source} 列，而一张单可能有多个
     * 部位（各自一条路线）⇒ 取**最需关注**的那一条，次序 {@code default} &gt; {@code missing_route}
     * &gt; {@code partial} &gt; {@code derived}：
     * <ol>
     *   <li>{@code default}（3）—— 两维全不命中 = **零信息**下的默认路线：不知道该怎么走，
     *       错配无从预判（罗马帘订单今天就落在这一层）；</li>
     *   <li>{@code missing_route}（2）—— 知道该走哪条、库里却没有 ⇒ 走了默认路线，工序与计件工资**可能整体错**；</li>
     *   <li>{@code partial}（1）—— 只命中/只直读一维 ⇒ 键可能错，补另一维即可；</li>
     *   <li>{@code derived} / {@code direct}（0）—— 无异常。</li>
     * </ol>
     * 同档取先出现者（稳定）。逐部位明细在工序实例里，这里只回答「这张单有没有需要人看的东西」。
     *
     * <p>{@code direct}（issue #4354）与 {@code derived} **同档**：两者都不是「需要人看」的形态，
     * 故不新增档位、不改既有相对次序；混档时按行序取先出现者（与「两个 derived 之间」的既有取法一致）。</p>
     */
    private static int severity(String routeSource) {
        return switch (routeSource == null ? "default" : routeSource) {
            case "derived", "direct" -> 0;
            case "partial" -> 1;
            case "missing_route" -> 2;
            default -> 3; // default 及其它未知取值：按最需关注处理（不静默降级）
        };
    }

    // ============================================================ 存量单恢复 / 打印计数

    /**
     * **异常订单清单**（issue #4452 交付物 ④）：{@code route_source ∈ {default, partial}} 的加工单
     * 逐条可查 —— 加工单号 + **实际使用键** + **请求键** + **可行动文案**。
     *
     * <p><b>为什么必须有它</b>：信号映射退场后，「部位/工艺是猜的或没填」这件事**必须有可观测面**
     * —— 否则退场只是把静默错配从「猜错」换成「悄悄落默认」（两者用户侧都看不见）。
     * 五态 {@code route_source} 早就在库里，但**没有清单** ⇒ 商家不知道要去看哪张单。</p>
     *
     * <p><b>两只清单的补救动作不同</b>（这就是不能把两者合并的原因）：</p>
     * <ul>
     *   <li>{@code default}（两维全不命中 = 零信息）⇒ 去下单侧**把部位与工艺填上**
     *       （或让加工项声明它的工艺 {@code craft_hint}）；</li>
     *   <li>{@code partial}（只补齐一维）⇒ 把**缺的那一维**填上。</li>
     * </ul>
     *
     * <p>{@code missing_route} **不在本清单**：它不是「订单没填」而是「库里缺路线」
     * ⇒ 由既有 {@code GET /production/routing-gaps} 承担（补救 = 建路线）。</p>
     *
     * @return {@code {total, orders:[{processing_order_no, order_id, route_key,
     *         route_requested_key, route_source, suggestion}]}}
     */
    public Map<String, Object> routingAnomalies(Long tenantId) {
        List<ProcessingOrder> rows = processingOrderMapper.selectList(
                new LambdaQueryWrapper<ProcessingOrder>()
                        .eq(ProcessingOrder::getTenantId, tenantId)
                        .eq(ProcessingOrder::getDeleted, 0)
                        .in(ProcessingOrder::getRouteSource, List.of("default", "partial"))
                        .orderByAsc(ProcessingOrder::getCreatedAt));
        List<Map<String, Object>> orders = new ArrayList<>();
        for (ProcessingOrder row : rows == null ? List.<ProcessingOrder>of() : rows) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("processing_order_no", row.getProcessingOrderNo());
            entry.put("order_id", row.getOrderId());
            entry.put("route_key", row.getRouteKey());
            entry.put("route_requested_key", row.getRouteRequestedKey());
            entry.put("route_source", row.getRouteSource());
            entry.put("suggestion", "default".equals(row.getRouteSource())
                    ? "这张单的部位与工艺都没填 ⇒ 系统取了默认路线。请在下单侧补上部位（帘种）与工艺，"
                            + "或给加工项声明它的工艺（craft_hint），再重新生成加工单"
                    : "这张单只填了一维（部位或工艺）⇒ 另一维取了默认。请把缺的那一维补上再重新生成加工单");
            orders.add(entry);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", orders.size());
        result.put("orders", orders);
        return result;
    }

    /**
     * 按订单派生工序实例 payload（issue #4202）——{@code POST /api/admin/production/orders/{orderId}/instantiate}
     * 的 {@code positions} 缺省路径复用**生成加工单时的同一份**解析：
     * {@link #buildSnapshot}（订单明细 → 部位/工艺信号）+ {@link #buildPositionPayload}（工序库路线）。
     *
     * <p>为什么必须复用而不是另写一份：存量单（生成于 #4116「生成即实例化」之前，工序实例与
     * {@code qr_token} 双空）补工序时，派生的路线/单价/必完标记必须与**新建单**逐字同源 ——
     * 第二份路线解析必然与 {@link #generateOne} 漂移（关键字表/默认路线/fail-closed 三处口径）。</p>
     *
     * <p>取不到路线、或路线引用的工序在库中缺行时**同样 fail-closed**
     * （{@link #ERR_ROUTING_NOT_FOUND} / {@link #ERR_OPERATION_NOT_FOUND} + suggestion），
     * 绝不静默返回空 payload（那会让调用方落一个「有加工单、零工序」的空壳）。</p>
     *
     * @return 与 {@code instantiate} 请求体里 {@code positions} 同构的列表
     */
    public List<Map<String, Object>> derivePositionPayload(String rawOrderId, Long tenantId) {
        Order order = resolveOrder(rawOrderId, tenantId);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        return buildPositionPayload(buildSnapshot(loadOrderItems(order.getId(), tenantId), tenantId), tenantId)
                .positions();
    }

    /**
     * 记录一次任务卡打印（issue #4202 边角修复）——{@code processing_orders.print_count} 此前
     * **零写方**（全仓只有建单时的 {@code printCount(0)} 与响应映射）⇒ 真值源 §1「记录打印次数」
     * 在数据层不可观测。SQL 内原子自增（并发多标签页打印不丢计数），返回递增后的计数。
     *
     * @param rawId 加工单 id / 加工单号 / 订单 id（与 {@link #getDetail} 同一解析口径）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> recordPrint(String rawId, Long tenantId) {
        ProcessingOrder po = resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            throw BusinessException.notFound("加工单");
        }
        processingOrderMapper.incrementPrintCount(po.getId(), tenantId, OffsetDateTime.now());
        ProcessingOrder after = processingOrderMapper.selectById(po.getId());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", po.getOrderId());
        result.put("processing_order_no", po.getProcessingOrderNo());
        result.put("print_count", after == null ? null : after.getPrintCount());
        return result;
    }

    private static String str(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    /**
     * 快照构建（五要素 + options；不含销售价——决策 2）。
     * 加工项 options 下单时未落库，此处从加工项目录补齐（设计文档查漏点 1）。
     *
     * <p><b>craft spec + 算料输出（issue #4354，设计文档 §4.9）</b>：订单侧自 #4346 起把工艺规格与
     * 算料输出落在 {@code processing_info} 顶层；本方法**逐键**取（{@code copyIfPresent}）——
     * 新键不加进白名单就**不会进快照**，而快照是加工单的**固化真相**（生成时的条件工序与计件系数
     * 都从它读）⇒ 漏一个键 = 车间少一道活 / 少一个展示字段，事后补不回来。
     * 逐键透传的代价是「缺键就缺」（存量单没有这些键）—— **不造值**是硬约束。</p>
     */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        for (OrderItem item : items) {
            // 归一化：processingInfo 可能是 Map（BaseMapper 路径）或 JSON 字符串（自定义 @Select 路径）
            Map<String, Object> pi = normalizeProcessingInfo(item.getProcessingInfo());
            List<Map<String, Object>> procs = extractProcessingItems(pi);
            if (procs.isEmpty()) {
                continue;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            // 明细行 id：拼色绑组的组键来源（§4.8 的 craftLineId 取「主布行的 order_item.id」）
            entry.put("itemId", item.getId());
            entry.put("productName", item.getProductName());
            entry.put("quantity", item.getQuantity());
            entry.put("width", item.getWidth());
            entry.put("height", item.getHeight());
            // 销售信息（与加工项同存 processing_info，前端写入）
            copyIfPresent(pi, entry, "sku");
            copyIfPresent(pi, entry, "skuCode", "sku");
            copyIfPresent(pi, entry, "colorName");
            copyIfPresent(pi, entry, "sellingMethod");
            copyIfPresent(pi, entry, "doorWidth");
            copyIfPresent(pi, entry, "unit");
            // 特殊选项（issue #4230 v1a）：订单侧**新携带** specialOptions: string[]，
            // 落在既有 processingInfo JSONB 内（**无需迁移**）；加工单快照透传一份，
            // 生成时的条件工序/计件系数都从快照读（快照是加工单的固化真相）。
            copyIfPresent(pi, entry, "specialOptions");
            // 工艺规格 + 算料输出（issue #4354）：全键逐字透传（缺键就缺）
            for (String key : CRAFT_SPEC_SNAPSHOT_KEYS) {
                copyIfPresent(pi, entry, key);
            }
            for (String key : CALC_OUTPUT_SNAPSHOT_KEYS) {
                // 取值键名可能与落键键名不同（formula_text ← processing_info.formulaText，issue #4555）
                copyIfPresent(pi, entry, CALC_OUTPUT_SOURCE_KEY_ALIASES.getOrDefault(key, key), key);
            }
            // 显式字段覆盖（V63，issue #4362，S1）：order_items 的 craft spec **列**最后叠加 ——
            // 推导链的**最高优先级**是「显式字段」，JSONB 键是存量单的旧载体（同一事实的两种落法）。
            // 列非空即覆盖同名的 JSONB 键；列全空（存量单 / 未填）⇒ 本行是 no-op，
            // 快照与迁移前**逐字相同** ⇒ 派生路径不受影响（它是长期兜底，不退场）。
            entry.putAll(OrderLineCraftFields.toSnapshotKeys(item));
            // 加工项明细 + options 补齐
            List<Map<String, Object>> itemsWithOptions = new ArrayList<>();
            for (Map<String, Object> p : procs) {
                Map<String, Object> enriched = new LinkedHashMap<>(p);
                Object id = p.get("id");
                if (id != null) {
                    ProcessingItem piEntity = processingItemMapper.selectById(String.valueOf(id));
                    if (piEntity != null) {
                        enriched.put("options", piEntity.getOptions());
                        if (!enriched.containsKey("unit")) {
                            enriched.put("unit", piEntity.getUnit());
                        }
                        // 加工项**显式声明**的工艺（V78，issue #4452）：路线键「工艺」维的受控来源。
                        // 缺省 ⇒ 不落键（缺键就是缺键，派生链再走存量兜底 —— 不造值）。
                        if (piEntity.getCraftHint() != null && !piEntity.getCraftHint().isBlank()) {
                            enriched.put("craftHint", piEntity.getCraftHint().trim());
                        }
                    }
                }
                itemsWithOptions.add(enriched);
            }
            entry.put("processingItems", itemsWithOptions);
            snapshot.add(entry);
        }
        return snapshot;
    }

    private void copyIfPresent(Map<String, Object> from, Map<String, Object> to, String key) {
        copyIfPresent(from, to, key, key);
    }

    /**
     * processing_info 归一化：Map 直接用；JSON 字符串（自定义 @Select 路径，不经过
     * JacksonTypeHandler）解析为 Map；其它形态返回 null。
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> normalizeProcessingInfo(Object processingInfo) {
        if (processingInfo instanceof Map) {
            return (Map<String, Object>) processingInfo;
        }
        if (processingInfo instanceof String s && !s.isBlank()) {
            try {
                return objectMapper.readValue(s, Map.class);
            } catch (Exception e) {
                log.warn("processingInfo JSON 字符串解析失败: {}", e.getMessage());
            }
        }
        return null;
    }

    private void copyIfPresent(Map<String, Object> from, Map<String, Object> to, String fromKey, String toKey) {
        Object v = from.get(fromKey);
        if (v != null) {
            to.put(toKey, v);
        }
    }

    /**
     * 加载订单明细（走 BaseMapper，确保 processing_info 经 JacksonTypeHandler 反序列化为 Map）。
     * issue #3340 验收实战：自定义 @Select（selectByOrderId）不应用 typeHandler，
     * processing_info 以 JSON 字符串返回 → buildSnapshot 恒空 → 误判「无加工项」。
     */
    private List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, orderId)
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getDeleted, 0));
        return items != null ? items : java.util.Collections.emptyList();
    }

    /** 解析 processing_info 的加工项列表（与 OrderService.extractProcessingItems 同语义，兼容 JSON 字符串） */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> extractProcessingItems(Object processingInfo) {
        Map<String, Object> normalized = normalizeProcessingInfo(processingInfo);
        if (normalized == null) {
            return java.util.Collections.emptyList();
        }
        try {
            Object raw = normalized.get("processingItems");
            if (!(raw instanceof List)) {
                return java.util.Collections.emptyList();
            }
            List<Map<String, Object>> result = new ArrayList<>();
            for (Object element : (List<Object>) raw) {
                if (element instanceof Map) {
                    result.add(new LinkedHashMap<>((Map<String, Object>) element));
                }
            }
            return result;
        } catch (Exception e) {
            log.warn("解析 processingInfo 失败: {}", e.getMessage());
            return java.util.Collections.emptyList();
        }
    }

    private Order resolveOrder(String rawId, Long tenantId) {
        Order byId = orderMapper.selectById(rawId);
        if (byId != null && tenantId.equals(byId.getTenantId())) {
            return byId;
        }
        return orderMapper.selectOne(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getOrderNo, rawId)
                .eq(Order::getDeleted, 0)
                .last("LIMIT 1"));
    }

    private String generateOrderNo() {
        String base = "JG-" + LocalDate.now().format(PO_DATE_FMT) + "-";
        // DB 唯一约束兜底；此处随机化降低同秒碰撞概率
        return base + String.format("%04d", PO_SEQ.incrementAndGet());
    }

    // ============================================================ 状态更新

    /**
     * 加工单状态更新（action: issue/start/complete/cancel）。
     * 状态机校验 + 订单联动（issue → 订单 confirmed→producing；cancel → 订单 producing→confirmed 回退）。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProcessingOrderResponse updateStatus(String rawId, ProcessingOrderUpdateRequest req,
                                                Long tenantId, String operator) {
        if (req == null || !StringUtils.hasText(req.getAction())) {
            throw BusinessException.validationError("action 不能为空");
        }
        ProcessingOrder po = resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            throw BusinessException.notFound("加工单");
        }
        String action = req.getAction();
        String target;
        switch (action) {
            case "issue": target = "issued"; break;
            case "start": target = "in_processing"; break;
            case "complete": target = "completed"; break;
            case "cancel": target = "cancelled"; break;
            default: throw BusinessException.validationError("无效的加工单操作: " + action);
        }
        String current = po.getStatus();
        if (!STATUS_TRANSITIONS.getOrDefault(current, Set.of()).contains(target)) {
            throw BusinessException.validationError(String.format(
                    "加工单状态不允许从 [%s] 变更为 [%s]", label(current), label(target)));
        }
        if ("cancel".equals(action) && !StringUtils.hasText(req.getReason())) {
            throw BusinessException.validationError("取消加工单必须填写原因");
        }

        ProcessingOrder upd = ProcessingOrder.builder().id(po.getId()).status(target).build();
        OffsetDateTime now = OffsetDateTime.now();
        switch (action) {
            case "issue":
                // issue #3901：交期不允许早于今天（前端 date 控件之外的兜底，同时覆盖 agent processing_order_update 路径）
                if (req.getExpectedDeliveryDate() != null
                        && req.getExpectedDeliveryDate().isBefore(LocalDate.now())) {
                    throw BusinessException.validationError("交付日期不能早于今天");
                }
                upd.setIssuedAt(now);
                upd.setProcessor(req.getProcessor());
                upd.setExpectedDeliveryDate(req.getExpectedDeliveryDate());
                break;
            case "start":
                upd.setInProcessingAt(now);
                break;
            case "complete":
                upd.setCompletedAt(now);
                break;
            case "cancel":
                upd.setCancelledAt(now);
                upd.setCancelledReason(req.getReason());
                break;
            default:
                break;
        }
        // 联动先行（issue #4305，用户裁定「发加工 = 订单进入生产中」）：**发加工是订单
        // confirmed→producing 的唯一时点**（生成加工单不再推进订单）。先推进订单、再落加工单
        // issued —— 落库失败时回退订单状态，杜绝「订单生产中、加工单未发出」孤儿态
        // （形态 = #3345 P2② 给 generate 的同款 fail-closed，现随联动一并挪到这里）。
        // 已是 producing 的订单（旧语义下「生成即推进」的存量数据）不重复推进、也不回退。
        boolean orderLinked = false;
        if ("issue".equals(action)) {
            Order order = orderMapper.selectById(po.getOrderId());
            if (order != null && "confirmed".equals(order.getStatus())) {
                orderService.updateOrderStatus(order.getId(), "producing");
                orderLinked = true;
            }
        }
        try {
            processingOrderMapper.updateById(upd);
        } catch (Exception e) {
            if (orderLinked) {
                try {
                    orderService.revertProducingToConfirmed(po.getOrderId(), "加工单发加工落库失败，订单状态回退");
                } catch (Exception revertErr) {
                    log.warn("发加工落库失败且订单状态回退失败: orderId={}, err={}",
                            po.getOrderId(), revertErr.getMessage());
                }
            }
            throw e;
        }
        // 联动：加工单取消（未发货）→ 订单 producing→confirmed 回退（重新可生成加工单）
        if ("cancel".equals(action)) {
            Order order = orderMapper.selectById(po.getOrderId());
            if (order != null && "producing".equals(order.getStatus())) {
                orderService.revertProducingToConfirmed(order.getId(),
                        "加工单 " + po.getProcessingOrderNo() + " 取消，订单回退已确认");
                log.info("加工单取消联动回退订单: po={}, orderId={}", po.getProcessingOrderNo(), order.getId());
            }
        }
        log.info("加工单状态变更: no={}, {} -> {}, operator={}", po.getProcessingOrderNo(), current, target, operator);
        return getDetail(po.getId(), tenantId);
    }

    private String label(String status) {
        return STATUS_LABELS.getOrDefault(status, status);
    }

    private ProcessingOrder resolveProcessingOrder(String rawId, Long tenantId) {
        return processingOrderMapper.selectOne(new LambdaQueryWrapper<ProcessingOrder>()
                .eq(ProcessingOrder::getTenantId, tenantId)
                .eq(ProcessingOrder::getDeleted, 0)
                .and(w -> w.eq(ProcessingOrder::getId, rawId)
                        .or().eq(ProcessingOrder::getProcessingOrderNo, rawId)
                        .or().eq(ProcessingOrder::getOrderId, rawId))
                .last("LIMIT 1"));
    }

    // ============================================================ 查询

    public List<ProcessingOrderResponse> list(String keyword, String status, Long tenantId) {
        List<ProcessingOrder> list;
        if (StringUtils.hasText(keyword)) {
            list = processingOrderMapper.selectByKeyword(keyword.trim(), tenantId);
        } else {
            LambdaQueryWrapper<ProcessingOrder> wrapper = new LambdaQueryWrapper<ProcessingOrder>()
                    .eq(ProcessingOrder::getTenantId, tenantId)
                    .eq(ProcessingOrder::getDeleted, 0)
                    .orderByDesc(ProcessingOrder::getCreatedAt)
                    .last("LIMIT 100");
            if (StringUtils.hasText(status)) {
                wrapper.eq(ProcessingOrder::getStatus, status);
            }
            list = processingOrderMapper.selectList(wrapper);
        }
        Map<String, Order> orders = loadOrders(list);
        List<ProcessingOrderResponse> result = new ArrayList<>();
        for (ProcessingOrder po : list) {
            result.add(toResponse(po, tenantId, orders.get(po.getOrderId())));
        }
        return result;
    }

    /**
     * 批量取回列表所需的订单（issue #4304）。
     *
     * <p><b>为什么必须批量</b>：列表此前逐行调用 {@link #toResponse(ProcessingOrder, Long)}，
     * 而后者内部 {@code orderMapper.selectById(po.getOrderId())} 只为拿
     * orderNo/customerName/customerPhone ⇒ N 行 N 次单查。实测 31 行的列表请求里
     * {@code FROM orders} 单行查询 63 条、本地耗时 ~2.0s（云 dev DB 每跳几十毫秒）。
     * 这里一次 {@code IN} 取回（{@code selectBatchIds}），逐行按 orderId 建映射。</p>
     *
     * <p><b>租户过滤不在本方法</b>：{@code selectBatchIds} 与 {@code selectById} 同为 BaseMapper
     * 标准方法，租户条件由 {@code TenantLineInnerInterceptor} 注入、软删由 {@code Order} 的
     * {@code @TableLogic} 兜底 ⇒ 与单查同口径，不因批量而放宽。</p>
     */
    private Map<String, Order> loadOrders(List<ProcessingOrder> list) {
        Set<String> orderIds = new LinkedHashSet<>();
        for (ProcessingOrder po : list) {
            if (po.getOrderId() != null) {
                orderIds.add(po.getOrderId());
            }
        }
        if (orderIds.isEmpty()) {
            return Map.of();
        }
        List<Order> orders = orderMapper.selectBatchIds(orderIds);
        Map<String, Order> byId = new HashMap<>();
        if (orders != null) {
            for (Order order : orders) {
                byId.put(order.getId(), order);
            }
        }
        return byId;
    }

    public ProcessingOrderResponse getDetail(String rawId, Long tenantId) {
        ProcessingOrder po = resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            // 订单还没有加工单是正常状态（issue #3887）：rawId 若能解析为有效订单（tenant 隔离），
            // 返回 null → ApiResponse.success(null) → 前端 ProcessingOrderBlock 走
            // res.data?.data ?? null / setNotFound(!data) 展示「生成加工单」态；
            // 订单也不存在（真无效 ID）才保持 404。
            if (resolveOrder(rawId, tenantId) == null) {
                throw BusinessException.notFound("加工单");
            }
            return null;
        }
        return toResponse(po, tenantId);
    }

    /**
     * 单条路径（详情/状态变更）：按 {@code po.getOrderId()} 单查订单。
     * 行为与 #4304 之前逐字相同 —— 列表路径改用 {@link #toResponse(ProcessingOrder, Long, Order)}
     * 批量取回的订单，两条路径的响应字段口径共用同一段映射。
     */
    private ProcessingOrderResponse toResponse(ProcessingOrder po, Long tenantId) {
        return toResponse(po, tenantId, orderMapper.selectById(po.getOrderId()));
    }

    @SuppressWarnings("unchecked")
    private ProcessingOrderResponse toResponse(ProcessingOrder po, Long tenantId, Order order) {
        ProcessingOrderResponse resp = new ProcessingOrderResponse();
        resp.setId(po.getId());
        resp.setTenantId(String.valueOf(po.getTenantId()));
        resp.setOrderId(po.getOrderId());
        resp.setProcessingOrderNo(po.getProcessingOrderNo());
        resp.setProcessor(po.getProcessor());
        resp.setExpectedDeliveryDate(po.getExpectedDeliveryDate());
        resp.setStatus(po.getStatus());
        resp.setRemark(po.getRemark());
        resp.setTemplateVersion(po.getTemplateVersion());
        resp.setGeneratedAt(po.getGeneratedAt());
        resp.setIssuedAt(po.getIssuedAt());
        resp.setInProcessingAt(po.getInProcessingAt());
        resp.setCompletedAt(po.getCompletedAt());
        resp.setCancelledAt(po.getCancelledAt());
        resp.setCancelledReason(po.getCancelledReason());
        resp.setPrintCount(po.getPrintCount());
        // 路线可观测（V60，issue #4308）：详情 API 必须能查出「实际走哪条 / 想走哪条 / 怎么来的」
        resp.setRouteKey(po.getRouteKey());
        resp.setRouteRequestedKey(po.getRouteRequestedKey());
        resp.setRouteSource(po.getRouteSource());
        // 订单信息（列表路径由调用方批量取回后传入，单条路径传入单查结果；null 时字段留空，同旧行为）
        if (order != null) {
            resp.setOrderNo(order.getOrderNo());
            resp.setCustomerName(order.getCustomerName());
            resp.setCustomerPhone(order.getCustomerPhone());
        }
        // 快照解析（兼容 JSON 字符串：自定义 @Select 查询路径不经过 typeHandler）
        Object snapshot = po.getItemsSnapshot();
        if (snapshot instanceof String s && !s.isBlank()) {
            try {
                snapshot = objectMapper.readValue(s, Object.class);
            } catch (Exception e) {
                log.warn("加工单快照 JSON 字符串解析失败: po={}, err={}", po.getProcessingOrderNo(), e.getMessage());
                snapshot = null;
            }
        }
        if (snapshot != null) {
            try {
                resp.setItems(objectMapper.convertValue(snapshot,
                        objectMapper.getTypeFactory().constructCollectionType(List.class,
                                ProcessingOrderResponse.ProcessingOrderItemBrief.class)));
            } catch (Exception e) {
                log.warn("加工单快照解析失败: po={}, err={}", po.getProcessingOrderNo(), e.getMessage());
            }
        }
        return resp;
    }

    // ============================================================ 生成结果

    @lombok.Data
    public static class GenerateResult {
        private final String orderRef;
        private final boolean success;
        private final String message;
        private final String processingOrderNo;
        /**
         * 失败时的业务错误码（issue #4116 切库：库取不到工序 ⇒ {@link #ERR_ROUTING_NOT_FOUND} /
         * {@link #ERR_OPERATION_NOT_FOUND}）。此前逐单 catch 只留 message ⇒ 错误码在接口层不可见，
         * 调用方只能靠中文文案分辨失败原因。成功时为 null（不进 JSON，Jackson 默认排除 null）。
         */
        private final String code;
        /** 失败时的可行动建议（同 {@code BusinessException.suggestion} 的口径）；成功时为 null。 */
        private final String suggestion;

        public static GenerateResult ok(String orderRef, String no) {
            return new GenerateResult(orderRef, true, null, no, null, null);
        }

        public static GenerateResult fail(String orderRef, String message) {
            return new GenerateResult(orderRef, false, message, null, null, null);
        }

        /** 带错误码与建议的失败结果（fail-closed 场景：调用方要能机器分辨原因并照着建议修库）。 */
        public static GenerateResult fail(String orderRef, String code, String message, String suggestion) {
            return new GenerateResult(orderRef, false, message, null, code, suggestion);
        }
    }
}
