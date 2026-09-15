import { defineConfig } from 'vitest/config';

// Deliberately standalone: vite.config.ts requires PORT/BASE_PATH (server/build
// concerns that don't apply to unit tests) and pulls in the React/Tailwind/Replit
// plugin stack this package's pure lib/ modules don't need.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
