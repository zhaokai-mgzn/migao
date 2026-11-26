package com.migao.admin.service.kf;

/** 微信客服接口业务错误（errcode != 0）。 */
public class KfApiException extends RuntimeException {

    private final int errcode;

    public KfApiException(int errcode, String message) {
        super("wecom kf errcode=" + errcode + " msg=" + message);
        this.errcode = errcode;
    }

    public int getErrcode() {
        return errcode;
    }
}
