import { useEffect, useRef, useState } from 'react'
import { parseAmount, today } from './format.js'

const CATEGORIES = ['supermarket', 'clothing', 'restaurant', 'transport', 'health', 'home', 'leisure']

/**
 * Add / edit dialog. `expense` is null when adding.
 * `onSave` returns a promise; if it rejects, the message is shown in the form.
 */
export default function ExpenseForm({ expense, merchants, onSave, onClose }) {
  const dialog = useRef(null)
  const [amount, setAmount] = useState(expense ? String(expense.amount).replace('.', ',') : '')
  const [date, setDate] = useState(expense?.date ?? today())
  const [category, setCategory] = useState(expense?.category ?? '')
  const [merchant, setMerchant] = useState(expense?.merchant ?? '')
  const [note, setNote] = useState(expense?.description ?? '')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const element = dialog.current
    if (!element.open) element.showModal()
    return () => {
      if (element.open) element.close()
    }
  }, [])

  async function submit(event) {
    event.preventDefault()
    setError('')

    const parsed = parseAmount(amount)
    if (parsed === null) {
      setError('Enter an amount greater than 0, like 42,90.')
      return
    }

    setSaving(true)
    try {
      await onSave({
        amount: parsed,
        date,
        category: category.trim(),
        merchant: merchant.trim(),
        description: note.trim(),
      })
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  return (
    <dialog
      ref={dialog}
      aria-labelledby="form-title"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose()
      }}
    >
      <form className="form" onSubmit={submit}>
        <h2 id="form-title">{expense ? 'Edit expense' : 'Add expense'}</h2>

        <label>
          Amount
          <input
            inputMode="decimal"
            placeholder="0,00"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            required
            autoFocus
          />
        </label>

        <label>
          Date
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
        </label>

        <label>
          Category
          <input
            list="category-options"
            placeholder="supermarket"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            required
          />
        </label>

        <label>
          Merchant
          <input
            list="merchant-options"
            placeholder="Where you paid"
            value={merchant}
            onChange={(event) => setMerchant(event.target.value)}
            required
          />
        </label>

        <label>
          Note (optional)
          <input value={note} onChange={(event) => setNote(event.target.value)} />
        </label>

        <datalist id="category-options">
          {CATEGORIES.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <datalist id="merchant-options">
          {merchants.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>

        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}

        <div className="form-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save expense'}
          </button>
        </div>
      </form>
    </dialog>
  )
}
