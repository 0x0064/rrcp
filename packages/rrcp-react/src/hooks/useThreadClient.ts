import { useContext } from 'react'
import { ThreadContext } from '../provider/ThreadContext'

export function useThreadClient() {
  const ctx = useContext(ThreadContext)
  if (!ctx) throw new Error('useThreadClient must be used inside <ThreadProvider>')
  return ctx.client
}

export function useThreadStore() {
  const ctx = useContext(ThreadContext)
  if (!ctx) throw new Error('useThreadStore must be used inside <ThreadProvider>')
  return ctx.store
}
