#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const appData = path.join(root, ".appdata", "Roaming");
const localAppData = path.join(root, ".appdata", "Local");
fs.mkdirSync(appData, { recursive: true });
fs.mkdirSync(localAppData, { recursive: true });

const hardhatBin = process.platform === "win32"
  ? path.join(root, "node_modules", ".bin", "hardhat.cmd")
  : path.join(root, "node_modules", ".bin", "hardhat");

const proc = spawnSync(hardhatBin, ["test", "tests/hardhat/DemoFlow.settlement.cjs"], {
  cwd: root,
  stdio: "inherit",
  shell: process.platform === "win32",
  env: {
    ...process.env,
    APPDATA: appData,
    LOCALAPPDATA: localAppData,
  },
});

if (proc.error) {
  console.error(proc.error.message);
  process.exit(1);
}
process.exit(proc.status ?? 1);
