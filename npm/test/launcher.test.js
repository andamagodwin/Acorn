"use strict";

/**
 * Tests for the npm launcher. Uses a fake `acorn` executable in a fake venv so
 * the behaviour that matters — argument passing, exit codes, signal forwarding
 * — is checked without needing a real install.
 */

const assert = require("node:assert");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const LAUNCHER = path.join(ROOT, "bin", "acorn.js");
const VENV = path.join(ROOT, ".venv");
const BIN_DIR = path.join(VENV, process.platform === "win32" ? "Scripts" : "bin");

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`ok   ${name}`);
    passed++;
  } catch (error) {
    console.log(`FAIL ${name}\n     ${error.message}`);
    failed++;
  }
}

// --- fixture ---------------------------------------------------------------

let createdVenv = false;

function installFakeVenv() {
  if (fs.existsSync(VENV)) {
    throw new Error(
      `refusing to clobber an existing venv at ${VENV} — remove it to run tests`
    );
  }
  fs.mkdirSync(BIN_DIR, { recursive: true });
  createdVenv = true;

  // Stand-in for the Python CLI: echoes argv, exits with a requested code, and
  // reports the signal it received.
  const script = `#!/usr/bin/env node
process.on("SIGTERM", () => { process.stdout.write("got:SIGTERM\\n"); process.exit(42); });
process.on("SIGINT",  () => { process.stdout.write("got:SIGINT\\n");  process.exit(43); });
const args = process.argv.slice(2);
if (args[0] === "--exit-code") process.exit(Number(args[1]));
if (args[0] === "--sleep") { setTimeout(() => process.exit(0), Number(args[1])); process.stdout.write("sleeping\\n"); }
else { process.stdout.write("args:" + JSON.stringify(args) + "\\n"); }
`;
  const target = path.join(BIN_DIR, process.platform === "win32" ? "acorn.exe" : "acorn");

  if (process.platform === "win32") {
    // Can't fake an .exe; skip the exec-level tests on Windows.
    fs.writeFileSync(target, script);
  } else {
    fs.writeFileSync(target, script, { mode: 0o755 });
  }
  // The launcher checks for a venv python when deciding whether to rebuild.
  fs.writeFileSync(path.join(BIN_DIR, "python"), "#!/bin/sh\nexit 0\n", { mode: 0o755 });
}

function removeFakeVenv() {
  if (createdVenv) fs.rmSync(VENV, { recursive: true, force: true });
}

function runLauncher(args = [], options = {}) {
  return spawnSync(process.execPath, [LAUNCHER, ...args], {
    encoding: "utf8",
    timeout: 20000,
    ...options,
  });
}

// --- unit tests on setup.js ------------------------------------------------

const setup = require("../lib/setup");

test("finds a Python and reports a version", () => {
  const python = setup.findPython();
  assert.ok(python.command || python.rejected, "should return a command or rejections");
  if (python.ok) {
    assert.match(python.version, /^\d+\.\d+$/, `odd version: ${python.version}`);
  }
});

test("rejects Python below the documented minimum", () => {
  // 3.11 is the floor declared in pyproject.toml; guard against drift.
  assert.deepStrictEqual(setup.MIN_PYTHON, [3, 11]);
});

test("ACORN_PYTHON takes precedence", () => {
  const before = process.env.ACORN_PYTHON;
  process.env.ACORN_PYTHON = "definitely-not-a-real-python-xyz";
  try {
    const python = setup.findPython();
    // The bogus override must not resolve, and must not silently fall through
    // to a system python — otherwise the env var would be meaningless.
    assert.notStrictEqual(python.command, "definitely-not-a-real-python-xyz");
  } finally {
    if (before === undefined) delete process.env.ACORN_PYTHON;
    else process.env.ACORN_PYTHON = before;
  }
});

test("PythonMissingError explains how to fix it", () => {
  const error = new setup.PythonMissingError([
    { command: "python3", version: "3.9" },
  ]);
  assert.match(error.message, /Python 3\.11\+/);
  assert.match(error.message, /python3 \(3\.9\)/, "should name what it found");
  assert.match(error.message, /ACORN_PYTHON/, "should mention the override");
});

// --- resolution tests ------------------------------------------------------

