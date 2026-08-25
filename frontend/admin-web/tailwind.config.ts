/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // 织物质感：靛蓝主色（替换默认蓝，全库不再使用默认蓝）
        primary: {
          50: '#eef1f6',
          100: '#d8dfe9',
          200: '#b3c0d4',
          300: '#8ba0bc',
          400: '#6883a6',
          500: '#48618f',
          600: '#3b4f74',
          700: '#303f5c',
          800: '#263147',
          900: '#1d2536',
        },
        // 织物质感：陶土点缀
        accent: {
          50: '#faf0e9',
          100: '#f3dccb',
          200: '#e6bd9e',
          300: '#d99b6c',
          400: '#cd7d4a',
          500: '#c06a3e',
          600: '#a25632',
          700: '#824327',
          800: '#65331e',
          900: '#4b2515',
        },
        // 织物质感：暖中性灰阶
        neutral: {
          50: '#faf7f2',
          100: '#f1ece4',
          200: '#e4ddd1',
          300: '#d3c9b9',
          400: '#b3a892',
          500: '#948a75',
          600: '#776e5d',
          700: '#5e574a',
          800: '#4a4439',
          900: '#38332b',
        },
      },
    },
  },
  plugins: [],
}
