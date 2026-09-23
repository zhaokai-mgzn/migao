package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;
import java.util.regex.Pattern;

/**
 * 扫码解析 + 工序推断（切片 ①，issue #4698；设计 {@code docs/design/set-code-and-scan-loop.md} §2.3 / §2.6 / §3）。
 *
 * <p><b>本切片是只读面</b>：只到「解析出 (套, 部位) + 推断出该报哪一道工序 + 返回一屏所需数据」，
 * <b>不写库</b>（报工主闭环 = 切片 ②）。因此本类的全部方法都**不**带 {@code @Transactional}、
 * **不**落任何痕。</p>
 *
 * <h2>① 解析顺序（设计 §2.6，五形态）</h2>
 * <ol>
 *   <li><b>新 token</b>（{@code processing_set_part_tokens.token}，带套带部位）⇒ 返回
 *       {@code (set_id, order_item_id, position)}，<b>部位由码给出、工人不选</b>；</li>
 *   <li>旧 {@code processing_orders.qr_token} → ③ {@code processing_order_no} → ④ {@code order_no}
 *       → ⑤ 内部 {@code order_id} —— 后四形态是 {@link ProductionService#resolveOrder} 的
 *       <b>既有冻结契约，一字不动</b>（issue #4005 / #4222），本类**只调用、不复制**；</li>
 * </ol>
 * 旧码命中 ⇒ <b>降级形态</b>：{@code granularity="order"} + {@code needs_selection:["set","position"]}
 * + 可选清单（该单的套 × 部位）。🔴 <b>绝不默认取第 1 套</b> —— 默认 = 静默把进度记到错的套上，
 * 正是要治的病（设计 §2.6）。降级形态的 {@code set_no} / {@code set_index} / {@code position} /
 * {@code operation} 一律 {@code null}（**不猜**）。
 *
 * <h2>② 推断算法（设计 §3.2）</h2>
 * <pre>
 * ① 部位级：扫到的那个部位的未完成工序 ⇒ min(seq)
 * ② 套级回落：本部位干完了，但整樘窗还有套级活（打卷/装袋/发货）⇒ min(seq) + rerouted=true
 * ③ 本套无活可做 ⇒ completed=true（不报错）
 * </pre>
 * <b>为什么必须有 ②</b>：套级工序只落在樘窗组的主布行（F11）⇒ 工人做完纱帘、拿纱帘的码再扫时，
 * 只按 ① 会得到「无工序可做」，而整樘窗其实还没做完 ⇒ 闭环断在这里。
 *
 * <h2>③ 硬约束：工序必须确定（设计 §3.3，用户裁定②-2）</h2>
 * 「不拦生产顺序」管<b>准入</b>，「工序必须确定」管<b>记账的确定性</b>（工资不能记到猜的那道）。
 * 本类兑现前半句的**唯一**实现方式：<b>绝不产出非唯一确定的工序</b> ——
 * 推断出多道（{@code seq} 重复的脏数据）且未显式给 {@code operation_id} ⇒
 * {@code OPERATION_AMBIGUOUS}（422，不返回任何工序），<b>不静默取第一道</b>。
 * 切片 ② 的记账入口在此之上加「未确定 ⇒ 拒绝写 {@code production_work_logs}」。
 *
 * <p><b>与设计的偏离（照实登记）</b>：</p>
 * <ul>
 *   <li>{@code PENDING} 的判据用<b>既有</b> {@link ProductionService#isDone}（{@code done_qty ≥ qty}），
 *       而不是设计 §3.2 字面的 {@code status <> 'done'} —— 报工允许**部分数量**
 *       （{@code assertWithinPlannedQty} 只拒绝超上限），而 {@code advanceDoneQtyIfUnchanged}
 *       一旦推进就把 {@code status} 置 {@code 'done'} ⇒ 照字面实现会让「报了 6/11 米」的工序
 *       从默认建议里消失、**永远做不完**（与 §3.4「默认数量 = 应做数量」的续报语义冲突）。
 *       取既有口径同时满足「不新造第二份口径」。</li>
 *   <li>§3.1 的 {@code display_name} 不落：显示名 = {@code logical_name} + {@code position}，
 *       由**既有**前端 helper 拼接（本类只给两个源键）—— 在 Java 侧再拼一份就是第二份口径
 *       （#4621 / #4630 的同族纪律）。</li>
 *   <li>{@code stalled}（§3.1）**已于切片 ③（issue #4776）落码**：判据本体在
 *       {@link ProductionStuckPointService}（A 模式只判「没开工」那一种；「卡了多久」取前道
 *       {@code done_at}）—— 本类只把该键**加**进响应（既有键一字不动）。</li>
 * </ul>
 *
 * <p><b>issue #5247 的搬移登记（结构性判据的落点）</b>：本类的 {@code set_overview} 聚合、
 * 部位整形（{@code positionEntry} / {@code positionView} / {@code productNameOf}）、
 * 套内/单内工序查询（{@code listSetOperations} / {@code listOrderOperations}）、{@code completedAt}
 * 与 {@code requireProcessingOrder} **原样搬到</b> {@link ProcessingSetReadService}（全仓唯一一份聚合），
 * 本类改为反向依赖它 ⇒「工人扫码面」与「商家/agent 套件读面」的两处 {@code set_overview}
 * **结构性同源**（改一处 ⇒ 两侧同变；红证见 {@code ProcessingSetReadServiceTest}）。
 * 本单**不改**本类任何对外键/值 —— 既有扫码响应一字未动。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionScanService {

    /** 解析粒度：新码（套 × 部位）—— 部位由码给出，工人不选。 */
    public static final String GRANULARITY_SET_POSITION = "set_position";

    /** 解析粒度：旧码降级（加工单级）—— 必须选套 + 选部位（设计 §2.6）。 */
    public static final String GRANULARITY_ORDER = "order";

    /** 推断来源：系统推断的下一道待做。 */
    public static final String DETERMINED_BY_INFERRED = "inferred";

    /** 推断来源：工人一键改（显式指定）。 */
    public static final String DETERMINED_BY_PICKED = "picked";

    /** 套级工序的作用域取值（{@code production_operations.scope}，V67 / issue #4384 A1）。 */
    private static final String SCOPE_SET = "set";

    /** 旧码降级形态必须由工人补齐的两个选择（设计 §2.6 逐字）。 */
    private static final List<String> DEGRADED_NEEDS_SELECTION = List.of("set", "position");

    /**
     * URL 里承载码值的键（**与前端 counterpart {@code frontend/worker-h5/src/scan-input.mjs} 的
     * {@code CODE_KEYS} 同一份口径**：只认这三个，其它 query 参数一律不当码值）。
     */
    private static final List<String> SCAN_CODE_KEYS = List.of("t", "token", "code");

    /** 「像 URL」= 含协议前缀（与前端 `parseScanInput` 的判据同形）。 */
    private static final Pattern URL_PREFIX = Pattern.compile("^[a-zA-Z][a-zA-Z0-9+.\\-]*://");

    private final ProcessingSetPartTokenMapper setPartTokenMapper;
    private final ProcessingOrderSetMapper orderSetMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    /** 工序库（判「部位级 / 套级」的**唯一**来源：实例行不带 scope，逐字取库、不硬编码工序名）。 */
    private final ProductionOperationQueryService operationQueryService;
    /**
     * 复用**冻结的四形态订单解析**（issue #4005 / #4222）：旧码路径必须是同一份实现 ——
     * 在扫描侧再写一份就是第二份口径（两处迟早不同），故只调用 {@link ProductionService#resolveOrder}。
     */
    private final ProductionService productionService;

    /**
     * 「卡在哪」的判据（切片 ③，issue #4776；设计 §6）：一屏输出里的 {@code stalled} 键由它算。
     *
     * <p>判据**只有一份**（{@link ProductionStuckPointService}）—— 在扫描侧再写一遍
     * 「没开工 / 上道完成时刻 / 等超阈值」就是第二份口径（两处迟早不同）。</p>
     */
    private final ProductionStuckPointService stuckPointService;

    /**
     * 套件读面（issue #5247 的 admin-api 半边）：本类的 {@code set_overview} 聚合、部位整形、
     * 套内/单内工序查询、{@code completedAt} 与加工单归属校验**全部**由它提供
     * （那是**唯一一份**实现 —— 原本长在本类里，本单**原样搬走**并由本类反向依赖）。
     *
     * <p>🔴 <b>不得在本类再写第二份</b>：「这一套还有哪几道没做」若有两份实现，工人屏与商家/agent
     * 读面迟早不同 —— 而工人据此领活、系统据此计件（设计 §4.1 单一口径）。</p>
     */
    private final ProcessingSetReadService processingSetReadService;

    // ============================================================ 解析入口

    /**
     * 扫码解析 + 工序推断（只读）。
     *
     * @param token       码内容 / 手输号 / **整条印刷 URL**（issue #4946 归一，见
     *                    {@link #normalizeScanKey}）：短码 / 新 token 优先，未命中回落既有四形态
     *                    （qr_token → processing_order_no → order_no → order_id）
     * @param operationId 可选：工人「一键改」指定的工序（必须属于本次扫码的部位/套，否则 422）
     * @param tenantId    当前租户
     * @return 一屏所需数据（见类 javadoc）；旧码 ⇒ 降级形态 + {@code needs_selection}
     */
    public Map<String, Object> resolve(String token, String operationId, Long tenantId) {
        return resolve(token, operationId, null, null, tenantId);
    }

    /**
     * 扫码解析（**契约扩展**，issue #4794）：旧码「选完套 + 部位」之后的收口。
     *
     * <p>旧码（{@code processing_orders.qr_token} 等四形态）只到**加工单级** ⇒ 没有部位级 token
     * ⇒ 选完套/部位后**没有可再解析的键**（设计 {@code docs/design/worker-h5-scan-and-report.md}
     * §9.3 D1）。本重载**只加不改**：给 {@code setId} + {@code orderItemId} ⇒ 服务端据此按
     * <b>同一份</b>推断口径重新解析出部位级视图；不给（或只给一半）⇒ 与改前**逐字一致**的
     * 降级形态（{@code needs_selection}）。</p>
     *
     * <p><b>为什么不新增端点、也不让降级形态直接升一档</b>：</p>
     * <ul>
     *   <li>「解析」本就是同一个只读面（读面加两个**可选**入参 = 契约扩展；新增端点 = 第二套响应形状）；</li>
     *   <li>降级形态**必须**保留 {@code granularity="order"}：它是「系统明确知道它不知道是哪套」的
     *       机器可读信号（前端据此强制选择，绝不默认取第 1 套）—— 升档 = 把该信号删掉；</li>
     *   <li>新码路径**不读**这两个入参（码已给出套 × 部位）⇒ 对已有新码**零影响**。</li>
     * </ul>
     *
     * <p>🔴 <b>幂等 / 鉴权</b>：仍是只读（无写库、无 {@code @Transactional}）；身份由调用方从
     * {@code X-Worker-Session-Id} 解（本类不碰身份）；所选（套, 部位）必须属于**本次扫码那张单**
     * —— 否则 422 {@code SCAN_SELECTION_NOT_IN_ORDER}（fail-closed，不按别人的单记账）。</p>
     *
     * @param setId       可选：工人从降级清单 {@code selections[].set_id} 里选的套
     * @param orderItemId 可选：工人从 {@code selections[].positions[].order_item_id} 里选的部位
     */
    public Map<String, Object> resolve(String token, String operationId, String setId, String orderItemId,
                                       Long tenantId) {
        if (!StringUtils.hasText(token)) {
            throw BusinessException.validationError("扫码内容不能为空");
        }
        String key = normalizeScanKey(token);
        // ① 新码优先（带套带部位）；未命中**只回落**，不并行写（设计 §2.6 双读一致性）
        ProcessingSetPartToken partToken = findPartToken(key, tenantId);
        if (partToken == null) {
            // ①′ 短码（V99，设计 §1.4）：印刷品写 `/s/<短码>` ⇒ **同一行记录的第二种表示**
            partToken = findPartTokenByShortCode(key, tenantId);
        }
        if (partToken != null) {
            // 🔴 新码**不读** setId/orderItemId：套 × 部位由码给出 ⇒ 契约扩展对已有新码零影响
            return setPositionView(partToken, operationId, tenantId);
        }
        // ①′ 旧码收口（issue #4794）：选完套 + 部位 ⇒ 部位级视图（工序仍由系统推断）
        if (StringUtils.hasText(setId) && StringUtils.hasText(orderItemId)) {
            return legacySelectionView(key, setId.trim(), orderItemId.trim(), operationId, tenantId);
        }
        // ②~⑤ 既有四形态（一字不动）；全不命中 ⇒ 404「订单不存在」（既有行为）
        return degradedView(key, tenantId);
    }

    /** 新码命中：`token` 未撤销 + 同租户（fail-closed，`deleted = 0` 正向相等）。 */
    private ProcessingSetPartToken findPartToken(String token, Long tenantId) {
        return setPartTokenMapper.selectOne(new LambdaQueryWrapper<ProcessingSetPartToken>()
                .eq(ProcessingSetPartToken::getToken, token)
                .eq(ProcessingSetPartToken::getTenantId, tenantId)
                .eq(ProcessingSetPartToken::getDeleted, 0)
                .last("LIMIT 1"));
    }

    /**
     * 短码 ⇒ 承载行（V99 / issue #4946；设计 {@code docs/design/worker-h5-scan-and-report.md} §1.4）。
     *
     * <p><b>归一化只有一份</b>：直接调既有 {@link WorkerShortLinkService#normalize}（Crockford Base32
     * 的字符集 / 长度 / 别名规则都在那里）—— 在扫描侧再写一份就是第二份口径（两处迟早不同）。</p>
     *
     * <p><b>跨租户查询 + fail-closed</b>：`selectByShortCode` 本身**绕过多租户拦截器**（短码全局唯一，
     * `/s/{短码}` 无租户上下文 ⇒ 由短码解出租户）。扫描面**有**租户上下文 ⇒ 这里必须自己兜住三条：
     * 租户不符（别人的码）／已撤销（`token IS NULL`，设计 §1.3.1：撤销 = 解析不到）／形态不合法
     * —— 一律视同**未命中**，回落既有四形态（**绝不**按别人的单记账）。</p>
     */
    private ProcessingSetPartToken findPartTokenByShortCode(String key, Long tenantId) {
        String code = WorkerShortLinkService.normalize(key);
        if (code.isEmpty()) {
            return null;
        }
        ProcessingSetPartToken row = setPartTokenMapper.selectByShortCode(code);
        if (row == null || !tenantId.equals(row.getTenantId()) || !StringUtils.hasText(row.getToken())) {
            return null;
        }
        return row;
    }

    /**
     * 把「扫码结果 / 手输内容」归一成**码值**（issue #4946；设计
     * {@code docs/design/worker-h5-scan-and-report.md} §1.4 逐字：接受 ① 短码 ② 裸 token
     * ③ 加工单号 ④ 订单号）。
     *
     * <p><b>为什么归一必须在服务端</b>：印刷品上的码是**整条 HTTPS URL**（{@code https://app.migaozn.com/s/<短码>}），
     * 而工人小程序（{@code frontend/bmini-app/src/pages/production/index/index.tsx} 的 {@code handleScan}）
     * 把 {@code Taro.scanCode} 的**原文**直传本端点 ⇒ 不归一 ⇒ 小程序扫印刷码解析不出
     * （纸面能力形同虚设）。服务端 owns the decision；前端 h5 那份 helper 只是同一份口径的镜像。</p>
     *
     * <p>逐条与 counterpart {@code frontend/worker-h5/src/scan-input.mjs::parseScanInput} 对齐：
     * ① 不像 URL（无协议前缀、也不以 {@code /} 开头）⇒ **原样**当码值（裸 token / 加工单号 / 订单号
     * 本身就是合法码值，= 手输兜底路径）；② 像 URL ⇒ 先取 query 的 {@code t} → {@code token} → {@code code}
     * （**键序**优先，与 {@code searchParams.get} 同口径）；③ 再取 hash 里的同组键（部分短链实现把参数放 hash）；
     * ④ 都没有 ⇒ 取**最后一段非空路径段**；它若正是路径名（{@code /w/} 或 {@code /s/}）⇒ 空串
     * （没有码值，不硬编）。</p>
     *
     * <p>⚠️ 本方法**只取码值、不判形态**：短码 / 旧 token / 单号分别由 {@link #findPartToken}、
     * {@link #findPartTokenByShortCode}、{@link ProductionService#resolveOrder} 判 —— 在这里再判一次
     * 形态就是第二份口径。</p>
     *
     * @param raw 扫码结果（任意 HTTPS URL）或手输内容（短码 / 裸 token / 加工单号 / 订单号）
     * @return 码值；无法取出（空 / 像 URL 但取不到码）⇒ 空串（调用方按未命中处理）
     */
    static String normalizeScanKey(String raw) {
        String text = raw == null ? "" : raw.trim();
        if (text.isEmpty() || (!URL_PREFIX.matcher(text).find() && !text.startsWith("/"))) {
            return text;
        }
        URI uri;
        try {
            uri = URI.create(text);
        } catch (IllegalArgumentException notUrl) {
            return text; // 像 URL 但解析不了 ⇒ 原样当码值（不吞输入）
        }
        String fromQuery = codeParam(uri.getRawQuery());
        if (fromQuery != null) {
            return fromQuery;
        }
        String fromHash = codeParam(uri.getRawFragment());
        if (fromHash != null) {
            return fromHash;
        }
        String last = "";
        String path = uri.getRawPath();
        if (path != null) {
            for (String segment : path.split("/")) {
                if (!segment.isEmpty()) {
                    last = segment;
                }
            }
        }
        return "w".equals(last) || "s".equals(last) ? "" : last;
    }

    /** 从 {@code k=v&…} 取出码值：键序 {@code t → token → code}（与前端同）；无 ⇒ {@code null}。 */
    private static String codeParam(String encodedParams) {
        if (encodedParams == null || encodedParams.isEmpty()) {
            return null;
        }
        List<String[]> pairs = new ArrayList<>();
        for (String pair : encodedParams.split("&")) {
            int eq = pair.indexOf('=');
            pairs.add(eq < 0
                    ? new String[]{pair, ""}
                    : new String[]{pair.substring(0, eq), pair.substring(eq + 1)});
        }
        for (String key : SCAN_CODE_KEYS) {
            for (String[] pair : pairs) {
                if (!key.equals(decode(pair[0]))) {
                    continue;
                }
                String value = decode(pair[1]).trim();
                if (!value.isEmpty()) {
                    return value;
                }
                break; // 该键的**首个**参数为空 ⇒ 换下一个键（与 `searchParams.get` 同口径）
            }
        }
        return null;
    }

    /** 百分号解码（query/hash 条形态；`+` 按表单口径解成空格 —— 与前端 `URLSearchParams` 同）。 */
    private static String decode(String raw) {
        try {
            return URLDecoder.decode(raw, StandardCharsets.UTF_8);
        } catch (IllegalArgumentException malformed) {
            return raw; // 非法转义 ⇒ 用原文（不吞输入）
        }
    }

    // ============================================================ 新码：套 × 部位 + 推断

    private Map<String, Object> setPositionView(ProcessingSetPartToken partToken, String operationId,
                                                Long tenantId) {
        ProcessingOrderSet set = requireSet(partToken, tenantId);
        ProcessingOrder po = processingSetReadService.requireProcessingOrder(set.getProcessingOrderId(), tenantId);
        return setPositionView(po, set, partToken.getOrderItemId(), partToken.getPositionKind(),
                operationId, tenantId);
    }

    /**
     * 部位级视图（新码与「旧码 + 选择」**共用同一份**推断/整形实现）。
     *
     * <p>套 × 部位的**来源**不同（新码由码给出 / 旧码由工人选择 + 服务端校验），但「推断哪一道、
     * 一键改的归属校验、套级回落、进度、卡点」必须逐字同源 —— 否则两条路径迟早给出不同的工序。</p>
     */
    private Map<String, Object> setPositionView(ProcessingOrder po, ProcessingOrderSet set,
                                                String orderItemId, String positionKind,
                                                String operationId, Long tenantId) {
        List<ProcessingPositionOperation> setOperations =
                processingSetReadService.listSetOperations(po.getId(), set.getId(), tenantId);
        Map<String, Map<String, Object>> catalog = operationQueryService.operationsByName(tenantId);

        // ── ① 部位级：扫到的那个部位的未完成工序 ──────────────────────────────
        List<ProcessingPositionOperation> candidates =
                pending(setOperations, op -> orderItemId.equals(op.getOrderItemId()));
        // ── ② 套级回落：本部位干完 ⇒ 整樘窗的套级活（打卷/装袋/发货）──────────
        boolean rerouted = false;
        if (candidates.isEmpty()) {
            candidates = pending(setOperations, op -> SCOPE_SET.equals(scopeOf(op, catalog)));
            rerouted = !candidates.isEmpty();
        }
        List<ProcessingPositionOperation> sorted = sortedBySeq(candidates);

        ProcessingPositionOperation chosen = null;
        String determinedBy = null;
        if (!sorted.isEmpty()) {
            if (StringUtils.hasText(operationId)) {
                // 一键改（§3.3）：显式指定 ⇒ 必须属于本次扫码的部位/套，否则 422（不记账）
                chosen = sorted.stream()
                        .filter(op -> operationId.trim().equals(op.getId()))
                        .findFirst()
                        .orElseThrow(() -> new BusinessException("OPERATION_NOT_IN_SCAN_TARGET",
                                "工序 " + operationId.trim() + " 不属于本次扫码的部位（"
                                        + orderItemId + "），不得跨部位报工",
                                422,
                                "请重新扫码，或在返回的 alternatives 里选择本部位/本套的待做工序"));
                determinedBy = DETERMINED_BY_PICKED;
            } else {
                // 🔴 硬约束：工序必须确定 —— seq 重复（脏数据）⇒ 拒绝，不静默取第一道
                int minSeq = seqOf(sorted.get(0));
                List<ProcessingPositionOperation> ties = sorted.stream()
                        .filter(op -> seqOf(op) == minSeq)
                        .toList();
                if (ties.size() > 1) {
                    throw new BusinessException("OPERATION_AMBIGUOUS",
                            "本部位有 " + ties.size() + " 道待做工序的 seq 相同（= " + minSeq
                                    + "），无法确定本次报哪一道 ⇒ 拒绝（工序未确定不得记账）",
                            422,
                            "请先在生产 → 工序库修正该部位的工序顺序（seq 必须唯一），"
                                    + "或由工人显式指定 operation_id");
                }
                chosen = ties.get(0);
                determinedBy = DETERMINED_BY_INFERRED;
            }
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("granularity", GRANULARITY_SET_POSITION);
        result.put("order_id", po.getOrderId());
        result.put("processing_order_no", po.getProcessingOrderNo());
        result.put("set_no", set.getSetNo());
        result.put("set_index", set.getSetIndex());
        result.put("position",
                processingSetReadService.positionView(orderItemId, positionKind, setOperations, tenantId));
        // ⑤ 本套工序总览（issue #4967 交付物 2，**只加一个键**，既有键一字不动）：
        //    工人扫一次就要看到「这一套还有哪几道没做」⇒ 本套 → 部位 → 工序明细，
        //    全部来自**同一份** `setOperations`（与上面的推断/进度/卡点同源）
        //    ⇒ 页面不再另写一份聚合（第二份口径）。🔴 实现自 issue #5247 起在
        //    `ProcessingSetReadService`（全仓唯一一份），与商家/agent 套件读面**同一份**。
        result.put("set_overview",
                processingSetReadService.setOverview(set, setOperations, tenantId));
        result.put("operation", chosen == null
                ? null
                : operationView(chosen, determinedBy, rerouted));
        result.put("alternatives", alternativeViews(sorted, chosen));
        result.put("set_progress", productionService.progressOf(setOperations));
        // ④ 卡点判据（切片 ③，issue #4776；设计 §3.1 逐字：「"stalled": { "kind": null }} // §6：
        //    非空 = 这道卡住了，附判据与阈值来源」）。**只加一个键**，既有键一字不动。
        //    A 模式只判「没开工」那一种；「卡了多久」取**前道 done_at**，绝不用 updated_at
        //    （§6.1 逐字点名它会被任何更新污染 ⇒ 会静默给出错数）。
        result.put("stalled", stuckPointService.stalledView(setOperations, chosen));
        // ③ 本套无活可做 ⇒ 「本套已完成」（含完成时刻），不报错（设计 §3.2）
        result.put("completed", chosen == null);
        result.put("completed_at", processingSetReadService.completedAt(setOperations));
        result.put("needs_selection", List.of());
        return result;
    }

    /** 套归属校验：必须同租户 + 未软删 + 与 token 的加工单一致（三任一条不成立 ⇒ 404，fail-closed）。 */
    private ProcessingOrderSet requireSet(ProcessingSetPartToken partToken, Long tenantId) {
        ProcessingOrderSet set = orderSetMapper.selectById(partToken.getSetId());
        if (set == null || !tenantId.equals(set.getTenantId())
                || !Integer.valueOf(0).equals(set.getDeleted())
                || !partToken.getProcessingOrderId().equals(set.getProcessingOrderId())) {
            throw BusinessException.notFound("套", "该码指向的套不存在或已作废，请重新打印任务卡");
        }
        return set;
    }

    // ============================================================ 旧码：降级形态（强制选部位）

    /**
     * 旧码降级形态（设计 §2.6）：{@code granularity="order"} + {@code needs_selection:["set","position"]}
     * + 可选清单。
     *
     * <p>🔴 <b>绝不默认取第 1 套</b>：{@code set_no} / {@code set_index} / {@code position} /
     * {@code operation} / {@code set_progress} 一律 {@code null}（**不知道就是不知道**），
     * 第 1 套只作为 {@code selections} 里的一个候选出现 —— 由工人选一次。</p>
     */
    private Map<String, Object> degradedView(String key, Long tenantId) {
        // 既有四形态（qr_token → processing_order_no → order_no → order_id），一字不动
        Order order = productionService.resolveOrder(key, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("granularity", GRANULARITY_ORDER);
        result.put("order_id", order.getId());
        result.put("processing_order_no", po == null ? null : po.getProcessingOrderNo());
        result.put("set_no", null);
        result.put("set_index", null);
        result.put("position", null);
        result.put("operation", null);
        result.put("alternatives", List.of());
        result.put("set_progress", null);
        // null = **未知**（降级形态判不出是哪一套 ⇒ 判不出完没完），不是 false
        result.put("completed", null);
        result.put("completed_at", null);
        result.put("needs_selection", DEGRADED_NEEDS_SELECTION);
        result.put("selections", po == null ? List.of() : selectionView(po, tenantId));
        return result;
    }

    /**
     * 旧码收口（issue #4794）：工人从降级清单里选的（套 + 部位）⇒ **部位级视图**。
     *
     * <p>分工：<b>码</b>决定「哪张单」（仍走既有四形态，一字不动）；<b>选择</b>只决定「这张单里的
     * 哪一套、哪个部位」。选完之后的推断/整形与**新码逐字同源**（{@link #setPositionView}）——
     * 在旧码侧再写一份推断就是第二份口径（两处迟早不同）。</p>
     *
     * <p>🔴 <b>fail-closed</b>：所选（套, 部位）必须属于**本次扫码那张单**，且部位必须是该套
     * <b>活跃工序实例</b>里的部位（与 {@code selections} 清单**同一份**判据）—— 否则 422，
     * 绝不「按别处的单/不存在的部位」静默记账。</p>
     */
    private Map<String, Object> legacySelectionView(String key, String setId, String orderItemId,
                                                    String operationId, Long tenantId) {
        Order order = productionService.resolveOrder(key, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (po == null) {
            throw new BusinessException("SCAN_SELECTION_NOT_IN_ORDER",
                    "该单没有活跃加工单，选不出套/部位 ⇒ 拒绝记账", 422,
                    "请重新打印带套号 + 部位的新任务卡（新码由码给出套 × 部位，无需选择）");
        }
        // 套：同租户 + 未软删 + 与本次扫码的加工单一致（三任一条不成立 ⇒ 422）
        ProcessingOrderSet set = orderSetMapper.selectById(setId);
        if (set == null || !tenantId.equals(set.getTenantId())
                || !Integer.valueOf(0).equals(set.getDeleted())
                || !po.getId().equals(set.getProcessingOrderId())) {
            throw new BusinessException("SCAN_SELECTION_NOT_IN_ORDER",
                    "所选的套（" + setId + "）不属于本次扫码的加工单 ⇒ 拒绝记账", 422,
                    "请重新扫码，并从本单返回的 selections 清单里选择套号");
        }
        List<ProcessingPositionOperation> setOperations = processingSetReadService.listSetOperations(po.getId(), set.getId(), tenantId);
        if (setOperations.stream().noneMatch(op -> orderItemId.equals(op.getOrderItemId()))) {
            throw new BusinessException("SCAN_SELECTION_NOT_IN_ORDER",
                    "所选的部位（" + orderItemId + "）不属于该套 ⇒ 拒绝记账", 422,
                    "请重新选择部位（清单只列该套**真能报工**的部位）");
        }
        String positionKind = setOperations.stream()
                .filter(op -> orderItemId.equals(op.getOrderItemId()))
                .map(ProcessingPositionOperation::getPositionKind)
                .filter(StringUtils::hasText)
                .findFirst()
                .orElse(null);
        return setPositionView(po, set, orderItemId, positionKind, operationId, tenantId);
    }

    /**
     * 可选清单 = 该单的**套 × 部位**（设计 §2.6）。
     *
     * <p>部位取自该单**活跃工序实例**的 {@code order_item_id}（= 真能报工的部位；未实例化的套给空清单，
     * 因为对它无可报之事），按 {@code set_index} 升序、套内按既有读面同序（部位名 → seq）。</p>
     */
    private List<Map<String, Object>> selectionView(ProcessingOrder po, Long tenantId) {
        List<ProcessingOrderSet> sets = orderSetMapper.selectList(
                new LambdaQueryWrapper<ProcessingOrderSet>()
                        .eq(ProcessingOrderSet::getProcessingOrderId, po.getId())
                        .eq(ProcessingOrderSet::getTenantId, tenantId)
                        .eq(ProcessingOrderSet::getDeleted, 0)
                        .orderByAsc(ProcessingOrderSet::getSetIndex));
        List<ProcessingPositionOperation> operations = processingSetReadService.listOrderOperations(po.getId(), tenantId);

        List<Map<String, Object>> views = new ArrayList<>();
        for (ProcessingOrderSet set : sets == null ? List.<ProcessingOrderSet>of() : sets) {
            Set<String> seen = new LinkedHashSet<>();
            List<Map<String, Object>> positions = new ArrayList<>();
            for (ProcessingPositionOperation op : operations) {
                if (!set.getId().equals(op.getSetId()) || op.getOrderItemId() == null
                        || !seen.add(op.getOrderItemId())) {
                    continue;
                }
                positions.add(ProcessingSetReadService.positionEntry(op.getOrderItemId(), op.getPositionKind(),
                        op.getPositionName()));
            }
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("set_id", set.getId());
            view.put("set_no", set.getSetNo());
            view.put("set_index", set.getSetIndex());
            view.put("positions", positions);
            views.add(view);
        }
        return views;
    }

    // ============================================================ 整形

            /**
     * 一屏上的「这次报哪一道」。
     *
     * <p>{@code unit_price} 为 {@code null} = <b>未定价</b>（≠ 0 元，V90 / issue #4696）——
     * 读面**不折 0**；{@code rerouted=true} = 本部位已干完、系统换到了**套级工序**（§3.2 ②），
     * 此时额外给 {@code carrier}（该套级工序的承载部位）⇒ 工人知道去哪做，**不静默换工序**。</p>
     */
    private static Map<String, Object> operationView(ProcessingPositionOperation op, String determinedBy,
                                                     boolean rerouted) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("operation_id", op.getId());
        view.put("logical_name",
                ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
        view.put("position", ProductionOperationQueryService.displayPosition(
                op.getOperationName(), op.getPositionKind()));
        view.put("group_name", op.getGroupName());
        view.put("unit", op.getUnit());
        view.put("qty", nz(op.getQty()));
        view.put("qty_source", op.getQtySource());
        view.put("unit_price", op.getUnitPrice());
        view.put("seq", op.getSeq());
        view.put("status", op.getStatus());
        view.put("determined_by", determinedBy);
        view.put("rerouted", rerouted);
        if (rerouted) {
            view.put("carrier", ProcessingSetReadService.positionEntry(op.getOrderItemId(), op.getPositionKind(),
                    op.getPositionName()));
        }
        return view;
    }

    /** 一键改的候选 = 与默认项**同一层级**的其他待做工序（部位级命中 ⇒ 同部位；套级回落 ⇒ 同套级）。 */
    private static List<Map<String, Object>> alternativeViews(List<ProcessingPositionOperation> sorted,
                                                             ProcessingPositionOperation chosen) {
        List<Map<String, Object>> views = new ArrayList<>();
        for (ProcessingPositionOperation op : sorted) {
            if (chosen != null && chosen.getId().equals(op.getId())) {
                continue;
            }
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("operation_id", op.getId());
            view.put("logical_name",
                    ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
            view.put("position", ProductionOperationQueryService.displayPosition(
                    op.getOperationName(), op.getPositionKind()));
            view.put("seq", op.getSeq());
            view.put("qty", nz(op.getQty()));
            view.put("unit", op.getUnit());
            views.add(view);
        }
        return views;
    }

    // ============================================================ 查询 / 纯函数

    private List<ProcessingPositionOperation> pending(List<ProcessingPositionOperation> operations,
                                                      Predicate<ProcessingPositionOperation> match) {
        return operations.stream()
                .filter(match)
                .filter(op -> !productionService.isDone(op))
                .toList();
    }

    private static List<ProcessingPositionOperation> sortedBySeq(List<ProcessingPositionOperation> operations) {
        List<ProcessingPositionOperation> sorted = new ArrayList<>(operations);
        sorted.sort(Comparator.comparingInt(ProductionScanService::seqOf)
                .thenComparing(op -> op.getId() == null ? "" : op.getId()));
        return sorted;
    }

    private static int seqOf(ProcessingPositionOperation op) {
        return op.getSeq() == null ? Integer.MAX_VALUE : op.getSeq();
    }

    /** 套级工序的判据 = **工序库**的 `scope`（逐字取库，不硬编码工序名）；库中缺该工序 ⇒ 不是套级。 */
    private static String scopeOf(ProcessingPositionOperation op,
                                  Map<String, Map<String, Object>> catalog) {
        Map<String, Object> meta = catalog.get(op.getOperationName());
        Object scope = meta == null ? null : meta.get("scope");
        return scope == null ? null : String.valueOf(scope);
    }

        private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }
}
