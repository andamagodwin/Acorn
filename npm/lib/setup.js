"use strict";

/**
 * Shared setup for the npm distribution of Acorn.
 *
 * Acorn is a Python program, and npm cannot install Python packages. So this
 * package is a launcher: it finds a suitable Python, creates a private virtual
 * environment, installs `acorn-agent` from PyPI into it, and execs the real
 * entry point from there.
 *
 * The venv is private on purpose. Installing into the user's global or active
 * Python would let an unrelated `pip install` break Acorn, and would leave
 * packages behind after `npm uninstall`.
 */

const { execFileSync, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const IS_WINDOWS = process.platform === "win32";

// Matches pyproject.toml's requires-python. Kept as numbers so the comparison
// doesn't do the wrong thing on "3.10" vs "3.9" (string compare says 3.10 < 3.9).
const MIN_PYTHON = [3, 11];

const PYPI_PACKAGE = "acorn-agent";

/** Candidate interpreters, in preference order. */
function pythonCandidates() {
  const fromEnv = process.env.ACORN_PYTHON;
  const candidates = fromEnv ? [fromEnv] : [];

  if (IS_WINDOWS) {
    // The `py` launcher resolves the newest install, which is usually what we
    // want; the bare names are the fallback.
    candidates.push("py", "python3", "python");
  } else {
    candidates.push("python3", "python");
    // Explicit minor versions catch systems where `python3` is older than an
    // additionally installed 3.11+.
    for (let minor = 14; minor >= MIN_PYTHON[1]; minor--) {
      candidates.push(`python3.${minor}`);
    }
  }

  return candidates;
}

function probePython(command) {
  // Ask the interpreter for its own version rather than parsing `--version`
  // output, which has moved between stdout and stderr across releases.
  const args = command === "py" ? ["-3", "-c"] : ["-c"];
  const script = "import sys; print('%d.%d' % sys.version_info[:2])";

  const result = spawnSync(command, [...args, script], {
    encoding: "utf8",
    // Inherit nothing: a prompt from the Windows Store python stub would hang.
    stdio: ["ignore", "pipe", "ignore"],
    timeout: 15000,
  });

  if (result.error || result.status !== 0 || !result.stdout) return null;

  const match = result.stdout.trim().match(/^(\d+)\.(\d+)$/);
  if (!match) return null;

  const major = Number(match[1]);
  const minor = Number(match[2]);
  const ok =
    major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1]);

  return { command, major, minor, ok, version: `${major}.${minor}` };
}

/** Finds the first Python that satisfies MIN_PYTHON. */
function findPython() {
  const seen = [];
  for (const candidate of pythonCandidates()) {
    const probed = probePython(candidate);
    if (!probed) continue;
    if (probed.ok) return probed;
    seen.push(probed);
  }
  return { command: null, ok: false, rejected: seen };
}

/**
 * Where the private venv lives.
 *
 * Prefers a directory inside the installed package so `npm uninstall` takes it
 * away too. Falls back to a user cache directory when the package directory is
 * read-only, which happens with root-owned global prefixes.
 */
function venvCandidates() {
  const inPackage = path.join(__dirname, "..", ".venv");
  const cacheHome =
    process.env.XDG_CACHE_HOME ||
    (IS_WINDOWS
      ? process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local")
      : path.join(os.homedir(), ".cache"));
  return [inPackage, path.join(cacheHome, "acorn-agent-npm", "venv")];
}

function venvBinDir(venvDir) {
  return path.join(venvDir, IS_WINDOWS ? "Scripts" : "bin");
}

function venvExecutable(venvDir) {
  return path.join(venvBinDir(venvDir), IS_WINDOWS ? "acorn.exe" : "acorn");
}

function venvPython(venvDir) {
  return path.join(venvBinDir(venvDir), IS_WINDOWS ? "python.exe" : "python");
}

/** An existing, usable venv, or null. */
function findExistingVenv() {
  for (const dir of venvCandidates()) {
    if (fs.existsSync(venvExecutable(dir))) return dir;
  }
  return null;
}

