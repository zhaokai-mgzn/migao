package com.migao.admin.service;

import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.mapper.ProcessingOrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * 加工单级**公开短链**（{@code GET /o/{shortCode}}）的解析层（issue #6867 / 实现包 B2；设计
 * {@code docs/design/worker-h5-scan-and-report.md} §11.3 / §11.6）。
 *
 * <h2>它做什么（只有两件事）</h2>
 * ① **形态归一 + 合法性判定**：复用 {@link WorkerShortLinkService#normalize}（同一份
 * 8 位 Crockford Base32 口径与 {@code O→0} / {@code I/L→1} 抄错别名）⇒ 形态不合法返回空串；
 * ② **跨租户解析**：短码**全局唯一**（部分唯一索引 {@code uk_processing_orders_short_code}）
 * ⇒ 租户由短码本身解出（设计 §11.6 与 {@code /s/} 同款）。
 *
 * <h2>为什么必须跨租户查（{@code @InterceptorIgnore}）</h2>
 * 本入口是**公开**的（无 JWT、无工人 session）⇒ {@code TenantContext} 为空 ⇒ 多租户拦截器会抛
 * {@code Tenant context not initialized} ⇒ 纸上的码恒 500。绕过的安全性由**部分唯一索引**兜底
 * （列级、与租户无关）⇒ 最多命中一行，**不会**把别的租户的行混进来。
 * 同款手法见 {@code ProcessingSetPartTokenMapper.selectByShortCode} 与 {@code UserMapper}。
 *
 * <h2>边界（如实登记）</h2>
 * 本类**不**分配短码（分配在 B1 的 {@code ProductionService.ensureShortCode} 里，复用
 * {@link WorkerShortLinkService#allocateUnique}）、**不**写任何列（公开入口只读：撤销/重新发码
 * 都走管理面，见 {@code ProcessingOrderMapper.revokeQrToken} 与 {@code fillMissingShortCode}）、
 * **不**返回任何业务字段（只交出一行给控制器判 302/404/410）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingOrderShortLinkService {

    private final ProcessingOrderMapper processingOrderMapper;

    /**
     * 短码 ⇒ 承载行（**跨租户**：短码全局唯一，租户由短码本身解出）。
     *
     * @param rawCode 短码（手输形态会自动归一化）
     * @return 命中行（{@code qrToken} 为 {@code null} = 已撤销）；未知 / 形态不合法 ⇒ {@code null}
     */
    public ProcessingOrder resolve(String rawCode) {
        String code = WorkerShortLinkService.normalize(rawCode);
        if (code.isEmpty()) {
            return null;
        }
        return processingOrderMapper.selectByShortCodeGlobal(code);
    }
}
