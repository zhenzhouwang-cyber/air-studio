import type { MouseEvent, WheelEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import "./InfiniteCanvas.css";

type CanvasElement = {
  id: string;
  type: "note" | "image" | "shape";
  x: number;
  y: number;
  w: number;
  h: number;
  content: string;
  image_url: string;
};

type CanvasBoard = {
  id: string;
  title: string;
  viewport: { x: number; y: number; zoom: number };
  elements: CanvasElement[];
  command_history: Array<Record<string, unknown>>;
};

type CommandResp = {
  board_id: string;
  command_id: string;
  optimized_prompt: string;
  negative_prompt: string;
  category: string;
  score: number;
  suggested_element: CanvasElement;
};

const API_BASE = (import.meta.env.VITE_API_BASE || "").trim();

function apiUrl(path: string): string {
  if (!API_BASE) return path;
  return `${API_BASE.replace(/\/$/, "")}${path}`;
}

type Props = {
  onBack: () => void;
};

export default function InfiniteCanvas({ onBack }: Props) {
  const [board, setBoard] = useState<CanvasBoard | null>(null);
  const [instruction, setInstruction] = useState("");
  const [referenceImageDataUrl, setReferenceImageDataUrl] = useState("");
  const [referenceWeight, setReferenceWeight] = useState(0.7);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [lastResult, setLastResult] = useState<CommandResp | null>(null);

  const canvasRef = useRef<HTMLDivElement | null>(null);
  const dragIdRef = useRef<string>("");
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const panningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0, vx: 0, vy: 0 });

  const viewport = useMemo(() => board?.viewport ?? { x: 0, y: 0, zoom: 1 }, [board]);

  useEffect(() => {
    let mounted = true;
    async function init() {
      const localId = localStorage.getItem("air_canvas_board_id");
      if (localId) {
        const r = await fetch(apiUrl(`/api/canvas/boards/${localId}`));
        if (r.ok) {
          const data = (await r.json()) as CanvasBoard;
          if (mounted) setBoard(data);
          return;
        }
      }

      const created = await fetch(apiUrl("/api/canvas/boards"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "Untitled" }),
      });
      const data = (await created.json()) as CanvasBoard;
      localStorage.setItem("air_canvas_board_id", data.id);
      if (mounted) setBoard(data);
    }

    void init();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!board) return;
    const timer = setTimeout(async () => {
      await fetch(apiUrl(`/api/canvas/boards/${board.id}`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ viewport: board.viewport, elements: board.elements }),
      });
    }, 400);
    return () => clearTimeout(timer);
  }, [board]);

  function onWheel(e: WheelEvent<HTMLDivElement>) {
    e.preventDefault();
    if (!board) return;
    const delta = e.deltaY > 0 ? 0.92 : 1.08;
    const nextZoom = Math.max(0.2, Math.min(3, board.viewport.zoom * delta));
    setBoard({ ...board, viewport: { ...board.viewport, zoom: nextZoom } });
  }

  function beginPan(e: MouseEvent<HTMLDivElement>) {
    if (e.button !== 1 && (e.button !== 0 || (e.target as HTMLElement).dataset.role === "element")) return;
    if (!board) return;
    panningRef.current = true;
    panStartRef.current = { x: e.clientX, y: e.clientY, vx: board.viewport.x, vy: board.viewport.y };
  }

  function onMove(e: MouseEvent<HTMLDivElement>) {
    if (!board) return;

    if (panningRef.current) {
      const dx = e.clientX - panStartRef.current.x;
      const dy = e.clientY - panStartRef.current.y;
      setBoard({ ...board, viewport: { ...board.viewport, x: panStartRef.current.vx + dx, y: panStartRef.current.vy + dy } });
      return;
    }

    const dragId = dragIdRef.current;
    if (!dragId) return;
    const nx = (e.clientX - dragOffsetRef.current.x - board.viewport.x) / board.viewport.zoom;
    const ny = (e.clientY - dragOffsetRef.current.y - board.viewport.y) / board.viewport.zoom;
    setBoard({
      ...board,
      elements: board.elements.map((el) => (el.id === dragId ? { ...el, x: nx, y: ny } : el)),
    });
  }

  function endPointer() {
    panningRef.current = false;
    dragIdRef.current = "";
  }

  function beginDragElement(e: MouseEvent<HTMLDivElement>, el: CanvasElement) {
    e.stopPropagation();
    if (!board) return;
    dragIdRef.current = el.id;
    dragOffsetRef.current = {
      x: e.clientX - (board.viewport.x + el.x * board.viewport.zoom),
      y: e.clientY - (board.viewport.y + el.y * board.viewport.zoom),
    };
  }

  function addNote() {
    if (!board) return;
    const note: CanvasElement = {
      id: crypto.randomUUID(),
      type: "note",
      x: 120,
      y: 120,
      w: 260,
      h: 160,
      content: "New note",
      image_url: "",
    };
    setBoard({ ...board, elements: [...board.elements, note] });
  }

  async function onReferenceFile(file: File | null) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setReferenceImageDataUrl(String(reader.result || ""));
    reader.readAsDataURL(file);
  }

  async function runCommand() {
    if (!board || !instruction.trim()) return;
    setRunning(true);
    setError("");
    try {
      const resp = await fetch(apiUrl(`/api/canvas/boards/${board.id}/commands`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction,
          reference_image_data_url: referenceImageDataUrl,
          reference_weight: referenceWeight,
          image_size: "1K",
          style_strength: "medium",
        }),
      });
      const data = (await resp.json()) as CommandResp | { detail?: string };
      if (!resp.ok) throw new Error((data as { detail?: string }).detail || `HTTP ${resp.status}`);
      const okData = data as CommandResp;
      setLastResult(okData);
      setBoard((prev) => {
        if (!prev) return prev;
        return { ...prev, elements: [...prev.elements, okData.suggested_element] };
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Command failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="canvas-shell">
      <header className="canvas-topbar">
        <div>
          <h2>{board?.title || "Untitled"}</h2>
          <p>Infinite Canvas Workspace</p>
        </div>
        <button className="back-btn" onClick={onBack}>返回 Pipeline</button>
      </header>

      <section className="canvas-layout">
        <div
          className="canvas-stage"
          ref={canvasRef}
          onWheel={onWheel}
          onMouseDown={beginPan}
          onMouseMove={onMove}
          onMouseUp={endPointer}
          onMouseLeave={endPointer}
        >
          <div
            className="canvas-grid"
            style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})` }}
          >
            {board?.elements.map((el) => (
              <div
                key={el.id}
                className={`canvas-element ${el.type}`}
                data-role="element"
                style={{ left: `${el.x}px`, top: `${el.y}px`, width: `${el.w}px`, height: `${el.h}px` }}
                onMouseDown={(e) => beginDragElement(e, el)}
              >
                {el.type === "image" && el.image_url ? <img src={el.image_url} alt="canvas" /> : <pre>{el.content}</pre>}
              </div>
            ))}
          </div>

          <div className="canvas-toolbar">
            <button onClick={addNote}>+ Note</button>
            <span>Zoom {Math.round(viewport.zoom * 100)}%</span>
          </div>
        </div>

        <aside className="canvas-sidebar">
          <h3>指令面板</h3>
          <label>
            指令输入
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="输入你的创作指令，例如：生成食品海报，暖色蒸汽感，主体完整入画"
            />
          </label>

          <label>
            参考图添加
            <input type="file" accept="image/*" onChange={(e) => void onReferenceFile(e.target.files?.[0] ?? null)} />
          </label>

          {referenceImageDataUrl && <img className="ref-preview" src={referenceImageDataUrl} alt="reference" />}

          <label>
            参考权重 {referenceWeight.toFixed(2)}
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={referenceWeight}
              onChange={(e) => setReferenceWeight(Number(e.target.value))}
            />
          </label>

          <button className="run-btn" disabled={running || !instruction.trim()} onClick={runCommand}>
            {running ? "执行中..." : "执行指令"}
          </button>

          {error && <p className="panel-error">{error}</p>}

          {lastResult && (
            <div className="result-panel">
              <p>分类：{lastResult.category}</p>
              <p>评分：{lastResult.score}</p>
              <h4>Optimized Prompt</h4>
              <pre>{lastResult.optimized_prompt}</pre>
              <h4>Negative Prompt</h4>
              <pre>{lastResult.negative_prompt}</pre>
            </div>
          )}
        </aside>
      </section>
    </main>
  );
}

