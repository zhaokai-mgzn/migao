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
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

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
     * **自动批次决策族**（issue #8770 自动批次一档）：惰性构造，**不进构造器** —— 与
     * {@link #dispatchPool()} 同一理由（构造器是 16 处直接 {@code new} 的契约）。单元**无状态**，
     * 只持有回调门面的窄接口；回调**即时**取值（时钟 / 算料服务可能被既有判据在构造之后换掉）。
     * 公开面（策略记录 / 读数记录 / 常量 / {@code autoBatchPolicy}）仍住门面 —— 它们是
     * {@code AutoBatchDispatchListener} 与既有判据的取用面。
     */
    private ProcessingOrderAutoBatch autoBatch;

    private ProcessingOrderAutoBatch autoBatch() {
        if (autoBatch == null) {
            autoBatch = new ProcessingOrderAutoBatch(new ProcessingOrderAutoBatch.Owner() {
                @Override
                public ProductionPoolViews.Pool pool(Long tenantId, BigDecimal maxWaitHours) {
                    return ProcessingOrderService.this.pool(tenantId, maxWaitHours);
                }

                @Override
                public List<GenerateResult> generate(List<String> orderIds,
                                                     List<BatchAssignment> assignments, Long tenantId,
                                                     String operator, String rule, Boolean pooled) {
                    return ProcessingOrderService.this.generate(orderIds, assignments, tenantId,
                            operator, rule, pooled);
                }

                @Override
                public LocalDate today() {
                    return businessClock.today();
                }

                @Override
                public StockBatchConsumptionService batchStock() {
                    return ProcessingOrderService.this.batchStock();
                }
            });
        }
        return autoBatch;
    }

    /**
     * **快照构建单元**（issue #8770 快照/读面一档）：惰性构造，**不进构造器** —— 与
     * {@link #dispatchPool()} 同一理由（构造器是 16 处直接 {@code new} 的契约）。单元**无状态**，
     * 只持有 {@code processingItemMapper} + {@code objectMapper}（两个都是门面的既有依赖）。
     */
    private ProcessingOrderSnapshotBuilder snapshotBuilder;

    private ProcessingOrderSnapshotBuilder snapshotBuilder() {
        if (snapshotBuilder == null) {
            snapshotBuilder = new ProcessingOrderSnapshotBuilder(processingItemMapper, objectMapper);
        }
        return snapshotBuilder;
    }

    /**
     * **读面单元**（issue #8770 快照/读面一档）：惰性构造，理由同上。单号解析留在门面
     * （状态机 / 打印计数 / 详情都在用）⇒ 本类经窄接口 {@link ProcessingOrderReadFace.Owner} 回调，
     * 且**即时取值**（详情域名可能被既有判据在构造之后换掉）。
     */
    private ProcessingOrderReadFace readFace;

    private ProcessingOrderReadFace readFace() {
        if (readFace == null) {
            readFace = new ProcessingOrderReadFace(processingOrderMapper, orderMapper, objectMapper,
                    new ProcessingOrderReadFace.Owner() {
                        @Override
                        public ProcessingOrder resolveProcessingOrder(String rawId, Long tenantId) {
                            return ProcessingOrderService.this.resolveProcessingOrder(rawId, tenantId);
                        }

                        @Override
                        public Order resolveOrder(String rawId, Long tenantId) {
                            return ProcessingOrderService.this.resolveOrder(rawId, tenantId);
                        }

                        @Override
                        public String scanBaseUrl() {
                            return ProcessingOrderService.this.shortLinkBaseUrl;
                        }
                    });
        }
        return readFace;
    }

    /**
     * **派单生成链单元**（issue #8770 生成族一档）：惰性构造，**不进构造器** —— 与
     * {@link #dispatchPool()} 同一理由（构造器是既有判据直接 {@code new} 的契约，共 20 处装配面）。
     * 单元**无状态**，只持有两个不可变依赖 + 回调门面的窄接口；回调**即时取值**
     * （时钟 / 算料服务 / 工序 payload 构造器都可能被既有判据在构造之后换掉）。
     */
    private ProcessingOrderGeneration generation;

    private ProcessingOrderGeneration generation() {
        if (generation == null) {
            generation = new ProcessingOrderGeneration(processingOrderMapper, objectMapper,
                    new ProcessingOrderGeneration.Owner() {
                        @Override
                        public LocalDate today() {
                            return businessClock.today();
                        }

                        @Override
                        public BusinessClock businessClock() {
                            return businessClock;
                        }

                        @Override
                        public StockBatchConsumptionService batchStock() {
                            return ProcessingOrderService.this.batchStock();
                        }

                        @Override
                        public ProcessingPositionPayloadBuilder positionPayloadBuilder() {
                            return ProcessingOrderService.this.positionPayloadBuilder();
                        }

                        @Override
                        public ProcessingOrderDispatchPool dispatchPool() {
                            return ProcessingOrderService.this.dispatchPool();
                        }

                        @Override
                        public SupplierMapper supplierMapper() {
                            return supplierMapper;
                        }

                        @Override
                        public ProductionService productionService() {
                            return productionService;
                        }

                        @Override
                        public OrderService orderService() {
                            return orderService;
                        }

                        @Override
                        public Order resolveOrder(String rawId, Long tenantId) {
                            return ProcessingOrderService.this.resolveOrder(rawId, tenantId);
                        }

                        @Override
                        public List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
                            return ProcessingOrderService.this.loadOrderItems(orderId, tenantId);
                        }

                        @Override
                        public List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
                            return ProcessingOrderService.this.buildSnapshot(items, tenantId);
                        }
                    });
        }
        return generation;
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
    static final List<String> CALC_OUTPUT_SNAPSHOT_KEYS = List.of(
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
    static final Map<String, String> CALC_OUTPUT_SOURCE_KEY_ALIASES = Map.of(
            "formula_text", "formulaText");

    /**
     * 加工单快照要固化的**工艺规格**键（issue #4354，设计文档 §4.2 / §4.8）：
     * {@code processing_info} 顶层扁平键，订单侧下单时原样落库。
     *
     * <p>⚠️ 新键不加进这里就**不会进快照**（{@link #buildSnapshot} 逐键取）⇒
     * 「车间少一道活 / 少一个展示字段」，而快照是加工单的固化真相，事后补不回来。</p>
     */
    static final List<String> CRAFT_SPEC_SNAPSHOT_KEYS = List.of(
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
    static final String SNAPSHOT_ORDER_URGENT = "isUrgent";

    /** 订单级**客户要求到货日**的快照键（{@code YYYY-MM-DD}；**缺值不落键**）。见 {@link #SNAPSHOT_ORDER_URGENT}。 */
    static final String SNAPSHOT_ORDER_REQUIRED_DELIVERY_DATE = "requiredDeliveryDate";

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

    // 加工单号取号（P0-5，issue #9021）在 ProcessingOrderNoAllocator —— 本类已进体量棘轮的冻结清单
    // （只许变短），新增逻辑不再往这里堆；见该类注释的「病根 / 为什么不能捕获异常」。

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
        return generation().preview(tenantId, orderIds, batches, assignmentRule);
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
        ProcessingOrderHeaderStamp.stampOrderUrgency(snapshot, order);
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
        return autoBatch().dispatch(tenantId, trigger, policy);
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
        return autoBatch().dispatchDue(tenantId, trigger, policy);
    }

    /** 到期理由的**唯一措辞**（两条腿的 {@code reasons} 逐字一致 ⇒ 痕迹可对比、不留两套说法）。 */
    static String dueReason(ProductionPoolViews.PoolLine first, LocalDate latest) {
        return "order=" + first.orderNo() + ":business_due=" + latest
                + (first.requiredDeliveryDate() != null
                ? "(required_delivery_date=" + first.requiredDeliveryDate() + ")"
                : "(no_required_delivery_date ⇒ 进池日 + 标准生产周期)");
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

    // ============================================================ 生成

    /**
     * 批量生成加工单（全事务；单个失败不影响已成功项结果返回，但整体回滚）。
     * 返回逐单结果（success/processingOrderNo/message）。
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, Long tenantId, String operator) {
        return generation().generate(orderIds, tenantId, operator);
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
        return generation().generate(orderIds, batches, tenantId, operator);
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
        return generation().generate(orderIds, batches, tenantId, operator, assignmentRule);
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
        return generation().generate(orderIds, batches, tenantId, operator, assignmentRule, pooled);
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
        return generation().generate(orderIds, batches, tenantId, operator, assignmentRule, pooled,
                processorSupplierId, expectedDeliveryDate);
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
        return generation().generateDirect(orderIds, batches, tenantId, operator, assignmentRule);
    }

    /** 池级求解结果按 {@code orderItemId} 归拢（一行可能命中多行 —— 同一行被拆到多批次时才发生）。 */

    /** 本单该落的那几行（**按本单指派顺序**取 ⇒ 与逐单派落的行序逐值相同）。 */

    /**
     * 派单页「承接方」下拉的数据源（issue #7723）：只回**在用加工厂**的 id + 名称。
     *
     * <p>为什么不复用 {@code GET /api/admin/suppliers}：那把码是 {@code inbound:view}，
     * 生产岗（{@code processing:view}）通常没有 ⇒ 下拉会空，派单页被迫提权。本读面挂派单同码，
     * 且只暴露 id + 名称（不泄露联系人/账期/欠款）。</p>
     */
    public List<ProcessorOption> processorOptions(Long tenantId) {
        return generation().processorOptions(tenantId);
    }

    /** 外发承接方（解析后的**名称快照 + 档案引用 + 回厂日**；{@code null} 字段 = 本厂自做 / 不设）。 */

    /** 派单页下拉选项（issue #7723）：{@code id} = 档案引用，{@code name} = 展示名。 */
    public record ProcessorOption(String id, String name) {
    }

    /** 逐单派（缺省路径）：准备 → 本单求解 → 落库。与池化派**共用**同一条准备与落库链。 */

    /**
     * 只读准备（**不写任何一行**）：解析订单 → 状态闸 → 快照 → 幂等闸 → 工序 payload →
     * 扣减入参（{@link #buildDesignations}）。
     *
     * <p>语句顺序与拆分前的 {@code generateOne} **逐字相同**（判据 1 要的「不启用池化 ⇒
     * 逐值相同」包括「哪一步先失败」——把幂等闸挪到快照之前就会换一条错误文案）。</p>
     */
    /** 只读预览等**不派单**的路径：无承接方（与改造前逐字相同）。 */

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
    static String deriveOrderKind(List<Map<String, Object>> snapshot) {
        return ProcessingOrderHeaderStamp.deriveOrderKind(snapshot);
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
    static void stampCuttingPlan(List<Map<String, Object>> snapshot,
                                 List<StockBatchConsumptionService.Deduction> plan) {
        ProcessingOrderCuttingStamp.stampCuttingPlan(snapshot, plan);
    }

    /** 把指定的批次号写进快照行（`batchNo` = 加工单的固化真相里「这行从哪一批裁」）。 */
    static void stampAssignedBatches(List<Map<String, Object>> snapshot,
                                     List<StockBatchConsumptionService.Deduction> plan) {
        ProcessingOrderCuttingStamp.stampAssignedBatches(snapshot, plan);
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
     * 快照构建的**唯一入口**（体积已下沉到 {@link ProcessingOrderSnapshotBuilder}）。
     *
     * <p>保留这一层而不是把三个调用点改成 {@code snapshotBuilder().buildSnapshot(...)}：调用点
     * （{@code generate} / {@code derivePositionPayload} / 派单池 {@code Owner}）与全部
     * {@code {@link #buildSnapshot}} 文档引用因此**一字未改**。</p>
     */
    private List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
        return snapshotBuilder().buildSnapshot(items, tenantId);
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
        return readFace().list(keyword, status, tenantId, outsourced);
    }

    public ProcessingOrderResponse getDetail(String rawId, Long tenantId) {
        return readFace().getDetail(rawId, tenantId);
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
