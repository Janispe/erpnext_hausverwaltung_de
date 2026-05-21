import React, { useState, useEffect, useRef, useLayoutEffect, useMemo } from "react";
import { TEXT_BAUSTEINE } from "../data.js";

// A4 dimensions @ 96dpi
const A4_WIDTH = 794;
const A4_HEIGHT = 1123;
const A4_MARGIN_TOP = 96;     // ≈ 2.54 cm
const A4_MARGIN_BOTTOM = 100;
const A4_MARGIN_X = 96;
const PAGE_INNER_HEIGHT = A4_HEIGHT - A4_MARGIN_TOP - A4_MARGIN_BOTTOM;

// Substitute placeholders in a string with resolved recipient values
export const substituteText = (text, recipient) => {
  if (!text) return "";
  return text.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (m, key) => {
    const v = recipient?.values?.[key.trim()];
    return v != null ? v : m;
  });
};

// Evaluate a simple jinja-if condition (only supports == comparison)
export const evalJinjaCondition = (cond, recipient) => {
  if (!cond) return false;
  const m = cond.match(/^(\w+(?:\.\w+)*)\s*==\s*"([^"]+)"$/);
  if (m) {
    const v = recipient?.values?.[m[1]];
    return String(v) === m[2];
  }
  // truthy: variable defined
  const v = recipient?.values?.[cond.trim()];
  return v != null && v !== "" && v !== "0";
};

// Resolve a block to a flat array of "rendered" sub-blocks (paragraph-like).
// Bausteine expand to their preview text (further split by line break into paragraphs).
export const resolveBlocks = (blocks, recipient, bausteinMap) => {
  const out = [];
  for (const b of blocks) {
    if (b.type === "p" || b.type === "h2") {
      out.push(b);
    } else if (b.type === "baustein") {
      const bs = bausteinMap.get(b.name);
      if (!bs) {
        out.push({ type: "p", inlines: [{ type: "text", value: `[Baustein „${b.name}" nicht gefunden]` }] });
        continue;
      }
      // Add page-break-before hint if set
      if (bs.pageBreakBefore) {
        out.push({ type: "page-break-hint", before: true });
      }
      // Render baustein content — split on blank lines into paragraphs
      const paragraphs = bs.preview.split(/\n+/);
      for (const para of paragraphs) {
        out.push({ type: "p", fromBaustein: b.name, inlines: [{ type: "rendered-text", value: substituteText(para, recipient) }] });
      }
    } else if (b.type === "jinja-if") {
      if (evalJinjaCondition(b.condition, recipient)) {
        for (const inner of b.thenBlocks) {
          out.push(...resolveBlocks([inner], recipient, bausteinMap));
        }
      }
    }
  }
  return out;
};

// Render an inline node in rendered (substituted) mode
export const RenderedInline = ({ node, recipient }) => {
  if (node.type === "text") return <span>{node.value}</span>;
  if (node.type === "rendered-text") return <span>{node.value}</span>;
  if (node.type === "chip") {
    const key = (node.token.match(/\{\{\s*([^}]+?)\s*\}\}/) || [])[1]?.trim();
    const v = recipient?.values?.[key];
    if (v == null) {
      return <span className="missing-value" title={node.token}>{node.token}</span>;
    }
    return <span className="resolved-value" data-token={node.token}>{v}</span>;
  }
  return null;
};

export const RenderedBlock = ({ block, recipient }) => {
  if (block.type === "p") {
    return (
      <p>
        {block.inlines.length === 0 || (block.inlines.length === 1 && !block.inlines[0].value)
          ? <br/>
          : block.inlines.map((n, i) => <RenderedInline key={i} node={n} recipient={recipient}/>)}
      </p>
    );
  }
  if (block.type === "h2") {
    return <h2>{block.inlines.map((n, i) => <RenderedInline key={i} node={n} recipient={recipient}/>)}</h2>;
  }
  return null;
};

// =====================================
// Page-paginated rendering
// =====================================
export const InlinePreview = ({ template, recipient, onPageCount }) => {
  const bausteinMap = useMemo(() => {
    const m = new Map();
    TEXT_BAUSTEINE.forEach(bs => m.set(bs.name, bs));
    return m;
  }, []);

  const resolved = useMemo(() => resolveBlocks(template.blocks, recipient, bausteinMap), [template, recipient, bausteinMap]);

  // We render into a hidden measurer, capture each block's height, then group into pages.
  const measureRef = useRef(null);
  const [pages, setPages] = useState([[]]);
  const [stale, setStale] = useState(true);

  useLayoutEffect(() => { setStale(true); }, [resolved]);

  useLayoutEffect(() => {
    if (!stale) return;
    const el = measureRef.current;
    if (!el) return;
    const children = el.querySelectorAll("[data-measure-idx]");
    const heights = Array.from(children).map(c => c.getBoundingClientRect().height);

    const pagesNext = [];
    let cur = [];
    let curH = 0;
    resolved.forEach((b, i) => {
      const h = heights[i] || 0;
      if (b.type === "page-break-hint" && b.before && cur.length > 0) {
        pagesNext.push(cur);
        cur = []; curH = 0;
        return;
      }
      if (curH + h > PAGE_INNER_HEIGHT && cur.length > 0) {
        pagesNext.push(cur);
        cur = []; curH = 0;
      }
      cur.push(b);
      curH += h;
    });
    if (cur.length > 0) pagesNext.push(cur);
    setPages(pagesNext);
    setStale(false);
    onPageCount && onPageCount(pagesNext.length);
  }, [stale, resolved, onPageCount]);

  return (
    <div className="a4-stage">
      {/* Hidden measurer */}
      <div ref={measureRef} className="a4-measurer" aria-hidden="true">
        {resolved.map((b, i) => (
          <div key={i} data-measure-idx={i}>
            {b.type === "page-break-hint" ? <div style={{height: 0}}/> : <RenderedBlock block={b} recipient={recipient}/>}
          </div>
        ))}
      </div>

      {pages.map((pageBlocks, pageIdx) => (
        <React.Fragment key={pageIdx}>
          {pageIdx > 0 && (
            <div className="page-break-label">
              <span className="page-break-line"/>
              <span className="page-break-text">Seitenumbruch · Seite {pageIdx + 1}</span>
              <span className="page-break-line"/>
            </div>
          )}
          <div className="a4-page">
            <div className="a4-margin-guide top" />
            <div className="a4-margin-guide bottom" />
            <div className="a4-margin-guide left" />
            <div className="a4-margin-guide right" />
            <div className="a4-content">
              {pageBlocks.map((b, i) => (
                <RenderedBlock key={i} block={b} recipient={recipient}/>
              ))}
            </div>
            <div className="a4-page-footer">
              <span>Seite {pageIdx + 1} von {pages.length}</span>
              <span style={{ float: "right" }}>{recipient.label.split("—")[0].trim()} · {template.title}</span>
            </div>
          </div>
        </React.Fragment>
      ))}
    </div>
  );
};


