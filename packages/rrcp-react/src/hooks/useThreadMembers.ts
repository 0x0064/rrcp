import { useSyncExternalStore } from 'react'
import type { Identity } from '../protocol/identity'
import { useAcpStore } from './useAcpClient'

const EMPTY: Identity[] = []

export function useThreadMembers(threadId: string | null): Identity[] {
  const store = useAcpStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? (store.getState().members[threadId] ?? EMPTY) : EMPTY),
    () => (threadId ? (store.getState().members[threadId] ?? EMPTY) : EMPTY)
  )
}
