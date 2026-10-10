// Injected at build time (see .env.example and the CD pipeline).
export const config = {
  userPoolId: import.meta.env.VITE_USER_POOL_ID,
  userPoolClientId: import.meta.env.VITE_USER_POOL_CLIENT_ID,
}

export const configured = Boolean(config.userPoolId && config.userPoolClientId)
