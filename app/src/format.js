// Display settings. Change these two to switch currency or number style.
const MONEY_LOCALE = 'pt-BR'
const CURRENCY = 'BRL'

const money = new Intl.NumberFormat(MONEY_LOCALE, { style: 'currency', currency: CURRENCY })

export const formatMoney = (value) => money.format(value)

/** Today as YYYY-MM-DD in the user's own time zone. */
export const today = () => new Date().toLocaleDateString('en-CA')

export const currentMonth = () => today().slice(0, 7)

function parts(isoDate) {
  const [year, month, day = 1] = isoDate.split('-').map(Number)
  return new Date(year, month - 1, day)
}

export function shiftMonth(month, delta) {
  const date = parts(month)
  date.setMonth(date.getMonth() + delta)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

export const monthLabel = (month) =>
  parts(month).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })

export const dayLabel = (isoDate) =>
  parts(isoDate).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

/**
 * Reads what a person types: "42,90", "42.90", "1.234,56", "R$ 15".
 * A comma means decimal comma (dots are thousands); otherwise a dot is the decimal point.
 * Returns a number greater than 0, or null.
 */
export function parseAmount(text) {
  const cleaned = text.trim().replace(/\s/g, '').replace(/^R\$/i, '')
  const normalized = cleaned.includes(',') ? cleaned.replace(/\./g, '').replace(',', '.') : cleaned
  const value = Number(normalized)
  if (!normalized || !Number.isFinite(value) || value <= 0) return null
  return Math.round(value * 100) / 100
}
