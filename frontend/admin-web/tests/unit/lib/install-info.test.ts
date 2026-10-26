// case_ids: OR-070
/**
 * 安装信息的**软限**（issue #7856）—— 前端只这一个源（`@/lib/install-info`）。
 *
 * 为什么值得单独钉：服务端对超长是 **422 硬拒**（`OrderInstallInfo.normalizeCommunity` /
 * `normalizeRoom`），前端两个录入面（下单页 / 改单弹层）都靠这两个常量给 `maxLength`
 * ⇒ 这里一漂（比如有人把 40 改成 30），商家会先在浏览器里被砍掉合法内容，
 * 且**没有任何别的判据**会发现（Java 单测只钉后端那一份）。
 */
import { describe, it, expect } from 'vitest'
import { INSTALL_COMMUNITY_MAX_LENGTH, INSTALL_ROOM_MAX_LENGTH } from '@/lib/install-info'

describe('安装信息的软限（#7856）', () => {
  it('安装小区 40 字 / 安装位置 12 字 —— 与后端 `OrderInstallInfo` 同值', () => {
    expect(INSTALL_COMMUNITY_MAX_LENGTH).toBe(40)
    expect(INSTALL_ROOM_MAX_LENGTH).toBe(12)
  })

  it('位置上限恒严于小区上限（小区可带楼栋/单元/门牌，位置只是空间名）', () => {
    expect(INSTALL_ROOM_MAX_LENGTH).toBeLessThan(INSTALL_COMMUNITY_MAX_LENGTH)
  })
})
