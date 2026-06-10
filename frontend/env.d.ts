/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 前端 API 基础地址，默认走 Vite 代理的 /api */
  readonly VITE_API_BASE_URL?: string
  /** 百度地图 JS API 浏览器端 AK（按域名白名单申请，与后端 server AK 不同） */
  readonly VITE_BAIDU_MAP_AK?: string
  /** 开发代理后端目标地址，仅 vite.config.ts 使用 */
  readonly VITE_BACKEND_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
