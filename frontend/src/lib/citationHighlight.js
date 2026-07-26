/**
 * Best-effort visual link between a streamed answer and the source chunks
 * that produced it. The backend doesn't return citation offsets, so this
 * finds the longest verbatim overlap between the answer and each source
 * chunk's text and marks it - it's a presentation heuristic layered on top
 * of always-accurate source cards, not a claim the model told us what it
 * cited. Answers that don't reuse chunk wording verbatim just render plain.
 */
const MIN_MATCH_LENGTH = 12;

function longestCommonSubstring(a, b) {
  const na = a.toLowerCase();
  const nb = b.toLowerCase();
  let prev = new Array(nb.length + 1).fill(0);
  let best = { length: 0, bStart: 0 };

  for (let i = 1; i <= na.length; i++) {
    const curr = new Array(nb.length + 1).fill(0);
    for (let j = 1; j <= nb.length; j++) {
      if (na[i - 1] === nb[j - 1]) {
        curr[j] = prev[j - 1] + 1;
        if (curr[j] > best.length) {
          best = { length: curr[j], bStart: j - curr[j] };
        }
      }
    }
    prev = curr;
  }
  return best;
}

export function highlightCitations(answer, sources) {
  const spans = [];
  for (const src of sources) {
    const match = longestCommonSubstring(src.text, answer);
    if (match.length >= MIN_MATCH_LENGTH) {
      spans.push({ start: match.bStart, end: match.bStart + match.length, sourceId: src.id });
    }
  }
  spans.sort((a, b) => a.start - b.start);

  const nonOverlapping = [];
  let lastEnd = -1;
  for (const s of spans) {
    if (s.start >= lastEnd) {
      nonOverlapping.push(s);
      lastEnd = s.end;
    }
  }

  if (!nonOverlapping.length) return [{ text: answer, sourceId: null }];

  const segments = [];
  let cursor = 0;
  for (const s of nonOverlapping) {
    if (s.start > cursor) segments.push({ text: answer.slice(cursor, s.start), sourceId: null });
    segments.push({ text: answer.slice(s.start, s.end), sourceId: s.sourceId });
    cursor = s.end;
  }
  if (cursor < answer.length) segments.push({ text: answer.slice(cursor), sourceId: null });
  return segments;
}
