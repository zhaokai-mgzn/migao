package com.migao.admin.service.kf;

/** 媒体归档失败（下载 / 落盘 / 落行任一环节）。调用方按「消息优先」容忍。 */
public class KfMediaException extends RuntimeException {

    public KfMediaException(String message, Throwable cause) {
        super(message, cause);
    }

    public KfMediaException(String message) {
        super(message);
    }
}
