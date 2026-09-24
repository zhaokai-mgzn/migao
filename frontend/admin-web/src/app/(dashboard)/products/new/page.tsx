'use client'

import { useCallback, useEffect, useState } from 'react'
import ProductForm from '@/components/products/ProductForm'
import ImageRecognizeButton from '@/components/image-recognize/ImageRecognizeButton'
import { productApi } from '@/lib/api'
import type { RecognizedField } from '@/lib/api'
import { buildProductPrefill } from '@/lib/image-recognize'
import {
  PAGE_FILL_SOURCE_INTERPRETED,
  PAGE_FILL_SOURCE_RECOGNIZED,
  fieldsOfSource,
  subscribePageFill,
} from '@/lib/agent-page-fill'
import type { ProductFormData } from '@/types'

export default function NewProductPage() {
  // 图片识别预填：**一个内核、两个入口**（issue #5321 包 1 页面快通道 / issue #5368 包 2 深通道）
  // —— 识别结果**只填表**，提交仍是人点「提交并上架」。
  const [prefill, setPrefill] = useState<Partial<ProductFormData> | null>(null)
  const [recognizedFields, setRecognizedFields] = useState<string[]>([])
  const [interpretedFields, setInterpretedFields] = useState<string[]>([])

  const handleSubmit = async (data: ProductFormData) => {
    await productApi.createProduct(data)
  }

  /**
   * **两个入口共用同一份映射**（`buildProductPrefill`）⇒ 同一张图，快通道与深通道填同一组键
   * （只有一处映射表，不存在「两处必须一致」这种要靠人记的约定）。
   *
   * `interpretedKeys` = 米宝**解读/推荐**来源的键：它们进的是同一份 `initialData`，
   * 但**徽标不同**（`[米宝解读]`）—— 同一格只挂一枚，故从识别清单里摘掉。
   */
  const applyFields = useCallback((all: RecognizedField[], interpretedKeys: string[]) => {
    const next = buildProductPrefill(all)
    const interpreted = new Set(interpretedKeys)
    setPrefill(next.initialData)
    setRecognizedFields(next.recognizedFields.filter((key) => !interpreted.has(key)))
    setInterpretedFields(next.recognizedFields.filter((key) => interpreted.has(key)))
  }, [])

  /** 快通道回调（页面上那个「拍照 / 上传识别」按钮，**不依赖米宝**） */
  const handleRecognized = useCallback(
    (fields: RecognizedField[]) => applyFields(fields, []),
    [applyFields],
  )

  // 深通道（issue #5368 包 2）：米宝识别结果经 **SSE → store → 浏览器内存事件**推到本页
  // （浮动面板就在表单上方，不需要跳转）。两条口径与后端一致：
  //   ① 只收 `target_type=product` 的计划（别页的计划本页忽略）；
  //   ② 只收**值非空**的格子 —— 歧义格（有候选、值为空）**一格都不填**，由商家自己挑。
  useEffect(
    () =>
      subscribePageFill('product', (plan) => {
        applyFields(
          [
            ...fieldsOfSource(plan, PAGE_FILL_SOURCE_RECOGNIZED),
            ...fieldsOfSource(plan, PAGE_FILL_SOURCE_INTERPRETED),
          ],
          fieldsOfSource(plan, PAGE_FILL_SOURCE_INTERPRETED).map((field) => field.key),
        )
      }),
    [applyFields],
  )

  return (
    <>
      {/* 快通道入口：拍照/上传识别 → 字段候选（映射不到的键一律不填，见 lib/image-recognize.ts）。
          🔴 这条入口**不依赖米宝**（判据 5）：没有 LLM 也能用。 */}
      <div className="max-w-6xl mx-auto px-6 pt-4">
        <ImageRecognizeButton targetType="product" onRecognized={handleRecognized} />
      </div>
      {/* 未识别前 `initialData` 传 `undefined` —— `ProductForm` 以 `!!initialData` 判「编辑态」，
          传 `{}` 会让新增页标题变成「编辑商品」 */}
      <ProductForm
        initialData={prefill ?? undefined}
        onSubmit={handleSubmit}
        submitText="提交并上架"
        recognizedFields={recognizedFields}
        interpretedFields={interpretedFields}
      />
    </>
  )
}