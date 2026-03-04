import { useRef, useEffect, useCallback, useState } from 'react';

export default function HtmlSentenceViewer({
  sanitizedHtml,
  sentences,
  currentSentenceIdx,
  onSentenceClick,
}) {
  const containerRef = useRef(null);
  const [hoveredIdx, setHoveredIdx] = useState(null);
  const marksRef = useRef(new Map()); // idx → [mark elements]

  // 1. Render HTML and wrap sentences in <mark> elements
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !sanitizedHtml) return;

    // Set raw HTML first
    container.innerHTML = sanitizedHtml;

    if (sentences.length === 0) return;

    // Collect all text nodes
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    let totalText = '';
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = node.textContent;
      textNodes.push({ node, start: totalText.length, length: text.length });
      totalText += text;
    }

    // Normalize whitespace for matching
    const normalize = (s) => s.replace(/\s+/g, ' ').trim();
    const normalizedTotal = normalize(totalText);

    // Build a mapping from normalized-string positions back to original positions
    // (needed because whitespace collapsing changes offsets)
    const normToOrig = [];
    let ni = 0;
    for (let oi = 0; oi < totalText.length && ni < normalizedTotal.length; oi++) {
      if (/\s/.test(totalText[oi])) {
        if (normalizedTotal[ni] === ' ') {
          normToOrig[ni] = oi;
          ni++;
        }
      } else {
        normToOrig[ni] = oi;
        ni++;
      }
    }

    // Find each sentence's position in the concatenated text
    const sentenceRanges = [];
    let searchFrom = 0;
    for (let i = 0; i < sentences.length; i++) {
      const normSent = normalize(sentences[i].text);
      if (!normSent) continue;
      const pos = normalizedTotal.indexOf(normSent, searchFrom);
      if (pos === -1) continue;
      const origStart = normToOrig[pos];
      const lastNormIdx = pos + normSent.length - 1;
      const origEnd = (lastNormIdx < normToOrig.length ? normToOrig[lastNormIdx] : totalText.length - 1) + 1;
      sentenceRanges.push({ sentIdx: i, origStart, origEnd });
      searchFrom = pos + normSent.length;
    }

    // Wrap in reverse order to preserve earlier offsets
    const newMarks = new Map();
    for (let r = sentenceRanges.length - 1; r >= 0; r--) {
      const { sentIdx, origStart, origEnd } = sentenceRanges[r];

      const marks = [];
      for (const tn of textNodes) {
        const tnEnd = tn.start + tn.length;
        if (tn.start >= origEnd || tnEnd <= origStart) continue;

        const localStart = Math.max(0, origStart - tn.start);
        const localEnd = Math.min(tn.length, origEnd - tn.start);

        const range = document.createRange();
        range.setStart(tn.node, localStart);
        range.setEnd(tn.node, localEnd);

        const mark = document.createElement('mark');
        mark.dataset.sentenceIdx = sentIdx;
        mark.className = 'sentence-mark cursor-pointer transition-colors rounded';
        try {
          range.surroundContents(mark);
        } catch {
          const fragment = range.extractContents();
          mark.appendChild(fragment);
          range.insertNode(mark);
        }
        marks.push(mark);
      }
      newMarks.set(sentIdx, marks);
    }

    marksRef.current = newMarks;
  }, [sanitizedHtml, sentences]);

  // 2. Update highlight classes when active/hovered sentence changes
  useEffect(() => {
    const marks = marksRef.current;
    marks.forEach((elements, idx) => {
      for (const el of elements) {
        el.classList.remove('bg-blue-200', 'text-blue-900', 'bg-blue-50');
        if (idx === currentSentenceIdx) {
          el.classList.add('bg-blue-200', 'text-blue-900');
        } else if (idx === hoveredIdx) {
          el.classList.add('bg-blue-50');
        }
      }
    });
  }, [currentSentenceIdx, hoveredIdx]);

  // 3. Auto-scroll to active sentence
  useEffect(() => {
    const marks = marksRef.current.get(currentSentenceIdx);
    if (marks && marks.length > 0) {
      marks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [currentSentenceIdx]);

  // 4. Event delegation for clicks and hover
  const handleClick = useCallback((e) => {
    const mark = e.target.closest('mark[data-sentence-idx]');
    if (mark) {
      onSentenceClick(parseInt(mark.dataset.sentenceIdx, 10));
    }
  }, [onSentenceClick]);

  const handleMouseOver = useCallback((e) => {
    const mark = e.target.closest('mark[data-sentence-idx]');
    if (mark) setHoveredIdx(parseInt(mark.dataset.sentenceIdx, 10));
  }, []);

  const handleMouseOut = useCallback((e) => {
    const mark = e.target.closest('mark[data-sentence-idx]');
    if (mark) setHoveredIdx(null);
  }, []);

  return (
    <article
      ref={containerRef}
      className="prose prose-lg max-w-none text-gray-900 prose-headings:text-gray-900 prose-p:text-gray-800 prose-li:text-gray-800 prose-strong:text-gray-900 prose-a:text-blue-600"
      onClick={handleClick}
      onMouseOver={handleMouseOver}
      onMouseOut={handleMouseOut}
    />
  );
}
