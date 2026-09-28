import { defineConfig, type UserConfigExport } from '@tarojs/cli'
import path from 'path'

export default defineConfig(async (merge) => {
  const baseConfig: UserConfigExport = {
    projectName: 'bmini-app',
    date: '2025-01-01',
    designWidth: 750,
    deviceRatio: {
      640: 2.34 / 2,
      750: 1,
      828: 1.81 / 2,
      375: 2 / 1,
    },
    sourceRoot: 'src',
    outputRoot: 'dist',
    plugins: [],
    // 显式定义 TARO_APP_* 环境变量替换（webpack DefinePlugin），不依赖 .env 文件：
    // Taro 的 dotenv 机制只注入 .env/.env.local 中的变量，CI 无 .env 文件时产物会残留
    // process.env 引用导致浏览器端 `process is not defined` 白屏（issue #2693）。
    defineConstants: {
      'process.env.TARO_APP_API_URL': JSON.stringify(process.env.TARO_APP_API_URL || ''),
      'process.env.TARO_APP_AI_API_URL': JSON.stringify(process.env.TARO_APP_AI_API_URL || ''),
    },
    copy: {
      patterns: [],
      options: {},
    },
    framework: 'react',
    compiler: 'webpack5',
    cache: {
      enable: false,
    },
    mini: {
      postcss: {
        pxtransform: {
          enable: true,
          config: {},
        },
        cssModules: {
          enable: false,
          config: {
            namingPattern: 'module',
            generateScopedName: '[name]__[local]___[hash:base64:5]',
          },
        },
      },
    },
    h5: {
      // 资源前缀（issue #5668）：B 端 h5 的落地面 = `app.migaozn.com` 静态根下的 **`/b/`**，
      // 而那个静态根**同时承载 C 端小布**（同一台 nginx、同一个 `location /`）。
      // 🔴 默认 `'/'` 时产物引用 `/js/app.js` —— 与 **C 端同名同路径**（实测两者产物都打成
      //    `js/app.js` + `css/app.css`）⇒ 浏览器会把 **C 端的包**加载进 bmini 页面：
      //    页面"打得开"，跑的却是另一个应用（静默串端，比 404 难发现得多）。
      // ⇒ 发布腿显式注入 `TARO_APP_H5_PUBLIC_PATH=/b/`（CI）；本地 dev / 视觉回归保持 `'/'`
      //    逐字不变（同一份 config，不为发布引入第二条构建腿）。
      publicPath: process.env.TARO_APP_H5_PUBLIC_PATH || '/',
      staticDirectory: 'static',
      postcss: {
        autoprefixer: {
          enable: true,
          config: {},
        },
        cssModules: {
          enable: false,
          config: {
            namingPattern: 'module',
            generateScopedName: '[name]__[local]___[hash:base64:5]',
          },
        },
      },
    },
    alias: {
      '@': path.resolve(__dirname, '..', 'src'),
    },
  }
  return baseConfig
})
