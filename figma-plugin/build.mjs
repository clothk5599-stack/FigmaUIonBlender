// Bundles code.ts -> dist/code.js and inlines the bundled ui.ts into
// dist/ui.html (Figma loads the UI as a single HTML string).
import { mkdir, readFile, writeFile } from "node:fs/promises";
import * as esbuild from "esbuild";

const watch = process.argv.includes("--watch");
const common = { bundle: true, target: "es2017", logLevel: "info" };

async function buildUI() {
  const result = await esbuild.build({ ...common, entryPoints: ["ui.ts"], write: false });
  const js = result.outputFiles[0].text.replace(/<\/script/gi, "<\\/script");
  const html = await readFile("ui.html", "utf8");
  const tag = '<script src="ui.js"></script>';
  if (!html.includes(tag)) throw new Error(`ui.html must contain ${tag}`);
  await writeFile("dist/ui.html", html.replace(tag, () => `<script>\n${js}</script>`));
}

await mkdir("dist", { recursive: true });

if (watch) {
  const code = await esbuild.context({ ...common, entryPoints: ["code.ts"], outfile: "dist/code.js" });
  await code.watch();
  const ui = await esbuild.context({
    ...common,
    entryPoints: ["ui.ts"],
    write: false,
    plugins: [{
      name: "inline-ui",
      setup(build) {
        build.onEnd(async (result) => {
          if (result.errors.length === 0) await buildUI();
        });
      },
    }],
  });
  await ui.watch();
} else {
  await esbuild.build({ ...common, entryPoints: ["code.ts"], outfile: "dist/code.js" });
  await buildUI();
}
