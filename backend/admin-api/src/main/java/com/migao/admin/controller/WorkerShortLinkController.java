package com.migao.admin.controller;

import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.service.WorkerShortLinkService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;

/**
 * 工人端**稳定短链**：{@code GET /s/{shortCode}} ⇒ **服务端 302** 到报工页（issue #4802；
 * 设计 {@code docs/design/worker-h5-scan-and-report.md} §1.3 / §1.4 / §7.2）。
 *
 * <pre>
 * 纸上的码（永不变）                     服务端（可变）                        实际页面（随便换）
 * https://app.migaozn.com/s/7K3M9QP2  ──302──▶  /w/?t=&lt;token&gt;&amp;tenant_id=&lt;id&gt;
 * </pre>
 *
 * <h2>为什么落点在 admin-api（而不是 nginx 规则 / 静态页）</h2>
 * <ul>
 *   <li><b>静态页</b> ❌：短码 ⇒ token 要**查库**（短码本身不含 token）⇒ 静态文件做不到；</li>
 *   <li><b>nginx 规则</b> ❌（作为唯一落点）：nginx 只能做**静态映射**（正则改写 / 固定跳转），
 *       它查不到 {@code processing_set_part_tokens} ⇒ 短码换不回 token。它只能承担**转发的半边**
 *       （把 {@code /s/} 反代到 admin-api，见 {@code deploy/swas/nginx.conf}）；</li>
 *   <li><b>前端 JS 跳转</b> ❌（**硬要求**）：用户裁定③「任意扫一扫工具都能用」⇒ 部分扫码工具
 *       **只认服务端跳转**（JS 跳转对它们是白屏）。</li>
 * </ul>
 *
 * <h2>路由稳定性（印刷品红线，设计 §1.3）</h2>
 * 码一旦打印贴到实物上**不可能回收重印** ⇒ 本路径段（{@code /s/}）与短码都是**稳定契约**；
 * 换前端框架 / 改报工页路径**只改 302 的目标**（{@link WorkerShortLinkService#REPORT_PAGE_PATH}），
 * 已打印的码继续有效。
 *
 * <h2>公开入口（无鉴权）与它**不**泄露什么</h2>
 * 本端点挂在 {@code permitAll}（{@code SecurityConfig}）：印刷品上的码对**任何**持码人等价
 * ⇒ 鉴权只能由「报工页的工人 session」承担（换 token 这一跳**不是**身份入口）。
 * 响应体为空（只有 302 的 {@code Location}），**不返回**工人身份、权限、订单/工序/价格
 * ⇒ 拿不到任何越权面（设计 §2.4 红线「不给工人任何商家权限」）。
 *
 * <h2>撤销语义（设计 §1.3.1，逐字复用既有口径）</h2>
 * 撤销 = 置 {@code token = NULL}（不换新 token，与 {@code ProcessingOrderMapper.revokeQrToken} 同语义）
 * ⇒ 本端点解析到「行在但 token 为空」⇒ **410 Gone**（**不得**静默回落到别的码）；
 * 短码未知/形态不合法 ⇒ **404**。
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class WorkerShortLinkController {

    private final WorkerShortLinkService workerShortLinkService;

    /**
     * 短码 ⇒ 302 报工页。
     *
     * <p>GET /s/{shortCode}（例：{@code https://app.migaozn.com/s/7K3M9QP2}）</p>
     *
     * @param shortCode 短码（8 位 Crockford Base32；手输形态 {@code O/I/L} 会被归一化）
     * @return 302 + {@code Location: /w/?t=&lt;token&gt;&amp;tenant_id=&lt;id&gt;}；未知 ⇒ 404；已撤销 ⇒ 410
     */
    @GetMapping("/s/{shortCode}")
    public ResponseEntity<Void> resolve(@PathVariable String shortCode) {
        ProcessingSetPartToken row = workerShortLinkService.resolve(shortCode);
        if (row == null) {
            return ResponseEntity.notFound().build();
        }
        if (!StringUtils.hasText(row.getToken())) {
            // 已撤销（token 置 NULL）：这张纸作废 ⇒ 410。**不得**回落、**不得**换新码。
            return ResponseEntity.status(HttpStatus.GONE).build();
        }
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(URI.create(
                        WorkerShortLinkService.reportPageLocation(row.getToken(), row.getTenantId())))
                .build();
    }
}
