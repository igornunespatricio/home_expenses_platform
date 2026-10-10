import { useEffect, useMemo, useState } from 'react'
import { createExpense, deleteExpense, listExpenses, updateExpense } from './api.js'
import ExpenseForm from './ExpenseForm.jsx'
import { currentMonth, dayLabel, formatMoney, monthLabel, shiftMonth } from './format.js'

const MAX_SEGMENTS = 6
const SEED_MERCHANTS = ['guanabara', 'assai', 'mundial']

const cents = (value) => Math.round(value * 100)

export default function Tracker({ signOut, email }) {
  const [month, setMonth] = useState(currentMonth)
  const [reload, setReload] = useState(0)
  const [state, setState] = useState({ status: 'loading', items: [], error: '' })
  const [merchantFilter, setMerchantFilter] = useState(null)
  const [editing, setEditing] = useState(null) // null | 'new' | an expense
  const [confirmId, setConfirmId] = useState(null)
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    let cancelled = false
    setState((current) => ({ ...current, status: 'loading' }))
    listExpenses(month)
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', items: data.items, error: '' })
      })
      .catch((err) => {
        if (!cancelled) setState({ status: 'error', items: [], error: err.message })
      })
    return () => {
      cancelled = true
    }
  }, [month, reload])

  const { totalCents, segments } = useMemo(() => {
    const byMerchant = new Map()
    let total = 0
    for (const item of state.items) {
      const value = cents(item.amount)
      total += value
      byMerchant.set(item.merchant, (byMerchant.get(item.merchant) ?? 0) + value)
    }
    const sorted = [...byMerchant].sort((a, b) => b[1] - a[1])
    const list = sorted.slice(0, MAX_SEGMENTS).map(([name, value]) => ({ name, cents: value }))
    const rest = sorted.slice(MAX_SEGMENTS).reduce((sum, [, value]) => sum + value, 0)
    if (rest > 0) list.push({ name: 'Other merchants', cents: rest, other: true })
    return { totalCents: total, segments: list }
  }, [state.items])

  // Ignore a filter whose merchant no longer exists (deleted, or another month).
  const activeFilter =
    merchantFilter && state.items.some((item) => item.merchant === merchantFilter)
      ? merchantFilter
      : null

  const days = useMemo(() => {
    const visible = activeFilter
      ? state.items.filter((item) => item.merchant === activeFilter)
      : state.items
    const groups = []
    for (const item of visible) {
      const last = groups[groups.length - 1]
      if (last && last.date === item.date) {
        last.items.push(item)
        last.cents += cents(item.amount)
      } else {
        groups.push({ date: item.date, items: [item], cents: cents(item.amount) })
      }
    }
    return groups
  }, [state.items, activeFilter])

  const merchantOptions = useMemo(
    () => [...new Set([...state.items.map((item) => item.merchant), ...SEED_MERCHANTS])].sort(),
    [state.items],
  )

  function goToMonth(next) {
    setMonth(next)
    setMerchantFilter(null)
    setConfirmId(null)
    setActionError('')
  }

  async function save(payload) {
    const saved =
      editing === 'new' ? await createExpense(payload) : await updateExpense(editing.id, payload)
    setEditing(null)
    const savedMonth = saved.date.slice(0, 7)
    if (savedMonth === month) setReload((n) => n + 1)
    else goToMonth(savedMonth)
  }

  async function remove(id) {
    setActionError('')
    try {
      await deleteExpense(id)
      setConfirmId(null)
      setReload((n) => n + 1)
    } catch (err) {
      setActionError(err.message)
    }
  }

  const count = state.items.length

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">Home expenses</span>
        <div className="account">
          {email && <span className="email">{email}</span>}
          <button type="button" className="link" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      <main className="layout">
        <section className="summary" aria-labelledby="month-title">
          <div className="month-nav">
            <button
              type="button"
              className="icon-btn"
              aria-label="Previous month"
              onClick={() => goToMonth(shiftMonth(month, -1))}
            >
              ‹
            </button>
            <h1 id="month-title">{monthLabel(month)}</h1>
            <button
              type="button"
              className="icon-btn"
              aria-label="Next month"
              onClick={() => goToMonth(shiftMonth(month, 1))}
            >
              ›
            </button>
          </div>

          <p className="total">{formatMoney(totalCents / 100)}</p>
          <p className="count">
            {state.status === 'ready' ? `${count} ${count === 1 ? 'expense' : 'expenses'}` : ' '}
          </p>

          {segments.length > 0 && (
            <>
              <div className="strip" role="img" aria-label="Share of spending by merchant">
                {segments.map((segment, index) => (
                  <span
                    key={segment.name}
                    style={{
                      flexGrow: segment.cents,
                      background: segment.other ? 'var(--c-other)' : `var(--c${index + 1})`,
                    }}
                  />
                ))}
              </div>

              <h2 className="section-title">By merchant</h2>
              <ul className="breakdown">
                {segments.map((segment, index) => (
                  <li key={segment.name}>
                    {segment.other ? (
                      <div className="breakdown-row">
                        <span className="swatch" style={{ background: 'var(--c-other)' }} />
                        <span className="breakdown-name">{segment.name}</span>
                        <span className="breakdown-amount">{formatMoney(segment.cents / 100)}</span>
                        <span className="breakdown-share">
                          {Math.round((segment.cents / totalCents) * 100)}%
                        </span>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="breakdown-row"
                        aria-pressed={activeFilter === segment.name}
                        onClick={() =>
                          setMerchantFilter(activeFilter === segment.name ? null : segment.name)
                        }
                      >
                        <span className="swatch" style={{ background: `var(--c${index + 1})` }} />
                        <span className="breakdown-name">{segment.name}</span>
                        <span className="breakdown-amount">{formatMoney(segment.cents / 100)}</span>
                        <span className="breakdown-share">
                          {Math.round((segment.cents / totalCents) * 100)}%
                        </span>
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="entries" aria-labelledby="entries-title">
          <div className="entries-head">
            <h2 id="entries-title">
              {activeFilter ? (
                <>
                  Expenses at <span className="cap">{activeFilter}</span>
                </>
              ) : (
                'Expenses'
              )}
            </h2>
            {activeFilter && (
              <button type="button" className="link" onClick={() => setMerchantFilter(null)}>
                Show all
              </button>
            )}
            <button type="button" className="primary" onClick={() => setEditing('new')}>
              Add expense
            </button>
          </div>

          {actionError && (
            <p className="alert" role="alert">
              {actionError}
            </p>
          )}

          {state.status === 'loading' && <p className="muted">Loading expenses…</p>}

          {state.status === 'error' && (
            <div className="alert" role="alert">
              <p>{state.error}</p>
              <button type="button" className="secondary" onClick={() => setReload((n) => n + 1)}>
                Try again
              </button>
            </div>
          )}

          {state.status === 'ready' && count === 0 && (
            <p className="empty">
              No expenses in {monthLabel(month)}. Add the first one to start this month&rsquo;s
              total.
            </p>
          )}

          {state.status === 'ready' &&
            days.map((day) => (
              <div className="day" key={day.date}>
                <div className="day-head">
                  <h3>{dayLabel(day.date)}</h3>
                  <span>{formatMoney(day.cents / 100)}</span>
                </div>
                <ul className="rows">
                  {day.items.map((item) => (
                    <li className="row" key={item.id}>
                      <div className="row-main">
                        <span className="merchant">{item.merchant}</span>
                        <span className="detail">
                          {item.category}
                          {item.description && <span className="note">{item.description}</span>}
                        </span>
                      </div>
                      <span className="amount">{formatMoney(item.amount)}</span>
                      <div className="row-actions">
                        {confirmId === item.id ? (
                          <>
                            <button
                              type="button"
                              className="link danger"
                              onClick={() => remove(item.id)}
                            >
                              Confirm delete
                            </button>
                            <button type="button" className="link" onClick={() => setConfirmId(null)}>
                              Cancel
                            </button>
                          </>
                        ) : (
                          <>
                            <button type="button" className="link" onClick={() => setEditing(item)}>
                              Edit
                            </button>
                            <button type="button" className="link" onClick={() => setConfirmId(item.id)}>
                              Delete
                            </button>
                          </>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </section>
      </main>

      {editing && (
        <ExpenseForm
          expense={editing === 'new' ? null : editing}
          merchants={merchantOptions}
          onSave={save}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
