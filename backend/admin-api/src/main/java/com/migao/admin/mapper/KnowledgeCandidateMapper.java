package com.migao.admin.mapper;

import com.migao.admin.entity.KnowledgeCandidate;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * 知识提炼候选Mapper接口（LLM WIKI 板块，issue #3051）
 * 标准 CRUD 由 TenantLineInnerInterceptor 自动注入租户过滤。
 */
@Mapper
public interface KnowledgeCandidateMapper extends BaseMapper<KnowledgeCandidate> {

    /**
     * 抢占候选的「处置权」= 条件更新（CAS，issue #6962 P5-②）：采纳 / 编辑后采纳 / 拒绝三条路径
     * 共用这一条语句，按<b>影响行数</b>判归属。
     *
     * <p><b>为什么不是 {@code updateById}</b>：修前三条路径都是「{@code getOwned} 读出 {@code pending}
     * → 应用层判 → 整实体 {@code updateById}（WHERE 仅主键）」，读判与写之间没有互斥 ⇒ 并发双采纳
     * <b>各插一张卡</b>（实测 2 张）；「采纳 × 拒绝」并发则两个都成功、终态由后写者决定。</p>
     *
     * <p><b>谓词</b>：{@code id} + {@code tenant_id}（显式租户列纪律，不依赖拦截器在场）+
     * {@code status = 'pending'}。⚠️ 本表<b>没有 {@code deleted} 列</b>（{@code db/init/schema.sql}
     * 自证：{@code knowledge_candidates} 的列止于 {@code reviewed_by}）⇒ 谓词里<b>不得</b>写
     * {@code deleted = 0}（写了就是列不存在 ⇒ SQL 报错）。软删语义在本表由 {@code status} 承担。</p>
     *
     * <p>{@code statusNote} 只在 {@code note} 非 {@code null} 时写（采纳路径不动拒绝原因 ——
     * 与修前 {@code updateById} 整行回写时 {@code statusNote} 保持原值同口径）。</p>
     *
     * @return 受影响行数（{@code 0} = 不存在 / 跨租户 / 已被他人处置过）
     */
    @Update("<script>UPDATE knowledge_candidates SET status = #{status}, "
            + "status_note = <choose><when test='note != null'>#{note}</when>"
            + "<otherwise>status_note</otherwise></choose>, "
            + "reviewed_by = #{reviewedBy}, reviewed_at = #{reviewedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'pending'</script>")
    int markReviewedIfPending(@Param("id") String id, @Param("tenantId") Long tenantId,
                              @Param("status") String status, @Param("note") String note,
                              @Param("reviewedBy") String reviewedBy,
                              @Param("reviewedAt") OffsetDateTime reviewedAt);
}
