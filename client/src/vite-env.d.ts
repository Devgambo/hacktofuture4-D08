/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the backend API. Empty string = same-origin (served behind nginx). */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
