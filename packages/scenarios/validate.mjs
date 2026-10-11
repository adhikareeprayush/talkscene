#!/usr/bin/env node
/**
 * Validates every scenario pack against schema.json, then applies the
 * cross-field rules a JSON Schema cannot express (plan §12.2 step 2).
 * Exit code 1 on any error. Warnings do not fail the build.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv from "ajv";
import addFormats from "ajv-formats";
import { parse } from "yaml";

const here = dirname(fileURLToPath(import.meta.url));
const schema = JSON.parse(readFileSync(join(here, "schema.json"), "utf8"));
const ajv = addFormats(new Ajv({ allErrors: true, strict: false }));
const validate = ajv.compile(schema);

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const p = join(dir, entry);
    return statSync(p).isDirectory() ? walk(p) : p.endsWith(".yaml") || p.endsWith(".yml") ? [p] : [];
  });
}

const errors = [];
const warnings = [];
const seen = new Map();
const files = walk(join(here, "packs")).sort();

for (const file of files) {
  const rel = file.slice(here.length + 1);
  let doc;
  try {
    doc = parse(readFileSync(file, "utf8"));
  } catch (e) {
    errors.push(`${rel}: unparseable YAML - ${e.message}`);
    continue;
  }

  if (!validate(doc)) {
    for (const e of validate.errors) errors.push(`${rel}: ${e.instancePath || "/"} ${e.message}`);
    continue;
  }

  if (seen.has(doc.id)) errors.push(`${rel}: duplicate id "${doc.id}" (also in ${seen.get(doc.id)})`);
  seen.set(doc.id, rel);

  if (!doc.id.startsWith(`${doc.language}-`))
    errors.push(`${rel}: id "${doc.id}" does not start with language "${doc.language}-"`);
  if (!doc.id.endsWith(`-${doc.level.toLowerCase()}`))
    errors.push(`${rel}: id "${doc.id}" does not end with level "-${doc.level.toLowerCase()}"`);

  const dirLang = basename(dirname(file));
  if (dirLang !== doc.language) errors.push(`${rel}: lives in packs/${dirLang}/ but language is "${doc.language}"`);

  const { min, default: def, max } = doc.turn_limits;
  if (!(min <= def && def <= max)) errors.push(`${rel}: turn_limits must satisfy min <= default <= max`);

  const ids = doc.goals.map((g) => g.id);
  if (new Set(ids).size !== ids.length) errors.push(`${rel}: duplicate goal ids`);

  if (doc.title[doc.language] === undefined && doc.language !== "en")
    warnings.push(`${rel}: no "${doc.language}" title - the library card will fall back to English`);
  if (!doc.voice?.azure) warnings.push(`${rel}: no Azure voice - premium TTS will pick the language default`);
  if (doc.status !== "published") warnings.push(`${rel}: status "${doc.status ?? "draft"}" - hidden from the public catalog`);
}

const byLang = {};
for (const [, rel] of seen) {
  const lang = rel.split("/")[1];
  byLang[lang] = (byLang[lang] ?? 0) + 1;
}

for (const w of warnings) console.warn(`  warn  ${w}`);
for (const e of errors) console.error(`  ERROR ${e}`);
console.log(
  `\n${files.length} scenario file(s): ` +
    Object.entries(byLang).map(([l, n]) => `${l}=${n}`).join(" ") +
    `  |  ${errors.length} error(s), ${warnings.length} warning(s)`
);
process.exit(errors.length ? 1 : 0);
