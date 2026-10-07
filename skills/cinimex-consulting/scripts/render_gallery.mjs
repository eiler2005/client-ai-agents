#!/usr/bin/env node
/**
 * Original, fictional Cinimex consulting compositions.
 * Run with Node.js 22+: node render_gallery.mjs --out output/gallery
 * No client files, source decks, web assets, or repository code are imported.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { inflateRawSync } from 'node:zlib';
import { fileURLToPath, pathToFileURL } from 'node:url';

const sourceDirectory = path.dirname(fileURLToPath(import.meta.url));
const tokenPath = path.resolve(sourceDirectory, '../assets/design-tokens.json');
const tokens = JSON.parse(await fs.readFile(tokenPath, 'utf8'));
if (tokens.slides?.unit !== 'px' || !tokens.colors || !tokens.slides.font) throw new Error('Invalid slide design tokens');
const C = Object.freeze(tokens.colors);
const SIZE = { width: tokens.slides.width, height: tokens.slides.height };
const FONT = tokens.slides.font;
const BODY = tokens.slides.body;
const MIN_BODY = tokens.slides.minBody;
const TITLE = tokens.slides.title;
const SOURCE = tokens.slides.source;
const FICTION = 'ВЫМЫШЛЕННЫЙ ПРИМЕР · ДАННЫЕ ДЛЯ ДЕМОНСТРАЦИИ';
const CLAIMS = [
  { id: 'Q00', text: 'Срез: конец недели 4.', kind: 'fictional-as-of', value: 4, unit: 'demo-week' },
  { id: 'Q01', text: 'Базовый план проверки завершается в демонстрационную неделю 5.', kind: 'fictional-baseline', value: 5, unit: 'demo-week' },
  { id: 'Q02', text: 'Текущий прогноз проверки завершается в демонстрационную неделю 6.', kind: 'fictional-forecast', value: 6, unit: 'demo-week' },
  { id: 'Q03', text: 'Пилот можно начать после проверки источников. Решение сейчас: назначить владельца данных и согласовать проверку неизвестных случаев.', kind: 'fictional-decision' },
  { id: 'F01', text: 'Периметр согласован: один тип внутренних запросов.', kind: 'fictional-status' },
  { id: 'F02', text: 'Рабочий сценарий собран; источники проверены частично.', kind: 'fictional-status' },
  { id: 'F03', text: 'Риск: нет подтверждённого источника для исключений.', kind: 'fictional-risk' },
  { id: 'F04', text: 'Зависимость: владелец данных должен разобрать примеры.', kind: 'fictional-dependency' },
  { id: 'G1', text: 'Согласовать периметр', criteria: ['A'], decision_role: 'владелец процесса', kind: 'fictional-gate' },
  { id: 'G2', text: 'Разрешить сборку', criteria: ['A', 'B'], decision_role: 'архитектор', kind: 'fictional-gate' },
  { id: 'G3', text: 'Решить о расширении', criteria: ['A', 'B', 'C'], decision_role: 'владелец процесса', kind: 'fictional-gate' },
  { id: 'G4', text: 'Принять в сопровождение', criteria: ['A', 'B', 'C', 'D'], decision_role: 'владелец сервиса', kind: 'fictional-gate' },
  { id: 'W01', text: 'Агент готовит ответ; эксперт разбирает пробелы.', kind: 'fictional-role-allocation' },
  { id: 'W02', text: 'При отсутствии основания ответ остановлен до подтверждения; эксперт разбирает неизвестное.', kind: 'fictional-exception' },
];

function parseArgs(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') options.help = true;
    else if (arg === '--out') {
      if (!argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error('--out requires a directory or .pptx path');
      options.out = argv[++i];
    } else throw new Error(`Unknown argument: ${arg}`);
  }
  return options;
}

async function exists(candidate) {
  return fs.access(candidate).then(() => true, () => false);
}

async function loadArtifactTool() {
  const override = process.env.CINIMEX_ARTIFACT_TOOL;
  const candidates = [];
  if (override) candidates.push(path.resolve(override));
  else {
    try { candidates.push(fileURLToPath(import.meta.resolve('@oai/artifact-tool'))); } catch { /* Use the runtime fallback below. */ }
    candidates.push(path.join(os.homedir(), '.cache', 'codex-runtimes',
      'codex-primary-runtime', 'dependencies', 'node', 'node_modules', '@oai', 'artifact-tool'));
  }
  for (const candidate of candidates) {
    let entry;
    if (await exists(candidate) && (await fs.stat(candidate)).isFile()) entry = candidate;
    else {
      for (const relative of ['dist/node/artifact_tool.mjs', 'dist/artifact_tool.mjs']) {
        const possible = path.join(candidate, relative);
        if (await exists(possible)) { entry = possible; break; }
      }
    }
    if (!entry) continue;
    const artifact = await import(pathToFileURL(entry).href);
    if (!artifact.Presentation || !artifact.PresentationFile) throw new Error(`Invalid artifact-tool entry: ${entry}`);
    const require = createRequire(entry);
    const { Canvas } = require('skia-canvas');
    let metadata = { name: '@oai/artifact-tool', version: 'unknown' };
    for (const directory of [candidate, path.dirname(path.dirname(entry)), path.dirname(path.dirname(path.dirname(entry)))]) {
      try {
        const possible = JSON.parse(await fs.readFile(path.join(directory, 'package.json'), 'utf8'));
        if (possible.name === '@oai/artifact-tool') { metadata = possible; break; }
      } catch { /* Metadata is optional; the API export check above is required. */ }
    }
    return { ...artifact, Canvas, metadata };
  }
  throw new Error('Cannot resolve @oai/artifact-tool. Install it or set CINIMEX_ARTIFACT_TOOL to its package directory or ES-module entry.');
}

