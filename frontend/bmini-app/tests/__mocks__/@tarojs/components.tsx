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
export const Input = React.forwardRef<any, any>(({ onInput, onConfirm, password, ...rest }, ref) => {
  return React.createElement('input', {
    ref,
    ...rest,
    // Taro 的 `password` 是布尔属性（小程序侧＝遮蔽输入）；HTML 侧对应 type="password"。
    // 不映射的话「密码框是否遮蔽」在测试里完全不可见（断言会退化成恒真）。
    type: rest.type || (password ? 'password' : undefined),
    onChange: (e: any) => onInput?.({ detail: { value: e.target.value } }),
    onKeyDown: (e: any) => {
      if (e.key === 'Enter') onConfirm?.({ detail: { value: e.target.value } })
    },
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

export const Button = React.forwardRef<any, any>(
  ({ children, onClick, onAgreePrivacyAuthorization, openType, ...rest }, ref) => {
    // `open-type='agreePrivacyAuthorization'` 的按钮：小程序在用户点按后回调
    // `bindagreeprivacyauthorization`（Taro 侧 = `onAgreePrivacyAuthorization`）。DOM 没有这个事件
    // ⇒ mock 在同一次点击里补上，否则「点同意 ⇒ resolve({event:'agree',buttonId})」这条判据
    // 只能靠读源码（假绿）。issue #9011。
    return React.createElement(
      'button',
      {
        ref,
        ...rest,
        // 与 WXML 同名（`open-type`）：写成 `openType` 会触发 React 的 unknown-prop 告警
        ...(openType ? { 'open-type': openType } : {}),
        onClick: (e: any) => {
          onClick?.(e)
          onAgreePrivacyAuthorization?.(e)
        },
      },
      children,
    )
  },
)
Button.displayName = 'Button'
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
