import { type UseQueryResult, useQuery } from '@tanstack/react-query'
import type { Page } from '../client/AcpClient'
import type { Thread } from '../protocol/thread'
import { useAcpClient } from './useAcpClient'

export type UseThreadsOptions = {
  limit?: number
}

export function useThreads(options: UseThreadsOptions = {}): UseQueryResult<Page<Thread>, Error> {
  const client = useAcpClient()
  const limit = options.limit ?? 50
  return useQuery({
    queryKey: ['acp', 'threads', limit],
    queryFn: () => client.listThreads({ limit }),
  })
}
