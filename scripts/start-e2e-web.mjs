import { readFileSync } from "node:fs";
import { spawn } from "node:child_process";
const config = JSON.parse(
  readFileSync(new URL("../.local/test-config.json", import.meta.url)),
);
const child = spawn(
  process.execPath,
  ["../../node_modules/next/dist/bin/next", "dev", "--port", "3001"],
  {
    cwd: new URL("../apps/web", import.meta.url),
    stdio: "inherit",
    env: {
      ...process.env,
      WEB_ORIGIN: "http://localhost:3001",
      API_URL: "http://127.0.0.1:8001",
      GATEWAY_SECRET: config.GATEWAY_SECRET,
      NEXT_DIST_DIR: ".next-e2e",
    },
  },
);
for (const s of ["SIGINT", "SIGTERM"]) process.on(s, () => child.kill(s));
child.on("exit", (code) => process.exit(code || 0));
