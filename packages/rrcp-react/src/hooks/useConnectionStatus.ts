import { useSyncExternalStore } from 'react'
import { useThreadStore } from './useThreadClient'

export function useConnectionStatus() {
  const store = useThreadStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => store.getState().connectionStatus,
    () => store.getState().connectionStatus
  )
}
