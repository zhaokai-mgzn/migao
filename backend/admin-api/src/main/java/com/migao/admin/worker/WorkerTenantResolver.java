package com.migao.admin.worker;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.config.TenantDomainResolver;
import com.migao.admin.dto.WorkerLoginRequest;
import com.migao.admin.entity.Tenant;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.support.LoginIdentifiers;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Optional;

/**
 * 工人登录（`/api/worker/login` 与 `/api/worker/session/switch`）的**租户解析唯一实现点**（issue #6564）。
 *
 * <h2>要治的缺陷</h2>
 * 生产环境（`app.migaozn.com/b/`，租户 25 = 企业编码 `migao`）的工人登录恒 401：B 端 H5 前端
 * 只送 `workerNo + pin`（不送任何租户），Controller 回落 `request.getTenantId()` —— 而前端默认发
 * `DEFAULT_TENANT_ID = 1` ⇒ 租户谓词把 `tenant_id = 25` 的工人行过滤掉 ⇒ 查不到 ⇒ 401。
 *
 * <h2>解析优先级（从高到低）</h2>
 * <ol>
 *   <li>{@link TenantDomainResolver#resolve(HttpServletRequest)} —— 服务端可信来源
 *       （`X-Tenant-Id` 头 / `<tenantId>.app.migaozn.com` 子域）；</li>
 *   <li>body {@code enterpriseCode}（企业编码）⇒ {@code tenants}（{@code code = 规整后的编码}
 *       且 {@code status = 'active'}）拿 id；</li>
 *   <li>{@code workerNo} 含 {@code @} ⇒ {@code <工号>@<企业编码>}；</li>
 *   <li><b>兼容期兜底</b>：body {@code tenantId}（已发布的 H5 静态包会被浏览器缓存，删掉这一档会让
 *       车间 PAD 立刻登不进）—— 命中时打 {@code WARN}。这是**部署安全兜底，不是口径**；</li>
 *   <li>四档都拿不到 ⇒ {@code tenantId = null}（由 Controller 抛 422 可行动文案）。</li>
 * </ol>
 *
 * <p>🔴 <b>工号里的 {@code @企业编码} 后缀**先无条件剥掉**</b>（与租户走哪一档无关）：租户取自信任
 * 域名/网关头时，工人在工号框里顺手输 {@code cy-1001@migao} 也必须能登进来 —— 否则
 * {@code findWorkerByNo} 拿带后缀的串做等值匹配，租户明明对却仍 401。</p>
 *
 * <p><b>刻意不在这里抛异常、也不在这里计数</b>（与员工登录 #5485「标识不可解析不计数」同款出口）：
 * 解析不出租户 = 没有稳定的计数键，也不构成对某个账号的猜测。错误码的分流由
 * {@code WorkerAuthController} 按 {@link #tenantSourceAttempted(WorkerLoginRequest)} 决定。</p>
 *
 * <h2>为什么 ③ 不用 {@link LoginIdentifiers#split(String)}</h2>
 * 那个方法的契约是**员工登录标识** {@code <username>@<tenantCode>}：它把两侧都**转小写**，
 * 并按**员工用户名**正则 {@code ^[a-z0-9][a-z0-9._-]{2,31}$} 校验左侧。工号不是用户名 ——
 * {@code users.worker_no} 在 {@code WorkerAdminService.createWorker} 里**只限长度 ≤64、无字符集约束**
 * （现场是「对着纸质工牌录入」的形态，如 {@code CY-1001}、甚至含中文）⇒ 整体复用它会有两个真实缺陷：
 * ① 大写/中文工号被判「格式不合法」而登不进来；② 小写化后 {@code WorkerSessionService.findWorkerByNo}
 * （PG 里是**大小写敏感**的等值匹配）再也查不到那一行。故本类只复用**企业编码那一半**的口径
 * （{@link LoginIdentifiers#normalize} + {@link LoginIdentifiers#isValidTenantCode}），
 * 工号**原样保留**（只 {@code trim()}）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WorkerTenantResolver {

    private final TenantDomainResolver tenantDomainResolver;
    private final TenantMapper tenantMapper;

    /**
     * 解析结果。
     *
     * @param tenantId 解析出的租户 id；解析不出 ⇒ {@code null}（**不是**异常）
     * @param workerNo 实际工号 —— 带 {@code @企业编码} 后缀时已剥掉后缀，其余情况原样 {@code trim()}
     */
    public record ResolvedWorkerLogin(Long tenantId, String workerNo) {
    }

    /** 按上述优先级解析租户与工号；解析不出 ⇒ {@code tenantId = null}。 */
    public ResolvedWorkerLogin resolve(HttpServletRequest request, WorkerLoginRequest body) {
        String rawWorkerNo = body.getWorkerNo() == null ? "" : body.getWorkerNo().trim();
        // 后缀剥离与「租户走哪一档」无关：先剥，再定租户（见类注释的红字）
        String[] parts = splitWorkerIdentifier(rawWorkerNo);
        String workerNo = parts == null ? rawWorkerNo : parts[0];

        // ① 服务端可信来源（网关头 / 租户子域）—— 租户已定，后缀里的企业编码不参与判定
        Optional<Long> fromDomain = tenantDomainResolver.resolve(request);
        if (fromDomain.isPresent()) {
            return new ResolvedWorkerLogin(fromDomain.get(), workerNo);
        }

        // ② body 企业编码
        String bodyCode = LoginIdentifiers.normalize(body.getEnterpriseCode());
        if (bodyCode != null) {
            return new ResolvedWorkerLogin(tenantIdByCode(bodyCode), workerNo);
        }

        // ③ 工号@企业编码（切分口径见类注释）
        if (parts != null) {
            return new ResolvedWorkerLogin(tenantIdByCode(parts[1]), workerNo);
        }

        // ④ 兼容期兜底（部署安全，不是口径）
        if (body.getTenantId() != null) {
            log.warn("兼容期：按 body tenantId 解析租户，请升级前端到企业编码口径（issue #6564）tenantId={}",
                    body.getTenantId());
            return new ResolvedWorkerLogin(body.getTenantId(), workerNo);
        }

        // ⑤ 四档都拿不到
        return new ResolvedWorkerLogin(null, workerNo);
    }

    /**
     * 客户端**是否尝试**用企业编码定位租户（反枚举分流，issue #6564 / 与 #5485 同口径）。
     *
     * <p>尝试过但解析不出 ⇒ 与「工号不存在 / PIN 错」返回**同一个 401 同一文案**（不泄露企业是否存在）；
     * 完全没提供任何租户来源 ⇒ 422（那是**可行动的输入缺失**，不是凭据错误）。
     * 判定用的 {@code @} 后缀必须是**合法企业编码形态**才算出「尝试过」—— 形态不合法的后缀按「未命中」
     * 处理（继续走 ④ 兼容兜底）。</p>
     */
    public boolean tenantSourceAttempted(WorkerLoginRequest body) {
        if (LoginIdentifiers.normalize(body.getEnterpriseCode()) != null) {
            return true;
        }
        String rawWorkerNo = body.getWorkerNo() == null ? "" : body.getWorkerNo().trim();
        return splitWorkerIdentifier(rawWorkerNo) != null;
    }

    /** 企业编码 ⇒ 租户 id（只在 {@code status = 'active'} 的租户里解析，照 {@code AuthService} 员工登录写法）。 */
    private Long tenantIdByCode(String code) {
        Tenant tenant = tenantMapper.selectOne(new LambdaQueryWrapper<Tenant>()
                .eq(Tenant::getCode, code)
                .eq(Tenant::getStatus, "active")
                .last("LIMIT 1"));
        return tenant == null ? null : tenant.getId();
    }

    /**
     * 切 {@code <工号>@<企业编码>}：按**最后一个** {@code @}（与 {@link LoginIdentifiers} 同规则），
     * 右侧走企业编码的**唯一实现点**校验，左侧**原样保留**（工号无字符集约束，且服务端按大小写敏感匹配）。
     *
     * @return {@code [工号, 企业编码]}；切不出/左侧为空/右侧非合法编码 ⇒ {@code null}（该档「未命中」）
     */
    private static String[] splitWorkerIdentifier(String rawWorkerNo) {
        int at = rawWorkerNo.lastIndexOf('@');
        if (at <= 0 || at == rawWorkerNo.length() - 1) {
            return null;
        }
        String workerNo = rawWorkerNo.substring(0, at).trim();
        String tenantCode = LoginIdentifiers.normalize(rawWorkerNo.substring(at + 1));
        if (workerNo.isEmpty() || !LoginIdentifiers.isValidTenantCode(tenantCode)) {
            return null;
        }
        return new String[]{workerNo, tenantCode};
    }
}
