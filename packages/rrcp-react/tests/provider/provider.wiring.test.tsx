import { QueryClient, useQueryClient } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { useContext } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Hoisted mock so the provider's `import { io } from 'socket.io-client'` sees our fake.
const { socketOn, socketOnce, socketDisconnect } = vi.hoisted(() => ({
  socketOn: vi.fn(),
  socketOnce: vi.fn(),
  socketDisconnect: vi.fn(),
}))

vi.mock('socket.io-client', () => ({
  io: vi.fn(() => ({
    on: socketOn,
    off: vi.fn(),
    once: (event: string, cb: (...args: unknown[]) => void) => {
      socketOnce(event, cb)
      if (event === 'connect') queueMicrotask(() => cb())
    },
    disconnect: socketDisconnect,
    emitWithAck: vi.fn(),
  })),
}))

import type { useAcpStore } from '../../src/hooks/useAcpClient'
import { AcpContext } from '../../src/provider/AcpContext'
import { AcpProvider } from '../../src/provider/AcpProvider'

function StoreProbe({ onStore }: { onStore: (s: ReturnType<typeof useAcpStore>) => void }) {
  const ctx = useContext(AcpContext)
  if (ctx) onStore(ctx.store)
  return null
}

describe('AcpProvider socket wiring', () => {
  beforeEach(() => {
    socketOn.mockClear()
    socketOnce.mockClear()
    socketDisconnect.mockClear()
  })

  it('routes thread:updated socket events into store.threadMeta', async () => {
    let captured: ReturnType<typeof useAcpStore> | null = null
    render(
      <AcpProvider url="http://x" authenticate={async () => ({})}>
        <StoreProbe
          onStore={(s) => {
            captured = s
          }}
        />
      </AcpProvider>
    )

    await waitFor(() => expect(captured).not.toBeNull())

    // Find the handler the provider registered for 'thread:updated'
    const call = socketOn.mock.calls.find(([event]) => event === 'thread:updated')
    expect(call).toBeDefined()
    const handler = (call as unknown as [string, (data: unknown) => void])[1]

    handler({
      id: 'th_1',
      tenant: { org: 'A' },
      metadata: { title: 'Hello' },
      created_at: '2026-04-10T00:00:00Z',
      updated_at: '2026-04-10T00:05:00Z',
    })

    const store = captured as unknown as ReturnType<typeof useAcpStore>
    expect(store.getState().threadMeta.th_1).toMatchObject({
      id: 'th_1',
      tenant: { org: 'A' },
      metadata: { title: 'Hello' },
      createdAt: '2026-04-10T00:00:00Z',
      updatedAt: '2026-04-10T00:05:00Z',
    })
  })

  it('routes members:updated socket events into store.members', async () => {
    let captured: ReturnType<typeof useAcpStore> | null = null
    render(
      <AcpProvider url="http://x" authenticate={async () => ({})}>
        <StoreProbe
          onStore={(s) => {
            captured = s
          }}
        />
      </AcpProvider>
    )

    await waitFor(() => expect(captured).not.toBeNull())

    const call = socketOn.mock.calls.find(([event]) => event === 'members:updated')
    expect(call).toBeDefined()
    const handler = (call as unknown as [string, (data: unknown) => void])[1]

    handler({
      thread_id: 'th_1',
      members: [
        { role: 'user', id: 'u1', name: 'Alice', metadata: {} },
        { role: 'assistant', id: 'a1', name: 'Helper', metadata: {} },
      ],
    })

    const store = captured as unknown as ReturnType<typeof useAcpStore>
    const members = store.getState().members.th_1
    expect(members).toHaveLength(2)
    expect(members?.[0]?.id).toBe('u1')
    expect(members?.[1]?.role).toBe('assistant')
  })
})

describe('AcpProvider TanStack Query integration', () => {
  it('uses the consumer-provided QueryClient when one is passed', async () => {
    const consumerQc = new QueryClient()
    let captured: unknown = null

    function QcProbe() {
      captured = useQueryClient()
      return null
    }

    render(
      <AcpProvider url="http://x" authenticate={async () => ({})} queryClient={consumerQc}>
        <QcProbe />
      </AcpProvider>
    )

    await waitFor(() => expect(captured).not.toBeNull())
    expect(captured).toBe(consumerQc)
  })

  it('creates a default QueryClient when none is passed', async () => {
    let captured: unknown = null
    function QcProbe() {
      captured = useQueryClient()
      return null
    }

    render(
      <AcpProvider url="http://x" authenticate={async () => ({})}>
        <QcProbe />
      </AcpProvider>
    )

    await waitFor(() => expect(captured).not.toBeNull())
    expect(captured).toBeInstanceOf(QueryClient)
  })
})
