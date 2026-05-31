/* op-workflow bundle — siehe op_workflow_build/esbuild.config.mjs */
var OpWorkflow = (() => {
  // ../hausverwaltung/public/op_workflow/tweaks-panel.jsx
  var __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;
  function useTweaks2(defaults) {
    const [values, setValues] = React.useState(defaults);
    const setTweak = React.useCallback((keyOrEdits, val) => {
      const edits = typeof keyOrEdits === "object" && keyOrEdits !== null ? keyOrEdits : { [keyOrEdits]: val };
      setValues((prev) => ({ ...prev, ...edits }));
      window.parent.postMessage({ type: "__edit_mode_set_keys", edits }, "*");
      window.dispatchEvent(new CustomEvent("tweakchange", { detail: edits }));
    }, []);
    return [values, setTweak];
  }
  function TweaksPanel2({ title = "Tweaks", children }) {
    const [open, setOpen] = React.useState(false);
    const dragRef = React.useRef(null);
    const offsetRef = React.useRef({ x: 16, y: 16 });
    const PAD = 16;
    const clampToViewport = React.useCallback(() => {
      const panel = dragRef.current;
      if (!panel)
        return;
      const w = panel.offsetWidth, h = panel.offsetHeight;
      const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
      const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
      offsetRef.current = {
        x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
        y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
      };
      panel.style.right = offsetRef.current.x + "px";
      panel.style.bottom = offsetRef.current.y + "px";
    }, []);
    React.useEffect(() => {
      if (!open)
        return;
      clampToViewport();
      if (typeof ResizeObserver === "undefined") {
        window.addEventListener("resize", clampToViewport);
        return () => window.removeEventListener("resize", clampToViewport);
      }
      const ro = new ResizeObserver(clampToViewport);
      ro.observe(document.documentElement);
      return () => ro.disconnect();
    }, [open, clampToViewport]);
    React.useEffect(() => {
      const onMsg = (e) => {
        const t = e?.data?.type;
        if (t === "__activate_edit_mode")
          setOpen(true);
        else if (t === "__deactivate_edit_mode")
          setOpen(false);
      };
      window.addEventListener("message", onMsg);
      window.parent.postMessage({ type: "__edit_mode_available" }, "*");
      return () => window.removeEventListener("message", onMsg);
    }, []);
    const dismiss = () => {
      setOpen(false);
      window.parent.postMessage({ type: "__edit_mode_dismissed" }, "*");
    };
    const onDragStart = (e) => {
      const panel = dragRef.current;
      if (!panel)
        return;
      const r = panel.getBoundingClientRect();
      const sx = e.clientX, sy = e.clientY;
      const startRight = window.innerWidth - r.right;
      const startBottom = window.innerHeight - r.bottom;
      const move = (ev) => {
        offsetRef.current = {
          x: startRight - (ev.clientX - sx),
          y: startBottom - (ev.clientY - sy)
        };
        clampToViewport();
      };
      const up = () => {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    };
    if (!open)
      return null;
    return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("style", null, __TWEAKS_STYLE), /* @__PURE__ */ React.createElement(
      "div",
      {
        ref: dragRef,
        className: "twk-panel",
        "data-omelette-chrome": "",
        style: { right: offsetRef.current.x, bottom: offsetRef.current.y }
      },
      /* @__PURE__ */ React.createElement("div", { className: "twk-hd", onMouseDown: onDragStart }, /* @__PURE__ */ React.createElement("b", null, title), /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "twk-x",
          "aria-label": "Close tweaks",
          onMouseDown: (e) => e.stopPropagation(),
          onClick: dismiss
        },
        "\u2715"
      )),
      /* @__PURE__ */ React.createElement("div", { className: "twk-body" }, children)
    ));
  }
  function TweakSection2({ label, children }) {
    return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "twk-sect" }, label), children);
  }
  function TweakRow({ label, value, children, inline = false }) {
    return /* @__PURE__ */ React.createElement("div", { className: inline ? "twk-row twk-row-h" : "twk-row" }, /* @__PURE__ */ React.createElement("div", { className: "twk-lbl" }, /* @__PURE__ */ React.createElement("span", null, label), value != null && /* @__PURE__ */ React.createElement("span", { className: "twk-val" }, value)), children);
  }
  function TweakSlider({ label, value, min = 0, max = 100, step = 1, unit = "", onChange }) {
    return /* @__PURE__ */ React.createElement(TweakRow, { label, value: `${value}${unit}` }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "range",
        className: "twk-slider",
        min,
        max,
        step,
        value,
        onChange: (e) => onChange(Number(e.target.value))
      }
    ));
  }
  function TweakToggle2({ label, value, onChange }) {
    return /* @__PURE__ */ React.createElement("div", { className: "twk-row twk-row-h" }, /* @__PURE__ */ React.createElement("div", { className: "twk-lbl" }, /* @__PURE__ */ React.createElement("span", null, label)), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "twk-toggle",
        "data-on": value ? "1" : "0",
        role: "switch",
        "aria-checked": !!value,
        onClick: () => onChange(!value)
      },
      /* @__PURE__ */ React.createElement("i", null)
    ));
  }
  function TweakRadio2({ label, value, options, onChange }) {
    const trackRef = React.useRef(null);
    const [dragging, setDragging] = React.useState(false);
    const valueRef = React.useRef(value);
    valueRef.current = value;
    const labelLen = (o) => String(typeof o === "object" ? o.label : o).length;
    const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
    const fitsAsSegments = maxLen <= ({ 2: 16, 3: 10 }[options.length] ?? 0);
    if (!fitsAsSegments) {
      const resolve = (s) => {
        const m = options.find((o) => String(typeof o === "object" ? o.value : o) === s);
        return m === void 0 ? s : typeof m === "object" ? m.value : m;
      };
      return /* @__PURE__ */ React.createElement(
        TweakSelect,
        {
          label,
          value,
          options,
          onChange: (s) => onChange(resolve(s))
        }
      );
    }
    const opts = options.map((o) => typeof o === "object" ? o : { value: o, label: o });
    const idx = Math.max(0, opts.findIndex((o) => o.value === value));
    const n = opts.length;
    const segAt = (clientX) => {
      const r = trackRef.current.getBoundingClientRect();
      const inner = r.width - 4;
      const i = Math.floor((clientX - r.left - 2) / inner * n);
      return opts[Math.max(0, Math.min(n - 1, i))].value;
    };
    const onPointerDown = (e) => {
      setDragging(true);
      const v0 = segAt(e.clientX);
      if (v0 !== valueRef.current)
        onChange(v0);
      const move = (ev) => {
        if (!trackRef.current)
          return;
        const v = segAt(ev.clientX);
        if (v !== valueRef.current)
          onChange(v);
      };
      const up = () => {
        setDragging(false);
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    };
    return /* @__PURE__ */ React.createElement(TweakRow, { label }, /* @__PURE__ */ React.createElement(
      "div",
      {
        ref: trackRef,
        role: "radiogroup",
        onPointerDown,
        className: dragging ? "twk-seg dragging" : "twk-seg"
      },
      /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "twk-seg-thumb",
          style: {
            left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
            width: `calc((100% - 4px) / ${n})`
          }
        }
      ),
      opts.map((o) => /* @__PURE__ */ React.createElement("button", { key: o.value, type: "button", role: "radio", "aria-checked": o.value === value }, o.label))
    ));
  }
  function TweakSelect({ label, value, options, onChange }) {
    return /* @__PURE__ */ React.createElement(TweakRow, { label }, /* @__PURE__ */ React.createElement("select", { className: "twk-field", value, onChange: (e) => onChange(e.target.value) }, options.map((o) => {
      const v = typeof o === "object" ? o.value : o;
      const l = typeof o === "object" ? o.label : o;
      return /* @__PURE__ */ React.createElement("option", { key: v, value: v }, l);
    })));
  }
  function TweakText({ label, value, placeholder, onChange }) {
    return /* @__PURE__ */ React.createElement(TweakRow, { label }, /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "twk-field",
        type: "text",
        value,
        placeholder,
        onChange: (e) => onChange(e.target.value)
      }
    ));
  }
  function TweakNumber({ label, value, min, max, step = 1, unit = "", onChange }) {
    const clamp = (n) => {
      if (min != null && n < min)
        return min;
      if (max != null && n > max)
        return max;
      return n;
    };
    const startRef = React.useRef({ x: 0, val: 0 });
    const onScrubStart = (e) => {
      e.preventDefault();
      startRef.current = { x: e.clientX, val: value };
      const decimals = (String(step).split(".")[1] || "").length;
      const move = (ev) => {
        const dx = ev.clientX - startRef.current.x;
        const raw = startRef.current.val + dx * step;
        const snapped = Math.round(raw / step) * step;
        onChange(clamp(Number(snapped.toFixed(decimals))));
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    };
    return /* @__PURE__ */ React.createElement("div", { className: "twk-num" }, /* @__PURE__ */ React.createElement("span", { className: "twk-num-lbl", onPointerDown: onScrubStart }, label), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "number",
        value,
        min,
        max,
        step,
        onChange: (e) => onChange(clamp(Number(e.target.value)))
      }
    ), unit && /* @__PURE__ */ React.createElement("span", { className: "twk-num-unit" }, unit));
  }
  function __twkIsLight(hex) {
    const h = String(hex).replace("#", "");
    const x = h.length === 3 ? h.replace(/./g, (c) => c + c) : h.padEnd(6, "0");
    const n = parseInt(x.slice(0, 6), 16);
    if (Number.isNaN(n))
      return true;
    const r = n >> 16 & 255, g = n >> 8 & 255, b = n & 255;
    return r * 299 + g * 587 + b * 114 > 148e3;
  }
  var __TwkCheck = ({ light }) => /* @__PURE__ */ React.createElement("svg", { viewBox: "0 0 14 14", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement(
    "path",
    {
      d: "M3 7.2 5.8 10 11 4.2",
      fill: "none",
      strokeWidth: "2.2",
      strokeLinecap: "round",
      strokeLinejoin: "round",
      stroke: light ? "rgba(0,0,0,.78)" : "#fff"
    }
  ));
  function TweakColor({ label, value, options, onChange }) {
    if (!options || !options.length) {
      return /* @__PURE__ */ React.createElement("div", { className: "twk-row twk-row-h" }, /* @__PURE__ */ React.createElement("div", { className: "twk-lbl" }, /* @__PURE__ */ React.createElement("span", null, label)), /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "color",
          className: "twk-swatch",
          value,
          onChange: (e) => onChange(e.target.value)
        }
      ));
    }
    const key = (o) => String(JSON.stringify(o)).toLowerCase();
    const cur = key(value);
    return /* @__PURE__ */ React.createElement(TweakRow, { label }, /* @__PURE__ */ React.createElement("div", { className: "twk-chips", role: "radiogroup" }, options.map((o, i) => {
      const colors = Array.isArray(o) ? o : [o];
      const [hero, ...rest] = colors;
      const sup = rest.slice(0, 4);
      const on = key(o) === cur;
      return /* @__PURE__ */ React.createElement(
        "button",
        {
          key: i,
          type: "button",
          className: "twk-chip",
          role: "radio",
          "aria-checked": on,
          "data-on": on ? "1" : "0",
          "aria-label": colors.join(", "),
          title: colors.join(" \xB7 "),
          style: { background: hero },
          onClick: () => onChange(o)
        },
        sup.length > 0 && /* @__PURE__ */ React.createElement("span", null, sup.map((c, j) => /* @__PURE__ */ React.createElement("i", { key: j, style: { background: c } }))),
        on && /* @__PURE__ */ React.createElement(__TwkCheck, { light: __twkIsLight(hero) })
      );
    })));
  }
  function TweakButton({ label, onClick, secondary = false }) {
    return /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: secondary ? "twk-btn secondary" : "twk-btn",
        onClick
      },
      label
    );
  }
  Object.assign(window, {
    useTweaks: useTweaks2,
    TweaksPanel: TweaksPanel2,
    TweakSection: TweakSection2,
    TweakRow,
    TweakSlider,
    TweakToggle: TweakToggle2,
    TweakRadio: TweakRadio2,
    TweakSelect,
    TweakText,
    TweakNumber,
    TweakColor,
    TweakButton
  });

  // ../hausverwaltung/public/op_workflow/op-components.jsx
  var { useState: useStateOP, useMemo: useMemoOP } = React;
  var fmtEUR_op2 = (n) => {
    if (n == null || isNaN(n))
      return "\u2014";
    return new Intl.NumberFormat("de-DE", {
      style: "currency",
      currency: "EUR",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(n);
  };
  var fmtDate_op2 = (s) => {
    if (!s)
      return "\u2014";
    const [y, m, d] = s.split("-");
    return `${d}.${m}.${y}`;
  };
  var AGING_BUCKETS = [
    { key: "b0", label: "nicht f\xE4llig", min: -Infinity, max: 0, sub: "0 Tage" },
    { key: "b1", label: "1\u201330", min: 1, max: 30, sub: "Tage" },
    { key: "b2", label: "31\u201360", min: 31, max: 60, sub: "Tage" },
    { key: "b3", label: "61\u201390", min: 61, max: 90, sub: "Tage" },
    { key: "b4", label: "> 90", min: 91, max: Infinity, sub: "Tage" }
  ];
  var bucketOf2 = (age) => AGING_BUCKETS.find((b) => age >= b.min && age <= b.max);
  function StatusBadge2({ status }) {
    const map = {
      "Paid": ["op-status-paid", "Bezahlt"],
      "Partly Paid": ["op-status-partly", "Teilweise bezahlt"],
      "Unpaid": ["op-status-unpaid", "Offen"],
      "Overdue": ["op-status-overdue", "\xDCberf\xE4llig"],
      "Written Off": ["op-status-writtenoff", "Abgeschrieben"],
      "Partly Paid and Written Off": ["op-status-writtenoff", "Teilweise abgeschr."]
    };
    const [cls, label] = map[status] || ["op-status-unpaid", status || "\u2014"];
    return /* @__PURE__ */ React.createElement("span", { className: `op-status ${cls}` }, label);
  }
  function DirectionBadge2({ direction }) {
    const map = {
      "Geld bekommen": ["is-in", "Geld bekommen"],
      "Geld bezahlen / erstatten": ["is-out", "Geld bezahlen"],
      "Ausgeglichen": ["is-bal", "Ausgeglichen"]
    };
    const [cls, label] = map[direction] || ["is-bal", direction];
    return /* @__PURE__ */ React.createElement("span", { className: `op-dir ${cls}` }, label);
  }
  function MahnstufeBadge2({ stufe }) {
    if (!stufe)
      return null;
    const dots = Array.from({ length: stufe }, (_, i) => /* @__PURE__ */ React.createElement("span", { key: i, className: "op-mahn-dot" }));
    return /* @__PURE__ */ React.createElement("span", { className: "op-mahn", title: `Mahnstufe ${stufe}` }, dots, /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 2 } }, "M", stufe));
  }
  function AgePill2({ age, faellig_am }) {
    if (age == null)
      return null;
    if (age <= 0) {
      return /* @__PURE__ */ React.createElement("span", { className: "op-age-pill is-future" }, "f\xE4llig ", fmtDate_op2(faellig_am));
    }
    const cls = age > 30 ? "is-late" : "is-due";
    return /* @__PURE__ */ React.createElement("span", { className: `op-age-pill ${cls}` }, age, " Tage");
  }
  function AgingBar2({ buckets, totalSum, mini = false }) {
    const parts = AGING_BUCKETS.map((b) => ({ ...b, val: buckets[b.key] || 0 }));
    const total = totalSum ?? parts.reduce((a, p) => a + p.val, 0);
    if (Math.abs(total) < 0.01) {
      return /* @__PURE__ */ React.createElement("div", { className: "op-aging-bars" }, /* @__PURE__ */ React.createElement("div", { className: "op-aging-seg is-empty" }, "keine"));
    }
    return /* @__PURE__ */ React.createElement("div", { className: "op-aging-bars" }, parts.map((p, i) => {
      if (Math.abs(p.val) < 0.01)
        return null;
      const pct = p.val / total * 100;
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          key: p.key,
          className: `op-aging-seg op-aging-seg-${i}`,
          style: { flex: `${pct} 1 0` },
          title: `${p.label}: ${fmtEUR_op2(p.val)}`
        },
        !mini && pct > 8 && fmtEUR_op2(p.val).replace("\u20AC", "").trim()
      );
    }));
  }
  function AgingStrip2({ buckets }) {
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(AgingBar2, { buckets }), /* @__PURE__ */ React.createElement("div", { className: "op-aging-legend" }, AGING_BUCKETS.map((b) => {
      const v = buckets[b.key] || 0;
      return /* @__PURE__ */ React.createElement("span", { key: b.key }, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--ink-2)", fontWeight: 500 } }, b.label), /* @__PURE__ */ React.createElement("div", { className: "num" }, Math.abs(v) < 0.01 ? "\u2014" : fmtEUR_op2(v)));
    })));
  }
  Object.assign(window, {
    fmtEUR_op: fmtEUR_op2,
    fmtDate_op: fmtDate_op2,
    AGING_BUCKETS,
    bucketOf: bucketOf2,
    StatusBadge: StatusBadge2,
    DirectionBadge: DirectionBadge2,
    MahnstufeBadge: MahnstufeBadge2,
    AgePill: AgePill2,
    AgingBar: AgingBar2,
    AgingStrip: AgingStrip2
  });

  // ../hausverwaltung/public/op_workflow/op-actions.jsx
  var { useState: useStateAct, useEffect: useEffectAct } = React;
  function primaryActionFor(row) {
    if (row.status === "Written Off")
      return null;
    if (row.art === "Rechnungen" && row.offen > 0) {
      return { key: "zahlung_anlegen", label: "Zahlung anlegen", kind: "primary" };
    }
    if (row.belegart === "Payment Entry") {
      return { key: "zuordnen", label: "Zuordnen", kind: "warn" };
    }
    if (row.art === "Forderungen" && row.belegart === "Sales Invoice" && row.offen < -0.01) {
      return { key: "guthaben_auszahlen", label: "Guthaben auszahlen", kind: "ghost" };
    }
    const isSalesInvoice = String(row.belegart || "").replace(/ \(×\d+\)$/, "") === "Sales Invoice";
    if (row.art === "Forderungen" && isSalesInvoice && row.offen > 0.01 && row.alter_tage > 0) {
      const nextStufe = (row.mahnstufe || 0) + 1;
      if (nextStufe <= 4) {
        return {
          key: "mahnwesen",
          label: "Mahnwesen",
          kind: nextStufe >= 2 ? "late" : "primary"
        };
      } else {
        return { key: "inkasso", label: "An Inkasso", kind: "late" };
      }
    }
    return null;
  }
  function ActionCell2({ row, onAction }) {
    const [menuOpen, setMenuOpen] = useStateAct(false);
    const primary = primaryActionFor(row);
    useEffectAct(() => {
      if (!menuOpen)
        return;
      const onClick = () => setMenuOpen(false);
      window.addEventListener("click", onClick);
      return () => window.removeEventListener("click", onClick);
    }, [menuOpen]);
    return /* @__PURE__ */ React.createElement("div", { className: "op-row-actions", onClick: (e) => e.stopPropagation() }, primary && /* @__PURE__ */ React.createElement(
      "button",
      {
        className: `op-action-btn is-${primary.kind}`,
        onClick: () => onAction(primary.key, row)
      },
      primary.label
    ), /* @__PURE__ */ React.createElement("div", { className: "op-action-wrap" }, /* @__PURE__ */ React.createElement("button", { className: "op-action-more", onClick: (e) => {
      e.stopPropagation();
      setMenuOpen((o) => !o);
    } }, "\u22EF"), menuOpen && /* @__PURE__ */ React.createElement("div", { className: "op-action-menu" }, /* @__PURE__ */ React.createElement("button", { className: "op-action-menu-item", onClick: () => onAction("mieterkonto", row) }, "\u2192 Mieterkonto \xF6ffnen", /* @__PURE__ */ React.createElement("span", { className: "op-action-menu-shortcut" }, "\u2197")), /* @__PURE__ */ React.createElement("button", { className: "op-action-menu-item", onClick: () => onAction("beleg", row) }, "\u2192 Beleg \xF6ffnen"), row.art === "Forderungen" && /* @__PURE__ */ React.createElement("button", { className: "op-action-menu-item", onClick: () => onAction("kontakt", row) }, "Mieter anrufen / mailen"), /* @__PURE__ */ React.createElement("div", { className: "op-action-menu-sep" }), /* @__PURE__ */ React.createElement("button", { className: "op-action-menu-item", onClick: () => onAction("notiz", row) }, "Notiz hinzuf\xFCgen"), /* @__PURE__ */ React.createElement("button", { className: "op-action-menu-item", onClick: () => onAction("stundung", row) }, "Stundung vereinbaren"), /* @__PURE__ */ React.createElement("button", { className: "op-action-menu-item", onClick: () => onAction("kl\xE4rung", row) }, 'Auf \u201Ein Kl\xE4rung" setzen'), /* @__PURE__ */ React.createElement("div", { className: "op-action-menu-sep" }), row.can_write_off && /* @__PURE__ */ React.createElement("button", { className: "op-action-menu-item is-danger", onClick: () => onAction("abschreiben", row) }, "Abschreiben\u2026"))));
  }
  function Modal({ title, subtitle, onClose, footer, children }) {
    useEffectAct(() => {
      const onKey = (e) => e.key === "Escape" && onClose();
      document.addEventListener("keydown", onKey);
      return () => document.removeEventListener("keydown", onKey);
    }, [onClose]);
    return /* @__PURE__ */ React.createElement("div", { className: "op-modal-backdrop", onClick: onClose }, /* @__PURE__ */ React.createElement("div", { className: "op-modal", onClick: (e) => e.stopPropagation() }, /* @__PURE__ */ React.createElement("div", { className: "op-modal-head" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h3", null, title), subtitle && /* @__PURE__ */ React.createElement("div", { className: "op-modal-sub" }, subtitle)), /* @__PURE__ */ React.createElement("button", { className: "op-modal-close", onClick: onClose }, "\xD7")), /* @__PURE__ */ React.createElement("div", { className: "op-modal-body" }, children), footer && /* @__PURE__ */ React.createElement("div", { className: "op-modal-foot" }, footer)));
  }
  function MahnungModal2({ row, onClose, onDone }) {
    const nextStufe = (row.mahnstufe || 0) + 1;
    const [mahngebuehr, setMahngebuehr] = useStateAct(nextStufe === 1 ? 0 : nextStufe === 2 ? 5 : nextStufe === 3 ? 10 : 15);
    const [zinsen, setZinsen] = useStateAct(true);
    const [zinssatz, setZinssatz] = useStateAct(9.12);
    const [versand, setVersand] = useStateAct("Brief");
    const [zusatztext, setZusatztext] = useStateAct("");
    const [busy, setBusy] = useStateAct(false);
    const [neueFaelligkeit, setNeueFaelligkeit] = useStateAct(() => {
      const d = /* @__PURE__ */ new Date();
      d.setDate(d.getDate() + 7);
      return d.toISOString().slice(0, 10);
    });
    const suggestedDunningType = row.dunning_type || (nextStufe === 1 ? "Zahlungserinnerung - HP" : nextStufe === 2 ? "1. Mahnung - HP" : nextStufe === 3 ? "2. Mahnung - HP" : "Letzte Mahnung - HP");
    const [dunningTypes, setDunningTypes] = useStateAct([]);
    const [textStufe, setTextStufe] = useStateAct(suggestedDunningType);
    const [vorlagen, setVorlagen] = useStateAct([]);
    const [serienbriefVorlage, setSerienbriefVorlage] = useStateAct(row.serienbrief_vorlage || "");
    useEffectAct(() => {
      let alive = true;
      Promise.all([
        window.OP_ACTIONS.listDunningTypes(),
        window.OP_ACTIONS.listSerienbriefVorlagen ? window.OP_ACTIONS.listSerienbriefVorlagen() : Promise.resolve([])
      ]).then(([items, templates]) => {
        if (!alive)
          return;
        setDunningTypes(items);
        if (items.length && !items.includes(textStufe))
          setTextStufe(items[0]);
        setVorlagen(templates || []);
      }).catch(() => {
      });
      return () => {
        alive = false;
      };
    }, []);
    const zinsBetrag = zinsen ? row.offen * (zinssatz / 100) * (row.alter_tage / 365) : 0;
    const summe = row.offen + mahngebuehr + zinsBetrag;
    const partyName = window.OFFENE_POSTEN.partyName(row.party);
    const objekt = window.OFFENE_POSTEN.ccLabel[row.kostenstelle] || row.kostenstelle;
    const submit = async () => {
      setBusy(true);
      try {
        const result = await window.OP_ACTIONS.createDunning(row, {
          dunningType: textStufe,
          neueFaelligkeit,
          mahngebuehr,
          zinsenAktiv: zinsen,
          serienbriefVorlage,
          serienbriefWerte: zusatztext.trim() ? [{ variable: "zusatztext", wert: zusatztext.trim(), beschreibung: "Optionaler Text aus dem Mahn-Cockpit" }] : []
        });
        onDone?.(result);
      } finally {
        setBusy(false);
      }
    };
    return /* @__PURE__ */ React.createElement(
      Modal,
      {
        title: `${nextStufe === 1 ? "Zahlungserinnerung" : nextStufe === 4 ? "Letzte Mahnung" : `${nextStufe - 1}. Mahnung`} erstellen`,
        subtitle: `${partyName} \xB7 ${row.belegnummer} \xB7 ${fmtEUR_op(row.offen)} offen seit ${row.alter_tage} Tagen`,
        onClose,
        footer: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "op-modal-foot-info" }, "Erzeugt 1 Dunning-Draft \xB7 Mahngeb\xFChr-Rechnung beim Submit \xB7 1 PDF"), /* @__PURE__ */ React.createElement("div", { className: "op-modal-foot-actions" }, /* @__PURE__ */ React.createElement("button", { className: "mk-btn", onClick: onClose, disabled: busy }, "Abbrechen"), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-primary", onClick: submit, disabled: busy }, busy ? "Draft wird angelegt \u2026" : `Mahnung als Draft anlegen \xB7 ${fmtEUR_op(summe)}`)))
      },
      /* @__PURE__ */ React.createElement("div", { className: "op-form-grid" }, /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Mahnstufe / Regel"), dunningTypes.length ? /* @__PURE__ */ React.createElement("select", { value: textStufe, onChange: (e) => setTextStufe(e.target.value) }, dunningTypes.map((name) => /* @__PURE__ */ React.createElement("option", { key: name, value: name }, name))) : /* @__PURE__ */ React.createElement("input", { value: textStufe, onChange: (e) => setTextStufe(e.target.value) }), dunningTypes.includes(suggestedDunningType) && textStufe !== suggestedDunningType && /* @__PURE__ */ React.createElement("button", { type: "button", className: "mk-btn mk-btn-ghost", style: { marginTop: 6, padding: "4px 8px", fontSize: 11 }, onClick: () => setTextStufe(suggestedDunningType) }, "Vorschlag w\xE4hlen")), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Serienbrief-Vorlage"), vorlagen.length ? /* @__PURE__ */ React.createElement("select", { value: serienbriefVorlage, onChange: (e) => setSerienbriefVorlage(e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "Default aus Mahnstufe"), vorlagen.map((name) => /* @__PURE__ */ React.createElement("option", { key: name, value: name }, name))) : /* @__PURE__ */ React.createElement("input", { value: serienbriefVorlage, placeholder: "Default aus Mahnstufe", onChange: (e) => setSerienbriefVorlage(e.target.value) })), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Versandart"), /* @__PURE__ */ React.createElement("select", { value: versand, onChange: (e) => setVersand(e.target.value) }, /* @__PURE__ */ React.createElement("option", null, "Brief"), /* @__PURE__ */ React.createElement("option", null, "E-Mail"), /* @__PURE__ */ React.createElement("option", null, "Brief + E-Mail"), /* @__PURE__ */ React.createElement("option", null, "Einschreiben"))), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Mahngeb\xFChr"), /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "number",
          step: "0.50",
          value: mahngebuehr,
          onChange: (e) => setMahngebuehr(parseFloat(e.target.value) || 0)
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Neue Zahlungsfrist"), /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "date",
          value: neueFaelligkeit,
          onChange: (e) => setNeueFaelligkeit(e.target.value)
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "op-field is-full" }, /* @__PURE__ */ React.createElement("label", null, "Optionaler Zusatztext"), /* @__PURE__ */ React.createElement(
        "textarea",
        {
          rows: "3",
          value: zusatztext,
          placeholder: "Wird als Variable {{ zusatztext }} an die Serienbrief-Vorlage \xFCbergeben.",
          onChange: (e) => setZusatztext(e.target.value)
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "op-field is-full" }, /* @__PURE__ */ React.createElement("label", { style: { display: "flex", alignItems: "center", gap: 6, cursor: "pointer" } }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: zinsen, onChange: (e) => setZinsen(e.target.checked) }), /* @__PURE__ */ React.createElement("span", null, "Verzugszinsen berechnen (", zinssatz, "% p.a. \xB7 \xA7288 BGB)")))),
      /* @__PURE__ */ React.createElement("div", { className: "op-preview" }, /* @__PURE__ */ React.createElement("div", { className: "op-preview-label" }, "Vorschau Forderung"), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "Offene Hauptforderung"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(row.offen))), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "+ Mahngeb\xFChr"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(mahngebuehr))), zinsen && /* @__PURE__ */ React.createElement("div", { className: "op-preview-row" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "+ Verzugszinsen (", row.alter_tage, " Tage)"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(zinsBetrag))), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row is-total" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "\u03A3 Zahlungsaufforderung"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(summe)))),
      /* @__PURE__ */ React.createElement("div", { className: "op-doc-letter" }, /* @__PURE__ */ React.createElement("div", { className: "op-doc-head" }, "Hausverwaltung M\xFCller GmbH \xB7 Hauptstr. 1 \xB7 70173 Stuttgart"), /* @__PURE__ */ React.createElement("h4", null, textStufe), /* @__PURE__ */ React.createElement("p", null, partyName, /* @__PURE__ */ React.createElement("br", null), "Objekt ", objekt), /* @__PURE__ */ React.createElement("p", null, "Sehr geehrte Damen und Herren,", /* @__PURE__ */ React.createElement("br", null), "wir bitten Sie h\xF6flich, den nachfolgend genannten Betrag bis sp\xE4testens", /* @__PURE__ */ React.createElement("strong", null, " ", fmtDate_op(neueFaelligkeit)), " auf unser Konto zu \xFCberweisen. Verwendungszweck: ", /* @__PURE__ */ React.createElement("strong", null, row.belegnummer)), /* @__PURE__ */ React.createElement("table", null, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", null, "Beleg"), /* @__PURE__ */ React.createElement("th", null, "F\xE4llig am"), /* @__PURE__ */ React.createElement("th", { className: "num" }, "Betrag"))), /* @__PURE__ */ React.createElement("tbody", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("td", null, row.belegnummer), /* @__PURE__ */ React.createElement("td", null, fmtDate_op(row.faellig_am)), /* @__PURE__ */ React.createElement("td", { className: "num" }, fmtEUR_op(summe)))))),
      /* @__PURE__ */ React.createElement("div", { className: "op-checklist" }, /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "Dunning-Doc gem\xE4\xDF ERPNext-Standard"), /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "Mahngeb\xFChr als verlinkte Sales Invoice beim Submit"), /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "PDF-Anhang automatisch erzeugt + im Mieter-Kontakt archiviert"), versand.includes("E-Mail") && /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "E-Mail-Versand vorbereitet (", partyName, ")"))
    );
  }
  function ZahlungModal2({ row, onClose, onDone }) {
    const skontoMatch = (row.bemerkungen || "").match(/Skonto bis (\d{2}\.\d{2}\.).*?(-?\d+(?:\.\d+)?)\s*%/i);
    const hasSkonto = !!skontoMatch;
    const skontoBis = skontoMatch ? skontoMatch[1] : null;
    const skontoSatz = skontoMatch ? parseFloat(skontoMatch[2]) : 0;
    const [nutzeSkonto, setNutzeSkonto] = useStateAct(hasSkonto);
    const [zahldatum, setZahldatum] = useStateAct(() => frappe.datetime.get_today());
    const [zahlart, setZahlart] = useStateAct("SEPA-\xDCberweisung");
    const [busy, setBusy] = useStateAct(false);
    const abzug = nutzeSkonto ? row.offen * (Math.abs(skontoSatz) / 100) : 0;
    const auszahlung = row.offen - abzug;
    const submit = async () => {
      setBusy(true);
      try {
        const result = await window.OP_ACTIONS.createPaymentEntry(row, {
          zahldatum,
          useSkonto: nutzeSkonto,
          skontoAmount: abzug,
          zahlart
        });
        onDone?.(result);
      } finally {
        setBusy(false);
      }
    };
    return /* @__PURE__ */ React.createElement(
      Modal,
      {
        title: "Zahlung an Lieferant anlegen",
        subtitle: `${window.OFFENE_POSTEN.partyName(row.party)} \xB7 ${row.belegnummer} \xB7 ${fmtEUR_op(row.offen)}`,
        onClose,
        footer: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "op-modal-foot-info" }, "Erzeugt 1 Payment Entry \xB7 ggf. 1 SEPA-XML"), /* @__PURE__ */ React.createElement("div", { className: "op-modal-foot-actions" }, /* @__PURE__ */ React.createElement("button", { className: "mk-btn", onClick: onClose, disabled: busy }, "Abbrechen"), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-primary", onClick: submit, disabled: busy }, busy ? "Draft wird angelegt \u2026" : `Zahlung als Draft anlegen \xB7 ${fmtEUR_op(auszahlung)}`)))
      },
      /* @__PURE__ */ React.createElement("div", { className: "op-form-grid" }, /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Zahldatum"), /* @__PURE__ */ React.createElement("input", { type: "date", value: zahldatum, onChange: (e) => setZahldatum(e.target.value) })), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Zahlart"), /* @__PURE__ */ React.createElement("select", { value: zahlart, onChange: (e) => setZahlart(e.target.value) }, /* @__PURE__ */ React.createElement("option", null, "SEPA-\xDCberweisung"), /* @__PURE__ */ React.createElement("option", null, "Lastschrift"), /* @__PURE__ */ React.createElement("option", null, "Manuelle \xDCberweisung"))), hasSkonto && /* @__PURE__ */ React.createElement("div", { className: "op-field is-full", style: { background: "oklch(0.97 0.04 80)", padding: 12, border: "1px solid oklch(0.85 0.06 70)", borderRadius: 4 } }, /* @__PURE__ */ React.createElement("label", { style: { display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "oklch(0.40 0.10 70)" } }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: nutzeSkonto, onChange: (e) => setNutzeSkonto(e.target.checked) }), /* @__PURE__ */ React.createElement("strong", null, "Skonto bis ", skontoBis, " nutzen (", Math.abs(skontoSatz), "%)")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--ink-3)", marginTop: 2 } }, "Spart ", fmtEUR_op(row.offen * (Math.abs(skontoSatz) / 100)), " bei dieser Rechnung."))),
      /* @__PURE__ */ React.createElement("div", { className: "op-preview" }, /* @__PURE__ */ React.createElement("div", { className: "op-preview-label" }, "Buchungs-Vorschau"), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "Rechnungsbetrag"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(row.offen))), nutzeSkonto && /* @__PURE__ */ React.createElement("div", { className: "op-preview-row" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "\u2212 Skonto ", Math.abs(skontoSatz), "%"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, "\u2212", fmtEUR_op(abzug))), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row is-total" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "Auszahlung"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(auszahlung)))),
      /* @__PURE__ */ React.createElement("div", { className: "op-checklist" }, /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "Payment Entry zu ", row.belegnummer), nutzeSkonto && /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "Skonto-Buchung auf 3736 (Aufwandsminderung)"), zahlart === "SEPA-\xDCberweisung" && /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "SEPA-XML zur n\xE4chsten Zahlungsdatei hinzugef\xFCgt"))
    );
  }
  function GuthabenAuszahlenModal2({ row, onClose, onDone }) {
    const [postingDate, setPostingDate] = useStateAct(() => frappe.datetime.get_today());
    const [modeOfPayment, setModeOfPayment] = useStateAct("Bank Draft");
    const [busy, setBusy] = useStateAct(false);
    const amount = Math.abs(row.offen || 0);
    const partyName = window.OFFENE_POSTEN.partyName(row.party);
    const submit = async () => {
      setBusy(true);
      try {
        const result = await window.OP_ACTIONS.createRefundPayment(row, {
          postingDate,
          modeOfPayment
        });
        onDone?.(result);
      } finally {
        setBusy(false);
      }
    };
    return /* @__PURE__ */ React.createElement(
      Modal,
      {
        title: "Guthaben auszahlen",
        subtitle: `${partyName} \xB7 ${row.belegnummer} \xB7 ${fmtEUR_op(amount)}`,
        onClose,
        footer: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "op-modal-foot-info" }, "Erzeugt einen Payment-Entry-Draft. Gebucht wird erst nach Submit im Desk."), /* @__PURE__ */ React.createElement("div", { className: "op-modal-foot-actions" }, /* @__PURE__ */ React.createElement("button", { className: "mk-btn", onClick: onClose, disabled: busy }, "Abbrechen"), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-primary", onClick: submit, disabled: busy }, busy ? "Draft wird angelegt \u2026" : `Auszahlung als Draft anlegen \xB7 ${fmtEUR_op(amount)}`)))
      },
      /* @__PURE__ */ React.createElement("div", { className: "op-form-grid" }, /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Auszahlungsdatum"), /* @__PURE__ */ React.createElement("input", { type: "date", value: postingDate, onChange: (e) => setPostingDate(e.target.value) })), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Zahlart"), /* @__PURE__ */ React.createElement("select", { value: modeOfPayment, onChange: (e) => setModeOfPayment(e.target.value) }, /* @__PURE__ */ React.createElement("option", null, "Bank Draft"), /* @__PURE__ */ React.createElement("option", null, "SEPA-\xDCberweisung"), /* @__PURE__ */ React.createElement("option", null, "Manuelle \xDCberweisung")))),
      /* @__PURE__ */ React.createElement("div", { className: "op-preview" }, /* @__PURE__ */ React.createElement("div", { className: "op-preview-label" }, "Auszahlungs-Vorschau"), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "Guthaben aus Beleg"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, row.belegnummer)), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row is-total" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "Auszahlung an Mieter"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(amount)))),
      /* @__PURE__ */ React.createElement("div", { className: "op-checklist" }, /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, 'Payment Entry Typ \u201EPay" gegen die Sales Invoice'), /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "Auszahlung wird mit dem negativen offenen Betrag verrechnet"), /* @__PURE__ */ React.createElement("div", { className: "op-checklist-item" }, "Bank-/Kassenkonto kann im Draft vor Submit gepr\xFCft werden"))
    );
  }
  function ZuordnenModal2({ row, onClose, onDone }) {
    const partyOpens = window.OFFENE_POSTEN.rows.filter((r) => r.party === row.party && r.offen > 0.01).sort((a, b) => a.faellig_am.localeCompare(b.faellig_am));
    const verfuegbar = Math.abs(row.offen);
    const [selected, setSelected] = useStateAct(() => new Set(partyOpens[0] ? [partyOpens[0].belegnummer] : []));
    const [busy, setBusy] = useStateAct(false);
    const sel = partyOpens.filter((p) => selected.has(p.belegnummer));
    const zugeordnet = sel.reduce((a, p) => a + Math.min(p.offen, verfuegbar - a), 0);
    const rest = verfuegbar - zugeordnet;
    const partyName = window.OFFENE_POSTEN.partyName(row.party);
    const toggle = (id) => {
      setSelected((prev) => {
        const next = new Set(prev);
        next.has(id) ? next.delete(id) : next.add(id);
        return next;
      });
    };
    const submit = async () => {
      let remaining = verfuegbar;
      const allocations = [];
      for (const item of sel) {
        if (remaining <= 0)
          break;
        const amount = Math.min(item.offen, remaining);
        allocations.push({ invoice: item.belegnummer, amount });
        remaining -= amount;
      }
      setBusy(true);
      try {
        const result = await window.OP_ACTIONS.allocatePayment(row, allocations);
        onDone?.(result);
      } finally {
        setBusy(false);
      }
    };
    return /* @__PURE__ */ React.createElement(
      Modal,
      {
        title: "Vorauszahlung zuordnen",
        subtitle: `${partyName} \xB7 Eingang ${fmtEUR_op(verfuegbar)} am ${fmtDate_op(row.buchungsdatum)}`,
        onClose,
        footer: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "op-modal-foot-info" }, "Rest ", fmtEUR_op(rest), " bleibt als Vorauszahlung stehen."), /* @__PURE__ */ React.createElement("div", { className: "op-modal-foot-actions" }, /* @__PURE__ */ React.createElement("button", { className: "mk-btn", onClick: onClose, disabled: busy }, "Abbrechen"), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-primary", onClick: submit, disabled: busy || sel.length === 0 }, busy ? "Draft wird angelegt \u2026" : `${sel.length} ${sel.length === 1 ? "Zuordnung vorbereiten" : "Zuordnungen vorbereiten"}`)))
      },
      partyOpens.length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { padding: 24, textAlign: "center", color: "var(--ink-3)" } }, "Keine offenen Forderungen bei ", partyName, ". Eingang als Anzahlung stehen lassen?") : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("p", { style: { margin: "0 0 12px", fontSize: 12.5, color: "var(--ink-2)" } }, "W\xE4hle die Forderungen, die mit dieser Vorauszahlung verrechnet werden sollen. \xC4ltester Posten ist vorausgew\xE4hlt."), /* @__PURE__ */ React.createElement("table", { style: { width: "100%", fontSize: 12.5, borderCollapse: "collapse" } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--bg-soft)", color: "var(--ink-3)", textTransform: "uppercase", fontSize: 10.5, letterSpacing: "0.04em" } }, /* @__PURE__ */ React.createElement("th", { style: { padding: "8px 10px", textAlign: "left" } }), /* @__PURE__ */ React.createElement("th", { style: { padding: "8px 10px", textAlign: "left" } }, "Beleg"), /* @__PURE__ */ React.createElement("th", { style: { padding: "8px 10px", textAlign: "left" } }, "F\xE4llig"), /* @__PURE__ */ React.createElement("th", { style: { padding: "8px 10px", textAlign: "right" } }, "Offen"))), /* @__PURE__ */ React.createElement("tbody", null, partyOpens.map((p) => /* @__PURE__ */ React.createElement("tr", { key: p.belegnummer, style: { borderBottom: "1px solid var(--line)" } }, /* @__PURE__ */ React.createElement("td", { style: { padding: "8px 10px" } }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "checkbox",
          checked: selected.has(p.belegnummer),
          onChange: () => toggle(p.belegnummer)
        }
      )), /* @__PURE__ */ React.createElement("td", { style: { padding: "8px 10px", fontFamily: "ui-monospace, monospace", fontSize: 11.5 } }, p.belegnummer), /* @__PURE__ */ React.createElement("td", { style: { padding: "8px 10px" } }, fmtDate_op(p.faellig_am)), /* @__PURE__ */ React.createElement("td", { style: { padding: "8px 10px", textAlign: "right", fontVariantNumeric: "tabular-nums" } }, fmtEUR_op(p.offen)))))), /* @__PURE__ */ React.createElement("div", { className: "op-preview", style: { marginTop: 14 } }, /* @__PURE__ */ React.createElement("div", { className: "op-preview-row" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "Verf\xFCgbar"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(verfuegbar))), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "Zugeordnet (", sel.length, " Beleg", sel.length === 1 ? "" : "e", ")"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, "\u2212", fmtEUR_op(zugeordnet))), /* @__PURE__ */ React.createElement("div", { className: "op-preview-row is-total" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "Rest als Vorauszahlung"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(rest)))))
    );
  }
  function Toast2({ message, onClose }) {
    useEffectAct(() => {
      const t = setTimeout(onClose, 2400);
      return () => clearTimeout(t);
    }, []);
    return /* @__PURE__ */ React.createElement("div", { style: {
      position: "fixed",
      bottom: 24,
      left: "50%",
      transform: "translateX(-50%)",
      background: "var(--ink)",
      color: "var(--bg)",
      padding: "10px 18px",
      borderRadius: 6,
      fontSize: 13,
      boxShadow: "0 8px 24px rgba(0,0,0,0.2)",
      zIndex: 200
    } }, message);
  }
  function SammelmahnungModal2({ rows, onClose, onDone }) {
    const groups = React.useMemo(() => {
      const map = /* @__PURE__ */ new Map();
      rows.forEach((r) => {
        if (!map.has(r.party))
          map.set(r.party, { party: r.party, items: [], sum: 0 });
        const g = map.get(r.party);
        g.items.push(r);
        g.sum += r.offen;
      });
      return [...map.values()].map((g) => ({
        ...g,
        name: window.OFFENE_POSTEN.partyName(g.party),
        nextStufe: Math.min(4, Math.max(...g.items.map((r) => (r.mahnstufe || 0) + 1))),
        gebuehr: g.items.reduce((sum, r) => {
          const stufe = Math.min(4, (r.mahnstufe || 0) + 1);
          return sum + (stufe === 1 ? 0 : stufe === 2 ? 5 : stufe === 3 ? 10 : 15);
        }, 0)
      })).sort((a, b) => b.sum - a.sum);
    }, [rows]);
    const [versand, setVersand] = useStateAct("Brief");
    const [zusatztext, setZusatztext] = useStateAct("");
    const [dunningTypes, setDunningTypes] = useStateAct([]);
    const [dunningType, setDunningType] = useStateAct(rows.find((r) => r.dunning_type)?.dunning_type || "");
    const [vorlagen, setVorlagen] = useStateAct([]);
    const [serienbriefVorlage, setSerienbriefVorlage] = useStateAct(rows.find((r) => r.serienbrief_vorlage)?.serienbrief_vorlage || "");
    const [neueFaelligkeit, setNeueFaelligkeit] = useStateAct(() => {
      const d = /* @__PURE__ */ new Date();
      d.setDate(d.getDate() + 7);
      return d.toISOString().slice(0, 10);
    });
    const [excluded, setExcluded] = useStateAct(() => /* @__PURE__ */ new Set());
    const [busy, setBusy] = useStateAct(false);
    const aktiv = groups.filter((g) => !excluded.has(g.party));
    const totalSum = aktiv.reduce((a, g) => a + g.sum + g.gebuehr, 0);
    useEffectAct(() => {
      let alive = true;
      Promise.all([
        window.OP_ACTIONS.listDunningTypes(),
        window.OP_ACTIONS.listSerienbriefVorlagen ? window.OP_ACTIONS.listSerienbriefVorlagen() : Promise.resolve([])
      ]).then(([items, templates]) => {
        if (!alive)
          return;
        setDunningTypes(items);
        if (items.length && !dunningType)
          setDunningType(items[0]);
        setVorlagen(templates || []);
      }).catch(() => {
      });
      return () => {
        alive = false;
      };
    }, []);
    const toggle = (p) => {
      setExcluded((prev) => {
        const next = new Set(prev);
        next.has(p) ? next.delete(p) : next.add(p);
        return next;
      });
    };
    const submit = async () => {
      const rowsByParty = {};
      aktiv.forEach((group) => {
        rowsByParty[group.party] = group.items;
      });
      setBusy(true);
      try {
        const serienbriefWerte = zusatztext.trim() ? [{ variable: "zusatztext", wert: zusatztext.trim(), beschreibung: "Optionaler Text aus dem Mahn-Cockpit" }] : [];
        const result = await window.OP_ACTIONS.createBulkDunning(rowsByParty, {
          neueFaelligkeit,
          dunningType,
          serienbriefVorlage,
          serienbriefWerte
        });
        onDone?.(result);
      } finally {
        setBusy(false);
      }
    };
    return /* @__PURE__ */ React.createElement(
      Modal,
      {
        title: "Sammelmahnung erstellen",
        subtitle: `${rows.length} Posten \xB7 ${groups.length} ${groups.length === 1 ? "Mieter" : "Mieter"} \xB7 ein Dunning-Doc pro Mieter`,
        onClose,
        footer: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "op-modal-foot-info" }, "Erzeugt ", aktiv.length, " Dunning-Doc", aktiv.length === 1 ? "" : "s", " \xB7 Mahngeb\xFChr-Rechnung beim Submit \xB7 ", aktiv.length, " PDF", aktiv.length === 1 ? "" : "s"), /* @__PURE__ */ React.createElement("div", { className: "op-modal-foot-actions" }, /* @__PURE__ */ React.createElement("button", { className: "mk-btn", onClick: onClose, disabled: busy }, "Abbrechen"), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-primary", disabled: busy || aktiv.length === 0, onClick: submit }, busy ? "Drafts werden angelegt \u2026" : `${aktiv.length} ${aktiv.length === 1 ? "Mahnung" : "Mahnungen"} als Draft anlegen \xB7 ${fmtEUR_op(totalSum)}`)))
      },
      /* @__PURE__ */ React.createElement("div", { className: "op-form-grid" }, /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Versandart (f\xFCr alle)"), /* @__PURE__ */ React.createElement("select", { value: versand, onChange: (e) => setVersand(e.target.value) }, /* @__PURE__ */ React.createElement("option", null, "Brief"), /* @__PURE__ */ React.createElement("option", null, "E-Mail"), /* @__PURE__ */ React.createElement("option", null, "Brief + E-Mail"), /* @__PURE__ */ React.createElement("option", null, "Einschreiben"))), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Mahnstufe / Regel (f\xFCr alle)"), dunningTypes.length ? /* @__PURE__ */ React.createElement("select", { value: dunningType, onChange: (e) => setDunningType(e.target.value) }, dunningTypes.map((name) => /* @__PURE__ */ React.createElement("option", { key: name, value: name }, name))) : /* @__PURE__ */ React.createElement("input", { value: dunningType, onChange: (e) => setDunningType(e.target.value), placeholder: "Automatisch" })), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Serienbrief-Vorlage"), vorlagen.length ? /* @__PURE__ */ React.createElement("select", { value: serienbriefVorlage, onChange: (e) => setSerienbriefVorlage(e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "Default aus Mahnstufe"), vorlagen.map((name) => /* @__PURE__ */ React.createElement("option", { key: name, value: name }, name))) : /* @__PURE__ */ React.createElement("input", { value: serienbriefVorlage, onChange: (e) => setSerienbriefVorlage(e.target.value), placeholder: "Default aus Mahnstufe" })), /* @__PURE__ */ React.createElement("div", { className: "op-field" }, /* @__PURE__ */ React.createElement("label", null, "Neue Zahlungsfrist"), /* @__PURE__ */ React.createElement("input", { type: "date", value: neueFaelligkeit, onChange: (e) => setNeueFaelligkeit(e.target.value) })), /* @__PURE__ */ React.createElement("div", { className: "op-field is-full" }, /* @__PURE__ */ React.createElement("label", null, "Optionaler Zusatztext"), /* @__PURE__ */ React.createElement(
        "textarea",
        {
          rows: "3",
          value: zusatztext,
          placeholder: "Wird als Variable {{ zusatztext }} an jede Serienbrief-Vorlage \xFCbergeben.",
          onChange: (e) => setZusatztext(e.target.value)
        }
      ))),
      /* @__PURE__ */ React.createElement("div", { className: "op-preview-label", style: { marginBottom: 8 } }, "Mahnungen pro Mieter"),
      /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, groups.map((g) => {
        const isOff = excluded.has(g.party);
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            key: g.party,
            style: {
              display: "grid",
              gridTemplateColumns: "24px 1fr auto 100px",
              gap: 12,
              alignItems: "center",
              padding: "10px 12px",
              background: isOff ? "var(--bg-soft)" : "var(--bg-card)",
              border: "1px solid var(--line)",
              borderRadius: 4,
              opacity: isOff ? 0.55 : 1,
              transition: "opacity 0.1s"
            }
          },
          /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !isOff, onChange: () => toggle(g.party) }),
          /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, fontSize: 13 } }, g.name), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11.5, color: "var(--ink-3)", marginTop: 2 } }, g.items.length, " ", g.items.length === 1 ? "Posten" : "Posten", " \xB7", " ", "\xC4lteste seit ", Math.max(...g.items.map((i) => i.alter_tage)), " Tagen")),
          /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11.5, color: "var(--ink-3)", textAlign: "center" } }, "Stufe", /* @__PURE__ */ React.createElement("br", null), /* @__PURE__ */ React.createElement("span", { style: { color: g.nextStufe >= 4 ? "var(--accent)" : "var(--ink)", fontWeight: 600, fontSize: 13 } }, "\u2192 ", g.nextStufe === 1 ? "ZE" : g.nextStufe === 4 ? "Letzte" : `M${g.nextStufe - 1}`)),
          /* @__PURE__ */ React.createElement("div", { style: { textAlign: "right", fontVariantNumeric: "tabular-nums" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13.5, fontWeight: 600 } }, fmtEUR_op(g.sum + g.gebuehr)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--ink-3)" } }, "inkl. ", fmtEUR_op(g.gebuehr), " Geb\xFChr"))
        );
      })),
      /* @__PURE__ */ React.createElement("div", { className: "op-preview", style: { marginTop: 14 } }, /* @__PURE__ */ React.createElement("div", { className: "op-preview-row is-total" }, /* @__PURE__ */ React.createElement("span", { className: "op-preview-key" }, "\u03A3 Sammelmahnung (", aktiv.length, " Schreiben)"), /* @__PURE__ */ React.createElement("span", { className: "op-preview-val" }, fmtEUR_op(totalSum))))
    );
  }
  Object.assign(window, {
    primaryActionFor,
    ActionCell: ActionCell2,
    Modal,
    MahnungModal: MahnungModal2,
    ZahlungModal: ZahlungModal2,
    GuthabenAuszahlenModal: GuthabenAuszahlenModal2,
    ZuordnenModal: ZuordnenModal2,
    SammelmahnungModal: SammelmahnungModal2,
    Toast: Toast2
  });

  // ../hausverwaltung/public/op_workflow/op-app.jsx
  var { useState: useStateA0, useMemo: useMemoA0, useEffect: useEffectA0 } = React;
  var OP_TWEAK_DEFAULTS = (
    /*EDITMODE-BEGIN*/
    {
      "layout": "flat",
      "showAktion": true,
      "density": "regular",
      "gruppierung": "keine",
      "showObjekt": true
    }
  );
  var MODE_LABEL = {
    "Forderungen": "Forderungen",
    "Rechnungen": "Rechnungen",
    "Beides": "Beides"
  };
  var MODE_SUB = {
    "Forderungen": "Mieter schulden uns",
    "Rechnungen": "Wir schulden Lieferanten",
    "Beides": "Bilanzielle Gesamtsicht"
  };
  function OpApp() {
    const [t, setTweak] = useTweaks(OP_TWEAK_DEFAULTS);
    const { partyName } = window.OFFENE_POSTEN;
    const [ALL_ROWS, setAllRows] = React.useState(window.OFFENE_POSTEN.rows);
    const [MAHN_ROWS, setMahnRows] = React.useState(window.OFFENE_POSTEN.mahnkandidaten || []);
    const [isLoading, setIsLoading] = React.useState(false);
    React.useEffect(() => {
      const onRefresh = () => {
        setAllRows([...window.OFFENE_POSTEN.rows]);
        setMahnRows([...window.OFFENE_POSTEN.mahnkandidaten || []]);
        setSelected(/* @__PURE__ */ new Set());
      };
      const onMahnRefresh = () => setMahnRows([...window.OFFENE_POSTEN.mahnkandidaten || []]);
      const onLoadStart = () => setIsLoading(true);
      const onLoadEnd = () => setIsLoading(false);
      window.addEventListener("op-data-refreshed", onRefresh);
      window.addEventListener("op-mahn-data-refreshed", onMahnRefresh);
      window.addEventListener("op-loading-start", onLoadStart);
      window.addEventListener("op-loading-end", onLoadEnd);
      return () => {
        window.removeEventListener("op-data-refreshed", onRefresh);
        window.removeEventListener("op-mahn-data-refreshed", onMahnRefresh);
        window.removeEventListener("op-loading-start", onLoadStart);
        window.removeEventListener("op-loading-end", onLoadEnd);
      };
    }, []);
    const [view, setView] = useStateA0(() => {
      const params = new URLSearchParams(window.location.search || "");
      return params.get("view") === "mahnwesen" || frappe.route_options?.view === "mahnwesen" ? "mahnwesen" : "op";
    });
    const [mode, setMode] = useStateA0("Forderungen");
    const [sortierung, setSortierung] = useStateA0("F\xE4llig am");
    const [sortDir, setSortDir] = useStateA0("asc");
    const [showSettled, setShowSettled] = useStateA0(false);
    const [showWrittenOff, setShowWrittenOff] = useStateA0(false);
    const [search, setSearch] = useStateA0("");
    const [activeChip, setActiveChip] = useStateA0(null);
    const [directionFilter, setDirectionFilter] = useStateA0("alle");
    const [partyFilter, setPartyFilter] = useStateA0("");
    const [partySearch, setPartySearch] = useStateA0("");
    const [selected, setSelected] = useStateA0(() => /* @__PURE__ */ new Set());
    const [immoFilter, setImmoFilter] = useStateA0(() => /* @__PURE__ */ new Set());
    const _initNow = /* @__PURE__ */ new Date();
    const _initPad = (n) => String(n).padStart(2, "0");
    const _initMonthStart = `${_initNow.getFullYear()}-${_initPad(_initNow.getMonth() + 1)}-01`;
    const _initMonthEnd = `${_initNow.getFullYear()}-${_initPad(_initNow.getMonth() + 1)}-${_initPad(new Date(_initNow.getFullYear(), _initNow.getMonth() + 1, 0).getDate())}`;
    const [datumVon, setDatumVon] = useStateA0(_initMonthStart);
    const [datumBis, setDatumBis] = useStateA0(_initMonthEnd);
    const _didInitRef = React.useRef(false);
    React.useEffect(() => {
      if (!_didInitRef.current) {
        _didInitRef.current = true;
        return;
      }
      const timer = setTimeout(() => {
        window.OP_ADAPTER.refresh({
          mode: "Beides",
          von_faelligkeit: datumVon,
          bis_faelligkeit: datumBis,
          show_settled: showSettled ? 1 : 0,
          show_written_off: showWrittenOff ? 1 : 0
        });
      }, 300);
      return () => clearTimeout(timer);
    }, [datumVon, datumBis, showSettled, showWrittenOff]);
    const [modal, setModal] = useStateA0(null);
    const [toast, setToast] = useStateA0(null);
    const [expandedMahnRows, setExpandedMahnRows] = useStateA0(() => /* @__PURE__ */ new Set());
    const mahnCandidateByInvoice = useMemoA0(() => {
      const map = /* @__PURE__ */ new Map();
      (MAHN_ROWS || []).forEach((candidate) => {
        (candidate.invoices || []).forEach((invoice) => {
          if (invoice.sales_invoice)
            map.set(invoice.sales_invoice, candidate);
        });
      });
      return map;
    }, [MAHN_ROWS]);
    const toggleMahnwesenForRow = (row) => {
      setExpandedMahnRows((prev) => {
        const next = new Set(prev);
        next.has(row.belegnummer) ? next.delete(row.belegnummer) : next.add(row.belegnummer);
        return next;
      });
      setSelected(/* @__PURE__ */ new Set());
    };
    const handleAction = async (key, row) => {
      try {
        if (key === "mahnwesen")
          toggleMahnwesenForRow(row);
        else if (key === "mahnung" || key === "sammelmahnung")
          setModal({ type: "mahnung", row });
        else if (key === "zahlung_anlegen")
          setModal({ type: "zahlung", row });
        else if (key === "zuordnen")
          setModal({ type: "zuordnen", row });
        else if (key === "guthaben_auszahlen")
          setModal({ type: "guthaben", row });
        else if (key === "mieterkonto") {
          window.OP_ACTIONS.openMieterkonto(row);
        } else if (key === "abschreiben") {
          const result = await window.OP_ACTIONS.writeOff(row, {
            remarks: `Abschreibung aus OP-Workflow vorbereitet: ${row.belegnummer}`
          });
          setToast(`Journal Entry Draft erstellt: ${result.journal_entry}`);
        } else if (key === "beleg")
          window.OP_ACTIONS.openBeleg(row);
        else if (key === "kontakt")
          setToast(`Kontakt: ${window.OFFENE_POSTEN.partyName(row.party)}`);
        else if (key === "notiz")
          setToast("Notiz-Dialog (mock)");
        else if (key === "stundung") {
          await window.OP_ACTIONS.setStundungComment(row, { grund: "Stundung im OP-Workflow markiert" });
          setToast(`Stundung dokumentiert: ${row.belegnummer}`);
        } else if (key === "kl\xE4rung")
          setToast(`Status: in Kl\xE4rung \u2192 ${row.belegnummer}`);
        else if (key === "inkasso")
          setToast(`Inkasso-Vorgang er\xF6ffnet: ${row.belegnummer}`);
        else
          setToast(`Aktion: ${key}`);
      } catch (err) {
        console.error("op action failed", err);
      }
    };
    const countsByMode = useMemoA0(() => {
      const cnt = { "Forderungen": 0, "Rechnungen": 0, "Beides": 0 };
      ALL_ROWS.forEach((r) => {
        if (Math.abs(r.offen) < 0.01)
          return;
        cnt[r.art] = (cnt[r.art] || 0) + 1;
        cnt["Beides"] += 1;
      });
      return cnt;
    }, [ALL_ROWS]);
    const modeRows = useMemoA0(() => {
      return ALL_ROWS.filter((r) => mode === "Beides" || r.art === mode);
    }, [mode, ALL_ROWS]);
    const mahnStats = useMemoA0(() => {
      const reif = modeRows.filter((r) => {
        if (r.status === "Written Off")
          return false;
        if (r.art !== "Forderungen")
          return false;
        if (r.belegart === "Payment Entry")
          return false;
        if (r.offen <= 0)
          return false;
        return r.alter_tage > 0 && (r.mahnstufe || 0) < 4;
      });
      const sum = reif.reduce((a, r) => a + r.offen, 0);
      const partySet = new Set(reif.map((r) => r.party));
      const byStufe = { m0: 0, m1: 0, m2: 0, m3: 0 };
      reif.forEach((r) => {
        byStufe[`m${r.mahnstufe || 0}`] = (byStufe[`m${r.mahnstufe || 0}`] || 0) + 1;
      });
      const mahnreifIds = new Set(reif.map((r) => r.belegnummer));
      return { count: reif.length, sum, parties: partySet.size, byStufe, rows: reif, mahnreifIds };
    }, [modeRows]);
    const availableImmos = useMemoA0(() => {
      const map = /* @__PURE__ */ new Map();
      modeRows.forEach((r) => {
        const cc = r.kostenstelle;
        if (!cc)
          return;
        if (!map.has(cc))
          map.set(cc, { cc, label: window.OFFENE_POSTEN.ccLabel[cc] || cc, count: 0 });
        map.get(cc).count += 1;
      });
      return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
    }, [modeRows]);
    const availableParties = useMemoA0(() => {
      const map = /* @__PURE__ */ new Map();
      modeRows.forEach((r) => {
        if (!r.party)
          return;
        if (!map.has(r.party)) {
          map.set(r.party, {
            id: r.party,
            label: partyName(r.party) || r.party,
            count: 0
          });
        }
        map.get(r.party).count += 1;
      });
      return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
    }, [modeRows, partyName]);
    const chipCounts = useMemoA0(() => ({
      overdue: modeRows.filter((r) => r.alter_tage > 0 && r.status !== "Written Off" && Math.abs(r.offen) > 0.01).length,
      mahnung: modeRows.filter((r) => r.mahnstufe && r.mahnstufe > 0).length,
      gt1000: modeRows.filter((r) => Math.abs(r.offen) >= 1e3).length,
      guthaben: modeRows.filter((r) => r.offen < -0.01).length
    }), [modeRows]);
    const filteredRows = useMemoA0(() => {
      let rows = modeRows;
      if (immoFilter.size > 0)
        rows = rows.filter((r) => immoFilter.has(r.kostenstelle));
      if (partyFilter)
        rows = rows.filter((r) => r.party === partyFilter);
      if (directionFilter !== "alle")
        rows = rows.filter((r) => r.zahlungsrichtung === directionFilter);
      if (datumVon)
        rows = rows.filter((r) => (r.faellig_am || "") >= datumVon);
      if (datumBis)
        rows = rows.filter((r) => (r.faellig_am || "") <= datumBis);
      if (!showSettled)
        rows = rows.filter((r) => Math.abs(r.offen) > 0.01);
      if (!showWrittenOff)
        rows = rows.filter((r) => r.status !== "Written Off");
      if (activeChip === "overdue")
        rows = rows.filter((r) => r.alter_tage > 0 && r.status !== "Written Off");
      if (activeChip === "mahnung")
        rows = rows.filter((r) => r.mahnstufe && r.mahnstufe > 0);
      if (activeChip === "gt1000")
        rows = rows.filter((r) => Math.abs(r.offen) >= 1e3);
      if (activeChip === "guthaben")
        rows = rows.filter((r) => r.offen < -0.01);
      if (search.trim()) {
        const q = search.toLowerCase();
        rows = rows.filter((r) => (partyName(r.party) || "").toLowerCase().includes(q) || (r.belegnummer || "").toLowerCase().includes(q) || (r.party || "").toLowerCase().includes(q) || (r.bemerkungen || "").toLowerCase().includes(q));
      }
      const cmp = (a, b) => {
        let r = 0;
        if (sortierung === "Offener Betrag absteigend")
          r = Math.abs(b.offen) - Math.abs(a.offen);
        else if (sortierung === "Offener Betrag")
          r = a.offen - b.offen;
        else if (sortierung === "Buchungsdatum")
          r = (a.buchungsdatum || "").localeCompare(b.buchungsdatum || "");
        else if (sortierung === "Mieter")
          r = (window.OFFENE_POSTEN.partyName(a.party) || "").localeCompare(window.OFFENE_POSTEN.partyName(b.party) || "");
        else if (sortierung === "Status")
          r = (a.status || "").localeCompare(b.status || "");
        else if (sortierung === "Richtung")
          r = (a.zahlungsrichtung || "").localeCompare(b.zahlungsrichtung || "");
        else if (sortierung === "Richtung: Geld bekommen zuerst")
          r = (a.zahlungsrichtung === "Geld bekommen" ? -1 : 1) - (b.zahlungsrichtung === "Geld bekommen" ? -1 : 1);
        else if (sortierung === "Richtung: Geld bezahlen zuerst")
          r = (a.zahlungsrichtung === "Geld bezahlen / erstatten" ? -1 : 1) - (b.zahlungsrichtung === "Geld bezahlen / erstatten" ? -1 : 1);
        else if (sortierung === "Immobilie") {
          const ka = window.OFFENE_POSTEN.ccLabel[a.kostenstelle] || a.kostenstelle || "";
          const kb = window.OFFENE_POSTEN.ccLabel[b.kostenstelle] || b.kostenstelle || "";
          r = ka.localeCompare(kb);
        } else if (sortierung === "\xC4lteste zuerst" || sortierung === "Alter")
          r = (b.alter_tage || 0) - (a.alter_tage || 0);
        else
          r = (a.faellig_am || "").localeCompare(b.faellig_am || "");
        if (r === 0)
          r = (a.faellig_am || "").localeCompare(b.faellig_am || "");
        if (r === 0)
          r = (a.belegnummer || "").localeCompare(b.belegnummer || "");
        return sortDir === "desc" ? -r : r;
      };
      const sorted = [...rows].sort(cmp);
      return sorted;
    }, [modeRows, immoFilter, partyFilter, directionFilter, datumVon, datumBis, showSettled, showWrittenOff, activeChip, search, sortierung, sortDir]);
    const stats = useMemoA0(() => {
      const positiveOpen = filteredRows.filter((r) => r.offen > 0 && r.status !== "Written Off");
      const summe = positiveOpen.reduce((a, r) => a + r.offen, 0);
      const ueberfaellig = positiveOpen.filter((r) => r.alter_tage > 0).reduce((a, r) => a + r.offen, 0);
      const guthabenSum = filteredRows.filter((r) => r.offen < -0.01).reduce((a, r) => a + Math.abs(r.offen), 0);
      const parties = new Set(positiveOpen.map((r) => r.party));
      const oldest = positiveOpen.reduce((max, r) => Math.max(max, r.alter_tage || 0), 0);
      const buckets = { b0: 0, b1: 0, b2: 0, b3: 0, b4: 0 };
      positiveOpen.forEach((r) => {
        const b = bucketOf(r.alter_tage);
        if (b)
          buckets[b.key] += r.offen;
      });
      return { summe, ueberfaellig, guthabenSum, parties: parties.size, oldest, buckets };
    }, [filteredRows]);
    const selectableIds = useMemoA0(() => new Set(filteredRows.filter((r) => r.can_write_off).map((r) => r.belegnummer)), [filteredRows]);
    const selectedRows = useMemoA0(() => filteredRows.filter((r) => selected.has(r.belegnummer)), [filteredRows, selected]);
    React.useEffect(() => {
      const visibleIds = new Set(filteredRows.map((r) => r.belegnummer));
      setSelected((prev) => {
        const next = new Set([...prev].filter((id) => visibleIds.has(id)));
        return next.size === prev.size ? prev : next;
      });
    }, [filteredRows]);
    const selectedSum = selectedRows.reduce((a, r) => a + r.offen, 0);
    const toggleSel = (id) => {
      setSelected((prev) => {
        const next = new Set(prev);
        next.has(id) ? next.delete(id) : next.add(id);
        return next;
      });
    };
    const toggleSelAll = () => {
      if (selected.size === selectableIds.size)
        setSelected(/* @__PURE__ */ new Set());
      else
        setSelected(new Set(selectableIds));
    };
    const exportCsv = () => {
      const cols = [
        ["faellig_am", "F\xE4llig am"],
        ["alter_tage", "Alter Tage"],
        ["party", mode === "Rechnungen" ? "Lieferant" : "Mieter"],
        ["kostenstelle", "Immobilie/Kostenstelle"],
        ["belegart", "Belegart"],
        ["belegnummer", "Belegnummer"],
        ["bemerkungen", "Bemerkungen"],
        ["status", "Status"],
        ["rechnungsbetrag", "Rechnungsbetrag"],
        ["bezahlt", "Bezahlt"],
        ["offen", "Offen"],
        ["zahlungsrichtung", "Zahlungsrichtung"]
      ];
      const esc = (value) => {
        const text = value == null ? "" : String(value);
        return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
      };
      const csv = [
        cols.map(([, label]) => esc(label)).join(";"),
        ...filteredRows.map((row) => cols.map(([key]) => esc(row[key])).join(";"))
      ].join("\n");
      const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `offene-posten-${mode.toLowerCase()}-${(/* @__PURE__ */ new Date()).toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    };
    const openBulkDunning = (rows) => {
      const candidates = rows.filter(
        (r) => r.art === "Forderungen" && r.belegart === "Sales Invoice" && r.offen > 0.01 && r.alter_tage > 0 && r.status !== "Written Off"
      );
      if (!candidates.length) {
        setToast("Keine mahnf\xE4higen Forderungen in der Auswahl.");
        return;
      }
      setSelected(new Set(candidates.map((r) => r.belegnummer)));
      setModal({ type: "sammelmahnung", rows: candidates });
    };
    const openCandidateDunning = (candidate) => {
      const rows = (candidate.invoices || []).map((invoice) => ({
        art: "Forderungen",
        party_type: "Customer",
        party: candidate.customer,
        buchungsdatum: invoice.posting_date,
        faellig_am: invoice.due_date,
        belegart: "Sales Invoice",
        belegnummer: invoice.sales_invoice,
        rechnungsbetrag: invoice.grand_total,
        bezahlt: Math.max((invoice.grand_total || 0) - (invoice.outstanding_amount || 0), 0),
        offen: invoice.outstanding_amount,
        party_account: null,
        kostenstelle: invoice.cost_center,
        bemerkungen: invoice.remarks || invoice.mietabrechnung_id || "",
        status: invoice.status,
        zahlungsrichtung: "Geld bekommen",
        alter_tage: candidate.oldest_age_days || 0,
        can_write_off: true,
        mahnstufe: Math.max((candidate.next_level || 1) - 1, 0),
        dunning_type: candidate.next_dunning_type || "",
        serienbrief_vorlage: candidate.serienbrief_vorlage || ""
      }));
      if (!rows.length) {
        setToast("Keine offenen Rechnungen f\xFCr diese Mahnung.");
        return;
      }
      setModal({
        type: rows.length === 1 ? "mahnung" : "sammelmahnung",
        row: rows[0],
        rows
      });
    };
    const openCandidatesBulkDunning = (candidates) => {
      const rows = candidates.flatMap((candidate) => (candidate.invoices || []).map((invoice) => ({
        art: "Forderungen",
        party_type: "Customer",
        party: candidate.customer,
        buchungsdatum: invoice.posting_date,
        faellig_am: invoice.due_date,
        belegart: "Sales Invoice",
        belegnummer: invoice.sales_invoice,
        rechnungsbetrag: invoice.grand_total,
        bezahlt: Math.max((invoice.grand_total || 0) - (invoice.outstanding_amount || 0), 0),
        offen: invoice.outstanding_amount,
        party_account: null,
        kostenstelle: invoice.cost_center,
        bemerkungen: invoice.remarks || invoice.mietabrechnung_id || "",
        status: invoice.status,
        zahlungsrichtung: "Geld bekommen",
        alter_tage: candidate.oldest_age_days || 0,
        can_write_off: true,
        mahnstufe: Math.max((candidate.next_level || 1) - 1, 0),
        dunning_type: candidate.next_dunning_type || "",
        serienbrief_vorlage: candidate.serienbrief_vorlage || ""
      })));
      if (!rows.length) {
        setToast("Keine offenen Rechnungen f\xFCr eine Sammelmahnung.");
        return;
      }
      setModal({ type: "sammelmahnung", rows });
    };
    const writeOffSelected = async () => {
      const candidates = selectedRows.filter((r) => r.can_write_off);
      if (!candidates.length) {
        setToast("Keine abschreibbaren Sales-Invoice-Forderungen ausgew\xE4hlt.");
        return;
      }
      for (const row of candidates) {
        await window.OP_ACTIONS.writeOff(row, {
          remarks: `Abschreibung aus OP-Workflow vorbereitet: ${row.belegnummer}`
        });
      }
      setSelected(/* @__PURE__ */ new Set());
      setToast(`${candidates.length} Abschreibungs-Draft${candidates.length === 1 ? "" : "s"} erstellt.`);
    };
    const grouped = useMemoA0(() => {
      if (t.gruppierung === "keine")
        return null;
      const keyFn = t.gruppierung === "objekt" ? (r) => r.kostenstelle || "\u2014" : (r) => r.party;
      const labelFn = t.gruppierung === "objekt" ? (k) => window.OFFENE_POSTEN.ccLabel[k] || k : (k) => partyName(k);
      const map = /* @__PURE__ */ new Map();
      filteredRows.forEach((r) => {
        const k = keyFn(r);
        if (!map.has(k))
          map.set(k, []);
        map.get(k).push(r);
      });
      return [...map.entries()].map(([key, rows]) => {
        const sum = rows.reduce((a, r) => a + r.offen, 0);
        const overdue = rows.reduce((a, r) => a + (r.alter_tage > 0 ? r.offen : 0), 0);
        const buckets = { b0: 0, b1: 0, b2: 0, b3: 0, b4: 0 };
        rows.forEach((r) => {
          if (r.offen > 0) {
            const b = bucketOf(r.alter_tage);
            if (b)
              buckets[b.key] += r.offen;
          }
        });
        const maxAge = rows.reduce((m, r) => Math.max(m, r.alter_tage || 0), 0);
        const maxMahn = rows.reduce((m, r) => Math.max(m, r.mahnstufe || 0), 0);
        const partySet = new Set(rows.map((r) => r.party));
        return {
          key,
          label: labelFn(key),
          subLabel: t.gruppierung === "objekt" ? `${partySet.size} ${partySet.size === 1 ? "Mieter" : "Mieter"} \xB7 ${rows.length} ${rows.length === 1 ? "Posten" : "Posten"}` : `${key} \xB7 ${rows.length} ${rows.length === 1 ? "Posten" : "Posten"}`,
          rows,
          sum,
          overdue,
          buckets,
          maxAge,
          maxMahn
        };
      }).sort((a, b) => b.sum - a.sum);
    }, [filteredRows, t.gruppierung]);
    return /* @__PURE__ */ React.createElement("div", { className: "mk-app" }, /* @__PURE__ */ React.createElement("div", { className: "mk-topbar", "data-screen-label": "Topbar" }, /* @__PURE__ */ React.createElement("div", { className: "mk-topbar-left" }, /* @__PURE__ */ React.createElement("h1", null, "Noch offene Rechnungen und Forderungen", isLoading && /* @__PURE__ */ React.createElement("span", { style: { display: "inline-block", marginLeft: 10, width: 14, height: 14, border: "2px solid #ccc", borderTopColor: "#666", borderRadius: "50%", animation: "op-spin 0.8s linear infinite", verticalAlign: "middle" } })), /* @__PURE__ */ React.createElement("span", { className: "mk-crumb" }, "Hausverwaltung \xB7 Berichte")), /* @__PURE__ */ React.createElement("div", { className: "mk-topbar-actions" }, /* @__PURE__ */ React.createElement("a", { className: "mk-btn mk-btn-ghost", href: "/app/mieterkonto-workflow" }, "\u2190 Mieterkonto"), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-ghost", onClick: () => window.print() }, "Drucken"), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-ghost", onClick: exportCsv }, "Export CSV"), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-primary", onClick: () => openBulkDunning(mahnStats.rows) }, "Sammelmahnung"))), /* @__PURE__ */ React.createElement("main", { className: "mk-main", "data-screen-label": `Mode ${mode}` }, /* @__PURE__ */ React.createElement("div", { className: "op-view-tabs" }, /* @__PURE__ */ React.createElement("button", { className: `op-view-tab ${view === "op" ? "is-active" : ""}`, onClick: () => setView("op") }, "Offene Posten"), /* @__PURE__ */ React.createElement("button", { className: `op-view-tab ${view === "mahnwesen" ? "is-active" : ""}`, onClick: () => setView("mahnwesen") }, "Mahnwesen ", /* @__PURE__ */ React.createElement("span", { className: "op-count" }, MAHN_ROWS.length))), view === "op" && /* @__PURE__ */ React.createElement("div", { className: "op-mode-bar" }, /* @__PURE__ */ React.createElement("div", { className: "op-mode-tabs" }, ["Forderungen", "Rechnungen", "Beides"].map((m) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: m,
        className: `op-mode-tab ${mode === m ? "is-active" : ""}`,
        onClick: () => {
          setMode(m);
          setSelected(/* @__PURE__ */ new Set());
          setActiveChip(null);
          setPartyFilter("");
          setPartySearch("");
        }
      },
      /* @__PURE__ */ React.createElement("span", null, MODE_LABEL[m]),
      /* @__PURE__ */ React.createElement("span", { className: "op-count" }, countsByMode[m])
    ))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--ink-3)", textAlign: "right" } }, /* @__PURE__ */ React.createElement("div", null, MODE_SUB[mode]), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 2 } }, "Stichtag: ", fmtDate_op(window.OFFENE_POSTEN.TODAY)))), view === "mahnwesen" ? /* @__PURE__ */ React.createElement(
      MahnwesenView,
      {
        rows: MAHN_ROWS,
        search,
        setSearch,
        onCreateDunning: openCandidateDunning,
        onCreateBulkDunning: openCandidatesBulkDunning
      }
    ) : /* @__PURE__ */ React.createElement(React.Fragment, null, mahnStats.count > 0 && mode !== "Rechnungen" && /* @__PURE__ */ React.createElement("div", { className: "op-mahn-banner" }, /* @__PURE__ */ React.createElement("span", { className: "op-mahn-badge" }, mahnStats.count), /* @__PURE__ */ React.createElement("span", { className: "op-mahn-banner-headline" }, mahnStats.count, " Posten ", /* @__PURE__ */ React.createElement("strong", null, "mahnreif")), /* @__PURE__ */ React.createElement("span", { className: "op-mahn-banner-meta" }, "bei ", /* @__PURE__ */ React.createElement("strong", null, mahnStats.parties), " ", mahnStats.parties === 1 ? "Mieter" : "Mietern", " \xB7 \u03A3 ", /* @__PURE__ */ React.createElement("strong", null, fmtEUR_op(mahnStats.sum))), /* @__PURE__ */ React.createElement("span", { className: "op-mahn-stufes" }, mahnStats.byStufe.m0 > 0 && /* @__PURE__ */ React.createElement("span", null, "\u2192 ZE ", /* @__PURE__ */ React.createElement("strong", null, mahnStats.byStufe.m0)), mahnStats.byStufe.m1 > 0 && /* @__PURE__ */ React.createElement("span", null, "\u2192 M1 ", /* @__PURE__ */ React.createElement("strong", null, mahnStats.byStufe.m1)), mahnStats.byStufe.m2 > 0 && /* @__PURE__ */ React.createElement("span", null, "\u2192 M2 ", /* @__PURE__ */ React.createElement("strong", null, mahnStats.byStufe.m2)), mahnStats.byStufe.m3 > 0 && /* @__PURE__ */ React.createElement("span", null, "\u2192 Letzte ", /* @__PURE__ */ React.createElement("strong", null, mahnStats.byStufe.m3))), /* @__PURE__ */ React.createElement("span", { className: "op-mahn-banner-spacer" }), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "op-mahn-banner-secondary",
        onClick: () => setActiveChip(activeChip === "overdue" ? null : "overdue")
      },
      activeChip === "overdue" ? "Filter zur\xFCcksetzen" : "Nur diese zeigen"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "op-mahn-banner-cta",
        onClick: () => {
          setSelected(new Set(mahnStats.rows.map((r) => r.belegnummer)));
          setModal({ type: "sammelmahnung", rows: mahnStats.rows });
        }
      },
      "Sammelmahnung erstellen \u2192"
    )), /* @__PURE__ */ React.createElement("div", { className: "op-stats" }, /* @__PURE__ */ React.createElement("div", { className: `op-stat is-primary` }, /* @__PURE__ */ React.createElement("div", { className: "op-stat-label" }, "Offen gesamt"), /* @__PURE__ */ React.createElement("div", { className: "op-stat-value" }, fmtEUR_op(stats.summe)), /* @__PURE__ */ React.createElement("div", { className: "op-stat-sub" }, filteredRows.filter((r) => r.offen > 0 && r.status !== "Written Off").length, " Posten \xB7", " ", stats.parties, " ", mode === "Rechnungen" ? "Lieferanten" : "Mieter")), /* @__PURE__ */ React.createElement("div", { className: "op-stat" }, /* @__PURE__ */ React.createElement("div", { className: "op-stat-label" }, "davon \xFCberf\xE4llig"), /* @__PURE__ */ React.createElement("div", { className: "op-stat-value", style: { color: "var(--accent)" } }, fmtEUR_op(stats.ueberfaellig)), /* @__PURE__ */ React.createElement("div", { className: "op-stat-sub" }, (stats.ueberfaellig / Math.max(stats.summe, 1) * 100).toFixed(0), " % des Offen-Saldos")), /* @__PURE__ */ React.createElement("div", { className: "op-stat" }, /* @__PURE__ */ React.createElement("div", { className: "op-stat-label" }, "\xC4lteste Forderung"), /* @__PURE__ */ React.createElement("div", { className: "op-stat-value" }, stats.oldest, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14, color: "var(--ink-3)", marginLeft: 4 } }, "Tage"))), /* @__PURE__ */ React.createElement("div", { className: "op-stat" }, /* @__PURE__ */ React.createElement("div", { className: "op-stat-label" }, "Guthaben (auszuzahlen)"), /* @__PURE__ */ React.createElement("div", { className: "op-stat-value" }, stats.guthabenSum > 0 ? fmtEUR_op(stats.guthabenSum) : "\u2014")), /* @__PURE__ */ React.createElement("div", { className: "op-aging-strip" }, /* @__PURE__ */ React.createElement("div", { className: "op-stat-label" }, "Aging nach F\xE4lligkeit"), /* @__PURE__ */ React.createElement(AgingStrip, { buckets: stats.buckets }))), /* @__PURE__ */ React.createElement(
      FilterRow,
      {
        availableImmos,
        immoFilter,
        setImmoFilter,
        datumVon,
        datumBis,
        setDatumVon,
        setDatumBis
      }
    ), /* @__PURE__ */ React.createElement("div", { className: "op-toolbar" }, /* @__PURE__ */ React.createElement("div", { className: "op-chips" }, /* @__PURE__ */ React.createElement("button", { className: `op-chip ${activeChip === null ? "is-active" : ""}`, onClick: () => setActiveChip(null) }, "Alle ", /* @__PURE__ */ React.createElement("span", { className: "op-chip-count" }, filteredRows.length)), /* @__PURE__ */ React.createElement("button", { className: `op-chip ${activeChip === "overdue" ? "is-active" : ""}`, onClick: () => setActiveChip(activeChip === "overdue" ? null : "overdue") }, "\xDCberf\xE4llig ", /* @__PURE__ */ React.createElement("span", { className: "op-chip-count" }, chipCounts.overdue)), /* @__PURE__ */ React.createElement("button", { className: `op-chip ${activeChip === "mahnung" ? "is-active" : ""}`, onClick: () => setActiveChip(activeChip === "mahnung" ? null : "mahnung") }, "Im Mahnlauf ", /* @__PURE__ */ React.createElement("span", { className: "op-chip-count" }, chipCounts.mahnung)), /* @__PURE__ */ React.createElement("button", { className: `op-chip ${activeChip === "gt1000" ? "is-active" : ""}`, onClick: () => setActiveChip(activeChip === "gt1000" ? null : "gt1000") }, "\u2265 1.000 \u20AC ", /* @__PURE__ */ React.createElement("span", { className: "op-chip-count" }, chipCounts.gt1000)), /* @__PURE__ */ React.createElement("button", { className: `op-chip ${activeChip === "guthaben" ? "is-active" : ""}`, onClick: () => setActiveChip(activeChip === "guthaben" ? null : "guthaben") }, "Guthaben ", /* @__PURE__ */ React.createElement("span", { className: "op-chip-count" }, chipCounts.guthaben)), /* @__PURE__ */ React.createElement("span", { className: "op-chip-separator" }), /* @__PURE__ */ React.createElement("button", { className: `op-chip ${directionFilter === "alle" ? "is-active" : ""}`, onClick: () => setDirectionFilter("alle") }, "Alle Richtungen"), /* @__PURE__ */ React.createElement("button", { className: `op-chip ${directionFilter === "Geld bekommen" ? "is-active" : ""}`, onClick: () => setDirectionFilter("Geld bekommen") }, "Geld bekommen"), /* @__PURE__ */ React.createElement("button", { className: `op-chip ${directionFilter === "Geld bezahlen / erstatten" ? "is-active" : ""}`, onClick: () => setDirectionFilter("Geld bezahlen / erstatten") }, "Geld zahlen"), /* @__PURE__ */ React.createElement("label", { className: "mk-toggle", style: { marginLeft: 10 } }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: showWrittenOff, onChange: (e) => setShowWrittenOff(e.target.checked) }), "Abgeschriebene"), /* @__PURE__ */ React.createElement("label", { className: "mk-toggle" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: showSettled, onChange: (e) => setShowSettled(e.target.checked) }), "Auch ausgeglichene")), /* @__PURE__ */ React.createElement("div", { className: "op-toolbar-right" }, /* @__PURE__ */ React.createElement(
      PartyPicker,
      {
        value: partyFilter,
        searchText: partySearch,
        parties: availableParties,
        mode,
        onSearchChange: setPartySearch,
        onChange: (partyId) => {
          setPartyFilter(partyId);
          setSelected(/* @__PURE__ */ new Set());
        }
      }
    ), /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "op-search",
        placeholder: "Beleg oder Bemerkung suchen\u2026",
        value: search,
        onChange: (e) => setSearch(e.target.value)
      }
    ), /* @__PURE__ */ React.createElement("select", { className: "op-sort-select", value: sortierung, onChange: (e) => {
      setSortierung(e.target.value);
      setSortDir("asc");
    } }, /* @__PURE__ */ React.createElement("option", null, "F\xE4llig am"), /* @__PURE__ */ React.createElement("option", null, "Buchungsdatum"), /* @__PURE__ */ React.createElement("option", null, "\xC4lteste zuerst"), /* @__PURE__ */ React.createElement("option", null, "Offener Betrag absteigend"), /* @__PURE__ */ React.createElement("option", null, "Mieter"), /* @__PURE__ */ React.createElement("option", null, "Immobilie"), /* @__PURE__ */ React.createElement("option", null, "Status"), /* @__PURE__ */ React.createElement("option", null, "Richtung"), /* @__PURE__ */ React.createElement("option", null, "Richtung: Geld bekommen zuerst"), /* @__PURE__ */ React.createElement("option", null, "Richtung: Geld bezahlen zuerst")), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "mk-btn mk-btn-ghost",
        title: "Richtung umkehren",
        onClick: () => setSortDir(sortDir === "asc" ? "desc" : "asc"),
        style: { padding: "5px 10px", fontSize: 12 }
      },
      sortDir === "asc" ? "\u2191 aufst." : "\u2193 abst."
    ))), selected.size > 0 && /* @__PURE__ */ React.createElement("div", { className: "op-bulkbar" }, /* @__PURE__ */ React.createElement("div", { className: "op-bulkbar-left" }, /* @__PURE__ */ React.createElement("span", { className: "op-bulkbar-count" }, selected.size, " ausgew\xE4hlt"), /* @__PURE__ */ React.createElement("span", { className: "op-bulkbar-sep" }), /* @__PURE__ */ React.createElement("span", { className: "op-bulkbar-sum" }, "\u03A3 offen: ", /* @__PURE__ */ React.createElement("strong", null, fmtEUR_op(selectedSum)))), /* @__PURE__ */ React.createElement("div", { className: "op-bulkbar-actions" }, /* @__PURE__ */ React.createElement("button", { className: "op-bulk-btn", onClick: () => setSelected(/* @__PURE__ */ new Set()) }, "Auswahl aufheben"), /* @__PURE__ */ React.createElement("button", { className: "op-bulk-btn", onClick: () => openBulkDunning(selectedRows) }, "Mahnung erstellen"), /* @__PURE__ */ React.createElement("button", { className: "op-bulk-btn is-primary", onClick: writeOffSelected }, "Ausgew\xE4hlte abschreiben"))), filteredRows.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "op-empty" }, /* @__PURE__ */ React.createElement("strong", null, "Keine offenen Posten in dieser Auswahl."), 'Filter \xE4ndern oder \u201EAuch ausgeglichene anzeigen" aktivieren.') : t.gruppierung !== "keine" ? /* @__PURE__ */ React.createElement(
      GroupedView,
      {
        groups: grouped,
        selected,
        toggleSel,
        selectableIds,
        mode,
        gruppierung: t.gruppierung,
        showObjekt: t.showObjekt,
        onAction: handleAction,
        mahnCandidateByInvoice,
        expandedMahnRows,
        onCreateDunning: openCandidateDunning
      }
    ) : /* @__PURE__ */ React.createElement(
      FlatTable,
      {
        rows: filteredRows,
        selected,
        toggleSel,
        selectableIds,
        toggleSelAll,
        mode,
        showAktion: t.showAktion,
        showObjekt: t.showObjekt,
        sortierung,
        sortDir,
        onSort: (col) => {
          if (sortierung === col)
            setSortDir(sortDir === "asc" ? "desc" : "asc");
          else {
            setSortierung(col);
            setSortDir("asc");
          }
        },
        onAction: handleAction,
        mahnreifIds: mahnStats.mahnreifIds,
        mahnCandidateByInvoice,
        expandedMahnRows,
        onCreateDunning: openCandidateDunning
      }
    ), /* @__PURE__ */ React.createElement("div", { className: "op-footer-total" }, /* @__PURE__ */ React.createElement("div", { className: "op-footer-total-label" }, "\u03A3 ", filteredRows.length, " Posten in Auswahl"), /* @__PURE__ */ React.createElement("div", { className: "op-footer-total-value" }, fmtEUR_op(filteredRows.reduce((a, r) => a + r.offen, 0)))))), /* @__PURE__ */ React.createElement(TweaksPanel, { title: "Tweaks" }, /* @__PURE__ */ React.createElement(TweakSection, { label: "Gruppierung" }), /* @__PURE__ */ React.createElement(
      TweakRadio,
      {
        label: "Gruppiert nach",
        value: t.gruppierung,
        options: ["keine", "mieter", "objekt"],
        onChange: (v) => setTweak("gruppierung", v)
      }
    ), /* @__PURE__ */ React.createElement("p", { style: { margin: "0 0 4px", fontSize: 10.5, color: "rgba(41,38,27,.55)", lineHeight: 1.4 } }, "Mieter \xB7 pro Partei \xB7 Objekt \xB7 pro Immobilie"), /* @__PURE__ */ React.createElement(TweakSection, { label: "Layout" }), /* @__PURE__ */ React.createElement(
      TweakRadio,
      {
        label: "Dichte",
        value: t.density,
        options: ["compact", "regular", "comfy"],
        onChange: (v) => setTweak("density", v)
      }
    ), /* @__PURE__ */ React.createElement(TweakSection, { label: "Spalten" }), /* @__PURE__ */ React.createElement(
      TweakToggle,
      {
        label: "Immobilie anzeigen",
        value: t.showObjekt,
        onChange: (v) => setTweak("showObjekt", v)
      }
    ), /* @__PURE__ */ React.createElement(
      TweakToggle,
      {
        label: "Aktion-Spalte (Abschreiben)",
        value: t.showAktion,
        onChange: (v) => setTweak("showAktion", v)
      }
    )), modal?.type === "mahnung" && /* @__PURE__ */ React.createElement(MahnungModal, { row: modal.row, onClose: () => setModal(null), onDone: (result) => {
      setModal(null);
      setToast(`Mahnung-Draft erstellt: ${result.dunning}`);
    } }), modal?.type === "sammelmahnung" && /* @__PURE__ */ React.createElement(SammelmahnungModal, { rows: modal.rows, onClose: () => setModal(null), onDone: (result) => {
      setModal(null);
      setToast(`${(result.created || []).length} Mahnung-Drafts erstellt`);
    } }), modal?.type === "zahlung" && /* @__PURE__ */ React.createElement(ZahlungModal, { row: modal.row, onClose: () => setModal(null), onDone: (result) => {
      setModal(null);
      setToast(`Payment Entry Draft erstellt: ${result.payment_entry}`);
    } }), modal?.type === "guthaben" && /* @__PURE__ */ React.createElement(GuthabenAuszahlenModal, { row: modal.row, onClose: () => setModal(null), onDone: (result) => {
      setModal(null);
      setToast(`Auszahlungs-Draft erstellt: ${result.payment_entry}`);
    } }), modal?.type === "zuordnen" && /* @__PURE__ */ React.createElement(ZuordnenModal, { row: modal.row, onClose: () => setModal(null), onDone: (result) => {
      setModal(null);
      setToast(`Payment Reconciliation Draft erstellt: ${result.payment_reconciliation}`);
    } }), toast && /* @__PURE__ */ React.createElement(Toast, { message: toast, onClose: () => setToast(null) }));
  }
  function partyPickerLabel(party) {
    if (!party)
      return "";
    return party.label && party.label !== party.id ? `${party.label} (${party.id})` : party.id;
  }
  function PartyPicker({ value, searchText, parties, mode, onSearchChange, onChange }) {
    const [open, setOpen] = useStateA0(false);
    const rootRef = React.useRef(null);
    const selected = parties.find((party) => party.id === value);
    const roleLabel = mode === "Rechnungen" ? "Lieferant" : mode === "Beides" ? "Partei" : "Mieter";
    const q = (searchText || "").trim().toLowerCase();
    const visibleParties = useMemoA0(() => {
      if (!q)
        return parties.slice(0, 80);
      return parties.filter(
        (party) => (party.label || "").toLowerCase().includes(q) || (party.id || "").toLowerCase().includes(q)
      ).slice(0, 80);
    }, [parties, q]);
    useEffectA0(() => {
      const onPointerDown = (event) => {
        if (!rootRef.current || rootRef.current.contains(event.target))
          return;
        setOpen(false);
      };
      window.addEventListener("pointerdown", onPointerDown);
      return () => window.removeEventListener("pointerdown", onPointerDown);
    }, []);
    const choose = (party) => {
      onSearchChange(party ? partyPickerLabel(party) : "");
      onChange(party?.id || "");
      setOpen(false);
    };
    return /* @__PURE__ */ React.createElement("div", { className: "op-party-picker", ref: rootRef }, /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "op-party-search",
        type: "search",
        value: searchText,
        placeholder: selected ? partyPickerLabel(selected) : `${roleLabel} suchen`,
        onFocus: (e) => {
          e.target.select();
          setOpen(true);
        },
        onChange: (e) => {
          onSearchChange(e.target.value);
          setOpen(true);
        }
      }
    ), value && /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "op-party-clear",
        "aria-label": `${roleLabel}auswahl l\xF6schen`,
        onClick: () => choose(null)
      },
      "\xD7"
    ), open && /* @__PURE__ */ React.createElement("div", { className: "op-party-menu" }, visibleParties.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "op-party-empty" }, "Keine Treffer") : visibleParties.map((party) => /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        key: party.id,
        className: `op-party-option ${value === party.id ? "is-selected" : ""}`,
        onClick: () => choose(party)
      },
      /* @__PURE__ */ React.createElement("span", { className: "op-party-option-title" }, partyPickerLabel(party)),
      /* @__PURE__ */ React.createElement("span", { className: "op-party-option-meta" }, party.count, " ", party.count === 1 ? "Posten" : "Posten")
    ))));
  }
  function MahnwesenView({ rows, search, setSearch, onCreateDunning, onCreateBulkDunning }) {
    const [openSet, setOpenSet] = useStateA0(() => /* @__PURE__ */ new Set());
    const filtered = useMemoA0(() => {
      const q = (search || "").trim().toLowerCase();
      if (!q)
        return rows;
      return rows.filter(
        (row) => (row.customer_name || "").toLowerCase().includes(q) || (row.customer || "").toLowerCase().includes(q) || (row.mietvertrag || "").toLowerCase().includes(q) || (row.wohnung || "").toLowerCase().includes(q) || (row.serienbrief_vorlage || "").toLowerCase().includes(q) || (row.invoices || []).some(
          (invoice) => (invoice.sales_invoice || "").toLowerCase().includes(q) || (invoice.remarks || "").toLowerCase().includes(q) || (invoice.mietabrechnung_id || "").toLowerCase().includes(q)
        ) || (row.mahnungen || []).some(
          (mahnung) => (mahnung.name || "").toLowerCase().includes(q) || (mahnung.dunning_type || "").toLowerCase().includes(q)
        )
      );
    }, [rows, search]);
    const total = filtered.reduce((sum, row) => sum + (row.offen || 0), 0);
    const toggle = (key) => {
      setOpenSet((prev) => {
        const next = new Set(prev);
        next.has(key) ? next.delete(key) : next.add(key);
        return next;
      });
    };
    return /* @__PURE__ */ React.createElement("div", { className: "op-mahn-cockpit" }, /* @__PURE__ */ React.createElement("div", { className: "op-mahn-head" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h2", null, "Mahnwesen"), /* @__PURE__ */ React.createElement("div", { className: "op-mahn-head-sub" }, filtered.length, " Kandidaten \xB7 ", fmtEUR_op(total), " offen \xB7 Stichtag ", fmtDate_op(window.OFFENE_POSTEN.TODAY))), /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "op-search",
        placeholder: "Mieter, Beleg, Wohnung, Vertrag oder Vorlage suchen...",
        value: search,
        onChange: (e) => setSearch(e.target.value)
      }
    ), /* @__PURE__ */ React.createElement("button", { className: "mk-btn mk-btn-primary", onClick: () => onCreateBulkDunning(filtered), disabled: !filtered.length }, "Sammelmahnung erstellen")), filtered.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "op-empty" }, /* @__PURE__ */ React.createElement("strong", null, "Keine Mahnkandidaten."), "Es gibt aktuell keine \xFCberf\xE4lligen offenen Sales Invoices in dieser Auswahl.") : /* @__PURE__ */ React.createElement("div", { className: "op-mahn-table-wrap" }, /* @__PURE__ */ React.createElement("table", { className: "op-table op-mahn-table" }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: { width: 34 } }), /* @__PURE__ */ React.createElement("th", null, "Mieter"), /* @__PURE__ */ React.createElement("th", null, "Wohnung"), /* @__PURE__ */ React.createElement("th", null, "Mietvertrag"), /* @__PURE__ */ React.createElement("th", { className: "is-num" }, "Offen"), /* @__PURE__ */ React.createElement("th", null, "\xC4lteste F\xE4lligkeit"), /* @__PURE__ */ React.createElement("th", null, "Letzte Mahnung"), /* @__PURE__ */ React.createElement("th", null, "N\xE4chste Stufe"), /* @__PURE__ */ React.createElement("th", null, "Serienbrief-Vorlage"), /* @__PURE__ */ React.createElement("th", { style: { width: 170 } }, "Aktionen"))), /* @__PURE__ */ React.createElement("tbody", null, filtered.map((row) => {
      const open = openSet.has(row.key);
      const last = (row.mahnungen || [])[0];
      const drafts = (row.mahnungen || []).filter((mahnung) => mahnung.docstatus === 0);
      const draft = drafts[0];
      return /* @__PURE__ */ React.createElement(React.Fragment, { key: row.key }, /* @__PURE__ */ React.createElement("tr", { className: row.draft_warning ? "is-mahn-draft" : "" }, /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("button", { className: "op-row-toggle", onClick: () => toggle(row.key) }, open ? "\u25BE" : "\u25B8")), /* @__PURE__ */ React.createElement("td", { className: "col-party" }, row.customer_name || row.customer, /* @__PURE__ */ React.createElement("span", { className: "op-party-id" }, row.customer)), /* @__PURE__ */ React.createElement("td", null, row.wohnung || "\u2014"), /* @__PURE__ */ React.createElement("td", null, row.mietvertrag || "\u2014"), /* @__PURE__ */ React.createElement("td", { className: "is-num col-offen" }, fmtEUR_op(row.offen)), /* @__PURE__ */ React.createElement("td", null, fmtDate_op(row.oldest_due_date), /* @__PURE__ */ React.createElement("span", { className: "op-party-id" }, row.oldest_age_days || 0, " Tage")), /* @__PURE__ */ React.createElement("td", null, last ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", null, last.dunning_type || last.name, last.docstatus === 0 && /* @__PURE__ */ React.createElement("span", { className: "op-draft-badge" }, "Draft"), drafts.length > 1 && /* @__PURE__ */ React.createElement("span", { className: "op-draft-badge is-multiple" }, drafts.length, " Drafts")), /* @__PURE__ */ React.createElement("span", { className: "op-party-id" }, fmtDate_op(last.posting_date), " \xB7 ", last.status)) : "\u2014"), /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement(MahnstufeBadge, { stufe: row.next_level })), /* @__PURE__ */ React.createElement("td", null, row.serienbrief_vorlage || /* @__PURE__ */ React.createElement("span", { className: "op-muted" }, "Default fehlt")), /* @__PURE__ */ React.createElement("td", { className: "op-mahn-actions" }, drafts.length > 1 ? /* @__PURE__ */ React.createElement("button", { className: "op-action-btn is-draft", onClick: () => toggle(row.key) }, "Drafts pr\xFCfen") : draft ? /* @__PURE__ */ React.createElement("button", { className: "op-action-btn is-draft", onClick: () => window.OP_ACTIONS.openDunning(draft.name) }, "Draft \xF6ffnen") : /* @__PURE__ */ React.createElement("button", { className: "op-action-btn is-primary", onClick: () => onCreateDunning(row) }, "Mahnung erstellen"))), open && /* @__PURE__ */ React.createElement("tr", { className: "op-mahn-detail-row" }, /* @__PURE__ */ React.createElement("td", null), /* @__PURE__ */ React.createElement("td", { colSpan: "9" }, /* @__PURE__ */ React.createElement("div", { className: "op-mahn-detail" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "op-preview-label" }, "Offene Rechnungen"), /* @__PURE__ */ React.createElement("table", { className: "op-mini-table" }, /* @__PURE__ */ React.createElement("tbody", null, (row.invoices || []).map((invoice) => /* @__PURE__ */ React.createElement("tr", { key: invoice.sales_invoice }, /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("button", { className: "op-link-btn", onClick: () => window.OP_ACTIONS.openBeleg({ belegart: "Sales Invoice", belegnummer: invoice.sales_invoice }) }, invoice.sales_invoice)), /* @__PURE__ */ React.createElement("td", null, fmtDate_op(invoice.due_date)), /* @__PURE__ */ React.createElement("td", { className: "is-num" }, fmtEUR_op(invoice.outstanding_amount)), /* @__PURE__ */ React.createElement("td", null, invoice.status)))))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "op-preview-label" }, "Mahnhistorie", drafts.length > 1 && /* @__PURE__ */ React.createElement("span", { className: "op-draft-note" }, "Mehrere offene Drafts. Bitte einen finalisieren oder alte Drafts l\xF6schen.")), (row.mahnungen || []).length ? /* @__PURE__ */ React.createElement("table", { className: "op-mini-table" }, /* @__PURE__ */ React.createElement("tbody", null, row.mahnungen.map((mahnung) => /* @__PURE__ */ React.createElement("tr", { key: mahnung.name }, /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("button", { className: "op-link-btn", onClick: () => window.OP_ACTIONS.openDunning(mahnung.name) }, mahnung.name)), /* @__PURE__ */ React.createElement("td", null, mahnung.docstatus === 0 ? /* @__PURE__ */ React.createElement("span", { className: "op-draft-badge" }, "Draft") : mahnung.status), /* @__PURE__ */ React.createElement("td", null, mahnung.dunning_type || "\u2014"), /* @__PURE__ */ React.createElement("td", null, mahnung.serienbrief_vorlage || "\u2014"), /* @__PURE__ */ React.createElement("td", null, mahnung.fee_sales_invoice ? /* @__PURE__ */ React.createElement("button", { className: "op-link-btn", onClick: () => window.OP_ACTIONS.openBeleg({ belegart: "Sales Invoice", belegnummer: mahnung.fee_sales_invoice }) }, "Geb\xFChr") : "\u2014"), /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("button", { className: "op-link-btn", onClick: () => window.OP_ACTIONS.openDunningPdf(mahnung.name) }, "PDF")))))) : /* @__PURE__ */ React.createElement("div", { className: "op-muted" }, "Noch keine Mahnung zu diesen offenen Rechnungen."))))));
    })))));
  }
  function MahnInlineDetail({ candidate, row, onCreateDunning }) {
    if (!candidate) {
      return /* @__PURE__ */ React.createElement("div", { className: "op-mahn-inline" }, /* @__PURE__ */ React.createElement("div", { className: "op-muted" }, "F\xFCr ", row.belegnummer, " wurde kein Mahnwesen-Datensatz gefunden."));
    }
    const mahnungen = candidate.mahnungen || [];
    const drafts = mahnungen.filter((mahnung) => mahnung.docstatus === 0);
    const draft = drafts[0];
    return /* @__PURE__ */ React.createElement("div", { className: "op-mahn-inline" }, /* @__PURE__ */ React.createElement("div", { className: "op-mahn-inline-head" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, candidate.customer_name || candidate.customer), /* @__PURE__ */ React.createElement("span", null, candidate.wohnung || "\u2014", " \xB7 ", candidate.mietvertrag || "\u2014", " \xB7 ", fmtEUR_op(candidate.offen), " offen")), drafts.length > 1 ? /* @__PURE__ */ React.createElement("button", { className: "op-action-btn is-draft", onClick: () => window.OP_ACTIONS.openDunning(draft.name) }, "Ersten Draft \xF6ffnen") : draft ? /* @__PURE__ */ React.createElement("button", { className: "op-action-btn is-draft", onClick: () => window.OP_ACTIONS.openDunning(draft.name) }, "Draft \xF6ffnen") : /* @__PURE__ */ React.createElement("button", { className: "op-action-btn is-primary", onClick: () => onCreateDunning(candidate) }, "Mahnung erstellen")), drafts.length > 1 && /* @__PURE__ */ React.createElement("div", { className: "op-draft-note" }, "Mehrere offene Drafts. Bitte einen finalisieren oder alte Drafts l\xF6schen."), /* @__PURE__ */ React.createElement("div", { className: "op-mahn-detail" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "op-preview-label" }, "Offene Rechnungen"), /* @__PURE__ */ React.createElement("table", { className: "op-mini-table" }, /* @__PURE__ */ React.createElement("tbody", null, (candidate.invoices || []).map((invoice) => /* @__PURE__ */ React.createElement("tr", { key: invoice.sales_invoice }, /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("button", { className: "op-link-btn", onClick: () => window.OP_ACTIONS.openBeleg({ belegart: "Sales Invoice", belegnummer: invoice.sales_invoice }) }, invoice.sales_invoice)), /* @__PURE__ */ React.createElement("td", null, fmtDate_op(invoice.due_date)), /* @__PURE__ */ React.createElement("td", { className: "is-num" }, fmtEUR_op(invoice.outstanding_amount)), /* @__PURE__ */ React.createElement("td", null, invoice.status)))))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "op-preview-label" }, "Mahnhistorie"), mahnungen.length ? /* @__PURE__ */ React.createElement("table", { className: "op-mini-table" }, /* @__PURE__ */ React.createElement("tbody", null, mahnungen.map((mahnung) => /* @__PURE__ */ React.createElement("tr", { key: mahnung.name }, /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("button", { className: "op-link-btn", onClick: () => window.OP_ACTIONS.openDunning(mahnung.name) }, mahnung.name)), /* @__PURE__ */ React.createElement("td", null, mahnung.docstatus === 0 ? /* @__PURE__ */ React.createElement("span", { className: "op-draft-badge" }, "Draft") : mahnung.status), /* @__PURE__ */ React.createElement("td", null, mahnung.dunning_type || "\u2014"), /* @__PURE__ */ React.createElement("td", null, mahnung.serienbrief_vorlage || "\u2014"), /* @__PURE__ */ React.createElement("td", null, mahnung.fee_sales_invoice ? /* @__PURE__ */ React.createElement("button", { className: "op-link-btn", onClick: () => window.OP_ACTIONS.openBeleg({ belegart: "Sales Invoice", belegnummer: mahnung.fee_sales_invoice }) }, "Geb\xFChr") : "\u2014"), /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("button", { className: "op-link-btn", onClick: () => window.OP_ACTIONS.openDunningPdf(mahnung.name) }, "PDF")))))) : /* @__PURE__ */ React.createElement("div", { className: "op-muted" }, "Noch keine Mahnung zu diesen offenen Rechnungen."))));
  }
  function FlatTable({
    rows,
    selected,
    toggleSel,
    selectableIds,
    toggleSelAll,
    mode,
    showAktion,
    showObjekt,
    sortierung,
    sortDir,
    onSort,
    onAction,
    mahnreifIds,
    mahnCandidateByInvoice,
    expandedMahnRows,
    onCreateDunning
  }) {
    const allChecked = selectableIds.size > 0 && selected.size === selectableIds.size;
    const someChecked = selected.size > 0 && !allChecked;
    const SortableTh = ({ col, label, style, className = "" }) => {
      const active = sortierung === col;
      const ind = active ? sortDir === "asc" ? "\u25B2" : "\u25BC" : "\u25C7";
      return /* @__PURE__ */ React.createElement(
        "th",
        {
          style,
          className: `is-sortable ${active ? "is-sorted" : ""} ${className}`,
          onClick: () => onSort(col),
          title: `Nach ${label} sortieren`
        },
        label,
        /* @__PURE__ */ React.createElement("span", { className: "op-sort-ind" }, ind)
      );
    };
    return /* @__PURE__ */ React.createElement("div", { className: "op-table-wrap" }, /* @__PURE__ */ React.createElement("table", { className: "op-table" }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { className: "is-check" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "checkbox",
        checked: allChecked,
        ref: (el) => el && (el.indeterminate = someChecked),
        onChange: toggleSelAll,
        disabled: selectableIds.size === 0
      }
    )), /* @__PURE__ */ React.createElement(SortableTh, { col: "F\xE4llig am", label: "F\xE4llig am", style: { width: 100 } }), /* @__PURE__ */ React.createElement(SortableTh, { col: "Alter", label: "Alter", style: { width: 80 } }), /* @__PURE__ */ React.createElement(SortableTh, { col: "Mieter", label: mode === "Rechnungen" ? "Lieferant" : "Mieter", style: { minWidth: 200 } }), showObjekt && /* @__PURE__ */ React.createElement(SortableTh, { col: "Immobilie", label: "Immobilie", style: { width: 140 } }), /* @__PURE__ */ React.createElement("th", { style: { width: 170 } }, "Beleg"), /* @__PURE__ */ React.createElement("th", null, "Bemerkung"), /* @__PURE__ */ React.createElement(SortableTh, { col: "Status", label: "Status", style: { width: 120 } }), /* @__PURE__ */ React.createElement(SortableTh, { col: "Richtung", label: "Richtung", style: { width: 130 } }), /* @__PURE__ */ React.createElement("th", { className: "is-num", style: { width: 120 } }, "Rechnungsbetrag"), /* @__PURE__ */ React.createElement("th", { className: "is-num", style: { width: 100 } }, "Bezahlt"), /* @__PURE__ */ React.createElement(SortableTh, { col: "Offener Betrag absteigend", label: "Offen", style: { width: 130 }, className: "is-num" }), showAktion && /* @__PURE__ */ React.createElement("th", { style: { width: 200 } }, "Aktion"))), /* @__PURE__ */ React.createElement("tbody", null, rows.map((r) => {
      const sel = selected.has(r.belegnummer);
      const isNeg = r.offen < -0.01;
      const writtenOff = r.status === "Written Off";
      const mahnreif = mahnreifIds && mahnreifIds.has(r.belegnummer);
      const mahnOpen = expandedMahnRows?.has(r.belegnummer);
      const mahnCandidate = mahnCandidateByInvoice?.get(r.belegnummer);
      const detailColspan = 11 + (showObjekt ? 1 : 0) + (showAktion ? 1 : 0);
      return /* @__PURE__ */ React.createElement(React.Fragment, { key: r.belegnummer + r.party }, /* @__PURE__ */ React.createElement("tr", { className: `${sel ? "is-selected" : ""} ${writtenOff ? "is-written-off" : ""} ${mahnreif ? "is-mahnreif" : ""} ${mahnOpen ? "is-mahn-open" : ""}` }, /* @__PURE__ */ React.createElement("td", { className: "col-check" }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "checkbox",
          checked: sel,
          disabled: !r.can_write_off,
          onChange: () => toggleSel(r.belegnummer)
        }
      )), /* @__PURE__ */ React.createElement("td", { className: "col-date" }, fmtDate_op(r.faellig_am)), /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement(AgePill, { age: r.alter_tage, faellig_am: r.faellig_am })), /* @__PURE__ */ React.createElement("td", { className: "col-party" }, window.OFFENE_POSTEN.partyName(r.party), /* @__PURE__ */ React.createElement("span", { className: "op-party-id" }, r.party)), showObjekt && /* @__PURE__ */ React.createElement("td", { style: { fontSize: 12.5, color: "var(--ink-2)" } }, window.OFFENE_POSTEN.ccLabel[r.kostenstelle] || r.kostenstelle || "\u2014"), /* @__PURE__ */ React.createElement("td", { className: "col-beleg" }, /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "op-link-btn op-beleg-link",
          onClick: () => window.OP_ACTIONS.openBeleg(r),
          title: `${r.belegart} ${r.belegnummer} \xF6ffnen`
        },
        r.belegnummer
      ), /* @__PURE__ */ React.createElement("span", { className: "op-beleg-art" }, r.belegart)), /* @__PURE__ */ React.createElement("td", { className: "col-bemerk" }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", null, r.bemerkungen), r.mahnstufe ? /* @__PURE__ */ React.createElement(MahnstufeBadge, { stufe: r.mahnstufe }) : null)), /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement(StatusBadge, { status: r.status })), /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement(DirectionBadge, { direction: r.zahlungsrichtung })), /* @__PURE__ */ React.createElement("td", { className: "is-num" }, fmtEUR_op(r.rechnungsbetrag)), /* @__PURE__ */ React.createElement("td", { className: "is-num", style: { color: "var(--ink-3)" } }, r.bezahlt > 0.01 ? fmtEUR_op(r.bezahlt) : "\u2014"), /* @__PURE__ */ React.createElement("td", { className: `is-num col-offen ${isNeg ? "is-negative" : ""}` }, fmtEUR_op(r.offen)), showAktion && /* @__PURE__ */ React.createElement("td", { style: { position: "relative", textAlign: "right" } }, /* @__PURE__ */ React.createElement(ActionCell, { row: r, onAction }))), mahnOpen && /* @__PURE__ */ React.createElement("tr", { className: "op-mahn-inline-row" }, /* @__PURE__ */ React.createElement("td", { colSpan: detailColspan }, /* @__PURE__ */ React.createElement(MahnInlineDetail, { candidate: mahnCandidate, row: r, onCreateDunning }))));
    }))));
  }
  function GroupedView({
    groups,
    selected,
    toggleSel,
    selectableIds,
    mode,
    gruppierung,
    showObjekt,
    onAction,
    mahnCandidateByInvoice,
    expandedMahnRows,
    onCreateDunning
  }) {
    const [openSet, setOpenSet] = useStateA0(() => new Set(groups.map((g) => g.key)));
    const toggle = (p) => {
      setOpenSet((prev) => {
        const next = new Set(prev);
        next.has(p) ? next.delete(p) : next.add(p);
        return next;
      });
    };
    return /* @__PURE__ */ React.createElement("div", null, groups.map((g) => {
      const open = openSet.has(g.key);
      return /* @__PURE__ */ React.createElement("div", { key: g.key, className: `op-group ${open ? "is-open" : ""}` }, /* @__PURE__ */ React.createElement("div", { className: "op-group-head", onClick: () => toggle(g.key) }, /* @__PURE__ */ React.createElement("span", { className: "op-group-chevron" }, "\u25B6"), /* @__PURE__ */ React.createElement("div", { className: "op-group-party" }, /* @__PURE__ */ React.createElement("span", { className: "op-group-party-name" }, gruppierung === "objekt" && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--ink-3)", fontWeight: 400, marginRight: 6 } }, "\u{1F3E0}"), g.label), /* @__PURE__ */ React.createElement("span", { className: "op-group-party-id" }, g.subLabel)), /* @__PURE__ */ React.createElement("div", { className: "op-group-aging" }, /* @__PURE__ */ React.createElement(AgingBar, { buckets: g.buckets, mini: true })), /* @__PURE__ */ React.createElement("div", { className: "op-group-stat" }, "\xC4ltester", /* @__PURE__ */ React.createElement("strong", null, g.maxAge, " d")), /* @__PURE__ */ React.createElement("div", { className: "op-group-stat" }, "Mahnstufe", /* @__PURE__ */ React.createElement("strong", null, g.maxMahn || "\u2014")), /* @__PURE__ */ React.createElement("div", { className: `op-group-stat ${g.overdue > 0.01 ? "is-overdue" : ""}` }, "\u03A3 Offen", /* @__PURE__ */ React.createElement("strong", null, fmtEUR_op(g.sum)))), open && /* @__PURE__ */ React.createElement("div", { className: "op-group-body" }, /* @__PURE__ */ React.createElement("table", { className: "op-table" }, /* @__PURE__ */ React.createElement("tbody", null, g.rows.map((r) => {
        const sel = selected.has(r.belegnummer);
        const isNeg = r.offen < -0.01;
        const writtenOff = r.status === "Written Off";
        const mahnOpen = expandedMahnRows?.has(r.belegnummer);
        const mahnCandidate = mahnCandidateByInvoice?.get(r.belegnummer);
        const detailColspan = 8 + (gruppierung !== "objekt" && showObjekt ? 1 : 0) + (gruppierung === "objekt" ? 1 : 0);
        return /* @__PURE__ */ React.createElement(React.Fragment, { key: r.belegnummer }, /* @__PURE__ */ React.createElement("tr", { className: `${sel ? "is-selected" : ""} ${writtenOff ? "is-written-off" : ""} ${mahnOpen ? "is-mahn-open" : ""}` }, /* @__PURE__ */ React.createElement("td", { className: "col-check", style: { width: 32 } }, /* @__PURE__ */ React.createElement(
          "input",
          {
            type: "checkbox",
            checked: sel,
            disabled: !r.can_write_off,
            onChange: () => toggleSel(r.belegnummer)
          }
        )), /* @__PURE__ */ React.createElement("td", { className: "col-date", style: { width: 100 } }, fmtDate_op(r.faellig_am)), /* @__PURE__ */ React.createElement("td", { style: { width: 80 } }, /* @__PURE__ */ React.createElement(AgePill, { age: r.alter_tage, faellig_am: r.faellig_am })), /* @__PURE__ */ React.createElement("td", { className: "col-beleg", style: { width: 170 } }, /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "op-link-btn op-beleg-link",
            onClick: () => window.OP_ACTIONS.openBeleg(r),
            title: `${r.belegart} ${r.belegnummer} \xF6ffnen`
          },
          r.belegnummer
        ), /* @__PURE__ */ React.createElement("span", { className: "op-beleg-art" }, r.belegart)), gruppierung !== "objekt" && showObjekt && /* @__PURE__ */ React.createElement("td", { style: { width: 130, fontSize: 12.5, color: "var(--ink-2)" } }, window.OFFENE_POSTEN.ccLabel[r.kostenstelle] || "\u2014"), gruppierung === "objekt" && /* @__PURE__ */ React.createElement("td", { className: "col-party", style: { width: 200, fontSize: 12.5 } }, window.OFFENE_POSTEN.partyName(r.party), /* @__PURE__ */ React.createElement("span", { className: "op-party-id" }, r.party)), /* @__PURE__ */ React.createElement("td", { className: "col-bemerk" }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", null, r.bemerkungen), r.mahnstufe ? /* @__PURE__ */ React.createElement(MahnstufeBadge, { stufe: r.mahnstufe }) : null)), /* @__PURE__ */ React.createElement("td", { style: { width: 120 } }, /* @__PURE__ */ React.createElement(StatusBadge, { status: r.status })), /* @__PURE__ */ React.createElement("td", { className: `is-num col-offen ${isNeg ? "is-negative" : ""}`, style: { width: 130 } }, fmtEUR_op(r.offen)), /* @__PURE__ */ React.createElement("td", { style: { position: "relative", textAlign: "right", width: 200 } }, /* @__PURE__ */ React.createElement(ActionCell, { row: r, onAction }))), mahnOpen && /* @__PURE__ */ React.createElement("tr", { className: "op-mahn-inline-row" }, /* @__PURE__ */ React.createElement("td", { colSpan: detailColspan }, /* @__PURE__ */ React.createElement(MahnInlineDetail, { candidate: mahnCandidate, row: r, onCreateDunning }))));
      })))));
    }));
  }
  function FilterRow({ availableImmos, immoFilter, setImmoFilter, datumVon, datumBis, setDatumVon, setDatumBis }) {
    const toggleImmo = (cc) => {
      setImmoFilter((prev) => {
        const next = new Set(prev);
        next.has(cc) ? next.delete(cc) : next.add(cc);
        return next;
      });
    };
    const clearAll = () => {
      setImmoFilter(/* @__PURE__ */ new Set());
      setDatumVon("");
      setDatumBis("");
    };
    const hasFilter = immoFilter.size > 0 || datumVon || datumBis;
    const _now = /* @__PURE__ */ new Date();
    const _Y = _now.getFullYear();
    const _M = _now.getMonth();
    const _pad = (n) => String(n).padStart(2, "0");
    const _ymd = (y, m, d) => `${y}-${_pad(m + 1)}-${_pad(d)}`;
    const curMonthStart = _ymd(_Y, _M, 1);
    const curMonthEnd = _ymd(_Y, _M, new Date(_Y, _M + 1, 0).getDate());
    const _prev = new Date(_Y, _M - 1, 1);
    const prevMonthStart = _ymd(_prev.getFullYear(), _prev.getMonth(), 1);
    const prevMonthEnd = _ymd(
      _prev.getFullYear(),
      _prev.getMonth(),
      new Date(_prev.getFullYear(), _prev.getMonth() + 1, 0).getDate()
    );
    const todayStr = _ymd(_Y, _M, _now.getDate());
    const _d30 = new Date(_now);
    _d30.setDate(_d30.getDate() - 30);
    const minus30Str = _ymd(_d30.getFullYear(), _d30.getMonth(), _d30.getDate());
    const presets = [
      { label: "Aktueller Monat", von: curMonthStart, bis: curMonthEnd },
      { label: "Letzter Monat", von: prevMonthStart, bis: prevMonthEnd },
      { label: "Heute", von: todayStr, bis: todayStr },
      { label: "> 30 Tage", von: "", bis: minus30Str },
      { label: `${_Y}`, von: `${_Y}-01-01`, bis: `${_Y}-12-31` },
      { label: `${_Y - 1}`, von: `${_Y - 1}-01-01`, bis: `${_Y - 1}-12-31` }
    ];
    const presetMatch = presets.find((p) => p.von === datumVon && p.bis === datumBis);
    return /* @__PURE__ */ React.createElement("div", { className: "op-filter-row" }, /* @__PURE__ */ React.createElement("div", { className: "op-filter-group" }, /* @__PURE__ */ React.createElement("span", { className: "op-filter-group-label" }, "Immobilie"), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: `op-immo-chip ${immoFilter.size === 0 ? "is-active" : ""}`,
        onClick: () => setImmoFilter(/* @__PURE__ */ new Set())
      },
      "Alle"
    ), availableImmos.map((i) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: i.cc,
        className: `op-immo-chip ${immoFilter.has(i.cc) ? "is-active" : ""}`,
        onClick: () => toggleImmo(i.cc)
      },
      i.label,
      /* @__PURE__ */ React.createElement("span", { className: "op-immo-chip-count" }, i.count)
    ))), /* @__PURE__ */ React.createElement("div", { className: "op-filter-sep" }), /* @__PURE__ */ React.createElement("div", { className: "op-filter-group" }, /* @__PURE__ */ React.createElement("span", { className: "op-filter-group-label" }, "F\xE4lligkeit"), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "date",
        className: "op-date-input",
        value: datumVon,
        onChange: (e) => setDatumVon(e.target.value),
        placeholder: "von"
      }
    ), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--ink-3)" } }, "\u2014"), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "date",
        className: "op-date-input",
        value: datumBis,
        onChange: (e) => setDatumBis(e.target.value),
        placeholder: "bis"
      }
    ), /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", gap: 2, marginLeft: 4 } }, presets.map((p) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: p.label,
        className: `op-date-preset ${presetMatch?.label === p.label ? "is-active" : ""}`,
        onClick: () => {
          setDatumVon(p.von);
          setDatumBis(p.bis);
        }
      },
      p.label
    )))), hasFilter && /* @__PURE__ */ React.createElement("button", { className: "op-filter-clear", onClick: clearAll }, "Filter zur\xFCcksetzen \xD7"));
  }
  ReactDOM.createRoot(document.getElementById("root")).render(/* @__PURE__ */ React.createElement(OpApp, null));
})();
