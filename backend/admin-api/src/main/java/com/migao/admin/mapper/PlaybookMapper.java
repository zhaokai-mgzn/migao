package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.Playbook;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * 口径卡 Mapper（issue #8175）。
 *
 * <p><b>状态迁移一律 CAS（条件更新 + 按影响行数判归属）</b>：审核是两个人可能同时点的动作。
 * 若写成「先 select 出 draft → 应用层判 → updateById（WHERE 仅主键）」，读与写之间没有互斥
 * ⇒ 并发双审核会让两条路径都"成功"，审计里出现两条互相矛盾的迁移记录。
 * 这里把前态写进 WHERE：影响行数 0 = 不存在 / 跨租户 / 已被别人处置过。</p>
 *
 * <p>谓词里<b>显式写 {@code tenant_id}</b>（不依赖租户拦截器在场）—— 口径会直接进 system prompt，
 * 越权读等于把别家的经营规则灌进本家对话。</p>
 */
@Mapper
public interface PlaybookMapper extends BaseMapper<Playbook> {

    /** draft → active（审核通过）。 */
    @Update("UPDATE playbooks SET state = 'active', activated_at = #{now}, "
            + "reviewed_by = #{reviewedBy}, updated_at = #{now} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND state = 'draft'")
    int activateIfDraft(@Param("id") String id,
                        @Param("tenantId") Long tenantId,
                        @Param("reviewedBy") String reviewedBy,
                        @Param("now") OffsetDateTime now);

    /** active → retired（退役）。 */
    @Update("UPDATE playbooks SET state = 'retired', retired_at = #{now}, "
            + "reviewed_by = #{reviewedBy}, updated_at = #{now} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND state = 'active'")
    int retireIfActive(@Param("id") String id,
                       @Param("tenantId") Long tenantId,
                       @Param("reviewedBy") String reviewedBy,
                       @Param("now") OffsetDateTime now);
}
