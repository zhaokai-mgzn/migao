package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 质检记录（**成品帘级**）实体 —— issue #5652 的第一刀。
 * 对应表：quality_inspections（V157）。
 *
 * <p>🔴 <b>口径（用户 2026-10-16 逐字裁定）</b>：一行 = <b>一件成品帘</b>（{@code orderItemId}）
 * ——「是按成品帘来检查的」⇒ <b>不逐工序、不逐工序完工检</b>（本实体<b>没有</b>
 * {@code operationId} 字段，是有意不加）。录入者 = <b>独立质检员</b>
 * （{@code inspectorId} 由服务端从 {@code SecurityContext} 解，body 伪造不了）。</p>
 *
 * <p>🔴 <b>两套口径并存、互不覆盖</b>：{@link ProductionWorkLog} 是<b>数量事实</b>
 * （{@code qty} / {@code qualifiedQty} / {@code workType}），本实体是<b>质检判定</b>。
 * 本实体<b>不</b>重算报工数量、<b>不</b>改写任何报工行；报工侧也<b>不</b>读本表。
 * 质检<b>不参与计件</b>（返工/报废不计件是报工侧 {@code workType} 的既有口径）。</p>
 *
 * <p>无唯一约束是<b>有意</b>的：同一件成品帘允许多条（返工后重检 = 一次新的检验事实）；
 * 「当前判定」由读面按 {@code inspectedAt} 最新一条给出（见
 * {@link com.migao.admin.mapper.QualityCheckMapper#selectLatestByOrderItemIds}）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("quality_inspections")
public class QualityCheck {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 这张成品帘所属的加工单（服务端由订单解出，不由客户端送） */
    private String processingOrderId;

    /** 🔴 质检的唯一颗粒度：一件成品帘（{@code order_items.id}） */
    private String orderItemId;

    /** 成品帘展示名快照（读时从工序实例解；解不到为 {@code null} —— 缺值不渲染假数据） */
    private String positionName;

    /** 检验人 id（独立质检员；服务端从 {@code SecurityContext} 解） */
    private String inspectorId;

    private String inspectorName;

    /**
     * 检验人身份类别（V163，issue #7162）：{@code employee} 观星台员工 / {@code worker} 工人端。
     *
     * <p>为什么要单列：工人 session 与观星台员工是**两套 id 空间**（工人也会落 {@code users.id}，
     * 但登录与授权路径完全不同）⇒ 只靠 {@code inspector_id} 分不清「这条是谁录的」。
     * 既有行（全部来自观星台）默认 {@code employee}。</p>
     */
    private String inspectorKind;

    /** 质检三态：{@code pass} 合格 / {@code rework} 返工 / {@code scrap} 报废 */
    private String inspectionResult;

    /** 不合格原因：判定 ≠ {@code pass} 时必填（缺 ⇒ 服务层 422 具名报错） */
    private String reason;

    /** 检验时刻（业务时钟单点 {@code BusinessClock}，Asia/Shanghai） */
    private OffsetDateTime inspectedAt;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
