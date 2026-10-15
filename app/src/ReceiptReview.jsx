import { useState } from 'react'
import { formatMoney, parseAmount, parseNumber } from './format.js'
import { CATEGORIES } from './options.js'

const comma = (value) => String(value).replace('.', ',')

// Signed cents of a typed total. A discount is always negative, whichever way it is typed.
function cents(row) {
  const value = Math.round((parseNumber(row.total) ?? 0) * 100)
  return row.kind === 'discount' ? -Math.abs(value) : value
}

// Prefer a merchant you already use if its name is in the issuer's ("supermercados mundial ltda").
function guessMerchant(issuer, merchants) {
  const name = issuer.toLowerCase()
  const known = merchants.filter((m) => m.length >= 3 && name.includes(m))
  known.sort((a, b) => b.length - a.length)
  return known[0] ?? name
}

const toRow = (item, id) => ({
  id,
  kind: item.kind,
  code: item.code,
  unit: item.unit,
  name: item.name,
  quantity: comma(item.quantity),
  unitPrice: comma(item.unit_price),
  total: comma(item.total),
  category: '',
})

/** Validates the form and builds the request body, or returns { error }. */
function build({ merchant, date, category, rows }) {
  if (!merchant.trim()) return { error: 'Enter the merchant.' }
  if (!date) return { error: 'Choose the date.' }
  if (rows.length === 0) return { error: 'The receipt needs at least one item. Go back to start over.' }

  const items = []
  for (const [index, row] of rows.entries()) {
    const label = `Item ${index + 1}`
    const name = row.name.trim()
    if (!name) return { error: `${label}: enter a name.` }

    const itemCategory = row.category.trim() || category.trim()
    if (!itemCategory) return { error: 'Choose a category for the receipt, or one for every item.' }

    const discount = row.kind === 'discount'
    const total = parseAmount(row.total, { discount })
    if (total === null) {
      return {
        error: discount
          ? `${label}: enter the discount amount, like 2,04.`
          : `${label}: enter a total greater than 0.`,
      }
    }

    const item = {
      kind: row.kind,
      name,
      code: row.code,
      unit: row.unit,
      category: itemCategory,
      total: String(total),
    }
    if (!discount) {
      const quantity = parseNumber(row.quantity)
      const unitPrice = parseNumber(row.unitPrice)
      if (quantity === null || quantity <= 0) return { error: `${label}: enter a quantity greater than 0.` }
      if (unitPrice === null || unitPrice < 0) return { error: `${label}: enter the unit price, like 6,99.` }
      item.quantity = String(quantity)
      item.unit_price = String(unitPrice)
    }
    items.push(item)
  }
  return { payload: { merchant: merchant.trim(), date, category: category.trim(), items } }
}

/**
 * Second step of the import: edit what was read from the receipt, then save.
 * `onSave` returns a promise; if it rejects, the message is shown in the form.
 */
export default function ReceiptReview({ receipt, merchants, onSave, onBack, onCancel }) {
  const [merchant, setMerchant] = useState(() => guessMerchant(receipt.issuer_name, merchants))
  const [date, setDate] = useState(receipt.date)
  const [category, setCategory] = useState('')
  const [rows, setRows] = useState(() => receipt.items.map(toRow))
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const itemsCents = rows.reduce((sum, row) => sum + cents(row), 0)
  const receiptCents = Math.round(Number(receipt.total_paid) * 100)
  const matches = itemsCents === receiptCents

  const change = (id, changes) =>
    setRows((current) => current.map((row) => (row.id === id ? { ...row, ...changes } : row)))

  async function submit(event) {
    event.preventDefault()
    setError('')

    const built = build({ merchant, date, category, rows })
    if (built.error) {
      setError(built.error)
      return
    }

    setSaving(true)
    try {
      await onSave(built.payload)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  return (
    <form className="form review" onSubmit={submit}>
      <h2 id="import-title">Review receipt</h2>
      <p className="hint">
        <strong className="cap">{receipt.issuer_name.toLowerCase()}</strong> · CNPJ{' '}
        {receipt.issuer_cnpj} · receipt {receipt.number}
      </p>

      {receipt.warnings.length > 0 && (
        <div className="warning">
          <p>Check these before saving:</p>
          <ul>
            {receipt.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="review-head">
        <label>
          Merchant
          <input
            list="review-merchants"
            value={merchant}
            onChange={(event) => setMerchant(event.target.value)}
            required
          />
        </label>
        <label>
          Date
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
        </label>
        <label>
          Category (for all items)
          <input
            list="review-categories"
            placeholder="supermarket"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          />
        </label>
      </div>

      <ul className="review-items">
        {rows.map((row, index) => (
          <li className="review-item" key={row.id}>
            <label className="review-name">
              Item {index + 1}
              <input
                value={row.name}
                onChange={(event) => change(row.id, { name: event.target.value })}
                required
              />
            </label>

            {row.kind === 'discount' ? (
              <>
                <span className="review-spacer" />
                <span className="review-spacer" />
              </>
            ) : (
              <>
                <label>
                  Qty ({row.unit})
                  <input
                    inputMode="decimal"
                    value={row.quantity}
                    onChange={(event) => change(row.id, { quantity: event.target.value })}
                  />
                </label>
                <label>
                  Unit price
                  <input
                    inputMode="decimal"
                    value={row.unitPrice}
                    onChange={(event) => change(row.id, { unitPrice: event.target.value })}
                  />
                </label>
              </>
            )}

            <label>
              {row.kind === 'discount' ? 'Discount' : 'Total'}
              <input
                inputMode="decimal"
                value={row.total}
                onChange={(event) => change(row.id, { total: event.target.value })}
              />
            </label>
            <label className="review-category">
              Category
              <input
                list="review-categories"
                placeholder={category || 'same as above'}
                value={row.category}
                onChange={(event) => change(row.id, { category: event.target.value })}
              />
            </label>
            <button
              type="button"
              className="link danger review-remove"
              onClick={() => setRows((current) => current.filter((r) => r.id !== row.id))}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <datalist id="review-merchants">
        {merchants.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <datalist id="review-categories">
        {CATEGORIES.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      <div className={matches ? 'review-total' : 'review-total warning'}>
        <span>
          Items add up to <strong>{formatMoney(itemsCents / 100)}</strong>
        </span>
        <span>Receipt total {formatMoney(receiptCents / 100)}</span>
        {!matches && <span>The amounts differ. You can still save.</span>}
      </div>

      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      <div className="form-actions review-actions">
        <button type="button" className="link" onClick={onBack} disabled={saving}>
          Choose another file
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="submit" className="primary" disabled={saving || rows.length === 0}>
          {saving ? 'Saving…' : `Save ${rows.length} ${rows.length === 1 ? 'item' : 'items'}`}
        </button>
      </div>
    </form>
  )
}
