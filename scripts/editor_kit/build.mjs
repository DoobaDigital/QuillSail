// Rebuild static/vendor/prosemirror/ from the exact versions in package-lock.json:
//
//     cd scripts/editor_kit && npm ci && npm run build
//
// Only maintainers run this, when updating ProseMirror. The output is committed,
// so installing or running QuillSail never needs Node.
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const output = resolve(here, "../../src/copydesk/static/vendor/prosemirror");
const bundle = join(output, "editor-kit.min.js");

await build({
  entryPoints: [join(here, "entry.js")],
  outfile: bundle,
  bundle: true,
  minify: true,
  format: "iife",
  globalName: "QuillSailEditorKit",
  target: ["es2019"],
  legalComments: "none",
  charset: "utf8",
});

const lock = JSON.parse(readFileSync(join(here, "package-lock.json"), "utf8"));
const notices = [];
const versions = [];
for (const [path, info] of Object.entries(lock.packages)) {
  if (!path || info.dev) continue;
  const directory = join(here, path);
  const name = path.replace(/^node_modules\//, "");
  const license = readdirSync(directory).find(file => /^licen[sc]e/i.test(file));
  if (!license) throw new Error(`${name} ships no license file`);
  versions.push(`- ${name} ${info.version} (${info.license || "see below"})`);
  notices.push(`${name} ${info.version}\n${"-".repeat(40)}\n${readFileSync(join(directory, license), "utf8").trim()}\n`);
}
writeFileSync(join(output, "LICENSES.txt"), notices.join("\n"));
const digest = createHash("sha256").update(readFileSync(bundle)).digest("hex");
writeFileSync(join(output, "README.md"), `# Prebuilt editor kit

\`editor-kit.min.js\` is ProseMirror, bundled for the visual editor. Don't edit it by hand.
Rebuild it with \`scripts/editor_kit\`, which pins these versions:

${versions.join("\n")}

SHA-256 of \`editor-kit.min.js\`: \`${digest}\`

The licenses of everything inside the bundle are in \`LICENSES.txt\`.
`);
console.log(`editor-kit.min.js sha256 ${digest}`);
