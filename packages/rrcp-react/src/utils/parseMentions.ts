import type { AssistantIdentity, Identity } from '../protocol/identity'

const MENTION_RE = /@([\w-]+)/g

/**
 * Extract `@name` mentions from text and resolve them to assistant ids.
 *
 * - Matches `@name` tokens (word characters + hyphen) against assistant names,
 *   case-insensitively.
 * - `@here` expands to every assistant in `members` in first-seen order.
 * - Unknown mentions are silently ignored.
 * - Result is deduped, preserving the first occurrence.
 * - Non-assistant identities are always ignored.
 */
export function parseMentions(text: string, members: Identity[]): string[] {
  const assistants = members.filter((m): m is AssistantIdentity => m.role === 'assistant')
  const byLowercaseName = new Map<string, AssistantIdentity>()
  for (const a of assistants) {
    byLowercaseName.set(a.name.toLowerCase(), a)
  }

  const seen = new Set<string>()
  const result: string[] = []
  const add = (id: string) => {
    if (!seen.has(id)) {
      seen.add(id)
      result.push(id)
    }
  }

  for (const match of text.matchAll(MENTION_RE)) {
    const token = match[1]!.toLowerCase()
    if (token === 'here') {
      for (const a of assistants) add(a.id)
    } else {
      const hit = byLowercaseName.get(token)
      if (hit) add(hit.id)
    }
  }

  return result
}
