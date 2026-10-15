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
 * Reads a number the way a person types it: "42,90", "42.90", "1.234,56", "R$ 15", "-2,04".
 * A comma means decimal comma (dots are thousands); otherwise a dot is the decimal point.
 * Returns the number, or null if it is not one. No rounding (quantities have 3 decimals).
 */
export function parseNumber(text) {
  const cleaned = String(text).trim().replace(/\s/g, '').replace(/^(-?)R\$/i, '$1')
  const normalized = cleaned.includes(',') ? cleaned.replace(/\./g, '').replace(',', '.') : cleaned
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(normalized)) return null
  return Number(normalized)
}

/**
 * An amount of money, rounded to cents. Expenses must be greater than 0.
 * With `discount`, the sign is ignored and the result is negative ("2,04" and "-2,04" both give -2.04).
 * Returns null when it is not valid.
 */
export function parseAmount(text, { discount = false } = {}) {
  const value = parseNumber(text)
  if (value === null) return null
  const amount = discount ? -Math.abs(value) : value
  if (amount === 0 || (!discount && amount < 0)) return null
  return Math.round(amount * 100) / 100
}

const quantity = new Intl.NumberFormat(MONEY_LOCALE, { maximumFractionDigits: 3 })

export const formatQuantity = (value) => quantity.format(value)
