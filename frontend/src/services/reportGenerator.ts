import { jsPDF } from 'jspdf';
import type {
  DisasterEvent,
  DisasterModule,
  DisasterType,
  NarrationResponse,
  PriorityZone,
} from '../types';
import { getDisasterColor } from '../utils/disasterColors';
import { MODULE_COVERAGE } from '../utils/moduleMeta';

/**
 * OrbitalMind PDF report generator.
 *
 * Design system, translated to print: one margin grid (20mm), the same
 * restrained "color as signal" rule as the app — the disaster accent
 * only ever appears in a header bar, a left-border indicator, or a
 * score-bar fill, never as a background wash — and a repeated
 * header/footer on every page so this reads as a bound report rather
 * than eight disconnected printouts. See design-decision notes in chat
 * for the full rationale.
 */

const PAGE_W = 210;
const PAGE_H = 297;
const MARGIN = 20;
const CONTENT_W = PAGE_W - MARGIN * 2;

const INK_DARK: [number, number, number] = [8, 13, 26]; // #080d1a — cover bg
const GREY_MUTED: [number, number, number] = [139, 149, 168]; // --text-secondary
const GREY_FAINT: [number, number, number] = [84, 94, 112]; // --text-tertiary
const WHITE: [number, number, number] = [232, 236, 244]; // --text-primary
const ROW_ALT: [number, number, number] = [244, 245, 248]; // light alt row on white pages

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace('#', '');
  return [
    parseInt(clean.slice(0, 2), 16),
    parseInt(clean.slice(2, 4), 16),
    parseInt(clean.slice(4, 6), 16),
  ];
}

function formatNumber(n: number): string {
  return n.toLocaleString('en-IN');
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' });
}

export interface GenerateReportInput {
  module: DisasterModule;
  event: DisasterEvent;
  /** Already sorted by priorityRank ascending. */
  zones: PriorityZone[];
  narrations: Record<string, NarrationResponse>;
  totalPopulationAffected: number;
  criticalZoneCount: number;
  /** 0–1 */
  averageConfidence: number;
}

/**
 * Every page after the cover shares the same chrome: a thin top bar in
 * the disaster's accent color, and a footer with page number + a
 * generation timestamp. Repeating this on every page is what makes the
 * document feel bound rather than assembled from loose pages.
 */
function drawChrome(
  doc: jsPDF,
  disasterType: DisasterType,
  pageNum: number,
  totalPages: number,
  generatedAt: string,
) {
  const [r, g, b] = hexToRgb(getDisasterColor(disasterType, 'primary'));
  doc.setFillColor(r, g, b);
  doc.rect(0, 0, PAGE_W, 2.5, 'F');

  doc.setDrawColor(226, 228, 233);
  doc.setLineWidth(0.2);
  doc.line(MARGIN, PAGE_H - 14, PAGE_W - MARGIN, PAGE_H - 14);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  doc.setTextColor(...GREY_FAINT);
  doc.text(`OrbitalMind Platform  |  ${generatedAt}`, MARGIN, PAGE_H - 9);
  doc.text(`${pageNum} / ${totalPages}`, PAGE_W - MARGIN, PAGE_H - 9, { align: 'right' });
}

function drawCoverPage(doc: jsPDF, input: GenerateReportInput) {
  const { module, event } = input;
  const meta = MODULE_COVERAGE[module.type];
  const [ar, ag, ab] = hexToRgb(getDisasterColor(module.type, 'primary'));

  doc.setFillColor(...INK_DARK);
  doc.rect(0, 0, PAGE_W, PAGE_H, 'F');

  // Accent rule near the top — a single deliberate mark of color on an
  // otherwise near-black page, echoing the app's restrained glass-panel
  // border treatment rather than a full-bleed colored banner.
  doc.setFillColor(ar, ag, ab);
  doc.rect(MARGIN, 70, 28, 2, 'F');

  doc.setFontSize(52);
  doc.text(meta.emoji, MARGIN, 108);

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(15);
  doc.setTextColor(ar, ag, ab);
  doc.text(module.displayName.toUpperCase(), MARGIN, 128);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(24);
  doc.setTextColor(...WHITE);
  const nameLines = doc.splitTextToSize(event.name, CONTENT_W);
  doc.text(nameLines, MARGIN, 142);

  doc.setFontSize(13);
  doc.setTextColor(...GREY_MUTED);
  doc.text(`${module.regionLabel}  \u00b7  ${formatDate(event.date)}`, MARGIN, 142 + nameLines.length * 10);

  // Footer: thin accent rule separating it from the content above, then
  // the product mark small and quiet — a signature, not a logo lockup.
  doc.setDrawColor(ar, ag, ab);
  doc.setLineWidth(0.4);
  doc.line(MARGIN, PAGE_H - 24, PAGE_W - MARGIN, PAGE_H - 24);
  doc.setFontSize(9);
  doc.setTextColor(...GREY_FAINT);
  doc.text('Powered by OrbitalMind', MARGIN, PAGE_H - 16);
  doc.text(module.status === 'live' ? 'LIVE ANALYSIS' : 'DEMO SCENARIO', PAGE_W - MARGIN, PAGE_H - 16, {
    align: 'right',
  });
}

