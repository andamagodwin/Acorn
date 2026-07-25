#!/usr/bin/env node
"use strict";

/**
 * `acorn` entry point for the npm distribution.
 *
 * Execs the real Python CLI from a private venv, forwarding arguments, stdio,
 * signals, and the exit code. If the venv isn't there — a fresh install with
 * `--ignore-scripts`, or an interrupted postinstall — it is built on first run
 * rather than failing.
 */

const { spawn } = require("node:child_process");
const setup = require("../lib/setup");

const { version: PACKAGE_VERSION } = require("../package.json");

function fail(message) {
  process.stderr.write(`\nacorn: ${message}\n`);
  process.exit(1);
}

function resolveExecutable() {
  const existing = setup.findExistingVenv();
  if (existing) return setup.venvExecutable(existing);

  // First run after `--ignore-scripts`, or postinstall failed. Announce it —
  // building a venv takes a few seconds and silence looks like a hang. Output
  // is captured rather than inherited so the full pip log doesn't bury the
  // reason someone ran `acorn` in the first place; it's replayed on failure.
  process.stderr.write("acorn: first run — setting up Python environment (~30s)...\n");
  try {
    const executable = setup.install({ quiet: true, version: PACKAGE_VERSION });
    process.stderr.write("acorn: ready.\n");
    return executable;
  } catch (error) {
    if (error instanceof setup.PythonMissingError) fail(error.message);
    fail(
      `setup failed.\n\n${error.message}\n\n` +
        "You can install Acorn directly with pip instead:\n" +
        `  pip install ${setup.PYPI_PACKAGE}\n`
    );
  }
  return null; // unreachable; fail() exits
}

function main() {
  const executable = resolveExecutable();

  const child = spawn(executable, process.argv.slice(2), {
    // inherit, not pipe: Acorn is an interactive TUI. Piping would break its
    // TTY detection, its raw-mode prompt, and live streaming output.
    stdio: "inherit",
    // Not `shell: true` — that would mangle arguments containing spaces or
    // quotes, and let shell metacharacters in user input be interpreted.
    shell: false,
  });

  // Ctrl-C must reach the Python process so it can cancel the current turn
  // instead of killing the session. Node would otherwise handle SIGINT itself
  // and tear this launcher down first.
  const forwarded = ["SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT"];
  const handlers = new Map();
  for (const signal of forwarded) {
    const handler = () => {
      if (!child.killed) {
        try {
          child.kill(signal);
        } catch {
          // Child already gone; nothing to forward to.
        }
      }
    };
    handlers.set(signal, handler);
    process.on(signal, handler);
  }

  const cleanup = () => {
    for (const [signal, handler] of handlers) process.off(signal, handler);
  };

  child.on("error", (error) => {
    cleanup();
    if (error.code === "ENOENT") {
      fail(
        `could not run ${executable}\n` +
          "The Python environment looks broken. Remove it and let Acorn rebuild:\n" +
          "  npm rebuild acorn-agent\n"
      );
    }
    fail(error.message);
  });

  child.on("exit", (code, signal) => {
    cleanup();
    if (signal) {
      // Convention: report a signal death as 128 + signum, like a shell does,
      // so callers and CI see a non-zero status.
      const numbers = { SIGINT: 2, SIGQUIT: 3, SIGKILL: 9, SIGTERM: 15, SIGHUP: 1 };
      process.exit(128 + (numbers[signal] || 0));
    }
    process.exit(code === null ? 1 : code);
  });
}

main();
