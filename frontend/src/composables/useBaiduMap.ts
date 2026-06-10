/**
 * 百度地图 JS API 加载器。
 *
 * 通过动态注入 <script> 异步加载百度地图 JS API（GL 版本），
 * 全局只加载一次（多次调用复用同一 Promise）。
 *
 * 脚手架阶段仅提供加载能力与状态；实际地图初始化、画线、打点等
 * 在后续业务页面基于返回的全局 BMapGL 实现。
 */
import { ref } from 'vue'

const BAIDU_MAP_AK = import.meta.env.VITE_BAIDU_MAP_AK || ''

// 全局加载 Promise，确保脚本只注入一次
let loadPromise: Promise<void> | null = null

// 百度地图回调函数名（挂在 window 上，供 JS API 加载完成后触发）
const CALLBACK_NAME = '__onBMapGLLoaded__'

function injectScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!BAIDU_MAP_AK) {
      reject(new Error('未配置百度地图 AK（VITE_BAIDU_MAP_AK）'))
      return
    }

    // 已加载完成
    if (typeof window !== 'undefined' && (window as any).BMapGL) {
      resolve()
      return
    }

    // 注册全局回调
    ;(window as any)[CALLBACK_NAME] = () => {
      resolve()
    }

    const script = document.createElement('script')
    script.type = 'text/javascript'
    script.src =
      `https://api.map.baidu.com/api?type=webgl&v=1.0` +
      `&ak=${BAIDU_MAP_AK}&callback=${CALLBACK_NAME}`
    script.onerror = () => reject(new Error('百度地图 JS API 脚本加载失败'))
    document.head.appendChild(script)
  })
}

/**
 * 加载百度地图 JS API。
 *
 * @returns 加载状态与加载方法
 */
export function useBaiduMap() {
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref<string | null>(null)

  async function load(): Promise<void> {
    if (loaded.value) return

    loading.value = true
    error.value = null
    try {
      if (!loadPromise) {
        loadPromise = injectScript()
      }
      await loadPromise
      loaded.value = true
    } catch (e) {
      loadPromise = null // 失败后允许重试
      error.value = e instanceof Error ? e.message : String(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  return { loading, loaded, error, load }
}
