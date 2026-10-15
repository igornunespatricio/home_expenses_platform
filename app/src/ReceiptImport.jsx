import { useEffect, useRef, useState } from 'react'
import { importReceipt, saveReceipt } from './api.js'
import ReceiptReview from './ReceiptReview.jsx'

const MAX_BYTES = 2_000_000 // same limit as the server

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
    reader.onerror = () => reject(new Error('Could not read that file.'))
    reader.readAsDataURL(file)
  })
}

/**
 * Receipt import dialog.
 * Step 1: pick the saved NFC-e page; the server reads it and answers with a draft.
 * Step 2: review and edit the draft, then save. Nothing is stored before that save.
 */
export default function ReceiptImport({ merchants, onSaved, onClose }) {
  const dialog = useRef(null)
  const [stage, setStage] = useState(null) // null while picking; { file, receipt } while reviewing
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const element = dialog.current
    if (!element.open) element.showModal()
    return () => {
      if (element.open) element.close()
    }
  }, [])

  async function pick(event) {
    const input = event.target
    const chosen = input.files?.[0]
    if (!chosen) return
    setError('')
    if (chosen.size > MAX_BYTES) {
      setError('That file is too large to be a receipt.')
      input.value = ''
      return
    }

    setBusy(true)
    try {
      const file = await toBase64(chosen)
      const { receipt } = await importReceipt(file)
      setStage({ file, receipt })
    } catch (err) {
      setError(err.message)
      input.value = '' // lets the same file be picked again
    } finally {
      setBusy(false)
    }
  }

  async function save(payload) {
    await saveReceipt(stage.file, payload)
    onSaved(payload.date)
  }

  return (
    <dialog
      ref={dialog}
      className={stage ? 'wide' : undefined}
      aria-labelledby="import-title"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        // Only while picking: a stray click must not throw away a review in progress.
        if (!stage && event.target === dialog.current) onClose()
      }}
    >
      {stage ? (
        <ReceiptReview
          receipt={stage.receipt}
          merchants={merchants}
          onSave={save}
          onBack={() => setStage(null)}
          onCancel={onClose}
        />
      ) : (
        <div className="form">
          <h2 id="import-title">Import a receipt</h2>
          <p className="hint">
            Open your NFC-e on the Fazenda site, press Ctrl+S, choose &ldquo;Webpage, Single
            File&rdquo; and pick the saved file here. You can check and edit everything before
            anything is saved.
          </p>

          <label>
            Receipt file
            <input
              type="file"
              accept=".mht,.mhtml,.html,.htm"
              onChange={pick}
              disabled={busy}
            />
          </label>

          {busy && <p className="hint">Reading the receipt…</p>}

          {error && (
            <p className="alert" role="alert">
              {error}
            </p>
          )}

          <div className="form-actions">
            <button type="button" className="secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </dialog>
  )
}
