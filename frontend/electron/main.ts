import { app, BrowserWindow, ipcMain, screen, Tray, Menu, nativeImage } from 'electron'
import path from 'path'
import fs from 'fs'

let mainWindow: BrowserWindow | null = null
let overlayWindow: BrowserWindow | null = null
let tray: Tray | null = null

const isDev = !app.isPackaged
const VITE_URL = 'http://localhost:5173'

const CONFIG_PATH = path.join(app.getPath('userData'), 'overlay-geometry.json')

function loadOverlayGeometry(): { x: number; y: number; width: number; height: number } | null {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'))
    }
  } catch {}
  return null
}

function saveOverlayGeometry() {
  if (!overlayWindow) return
  try {
    const bounds = overlayWindow.getBounds()
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(bounds))
  } catch {}
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'Meeting Copilot',
    backgroundColor: '#030712',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (isDev) {
    mainWindow.loadURL(VITE_URL)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  mainWindow.on('close', (e) => {
    if (tray && overlayWindow) {
      e.preventDefault()
      mainWindow?.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
    if (overlayWindow) {
      saveOverlayGeometry()
      overlayWindow.close()
      overlayWindow = null
    }
  })
}

function createOverlayWindow() {
  const saved = loadOverlayGeometry()
  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize

  const defaults = { width: 500, height: 300, x: screenW - 520, y: screenH - 320 }
  const geo = saved || defaults

  overlayWindow = new BrowserWindow({
    ...geo,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: true,
    focusable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  overlayWindow.setIgnoreMouseEvents(false)

  if (isDev) {
    overlayWindow.loadURL(`${VITE_URL}#/overlay`)
  } else {
    overlayWindow.loadFile(path.join(__dirname, '../dist/index.html'), { hash: '/overlay' })
  }

  overlayWindow.on('moved', () => saveOverlayGeometry())
  overlayWindow.on('resized', () => saveOverlayGeometry())
  overlayWindow.on('closed', () => { overlayWindow = null })
}

function createTray() {
  const iconPath = path.join(__dirname, '../assets/tray-icon.png')
  let icon: Electron.NativeImage

  try {
    if (fs.existsSync(iconPath)) {
      icon = nativeImage.createFromPath(iconPath)
    } else {
      icon = nativeImage.createEmpty()
    }
  } catch {
    icon = nativeImage.createEmpty()
  }

  tray = new Tray(icon)
  tray.setToolTip('Meeting Copilot')

  const contextMenu = Menu.buildFromTemplate([
    { label: 'Open', click: () => { mainWindow?.show(); mainWindow?.focus() } },
    { label: 'Toggle Overlay', click: () => { if (overlayWindow) { saveOverlayGeometry(); overlayWindow.close(); overlayWindow = null } else { createOverlayWindow() } } },
    { type: 'separator' },
    { label: 'Quit', click: () => { if (overlayWindow) saveOverlayGeometry(); app.quit() } },
  ])

  tray.setContextMenu(contextMenu)
  tray.on('double-click', () => { mainWindow?.show(); mainWindow?.focus() })
}

app.whenReady().then(() => {
  createMainWindow()
  createTray()

  ipcMain.handle('toggle-overlay', () => {
    if (overlayWindow) {
      saveOverlayGeometry()
      overlayWindow.close()
      overlayWindow = null
    } else {
      createOverlayWindow()
    }
    return !!overlayWindow
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (overlayWindow) saveOverlayGeometry()
})
