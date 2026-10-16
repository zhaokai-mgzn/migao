package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.service.ProductionService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 工人端「我的计件」读面（issue #6767）：{@code GET /api/worker/piecework?month=YYYY-MM}。
 *
 * <p>口径真值源 = {@code docs/design/worker-home-menu.md} §6.3（2026-10-12 用户逐字「需要给工人看」）。</p>
 *
 * <h3>六条钉死（逐条在本类的落点）</h3>
 * <ol>
 *   <li><b>单一真值</b>：金额聚合复用商家端计件读面的**同一份**实现
 *       （{@link ProductionService#aggregate}，per-order 汇总 / 期间报表 / agent 工人计件共用的唯一算法）
 *       —— 本路径**只做**「当前工人 + 期间」的过滤投影，没有第二份求和
 *       （{@link ProductionService#workerPieceworkLedger}）。</li>
 *   <li><b>作用域只认会话</b>：{@code worker_id} 由 {@link WorkerSessionService#resolveIdentity} 从
 *       {@code X-Worker-Session-Id} 解出 —— 本方法**只**接收一个请求参数 {@code month}，
 *       请求里带 {@code worker_id} 连一个读取点都没有（想冒领的人改前端也没用）。</li>
 *   <li><b>期间</b>：默认业务当前自然月（Asia/Shanghai，{@code BusinessClock}），可切上月；
 *       半开区间 {@code [月初, 次月初)}；{@code prev_period} / {@code next_period} / {@code can_prev} /
 *       {@code can_next} 由服务端算 ⇒ 端侧不做月份边界推算。</li>
 *   <li><b>未定价</b>：透出服务端同一份 {@code unpriced} 块（未定价 ≠ 0 元，一律不进合计）。</li>
 *   <li><b>只读</b>：本类**只有** {@code @GetMapping} —— 工人面不做确认 / 锁定 / 结算
 *       （判据 {@code WorkerPieceworkControllerTest::onlyGetIsExposedOnThisPath}）。</li>
 *   <li><b>口径风险同源</b>：已取消 / 返工 / 改价的扣减口径与商家端**同一份聚合**（不新发明）。</li>
 * </ol>
 *
 * <p>🔴 <b>权限</b>：本路径在 {@code /api/worker/**} 内 ⇒ **零商家权限码**（工人 {@code permissions=[]}，
 * 加 {@code @RequirePermission} 只会恒 403）；准入 = 有效工人 session（无 ⇒ 401，fail-closed）。
 * {@code /api/admin/**} 对 {@code worker} 一律 403（{@code SecurityConfig}）⇒ 工人读不到商家端计件面。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker/piecework")
@RequiredArgsConstructor
public class WorkerPieceworkController {

    private final ProductionService productionService;
    private final WorkerSessionService workerSessionService;

    /**
     * 我的计件：合计金额 + 件数 + 逐笔（本月 / 上月）。
     *
     * <p>无有效工人 session ⇒ 401（fail-closed，与报工面同款）；非法 / 未来月份 ⇒ 422。
     * 两者都在**读任何计件数据之前**判 —— 未认证请求不触达聚合（判据：401 时服务层零调用）。</p>
     */
    @GetMapping
    public ApiResponse<Map<String, Object>> piecework(
            @RequestParam(name = "month", required = false) String month,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw com.migao.admin.exception.BusinessException.authFailed(
                    "尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return ApiResponse.success(productionService.workerPieceworkLedger(
                identity.workerId(), identity.workerName(), month, TenantContext.getTenantId()));
    }
}
