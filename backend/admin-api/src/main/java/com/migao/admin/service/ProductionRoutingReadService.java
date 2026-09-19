package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 新路线模型的**只读**消费面（issue #4500 = 母单 #4423 的 P2c）：部位价目矩阵 + 规则区。
 *
 * <p>供 P3 前端（#4433）渲染「工序库的部位价目矩阵」与「统一规则区」—— 两个域的**读面**
 * 此前不存在（实测：规则/部位价目无端点），前端无数据可渲染。</p>
 *
 * <table>
 *   <caption>两个投影</caption>
 *   <tr><th>方法</th><th>数据源</th><th>形状</th><th>顺序</th></tr>
 *   <tr><td>{@link #operationPositions}</td><td>{@code production_operation_positions}（V71 84 行）</td>
 *       <td>{@code {operation, position, unit_price, applicable}}</td><td>{@code (operation, position)}</td></tr>
 *   <tr><td>{@link #routeRules}</td><td>{@code production_route_rules}（V71 26 条）</td>
 *       <td>10 键（见 {@code ruleView}）</td><td>{@code (priority, id)}</td></tr>
 * </table>
 *
 * <p><b>只读</b>：本类只有 SELECT，端点也只有 GET。写面（改价/增删规则）留 v1b —— 与「商家配置面
 * v1b」同批，不在 #4500。</p>
 *
 * <p><b>顺序为什么在 Java 侧显式排序</b>（不是 `ORDER BY`）：`logical_name` / `position` 是中文，
 * `ORDER BY` 的结果随 DB collation 变（C / en_US / ICU 三种排序各不相同）⇒ 同一份数据在不同环境
 * 得到不同顺序，前端每次刷新都可能换序。显式比较器把顺序钉成**环境无关**的确定值，且让
 * 「顺序」这条判据在单测里**可执行**（mocked mapper 返回乱序 ⇒ 断言可红）。</p>
 *
 * <p><b>行过滤只有三个条件</b>（租户 / 软删 / 停用）+ 规则表的 {@code action IN (insert, remove)}：
 * 任何额外的值过滤（如「只返回 applicable=true」）都会让矩阵/规则区**少行**，而「明确不做」
 * 与「没定价」必须在界面上可区分（#4433 判据 2）⇒ 84 格整份呈现。</p>
 *
 * <p><b>为什么 `action='factor'` 不在本端点</b>：V72 把旧 {@code production_option_factors} 的计件
 * 系数档搬进了同一张规则表（{@code action='factor'}），但那是**计件系数**（实例化路径消费），
 * 不是「工艺变体 ∪ 特殊选项」的路线编排规则（P3 统一规则区只呈现「插入 after X / 移除」）。
 * 混在一起会让 26 条口径失真、且形状里没有 {@code factor} 列可承载它。</p>
 *
 * <p><b>与实例化读面的关系</b>：{@code ProductionOperationQueryService}（P2b / issue #4459）也读这两张表
 * （{@code operationPositions} / {@code routeRules}），但那是**实例化用**的读面：返回**实体**、
 * 规则**不过滤** {@code action}（实例化需要 {@code factor} 计件系数档）、顺序交给 SQL {@code ORDER BY}。
 * 本类是**展示用**的读面，契约有三处不同，故不合并：① 形状 = issue #4500 冻结的键（规则项 10 键、
 * **不含** {@code factor}）；② 过滤 = 只呈现**路线编排档**（{@code insert}/{@code remove}，26 条口径）；
 * ③ 顺序 = Java 侧显式排序（见上，环境无关）。「怎么读这两张表」在 Mapper 层是同一条（同一组
 * 租户/软删/停用条件），差异只在投影 —— 合并会把「实例化契约」与「展示契约」耦成一处，
 * 任何一侧改口径都会静默改另一侧语义。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionRoutingReadService {

    /** 本端点呈现的规则动作 = 路线编排（{@code insert} / {@code remove}）。 */
    private static final List<String> ROUTE_ACTIONS = List.of("insert", "remove");

    private final ProductionOperationPositionMapper productionOperationPositionMapper;
    private final ProductionRouteRuleMapper productionRouteRuleMapper;

    /**
     * 部位价目矩阵：一道**逻辑工序** × 一个**部位** = 一格（28 × 3 = 84 格）。
     *
     * @return `[{operation, position, unit_price, applicable}]`，按 `(operation, position)` 稳定排序；
     *         `applicable=false` 的格 `unit_price=null`（**明确不做 ⇒ 不报价**，与「没定价」可区分）
     */
    public List<Map<String, Object>> operationPositions(Long tenantId) {
        List<ProductionOperationPosition> rows = productionOperationPositionMapper.selectList(
                new LambdaQueryWrapper<ProductionOperationPosition>()
                        .eq(ProductionOperationPosition::getTenantId, tenantId)
                        .eq(ProductionOperationPosition::getDeleted, 0)
                        .eq(ProductionOperationPosition::getStatus, "active"));
        List<ProductionOperationPosition> ordered = rows == null ? new ArrayList<>() : new ArrayList<>(rows);
        ordered.sort(Comparator.comparing(ProductionOperationPosition::getLogicalName)
                .thenComparing(ProductionOperationPosition::getPosition));
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionOperationPosition row : ordered) {
            items.add(positionView(row));
        }
        return items;
    }

    /**
     * 规则区：工艺变体 ∪ 特殊选项（**26 条** = 工艺 10 + 选项 16，母单 #4423 冻结数字）。
     *
     * @return 10 键（见 {@link #ruleView}），按 `(priority, id)` 稳定排序 ——
     *         **顺序敏感**（规则应用顺序决定工序序列），而 priority 撞档时「谁先」由 id 定
     */
    public List<Map<String, Object>> routeRules(Long tenantId) {
        List<ProductionRouteRule> rows = productionRouteRuleMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteRule>()
                        .eq(ProductionRouteRule::getTenantId, tenantId)
                        .eq(ProductionRouteRule::getDeleted, 0)
                        .eq(ProductionRouteRule::getStatus, "active")
                        .in(ProductionRouteRule::getAction, ROUTE_ACTIONS));
        List<ProductionRouteRule> ordered = rows == null ? new ArrayList<>() : new ArrayList<>(rows);
        ordered.sort(Comparator.comparing(ProductionRouteRule::getPriority)
                .thenComparing(ProductionRouteRule::getId));
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionRouteRule row : ordered) {
            items.add(ruleView(row));
        }
        return items;
    }

    /**
     * 部位价目格展示形态（**唯一**的整形点）。
     *
     * <p>⚠️ {@code operation} 取 {@code logical_name}（**逻辑工序名**：精裁/三边/韩褶…），
     * **不是** {@code production_operations.name}（那边仍是旧名 精裁-布/布三边…）。矩阵的行键
     * 是逻辑名 —— 取错会让前端按 35 个旧名渲染出「一行一道工序」的旧形态。</p>
     */
    private Map<String, Object> positionView(ProductionOperationPosition row) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("operation", row.getLogicalName());
        view.put("position", row.getPosition());
        view.put("unit_price", row.getUnitPrice());
        view.put("applicable", row.getApplicable());
        return view;
    }

    /**
     * 规则项展示形态（**唯一**的整形点；`position` / `after_operation` 可为 null = 不限部位 / 追加末尾）。
     *
     * <p>{@code customer_unit_price}（V77，**元/套**）只对 {@code trigger_kind='option'} 的
     * **特殊选项**行有意义 —— 行业口径是「选项按**套**收费」（拼2次 / 防翘扣 一类）。
     * ⚠️ {@code NULL} = **未定价**，与 {@code 0}（定价为 0 元）是两件事：前端**不得**把它
     * 渲染成 {@code ¥0.00}（未定价 ≠ 0 元，仓库硬纪律）。非 {@code option} 行（{@code craft}
     * 等工艺变体）**一律** {@code NULL} —— 工艺变体不按套计价。</p>
     *
     * <p>本方法**不**做任何取价 / 回退：不读 {@code production_option_factors}、不做 contains
     * 匹配、不按 trigger_value 拼键 —— 值原样取自 {@code production_route_rules.customer_unit_price}。</p>
     */
    private Map<String, Object> ruleView(ProductionRouteRule row) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", row.getId());
        view.put("trigger_kind", row.getTriggerKind());
        view.put("trigger_value", row.getTriggerValue());
        view.put("position", row.getPosition());
        view.put("action", row.getAction());
        view.put("operation", row.getOperation());
        view.put("after_operation", row.getAfterOperation());
        view.put("priority", row.getPriority());
        view.put("status", row.getStatus());
        view.put("customer_unit_price", row.getCustomerUnitPrice());
        return view;
    }
}
