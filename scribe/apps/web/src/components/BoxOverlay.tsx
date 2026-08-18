import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

// Interactive overlay for the cabinets found on a read image: an <img> with an
// SVG drawn over it in the image's NATURAL pixel coordinates (viewBox does the
// scaling — no manual math). Pure component: no data fetching; the parent owns
// the boxes and hears about edits via callbacks.
//
// Each cabinet shows as a DOT at the centre of its box, not as an outlined
// rectangle (owner feedback 2026-08-18: a plan covered in loose rectangles
// reads as clutter, and the boxes are advisory-quality anyway — the model's
// own boxes are loose and the inch fields drive price). The rectangle is still
// there, revealed on hover and while selected, where it is useful and where
// the reviewer can drag/resize it.
//
// ZOOM/PAN: a plan sheet fitted to a panel is unreadable — a 36x24 sheet in a
// 600px column is ~1.4 real inches wide. The image sits in a scroll container
// whose inner width is `zoom x 100%`, so panning is native scrolling and every
// coordinate stays in image space: the SVG viewBox keeps mapping, and dots,
// labels and handles stay a constant size ON SCREEN at any zoom (they are
// derived from the SVG's measured width).

export type BBox = [number, number, number, number];

export interface OverlayBox {
  id: string;
  bbox: BBox;
  category: string;
  label: string;
}

// Category palette from the detector-PoC verify_boxes.py overlays.
const CATEGORY_COLORS: Record<string, string> = {
  casework_base: "rgb(0,170,0)",
  casework_wall: "rgb(200,0,200)",
  casework_tall: "rgb(0,90,220)",
  vanity: "rgb(230,140,0)",
};
const DEFAULT_COLOR = "rgb(220,38,38)";

export function categoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? DEFAULT_COLOR;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 10;
const ZOOM_STEP = 1.4;
// Pointer travel under this (CSS px) is a click, not a pan.
const CLICK_SLOP = 4;

type DragState =
  | { kind: "move"; id: string; start: { x: number; y: number }; orig: BBox }
  | {
      kind: "resize";
      id: string;
      corner: "nw" | "ne" | "sw" | "se";
      orig: BBox;
    }
  | { kind: "draw"; start: { x: number; y: number } }
  | {
      kind: "pan";
      from: { x: number; y: number };
      scroll: { left: number; top: number };
      moved: boolean;
    };

function normalize(b: BBox): BBox {
  return [
    Math.min(b[0], b[2]),
    Math.min(b[1], b[3]),
    Math.max(b[0], b[2]),
    Math.max(b[1], b[3]),
  ];
}

function centerOf(b: BBox): { cx: number; cy: number } {
  return { cx: (b[0] + b[2]) / 2, cy: (b[1] + b[3]) / 2 };
}

