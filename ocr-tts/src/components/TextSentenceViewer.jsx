import { useState, useEffect, useRef, useCallback } from 'react';

export default function TextSentenceViewer({
  sentences,
  currentSentenceIdx,
  onSentenceClick,
}) {
  const currentSentenceRef = useRef(null);
  const [hoveredIdx, setHoveredIdx] = useState(null);

  // Auto-scroll to current sentence
  useEffect(() => {
    if (currentSentenceRef.current) {
      currentSentenceRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [currentSentenceIdx]);

  return (
    <div className="space-y-1">
      {sentences.map((sentence, idx) => {
        const isActive = idx === currentSentenceIdx;
        const isHovered = idx === hoveredIdx;

        return (
          <span
            key={sentence.sentence_id}
            ref={isActive ? currentSentenceRef : null}
            onClick={() => onSentenceClick(idx)}
            onMouseEnter={() => setHoveredIdx(idx)}
            onMouseLeave={() => setHoveredIdx(null)}
            className={[
              'cursor-pointer rounded px-1 py-0.5 transition-colors inline',
              isActive
                ? 'bg-blue-200 text-blue-900'
                : isHovered
                  ? 'bg-blue-50 text-gray-900'
                  : 'text-gray-800',
            ].join(' ')}
          >
            {sentence.text}{' '}
          </span>
        );
      })}
    </div>
  );
}
