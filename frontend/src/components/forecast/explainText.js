// Helpers for the sparkle "Explain this chart" popover.

// Split precomputed explanation text into a short headline (first sentence or two, kept under
// maxHeadline characters) and the remaining detail. Sentences are split on ". " / "! " / "? "
// followed by a capital letter, "$" or "(" so decimals like "$13.6M" never split.
export function splitExplanation(text, maxHeadline = 190) {
  const value = String(text ?? '').trim();
  if (!value) return { headline: '', rest: '' };
  const sentences = value.split(/(?<=[.!?])\s+(?=[A-Z$(])/);
  let headline = '';
  let used = 0;
  for (const sentence of sentences) {
    const candidate = headline ? `${headline} ${sentence}` : sentence;
    if (headline && candidate.length > maxHeadline) break;
    headline = candidate;
    used += 1;
  }
  return { headline, rest: sentences.slice(used).join(' ') };
}

// Short bullets ("Q1: $13.6M actual") read better as a compact grid than a tall list.
export function bulletsAreCompact(bullets, maxLength = 40) {
  const list = bullets || [];
  return list.length > 1 && list.every(b => String(b).length <= maxLength);
}
