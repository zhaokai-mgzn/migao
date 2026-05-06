/**
 * Mock @tarojs/components
 *
 * 将 Taro 组件映射为 HTML 元素，供 @testing-library/react 渲染
 */
import React from 'react'

// 通用包装：把 className 透传给 div/span 等
function createComponent(tag: string) {
  const Component = React.forwardRef<any, any>(({ children, className, ...rest }, ref) => {
    return React.createElement(tag, { ref, className, ...rest }, children)
  })
  Component.displayName = tag.charAt(0).toUpperCase() + tag.slice(1)
  return Component
}

export const View = createComponent('div')
export const Text = createComponent('span')
export const Image = createComponent('img')
export const ScrollView = createComponent('div')
export const Input = React.forwardRef<any, any>(({ onInput, onConfirm, ...rest }, ref) => {
  return React.createElement('input', {
    ref,
    onChange: (e: any) => onInput?.({ detail: { value: e.target.value } }),
    onKeyDown: (e: any) => {
      if (e.key === 'Enter') onConfirm?.({ detail: { value: e.target.value } })
    },
    ...rest,
  })
})
Input.displayName = 'Input'

export const Textarea = React.forwardRef<any, any>(({ onInput, ...rest }, ref) => {
  return React.createElement('textarea', {
    ref,
    onChange: (e: any) => onInput?.({ detail: { value: e.target.value } }),
    ...rest,
  })
})
Textarea.displayName = 'Textarea'

export const Button = createComponent('button')
export const Navigator = createComponent('a')
export const Swiper = createComponent('div')
export const SwiperItem = createComponent('div')
export const RichText = createComponent('div')
export const Progress = createComponent('div')
export const Form = createComponent('form')
export const Label = createComponent('label')
export const Picker = createComponent('div')
export const Slider = createComponent('div')
export const Switch = createComponent('div')
export const Camera = createComponent('div')
export const Video = createComponent('video')
export const Map = createComponent('div')
export const CoverView = createComponent('div')
export const CoverImage = createComponent('img')
export const Block = React.Fragment
