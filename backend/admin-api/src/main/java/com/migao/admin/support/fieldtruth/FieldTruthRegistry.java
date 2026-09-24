package com.migao.admin.support.fieldtruth;

import com.migao.admin.entity.CustomerProfile;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 字段级真值声明的<b>注册表</b> —— 把「一张表的声明」升级为「一类表都要有声明」（issue #5362 / 铁律 8 类级固化）。
 *
 * <p>机制（判据见
 * {@code backend/admin-api/src/test/java/com/migao/admin/support/fieldtruth/}）：
 * <ol>
 *   <li><b>注册</b>：一张表进入本注册表 ⇒ 自动获得三条机械判据
 *       （① 实体每个字段都必须登记真值状态 + 原因；② 声明「有真值」⇒ 源码里存在真值级写入点；
 *       ③ 声明「无真值」⇒ 读面遮蔽清单里必须有它）；</li>
 *   <li><b>未登记即红</b>：注册表之外、又出现「列有常量 DEFAULT 且源码零写入」这种病征的表，
 *       会被类级元守卫按存量台账对账点名（台账只许缩短，涨跌都红）——
 *       新表/新字段<b>不会静默溜过</b>；</li>
 *   <li><b>新增一张表要付的代价</b>：写一份 {@link FieldTruth.Declaration} + 一份遮蔽清单，
 *       判据与元守卫自动生效，<b>不需要改判据代码</b>。</li>
 * </ol>
 *
 * <p>⚠️ 如实登记（§19.1）：本注册表目前只收了客户域第一张表（{@link CustomerProfileFieldTruth}）；
 * 其它域的同款病征由元守卫的存量台账冻结并点名，逐表收口路径见 issue #5362 的后续单（A1/A2）。
 */
public final class FieldTruthRegistry {

    private static final Map<Class<?>, FieldTruth.Declaration> BY_ENTITY = new LinkedHashMap<>();

    static {
        register(CustomerProfileFieldTruth.declaration());
    }

    private FieldTruthRegistry() {
    }

    /** 登记一张表（重复登记同一实体 ⇒ 显式报错，不静默覆盖）。 */
    public static void register(FieldTruth.Declaration declaration) {
        if (declaration == null) {
            throw new IllegalArgumentException("登记项不可为空");
        }
        FieldTruth.Declaration previous = BY_ENTITY.putIfAbsent(declaration.entity(), declaration);
        if (previous != null) {
            throw new IllegalStateException("实体 " + declaration.entity().getName()
                    + " 已登记真值声明（重复登记会让两份声明静默分叉）");
        }
    }

    /** 已登记的全部声明（按登记顺序）。 */
    public static Map<Class<?>, FieldTruth.Declaration> all() {
        return Map.copyOf(BY_ENTITY);
    }

    public static FieldTruth.Declaration declarationOf(Class<?> entity) {
        return BY_ENTITY.get(entity);
    }

    /** 便捷入口：客户档案（首个载体）。 */
    public static FieldTruth.Declaration customerProfile() {
        return declarationOf(CustomerProfile.class);
    }
}