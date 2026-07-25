"use strict";

/**
 * Works out which Acorn to run.
 *
 * Two delivery routes, tried in order:
 *
 *   1. A standalone binary from the matching `acorn-agent-<platform>-<arch>`
 *      package. Needs no Python at all, so it's the default path.
 *   2. A private Python venv built from PyPI (see setup.js). Covers platforms
 *      with no prebuilt binary, and installs where optional dependencies were
 *      skipped.
 */

const fs = require("node:fs");
const path = require("node:path");

const IS_WINDOWS = process.platform === "win32";

/** npm package name carrying the binary for the current host. */
function platformPackageName(platform = process.platform, arch = process.arch) {
  return `acorn-agent-${platform}-${arch}`;
}

/**
 * Locates the bundled binary, or null if this host has no platform package.
 *
 * Resolution goes through require.resolve so it follows whatever layout the
 * package manager used — npm's flat node_modules, pnpm's symlinked store, or a
 * hoisted workspace root — rather than assuming a relative path.
 */
function findBundledBinary() {
  const packageName = platformPackageName();
  const executable = IS_WINDOWS ? "acorn.exe" : "acorn";

  let manifestPath;
  try {
    manifestPath = require.resolve(`${packageName}/package.json`, {
      paths: [__dirname],
    });
  } catch {
    // Not installed: unsupported platform, --no-optional, or a package manager
    // that skipped it. The Python route takes over.
    return null;
  }

  const candidate = path.join(path.dirname(manifestPath), "bin", executable);
  if (!fs.existsSync(candidate)) return null;

  // A binary that lost its exec bit in transit would fail with a confusing
  // EACCES from spawn; repair it here where we can explain what happened.
  if (!IS_WINDOWS) {
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
    } catch {
      try {
        fs.chmodSync(candidate, 0o755);
      } catch {
        return null;
      }
    }
  }

  return candidate;
}

module.exports = { findBundledBinary, platformPackageName };