function drawPlatformScopePage(
  doc: jsPDF,
  input: GenerateReportInput,
  pageNum: number,
  totalPages: number,
  generatedAt: string,
) {
  doc.addPage();
  drawChrome(doc, input.module.type, pageNum, totalPages, generatedAt);

  let y = 30;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  doc.setTextColor(20, 24, 32);
  doc.text('Platform Coverage', MARGIN, y);
  y += 12;

  const modules: DisasterType[] = ['flood', 'wildfire', 'landslide', 'cyclone', 'earthquake'];
  const displayNames: Record<DisasterType, string> = {
    flood: 'Flood',
    wildfire: 'Wildfire',
    landslide: 'Landslide',
    cyclone: 'Cyclone',
    earthquake: 'Earthquake',
  };
  const rowH = 12;
  const col1 = MARGIN + 6;
  const col2 = MARGIN + 55;
  const col3 = MARGIN + 125;

  doc.setFontSize(8.5);
  doc.setTextColor(...GREY_FAINT);
  doc.setFont('helvetica', 'bold');
  doc.text('MODULE', col1, y);
  doc.text('SATELLITE SOURCE', col2, y);
  doc.text('STATUS', col3, y);
  y += 5;

  modules.forEach((type, i) => {
    const isActive = type === input.module.type;
    const rowTop = y + i * rowH;

    if (i % 2 === 0) {
      doc.setFillColor(...ROW_ALT);
      doc.rect(MARGIN, rowTop - 8, CONTENT_W, rowH, 'F');
    }
    if (isActive) {
      const [r, g, b] = hexToRgb(getDisasterColor(type, 'primary'));
      doc.setFillColor(r, g, b);
      doc.rect(MARGIN, rowTop - 8, 1.4, rowH, 'F');
    }

    doc.setFont('helvetica', isActive ? 'bold' : 'normal');
    doc.setFontSize(10.5);
    doc.setTextColor(20, 24, 32);
    doc.text(displayNames[type], col1, rowTop);

    doc.setFont('helvetica', 'normal');
    doc.setTextColor(90, 96, 110);
    doc.text(MODULE_COVERAGE[type].satelliteSource, col2, rowTop);

    const isLive = type === 'flood';
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...(isLive ? ([34, 150, 90] as [number, number, number]) : ([180, 130, 20] as [number, number, number])));
    doc.setFontSize(8.5);
    doc.text(isLive ? 'LIVE' : 'DEMO', col3, rowTop);
  });

  y += modules.length * rowH + 8;
  doc.setDrawColor(226, 228, 233);
  doc.setLineWidth(0.2);
  doc.line(MARGIN, y, PAGE_W - MARGIN, y);
  y += 8;

  const others = modules.filter((t) => t !== input.module.type).map((t) => displayNames[t]);
  doc.setFont('helvetica', 'italic');
  doc.setFontSize(9);
  doc.setTextColor(...GREY_MUTED);
  const note = doc.splitTextToSize(
    `This report covers the ${displayNames[input.module.type]} module. Additional modules: ${others.join(' | ')}`,
    CONTENT_W,
  );
  doc.text(note, MARGIN, y);
}

function drawExecutiveSummaryPage(
  doc: jsPDF,
  input: GenerateReportInput,
  pageNum: number,
  totalPages: number,
  generatedAt: string,
) {
  doc.addPage();
  drawChrome(doc, input.module.type, pageNum, totalPages, generatedAt);

  let y = 30;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  doc.setTextColor(20, 24, 32);
  doc.text('Executive Summary', MARGIN, y);
  y += 14;

  const stats: { value: string; label: string }[] = [
    { value: String(input.zones.length), label: 'Priority zones scored' },
    { value: formatNumber(input.totalPopulationAffected), label: 'Population affected' },
    { value: String(input.criticalZoneCount), label: 'Critical-priority zones' },
    { value: `${Math.round(input.averageConfidence * 100)}%`, label: 'Average model confidence' },
  ];

  const blockW = (CONTENT_W - 8) / 2;
  const blockH = 30;
  const gap = 8;
  const [ar, ag, ab] = hexToRgb(getDisasterColor(input.module.type, 'primary'));

  stats.forEach((s, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = MARGIN + col * (blockW + gap);
    const by = y + row * (blockH + gap);

    doc.setFillColor(...ROW_ALT);
    doc.rect(x, by, blockW, blockH, 'F');
    doc.setFillColor(ar, ag, ab);
    doc.rect(x, by, 1.4, blockH, 'F');

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(20);
    doc.setTextColor(20, 24, 32);
    doc.text(s.value, x + 8, by + 15);

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(...GREY_MUTED);
    doc.text(s.label, x + 8, by + 23);
  });

  y += 2 * blockH + gap + 12;
  doc.setDrawColor(226, 228, 233);
  doc.line(MARGIN, y, PAGE_W - MARGIN, y);
  y += 8;

  doc.setFont('helvetica', 'italic');
  doc.setFontSize(9);
  doc.setTextColor(...GREY_MUTED);
  const confNote = doc.splitTextToSize(
    `Confidence reflects the model's certainty in zone-level priority scoring for this event, based on ${
      input.module.status === 'live' ? 'live satellite-derived analysis' : 'a scripted demo scenario'
    }. Scores below 75% should be corroborated with ground reports before dispatching resources.`,
    CONTENT_W,
  );
  doc.text(confNote, MARGIN, y);
}

