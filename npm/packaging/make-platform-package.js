#!/usr/bin/env node
"use strict";

/**
 * Wraps a PyInstaller-built binary into a per-platform npm package.
 *
 * The main `acorn-agent` package lists these as optionalDependencies. npm reads
 * each one's `os`/`cpu` fields and installs only the one matching the host, so a
 * user downloads a single ~30MB binary rather than all five.
 *
 * Usage:
 *   node make-platform-package.js --binary <path> --platform darwin --arch arm64 \
 *     --version 2.3.1 --outdir ./dist
 */

const fs = require("node:fs");
const path = require("node:path");

const SUPPORTED = {
  "darwin-arm64": { os: "darwin", cpu: "arm64", label: "macOS (Apple Silicon)" },
  "darwin-x64": { os: "darwin", cpu: "x64", label: "macOS (Intel)" },
  "linux-x64": { os: "linux", cpu: "x64", label: "Linux (x86_64)" },
  "linux-arm64": { os: "linux", cpu: "arm64", label: "Linux (arm64)" },
  "win32-x64": { os: "win32", cpu: "x64", label: "Windows (x86_64)" },
};

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`expected a --flag, got "${key}"`);
    args[key.slice(2)] = argv[i + 1];
  }
  return args;
}

function main() {
  const { binary, platform, arch, version, outdir } = parseArgs(process.argv.slice(2));

  for (const [name, value] of Object.entries({ binary, platform, arch, version, outdir })) {
    if (!value) throw new Error(`missing required --${name}`);
  }

  const key = `${platform}-${arch}`;
  const target = SUPPORTED[key];
  if (!target) {
    throw new Error(
      `unsupported target "${key}". Known: ${Object.keys(SUPPORTED).join(", ")}`
    );
  }

  if (!fs.existsSync(binary)) throw new Error(`binary not found: ${binary}`);

  const packageName = `acorn-agent-${key}`;
  const packageDir = path.join(outdir, packageName);
  const binDir = path.join(packageDir, "bin");
  fs.mkdirSync(binDir, { recursive: true });

  const executableName = target.os === "win32" ? "acorn.exe" : "acorn";
  const destination = path.join(binDir, executableName);
  fs.copyFileSync(binary, destination);
  // The exec bit does not survive every CI artifact round trip, and npm
  // preserves whatever mode it finds at pack time.
  if (target.os !== "win32") fs.chmodSync(destination, 0o755);

  const manifest = {
    name: packageName,
    version,
    description: `Acorn standalone binary for ${target.label}`,
    // No `bin` field: this package is a payload, not a CLI. The main package's
    // launcher resolves this path itself. Declaring a bin here would create a
    // second `acorn` on PATH and race with the launcher's own shim.
    repository: {
      type: "git",
      url: "git+https://github.com/andamagodwin/acorn.git",
      directory: "npm",
    },
    homepage: "https://acorncli.dev",
    license: "MIT",
    author: "Andama Godwin",
    // npm refuses to install a package whose os/cpu don't match the host, which
    // is exactly what makes the optionalDependencies fan-out work.
    os: [target.os],
    cpu: [target.cpu],
    files: ["bin/"],
    preferUnplugged: true,
  };

  fs.writeFileSync(
    path.join(packageDir, "package.json"),
    JSON.stringify(manifest, null, 2) + "\n"
  );

  fs.writeFileSync(
    path.join(packageDir, "README.md"),
    `# ${packageName}\n\n` +
      `Standalone Acorn binary for ${target.label}.\n\n` +
      "This is an internal platform package. Install the main package instead:\n\n" +
      "```bash\nnpm install -g acorn-agent\n```\n\n" +
      "See [acorncli.dev](https://acorncli.dev).\n"
  );

  const sizeMb = (fs.statSync(destination).size / 1024 / 1024).toFixed(1);
  console.log(`${packageName}@${version}  ${sizeMb}MB  ${target.label}`);
}

// Only build when invoked as a script. Tests import SUPPORTED to check it
// against package.json's optionalDependencies, and must not trigger a build.
if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(`make-platform-package: ${error.message}`);
    process.exit(1);
  }
}

module.exports = { SUPPORTED };
