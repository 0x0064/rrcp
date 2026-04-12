import { useSyncExternalStore } from 'react'
import type { Thread } from '../protocol/thread'
import { useAcpStore } from './useAcpClient'

export function useThreadMetadata(threadId: string | null): Thread | null {
  const store = useAcpStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? (store.getState().threadMeta[threadId] ?? null) : null),
    () => (threadId ? (store.getState().threadMeta[threadId] ?? null) : null)
  )
}
