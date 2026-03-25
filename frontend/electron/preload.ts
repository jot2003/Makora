import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  toggleOverlay: () => ipcRenderer.invoke('toggle-overlay'),
  onOverlayToggle: (callback: () => void) => {
    ipcRenderer.on('overlay-toggle', callback)
  },
})
