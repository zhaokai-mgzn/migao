'use client'

import { useState } from 'react'
import ProductForm from '@/components/products/ProductForm'
import ImageRecognizeButton from '@/components/image-recognize/ImageRecognizeButton'
import { productApi } from '@/lib/api'
import type { RecognizedField } from '@/lib/api'
import { buildProductPrefill } from '@/lib/image-recognize'
import type { ProductFormData } from '@/types'

export default function NewProductPage() {
  // 图片识别预填（issue #5321 包 1）：识别结果**只填表**，提交仍是人点「提交并上架」
  const [prefill, setPrefill] = useState<Partial<ProductFormData> | null>(null)
  const [recognizedFields, setRecognizedFields] = useState<string[]>([])

  const handleSubmit = async (data: ProductFormData) => {
    await productApi.createProduct(data)
  }

  const handleRecognized = (fields: RecognizedField[]) => {
    const next = buildProductPrefill(fields)
    setPrefill(next.initialData)
    setRecognizedFields(next.recognizedFields)
  }

  return (
    <>
      {/* 快通道入口：拍照/上传识别 → 字段候选（映射不到的键一律不填，见 lib/image-recognize.ts） */}
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
      />
    </>
  )
}
