// Inline SVG icon set
import React from "react";

export const Icon = ({ name, size = 16, ...props }) => {
  const s = size;
  const common = { width: s, height: s, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", ...props };
  switch (name) {
    case "search":
      return <svg {...common}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>;
    case "chevron-right":
      return <svg {...common}><path d="m9 6 6 6-6 6"/></svg>;
    case "chevron-down":
      return <svg {...common}><path d="m6 9 6 6 6-6"/></svg>;
    case "pin":
      return <svg {...common}><path d="M12 2v6"/><path d="M5 10h14l-2 5H7l-2-5Z"/><path d="M12 15v7"/></svg>;
    case "user":
      return <svg {...common}><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>;
    case "building":
      return <svg {...common}><rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2"/></svg>;
    case "door":
      return <svg {...common}><path d="M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16"/><path d="M3 21h18"/><circle cx="15" cy="13" r=".7" fill="currentColor"/></svg>;
    case "euro":
      return <svg {...common}><path d="M16 6a6 6 0 1 0 0 12"/><path d="M5 10h8M5 14h8"/></svg>;
    case "calendar":
      return <svg {...common}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 3v4M16 3v4"/></svg>;
    case "credit-card":
      return <svg {...common}><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 11h18M7 16h3"/></svg>;
    case "bold":
      return <svg {...common}><path d="M7 5h6a3.5 3.5 0 0 1 0 7H7zM7 12h7a3.5 3.5 0 0 1 0 7H7z"/></svg>;
    case "italic":
      return <svg {...common}><path d="M19 4h-9M14 20H5M15 4 9 20"/></svg>;
    case "underline":
      return <svg {...common}><path d="M6 4v7a6 6 0 0 0 12 0V4"/><path d="M4 20h16"/></svg>;
    case "list":
      return <svg {...common}><path d="M9 6h12M9 12h12M9 18h12M4 6h.01M4 12h.01M4 18h.01"/></svg>;
    case "list-ordered":
      return <svg {...common}><path d="M9 6h12M9 12h12M9 18h12M3 6h1v4M3 10h2M4 14h-1.5a1 1 0 0 0 0 2c1 0 1.5 1 1.5 1s-.5 1-1.5 1H3"/></svg>;
    case "align-left":
      return <svg {...common}><path d="M3 6h18M3 12h12M3 18h18M3 9h18"/></svg>;
    case "align-center":
      return <svg {...common}><path d="M3 6h18M6 12h12M3 18h18M3 9h18"/></svg>;
    case "align-right":
      return <svg {...common}><path d="M3 6h18M9 12h12M3 18h18M3 9h18"/></svg>;
    case "link":
      return <svg {...common}><path d="M10 14a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1 1"/><path d="M14 10a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1-1"/></svg>;
    case "code":
      return <svg {...common}><path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/></svg>;
    case "tag":
      return <svg {...common}><path d="M20.59 13.41 12 22l-9-9V3h10l9.59 9.59a2 2 0 0 1 0 2.82Z"/><circle cx="7.5" cy="7.5" r=".8" fill="currentColor"/></svg>;
    case "block":
      return <svg {...common}><rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="11" height="6" rx="1"/></svg>;
    case "branch":
      return <svg {...common}><circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="12" r="2"/><path d="M6 8v8M6 14c0-4 5-2 5-2 1 0 7 0 7 0"/></svg>;
    case "play":
      return <svg {...common}><polygon points="6 4 20 12 6 20 6 4" fill="currentColor"/></svg>;
    case "refresh":
      return <svg {...common}><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>;
    case "download":
      return <svg {...common}><path d="M12 4v12M6 12l6 6 6-6M4 20h16"/></svg>;
    case "send":
      return <svg {...common}><path d="m4 12 16-8-6 18-3-8z"/></svg>;
    case "more":
      return <svg {...common}><circle cx="12" cy="6" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="18" r="1.4" fill="currentColor"/></svg>;
    case "copy":
      return <svg {...common}><rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>;
    case "x":
      return <svg {...common}><path d="m6 6 12 12M18 6 6 18"/></svg>;
    case "check":
      return <svg {...common}><path d="m5 12 5 5L20 7"/></svg>;
    case "back":
      return <svg {...common}><path d="m15 18-6-6 6-6"/></svg>;
    case "save":
      return <svg {...common}><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>;
    case "plus":
      return <svg {...common}><path d="M12 5v14M5 12h14"/></svg>;
    case "drag":
      return <svg {...common}><circle cx="9" cy="6" r="1" fill="currentColor"/><circle cx="9" cy="12" r="1" fill="currentColor"/><circle cx="9" cy="18" r="1" fill="currentColor"/><circle cx="15" cy="6" r="1" fill="currentColor"/><circle cx="15" cy="12" r="1" fill="currentColor"/><circle cx="15" cy="18" r="1" fill="currentColor"/></svg>;
    default:
      return <svg {...common}><circle cx="12" cy="12" r="9"/></svg>;
  }
};
