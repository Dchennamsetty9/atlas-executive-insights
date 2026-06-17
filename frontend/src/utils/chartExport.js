/**
 * chartExport.js — PNG + CSV export utilities for Recharts charts.
 *
 * Usage:
 *   import { exportChartPng, exportChartCsv } from '../../utils/chartExport';
 *
 *   // PNG: pass the container ref wrapping <ResponsiveContainer>
 *   exportChartPng(containerRef, 'arr-trend');
 *
 *   // CSV: pass the data array and column keys
 *   exportChartCsv(data, ['month', 'arr', 'target'], 'arr-trend');
 */

/**
 * Export a chart container's SVG as a PNG download.
 * @param {React.RefObject} containerRef - ref attached to the chart wrapper div
 * @param {string} filename - output file name (without extension)
 */
export function exportChartPng(containerRef, filename = 'chart') {
  const svg = containerRef?.current?.querySelector('svg');
  if (!svg) {
    console.warn('[exportChartPng] No SVG found in container');
    return;
  }

  const svgData = new XMLSerializer().serializeToString(svg);
  const canvas = document.createElement('canvas');
  const { width, height } = svg.getBoundingClientRect();
  canvas.width = width * 2;   // 2x for retina
  canvas.height = height * 2;

  const ctx = canvas.getContext('2d');
  ctx.scale(2, 2);

  // White or transparent background
  ctx.fillStyle = '#0a0f1e'; // match app dark bg
  ctx.fillRect(0, 0, width, height);

  const img = new Image();
  const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  img.onload = () => {
    ctx.drawImage(img, 0, 0, width, height);
    URL.revokeObjectURL(url);

    const link = document.createElement('a');
    link.download = `${filename}-${new Date().toISOString().slice(0, 10)}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  };
  img.onerror = () => URL.revokeObjectURL(url);
  img.src = url;
}

/**
 * Export data array as a CSV download.
 * @param {Array<Object>} data - array of row objects
 * @param {string[]} columns - keys to include (in order)
 * @param {string} filename - output file name (without extension)
 */
export function exportChartCsv(data, columns, filename = 'chart-data') {
  if (!data?.length) return;

  const cols = columns || Object.keys(data[0]);
  const header = cols.join(',');
  const rows = data.map(row =>
    cols.map(col => {
      const val = row[col] ?? '';
      // Quote values containing commas or quotes
      return typeof val === 'string' && (val.includes(',') || val.includes('"'))
        ? `"${val.replace(/"/g, '""')}"`
        : val;
    }).join(',')
  );

  const csv = [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.download = `${filename}-${new Date().toISOString().slice(0, 10)}.csv`;
  link.href = URL.createObjectURL(blob);
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

/**
 * ChartExportBar — reusable export button row for charts.
 * A simple React functional component you can drop above/below any chart.
 *
 * Props:
 *   containerRef — the chart wrapper ref
 *   data         — array of row objects for CSV
 *   columns      — CSV column keys
 *   filename     — base filename (no extension)
 *   style        — optional style overrides
 */
export function ChartExportBar({ containerRef, data, columns, filename, style }) {
  return (
    <div style={{
      display: 'flex', gap: 6, justifyContent: 'flex-end',
      marginBottom: 6, ...style,
    }}>
      <button
        onClick={() => exportChartPng(containerRef, filename)}
        title="Download chart as PNG"
        style={exportBtnStyle}
      >
        ⬇ PNG
      </button>
      {data && (
        <button
          onClick={() => exportChartCsv(data, columns, filename)}
          title="Download data as CSV"
          style={exportBtnStyle}
        >
          ⬇ CSV
        </button>
      )}
    </div>
  );
}

const exportBtnStyle = {
  padding: '3px 10px',
  fontSize: 10, fontWeight: 600,
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 5,
  color: '#64748b',
  cursor: 'pointer',
  transition: 'all 0.15s',
  fontFamily: 'inherit',
};
