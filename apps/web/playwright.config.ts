import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  use: { baseURL: "http://localhost:3001", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        "cd ../api && uv run uvicorn tests.e2e_server:app --host 127.0.0.1 --port 8001",
      url: "http://127.0.0.1:8001/health",
      reuseExistingServer: false,
    },
    {
      command: "node ../../scripts/start-e2e-web.mjs",
      url: "http://localhost:3001/sign-in",
      reuseExistingServer: false,
    },
  ],
});
