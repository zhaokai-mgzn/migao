package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.MaterialLabels;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.service.ProcessingPositionPayloadBuilder.PositionPayload;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.SupplierMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
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
 * 取法 = {@link ProcessingRouteResolver#deriveRouteKey} 的三层链（issue #4452 起，第 2 层从「{@code contains} 猜文本」
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

    /** 业务时钟（issue #3802）：业务「今天」的唯一来源。Spring 注入单例；**不扫描 @Component 的切片上下文**
     * （@WebMvcTest / ApplicationContextRunner）与直接 new 构造的既有单测没有该 bean ⇒ required=false +
     * 默认实例（同为 +08 口径，行为一致），不因引入时钟让任何既有上下文启动失败（实测 OssEmptyConfigContextTest）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

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
     * 承接方档案（V193，issue #7723）：智能派单选中的加工厂 = `suppliers.type = processor` 的一行。
     *
     * <p><b>字段注入</b>（不改进构造签名）：本类的构造签名被多处测试显式 {@code new}（同
     * {@link #shortLinkBaseUrl} 的理由）。{@code required = false} ⇒ 切片上下文照常启动；
     * 真有承接方入参而它没装配时**显式抛错**（{@link #resolveConsignee}），不静默当成「本厂自做」。</p>
     */
    @Autowired(required = false)
    private SupplierMapper supplierMapper;

    /**
     * 印刷品上的码的稳定域名（issue #6867 / B3；设计
     * {@code docs/design/worker-h5-scan-and-report.md} §11.3「后端 · 读面键」）。
     *
     * <p><b>与 {@code ProductionService.shortLinkBaseUrl} 取自同一条既有配置</b>
     * （{@code migao.worker.short-link-base-url}，缺省 {@code https://app.migaozn.com}）——
     * 域名**不在代码里写第二份字面量**，加工单纸上的码（{@code /o/}）与部位码（{@code /s/}）
     * 因此换域名时同批生效。</p>
     *
     * <p>字段注入 + <b>内联默认值</b>：本类构造签名被多处测试显式 {@code new}（见
     * {@code ProcessingOrderServiceTest} 的装配注释）⇒ 加构造参数会把这些装配全改一遍，
     * 而它们都不过 Spring 上下文 ⇒ 取内联默认值（确定性）。同款先例见
     * {@code ProductionService.shortLinkBaseUrl} 的字段注释。</p>
     */
    @Value("${migao.worker.short-link-base-url:https://app.migaozn.com}")
    private String shortLinkBaseUrl = "https://app.migaozn.com";

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
     * **路线解析 / 部位 payload 两个单元**（issue #8725 第二档切片）：惰性构造，**不**进构造器 ——
     * 本类的构造器是 16 处直接 `new ProcessingOrderService(...)`（测试装配面）的契约，
     * 加构造参数会波及所有与本切片无关的直接构造点；两个单元**无状态**（只持有查询/算料客户端），
     * 惰性构造与单例在行为上等价（同一实例、同一调用序）。
     */
    private ProcessingRouteResolver routeResolver;
    private ProcessingPositionPayloadBuilder positionPayloadBuilder;

    private ProcessingRouteResolver routeResolver() {
        if (routeResolver == null) {
            routeResolver = new ProcessingRouteResolver(productionOperationQueryService);
        }
        return routeResolver;
    }

    private ProcessingPositionPayloadBuilder positionPayloadBuilder() {
        if (positionPayloadBuilder == null) {
            positionPayloadBuilder = new ProcessingPositionPayloadBuilder(
                    productionOperationQueryService, productionOperationQtyClient);
        }
        return positionPayloadBuilder;
    }

    /**
     * **派单池读面**（issue #8770 派单池一档）：惰性构造，**不进构造器** —— 与
     * {@link #positionPayloadBuilder()} 同一理由（构造器是 16 处直接 {@code new} 的契约）。
     * 单元无状态（两个 mapper + 回调门面的窄接口），惰性构造与单例在行为上等价；回调**即时**取值
     * （时钟 / 算料服务可能被既有判据在构造之后换掉）。
     */
    private ProcessingOrderDispatchPool dispatchPool;

    private ProcessingOrderDispatchPool dispatchPool() {
        if (dispatchPool == null) {
            dispatchPool = new ProcessingOrderDispatchPool(orderMapper, processingOrderMapper,
                    new ProcessingOrderDispatchPool.Owner() {
                        @Override
                        public LocalDate today() {
                            return businessClock.today();
                        }

                        @Override
                        public List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
                            return ProcessingOrderService.this.loadOrderItems(orderId, tenantId);
                        }

                        @Override
                        public List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
                            return ProcessingOrderService.this.buildSnapshot(items, tenantId);
                        }

                        @Override
                        public StockBatchConsumptionService batchStock() {
                            return ProcessingOrderService.this.batchStock();
                        }

                        @Override
                        public Order resolveOrder(String rawId, Long tenantId) {
                            return ProcessingOrderService.this.resolveOrder(rawId, tenantId);
                        }
                    });
        }
        return dispatchPool;
    }

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
     * 唯一判据），因此实例化侧只看列、不看 kind —— 见 {@link ProcessingOperationWeaver#rulePositionMatches}。</p>
     */
    public static final String TRIGGER_KIND_POSITION = "position";

    /**
     * 触发类型 · **售卖方式**（issue #7523，用户裁定 2026-10-23）。
     *
     * <p>取值 = 订单行 {@code sellingMethod}：{@code full_roll}（整卷）/ {@code bulk_cut}（散剪）。
     * **只对布料产品形态生效**：整卷 ⇒ {@code 出库 → 打包}（不裁剪，工人按卷/批次拣货）；
     * 散剪 ⇒ 主线原样 {@code 裁剪 → 打包}。与真值源 {@code routing.py::ROUTE_RULES} 的两条
     * sales_form 规则逐条同源（insert 出库 after 裁剪 → remove 裁剪，priority 270/280）。</p>
     */
    public static final String TRIGGER_KIND_SALES_FORM = "sales_form";

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
     * <p>⚠️ 判据**不再只看这一个键**（issue #7222）：缺键时由
     * {@link #isFabricSaleLine(Map)} 按已落库的布料专属事实（{@code sellingMethod} / {@code rollCount}）
     * 兜底 —— API / 米宝 / 回归脚本漏写 {@code saleForm} 时，整条作业链会**三段同时静默放行**。</p>
     */
    public static final String SALE_FORM_FABRIC = "布料";
    /** 第 4 个部位（布料单专用）—— 与 {@code routing.py::FABRIC_POSITION} 逐字同源。 */
    public static final String FABRIC_POSITION = "布料";

    /**
     * **卖布行判据 —— 唯一实现点**（issue #4493 / #7079 / #7222）。
     *
     * <p>① **显式声明优先**：{@code processing_info.saleForm == 布料} ⇒ 卖布行；
     * 非空且不是布料（如 {@code 成品帘}）⇒ **不是**卖布行 —— 有明确声明就不许被派生信号覆盖。</p>
     *
     * <p>② **缺键时按已落库的布料专属事实兜底**（issue #7222）：{@code sellingMethod}
     * （{@code bulk_cut} 散剪 / {@code full_roll} 整卷）或 {@code rollCount}（整卷售卖，issue #5846）
     * 非空 ⇒ 卖布行。这两项**只有布料行才有**（下单页上「卷数 / 每卷实际米数」只出现在布料行，
     * 服务端也只用它做布料整卷分摊）⇒ 不是猜业务，而是把客户端（API / 米宝 / 回归脚本）
     * **漏写**的声明按已落库事实补回来。漏写的后果 = 作业单 / 派单池 / 发货守卫**三段同时静默放行**，
     * 工人拿不到裁剪活且不报错。</p>
     *
     * <p>③ 两者都没有 ⇒ 返回 {@code false}，保持存量语义（**缺键就是缺，不造值**）。</p>
     */
    public static boolean isFabricSaleLine(Map<String, Object> processingInfo) {
        if (processingInfo == null) {
            return false;
        }
        Object rawSaleForm = processingInfo.get("saleForm");
        String saleForm = rawSaleForm == null ? null : String.valueOf(rawSaleForm).trim();
        if (SALE_FORM_FABRIC.equals(saleForm)) {
            return true;
        }
        if (saleForm != null && !saleForm.isEmpty()) {
            return false;
        }
        // 🔴 **有加工项 ⇒ 一定不是卖布行**（卖布行按米卖，行上从无加工项 —— 这是它最硬的形态特征）。
        // 不加这道闸，AI 建单时顺手带的「整卷发货偏好」（sellingMethod）会让一张**成品帘**
        // 被误判成卖布单 ⇒ 走布料路线（只有裁剪/打包两道）、丢掉缝制工序，比原缺陷更糟。
        if (processingInfo.get("processingItems") instanceof List<?> items && !items.isEmpty()) {
            return false;
        }
        Object rawSellingMethod = processingInfo.get("sellingMethod");
        String sellingMethod = rawSellingMethod == null ? null : String.valueOf(rawSellingMethod).trim();
        if ("bulk_cut".equals(sellingMethod) || "full_roll".equals(sellingMethod)) {
            return true;
        }
        return processingInfo.get("rollCount") != null;
    }

    /**
     * 作业单类型 · **加工**（成品帘；**混合单**也在这一档）—— 与迁移 V159 的 CHECK / 前端联合类型逐值同源。
     */
    public static final String ORDER_KIND_PROCESSING = "processing";
    /** 作业单类型 · **出库**（卖布单的裁剪/打包作业 —— 快照**每一行** {@code saleForm=布料}）。 */
    public static final String ORDER_KIND_OUTBOUND = "outbound";

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
     * 订单侧若已存算料输出就原样送过去，Java 侧**不发明数字**（见 {@link ProcessingPositionPayloadBuilder#calcInfo}）。
     *
     * <p>{@code per_panel_pleats} / {@code fullness} / {@code fullness_actual} 为 issue #4354 新增
     * （设计文档 §4.3）：它们是**展示/复核**用键（每片褶数、理论/实际褶倍），算料端点按
     * {@code calc_info} 的自由字典读，多传不改变取值口径。</p>
     */
    static final List<String> CALC_INFO_KEYS = List.of(
            "fabric_meters", "meters", "pleat_count", "holes", "panels", "set_count", "source",
            "per_panel_pleats", "fullness", "fullness_actual",
            // 整卷出库（issue #7523）：出库工序的应做数量 = 订单行卷数（真实订单事实）
            "roll_count");

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
            "saleForm",
            // 部位级备注（issue #5685）：客户现行系统的加工单/工人扫码端上有 `部位备注: 公式--48个折`
            // —— 它装的是「**这个数字怎么来的**」（算料依据的人工说明）。订单侧把它落在
            // `processing_info.remark`（自由文本）⇒ 不进白名单就**不会进快照**，而快照是加工单的
            // 固化真相（`ProcessingOrderItemBrief.remark` 早已声明，只是此前**没有任何写入方** = 死字段）。
            // 缺值不落键（`copyIfPresent` 语义）⇒ 没填备注的单在快照里**没有**该键。
            "remark",
            // 安装信息（issue #7856）：水洗唛 / 发货标签 / 入库标签要印「安装小区 + 安装位置」。
            // 两者都落在 `order_items.processing_info` 顶层（与 `formulaText` / `remark` 同层，
            // **已登记 JSONB ⇒ 零迁移**）：
            //   · `installRoom` = **件级**（= 一行 = 一扇窗），下单时原样落库 ⇒ 逐键透传即可；
            //   · `installCommunity` = **订单级语义**，但由写侧单点扇出到每行同一字符串
            //     （快照是行数组、没有订单级顶层对象）⇒ 也在这里逐键取，**不另走 stampOrderUrgency**
            //     （订单级键塞进那一组会恒取不到 —— 那组的来源是 `orders` 行，本键的来源是明细行）。
            // 不进白名单 ⇒ 纸面少两行，且快照是固化真相、事后补不回来。
            // 缺值不落键（`copyIfPresent` 语义）⇒ 没填的单在快照里**没有**这两个键（纸面不印）。
            "installCommunity", "installRoom");

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
    static final List<String> UNSHAPED_REMOVED_OPERATIONS = List.of("定型", "复烫");

    /** 配布边（§4.8）：**不独立成加工部位**的部件角色 —— 组内出现主布行时它被合并进去。 */
    static final String COMPONENT_ROLE_EDGE = "配布边";

    /**
     * **套级**工序的作用域取值（`production_operations.scope`，V67 / issue #4384 A1）。
     *
     * <p>套级 = **每樘窗一次**（真值源 §8：「外帘是加工单打印行部位，**不是**路线键」）⇒
     * 实例化时同一樘窗（{@code craftGroupKey} 组）只落一次，而不是像部位级那样每个部位各落一次。</p>
     *
     * <p>⚠️ 这是**词表值**（库列注释冻结的两态之一），不是工序名白名单 —— 判据一律读
     * {@link ProcessingRouteResolver#buildRoute} 从工序库带出的 `scope`（逐字取库）；
     * 硬编码 `外帘打卷/装袋/发货` 会让商家在工序库把某道改成部位级后**不生效**（第二份口径）。</p>
     */
    static final String SCOPE_SET = "set";

    /** 部位（`curtainType`）取值「布帘」—— 樘窗的**主布行**（套级工序的承载体，同写侧 #4395 的代表行口径）。 */
    static final String CURTAIN_TYPE_CLOTH = "布帘";

    /** 部位（`curtainType`）取值「纱帘」—— 纱是**独立部位**（`componentRole=纱` 的行）。 */
    private static final String CURTAIN_TYPE_SHEER = "纱帘";

    /**
     * **可生成作业单**的订单状态（issue #7626，用户 2026-10-24 裁定 A）：
     * {@code pending}（待付款）/ {@code confirmed}（已确认）。
     *
     * <p>为什么把待付款放进来：作业单是**生产计划**，不扣库存、不记资金 —— 扣减与收款流水
     * 仍只发生在 {@code OrderService.confirmPayment}；而销售单上的「扫码报工」码取作业单
     * {@code scan_url}，旧闸门让待付款单永远没有作业单 ⇒ 纸面永远没有码，用户实测报
     * 「只有在确认付款后，打印预览才会出现二维码」。</p>
     *
     * <p>⚠️ 已取消 / 已完成等状态**仍拒绝**（闸门只放宽到待付款，不是全放开）。</p>
     */
    static final Set<String> GENERATABLE_ORDER_STATUSES = Set.of("pending", "confirmed");

    /**
     * **部件角色 → 部位**（V78，issue #4452）：受控枚举
     * （`order_create.py` 的工具 schema 里就是 enum：主布 / 配布边 / 纱）⇒ 它是**结构化输入**，
     * 不是「名词解释」。
     *
     * <p><b>为什么改走它</b>：旧派生链去**商品名**里 `contains '纱'` 判部位 —— 营销文案不是结构化输入，
     * 而受控枚举已经在手边（{@code isAbsorbedEdgeRow} 早就用它判「纱 = 独立部位」）。</p>
     *
     * <p>{@code 配布边} ⇒ 布帘：它是**不独立成部位**的部件（组内出现主布行时被吸收，
     * 见 {@link ProcessingPositionPayloadBuilder#isAbsorbedEdgeRow}），只有在组内没有主布行时才自成部位 ⇒ 此时它是**主布位**。</p>
     *
     * <p>⚠️ 未知取值 ⇒ **不猜**（返回 null，让该维落到缺维处理），不得默认成布帘：
     * 枚举以后扩值（如「帘头」）时，旧代码静默按布帘算就是错配。</p>
     */
    static final Map<String, String> COMPONENT_ROLE_POSITIONS = Map.of(
            "纱", CURTAIN_TYPE_SHEER,
            "主布", CURTAIN_TYPE_CLOTH,
            COMPONENT_ROLE_EDGE, CURTAIN_TYPE_CLOTH);

    /**
     * 加工单状态：**加工中**。
     *
     * <p>它是 `issued → in_processing` 这条迁移的唯一目标态，**手工与自动两条路径共用同一个字符串**：
     * 手工 = {@link #updateStatus} 的 `action = "start"`；自动 = 首工序报满（issue #4695 / D13，
     * 落点在 {@code ProductionService}）。两条路径走**同一张状态机**（{@link #STATUS_TRANSITIONS}）——
     * 自动路径不另立判据、也不裸 UPDATE 绕过。</p>
     */
    static final String STATUS_IN_PROCESSING = "in_processing";

    /**
     * 加工单状态机（与 OrderService.STATUS_TRANSITIONS 同模式）。
     *
     * <p>🔴 {@code generated → in_processing}（issue #7723，用户 2026-10-25 裁定 A，落 A6 后半）：
     * 「发加工」不再是必经动作 —— 智能派单排出作业单后，工人首工序报满即进「加工中」。
     * 消费者 = {@code ProductionService.startProcessingIfAllowed}（合法性取自本表，不另写一份）。
     * {@code issued} 保留给存量单与 agent 通道，不再是新单的必经态。</p>
     */
    private static final Map<String, Set<String>> STATUS_TRANSITIONS = Map.of(
            "generated", Set.of("issued", STATUS_IN_PROCESSING, "cancelled"),
            "issued", Set.of(STATUS_IN_PROCESSING, "cancelled"),
            STATUS_IN_PROCESSING, Set.of("completed", "cancelled"),
            "completed", Set.of(),
            "cancelled", Set.of()
    );

    private static final Map<String, String> STATUS_LABELS = Map.of(
            "generated", "已生成",
            "issued", "已发加工",
            STATUS_IN_PROCESSING, "加工中",
            "completed", "加工完成",
            "cancelled", "已取消"
    );

    /**
     * 状态机的**唯一读口**（包级可见 ⇒ 同包的生产侧判合法性时不再抄第二份迁移表）。
     *
     * <p>为什么要有它：原表是 `private` ⇒ 外部消费者只能自己写一个字面量集合
     * （「同一真值两处投影」）⇒ 迟早漂移。首工序报满的自动路径（issue #4695 / D13）因此走本方法
     * 问合法性，落库谓词再取**本次被授权的那一个起始态** ⇒ 既走状态机、又不是裸 UPDATE。</p>
     *
     * <p>未知 / 缺失起始态一律 **false**（fail-closed：脏数据不推进，而不是替它挑一个合法起点）。</p>
     */
    static boolean allowsTransition(String from, String to) {
        return from != null && to != null && STATUS_TRANSITIONS.getOrDefault(from, Set.of()).contains(to);
    }

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
     * 待派池视图（issue #5169 判据 5 的可查面）—— 实现与完整口径见
     * {@link ProcessingOrderDispatchPool#pool}；本方法只保留**公开入口**
     * （控制器与既有判据按门面调用，签名与语义一字未改）。
     */
    public ProductionPoolViews.Pool pool(Long tenantId, BigDecimal maxWaitHoursRaw) {
        return dispatchPool().pool(tenantId, maxWaitHoursRaw);
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
        dispatchPool().assertNoUrgentInPooledBatch(orderIds, tenantId);
        dispatchPool().assertNoOutsourcedInPooledBatch(orderIds, tenantId);
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

    // ============================================================ 事件驱动自动成批（issue #5182 = 阶段 2b-3）

    /**
     * <b>自动成批派单的缺省值 = 开</b>（issue #6588；2026-10-09 用户裁定「记录期已结束，可以翻默认」）。
     *
     * <p>用户原话：「我觉得是不是不应该有这个开关，默认就应该开启智能派单」⇒ 智能派单是**默认能力**，
     * 不是要商家去拨的开关：满足成批条件（①②③）或已过最晚派单日 ⇒ 系统自己合并排料并派单，
     * 商家不必逐单勾选（人工入口「一键合并派单」照旧并存 —— 两条路都到同一个
     * {@link #generatePooled} 口径）。</p>
     *
     * <p><b>翻缺省改变了什么</b>：此前缺省 = 关，理由是「记录期基线」（#5145/#5158/#5167/#5169/#5177
     * 一路以「不启用 ⇒ 与今天逐值相同」为前提）；用户已裁定记录期结束 ⇒ 该前提不再成立，
     * 那条「缺省关 ⇒ 零动作」的判据随之退役（改为「**显式**关 ⇒ 零读零写」，见下）。</p>
     *
     * <p>🔴 <b>不变式（不因翻缺省而放松）</b>：{@code enabled=false}（显式策略 / 部署属性）⇒
     * {@link #autoBatchDispatch} <b>零读零写</b>立刻返回 —— 关闸仍是一条真闸
     * （红证 = 摘掉那行判定 ⇒ {@code explicitOffDoesNothingAtAll} 当场红）。</p>
     *
     * <p>缺省值只有这一个载体（Spring 属性 {@code migao.production.auto-batch.enabled} 覆盖它，
     * 属性缺失 ⇒ 本值）；运维回退 = 部署侧显式写 {@code =false}，**不改码**。
     * 红证 = 把它改回 {@code false} ⇒「缺省即开」那条判据当场变红。</p>
     */
    public static final boolean AUTO_BATCH_DEFAULT_ENABLED = true;

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

        /** 缺省策略（与 {@link #AUTO_BATCH_DEFAULT_ENABLED} 同源 ⇒ **开着**；要显式关，直接构造 {@code enabled=false} 的策略）。 */
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
     * @param enabled           本次是否真的评估了（{@code false} ⇒ **显式关**，零动作）
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
            // 🔴 判据 1（#6588 重写）：**显式关** ⇒ 零读零写（连池都不查）。
            // 缺省已翻成「开」⇒ 本条钉的从「缺省不动数据」变成「关闸真的关得上」。
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
            // 🔴 判据 4（#6588 重写）：**显式关** ⇒ 零读零写（与 autoBatchDispatch 同一条判断，不另立口径）
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
        LocalDate today = businessClock.today();
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
        return generate(orderIds, batches, tenantId, operator, assignmentRule, pooled, null, null);
    }

    /**
     * 批量派单 + **外发承接方 / 回厂日**（issue #7723，用户 2026-10-25 裁定 A）。
     *
     * <p>承接方粒度 = **整批一个**（用户裁定「整单外发」）：一批单发给同一家加工厂才合批，
     * 要分给两家就分两次派。{@code null} = 本厂自做（与改造前逐字相同）。</p>
     *
     * <p><b>订单联动时点的挪动</b>：{@code confirmed → producing} 从「发加工」（#4305）挪到本方法
     * （派单 = 决定要生产了）。改动理由见 {@link #commit}。待付款单仍不动订单
     * （订单状态机没有 {@code pending → producing}）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> batches,
                                         Long tenantId, String operator, String assignmentRule,
                                         Boolean pooled, String processorSupplierId,
                                         LocalDate expectedDeliveryDate) {
        // 承接方 / 回厂日在**任何写库之前**校验完（fail-closed：不存在/停用/非加工厂 ⇒ 整批拒绝）
        Consignee consignee = resolveConsignee(processorSupplierId, expectedDeliveryDate, tenantId);
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
                            operator, rule, consignee));
                } catch (BusinessException e) {
                    results.add(GenerateResult.fail(rawId, e.getCode(), e.getMessage(), e.getSuggestion()));
                }
            }
            return results;
        }
        return generatePooled(orderIds, byOrder, tenantId, operator, rule, consignee);
    }

    /**
     * **直派关闸**的机器可判错误码（issue #7507）。
     *
     * <p>与「生成失败」区分开：调用方（订单详情页 / agent）据此知道该**换个入口**（去智能派单），
     * 而不是去修订单或工序库 —— 同族口径见 {@code ERR_ROUTING_NOT_FOUND} 的「码 + suggestion」。</p>
     */
    public static final String ERR_DIRECT_DISPATCH_POOL_REQUIRED = "DIRECT_DISPATCH_POOL_REQUIRED";

    /** 直派被拒的商家可见文案（单一真值：@see #generateDirect）。 */
    public static final String DIRECT_DISPATCH_POOL_REQUIRED_MESSAGE =
            "作业单统一在「智能派单」生成：请到「智能派单」勾选该单派单（同料合并更省料）";

    /** 直派被拒时的可行动建议（#7634：待付款 / 加急同样走派单页 —— 不再有直派例外）。 */
    public static final String DIRECT_DISPATCH_POOL_REQUIRED_SUGGESTION =
            "到后台「智能派单」页勾选该单派单；待付款与加急订单同样在派单页派，不再从订单详情直派。";

    /**
     * 订单详情页 / agent 的**直派**入口 —— issue #7634 起对**所有**订单关闸（原 #7507 只拦非加急）。
     *
     * <h2>为什么要在这里关闸（而不是只藏按钮）</h2>
     * {@code POST /api/admin/processing-orders/generate} 与智能派单的
     * {@code POST /api/admin/production/pool/dispatch} 最终都落到 {@link #generate}，但前者的
     * {@code pooled} 缺省 = 关 ⇒ 只做逐单排料、**不做跨单同料合并**；而且它会在自动成批
     * （{@code AUTO_BATCH_DEFAULT_ENABLED}，事件驱动）评估之前把订单派走 ⇒ 那一单永久离开池子、
     * 失去合并省料的机会（用户 2026-10-23：「为什么从订单可以直接生成加工单，而不是默认走智能派单流程」）。
     * 只藏前端按钮挡不住 API / agent ⇒ 闸落在服务端这一处。
     *
     * <h2>加急单也不再放行（issue #7634，2026-10-24 用户裁定）</h2>
     * 旧口径（issue #5177 / #7507）给加急单留了直派出口。用户 2026-10-24 裁定「一起收，也要统一走
     * 智能派单」⇒ 本入口对**所有**订单关闸；加急单改在派单页的**插队区单派**
     * （{@code /dispatch} + {@code pooled=false}），能力不受影响。
     *
     * <h2>结果面</h2>
     * 与 {@link #generate} 逐单同一形状：被拒的单记 {@code GenerateResult.fail(rawId, code, message,
     * suggestion)}，**一行都不写**；未加急的单被拒不影响同批里的加急单（顺序 = {@code orderIds} 顺序）。
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generateDirect(List<String> orderIds, List<BatchAssignment> batches,
                                               Long tenantId, String operator, String assignmentRule) {
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        // 与 generate() 同一道「未匹配指派」校验（在任何写库之前）—— 语义不得因为多一层闸而漂移。
        Map<String, List<BatchAssignment>> byOrder = assignmentsByOrder(orderIds, batches);
        GenerateResult[] slots = new GenerateResult[orderIds.size()];
        List<String> allowed = new ArrayList<>();
        List<Integer> allowedSlots = new ArrayList<>();
        List<BatchAssignment> allowedBatches = new ArrayList<>();
        for (int i = 0; i < orderIds.size(); i++) {
            String rawId = orderIds.get(i);
            Order order = resolveOrder(rawId, tenantId);
            // 解析不到的订单**不在这里另造文案**：留给 generate() 的既有 ORDER_NOT_FOUND 分支
            // （两处文案必然漂移；「哪一步先失败」也是既有契约的一部分）。
            if (order != null) {
                slots[i] = GenerateResult.fail(rawId, ERR_DIRECT_DISPATCH_POOL_REQUIRED,
                        DIRECT_DISPATCH_POOL_REQUIRED_MESSAGE, DIRECT_DISPATCH_POOL_REQUIRED_SUGGESTION);
                continue;
            }
            allowed.add(rawId);
            allowedSlots.add(i);
            allowedBatches.addAll(byOrder.getOrDefault(rawId, List.of()));
        }
        if (!allowed.isEmpty()) {
            List<GenerateResult> generated = generate(allowed, allowedBatches, tenantId, operator,
                    assignmentRule);
            for (int k = 0; k < allowedSlots.size(); k++) {
                slots[allowedSlots.get(k)] = generated.get(k);
            }
        }
        return new ArrayList<>(java.util.Arrays.asList(slots));
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
                                                Long tenantId, String operator, String rule,
                                                Consignee consignee) {
        // 🔴 加急单**不进池**（issue #5177 判据 3）：混进成批批次 ⇒ 整批显式拒绝，**一行都不写**。
        // 放在 prepare 之前 ⇒ 拒绝时连只读准备都还没跑，更没有半成品。
        dispatchPool().assertNoUrgentInPooledBatch(orderIds, tenantId);
        dispatchPool().assertNoOutsourcedInPooledBatch(orderIds, tenantId);
        GenerateResult[] slots = new GenerateResult[orderIds.size()];
        List<Prepared> prepared = new ArrayList<>();
        List<Integer> indexes = new ArrayList<>();
        List<StockBatchConsumptionService.Designation> pooledLines = new ArrayList<>();
        for (int i = 0; i < orderIds.size(); i++) {
            String rawId = orderIds.get(i);
            try {
                Prepared p = prepare(rawId, byOrder.getOrDefault(rawId, List.of()), tenantId, operator,
                        rule, consignee);
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

    /**
     * 承接方（外发加工厂）解析 —— 派单写面的**唯一**校验点（issue #7723）。
     *
     * <p>三条 fail-closed：① 档案存在且属本租户；② 在用；③ 类型 = 加工厂
     * （{@code processor}）—— 采购供应商不得被派成外发承接方。回厂日早于今天同样拒绝
     * （沿用 issue #3901 的交期边界）。校验失败 ⇒ 整批拒绝（{@link #generate} 在任何写库之前调用）。</p>
     */
    private Consignee resolveConsignee(String processorSupplierId, LocalDate expectedDeliveryDate,
                                       Long tenantId) {
        if (expectedDeliveryDate != null && expectedDeliveryDate.isBefore(businessClock.today())) {
            throw BusinessException.validationError("回厂日不能早于今天");
        }
        if (!StringUtils.hasText(processorSupplierId)) {
            return new Consignee(null, null, expectedDeliveryDate);
        }
        if (supplierMapper == null) {
            throw new IllegalStateException(
                    "SupplierMapper 未装配 —— 外发承接方不能静默当成「本厂自做」（issue #7723）");
        }
        Supplier supplier = supplierMapper.selectById(processorSupplierId);
        if (supplier == null || Boolean.TRUE.equals(supplier.getDeleted())
                || !tenantId.equals(supplier.getTenantId())) {
            throw BusinessException.validationError("承接方（加工厂）不存在：" + processorSupplierId);
        }
        if (!SupplierService.STATUS_ACTIVE.equals(supplier.getStatus())) {
            throw BusinessException.validationError(
                    "承接方「" + supplier.getName() + "」已停用，请先启用或换一家");
        }
        if (!SupplierService.TYPE_PROCESSOR.equals(supplier.getType())) {
            throw BusinessException.validationError(
                    "「" + supplier.getName() + "」不是加工厂（档案类型须为 processor）");
        }
        return new Consignee(supplier.getId(), supplier.getName(), expectedDeliveryDate);
    }

    /**
     * 派单页「承接方」下拉的数据源（issue #7723）：只回**在用加工厂**的 id + 名称。
     *
     * <p>为什么不复用 {@code GET /api/admin/suppliers}：那把码是 {@code inbound:view}，
     * 生产岗（{@code processing:view}）通常没有 ⇒ 下拉会空，派单页被迫提权。本读面挂派单同码，
     * 且只暴露 id + 名称（不泄露联系人/账期/欠款）。</p>
     */
    public List<ProcessorOption> processorOptions(Long tenantId) {
        if (supplierMapper == null) {
            return List.of();
        }
        List<Supplier> suppliers = supplierMapper.selectList(new LambdaQueryWrapper<Supplier>()
                .eq(Supplier::getTenantId, tenantId)
                .eq(Supplier::getStatus, SupplierService.STATUS_ACTIVE)
                .eq(Supplier::getType, SupplierService.TYPE_PROCESSOR)
                .orderByAsc(Supplier::getName));
        List<ProcessorOption> out = new ArrayList<>();
        for (Supplier supplier : suppliers) {
            out.add(new ProcessorOption(supplier.getId(), supplier.getName()));
        }
        return out;
    }

    /** 外发承接方（解析后的**名称快照 + 档案引用 + 回厂日**；{@code null} 字段 = 本厂自做 / 不设）。 */
    private record Consignee(String supplierId, String name, LocalDate deliveryDate) {
    }

    /** 派单页下拉选项（issue #7723）：{@code id} = 档案引用，{@code name} = 展示名。 */
    public record ProcessorOption(String id, String name) {
    }

    /** 逐单派（缺省路径）：准备 → 本单求解 → 落库。与池化派**共用**同一条准备与落库链。 */
    private GenerateResult generateOne(String rawId, List<BatchAssignment> assignments,
                                       Long tenantId, String operator, String rule,
                                       Consignee consignee) {
        Prepared p = prepare(rawId, assignments, tenantId, operator, rule, consignee);
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
    /** 只读预览等**不派单**的路径：无承接方（与改造前逐字相同）。 */
    private Prepared prepare(String rawId, List<BatchAssignment> assignments,
                             Long tenantId, String operator, String rule) {
        return prepare(rawId, assignments, tenantId, operator, rule, null);
    }

    private Prepared prepare(String rawId, List<BatchAssignment> assignments,
                             Long tenantId, String operator, String rule, Consignee consignee) {
        Order order = resolveOrder(rawId, tenantId);
        if (order == null) {
            throw new BusinessException("ORDER_NOT_FOUND", "无法找到订单：" + rawId, 404);
        }
        // 作业单可在**待付款 / 已确认**生成（issue #7626）—— 作业单是生产计划，
        // 不扣库存、不记资金；收款与扣减仍只在 `OrderService.confirmPayment`。
        if (!GENERATABLE_ORDER_STATUSES.contains(order.getStatus())) {
            throw BusinessException.validationError(
                    String.format("订单 %s 当前状态 [%s] 不允许生成加工单（须为待付款 / 已确认）",
                            order.getOrderNo(), order.getStatus()));
        }
        // 外发单**必须**指定承接方（issue #7746 后续）：外发标记的含义就是「交给外部加工厂做」，
        // 派单时却选「本厂自做」= 自相矛盾 ⇒ 显式拒绝（不静默按本厂派，也不静默忽略标记）。
        if (Boolean.TRUE.equals(order.getIsOutsourced())
                && (consignee == null || !StringUtils.hasText(consignee.supplierId()))) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 已标记为外发加工，派单时必须选择承接方（加工厂）",
                    List.of(),
                    "在「智能派单」页顶部选「承接方」（加工厂）后再派；若这单其实本厂自己做，"
                            + "先到订单详情把「外发加工」关掉");
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
        PositionPayload payload = positionPayloadBuilder().buildPositionPayload(snapshot, tenantId);
        List<Map<String, Object>> positions = payload.positions();

        // 派工指定批次（V116 / issue #5145 阶段 1）：**只读校验 + 计划在任何写库之前跑完** ——
        // 与上面工序 payload 同一条纪律（generate() 逐单 catch BusinessException 后事务不回滚 ⇒
        // 写库之后再抛业务异常会留下「有加工单、扣了半截」的半成品，见
        // StockBatchConsumptionService 类注释「写面分两段」）。
        List<StockBatchConsumptionService.Designation> designations =
                buildDesignations(items, snapshot, assignments, tenantId, rule);

        // 单据类型（V159，issue #7079）：与快照**同一时机**冻结 —— 卖布单（每一行 saleForm=布料）
        // 落 `outbound`（出库作业单），其余（含混合单）落 `processing`。事后改订单行不回改。
        String orderKind = deriveOrderKind(snapshot);
        // 出库作业单**没有加工环节**（#7079：不设加工方 / 交期）⇒ 外发承接方对它无意义。
        // 显式拒绝而不是静默忽略：静默忽略 = 商家以为这批卖布单已经发给加工厂了。
        if (orderKind.equals(ORDER_KIND_OUTBOUND) && consignee != null && consignee.supplierId() != null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 是卖布单（出库作业单），只做出库作业，不支持外发加工厂");
        }

        ProcessingOrder po = ProcessingOrder.builder()
                .tenantId(tenantId)
                .orderId(order.getId())
                .processingOrderNo(generateOrderNo())
                .status("generated")
                .itemsSnapshot(snapshot)
                // 承接方 / 回厂日（V193，issue #7723）：**派单即写**（不再是作业单页上的「发加工」）。
                // 名称快照 + 档案引用同批落库；null = 本厂自做。
                .processor(consignee == null ? null : consignee.name())
                .processorSupplierId(consignee == null ? null : consignee.supplierId())
                .expectedDeliveryDate(consignee == null ? null : consignee.deliveryDate())
                .orderKind(orderKind)
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
     * **单据类型**（V159，issue #7079）—— 判定规则**冻结**为：快照非空**且每一行**
     * {@code saleForm == '布料'} ⇒ {@link #ORDER_KIND_OUTBOUND}；否则
     * {@link #ORDER_KIND_PROCESSING}（**混合单 = 有加工 ⇒ 加工**）。
     *
     * <p>判定在**生成那一刻**做一次并随 {@code items_snapshot} 一起落库（见 {@link #prepare}）——
     * 「这一单当时按哪一型做的作业」是**已发生的事实**，事后改订单行**不回改**、历史单不改型。</p>
     *
     * <p>⚠️ 快照行的 {@code saleForm} 由 {@link #CRAFT_SPEC_SNAPSHOT_KEYS} 从
     * {@code order_items.processing_info} **透传** ⇒ <b>缺键就是缺</b>（存量单的常态）：
     * 缺键的行按**非布料**处理，**不得为它造值**（造值 = 把「没这回事」写成「有这回事」）。</p>
     */
    private static String deriveOrderKind(List<Map<String, Object>> snapshot) {
        if (snapshot == null || snapshot.isEmpty()) {
            return ORDER_KIND_PROCESSING;
        }
        for (Map<String, Object> row : snapshot) {
            // 判据委托给唯一实现点（issue #7222）：显式 saleForm 优先，缺键按布料专属事实兜底。
            if (!isFabricSaleLine(row)) {
                return ORDER_KIND_PROCESSING;
            }
        }
        return ORDER_KIND_OUTBOUND;
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

        // 🔴 派单即生产（issue #7723，用户 2026-10-25 裁定 A）：订单 confirmed→producing 的
        // **唯一时点** 从「发加工」（#4305）挪到「派单」。为什么必须挪：发加工已不再是必经动作
        // （状态机放开 generated→in_processing）⇒ 仍留在那里的话，派单后没有任何人点它，
        // 订单就永远不会进 producing（作业单照做、订单永远「已确认」）。
        //
        // **联动先行 + 失败回退**（与 updateStatus 的 issue 分支同款 fail-closed）：先推进订单、
        // 再落作业单；随后任何写库失败都把订单回退 ⇒ 杜绝「订单生产中、作业单没生成」的孤儿态。
        // 待付款单**不动**（订单状态机没有 pending→producing；付款转 confirmed 后不会补推，
        // 这是存量缺口，本单不放大也不修 —— 见 issue #7723 的边界）。
        Order order = p.order();
        boolean orderLinked = OrderStatusTransitions.CONFIRMED.equals(order.getStatus());
        if (orderLinked) {
            orderService.lifecycleService().updateOrderStatus(order.getId(), OrderStatusTransitions.PRODUCING, orderService.sharedParts());
        }
        try {
            try {
                processingOrderMapper.insert(p.po());
            } catch (org.springframework.dao.DuplicateKeyException e) {
                throw BusinessException.validationError(
                        "订单 " + order.getOrderNo() + " 加工单已生成（并发操作），请刷新后重试");
            }
            log.info("生成加工单: no={}, orderId={}, tenantId={}, operator={}",
                    p.po().getProcessingOrderNo(), order.getId(), tenantId, operator);
        // 派工扣批次库存（issue #5145 判据 1）：与加工单生成**同一事务** ——
        // 加工单插入成功之后才扣（重复生成在更上游就被 selectActiveByOrderId +
        // uk_processing_orders_active 拒掉 ⇒ 不可能二次扣减）；计划已在插入前校验完，
        // 这里只落账、不再抛业务异常。不指定批次 ⇒ 计划为空 ⇒ 本段零动作（行为与今天逐字相同）。
            if (!deductions.isEmpty()) {
                batchStock().apply(tenantId, p.po().getProcessingOrderNo(), order.getOrderNo(), deductions);
            }
        // 工序实例化（issue #4116，P0 断链第一环）：加工单落行后**立即**实例化工序。
        // 此前 instantiate 端点全仓零调用者 ⇒ 工序列表恒空 ⇒ qr_token 恒 null ⇒
        // 任务卡只出「二维码待生成」占位、工人扫码报工不可达。
        // 工序序列已在插入前解析完毕（见 prepare 的 positions）：库取不到 ⇒ 根本走不到这里，
        // 所以本行的失败只可能是 DB 层错误 —— 那种情况异常逸出并由外层逐单
        // catch 记账，同样不留「有加工单、无工序」的静默半成品（工序另可由
        // POST .../instantiate 手工补做）。
            instantiateOperations(order, p.po(), p.positions(), tenantId);
            return GenerateResult.ok(p.rawId(), p.po().getProcessingOrderNo());
        } catch (RuntimeException e) {
            // 联动回退（issue #7723）：与 updateStatus 的 issue 分支同款 —— 落库失败 ⇒ 订单退回已确认，
            // 让商家刷新后能原样重派。回退自身失败只记 WARN（不掩盖主异常，也不能把主异常吞掉）。
            if (orderLinked) {
                try {
                    orderService.lifecycleService().revertProducingToConfirmed(order.getId(), "派单落库失败，订单状态回退");
                } catch (Exception revertErr) {
                    log.warn("派单落库失败且订单状态回退失败: orderId={}, err={}",
                            order.getId(), revertErr.getMessage());
                }
            }
            throw e;
        }
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
     * <b>测试探针</b>（issue #6954，生产恒为 {@code 0}）：在 {@link #updateStatus} 的「读-判」之后、
     * 「写」之前暂停指定毫秒。
     *
     * <p><b>为什么需要它</b>：窗口注入是竞态类缺陷的<b>唯一可信证据</b>形态
     * （{@code migao-dev-flow} §28.1）—— 判据要在「注入 ⇒ 必红 / 撤回 ⇒ 复绿」两侧各跑一次。
     * 窗口本身只有微秒级（#6928 实测 HTTP 20 轮只命中 3 轮），不注入就只能靠碰运气，判据会退化成 flake。</p>
     *
     * <p><b>为什么放在这里而不是只放测试侧</b>：窗口在服务方法体内，测试侧无法在「已判定仍可迁移、
     * 尚未落库」那一刻插进一段延时（除非用 {@code mock()} 替换真 mapper —— 那会把唯一的 DB 原子
     * 判据换成 mock 的恒真返回，判据当场失去意义）。故留这条窄缝，且只在包内可见
     * （{@code ProcessingOrderStatusCasRaceRealDbTest} 与生产同类同包）。与
     * {@code InboundOrderService#setCancelProbePauseMillisForTest}（#6928）逐字同款。</p>
     */
    static void setStatusUpdateProbePauseMillisForTest(long millis) {
        STATUS_UPDATE_PROBE_PAUSE_MILLIS = millis;
    }

    /** 测试探针时长（默认 0 = 不暂停）；见 {@link #setStatusUpdateProbePauseMillisForTest}。 */
    private static volatile long STATUS_UPDATE_PROBE_PAUSE_MILLIS = 0L;

    /** 探针**正在**暂停窗口内的信号（测试用它把两个线程钉在确定的时序上）。 */
    private static volatile boolean statusUpdateProbePaused = false;

    /** 测试观察点：探针是否已进入暂停窗口；生产不读。 */
    static boolean statusUpdateProbePausedForTest() {
        return statusUpdateProbePaused;
    }

    /** 测试观察点：当前注入的探针时长；生产不读。 */
    static long statusUpdateProbeMillisForTest() {
        return STATUS_UPDATE_PROBE_PAUSE_MILLIS;
    }

    /** 进入窗口 ⇒ 置位 → 停 → 清位（测试在「已置位 / 未清位」之间把另一条迁移走完）。 */
    private static void pauseStatusUpdateForProbe(long millis) {
        statusUpdateProbePaused = true;
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            statusUpdateProbePaused = false;
        }
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
                    // 🔴 2026-10-17（issue #7077，用户逐字「得把报错原因用业务文案写清楚，而不是技术语言」）：
                    // 旧文案把**内部规则码**（`fifo` / `best_fit`）与**明细行 id**（UUID）端给商家
                    // —— 两句都是他照着做不了的读数。现在说清四件事：哪一行（商品名）/ 要多少米 /
                    // 为什么补不上（按「先到先用」也找不到能整行裁出的批次）/ 下一步做什么（入库或核对余量）。
                    // ⚠️ 判据 `ProcessingOrderServiceTest#noCandidateUnderTheRuleFailsClosed` 同时钉
                    // 「新文案在」与「内部标识符不在」两条（把任一句写回去 ⇒ 红）。
                    String productName = str(row.get("productName"));
                    String lineLabel = StringUtils.hasText(productName) ? productName : "这一行";
                    throw BusinessException.validationError(String.format(
                            "「%s」这行需要 %s 米，库存里没有能裁出它的批次（按「先到先用」也补不上）"
                                    + "—— 请先把这批布入库，或核对库存里对应门幅与颜色的余量后重试",
                            lineLabel, meters.toPlainString()));
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
    static String snapshotSkuCode(Map<String, Object> row) {
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
     * 由 {@link ProductionOperationQueryService} 的新读面读出（见 {@link ProcessingRouteResolver#buildRoute}）。加工项目录（快照里的
     * `processingItems`）自此刻起**只**用于①派生路线键的信号、②加工单快照本身的展示，
     * **不再**提供工序 —— 旧的「工序 = 加工项名」路径已删除，取不到库数据时**显式失败**，
     * 不回退（回退会让「切库」变成装饰性的：旧路径还在 ⇒ 库为空也没人发现）。</p>
     *
     * <p><b>取路线判据</b>（订单侧**没有**部位/帘种字段，故必须显式定义取法）：按可派生信号
     * 匹配 `curtain_type`/`craft`，优先级 = 加工项名 &gt; 加工项 options &gt; 商品名 &gt; 销售方式，
     * 命中即止；两类信号全不命中 ⇒ 该租户的**默认路线模板**（见 {@link ProcessingRouteResolver#deriveRouteKey}
     * 与 {@link ProcessingRouteResolver#resolveRoute}）。</p>
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
     * 工艺维的**显式声明**（issue #4452）：取本行加工项在 {@code processing_items.craft_hint}
     * 里声明的工艺（{@link #buildSnapshot} 从加工项目录带进快照的 {@code craftHint} 键）。
     *
     * <p>都不声明 ⇒ 返回 null（该维按缺维处理）。</p>
     *
     * <p><b>声明了 ≥2 个**不同**工艺 ⇒ fail-closed（422）</b>（用户裁定 2026-09-19：「工艺单值护栏：
     * 每个部位最多一个声明工艺的加工项，两个 ⇒ fail-closed」，否则同一单会派生出**两套工序**
     * —— 工人按两遍单价拿钱）。本方法**只认「不同」**：同一工艺被多个加工项声明（如「韩褶」与
     * 「韩定+S钩」都声明工艺韩褶）是**合法**的，不算冲突。</p>
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
                    "请在订单里只保留一个带工艺的加工项（如「韩褶」或「打孔」），其余取消勾选");
        }
        return hints.isEmpty() ? null : hints.get(0);
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
     * {@link #buildSnapshot}（订单明细 → 部位/工艺信号）+ {@link ProcessingPositionPayloadBuilder#buildPositionPayload}（工序库路线）。
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
        return positionPayloadBuilder()
                .buildPositionPayload(buildSnapshot(loadOrderItems(order.getId(), tenantId), tenantId), tenantId)
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

    static String str(Object value) {
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
            // 卖布判据（issue #7222）：缺 `saleForm` 时按**订单行已落库的布料专属事实**兜底 ——
            // API / 米宝 / 回归脚本漏写 `saleForm` 时，这一行仍必须进快照，否则
            // `buildPositionPayload` 的布料分支永不执行 ⇒ 工人拿不到裁剪 / 打包活（#4909 的同族形态）。
            Map<String, Object> fabricEvidence = new LinkedHashMap<>(pi);
            if (item.getSellingMethod() != null) {
                fabricEvidence.put("sellingMethod", item.getSellingMethod());
            }
            if (item.getRollCount() != null) {
                fabricEvidence.put("rollCount", item.getRollCount());
            }
            if (procs.isEmpty() && !isFabricSaleLine(fabricEvidence)) {
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
            // 布料专属事实（issue #7222）：列值 = **服务端落库的事实**，优先于 processing_info 的同名键
            // ⇒ 客户端漏写 `saleForm` 时，路线键与单据类型仍能认出这一行是卖布行。
            if (item.getSellingMethod() != null) {
                entry.put("sellingMethod", item.getSellingMethod());
            }
            if (item.getRollCount() != null) {
                entry.put("rollCount", item.getRollCount());
            }
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
        String base = "JG-" + businessClock.today().format(PO_DATE_FMT) + "-";
        // DB 唯一约束兜底；此处随机化降低同秒碰撞概率
        return base + String.format("%04d", PO_SEQ.incrementAndGet());
    }

    // ============================================================ 状态更新

    /**
     * 加工单状态更新（action: issue/start/complete/cancel）—— **手工端点**。
     * 状态机校验 + 订单联动（issue → 订单 confirmed→producing；cancel → 订单 producing→confirmed 回退）。
     *
     * <p>🔴 <b>{@code action = "start"} 的语义（issue #4695 起显式写明）</b>：它是
     * `issued → in_processing` 这条迁移的**手工入口**，与首工序报满的**自动入口**
     * （{@code ProductionService}：完成 `is_start_marker` 那道工序 ⇒ 落同一个状态）**目标态相同、
     * 状态机相同**。二者分工：</p>
     * <ul>
     *   <li><b>自动（默认路径）</b>= 首工序报满时由报工链自动落 —— 单进入「生产中」不再依赖人点按钮；</li>
     *   <li><b>手工（本端点，保留）</b>= 存量单补开工 / 自动路径不适用时的兜底：单里没有任何
     *       `is_start_marker` 工序、首工序报工时该单尚未「发加工」（`generated` 不得直达，A6 未裁定
     *       ⇒ 自动路径不动它）、或首工序早在自动路径上线前就报满了。</li>
     * </ul>
     * <p>已是 `in_processing` 时本端点**照旧拒绝**（`in_processing → in_processing` 不是合法迁移）——
     * 与自动路径的幂等语义一致：重复请求得到一句明确的「不允许变更」，而不是静默成功。</p>
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
            case "start": target = STATUS_IN_PROCESSING; break;
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

        // 本次迁移只 SET 自己那一列（issue #6954）：issue 只动 issued_at/processor/交期、
        // cancel 只动 cancelled_at/reason —— 与 OrderService 的 T2b 同一条纪律
        // （不整实体回写 ⇒ 不把不负责的列 / 并发的状态变更一并覆写）。
        OffsetDateTime now = OffsetDateTime.now();
        OffsetDateTime issuedAt = null;
        String processor = null;
        LocalDate expectedDeliveryDate = null;
        OffsetDateTime inProcessingAt = null;
        OffsetDateTime completedAt = null;
        OffsetDateTime cancelledAt = null;
        String cancelledReason = null;
        switch (action) {
            case "issue":
                // issue #3901：交期不允许早于今天（前端 date 控件之外的兜底，同时覆盖 agent processing_order_update 路径）
                if (req.getExpectedDeliveryDate() != null
                        && req.getExpectedDeliveryDate().isBefore(businessClock.today())) {
                    throw BusinessException.validationError("交付日期不能早于今天");
                }
                issuedAt = now;
                processor = req.getProcessor();
                expectedDeliveryDate = req.getExpectedDeliveryDate();
                break;
            case "start":
                inProcessingAt = now;
                break;
            case "complete":
                completedAt = now;
                break;
            case "cancel":
                cancelledAt = now;
                cancelledReason = req.getReason();
                break;
            default:
                break;
        }
        // 测试探针（issue #6954）：放大「读-判」与「写」之间的窗口（生产恒为 0）。与 #6928 的作废探针同款：
        // 窗口只有微秒级，不注入就只能靠碰运气，判据会退化成 flake。
        if (STATUS_UPDATE_PROBE_PAUSE_MILLIS > 0) {
            pauseStatusUpdateForProbe(STATUS_UPDATE_PROBE_PAUSE_MILLIS);
        }
        // 联动先行（issue #4305，用户裁定「发加工 = 订单进入生产中」）：**发加工是订单
        // confirmed→producing 的唯一时点**（生成加工单不再推进订单）。先推进订单、再落加工单
        // issued —— 落库失败时回退订单状态，杜绝「订单生产中、加工单未发出」孤儿态
        // （形态 = #3345 P2② 给 generate 的同款 fail-closed，现随联动一并挪到这里）。
        // 已是 producing 的订单（旧语义下「生成即推进」的存量数据）不重复推进、也不回退。
        boolean orderLinked = false;
        if ("issue".equals(action)) {
            Order order = orderMapper.selectById(po.getOrderId());
            if (order != null && OrderStatusTransitions.CONFIRMED.equals(order.getStatus())) {
                orderService.lifecycleService().updateOrderStatus(order.getId(), OrderStatusTransitions.PRODUCING, orderService.sharedParts());
                orderLinked = true;
            }
        }
        try {
            // 状态迁移 = **条件更新**（issue #6954）：谓词含 id + tenant_id + deleted=0 + **状态机授权的前驱**
            // ⇒ 与并发的相反迁移争同一份迁移权。修前是 updateById（WHERE 仅主键）⇒ 两个相反迁移可双双成功、
            // 终态由后写者决定（issued 与 cancelled 互不可达 ⇒ 终态必然自相矛盾）。0 行 ⇒ 409 + 实际当前态。
            int rows = processingOrderMapper.markStatusIfFrom(po.getId(), tenantId, current, target,
                    issuedAt, processor, expectedDeliveryDate, inProcessingAt, completedAt,
                    cancelledAt, cancelledReason, now);
            if (rows == 0) {
                ProcessingOrder fresh = resolveProcessingOrder(rawId, tenantId);
                throw BusinessException.conflict(
                        String.format("加工单状态不允许从 [%s] 变更为 [%s]",
                                label(fresh != null ? fresh.getStatus() : current), label(target)),
                        "该加工单的状态刚被另一个操作变更，请刷新后按当前状态重试");
            }
        } catch (Exception e) {
            if (orderLinked) {
                try {
                    orderService.lifecycleService().revertProducingToConfirmed(po.getOrderId(), "加工单发加工落库失败，订单状态回退");
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
            if (order != null && OrderStatusTransitions.PRODUCING.equals(order.getStatus())) {
                orderService.lifecycleService().revertProducingToConfirmed(order.getId(),
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
        return list(keyword, status, tenantId, null);
    }

    /**
     * 加工单列表 + **只看外发**（issue #7723）。
     *
     * <p>{@code outsourced = true} ⇒ 只回「有承接方档案引用」的行（外发在途的跟踪面）。
     * 过滤在内存里做（列表上限 100 行，不值得为它另写一条 SQL + 关键词分支的第二套条件）；
     * 缺省/空白 ⇒ 与改造前逐字相同。</p>
     */
    public List<ProcessingOrderResponse> list(String keyword, String status, Long tenantId,
                                              Boolean outsourced) {
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
        if (Boolean.TRUE.equals(outsourced)) {
            // 过滤成**副本**：不原地改 mapper 返回的集合（那会把「被裁过的列表」留给上游/同一次请求里
            // 的第二个读面；测试里的 mock 更会当场暴露这件事）
            list = list.stream()
                    .filter(po -> StringUtils.hasText(po.getProcessorSupplierId()))
                    .toList();
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
            // #6226：空集分支**必须**返回容忍空键的表。此前是 `Map.of()`（不可变空表）—— 它的
            // `get(null)` 会抛 NPE，而调用点 `orders.get(po.getOrderId())` 的键**未判空**
            // ⇒ 该批加工单只要 `order_id` 全为空就整页 500。下面非空分支返回的是
            // `new HashMap<>()`（同族、`get(null)` 返 null）⇒ 这里取同一形态，两个分支契约一致。
            return new HashMap<>();
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

    /**
     * 加工单纸上的码 = {@code {稳定域名}/o/{短码}}（issue #6867 / B3；设计
     * {@code docs/design/worker-h5-scan-and-report.md} §11.3 的「后端 · 读面键」行）。
     *
     * <p><b>服务端拼装</b>（前端不拼 URL —— 拼法只有这一份），域名走上面 {@link #shortLinkBaseUrl}
     * 那条既有配置。形态与 {@code ProductionService.scanUrlOf(ProcessingSetPartToken)} **同款**
     * （设计 §11.3 明写「base + 路径段不同 ⇒ **各自一份，不许互相拼**」：{@code /s/} 解「哪一张
     * 部位纸」、{@code /o/} 解「哪一张加工单纸」，两个码空间互不命中）。</p>
     *
     * <p>🔴 <b>短码为空（存量行尚未分配）⇒ 返回 {@code null}</b>，**绝不产出 {@code /o/null}
     * 这种假码** —— 前端按「无码」处（纸面印 {@code —}），而不是把一个扫不开也输不进的串印出去。
     * 与 {@code token} 无关：撤销（{@code qr_token} 置 NULL）**不碰短码**，故本键**不因撤销变 null**
     * （那一跳 {@code /o/{短码}} 见 token 为空 ⇒ 410 Gone，归 B2）。</p>
     */
    private String scanUrlOf(ProcessingOrder po) {
        if (po == null || !StringUtils.hasText(po.getShortCode())) {
            return null;
        }
        String base = shortLinkBaseUrl == null ? "" : shortLinkBaseUrl.trim();
        while (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        return base + "/o/" + po.getShortCode();
    }

    @SuppressWarnings("unchecked")
    private ProcessingOrderResponse toResponse(ProcessingOrder po, Long tenantId, Order order) {
        ProcessingOrderResponse resp = new ProcessingOrderResponse();
        resp.setId(po.getId());
        resp.setTenantId(String.valueOf(po.getTenantId()));
        resp.setOrderId(po.getOrderId());
        resp.setProcessingOrderNo(po.getProcessingOrderNo());
        resp.setProcessor(po.getProcessor());
        resp.setProcessorSupplierId(po.getProcessorSupplierId());
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
        // 单据类型（V159，issue #7079）：同表列，随既有查询**已经带回** ⇒ 零新增查询（同 route_* 三列）。
        resp.setOrderKind(po.getOrderKind());
        // 加工单纸上的码（issue #6867 / B3；设计 §11.3「后端 · 读面键」）：**追加**两键，
        // 键**恒在**（未知 ⇒ null），既有键一字不动。
        // 🔴 **零新增查询**：`po` 由本方法的唯一入口 `resolveProcessingOrder`（详情）/
        // `selectList`/`selectByKeyword`（列表）**已经带回**（`short_code` 是同表列）⇒
        // 这里只做映射与拼串，不为这两键多查一次 DB。
        resp.setShortCode(po.getShortCode());
        resp.setScanUrl(scanUrlOf(po));
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
