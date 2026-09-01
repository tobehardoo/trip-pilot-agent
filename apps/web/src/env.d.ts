/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AMAP_WEB_JS_KEY?: string
  readonly VITE_AMAP_SECURITY_CODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