export function BoxOverlay({
  src,
  boxes,
  underlays = [],
  selectedId,
  drawMode,
  maxHeight = "70vh",
  onSelect,
  onChange,
  onCreate,
}: {
  src: string;
  boxes: OverlayBox[];
  // Non-interactive dashed context rects (e.g. already-scanned regions),
  // drawn beneath the dots in the same natural-pixel space.
  underlays?: BBox[];
  selectedId: string | null;
  // When true, dragging on empty canvas draws a new box instead of panning.
  drawMode: boolean;
  // Height of the scroll viewport (any CSS length).
  maxHeight?: string;
  onSelect: (id: string | null) => void;
  onChange: (id: string, bbox: BBox) => void;
  onCreate: (bbox: BBox) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  // Image px per CSS px, so a dot stays the same size on screen whatever the
  // sheet's resolution, the panel's width, or the zoom.
  const [scale, setScale] = useState(1);
  // Labels render only for the hovered/selected cabinet — a dense elevation
  // with every label visible at once is unreadable (all the text overlaps).
  const [hovered, setHovered] = useState<string | null>(null);
  // Held space pans even in draw mode — the wizard is always in draw mode and
  // is exactly where you zoom in and need to move around.
  const [spaceHeld, setSpaceHeld] = useState(false);
  // Live bbox during a drag: id === null while drawing a new box.
  const [draft, setDraft] = useState<{ id: string | null; bbox: BBox } | null>(
    null
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      const el = e.target as HTMLElement | null;
      // Never steal the space bar from someone typing in the line table.
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (e.type === "keydown") e.preventDefault();
      setSpaceHeld(e.type === "keydown");
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    const clear = () => setSpaceHeld(false);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKey);
      window.removeEventListener("blur", clear);
    };
  }, []);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !nat) return;
    const update = () =>
      setScale(svg.getBoundingClientRect().width / nat.w || 1);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(svg);
    return () => observer.disconnect();
  }, [nat]);

  // CSS pixels → image pixels, for anything that should keep a constant
  // on-screen size (dots, hit targets, handles, label text).
  const px = (cssPx: number) => cssPx / (scale || 1);

  // Zoom keeps whatever sits under (viewX, viewY) — viewport-relative CSS
  // pixels — pinned there. The scroll position can only be corrected once the
  // new width has laid out, so it is queued for the layout effect below.
  const anchorRef = useRef<{
    contentX: number;
    contentY: number;
    viewX: number;
    viewY: number;
    ratio: number;
  } | null>(null);

  const zoomBy = useCallback(
    (factor: number, clientX?: number, clientY?: number) => {
      const el = scrollRef.current;
      if (!el) return;
      setZoom((current) => {
        const next = Math.min(
          MAX_ZOOM,
          Math.max(MIN_ZOOM, current * factor)
        );
        if (next === current) return current;
        const r = el.getBoundingClientRect();
        const viewX = clientX != null ? clientX - r.left : el.clientWidth / 2;
        const viewY = clientY != null ? clientY - r.top : el.clientHeight / 2;
        anchorRef.current = {
          contentX: el.scrollLeft + viewX,
          contentY: el.scrollTop + viewY,
          viewX,
          viewY,
          ratio: next / current,
        };
        return next;
      });
    },
    []
  );

  useLayoutEffect(() => {
    const el = scrollRef.current;
    const anchor = anchorRef.current;
    anchorRef.current = null;
    if (!el || !anchor) return;
    el.scrollLeft = anchor.contentX * anchor.ratio - anchor.viewX;
    el.scrollTop = anchor.contentY * anchor.ratio - anchor.viewY;
  }, [zoom]);

  // ctrl/cmd + wheel zooms at the cursor (the convention every PDF viewer
  // uses); a plain wheel keeps scrolling the panel. Bound by hand because the
  // handler has to preventDefault, which React's passive listener cannot.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      zoomBy(e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP, e.clientX, e.clientY);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomBy]);

  // Selecting a line in the table has to bring its cabinet into view — at 4x
  // zoom the dot is usually somewhere off-screen.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !nat || selectedId == null) return;
    const box = boxes.find((b) => b.id === selectedId);
    if (!box) return;
    const { cx, cy } = centerOf(box.bbox);
    const x = (cx / nat.w) * el.scrollWidth;
    const y = (cy / nat.h) * el.scrollHeight;
    const margin = 24;
    const inView =
      x >= el.scrollLeft + margin &&
      x <= el.scrollLeft + el.clientWidth - margin &&
      y >= el.scrollTop + margin &&
      y <= el.scrollTop + el.clientHeight - margin;
    if (inView) return;
    el.scrollLeft = x - el.clientWidth / 2;
    el.scrollTop = y - el.clientHeight / 2;
    // `boxes` deliberately not a dependency: re-centering on every bbox edit
    // would fight the reviewer dragging a box near the edge.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, zoom, nat]);

  const toImage = (e: { clientX: number; clientY: number }) => {
    const svg = svgRef.current!;
    const r = svg.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(((e.clientX - r.left) / r.width) * (nat?.w ?? 1), nat?.w ?? 1)),
      y: Math.max(0, Math.min(((e.clientY - r.top) / r.height) * (nat?.h ?? 1), nat?.h ?? 1)),
    };
  };

  const beginDrag = (e: ReactPointerEvent, state: DragState) => {
    e.stopPropagation();
    dragRef.current = state;
    svgRef.current?.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    const drag = dragRef.current;
    if (!drag || !nat) return;
    if (drag.kind === "pan") {
      const el = scrollRef.current;
      if (!el) return;
      const dx = e.clientX - drag.from.x;
      const dy = e.clientY - drag.from.y;
      if (Math.abs(dx) > CLICK_SLOP || Math.abs(dy) > CLICK_SLOP)
        drag.moved = true;
      el.scrollLeft = drag.scroll.left - dx;
      el.scrollTop = drag.scroll.top - dy;
      return;
    }
    const p = toImage(e);
    if (drag.kind === "move") {
      const dx = p.x - drag.start.x;
      const dy = p.y - drag.start.y;
      setDraft({
        id: drag.id,
        bbox: [
          drag.orig[0] + dx,
          drag.orig[1] + dy,
          drag.orig[2] + dx,
          drag.orig[3] + dy,
        ],
      });
    } else if (drag.kind === "resize") {
      const b: BBox = [...drag.orig];
      if (drag.corner === "nw" || drag.corner === "sw") b[0] = p.x;
      else b[2] = p.x;
      if (drag.corner === "nw" || drag.corner === "ne") b[1] = p.y;
      else b[3] = p.y;
      setDraft({ id: drag.id, bbox: b });
    } else {
      setDraft({ id: null, bbox: [drag.start.x, drag.start.y, p.x, p.y] });
    }
  };

  const onPointerUp = (e: ReactPointerEvent) => {
    const drag = dragRef.current;
    dragRef.current = null;
    svgRef.current?.releasePointerCapture(e.pointerId);
    if (drag?.kind === "pan") {
      // A press that went nowhere is still a click on empty canvas — but only
      // when the click meant "nothing here", not when it meant "pan".
      if (!drag.moved && !spaceHeld && e.button === 0 && !drawMode)
        onSelect(null);
      return;
    }
    if (!drag || !draft) {
      setDraft(null);
      return;
    }
    const b = normalize(draft.bbox);
    setDraft(null);
    const minSide = Math.max(4, (nat?.w ?? 1000) * 0.005);
    if (drag.kind === "draw") {
      if (b[2] - b[0] >= minSide && b[3] - b[1] >= minSide) onCreate(b);
    } else if (draft.id != null) {
      onChange(draft.id, b);
    }
  };

  const onBackgroundDown = (e: ReactPointerEvent) => {
    if (!nat) return;
    if (drawMode && !spaceHeld && e.button === 0) {
      beginDrag(e, { kind: "draw", start: toImage(e) });
      return;
    }
    const el = scrollRef.current;
    beginDrag(e, {
      kind: "pan",
      from: { x: e.clientX, y: e.clientY },
      scroll: { left: el?.scrollLeft ?? 0, top: el?.scrollTop ?? 0 },
      moved: false,
    });
  };

  const dot = px(6);
  const hit = px(15);
  const handle = px(7);

  return (
    <div className="relative">
      <div
        ref={scrollRef}
        className="overflow-auto border border-zinc-200"
        style={{ maxHeight }}
      >
        <div
          className={`relative ${
            drawMode && !spaceHeld ? "cursor-crosshair" : "cursor-grab"
          }`}
          style={{ width: `${zoom * 100}%` }}
        >
          <img
            src={src}
            alt="read image"
            className="block w-full select-none"
            draggable={false}
            onLoad={(e) =>
              setNat({
                w: e.currentTarget.naturalWidth,
                h: e.currentTarget.naturalHeight,
              })
            }
          />
          {nat && (
            <svg
              ref={svgRef}
              viewBox={`0 0 ${nat.w} ${nat.h}`}
              preserveAspectRatio="none"
              className="absolute inset-0 h-full w-full touch-none"
              onPointerDown={onBackgroundDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
            >
              {underlays.map((u, i) => (
                <rect
                  key={`underlay-${i}`}
                  x={Math.min(u[0], u[2])}
                  y={Math.min(u[1], u[3])}
                  width={Math.abs(u[2] - u[0])}
                  height={Math.abs(u[3] - u[1])}
                  fill="none"
                  stroke="rgb(161,161,170)"
                  strokeWidth={1}
                  strokeDasharray="8 6"
                  vectorEffect="non-scaling-stroke"
                  className="pointer-events-none"
                />
              ))}
              {boxes.map((box) => {
                const b =
                  draft && draft.id === box.id
                    ? normalize(draft.bbox)
                    : box.bbox;
                const color = categoryColor(box.category);
                const selected = box.id === selectedId;
                const active = selected || box.id === hovered;
                const { cx, cy } = centerOf(b);
                return (
                  <g key={box.id}>
                    {/* The box itself is context, shown only when the cabinet
                        is hovered or selected — and it is what gets edited. */}
                    {active && (
                      <rect
                        x={b[0]}
                        y={b[1]}
                        width={Math.max(1, b[2] - b[0])}
                        height={Math.max(1, b[3] - b[1])}
                        fill={color}
                        fillOpacity={selected ? 0.12 : 0.06}
                        stroke={color}
                        strokeWidth={selected ? 2 : 1.5}
                        strokeDasharray={selected ? undefined : "6 4"}
                        vectorEffect="non-scaling-stroke"
                        className="pointer-events-none"
                      />
                    )}
                    <circle
                      cx={cx}
                      cy={cy}
                      r={selected ? dot * 1.35 : dot}
                      fill={color}
                      fillOpacity={active ? 1 : 0.85}
                      stroke="white"
                      strokeWidth={2}
                      vectorEffect="non-scaling-stroke"
                      className="pointer-events-none"
                    />
                    {/* Invisible, comfortably sized hit target: the dot is
                        small on purpose, but it still has to be easy to grab. */}
                    <circle
                      cx={cx}
                      cy={cy}
                      r={hit}
                      fill="transparent"
                      className="cursor-move"
                      onPointerEnter={() => setHovered(box.id)}
                      onPointerLeave={() =>
                        setHovered((h) => (h === box.id ? null : h))
                      }
                      onPointerDown={(e) => {
                        onSelect(box.id);
                        beginDrag(e, {
                          kind: "move",
                          id: box.id,
                          start: toImage(e),
                          orig: b,
                        });
                      }}
                    />
                    {active && (
                      <text
                        x={cx + hit * 0.8}
                        y={cy - hit * 0.5}
                        fontSize={px(13)}
                        fill={color}
                        className="pointer-events-none select-none font-semibold"
                        paintOrder="stroke"
                        stroke="white"
                        strokeWidth={px(4)}
                      >
                        {box.label}
                      </text>
                    )}
                    {selected &&
                      (
                        [
                          ["nw", b[0], b[1]],
                          ["ne", b[2], b[1]],
                          ["sw", b[0], b[3]],
                          ["se", b[2], b[3]],
                        ] as const
                      ).map(([corner, hx, hy]) => (
                        <rect
                          key={corner}
                          x={hx - handle}
                          y={hy - handle}
                          width={handle * 2}
                          height={handle * 2}
                          fill="white"
                          stroke={color}
                          strokeWidth={1.5}
                          vectorEffect="non-scaling-stroke"
                          className={
                            corner === "nw" || corner === "se"
                              ? "cursor-nwse-resize"
                              : "cursor-nesw-resize"
                          }
                          onPointerDown={(e) =>
                            beginDrag(e, {
                              kind: "resize",
                              id: box.id,
                              corner,
                              orig: b,
                            })
                          }
                        />
                      ))}
                  </g>
                );
              })}
              {draft && draft.id === null && (
                <rect
                  x={normalize(draft.bbox)[0]}
                  y={normalize(draft.bbox)[1]}
                  width={normalize(draft.bbox)[2] - normalize(draft.bbox)[0]}
                  height={normalize(draft.bbox)[3] - normalize(draft.bbox)[1]}
                  fill="rgb(37,99,235)"
                  fillOpacity={0.12}
                  stroke="rgb(37,99,235)"
                  strokeWidth={2}
                  strokeDasharray="6 4"
                  vectorEffect="non-scaling-stroke"
                />
              )}
            </svg>
          )}
        </div>
      </div>

      <ZoomControls
        zoom={zoom}
        onZoom={(factor) => zoomBy(factor)}
        onFit={() => {
          const el = scrollRef.current;
          setZoom(1);
          if (el) {
            el.scrollLeft = 0;
            el.scrollTop = 0;
          }
        }}
      />
    </div>
  );
}

