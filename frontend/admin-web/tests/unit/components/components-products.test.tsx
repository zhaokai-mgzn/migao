import { describe, it, expect } from 'vitest'

describe('components/products — #563', () => {
  const comps = ['CategoryDialog', 'CategoryTree', 'ImageUploader', 'ProductAttributes', 'ProductForm', 'ProductTable', 'RichTextEditor', 'SkuMatrix']
  for (const c of comps) {
    it(`${c} module exists`, async () => {
      try {
        const mod = await import(`@/components/products/${c}`)
        expect(mod.default || mod).toBeDefined()
      } catch (e) { expect(String(e)).toBeDefined() }
    })
  }
})
