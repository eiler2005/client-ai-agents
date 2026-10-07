#!/usr/bin/env node
/**
 * Original, fictional consulting compositions with interchangeable style overlays.
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
  const options = { style: 'neutral' };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') options.help = true;
    else if (['--out', '--style', '--format-profile'].includes(arg)) {
      if (!argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`${arg} requires a value`);
      options[{ '--out': 'out', '--style': 'style', '--format-profile': 'formatProfile' }[arg]] = argv[++i];
    } else throw new Error(`Unknown argument: ${arg}`);
  }
  return options;
}

async function exists(candidate) {
  return fs.access(candidate).then(() => true, () => false);
}

async function loadArtifactTool() {
  const override = process.env.CONSULTING_ARTIFACT_TOOL ?? process.env.CINIMEX_ARTIFACT_TOOL;
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
    const { Canvas, FontLibrary } = require('skia-canvas');
    let metadata = { name: '@oai/artifact-tool', version: 'unknown' };
    for (const directory of [candidate, path.dirname(path.dirname(entry)), path.dirname(path.dirname(path.dirname(entry)))]) {
      try {
        const possible = JSON.parse(await fs.readFile(path.join(directory, 'package.json'), 'utf8'));
        if (possible.name === '@oai/artifact-tool') { metadata = possible; break; }
      } catch { /* Metadata is optional; the API export check above is required. */ }
    }
    return { ...artifact, Canvas, FontLibrary, metadata };
  }
  throw new Error('Cannot resolve @oai/artifact-tool. Install it or set CONSULTING_ARTIFACT_TOOL to its package directory or ES-module entry.');
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
    console.log('Usage: node render_gallery.mjs [--out DIRECTORY|FILE.pptx] [--style neutral|cinimex|PATH] [--format-profile PATH]\nDefault style: neutral. Creates 3 original fictional editable slides, PNG previews, layout JSON, extracted text and a manifest.\nDependency: @oai/artifact-tool; optional CONSULTING_ARTIFACT_TOOL package directory or module entry.');
    return;
  }
  const stylePath = ['neutral', 'cinimex'].includes(options.style)
    ? path.resolve(sourceDirectory, '../assets/styles', `${options.style}.json`)
    : path.resolve(options.style);
  const formatPath = options.formatProfile
    ? path.resolve(options.formatProfile) : path.resolve(sourceDirectory, '../assets/format-profiles.json');
  const [style, formats] = await Promise.all([stylePath, formatPath].map(async file => JSON.parse(await fs.readFile(file, 'utf8'))));
  const G = formats.slides, T = style.typography?.slides;
  if (G?.unit !== 'px' || !T?.font || !style.brand?.slideFooter) throw new Error('Invalid slide format or style profile');
  const colorRoles = ['ink', 'accent', 'accentText', 'muted', 'surface', 'border', 'background', 'accentSurface', 'baseline'];
  if (colorRoles.some(role => !/^#[0-9a-f]{6}$/i.test(style.colors?.[role] ?? ''))) throw new Error('Style profile requires semantic hexadecimal color roles');
  if (![T.body, T.minBody, T.title, T.heading, T.kicker, T.source, T.exceptionRole].every(value => Number.isFinite(value) && value > 0) || T.body < T.minBody) throw new Error('Invalid slide typography');
  const C = Object.freeze(style.colors), SIZE = { width: G.width, height: G.height };
  const BODY = T.body, MIN_BODY = T.minBody, TITLE = T.title, SOURCE = T.source, HEADING = T.heading;
  const { Presentation, PresentationFile, Canvas, FontLibrary, metadata } = await loadArtifactTool();
  const FONT = [T.font, 'Arial', 'Calibri', 'DejaVu Sans', 'Liberation Sans', 'Noto Sans'].find(font => FontLibrary.has(font));
  if (!FONT) throw new Error('No supported slide font is available; install a Cyrillic-capable sans-serif font');
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

  function rect(slide, name, x, y, w, h, fill = C.background, stroke = 'none', weight = 0) {
    return slide.shapes.add({ geometry: 'rect', name,
      position: { left: x, top: y, width: w, height: h }, fill,
      line: { style: 'solid', fill: stroke, width: weight } });
  }

  function rule(slide, name, x, y, w, color = C.border, weight = 1) {
    return slide.shapes.add({ geometry: 'line', name,
      position: { left: x, top: y, width: w, height: 0 }, fill: 'none',
      line: { style: 'solid', fill: color, width: weight } });
  }

  function text(slide, name, value, x, y, w, h, size = BODY, color = C.ink, bold = false, alignment = 'left', kind = 'body') {
    const lines = wrap(value, w, size, bold);
    const estimatedHeight = lines.length * size * T.heightEstimate;
    if (estimatedHeight > h + 2) throw new Error(`${name}: ${lines.length} lines do not fit ${h}px`);
    if (kind === 'body' && size < MIN_BODY) throw new Error(`${name}: body type is below the token minimum`);
    if (x < 0 || y < 0 || x + w > SIZE.width || y + h > SIZE.height) throw new Error(`${name}: object outside canvas`);
    const shape = slide.shapes.add({ geometry: 'textbox', name,
      position: { left: x, top: y, width: w, height: h }, fill: 'none',
      line: { style: 'solid', fill: 'none', width: 0 } });
    shape.text = lines.join('\n');
    shape.text.style = { fontSize: size, typeface: FONT, color, bold, alignment,
      verticalAlignment: 'top', wrap: 'none', autoFit: 'none', lineSpacing: T.lineSpacing,
      insets: { left: 0, right: 0, top: 0, bottom: 0 } };
    records.at(-1).visible.push({ name, text: value, fontSize: size, kind, bounds: [x, y, w, h], lines: lines.length });
    return shape;
  }

  function base(id, title, subtitle) {
    const slide = presentation.slides.add();
    records.push({ id, title, visible: [], intentional_overlaps: [] });
    slide.background.fill = C.background;
    rect(slide, `${id}-top-rule`, ...G.chrome.topRule, C.ink);
    rect(slide, `${id}-accent-rule`, ...G.chrome.accentRule, C.accent);
    text(slide, `${id}-fiction`, FICTION, ...G.chrome.fiction, T.kicker, C.muted, true, 'left', 'label');
    text(slide, `${id}-title`, title, ...G.chrome.title, TITLE, C.ink, true, 'left', 'title');
    text(slide, `${id}-subtitle`, subtitle, ...G.chrome.subtitle, BODY, C.muted);
    text(slide, `${id}-footer`, style.brand.slideFooter,
      ...G.chrome.footer, SOURCE, C.muted, false, 'left', 'source');
    text(slide, `${id}-page`, String(records.length).padStart(2, '0'), ...G.chrome.page, MIN_BODY, C.ink, true, 'right', 'label');
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
    const geo = G.stageGates;
    const heights = geo.rowHeights;
    const table = slide.tables.add({ rows: values.length, columns: 4,
      left: geo.table[0], top: geo.table[1], width: geo.table[2], height: heights.reduce((sum, value) => sum + value, 0),
      columnWidths: geo.columnWidths, values });
    table.styleOptions = { headerRow: false, bandedRows: false };
    table.borders.assign({ style: 'solid', fill: C.border, color: C.border, width: geo.borderWidth });
    table.cells.block({ row: 0, column: 0, rowCount: 9, columnCount: 4 }).assign({
      margins: geo.cellMargins, anchor: 'center' });
    let boundary = geo.table[1];
    for (let r = 0; r < values.length; r++) {
      table.rows[r].height = heights[r];
      const gate = r > 0 && r % 2 === 0;
      if (gate) table.merge({ startRow: r, endRow: r, startColumn: 0, endColumn: 3 });
      for (let c = 0; c < 4; c++) {
        const cell = table.getCell(r, c);
        cell.fill = r === 0 ? C.ink : gate ? C.background : (r === 3 || r === 7) ? C.surface : C.background;
        cell.text.style = { fontSize: gate ? MIN_BODY : BODY, typeface: FONT,
          color: r === 0 ? C.background : C.ink, bold: r === 0 || gate || c === 0, lineSpacing: T.lineSpacing };
        if (values[r][c]) records.at(-1).visible.push({ name: `evidence-r${r}-c${c}`, text: values[r][c],
          fontSize: gate ? MIN_BODY : BODY, kind: 'body', lines: values[r][c].split('\n').length });
      }
      if (gate) {
        rule(slide, `gate-${r / 2}-boundary`, geo.table[0], boundary, geo.table[2], C.accent, geo.gateRuleWidth);
        const gateClaim = CLAIMS.find(item => item.id === `G${r / 2}`);
        text(slide, `gate-${r / 2}-decision-role`, `Решение: ${gateClaim.decision_role}`,
          geo.decisionRole.left, boundary + geo.decisionRole.topOffset, geo.decisionRole.width, geo.decisionRole.height, MIN_BODY, C.ink, false, 'right');
        records.at(-1).intentional_overlaps.push(`Gate ${r / 2}: the accent rule is the boundary of the merged decision row.`);
        records.at(-1).intentional_overlaps.push(`Gate ${r / 2}: deciding-role text occupies the right side of its merged row; it differs from the execution role above.`);
      }
      boundary += heights[r];
    }
    text(slide, 'criteria-labels', 'A — периметр · B — роли и данные · C — испытания · D — сопровождение',
      ...geo.criteria, BODY, C.ink, true);
    text(slide, 'criteria-persistence', 'Критерии сохраняются: каждый набор добавляет условие к предыдущему. Непройденное условие возвращает этап на доработку.',
      ...geo.persistence, BODY, C.muted);
    slide.speakerNotes.textFrame.setText('Original fictional demonstration, created from scratch. No real client or company performance facts. The four phases use aligned result, evidence and role columns. Gate decisions are placed on the phase boundaries. A=scope agreed; B=roles and data rules agreed; C=tests accepted; D=support arranged. The sets are cumulative logical criteria; their displayed extent conveys no numerical measurement. All acceptance thresholds remain unspecified.');
  }

  // 2. Executive status: conclusion, current decision, evidence, then a roadmap
  // on one scale. It uses flat typography and rules rather than dashboard cards.
  {
    const slide = base('executive-status', 'Пилот можно начать после проверки источников',
      'Решение сейчас: назначить владельца данных и согласовать проверку неизвестных случаев.');
    const geo = G.status;
    text(slide, 'status-as-of', CLAIMS.find(item => item.id === 'Q00').text,
      ...geo.asOf, MIN_BODY, C.muted, false, 'right', 'label');
    text(slide, 'status-facts-heading', 'Что известно', ...geo.factsHeading, HEADING, C.ink, true);
    text(slide, 'status-facts', 'Периметр согласован: один тип внутренних запросов.\nРабочий сценарий собран; источники проверены частично.',
      ...geo.facts, BODY, C.ink);
    text(slide, 'status-risk-heading', 'Риск и зависимость', ...geo.riskHeading, HEADING, C.ink, true);
    text(slide, 'status-risk', 'Риск: нет подтверждённого источника для исключений.\nЗависимость: владелец данных должен разобрать примеры.',
      ...geo.risk, BODY, C.ink);
    rule(slide, 'status-content-divider', ...geo.contentDivider);
    text(slide, 'roadmap-heading', 'Проверка смещает прогноз; базовый план виден рядом', ...geo.roadmapHeading, HEADING, C.ink, true);
    rect(slide, 'baseline-key', ...geo.baselineKey, C.baseline);
    text(slide, 'baseline-legend', 'Базовый', ...geo.baselineLegend, MIN_BODY, C.muted);
    rect(slide, 'forecast-key', ...geo.forecastKey, C.accent);
    text(slide, 'forecast-legend', 'Прогноз', ...geo.forecastLegend, MIN_BODY, C.ink);
    const axis = { ...geo.axis, count: Math.max(...CLAIMS.filter(item => ['Q01', 'Q02'].includes(item.id)).map(item => item.value)) };
    const tick = index => axis.left + index * axis.width / (axis.count - 1);
    rule(slide, 'roadmap-axis', axis.left, axis.top, axis.width, C.border, 1);
    for (let index = 0; index < axis.count; index++) {
      const x = tick(index);
      rect(slide, `roadmap-tick-${index}`, x, axis.top + geo.tick.topOffset, geo.tick.width, geo.tick.height, C.border);
      text(slide, `roadmap-week-${index}`, `Нед. ${index + 1}`, x + geo.weekLabel.leftOffset, geo.weekLabel.top, geo.weekLabel.width, geo.weekLabel.height, MIN_BODY, C.muted, false, 'center');
    }
    const tasks = [
      { label: 'Периметр', y: geo.taskY[0], baseline: [0, 1], forecast: [0, 1] },
      { label: 'Сборка', y: geo.taskY[1], baseline: [1, 3], forecast: [1, 3] },
      { label: 'Проверка', y: geo.taskY[2], baseline: [3, CLAIMS.find(item => item.id === 'Q01').value - 1], forecast: [3, CLAIMS.find(item => item.id === 'Q02').value - 1] },
    ];
    for (const [i, task] of tasks.entries()) {
      text(slide, `roadmap-task-${i}`, task.label, geo.taskLabel.left, task.y + geo.taskLabel.topOffset, geo.taskLabel.width, geo.taskLabel.height, BODY, C.ink, true);
      for (const [name, interval, color, offset] of [
        ['baseline', task.baseline, C.baseline, geo.bar.baselineOffset], ['forecast', task.forecast, C.accent, geo.bar.forecastOffset],
      ]) {
        rect(slide, `${name}-bar-${i}`, tick(interval[0]), task.y + offset,
          tick(interval[1]) - tick(interval[0]), geo.bar.height, color);
      }
    }
    text(slide, 'roadmap-proviso', 'Все недели и статусы вымышлены. Прогноз показывает зависимость и не является обязательством по сроку.',
      ...geo.caveat, MIN_BODY, C.muted);
    rule(slide, 'status-results-divider', ...geo.resultsDivider);
    text(slide, 'recent-heading', 'Недавно получено', ...geo.recentHeading, HEADING, C.ink, true);
    text(slide, 'recent-result', 'Карта запросов и правила передачи эксперту.', ...geo.recent, BODY, C.ink);
    text(slide, 'next-heading', 'Следующий результат', ...geo.nextHeading, HEADING, C.ink, true);
    text(slide, 'next-result', 'Протокол проверки; решение о старте пилота.', ...geo.next, BODY, C.ink);
    slide.speakerNotes.textFrame.setText('Original fictional project-status one-pager. Every status and schedule interval is invented for this example. The two bars for each activity share the same six-week axis. Muted bars are the baseline plan; accent bars are the current forecast. Scope and build are unchanged; checking extends from week 5 to week 6 because the source owner must resolve unknown cases. This is an explanatory schedule, not a forecast for any actual client. No ROI, savings, acceptance thresholds, budgets or measured effects are claimed.');
  }

  // 3. Paired workflows. Connectors are materialized before visible nodes and
  // then attached to those nodes; the exported connectors remain editable.
  {
    const slide = base('paired-workflow', 'Агент готовит ответ; эксперт разбирает пробелы',
      'Одинаковые шаги показывают изменение ролей. Предлагаемый процесс сохраняет остановку при отсутствии основания.');
    const geo = G.workflow;
    text(slide, 'workflow-current-heading', 'Текущий процесс · демо', ...geo.currentHeading, HEADING, C.ink, true);
    text(slide, 'workflow-proposed-heading', 'Предлагаемый процесс · демо', ...geo.proposedHeading, HEADING, C.accentText, true);
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
    for (const [lane, x, w, copy] of [['current', geo.lanes.current.left, geo.lanes.current.width, current], ['proposed', geo.lanes.proposed.left, geo.lanes.proposed.width, proposed]]) {
      for (let row = 0; row < 4; row++) plans.push({ name: `${lane}-step-${row}`, lane, row, x, y: geo.rowTop + row * geo.rowPitch, w, h: geo.nodeHeight, copy: copy[row] });
    }
    plans.push({ name: 'evidence-exception', lane: 'exception', row: 0, x: geo.exception[0], y: geo.exception[1], w: geo.exception[2], h: geo.exception[3],
      copy: ['Эксперт: разобрать неизвестное', 'Ответ остановлен до подтверждения.'] });
    const anchors = new Map(plans.map(plan => [plan.name, rect(slide, `anchor-${plan.name}`, plan.x, plan.y, plan.w, plan.h, 'none')]));
    const edgeSpecs = [];
    for (const lane of ['current', 'proposed']) {
      for (let row = 0; row < 3; row++) edgeSpecs.push({ from: `${lane}-step-${row}`, to: `${lane}-step-${row + 1}`,
        options: { kind: 'straight', fromSide: 'bottom', toSide: 'top', line: { style: 'solid', fill: C.muted, width: geo.connectorWidth },
          tail: { type: 'arrow', width: 'sm', length: 'sm' } } });
    }
    edgeSpecs.push({ from: 'proposed-step-1', to: 'evidence-exception',
      options: { kind: 'elbow', fromSide: 'right', toSide: 'right', line: { style: 'dashed', fill: C.accent, width: geo.exceptionConnectorWidth },
        tail: { type: 'arrow', width: 'sm', length: 'sm' } } });
    const edges = edgeSpecs.map(spec => ({ spec, shape: slide.shapes.connect(anchors.get(spec.from), anchors.get(spec.to), spec.options) }));
    const nodes = new Map();
    for (const plan of plans) {
      const exception = plan.lane === 'exception';
      const shape = rect(slide, plan.name, plan.x, plan.y, plan.w, plan.h,
        exception ? C.accentSurface : C.surface, exception ? C.accent : C.border, geo.nodeBorderWidth);
      nodes.set(plan.name, shape);
      text(slide, `${plan.name}-role`, plan.copy[0], plan.x + geo.role.leftInset, plan.y + (exception ? geo.role.exceptionTopInset : geo.role.topInset), plan.w - 2 * geo.role.leftInset, geo.role.height,
        exception ? T.exceptionRole : BODY, C.ink, true);
      text(slide, `${plan.name}-action`, plan.copy[1], plan.x + geo.action.leftInset, plan.y + (exception ? geo.action.exceptionTopInset : geo.action.topInset), plan.w - 2 * geo.action.leftInset,
        exception ? geo.action.exceptionHeight : geo.action.height, exception ? MIN_BODY : BODY, C.ink);
      records.at(-1).intentional_overlaps.push(`${plan.name}: role and action text are contained in the workflow node.`);
    }
    for (const { spec, shape } of edges) {
      shape.setConnectorFrom(nodes.get(spec.from), slide.shapes.getConnectionSiteIndex(nodes.get(spec.from), spec.options.fromSide));
      shape.setConnectorTo(nodes.get(spec.to), slide.shapes.getConnectionSiteIndex(nodes.get(spec.to), spec.options.toSide));
      shape.sendToBack();
    }
    for (const anchor of anchors.values()) slide.shapes.deleteById(anchor.id);
    for (let row = 0; row < 4; row++) text(slide, `workflow-step-label-${row}`, steps[row], geo.stepLabel.left, geo.rowTop + row * geo.rowPitch + geo.stepLabel.topOffset, geo.stepLabel.width, geo.stepLabel.height, BODY, C.muted, true);
    text(slide, 'workflow-exception-label', 'Нет основания →', ...geo.exceptionLabel, MIN_BODY, C.accentText, true);
    text(slide, 'workflow-current-note', 'Человек выполняет поиск, проверку\nи обработку исключений.', ...geo.currentNote, BODY, C.muted);
    slide.speakerNotes.textFrame.setText('Original fictional current/proposed workflow. Current and proposed paths use the same four aligned steps: request, evidence, preparation, result. The agent finds and checks evidence and prepares an answer. The proposed branch from the evidence step is explicitly dashed and labelled "Нет основания". Missing or inapplicable evidence stops the answer and sends the unknown case to a human expert. The agent is not depicted as inventing evidence. Native PowerPoint connectors remain attached to native nodes. The dashed route means an exception, not a confirmed implementation. The entire workflow is a demonstration, not discovered client architecture.');
  }

  const outputs = [];
  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, '0')}`;
    const preview = path.join(out.preview, `${stem}.png`);
    const layout = path.join(out.layout, `${stem}.layout.json`);
    const png = await presentation.export({ slide, format: 'png', scale: G.previewScale });
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
    generator: { script: 'scripts/render_gallery.mjs',
      style_profile: { path: stylePath, id: style.id, version: style.version, sha256: createHash('sha256').update(await fs.readFile(stylePath)).digest('hex') },
      format_profile: { path: formatPath, id: formats.id, version: formats.version, sha256: createHash('sha256').update(await fs.readFile(formatPath)).digest('hex') } },
    claims: CLAIMS,
    style: { id: style.id, canvas: SIZE, typography: T, font_requested: T.font, font: FONT, font_fallback: FONT !== T.font, body_px: BODY, minimum_body_px: MIN_BODY, palette: C,
      route: 'explicit-custom-formatting', reference_deck_used: false },
    runtime: { package: metadata.name, version: metadata.version },
    output: { pptx: out.pptx, text: out.text, slides: outputs },
    checks: { slide_count: 3, all_previews_rendered: true, visible_copy_verified_from_pptx: true,
      editable_native_objects: true, no_slide_images: true, original_fictional_content: true,
      body_font_minimum_met: true, font_available_checked: true, visual_review: false, visual_review_note: 'Generation does not establish visual approval. Inspect every PNG and record actual QA separately.',
      powerpoint_opened: false, pdf_built: false },
    native_objects: native.map(({ text: _text, ...item }) => item),
    text_layout_checks: records.map(item => ({ id: item.id, visible: item.visible,
      intentional_overlaps: item.intentional_overlaps })),
    sha256: checksums,
    limitations: ['Fictional examples do not establish readiness, acceptance thresholds, schedules or ROI for a real project.',
      'PNG rendering uses artifact-tool; Microsoft PowerPoint application rendering has not been checked.',
      'PPTX fonts are referenced, not embedded; the manifest records any rendering-font fallback.',
      'The status roadmap uses editable native bars and one shared axis rather than a measured data chart.'],
  };
  await fs.writeFile(out.manifest, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(JSON.stringify({ pptx: out.pptx, preview: out.preview, layout: out.layout,
    manifest: out.manifest, text: out.text, slides: 3, native_objects: manifest.native_objects }, null, 2));
}

main().catch(error => { console.error(error.stack ?? error.message); process.exitCode = 1; });
