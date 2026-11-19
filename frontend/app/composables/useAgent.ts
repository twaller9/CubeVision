// Shared agent speech state. The speech-to-speech pipeline should set `speaking`
// true only while audio is playing back, and stream the spoken words into `text`.
export function useAgent() {
  const speaking = useState('agent-speaking', () => false)
  const text = useState('agent-text', () => '')
  return { speaking, text }
}
