import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ThreadAuthError,
  ThreadClient,
  ThreadConflictError,
  ThreadHttpError,
  ThreadNotFoundError,
} from '../../src/client/ThreadClient'

const fakeThread = {
  id: 'th_1',
  tenant: { org: 'A' },
  metadata: {},
  created_at: '2026-04-10T00:00:00Z',
  updated_at: '2026-04-10T00:00:00Z',
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('ThreadClient REST', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let client: ThreadClient

  beforeEach(() => {
    fetchMock = vi.fn()
    client = new ThreadClient({
      url: 'http://localhost:8000',
      authenticate: async () => ({ headers: { authorization: 'Bearer xyz' } }),
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
  })

  it('createThread sends body and parses response', async () => {
    fetchMock.mockResolvedValue(jsonResponse(fakeThread, 201))
    const t = await client.createThread({ tenant: { org: 'A' } })
    expect(t.id).toBe('th_1')
    expect(t.createdAt).toBe('2026-04-10T00:00:00Z')

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('http://localhost:8000/acp/threads')
    expect((init as RequestInit).method).toBe('POST')
    const headers = (init as RequestInit).headers as Record<string, string>
    expect(headers.authorization).toBe('Bearer xyz')
    expect(headers['content-type']).toBe('application/json')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      tenant: { org: 'A' },
    })
  })

  it('sendMessage converts EventDraft to wire format', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          id: 'evt_1',
          thread_id: 'th_1',
          type: 'message',
          author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
          created_at: '2026-04-10T00:00:00Z',
          metadata: {},
          content: [{ type: 'text', text: 'hi' }],
          client_id: 'c1',
        },
        201
      )
    )
    const e = await client.sendMessage('th_1', {
      clientId: 'c1',
      content: [{ type: 'text', text: 'hi' }],
    })
    expect(e.type).toBe('message')
    expect(e.clientId).toBe('c1')

    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)
    expect(body.client_id).toBe('c1')
  })

  it('invoke maps assistantIds to assistant_ids', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          runs: [
            {
              id: 'run_1',
              thread_id: 'th_1',
              assistant: { role: 'assistant', id: 'a1', name: 'H', metadata: {} },
              triggered_by: { role: 'user', id: 'u1', name: 'A', metadata: {} },
              status: 'pending',
              started_at: '2026-04-10T00:00:00Z',
              metadata: {},
            },
          ],
        },
        201
      )
    )
    const result = await client.invoke('th_1', { assistantIds: ['a1'] })
    expect(result.runs).toHaveLength(1)
    expect(result.runs[0]!.threadId).toBe('th_1')

    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)
    expect(body.assistant_ids).toEqual(['a1'])
  })

  it('throws ThreadHttpError on non-2xx', async () => {
    fetchMock.mockResolvedValue(new Response('not found', { status: 404 }))
    await expect(client.getThread('th_nope')).rejects.toThrow('HTTP 404')
  })

  it('throws ThreadNotFoundError on 404', async () => {
    fetchMock.mockResolvedValue(new Response('not found', { status: 404 }))
    await expect(client.getThread('th_nope')).rejects.toBeInstanceOf(ThreadNotFoundError)
    fetchMock.mockResolvedValue(new Response('not found', { status: 404 }))
    await expect(client.getThread('th_nope')).rejects.toBeInstanceOf(ThreadHttpError)
  })

  it('throws ThreadAuthError on 401 and 403', async () => {
    fetchMock.mockResolvedValue(new Response('unauth', { status: 401 }))
    await expect(client.getThread('th_1')).rejects.toBeInstanceOf(ThreadAuthError)
    fetchMock.mockResolvedValue(new Response('forbidden', { status: 403 }))
    await expect(client.getThread('th_1')).rejects.toBeInstanceOf(ThreadAuthError)
  })

  it('throws ThreadConflictError on 409', async () => {
    fetchMock.mockResolvedValue(new Response('conflict', { status: 409 }))
    await expect(
      client.invoke('th_1', { assistantIds: ['a1'], idempotencyKey: 'k1' })
    ).rejects.toBeInstanceOf(ThreadConflictError)
  })

  it('throws the base ThreadHttpError on other statuses (e.g. 500)', async () => {
    fetchMock.mockResolvedValue(new Response('boom', { status: 500 }))
    let err: ThreadHttpError | null = null
    try {
      await client.getThread('th_1')
    } catch (e) {
      err = e as ThreadHttpError
    }
    expect(err).toBeInstanceOf(ThreadHttpError)
    expect(err).not.toBeInstanceOf(ThreadNotFoundError)
    expect(err).not.toBeInstanceOf(ThreadAuthError)
    expect(err).not.toBeInstanceOf(ThreadConflictError)
    expect(err?.status).toBe(500)
  })

  it('listEvents parses page and converts cursor', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        items: [
          {
            id: 'evt_1',
            thread_id: 'th_1',
            type: 'message',
            author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
            created_at: '2026-04-10T00:00:00Z',
            metadata: {},
            content: [],
          },
        ],
        next_cursor: { created_at: '2026-04-10T00:01:00Z', id: 'evt_1' },
      })
    )
    const page = await client.listEvents('th_1')
    expect(page.items).toHaveLength(1)
    expect(page.nextCursor?.createdAt).toBe('2026-04-10T00:01:00Z')
  })

  it('addMember converts identity to wire', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          thread_id: 'th_1',
          identity_id: 'u_bob',
          identity: { role: 'user', id: 'u_bob', name: 'Bob', metadata: {} },
          role: 'member',
          added_at: '2026-04-10T00:00:00Z',
          added_by: { role: 'user', id: 'u_alice', name: 'A', metadata: {} },
        },
        201
      )
    )
    const m = await client.addMember('th_1', {
      role: 'user',
      id: 'u_bob',
      name: 'Bob',
      metadata: {},
    })
    expect(m.identityId).toBe('u_bob')
  })

  it('cancelRun returns void', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(client.cancelRun('run_1')).resolves.toBeUndefined()
  })
})
