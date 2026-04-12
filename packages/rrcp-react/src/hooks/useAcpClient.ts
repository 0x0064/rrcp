import { useContext } from 'react'
import { AcpContext } from '../provider/AcpContext'

export function useAcpClient() {
  const ctx = useContext(AcpContext)
  if (!ctx) throw new Error('useAcpClient must be used inside <AcpProvider>')
  return ctx.client
}

export function useAcpStore() {
  const ctx = useContext(AcpContext)
  if (!ctx) throw new Error('useAcpStore must be used inside <AcpProvider>')
  return ctx.store
}
