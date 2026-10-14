package com.migao.admin.controller;

import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.service.ProcessingOrderShortLinkService;
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
 * **加工单级**稳定短链：{@code GET /o/{shortCode}} ⇒ **服务端 302** 到报工页
 * （issue #6867 / 实现包 B2；设计 {@code docs/design/worker-h5-scan-and-report.md}
 * §11.3 / §11.6 / §11.9(B2 行) / §11.10）。
 *
 * <pre>
 * 纸上的码（永不变）                     服务端（可变）                        实际页面（随便换）
 * https://app.migaozn.com/o/7K3M9QP2  ──302──▶  /w/?t=&lt;token&gt;&amp;tenant_id=&lt;id&gt;&amp;tenant_code=&lt;code&gt;
 * </pre>
 *
 * <h2>为什么是**第三个**前缀（不与 {@code /s/} 共表、不共用解析入口）</h2>
 * <ul>
 *   <li>{@code /s/} 解「哪一张**部位**纸」（带套带部位 ⇒ 直进报工页）；{@code /i/} 解「哪一张**入库标签**」；
 *       本端点解「哪一张**加工单**纸」—— 加工单纸是**单级**的（一张纸 = 一整单）⇒ 它**结构上指不出部位**，
 *       落地必然是「**选套 → 选部位**」降级面（H5 已实现且已判据化：
 *       {@code frontend/worker-h5/src/render.mjs} 的 {@code needs_selection} 强制选，**绝不默认取第 1 套**）；</li>
 *   <li>三个码空间的短码规格**故意同款**（8 位 Crockford Base32）⇒ 承载表不同 +
 *       各自的部分唯一索引（{@code uk_processing_orders_short_code} vs {@code uk_set_part_tokens_short_code}）
 *       ⇒ **两边的短码可以重叠而不冲突**（同一个 8 位串在两张表里各指各的，路径段把它分开）；
 *       复用 {@code /s/} 去查两张表会让「同一命名空间混两套语义」，而那种事**没有任何判据会红**
 *       （这正是 {@code tests/unit_ci_workflows/test_public_code_spaces_are_disjoint.py} 判据 A 要治的）；
 *   <li>前缀**自识别**：路径段本身就说明「这是加工单级」—— 纸面 / 日志 / 探针一眼分辨。</li>
 * </ul>
 *
 * <h2>302 的目标**没有第二份实现**</h2>
 * {@code Location} 由 {@link WorkerShortLinkService#reportPageLocation} 拼装（与 {@code /s/} 同一份：
 * 同一 {@code REPORT_PAGE_PATH}、同一租户参数口径、同一「相对 Location」决策）。本类**只**决定
 * 「到哪一张纸」与「多少状态码」，**不**自己拼 URL —— 复制第二份拼装 = 第二条真相源，
 * 日后改落地页路径会只改一处（判据见
 * {@code ProcessingOrderShortLinkControllerTest#the302TargetComesFromTheSingleExistingBuilder}）。
 *
 * <h2>响应三形态（设计 §11.6，逐字）</h2>
 * <ul>
 *   <li>命中且 {@code qr_token} 非空 ⇒ <b>302</b> + {@code Location}；</li>
 *   <li>短码未知 / **形态不合法**（长度 ≠ 8 或含字符集外字符）⇒ <b>404</b>（且**一次库都不查**）；</li>
 *   <li>行在但 {@code qr_token} 为 {@code NULL}（**已撤销**）⇒ <b>410 Gone</b> ——
 *       撤销 = {@code qr_token} 置 NULL（**不换新 token、不碰 {@code short_code}**）
 *       ⇒ 已打印的纸**不作废**、重新发码后**同一个短码**仍可用。「重新发码」只补 {@code token IS NULL}
 *       的行 ⇒ 本端点在同一张纸上先 410、再 302，而路径段一个字都没变。</li>
 * </ul>
 *
 * <h2>公开入口（无鉴权）与它**不**泄露什么</h2>
 * 本端点挂在 {@code permitAll}（{@code SecurityConfig}）：印刷品上的码对**任何**持码人等价
 * ⇒ 鉴权只能由**报工页的工人 session** 承担（换 token 这一跳**不是**身份入口）。
 * 响应体**为空**（只有 302 的 {@code Location}），且 {@code Location} 的查询参数**恰好三个**
 * （{@code t} / {@code tenant_id} / {@code tenant_code}）—— **不返回**加工单号、客户名、工序、价格、
 * 工人身份等任何业务字段（判据 = 同类的
 * {@code ProcessingOrderShortLinkControllerTest#the302LeaksNothingBeyondTheThreeTenantParams}）。
 * 🔴 「扫一张纸 ≠ 拿到数据」：真数据在 {@code /api/worker/**} 上，那一层要求**有效工人 session**
 * （{@code WorkerSessionFilter} fail-closed：无效 / 已结束 / 闲置超时 / 会话租户与请求租户不一致
 * ⇒ 不设认证 ⇒ 401），无 session 的页面只显示登录表单。
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class ProcessingOrderShortLinkController {

    private final ProcessingOrderShortLinkService processingOrderShortLinkService;
    private final WorkerShortLinkService workerShortLinkService;

    /**
     * 加工单短码 ⇒ 302 报工页。
     *
     * <p>GET /o/{shortCode}（例：{@code https://app.migaozn.com/o/7K3M9QP2}）</p>
     *
     * @param shortCode 短码（8 位 Crockford Base32；手输形态 {@code O/I/L} 会被归一化）
     * @return 302 + {@code Location: /w/?t=&lt;token&gt;&amp;tenant_id=&lt;id&gt;&amp;tenant_code=&lt;code&gt;}；
     *         未知 / 形态不合法 ⇒ 404；已撤销 ⇒ 410
     */
    @GetMapping("/o/{shortCode}")
    public ResponseEntity<Void> resolve(@PathVariable("shortCode") String shortCode) {
        ProcessingOrder order = processingOrderShortLinkService.resolve(shortCode);
        if (order == null) {
            return ResponseEntity.notFound().build();
        }
        if (!StringUtils.hasText(order.getQrToken())) {
            // 已撤销（qr_token 置 NULL，short_code 一字未动）：这张纸当前作废 ⇒ 410。
            // **不得**回落成 404（那是「没这个码」）、**不得**换新码、**不得**碰 short_code。
            return ResponseEntity.status(HttpStatus.GONE).build();
        }
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(URI.create(WorkerShortLinkService.reportPageLocation(
                        order.getQrToken(), order.getTenantId(),
                        workerShortLinkService.tenantCodeOf(order.getTenantId()))))
                .build();
    }
}
