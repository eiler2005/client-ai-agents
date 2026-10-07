// Редактируемые объекты PowerPoint; стиль и данные приходят из проверенных YAML.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";

const [inputPath, outputPath, runtimePath] = process.argv.slice(2);
const { Presentation, PresentationFile } = await import(pathToFileURL(runtimePath).href);
const { Canvas } = createRequire(runtimePath)("skia-canvas");
const measure = new Canvas(1, 1).getContext("2d");
const deck = JSON.parse(await fs.readFile(inputPath, "utf8"));
const { colors: C, typography: T, font, canvas } = deck.style;
const presentation = Presentation.create({ slideSize: canvas });
const qa = path.join(path.dirname(inputPath), "preview");
await fs.mkdir(qa, { recursive: true });
const bounds = [];
let abridged = 0;

function short(value, limit = 180) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (text.length <= limit) return text;
  return text.slice(0, limit - 1).replace(/\s+\S*$/, "") + "…";
}

function fit(value, width, height, size, bold = false) {
  measure.font = `${bold ? "bold " : ""}${size}px ${font}`;
  const maxLines = Math.max(1, Math.floor(height / (size * 1.3)));
  let body = String(value);
  function fits(candidate) {
    let count = 0;
    for (const paragraph of candidate.split("\n")) {
      let line = "";
      count++;
      for (const word of paragraph.split(/\s+/)) {
        if (measure.measureText(word).width > width) return false;
        const next = line ? `${line} ${word}` : word;
        if (measure.measureText(next).width > width) { count++; line = word; }
        else line = next;
      }
    }
    return count <= maxLines;
  }
  if (fits(body)) return body;
  abridged++;
  const words = body.split(/\s+/);
  while (words.length > 1) {
    words.pop();
    body = words.join(" ") + "…";
    if (fits(body)) return body;
  }
  throw new Error(`Текст не помещается без потери смысла: ${value}`);
}

function text(slide, value, x, y, width, height, size = T.body, color = C.ink, bold = false) {
  const shape = slide.shapes.add({
    geometry: "textbox", name: `text-${bounds.length}`,
    position: { left: x, top: y, width, height },
    fill: "none", line: { fill: "none", width: 0, style: "solid" },
  });
  shape.text = fit(value, width, height, size, bold);
  shape.text.style = { fontSize: size, typeface: font, color, bold,
    verticalAlignment: "top", insets: { left: 0, right: 0, top: 0, bottom: 0 } };
  bounds.push({ slide: presentation.slides.items.length, x, y, width, height, value });
  return shape;
}

function base(part, index) {
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  const page = part.pages > 1 ? ` · часть ${part.page} из ${part.pages}` : "";
  text(slide, deck.brand + page, 96, 32, 1200, 28, T.source, C.muted, true);
  if (part.kind !== "cover") text(slide, short(part.title, 130), 96, 91, 1408, 135, T.title, C.ink, true);
  text(slide, short(part.source, 190), 96, 825, 1280, 42, T.source, C.muted);
  text(slide, `${index + 1}`, 1432, 827, 72, 30, T.source, C.muted);
  text(slide, "Конфиденциально", 96, 790, 320, 26, T.source, C.muted);
  slide.speakerNotes.textFrame.setText([
    part.title, part.source, JSON.stringify(part, null, 2),
    "Источники:", JSON.stringify(deck.references ?? [], null, 2),
    "Замечания:", ...deck.warnings,
  ]);
  return slide;
}

function points(slide, items, x, y, width, max = 4, height = 105, limit = 200) {
  for (const [index, point] of items.slice(0, max).entries()) {
    text(slide, `${index + 1}.`, x, y + index * height, 42, 45, T.heading, C.accent, true);
    text(slide, short(point, limit), x + 56, y + index * height, width - 56,
      height - 18, T.body);
  }
}

function addTable(slide, part) {
  const n = part.headers.length;
  const widths = n === 2 ? [704, 704] : [370, 565, 473];
  const values = [part.headers, ...part.rows.map(row => row.map((cell, i) =>
    fit(String(cell), widths[i] - 36, 157, T.body)))];
  const table = slide.tables.add({
    rows: values.length, columns: n, left: 96, top: 270,
    width: 1408, height: 430, columnWidths: widths, values,
  });
  table.borders.assign({ style: "solid", color: C.grid, width: 1 });
  table.cells.block({ row: 0, column: 0, rowCount: values.length, columnCount: n }).assign({
    fill: C.paper, textStyle: { typeface: font, fontSize: T.body, color: C.ink },
    margins: { left: 18, right: 18, top: 14, bottom: 14 }, anchor: "top",
  });
  for (let col = 0; col < n; col++) {
    table.getCell(0, col).fill = C.light;
    table.getCell(0, col).text.style = { fontSize: T.body, typeface: font, bold: true, color: C.ink };
  }
  table.rows[0].height = 60;
  for (let row = 1; row < values.length; row++) table.rows[row].height = 185;
  if (part.caveat) text(slide, short(part.caveat, 270), 96, 728, 1408, 54, T.source, C.muted);
}

