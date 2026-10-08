package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperation;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

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
}
