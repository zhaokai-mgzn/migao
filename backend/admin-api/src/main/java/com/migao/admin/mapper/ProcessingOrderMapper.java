package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingOrder;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 加工单 Mapper（issue #3340）
 *
 * <p>🔴 <b>手写 {@code @Select} 必须显式绑 MyBatis-Plus 的 autoResultMap</b>
 * （{@code @ResultMap("mybatis-plus_ProcessingOrder")}）：{@code @TableName(autoResultMap = true)}
 * 只对 BaseMapper 的内置方法生效 —— **手写 SQL 不绑就不走 {@code JacksonTypeHandler}** ⇒
 * {@code items_snapshot}（JSONB）以 **JSON 字符串**落到 {@code Object itemsSnapshot} 上 ⇒
 * 所有 {@code instanceof List} 判据静默为假。</p>
 *
 * <p><b>实测代价（issue #4865）</b>：{@code ProductionService.ensureSetsFor} 因此把**非空**快照判成空
 * ⇒ 套号分配整段跳过 ⇒ 部位码/短码**永不产出**（实测全库 {@code processing_set_part_tokens} 0 行）。</p>
 *
 * <p><b>同形态的历史事故</b>：{@code ProcessingOrderService.loadOrderItems} 的 javadoc 逐字记录过
 * issue #3340 的同一件事（{@code order_items.processing_info} 以 JSON 字符串返回 ⇒ buildSnapshot 恒空）
 * —— 当时的处置是**改调用方走 BaseMapper + 加 {@code instanceof String} 归一化兜底**，
 * 映射本身没修、也没有守卫 ⇒ 同一根因在 {@link #selectActiveByOrderId} 上原样复发。
 * 本单改为**修映射**（绑 resultMap），并把不变量钉在
 * {@code com.migao.admin.mapper.JacksonTypeHandlerMappingGuardTest}（真 MyBatis 映射级；注入一处违规即红）。</p>
 */
@Mapper
public interface ProcessingOrderMapper extends BaseMapper<ProcessingOrder> {

    /**
     * 订单当前的活跃加工单（非取消态，租户隔离由 TenantLineInnerInterceptor 注入）
     *
     * <p>⚠️ {@code @ResultMap} 是**判据的一部分**，不是可选优化（见类注释）。</p>
     */
    @ResultMap("mybatis-plus_ProcessingOrder")
    @Select("SELECT * FROM processing_orders WHERE order_id = #{orderId} AND tenant_id = #{tenantId} " +
            "AND deleted = 0 AND status IN ('generated','issued','in_processing','completed') LIMIT 1")
    ProcessingOrder selectActiveByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);

    /**
     * **批量**活跃加工单（issue #7582，报表中心订单毛利用）：把 N 次 {@link #selectActiveByOrderId} 压成 1 次。
     *
     * <p>🔴 状态白名单与单条版**逐字相同**（{@code generated/issued/in_processing/completed} + 未软删 + 同租户）——
     * 两处口径一旦不同，「单张订单页的毛利」与「报表里这一单」会算出两个加工成本，
     * 而那是同一份钱的两个读数（判据见 {@code OrderMarginBatchTest}）。</p>
     *
     * @param orderIds 非空集合（调用方保证；空集合渲染成 {@code IN ()} 是语法错误）
     */
    @ResultMap("mybatis-plus_ProcessingOrder")
    @Select("<script>SELECT * FROM processing_orders WHERE order_id IN "
            + "<foreach collection='orderIds' item='orderId' open='(' separator=',' close=')'>#{orderId}</foreach> "
            + "AND tenant_id = #{tenantId} AND deleted = 0 "
            + "AND status IN ('generated','issued','in_processing','completed')</script>")
    java.util.List<ProcessingOrder> selectActiveByOrderIds(
            @Param("orderIds") java.util.Collection<String> orderIds, @Param("tenantId") Long tenantId);

    /**
     * 按加工单号/订单号/订单UUID 解析加工单（租户隔离）
     *
     * <p>⚠️ 与 {@link #selectActiveByOrderId} 同款：{@code po.*} 同样打 {@code items_snapshot}，
     * 不绑 resultMap 就同样静默返回字符串（同一文件两处，缺一不可）。</p>
     */
    @ResultMap("mybatis-plus_ProcessingOrder")
    @Select("SELECT po.* FROM processing_orders po " +
            "LEFT JOIN orders o ON po.order_id = o.id " +
            "WHERE po.tenant_id = #{tenantId} AND po.deleted = 0 " +
            "AND (po.processing_order_no = #{keyword} OR o.order_no = #{keyword} OR po.order_id = #{keyword}) " +
            "ORDER BY po.created_at DESC LIMIT 10")
    List<ProcessingOrder> selectByKeyword(@Param("keyword") String keyword, @Param("tenantId") Long tenantId);

    /**
     * 这批订单里**已有活跃加工单**的那些（issue #5169 待派池的排除面）。
     *
     * <p>活跃口径与 {@link #selectActiveByOrderId} / {@code uk_processing_orders_active}
     * **逐字相同**（非取消态 + 未软删）—— 池 = 「已确认支付 **且不在本方法结果里**」的订单，
     * 少一个口径就会出现「池里看得见、派的时候被唯一键拒掉」这种自相矛盾的读面。</p>
     *
     * <p>返回**标量 order_id**，故不需要 {@code @ResultMap}（那个注解是给
     * {@code items_snapshot} 这个 JSONB 列用的，见类注释）；本方法一个 JSONB 列都不碰。</p>
     *
     * @param orderIds 非空集合（调用方保证；空集合会被渲染成 {@code IN ()} 而语法错误）
     */
    @Select("<script>SELECT DISTINCT order_id FROM processing_orders WHERE tenant_id = #{tenantId} "
            + "AND deleted = 0 AND status IN ('generated','issued','in_processing','completed') "
            + "AND order_id IN <foreach item='id' collection='orderIds' open='(' separator=',' close=')'>"
            + "#{id}</foreach></script>")
    List<String> selectActiveOrderIds(@Param("tenantId") Long tenantId,
                                      @Param("orderIds") java.util.Collection<String> orderIds);

    /**
     * 订单是否已有完成的加工单（shipped 守卫用）
     */
    @Select("SELECT COUNT(1) FROM processing_orders WHERE order_id = #{orderId} AND tenant_id = #{tenantId} " +
            "AND deleted = 0 AND status = 'completed'")
    long countCompletedByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);

    /**
     * 把**活跃**加工单原子置 completed —— 生产报工「完工」的唯一写路径（issue #4117）。
     *
     * 生产完工 = **加工单**加工完成，**不是**订单状态推进：订单状态机
     * （OrderService.STATUS_TRANSITIONS）不设 producing→completed，且 completed 是终态
     * ⇒ 旧实现用裸 UpdateWrapper 直写订单 completed，会让含加工项订单**既发不了货也回不去**
     * （发货守卫读的正是本表 {@link #countCompletedByOrderId}，而 shipOrderIfApplicable
     * 只在订单 confirmed/producing 时流转）⇒ 把加工单置 completed、订单留在 producing，
     * 发货链才通。
     *
     * 条件 = 活跃集（与 {@link #selectActiveByOrderId} 同口径，排除 cancelled）：
     * 并发取消的加工单不会被复活；已是 completed 时不覆盖首次完工时间（重复报工幂等）。
     */
    @Update("UPDATE processing_orders SET status = 'completed', " +
            "completed_at = COALESCE(completed_at, #{completedAt}), updated_at = #{completedAt} " +
            "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 " +
            "AND status IN ('generated','issued','in_processing','completed')")
    int markCompletedIfActive(@Param("id") String id, @Param("tenantId") Long tenantId,
                              @Param("completedAt") OffsetDateTime completedAt);

    /**
     * 首工序（`is_start_marker`）**报满** ⇒ 加工单 `issued → in_processing` + 落 `in_processing_at`
     * —— 「生产开始」的**唯一**自动写路径（issue #4695 / 设计 D13）。
     *
     * <p>没它之前：`is_start_marker` 从工序库落进实例、读面也带得出来，**却没有任何消费者**
     * ⇒ 首工序报满后加工单仍是 `issued`，在产单被当成「未开工」。</p>
     *
     * <p>🔴 <b>为什么谓词是参数而不是字面量</b>：合法的起始态**只有状态机说了算**
     * （{@code ProcessingOrderService.STATUS_TRANSITIONS}）。调用方先问
     * {@code ProcessingOrderService.allowsTransition(from, "in_processing")}，再把**那个被授权的起始态**
     * 传进来做 CAS 谓词 ⇒ 迁移表**只有一份**（写死 `status = 'issued'` 就是第二份投影，迟早漂移）；
     * 同时本次写只在行**仍是那个态**时命中 ⇒ 不裸 UPDATE 绕过状态机（#4117 的教训：绕过 ⇒ 订单
     * 既发不了货也回不去）。`generated` / `cancelled` / `completed` / 已是 `in_processing` ⇒ 0 行。</p>
     *
     * <p><b>幂等（重复报工 / 并发报工）</b>：① 谓词不成立 ⇒ 0 行（并发双写里只有一个能命中）；
     * ② {@code COALESCE(in_processing_at, …)} ⇒ 首次开工时刻**不被改写**（与
     * {@link #markCompletedIfActive} 同款写法）。返回影响行数（0 ⇒ 本次没有发生迁移）。</p>
     *
     * <p>手工入口一字未动：{@code ProcessingOrderService.updateStatus} 的 `action = "start"`
     * 仍是同一条迁移的手工路径（存量单补开工 / 兜底），语义写在那个方法的 javadoc 里。</p>
     */
    @Update("UPDATE processing_orders SET status = 'in_processing', " +
            "in_processing_at = COALESCE(in_processing_at, #{inProcessingAt}), " +
            "updated_at = #{inProcessingAt} " +
            "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 " +
            "AND status = #{fromStatus}")
    int markInProcessingIfFrom(@Param("id") String id, @Param("tenantId") Long tenantId,
                               @Param("fromStatus") String fromStatus,
                               @Param("inProcessingAt") OffsetDateTime inProcessingAt);

    /**
     * 返工改记后**重开已完工的加工单**（issue #7860）：{@code completed → in_processing} + 清 {@code completed_at}。
     *
     * <p>🔴 为什么需要它：工人报返工会把某一笔报工退回「没做出来」⇒ {@code allInstancesDone} 不再成立；
     * 若这时加工单还停在 {@code completed}，就会出现「单子已完工、工序却没做满」的自相矛盾读数
     * （进度条 / 完工判据 / 发货守卫各说一套）。</p>
     *
     * <p>⚠️ 这是「{@code completed} 是终态」**唯一**的反向路径，刻意不从
     * {@code ProcessingOrderService.STATUS_TRANSITIONS} 走：那张表管的是**人工状态迁移**，
     * 而这里是「同一件事实被改记」的补偿动作 —— 谓词死锁在 {@code status = 'completed'}，
     * 谁先改记谁重开，重复/并发只生效一次（影响行数 0 即已重开过，不作失败）。</p>
     */
    @Update("UPDATE processing_orders SET status = 'in_processing', completed_at = NULL, "
            + "updated_at = #{updatedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
            + "AND status = 'completed'")
    int reopenCompletedIfAny(@Param("id") String id, @Param("tenantId") Long tenantId,
                             @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 加工单状态迁移的**唯一条件更新写面**（issue #6954）：手工入口
     * {@code ProcessingOrderService.updateStatus} 的四条迁移（issue / start / complete / cancel）
     * 与订单取消联动作废 {@code OrderService.cancelOrder} 都走它。
     *
     * <p>🔴 <b>为什么不能是「先读 status 判、再 {@code updateById} 写」</b>（本单的病根）：
     * {@code updateById} 的 WHERE 只有主键 ⇒ 谓词缺位 ⇒ **两个相反迁移可以双双成功**，终态由后写者决定。
     * 实测形态：同一张加工单并发 {@code issue} + {@code cancel} ⇒ 两个请求都 200，落库态由竞态决定
     * （{@code STATUS_TRANSITIONS} 里 {@code issued} 与 {@code cancelled} 互不可达 ⇒ 终态**必然**自相矛盾）；
     * 订单作废 × 加工单开工 ⇒ 出现「**订单 cancelled + 加工单 issued**」（订单已废、单还在产）。
     * 条件更新的判断与写入是同一条语句，PG 对命中行加行锁并持有到事务结束 ⇒ 后到者要么阻塞到前者提交、
     * 要么看到 0 行受影响。形态与同文件既有的 {@link #markCompletedIfActive} /
     * {@link #markInProcessingIfFrom} <b>逐字同款</b>（本文件早有 CAS，只是手工入口没走）。</p>
     *
     * <p>🔴 <b>为什么 {@code fromStatus} 是参数而不是字面量</b>：合法的起始态**只有状态机说了算**
     * （{@code ProcessingOrderService.STATUS_TRANSITIONS}）。调用方先过状态机、再把**那个被授权的起始态**
     * 传进来做 CAS 谓词 ⇒ 迁移表**只有一份**（写死就是第二份投影，迟早漂移）；同时本次写只在行**仍是那个态**
     * 时命中 ⇒ 不裸 UPDATE 绕过状态机。</p>
     *
     * <p>🔴 <b>为什么每个动作只 SET 自己那一列</b>：{@code issue} 只写 {@code issued_at} /
     * {@code processor} / {@code expected_delivery_date}，{@code cancel} 只写 {@code cancelled_at} /
     * {@code cancelled_reason} —— 用 {@code <if>} 包住 ⇒ 不把本次不负责的列（如发加工时把
     * {@code cancelled_reason} 写成 null）一并覆写。这同时让 {@code cancel} 只回补、不误清发加工信息
     * （发加工信息是**加工方拿到的那张纸**的内容）。</p>
     *
     * <p><b>幂等（重复请求 / 并发请求）</b>：谓词不成立 ⇒ 0 行（并发双写里只有一个能命中）；
     * 返回影响行数（0 ⇒ 本次没有发生迁移，调用方按 409 处置并回读真实状态）。</p>
     *
     * @param fromStatus 状态机**授权**的当前态（{@code ProcessingOrderService.STATUS_TRANSITIONS} 的前驱）
     * @return 受影响行数（0 = 该行不存在 / 已软删 / 跨租户 / 状态已被并发改动）
     */
    @Update("<script>UPDATE processing_orders SET status = #{targetStatus}, updated_at = #{now}"
            + "<if test='issuedAt != null'>, issued_at = #{issuedAt}</if>"
            + "<if test='processor != null'>, processor = #{processor}</if>"
            + "<if test='expectedDeliveryDate != null'>, expected_delivery_date = #{expectedDeliveryDate}</if>"
            + "<if test='inProcessingAt != null'>, in_processing_at = #{inProcessingAt}</if>"
            + "<if test='completedAt != null'>, completed_at = #{completedAt}</if>"
            + "<if test='cancelledAt != null'>, cancelled_at = #{cancelledAt}</if>"
            + "<if test='cancelledReason != null'>, cancelled_reason = #{cancelledReason}</if>"
            + " WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0"
            + " AND status = #{fromStatus}</script>")
    int markStatusIfFrom(@Param("id") String id, @Param("tenantId") Long tenantId,
                         @Param("fromStatus") String fromStatus, @Param("targetStatus") String targetStatus,
                         @Param("issuedAt") OffsetDateTime issuedAt, @Param("processor") String processor,
                         @Param("expectedDeliveryDate") java.time.LocalDate expectedDeliveryDate,
                         @Param("inProcessingAt") OffsetDateTime inProcessingAt,
                         @Param("completedAt") OffsetDateTime completedAt,
                         @Param("cancelledAt") OffsetDateTime cancelledAt,
                         @Param("cancelledReason") String cancelledReason,
                         @Param("now") OffsetDateTime now);

    /**
     * 打印计数原子递增（issue #4202 边角修复）—— {@code print_count} 此前**零 UPDATE 写方**：
     * 真值源 §1 要求加工单打印物「记录打印次数」，而全仓只有建单时的 {@code printCount(0)}
     * 与响应映射 ⇒ 打印次数在数据层永不可观测。
     *
     * <p>SQL 内自增（{@code COALESCE(print_count,0)+1}）而不是「读出来 +1 再写回」：
     * 同一张卡可能被多人/多标签页同时打印，读改写会丢计数。返回影响行数
     * （0 = 加工单不存在/跨租户/已软删 ⇒ 调用方 fail-closed）。</p>
     */
    @Update("UPDATE processing_orders SET print_count = COALESCE(print_count, 0) + 1, " +
            "updated_at = #{updatedAt} " +
            "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0")
    int incrementPrintCount(@Param("id") String id, @Param("tenantId") Long tenantId,
                            @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 命中该短码的**本租户**加工单（issue #6867 / B1）：分配查重与「同一张纸」判定的**唯一读面**。
     *
     * <p>带 {@code tenant_id = #{tenantId}}：分配与判定都发生在**已认证请求内**（{@code TenantContext}
     * 有值），租户隔离由 SQL **显式**持有 ⇒ 不依赖拦截器是否挂上（同
     * {@code ProcessingSetPartTokenMapper.insertIgnoreConflict} 的显式租户列纪律）。</p>
     *
     * <p>⚠️ 与「{@code /o/{短码}} 跨租户解析」是**两件事**：那个入口没有租户上下文（由短码本身解出
     * 租户），归 B2；本方法的租户谓词是**刻意的**，不是遗漏。短码的**跨租户**唯一性由部分唯一索引
     * {@code uk_processing_orders_short_code} 兜底（列级、与租户无关）。</p>
     *
     * <p>不带 {@code short_code IS NOT NULL} 过滤：未知 ⇒ {@code null}（调用方据此判定「可用」）。</p>
     */
    @ResultMap("mybatis-plus_ProcessingOrder")
    @Select("SELECT * FROM processing_orders WHERE tenant_id = #{tenantId} "
            + "AND short_code = #{shortCode} AND deleted = 0 LIMIT 1")
    ProcessingOrder selectByShortCode(@Param("shortCode") String shortCode, @Param("tenantId") Long tenantId);

    /**
     * 短码 ⇒ **跨租户**解析加工单（issue #6867 / B2）：公开入口 {@code GET /o/{短码}} 的唯一读面。
     *
     * <p>🔴 {@code @InterceptorIgnore(tenantLine = "true")} 是**必须的**（不是优化）：
     * {@code /o/{短码}} 是公开入口（无 JWT / 无工人 session）⇒ {@code TenantContext} 为空 ⇒
     * 多租户拦截器会抛 {@code Tenant context not initialized} ⇒ 纸上的码恒 500。
     * 短码本身**全局唯一**（部分唯一索引 {@code uk_processing_orders_short_code}，列级、跨租户）
     * ⇒ 跨租户查询最多命中一行，租户由短码解出（设计 §11.6）。同款手法见
     * {@code ProcessingSetPartTokenMapper.selectByShortCode} 与 {@code UserMapper} 的跨租户手机号查询。</p>
     *
     * <p>⚠️ 与上面的 {@link #selectByShortCode}（带 {@code tenantId}）是**两件事**，不要互相替代：
     * 那个的租户谓词是**刻意的**（分配期查重与「同一张纸」判定都在已认证请求内，不带 tenant_id 就是越权面）；
     * 本方法的跨租户是**刻意的**（公开入口没有租户上下文）。谁把两者合并成一个，都会打破另一半的判据
     * （{@code ProcessingOrderShortCodeMapperTest#selectByShortCodeStaysInsideTheTenant} 与
     * {@code ProcessingOrderShortLinkControllerTest}）。</p>
     *
     * <p><b>不带</b> {@code qr_token IS NOT NULL} 过滤：撤销 = 置 NULL（设计 §11.6 / §1.3.1）⇒
     * 调用方要能区分「短码不存在」（404）与「这张纸已作废」（410），静默回落成 404 会把撤销说成「没这个码」。</p>
     *
     * <p>⚠️ {@code @ResultMap} 与同文件其它手写 {@code @Select} 同因（见类注释）：
     * {@code po.*} 打 {@code items_snapshot}（JSONB），不绑 resultMap 就静默返回字符串。</p>
     *
     * @param shortCode 归一化后的短码（8 位 Crockford Base32）
     * @return 命中行（{@code qrToken} 为 {@code null} = 已撤销）；未知 ⇒ {@code null}
     */
    @InterceptorIgnore(tenantLine = "true")
    @ResultMap("mybatis-plus_ProcessingOrder")
    @Select("SELECT * FROM processing_orders WHERE short_code = #{shortCode} AND deleted = 0 LIMIT 1")
    ProcessingOrder selectByShortCodeGlobal(@Param("shortCode") String shortCode);

    /**
     * 给**已存在**的加工单补短码（issue #6867 / B1；幂等 = 「只补 {@code NULL}」）。
     *
     * <p>🔴 三条红线（逐条落在 SQL 上，与
     * {@code ProcessingSetPartTokenMapper.fillMissingShortCode} 逐字同款）：
     * ① {@code AND short_code IS NULL} ⇒ <b>已有短码的行一字不动</b>（已打印的纸不作废）；
     * ② 只写 {@code short_code} + {@code updated_at} ⇒ <b>不碰 {@code qr_token}</b>
     * （撤销状态只有一处）、不碰任何单价/计件列（不追溯）；
     * ③ {@code deleted = 0} ⇒ 不动软删行。</p>
     *
     * <p>为什么不用 {@code updateById}：那是「整行覆盖」语义 —— 并发下两个请求各拿到同一个
     * {@code po}（{@code short_code} 都为空）、各自分配再回写 ⇒ 后写者**覆盖**前者，
     * 而前者那张纸已经打印出去了。条件更新把「只补空」钉在 SQL 上，不看调用方记不记得。</p>
     *
     * @return 受影响行数（0 = 该行不存在 / 已有短码 / 已软删 ⇒ 调用方无需重试）
     */
    @Update("UPDATE processing_orders SET short_code = #{shortCode}, updated_at = #{updatedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 AND short_code IS NULL")
    int fillMissingShortCode(@Param("id") String id, @Param("tenantId") Long tenantId,
                             @Param("shortCode") String shortCode,
                             @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 撤销二维码 token（issue #4202）：置空 {@code qr_token} ⇒ 已打印的码立即失效
     * （扫码解析走 {@code qr_token} 形态，置空后解析不到订单 ⇒ 报工 404），
     * 再次实例化时由 {@code ProductionService.ensureQrToken} 重新生成。
     *
     * <p>置 NULL 而不是换一个新 token：撤销的语义是「这张纸作废」，不是「静默换一张纸」——
     * 换 token 会让工人手里的旧码解析失败但页面/接口仍显示有码，谁也不知道该重新打印。</p>
     *
     * <p>🔴 <b>不碰 {@code short_code}</b>（issue #6867；设计
     * {@code docs/design/worker-h5-scan-and-report.md} §11.6 逐字复用 §1.3.1）：短码是「哪一张纸」，
     * 撤销只作废这张纸的**当前 token**（{@code /o/{短码}} 见 token 为空 ⇒ 410 Gone，那一跳是 B2）。
     * 一并清短码 ⇒ 已打印的纸**永久成为废纸**（换域名/路径都不废纸这件事正是短码存在的理由）。</p>
     */
    @Update("UPDATE processing_orders SET qr_token = NULL, updated_at = #{updatedAt} " +
            "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0")
    int revokeQrToken(@Param("id") String id, @Param("tenantId") Long tenantId,
                      @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 给**还没有码**的加工单补 {@code qr_token}（issue #6955）—— 与
     * {@link #fillMissingShortCode} / {@code ProcessingSetPartTokenMapper.fillMissingToken}
     * <b>逐字同款</b>的「只补缺列」条件更新。
     *
     * <p>🔴 <b>为什么换掉 {@code updateById(builder().id().qrToken().build())}</b>（本单扫出的同族形态）：
     * 那条路的 SET 子句由 <b>实体非 null 字段</b>决定 ⇒ 除 {@code qr_token} 外的列一个都不进 SET。
     * 今天恰好「不写 = 不动」对多数列成立（MyBatis-Plus 默认 {@code NOT_NULL} 策略），但
     * <b>状态迁移权同样不在这条路上</b>：本次调用的语义是「只补码」，而整实体写面的语义是
     * 「这份内存快照就是该行」—— 两者只在「快照恰好新鲜」时等价。条件更新把「只补码」钉在 SQL 上，
     * 不看调用方记不记得（同 {@link #fillMissingShortCode} 的理由）。</p>
     *
     * <p>谓词 = {@code id + tenant_id + deleted = 0}；{@code COALESCE(qr_token, #{qrToken})} ⇒
     * <b>已有码的行一字不动</b>（已打印的纸不作废；并发双写时两次都命中、但第二次写的是同一个既有值
     * ⇒ 与 {@code markInProcessingIfFrom} 的「首次时刻不被改写」同款幂等）。</p>
     */
    @Update("UPDATE processing_orders SET qr_token = COALESCE(qr_token, #{qrToken}), "
            + "updated_at = COALESCE(updated_at, #{updatedAt}) "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0")
    int fillMissingQrToken(@Param("id") String id, @Param("tenantId") Long tenantId,
                           @Param("qrToken") String qrToken, @Param("updatedAt") OffsetDateTime updatedAt);
}
