#!/usr/bin/env node
"use strict";

/**
 * `acorn` entry point for the npm distribution.
 *
 * Prefers a prebuilt standalone binary from the matching platform package,
 * which needs no Python. Falls back to building a private Python venv from PyPI
 * for hosts with no prebuilt binary, or installs where optional dependencies
 * were skipped.
 *
 * Either way it forwards arguments, stdio, signals, and the exit code.
 */

const { spawn } = require("node:child_process");
const resolve = require("../lib/resolve");
const setup = require("../lib/setup");

const { version: PACKAGE_VERSION } = require("../package.json");

function fail(message) {
  process.stderr.write(`\nacorn: ${message}\n`);
  process.exit(1);
}

function resolveExecutable() {
  // Fast path: the prebuilt binary for this platform.
  const bundled = resolve.findBundledBinary();
  if (bundled) return bundled;

  const existing = setup.findExistingVenv();
  if (existing) return setup.venvExecutable(existing);

  // No prebuilt binary for this host, or optional dependencies were skipped.
  // Announce the fallback — building a venv takes a few seconds and silence
  // looks like a hang. Output is captured rather than inherited so the full pip
  // log doesn't bury the reason someone ran `acorn`; it's replayed on failure.
  process.stderr.write(
    `acorn: no prebuilt binary for ${process.platform}-${process.arch}; ` +
      "using Python (one-time setup, ~30s)...\n"
  );
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
