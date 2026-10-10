import { fetchAuthSession } from 'aws-amplify/auth'

// Same domain as the app: CloudFront forwards /api/* to API Gateway.
const BASE = '/api/expenses'

const SESSION_EXPIRED = 'Your session expired. Sign in again.'

async function request(method, path = '', body) {
  const { tokens } = await fetchAuthSession()
  const token = tokens?.idToken?.toString()
  if (!token) throw new Error(SESSION_EXPIRED)

  const response = await fetch(BASE + path, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })

  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) throw new Error(SESSION_EXPIRED)
    throw new Error(data.error || `Request failed (${response.status}).`)
  }
  return data
}

export const listExpenses = (month) => request('GET', `?month=${encodeURIComponent(month)}`)
export const createExpense = (expense) => request('POST', '', expense)
export const updateExpense = (id, expense) =>
  request('PUT', `/${encodeURIComponent(id)}`, expense)
export const deleteExpense = (id) => request('DELETE', `/${encodeURIComponent(id)}`)
