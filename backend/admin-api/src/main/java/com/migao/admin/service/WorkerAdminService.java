package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.regex.Pattern;

/**
 * 工人档案建号／列表（issue #4869）—— **首个工人怎么建出来**。
 *
 * <p><b>要治的形态</b>：工人档案的定义是 {@code users.worker_no IS NOT NULL AND role='worker'}
 * （V98 的部分唯一索引 {@code uk_users_tenant_worker_no}），而改前**全仓零写入方**
 * ⇒ 「工号 + PIN 登录」（#4733，已落码且已可用）在真实部署里<b>永远没有可登录的对象</b>。
 * 本类补的就是那个唯一的写入方。</p>
 *
 * <p><b>为什么不复用 {@code UserService.createUser}</b>：那条路径是**员工**语义 ——
 * 强制 {@code phone} 非空、写 {@code position}／权限快照、关联 {@code user_roles}、
 * 可置强制改密。工人**不是员工**：没有菜单权限、没有登录用户名、不进管理后台
 * ⇒ 塞进员工语义只会让两侧都失真（「看起来像员工」正是本单要避免的）。</p>
 *
 * <p><b>四条硬约束（每条都有断言，见 {@code WorkerAdminServiceTest}）</b>：</p>
 * <ol>
 *   <li><b>零商家权限</b>：只落 {@code role=worker}，{@code permissions}／{@code username}／
 *       {@code must_change_password} 一律不设；本类**结构上没有**任何角色/权限写入依赖
 *       （不注入 {@code RoleService}／{@code RoleMapper}／{@code UserRoleMapper}）⇒ 写不出
 *       {@code user_roles} 行；「能不能进管理后台」由 {@code SecurityConfig} 的
 *       {@code ADMIN_API_REJECTED_ROLES}（含 {@code worker}）拒绝，**不在这里另造判定**；</li>
 *   <li><b>工号租户内唯一，冲突 fail-closed</b>：先查后插 + 唯一索引撞车兜底，两种路径都是
 *       **409 + 说清是哪个工号 + 给出出口**（不是 500、更不是静默建第二个）；</li>
 *   <li><b>PIN 走 BCrypt</b>，与登录侧 {@code passwordEncoder.matches} 同一套编码；</li>
 *   <li><b>归属租户</b>：{@code tenant_id} 取当前租户上下文，读取面靠既有租户拦截器隔离
 *       ⇒ 别个租户用同一工号也查不到这一行。</li>
 * </ol>
 *
 * <p><b>为什么 PIN 限定 4~12 位数字</b>：工人端 PIN 输入框是数字键盘
 * （{@code frontend/worker-h5/src/render.mjs} 的 {@code inputmode="numeric"}）⇒ 建一个含字母的
 * PIN 等于建一个**登不进的账号**，必须在建号时就拒（fail-closed，而不是等工人报障）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerAdminService {

    /**
     * 工人角色码 —— 与 {@code WorkerSessionService.WORKER_ROLE} **同一字面量**。
     *
     * <p>三处必须一致（建号 / 登录 / 门禁拒绝集合），任一处漂移都是事故：写错了 ⇒ 建出来的档案
     * 登录侧不认（工人登不进）；或门禁不拒（工人可进管理后台）。
     * 判据 = {@code WorkerAdminServiceTest#workerRoleLiteralIsSingleSource} +
     * {@code AdminApiWorkerRoleGateTest#workerArchiveRoleIsDeniedAtTheGate}。</p>
     */
    public static final String WORKER_ROLE = "worker";

    /** PIN 形态：工人端是数字键盘 ⇒ 只认数字；4~12 位（6 位为主流，下界防「1 位 PIN」）。 */
    private static final Pattern PIN_PATTERN = Pattern.compile("\\d{4,12}");

    /** 工号长度上限（与 {@code users.worker_no VARCHAR(64)} 同宽）。 */
    private static final int MAX_WORKER_NO_LENGTH = 64;

    /** 姓名长度上限（与 {@code users.nickname VARCHAR(128)} 同量级，留足余量）。 */
    private static final int MAX_NAME_LENGTH = 64;

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;

    /**
     * 建一个工人档案（**本单的核心交付**）。
     *
     * @param workerNo 工号（租户内唯一；由管理员对着纸质工牌录入，首尾空白规整后落库）
     * @param name     工人姓名（报工页页头「当前工人：张三」显示的就是它）
     * @param pin      PIN（明文，仅用于 BCrypt 编码，不落日志；工人端数字键盘 ⇒ 4~12 位数字）
     * @return 新建的档案（{@code passwordHash} 已清空，与 {@code UserService.createUser} 同口径）
     * @throws BusinessException 422 入参非法 / 409 工号已被占用（两种都是**明确拒绝**）
     */
    @Transactional(rollbackFor = Exception.class)
    public User createWorker(String workerNo, String name, String pin) {
        Long tenantId = TenantContext.getTenantId();
        if (tenantId == null) {
            throw BusinessException.tenantInvalid();
        }

        String no = workerNo == null ? "" : workerNo.trim();
        if (no.isEmpty()) {
            throw BusinessException.validationError("工号不能为空");
        }
        if (no.length() > MAX_WORKER_NO_LENGTH) {
            throw BusinessException.validationError("工号不能超过 " + MAX_WORKER_NO_LENGTH + " 个字符");
        }
        String workerName = name == null ? "" : name.trim();
        if (workerName.isEmpty()) {
            throw BusinessException.validationError("工人姓名不能为空");
        }
        if (workerName.length() > MAX_NAME_LENGTH) {
            throw BusinessException.validationError("工人姓名不能超过 " + MAX_NAME_LENGTH + " 个字符");
        }
        String normalizedPin = pin == null ? "" : pin.trim();
        if (!PIN_PATTERN.matcher(normalizedPin).matches()) {
            throw BusinessException.validationError(
                    "PIN 必须是 4~12 位数字（工人端 PIN 输入框是数字键盘，含字母的 PIN 工人打不出来）");
        }

        assertWorkerNoAvailable(no);

        // 刻意**不**设：phone（工人不用手机号登录）／username（那是员工登录名，V128）／
        // permissions（工人零菜单权限）／position／mustChangePassword（工人没有可改的密码语义，
        // 置 true 会让这个账号被强制改密流程永久锁死）。
        User worker = User.builder()
                .tenantId(tenantId)
                .workerNo(no)
                .nickname(workerName)
                .role(WORKER_ROLE)
                .passwordHash(passwordEncoder.encode(normalizedPin))
                .status("active")
                .build();

        try {
            userMapper.insert(worker);
        } catch (DuplicateKeyException e) {
            // 数据库唯一索引是**并发下的兜底**（两个请求同时通过应用层校验时挡不住）
            throw duplicateWorkerNo(no);
        }

        log.info("[工人档案] 建号成功：tenantId={}, workerNo={}, workerId={}", tenantId, no, worker.getId());
        worker.setPasswordHash(null);
        return worker;
    }

    /**
     * 列工人档案（分页）—— 与员工列表**分开**：工人不混进员工列表
     * （{@code UserService.getUserPage} 已显式排除 {@code role=worker}）。
     *
     * @param keyword 关键词（工号 / 姓名 —— 管理员手上有的往往就是工牌上那串工号）
     * @param status  状态（active / disabled；停用/启用复用 {@code PUT /api/admin/users/{id}/status}）
     */
    public PageResponse<User> listWorkers(long page, long size, String keyword, String status) {
        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
        // 工人档案 = role=worker（worker_no 非空是同一件事的另一种说法，见 V98 的列注释）
        wrapper.eq(User::getRole, WORKER_ROLE);
        if (StringUtils.hasText(status)) {
            wrapper.eq(User::getStatus, status.trim());
        }
        if (StringUtils.hasText(keyword)) {
            String kw = keyword.trim();
            wrapper.and(w -> w.like(User::getWorkerNo, kw).or().like(User::getNickname, kw));
        }
        wrapper.orderByDesc(User::getCreatedAt);

        Page<User> resultPage = userMapper.selectPage(new Page<>(page, size), wrapper);
        // 脱敏：绝不把 PIN 的哈希下发到浏览器（与员工列表同口径）
        resultPage.getRecords().forEach(u -> u.setPasswordHash(null));
        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(),
                resultPage.getRecords());
    }

    /** 工号可用性（应用层先查一次 ⇒ 冲突时给得出「是哪个工号」；并发仍由唯一索引兜底）。 */
    private void assertWorkerNoAvailable(String workerNo) {
        User existing = userMapper.selectOne(new LambdaQueryWrapper<User>()
                .eq(User::getWorkerNo, workerNo)
                .last("LIMIT 1"));
        if (existing != null) {
            throw duplicateWorkerNo(workerNo);
        }
    }

    /** 工号冲突：**说清是哪个工号 + 给出可执行出口**（fail-closed，不静默改号、不覆盖已有档案）。 */
    private BusinessException duplicateWorkerNo(String workerNo) {
        return BusinessException.conflict(
                "工号已被占用：" + workerNo + "（工号在您的企业内必须唯一）",
                "换一个工号；若这位工人已有档案，请在「工人档案」列表里按工号找到它"
                        + "（停用的档案可重新启用），不要重复建号 —— 重复建号会把报工记到两个身份上");
    }
}
