import { act, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AcpClient } from '../../src/client/AcpClient'
import { useThreadMembers } from '../../src/hooks/useThreadMembers'
import { AcpContext } from '../../src/provider/AcpContext'
import { createThreadStore } from '../../src/store/threadStore'

function Probe() {
  const members = useThreadMembers('th_1')
  return <div data-testid="count">{members.length}</div>
}

describe('useThreadMembers', () => {
  it('returns empty array when no members loaded', () => {
    const store = createThreadStore()
    const { getByTestId } = render(
      <AcpContext.Provider value={{ client: {} as AcpClient, store }}>
        <Probe />
      </AcpContext.Provider>
    )
    expect(getByTestId('count').textContent).toBe('0')
  })

  it('reflects setMembers updates', () => {
    const store = createThreadStore()
    const { getByTestId } = render(
      <AcpContext.Provider value={{ client: {} as AcpClient, store }}>
        <Probe />
      </AcpContext.Provider>
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
      <AcpContext.Provider value={{ client: {} as AcpClient, store }}>
        <Probe2 />
      </AcpContext.Provider>
    )
    rerender(
      <AcpContext.Provider value={{ client: {} as AcpClient, store }}>
        <Probe2 />
      </AcpContext.Provider>
    )
    // Identical empty-array reference across renders (prevents
    // `useSyncExternalStore` infinite-loop detection).
    expect(seen[0]).toBe(seen[1])
  })
})
