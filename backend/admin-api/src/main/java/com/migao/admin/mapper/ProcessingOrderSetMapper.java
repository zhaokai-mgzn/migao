package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingOrderSet;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 套号载体 Mapper（V92，切片 ⓪ / issue #4698）：一单 × 一套 = 一行。
 * 切片 ① 只读（解析时按 {@code set_id} 取套号做归属校验与响应）；
 * 切片 ⓪.5（issue #4789）新增**唯一写方** {@link #insertIgnoreConflict}。
 *
 * <p>🔴 手写 {@code @Select} 必须显式绑 autoResultMap（口径与判据见
 * {@code ProcessingOrderMapper} 类注释 / {@code JacksonTypeHandlerMappingGuardTest}）——
 * {@code ProcessingOrderSet.positionItemIds} 是 JSONB（JacksonTypeHandler）。</p>
 */
@Mapper
public interface ProcessingOrderSetMapper extends BaseMapper<ProcessingOrderSet> {

    /**
     * 锁住该加工单的套号分配（`SELECT … FOR UPDATE`，**必须在分配事务内**）。
     *
     * <p><b>为什么用悲观锁而不是「撞唯一键再重试」</b>（设计 §2.4 规则 3 允许的两种实现）：
     * 分配发生在 {@code ProcessingOrderService.generateOne} 的**外层事务内**（加工单行刚插入、
     * 尚未提交）⇒ 任何 {@code REQUIRES_NEW} 的分配事务都会**阻塞在父事务持有的行锁**上直到父事务结束
     * —— 那不是并发保护，是**自己把自己锁死**（新单首实例化必走这条路）。且 PostgreSQL 里语句失败会把
     * 当前事务置 aborted（25P02）⇒ 同一事务内「撞唯一键后重读 MAX 重试」根本不成立。
     * ⇒ 选**悲观锁**：并发请求在 {@code FOR UPDATE} 上串行，读到的 MAX 必然是最新值。
     * 唯一键 {@code uk_processing_order_sets_index} 仍在库层兜底（V92 建）。</p>
     *
     * <p>⚠️ 锁**该单的已有套行**（不是加工单行）：分配语义的作用域就是「该单的号池」，
     * 且不依赖 {@code processing_orders} 的列形态（该表的读取口径不因本单而变）。</p>
     *
     * <p>🔴 <b>{@code @InterceptorIgnore(tenantLine = "true")} 是必须的（issue #4865 实测）</b>：
     * 本语句同时含 {@code ORDER BY} 与 {@code FOR UPDATE}，多租户拦截器会把 SQL 交给 JSqlParser
     * **解析再序列化**（并追加 {@code AND tenant_id = ?}），而该往返把 {@code FOR UPDATE} 重排到
     * {@code ORDER BY} **之前** ⇒ 实际执行的是
     * {@code … AND deleted = 0 AND tenant_id = 1 FOR UPDATE ORDER BY set_index}
     * ⇒ PG 报 {@code 语法错误 在 "ORDER" 或附近的} ⇒ 生成/实例化 500。</p>
     *
     * <p>这个缺陷此前被 #4865 的**上游缺陷**掩盖（快照反序列化坏 ⇒ {@code ensureSetsFor} 在读快照时
     * 就 return 了，根本走不到分配器）；修好映射后它立刻显形。禁用该拦截器**不削弱租户隔离**：
     * WHERE 里的 {@code tenant_id = #{tenantId}} 是**显式**条件（拦截器追加的那一份是冗余的），
     * 与 {@code ProcessingSetPartTokenMapper.selectByShortCode} 的处置同款。</p>
     *
     * @return 被锁住的套行（首次分配 ⇒ 空集，此时锁的是该单号池的**间隙**）
     */
    @ResultMap("mybatis-plus_ProcessingOrderSet")
    @InterceptorIgnore(tenantLine = "true")
    @Select("""
            SELECT id, tenant_id, processing_order_id, set_index, set_no, craft_line_id, deleted
              FROM processing_order_sets
             WHERE tenant_id = #{tenantId}
               AND processing_order_id = #{processingOrderId}
               AND deleted = 0
             ORDER BY set_index
               FOR UPDATE
            """)
    List<ProcessingOrderSet> lockSetsOfOrder(@Param("tenantId") Long tenantId,
                                             @Param("processingOrderId") String processingOrderId);

    /**
     * 插入套行，撞 `set_index` 唯一键则**不插**（幂等 + 并发兜底，设计 §2.4 规则 3）。
     *
     * <p>⚠️ {@code ON CONFLICT} 的目标必须带**索引谓词** {@code WHERE deleted = 0}：V92 的
     * {@code uk_processing_order_sets_index} 是**部分**唯一索引，PG 的冲突推断要求谓词匹配。
     * 已在本地 PG 16 上实测：表名形态（本方法）✅；{@code ON CONFLICT ON CONSTRAINT} 形态 ❌
     * （部分唯一索引不是 constraint，报 "constraint … does not exist"）。</p>
     *
     * <p>列清单显式（issue #4608 纪律）；{@code position_item_ids} 显式 {@code ::jsonb}
     * （与 V92 回填同形态）。</p>
     */
    @Insert("""
            INSERT INTO processing_order_sets
                (id, tenant_id, processing_order_id, set_index, set_no, craft_line_id,
                 position_item_ids, created_at, updated_at, deleted)
            VALUES (#{s.id}, #{s.tenantId}, #{s.processingOrderId}, #{s.setIndex}, #{s.setNo},
                    #{s.craftLineId}, CAST(#{s.positionItemIdsJson} AS jsonb),
                    #{s.createdAt}, #{s.updatedAt}, #{s.deleted})
            ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING
            """)
    int insertIgnoreConflict(@Param("s") ProcessingOrderSetRow s);

    /**
     * 插入用的行（{@code position_item_ids} 以**已序列化的 JSON 文本**传入 —— JSONB 的
     * typeHandler 在 `@Insert` 里不会自动生效，显式文本 + {@code CAST(… AS jsonb)} 更直白）。
     */
    record ProcessingOrderSetRow(String id, Long tenantId, String processingOrderId, Integer setIndex,
                                 String setNo, String craftLineId, String positionItemIdsJson,
                                 java.time.OffsetDateTime createdAt, java.time.OffsetDateTime updatedAt,
                                 Integer deleted) {
    }
}