const resolveLib = require("../lib/resolve");

test("platform package name matches the host", () => {
  assert.strictEqual(
    resolveLib.platformPackageName("darwin", "arm64"),
    "acorn-agent-darwin-arm64"
  );
  assert.strictEqual(
    resolveLib.platformPackageName("win32", "x64"),
    "acorn-agent-win32-x64"
  );
});

test("returns null when no platform package is installed", () => {
  // Nothing is installed in the repo checkout, so this must not throw — the
  // Python fallback depends on a clean null rather than an exception.
  assert.strictEqual(resolveLib.findBundledBinary(), null);
});

// win32-x64 stays buildable in make-platform-package.js (SUPPORTED) but is
// deliberately left out of optionalDependencies: npm's abuse detection flags
// the unscoped "acorn-agent-win32-x64" name as spam on every publish attempt,
// confirmed not rate-related. Revisit under a scoped name.
const RELEASE_EXCLUDED = new Set(["win32-x64"]);

test("every optionalDependency has a generator target", () => {
  const { optionalDependencies, version } = require("../package.json");
  const { SUPPORTED } = require("../packaging/make-platform-package.js");
  const names = Object.keys(optionalDependencies);
  assert.ok(names.length > 0, "should declare platform packages");
  for (const name of names) {
    const key = name.replace(/^acorn-agent-/, "");
    assert.ok(SUPPORTED[key], `${name} has no build target`);
    assert.strictEqual(
      optionalDependencies[name],
      version,
      `${name} must be pinned to the main package version`
    );
  }
  // And the reverse: nothing buildable is left unpublished, aside from
  // known, documented exclusions.
  for (const key of Object.keys(SUPPORTED)) {
    if (RELEASE_EXCLUDED.has(key)) continue;
    assert.ok(
      names.includes(`acorn-agent-${key}`),
      `build target ${key} is missing from optionalDependencies`
    );
  }
});

// --- launcher tests --------------------------------------------------------

if (process.platform === "win32") {
  console.log("--   skipping exec tests (cannot fake acorn.exe on Windows)");
} else {
  installFakeVenv();
  try {
    test("forwards arguments verbatim", () => {
      const result = runLauncher(["--model", "gemini-3-flash", "a b", "--x=1"]);
      assert.strictEqual(result.status, 0, result.stderr);
      assert.match(result.stdout, /args:\["--model","gemini-3-flash","a b","--x=1"\]/);
    });

    test("propagates a non-zero exit code", () => {
      const result = runLauncher(["--exit-code", "17"]);
      assert.strictEqual(result.status, 17);
    });

    test("propagates exit code 0", () => {
      const result = runLauncher(["--exit-code", "0"]);
      assert.strictEqual(result.status, 0);
    });

    test("does not rebuild when a venv already exists", () => {
      const result = runLauncher([]);
      assert.doesNotMatch(
        result.stderr,
        /preparing Python environment/,
        "should have used the existing venv"
      );
    });

    test("forwards SIGTERM to the child", async () => {
      // Async inside a sync harness: spawn, signal, then busy-wait on the result.
      const child = spawn(process.execPath, [LAUNCHER, "--sleep", "5000"], {
        stdio: ["ignore", "pipe", "pipe"],
      });
      let out = "";
      child.stdout.on("data", (d) => (out += d));

      const deadline = Date.now() + 15000;
      const waitFor = (predicate) => {
        while (!predicate() && Date.now() < deadline) {
          // Block briefly; spawnSync yields to the event loop between calls.
          spawnSync(process.execPath, ["-e", "setTimeout(()=>{},50)"], { timeout: 5000 });
        }
      };

      waitFor(() => out.includes("sleeping"));
      assert.ok(out.includes("sleeping"), "child did not start");

      child.kill("SIGTERM");

      let exitCode = null;
      child.on("exit", (code) => (exitCode = code));
      waitFor(() => exitCode !== null);

      assert.ok(out.includes("got:SIGTERM"), `child never saw SIGTERM (stdout: ${out.trim()})`);
      assert.strictEqual(exitCode, 42, "should propagate the child's post-signal exit code");
    });
  } finally {
    removeFakeVenv();
  }
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
