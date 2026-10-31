package com.migao.admin.controller;

import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.service.WorkerShortLinkService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 工人端**稳定短链**：{@code GET /s/{shortCode}} ⇒ **服务端 302** 到报工页（issue #4802；
 * 设计 {@code docs/design/worker-h5-scan-and-report.md} §1.3 / §1.4 / §7.2）。
 *
 * <pre>
 * 纸上的码（永不变）                     服务端（可变）                        实际页面（随便换）
 * https://app.migaozn.com/s/7K3M9QP2  ──302──▶  /b/?t=&lt;token&gt;&amp;tenant_id=&lt;id&gt;&amp;tenant_code=&lt;code&gt;
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
     * @return 302 + {@code Location: /b/?t=&lt;token&gt;&amp;tenant_id=&lt;id&gt;&amp;tenant_code=&lt;code&gt;}；未知 ⇒ 404；已撤销 ⇒ 410
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
                        WorkerShortLinkService.reportPageLocation(row.getToken(), row.getTenantId(),
                                workerShortLinkService.tenantCodeOf(row.getTenantId()))))
                .build();
    }

    /**
     * 短码 ⇒ **JSON**（issue #8196：微信「扫普通链接二维码打开小程序」的 A 档）。
     *
     * <p>微信把印在纸上的整条链接放进小程序的 {@code getEnterOptionsSync().query.q}，而
     * <b>小程序不跟随 HTTP 302</b> ⇒ 上面那条既有的 302 面在这里只剩一个空响应，
     * 短码换不回 token（线上表现 = 扫码后停在报工页、报工按钮一直不出来，且没有任何东西会变红）。
     * 本端点就是那一跳的 JSON 形态：{@code GET /s/{shortCode}/json}。</p>
     *
     * <h2>为什么是**显式子路径**，不是内容协商（{@code Accept: application/json}）</h2>
     *
     * 印刷品红线：{@code /s/} 的 302 一旦跟着 {@code Accept} 变语义，
     * <b>不带 Accept / 带 {@code *&#47;*} 的扫码工具</b>（部分只认服务端跳转，用户裁定③）就会从
     * 「302 到报工页」变成「一段 JSON 文本」—— 已印出去的码**不可重印**，这是不可接受的静默失联，
     * 且现场无法用测试事先排除（不同扫码工具的 Accept 各不相同）。显式子路径把这件事变确定：
     * 旧路径<b>任何 Accept</b> 都仍是 302，新面在它自己的路径上。
     *
     * <h2>响应与它**不**泄露什么</h2>
     *
     * 成功 ⇒ {@code 200 {reportPath, token}}：两个值都取自 302 的 {@code Location}
     * （{@link WorkerShortLinkService#REPORT_PAGE_PATH} 与 {@code t}），<b>不</b>额外多给任何一项
     * （不返回工人身份 / 工序 / 订单 / 价格 / 租户参数）⇒ 拿不到任何 302 之外的面。
     * 未知 ⇒ {@code 404 {"error":"not_found"}}；已撤销（{@code token} 置 NULL）⇒
     * {@code 410 {"error":"revoked"}} —— 错误体只重复状态码已经表达的语义。
     *
     * <p>公开面与限流：本端点与 {@code /s/} 同族（{@code SecurityConfig} 的 {@code /s/**} = permitAll，
     * nginx {@code location /s/} 的 {@code worker_entry} 档 per-IP 限流）⇒ <b>不新增</b>任何鉴权面；
     * 短码形态判定仍只有 {@link WorkerShortLinkService#normalize} 一份（手输抄错形态在这里同样可用）。</p>
     *
     * @param shortCode 短码（8 位 Crockford Base32；手输形态 {@code O/I/L} 会被归一化）
     * @return 200 + {@code {reportPath, token}}；未知 ⇒ 404；已撤销 ⇒ 410
     */
    @GetMapping("/s/{shortCode}/json")
    public ResponseEntity<Map<String, Object>> resolveJson(@PathVariable String shortCode) {
        ProcessingSetPartToken row = workerShortLinkService.resolve(shortCode);
        if (row == null) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("error", "not_found"));
        }
        if (!StringUtils.hasText(row.getToken())) {
            // 撤销语义与 302 面**同一份**（置 NULL = 这张纸作废）：不回落、不换新码、不给任何可用值。
            return ResponseEntity.status(HttpStatus.GONE)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("error", "revoked"));
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("reportPath", WorkerShortLinkService.REPORT_PAGE_PATH);
        body.put("token", row.getToken());
        return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(body);
    }
}