function isWritable(dir) {
  // Walk up to the nearest existing ancestor — we may need to create `dir`.
  let probe = dir;
  while (!fs.existsSync(probe)) {
    const parent = path.dirname(probe);
    if (parent === probe) return false;
    probe = parent;
  }
  try {
    fs.accessSync(probe, fs.constants.W_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * Creates the venv and installs the package into it.
 *
 * @param {object} options
 * @param {boolean} [options.quiet] Suppress pip/venv output.
 * @param {string}  [options.version] Exact version to pin; defaults to the
 *   version of this npm package so the two stay in lockstep.
 * @returns {string} Path to the `acorn` executable inside the venv.
 */
function install({ quiet = false, version } = {}) {
  const python = findPython();
  if (!python.ok) {
    throw new PythonMissingError(python.rejected);
  }

  const target = venvCandidates().find(isWritable);
  if (!target) {
    throw new Error(
      "Could not find a writable location for Acorn's Python environment.\n" +
        "Tried:\n" +
        venvCandidates()
          .map((d) => `  ${d}`)
          .join("\n")
    );
  }

  const stdio = quiet ? ["ignore", "pipe", "pipe"] : "inherit";
  const run = (file, args) => {
    try {
      return execFileSync(file, args, { stdio, encoding: "utf8" });
    } catch (error) {
      // When quiet, execFileSync's own message is just "Command failed" — the
      // actual reason is in the captured streams, so fold it in or the caller
      // has nothing useful to show.
      const detail = [error.stdout, error.stderr]
        .filter(Boolean)
        .join("\n")
        .trim();
      const wrapped = new Error(
        `${path.basename(file)} ${args[0] ?? ""} failed` +
          (detail ? `:\n${detail.split("\n").slice(-15).join("\n")}` : ` (${error.message})`)
      );
      wrapped.cause = error;
      throw wrapped;
    }
  };

  // A half-built venv from an interrupted install would fail confusingly.
  if (fs.existsSync(target) && !fs.existsSync(venvPython(target))) {
    fs.rmSync(target, { recursive: true, force: true });
  }

  if (!fs.existsSync(venvPython(target))) {
    const venvArgs = python.command === "py" ? ["-3", "-m", "venv"] : ["-m", "venv"];
    run(python.command, [...venvArgs, target]);
  }

  const spec = version ? `${PYPI_PACKAGE}==${version}` : PYPI_PACKAGE;
  run(venvPython(target), [
    "-m",
    "pip",
    "install",
    "--upgrade",
    "--disable-pip-version-check",
    // No cache: keeps the installed footprint down, and this runs once.
    "--no-cache-dir",
    spec,
  ]);

  const executable = venvExecutable(target);
  if (!fs.existsSync(executable)) {
    throw new Error(
      `pip reported success but no 'acorn' executable appeared in ${venvBinDir(target)}.`
    );
  }
  return executable;
}

/** Thrown when no suitable interpreter is on PATH. */
class PythonMissingError extends Error {
  constructor(rejected = []) {
    const wanted = `Python ${MIN_PYTHON.join(".")}+`;
    let message = `Acorn needs ${wanted}, which was not found on your PATH.\n`;
    if (rejected.length) {
      const found = rejected.map((r) => `${r.command} (${r.version})`).join(", ");
      message += `\nFound but too old: ${found}\n`;
    }
    message +=
      "\nInstall Python from https://python.org/downloads and reopen your terminal.\n" +
      "Already have it somewhere unusual? Point Acorn at it:\n" +
      "  ACORN_PYTHON=/path/to/python3 acorn\n";
    super(message);
    this.name = "PythonMissingError";
    this.rejected = rejected;
  }
}

module.exports = {
  MIN_PYTHON,
  PYPI_PACKAGE,
  PythonMissingError,
  findExistingVenv,
  findPython,
  install,
  venvExecutable,
};
