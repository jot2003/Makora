import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useAuth } from '@/stores/useAuth'

const { getState } = useAuth

describe('useAuth store', () => {
  beforeEach(() => {
    localStorage.clear()
    getState().logout()
  })

  it('starts with no user and no token after logout', () => {
    const s = getState()
    expect(s.token).toBeNull()
    expect(s.user).toBeNull()
  })

  it('getHeaders returns empty when no token', () => {
    expect(getState().getHeaders()).toEqual({})
  })

  it('getHeaders returns Authorization when token exists', () => {
    localStorage.setItem('token', 'abc123')
    useAuth.setState({ token: 'abc123' })
    expect(getState().getHeaders()).toEqual({ Authorization: 'Bearer abc123' })
  })

  it('logout clears token and user', () => {
    useAuth.setState({ token: 'xyz', user: { id: 1, email: 'a@b.c', username: 'u', avatar_url: '', provider: 'local', is_verified: true } })
    localStorage.setItem('token', 'xyz')

    getState().logout()
    expect(getState().token).toBeNull()
    expect(getState().user).toBeNull()
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('clearError resets error state', () => {
    useAuth.setState({ error: 'something broke' })
    getState().clearError()
    expect(getState().error).toBeNull()
  })

  it('login sets error on fetch failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')))
    const ok = await getState().login('a@b.c', 'pass')
    expect(ok).toBe(false)
    expect(getState().error).toBe('Server unreachable')
    vi.unstubAllGlobals()
  })

  it('login succeeds with valid response', async () => {
    const mockUser = { id: 1, email: 'a@b.c', username: 'u', avatar_url: '', provider: 'local', is_verified: true }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ token: 'tok', user: mockUser }),
    }))

    const ok = await getState().login('a@b.c', 'pass')
    expect(ok).toBe(true)
    expect(getState().token).toBe('tok')
    expect(getState().user?.email).toBe('a@b.c')
    vi.unstubAllGlobals()
  })

  it('register sets error on 409 conflict', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: 'Email already registered' }),
    }))

    const ok = await getState().register('a@b.c', 'user', 'password123')
    expect(ok).toBe(false)
    expect(getState().error).toBe('Email already registered')
    vi.unstubAllGlobals()
  })
})
