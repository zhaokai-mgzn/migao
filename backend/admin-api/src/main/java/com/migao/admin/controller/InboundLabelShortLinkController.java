package com.migao.admin.controller;

import com.migao.admin.entity.InboundLabel;
import com.migao.admin.service.InboundLabelService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;

/**
 * 入库标签的**公开入口**：{@code GET /i/{shortCode}} ⇒ 服务端 302 到落地页
 * （issue #5052 P2；设计 {@code docs/design/inbound-photo-and-label.md} §5.2 / §7.1）。
 *
 * <pre>
 * 纸上的码（永不变）                     服务端（可变）                       实际页面（随便换）
 * https://app.migaozn.com/i/7K3M9QP2  ──302──▶  /b/?code=7K3M9QP2&amp;tenant_id=7
 * </pre>
 *
 * <h3>🔴 与 {@code GET /s/{短码}}（工人报工短链）是**两个码空间**</h3>
 * <p>{@code /s/} 是「哪一张工单纸」（302 → {@code /w/?t=<token>}），{@code /i/} 是「哪一张入库标签」
 * （302 → 落地页）—— 语义不同、落地页不同，混用会把「扫标签」变成「进报工页」。
 * 两条入口各自解析自己的表（{@code inbound_labels} vs {@code processing_set_part_tokens}），
 * 一个码在另一条入口上**必须**解析不到（判据 = {@code InboundLabelSurfaceGuardTest} 的互斥断言
 * 与 {@code tests/unit_ci_workflows/test_public_code_spaces_are_disjoint.py} 的类级守卫）。</p>
 *
 * <h3>公开入口（无鉴权）与它**不**泄露什么</h3>
 * <p>本端点挂在 {@code permitAll}（{@code SecurityConfig}）：印刷品上的码对**任何**持码人等价
 * ⇒ 鉴权只能由落地页里的工人 session 承担（换这一跳**不是**身份入口）。
 * 响应体为空（只有 302 的 {@code Location}），<b>不返回</b>品名 / 色号 / 米数 / 供应商 / 单号
 * 等任何业务字段 —— 拿不到任何越权面（§5.2 逐字「只回跳转、不泄露业务字段」）。</p>
 *
 * <h3>撤销语义（§7.3）</h3>
 * <p>撤销 = 短码置 NULL（原码留档）⇒ 本端点解析到「行在但已撤销」⇒ <b>410 Gone</b>
 * （**不得**静默回落到别的码）；短码未知 / 形态不合法 ⇒ <b>404</b>。</p>
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class InboundLabelShortLinkController {

    private final InboundLabelService inboundLabelService;

    /**
     * 短码 ⇒ 302 落地页。
     *
     * @param shortCode 8 位 Crockford Base32 短码（手抄形态 {@code O/I/L} 会被归一化）
     * @return 302 + {@code Location}；未知 ⇒ 404；已撤销 ⇒ 410
     */
    @GetMapping("/i/{shortCode}")
    public ResponseEntity<Void> resolve(@PathVariable("shortCode") String shortCode) {
        InboundLabel label = inboundLabelService.resolve(shortCode);
        if (label == null) {
            return ResponseEntity.notFound().build();
        }
        if (label.isRevoked()) {
            // 已撤销（短码置 NULL，原码留档）：这张纸作废 ⇒ 410。**不得**回落、**不得**换新码。
            return ResponseEntity.status(HttpStatus.GONE).build();
        }
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(URI.create(inboundLabelService.landingLocation(
                        label.getShortCode(), label.getTenantId())))
                .build();
    }
}
