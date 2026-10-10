import { Authenticator } from '@aws-amplify/ui-react'
import Tracker from './Tracker.jsx'
import { configured } from './config.js'

const components = {
  Header: () => <h1 className="login-title">Home expenses</h1>,
}

export default function App() {
  if (!configured) {
    return (
      <main className="notice">
        <h1>Sign-in is not configured</h1>
        <p>
          Set <code>VITE_USER_POOL_ID</code> and <code>VITE_USER_POOL_CLIENT_ID</code> in{' '}
          <code>app/.env.local</code>, then restart <code>npm run dev</code>. The values are
          Terraform outputs.
        </p>
      </main>
    )
  }

  return (
    <Authenticator hideSignUp components={components}>
      {({ signOut, user }) => (
        <Tracker signOut={signOut} email={user?.signInDetails?.loginId ?? ''} />
      )}
    </Authenticator>
  )
}
