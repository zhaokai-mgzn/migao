// case_ids: PG-074

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 🔴 并发判据（issue #6936）：{@code DELETE /api/admin/production/operations/{id}/detach-and-delete}
 * 的「一键摘格 + 删工序」写面在并发下必须 <b>exactly-once</b>（至多一个赢家）。
 *
 * <h2>缺陷形态（独立验收复现，证据 <code>acceptance/2026-10-14/line1-worker-config/out/batch-writeface-sweep/E4-detach-concurrent.json</code>）</h2>
 * 并发 5 次同一工序 ⇒ HTTP <b>{@code [200,200,200,422,422]}</b>（成功 3 次；应至多 1 次）。
 * 终态正确（{@code deleted=1}、无半完成）<b>不是</b>本单的判据 —— 本单的判据是
 * <b>并发语义</b>：读-判-写无 CAS ⇒ 多个请求都进了写侧。病根 = {@link ProductionOperationCommandService#deleteDetaching}
 * 的「先读 {@code op.deleted==0} 判活、后写」是 <b>check-then-act</b>：判断与写入不在同一条语句上，
 * PG 层没有任何互斥；三个请求都读到 {@code deleted=0} ⇒ 都去摘格/级联软删，只有一部分在
 * 级联阶段撞上「行已被软删」才 422（剩下两个 200 = 多赢家）。
 *
 * <h2>与 issue #6928 同族（照它的形态做）</h2>
 * {@code InboundOrderService#cancel} 修前的形态与这里逐字同源：状态迁移写面用无谓词
 * {@code updateById}（WHERE 仅主键）⇒ 与另一写面不互斥。修法 = <b>条件更新（CAS）+ 影响行数判定</b>：
 * 工序行的软删写成 {@code WHERE id=? AND tenant_id=? AND deleted=0}，0 行 ⇒ 409 CONFLICT
 * （与既有 conflict 口径一致）。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>至多一个赢家</b>：N=5 并发同一工序 ⇒ 成功（200）次数 <b>≤ 1</b>；落败方必须显式 4xx
 *       （{@code 409 CONFLICT}），不得是 500 / 不得静默成功 —— 修前实测 <b>3</b> 次 200 ⇒ 本条红；</li>
 *   <li><b>无重复副作用</b>：摘格写（{@code updatePriceAndApplicable}）与级联软删（{@code softDelete}）
 *       在整轮并发里对每个格<b>各恰一次</b>（修前多赢家 ⇒ 各被写多次）；</li>
 *   <li><b>终态唯一</b>：赢家自己报告 {@code detached_positions=1} / {@code deleted_positions=1}，
 *       其余请求（无论 200 幂等 no-op 还是 409）一律报 {@code detached_positions=0}
 *       —— 「工序已经不在活跃集里」这句话由至多一个请求说出口；</li>
 *   <li><b>正对照（护栏与 CAS 不误杀）</b>：单请求串行调用必须成功（200）且摘格/软删各恰一次
 *       —— 若谓词写错（如把 {@code deleted=0} 写成 {@code deleted=1}），本条会红。</li>
 * </ol>
 *
 * <h2>为什么用「包内探针缝」而不是靠碰运气</h2>
 * 窗口只有微秒级（HTTP 层 5 并发实测命中 3/5 也说明它是**概率性**的）⇒ 不注入就只能靠调度巧合。
 * 本判据的确定性来源 = {@code CyclicBarrier} 让 N 个线程在<b>同一时刻</b>进入服务调用
 * （全部先读、再写，落在同一个窗口里），并把「工序行 CAS」的返回行数做成**第 1 次 1、其余 0**
 * （{@code ProductionOperationMapper#claimDelete} 的有序桩）—— 生产路径里这个返回值由 PG 的行锁 + 条件重估给出。
 *
 * <p><b>边界（如实登记）</b>：① 本类是 <b>mock 面</b>判据：它证「服务层只认 CAS 的影响行数」，
 * 结构上判不了「真 PG 上行锁是否真的串行化了两个 CAS」—— 那一层由 #6928 的同族真库判据
 * （{@code InboundOrderCancelRaceRealDbTest}）承担；本单的 HTTP 层成对读数见 PR body；
 * ② 只覆盖 {@code deleteDetaching} 一个入口（{@code delete} 两参版本不在本单射程）；
 * ③ 不动公开契约 / 字段名 / 状态枚举：已软删的工序仍返回 200 幂等 no-op（既有契约）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("🔴 并发判据（#6936）：detach-and-delete 写面 exactly-once（CAS + 影响行数）")
class ProductionOperationDetachConcurrentTest {

    private static final Long TENANT = 1L;
    private static final String OP_ID = "op-6936-race";
    /** 并发度（与验收探针 E4 的 5 次逐字一致）。 */
    private static final int CONCURRENCY = 5;

    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionOperationPriceVersionMapper priceVersionMapper;
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    @BeforeAll
    static void primeMybatisPlusLambdaCache() {
        // `LambdaUpdateWrapper` 的 `.set(...)` **立即**求值列名（同 ProductionOperationDeleteGuardTest 的做法）
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, ProductionOperation.class);
        TableInfoHelper.initTableInfo(assistant, ProductionOperationPosition.class);
    }

    // ── 夹具 ──

    /** 被并发删的工序：库中名 = 无部位后缀的自定义名（逻辑名 = 自身）。 */
    private ProductionOperation operation(int deleted) {
        return ProductionOperation.builder()
                .id(OP_ID).tenantId(TENANT).name("核验工序6936").groupName("车位").unit("米")
                .unitPrice(new BigDecimal("0.40")).scope("position").isMustFinish(false)
                .isStartMarker(false).sortOrder(1).status("active").deleted(deleted).build();
    }

    private ProductionOperationPosition cell(String id, String position, boolean applicable) {
        return ProductionOperationPosition.builder()
                .id(id).tenantId(TENANT).logicalName("核验工序6936").position(position)
                .unitPrice(new BigDecimal("0.40")).applicable(applicable).status("active").deleted(0)
                .build();
    }

    /** 一个命中格（{@code applicable=true} ⇒ 一键摘格会真的写它）。 */
    private void stubOneDetachableCell() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(operation(0)));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(cell("opp-6936-布帘", "布帘", true)));
        when(productionOperationPositionMapper.updatePriceAndApplicable(
                any(), any(), any(), any(), any())).thenReturn(1);
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(1);
    }

    /**
     * 删除权 CAS（{@code ProductionOperationMapper#claimDelete}）的**有序桩**：第 1 次返回 1
     * （抢到删除权），其后返回 0（已被并发者抢走）。生产路径里这个返回值由 PG 的行锁 +
     * 条件重估给出（本类的边界见类注释）。
     */
    private void stubCasFirstCallWins() {
        AtomicInteger casCalls = new AtomicInteger();
        when(productionOperationMapper.claimDelete(any(), any(), any()))
                .thenAnswer(inv -> casCalls.getAndIncrement() == 0 ? 1 : 0);
    }

    // ── 判据 1~3：并发 exactly-once ──

    @Test
    @DisplayName("#6936 并发 5 次 detach-and-delete 同一工序 ⇒ 成功次数 ≤ 1 + 无重复副作用 + 终态唯一")
    void concurrentDetachAndDeleteHasAtMostOneWinner() throws Exception {
        stubOneDetachableCell();
        stubCasFirstCallWins();

        List<Object> outcomes = runConcurrently(CONCURRENCY);

        long successes = outcomes.stream().filter(o -> o instanceof Map).count();
        List<String> codes = outcomes.stream().map(this::code).toList();
        long winners = outcomes.stream()
                .filter(o -> o instanceof Map)
                .map(o -> String.valueOf(((Map<?, ?>) o).get("detached_positions")))
                .filter("1"::equals)
                .count();
        long detachedByLosers = outcomes.stream()
                .filter(o -> o instanceof BusinessException)
                .count();

        System.out.println("[READING #6936 并发] 各状态=" + codes
                + " 成功数=" + successes
                + " 报 detached_positions=1 的请求数=" + winners
                + " 被拒(409)数=" + detachedByLosers);

        assertThat(successes)
                .as("并发 5 次同一工序 ⇒ **至多一个赢家**（修前实测 3 次 200，见 E4-detach-concurrent.json）")
                .isLessThanOrEqualTo(1L);
        assertThat(winners)
                .as("「我摘了格」这句话至多由一个请求说出口（赢家）；其余必须报 detached_positions=0")
                .isLessThanOrEqualTo(1L);
        // ② 无重复副作用：摘格与级联软删对**这一个格**各恰一次
        verify(productionOperationPositionMapper, times(1))
                .updatePriceAndApplicable(any(), any(), any(), any(), any());
        verify(productionOperationPositionMapper, times(1)).softDelete(any(), any(), any());
        // ③ 落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功）
        assertThat(outcomes.stream()
                .filter(o -> o instanceof BusinessException)
                .map(o -> ((BusinessException) o).getHttpStatus())
                .collect(Collectors.toSet()))
                .as("落败方必须是显式 409 CONFLICT（不是 500）")
                .isSubsetOf(java.util.Set.of(409));
    }

    // ── 判据 4：正对照（CAS 谓词不误杀正常请求）──

    @Test
    @DisplayName("#6936 正对照：单请求串行 detach-and-delete 必须成功（CAS 不误杀）")
    void serialDetachAndDeleteStillSucceeds() {
        stubOneDetachableCell();
        when(productionOperationMapper.claimDelete(any(), any(), any())).thenReturn(1);

        Map<String, Object> result = service().deleteDetaching(OP_ID, TENANT);

        System.out.println("[READING #6936 串行正对照] detached=" + result.get("detached_positions")
                + " deleted=" + result.get("deleted_positions") + " deleted_flag=" + result.get("deleted"));
        assertThat(result.get("deleted")).isEqualTo(true);
        assertThat(result.get("detached_positions")).isEqualTo(1);
        assertThat(result.get("deleted_positions")).isEqualTo(1);
        verify(productionOperationPositionMapper, times(1))
                .updatePriceAndApplicable(any(), any(), any(), any(), any());
        verify(productionOperationPositionMapper, times(1)).softDelete(any(), any(), any());

        // 谓词完整性：删除权走 mapper 的**条件更新**（`claimDelete`），且**必须判影响行数**
        // （经 `if (… == 0) throw 409`）；三条谓词（id / tenant_id / deleted=0）由
        // ProductionOperationDeleteCasMetaGuardTest 按 mapper SQL 逐条扫描（本类只管接线与语义）。
        verify(productionOperationMapper).claimDelete(eq(OP_ID), eq(TENANT), any());
    }

    // ── 并发装置 ──

    /** N 个线程同一时刻进入服务调用；返回每个请求的结果（响应 Map 或业务异常）。 */
    private List<Object> runConcurrently(int n) throws Exception {
        CyclicBarrier barrier = new CyclicBarrier(n);
        ExecutorService pool = Executors.newFixedThreadPool(n);
        try {
            List<Callable<Object>> tasks = new ArrayList<>();
            for (int i = 0; i < n; i++) {
                tasks.add(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    try {
                        return service().deleteDetaching(OP_ID, TENANT);
                    } catch (BusinessException e) {
                        return e;
                    }
                });
            }
            List<Future<Object>> futures = pool.invokeAll(tasks, 60, TimeUnit.SECONDS);
            List<Object> out = new ArrayList<>();
            for (Future<Object> f : futures) {
                out.add(f.get(60, TimeUnit.SECONDS));
            }
            return out;
        } finally {
            pool.shutdownNow();
        }
    }

    private String code(Object outcome) {
        return outcome instanceof Map ? "200" : String.valueOf(((BusinessException) outcome).getHttpStatus());
    }

    private ProductionOperationCommandService service() {
        // 读面用**真实对象**（只 mock Mapper）：命中格/归一/护栏与生产同源
        return new ProductionOperationCommandService(
                productionOperationMapper, priceVersionMapper, productionOperationPositionMapper,
                new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                        productionRouteRuleMapper, productionOperationPositionMapper,
                        productionCraftMapper, productionRouteSignalMapper));
    }
}
