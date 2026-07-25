"use strict";

/**
 * Builds the private Python environment at install time, so the first `acorn`
 * run starts immediately.
 *
 * Deliberately never fails the install. npm aborts the whole installation on a
 * non-zero postinstall, and a missing Python is a fixable local condition, not
 * a broken package. The launcher retries this same setup on first run, so the
 * worst case is a slower first start.
 */

const resolve = require("../lib/resolve");
const setup = require("../lib/setup");
const { version: PACKAGE_VERSION } = require("../package.json");

const note = (message) => console.log(`acorn: ${message}`);

// Nothing to do in the common case: the platform package supplied a standalone
// binary, so Python is not involved at all.
if (resolve.findBundledBinary()) {
  note(`ready (${process.platform}-${process.arch} binary). Run \`acorn\` to start.`);
  process.exit(0);
}

// Respect the usual opt-outs for packages that do work at install time.
if (process.env.ACORN_SKIP_POSTINSTALL || process.env.CI === "true") {
  const why = process.env.ACORN_SKIP_POSTINSTALL ? "ACORN_SKIP_POSTINSTALL" : "CI";
  console.log(`acorn: skipping Python setup (${why} is set); it will run on first use.`);
  process.exit(0);
}

note(`no prebuilt binary for ${process.platform}-${process.arch}; falling back to Python.`);

const python = setup.findPython();
if (!python.ok) {
  note(`Python ${setup.MIN_PYTHON.join(".")}+ not found — skipping setup for now.`);
  note("Install Python, then run `acorn` and it will finish setting itself up.");
  process.exit(0);
}

note(`using ${python.command} (Python ${python.version}); installing ${setup.PYPI_PACKAGE}...`);

try {
  setup.install({ quiet: true, version: PACKAGE_VERSION });
  note("ready. Run `acorn` to start.");
} catch (error) {
  note(`setup did not complete: ${error.message.split("\n")[0]}`);
  note("Not fatal — `acorn` will retry on first run.");
}
