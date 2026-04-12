import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { AcpClient, type AcpClientOptions } from '../client/AcpClient'
import { toEvent, toIdentity, toRun, toThread } from '../protocol/mappers'
import { createThreadStore } from '../store/threadStore'
import { AcpContext, type AcpContextValue } from './AcpContext'

export type AcpProviderProps = AcpClientOptions & {
  children: ReactNode
  queryClient?: QueryClient
  fallback?: ReactNode
  errorFallback?: ReactNode
}

export function AcpProvider(props: AcpProviderProps) {
  const { children, queryClient: externalQc, fallback, errorFallback, ...clientOpts } = props
  const optsRef = useRef(clientOpts)
  const [value, setValue] = useState<AcpContextValue | null>(null)
  const [failed, setFailed] = useState(false)
  const qcRef = useRef<QueryClient>(externalQc ?? new QueryClient())

  useEffect(() => {
    const client = new AcpClient(optsRef.current)
    const store = createThreadStore()

    let cancelled = false
    const setup = async () => {
      store.getState().actions.setConnectionStatus('connecting')
      try {
        await client.connect()
        if (cancelled) return
        store.getState().actions.setConnectionStatus('connected')

        client.on('event', (data) => {
          store.getState().actions.addEvent(toEvent(data as never))
        })
        client.on('run:updated', (data) => {
          store.getState().actions.upsertRun(toRun(data as never))
        })
        client.on('thread:updated', (data) => {
          store.getState().actions.setThreadMeta(toThread(data as never))
        })
        client.on('members:updated', (data) => {
          const payload = data as { thread_id: string; members: unknown[] }
          const identities = payload.members.map((m) => toIdentity(m as never))
          store.getState().actions.setMembers(payload.thread_id, identities)
        })

        setValue({ client, store })
      } catch {
        if (cancelled) return
        store.getState().actions.setConnectionStatus('disconnected')
        setFailed(true)
      }
    }
    void setup()

    return () => {
      cancelled = true
      void client.disconnect()
      store.getState().actions.reset()
    }
  }, [])

  let body: ReactNode
  if (value) {
    body = <AcpContext.Provider value={value}>{children}</AcpContext.Provider>
  } else if (failed) {
    body = errorFallback ?? null
  } else {
    body = fallback ?? null
  }
  return <QueryClientProvider client={qcRef.current}>{body}</QueryClientProvider>
}
