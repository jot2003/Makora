/// <reference types="vite/client" />

interface Window {
  electronAPI?: {
    platform: string
    toggleOverlay: () => void
    onOverlayToggle: (callback: () => void) => void
  }
}
