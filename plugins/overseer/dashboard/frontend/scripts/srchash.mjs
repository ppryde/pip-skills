#!/usr/bin/env node
/**
 * Writes `dist/.srchash` — a content hash of `src/**` used by the backend's
 * dist-freshness pytest (`backend/tests/test_dist_freshness.py`) to detect a
 * `dist/` that is stale relative to `src/`.
 *
 * Deliberately dependency-free (Node's `crypto` + `fs` only) and run as the
 * last step of `npm run build`.
 *
 * HASHING RULE (must be mirrored byte-for-byte by the Python side):
 *   1. List every FILE (not directory) under `src/`, recursively.
 *   2. Take each file's path relative to `src/`, normalised to forward
 *      slashes (POSIX-style), and sort the list lexicographically
 *      (plain ascending string sort — all paths here are ASCII, so this
 *      agrees between Node and Python).
 *   3. Feed a single sha256 hash, in that sorted order, for each file:
 *        - the relative path, UTF-8 bytes, then a NUL byte
 *        - the file's raw bytes, then a NUL byte
 *   4. The hex digest of that hash is the "srchash". It is written to
 *      `dist/.srchash` with a trailing newline (the reader trims
 *      whitespace, so the newline is cosmetic).
 *
 * mtimes are NEVER used — git does not preserve them, so they are useless
 * as a staleness signal across clones/checkouts.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = fileURLToPath(new URL(".", import.meta.url));
const frontendRoot = join(scriptDir, "..");
const srcDir = join(frontendRoot, "src");
const distDir = join(frontendRoot, "dist");

/** Recursively list absolute file paths under `dir`. */
function listFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...listFiles(full));
    } else if (entry.isFile()) {
      out.push(full);
    }
  }
  return out;
}

export function computeSrcHash(srcRoot) {
  const relPaths = listFiles(srcRoot)
    .map((f) => relative(srcRoot, f).split(sep).join("/"))
    .sort();

  const hash = createHash("sha256");
  for (const rel of relPaths) {
    hash.update(Buffer.from(rel, "utf8"));
    hash.update(Buffer.from([0]));
    hash.update(readFileSync(join(srcRoot, rel)));
    hash.update(Buffer.from([0]));
  }
  return hash.digest("hex");
}

function main() {
  const digest = computeSrcHash(srcDir);
  mkdirSync(distDir, { recursive: true });
  writeFileSync(join(distDir, ".srchash"), `${digest}\n`, "utf8");
  console.log(`wrote dist/.srchash = ${digest}`);
}

main();