function outputPaths(value) {
  const requested = path.resolve(value ?? path.join('output', 'consulting-skill-gallery'));
  if (requested.toLowerCase().endsWith('.pptx')) {
    const stem = requested.slice(0, -5);
    return { directory: path.dirname(requested), pptx: requested,
      preview: `${stem}-preview`, layout: `${stem}-layout`,
      manifest: `${stem}.manifest.json`, text: `${stem}.text.txt` };
  }
  return { directory: requested, pptx: path.join(requested, 'consulting-gallery.pptx'),
    preview: path.join(requested, 'preview'), layout: path.join(requested, 'layout'),
    manifest: path.join(requested, 'consulting-gallery.manifest.json'),
    text: path.join(requested, 'consulting-gallery.text.txt') };
}

function normalize(value) { return String(value).replace(/\s+/gu, ''); }
function xmlText(value) {
  return value.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&apos;/g, "'");
}

// Read the small OOXML package directly, without a second presentation library.
function unzip(bytes) {
  let eocd = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
    if (bytes.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('Exported PPTX has no ZIP directory');
  const entries = new Map();
  const count = bytes.readUInt16LE(eocd + 10);
  let offset = bytes.readUInt32LE(eocd + 16);
  for (let i = 0; i < count; i++) {
    if (bytes.readUInt32LE(offset) !== 0x02014b50) throw new Error('Invalid PPTX ZIP directory');
    const method = bytes.readUInt16LE(offset + 10);
    const compressedSize = bytes.readUInt32LE(offset + 20);
    const nameLength = bytes.readUInt16LE(offset + 28);
    const extraLength = bytes.readUInt16LE(offset + 30);
    const commentLength = bytes.readUInt16LE(offset + 32);
    const local = bytes.readUInt32LE(offset + 42);
    const name = bytes.subarray(offset + 46, offset + 46 + nameLength).toString('utf8');
    const dataStart = local + 30 + bytes.readUInt16LE(local + 26) + bytes.readUInt16LE(local + 28);
    const compressed = bytes.subarray(dataStart, dataStart + compressedSize);
    if (method !== 0 && method !== 8) throw new Error(`Unsupported ZIP compression: ${method}`);
    entries.set(name, method === 8 ? inflateRawSync(compressed) : compressed);
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function inspectPptx(bytes, expectedSlides) {
  const entries = unzip(bytes);
  const slides = [...entries.keys()].filter(name => /^ppt\/slides\/slide\d+\.xml$/.test(name))
    .sort((a, b) => Number(a.match(/slide(\d+)/)[1]) - Number(b.match(/slide(\d+)/)[1]));
  if (slides.length !== expectedSlides.length) throw new Error('Exported PPTX slide count differs from the source');
  const result = [];
  for (const [i, name] of slides.entries()) {
    const xml = entries.get(name).toString('utf8');
    const text = [...xml.matchAll(/<a:t>([\s\S]*?)<\/a:t>/g)].map(match => xmlText(match[1])).join('\n');
    const missing = expectedSlides[i].visible.filter(item => !normalize(text).includes(normalize(item.text)));
    if (missing.length) throw new Error(`PPTX lost visible copy on slide ${i + 1}: ${missing.map(item => item.name).join(', ')}`);
    const images = (xml.match(/<p:pic(?:\s|>)/g) ?? []).length;
    const shapes = (xml.match(/<p:sp(?:\s|>)/g) ?? []).length;
    const connectors = (xml.match(/<p:cxnSp(?:\s|>)/g) ?? []).length;
    const tables = (xml.match(/<a:tbl(?:\s|>)/g) ?? []).length;
    if (images || !shapes) throw new Error(`Slide ${i + 1} must contain native editable objects and no images`);
    result.push({ slide: i + 1, shapes, connectors, tables, images, text, missing_copy: [] });
  }
  return result;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log('Usage: node render_gallery.mjs [--out DIRECTORY|FILE.pptx]\nCreates 3 original fictional editable slides, PNG previews, layout JSON, extracted text and a manifest.\nDependency: @oai/artifact-tool; optional CINIMEX_ARTIFACT_TOOL package directory or module entry.');
    return;
  }
  const { Presentation, PresentationFile, Canvas, metadata } = await loadArtifactTool();
  const out = outputPaths(options.out);
  await fs.mkdir(out.directory, { recursive: true });
  await fs.mkdir(out.preview, { recursive: true });
  await fs.mkdir(out.layout, { recursive: true });
  const measure = new Canvas(1, 1).getContext('2d');
  const presentation = Presentation.create({ slideSize: SIZE });
  const records = [];

  function wrap(value, width, size, bold = false) {
    measure.font = `${bold ? 'bold ' : ''}${size}px ${FONT}`;
    const lines = [];
    for (const paragraph of String(value).split('\n')) {
      let current = '';
      for (const word of paragraph.split(/\s+/u).filter(Boolean)) {
        const next = current ? `${current} ${word}` : word;
        if (measure.measureText(next).width > width - 3 && current) { lines.push(current); current = word; }
        else current = next;
      }
      lines.push(current);
    }
    return lines;
  }

  function rect(slide, name, x, y, w, h, fill = C.white, stroke = 'none', weight = 0) {
    return slide.shapes.add({ geometry: 'rect', name,
      position: { left: x, top: y, width: w, height: h }, fill,
      line: { style: 'solid', fill: stroke, width: weight } });
  }

  function rule(slide, name, x, y, w, color = C.grid, weight = 1) {
    return slide.shapes.add({ geometry: 'line', name,
      position: { left: x, top: y, width: w, height: 0 }, fill: 'none',
      line: { style: 'solid', fill: color, width: weight } });
  }

  function text(slide, name, value, x, y, w, h, size = BODY, color = C.navy, bold = false, alignment = 'left', kind = 'body') {
    const lines = wrap(value, w, size, bold);
    const estimatedHeight = lines.length * size * 1.18;
    if (estimatedHeight > h + 2) throw new Error(`${name}: ${lines.length} lines do not fit ${h}px`);
    if (kind === 'body' && size < MIN_BODY) throw new Error(`${name}: body type is below the token minimum`);
    if (x < 0 || y < 0 || x + w > SIZE.width || y + h > SIZE.height) throw new Error(`${name}: object outside canvas`);
    const shape = slide.shapes.add({ geometry: 'textbox', name,
      position: { left: x, top: y, width: w, height: h }, fill: 'none',
      line: { style: 'solid', fill: 'none', width: 0 } });
    shape.text = lines.join('\n');
    shape.text.style = { fontSize: size, typeface: FONT, color, bold, alignment,
      verticalAlignment: 'top', wrap: 'none', autoFit: 'none', lineSpacing: 1.0,
      insets: { left: 0, right: 0, top: 0, bottom: 0 } };
    records.at(-1).visible.push({ name, text: value, fontSize: size, kind, bounds: [x, y, w, h], lines: lines.length });
    return shape;
  }

  function base(id, title, subtitle) {
    const slide = presentation.slides.add();
    records.push({ id, title, visible: [], intentional_overlaps: [] });
    slide.background.fill = C.white;
    rect(slide, `${id}-top-rule`, 72, 30, 1136, 3, C.navy);
    rect(slide, `${id}-orange-rule`, 72, 30, 70, 3, C.orange);
    text(slide, `${id}-fiction`, FICTION, 72, 40, 860, 22, MIN_BODY - 2, C.muted, true, 'left', 'label');
    text(slide, `${id}-title`, title, 72, 69, 1136, 47, TITLE, C.navy, true, 'left', 'title');
    text(slide, `${id}-subtitle`, subtitle, 72, 123, 1136, 49, BODY, C.muted);
    text(slide, `${id}-footer`, 'Синимекс · оригинальная учебная композиция · источник: вымышленный сценарий',
      72, 686, 1040, 20, SOURCE, C.muted, false, 'left', 'source');
    text(slide, `${id}-page`, String(records.length).padStart(2, '0'), 1158, 683, 50, 25, MIN_BODY, C.navy, true, 'right', 'label');
    return slide;
  }

  // 1. Evidence matrix: every phase owns the same four fields. Gate rows are
  // actual boundaries; cumulative criteria are named sets, not area or volume.
  {
    const slide = base('stage-gates', 'Каждый этап завершается проверяемым решением',
      'Демонстрация для сервиса внутренних запросов. Сроки, пороги качества и объём пилота требуют отдельного согласования.');
    const values = [
      ['Этап', 'Результат', 'Доказательство', 'Ответственная роль'],
      ['01 · Обследование', 'Карта запросов\nи рамки пилота', 'Примеры сценариев;\nреестр неизвестного', 'Владелец процесса'],
      ['G1 · Согласовать периметр — критерии {A}', '', '', ''],
      ['02 · Проектирование', 'Путь запроса\nи правила передачи', 'Матрица ролей;\nисточник для каждого шага', 'Архитектор +\nвладелец процесса'],
      ['G2 · Разрешить сборку — критерии {A, B}', '', '', ''],
      ['03 · Пилот', 'Рабочий сценарий\nв ограниченном контуре', 'Протокол испытаний;\nжурнал исключений', 'Команда пилота +\nэксперт процесса'],
      ['G3 · Решить о расширении — критерии {A, B, C}', '', '', ''],
      ['04 · Передача', 'Регламент работы\nи поддержка', 'Проверка ответственных;\nучебный сценарий', 'Владелец сервиса'],
      ['G4 · Принять в сопровождение — критерии {A, B, C, D}', '', '', ''],
    ];
    const heights = [38, 63, 30, 63, 30, 63, 30, 63, 30];
    const table = slide.tables.add({ rows: values.length, columns: 4,
      left: 72, top: 178, width: 1136, height: heights.reduce((sum, value) => sum + value, 0),
      columnWidths: [211, 309, 359, 257], values });
    table.styleOptions = { headerRow: false, bandedRows: false };
    table.borders.assign({ style: 'solid', fill: C.grid, color: C.grid, width: 0.7 });
    table.cells.block({ row: 0, column: 0, rowCount: 9, columnCount: 4 }).assign({
      margins: { left: 9, right: 9, top: 5, bottom: 4 }, anchor: 'center' });
    let boundary = 178;
    for (let r = 0; r < values.length; r++) {
      table.rows[r].height = heights[r];
      const gate = r > 0 && r % 2 === 0;
      if (gate) table.merge({ startRow: r, endRow: r, startColumn: 0, endColumn: 3 });
      for (let c = 0; c < 4; c++) {
        const cell = table.getCell(r, c);
        cell.fill = r === 0 ? C.navy : gate ? C.white : (r === 3 || r === 7) ? C.paper : C.white;
        cell.text.style = { fontSize: gate ? MIN_BODY : BODY, typeface: FONT,
          color: r === 0 ? C.white : C.navy, bold: r === 0 || gate || c === 0, lineSpacing: 1.0 };
        if (values[r][c]) records.at(-1).visible.push({ name: `evidence-r${r}-c${c}`, text: values[r][c],
          fontSize: gate ? MIN_BODY : BODY, kind: 'body', lines: values[r][c].split('\n').length });
      }
      if (gate) {
        rule(slide, `gate-${r / 2}-boundary`, 72, boundary, 1136, C.orange, 1.2);
        const gateClaim = CLAIMS.find(item => item.id === `G${r / 2}`);
        text(slide, `gate-${r / 2}-decision-role`, `Решение: ${gateClaim.decision_role}`,
          815, boundary + 5, 384, 24, MIN_BODY, C.navy, false, 'right');
        records.at(-1).intentional_overlaps.push(`Gate ${r / 2}: the orange rule is the boundary of the merged decision row.`);
        records.at(-1).intentional_overlaps.push(`Gate ${r / 2}: deciding-role text occupies the right side of its merged row; it differs from the execution role above.`);
      }
      boundary += heights[r];
    }
    text(slide, 'criteria-labels', 'A — периметр · B — роли и данные · C — испытания · D — сопровождение',
      72, 599, 1136, 28, BODY, C.navy, true);
    text(slide, 'criteria-persistence', 'Критерии сохраняются: каждый набор добавляет условие к предыдущему. Непройденное условие возвращает этап на доработку.',
      72, 634, 1136, 48, BODY, C.muted);
    slide.speakerNotes.textFrame.setText('Original fictional demonstration, created from scratch. No real client or company performance facts. The four phases use aligned result, evidence and role columns. Gate decisions are placed on the phase boundaries. A=scope agreed; B=roles and data rules agreed; C=tests accepted; D=support arranged. The sets are cumulative logical criteria; their displayed extent conveys no numerical measurement. All acceptance thresholds remain unspecified.');
  }

  // 2. Executive status: conclusion, current decision, evidence, then a roadmap
  // on one scale. It uses flat typography and rules rather than dashboard cards.
  {
    const slide = base('executive-status', 'Пилот можно начать после проверки источников',
      'Решение сейчас: назначить владельца данных и согласовать проверку неизвестных случаев.');
    text(slide, 'status-as-of', CLAIMS.find(item => item.id === 'Q00').text,
      958, 40, 250, 23, MIN_BODY, C.muted, false, 'right', 'label');
    text(slide, 'status-facts-heading', 'Что известно', 72, 184, 630, 31, 22, C.navy, true);
    text(slide, 'status-facts', 'Периметр согласован: один тип внутренних запросов.\nРабочий сценарий собран; источники проверены частично.',
      72, 225, 650, 67, BODY, C.navy);
    text(slide, 'status-risk-heading', 'Риск и зависимость', 782, 184, 426, 31, 22, C.navy, true);
    text(slide, 'status-risk', 'Риск: нет подтверждённого источника для исключений.\nЗависимость: владелец данных должен разобрать примеры.',
      782, 225, 426, 93, BODY, C.navy);
    rule(slide, 'status-content-divider', 72, 320, 1136);
    text(slide, 'roadmap-heading', 'Проверка смещает прогноз; базовый план виден рядом', 72, 337, 780, 31, 22, C.navy, true);
    rect(slide, 'baseline-key', 888, 342, 24, 7, C.baseline);
    text(slide, 'baseline-legend', 'Базовый', 920, 335, 115, 26, MIN_BODY, C.muted);
    rect(slide, 'forecast-key', 1042, 342, 24, 7, C.orange);
    text(slide, 'forecast-legend', 'Прогноз', 1074, 335, 134, 26, MIN_BODY, C.navy);
    const axis = { left: 332, top: 402, width: 816, count: 6 };
    const tick = index => axis.left + index * axis.width / (axis.count - 1);
    rule(slide, 'roadmap-axis', axis.left, axis.top, axis.width, C.grid, 1);
    for (let index = 0; index < 6; index++) {
      const x = tick(index);
      rect(slide, `roadmap-tick-${index}`, x, axis.top - 4, 1, 146, C.grid);
      text(slide, `roadmap-week-${index}`, `Нед. ${index + 1}`, x - 29, 374, 70, 23, MIN_BODY, C.muted, false, 'center');
    }
    const tasks = [
      { label: 'Периметр', y: 416, baseline: [0, 1], forecast: [0, 1] },
      { label: 'Сборка', y: 461, baseline: [1, 3], forecast: [1, 3] },
      { label: 'Проверка', y: 506, baseline: [3, 4], forecast: [3, 5] },
    ];
    for (const [i, task] of tasks.entries()) {
      text(slide, `roadmap-task-${i}`, task.label, 72, task.y - 1, 226, 30, BODY, C.navy, true);
      for (const [name, interval, color, offset] of [
        ['baseline', task.baseline, C.baseline, 0], ['forecast', task.forecast, C.orange, 14],
      ]) {
        rect(slide, `${name}-bar-${i}`, tick(interval[0]), task.y + offset,
          tick(interval[1]) - tick(interval[0]), 8, color);
      }
    }
    text(slide, 'roadmap-proviso', 'Все недели и статусы вымышлены. Прогноз показывает зависимость и не является обязательством по сроку.',
      72, 554, 1136, 29, MIN_BODY, C.muted);
    rule(slide, 'status-results-divider', 72, 590, 1136);
    text(slide, 'recent-heading', 'Недавно получено', 72, 607, 530, 28, 22, C.navy, true);
    text(slide, 'recent-result', 'Карта запросов и правила передачи эксперту.', 72, 645, 530, 29, BODY, C.navy);
    text(slide, 'next-heading', 'Следующий результат', 668, 607, 540, 28, 22, C.navy, true);
    text(slide, 'next-result', 'Протокол проверки; решение о старте пилота.', 668, 645, 540, 29, BODY, C.navy);
    slide.speakerNotes.textFrame.setText('Original fictional project-status one-pager. Every status and schedule interval is invented for this example. The two bars for each activity share the same six-week axis. Grey is the baseline plan; orange is the current forecast. Scope and build are unchanged; checking extends from week 5 to week 6 because the source owner must resolve unknown cases. This is an explanatory schedule, not a forecast for any actual client. No ROI, savings, acceptance thresholds, budgets or measured effects are claimed.');
  }

  // 3. Paired workflows. Connectors are materialized before visible nodes and
  // then attached to those nodes; the exported connectors remain editable.
  {
    const slide = base('paired-workflow', 'Агент готовит ответ; эксперт разбирает пробелы',
      'Одинаковые шаги показывают изменение ролей. Предлагаемый процесс сохраняет остановку при отсутствии основания.');
    text(slide, 'workflow-current-heading', 'Текущий процесс · демо', 260, 177, 393, 31, 22, C.navy, true);
    text(slide, 'workflow-proposed-heading', 'Предлагаемый процесс · демо', 760, 177, 448, 31, 22, C.orange, true);
    const current = [
      ['Сотрудник', 'Передаёт текст запроса эксперту.'],
      ['Эксперт процесса', 'Ищет источник и проверяет\nего применимость.'],
      ['Эксперт процесса', 'Готовит ответ и вручную\nразбирает пробелы.'],
      ['Сотрудник', 'Получает ответ после\nручной проверки.'],
    ];
    const proposed = [
      ['Сотрудник → агент', 'Уточняет цель\nи обязательные поля.'],
      ['Агент', 'Находит источник\nи проверяет его применимость.'],
      ['Агент', 'Готовит проект ответа\nи прикладывает основание.'],
      ['Сотрудник', 'Получает ответ\nс подтверждённым основанием.'],
    ];
    const steps = ['1. Запрос', '2. Основание', '3. Подготовка', '4. Результат'];
    const plans = [];
    for (const [lane, x, w, copy] of [['current', 260, 393, current], ['proposed', 760, 448, proposed]]) {
      for (let row = 0; row < 4; row++) plans.push({ name: `${lane}-step-${row}`, lane, row, x, y: 215 + row * 97, w, h: 80, copy: copy[row] });
    }
    plans.push({ name: 'evidence-exception', lane: 'exception', row: 0, x: 760, y: 614, w: 448, h: 50,
      copy: ['Эксперт: разобрать неизвестное', 'Ответ остановлен до подтверждения.'] });
    const anchors = new Map(plans.map(plan => [plan.name, rect(slide, `anchor-${plan.name}`, plan.x, plan.y, plan.w, plan.h, 'none')]));
    const edgeSpecs = [];
    for (const lane of ['current', 'proposed']) {
      for (let row = 0; row < 3; row++) edgeSpecs.push({ from: `${lane}-step-${row}`, to: `${lane}-step-${row + 1}`,
        options: { kind: 'straight', fromSide: 'bottom', toSide: 'top', line: { style: 'solid', fill: C.muted, width: 1.4 },
          tail: { type: 'arrow', width: 'sm', length: 'sm' } } });
    }
    edgeSpecs.push({ from: 'proposed-step-1', to: 'evidence-exception',
      options: { kind: 'elbow', fromSide: 'right', toSide: 'right', line: { style: 'dashed', fill: C.orange, width: 1.6 },
        tail: { type: 'arrow', width: 'sm', length: 'sm' } } });
    const edges = edgeSpecs.map(spec => ({ spec, shape: slide.shapes.connect(anchors.get(spec.from), anchors.get(spec.to), spec.options) }));
    const nodes = new Map();
    for (const plan of plans) {
      const exception = plan.lane === 'exception';
      const shape = rect(slide, plan.name, plan.x, plan.y, plan.w, plan.h,
        exception ? C.paleOrange : C.paper, exception ? C.orange : C.grid, 1);
      nodes.set(plan.name, shape);
      text(slide, `${plan.name}-role`, plan.copy[0], plan.x + 13, plan.y + (exception ? 4 : 7), plan.w - 26, 25,
        exception ? (BODY + MIN_BODY) / 2 : BODY, C.navy, true);
      text(slide, `${plan.name}-action`, plan.copy[1], plan.x + 13, plan.y + (exception ? 28 : 33), plan.w - 26,
        exception ? 22 : 46, exception ? MIN_BODY : BODY, C.navy);
      records.at(-1).intentional_overlaps.push(`${plan.name}: role and action text are contained in the workflow node.`);
    }
    for (const { spec, shape } of edges) {
      shape.setConnectorFrom(nodes.get(spec.from), slide.shapes.getConnectionSiteIndex(nodes.get(spec.from), spec.options.fromSide));
      shape.setConnectorTo(nodes.get(spec.to), slide.shapes.getConnectionSiteIndex(nodes.get(spec.to), spec.options.toSide));
      shape.sendToBack();
    }
    for (const anchor of anchors.values()) slide.shapes.deleteById(anchor.id);
    for (let row = 0; row < 4; row++) text(slide, `workflow-step-label-${row}`, steps[row], 72, 215 + row * 97 + 26, 164, 30, BODY, C.muted, true);
    text(slide, 'workflow-exception-label', 'Нет основания →', 986, 584, 222, 27, MIN_BODY, C.accentText, true);
    text(slide, 'workflow-current-note', 'Человек выполняет поиск, проверку\nи обработку исключений.', 260, 615, 393, 49, BODY, C.muted);
    slide.speakerNotes.textFrame.setText('Original fictional current/proposed workflow. Current and proposed paths use the same four aligned steps: request, evidence, preparation, result. The agent finds and checks evidence and prepares an answer. The proposed branch from the evidence step is explicitly dashed and labelled "Нет основания". Missing or inapplicable evidence stops the answer and sends the unknown case to a human expert. The agent is not depicted as inventing evidence. Native PowerPoint connectors remain attached to native nodes. The dashed route means an exception, not a confirmed implementation. The entire workflow is a demonstration, not discovered client architecture.');
  }

  const outputs = [];
  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, '0')}`;
    const preview = path.join(out.preview, `${stem}.png`);
    const layout = path.join(out.layout, `${stem}.layout.json`);
    const png = await presentation.export({ slide, format: 'png', scale: 1.5 });
    await fs.writeFile(preview, new Uint8Array(await png.arrayBuffer()));
    await fs.writeFile(layout, await (await slide.export({ format: 'layout' })).text());
    outputs.push({ slide: index + 1, id: records[index].id, preview, layout });
  }
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(out.pptx);
  const pptxBytes = await fs.readFile(out.pptx);
  const native = inspectPptx(pptxBytes, records);
  await fs.writeFile(out.text, `CLAIM LEDGER (FICTIONAL SOURCE; NOT EXTRACTED SLIDE COPY)\n${CLAIMS.map(item => `[${item.id}] ${item.text}${item.criteria ? ` - criteria {${item.criteria.join(', ')}}` : ''}`).join('\n')}\n\nEXTRACTED PPTX COPY\n${native.map(item => `SLIDE ${item.slide}\n${item.text}`).join('\n\n')}`);
  const files = [out.pptx, out.text, ...outputs.flatMap(item => [item.preview, item.layout])];
  const checksums = {};
  for (const file of files) checksums[path.relative(out.directory, file)] = createHash('sha256').update(await fs.readFile(file)).digest('hex');
  const manifest = {
    version: 1, generated_at: new Date().toISOString(), state: 'draft', purpose: 'original-fictional-gallery',
    source: { kind: 'original-fictional-examples', external_sources: [], client_files_used: false,
      provenance: 'Written from scratch for this gallery. No imported reference slide, image, client fact, financial effect or outcome.' },
    generator: { script: 'scripts/render_gallery.mjs', tokens: 'assets/design-tokens.json', tokens_version: tokens.version },
    claims: CLAIMS,
    style: { canvas: SIZE, font: FONT, body_px: BODY, minimum_body_px: MIN_BODY, palette: C,
      route: 'explicit-custom-formatting', reference_deck_used: false },
    runtime: { package: metadata.name, version: metadata.version },
    output: { pptx: out.pptx, text: out.text, slides: outputs },
    checks: { slide_count: 3, all_previews_rendered: true, visible_copy_verified_from_pptx: true,
      editable_native_objects: true, no_slide_images: true, original_fictional_content: true,
      body_font_minimum_met: true, visual_review: false, visual_review_note: 'Generation does not establish visual approval. Inspect every PNG and record actual QA separately.',
      powerpoint_opened: false, pdf_built: false },
    native_objects: native.map(({ text: _text, ...item }) => item),
    text_layout_checks: records.map(item => ({ id: item.id, visible: item.visible,
      intentional_overlaps: item.intentional_overlaps })),
    sha256: checksums,
    limitations: ['Fictional examples do not establish readiness, acceptance thresholds, schedules or ROI for a real project.',
      'PNG rendering uses artifact-tool; Microsoft PowerPoint application rendering has not been checked.',
      'The status roadmap uses editable native bars and one shared axis rather than a measured data chart.'],
  };
  await fs.writeFile(out.manifest, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(JSON.stringify({ pptx: out.pptx, preview: out.preview, layout: out.layout,
    manifest: out.manifest, text: out.text, slides: 3, native_objects: manifest.native_objects }, null, 2));
}

main().catch(error => { console.error(error.stack ?? error.message); process.exitCode = 1; });
