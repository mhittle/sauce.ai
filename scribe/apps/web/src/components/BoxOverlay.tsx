import { useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

// Interactive bounding-box overlay: an <img> with an SVG drawn over it in the
// image's NATURAL pixel coordinates (viewBox does the scaling — no manual
// math). Pure component: no data fetching; the parent owns the boxes and
// hears about edits via callbacks. Boxes are advisory-quality visual anchors
// (the model's self-reported boxes are loose) — the reviewer corrects them.

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

type DragState =
  | { kind: "move"; id: string; start: { x: number; y: number }; orig: BBox }
  | {
      kind: "resize";
      id: string;
      corner: "nw" | "ne" | "sw" | "se";
      orig: BBox;
    }
  | { kind: "draw"; start: { x: number; y: number } };

function normalize(b: BBox): BBox {
  return [
    Math.min(b[0], b[2]),
    Math.min(b[1], b[3]),
    Math.max(b[0], b[2]),
    Math.max(b[1], b[3]),
  ];
}

export function BoxOverlay({
  src,
  boxes,
  underlays = [],
  selectedId,
  drawMode,
  onSelect,
  onChange,
  onCreate,
}: {
  src: string;
  boxes: OverlayBox[];
  // Non-interactive dashed context rects (e.g. already-scanned regions),
  // drawn beneath the boxes in the same natural-pixel space.
  underlays?: BBox[];
  selectedId: string | null;
  // When true, dragging on empty canvas draws a new box instead of deselecting.
  drawMode: boolean;
  onSelect: (id: string | null) => void;
  onChange: (id: string, bbox: BBox) => void;
  onCreate: (bbox: BBox) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  // Labels render only for the hovered/selected box — a dense elevation with
  // every label visible at once is unreadable (all the text overlaps).
  const [hovered, setHovered] = useState<string | null>(null);
  // Live bbox during a drag: id === null while drawing a new box.
  const [draft, setDraft] = useState<{ id: string | null; bbox: BBox } | null>(
    null
  );

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
    if (drawMode) {
      beginDrag(e, { kind: "draw", start: toImage(e) });
    } else {
      onSelect(null);
    }
  };

  // Handle size in image px, so handles stay grabbable at any zoom.
  const handle = nat ? Math.max(6, nat.w * 0.008) : 8;

  return (
    <div className={`relative inline-block w-full ${drawMode ? "cursor-crosshair" : ""}`}>
      <img
        src={src}
        alt="read image"
        className="w-full select-none border border-zinc-200"
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
              draft && draft.id === box.id ? normalize(draft.bbox) : box.bbox;
            const color = categoryColor(box.category);
            const selected = box.id === selectedId;
            return (
              <g key={box.id}>
                <rect
                  x={b[0]}
                  y={b[1]}
                  width={Math.max(1, b[2] - b[0])}
                  height={Math.max(1, b[3] - b[1])}
                  fill={color}
                  fillOpacity={selected ? 0.18 : 0.08}
                  stroke={color}
                  strokeWidth={selected ? 3 : 1.5}
                  vectorEffect="non-scaling-stroke"
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
                {(box.id === hovered || selected) && (
                  <text
                    x={b[0] + handle / 2}
                    y={Math.max(b[1] - handle / 2, handle * 1.5)}
                    fontSize={handle * 1.8}
                    fill={color}
                    className="pointer-events-none select-none font-semibold"
                    paintOrder="stroke"
                    stroke="white"
                    strokeWidth={handle / 3}
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
                  ).map(([corner, cx, cy]) => (
                    <rect
                      key={corner}
                      x={cx - handle}
                      y={cy - handle}
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
                        beginDrag(e, { kind: "resize", id: box.id, corner, orig: b })
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
  );
}
