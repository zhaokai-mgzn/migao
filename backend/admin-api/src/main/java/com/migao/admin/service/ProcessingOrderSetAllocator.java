package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper.ProcessingOrderSetRow;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * 新单的**套号分配器**（设计 {@code docs/design/set-code-and-scan-loop.md} §2.4 / §14 切片 ⓪.5，issue #4789）。
 *
 * <p><b>为什么有这个类</b>：V92（#4698 切片⓪）只建了载体 + **存量回填** ⇒ 新单从来不会被分配套号
 * （#4725 实测登记）⇒ 新单无 {@code set_no} ⇒ 码无从生成 ⇒ 二维码按钮对新单是空的、工人 H5 扫不到。
 * 设计 §2.4 给了算法与规则，但 §14 的切片 ①~⑤ **没有任何一片认领这个动作** —— 本类是那个缺片的落码，
 * 口径见设计 §14.1（先补设计、再落码）。</p>
 *
 * <h2>口径（与 V92 存量回填**同一份**，不造第二份）</h2>
 * <ul>
 *   <li><b>一套 = 一樘窗</b>（用户裁定 2026-09-20）= 一个 {@code craftLineId} 组
 *       （缺省回落本行 {@code itemId}；两者皆缺 ⇒ 各自成组）；</li>
 *   <li>组键、被吸收的 {@code componentRole='配布边'} 行、{@code position_item_ids} 的**有序**部位清单
 *       —— 逐条同 V92 回填段（唯一输入 = {@code processing_orders.items_snapshot}，固化真相）；</li>
 *   <li>{@code set_no} = {@code {processing_order_no}-{lpad(set_index,3,'0')}}（设计 §2.1 逐字）；</li>
 *   <li>序号 {@code = MAX(set_index)+1}，**MAX 查询不带 {@code deleted = 0}**（软删仍占号 ⇒ 只增不复用，§2.4 规则 1）。</li>
 * </ul>
 *
 * <h2>幂等</h2>
 * <p>① 该加工单**已有 live 套行** ⇒ 整段跳过（不重编号、不重插、不碰 {@code updated_at}）
 * —— 这是「**历史单零变化**」的实现（存量已由 V92 回填）；② 插入带
 * {@code ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING}；
 * ③ 重复触发本方法（同一单第二次实例化）走 ①。</p>
 *
 * <h2>并发（**悲观锁**，不是「撞唯一键再重试」）</h2>
 * <p>权威仍是库层唯一键 {@code uk_processing_order_sets_index}（V92 建，设计 §2.4 规则 3）——
 * 但**它的用法**必须与本类的调用上下文相容：分配发生在 {@code ProcessingOrderService.generateOne}
 * 的**外层事务内**（加工单行刚插入、尚未提交）⇒ 任何 {@code REQUIRES_NEW} 的分配事务都会**阻塞在
 * 父事务持有的行锁**上直到父事务结束 —— 那不是并发保护，是**自己把自己锁死**（新单首实例化必走这条路）。</p>
 * <p>且 PostgreSQL 里语句失败会把当前事务置 aborted（25P02）⇒ 同一事务内「撞唯一键后重读 MAX 重试」
 * **根本不成立**。⇒ 选**悲观锁**：本方法先 {@code SELECT … FOR UPDATE} 该单的套行（首次分配 ⇒
 * 锁住号池**间隙**），并发请求在此串行 ⇒ 读到的 {@code MAX} 必然是最新值；唯一键仍在库层兜底。</p>
 *
 * <p><b>不追溯历史单</b>：历史单已被 V92 回填 ⇒ 幂等①直接跳过；**未实例化**的存量单按设计 §2.5
 * 逐字口径「在**下次实例化时**按快照行序分配（不预先回填）」—— 本类正是那个「下次实例化时」。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingOrderSetAllocator {

    /** 套号 3 位零填充的上界（设计 §2.1 表 3：>999 **显式拒绝**，不静默截断）。 */
    private static final int MAX_SET_INDEX = 999;

    /** 被吸收的部件行角色（与 {@code ProcessingOrderService.COMPONENT_ROLE_EDGE} 逐字同值）。 */
    private static final String COMPONENT_ROLE_EDGE = "配布边";

    private final ProcessingOrderSetMapper orderSetMapper;

    /**
     * 确保该加工单的套行齐备（**幂等**；历史单一行不碰）。
     *
     * <p>{@link Propagation#REQUIRED}（加入调用方事务）：分配与实例化必须**同生共死** ——
     * 分配成功而实例化失败 ⇒ 留下「有套号、无工序」的套行（套号是**只增不复用**的，回滚不掉才是对的）。</p>
     *
     * @param po       加工单（{@code processing_order_no} 必须已定 —— 套号由它拼出）
     * @param snapshot 加工单快照（{@code items_snapshot}，固化真相；与 V92 回填的唯一输入同源）
     * @param tenantId 租户
     * @return 该单当前的 live 套行（按 {@code set_index} 升序）；无需分配时即既有行
     */
    @Transactional(propagation = Propagation.REQUIRED, rollbackFor = Exception.class)
    public List<ProcessingOrderSet> ensureSets(ProcessingOrder po, List<Map<String, Object>> snapshot,
                                               Long tenantId) {
        // 并发串行点：拿到该单号池的排他锁（首次分配 ⇒ 空结果，锁住间隙）。必须在 liveSets 之前。
        List<ProcessingOrderSet> existing = orderSetMapper.lockSetsOfOrder(tenantId, po.getId());
        if (existing != null && !existing.isEmpty()) {
            // 幂等①：已有套行 ⇒ 整段跳过（历史单零变化；号是分配出来的，不是算出来的 —— §2.4 规则 2）
            return existing;
        }
        if (snapshot == null || snapshot.isEmpty()) {
            // 快照缺失 = 无法确定樘窗 ⇒ 不猜（与 V92 回填的「解析失败 ⇒ 跳过该单」同口径）
            log.warn("套号分配跳过（快照为空）: po={}", po.getProcessingOrderNo());
            return List.of();
        }
        List<Group> groups = windowGroups(snapshot);
        if (groups.isEmpty()) {
            return List.of();
        }
        if (groups.size() > MAX_SET_INDEX) {
            // 设计 §2.1 表 3 / §11.3 停止条件 2：**显式拒绝**（截断 = 两套同号）
            throw BusinessException.validationError(String.format(
                    "加工单 %s 的樘窗数 %d 超过 %d 套上限（套号是 3 位零填充）⇒ 请拆单后再生成",
                    po.getProcessingOrderNo(), groups.size(), MAX_SET_INDEX));
        }
        return insertFrom(po, groups, tenantId);
    }

    /** 一次分配：读号池上界 → 逐组插入（`ON CONFLICT DO NOTHING`）→ 回读。 */
    private List<ProcessingOrderSet> insertFrom(ProcessingOrder po, List<Group> groups, Long tenantId) {
        // ⚠️ MAX 查询**不带 deleted = 0**：软删行仍占号 ⇒ 删一个窗再加一个**不复用已删号**（§2.4 规则 1）
        Integer max = maxSetIndex(po.getId(), tenantId);
        int next = (max == null ? 0 : max) + 1;
        OffsetDateTime now = OffsetDateTime.now();
        for (Group group : groups) {
            orderSetMapper.insertIgnoreConflict(new ProcessingOrderSetRow(
                    UUID.randomUUID().toString().replace("-", ""),
                    tenantId,
                    po.getId(),
                    next,
                    po.getProcessingOrderNo() + "-" + String.format("%03d", next),
                    group.craftLineId(),
                    positionItemIdsJson(group.positionItemIds()),
                    now,
                    now,
                    0));
            next++;
        }
        return liveSets(po.getId(), tenantId);
    }

    /**
     * 部位清单 → JSONB 文本（与 V92 的 {@code jsonb_agg} 同形：字符串数组）。
     * `@Insert` 里的 typeHandler 不生效 ⇒ 显式序列化 + `CAST(… AS jsonb)`。
     */
    private static String positionItemIdsJson(List<String> itemIds) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < itemIds.size(); i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append('"').append(itemIds.get(i).replace("\\", "\\\\").replace("\"", "\\\"")).append('"');
        }
        return sb.append(']').toString();
    }

    /** 号池上界（**不带 `deleted = 0`** —— 软删行仍占号，设计 §2.4 规则 1）。 */
    private Integer maxSetIndex(String processingOrderId, Long tenantId) {
        QueryWrapper<ProcessingOrderSet> wrapper = new QueryWrapper<>();
        wrapper.select("MAX(set_index) AS set_index")
                .eq("tenant_id", tenantId)
                .eq("processing_order_id", processingOrderId);
        List<Map<String, Object>> rows = orderSetMapper.selectMaps(wrapper);
        if (rows == null || rows.isEmpty() || rows.get(0) == null) {
            return null;
        }
        Object value = rows.get(0).get("set_index");
        // 空表 ⇒ `MAX(...)` 为 NULL ⇒ 号池从 1 起（**不是** 0 —— set_index 1 起，§2.1）
        return value instanceof Number number ? number.intValue() : null;
    }

    /** 该单的 live 套行（按 `set_index` 升序）—— 幂等判据与调用方落 `set_id` 都用它。 */
    public List<ProcessingOrderSet> liveSets(String processingOrderId, Long tenantId) {
        List<ProcessingOrderSet> rows = orderSetMapper.selectList(
                new LambdaQueryWrapper<ProcessingOrderSet>()
                        .eq(ProcessingOrderSet::getProcessingOrderId, processingOrderId)
                        .eq(ProcessingOrderSet::getTenantId, tenantId)
                        .eq(ProcessingOrderSet::getDeleted, 0)
                        .orderByAsc(ProcessingOrderSet::getSetIndex));
        return rows == null ? List.of() : rows;
    }

    // ============================================================ 樘窗分组（与 V92 回填同一口径）

    /** 一个樘窗组：组键 + 该组的**有序**部位行 `order_items.id` 清单。 */
    public record Group(String craftLineId, List<String> positionItemIds) {
    }

    /**
     * 快照 → 樘窗组（**逐条同 V92 回填段**；设计 §2.1 F11/F12 / §11.3）。
     *
     * <p>过滤与 `ProcessingOrderService.buildPositionPayload` 的实例化循环逐条对齐：
     * ① 只考虑有 {@code processingItems} 数组的行；② {@code componentRole='配布边'} 的行在同组
     * 存在主布行时被**吸收**（不独立成窗）；③ 组键 = {@code craftLineId ?? itemId}；
     * ④ 组顺序 = 快照中出现次序。</p>
     *
     * <p>{@code position_item_ids} = 该组**全部**（未被吸收的）部位行 id，**有序** —— 与 V92 的
     * {@code jsonb_agg(... ORDER BY ord)} 逐值一致（V92 里 {@code itemId} 恒非空 ⇒ 不存在 null 元素）。</p>
     */
    public static List<Group> windowGroups(List<Map<String, Object>> snapshot) {
        // 组内存在「可作主布的行」（有加工项且角色非配布边）的组键集合 —— V92 的 EXISTS 子查询
        Set<String> groupsWithMainRow = new LinkedHashSet<>();
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>) || isEdgeRow(entry)) {
                continue;
            }
            String groupKey = craftGroupKey(entry);
            if (groupKey != null) {
                groupsWithMainRow.add(groupKey);
            }
        }
        Map<String, List<String>> byGroup = new LinkedHashMap<>();
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>)) {
                continue;
            }
            String groupKey = craftGroupKey(entry);
            if (isEdgeRow(entry) && groupKey != null && groupsWithMainRow.contains(groupKey)) {
                continue; // 被吸收的配布边行（与实例化循环同口径）
            }
            if (groupKey == null) {
                continue; // 脏快照：无组键 ⇒ 不猜（`itemId` 是主键，正常路径恒非空）
            }
            byGroup.computeIfAbsent(groupKey, k -> new ArrayList<>()).add(str(entry.get("itemId")));
        }
        List<Group> groups = new ArrayList<>(byGroup.size());
        byGroup.forEach((key, itemIds) -> {
            List<String> parts = new ArrayList<>(itemIds.size());
            for (String itemId : itemIds) {
                if (itemId != null) {
                    parts.add(itemId);
                }
            }
            groups.add(new Group(key, parts));
        });
        return groups;
    }

    /** 是否「配布边」部件行（缺省角色视为主布 ⇒ 不是配布边，存量单兼容）。 */
    private static boolean isEdgeRow(Map<String, Object> entry) {
        return COMPONENT_ROLE_EDGE.equals(str(entry.get("componentRole")));
    }

    /** 绑组键：{@code craftLineId} 优先，缺省回落到本行 {@code itemId}（与 V92 的 COALESCE 同口径）。 */
    private static String craftGroupKey(Map<String, Object> entry) {
        String craftLineId = str(entry.get("craftLineId"));
        return craftLineId != null ? craftLineId : str(entry.get("itemId"));
    }

    /** 归一：`trim` 后空串 ⇒ null（与 V92 的 `NULLIF(btrim(x),'')` 同口径）。 */
    private static String str(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }
}
