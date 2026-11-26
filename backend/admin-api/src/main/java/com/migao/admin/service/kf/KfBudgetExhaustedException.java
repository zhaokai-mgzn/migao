package com.migao.admin.service.kf;

/** 48h / 5 条预算耗尽：必须停发，不能“先发再补”。 */
public class KfBudgetExhaustedException extends RuntimeException {
    public KfBudgetExhaustedException(String sessionId) {
        super("kf 发送预算耗尽: " + sessionId);
    }
}
