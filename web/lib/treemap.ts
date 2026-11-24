// Squarified treemap layout (Bruls, Huizing, van Wijk 2000). Pure and deterministic.

export interface TreemapInput<T> {
  value: number;
  data: T;
}

export interface TreemapTile<T> {
  x: number;
  y: number;
  w: number;
  h: number;
  data: T;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

function worst(row: number[], side: number): number {
  const sum = row.reduce((a, b) => a + b, 0);
  const max = Math.max(...row);
  const min = Math.min(...row);
  const s2 = side * side;
  const sum2 = sum * sum;
  return Math.max((s2 * max) / sum2, sum2 / (s2 * min));
}

function placeRow<T>(
  row: { area: number; data: T }[],
  rect: Rect,
): { tiles: TreemapTile<T>[]; rest: Rect } {
  const total = row.reduce((a, r) => a + r.area, 0);
  const horizontal = rect.w >= rect.h; // lay the row along the short side
  const tiles: TreemapTile<T>[] = [];
  if (horizontal) {
    const colW = total / rect.h;
    let y = rect.y;
    for (const r of row) {
      const h = r.area / colW;
      tiles.push({ x: rect.x, y, w: colW, h, data: r.data });
      y += h;
    }
    return { tiles, rest: { x: rect.x + colW, y: rect.y, w: rect.w - colW, h: rect.h } };
  }
  const rowH = total / rect.w;
  let x = rect.x;
  for (const r of row) {
    const w = r.area / rowH;
    tiles.push({ x, y: rect.y, w, h: rowH, data: r.data });
    x += w;
  }
  return { tiles, rest: { x: rect.x, y: rect.y + rowH, w: rect.w, h: rect.h - rowH } };
}

export function squarify<T>(items: TreemapInput<T>[], width: number, height: number): TreemapTile<T>[] {
  const positive = items.filter((i) => i.value > 0).toSorted((a, b) => b.value - a.value);
  const total = positive.reduce((a, i) => a + i.value, 0);
  if (total <= 0 || width <= 0 || height <= 0) return [];
  const scale = (width * height) / total;
  const queue = positive.map((i) => ({ area: i.value * scale, data: i.data }));

  const out: TreemapTile<T>[] = [];
  let rect: Rect = { x: 0, y: 0, w: width, h: height };
  let row: typeof queue = [];
  for (const item of queue) {
    const side = Math.min(rect.w, rect.h);
    const areas = row.map((r) => r.area);
    if (row.length === 0 || worst([...areas, item.area], side) <= worst(areas, side)) {
      row = [...row, item];
      continue;
    }
    const placed = placeRow(row, rect);
    out.push(...placed.tiles);
    rect = placed.rest;
    row = [item];
  }
  if (row.length > 0) out.push(...placeRow(row, rect).tiles);
  return out;
}
