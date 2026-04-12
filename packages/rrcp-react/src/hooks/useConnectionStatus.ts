import { useSyncExternalStore } from 'react'
import { useAcpStore } from './useAcpClient'

export function useConnectionStatus() {
  const store = useAcpStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => store.getState().connectionStatus,
    () => store.getState().connectionStatus
  )
}
