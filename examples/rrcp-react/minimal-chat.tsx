import {
  AcpProvider,
  type Event,
  useThreadActions,
  useThreadEvents,
  useThreadIsWorking,
  useThreadSession,
} from '@0x0064/rrcp-react'
import { useState } from 'react'

export function App() {
  return (
    <AcpProvider
      url="http://localhost:8000"
      authenticate={async () => ({
        headers: { authorization: 'Bearer demo-token' },
      })}
    >
      <Chat threadId="th_demo" />
    </AcpProvider>
  )
}

function Chat({ threadId }: { threadId: string }) {
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const isWorking = useThreadIsWorking(threadId)
  const { ask } = useThreadActions(threadId)
  const [text, setText] = useState('')

  if (session.status === 'joining') return <div>Joining…</div>
  if (session.status === 'error') return <div>Error: {session.error?.message}</div>

  return (
    <div>
      <ul>
        {events.map((e) => (
          <li key={e.id}>{renderEvent(e)}</li>
        ))}
      </ul>
      {isWorking && <div>Assistant is working…</div>}
      <form
        onSubmit={(ev) => {
          ev.preventDefault()
          if (!text.trim()) return
          void ask(['a1'], {
            clientId: crypto.randomUUID(),
            content: [{ type: 'text', text }],
          })
          setText('')
        }}
      >
        <input value={text} onChange={(e) => setText(e.target.value)} />
        <button type="submit">Send</button>
      </form>
    </div>
  )
}

function renderEvent(e: Event): string {
  switch (e.type) {
    case 'message': {
      const text = e.content.find((p) => p.type === 'text')
      return `${e.author.name}: ${text && text.type === 'text' ? text.text : '[media]'}`
    }
    case 'reasoning':
      return `${e.author.name} (reasoning): ${e.content}`
    case 'tool.call':
      return `${e.author.name} → tool ${e.tool.name}(${JSON.stringify(e.tool.arguments)})`
    case 'tool.result':
      return `tool ${e.tool.id} → ${JSON.stringify(e.tool.result)}`
    case 'run.started':
      return '— run started —'
    case 'run.completed':
      return '— run completed —'
    case 'run.failed':
      return `— run failed: ${e.error.message} —`
    case 'run.cancelled':
      return '— run cancelled —'
    default:
      return `[${e.type}]`
  }
}
