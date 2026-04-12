import { act, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ThreadClient } from '../../src/client/ThreadClient'
import { useThreadMetadata } from '../../src/hooks/useThreadMetadata'
import { ThreadContext } from '../../src/provider/ThreadContext'
import { createThreadStore } from '../../src/store/threadStore'

const fakeThread = {
  id: 'th_1',
  tenant: { org: 'A' },
  metadata: { title: 'First' },
  createdAt: '2026-04-10T00:00:00Z',
  updatedAt: '2026-04-10T00:00:00Z',
}

function Probe() {
  const t = useThreadMetadata('th_1')
  return <div data-testid="title">{t ? String(t.metadata.title ?? '') : 'none'}</div>
}

describe('useThreadMetadata', () => {
  it('returns null when no thread is in the store', () => {
    const store = createThreadStore()
    const { getByTestId } = render(
      <ThreadContext.Provider value={{ client: {} as ThreadClient, store }}>
        <Probe />
      </ThreadContext.Provider>
    )
    expect(getByTestId('title').textContent).toBe('none')
  })

  it('reflects store updates', () => {
    const store = createThreadStore()
    const { getByTestId } = render(
      <ThreadContext.Provider value={{ client: {} as ThreadClient, store }}>
        <Probe />
      </ThreadContext.Provider>
    )

    act(() => {
      store.getState().actions.setThreadMeta(fakeThread)
    })
    expect(getByTestId('title').textContent).toBe('First')

    act(() => {
      store.getState().actions.setThreadMeta({ ...fakeThread, metadata: { title: 'Renamed' } })
    })
    expect(getByTestId('title').textContent).toBe('Renamed')
  })
})