function drawZonePage(
  doc: jsPDF,
  input: GenerateReportInput,
  zone: PriorityZone,
  pageNum: number,
  totalPages: number,
  generatedAt: string,
) {
  doc.addPage();
  drawChrome(doc, input.module.type, pageNum, totalPages, generatedAt);
  const [ar, ag, ab] = hexToRgb(getDisasterColor(input.module.type, 'primary'));
  const [fr, fg, fb] = hexToRgb(getDisasterColor(input.module.type, 'fill'));

  let y = 32;
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(11);
  doc.setTextColor(ar, ag, ab);
  doc.text(`RANK #${zone.priorityRank}`, MARGIN, y);
  y += 11;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(26);
  doc.setTextColor(20, 24, 32);
  doc.text(zone.zoneName, MARGIN, y);
  y += 12;

  // Priority score bar — the fill portion is the only saturated color
  // on the page, so the eye lands on it first.
  const barW = CONTENT_W;
  const barH = 6;
  doc.setFillColor(...ROW_ALT);
  doc.rect(MARGIN, y, barW, barH, 'F');
  doc.setFillColor(fr, fg, fb);
  doc.rect(MARGIN, y, barW * zone.priorityScore, barH, 'F');
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(20, 24, 32);
  doc.text(`${Math.round(zone.priorityScore * 100)}%`, MARGIN + barW, y + barH + 6, { align: 'right' });
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  doc.setTextColor(...GREY_FAINT);
  doc.text('PRIORITY SCORE', MARGIN, y + barH + 6);
  y += barH + 16;

  const statCols: { label: string; value: string }[] = [
    { label: 'Population affected', value: formatNumber(zone.populationAffected) },
    { label: 'Hospitals affected', value: String(zone.hospitalsAffected) },
    { label: 'Schools affected', value: String(zone.schoolsAffected) },
    { label: 'Bridges at risk', value: String(zone.bridgesAtRisk) },
    { label: 'Roads intact', value: `${zone.roadsIntactPct}%` },
  ];
  const colW = CONTENT_W / statCols.length;
  statCols.forEach((s, i) => {
    const x = MARGIN + i * colW;
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(13);
    doc.setTextColor(20, 24, 32);
    doc.text(s.value, x, y);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    doc.setTextColor(...GREY_FAINT);
    const labelLines = doc.splitTextToSize(s.label, colW - 4);
    doc.text(labelLines, x, y + 6);
  });
  y += 20;

  doc.setDrawColor(226, 228, 233);
  doc.line(MARGIN, y, PAGE_W - MARGIN, y);
  y += 10;

  const narration = input.narrations[zone.zoneId]?.narration;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(...GREY_FAINT);
  doc.text('AI SITUATION NARRATION', MARGIN, y);
  y += 8;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10.5);
  doc.setTextColor(50, 56, 68);
  const bodyText = narration ?? 'Narration not yet generated for this zone.';
  const wrapped = doc.splitTextToSize(bodyText, CONTENT_W);
  doc.text(wrapped, MARGIN, y, { lineHeightFactor: 1.5 });

  doc.setFont('helvetica', 'italic');
  doc.setFontSize(8.5);
  doc.setTextColor(...GREY_FAINT);
  doc.text(
    `Confidence: ${Math.round(zone.confidence * 100)}%  |  Source: ${MODULE_COVERAGE[input.module.type].satelliteSource}`,
    MARGIN,
    PAGE_H - 22,
  );
}

/**
 * Builds and downloads the full situation report:
 * Page 1 cover, Page 2 platform scope, Page 3 executive summary,
 * Pages 4–8 one page per top-5 priority zone.
 */
export function generateReport(input: GenerateReportInput) {
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const generatedAt = new Date().toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  const topZones = input.zones.slice(0, 5);
  const totalPages = 3 + topZones.length;
  let pageNum = 1;

  drawCoverPage(doc, input);
  pageNum += 1;
  drawPlatformScopePage(doc, input, pageNum, totalPages, generatedAt);
  pageNum += 1;
  drawExecutiveSummaryPage(doc, input, pageNum, totalPages, generatedAt);

  topZones.forEach((zone) => {
    pageNum += 1;
    drawZonePage(doc, input, zone, pageNum, totalPages, generatedAt);
  });

  const region = input.module.regionLabel.split('\u00b7')[0].trim().replace(/\s+/g, '');
  const dateStr = new Date().toISOString().slice(0, 10);
  const disasterLabel = input.module.displayName.replace(/\s+/g, '');
  doc.save(`OrbitalMind_${disasterLabel}_${region}_${dateStr}.pdf`);
}
