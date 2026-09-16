import { useEffect, useId, useRef, useState } from 'react';

/**
 * Renders agent-authored Mermaid text (e.g. a feature's sequenceDiagram).
 * Nothing validates Mermaid syntax server-side, so a render failure is a
 * normal, expected outcome here — falls back to the raw text rather than
 * crashing the page. Loads `mermaid` via a dynamic import: it's a large
 * package (dagre/cytoscape/dompurify transitively) and this is the only
 * place in the app that needs it.
 */
export function MermaidDiagram({ code }: { code: string }) {
  const rawId = useId().replace(/[^a-zA-Z0-9]/g, '');
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);

    import('mermaid')
      .then(async ({ default: mermaid }) => {
        mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
        const { svg } = await mermaid.render(`mermaid-${rawId}`, code);
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });

    return () => {
      cancelled = true;
    };
  }, [code, rawId]);

  if (error) {
    return (
      <div data-testid="mermaid-render-error">
        <p className="text-xs text-[#a5453c]">Couldn't render this diagram.</p>
        <pre className="mt-2 overflow-x-auto rounded bg-[#202f35] p-3 text-[10px] leading-5 text-[#d6ded6]">
          {code}
        </pre>
      </div>
    );
  }

  return <div ref={containerRef} data-testid="mermaid-diagram" className="overflow-x-auto" />;
}
