package com.migao.admin.service;

import com.migao.admin.dto.CustomerImportField;

import java.util.List;
import java.util.Optional;

/**
 * 客户主数据迁移的 canonical 字段清单（issue #8295）。
 *
 * <p><b>为什么放服务端常量而不是让 AI 自由发挥</b>：AI 只做「旧表头 → 这里的 key」的映射建议；
 * 页面下拉、Mapping JSON 校验、落库字段全部由本清单决定。AI 返回清单外的 key 一律丢弃。</p>
 *
 * <p>V1 不导入授信额度/账期（涉钱口径，需单独裁定；见 issue #8295 的 P2）。</p>
 */
public final class CustomerImportFields {

    public static final List<CustomerImportField> ALL = List.of(
            new CustomerImportField("externalId", "旧系统客户ID", true, "string",
                    List.of("客户编号", "客户ID", "客户编码", "旧系统客户ID", "旧客户编号", "客户号", "编号", "编码")),
            new CustomerImportField("displayName", "客户名称", true, "string",
                    List.of("客户名称", "客户姓名", "客户名", "姓名", "名称", "购货单位", "单位名称", "客户")),
            new CustomerImportField("phone", "手机号", false, "string",
                    List.of("手机号", "手机号码", "手机", "电话", "联系电话", "联系方式", "客户电话")),
            new CustomerImportField("province", "省", false, "string",
                    List.of("省", "省份", "所在省")),
            new CustomerImportField("city", "市", false, "string",
                    List.of("市", "城市", "所在市")),
            new CustomerImportField("district", "区县", false, "string",
                    List.of("区", "区县", "县", "所在区")),
            new CustomerImportField("address", "地址", false, "string",
                    List.of("地址", "详细地址", "收货地址", "送货地址", "送货地点", "联系地址", "客户地址")),
            new CustomerImportField("receiverName", "收货人", false, "string",
                    List.of("收货人", "收货人姓名", "联系人")),
            new CustomerImportField("receiverPhone", "收货电话", false, "string",
                    List.of("收货人电话", "收货电话")),
            new CustomerImportField("vipLevel", "客户等级", false, "enum",
                    List.of("客户等级", "VIP等级", "VIP", "等级")),
            new CustomerImportField("agentNotes", "备注", false, "string",
                    List.of("备注", "说明", "客户备注"))
    );

    private CustomerImportFields() {
    }

    public static Optional<CustomerImportField> byKey(String key) {
        return ALL.stream().filter(f -> f.key().equals(key)).findFirst();
    }

    public static boolean isSupported(String key) {
        return byKey(key).isPresent();
    }
}
