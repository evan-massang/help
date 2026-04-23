// PM2 config for memeterm local development.
// On Windows, run this from the repo root: `pm2 start infra/pm2.config.cjs`.
// Under WSL2, the backend process runs inside WSL; the frontend runs on
// Windows native so HMR / devtools work cleanly.

const path = require("path");
const repoRoot = path.resolve(__dirname, "..");

module.exports = {
  apps: [
    {
      name: "memeterm-backend",
      cwd: path.join(repoRoot, "backend"),
      script: "python",
      args: "-m memeterm.main",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1",
      },
      max_memory_restart: "1G",
      kill_timeout: 20_000,
      out_file: path.join(repoRoot, "data", "logs", "backend.out.log"),
      error_file: path.join(repoRoot, "data", "logs", "backend.err.log"),
      merge_logs: true,
      time: true,
      exp_backoff_restart_delay: 1_000,
    },
    {
      name: "memeterm-frontend",
      cwd: path.join(repoRoot, "frontend"),
      script: "pnpm",
      args: "dev",
      interpreter: "none",
      env: {
        NODE_ENV: "development",
        BACKEND_URL: "http://127.0.0.1:8787",
      },
      max_memory_restart: "1G",
      out_file: path.join(repoRoot, "data", "logs", "frontend.out.log"),
      error_file: path.join(repoRoot, "data", "logs", "frontend.err.log"),
      merge_logs: true,
      time: true,
    },
  ],
};
