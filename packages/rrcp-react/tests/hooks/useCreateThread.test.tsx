import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ThreadClient } from '../../src/client/ThreadClient'
import { useCreateThread } from '../../src/hooks/useCreateThread'
import { ThreadContext } from '../../src/provider/ThreadContext'
import { createThreadStore } from '../../src/store/threadStore'

function wrapper(client: ThreadClient, qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ThreadContext.Provider value={{ client, store: createThreadStore() }}>
        {children}
      </ThreadContext.Provider>
    </QueryClientProvider>
  )
}

function Probe({
  onMutate,
}: {
  onMutate: (fn: (input: { tenant?: Record<string, string> }) => Promise<unknown>) => void
}) {
  const m = useCreateThread()
  onMutate(m.mutateAsync)
  return null
}

describe('useCreateThread', () => {
  it('creates a thread and invalidates the threads query', async () => {
    const client = {
      createThread: vi.fn().mockResolvedValue({
        id: 'th_new',
        tenant: { org: 'A' },
        metadata: {},
        createdAt: '2026-04-10T00:00:00Z',
        updatedAt: '2026-04-10T00:00:00Z',
      }),
    } as unknown as ThreadClient
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const Wrapper = wrapper(client, qc)

    let mutateAsync: ((i: { tenant?: Record<string, string> }) => Promise<unknown>) | null = null
    render(
      <Wrapper>
        <Probe
          onMutate={(fn) => {
            mutateAsync = fn
          }}
        />
      </Wrapper>
    )

    await waitFor(() => expect(mutateAsync).not.toBeNull())
    const result = (await mutateAsync!({ tenant: { org: 'A' } })) as { id: string }
    expect(result.id).toBe('th_new')
    expect(client.createThread).toHaveBeenCalledWith({ tenant: { org: 'A' } })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['acp', 'threads'] })
  })
})
