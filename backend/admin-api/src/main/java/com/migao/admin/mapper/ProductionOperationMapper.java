package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperation;

import java.time.OffsetDateTime;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * 生产工序库 Mapper（V49，issue #3995）
 */
@Mapper
public interface ProductionOperationMapper extends BaseMapper<ProductionOperation> {

    /**
     * 🔴 <b>改价的读-判-写闸（issue #6238）</b>：按 id 取工序行的<b>排他行锁</b>
     * （{@code FOR UPDATE}，锁持有到事务提交）。行不存在 / 已软删 ⇒ 不加锁（返回 {@code null}，
     * 由调用方随后的存在性校验报 404）。
     *
     * <h2>为什么需要它（病根）</h2>
     * {@code ProductionOperationCommandService#update} 改价的形态是
     * <b>读旧价 → 判「价变了吗」 → 条件追加一行版本账</b>。不加锁读时，两个并发请求都读到
     * <b>提交前快照</b>的旧价 ⇒ 都判「价变了」⇒ 各追加一行 ⇒ <b>同一次调价被重复记账</b>
     * （实测 N=4 并发同价提交 ⇒ 版本账 4 行；{@code production_operation_price_versions}
     * 除主键外<b>没有唯一约束</b>，DDL 兜不住）。
     *
     * <h2>为什么是行锁而不是 CAS + 409</h2>
     * 同价重复提交<b>不是冲突</b>：请求的意图（价 = 新价）在第一次提交后<b>已经达成</b>
     * ⇒ 正确语义是<b>幂等空操作</b>（返回成功），不是拒绝。行锁把同一工序的并发改价串行化到提交，
     * 后到者重读拿到的是前者<b>已提交</b>的值 ⇒ ① 同价重复提交退化为「价没变 ⇒ 不追加」；
     * ② 异价并发（A 改 200、B 改 300）则两次变更<b>各自成行</b>、{@code created_at} 顺序与提交顺序一致
     * ⇒「当前价 = 最新版本行」这条冻结契约在并发下仍成立（CAS 丢弃后写者会造成静默丢改动）。
     *
     * <h2>用法（顺序即语义）</h2>
     * <b>先 {@code lockById}、再 {@code selectById}</b>：锁后的那次普通 SELECT 在 READ COMMITTED 下
     * 读到的是<b>最新已提交</b>版本 ⇒ 「价是否真变了」的判断建立在库内事实上。
     * 顺序颠倒（先读后锁）等于没修。调用方必须在<b>事务内</b>调用（锁靠事务边界释放；
     * {@code ProductionOperationCommandService#update} 已声明 {@code @Transactional}）。
     */
    @Select("SELECT id FROM production_operations WHERE id = #{id} AND deleted = 0 FOR UPDATE")
    String lockById(@Param("id") String id);

    /**
     * 🔴 <b>「删除权」的原子闸：条件更新（CAS）</b>（issue #6936；与 #6928 的
     * {@code InboundOrderMapper#markCancelled} 同款）。
     *
     * <p><b>为什么必须有它</b>：{@code delete} / {@code deleteDetaching} 改前是
     * <b>check-then-act</b>（先读 {@code deleted==0} 判活、再摘格 / 级联软删 / 无条件写回）——
     * 判断与写入不在同一条语句上 ⇒ 并发下多个请求都读到提交前快照、都进了写侧
     * （实测 5 并发 ⇒ {@code [200,200,200,422,422]}，成功 3 次）。条件更新把判断与写入压进
     * <b>同一条语句</b>，PG 对命中行加行锁并持有到事务结束 ⇒ 后到者要么阻塞到前者提交、
     * 要么看到 0 行受影响。</p>
     *
     * <p><b>谓词三条缺一不可</b>：{@code id}（只动这一行）、{@code tenant_id}（手写 SQL 不走
     * 多租户拦截器的自动追加，跨租户可写 = 越权）、{@code deleted = 0}（已软删的行不得再被抢删除权
     * —— 手写 SQL 也不走 {@code @TableLogic} 的自动过滤）。<b>显式写列</b> {@code deleted = 1}
     * （issue #4608：{@code setDeleted(1); updateById(...)} 会被 MP 从 SET 子句里剔除 ⇒ 静默 no-op）
     * 并保住审计字段 {@code updated_at}（「谁在什么时候删的」的唯一证据）。</p>
     *
     * <p>闸必须落在<b>任何副作用之前</b>（摘格 / 级联软删）：这样落败方零副作用、fail-closed。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到删除权；{@code 0} = 已被并发请求删掉 / 行不存在 / 非本租户
     */
    @Update("UPDATE production_operations SET deleted = 1, updated_at = #{updatedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0")
    int claimDelete(@Param("id") String id,
                    @Param("tenantId") Long tenantId,
                    @Param("updatedAt") OffsetDateTime updatedAt);
}
