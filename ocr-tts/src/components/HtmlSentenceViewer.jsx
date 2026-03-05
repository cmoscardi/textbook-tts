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

  // Render HTML and wrap sentences in <mark> elements
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !sanitizedHtml) return;

    container.innerHTML = sanitizedHtml;
    marksRef.current = new Map();

    if (sentences.length === 0) return;

    // Collect all text nodes, inserting a space between nodes from different
    // parents so that element boundaries (e.g. <br>, adjacent <p>) produce
    // whitespace — matching the backend's BS4 get_text(separator='\n').
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    let totalText = '';
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = node.textContent;
      if (text.length === 0) continue;
      // Insert a synthetic space between adjacent text nodes so that
      // "end of para""start of next" becomes "end of para start of next"
      if (totalText.length > 0 && !/\s$/.test(totalText) && !/^\s/.test(text)) {
        totalText += ' ';
      }
      textNodes.push({ node, start: totalText.length, length: text.length });
      totalText += text;
    }

    // Normalize whitespace for matching
    const normalize = (s) => s.replace(/\s+/g, ' ').trim();
    const normalizedTotal = normalize(totalText);

    // Build mapping from normalized-string positions back to original positions
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
      const origEnd = (lastNormIdx < normToOrig.length
        ? normToOrig[lastNormIdx]
        : totalText.length - 1) + 1;
      sentenceRanges.push({ sentIdx: i, origStart, origEnd });
      searchFrom = pos + normSent.length;
    }

    // Forward-pass: process each text node once, replacing it with a
    // DocumentFragment of plain text + <mark> elements. No stale references
    // because each node is visited exactly once then replaced.
    const newMarks = new Map();
    let srIdx = 0;

    for (const tn of textNodes) {
      const nodeStart = tn.start;
      const nodeEnd = tn.start + tn.length;
      const nodeText = tn.node.textContent;

      // Collect segments (runs of plain text or sentence-marked text)
      const segments = [];
      let localPos = 0;

      while (srIdx < sentenceRanges.length) {
        const sr = sentenceRanges[srIdx];
        if (sr.origStart >= nodeEnd) break; // sentence starts after this node

        // Skip sentences that ended before this node (shouldn't normally
        // happen, but guard against it)
        if (sr.origEnd <= nodeStart) { srIdx++; continue; }

        const localStart = Math.max(0, sr.origStart - nodeStart);
        const localEnd = Math.min(tn.length, sr.origEnd - nodeStart);

        // Gap before this sentence
        if (localStart > localPos) {
          segments.push({ text: nodeText.slice(localPos, localStart), sentIdx: null });
        }

        // Sentence portion
        segments.push({ text: nodeText.slice(localStart, localEnd), sentIdx: sr.sentIdx });
        localPos = localEnd;

        if (sr.origEnd <= nodeEnd) {
          srIdx++; // sentence ends in this node, advance to next
        } else {
          break; // sentence continues into the next text node
        }
      }

      // Trailing text after last sentence in this node
      if (localPos < tn.length) {
        segments.push({ text: nodeText.slice(localPos), sentIdx: null });
      }

      // If no sentence touches this node, skip — leave the DOM alone
      if (segments.length === 0) continue;
      if (segments.length === 1 && segments[0].sentIdx === null) continue;

      // Replace the original text node with a fragment
      const fragment = document.createDocumentFragment();
      for (const seg of segments) {
        if (seg.sentIdx !== null) {
          const mark = document.createElement('mark');
          mark.dataset.sentenceIdx = seg.sentIdx;
          mark.className = 'sentence-mark cursor-pointer transition-colors rounded';
          mark.textContent = seg.text;
          fragment.appendChild(mark);
          if (!newMarks.has(seg.sentIdx)) newMarks.set(seg.sentIdx, []);
          newMarks.get(seg.sentIdx).push(mark);
        } else {
          fragment.appendChild(document.createTextNode(seg.text));
        }
      }

      tn.node.parentNode.replaceChild(fragment, tn.node);
    }

    marksRef.current = newMarks;
  }, [sanitizedHtml, sentences]);

  // Update highlight classes when active/hovered sentence changes
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

  // Auto-scroll to active sentence
  useEffect(() => {
    const marks = marksRef.current.get(currentSentenceIdx);
    if (marks && marks.length > 0) {
      marks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [currentSentenceIdx]);

  // Event delegation for clicks and hover
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
