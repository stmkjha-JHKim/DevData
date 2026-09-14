/* icons.js -- one small inline-SVG icon set shared by the whole UI.
 *
 * Every icon is a plain 20x20 stroke-only glyph (no fill, currentColor
 * stroke) so a single CSS `color` on the wrapping element recolors it --
 * sidebar items, status badges, and list rows all reuse the same set
 * without needing per-context icon variants.
 *
 * Not an icon *font* or external library on purpose: this project has no
 * build step and is meant to run by double-clicking index.html, so every
 * asset it needs has to already be a local file (see README.md).
 */
const ICONS = {
  home: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9.5 10 3l7 6.5"/><path d="M5 8.5V17h10V8.5"/><path d="M8 17v-5h4v5"/></svg>`,

  compare: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4 4 7l3 3"/><path d="M4 7h9a3 3 0 0 1 3 3v1"/><path d="M13 16l3-3-3-3"/><path d="M16 13H7a3 3 0 0 1-3-3V9"/></svg>`,

  shieldCheck: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3l6 2.2v4.6c0 4-2.6 6.6-6 7.7-3.4-1.1-6-3.7-6-7.7V5.2L10 3z"/><path d="M7.5 10l1.8 1.8L12.8 8"/></svg>`,

  listCheck: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5.5h1.6M4 10h1.6M4 14.5h1.6"/><path d="M8.4 5.5H16M8.4 14.5H16"/><path d="M8.4 8.6l1.4 1.4 2.6-2.8"/></svg>`,

  history: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8a6 6 0 1 1 1.3 5.3"/><path d="M4 4.5V8h3.5"/><path d="M10 6.5V10l2.4 1.6"/></svg>`,

  code: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7.2 6 3.8 10l3.4 4"/><path d="M12.8 6l3.4 4-3.4 4"/></svg>`,

  searchAlert: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="8.6" cy="8.6" r="4.6"/><path d="M15.5 15.5 12 12"/><path d="M8.6 6.8v2.1"/><circle cx="8.6" cy="10.9" r="0.15" fill="currentColor" stroke="none"/></svg>`,

  lock: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4.5" y="9" width="11" height="7" rx="1.6"/><path d="M6.8 9V6.5a3.2 3.2 0 0 1 6.4 0V9"/></svg>`,

  barChart: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 16.5h12"/><path d="M6.5 16.5v-4M10 16.5v-8M13.5 16.5v-6"/></svg>`,

  trendingUp: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 13.5l4-4 2.6 2.6L16 6.8"/><path d="M12.2 6.8H16v3.8"/></svg>`,

  archive: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4" width="13" height="3.2" rx="0.8"/><path d="M4.5 7.2v7a1.4 1.4 0 0 0 1.4 1.4h8.2a1.4 1.4 0 0 0 1.4-1.4v-7"/><path d="M8.2 10.4h3.6"/></svg>`,

  calendarClock: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4.5" width="13" height="11" rx="1.6"/><path d="M3.5 8h13"/><path d="M6.5 3v3M13.5 3v3"/><circle cx="12.5" cy="12" r="2.6"/><path d="M12.5 10.9v1.1l0.8 0.5"/></svg>`,

  userShield: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="7" r="2.6"/><path d="M3.6 16c0.5-2.6 2.2-4 4.4-4"/><path d="M13.2 8.2l3 1.1v2.2c0 1.9-1.2 3.2-3 3.8-1.8-0.6-3-1.9-3-3.8V9.3l3-1.1z"/></svg>`,

  fileText: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5h5.5L15 7v9.5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1z"/><path d="M11.3 3.5V7H15"/><path d="M7 10h6M7 12.6h6M7 15.2h3.6"/></svg>`,

  building: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3.5" width="8" height="13" rx="0.8"/><path d="M12 8h3.5a1 1 0 0 1 1 1v7.5"/><path d="M6.4 6.5h1.4M9.6 6.5H11M6.4 9.5h1.4M9.6 9.5H11M6.4 12.5h1.4M9.6 12.5H11"/><path d="M13.6 11h1.2M13.6 13.8h1.2"/></svg>`,

  alertTriangle: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3.6 17 15.8H3L10 3.6z"/><path d="M10 8.4v3.2"/><circle cx="10" cy="13.6" r="0.15" fill="currentColor" stroke="none"/></svg>`,

  database: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="10" cy="5.2" rx="6" ry="2.2"/><path d="M4 5.2v9.6c0 1.2 2.7 2.2 6 2.2s6-1 6-2.2V5.2"/><path d="M4 10c0 1.2 2.7 2.2 6 2.2s6-1 6-2.2"/></svg>`,

  chevronRight: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7.5 4.5 13 10l-5.5 5.5"/></svg>`,

  clock: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="6.5"/><path d="M10 6.4V10l2.6 1.6"/></svg>`,

  layers: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M10 3.2 3.5 7 10 10.8 16.5 7 10 3.2z"/><path d="M3.5 10.4 10 14.2l6.5-3.8"/><path d="M3.5 13.7 10 17.5l6.5-3.8"/></svg>`,

  flask: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8.2 3.5h3.6"/><path d="M8.9 3.5v4.6L4.9 14a1.6 1.6 0 0 0 1.4 2.5h7.4a1.6 1.6 0 0 0 1.4-2.5l-4-5.9V3.5"/><path d="M6.4 12.2h7.2"/></svg>`,
};
