import { type UseQueryResult, useQuery } from '@tanstack/react-query'
import type { Page } from '../client/ThreadClient'
import type { Thread } from '../protocol/thread'
import { useThreadClient } from './useThreadClient'

export type UseThreadsOptions = {
  limit?: number
}

export function useThreads(options: UseThreadsOptions = {}): UseQueryResult<Page<Thread>, Error> {
  const client = useThreadClient()
  const limit = options.limit ?? 50
  return useQuery({
    queryKey: ['acp', 'threads', limit],
    queryFn: () => client.listThreads({ limit }),
  })
}
