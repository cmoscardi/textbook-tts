import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).toString();

export default function PdfOverlayViewer({
  pdfUrl,
  pages,
  sentences,
  currentSentenceIdx,
  onSentenceClick,
}) {
  const containerRef = useRef(null);
  const currentSentenceRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(800);
  const [hoveredSentenceId, setHoveredSentenceId] = useState(null);

  // Measure container width
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      setContainerWidth(entries[0].contentRect.width);
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Auto-scroll to current sentence
  useEffect(() => {
    if (currentSentenceRef.current) {
      currentSentenceRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [currentSentenceIdx]);

  // Group sentences by page_id, preserving global index
  const sentencesByPage = useMemo(() => {
    const grouped = new Map();
    sentences.forEach((sentence, globalIdx) => {
      if (!sentence.bbox || !sentence.page_id) return;
      if (!grouped.has(sentence.page_id)) {
        grouped.set(sentence.page_id, []);
      }
      grouped.get(sentence.page_id).push({ ...sentence, globalIdx });
    });
    return grouped;
  }, [sentences]);

  const getSentenceStyle = useCallback((globalIdx, sentenceId) => {
    const isActive = globalIdx === currentSentenceIdx;
    const isHovered = sentenceId === hoveredSentenceId;

    if (isActive) {
      return {
        fill: 'rgba(59, 130, 246, 0.3)',
        stroke: 'rgb(37, 99, 235)',
        strokeWidth: 2,
      };
    }
    if (isHovered) {
      return {
        fill: 'rgba(59, 130, 246, 0.15)',
        stroke: 'rgb(59, 130, 246)',
        strokeWidth: 1,
      };
    }
    return {
      fill: 'transparent',
      stroke: 'transparent',
      strokeWidth: 0,
    };
  }, [currentSentenceIdx, hoveredSentenceId]);

  return (
    <div ref={containerRef} className="w-full">
      <Document
        file={pdfUrl}
        loading={
          <div className="flex justify-center items-center h-96">
            <div className="text-gray-600">Loading PDF...</div>
          </div>
        }
        error={
          <div className="text-red-600 text-center py-8">
            Failed to load PDF.
          </div>
        }
      >
        {pages.map((page) => {
          const pageSentences = sentencesByPage.get(page.page_id) || [];

          return (
            <div key={page.page_id} className="mb-4 relative">
              <Page
                pageNumber={page.page_number + 1}
                width={containerWidth}
                renderTextLayer={false}
                renderAnnotationLayer={false}
              />
              <svg
                viewBox={`0 0 ${page.width} ${page.height}`}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  pointerEvents: 'none',
                }}
              >
                {pageSentences.map((sentence) => {
                  const isActive = sentence.globalIdx === currentSentenceIdx;
                  const style = getSentenceStyle(sentence.globalIdx, sentence.sentence_id);

                  return (
                    <g
                      key={sentence.sentence_id}
                      ref={isActive ? currentSentenceRef : null}
                      style={{ pointerEvents: 'auto', cursor: 'pointer' }}
                      onClick={() => onSentenceClick(sentence.globalIdx)}
                      onMouseEnter={() => setHoveredSentenceId(sentence.sentence_id)}
                      onMouseLeave={() => setHoveredSentenceId(null)}
                    >
                      {sentence.bbox.map((polygon, idx) => (
                        <polygon
                          key={idx}
                          points={polygon.map((p) => p.join(',')).join(' ')}
                          fill={style.fill}
                          stroke={style.stroke}
                          strokeWidth={style.strokeWidth}
                        />
                      ))}
                    </g>
                  );
                })}
              </svg>
            </div>
          );
        })}
      </Document>
    </div>
  );
}
