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
 * 口径卡实体（issue #8175 一期）。
 * 对应表：{@code playbooks}（迁移 V210）。
 *
 * <p><b>与 {@code user_memories} 的分工</b>：那张表的主语是**顾客**（个人画像，
 * #2815 对 mibao 关闭，upsert 后写覆盖先写）；本表的主语是**企业** —— 一条口径是
 * 「谁在什么时候纠正过、审核过没有、退役了没有」的工件。</p>
 *
 * <p><b>状态机</b>（唯一合法迁移，迁移语句是 CAS）：
 * {@code draft --activate--> active --retire--> retired}。
 * 只有 {@code active} 会出现在任何出口（prompt 片段 / 生成的用例）；
 * {@code draft} 与 {@code retired} 一条都不许露头（判据见
 * {@code backend/ai-agent-service/tests/test_prompt.py}、{@code test_store.py}）。</p>
 *
 * <p><b>{@code triggerJson} / {@code counterJson} 是条件语言 JSON</b>，不是自然语言。
 * 自由文本 / 未知算子 / 空条件 ⇒ 写面直接 422（{@code PlaybookConditionValidator}），
 * 读面再 fail-closed 一次（{@code backend/ai-agent-service/app/playbook/condition.py}）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("playbooks")
public class Playbook {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** tenant = 全企业；role = 某个岗位（此时 {@link #scopeRole} 必填） */
    private String scope;

    private String scopeRole;

    /** 触发条件（条件语言 JSON 对象，**不是**自然语言） */
    private String triggerJson;

    /** 正解：审核过的一句话口径（会作为 prompt 片段下发 ⇒ 读面必须消毒） */
    private String correctText;

    /** 反例（同一套条件语言）：命中即「本卡不适用」 */
    private String counterJson;

    private String sourceSessionId;

    private Integer sourceTurn;

    private Integer hits;

    /** draft / active / retired（DB 侧另有 CHECK 约束兜底） */
    private String state;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private OffsetDateTime activatedAt;

    private OffsetDateTime retiredAt;

    private String reviewedBy;

    /**
     * 冲突标记（issue #8175 P1；迁移 V211）：非 NULL = 本租户内还有同 key（scope + trigger）
     * 但正解不同的行 ⇒ 两条**并存**、待人工裁定。
     *
     * <p>它由落库面（{@code backend/ai-agent-service/app/playbook/ingest.py}）计算；
     * 「同一条口径的两个说法」不许用后写覆盖先写来消解 —— 那会让被冲掉的那条**无痕消失**。
     * 审核队列按这一列分组展示，因此它必须是**可读的实体字段**（写进库却没人读的列 = 假功能）。</p>
     */
    private String conflictKey;
}
