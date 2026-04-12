import { createContext } from 'react'
import type { ThreadClient } from '../client/ThreadClient'
import type { ThreadStore } from '../store/threadStore'

export type ThreadContextValue = {
  client: ThreadClient
  store: ThreadStore
}

export const ThreadContext = createContext<ThreadContextValue | null>(null)
ThreadContext.displayName = 'ThreadContext'
