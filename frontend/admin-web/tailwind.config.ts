import type { Config } from 'tailwindcss'

/**
 * 经营看板「织物质感」设计 token（issue #2534 子任务 A）。
 * primary/accent/neutral 三组各为完整 50-900 阶，替换原有单一默认蓝 primary。
 * 设计依据：ershen/design/20-migao-ui-redesign.md。
 */
const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eef2f8',
          100: '#d9e2ef',
          200: '#b3c4de',
          300: '#8ba4c7',
          400: '#6a84ac',
          500: '#48618f',
          600: '#3a4e75',
          700: '#2e3d5c',
          800: '#232e46',
          900: '#191f31',
        },
        accent: {
          50: '#faf0ea',
          100: '#f3dccd',
          200: '#e7b99d',
          300: '#d9966f',
          400: '#cc8056',
          500: '#c06a3e',
          600: '#a05531',
          700: '#804426',
          800: '#5f331c',
          900: '#402314',
        },
        neutral: {
          50: '#faf7f2',
          100: '#f2ede5',
          200: '#e6dfd3',
          300: '#d4c9b8',
          400: '#b8aa94',
          500: '#9c8c72',
          600: '#7e6f57',
          700: '#625545',
          800: '#484036',
          900: '#312c26',
        },
      },
    },
  },
  plugins: [],
}

export default config
