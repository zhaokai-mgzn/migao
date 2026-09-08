// case_ids: PR-010
/**
 * 规格属性 key 中英双向映射（issue #3044）
 *
 * 背景：商品规格属性存在两种 key 风格——agent 建品用中文 key（克重/材质/功能/
 * 工艺/风格/图案）落库，手动表单用英文 key（weight/material/function/craft/style/
 * pattern）。详情页对未识别 key 原样展示（中文正常），但编辑页 ProductAttributes
 * 只读英文 key → agent 建的商品编辑时不反显。
 *
 * 约定：存储统一为中文 key（与 agent 一致，详情页天然中文展示）；
 * 编辑表单内部用英文 key（组件既有约定）。本模块负责边界双向转换：
 * - toEnglishSpecKeys：反显时 中文→英文（供编辑表单读取）
 * - toChineseSpecKeys：提交时 英文→中文（落库统一中文，未知 key 原样保留）
 */

import { describe, it, expect } from 'vitest'
import {
  toChineseSpecKeys,
  toEnglishSpecKeys,
} from '@/lib/attribute-keys'

describe('spec-keys 双向映射（issue #3044）', () => {
  it('toEnglishSpecKeys: agent 中文 key 规格 → 编辑表单英文 key', () => {
    const cn = {
      克重: '200-300g',
      材质: '涤纶',
      功能: '遮光',
      工艺: '色织',
      风格: '现代简约',
      图案: '纯色',
    }
    expect(toEnglishSpecKeys(cn)).toEqual({
      weight: '200-300g',
      material: '涤纶',
      function: '遮光',
      craft: '色织',
      style: '现代简约',
      pattern: '纯色',
    })
  })

  it('toEnglishSpecKeys: 未知 key 原样保留（不丢失数据）', () => {
    expect(toEnglishSpecKeys({ 克重: '200g', customAttr: '自定义值' })).toEqual({
      weight: '200g',
      customAttr: '自定义值',
    })
  })

  it('toChineseSpecKeys: 编辑表单英文 key → 落库中文 key（与 agent 一致）', () => {
    const en = {
      weight: '200-300g',
      material: '涤纶',
      function: '遮光',
      craft: '色织',
      style: '现代简约',
      pattern: '纯色',
    }
    expect(toChineseSpecKeys(en)).toEqual({
      克重: '200-300g',
      材质: '涤纶',
      功能: '遮光',
      工艺: '色织',
      风格: '现代简约',
      图案: '纯色',
    })
  })

  it('toChineseSpecKeys: 未知 key 原样保留', () => {
    expect(toChineseSpecKeys({ weight: '200g', customAttr: 'x' })).toEqual({
      克重: '200g',
      customAttr: 'x',
    })
  })

  it('空对象/空值幂等', () => {
    expect(toEnglishSpecKeys({})).toEqual({})
    expect(toChineseSpecKeys({})).toEqual({})
    expect(toEnglishSpecKeys(undefined as any)).toEqual({})
    expect(toChineseSpecKeys(undefined as any)).toEqual({})
  })
})
