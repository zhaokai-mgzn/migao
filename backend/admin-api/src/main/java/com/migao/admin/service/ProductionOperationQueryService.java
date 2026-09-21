package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProductionCraft;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工序库 / 工艺路线**只读**消费者（issue #4116 P0-2）。
 *
 * <p>背景（取证事实）：{@code production_operations} / {@code production_routings} 自 V49 建表起
 * **零消费者、零种子** ⇒ 商家无配置入口、库里无数据、§3 工艺路线在 DB 层不可查不可展示。
 * 本类补上「可查询/可展示」这一半：读**工序库目录 + 工艺路线**并按展示口径整形。
 * 工序数与路线数**不在此写死**：它们随迁移漂移（V56 加过工序、V58 加过路线），
 * 写死即制造「注释与实际不符且不会变红」的假声明（issue #4259 ②）。</p>
 *
 * <h2>工序来源已切到新结构（P2b，issue #4459 = 母单 #4423）</h2>
 * <p>旧模型是 9 条「{@code (部位 × 工艺)} 展开快照」（{@code production_routings.operations} 里
 * 每道工序名把部位编码进名字：{@code 精裁-布}/{@code 布三边}…）。新模型 =
 * <b>1 条具名主线</b>（{@code production_route_templates.mainline}，逻辑工序名）+
 * <b>规则表</b>（{@code production_route_rules}：工艺/选项触发 insert/remove/factor）+
 * <b>部位价目与适用性</b>（{@code production_operation_positions}）。
 * 本类读**新**结构，旧两表 {@code production_option_routings} / {@code production_option_factors}
 * 的读取点**已全部收口**（V73 把它们的活跃行软删；表先不 DROP）。</p>
 *
 * <p><b>规则应用语义不在此实现</b>：它落在 {@link ProcessingOrderService} 的
 * {@code buildRoute}，与真值源 {@code routing.py::build_route_v2} 逐字同口径。
 * 本类只做「读库 + 稳定排序」—— 排序必须确定（{@code (priority, id)}），
 * 否则同一张单两次生成会得到不同工序序列与计件工资。</p>
 *
 * <p><b>只读边界（本类明确不做）</b>：本类**只有** SELECT，端点也只有 GET。工序库的写面
 * （改单价/停用/排序）在 {@link ProductionOperationCommandService}，路线的写面在
 * {@link ProductionRoutingCommandService} —— 读写分开，写面不在本类里开口子。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionOperationQueryService {

    /**
     * 「有工序、有价、**有意不消费**（等客户确认）」的工序集合（issue #4308 P4；真值源 =
     * {@code backend/ai-agent-service/app/production/routing.py::PENDING_CUSTOMER_CONFIRMATION_OPERATIONS}）。
     *
     * <p><b>这不是缺陷清单，是提问清单</b>：issue #4261 逐项登记了为什么必须问客户
     * （裁剪vs精裁是否两道 / 质检是否每单必做 / 腰靠垫归属 / 罗马帘整套工序 / 纱帘熨烫定型）——
     * 猜出来的工序与单价会**直接算成工人工资**，故一律不猜。</p>
     *
     * <p>⚠️ <b>与 routing.py 同源由测试守</b>（Java 无法 import Python）：
     * {@code ProductionRouteSignalMigrationTest} 逐字解析 {@code routing.py} 的
     * {@code frozenset} 并与本常量**双向比对**（少一道/多一道都红）。改一处不改另一处即红 ——
     * 抄一份字面量而不守，就是第二份口径。</p>
     */
    public static final Set<String> PENDING_CUSTOMER_CONFIRMATION_OPERATIONS =
            Set.of("裁剪-布", "裁剪-纱", "质检", "腰靠垫");

    /**
     * 旧工序名 → 逻辑工序名（35 条，与真值源 {@code routing.py::OPERATION_LOGICAL_NAMES} 逐字同源）。
     *
     * <p>为什么需要它：{@code production_operations.name} 仍是**旧名**（把部位编码进名字：
     * {@code 精裁-布}/{@code 布三边}），而新结构（主线 / 规则表 / 部位价目）用**逻辑名**
     * （{@code 精裁}/{@code 三边}）。两侧要互相翻译，翻译表**只此一份**。</p>
     */
    private static final Map<String, String> OPERATION_LOGICAL_NAMES = withSheerVariants(logicalNamePairs());

    /**
     * {@link #OPERATION_LOGICAL_NAMES} 的合成入口：{@link #logicalNamePairs()}（**35 条**，被
     * {@code ProductionOperationQueryServiceTest#logicalNameTableMatchesTruthSource} 逐条冻结）
     * + **4 条纱帘变体**（issue #4937）。
     *
     * <p>🔴 <b>为什么必须新增这 4 条</b>：{@code 熨烫 / 定型 / 复烫 / 车被} 原来被
     * {@code applicable} 过滤挡在纱帘路线之外 ⇒ 库里从来没建过它们的纱帘变体；
     * 本包把那条过滤整块删除 ⇒ 这 4 道会进纱帘路线，{@code normalizeOperationName} 若认不出
     * 「{@code 熨烫-纱}」这种名字，实例化侧就会把它当成**商家自建工序**（原样返回）
     * ⇒ 位次判据与缺工序判据同时失真。</p>
     *
     * <p>⚠️ <b>为什么另起一段而不是往 {@link #logicalNamePairs()} 里加</b>：那 35 条被
     * {@code ProductionOperationQueryServiceTest#logicalNameTableMatchesTruthSource} 与
     * {@code V97} 的守卫逐条冻结 ⇒ 与 {@code variantNames()} / {@code headVariants()} 同款，
     * 新增条目只能落在冻结段之外的这一处。</p>
     */
    private static Map<String, String> withSheerVariants(Map<String, String> names) {
        Map<String, String> out = new LinkedHashMap<>(names);
        out.put("熨烫-纱", "熨烫");
        out.put("定型-纱", "定型");
        out.put("复烫-纱", "复烫");
        out.put("车被-纱", "车被");
        return Map.copyOf(out);
    }

    /**
     * 逻辑工序名 → **该部位的变体名**（{@code production_operations.name} 的旧名）—— **显式逆索引**。
     *
     * <p>新结构用逻辑名（{@code 精裁} / {@code 三边} / {@code 车被}），而
     * {@code production_operations} 仍是旧名（{@code 精裁-布} / {@code 布三边} / {@code 布帘车被}）
     * ⇒ 读库取元数据（单位/单价/必完/开始标记/作用域）前必须把逻辑名映射回**该租户库里的变体名**。</p>
     *
     * <p>🔴 <b>为什么必须是显式表，而不是「逻辑名 + 部位后缀」的字符串规则</b>（P2b 实测：0/9）：
     * {@code 三边} 的布帘变体是 {@code 布三边}（**无 {@code -} 分隔**）、
     * {@code 车被} 的布帘变体是 {@code 布帘车被}（**前缀而非后缀**）——
     * 规则推导对这两道分别得到 {@code 三边-布} / {@code 车被-布}，库里都没有
     * ⇒ {@code variantNameOf} 返回 {@code null} ⇒ **该部位的每一条路线**都在实例化时 fail-closed
     * （真值源里 {@code 布帘×韩褶} 的 11 道会解析成 9 道 + 2 个 null）。</p>
     *
     * <p>与真值源 {@code routing.py::OPERATION_LOGICAL_NAMES} 同款口径：**逐条显式写出，
     * 不用字符串规则推导**。键 = 逻辑名，值 = 部位 → 变体名；漂移护栏 =
     * {@code ProductionOperationQueryServiceTest} 逐字解析 {@code routing.py} 的
     * {@code _LOGICAL_NAME_PAIRS} 并与本表**双向比对**。</p>
     *
     * <p><b>不含**部位无关**的工序</b>（{@code 外帘打卷} / {@code 外帘装袋} / {@code 外帘发货} /
     * {@code 质检} / {@code 抱枕} / {@code 腰靠垫}）—— 三种部位同名，由
     * {@link #variantNameOf} 的裸名兜底覆盖，写进来只是把同一件事写三遍。</p>
     *
     * <p>🔴 <b>两张 builder 合成（issue #4777）</b>：{@link #variantNames()} = 35 条旧名对的
     * **反向索引**（30 条，含 #4707 的 {@code 裁剪 × 布料} 回落）；{@link #headVariants(Map)}
     * = **21 条帘头条目**（逐条显式写出）。为什么帘头**另起一段**而不是并进
     * {@link #variantNames()}：后者被 {@code V97} 的守卫
     * （{@code test_v97_variant_map_matches_production_code}）**逐条冻结**为 30 条字面量
     * （它是已发布迁移的判据口径），而 {@code V97} 是**已发布迁移**（红线：不得改）
     * ⇒ 帘头条目只能落在 {@code variant(...)} 之后的另一段里。两段**都在本文件内**、
     * 都**逐条显式写出** ⇒ 不构成第二份口径。</p>
     */
    private static final Map<String, Map<String, String>> VARIANT_NAMES = variantNamesWithCurtainHead();

    /**
     * **基线三部位**（布帘/纱帘/帘头；迁移 V71 的闭词表）—— 部位值域的**单一出处**。
     *
     * <p>issue #4614：路线写面（新建路线的默认适用帘种）与工序写面（新增工序的默认适用部位）
     * 用的是**同一个值域**；各写一份必然漂移，而漂移的形态是「前端勾得出的部位、后端收不下」
     * （或反过来）⇒ 商家在界面上选得动、提交却 422。故此处只留一份，两处引用。</p>
     *
     * <p>⚠️ 它只是**基线**，不是完整值域：矩阵里出现的第 4 个部位（如 {@code 布料}，V79）
     * 同样合法（见 {@code ProductionOperationCommandService.rejectUnknownPositions}）。</p>
     */
    public static final List<String> BASELINE_POSITIONS = List.of("布帘", "纱帘", "帘头");

    /**
     * 去部位化（issue #4883）后，同一逻辑工序**唯一**价的取行来源 —— 用户裁定「取布帘价」。
     *
     * <p>只用于 {@link #collapseToLogical} 的选行与 {@link #variantNameOf} 的变体名回落，
     * <b>不是</b>新的值域：{@code BASELINE_POSITIONS} 仍是部位处的值域出处。</p>
     */
    public static final String COLLAPSE_PRICE_SOURCE_POSITION = "布帘";

    /**
     * 矩阵塌缩（V102）后幸存行的 {@code position} —— **中性值，不是部位**（部位维已退场）。
     *
     * <p>出处 = `backend/admin-api/src/main/resources/db/migration/V102__retire_applicability_flag.sql`
     * （与 `docs/sql/schema.sql` 的矩阵终态字面量逐字一致）。读面必须**认出**它：塌缩行的变体元数据
     * （{@code group} / {@code unit} / {@code variant_operation_id}）只能按
     * {@link #COLLAPSE_PRICE_SOURCE_POSITION 取价同一行}解析 —— 按中性值查变体必然落空，
     * 于是库里只有变体名的工序会静默变 null（issue #5008：商家面「未分组」+ 行尾 `—`）。</p>
     *
     * <p>它**不进** {@link #POSITION_LIMIT_VOCABULARY}（理由见那里）：这个值永不可能等于任何实例化部位。</p>
     */
    public static final String COLLAPSE_NEUTRAL_POSITION = "通用";

    /**
     * **规则级「部位限定」的闭词表**（issue #4962）：{@link #BASELINE_POSITIONS 基线三部位}
     * **∪ 第 4 个部位**（{@code 布料}，布料单专用 —— 与 {@code ProcessingOrderService.FABRIC_POSITION}
     * 逐字同源，**不另抄一个字面量**）。
     *
     * <p>用户裁定（2026-09-21 逐字）：「如果有一些工序只能布帘有或者纱帘有，可以在适用条件上设置」
     * ⇒ 「适用条件」加回**部位维**（{@code production_route_rules.position}）。该维此前被
     * issue #4937 / O2 整块退场，本单只恢复它一处（其余退场面照旧）。</p>
     *
     * <p>为什么是**闭词表**而不是「矩阵里有什么就收什么」：退场期间 `V104` 把矩阵存活行的
     * {@code position} 塌缩成了中性值 {@code 通用} ⇒ 按矩阵取值域会收下一个**永不可能等于任何
     * 实例化部位**的「部位」，那就是「规则已落库但永不生效」的黑洞（本仓明令要显式失败的形态）。
     * 实例化侧真正会传的部位只有这 4 个（{@code buildRoute} 的 {@code position} 参数）。</p>
     */
    public static final List<String> POSITION_LIMIT_VOCABULARY = positionLimitVocabulary();

    private static List<String> positionLimitVocabulary() {
        List<String> out = new ArrayList<>(BASELINE_POSITIONS);
        if (!out.contains(ProcessingOrderService.FABRIC_POSITION)) {
            out.add(ProcessingOrderService.FABRIC_POSITION);
        }
        return List.copyOf(out);
    }

    private final ProductionOperationMapper productionOperationMapper;
    /** 具名主线（新结构的「基准工序序列」载体，V71 / V72）。 */
    private final ProductionRouteTemplateMapper productionRouteTemplateMapper;
    /** 规则表（工艺/选项触发增删 + 计件系数覆盖），V71 / V72 —— 退场后**唯一**的规则真值源。 */
    private final ProductionRouteRuleMapper productionRouteRuleMapper;
    /** 部位价目 + 适用性矩阵（V71 / V72）。 */
    private final ProductionOperationPositionMapper productionOperationPositionMapper;
    /** 工艺词表 + 商户级默认工艺（V72）：缺 {@code craft} 时的兜底来源，**不写死常量**。 */
    private final ProductionCraftMapper productionCraftMapper;
    /** 信号 → 路线键映射（issue #4308，V60；派生路线键的**唯一**数据源，不再是 Java 常量）。 */
    private final ProductionRouteSignalMapper productionRouteSignalMapper;

    /**
     * 工序库目录：按分组 → 排序位的稳定顺序返回全部活跃工序。
     *
     * @return {total, groups:[{group, operations:[...]}]}；工序项含
     *         {id, name, library_name, group, position, scope, unit, unit_price, is_must_finish, is_start_marker, source}
     *         （{@code scope} = 部位级 {@code position} / 套级 {@code set}，V67，issue #4384 A1）。
     *         ⚠️ {@code name} = **逻辑工序名**（读时归一，issue #4642）；{@code library_name} = 库口径原名，
     *         **web 界面不得渲染**（见 {@link #operationView}）
     */
    public Map<String, Object> catalog(Long tenantId) {
        List<ProductionOperation> rows = activeOperations(tenantId);

        Map<String, List<Map<String, Object>>> grouped = new LinkedHashMap<>();
        for (ProductionOperation op : rows) {
            String group = op.getGroupName() == null ? "其他" : op.getGroupName();
            grouped.computeIfAbsent(group, key -> new ArrayList<>()).add(operationView(op));
        }
        List<Map<String, Object>> groups = new ArrayList<>();
        grouped.forEach((group, items) -> {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("group", group);
            entry.put("operations", items);
            groups.add(entry);
        });

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", rows.size());
        result.put("groups", groups);
        return result;
    }

    /**
     * 工艺路线模板：**具名主线 + 适用帘种 + 默认标记**（新结构的展示口径）。
     *
     * @return {total, routings:[{id, name, is_default, positions, mainline, status}]}
     */
    public Map<String, Object> routings(Long tenantId) {
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionRouteTemplate template : routeTemplates(tenantId)) {
            items.add(templateView(template));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", items.size());
        result.put("routings", items);
        return result;
    }

    /**
     * 路线单项展示形态（{@code GET /routings} 列表项 / 写面响应**共用同一份**，两处各拼一份必然漂移）。
     *
     * <p><b>{@code mainline} 读时归一（issue #4632）</b>：逐项走**既有**
     * {@link #normalizeOperationName}，把**存量**变体名（旧前端时代存进去的 {@code 精裁-布}）
     * 归一为逻辑工序名 —— 否则「工艺路线」tab 的主线 chip 直接渲染这个数组，界面上就还是旧名
     * （写面 #4618 只管住新写入的，管不住库里已有的）。三条边界：</p>
     * <ul>
     *   <li><b>只归一能归一的</b>：未登记的自定义工序名（{@code 测试22}）归一后等于自身 ⇒ 原样返回；</li>
     *   <li><b>不写库</b>：纯读时派生（与 S1「读时派生、不写回填」同一范式）—— 库里仍是原值，
     *       可回溯「当时存的是什么」；本类只有 SELECT（见 {@code queryServiceIsReadOnly}）；</li>
     *   <li><b>顺序与重复不变</b>：逐项 map、不去重、不排序（主线序列是计件/完工判定的输入，
     *       判重是**写面**护栏的事）。</li>
     * </ul>
     */
    public Map<String, Object> templateView(ProductionRouteTemplate template) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("id", template.getId());
        entry.put("name", template.getName());
        entry.put("is_default", Boolean.TRUE.equals(template.getIsDefault()));
        entry.put("positions", stringList(template.getPositions()));
        entry.put("mainline", normalizedMainline(template.getMainline()));
        entry.put("status", template.getStatus());
        return entry;
    }

    /**
     * 主线序列的**读时归一**（issue #4632）：逐项走 {@link #normalizeOperationName}，**顺序与重复一字不变**。
     *
     * <p>实现**只有这一处**（写面 {@code ProductionRoutingCommandService} 落库前调的是同一个
     * {@link #normalizeOperationName}）—— 另抄一份表就是第二份口径，漂移的那一份不会变红。</p>
     */
    private List<String> normalizedMainline(Object raw) {
        List<String> out = new ArrayList<>();
        for (String name : stringList(raw)) {
            out.add(normalizeOperationName(name));
        }
        return out;
    }

    /**
     * 信号映射列表（issue #4308 交付物 3 的读面）：{@code {total, signals:[{id, signal,
     * curtain_type, craft, priority, status}]}}。
     *
     * <p>写面（POST/PUT/DELETE）在 {@link ProductionRoutingCommandService} —— 与工序库
     * 「读写分开」同口径（本类只有 SELECT）。</p>
     */
    public Map<String, Object> routeSignalList(Long tenantId) {
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionRouteSignal signal : routeSignals(tenantId)) {
            items.add(signalView(signal));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", items.size());
        result.put("signals", items);
        return result;
    }

    /** 信号映射单项展示形态（列表项 / 写面响应共用同一份）。 */
    public Map<String, Object> signalView(ProductionRouteSignal signal) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", signal.getId());
        view.put("signal", signal.getSignal());
        view.put("curtain_type", signal.getCurtainType());
        view.put("craft", signal.getCraft());
        view.put("priority", signal.getPriority());
        view.put("status", signal.getStatus());
        return view;
    }

    /**
     * 库中现有的**路线模板名**（失败提示要**可行动**就必须能说出「库里有的是什么」，
     * 而不是只说「没找到」）。默认模板带 {@code （默认）} 后缀标注。
     */
    public List<String> routingKeys(Long tenantId) {
        List<String> names = new ArrayList<>();
        for (ProductionRouteTemplate template : routeTemplates(tenantId)) {
            names.add(Boolean.TRUE.equals(template.getIsDefault())
                    ? template.getName() + "（默认）" : template.getName());
        }
        return names;
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 新结构读面（P2b，issue #4459）—— 实例化的**唯一**工序来源
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * **实例化用**：该部位的具名路线模板（新结构的「基准工序序列」）。
     *
     * <p>命中口径 = 模板的 {@code positions} 含该部位；**没有**部位专属模板 ⇒ 返回 {@code null}
     * （「兜底到默认模板」是**调用方**的策略，不是库的语义 —— 与旧 {@code findRouting} 同款分工）。</p>
     *
     * <p>多命中时取 {@code (is_default DESC, created_at ASC, id ASC)} 第一条（读取侧已按此排序）：
     * 默认模板优先 ⇒ **先建者优先** ⇒ id 稳定。派生必须确定，否则同一张单两次生成会得到不同工序序列。</p>
     *
     * <p>🔴 **issue #4563（P1·涉钱）**：第二键曾是 `id`。而新建路线的 id 是 UUID（十六进制字符
     * **恒小于**种子 id 的 `rt-` 前缀）⇒ 商家新建一条 `positions` 含 `布料` 的路线就会**静默顶掉**
     * V79 种子的「布料工序路线」；叠加适用性过滤（窗帘各道对 `布料` 标 `applicable=FALSE`，
     * 只有 `配料`/`打包` 为 TRUE）⇒ **布料单只剩「打包」（丢「配料」）**，若新路线还是空壳
     * ⇒ **零工序加工单**（工人扫不了码、且没有任何东西变红）。工序 = 计件工资的输入 ⇒ 属**涉钱**。</p>
     */
    public ProductionRouteTemplate routeTemplateFor(Long tenantId, String position) {
        if (position == null) {
            return null;
        }
        for (ProductionRouteTemplate template : routeTemplates(tenantId)) {
            if (stringList(template.getPositions()).contains(position)) {
                return template;
            }
        }
        return null;
    }

    /**
     * 该租户的**默认路线模板**（回落链的终点，T1/T2 的目标）。
     *
     * <p>与 {@link #routeTemplateFor} 的分工：那个按部位选，这个按 {@code is_default} 选。
     * 每租户活跃模板中**恰好一条**默认（部分唯一索引 {@code uk_production_route_templates_tenant_default}
     * 保证 ≤1）⇒ 取第一条即确定。</p>
     *
     * <p>返回 {@code null} = 该租户**没有**默认路线 ⇒ 调用方 T3 fail-closed
     * （**不回退**任何常量或加工项目录）。</p>
     */
    public ProductionRouteTemplate defaultRouteTemplate(Long tenantId) {
        for (ProductionRouteTemplate template : routeTemplates(tenantId)) {
            if (Boolean.TRUE.equals(template.getIsDefault())) {
                return template;
            }
        }
        return null;
    }

    /**
     * 该租户的**商户级默认工艺**（缺 {@code craft} 时的兜底来源）。
     *
     * <p>规格订正（母单 #4423 评论「🔴 规格订正」）：重构后路线模板**没有工艺维**
     * ⇒ 缺 {@code craft} 不能「从默认路线取对应维」⇒ 必须引入商户级默认工艺。
     * <b>不得</b>写死常量 {@code 韩褶}（商户只做打孔时会插错工序 + 算错计件系数 = 错发工资）。</p>
     *
     * @return 默认工艺名；该租户没有默认工艺 ⇒ {@code null}（调用方按缺维处理，不猜）
     */
    public String defaultCraft(Long tenantId) {
        for (ProductionCraft craft : activeCrafts(tenantId)) {
            if (Boolean.TRUE.equals(craft.getIsDefault())) {
                return craft.getName();
            }
        }
        return null;
    }

    /**
     * 部位价目 + 适用性矩阵（**原始行**读面）：{@code (逻辑工序, 部位) → 单价 / 是否做}。
     *
     * <p>只返回**活跃**行（{@code status=active} + 未软删 + 同租户），按
     * {@code (logical_name, position)} 稳定排序 —— 取用侧按键查，顺序不影响结果，
     * 但确定序让「同一张单两次生成」的中间态可比对。</p>
     *
     * <p>⚠️ 去部位化（issue #4883）后，取用侧**不应**直接按 {@code position} 过滤取价 ——
     * 价目一律走 {@link #collapseToLogical}（一道逻辑工序一个价）。本方法保留原始行，
     * 供写面（寻址 {@code id}）与「按部位回写」等仍需矩阵行的场景使用。</p>
     */
    public List<ProductionOperationPosition> operationPositions(Long tenantId) {
        List<ProductionOperationPosition> rows = productionOperationPositionMapper.selectList(
                new LambdaQueryWrapper<ProductionOperationPosition>()
                        .eq(ProductionOperationPosition::getTenantId, tenantId)
                        .eq(ProductionOperationPosition::getDeleted, 0)
                        .eq(ProductionOperationPosition::getStatus, "active")
                        .orderByAsc(ProductionOperationPosition::getLogicalName)
                        .orderByAsc(ProductionOperationPosition::getPosition));
        return rows == null ? List.of() : rows;
    }

    /**
     * 部位价目矩阵 → **一道逻辑工序一行、一个价**（去部位化，issue #4883）。
     *
     * <p>矩阵的键曾是 {@code (逻辑工序, 部位)}；用户裁定「部位不再参与取价，取布帘价」
     * ⇒ 取用侧必须先把同一 {@code logical_name} 的多行**收敛为一行**。收敛顺序
     * （**完全确定**，不依赖 DB 返回序 —— 漂移会让同一张单两次生成得到不同工资）：</p>
     * <ol>
     *   <li>{@code applicable = TRUE} 的行优先：{@code FALSE} = 当年「该部位明确不做」，
     *       其 {@code unit_price} 一律 {@code NULL} ⇒ 优先它会把**有价**的工序（如
     *       {@code 帘头制作}：布帘格 FALSE+NULL、帘头格 TRUE+¥2.00）判成「未定价」；</li>
     *   <li>其中 {@link #COLLAPSE_PRICE_SOURCE_POSITION 布帘} 列优先（用户裁定「取布帘价」）；</li>
     *   <li>再按 {@code position} 字典序、{@code id} 升序（同部位重复行同样确定）。</li>
     * </ol>
     *
     * <p>🔴 <b>价只「选行」、绝不「回落」</b>（issue #4696，P1）：收敛行的 {@code unit_price}
     * 是 {@code NULL} ⇒ 就是**未定价**，<b>不得</b>回落 {@code production_operations.unit_price}
     * （那是 {@code NOT NULL DEFAULT 0} ⇒ 回落把「未定价」变成「真 0 元」，工人白干且无人知道）。</p>
     *
     * <p><b>为什么在代码里收敛、而不是加一条迁移把这些行软删</b>：V71 的矩阵种子是
     * {@code routing.py} ↔ {@code V71} ↔ {@code docs/sql/schema.sql} <b>三源收敛</b>的冻结产物，
     * 且 <b>bootstrap 路径不跑迁移链</b>（{@code docs/sql/schema.sql} 是终态种子）——
     * 在迁移里删种子行会让 bootstrap 与迁移链终态**分叉**，而那正是既有守卫要防的形态。
     * ⇒ 收敛发生在**三个取用侧共用的这一处**（读面 / 实例化 / 补价），物理行保持不动。</p>
     *
     * @return 每个 {@code logical_name} 一行，按 {@code logical_name} 升序（与
     *         {@code GET /operation-positions} 的既有「按逻辑工序名稳定排序」同口径）
     */
    public static List<ProductionOperationPosition> collapseToLogical(List<ProductionOperationPosition> rows) {
        Map<String, ProductionOperationPosition> survivors = new LinkedHashMap<>();
        if (rows != null) {
            for (ProductionOperationPosition row : rows) {
                if (row == null || row.getLogicalName() == null) {
                    continue;
                }
                ProductionOperationPosition current = survivors.get(row.getLogicalName());
                if (current == null || beatsForCollapse(row, current)) {
                    survivors.put(row.getLogicalName(), row);
                }
            }
        }
        List<String> names = new ArrayList<>(survivors.keySet());
        names.sort(String::compareTo);
        List<ProductionOperationPosition> out = new ArrayList<>();
        for (String name : names) {
            out.add(survivors.get(name));
        }
        return out;
    }

    /** {@link #collapseToLogical} 的选行比较：{@code candidate} 是否应取代 {@code current}。 */
    private static boolean beatsForCollapse(ProductionOperationPosition candidate,
                                            ProductionOperationPosition current) {
        int byApplicable = Boolean.compare(Boolean.TRUE.equals(candidate.getApplicable()),
                Boolean.TRUE.equals(current.getApplicable()));
        if (byApplicable != 0) {
            return byApplicable > 0;
        }
        int bySourcePosition = Boolean.compare(
                COLLAPSE_PRICE_SOURCE_POSITION.equals(candidate.getPosition()),
                COLLAPSE_PRICE_SOURCE_POSITION.equals(current.getPosition()));
        if (bySourcePosition != 0) {
            return bySourcePosition > 0;
        }
        int byPosition = blankSafe(candidate.getPosition()).compareTo(blankSafe(current.getPosition()));
        if (byPosition != 0) {
            return byPosition < 0;
        }
        return blankSafe(candidate.getId()).compareTo(blankSafe(current.getId())) < 0;
    }

    private static String blankSafe(String value) {
        return value == null ? "" : value;
    }

    /**
     * 规则表（**实例化用**读面）：工艺变体 / 特殊选项 / 计件系数档。
     *
     * <p>只返回**活跃**行（{@code status=active} + 未软删 + 同租户），按
     * {@code (priority, id)} 稳定排序 —— **规则应用顺序敏感**（{@code remove} 不先于
     * {@code insert}：顺序完全由 {@code priority} 决定，见 {@code routing.py::build_route_v2}），
     * 而派生必须确定，否则同一张单两次生成会得到不同工序序列与计件工资。</p>
     */
    public List<ProductionRouteRule> routeRules(Long tenantId) {
        List<ProductionRouteRule> rows = productionRouteRuleMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteRule>()
                        .eq(ProductionRouteRule::getTenantId, tenantId)
                        .eq(ProductionRouteRule::getDeleted, 0)
                        .eq(ProductionRouteRule::getStatus, "active")
                        .orderByAsc(ProductionRouteRule::getPriority)
                        .orderByAsc(ProductionRouteRule::getId));
        return rows == null ? List.of() : rows;
    }

    /**
     * 旧工序名 → 逻辑工序名（{@code routing.py::OPERATION_LOGICAL_NAMES} 的 Java 侧同一份表）。
     *
     * <p>未登记的工序名**原样返回**（不抛）：{@code production_operations} 是商家可自定义的，
     * 自建工序不在 35 条表里是正常态；把它当错误会让「商家加一道自定义工序」变成 500。</p>
     */
    public String normalizeOperationName(String name) {
        return logicalOperationName(name);
    }

    /**
     * 同上，**静态入口**（issue #4621）：读面派生「工序显示名」时，**未注入本服务**的读面
     * （{@code ProductionService} 的工序实例 / 报工流水读面）也要用**同一份表** ——
     * 在那里另抄一份映射、或另写一处推导，就是第二份口径（漂移的那一份不会变红）。
     *
     * <p>语义与 {@link #normalizeOperationName} **逐字相同**（同一个 {@link #OPERATION_LOGICAL_NAMES}）：
     * 未登记的工序名**原样返回**（商家自建工序不在 35 条表里是正常态）。</p>
     */
    public static String logicalOperationName(String name) {
        return name == null ? null : OPERATION_LOGICAL_NAMES.getOrDefault(name, name);
    }

    /**
     * 工序实例的**显示用部位**（issue #4621，读时派生、**不写库**）。
     *
     * <p>web 界面的工序显示名口径 = 逻辑名（{@link #logicalOperationName}），该实例**带部位**时
     * 拼成 {@code 逻辑名 · 部位}（如 {@code 三边 · 布帘}）。本方法回答「要不要拼、拼哪个部位」：</p>
     * <ul>
     *   <li>变体名与逻辑名**不同**（{@code 精裁-布} ≠ {@code 精裁}）⇒ 名字里**编了部位**
     *       ⇒ 返回 {@code position}（{@code 布帘}）；</li>
     *   <li>两者**相同**（{@code 外帘装袋} == {@code 外帘装袋}）⇒ 该工序**与部位无关**
     *       （真值源里 7 道裸名工序：帘头制作 / 外帘打卷 / 外帘装袋 / 外帘发货 / 质检 / 抱枕 /
     *       腰靠垫）⇒ 返回 {@code null}（界面只显示逻辑名，不拼部位）。</li>
     * </ul>
     *
     * <p>判据直接用**既有映射**（{@link #logicalOperationName}）判定，**不新增第二份表**；
     * 也不能拿 {@code production_operations.position} 列当判据 —— 那列对 {@code 外帘装袋} 是
     * {@code 外帘}（套级/通用工序的部位列），拿它会拼出「外帘装袋 · 外帘」这种自相矛盾的名字。</p>
     *
     * @param operationName 实例上的工序名（变体名 / 报工快照名）
     * @param position      该实例所属部位（路线部位 / 实例的 {@code position_kind}）
     * @return 显示用部位；部位无关 / 任一侧缺失 ⇒ {@code null}
     */
    public static String displayPosition(String operationName, String position) {
        if (operationName == null || position == null || position.isBlank()) {
            return null;
        }
        return operationName.equals(logicalOperationName(operationName)) ? null : position;
    }

    /**
     * 逻辑工序名 + 部位 → **该租户库里的变体名**（{@link #VARIANT_NAMES} 的显式逆索引）。
     *
     * <p>查找三步（顺序敏感）：</p>
     * <ol>
     *   <li>{@code (逻辑名, 部位)} 在逆索引里且**该变体真在库中** ⇒ 返回它。
     *       ⚠️ 帘头格走的是逆索引里的**显式**帘头条目（{@link #headVariants(Map)}，
     *       issue #4777）—— <b>改前</b>这里是一条**隐式规则**
     *       （「部位 = 帘头 ⇒ 取 {@code VARIANT_NAMES[逻辑名][布帘]}」），
     *       与「逻辑名 + 部位后缀」的字符串规则同一类东西，而本文件开头写明
     *       「**必须是显式表，不许规则推导**」⇒ 本单把它换成显式表（**解析结果逐格不变**，
     *       覆盖域由 {@code MainlineOperationReferenceTest} 双向钉住）；</li>
     *   <li>裸逻辑名在库中 ⇒ 返回裸名（{@code 外帘打卷} 这类**部位无关**的工序）；</li>
     *   <li>否则 {@code null}（**不猜**，由调用方 fail-closed 指名报缺）。</li>
     * </ol>
     *
     * <p>⚠️ <b>返回的变体名一律来自真值源表或裸逻辑名，且必须真在库中</b> ——
     * 任何「拼出来」的名字都会在库里落空，进而让实例化 fail-closed 或让工序错配。</p>
     *
     * <p>🔴 <b>不变式（issue #4777 的守卫）：矩阵里凡 {@code applicable = TRUE} 的格，
     * 本方法必须解析得到一条库行</b> —— 解析不到 ⇒ {@code ProcessingOrderService.buildRoute}
     * 把它记进 {@code missing_operations} ⇒ 该部位的单 **fail-closed 422**（商家配的价进不了单）。
     * 守卫 = {@code MainlineOperationReferenceTest#everyApplicableMatrixCellResolvesToALibraryRow}
     * （逐格，含帘头格）+ Python 侧
     * {@code tests/unit_ci_workflows/test_v91_baseline_operations_backfill.py}
     * 的 {@code test_canonical_matrix_applicable_cells_all_resolve_at_runtime}（同一判据的静态面）。</p>
     *
     * @param catalogByName 该租户工序库按名索引（{@link #operationsByName}）；
     *                      调用方一次取回、循环内复用（避免 N+1）
     * @return 变体名；库中没有该变体 ⇒ {@code null}（**不猜**，由调用方 fail-closed 指名报缺）
     */
    public String variantNameOf(String logicalName, String position,
                                Map<String, Map<String, Object>> catalogByName) {
        if (logicalName == null || catalogByName == null) {
            return null;
        }
        Map<String, String> byPosition = VARIANT_NAMES.get(logicalName);
        if (byPosition != null) {
            String variant = byPosition.get(position);
            if (variant != null && catalogByName.containsKey(variant)) {
                return variant;
            }
        }
        // 部位无关的工序（帘头制作 / 外帘打卷 / 外帘装袋 / 外帘发货 / 质检 / 抱枕 / 腰靠垫）
        return catalogByName.containsKey(logicalName) ? logicalName : null;
    }

    /**
     * 工序元数据按名索引（**条件工序**与主线工序共用同一份读取口径）。
     *
     * <p>返回的是**旧名**索引（{@code production_operations.name} 仍是旧名）——
     * 调用方先用 {@link #normalizeOperationName} 拿逻辑名、再用 {@link #variantNameOf}
     * 换回变体名，**不在此另存一份映射表**（那就是第二份口径）。</p>
     */
    public Map<String, Map<String, Object>> operationsByName(Long tenantId) {
        Map<String, Map<String, Object>> views = new LinkedHashMap<>();
        catalogByName(tenantId).forEach((name, op) -> views.put(name, operationMetaView(op)));
        return views;
    }

    /**
     * 路线主线的**逻辑工序名**序列（JSONB 列归一化；与 {@link #templateView} 同一份口径）。
     *
     * <p>public 的理由（issue #4587 ③）：删工序的护栏要按主线逐个工序名比对 ——
     * 归一化必须与读面同一份，在写面自己解一遍 JSONB 就是第二份口径。</p>
     */
    public List<String> mainlineOf(ProductionRouteTemplate template) {
        return template == null ? List.of() : stringList(template.getMainline());
    }

    /**
     * 信号 → 路线键映射（V60，issue #4308，**派生用**读面）。
     *
     * <p>与迁移前 {@code ProcessingOrderService} 里两个 {@code String[][]} 常量的分工完全相同，
     * 只是数据源从「研发改的常量」换成「商家可配的库行」：命中方式仍是文本 {@code contains}，
     * {@code priority} 仍是**用途内**扫描序（帘种行与工艺行各自排序，理由见 V60 迁移注释）。</p>
     *
     * <p>只返回**活跃**行（{@code status=active} + 未软删 + 同租户），按
     * {@code (priority, id)} 稳定排序 —— 派生必须是确定性的，否则同一张单两次生成会得到不同的
     * 路线键（进而不同的工序序列与计件工资）。</p>
     */
    public List<ProductionRouteSignal> routeSignals(Long tenantId) {
        List<ProductionRouteSignal> rows = productionRouteSignalMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteSignal>()
                        .eq(ProductionRouteSignal::getTenantId, tenantId)
                        .eq(ProductionRouteSignal::getDeleted, 0)
                        .eq(ProductionRouteSignal::getStatus, "active")
                        .orderByAsc(ProductionRouteSignal::getPriority)
                        .orderByAsc(ProductionRouteSignal::getId));
        return rows == null ? List.of() : rows;
    }

    /**
     * **缺口可查**（issue #4308 交付物 5 / P4）：把「只活在代码注释里的缺口」变成商家能看见的数据。
     *
     * <p>两只清单：</p>
     * <ol>
     *   <li>{@code unrouted_operations} —— **有活跃工序但未进任何活跃路线**的工序。
     *       真值源下应为 {@code 裁剪-布 / 裁剪-纱 / 质检 / 腰靠垫} 四道，且它们**不是缺陷**：
     *       issue #4261 逐项登记了「为什么必须问客户」（裁剪vs精裁是否两道 / 质检是否每单必做 /
     *       腰靠垫归属 / 罗马帘整套工序 / 纱帘熨烫定型）⇒ 每条带
     *       {@code pending_confirmation=true}，**不要让商家/前端把它们读成「系统漏了」**。</li>
     *   <li>{@code signal_keys_without_route} —— **库里没有路线的信号组合**：逐个活跃信号行算出
     *       「只命中它时会派生的键」（另一维取默认），报出库中无该路线的那些。
     *       例：商家自建信号「罗马帘」⇒ {@code 罗马帘×韩褶} 无路线（#4261 ①，本单**不发明**该路线）。</li>
     * </ol>
     *
     * <p><b>P2b 口径（issue #4459 §2②，按最小改动定）</b>：{@code signal_keys_without_route}
     * **不纳入**「工艺无规则」缺口 —— 它回答的是「这个键有没有路线」，而新结构里
     * 「某工艺没有规则行」**不构成缺陷**（主线本身就是该工艺的基准序列，规则只描述变体）。
     * 并进来会让 5 个工艺之外的一切都报缺口，商家看到一屏「缺口」而实际全部可用
     * ⇒ 真缺口（库里连模板都没有）被淹没。</p>
     */
    public Map<String, Object> routingGaps(Long tenantId) {
        Set<String> routed = new LinkedHashSet<>();
        for (ProductionRouteTemplate template : routeTemplates(tenantId)) {
            routed.addAll(stringList(template.getMainline()));
        }

        List<Map<String, Object>> unrouted = new ArrayList<>();
        int pending = 0;
        for (ProductionOperation op : activeOperations(tenantId)) {
            // 判据 = **归一后的逻辑名**是否被某条主线消费（主线存的是逻辑名，工序库存的是旧名）
            if (routed.contains(normalizeOperationName(op.getName()))) {
                continue;
            }
            boolean isPending = PENDING_CUSTOMER_CONFIRMATION_OPERATIONS.contains(op.getName());
            if (isPending) {
                pending++;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            // 读时归一（issue #4642，与 operationView 同口径）：缺口清单是**同一条泄漏路径**
            // —— 当前 FE 无渲染方，但让库口径变体名留在 web 可见响应里就是下一次漏回界的入口。
            entry.put("name", normalizeOperationName(op.getName()));
            entry.put("library_name", op.getName());
            entry.put("group_name", op.getGroupName());
            entry.put("unit", op.getUnit());
            entry.put("unit_price", nz(op.getUnitPrice()));
            entry.put("pending_confirmation", isPending);
            entry.put("note", isPending
                    ? "有意挂起、等客户输入（issue #4261 提问清单），不是系统漏了；客户回复前不要替它编工序/单价"
                    : "该工序有价但没有任何活跃路线消费它；可经「工艺路线」页把它加进某条路线，或停用它");
            unrouted.add(entry);
        }

        List<Map<String, Object>> signalGaps = new ArrayList<>();
        for (ProductionRouteSignal signal : routeSignals(tenantId)) {
            String curtainType = signal.getCurtainType() == null
                    ? ProcessingOrderService.DEFAULT_CURTAIN_TYPE : signal.getCurtainType();
            String craft = signal.getCraft() == null
                    ? ProcessingOrderService.DEFAULT_CRAFT : signal.getCraft();
            // 判据 = 该部位能否取到路线模板（默认模板兜底也算「有路线」）；
            // 库里连模板都没有才算「这个信号组合没有路线」。
            if (routeTemplateFor(tenantId, curtainType) != null
                    || defaultRouteTemplate(tenantId) != null) {
                continue;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("curtain_type", curtainType);
            entry.put("craft", craft);
            entry.put("route_key", curtainType + "×" + craft);
            entry.put("signal", signal.getSignal());
            signalGaps.add(entry);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("unrouted_operations", unrouted);
        result.put("unrouted_operation_total", unrouted.size());
        result.put("pending_confirmation_total", pending);
        result.put("signal_keys_without_route", signalGaps);
        return result;
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 内部读取口径
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 活跃路线模板（tenant + deleted=0 + status=active；**默认优先 → 先建者优先 → id 稳定**）。

     * <p>⚠️ 排序**第三键不是装饰**（issue #4563）：`id` 是 UUID（`ASSIGN_UUID`）而种子 id 形如
     * `rt-v79-01` ⇒ **UUID 的十六进制字符恒小于 `r`** ⇒ 只按 `id` 排会把**新建的**排在前面、
     * 静默顶掉种子路线。用 `created_at` 作第二键 = 「**先建者优先**」，新建的**不会**顶掉既有。</p>
     *
     * <p>public 的理由（issue #4587 ③）：删工序的护栏要判「它还在不在某条**活跃主线**里」
     * —— 那条判据必须读**同一份**活跃口径（{@code deleted=0 AND status='active'}），
     * 在写面另拼一次查询就是第二份口径。</p>
     */
    public List<ProductionRouteTemplate> routeTemplates(Long tenantId) {
        List<ProductionRouteTemplate> rows = productionRouteTemplateMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteTemplate>()
                        .eq(ProductionRouteTemplate::getTenantId, tenantId)
                        .eq(ProductionRouteTemplate::getDeleted, 0)
                        .eq(ProductionRouteTemplate::getStatus, "active")
                        .orderByDesc(ProductionRouteTemplate::getIsDefault)
                        // 🔴 issue #4563（P1·涉钱）：**先建者优先** —— 见 `routeTemplateFor` 的说明。
                        // 缺了它，tie-break 只剩 `id ASC`，而新建路线的 id 是 UUID（十六进制字符
                        // **恒小于**种子 `rt-…`）⇒ 任何新建的、`positions` 含同部位的路线都会
                        // **静默顶掉**既有路线（布料单会丢「配料」，空壳路线更会出**零工序加工单**）。
                        .orderByAsc(ProductionRouteTemplate::getCreatedAt)
                        .orderByAsc(ProductionRouteTemplate::getId));
        return rows == null ? List.of() : rows;
    }

    /**
     * 活跃**工艺词表**的名字（去重保序）—— 条件工序规则 {@code trigger_kind='craft'} 的
     * **受控取值域**（issue #4616）。
     *
     * <p>为什么必须由后端给：{@code production_crafts} 此前**没有任何读端点**，而规则写面要校验
     * 「触发值存在于对应词表」、前端要「按类型从对应词表取、不手输」⇒ 两侧都需要这一份。
     * 前端自己从规则表现存 trigger_value 反推 = 第二份会漂的词表（新建的工艺永远进不了下拉）。</p>
     *
     * @return 活跃工艺名（该租户零活跃工艺 ⇒ 空列表，**不发明**默认值）
     */
    public List<String> activeCraftNames(Long tenantId) {
        List<String> names = new ArrayList<>();
        for (ProductionCraft craft : activeCrafts(tenantId)) {
            if (craft.getName() != null && !names.contains(craft.getName())) {
                names.add(craft.getName());
            }
        }
        return names;
    }

    /** 活跃工艺词表行（tenant + deleted=0 + status=active；默认优先、其余按名稳定）。 */
    private List<ProductionCraft> activeCrafts(Long tenantId) {
        List<ProductionCraft> rows = productionCraftMapper.selectList(
                new LambdaQueryWrapper<ProductionCraft>()
                        .eq(ProductionCraft::getTenantId, tenantId)
                        .eq(ProductionCraft::getDeleted, 0)
                        .eq(ProductionCraft::getStatus, "active")
                        .orderByDesc(ProductionCraft::getIsDefault)
                        .orderByAsc(ProductionCraft::getName));
        return rows == null ? List.of() : rows;
    }

    /**
     * 活跃工序（tenant + deleted=0 + status=active，按分组/排序位稳定返回）。
     */
    private List<ProductionOperation> activeOperations(Long tenantId) {
        List<ProductionOperation> rows = productionOperationMapper.selectList(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getDeleted, 0)
                        .eq(ProductionOperation::getStatus, "active")
                        .orderByAsc(ProductionOperation::getSortOrder)
                        .orderByAsc(ProductionOperation::getName));
        return rows == null ? List.of() : rows;
    }

    /** 工序库行按名索引（不含 status 过滤：路线引用了停用/历史工序时要能**指名报缺**，而不是当它不存在）。 */
    private Map<String, ProductionOperation> catalogByName(Long tenantId) {
        Map<String, ProductionOperation> byName = new LinkedHashMap<>();
        List<ProductionOperation> rows = productionOperationMapper.selectList(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getDeleted, 0));
        if (rows != null) {
            for (ProductionOperation op : rows) {
                byName.put(op.getName(), op);
            }
        }
        return byName;
    }

    /**
     * 工序项展示形态（目录项 / 写面 PUT 的响应**共用同一份**——两处各自拼一份必然漂移，
     * 而前端拿同一个 TS 类型渲染两者）。
     *
     * <p><b>{@code name} 读时归一（issue #4642）</b>：返回**逻辑工序名**（走**既有**
     * {@link #normalizeOperationName}，不新造第二份表）—— 否则 web 面（工序库目录、孤儿接入弹窗）
     * 直接渲染 {@code op.name} 就把**库口径变体名**（{@code 精裁-布} / {@code 布三边}）送上商家屏。
     * 三条边界：</p>
     * <ul>
     *   <li><b>只归一能归一的</b>：未登记的自定义工序名（{@code 测试22}）归一后等于自身 ⇒ 原样返回；</li>
     *   <li><b>不写库</b>：纯读时派生 —— {@code production_operations.name} 那一列一字未动
     *       （本单不含数据迁移，可回溯「当时存的是什么」）；</li>
     *   <li><b>库口径另给显式键</b>：{@code library_name} 承载**原始库名**（见下）。</li>
     * </ul>
     *
     * <p>⚠️ <b>{@code library_name} = 库口径原名，web 界面不得渲染该键</b>（issue #4642 消费面核查）：
     * 它的值域是**工人端快照名口径**（{@code 精裁-布}），渲染它等于把变体名送回商家屏。
     * 它存在只为「按库名寻址/对账」的调用方（写面回显「我落的到底是哪一行」）；商家面显示名一律取
     * {@code name}（逻辑名）+ {@code position}（部位）。</p>
     */
    public Map<String, Object> operationView(ProductionOperation op) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", op.getId());
        view.put("name", normalizeOperationName(op.getName()));
        // 库口径原名（**web 不得渲染**，见 javadoc）：库里那一列仍是旧名（精裁-布），
        // 而 name 已是逻辑名（精裁）⇒ 需要「原始库名」的调用方从这里取，不从这里取显示名。
        view.put("library_name", op.getName());
        view.put("group", op.getGroupName());
        view.put("position", op.getPosition());
        // 作用域（V67，issue #4384 A1）：部位级 / 套级（每樘窗一次）。**逐字取库**（与 unit/unit_price 同级）——
        // 前端靠它渲染可改的下拉，实例化侧（A2）靠它判「每樘窗只做一次」。写死常量即第二份口径。
        view.put("scope", op.getScope());
        view.put("unit", op.getUnit());
        view.put("unit_price", nz(op.getUnitPrice()));
        // 🔴 历史载体，**恒 false**（#4961）：`is_must_finish` 已退场（完工口径 = 全部活跃工序实例完成），
        // 键保留只为不破冻结契约（工序目录/工艺项读面的既有消费者按固定键集取值）。
        view.put("is_must_finish", false);
        view.put("is_start_marker", Boolean.TRUE.equals(op.getIsStartMarker()));
        // provenance（V62，issue #4361）：单价是占位值/行业推算值这件事必须**在界面上可见**
        // （用户裁定：「照铺，但 provenance 必须可见，不许静默」）。NULL = 来源未知，不冒充已知。
        view.put("source", op.getSource());
        return view;
    }

    /**
     * 工序的库口径元数据（主线工序与**条件工序**共用同一份整形 —— 两处各拼一份必然漂移，
     * 而它们最终落在同一张实例表的同名列上）。
     */
    private Map<String, Object> operationMetaView(ProductionOperation op) {
        Map<String, Object> view = new LinkedHashMap<>();
        // id：矩阵读面要用它当 `variant_operation_id`（issue #4587 ①「该格实际落到工人端那道工序」）
        view.put("id", op == null ? null : op.getId());
        view.put("group", op == null ? null : op.getGroupName());
        view.put("unit", op == null ? null : op.getUnit());
        view.put("unit_price", op == null ? null : nz(op.getUnitPrice()));
        // 🔴 历史载体，**恒 false**（#4961）：概念退场，键保留（路线步骤/实例化 payload 的键集契约）。
        view.put("is_must_finish", false);
        view.put("is_start_marker", op != null && Boolean.TRUE.equals(op.getIsStartMarker()));
        // 作用域（V67，issue #4384 A1）：实例化侧据此带出「部位级 / 套级」。
        // 库中缺该工序（op == null）⇒ null，**不猜默认值** —— 猜出来的 scope 会让 A2 静默去重。
        view.put("scope", op == null ? null : op.getScope());
        // provenance 与目录读面**同一份口径**（两处各拼一份必然漂移，而前端拿同一个 TS 类型渲染）
        view.put("source", op == null ? null : op.getSource());
        return view;
    }

    /**
     * JSONB 列归一化为 {@code List<String>}（{@code JacksonTypeHandler} 反序列化后可能是
     * {@code List<?>}，少数路径回落到 JSON 文本）⇒ 两种形态都收敛，不让调用方各自解析一遍。
     */
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

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    /**
     * 旧工序名 → 逻辑工序名（**逐条写出，不用「去后缀」字符串规则推导**）。
     *
     * <p>与真值源 {@code routing.py::_LOGICAL_NAME_PAIRS} 逐字同源：{@code 布三边}/{@code 纱三边}
     * （无 {@code -} 分隔）、{@code 布帘车被}（{@code 布帘} 前缀）这类名字用规则推导会漏。
     * 漂移护栏 = {@code ProductionOperationQueryServiceTest#logicalNameTableMatchesTruthSource}
     * 逐字解析 {@code routing.py} 的 {@code _LOGICAL_NAME_PAIRS} 并与本表**双向比对**。</p>
     */
    private static Map<String, String> logicalNamePairs() {
        Map<String, String> names = new LinkedHashMap<>();
        names.put("精裁-布", "精裁");
        names.put("精裁-纱", "精裁");
        names.put("裁剪-布", "裁剪");
        names.put("裁剪-纱", "裁剪");
        names.put("布三边", "三边");
        names.put("纱三边", "三边");
        names.put("韩褶-布", "韩褶");
        names.put("韩褶-纱", "韩褶");
        names.put("上车布-布", "上车布");
        names.put("上车布-纱", "上车布");
        names.put("打孔-布", "打孔");
        names.put("打孔-纱", "打孔");
        names.put("拼1次-布", "拼1次");
        names.put("拼2次-布", "拼2次");
        names.put("拼3次-布", "拼3次");
        names.put("花边-布", "花边");
        names.put("铅坠-布", "铅坠");
        names.put("接高-布", "接高");
        names.put("帘头制作", "帘头制作");
        names.put("熨烫-布", "熨烫");
        names.put("定型-布", "定型");
        names.put("复烫-布", "复烫");
        names.put("布帘车被", "车被");
        names.put("外帘打卷", "外帘打卷");
        names.put("外帘装袋", "外帘装袋");
        names.put("质检", "质检");
        names.put("外帘发货", "外帘发货");
        names.put("绑带-布", "绑带");
        names.put("抱枕", "抱枕");
        names.put("腰靠垫", "腰靠垫");
        names.put("绑带-纱", "绑带");
        names.put("logo条-布", "logo条");
        names.put("立边-布", "立边");
        names.put("扣环-布", "扣环");
        names.put("防翘扣-布", "防翘扣");
        return Map.copyOf(names);
    }

    /**
     * {@link #VARIANT_NAMES} 的构造：**35 条旧名 ↔ 逻辑名对的反向索引**（真值源
     * {@code routing.py::_LOGICAL_NAME_PAIRS}，逐条一一对应），另加 **1 条部位回落**
     * （{@code 裁剪 × 布料} → {@code 裁剪-布}，issue #4707：布料主线 V88 后引用 `裁剪`）。
     *
     * <p>逐条显式写出（**不推导**）：{@code 布三边}（无 {@code -} 分隔）、{@code 布帘车被}
     * （{@code 布帘} 前缀）用规则推导会漏 —— 实测「逻辑名 + 部位后缀」对这两道得到的
     * {@code 三边-布}/{@code 车被-布} 库里都不存在。</p>
     */
    private static Map<String, Map<String, String>> variantNames() {
        Map<String, Map<String, String>> names = new LinkedHashMap<>();
        // ── 布帘变体（21 条）──
        variant(names, "精裁", "布帘", "精裁-布");
        variant(names, "裁剪", "布帘", "裁剪-布");
        variant(names, "三边", "布帘", "布三边");
        variant(names, "韩褶", "布帘", "韩褶-布");
        variant(names, "上车布", "布帘", "上车布-布");
        variant(names, "打孔", "布帘", "打孔-布");
        variant(names, "拼1次", "布帘", "拼1次-布");
        variant(names, "拼2次", "布帘", "拼2次-布");
        variant(names, "拼3次", "布帘", "拼3次-布");
        variant(names, "花边", "布帘", "花边-布");
        variant(names, "铅坠", "布帘", "铅坠-布");
        variant(names, "接高", "布帘", "接高-布");
        variant(names, "熨烫", "布帘", "熨烫-布");
        variant(names, "定型", "布帘", "定型-布");
        variant(names, "复烫", "布帘", "复烫-布");
        variant(names, "车被", "布帘", "布帘车被");
        variant(names, "绑带", "布帘", "绑带-布");
        variant(names, "logo条", "布帘", "logo条-布");
        variant(names, "立边", "布帘", "立边-布");
        variant(names, "扣环", "布帘", "扣环-布");
        variant(names, "防翘扣", "布帘", "防翘扣-布");
        // ── 纱帘变体（7 条）──
        variant(names, "精裁", "纱帘", "精裁-纱");
        variant(names, "裁剪", "纱帘", "裁剪-纱");
        variant(names, "三边", "纱帘", "纱三边");
        variant(names, "韩褶", "纱帘", "韩褶-纱");
        variant(names, "上车布", "纱帘", "上车布-纱");
        variant(names, "打孔", "纱帘", "打孔-纱");
        variant(names, "绑带", "纱帘", "绑带-纱");
        // ── 帘头专属（库里真有这一行；其余工序的帘头格走 `headVariants` 的显式条目）──
        variant(names, "帘头制作", "帘头", "帘头制作");
        // ── 布料（第 4 部位，issue #4707）──
        // `V88`（#4676）把布料主线从 `["配料","打包"]` 改成 **`["裁剪","打包"]`**，并显式种下
        // **保命格** `裁剪 × 布料`（`applicable = TRUE`，`V88` ④）。但保命格只过了 `buildRoute`
        // 的**第一道闸**（`applicableByLogical` 查得到键）；**第二道闸** `variantNameOf` 仍要
        // 「逻辑名 × 部位 → 该租户库里的变体名」——而 `裁剪` 的变体表里**只有 布帘 / 纱帘**
        // ⇒ 返回 `null` ⇒ `裁剪` 进 `missing_operations` ⇒ **纯布料单 fail-closed 422**。
        // ⚠️ 这与「工序库为空」**正交**：**健康租户（1 号）也 422**（真库红证见 PR body）。
        // 修复 = 把 `裁剪 × 布料` 显式指到 `裁剪-布`（唯一承载「裁剪」元数据的库行：
        // 分组=裁剪 / 单位=米 / scope=position）—— 与 `headVariants` 的帘头条目**同款显式回落**，
        // 逐条写出**不推导**（既有纪律：`布三边`/`布帘车被` 用规则推导会漏）。
        // ⚠️ 价**不**从这里取：矩阵格 `裁剪 × 布料` 的价（NULL = 未定价，V90）优先，
        //    本表只回答「是哪条库行」。
        variant(names, "裁剪", "布料", "裁剪-布");
        // ⚠️ 返回**可变**表（issue #4777）：{@link #variantNamesWithCurtainHead()} 要在它之上
        //    再叠加 {@link #headVariants(Map)} 的 21 条帘头条目，最后才 `Map.copyOf` 冻结。
        //    ⚠️ 本方法的 `variant(...)` 调用集被 V97 的守卫**逐条冻结**为 30 条 —— 不得增删。
        return names;
    }

    /**
     * {@link #VARIANT_NAMES} 的合成入口：{@link #variantNames()}（30 条，被 V97 守卫冻结）
     * + {@link #headVariants(Map)}（21 条帘头）。
     */
    private static Map<String, Map<String, String>> variantNamesWithCurtainHead() {
        Map<String, Map<String, String>> names = variantNames();
        headVariants(names);
        sheerVariants(names);
        return Map.copyOf(names);
    }

    /** 逆索引写入（同一逻辑名多部位 ⇒ 累加到同一个内层表）。 */
    private static void variant(Map<String, Map<String, String>> names,
                                String logicalName, String position, String variantName) {
        names.computeIfAbsent(logicalName, key -> new LinkedHashMap<>())
                .put(position, variantName);
    }

    /**
     * **帘头变体（21 条，逐条显式写出、不推导）** —— issue #4777。
     *
     * <p>帘头**没有自己的变体行**（库里从来没有 {@code -帘} 变体），历史上复用**布帘**那一列。
     * 旧实现把这件事写成 {@link #variantNameOf} 里的一条**隐式规则**
     * （「部位 = 帘头 ⇒ 取 {@code VARIANT_NAMES[逻辑名][布帘]}」）—— 与
     * 「逻辑名 + 部位后缀」的字符串规则**同一类东西**，而本文件开头就写明
     * 「**必须是显式表，不许规则推导**」（{@code 布三边} / {@code 布帘车被} 用规则推导会漏）。
     * 本单把它换成显式表：{@code 帘头 × 精裁 → 精裁-布} 这类条目**逐条写出来**，
     * 于是「删一条帘头条目 ⇒ 该帘头格解析不到 ⇒ 帘头单 fail-closed」这件事
     * **第一次可被守卫抓住**（改前由隐式规则兜着，删哪条都不会红）。</p>
     *
     * <p>🔴 <b>覆盖域 = {@code VARIANT_NAMES} 里**有布帘条目**的全部逻辑名（21 个）</b>，
     * <b>不是</b>只列「帘头 {@code applicable = TRUE}」的那 14 个：矩阵格
     * {@code applicable = FALSE}（「该部位明确不做」）在**读面**（{@code GET /operation-positions}
     * 的 {@code variant_operation_id} / {@code unit} / {@code group} / {@code scope} /
     * {@code is_must_finish}）照样要解析出「落到工人端哪道工序」⇒ 少列一条 = 读面那 5 个键
     * **静默变 null**（口径变更，不是本单要做的事）。
     * 覆盖域由 {@code MainlineOperationReferenceTest#headVariantsCoverExactlyTheClothColumn}
     * 双向钉住（少一条 / 多一条 / 值不同都红）。</p>
     *
     * <p>为什么**另起一段**而不是并进 {@link #variantNames()}：后者的
     * {@code variant(...)} 调用集被 {@code V97} 的守卫
     * （{@code test_v97_variant_map_matches_production_code}）**逐条冻结**为 30 条，
     * 而 {@code V97} 是**已发布迁移**（红线：不得改、不得重生成指纹）⇒ 帘头条目只能落在
     * 上面这个 {@code variant(...)} 写入器**之后**的另一段里
     * （该守卫的解析半径 = {@code variantNames()} 方法体到 {@code private static void variant(} 为止）。</p>
     *
     * <p>帘头路线的出处：{@code 帘头×平幔} 路线（V54 / V71）逐字引用
     * {@code 精裁-布} / {@code 布三边} / {@code 定型-布} —— 故帘头条目的值 = 该逻辑名的**布帘**变体。</p>
     */
    private static void headVariants(Map<String, Map<String, String>> names) {
        variant(names, "精裁", "帘头", "精裁-布");
        variant(names, "裁剪", "帘头", "裁剪-布");
        variant(names, "三边", "帘头", "布三边");
        variant(names, "韩褶", "帘头", "韩褶-布");
        variant(names, "上车布", "帘头", "上车布-布");
        variant(names, "打孔", "帘头", "打孔-布");
        variant(names, "拼1次", "帘头", "拼1次-布");
        variant(names, "拼2次", "帘头", "拼2次-布");
        variant(names, "拼3次", "帘头", "拼3次-布");
        variant(names, "花边", "帘头", "花边-布");
        variant(names, "铅坠", "帘头", "铅坠-布");
        variant(names, "接高", "帘头", "接高-布");
        variant(names, "熨烫", "帘头", "熨烫-布");
        variant(names, "定型", "帘头", "定型-布");
        variant(names, "复烫", "帘头", "复烫-布");
        variant(names, "车被", "帘头", "布帘车被");
        variant(names, "绑带", "帘头", "绑带-布");
        variant(names, "logo条", "帘头", "logo条-布");
        variant(names, "立边", "帘头", "立边-布");
        variant(names, "扣环", "帘头", "扣环-布");
        variant(names, "防翘扣", "帘头", "防翘扣-布");
    }

    /**
     * **纱帘变体（4 条，逐条显式写出）** —— issue #4937（去部位化彻底版）。
     *
     * <p>🔴 <b>为什么必须新增这 4 条</b>：{@code 熨烫 / 定型 / 复烫 / 车被} 原来被
     * {@code processing_operation_positions.applicable} 的过滤挡在**纱帘**路线之外
     * （{@code 熨烫 × 纱帘} 在 V71 种子里是 {@code FALSE}）⇒ 库里从来没建过它们的纱帘变体。
     * 本包把那条过滤**整块删除**（用户裁定「部位不再参与任何取价、取路、筛选、配置」，
     * 母单 #4936）⇒ 这 4 道会进入纱帘路线的实例化路径，而 {@link #variantNameOf} 解析不到
     * ⇒ {@code null} ⇒ **整张纱帘单 fail-closed（一张也建不出来）**。
     * ⇒ 补齐变体行（{@code docs/sql/schema.sql} 的 {@code op-v54-31..34}，单价逐字取对应
     * {@code -布} 变体 —— **不发明单价**）。</p>
     *
     * <p>⚠️ <b>为什么另起一段而不是并进 {@link #variantNames()}</b>：后者被 {@code V97} 的守卫
     * （{@code test_v97_variant_map_matches_production_code}）**逐条冻结**为 30 条字面量，
     * 而 {@code V97} 是**已发布迁移**（红线：不得改）⇒ 与 {@link #headVariants(Map)} 同款，
     * 新增条目只能落在该守卫解析半径之外的这一段里。</p>
     */
    private static void sheerVariants(Map<String, Map<String, String>> names) {
        variant(names, "熨烫", "纱帘", "熨烫-纱");
        variant(names, "定型", "纱帘", "定型-纱");
        variant(names, "复烫", "纱帘", "复烫-纱");
        variant(names, "车被", "纱帘", "车被-纱");
    }
}
