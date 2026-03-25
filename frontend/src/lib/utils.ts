import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, 'ws')
  : `ws://${window.location.host}`
