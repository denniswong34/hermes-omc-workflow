import path from "path";
import { defineConfig } from "@playwright/test";

const repoRoot = __dirname;
const vaultPath = path.join(repoRoot, "tests", "fixtures", "e2e-vault");
const taskMapPath = path.join(repoRoot, "tests", "fixtures", "e2e-task_map.json");
const uiRoot = path.join(repoRoot, "apps", "agentic-os");

export default defineConfig({
  testDir: path.join(repoRoot, "tests", "e2e"),
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: "python -m uvicorn apps.api.main:app --port 8000",
      cwd: repoRoot,
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: !process.env.CI,
      env: {
        ...process.env,
        OMC_CONFIG: path.join(repoRoot, "tests", "fixtures", "omc.e2e.yaml"),
        OMC_OBSIDIAN_VAULT: vaultPath,
        OMC_E2E_TASK_MAP: taskMapPath,
        OMC_E2E: "1",
        OMC_WORKSPACE: repoRoot,
        OMC_ENV_FILE: path.join(repoRoot, "tests", "fixtures", "e2e.env"),
      },
    },
    {
      command: "npm run dev -- --port 3000",
      cwd: uiRoot,
      url: "http://127.0.0.1:3000",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
