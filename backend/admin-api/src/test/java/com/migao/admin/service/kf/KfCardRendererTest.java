// case_ids: KF-023
package com.migao.admin.service.kf;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class KfCardRendererTest {

    private final KfCardRenderer renderer = new KfCardRenderer();

    @Test
    @DisplayName("商品/订单等卡片降级为标题+摘要+链接")
    void businessCardToText() {
        String out = renderer.render("product",
                Map.of("title", "纯棉面料", "summary", "¥12/米", "url", "https://x/p/1"));
        assertThat(out).contains("纯棉面料").contains("¥12/米").contains("https://x/p/1");
    }

    @Test
    @DisplayName("支付/按钮/表单降级")
    void specialCards() {
        assertThat(renderer.render("payment", Map.of("url", "https://pay")))
                .isEqualTo("请扫码支付：https://pay");
        assertThat(renderer.render("quick_actions", Map.of("options", List.of("查订单", "找人工"))))
                .contains("1. 查订单").contains("2. 找人工");
        assertThat(renderer.render("form", Map.of())).contains("请直接回复文字");
    }
}
