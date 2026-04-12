import { useMemo, useSyncExternalStore } from 'react'
import type { Run } from '../protocol/run'
import { useThreadStore } from './useThreadClient'

const EMPTY: Run[] = []

export function useThreadActiveRuns(threadId: string | null): Run[] {
  const store = useThreadStore()
  const runs = useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? store.getState().activeRuns[threadId] : undefined),
    () => undefined
  )
  return useMemo(() => (runs ? Object.values(runs) : EMPTY), [runs])
}