function score(slide, part) {
  const scored = part.dimensions.filter(item => item.level !== null);
  const chartItems = [...scored].reverse();
  if (scored.length) {
    slide.charts.add("bar", {
      position: { left: 96, top: 275, width: 950, height: 440 },
      categories: chartItems.map(item => String(part.dimensions.indexOf(item) + 1)),
      series: [{ name: "Уровень", values: chartItems.map(item => item.level), fill: C.accent }],
      barOptions: { direction: "bar", grouping: "clustered", gapWidth: 60 },
      hasLegend: false,
      xAxis: { visible: true, textStyle: { fontSize: 20, typeface: font, fill: C.ink } },
      yAxis: { visible: true, min: 0, max: 4, majorUnit: 1,
        textStyle: { fontSize: 20, typeface: font, fill: C.muted },
        majorGridlines: { fill: C.grid, width: 1, style: "solid" } },
      dataLabels: { showValue: true, position: "outEnd",
        textStyle: { fontSize: 22, typeface: font, fill: C.ink, bold: true } },
    });
  } else {
    text(slide, "Измерения пока не оценены", 96, 300, 880, 100, T.heading, C.muted);
  }
  for (const [index, item] of part.dimensions.entries()) {
    const y = 265 + index * 78;
    const blocking = item.blocking && item.level !== null && item.level <= 1;
    text(slide, `${index + 1}. ${short(item.name, 32)}`, 1100, y, 404, 35, 24,
      blocking ? C.critical : C.ink, true);
    text(slide, item.level === null ? "Не оценено" : `Уровень ${item.level} · уверенность ${item.confidence}`,
      1100, y + 36, 404, 35, 22, blocking ? C.critical : C.muted);
  }
}

for (const [index, part] of deck.slides.entries()) {
  const slide = base(part, index);
  if (part.kind === "cover") {
    text(slide, short(part.title, 115), 96, 210, 1408, 280, T.cover, C.ink, true);
    text(slide, part.subtitle, 96, 525, 1408, 65, T.heading, C.accent);
    text(slide, `${part.client} · ${part.date}`, 96, 625, 1408, 50, T.body, C.muted);
    text(slide, part.status === "final" ? "Итоговые материалы" : "Черновик · выводы могут измениться",
      96, 700, 1408, 45, T.body, C.muted);
  } else if (part.kind === "summary") {
    const spacing = 1408 / part.metrics.length;
    for (const [i, [value, label]] of part.metrics.entries()) {
      text(slide, value, 96 + i * spacing, 265, spacing - 36, 100, T.cover, C.accent, true);
      text(slide, label, 96 + i * spacing, 372, spacing - 40, 75, T.body, C.muted);
    }
    points(slide, part.points, 96, 486, 1408, 3, 92, 225);
    if (part.warnings?.length) text(slide, short(part.warnings.join("; "), 200),
      96, 754, 1408, 28, T.source, C.critical);
  } else if (part.kind === "score") {
    score(slide, part);
  } else if (part.kind === "table") {
    addTable(slide, part);
  } else if (part.kind === "closing") {
    points(slide, part.points, 96, 275, 760, 4, 112, 160);
    const contact = part.contacts[0];
    if (contact) {
      text(slide, contact.name, 930, 275, 574, 60, T.heading, C.ink, true);
      text(slide, [contact.role, contact.unit].filter(Boolean).join("\n"), 930, 350, 574, 120, T.body, C.muted);
      text(slide, [contact.phone, contact.email, contact.telegram ? `Telegram: @${contact.telegram}` : ""]
        .filter(Boolean).join("\n"), 930, 490, 574, 160, T.body, C.accent);
    }
    text(slide, [part.organisation, part.site].filter(Boolean).join(" · "), 930, 690, 574, 70, 22, C.muted);
  } else {
    const extras = part.assumptions ?? part.exclusions ?? [];
    if (extras.length) {
      points(slide, part.points, 96, 275, 820, 4, 112, 180);
      text(slide, part.assumptions ? "Допущения" : "Вне периметра", 1010, 275, 494, 65, T.heading, C.ink, true);
      points(slide, extras, 1010, 365, 494, 3, 125, 110);
    } else {
      points(slide, part.points, 96, 275, 1408, 4, 112, 270);
    }
    if (part.caveat) text(slide, short(part.caveat, 270), 96, 735, 1408, 45, T.source, C.muted);
  }
}

const outside = bounds.filter(box => box.x < 0 || box.y < 0 ||
  box.x + box.width > canvas.width || box.y + box.height > canvas.height);
if (outside.length) throw new Error(`Объекты выходят за границы слайда: ${JSON.stringify(outside)}`);
for (let i = 0; i < bounds.length; i++) {
  for (let j = i + 1; j < bounds.length; j++) {
    const a = bounds[i], b = bounds[j];
    if (a.slide === b.slide && Math.min(a.x + a.width, b.x + b.width) > Math.max(a.x, b.x) &&
      Math.min(a.y + a.height, b.y + b.height) > Math.max(a.y, b.y)) {
      throw new Error(`Наложение текстовых блоков на слайде ${a.slide}: ${a.value} / ${b.value}`);
    }
  }
}
for (const [index, slide] of presentation.slides.items.entries()) {
  const name = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await presentation.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(qa, `${name}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(qa, `${name}.layout.json`), await layout.text());
}
const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(outputPath);
const bytes = await fs.readFile(outputPath);
const manifest = {
  document: "presentation", id: deck.id, kind: deck.kind, date: deck.date,
  style_version: deck.style.version, slides: deck.slides.length,
  output: path.basename(outputPath), sha256: createHash("sha256").update(bytes).digest("hex"),
  inputs: deck.inputs,
  renderer: deck.renderer,
  checks: { text_bounds: true, text_overlaps: false, measured_text_fit: true,
    abridged_blocks: abridged, previews: deck.slides.length, visual_review: false,
    notes: deck.warnings, pdf_built: false },
};
await fs.writeFile(outputPath.replace(/\.pptx$/, ".manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(JSON.stringify({ output: outputPath, preview: qa }));
