import { act, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ThreadClient } from '../../src/client/ThreadClient'
import { useThreadMembers } from '../../src/hooks/useThreadMembers'
import { ThreadContext } from '../../src/provider/ThreadContext'
import { createThreadStore } from '../../src/store/threadStore'

function Probe() {
  const members = useThreadMembers('th_1')
  return <div data-testid="count">{members.length}</div>
}

describe('useThreadMembers', () => {
  it('returns empty array when no members loaded', () => {
    const store = createThreadStore()
    const { getByTestId } = render(
      <ThreadContext.Provider value={{ client: {} as ThreadClient, store }}>
        <Probe />
      </ThreadContext.Provider>
    )
    expect(getByTestId('count').textContent).toBe('0')
  })

  it('reflects setMembers updates', () => {
    const store = createThreadStore()
    const { getByTestId } = render(
      <ThreadContext.Provider value={{ client: {} as ThreadClient, store }}>
        <Probe />
      </ThreadContext.Provider>
    )

    act(() => {
      store.getState().actions.setMembers('th_1', [
        { role: 'user', id: 'u1', name: 'Alice', metadata: {} },
        { role: 'assistant', id: 'a1', name: 'Helper', metadata: {} },
      ])
    })
    expect(getByTestId('count').textContent).toBe('2')

    act(() => {
      store
        .getState()
        .actions.setMembers('th_1', [{ role: 'user', id: 'u1', name: 'Alice', metadata: {} }])
    })
    expect(getByTestId('count').textContent).toBe('1')
  })

  it('returns the same reference for unchanged state (reference stability)', () => {
    const store = createThreadStore()
    const seen: Array<readonly unknown[]> = []
    function Probe2() {
      const members = useThreadMembers('th_1')
      seen.push(members)
      return null
    }
    const { rerender } = render(
      <ThreadContext.Provider value={{ client: {} as ThreadClient, store }}>
        <Probe2 />
      </ThreadContext.Provider>
    )
    rerender(
      <ThreadContext.Provider value={{ client: {} as ThreadClient, store }}>
        <Probe2 />
      </ThreadContext.Provider>
    )
    // Identical empty-array reference across renders (prevents
    // `useSyncExternalStore` infinite-loop detection).
    expect(seen[0]).toBe(seen[1])
  })
})
