// Воспроизводит сохранённый редактируемый эталон; PDF и отчёты не собирает.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const sourceDir = path.dirname(fileURLToPath(import.meta.url));
const runtime = process.env.CINIMEX_ARTIFACT_TOOL ?? path.join(os.homedir(),
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool');
const metadata = JSON.parse(await fs.readFile(path.join(runtime, 'package.json'), 'utf8'));
if (metadata.name !== '@oai/artifact-tool') throw new Error('Нужен пакет @oai/artifact-tool');
let entry;
for (const relative of ['dist/node/artifact_tool.mjs', 'dist/artifact_tool.mjs']) {
  const candidate = path.join(runtime, relative);
  if (await fs.access(candidate).then(() => true, () => false)) { entry = candidate; break; }
}
if (!entry) throw new Error('Не найден модуль @oai/artifact-tool в CINIMEX_ARTIFACT_TOOL');
const { Presentation, PresentationFile } = await import(pathToFileURL(entry).href);
const { Canvas, loadImage } = createRequire(entry)('skia-canvas');
const proto = JSON.parse(await fs.readFile(path.join(sourceDir, 'template.json'), 'utf8'));
for (const item of proto.images) {
  const logo = await loadImage(path.join(sourceDir, item.asset));
  const canvas = new Canvas(600, 128);
  canvas.getContext('2d').drawImage(logo, 0, 0, 600, 128);
  item.data = new Uint8Array(await canvas.toBuffer('png'));
  delete item.asset;
}
const presentation = Presentation.load(proto);
const out = path.resolve(process.argv[2] ?? path.join(sourceDir,
  '../../../dist/slides/cinimex-consulting-reference.pptx'));
await fs.mkdir(path.dirname(out), { recursive: true });
const previewDir = await fs.mkdtemp(path.join(os.tmpdir(), 'cinimex-consulting-'));
for (const [index, slide] of presentation.slides.items.entries()) {
  const png = await presentation.export({ slide, format: 'png', scale: 1.5 });
  await fs.writeFile(path.join(previewDir, `slide-${index + 1}.png`),
    new Uint8Array(await png.arrayBuffer()));
}
const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(out);
console.log(JSON.stringify({ output: out, preview: previewDir,
  slides: presentation.slides.items.length, runtime: metadata.version }));
