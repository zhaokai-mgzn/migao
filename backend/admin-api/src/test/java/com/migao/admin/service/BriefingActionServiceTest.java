// case_ids: DA-032

package com.migao.admin.service;

import com.migao.admin.entity.BriefingAction;
import com.migao.admin.mapper.BriefingActionMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * 决策采纳记录（issue #8260）。
 *
 * <p>它要回答的问题只有一句：**「AI 建议了什么 → 人做了什么」能不能证明？**
 * 主判据不是「能存能查」，而是三条**容易做错的**：</p>
 *
 * <ol>
 *   <li><b>item_key 必须稳定且不含原文</b>：简报 {@code content} 里是字符串数组、没有 id。
 *       按标题取 hash ⇒ 不依赖顺序、也不会因 LLM 换个说法被当成同一条（换个说法本来就是另一条建议）。</li>
 *   <li><b>幂等</b>：同一条目反复点「问黄金策」只留一行 —— 否则「31 个问题你处理了 47 次」这种读数会自己长出来。</li>
 *   <li><b>不记标题原文</b>：只记 hash + 动作 + actor_id，不进 PII（红线同 daily_briefings）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("决策采纳记录（issue #8260）")
class BriefingActionServiceTest {

    @Mock
    private BriefingActionMapper briefingActionMapper;

    @InjectMocks
    private BriefingActionService service;

    @Test
    @DisplayName("item_key 稳定：同标题同 key、不同标题不同 key，且**不含标题原文**")
    void item_key_is_a_stable_hash_without_the_title() {
        String first = BriefingActionService.itemKey("给 A 商品补货");
        String second = BriefingActionService.itemKey("给 A 商品补货");
        String other = BriefingActionService.itemKey("B 商品改价");

        assertThat(first).isEqualTo(second);
        assertThat(first).isNotEqualTo(other);
        assertThat(first).hasSize(16);
        assertThat(first).doesNotContain("补货").doesNotContain("商品");
    }

    @Test
    @DisplayName("幂等：同一条目第二次上报走更新、不再插入新行")
    void repeated_actions_upsert_instead_of_inserting() {
        when(briefingActionMapper.selectOne(any())).thenReturn(null, existing());

        service.record(7L, "2026-10-31", "suggestion", "给 A 商品补货", "opened_agent", "u-1");
        service.record(7L, "2026-10-31", "suggestion", "给 A 商品补货", "opened_agent", "u-1");

        verify(briefingActionMapper, times(1)).insert(any(BriefingAction.class));
        verify(briefingActionMapper, times(1)).updateById(any(BriefingAction.class));
    }

    @Test
    @DisplayName("入库行只有 hash，没有标题原文（PII / 内容冗余红线）")
    void stored_row_carries_no_raw_title() {
        when(briefingActionMapper.selectOne(any())).thenReturn(null);

        service.record(7L, "2026-10-31", "risk", "库存告急：A 商品剩 8 米", "opened_agent", "u-1");

        ArgumentCaptor<BriefingAction> captor = ArgumentCaptor.forClass(BriefingAction.class);
        verify(briefingActionMapper).insert(captor.capture());
        BriefingAction row = captor.getValue();
        assertThat(row.getItemKey()).hasSize(16).doesNotContain("库存").doesNotContain("A 商品");
        assertThat(row.getTenantId()).isEqualTo(7L);
        assertThat(row.getBizDate()).isNotNull();
        assertThat(row.getAction()).isEqualTo("opened_agent");
    }

    @Test
    @DisplayName("非法动作被拒（白名单不猜）")
    void unknown_action_is_rejected() {
        assertThat(service.isKnownAction("opened_agent")).isTrue();
        assertThat(service.isKnownAction("done")).isFalse();
        assertThat(service.isKnownAction("")).isFalse();
        assertThat(service.isKnownAction(null)).isFalse();
    }

    @Test
    @DisplayName("查不到记录 ⇒ 空列表（不是 null）")
    void empty_result_is_empty_list_not_null() {
        when(briefingActionMapper.selectList(any())).thenReturn(null);

        assertThat(service.listRecent(7L, 30)).isNotNull().isEmpty();
    }

    private BriefingAction existing() {
        return BriefingAction.builder()
                .id("x").tenantId(7L).bizDate(java.time.LocalDate.of(2026, 10, 31))
                .itemKind("suggestion").itemKey("abc").action("opened_agent").actorId("u-1")
                .build();
    }
}
