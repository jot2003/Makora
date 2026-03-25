import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, AlertCircle } from 'lucide-react'
import { useAuth } from '@/stores/useAuth'

export default function AuthCallback() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { setToken } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const token = params.get('token')
    const err = params.get('error')

    if (err) {
      setError(decodeURIComponent(err))
      setTimeout(() => navigate('/login'), 4000)
      return
    }

    if (token) {
      setToken(token).then((ok) => {
        if (ok) {
          navigate('/')
        } else {
          setError('Invalid or expired token')
          setTimeout(() => navigate('/login'), 3000)
        }
      })
    } else {
      navigate('/login')
    }
  }, [])

  if (error) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-4">
        <div className="text-center animate-fade-in max-w-sm">
          <div className="w-12 h-12 rounded-2xl bg-red-500/10 flex items-center justify-center mx-auto mb-4">
            <AlertCircle className="w-6 h-6 text-red-500" />
          </div>
          <h2 className="text-lg font-semibold mb-2">Authentication Error</h2>
          <p className="text-sm text-muted-foreground mb-4">{error}</p>
          <p className="text-[11px] text-muted-foreground/60">Redirecting to login...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <div className="text-center animate-fade-in">
        <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto mb-3" />
        <p className="text-sm text-muted-foreground">Signing in...</p>
      </div>
    </div>
  )
}
