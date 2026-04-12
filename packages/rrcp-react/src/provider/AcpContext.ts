import { createContext } from 'react'
import type { AcpClient } from '../client/AcpClient'
import type { ThreadStore } from '../store/threadStore'

export type AcpContextValue = {
  client: AcpClient
  store: ThreadStore
}

export const AcpContext = createContext<AcpContextValue | null>(null)
AcpContext.displayName = 'AcpContext'
