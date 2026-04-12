import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    globals: true,
    // The Node server is currently a Slice 4 skeleton — no test files yet.
    // Remove this once real tests land.
    passWithNoTests: true,
  },
})
