import { describe, expect, it } from 'vitest'
import type { Identity } from '../../src/protocol/identity'
import { parseMentions } from '../../src/utils/parseMentions'

const alice: Identity = { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} }
const helper: Identity = { role: 'assistant', id: 'a_helper', name: 'Helper', metadata: {} }
const codex: Identity = { role: 'assistant', id: 'a_codex', name: 'Codex', metadata: {} }
const system: Identity = { role: 'system', id: 's_1', name: 'System', metadata: {} }

describe('parseMentions', () => {
  it('matches an assistant by exact name (case-insensitive)', () => {
    expect(parseMentions('hey @helper do X', [alice, helper])).toEqual(['a_helper'])
    expect(parseMentions('hey @HELPER do X', [alice, helper])).toEqual(['a_helper'])
  })

  it('ignores non-assistant identities', () => {
    expect(parseMentions('@alice @helper', [alice, helper])).toEqual(['a_helper'])
  })

  it('@here expands to all assistants in first-seen thread order', () => {
    expect(parseMentions('ping @here', [helper, codex, alice])).toEqual(['a_helper', 'a_codex'])
  })

  it('silently drops unknown mentions', () => {
    expect(parseMentions('@nobody @helper', [helper])).toEqual(['a_helper'])
  })

  it('dedupes repeated mentions but preserves first-seen order', () => {
    expect(parseMentions('@helper @codex @helper', [helper, codex])).toEqual([
      'a_helper',
      'a_codex',
    ])
  })

  it('returns empty array when there are no mentions', () => {
    expect(parseMentions('hello world', [helper])).toEqual([])
  })

  it('ignores system identities for @here', () => {
    expect(parseMentions('@here', [system, helper])).toEqual(['a_helper'])
  })

  it('merges @here with explicit mentions, still deduped', () => {
    expect(parseMentions('@helper @here', [helper, codex])).toEqual(['a_helper', 'a_codex'])
  })
})
