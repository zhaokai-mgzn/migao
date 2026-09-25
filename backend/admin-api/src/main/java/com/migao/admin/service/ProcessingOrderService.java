package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.dto.ProductionPoolViews;
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
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
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
 * + {@code production_operations}（分组/单位/作用域；「必完标记」自 issue #4961 起不再参与实例化与完工判定），经
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
     * 批次消耗台账（V116，issue #5145 阶段 1）：派工扣批次 + 作废回补。
     *
     * <p>用<b>字段注入</b>而不是构造参数：本类构造签名被 5 处测试显式装配
     * （{@code ProcessingOrderServiceTest} / {@code ProcessingRouteSourceDeclarationTest} /
     * {@code ProductionControllerTest} / {@code ProductionRoutingReadControllerTest} /
     * {@code ProcessingOrderDetailNoProcOrderTest}），加参数会把它们全改一遍 ——
     * 本单的改动面不应扩到既有测试装配（同 {@code ProductionController.processingFeeQueryService}
     * 的先例与理由）。Spring 生产装配下该依赖一定非 null；真装配不上时
     * {@link #batchStock()} **显式抛错**，绝不静默跳过扣减。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired
    private StockBatchConsumptionService stockBatchConsumptionService;

    /**
     * 工序库查不到「部位×工艺」路线时的错误码（fail-closed）。
     * 可见位置：① 生成加工单的响应 `GenerateResult.message`（`success=false` 的原文）；
     * ② 服务层日志 `INCIDENT_PRODUCTION_ROUTING_UNRESOLVED`（incident 级，按此串检索）。
     */
    public static final String ERR_ROUTING_NOT_FOUND = "PRODUCTION_ROUTING_NOT_FOUND";

    /**
     * 规则的第 4 档触发类型（issue #4962）：**部位维** —— {@code trigger_value} = 部位名
     * （取值 = {@link ProductionOperationQueryService#POSITION_LIMIT_VOCABULARY}）。
     *
     * <p>写面把它**镜像**进 {@code production_route_rules.position} 列（列才是「限哪个部位」的
     * 唯一判据），因此实例化侧只看列、不看 kind —— 见 {@link #rulePositionMatches}。</p>
     */
    public static final String TRIGGER_KIND_POSITION = "position";

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
     * （设计文档 §4.3）：它们是**展示/复核**用键（每片褶数、理论/实际褶倍），算料端点按
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
            // 用料公式 / 算料档位（issue #4874；**issue #4878 独立复核 P1 补进白名单**）：
            // 下单页与 agent 都把它们写进 `processing_info`（写侧键），但**不加进本白名单就不会进快照**
            // ⇒ 加工单看不出「这单按哪个公式/哪一档算的料」——而 `order-craft-fields.ts` 与
            // `CONTRACT-LEDGER` 都已对外承诺「随单落库、加工单要能看出档位」。
            // ⚠️ `pleatSpacing`（褶距）**保留**：写侧已退役，但存量单仍靠它回显（读侧容错）。
            "formula", "craftTier",
            // 售卖形态（issue #4529）：`saleForm === '布料'` ⇒ 选**布料基础路线**（第 4 部位）。
            // 与「部位/工艺」同一载体（`processing_info` 顶层，订单侧下单时原样落库）——
            // 不进白名单 ⇒ 派生链读不到它 ⇒ 布料单永远落窗帘路线。
            "saleForm");

    /**
     * **订单级**字段进加工单快照的键（issue #5177 范围 5「透传」）—— 与
     * {@link #CRAFT_SPEC_SNAPSHOT_KEYS} **同族**（都是「生成那一刻的固化真相」），
     * 但**取数面不同**：那一个键族的来源是 {@code order_items.processing_info}（**行级**），
     * 本组键的来源是 **{@code orders} 行**（**订单级**）⇒ 不能塞进同一个 List
     * （那个 List 由 {@code copyIfPresent(pi, entry, key)} 逐键取，订单级键塞进去会**恒取不到**
     * = 静默缺行，而快照是加工单的固化真相、事后补不回来）。
     *
     * <p>落点 = {@link #stampOrderUrgency}（在 {@code prepare} 里、加工单 insert **之前**盖章，
     * 与 {@code stampCuttingPlan} / {@code stampAssignedBatches} 同一时机纪律）。</p>
     *
     * <p>⚠️ 新键**必须**同时进 {@code ProcessingOrderResponse.ProcessingOrderItemBrief} ——
     * 快照里出现 DTO 没声明的键会让 {@code items} 整段解析失败（响应静默退化）。</p>
     */
    private static final String SNAPSHOT_ORDER_URGENT = "isUrgent";

    /** 订单级**客户要求到货日**的快照键（{@code YYYY-MM-DD}；**缺值不落键**）。见 {@link #SNAPSHOT_ORDER_URGENT}。 */
    private static final String SNAPSHOT_ORDER_REQUIRED_DELIVERY_DATE = "requiredDeliveryDate";

    /**
     * 智能派单的**唯一**排序口径（issue #5177 判据 5「排序是真实消费者」）。
     *
     * <h2>键序（每一把都有理由，且都不是「单号序」）</h2>
     * <ol>
     *   <li><b>到货日升序，{@code null} 排最后</b> —— 这是 {@code required_delivery_date} 的
     *       <b>第一个真实消费者</b>：临期的先派。{@code null}（未指定）**不得**当成最紧急
     *       （把未知排在最前，等于让没填过日期的单永远插队）；</li>
     *   <li><b>等待时长降序</b> —— 等得久的先派（「不得静默压单」的方向）；</li>
     *   <li><b>进池时刻升序</b> / <b>单号升序</b> —— 只为**确定性**（同一份数据两次读必须在
     *       同一序上，否则看板会自己抖）。</li>
     * </ol>
     *
     * <h2>为什么「缺省不变」也成立（判据 1/2）</h2>
     * 没有任何加急单、没有任何到货日时，第 1 把键恒相等 ⇒ 退化为
     * 「等待时长降序 → 进池时刻升序 → 单号升序」，而 {@code waitHours} 是
     * {@code now − created_at} 的单调函数（分钟粒度）⇒ 与今天「按 {@code created_at} 升序遍历」
     * 的序**逐值相同**；同一张单内的多行由 {@link java.util.List#sort} 的**稳定性**保持原插入序。
     *
     * <p>🔴 <b>不得**改成单号序（或任何与加急/临期无关的键）</b>：那样看板看着正常，
     * 而「临期先派」这个能力静默消失（红证见 {@code PoolBoardOrderingTest}）。</p>
     */
    static final Comparator<ProductionPoolViews.PoolLine> POOL_LINE_ORDER = Comparator
            .comparing(ProductionPoolViews.PoolLine::requiredDeliveryDate,
                    Comparator.nullsLast(Comparator.naturalOrder()))
            .thenComparing(ProductionPoolViews.PoolLine::waitHours, Comparator.reverseOrder())
            .thenComparing(ProductionPoolViews.PoolLine::waitingSince,
                    Comparator.nullsLast(Comparator.naturalOrder()))
            .thenComparing(ProductionPoolViews.PoolLine::orderId,
                    Comparator.nullsLast(Comparator.naturalOrder()));

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

    // ============================================================ 池化（issue #5169 = 阶段 2b-1）

    /**
     * 🔴 <b>池化开关的缺省值 = 关</b>（issue #5169 判据 1）。
     *
     * <p>不启用池化 ⇒ 行为与今天**逐值相同**（逐单派；含错误文案与结果顺序）。这不是保守：
     * 记录期基线正建立在「指派行为不变」之上（#5145/#5158/#5167 一路同款），
     * 池化窗口一开，攒下来的可比性就没了。</p>
     *
     * <p>开关只有这一个载体（{@code ProductionPoolRequest.pooled} 是显式入参，
     * 缺省值**不在 DTO 上**再写一遍 —— 两处缺省值必然漂移）。红证 = 把它改为 {@code true}
     * ⇒ 「不传 pooled == 逐单派」的判据当场变红（见 {@code PooledDispatchTest}）。</p>
     */
    public static final boolean POOLED_DEFAULT_ENABLED = false;

    /**
     * 池内滞留上限的**缺省值**（小时）—— 可配：请求参数 {@code maxWaitHours} 覆盖它。
     *
     * <p>为什么是请求参数而不是租户级配置表：本单「能不加迁移就不加」（池的判定口径与读面
     * 全部复用既有 {@code orders} / {@code processing_orders} 状态），而滞留上限是**看板口径**
     * （多早开始告警），不是生产口径 —— 它不影响任何落账数值。传非正数 ⇒ 显式拒绝
     * （不静默回落本值，见 {@link #maxWaitHours}）。</p>
     */
    public static final BigDecimal DEFAULT_POOL_MAX_WAIT_HOURS = new BigDecimal("24");

    /** 池化开关归一：{@code null} ⇒ 缺省（{@link #POOLED_DEFAULT_ENABLED}）。**唯一**的缺省值解析点。 */
    public static boolean pooledEnabled(Boolean requested) {
        return requested == null ? POOLED_DEFAULT_ENABLED : requested;
    }

    /**
     * 待派池视图（issue #5169 判据 5 的可查面）。
     *
     * <h2>池的定义（唯一口径）</h2>
     * <b>已确认支付</b>（{@code orders.status = 'confirmed'} —— 与「仅已确认订单可生成加工单」同一道闸）
     * 且 **无活跃加工单**（排除口径与 {@code uk_processing_orders_active} 逐字相同）。
     * 无加工部位的单（配件/赠品行、无加工项）**不进池**：它们本来就不会生成加工单，
     * 进池只会让「池里有单却派不了」变成噪声。
     *
     * <h2>等待时长的口径（**不猜**，照实登记）</h2>
     * {@code waitHours = now − orders.created_at}。系统**没有**记录「支付时刻」（{@code orders}
     * 无 {@code paid_at}/{@code confirmed_at} 列）⇒ 用下单时刻作**上界**口径：它只会把等待算得**更久**、
     * 不会假装刚进池 —— 「不得静默压单」要的是**早**告警，故取保守方向。
     *
     * <h2>加急单**不进池**（issue #5177 判据 3）</h2>
     * {@code orders.is_urgent = true} 的单**不进** {@link ProductionPoolViews.Pool#groups()}
     * （= 不成批候选），而是进 {@link ProductionPoolViews.Pool#urgentLines()}（插队区）——
     * 用户裁定「允许加急的订单直接派，不加急的同批次候选池优先」。
     * ⇒ 看板对加急行的动作是**立刻单派**（{@code /dispatch} + {@code pooled=false}）；
     * 把它勾进 {@code pooled=true} 的批次会被 {@link #assertNoUrgentInPooledBatch} **整批拒绝**。
     *
     * @param maxWaitHoursRaw 滞留上限（小时）；{@code null} ⇒ {@link #DEFAULT_POOL_MAX_WAIT_HOURS}，
     *                        非正数 ⇒ 显式拒绝（见 {@link #maxWaitHours}）
     */
    public ProductionPoolViews.Pool pool(Long tenantId, BigDecimal maxWaitHoursRaw) {
        BigDecimal maxWaitHours = maxWaitHours(maxWaitHoursRaw);
        List<Order> confirmed = orderMapper.selectList(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getDeleted, 0)
                .eq(Order::getStatus, "confirmed")
                .orderByAsc(Order::getCreatedAt)
                .orderByAsc(Order::getId));
        if (confirmed == null) {
            confirmed = List.of();
        }
        List<String> ids = new ArrayList<>();
        for (Order order : confirmed) {
            if (order.getId() != null) {
                ids.add(order.getId());
            }
        }
        Set<String> dispatched = ids.isEmpty() ? Set.of()
                : new LinkedHashSet<>(processingOrderMapper.selectActiveOrderIds(tenantId, ids));

        OffsetDateTime now = OffsetDateTime.now();
        LocalDate today = LocalDate.now();
        // 物料键 → 行；顺序 = 先出现的物料在前（确定性输出，便于看板与快照比对）
        Map<String, List<ProductionPoolViews.PoolLine>> linesByMaterial = new LinkedHashMap<>();
        Map<String, String[]> materialOf = new LinkedHashMap<>();
        List<ProductionPoolViews.PoolWarning> warnings = new ArrayList<>();
        // 池内（非加急）与**加急插队区**分开装：加急单**不进池**（issue #5177 判据 3）
        Set<String> ordersInPool = new LinkedHashSet<>();
        Set<String> urgentOrders = new LinkedHashSet<>();
        List<ProductionPoolViews.PoolLine> urgentLines = new ArrayList<>();
        int lineCount = 0;
        for (Order order : confirmed) {
            if (order.getId() == null || dispatched.contains(order.getId())) {
                continue;
            }
            List<OrderItem> items = loadOrderItems(order.getId(), tenantId);
            List<Map<String, Object>> snapshot = buildSnapshot(items, tenantId);
            if (snapshot.isEmpty()) {
                continue;
            }
            Map<String, String> productIdByItemId = new LinkedHashMap<>();
            for (OrderItem item : items) {
                if (item.getId() != null) {
                    productIdByItemId.put(item.getId(), item.getProductId());
                }
            }
            BigDecimal waitHours = hoursBetween(order.getCreatedAt(), now);
            boolean overdue = waitHours.compareTo(maxWaitHours) > 0;
            if (overdue) {
                // 「不得静默压单」= 超上限这件事**必须带着对象名字说出来**（哪张单、等了多久、该做什么），
                // 而不是一个数不清对象的计数。**加急单同样告警** —— 它更不该被压住。
                warnings.add(new ProductionPoolViews.PoolWarning(order.getId(), order.getOrderNo(),
                        waitHours, String.format(
                        "订单 %s 已等待派单 %s 小时（超过上限 %s 小时）：请合并派单或单独派单"
                                + "（不要一直压着不派）",
                        order.getOrderNo(), waitHours.toPlainString(), maxWaitHours.toPlainString())));
            }
            boolean urgent = Boolean.TRUE.equals(order.getIsUrgent());
            LocalDate requiredDeliveryDate = order.getRequiredDeliveryDate();
            Integer deliveryDaysLeft = deliveryDaysLeft(requiredDeliveryDate, today);
            for (Map<String, Object> row : snapshot) {
                String itemId = str(row.get("itemId"));
                BigDecimal required = StockQuantity.toStockScaleByCeiling(
                        row.get("quantity") instanceof BigDecimal q ? q : null);
                if (itemId == null || required.signum() <= 0) {
                    continue;
                }
                String productId = productIdByItemId.get(itemId);
                String skuCode = snapshotSkuCode(row);
                ProductionPoolViews.PoolLine line = new ProductionPoolViews.PoolLine(
                        order.getId(), order.getOrderNo(), itemId, productId, str(row.get("productName")),
                        skuCode, required, order.getCreatedAt(), waitHours, overdue,
                        urgent, requiredDeliveryDate, deliveryDaysLeft);
                if (urgent) {
                    // 🔴 加急单**不进池**（用户裁定「允许加急的订单直接派，不加急的同批次候选池优先」）：
                    // 它的去处是插队区（看板上一个动作 = 立刻单派），**不是**成批候选。
                    urgentLines.add(line);
                } else {
                    String key = materialKey(productId, skuCode);
                    materialOf.putIfAbsent(key, new String[]{productId, skuCode});
                    linesByMaterial.computeIfAbsent(key, k -> new ArrayList<>()).add(line);
                    lineCount++;
                }
            }
            if (urgent) {
                urgentOrders.add(order.getId());
            } else {
                ordersInPool.add(order.getId());
            }
        }
        // 智能派单排序（判据 5 的唯一落点）：插队区与每个物料组**各自**按同一把键排（见 POOL_LINE_ORDER）
        urgentLines.sort(POOL_LINE_ORDER);
        List<ProductionPoolViews.PoolGroup> groups = new ArrayList<>();
        for (Map.Entry<String, List<ProductionPoolViews.PoolLine>> entry : linesByMaterial.entrySet()) {
            String[] material = materialOf.get(entry.getKey());
            Set<String> groupOrders = new LinkedHashSet<>();
            BigDecimal required = BigDecimal.ZERO;
            for (ProductionPoolViews.PoolLine line : entry.getValue()) {
                groupOrders.add(line.orderId());
                required = required.add(line.requiredMeters());
            }
            List<ProductionPoolViews.PoolLine> lines = new ArrayList<>(entry.getValue());
            lines.sort(POOL_LINE_ORDER);
            groups.add(new ProductionPoolViews.PoolGroup(entry.getKey(), material[0], material[1],
                    groupOrders.size(), required, List.copyOf(lines)));
        }
        return new ProductionPoolViews.Pool(maxWaitHours, POOLED_DEFAULT_ENABLED, ordersInPool.size(),
                lineCount, warnings.size(), urgentOrders.size(), List.copyOf(warnings),
                List.copyOf(urgentLines), List.copyOf(groups));
    }

    /**
     * 成批预览（issue #5169 判据 4「预览不说谎」）—— **只读**，不建加工单、不落台账。
     *
     * <p>🔴 它跑的是与 {@code /dispatch}（{@code pooled=true}）**同一条**准备链与**同一个**
     * {@code plan} 求解器、同一份入参 ⇒ 预览里的 {@code savedMeters} 与派单后落账的
     * {@code Σ saved_meters} 是**同一个数**，不是两套口径（两套口径正是「预览说谎」的成因）。</p>
     *
     * <p><b>同样 fail-closed</b>：池级累计余量不足 ⇒ 显式报错（不静默给一份派不出去的方案）；
     * 订单不存在 / 状态不对 / 已有加工单 / 指派行不在快照里 ⇒ 同样显式拒绝（与派单同一批判据）。</p>
     */
    public ProductionPoolViews.Preview preview(Long tenantId, List<String> orderIds,
                                               List<BatchAssignment> batches, String assignmentRule) {
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        String normalizedRule = StockBatchConsumptionService.normalizeAssignmentRule(assignmentRule);
        String rule = StringUtils.hasText(assignmentRule) ? normalizedRule : null;
        Map<String, List<BatchAssignment>> byOrder = assignmentsByOrder(orderIds, batches);
        // 🔴 加急单不进池（判据 3）—— 预览是**成批**的预览：让它预览一个**派不出去**的批次
        // 就是「预览说谎」（判据 4）⇒ 与 /dispatch 同一条闸、同一处口径。
        assertNoUrgentInPooledBatch(orderIds, tenantId);
        List<Prepared> prepared = new ArrayList<>();
        List<StockBatchConsumptionService.Designation> pooledLines = new ArrayList<>();
        for (String rawId : orderIds) {
            Prepared p = prepare(rawId, byOrder.getOrDefault(rawId, List.of()), tenantId, null, rule);
            prepared.add(p);
            pooledLines.addAll(p.designations());
        }
        List<StockBatchConsumptionService.Deduction> pooledPlan = batchStock().plan(tenantId, pooledLines);
        BigDecimal formula = StockQuantity.sum(
                pooledPlan.stream().map(StockBatchConsumptionService.Deduction::formulaMeters).toList());
        BigDecimal pooledPlanned = StockQuantity.sum(
                pooledPlan.stream().map(StockBatchConsumptionService.Deduction::plannedMeters).toList());
        // 对照读数：**逐单派**的应领合计（池化**新增**的收益 = 两者之差 —— 不把 #5158 已有的
        // 单订单内并排算成池化的功劳）
        BigDecimal perOrderPlanned = BigDecimal.ZERO;
        for (Prepared p : prepared) {
            perOrderPlanned = perOrderPlanned.add(StockQuantity.sum(
                    batchStock().plan(tenantId, p.designations()).stream()
                            .map(StockBatchConsumptionService.Deduction::plannedMeters).toList()));
        }
        return new ProductionPoolViews.Preview(prepared.size(), rule, formula, pooledPlanned,
                formula.subtract(pooledPlanned), perOrderPlanned,
                perOrderPlanned.subtract(pooledPlanned));
    }

    /** 滞留上限归一：缺省用 {@link #DEFAULT_POOL_MAX_WAIT_HOURS}；非正数 ⇒ **显式拒绝**（不静默回落）。 */
    private static BigDecimal maxWaitHours(BigDecimal raw) {
        if (raw == null) {
            return DEFAULT_POOL_MAX_WAIT_HOURS;
        }
        if (raw.signum() <= 0) {
            throw BusinessException.validationError(
                    "maxWaitHours 必须为正数（实际 " + raw.toPlainString() + "）");
        }
        return raw;
    }

    /**
     * 等待时长（小时，1 位小数）= {@code now − orders.created_at}。
     *
     * <p>取 {@code created_at} 的理由与保守方向见 {@link #pool}；时间倒挂（时钟回拨 / 脏数据）
     * ⇒ 记 0 而不是负数（负的等待时长在读面上无法解释，且会让「超上限」恒为假 = 静默压单）。</p>
     */
    private static BigDecimal hoursBetween(OffsetDateTime from, OffsetDateTime to) {
        if (from == null) {
            return BigDecimal.ZERO;
        }
        long minutes = Duration.between(from, to).toMinutes();
        if (minutes < 0) {
            minutes = 0;
        }
        return BigDecimal.valueOf(minutes).divide(BigDecimal.valueOf(60), 1, RoundingMode.HALF_UP);
    }

    /** 物料键（商品 × 颜色 × 门幅）。{@code skuCode} 在本系统里就是「颜色 × 门幅」的组合。 */
    private static String materialKey(String productId, String skuCode) {
        return (productId == null ? "" : productId) + "|" + (skuCode == null ? "" : skuCode);
    }

    /**
     * 到货日**临期度**（天）= 到货日 − 今天；负数 = **已逾期**；{@code null} = **未指定**。
     *
     * <p>服务端算、前端只渲染 —— 「临期」是看板的口径，在浏览器里再算一遍就是第二份口径
     * （一处改了另一处不跟 = 看板与排序对不上，且没有任何东西会变红）。</p>
     */
    private static Integer deliveryDaysLeft(LocalDate required, LocalDate today) {
        return required == null ? null : (int) ChronoUnit.DAYS.between(today, required);
    }

    /**
     * 把**订单级**的加急标记与客户要求到货日写进快照每一行（issue #5177 范围 5「透传」）。
     *
     * <h2>为什么落在每一行而不是加工单顶层</h2>
     * 加工单快照的载体是 {@code processing_orders.items_snapshot}（**行数组**，没有订单级顶层对象），
     * 而读面（{@code ProcessingOrderResponse.ProcessingOrderItemBrief}）逐行解析
     * ⇒ 订单级事实只能逐行固化。供 **2b-3** 的事件驱动兜底与分段评估读。
     *
     * <h2>缺值口径（与 {@code processing_info} 键族同一纪律）</h2>
     * {@code isUrgent} **恒落键**：列 {@code NOT NULL DEFAULT FALSE} ⇒ {@code false} 是**真值**
     * （「明确不加急」），不是「未填」—— 写侧不得把它当未填丢弃（#4874 硬约束 1）。
     * {@code requiredDeliveryDate} **缺值不写**：NULL = 未指定，写空串/占位会把「未指定」
     * 读成一个日期（快照是固化真相，读的人无从分辨）。
     */
    static void stampOrderUrgency(List<Map<String, Object>> snapshot, Order order) {
        if (snapshot.isEmpty() || order == null) {
            return;
        }
        boolean urgent = Boolean.TRUE.equals(order.getIsUrgent());
        String date = order.getRequiredDeliveryDate() == null
                ? null : order.getRequiredDeliveryDate().toString();
        for (Map<String, Object> row : snapshot) {
            row.put(SNAPSHOT_ORDER_URGENT, urgent);
            if (date != null) {
                row.put(SNAPSHOT_ORDER_REQUIRED_DELIVERY_DATE, date);
            }
        }
    }

    /**
     * 🔴 加急单**不进池**（issue #5177 判据 3）—— 成批（{@code pooled=true}）批次里出现加急单
     * ⇒ **整批显式拒绝**，且**一行都不写**（在任何只读准备与写库之前判完）。
     *
     * <h2>为什么是「拒绝」而不是「静默把加急单剔出去」</h2>
     * 静默剔除 = **静默少派**：商家勾了 3 张单、点了成批，回来 2 张加工单而没有任何提示
     * ⇒ 第 3 张单被压住且无人知道（同族纪律：「不得静默少扣 / 不得静默压单」）。
     * 拒绝带上**订单号**与**可行动处置**（单独派 = 插队；或先取消加急）。
     *
     * <p>查不到的单**不在这里报错**：{@code ORDER_NOT_FOUND} 由逐单路径按既有文案报
     * （本方法只补「加急」这一条新判据，不改既有失败面与失败顺序）。</p>
     */
    private void assertNoUrgentInPooledBatch(List<String> orderIds, Long tenantId) {
        List<String> urgent = new ArrayList<>();
        for (String rawId : orderIds) {
            Order order = resolveOrder(rawId, tenantId);
            if (order != null && Boolean.TRUE.equals(order.getIsUrgent())) {
                urgent.add(order.getOrderNo() == null ? rawId : order.getOrderNo());
            }
        }
        if (!urgent.isEmpty()) {
            throw BusinessException.validationError(
                    "加急单不参与合并派单，请单独派：" + String.join("、", urgent),
                    List.of(),
                    "请把这几个加急单单独派单（立即派 = 单订单派单），"
                            + "或先取消它们的加急标记再合并派单");
        }
    }

    // ============================================================ 事件驱动自动成批（issue #5182 = 阶段 2b-3）

    /**
     * 🔴 <b>自动成批派单的缺省值 = 关</b>（issue #5182 判据 1）。
     *
     * <p>不启用 ⇒ 与今天**逐值相同**（{@link #autoBatchDispatch} 在开关为假时
     * <b>零读零写</b>立刻返回，三个事件挂载点只多一句永不抛的
     * {@link PoolChangeNotifier#notifySafely}）。这不是保守：记录期基线正建立在
     * 「指派与派单行为不变」之上（#5145/#5158/#5167/#5169/#5177 一路同款）。</p>
     *
     * <p>开关只有这一个载体（Spring 属性 {@code migao.production.auto-batch.enabled} 覆盖它，
     * 属性缺失 ⇒ 本值）—— 红证 = 把它改为 {@code true} ⇒「默认关」那条判据当场变红。</p>
     */
    public static final boolean AUTO_BATCH_DEFAULT_ENABLED = false;

    /** 成批条件①的缺省阈值：能填满某批次 ≥ X%（按该批次**入库量**为分母）。 */
    public static final int AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT = 80;

    /** 成批条件②的缺省阈值：能让某批次余量收敛到 ≤ N 米（与余量分布四档的 `≤0.2m` 同界）。 */
    public static final String AUTO_BATCH_DEFAULT_CONVERGE_METERS = "0.2";

    /** 成批条件③的缺省阈值：池内同物料需求 ≥ 最小批量（米）。 */
    public static final String AUTO_BATCH_DEFAULT_MIN_BATCH_METERS = "30";

    /** 业务兜底的缺省「标准生产周期」（天）：`最晚派单日 = 到货日 − 本值`；无到货日 ⇒ `进池日 + 本值`。 */
    public static final int AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS = 7;

    /**
     * 自动成批采用的批次指派规则（#5167）缺省 = {@code fifo}。
     *
     * <p>🔴 <b>不改 #5167 的缺省口径</b>：手工路径「不传规则 ⇒ 未指定批次的行不补位、
     * 显式拒绝」一字未动。这里是**自动路径显式传** {@code fifo}（自动成批没有文员来挑批次；
     * 传了规则才把「系统建议值」升级为「直接采用」）—— 两件事不同层。</p>
     */
    public static final String AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE = "fifo";

    /** 自动派单落进 {@code processing_orders.generated_by} 的前缀（**可审计**的持久痕迹）。 */
    public static final String AUTO_BATCH_OPERATOR_PREFIX = "auto:";

    /**
     * 定时腿（到期扫描）的触发原因 —— {@code generated_by} 上的第五个取值，也是**唯一**一个
     * **非事件**触发的原因（issue #5184）。
     *
     * <p>前四个（{@link PoolChangeNotifier} 的四类）都是「某件业务刚发生」⇒ 顺带评估一次；
     * 本值是「**什么都没发生**，但有单已经过了最晚派单日」⇒ 定时腿兜底把它派出去。
     * 两者的持久痕迹因此天然可区分：{@code auto:order_confirmed:fifo} vs
     * {@code auto:due_scan:fifo}。</p>
     */
    public static final String AUTO_BATCH_TRIGGER_DUE_SCAN = "due_scan";

    // 自动成批的生效策略：属性缺失 ⇒ 上面的代码缺省（**唯一**的缺省值表；不在别处再写一遍）。
    @Value("${migao.production.auto-batch.enabled:" + AUTO_BATCH_DEFAULT_ENABLED + "}")
    private boolean autoBatchEnabled = AUTO_BATCH_DEFAULT_ENABLED;
    @Value("${migao.production.auto-batch.fill-ratio-percent:"
            + AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT + "}")
    private int autoBatchFillRatioPercent = AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT;
    @Value("${migao.production.auto-batch.converge-meters:"
            + AUTO_BATCH_DEFAULT_CONVERGE_METERS + "}")
    private String autoBatchConvergeMeters = AUTO_BATCH_DEFAULT_CONVERGE_METERS;
    @Value("${migao.production.auto-batch.min-batch-meters:"
            + AUTO_BATCH_DEFAULT_MIN_BATCH_METERS + "}")
    private String autoBatchMinBatchMeters = AUTO_BATCH_DEFAULT_MIN_BATCH_METERS;
    @Value("${migao.production.auto-batch.standard-cycle-days:"
            + AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS + "}")
    private int autoBatchStandardCycleDays = AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS;
    @Value("${migao.production.auto-batch.assignment-rule:"
            + AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE + "}")
    private String autoBatchAssignmentRule = AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE;

    /**
     * 自动成批的生效策略（成批条件 ①②③ + 业务兜底 + 指派规则）。
     *
     * @param enabled            总开关；{@code false} ⇒ 零读零写（判据 1）
     * @param fillRatioPercent   条件①：`需求米数 ≥ X% × 该批次入库量`
     * @param convergeMeters     条件②：`0 ≤ 该批次余量 − 需求米数 ≤ N`
     * @param minBatchMeters     条件③：`池内同物料需求 ≥ 最小批量`
     * @param standardCycleDays  业务兜底的标准生产周期（天）
     * @param assignmentRule     自动路径显式采用的指派规则（#5167）
     * @param maxWaitHours       智能派单的滞留上限（沿用 #5169 的请求参数缺省）
     */
    public record AutoBatchPolicy(boolean enabled, int fillRatioPercent, BigDecimal convergeMeters,
                                  BigDecimal minBatchMeters, int standardCycleDays,
                                  String assignmentRule, BigDecimal maxWaitHours) {

        /** 缺省关（与 {@link #AUTO_BATCH_DEFAULT_ENABLED} 同源，供测试与调用方构造显式策略用）。 */
        public static AutoBatchPolicy defaults() {
            return new AutoBatchPolicy(AUTO_BATCH_DEFAULT_ENABLED,
                    AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT,
                    new BigDecimal(AUTO_BATCH_DEFAULT_CONVERGE_METERS),
                    new BigDecimal(AUTO_BATCH_DEFAULT_MIN_BATCH_METERS),
                    AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS,
                    AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE, DEFAULT_POOL_MAX_WAIT_HOURS);
        }

        /** 同 {@link #defaults()} 但**开着**（测试与「显式开启」的唯一入口）。 */
        public static AutoBatchPolicy enabledPolicy() {
            return new AutoBatchPolicy(true, AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT,
                    new BigDecimal(AUTO_BATCH_DEFAULT_CONVERGE_METERS),
                    new BigDecimal(AUTO_BATCH_DEFAULT_MIN_BATCH_METERS),
                    AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS,
                    AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE, DEFAULT_POOL_MAX_WAIT_HOURS);
        }

        public AutoBatchPolicy with(int fillRatio, String converge, String minBatch, int cycleDays) {
            return new AutoBatchPolicy(enabled, fillRatio, new BigDecimal(converge),
                    new BigDecimal(minBatch), cycleDays, assignmentRule, maxWaitHours);
        }
    }

    /**
     * 一次「评估并按需成批」的**读数与痕迹**（判据 6 的审计面 + 判据 10 的可查面）。
     *
     * @param enabled           本次是否真的评估了（{@code false} ⇒ 缺省关，零动作）
     * @param trigger           触发原因（{@link PoolChangeNotifier} 的四类）
     * @param rule              本次生效的指派规则
     * @param reasons           **命中的规则**逐条（按哪条规则派的：条件①/②/③/加急/业务到期）
     * @param dispatchedOrderNos 派出去的加工单号（派了哪几张单）
     * @param failedOrderIds    最终仍失败的单
     * @param failures          逐条可行动失败文案
     */
    public record AutoBatchOutcome(boolean enabled, String trigger, String rule, List<String> reasons,
                                   List<String> dispatchedOrderNos, List<String> failedOrderIds,
                                   List<String> failures) {
    }

    /** 自动成批的生效策略（Spring 属性覆盖代码缺省；见 {@link AutoBatchPolicy}）。 */
    public AutoBatchPolicy autoBatchPolicy() {
        return new AutoBatchPolicy(autoBatchEnabled, autoBatchFillRatioPercent,
                new BigDecimal(autoBatchConvergeMeters), new BigDecimal(autoBatchMinBatchMeters),
                autoBatchStandardCycleDays, autoBatchAssignmentRule, DEFAULT_POOL_MAX_WAIT_HOURS);
    }

    /**
     * 🔴 <b>本单的核心：事件到达 ⇒ 即刻重算「现在能不能凑出值得成批的组合」 ⇒ 满足即成批。</b>
     *
     * <h2>主触发是业务事件，不是计时器（判据 2）</h2>
     * 调用方只有 {@link AutoBatchDispatchListener}（{@code AFTER_COMMIT} 的事件监听器）。
     * 本方法里**没有**任何定时器、没有「窗口到点」判定、没有等待时长门槛
     * —— 攒单是**优化**，业务约束才是死线。
     *
     * <h2>三段（顺序即优先级）</h2>
     * <ol>
     *   <li><b>加急</b>（判据 5）：加急单**永不入池**（{@code pool()} 已把它们放进插队区）
     *       ⇒ 这里**逐单立即派**（{@code pooled=false}，复用 #5177 已落的手动插队路径）。</li>
     *   <li><b>成批</b>：按物料组判成批条件 ①②③，满足**任一** ⇒ 该组的订单进成批候选
     *       （一次动作池级求解 = 跨订单成组）。</li>
     *   <li><b>业务兜底（不可取消）</b>：{@code 最晚派单日 = 到货日 − 标准生产周期}；
     *       无到货日 ⇒ {@code 进池日 + 标准生产周期}。到日 ⇒ **必派**（不看条件）。
     *       🔴 这是「不压单」的**唯一**死线 —— 与「池化窗口超时」无关。</li>
     * </ol>
     *
     * <h2>fail-soft（判据 10 / 用户裁定「不能损失客户」）</h2>
     * 逐单失败后**降级重试**两次：② 逐单 + 规则（池级累计余量不足时逐单多半够）
     * → ③ 逐单 + 不带规则（#5145 之前的缺省形态：不碰批次账）。批次/排料是**优化**，
     * 绝不是「这张单今天派不出去」的理由。三级都失败才记失败并留 incident 痕迹。
     *
     * <h2>幂等（判据 7）</h2>
     * 派出去的单立刻有了活跃加工单 ⇒ 下一次评估时 `pool()` **看不见它们**
     * （口径与 {@code uk_processing_orders_active} 逐字相同）⇒ 重复触发天然无动作；
     * 并发双触发则由 {@code selectActiveByOrderId} + 唯一索引兜底（第二路记失败，不重复扣）。
     */
    public AutoBatchOutcome autoBatchDispatch(Long tenantId, String trigger) {
        return autoBatchDispatch(tenantId, trigger, autoBatchPolicy());
    }

    /** 显式策略版本（测试与「按租户/按次覆盖」的入口；{@code null} ⇒ {@link #autoBatchPolicy()}）。 */
    public AutoBatchOutcome autoBatchDispatch(Long tenantId, String trigger, AutoBatchPolicy policyRaw) {
        AutoBatchPolicy policy = policyRaw == null ? autoBatchPolicy() : policyRaw;
        if (tenantId == null || !policy.enabled()) {
            // 🔴 判据 1：缺省关 ⇒ **零读零写**（连池都不查）⇒ 与今天逐值相同
            return new AutoBatchOutcome(false, trigger, null, List.of(), List.of(), List.of(), List.of());
        }
        String rule = StockBatchConsumptionService.normalizeAssignmentRule(policy.assignmentRule());
        String operator = AUTO_BATCH_OPERATOR_PREFIX + trigger + ":" + rule;
        List<String> reasons = new ArrayList<>();
        List<String> dispatched = new ArrayList<>();
        List<String> failedIds = new ArrayList<>();
        List<String> failures = new ArrayList<>();

        ProductionPoolViews.Pool pool = pool(tenantId, policy.maxWaitHours());
        Map<String, List<ProductionPoolViews.PoolLine>> linesByOrder = linesByOrderOf(pool);

        // ① 加急单永不入池 ⇒ 自动**立即派**（逐单、pooled=false —— 判据 5）
        for (ProductionPoolViews.PoolLine line : pool.urgentLines()) {
            String orderId = line.orderId();
            if (orderId == null || !linesByOrder.containsKey(orderId)) {
                continue;
            }
            reasons.add("order=" + line.orderNo() + ":urgent_never_pooled");
            List<ProductionPoolViews.PoolLine> lines = linesByOrder.remove(orderId);
            collect(dispatchAuto(List.of(orderId), assignmentsOf(lines), tenantId, operator, rule, false),
                    trigger, dispatched, failedIds, failures);
        }

        // ② 成批条件（任一满足即成批）：按**物料组**判、按**订单**派（一单一加工单是既有约束）
        List<String> batchOrderIds = new ArrayList<>();
        for (ProductionPoolViews.PoolGroup group : pool.groups()) {
            String reason = batchConditionReason(group, tenantId, policy);
            if (reason == null) {
                continue;
            }
            reasons.add(reason);
            for (ProductionPoolViews.PoolLine line : group.lines()) {
                if (line.orderId() != null && !batchOrderIds.contains(line.orderId())) {
                    batchOrderIds.add(line.orderId());
                }
            }
        }
        // 一单一加工单：派一张单会带上它的**全部**行（含未命中条件的另一物料组）
        // ⇒ 指派也按「该单的全部池行」装配（否则另一物料组会被静默漏扣）。
        if (!batchOrderIds.isEmpty()) {
            collect(dispatchAuto(batchOrderIds, assignmentsOf(pluck(linesByOrder, batchOrderIds)),
                            tenantId, operator, rule, true),
                    trigger, dispatched, failedIds, failures);
        }

        // ③ 业务兜底（**不可取消**）：最晚派单日已到 ⇒ 必派（判据 4）
        //   ⇒ 与定时腿（issue #5184）**共用同一实现**（dispatchDueOrders）：判定写两遍必然漂移，
        //     而「到日必派」一旦分叉，就会出现「事件腿认为到期、定时腿认为没到期」的静默压单。
        dispatchDueOrders(linesByOrder, tenantId, trigger, operator + ":due", policy, rule,
                reasons, dispatched, failedIds, failures);

        return new AutoBatchOutcome(true, trigger, rule, List.copyOf(reasons),
                List.copyOf(dispatched), List.copyOf(failedIds), List.copyOf(failures));
    }

    /**
     * 🔴 <b>定时腿的唯一入口（issue #5184）：只做业务兜底 —— 已过最晚派单日的池内订单 ⇒ 必派。</b>
     *
     * <h2>它<b>不是</b>什么（这条区分写在这里，因为做反了就正好是用户要去掉的东西）</h2>
     * <ul>
     *   <li>它<b>不</b>判成批条件 ①②③：那三条是**优化参数**（值不值得现在凑一批），
     *       定时腿是**兜底**、不是主触发 —— 主触发仍是业务事件（{@code AutoBatchDispatchListener}）。
     *       ⇒ 定时腿**只**跑第 ③ 段（{@code dispatchDueOrders}），与事件腿逐字同一实现。</li>
     *   <li>它<b>不</b>读「池化窗口 / 等待时长上限」（{@code maxWaitHours} / {@code PoolLine.overdue()}）：
     *       那个参数只决定**看板告警**（多早开始提示），**不是派单死线**。判据只有一条：
     *       {@code 今天 ≥ 最晚派单日}（= {@link #latestDispatchDate}，客户的到货日倒推 / 标准生产周期）。
     *       🔴 本类<b>没有</b>新增任何窗口类配置项 —— 判据的入参只有「到货日 / 进池日 / 标准生产周期」。</li>
     * </ul>
     *
     * <h2>默认关（判据 4）与幂等（判据 3）</h2>
     * 开关关 ⇒ <b>零读零写</b>（连池都不查），与事件腿同一条 {@code policy.enabled()} 判断、同一份缺省值表。
     * 与事件腿并发 ⇒ 沿用既有三道闸（{@code selectActiveByOrderId} + {@code uk_processing_orders_active}
     * + {@code uk_batch_consumption_line}）：派过的单已有活跃加工单 ⇒ 池里看不见它 ⇒ 不重复派、不重复扣。
     *
     * <h2>留痕（可区分来源）</h2>
     * {@code generated_by = auto:due_scan:<规则>}（如 {@code auto:due_scan:fifo}）——
     * 与事件腿的 {@code auto:<事件原因>:<规则>} 同一形态、不同取值 ⇒ 「这几张单是定时兜底派的」
     * 一眼可查。
     *
     * @return 与事件腿同一个读数结构（{@code trigger = due_scan}；{@code enabled=false} = 缺省关、零动作）
     */
    public AutoBatchOutcome autoBatchDispatchDue(Long tenantId) {
        return autoBatchDispatchDue(tenantId, AUTO_BATCH_TRIGGER_DUE_SCAN, autoBatchPolicy());
    }

    /** 显式策略版本（定时扫描与测试的入口；{@code null} ⇒ {@link #autoBatchPolicy()}）。 */
    public AutoBatchOutcome autoBatchDispatchDue(Long tenantId, String trigger,
                                                 AutoBatchPolicy policyRaw) {
        AutoBatchPolicy policy = policyRaw == null ? autoBatchPolicy() : policyRaw;
        if (tenantId == null || !policy.enabled()) {
            // 🔴 判据 4：缺省关 ⇒ **零读零写**（与 autoBatchDispatch 同一条判断，不另立口径）
            return new AutoBatchOutcome(false, trigger, null, List.of(), List.of(), List.of(),
                    List.of());
        }
        String rule = StockBatchConsumptionService.normalizeAssignmentRule(policy.assignmentRule());
        // 触发原因直接就是痕迹的一部分（**不**再追加 `:due` —— `due_scan` 已经说明了「为什么派」）；
        // 形态与事件腿**逐字同款**：`auto:<触发原因>:<规则>`（判别只看这一段）。
        String operator = AUTO_BATCH_OPERATOR_PREFIX + trigger + ":" + rule;
        List<String> reasons = new ArrayList<>();
        List<String> dispatched = new ArrayList<>();
        List<String> failedIds = new ArrayList<>();
        List<String> failures = new ArrayList<>();
        dispatchDueOrders(linesByOrderOf(pool(tenantId, policy.maxWaitHours())), tenantId, trigger,
                operator, policy, rule, reasons, dispatched, failedIds, failures);
        return new AutoBatchOutcome(true, trigger, rule, List.copyOf(reasons),
                List.copyOf(dispatched), List.copyOf(failedIds), List.copyOf(failures));
    }

    /**
     * 业务兜底段的**唯一实现**（事件腿的 ③ 与定时腿 {@link #autoBatchDispatchDue} 共用）。
     *
     * <p>判据 = {@code 今天 ≥ 最晚派单日}：{@code 有客户要求到货日 ⇒ 到货日 − 标准生产周期}；
     * {@code 无 ⇒ 进池日 + 标准生产周期}（见 {@link #latestDispatchDate}）。到日 ⇒ 必派，**不看条件**。</p>
     *
     * <p>🔴 <b>与等待时长无关</b>：本方法<b>不读</b> {@code PoolLine.waitHours()} / {@code overdue()}
     * —— 池化窗口（{@code maxWaitHours}）是**优化参数**、只决定看板多早告警；把它当派单死线正是
     * issue #5182/#5184 明令排除的形态。红证：把本方法的判据换成 {@code line.overdue()}
     * ⇒ 「超窗但未到期 ⇒ 不派」那条判据当场红（见 {@code scripts/auto-batch-due-scan-red-proof.py}）。</p>
     */
    private void dispatchDueOrders(Map<String, List<ProductionPoolViews.PoolLine>> linesByOrder,
                                   Long tenantId, String trigger, String operator,
                                   AutoBatchPolicy policy, String rule, List<String> reasons,
                                   List<String> dispatched, List<String> failedIds,
                                   List<String> failures) {
        LocalDate today = LocalDate.now();
        List<String> dueOrderIds = new ArrayList<>();
        List<String> dueReasons = new ArrayList<>();
        for (Map.Entry<String, List<ProductionPoolViews.PoolLine>> entry : linesByOrder.entrySet()) {
            ProductionPoolViews.PoolLine first = entry.getValue().get(0);
            LocalDate latest = latestDispatchDate(first, policy.standardCycleDays());
            if (latest == null || today.isBefore(latest)) {
                continue;
            }
            dueOrderIds.add(entry.getKey());
            dueReasons.add(dueReason(first, latest));
        }
        if (dueOrderIds.isEmpty()) {
            return;
        }
        reasons.addAll(dueReasons);
        collect(dispatchAuto(dueOrderIds, assignmentsOf(pluck(linesByOrder, dueOrderIds)),
                        tenantId, operator, rule, true),
                trigger, dispatched, failedIds, failures);
    }

    /** 到期理由的**唯一措辞**（两条腿的 {@code reasons} 逐字一致 ⇒ 痕迹可对比、不留两套说法）。 */
    static String dueReason(ProductionPoolViews.PoolLine first, LocalDate latest) {
        return "order=" + first.orderNo() + ":business_due=" + latest
                + (first.requiredDeliveryDate() != null
                ? "(required_delivery_date=" + first.requiredDeliveryDate() + ")"
                : "(no_required_delivery_date ⇒ 进池日 + 标准生产周期)");
    }

    /**
     * 成批条件判定（判据 3）：满足**任一** ⇒ 返回命中的那条规则（可读，进 {@code reasons} 痕迹）；
     * 都不满足 ⇒ {@code null}（**不派**）。
     *
     * <h2>三个条件的口径（写在这里一次）</h2>
     * <ul>
     *   <li><b>① 填满某批次 ≥ X%</b>：{@code 该物料组需求米数 ≥ X% × 某批次入库量}
     *       —— 分母是**入库量**（"填满一个整批"的字面口径；批次余量见 ②）。</li>
     *   <li><b>② 余量收敛到 ≤ N 米</b>：{@code 0 ≤ 该批次余量 − 需求米数 ≤ N}
     *       —— 「这批单正好把某一批用到见底」，N 缺省 0.2（与余量分布四档的 `≤0.2m` 同界）。</li>
     *   <li><b>③ 池内同物料需求 ≥ 最小批量</b>：{@code 需求米数 ≥ 阈值}。</li>
     * </ul>
     *
     * <p>⚠️ 这是**触发口径**（用一个可解释的算式回答"值不值得现在凑一批"），
     * 不是排料结果 —— 真正扣多少米由 {@code StockBatchConsumptionService.plan} 在派单时决定
     * （判据 6 的「口径一致」说的是**落账**与**预览**同源，不是触发口径等于排料口径）。
     * 触发口径保守（绝不高估收益）⇒ 不会因为"以为能省"而误派。</p>
     *
     * @return 命中的规则（含材料键与读数）；{@code null} = 三条都不满足 ⇒ 不成批
     */
    String batchConditionReason(ProductionPoolViews.PoolGroup group, Long tenantId,
                                AutoBatchPolicy policy) {
        BigDecimal demand = StockQuantity.orZero(group.requiredMeters());
        if (demand.signum() <= 0) {
            return null;
        }
        if (demand.compareTo(policy.minBatchMeters()) >= 0) {
            return String.format("material=%s:condition=min_batch(demand=%s>=%s)", group.materialKey(),
                    demand.toPlainString(), policy.minBatchMeters().toPlainString());
        }
        List<BatchStockViews.BatchRemaining> batches = batchesOfMaterial(tenantId, group);
        BigDecimal hundred = BigDecimal.valueOf(100);
        BigDecimal ratio = BigDecimal.valueOf(policy.fillRatioPercent());
        for (BatchStockViews.BatchRemaining batch : batches) {
            BigDecimal inbound = StockQuantity.orZero(batch.inboundMeters());
            if (inbound.signum() > 0 && demand.multiply(hundred).compareTo(ratio.multiply(inbound)) >= 0) {
                return String.format("material=%s:condition=fill_ratio(demand=%s>=%s%%×batch[%s]=%s)",
                        group.materialKey(), demand.toPlainString(), ratio.toPlainString(),
                        batch.batchNo(), inbound.toPlainString());
            }
            BigDecimal after = StockQuantity.orZero(batch.remainingMeters()).subtract(demand);
            if (after.signum() >= 0 && after.compareTo(policy.convergeMeters()) <= 0) {
                return String.format("material=%s:condition=converge(demand=%s,batch[%s]余量=%s⇒%s<=%s)",
                        group.materialKey(), demand.toPlainString(), batch.batchNo(),
                        StockQuantity.orZero(batch.remainingMeters()).toPlainString(),
                        after.toPlainString(), policy.convergeMeters().toPlainString());
            }
        }
        return null;
    }

    /**
     * 业务兜底的**最晚派单日**（判据 4 的唯一算式）。
     *
     * <p>{@code 有客户要求到货日 ⇒ 到货日 − 标准生产周期}（倒推：要赶上到货日，最迟哪天必须开工）；
     * {@code 无 ⇒ 进池日（= orders.created_at 的日期，与 waitHours 同一载体）+ 标准生产周期}
     * —— 没有客户死线时，**标准工期本身就是**「这批单最多能攒多久」的约束
     * （不让"凑不满"变成"永远不派"）。</p>
     *
     * <p>取不到任何时间依据（脏数据）⇒ {@code null} = 无从判定（不猜一个日子）；这条在
     * {@code orders.created_at} 为 {@code NOT NULL} 的前提下不可达，如实登记而不是编一个死线。</p>
     */
    static LocalDate latestDispatchDate(ProductionPoolViews.PoolLine line, int standardCycleDays) {
        if (line == null || standardCycleDays <= 0) {
            return null;
        }
        if (line.requiredDeliveryDate() != null) {
            return line.requiredDeliveryDate().minusDays(standardCycleDays);
        }
        return line.waitingSince() == null ? null
                : line.waitingSince().toLocalDate().plusDays(standardCycleDays);
    }

    /**
     * 自动派单的**三级尝试**（判据 10 的 fail-soft 落点）。
     *
     * <p>① 整批一次（成批 = {@code pooled=true} ⇒ 跨订单成组；加急 = 逐单 {@code pooled=false}）
     * → ② 对失败的**逐单 + 规则**（池级累计余量不足是池化**新出现**的失败面：
     * 两张单各要 3 米而批次只剩 5 米，逐单看各自都够）
     * → ③ 对仍失败的**逐单 + 不带规则**（#5145 之前的缺省形态：不碰批次账）。
     * 三级都失败才记失败 —— 「不能损失客户」不等于「假装成功」，失败照实留痕。</p>
     *
     * <p>重试**不会重复派**：① 里成功的单不在重试集里，而失败的判定依据
     * （{@code selectActiveByOrderId} + {@code uk_processing_orders_active}）是 fail-closed 的
     * —— 已经有加工单的单在②③里同样被拒（判据 7）。</p>
     */
    private List<AutoLine> dispatchAuto(List<String> orderIds, List<BatchAssignment> assignments,
                                        Long tenantId, String operator, String rule, Boolean pooled) {
        List<AutoLine> lines = new ArrayList<>();
        List<String> retry = new ArrayList<>();
        List<GenerateResult> results = generateSafely(orderIds, assignments, tenantId, operator, rule, pooled);
        for (int i = 0; i < orderIds.size(); i++) {
            GenerateResult r = i < results.size() ? results.get(i) : null;
            if (r != null && r.isSuccess()) {
                lines.add(new AutoLine(orderIds.get(i), true, r.getProcessingOrderNo()));
            } else {
                retry.add(orderIds.get(i));
            }
        }
        for (String orderId : retry) {
            GenerateResult one = firstOf(generateSafely(List.of(orderId),
                    assignmentsOfOrder(assignments, orderId), tenantId, operator + ":single", rule, false));
            if (one != null && one.isSuccess()) {
                lines.add(new AutoLine(orderId, true, one.getProcessingOrderNo()));
                continue;
            }
            GenerateResult plain = firstOf(generateSafely(List.of(orderId), List.of(), tenantId,
                    operator + ":plain", null, false));
            if (plain != null && plain.isSuccess()) {
                lines.add(new AutoLine(orderId, true, plain.getProcessingOrderNo()));
                continue;
            }
            lines.add(new AutoLine(orderId, false, messageOf(plain != null ? plain : one)));
        }
        return lines;
    }

    /**
     * {@link #generate} 的**不抛**包装：整批显式拒绝（池级求解失败 / 非法规则 / 累计余量不足）
     * ⇒ 逐单记失败，交给 {@link #dispatchAuto} 的降级重试。
     *
     * <p>{@code generate} 是 {@code @Transactional(rollbackFor = Exception.class)}：
     * 异常逸出 ⇒ 该次调用<b>整体回滚</b>（池级求解发生在任何写库之前，见 {@code generatePooled}）
     * ⇒ 这里的重试**不可能**撞上"写了一半"的中间态。</p>
     */
    private List<GenerateResult> generateSafely(List<String> orderIds, List<BatchAssignment> assignments,
                                                Long tenantId, String operator, String rule, Boolean pooled) {
        try {
            return generate(new ArrayList<>(orderIds), assignments, tenantId, operator, rule, pooled);
        } catch (RuntimeException e) {
            String message = e instanceof BusinessException be ? be.getMessage() : String.valueOf(e);
            String code = e instanceof BusinessException be ? be.getCode() : "AUTO_BATCH_DISPATCH_FAILED";
            String suggestion = e instanceof BusinessException be ? be.getSuggestion() : null;
            List<GenerateResult> out = new ArrayList<>();
            for (String orderId : orderIds) {
                out.add(GenerateResult.fail(orderId, code, message, suggestion));
            }
            return out;
        }
    }

    /** 池行按订单归拢（**包含加急行与每个物料组**；一单一加工单 ⇒ 派一张单要带上它的全部行）。 */
    private static Map<String, List<ProductionPoolViews.PoolLine>> linesByOrderOf(
            ProductionPoolViews.Pool pool) {
        Map<String, List<ProductionPoolViews.PoolLine>> out = new LinkedHashMap<>();
        for (ProductionPoolViews.PoolLine line : pool.urgentLines()) {
            if (line.orderId() != null) {
                out.computeIfAbsent(line.orderId(), k -> new ArrayList<>()).add(line);
            }
        }
        for (ProductionPoolViews.PoolGroup group : pool.groups()) {
            for (ProductionPoolViews.PoolLine line : group.lines()) {
                if (line.orderId() != null) {
                    out.computeIfAbsent(line.orderId(), k -> new ArrayList<>()).add(line);
                }
            }
        }
        return out;
    }

    /** 取出这几个订单的池行并**从索引里移除**（已处理过的单不参与后续段/不重复装配指派）。 */
    private static List<ProductionPoolViews.PoolLine> pluck(
            Map<String, List<ProductionPoolViews.PoolLine>> linesByOrder, List<String> orderIds) {
        List<ProductionPoolViews.PoolLine> out = new ArrayList<>();
        for (String orderId : orderIds) {
            List<ProductionPoolViews.PoolLine> lines = linesByOrder.remove(orderId);
            if (lines != null) {
                out.addAll(lines);
            }
        }
        return out;
    }

    /**
     * 池行 → 批次指派（{@code batchNo} **留空** ⇒ 由 {@code assignmentRule} 按 #5167 的规则补位）。
     *
     * <p>自动路径没有文员来指定批次，故逐行「有这一行、批次待定」；规则无效/无候选批次
     * ⇒ {@code buildDesignations} 抛业务异常 ⇒ 该单在①失败、由②③降级兜住（fail-soft）。</p>
     */
    private static List<BatchAssignment> assignmentsOf(List<ProductionPoolViews.PoolLine> lines) {
        List<BatchAssignment> out = new ArrayList<>();
        for (ProductionPoolViews.PoolLine line : lines) {
            if (line.orderId() == null || line.itemId() == null) {
                continue;
            }
            BatchAssignment a = new BatchAssignment();
            a.setOrderId(line.orderId());
            a.setItemId(line.itemId());
            out.add(a);
        }
        return out;
    }

    private static List<BatchAssignment> assignmentsOfOrder(List<BatchAssignment> assignments,
                                                            String orderId) {
        List<BatchAssignment> out = new ArrayList<>();
        for (BatchAssignment a : assignments) {
            if (Objects.equals(a.getOrderId(), orderId)) {
                out.add(a);
            }
        }
        return out;
    }

    /** 某物料的批次读数（余量口径 = 入库量 + Σ消耗，与余量分布/对账**同一函数**）。 */
    private List<BatchStockViews.BatchRemaining> batchesOfMaterial(Long tenantId,
                                                                   ProductionPoolViews.PoolGroup group) {
        List<BatchStockViews.BatchRemaining> out = new ArrayList<>();
        for (BatchStockViews.BatchRemaining batch
                : batchStock().remaining(tenantId, group.productId(), null, false)) {
            // SKU 一致性口径与 plan / suggestedBatchNo **同源**（有一侧没记 ⇒ 不作不一致判定）
            if (!StringUtils.hasText(group.skuCode()) || !StringUtils.hasText(batch.skuCode())
                    || group.skuCode().equals(batch.skuCode())) {
                out.add(batch);
            }
        }
        return out;
    }

    private void collect(List<AutoLine> lines, String trigger, List<String> dispatched,
                         List<String> failedIds, List<String> failures) {
        for (AutoLine line : lines) {
            if (line.success()) {
                dispatched.add(line.detail());
            } else {
                failedIds.add(line.orderId());
                failures.add(String.format("trigger=%s, orderId=%s: %s", trigger, line.orderId(),
                        line.detail()));
            }
        }
    }

    private static GenerateResult firstOf(List<GenerateResult> results) {
        return results == null || results.isEmpty() ? null : results.get(0);
    }

    private static String messageOf(GenerateResult r) {
        return r == null ? "自动派单未返回结果" : r.getMessage();
    }

    /** 自动派单里**一张单的最终结局**（三级尝试之后；{@code detail} = 加工单号或失败文案）。 */
    private record AutoLine(String orderId, boolean success, String detail) {
    }

    // ============================================================ 生成

    /**
     * 批量生成加工单（全事务；单个失败不影响已成功项结果返回，但整体回滚）。
     * 返回逐单结果（success/processingOrderNo/message）。
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, Long tenantId, String operator) {
        return generate(orderIds, List.of(), tenantId, operator);
    }

    /**
     * 批量生成加工单 + **派工指定批次**（V116，issue #5145 阶段 1）。
     *
     * <h2>为什么「指定批次」是可选入参（而不是必填）</h2>
     * 用户裁定「生成加工单时由文员指定批次（系统给候选 + 建议值，人工确认、可改）」+
     * 本阶段的定义特征是「**只记录、不改指派行为**」。⇒ 没有指派时（老调用方 / 该 SKU 还没有
     * 任何入库批次 / 文员不选）**行为与今天逐字相同**：不扣批次、不产生台账行、不多一个错误分支。
     * 指派了才扣 —— 记录的是**人工最终选择**，这正是基线成立的前提。
     *
     * <h2>fail-closed 的三条（都在任何写库之前判完）</h2>
     * ① 指派里的 {@code orderId} 不在本次 {@code orderIds} 内 ⇒ 显式拒绝（静默丢掉 = 文员以为指定了、
     *    账上永远少一笔）；② 指派的行不在该订单的加工单快照里 ⇒ 显式拒绝（同上）；
     * ③ 批次不存在 / 不属于该 SKU / 余量不足 ⇒ {@link StockBatchConsumptionService#plan} 抛错 +
     *    可行动建议（**不得静默少扣**）。
     *
     * @param batches 逐行指定批次（可空 / 空列表 = 不指派）
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> batches,
                                         Long tenantId, String operator) {
        return generate(orderIds, batches, tenantId, operator, null);
    }

    /**
     * 批量生成加工单 + **派工指定批次**（V116，issue #5145 阶段 1）+ **可切换的指派规则**（issue #5167）。
     *
     * <h2>为什么「指定批次」是可选入参（而不是必填）</h2>
     * 用户裁定「生成加工单时由文员指定批次（系统给候选 + 建议值，人工确认、可改）」+
     * 本阶段的定义特征是「**只记录、不改指派行为**」。⇒ 没有指派时（老调用方 / 该 SKU 还没有
     * 任何入库批次 / 文员不选）**行为与今天逐字相同**：不扣批次、不产生台账行、不多一个错误分支。
     * 指派了才扣 —— 记录的是**人工最终选择**，这正是基线成立的前提。
     *
     * <h2>指派规则（{@code assignmentRule}，issue #5167）—— 为什么「缺省 = 一字不改」</h2>
     * 规则是<b>显式开关</b>，不是缺省行为：传了它才把「系统建议值」升级为「直接采用」，
     * 且**只对没指定 {@code batchNo} 的行**生效（显式指定永远优先 = 人工最终选择 &gt; 规则）。
     * 不传它时未指定批次的行仍**逐字**走原来的显式拒绝 —— 否则缺省路径会从「拒绝」变成
     * 「静默指派」，而 #5145 的记录期基线正建立在「指派行为不变」之上（issue #5167 的 🔴 要求）。
     * 未知取值 ⇒ 在任何写库之前整批拒绝（{@link StockBatchConsumptionService#normalizeAssignmentRule}），
     * 即使本次所有行都显式指定了批次 —— 静默回落 fifo = 商家以为开了却没开。
     *
     * <h2>fail-closed 的三条（都在任何写库之前判完）</h2>
     * ① 指派里的 {@code orderId} 不在本次 {@code orderIds} 内 ⇒ 显式拒绝（静默丢掉 = 文员以为指定了、
     *    账上永远少一笔）；② 指派的行不在该订单的加工单快照里 ⇒ 显式拒绝（同上）；
     *    ②′ 传了规则但该行**没有可满足的批次** ⇒ 显式拒绝（不静默跳过该行 = 不静默少扣）；
     * ③ 批次不存在 / 不属于该 SKU / 余量不足 ⇒ {@link StockBatchConsumptionService#plan} 抛错 +
     *    可行动建议（**不得静默少扣**）。
     *
     * @param batches        逐行指定批次（可空 / 空列表 = 不指派）
     * @param assignmentRule 指派规则（{@code null}/空白 = 缺省 fifo **且不自动补位**；
     *                       {@code fifo} / {@code best_fit} = 显式开启，对未指定批次的行按规则补位）
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> batches,
                                         Long tenantId, String operator, String assignmentRule) {
        return generate(orderIds, batches, tenantId, operator, assignmentRule, null);
    }

    /**
     * 🔴 <b>池化开关（{@code pooled}）—— 缺省关</b>（issue #5169 判据 1：
     * 不启用池化 ⇒ 行为与今天**逐值相同**，含错误文案与结果顺序）。
     *
     * <h2>池化改的是什么（且只改这个）</h2>
     * 逐单派时，{@code StockBatchConsumptionService.plan} 每张单**各调一次** ⇒ 它的成组
     * （批次 × 加工类型）**只在本单内**发生。池化 = 把**池内多张单的行**合成一个
     * {@code List<Designation>}，**只调一次** {@code plan} ⇒ 候选块来自池内多张单，
     * 于是「两张单各一扇可并排的矮窗」从 2 行 6 米变成 1 行 3 米。
     * <b>成组键仍是「批次 × 加工类型」（#5158 口径不变）</b>：跨批次不得成组 ——
     * 两块料裁自不同卷时各自都得占一段卷长，跨批次并排是**虚报**。
     *
     * <h2>池化**不改**什么</h2>
     * <ul>
     *   <li>「一单一加工单」的约束（{@code uk_processing_orders_active}）：本单是
     *       **一次动作批量生成多张**加工单，不是把多单塞进一张（{@link #generatePooled}）；</li>
     *   <li>指派规则（#5167）：合法值集合、非法值 fail-closed、缺省 = 不补位 —— 一字不动；</li>
     *   <li>对客金额 / 售价 / 成品口径：池化只改「领料几米、从哪批裁」，
     *       公式口径米数（{@code formula_meters}）逐值不变（判据 7）。</li>
     * </ul>
     *
     * <h2>失败面（与逐单派的分工）</h2>
     * 逐单失败（订单不存在 / 状态不对 / 已有加工单 / 无加工项 / 指派行不在快照里）仍**逐单**
     * 记 {@code GenerateResult.fail} 且**不影响**其余单（顺序 = {@code orderIds} 顺序）。
     * 池级求解失败（累计余量不足 —— 池化**新出现**的失败面：两张单各要 3 米而批次只剩 5 米，
     * 逐单看各自都够）⇒ **整批显式拒绝**（fail-closed，不静默少扣，也不静默少派一张）。
     *
     * @param pooled 池化开关（{@code null} = 缺省，见 {@link #pooledEnabled}）
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> batches,
                                         Long tenantId, String operator, String assignmentRule,
                                         Boolean pooled) {
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        // 规则先归一 + 校验（**在任何写库之前**）：未知取值 ⇒ 整批显式拒绝，不留半成品。
        // `rule == null` = 调用方没传 ⇒ 不自动补位（缺省路径逐字不变，见方法注释）。
        String normalizedRule = StockBatchConsumptionService.normalizeAssignmentRule(assignmentRule);
        String rule = StringUtils.hasText(assignmentRule) ? normalizedRule : null;
        Map<String, List<BatchAssignment>> byOrder = assignmentsByOrder(orderIds, batches);
        // 🔴 默认关（判据 1）：不启用池化 ⇒ **逐单派**，与今天逐值相同（顺序、文案都不动）。
        boolean on = pooledEnabled(pooled);
        if (!on) {
            List<GenerateResult> results = new ArrayList<>();
            for (String rawId : orderIds) {
                try {
                    results.add(generateOne(rawId, byOrder.getOrDefault(rawId, List.of()), tenantId,
                            operator, rule));
                } catch (BusinessException e) {
                    results.add(GenerateResult.fail(rawId, e.getCode(), e.getMessage(), e.getSuggestion()));
                }
            }
            return results;
        }
        return generatePooled(orderIds, byOrder, tenantId, operator, rule);
    }

    /**
     * 批次指派 → {@code orderId → 逐行指派}（**任何写库之前**的唯一装配点；
     * 逐单派、池化派、成批预览三条路径共用 ⇒ ① 的 fail-closed 不可能只在一处生效）。
     *
     * <p>① 未匹配的指派（{@code orderId} 不在本次 {@code orderIds} 内）⇒ 显式拒绝
     * （静默丢掉 = 文员以为指定了、账上永远少一笔）。</p>
     */
    private static Map<String, List<BatchAssignment>> assignmentsByOrder(List<String> orderIds,
                                                                        List<BatchAssignment> batches) {
        List<BatchAssignment> assignments = batches == null ? List.of() : batches;
        Set<String> requested = new LinkedHashSet<>(orderIds);
        List<String> unknown = new ArrayList<>();
        for (BatchAssignment a : assignments) {
            String key = a == null ? null : a.getOrderId();
            if (key == null || !requested.contains(key)) {
                unknown.add(key == null ? "(空)" : key);
            }
        }
        if (!unknown.isEmpty()) {
            throw BusinessException.validationError(
                    "批次指派里的订单不在本次生成范围内：" + String.join(", ", unknown));
        }
        Map<String, List<BatchAssignment>> byOrder = new LinkedHashMap<>();
        for (BatchAssignment a : assignments) {
            byOrder.computeIfAbsent(a.getOrderId(), k -> new ArrayList<>()).add(a);
        }
        return byOrder;
    }

    /**
     * 池化成批派单（issue #5169 判据 2 的落点）—— 两段式：
     * <b>① 全部只读准备 → ② 池级一次性求解 → ③ 逐张落库</b>。
     *
     * <h2>为什么必须两段（不能边准备边落库）</h2>
     * 排料的成组要看**整个池子**：第 1 张单准备好时还不知道第 2 张单有没有可并排的块。
     * 故「写库」必须等到池级求解完成之后。而只读准备阶段**任何业务异常都还没写库**
     * ⇒ {@link #prepare} 抛错的那张单直接记 {@code fail} 并**不污染**其余单
     * （同 {@link #generateOne} 的既有纪律：异常不逸出事务边界 ⇒ 写库之后再抛就会留半成品）。
     *
     * <h2>结果顺序 = {@code orderIds} 顺序</h2>
     * 用下标槽位回填（不是「先追加成功的、再追加失败的」）—— 顺序也是判据 1 的一部分。
     */
    private List<GenerateResult> generatePooled(List<String> orderIds,
                                                Map<String, List<BatchAssignment>> byOrder,
                                                Long tenantId, String operator, String rule) {
        // 🔴 加急单**不进池**（issue #5177 判据 3）：混进成批批次 ⇒ 整批显式拒绝，**一行都不写**。
        // 放在 prepare 之前 ⇒ 拒绝时连只读准备都还没跑，更没有半成品。
        assertNoUrgentInPooledBatch(orderIds, tenantId);
        GenerateResult[] slots = new GenerateResult[orderIds.size()];
        List<Prepared> prepared = new ArrayList<>();
        List<Integer> indexes = new ArrayList<>();
        List<StockBatchConsumptionService.Designation> pooledLines = new ArrayList<>();
        for (int i = 0; i < orderIds.size(); i++) {
            String rawId = orderIds.get(i);
            try {
                Prepared p = prepare(rawId, byOrder.getOrDefault(rawId, List.of()), tenantId, operator,
                        rule);
                prepared.add(p);
                indexes.add(i);
                pooledLines.addAll(p.designations());
            } catch (BusinessException e) {
                slots[i] = GenerateResult.fail(rawId, e.getCode(), e.getMessage(), e.getSuggestion());
            }
        }
        if (!prepared.isEmpty()) {
            // 🔴 本单的核心：**只调一次** plan，候选块来自池内多张单 ⇒ 跨订单并排成立。
            // 成组键（批次 × 加工类型）在 plan 内部，本方法不碰（#5158 口径）。
            // 没有指派（`pooledLines` 为空）⇒ **一次都不调** plan：与逐单派的缺省路径逐字相同
            // （「不指派 ⇒ 不碰批次账」是 #5145 记录期的定义特征，见 generateOne 的同款守卫）。
            Map<String, List<StockBatchConsumptionService.Deduction>> byItemId = pooledLines.isEmpty()
                    ? Map.of() : deductionsByItemId(batchStock().plan(tenantId, pooledLines));
            for (int k = 0; k < prepared.size(); k++) {
                Prepared p = prepared.get(k);
                int slot = indexes.get(k);
                try {
                    slots[slot] = commit(p, deductionsOf(p, byItemId), tenantId, operator);
                } catch (BusinessException e) {
                    slots[slot] = GenerateResult.fail(orderIds.get(slot), e.getCode(), e.getMessage(),
                            e.getSuggestion());
                }
            }
        }
        List<GenerateResult> results = new ArrayList<>(orderIds.size());
        for (int i = 0; i < orderIds.size(); i++) {
            // 每个下标要么在上面的失败分支写过、要么在 commit 分支写过 ⇒ 恒非 null；
            // 非 BusinessException（如 DB 层错误）照旧逸出本方法（与逐单派同款：不吞异常）
            results.add(slots[i]);
        }
        return results;
    }

    /** 池级求解结果按 {@code orderItemId} 归拢（一行可能命中多行 —— 同一行被拆到多批次时才发生）。 */
    private static Map<String, List<StockBatchConsumptionService.Deduction>> deductionsByItemId(
            List<StockBatchConsumptionService.Deduction> plan) {
        Map<String, List<StockBatchConsumptionService.Deduction>> out = new LinkedHashMap<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            out.computeIfAbsent(d.orderItemId(), k -> new ArrayList<>()).add(d);
        }
        return out;
    }

    /** 本单该落的那几行（**按本单指派顺序**取 ⇒ 与逐单派落的行序逐值相同）。 */
    private static List<StockBatchConsumptionService.Deduction> deductionsOf(Prepared p,
            Map<String, List<StockBatchConsumptionService.Deduction>> byItemId) {
        List<StockBatchConsumptionService.Deduction> out = new ArrayList<>();
        for (StockBatchConsumptionService.Designation d : p.designations()) {
            out.addAll(byItemId.getOrDefault(d.orderItemId(), List.of()));
        }
        return out;
    }

    /**
     * 一个订单的**只读准备结果**（池化两段式的第一段）：写库之前的全部校验、快照与工序计划。
     *
     * <p>{@code designations} 是**排料/扣减的入参**（池级求解的输入），
     * 而 {@code po} 已经建好（含加工单号）但**未插入** —— 插入与扣账都在 {@link #commit}。</p>
     */
    private record Prepared(String rawId, Order order, List<Map<String, Object>> snapshot,
                            List<Map<String, Object>> positions, ProcessingOrder po,
                            List<StockBatchConsumptionService.Designation> designations) {
    }

    /** 逐单派（缺省路径）：准备 → 本单求解 → 落库。与池化派**共用**同一条准备与落库链。 */
    private GenerateResult generateOne(String rawId, List<BatchAssignment> assignments,
                                       Long tenantId, String operator, String rule) {
        Prepared p = prepare(rawId, assignments, tenantId, operator, rule);
        // 不指派批次（本单没有指定、也没传规则）⇒ **一次都不调** plan：与 #5145 之前逐字相同
        // （「不指派 ⇒ 不扣批次、不产生台账行、不多一个错误分支」—— 连 mock 交互次数都不许多一次）
        List<StockBatchConsumptionService.Deduction> deductions = p.designations().isEmpty()
                ? List.of() : batchStock().plan(tenantId, p.designations());
        return commit(p, deductions, tenantId, operator);
    }

    /**
     * 只读准备（**不写任何一行**）：解析订单 → 状态闸 → 快照 → 幂等闸 → 工序 payload →
     * 扣减入参（{@link #buildDesignations}）。
     *
     * <p>语句顺序与拆分前的 {@code generateOne} **逐字相同**（判据 1 要的「不启用池化 ⇒
     * 逐值相同」包括「哪一步先失败」——把幂等闸挪到快照之前就会换一条错误文案）。</p>
     */
    private Prepared prepare(String rawId, List<BatchAssignment> assignments,
                             Long tenantId, String operator, String rule) {
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
        // 订单级加急 / 客户要求到货日进快照（V120，issue #5177 范围 5）：**在加工单 insert 之前**写
        // `items_snapshot` —— 快照是加工单的**固化真相**，事后补不回来（与 commit() 里的
        // stampCuttingPlan / stampAssignedBatches 同一时机纪律）。
        stampOrderUrgency(snapshot, order);
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

        // 派工指定批次（V116 / issue #5145 阶段 1）：**只读校验 + 计划在任何写库之前跑完** ——
        // 与上面工序 payload 同一条纪律（generate() 逐单 catch BusinessException 后事务不回滚 ⇒
        // 写库之后再抛业务异常会留下「有加工单、扣了半截」的半成品，见
        // StockBatchConsumptionService 类注释「写面分两段」）。
        List<StockBatchConsumptionService.Designation> designations =
                buildDesignations(items, snapshot, assignments, tenantId, rule);

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
        return new Prepared(rawId, order, snapshot, positions, po, designations);
    }

    /**
     * 落库（两段式的第二段）：快照盖章 → 插加工单 → 扣批次 → 实例化工序。
     *
     * <p>{@code deductions} 由调用方给出（逐单派 = 本单求解；池化派 = 池级求解里属于本单的那几行）
     * —— 本方法因此对「池化开了没有」无感，判据 3「不可成组 ⇒ 与逐单派逐值相同」是
     * **结构性**成立的，而不是靠分支对齐。</p>
     */
    private GenerateResult commit(Prepared p, List<StockBatchConsumptionService.Deduction> deductions,
                                  Long tenantId, String operator) {
        // 把**文员最终指定**的批次写进加工单快照的 batchNo（V63 白名单早有该键、此前全仓零写入方
        // = 现成的空插座）；在插入**之前**写，故不多一次 UPDATE。
        stampAssignedBatches(p.snapshot(), deductions);
        // 排料结果（V119 / issue #5158）同样在插入之前写进快照：应领米数 / 公式米数 / 省下的米数
        // —— 快照是固化真相，前端与车间都读它（批次侧另有逐行台账，两条路都可审计）。
        stampCuttingPlan(p.snapshot(), deductions);

        // 生成**不**联动订单状态（issue #4305，用户裁定「发加工 = 订单进入生产中」）：
        // 订单 confirmed→producing 的时点已从「生成加工单」挪到「发加工」（见 updateStatus）。
        // 故此处不再有「联动先行 + 失败回退」那段 —— 订单状态在生成路径上全程不动，
        // 也就没有「producing 无加工单」的孤儿态可言（该孤儿态的成因随联动一并挪走）。
        // 并发重复生成仍由 partial unique index 兜底 → 转幂等错误（P2①）。
        try {
            processingOrderMapper.insert(p.po());
        } catch (org.springframework.dao.DuplicateKeyException e) {
            throw BusinessException.validationError(
                    "订单 " + p.order().getOrderNo() + " 加工单已生成（并发操作），请刷新后重试");
        }
        log.info("生成加工单: no={}, orderId={}, tenantId={}, operator={}",
                p.po().getProcessingOrderNo(), p.order().getId(), tenantId, operator);
        // 派工扣批次库存（issue #5145 判据 1）：与加工单生成**同一事务** ——
        // 加工单插入成功之后才扣（重复生成在更上游就被 selectActiveByOrderId +
        // uk_processing_orders_active 拒掉 ⇒ 不可能二次扣减）；计划已在插入前校验完，
        // 这里只落账、不再抛业务异常。不指定批次 ⇒ 计划为空 ⇒ 本段零动作（行为与今天逐字相同）。
        if (!deductions.isEmpty()) {
            batchStock().apply(tenantId, p.po().getProcessingOrderNo(), p.order().getOrderNo(), deductions);
        }
        // 工序实例化（issue #4116，P0 断链第一环）：加工单落行后**立即**实例化工序。
        // 此前 instantiate 端点全仓零调用者 ⇒ 工序列表恒空 ⇒ qr_token 恒 null ⇒
        // 任务卡只出「二维码待生成」占位、工人扫码报工不可达。
        // 工序序列已在插入前解析完毕（见 prepare 的 positions）：库取不到 ⇒ 根本走不到这里，
        // 所以本行的失败只可能是 DB 层错误 —— 那种情况异常逸出并由外层逐单
        // catch 记账，同样不留「有加工单、无工序」的静默半成品（工序另可由
        // POST .../instantiate 手工补做）。
        instantiateOperations(p.order(), p.po(), p.positions(), tenantId);
        return GenerateResult.ok(p.rawId(), p.po().getProcessingOrderNo());
    }

    /**
     * 批次消耗台账（V116 / issue #5145 阶段 1）—— 装配不上就**显式抛错**，绝不静默跳过扣减
     * （静默跳过 = 加工单照发、批次账不扣、余量分布永远好看，而没有任何东西会变红）。
     */
    private StockBatchConsumptionService batchStock() {
        if (stockBatchConsumptionService == null) {
            throw new IllegalStateException(
                    "StockBatchConsumptionService 未装配 —— 派工扣批次不能静默跳过（issue #5145）");
        }
        return stockBatchConsumptionService;
    }

    /**
     * 派工指定批次 → **只读校验 + 扣减入参**（必须在任何写库之前调用完）；**不**做池级求解
     * —— 求解在调用方（逐单派 = 本单一次 {@code plan}；池化派 = 池内多单一次 {@code plan}，
     * issue #5169 判据 2）。
     *
     * <p>逐行两件事：① 指派的行必须在该订单的加工单快照里（不在 ⇒ 显式拒绝 —— 配件/赠品行
     * 不成部位、不进快照，静默忽略会让文员以为指定了）；② 扣减米数 = 该行米数。</p>
     *
     * <p><b>两个米数（V119 / issue #5158）</b>：入参给 {@code StockBatchConsumptionService}
     * 的是**公式口径**（{@link StockQuantity#toStockScaleByCeiling} 后的订单行数量，与销售账扣减
     * **同一个函数**）+ 排料定尺要的三项（加工类型 / 窗高 / 分幅数，全部来自**快照**，即订单侧
     * 下单时落库的算料输出 —— Java 不重算幅数/褶倍/卷边）。扣多少米由
     * {@code StockBatchConsumptionService} 成组排料后决定（= 排料口径），本方法**不**替它算。</p>
     *
     * <p>两边同源是对账读面成立的前提：公式口径腿与销售账的扣减腿同函数 ⇒
     * 「{@code Σ批次余量} − {@code product_skus.stock}」的差额可以被拆成「已售未派」与
     * 「排料节省」两项而**不留口径差**（口径差会让差额读得出来却解释不清，正是路线 A 要防的漂移）。</p>
     *
     * <p><b>指派规则（issue #5167）</b>：{@code assignmentRule == null} = 调用方没传 ⇒ 未指定批次的行
     * **逐字**走原来的显式拒绝（缺省路径一字不改）；传了 ⇒ 只对未指定批次的行按规则补位
     * （{@link StockBatchConsumptionService#suggestedBatchNo}，与读面同一挑法），
     * 没有可满足批次 ⇒ 显式拒绝该行（不静默跳过 = 不静默少扣）。补位用的需求 = **公式口径**米数
     * （该行的领料上限），而实际扣减仍由 {@code plan} 按排料结果定（#5158 口径，本方法不碰）。</p>
     *
     * <p><b>SKU 码的取值键（issue #5174）</b>：逐行取快照**实际写入的键**（{@link #snapshotSkuCode}）。
     * 改前只有池化路径（#5169）这么取，既有路径读的是快照里**不存在**的 {@code skuCode} 键 ⇒ 恒 null
     * ⇒ 「批次 SKU 必须与订单行一致」这条判据与建议值的 SKU 过滤在**生产路径上从未生效**。
     * 取值键统一后两条路径在这一格上**同源**（其余口径本来就逐字相同：缺省拒绝、规则补位、
     * 米数、定尺入参）。</p>
     */
    private List<StockBatchConsumptionService.Designation> buildDesignations(
            List<OrderItem> items, List<Map<String, Object>> snapshot,
            List<BatchAssignment> assignments, Long tenantId, String assignmentRule) {
        if (assignments == null || assignments.isEmpty()) {
            return List.of();
        }
        Map<String, Map<String, Object>> rowByItemId = new LinkedHashMap<>();
        for (Map<String, Object> row : snapshot) {
            Object itemId = row.get("itemId");
            if (itemId != null) {
                rowByItemId.put(String.valueOf(itemId), row);
            }
        }
        Map<String, String> productIdByItemId = new LinkedHashMap<>();
        for (OrderItem item : items) {
            if (item.getId() != null) {
                productIdByItemId.put(item.getId(), item.getProductId());
            }
        }
        List<StockBatchConsumptionService.Designation> designations = new ArrayList<>();
        for (BatchAssignment a : assignments) {
            String itemId = a.getItemId() == null ? null : a.getItemId().trim();
            Map<String, Object> row = itemId == null ? null : rowByItemId.get(itemId);
            if (row == null) {
                throw BusinessException.validationError(String.format(
                        "批次指派的行 %s 不在本订单的加工单快照里（配件/赠品行不成部位，不参与派工指定）",
                        a.getItemId()));
            }
            // 缺省路径（没传规则）逐字不变：未指定批次 ⇒ 原样拒绝（错误码 / 文案 / 顺序都不动）
            if (!StringUtils.hasText(a.getBatchNo()) && assignmentRule == null) {
                throw BusinessException.validationError("批次指派缺少 batchNo（行 " + itemId + "）");
            }
            BigDecimal meters = StockQuantity.toStockScaleByCeiling(
                    row.get("quantity") instanceof BigDecimal q ? q : null);
            if (meters.compareTo(BigDecimal.ZERO) <= 0) {
                throw BusinessException.validationError(String.format(
                        "明细行 %s 的米数为 %s，无法指定批次扣减", itemId, meters.toPlainString()));
            }
            String batchNo = a.getBatchNo() == null ? null : a.getBatchNo().trim();
            // SKU 码（= 颜色 × 门幅）：**所有路径**都取快照实际写入的键（issue #5174；唯一入口见
            // {@link #snapshotSkuCode} —— 读错键会让整条 SKU 护栏 no-op）
            String skuCode = snapshotSkuCode(row);
            if (!StringUtils.hasText(batchNo)) {
                // 显式传了规则且该行没指定批次 ⇒ 按规则补位（建议值 = 直接采用）
                batchNo = batchStock().suggestedBatchNo(tenantId, productIdByItemId.get(itemId),
                        skuCode, meters, assignmentRule);
                if (!StringUtils.hasText(batchNo)) {
                    throw BusinessException.validationError(String.format(
                            "明细行 %s 在指派规则 %s 下没有可满足的批次（该行需要 %s 米）",
                            itemId, assignmentRule, meters.toPlainString()));
                }
            }
            designations.add(new StockBatchConsumptionService.Designation(
                    itemId, productIdByItemId.get(itemId), skuCode,
                    batchNo, meters,
                    // 排料定尺入参（V119 / issue #5158）：**逐字来自快照**（下单时落库的算料输出）
                    str(row.get("cuttingMode")),
                    OrderLineCraftFields.decimalOrNull(row.get("height"), "快照行 " + itemId + " 的窗高"),
                    OrderLineCraftFields.integerOrNull(row.get("panels"), "快照行 " + itemId + " 的分幅数")));
        }
        return designations;
    }

    /**
     * 快照行的 SKU 码（= **颜色 × 门幅**，即池化视图的「物料」维）—— **所有派工路径的唯一取键**。
     *
     * <p>🔴 快照里这个事实的键是 {@code sku}：{@code buildSnapshot} 把
     * {@code processing_info.sku} 与 {@code processing_info.skuCode} **都写进 {@code sku}**
     * 这一个键（两行 {@code copyIfPresent}，落键同为 {@code sku}）⇒ 快照里**没有**
     * {@code skuCode} 键。</p>
     *
     * <p><b>issue #5174：改前只有池化路径取对了键</b>（#5169 引入本方法时，既有路径逐字保留了
     * {@code row.get("skuCode")} —— 那正是**恒 null** 的来源）。后果不是「少一个字段」：
     * {@link StockBatchConsumptionService#plan} 的一致性判据第一个条件是
     * {@code StringUtils.hasText(d.skuCode())} ⇒ 整条 no-op；
     * {@link StockBatchConsumptionService#suggestedBatchNo} 的 SKU 过滤同样整条 no-op
     * ⇒ 同货号下**跨颜色/门幅**的批次会被静默接受并扣账（用错料，账上不留痕）。
     * 现统一走本方法（先 {@code sku}、取不到才退回 {@code skuCode} 兼容存量单）—— 两条路径**同源**。</p>
     *
     * <p>⚠️ 行为变更（如实登记）：取值键修对之后，「文员显式指定了另一 SKU 的批次」从
     * <b>静默接受</b>变为 {@code BATCH_SKU_MISMATCH} 拒绝 —— 这是**修 bug**，不是改记录期基线
     * （基线度量的是批次余量分配 / 采购米数 / 指派策略，本单一项都没动）。</p>
     */
    private static String snapshotSkuCode(Map<String, Object> row) {
        String sku = str(row.get("sku"));
        return sku != null ? sku : str(row.get("skuCode"));
    }

    /**
     * 把排料结果写进快照行（V119 / issue #5158）：{@code formulaMeters}（公式口径）/
     * {@code plannedMeters}（**应领米数** = 排料口径）/ {@code savedMeters}（省下的米数）。
     *
     * <p>快照是加工单的**固化真相** ⇒ 这三个数在生成那一刻就固定，事后改算料配置/批次价都不会
     * 改掉它（#5159 硬约束一「落库不重算」）。前端（{@code ProcessingOrderBlock}）据此显示
     * 「应领 X 米 / 公式 Y 米 / 省 Z 米」；批次侧另有一份逐行账（可逐单、可按批次汇总）。</p>
     *
     * <p>⚠️ 新键**必须**同时进 {@code ProcessingOrderResponse.ProcessingOrderItemBrief} ——
     * 快照里出现 DTO 没声明的键会让 {@code items} 整段解析失败（Jackson 未知属性 ⇒
     * {@code toResponse} 的 convertValue 抛错被 catch ⇒ 响应静默退化）。</p>
     */
    private static void stampCuttingPlan(List<Map<String, Object>> snapshot,
                                         List<StockBatchConsumptionService.Deduction> plan) {
        if (plan.isEmpty()) {
            return;
        }
        Map<String, StockBatchConsumptionService.Deduction> byItemId = new LinkedHashMap<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            byItemId.put(d.orderItemId(), d);
        }
        for (Map<String, Object> row : snapshot) {
            Object itemId = row.get("itemId");
            StockBatchConsumptionService.Deduction d =
                    itemId == null ? null : byItemId.get(String.valueOf(itemId));
            if (d == null) {
                continue;
            }
            row.put("formulaMeters", d.formulaMeters());
            row.put("plannedMeters", d.plannedMeters());
            row.put("savedMeters", d.formulaMeters().subtract(d.plannedMeters()));
        }
    }

    /** 把指定的批次号写进快照行（`batchNo` = 加工单的固化真相里「这行从哪一批裁」）。 */
    private static void stampAssignedBatches(List<Map<String, Object>> snapshot,
                                             List<StockBatchConsumptionService.Deduction> plan) {
        if (plan.isEmpty()) {
            return;
        }
        Map<String, String> batchNoByItemId = new LinkedHashMap<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            batchNoByItemId.put(d.orderItemId(), d.batchNo());
        }
        for (Map<String, Object> row : snapshot) {
            Object itemId = row.get("itemId");
            String batchNo = itemId == null ? null : batchNoByItemId.get(String.valueOf(itemId));
            if (batchNo != null) {
                row.put("batchNo", batchNo);
            }
        }
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
     * <p><b>`is_start_marker` 读库</b>：取 `production_operations` 的同名列。
     * 🔴 `is_must_finish`（必完）**已退场**（#4961，用户裁定 2026-09-21「完工 = 全部工序全绿」）：
     * 实例化 payload **不再带该键**（列保留为历史载体），完工判据改看「全部实例完成」。</p>
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
     * **不独立成部位**（否则一扇窗被算成两扇：褶数/开数/幅数/工序/计件全部翻倍）。
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
                // 褶数/开数/幅数/工序/计件全部翻倍）。该行自身的货号/米数仍在快照里可展示。
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
                // 分组/单位/单价/开始标记**逐字取库**（不猜、不补默认值）。
                // 🔴 `is_must_finish` **不再带出**（#4961）：概念已退场 ⇒ payload 里去掉该键
                // （实例化侧 parseSpecs 也不再读它；列保留为历史载体，见 V107 迁移）。
                operation.put("group", step.get("group"));
                operation.put("unit", step.get("unit"));
                operation.put("unit_price", step.get("unit_price"));
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
        if ("craft".equals(kind)) {
            // `craft` 维的 insert/remove **由 `buildRoute` 统一处理**（它先跑，序列已定稿）；
            // 本方法只补「按**订单行**触发」的那两类（特殊选项 / 加工项）⇒ craft 规则在这里
            // 返回 false 是「**不重复插入**」，**不是**「未实现」（别把它挪到下面的显式失败里：
            // 那会让每一张单在实例化时 422）。
            return false;
        }
        if ("option".equals(kind)) {
            return options.contains(rule.getTriggerValue());
        }
        if ("processing_item".equals(kind)) {
            return processingItems.contains(rule.getTriggerValue());
        }
        if (TRIGGER_KIND_POSITION.equals(kind)) {
            // 部位维（issue #4962）：`trigger_value` = 部位名，写面把它**镜像**进 `position` 列
            // ⇒ 「这条规则限哪个部位」只有**一处**判据（{@link #rulePositionMatches}，见两个调用方的
            // 统一筛选）。此处恒 true 只表示「该触发类型已实现」，**不是**「跳过筛选」。
            return true;
        }
        // ⛔ 未知 / 未实现的触发类型 ⇒ **显式失败**，不静默跳过（issue #4962）：
        // 返回 false 会让「规则已落库但永不生效」变成无人可见的黑洞
        // （与真值源 `routing.py::_rule_triggers` 的 `raise ValueError` 同款纪律）。
        throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                String.format("条件工序规则「%s」的触发类型「%s」尚未实现，无法实例化工序", rule.getId(), kind),
                422,
                "请在「工艺配置 → 工艺路线」停用该规则，或联系研发实现该触发类型");
    }

    /**
     * **规则级部位限定**（issue #4962 加回；此前由 issue #4937 / O2 整块退场）。
     *
     * <p>{@code position} 为空 / {@code NULL} = **不限部位**；否则必须**逐字**匹配当前实例化部位。
     * 与真值源 {@code app/production/routing.py::_rule_position_matches} **同款同序同判据** ——
     * 两侧漂移会让同一张单在 Java 与 Python 上得到不同的工序序列（车间按两套顺序干）。</p>
     *
     * <p>调用点**必须在触发类型分派之后**：未知类型要先显式失败，不能因为部位不匹配就静默跳过。</p>
     */
    private static boolean rulePositionMatches(ProductionRouteRule rule, String position) {
        String limit = rule.getPosition();
        return limit == null || limit.isEmpty() || Objects.equals(limit, position);
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
            // 🔴 **规则级部位限定**（issue #4962 加回；#4937 / O2 曾整块退场）：`position` 为空 /
            // NULL = **不限部位**；否则必须逐字匹配当前实例化部位。与真值源
            // `routing.py::build_route_v2` 的 `_rule_position_matches` 同款同序同判据。
            // ⚠️ 位置**必须在触发判定之后**（上面那行已经先跑）：未知触发类型要显式失败，
            // 不能因为部位不匹配就静默跳过（「规则落库但永不生效」的黑洞）。
            if (!rulePositionMatches(rule, position)) {
                continue;
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
     * 算料输入（issue #4208 Java 接线；米数判据先由 issue #4299 更正为**加工项** {@code pricingMethod}，
     * 再由 issue #4882 改为 {@link #isMeterBasedLine} 的**三段契约**）。
     *
     * <p><b>三层字段别混</b>（#4299 真库实测钉死，见 {@code acceptance/2026-09-18/4299-db-distribution/FINDINGS.md}）：</p>
     * <ul>
     *   <li>{@code sellingMethod} = <b>售卖方式</b>（真库取值：{@code bulk_cut} / {@code 散剪} /
     *       {@code full_roll} / {@code 整卷} / {@code 散剪售卖} / {@code 散剪按米} / {@code 散剪·按米购买} /
     *       {@code 散剪(bulk_cut)} / {@code cut} / {@code 散剪（按米裁剪）} / 无）—— <b>不是数量口径的来源</b>；
     *       {@code per_meter} 在该字段里一次都没出现过 ⇒ 拿它当判据<b>永不命中</b>（#4299 的病根）。</li>
     *   <li>加工项 {@code pricingMethod} = <b>加工项计价方式</b>（{@code per_meter} / {@code per_set} /
     *       {@code fixed} / {@code per_area}…）—— <b>订单行数量口径由它决定</b>，故 #4299 起它是判据字段
     *       （当时可达面 68 条订单行里命中 67 条）。⚠️ <b>#4882 起加工项目录已删该列</b> ⇒ 该键此后只可能
     *       出现在**存量订单快照**里（新单不再写），新单按「有加工项即米类」判 —— 见 {@link #isMeterBasedLine}。</li>
     *   <li>{@code products.pricing_type} = <b>商品</b>计价方式 —— 与订单行口径<b>不是同一层</b>：
     *       实测按它会漏 18/68 条（11 条商品缺失/软删 + 6 条 {@code pricing_type=fixed} 而其加工项仍按米）。</li>
     * </ul>
     * <p>{@code per_meter} 与「按米」是<b>加工项计价方式</b>的词汇，历史上被误当成售卖方式词表 ——
     * 同族混淆见前端展示表（{@code OrderDetail.tsx} / {@code OrderItemList.tsx} 把 {@code per_meter: '按米'}
     * 放进了 {@code sellingMethod} 的映射表）。</p>
     *
     * <p><b>#4882 登记：目录已无计价方式 ⇒ 新单按「有加工项即米类」</b>。用户裁定彻底删除
     * 「加工项单价」与「加工项计价方式」（{@code processing_items.pricing_method} / {@code unit_price} 两列），
     * 故判据不能再依赖目录。**有意取舍**（不是遗漏）：<b>存量无键老数据</b>的判定由「不命中」翻转为
     * 「命中米类」，理由 = #3005 行业口径（行业加工费按米计价、辅料含在加工费中）+ V83 目录 16 项
     * 历史上**全部** {@code per_meter}；翻转的代价只是「按订单行 quantity 当米数」，而不翻转的代价是
     * 米类工序兜底 1 ⇒ **假完工**（#4208 红线）。存量快照里**带** {@code pricingMethod} 键的行仍按原语义判
     * —— 含真库那条 {@code per_sqm} 刺绣散剪单的负例，不得冒充米数。</p>
     *
     * <p><b>取值</b>：命中时取<b>订单行</b> {@code quantity}（{@code OrderItem.quantity} javadoc：per_meter=米数），
     * <b>不</b>取加工项自己的 {@code quantity} —— 实测订单行 {@code 7e6f2a1c…} 订单数量 112.00
     * 而其 {@code per_meter} 加工项 quantity=1，取后者会让 112 米的单得到「应做 1 米」⇒ 报工上限 1 ⇒ 假完工。</p>
     *
     * <p><b>已知缺口（#4118，不是本方法缺陷）</b>：订单侧**从不落库算料输出** ⇒
     * {@code pleat_count}（褶数）/ {@code panels}（幅）/ {@code set_count}（套）/ {@code holes}（孔）
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
        // ② 该订单行是米类（判据见 isMeterBasedLine 的三段契约）⇒ 订单行数量即米数
        if (!calc.containsKey("fabric_meters") && isMeterBasedLine(entry)) {
            Object quantity = entry.get("quantity");
            if (quantity != null) {
                calc.put("fabric_meters", quantity);
            }
        }
        // ③ 卖布行（`saleForm = 布料`，issue #4909）：按米卖布、行上**没有加工项** ⇒ ② 永不命中
        //    （`isMeterBasedLine` 第 1 段对「processingItems 缺失」判 false），而这一行的部件维是
        //    「布料」、走**布料基础路线**（V88 终态 `裁剪 → 打包`）⇒ 米类工序（裁剪）必须有米数。
        //    缺这一步 ⇒ 端点按缺键兜底 1（`qty_source=fallback`，与「算料服务没答」不可区分）
        //    ⇒ 10 米的布单只做 1 米、计件按 1 米算 —— 正是 #4208 红线要治的形态。
        //    取法与 ② 同源（**订单行 quantity 即米数**），不新增第二份口径；数量 ≤ 0（脏数据）
        //    时**不落键**：「绝不落 0」是端点的硬不变量（应做 0 ⇒ `done_qty ≥ qty` 恒真 ⇒ 假完工）。
        if (!calc.containsKey("fabric_meters") && SALE_FORM_FABRIC.equals(str(entry.get("saleForm")))) {
            Object quantity = entry.get("quantity");
            if (quantity != null && new BigDecimal(String.valueOf(quantity)).signum() > 0) {
                calc.put("fabric_meters", quantity);
            }
        }
        return calc;
    }

    /**
     * 该订单行是否是**米类**（{@code calc_info.fabric_meters} 取订单行 {@code quantity} 的判据）。
     *
     * <p>判据按 issue #4882 的**三段契约**（逐条实现，勿简化）：</p>
     * <ol>
     *   <li>{@code processingItems} 缺失 / 非 {@code List} / 为空 ⇒ {@code false}（老数据与脏数据形态，不猜）；</li>
     *   <li>若**任一项显式带 {@code pricingMethod} 键**（= 存量订单快照形态）：存在 {@code "per_meter"}
     *       ⇒ {@code true}；所有带键项都不是 {@code "per_meter"} ⇒ {@code false}
     *       —— <b>这条负例必须保住</b>：真库有一条刺绣工艺 {@code per_sqm} 的散剪单，
     *       它的订单行 quantity 不是米数，不得冒充米数（#4299 实测，order_item {@code 286229cf…}）；</li>
     *   <li>若**一项都不带 {@code pricingMethod} 键**（= #4882 之后的新单：加工项目录已无计价方式，
     *       下单入口不再写该键）⇒ {@code true}（#3005 行业口径：行业加工费**按米计价**、辅料含在加工费中；
     *       V83 目录 16 项历史上全部 {@code per_meter}）。</li>
     * </ol>
     *
     * <p><b>有意取舍（登记，不是遗漏）</b>：第 3 段把**存量无键老数据**的判定由「不命中」翻转为
     * 「命中米类」。方向是刻意的 —— 不翻转的后果是米类工序落 {@code qty_source=fallback} 兜底 1
     * ⇒ 112 米的单做 1 米 ⇒ **假完工**（#4208 红线），翻转的后果只是「按订单行 quantity 当米数」。
     * 详见 {@link #calcInfo}。</p>
     *
     * <p>不看售卖方式 {@code sellingMethod}、也不看商品级 {@code pricing_type} ——
     * 理由与实测数字见 {@link #calcInfo}。</p>
     */
    private static boolean isMeterBasedLine(Map<String, Object> entry) {
        Object raw = entry.get("processingItems");
        if (!(raw instanceof List<?> items) || items.isEmpty()) {
            return false;   // ① 缺失 / 非 List / 空
        }
        boolean anyExplicitKey = false;
        for (Object item : items) {
            if (item instanceof Map<?, ?> proc && proc.containsKey("pricingMethod")) {
                anyExplicitKey = true;                          // ② 存量快照形态
                if ("per_meter".equals(str(proc.get("pricingMethod")))) {
                    return true;
                }
            }
        }
        return !anyExplicitKey;                                 // ③ 全无该键 ⇒ 新单 ⇒ 米类
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
                    // 🔴 issue #4937 / O1：`applicable` 过滤退场后，**位置维**不再由那道闸给出
                    // ⇒ 可行动性信息（「缺在哪个产品形态上」）必须由本条 message 自己承载
                    // （改前它由「该工序在「X」部位缺库行」那句 hint 顺带给出，而那句随过滤一起退场）。
                    String.format("工艺路线「%s」（产品形态「%s」）引用的工序 %s 在工序库中不存在，"
                                    + "无法实例化工序", template.getName(), routePosition, missing),
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
     *       触发命中（工艺精确匹配 / 选项 ∈ 本单选项）⇒
     *       {@code insert} 用 {@code after_operation} 定位（锚点不在序列中 ⇒ <b>追加末尾</b>，
     *       与 {@code _insert_after} 同款）；{@code remove} 直接删除该逻辑工序名。
     *       ⚠️ <b>{@code remove} 不先于 {@code insert}</b>：顺序完全由 {@code priority} 决定。
     *       ⚠️ <b>规则级</b>的 {@code position}（部位限定）**照旧筛选** —— 它与「路线层的帘种适用性」
     *       （{@code production_route_templates.positions}）**不是**同一件事：实测去掉它会让规范
     *       9 条老路线的逐字重建判据变红（`ProductionRouteParityTest`），并让 `韩褶 × 布帘` 那条
     *       插入 {@code 上车布} 的规则对帘头单生效 ⇒ 帘头主线多一道不该做的工序（错发计件工资）；</li>
     *   <li>🔴 <b>「部位适用性」已退场</b>（issue #4937，用户裁定 2026-09-21「不计成本的改」）：
     *       主线里的名字**不再被 {@code production_operation_positions.applicable} 过滤**。
     *       唯一保留的判据是<b>名字形态</b>（issue #4609）：名字归一后**不等于自己** ⇒
     *       它是变体名 / 别名（{@code 精裁-布}），实例化按逻辑名建键永远查不到
     *       ⇒ <b>必须可见</b>（进 {@code missing_operations}，调用方 fail-closed 并指名报缺）；
     *       名字本身就是逻辑工序名 ⇒ 正常建键。⛔ 原来那条「键不存在 ⇒ 静默 {@code continue}」
     *       与「{@code applicable=false} ⇒ 静默滤掉」两条闸**一并删除** —— 它们是「部位」最后一次
     *       参与取路，而用户已裁定部位不再参与任何取价、取路、筛选、配置。</li>
     * </ol>
     *
     * <p>工序元数据（分组/单位/单价/必完/开始标记/作用域）逐字取该租户的工序库行
     * （经 {@link ProductionOperationQueryService#variantNameOf} 换回变体名）；
     * 库中缺该变体、或主线里出现**不认识的名字** ⇒ 登记进 {@code missing_operations}
     * （由调用方 fail-closed，**不猜默认值**，也**不静默丢**）。</p>
     *
     * <p><b>单价 = 该逻辑工序的「一口价」</b>（去部位化，issue #4883：矩阵按逻辑工序收敛为一行，
     * 收敛规则见 {@link ProductionOperationQueryService#collapseToLogical}；用户裁定取布帘价），
     * <b>逐字带出、绝不回落</b>（issue #4696，P1）：该价 {@code NULL} = <b>未定价</b> ⇒
     * 实例快照落 {@code NULL}（不是 0）。</p>
     *
     * <p>⚠️ 改前这里回落「工序库行价」（{@code production_operations.unit_price}，V49 DDL 是
     * {@code NOT NULL DEFAULT 0}）⇒ 布料单的 `配料`/`打包`（矩阵格 NULL）落库 <b>0 元</b> ⇒
     * 报工即按 0 计件（<b>工人白干且无人知道</b>），而 V88 的读面
     * （{@code GET /operation-layers}）**不回落**、判 {@code unpriced}、界面显示「未定价」
     * ⇒ 两处口径不一致，且「没定价」与「价本来就是 0」不可区分。
     * 现在两侧**同口径**：格价 NULL ⇒ 未定价（落 {@code NULL}）；格价 0 ⇒ <b>有价 0 元</b>。</p>
     */
    private Map<String, Object> buildRoute(ProductionRouteTemplate template, String position, String craft,
                                           Map<String, Object> entry,
                                           List<ProductionRouteRule> rules,
                                           List<ProductionOperationPosition> priceRows,
                                           Map<String, Map<String, Object>> catalog,
                                           Long tenantId) {
        // 价目**一口价**（去部位化，issue #4883）：部位不再参与取价 ⇒ 把矩阵按逻辑工序收敛成
        // 「一道逻辑工序 → 一个价」（收敛规则 = ProductionOperationQueryService#collapseToLogical：
        // 适用行优先、其中**布帘列**优先 —— 用户裁定「取布帘价」）。
        // 🔴 未定价（收敛行的 unit_price IS NULL）**不得**回落工序库行价（issue #4696）：
        // 工序库是 `NOT NULL DEFAULT 0` ⇒ 回落把「未定价」变成「真 0 元」（工人白干且无人知道）。
        Map<String, BigDecimal> priceByLogical = new LinkedHashMap<>();
        for (ProductionOperationPosition row
                : ProductionOperationQueryService.collapseToLogical(priceRows)) {
            priceByLogical.put(row.getLogicalName(), row.getUnitPrice());
        }
        // ⛔ **「部位适用性」退场（issue #4937）**：此处原有 `applicableByLogical` 的构造 +
        // 下面两道 `continue` 闸（「键不存在」与「applicable=false」），本包按用户裁定
        // （2026-09-21「这个必须要改，我们移除了部位的设计，不计成本的改」，母单 #4936）
        // **整块删除** —— 部位不再参与取路。原来维护这条筛选的三条守卫已按同一次裁定退休/换基线：
        //  · `ProductionRouteParityTest#skippingApplicabilityFilterWouldLeakClothOnlyOperationsIntoSheerRoute`
        //    ⇒ 退休，原位换成「纱帘单与布帘单**工序集完全一致**」的新判据；
        //  · 9 条老路线**逐字重建** / `instantiationSequenceIsUnchangedForTheCanonicalRuleConfig`
        //    ⇒ 换成**去部位后的新模型冻结快照**基线（`RoutingModelFixture.DEPOSITIONED_ROUTINGS`）。
        // ⚠️ 唯一**保留**的判据是「名字形态」（见循环体：变体名/别名 ⇒ 进 missing_operations）。
        List<String> sequence = new ArrayList<>();
        for (String step : stringList(template.getMainline())) {
            sequence.add(step);
        }
        // 🔴 **工艺规则只对「窗帘类产品形态」生效**（issue #4937 / P2）。
        // 判据 = 与主线选择**同一个键**（`saleForm == 布料` ⇒ 布料主线，见 `routeTemplateFor`）：
        // 布料单是**另一个产品形态**（主线只有 `配料 → 打包`），在它上面套用窗帘工艺规则会把
        // `韩褶`/`上车布` 插进布料单 —— 而**旧口径下这件事被 `applicable` 过滤挡住了**
        // （`韩褶 × 布料` 当时不存在/不适用）。部位过滤退场后，「哪些工序不属于这个产品形态」
        // 必须由**产品形态**表达，否则布料单的工序数会当场从 2 变 4（真值源
        // `routing.py::build_route_v2` 的 `if is_fabric: continue` 是同一份口径）。
        boolean isFabricForm = FABRIC_POSITION.equals(position);
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
            if (isFabricForm) {
                // 布料产品形态不套用工艺规则（见上方注释；与真值源同一份口径）
                continue;
            }
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
            } else if (TRIGGER_KIND_POSITION.equals(kind)) {
                // 部位维（issue #4962）：`trigger_value` = 部位名，写面把它**镜像**进 `position` 列
                // ⇒ 真正的筛选是下面那一处 {@link #rulePositionMatches}（**只有一处判据**）。
                // 列缺值 ⇒ 这条规则对**任何**部位都不生效 = 「规则已落库但永不生效」的黑洞
                // ⇒ 显式失败（不允许静默）。
                if (rule.getPosition() == null || rule.getPosition().isEmpty()) {
                    throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                            String.format("工艺路线规则「%s」的部位维触发没有落 `position` 值，"
                                    + "无法判定它限哪个部位（规则永不生效）", rule.getId()),
                            422,
                            "请停用该规则后重建（部位维规则必须带 `position` / `trigger_value` 部位名）");
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
            // 🔴 **规则级部位限定**（issue #4962 加回；#4937 / O2 曾整块退场）：`position` 为空 /
            // NULL = **不限部位**；否则必须逐字匹配当前实例化部位。与真值源
            // `routing.py::build_route_v2` 的 `_rule_position_matches` 同款同序同判据。
            // ⚠️ 位置**必须在触发类型分派之后**：未知类型先显式失败，不因部位不匹配就静默跳过。
            if (!rulePositionMatches(rule, position)) {
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
            // 🔴 **唯一保留的判据 = 名字形态**（issue #4609，P0 静默丢工序）：
            // 主线里存着**变体名 / 别名**（`精裁-布`，老 bundle / 界面加过工序的存量路线）时，
            // 实例化按逻辑名建键永远查不到 ⇒ **必须可见**：进 `missing_operations`
            // （调用方据此 fail-closed 并指名报缺），**不得**静默滤掉。
            // 判据复用**同一份**归一表（`normalizeOperationName`，不新造第二份）。
            // ⛔ 原「键不存在 ⇒ 静默 continue」与「applicable=false ⇒ 静默 continue」两道闸
            // 已随「部位适用性」退场（issue #4937）—— 名字本身就是逻辑工序名 ⇔ 归一后等于自己
            // ⇒ 直接按逻辑名建键（不再是「没登记适用性就不猜」）。
            if (!logicalName.equals(productionOperationQueryService.normalizeOperationName(logicalName))) {
                missing.add(logicalName);
                continue;
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
            // 🔴 未定价（格价 NULL）**不得**回落工序库行价（issue #4696，P1）：工序库行价是
            // `NOT NULL DEFAULT 0` ⇒ 回落就把「未定价」变成「真 0 元」（工人白干且无人知道），
            // 且与「显式定价 0 元」不可区分。读面（V88 `GET /operation-layers`）不回落 ⇒
            // 实例化侧必须同口径：格价 NULL ⇒ 落 NULL（未定价），格价 0 ⇒ 有价 0 元。
            step.put("unit_price", priceByLogical.get(logicalName));
            // 🔴 `is_must_finish` **不再带出**（#4961）：路线步骤里去掉该键 ⇒ 实例化 payload 也没有它
            // （`buildPositionPayload` 逐字从中带出；列保留为历史载体）。
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
            // 🔴 存量行：`order_items.processing_info` **可为 NULL**（真库实证 issue #5550：待派池里
            // 29 行有 **15 行**是 NULL）⇒ 归一化结果是**可能为 null 的缺值**，不得直接解引用
            // —— #4909 那行 `str(pi.get("saleForm"))` 踩的正是这里，智能派单因此**恒 500**
            //（读面把整池的每一行都过一遍，NULL 行必被扫到；这不是间歇故障）。
            // 缺值语义 = 既没有加工项、也没有 `saleForm` ⇒ 与「无加工项的非卖布行」走**同一条**既有语义：跳过。
            if (pi == null) {
                continue;
            }
            List<Map<String, Object>> procs = extractProcessingItems(pi);
            // 卖布行（`saleForm = 布料`）**天然没有加工项**（按米卖布，不选加工项）⇒ 旧过滤把它整行丢掉，
            // 于是 `buildPositionPayload` 的布料路线分支（`deriveRouteKey`，issue #4529）**永不执行**
            // ⇒ 整件商品零工序（真库实证：加工单 JG-20260921-8237 缺「9231 遮光窗帘」的裁剪/打包，issue #4909）。
            // 其余「无加工项」行仍按旧语义跳过（配件 / 赠品行不成部位，行为逐字不变）。
            if (procs.isEmpty() && !SALE_FORM_FABRIC.equals(str(pi.get("saleForm")))) {
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
            // 派工扣减的**对称回补**（V116 / issue #5145 判据 3）：作废 ⇒ 同事务把批次余量还回去，
            // 回补量 = 原扣减量的相反数（逐值对称，小数场景如 2.7 也一样）。
            // 挂点就在取消分支里（母单 #5145 指认的「现成挂点」）；另有一个作废入口
            // —— 订单取消自动作废 generated 单走 OrderService.cancelOrder —— 那里接了同一句话。
            // 幂等：重复取消被上面状态机拒（cancelled → cancelled 不合法）；服务层再按
            // 「该行已回补则跳过」兜一层 ⇒ 可重跑。
            batchStock().reverse(tenantId, po.getProcessingOrderNo(),
                    order == null ? null : order.getOrderNo(),
                    "加工单作废回补批次库存：" + req.getReason());
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