function ZoomControls({
  zoom,
  onZoom,
  onFit,
}: {
  zoom: number;
  onZoom: (factor: number) => void;
  onFit: () => void;
}) {
  const btn =
    "px-2 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:text-zinc-300 disabled:hover:bg-transparent";
  return (
    <div className="pointer-events-none absolute bottom-2 right-2 flex items-center">
      <div className="pointer-events-auto flex items-center divide-x divide-zinc-200 overflow-hidden rounded-md border border-zinc-300 bg-white/95 shadow-sm">
        <button
          className={btn}
          onClick={() => onZoom(1 / ZOOM_STEP)}
          disabled={zoom <= MIN_ZOOM}
          title="Zoom out"
          aria-label="Zoom out"
        >
          −
        </button>
        <span className="px-2 py-1 text-xs tabular-nums text-zinc-500">
          {Math.round(zoom * 100)}%
        </span>
        <button
          className={btn}
          onClick={() => onZoom(ZOOM_STEP)}
          disabled={zoom >= MAX_ZOOM}
          title="Zoom in (⌘/ctrl + scroll)"
          aria-label="Zoom in"
        >
          +
        </button>
        <button className={btn} onClick={onFit} disabled={zoom === MIN_ZOOM}>
          Fit
        </button>
      </div>
    </div>
  );
}
