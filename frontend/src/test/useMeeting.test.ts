import { describe, it, expect, beforeEach } from 'vitest'
import { useMeeting } from '@/stores/useMeeting'

const { getState, setState } = useMeeting

function reset() {
  getState().reset()
}

describe('useMeeting store', () => {
  beforeEach(reset)

  it('starts with idle status and empty transcript', () => {
    const s = getState()
    expect(s.status).toBe('idle')
    expect(s.transcript).toEqual([])
    expect(s.meetingId).toBeNull()
  })

  it('setMeetingId / setMode / setStatus / setLanguage', () => {
    getState().setMeetingId('m1')
    getState().setMode('meeting')
    getState().setStatus('active')
    getState().setLanguage('en-US')

    const s = getState()
    expect(s.meetingId).toBe('m1')
    expect(s.mode).toBe('meeting')
    expect(s.status).toBe('active')
    expect(s.language).toBe('en-US')
  })

  it('adds final transcript lines and caps at 201', () => {
    for (let i = 0; i < 210; i++) {
      getState().addTranscriptLine({
        id: `line_${i}`,
        text: `msg ${i}`,
        romaji: '',
        speaker: 'spk',
        timestamp: Date.now(),
        isFinal: true,
      })
    }
    expect(getState().transcript.length).toBeLessThanOrEqual(201)
  })

  it('replaces interim lines for the same speaker', () => {
    getState().addTranscriptLine({
      id: 'temp', text: 'hello', romaji: '', speaker: 'me',
      timestamp: Date.now(), isFinal: false,
    })
    expect(getState().transcript).toHaveLength(1)
    expect(getState().transcript[0].id).toBe('interim_me')

    getState().addTranscriptLine({
      id: 'temp2', text: 'hello world', romaji: '', speaker: 'me',
      timestamp: Date.now(), isFinal: false,
    })
    expect(getState().transcript).toHaveLength(1)
    expect(getState().transcript[0].text).toBe('hello world')
  })

  it('clears interim when final arrives', () => {
    getState().addTranscriptLine({
      id: 'i1', text: 'partial', romaji: '', speaker: 'me',
      timestamp: Date.now(), isFinal: false,
    })
    getState().addTranscriptLine({
      id: 'final_1', text: 'full message', romaji: '', speaker: 'me',
      timestamp: Date.now(), isFinal: true,
    })
    const t = getState().transcript
    expect(t).toHaveLength(1)
    expect(t[0].id).toBe('final_1')
    expect(t[0].text).toBe('full message')
  })

  it('updateTranscriptLine updates a specific line', () => {
    getState().addTranscriptLine({
      id: 'x', text: 'orig', romaji: '', speaker: 'a',
      timestamp: Date.now(), isFinal: true,
    })
    getState().updateTranscriptLine('x', { translationVi: 'bản dịch' })
    expect(getState().transcript[0].translationVi).toBe('bản dịch')
  })

  it('suggestion stream lifecycle', () => {
    getState().startSuggestionStream('line_42')
    expect(getState().activeSuggestionLineId).toBe('line_42')
    expect(getState().streamingSuggestion).toEqual({ answerRomaji: '', answerVi: '' })

    getState().appendSuggestionChunk('answer_romaji', 'Hai, ')
    getState().appendSuggestionChunk('answer_romaji', 'watashi wa')
    expect(getState().streamingSuggestion?.answerRomaji).toBe('Hai, watashi wa')

    getState().appendSuggestionChunk('answer_vi', 'Vâng, tôi là')
    expect(getState().streamingSuggestion?.answerVi).toBe('Vâng, tôi là')

    getState().addSuggestion({
      id: 'sg_1', answerRomaji: 'full romaji', answerVi: 'full vi',
      pinned: false, timestamp: Date.now(),
    })
    const s = getState()
    expect(s.streamingSuggestion).toBeNull()
    expect(s.activeSuggestionLineId).toBeNull()
    expect(s.suggestions).toHaveLength(1)
    expect(s.lineSuggestions['line_42']).toBeDefined()
  })

  it('clearAllSuggestions wipes everything', () => {
    getState().addSuggestion({
      id: 'sg', answerRomaji: 'r', answerVi: 'v',
      pinned: false, timestamp: Date.now(), lineId: 'ln',
    })
    getState().setNowDiscussing('topic A')
    expect(getState().suggestions).toHaveLength(1)

    getState().clearAllSuggestions()
    const s = getState()
    expect(s.suggestions).toEqual([])
    expect(s.lineSuggestions).toEqual({})
    expect(s.nowDiscussing).toBe('')
    expect(s.streamingSuggestion).toBeNull()
  })

  it('dismissLineSuggestion removes one entry', () => {
    setState({
      lineSuggestions: {
        a: { id: '1', answerRomaji: '', answerVi: '', pinned: false, timestamp: 0 },
        b: { id: '2', answerRomaji: '', answerVi: '', pinned: false, timestamp: 0 },
      },
    })
    getState().dismissLineSuggestion('a')
    expect(getState().lineSuggestions).not.toHaveProperty('a')
    expect(getState().lineSuggestions).toHaveProperty('b')
  })

  it('reset returns to initial state', () => {
    getState().setMeetingId('m1')
    getState().setStatus('active')
    getState().addTranscriptLine({
      id: 'x', text: 'hi', romaji: '', speaker: 's',
      timestamp: Date.now(), isFinal: true,
    })
    getState().reset()
    const s = getState()
    expect(s.meetingId).toBeNull()
    expect(s.status).toBe('idle')
    expect(s.transcript).toEqual([])
  })
})
