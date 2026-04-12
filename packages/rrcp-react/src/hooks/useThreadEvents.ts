import { useSyncExternalStore } from 'react'
import type { Event } from '../protocol/event'
import { useAcpStore } from './useAcpClient'

const EMPTY: Event[] = []

export function useThreadEvents(threadId: string | null): Event[] {
  const store = useAcpStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? (store.getState().events[threadId] ?? EMPTY) : EMPTY),
    () => (threadId ? (store.getState().events[threadId] ?? EMPTY) : EMPTY)
  )
}
