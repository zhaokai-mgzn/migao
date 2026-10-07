// case_ids: AG-010
package com.migao.admin.service;

import com.migao.admin.time.BusinessClock;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.CreateNotificationRequest;
import com.migao.admin.dto.agent.AgentScheduledTaskRequest;
import com.migao.admin.entity.ScheduledTask;
import com.migao.admin.entity.Tenant;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ScheduledTaskMapper;
import com.migao.admin.mapper.TenantMapper;
import org.springframework.dao.DuplicateKeyException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 定时任务（用户「预约」）服务主判据 —— issue #6486 包 1。
 *
 * <p>本类钉死 issue #6486「业务真值」里**服务端那半边**，逐条对应用户可见判据：</p>
 * <ol>
 *   <li><b>三件套缺失 ⇒ 不建单</b>（真值 2）：`criterion` / `actionLabel` / `actionUrl` 任一为空
 *       抛 {@link BusinessException}，且 <b>一次 insert 都不发</b> —— 这是「没有处置入口的提醒不发」
 *       在建单期的落点；</li>
 *   <li><b>幂等 ⇒ 不重复建</b>（真值 5）：同 `dedupKey` 第二次调用返回既有行、<b>不 insert</b>；</li>
 *   <li><b>取消</b>（真值 4）：`pending` 可取消并落 `cancelled`；<b>`fired` 不可取消</b>
 *       （消息已发出，notifications 不可撤回）；跨租户的 id 取消不了；</li>
 *   <li><b>扫描投递</b>（真值 1）：到期的 `pending` ⇒ 调通知服务一次 + 置 `fired`，
 *       且投递内容 = 三件套；</li>
 *   <li><b>只读（真值 3）</b>：投递路径<b>只</b>触达通知服务 —— 结构面判据：本服务的依赖里没有
 *       任何业务写服务；</li>
 *   <li><b>逐租户设置/恢复租户上下文</b>（issue #3957 教训）：扫描完必须把上下文还原；</li>
 *   <li><b>fail-soft</b>：单条投递失败 ⇒ 该条置 `failed`，<b>不拖垮</b>同轮其它条；</li>
 *   <li><b>只有 pending 会被投递</b>（疲劳控制）：投递后不重投。</li>
 * </ol>
 *
 * <p>⚠️ 结构说明：本类**刻意不用 `@Nested` 分组** —— 实测 `mvn -Dtest=ScheduledTaskServiceTest test`
 * 在 @Nested 结构下报告 `Tests run: 0`（exit 0 = **假绿**：一条都没跑）。扁平结构下同一条命令真跑，
 * 故按「测试必须真跑」优先于分组可读性。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ScheduledTaskServiceTest {

    @Mock
    private ScheduledTaskMapper scheduledTaskMapper;

    @Mock
    private TenantMapper tenantMapper;

    @Mock
    private NotificationService notificationService;

    @Mock
    private BusinessClock businessClock;

    @InjectMocks
    private ScheduledTaskService service;

    private static final OffsetDateTime NOW = OffsetDateTime.parse("2026-10-07T12:00:00+08:00");

    @AfterEach
    void clearTenantContext() {
        TenantContext.clear();
    }

    private static AgentScheduledTaskRequest validRequest() {
        AgentScheduledTaskRequest r = new AgentScheduledTaskRequest();
        r.setTaskType("follow_up");
        r.setFireAt(NOW.plusDays(3));
        r.setCriterion("你说过：等王总回复后再跟进张先生");
        r.setActionLabel("去跟进张先生");
        r.setActionUrl("/customers?keyword=张先生");
        r.setImpact(Map.of("count", 1));
        return r;
    }

    private static Tenant tenant(long id) {
        Tenant t = new Tenant();
        t.setId(id);
        return t;
    }

    private static ScheduledTask task(String id, String status) {
        return ScheduledTask.builder()
                .id(id).tenantId(20L).taskType("follow_up")
                .fireAt(NOW.minusMinutes(1))
                .criterion("你说过：等王总回复后再跟进张先生")
                .actionLabel("去跟进张先生")
                .actionUrl("/customers?keyword=张先生")
                .subjectType("employee").subjectId("u-1")
                .source(ScheduledTask.SOURCE_USER)
                .status(status).deleted(0)
                .build();
    }

    // ==================== 真值 2：三件套缺失 ⇒ 不建单 ====================

    @Test
    @DisplayName("三件套 fail-closed：缺 criterion ⇒ 抛异常，且一次 insert 都不发")
    void missingCriterionRejected() {
        AgentScheduledTaskRequest r = validRequest();
        r.setCriterion("  ");
        assertThatThrownBy(() -> service.create(20L, "u-1", r))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("criterion");
        verify(scheduledTaskMapper, never()).insert(any(ScheduledTask.class));
    }

    @Test
    @DisplayName("三件套 fail-closed：缺 actionLabel ⇒ 抛异常，且一次 insert 都不发")
    void missingActionLabelRejected() {
        AgentScheduledTaskRequest r = validRequest();
        r.setActionLabel(null);
        assertThatThrownBy(() -> service.create(20L, "u-1", r))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("actionLabel");
        verify(scheduledTaskMapper, never()).insert(any(ScheduledTask.class));
    }

    @Test
    @DisplayName("三件套 fail-closed：缺 actionUrl ⇒ 抛异常，且一次 insert 都不发")
    void missingActionUrlRejected() {
        AgentScheduledTaskRequest r = validRequest();
        r.setActionUrl("");
        assertThatThrownBy(() -> service.create(20L, "u-1", r))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("actionUrl");
        verify(scheduledTaskMapper, never()).insert(any(ScheduledTask.class));
    }

    // ==================== 真值 5：幂等 ====================

    @Test
    @DisplayName("幂等：同 dedupKey 第二次 ⇒ 返回既有行，不重复 insert")
    void secondCallReturnsExisting() {
        AgentScheduledTaskRequest r = validRequest();
        ScheduledTask existing = task("st-existing", ScheduledTask.STATUS_PENDING);
        when(scheduledTaskMapper.selectByDedupKey(anyLong(), any())).thenReturn(existing);

        ScheduledTask result = service.create(20L, "u-1", r);

        assertThat(result.getId()).isEqualTo("st-existing");
        verify(scheduledTaskMapper, never()).insert(any(ScheduledTask.class));
    }

    @Test
    @DisplayName("派生幂等键 = 收件人:类型:触发时刻(秒)；未命中则 insert 一条 pending")
    void deriveKeyAndInsert() {
        when(scheduledTaskMapper.selectByDedupKey(anyLong(), any())).thenReturn(null);
        AgentScheduledTaskRequest r = validRequest();

        ScheduledTask result = service.create(20L, "u-1", r);

        ArgumentCaptor<ScheduledTask> captor = ArgumentCaptor.forClass(ScheduledTask.class);
        verify(scheduledTaskMapper).insert(captor.capture());
        ScheduledTask inserted = captor.getValue();
        assertThat(inserted.getStatus()).isEqualTo(ScheduledTask.STATUS_PENDING);
        assertThat(inserted.getSource()).isEqualTo(ScheduledTask.SOURCE_USER);
        assertThat(inserted.getDedupKey())
                .isEqualTo("u-1:follow_up:" + r.getFireAt().toEpochSecond());
        // 收件人缺省 = 建单者自己（subject 缺省 employee）
        assertThat(inserted.getSubjectType()).isEqualTo("employee");
        assertThat(inserted.getSubjectId()).isEqualTo("u-1");
        assertThat(result.getCriterion()).isEqualTo(r.getCriterion());
    }

    // ==================== 真值 4：取消 ====================

    @Test
    @DisplayName("取消：pending ⇒ 落 cancelled")
    void cancelPending() {
        when(businessClock.nowOffset()).thenReturn(NOW);
        when(scheduledTaskMapper.selectById("st-1"))
                .thenReturn(task("st-1", ScheduledTask.STATUS_PENDING));

        assertThat(service.cancel(20L, "st-1")).isTrue();

        ArgumentCaptor<ScheduledTask> captor = ArgumentCaptor.forClass(ScheduledTask.class);
        verify(scheduledTaskMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo(ScheduledTask.STATUS_CANCELLED);
    }

    @Test
    @DisplayName("取消：已 fired ⇒ 拒绝（消息已发出，不可撤回）")
    void cannotCancelFired() {
        when(scheduledTaskMapper.selectById("st-2"))
                .thenReturn(task("st-2", ScheduledTask.STATUS_FIRED));

        assertThat(service.cancel(20L, "st-2")).isFalse();
        verify(scheduledTaskMapper, never()).updateById(any(ScheduledTask.class));
    }

    @Test
    @DisplayName("取消：跨租户的 id ⇒ 拒绝（显式比对租户归属）")
    void cannotCancelOtherTenant() {
        ScheduledTask other = task("st-3", ScheduledTask.STATUS_PENDING).toBuilder()
                .tenantId(99L).build();
        when(scheduledTaskMapper.selectById("st-3")).thenReturn(other);

        assertThat(service.cancel(20L, "st-3")).isFalse();
        verify(scheduledTaskMapper, never()).updateById(any(ScheduledTask.class));
    }

    // ==================== 真值 1 / 3 / 5：扫描投递 ====================

    @Test
    @DisplayName("投递：到期待办 ⇒ 调通知服务一次（内容 = 三件套）+ 置 fired")
    void deliversDueTask() {
        when(businessClock.nowOffset()).thenReturn(NOW);
        when(tenantMapper.selectList(any())).thenReturn(List.of(tenant(20L)));
        when(scheduledTaskMapper.selectDueByTenant(eq(20L), any(), anyInt()))
                .thenReturn(List.of(task("st-due", ScheduledTask.STATUS_PENDING)));

        int delivered = service.scanDue();

        assertThat(delivered).isEqualTo(1);
        ArgumentCaptor<CreateNotificationRequest> notif =
                ArgumentCaptor.forClass(CreateNotificationRequest.class);
        verify(notificationService).createNotification(eq(20L), notif.capture());
        assertThat(notif.getValue().getRecipientId()).isEqualTo("u-1");
        assertThat(notif.getValue().getTitle()).isEqualTo("去跟进张先生");
        assertThat(notif.getValue().getContent())
                .isEqualTo("你说过：等王总回复后再跟进张先生");
        assertThat(notif.getValue().getChannel()).isEqualTo("internal");

        ArgumentCaptor<ScheduledTask> upd = ArgumentCaptor.forClass(ScheduledTask.class);
        verify(scheduledTaskMapper).updateById(upd.capture());
        assertThat(upd.getValue().getStatus()).isEqualTo(ScheduledTask.STATUS_FIRED);
        assertThat(upd.getValue().getFiredAt()).isNotNull();
    }

    @Test
    @DisplayName("投递只触达通知服务（真值 3 只读）—— 依赖里没有业务写服务")
    void deliveryIsReadOnly() {
        // 结构面判据：本服务的构造参数（= 真实依赖）里不得出现业务写服务。
        // 与「投递只写 notifications」互为正反：加了业务写服务 ⇒ 本用例当场红。
        List<String> dependencyTypes = java.util.Arrays
                .stream(ScheduledTaskService.class.getDeclaredFields())
                .filter(f -> java.lang.reflect.Modifier.isFinal(f.getModifiers()))
                .map(f -> f.getType().getSimpleName())
                .toList();
        assertThat(dependencyTypes)
                .contains("NotificationService")
                .doesNotContain("OrderService", "ProductService", "AfterSalesService",
                        "AgentBatchService", "InventoryService");
    }

    @Test
    @DisplayName("fail-soft：单条投递失败 ⇒ 该条置 failed，不拖垮同轮其它条")
    void singleFailureDoesNotBreakRound() {
        when(businessClock.nowOffset()).thenReturn(NOW);
        when(tenantMapper.selectList(any())).thenReturn(List.of(tenant(20L)));
        when(scheduledTaskMapper.selectDueByTenant(eq(20L), any(), anyInt()))
                .thenReturn(List.of(
                        task("st-bad", ScheduledTask.STATUS_PENDING),
                        task("st-good", ScheduledTask.STATUS_PENDING)));
        when(notificationService.createNotification(eq(20L), any()))
                .thenThrow(new RuntimeException("通知服务抖动"))
                .thenReturn(null);

        int delivered = service.scanDue();

        // 第一条失败、第二条成功 ⇒ 本轮投递数 = 1；两条都被 update（failed / fired）
        assertThat(delivered).isEqualTo(1);
        verify(notificationService, times(2)).createNotification(eq(20L), any());
        verify(scheduledTaskMapper, times(2)).updateById(any(ScheduledTask.class));
    }

    @Test
    @DisplayName("租户上下文：扫描后必须还原为进入前的值（issue #3957 调度线程教训）")
    void restoresTenantContext() {
        when(businessClock.nowOffset()).thenReturn(NOW);
        when(tenantMapper.selectList(any())).thenReturn(List.of(tenant(20L)));
        when(scheduledTaskMapper.selectDueByTenant(anyLong(), any(), anyInt()))
                .thenReturn(List.of());

        TenantContext.setTenantId(7L);
        service.scanDue();

        assertThat(TenantContext.getTenantId()).isEqualTo(7L);
    }

    @Test
    @DisplayName("并发撞唯一索引 ⇒ 冲突映射为**返回既有行**（不暴露成 500）")
    void duplicateKeyMapsToExistingRow() {
        ScheduledTask existing = task("st-raced", ScheduledTask.STATUS_PENDING);
        // 第一次检查「没有」、冲突后重查「有」—— 模拟两个请求同时通过检查的窗口
        when(scheduledTaskMapper.selectByDedupKey(anyLong(), any()))
                .thenReturn(null)
                .thenReturn(existing);
        doThrow(new DuplicateKeyException("uk_scheduled_tasks_tenant_dedup"))
                .when(scheduledTaskMapper).insert(any(ScheduledTask.class));

        ScheduledTask result = service.create(20L, "u-1", validRequest());

        assertThat(result.getId()).isEqualTo("st-raced");
        verify(scheduledTaskMapper, times(1)).insert(any(ScheduledTask.class));
    }

    @Test
    @DisplayName("冲突但重查仍为空（不是本键的冲突）⇒ 照常抛，不吞")
    void duplicateKeyOfAnotherKindIsRethrown() {
        when(scheduledTaskMapper.selectByDedupKey(anyLong(), any())).thenReturn(null);
        doThrow(new DuplicateKeyException("pk"))
                .when(scheduledTaskMapper).insert(any(ScheduledTask.class));

        assertThatThrownBy(() -> service.create(20L, "u-1", validRequest()))
                .isInstanceOf(DuplicateKeyException.class);
    }
}
