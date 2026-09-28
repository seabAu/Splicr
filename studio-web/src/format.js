export function textStats(text) {
  const trimmed = text.trim();
  return {
    characters: text.length,
    words: trimmed ? trimmed.split(/\s+/u).length : 0,
    bytes: new TextEncoder().encode(text).length,
  };
}

export function percent(value) {
  return `${Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100)))}%`;
}

export function formatCount(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

export function statusLabel(value) {
  return String(value || "idle")
    .replaceAll("_", " ")
    .replace(/^./u, (letter) => letter.toUpperCase());
}
