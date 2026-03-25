import { create } from 'zustand'

type Theme = 'light' | 'dark'

interface ThemeState {
  theme: Theme
  toggle: () => void
  set: (t: Theme) => void
}

function getInitial(): Theme {
  if (typeof window === 'undefined') return 'dark'
  const stored = localStorage.getItem('theme') as Theme | null
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function apply(theme: Theme) {
  const root = document.documentElement
  root.classList.remove('light', 'dark')
  root.classList.add(theme)
  localStorage.setItem('theme', theme)
}

export const useTheme = create<ThemeState>((set) => {
  const initial = getInitial()
  apply(initial)

  return {
    theme: initial,
    toggle: () =>
      set((s) => {
        const next = s.theme === 'dark' ? 'light' : 'dark'
        apply(next)
        return { theme: next }
      }),
    set: (t) => {
      apply(t)
      set({ theme: t })
    },
  }
})
