import * as React from "react";

type Tool = "select" | "hand" | "note" | "text" | "rect" | "line";
type ElementType = "note" | "text" | "rect" | "image" | "line";
type ToolMenu = "mode" | "model" | "ratio" | "size" | null;

type CanvasElement = {
  id: string;
  type: ElementType;
  x: number;
  y: number;
  w: number;
  h: number;
  text: string;
  image_url: string;
};

type Viewport = { x: number; y: number; zoom: number };

type Board = {
  id: string;
  title: string;
  viewport: Viewport;
  elements: CanvasElement[];
};

type CommandResponse = {
  board_id: string;
  optimized_prompt: string;
  negative_prompt: string;
  image_url: string;
  added_element: CanvasElement;
};

type DragState = {
  id: string;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
};

type ResizeCorner = "nw" | "ne" | "sw" | "se";
type ResizeState = {
  id: string;
  corner: ResizeCorner;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
  startW: number;
  startH: number;
};

type ModelOption = { label: string; value: string; desc: string };

const API = "http://127.0.0.1:8000";
const MODEL_OPTIONS: ModelOption[] = [
  { label: "Nano Banana", value: "gemini-2.5-flash-image", desc: "$0.02/次" },
  { label: "Nano Banana Pro", value: "gemini-3-pro-image-preview", desc: "$0.05/次" },
  { label: "Nano Banana 2", value: "gemini-3.1-flash-image-preview", desc: "$0.045/次" },
  { label: "ARK Seedream 4.0", value: "doubao-seedream-4-0-250828", desc: "ARK计费" },
];
const RATIO_OPTIONS = ["1:1", "16:9", "9:16", "4:3", "3:4"] as const;
const SIZE_OPTIONS = ["1K", "2K", "4K"] as const;

function uid(): string {
  return Math.random().toString(36).slice(2, 11);
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function App(): React.JSX.Element {
  const wrapRef = React.useRef<HTMLElement | null>(null);
  const canvasRef = React.useRef<HTMLDivElement | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);
  const refInputRef = React.useRef<HTMLInputElement | null>(null);
  const composerActionsRef = React.useRef<HTMLDivElement | null>(null);

  const [boards, setBoards] = React.useState<Board[]>([]);
  const [boardId, setBoardId] = React.useState("");
  const [boardTitle, setBoardTitle] = React.useState("Untitled");
  const [viewport, setViewport] = React.useState<Viewport>({ x: 420, y: 240, zoom: 1 });
  const [elements, setElements] = React.useState<CanvasElement[]>([]);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [tool, setTool] = React.useState<Tool>("select");
  const [isSpaceDown, setIsSpaceDown] = React.useState(false);

  const [menuOpen, setMenuOpen] = React.useState(false);
  const [shortcutOpen, setShortcutOpen] = React.useState(false);

  const [instruction, setInstruction] = React.useState("");
  const [runMode, setRunMode] = React.useState<"think" | "fast">("think");
  const [modelIndex, setModelIndex] = React.useState(3);
  const [ratioIndex, setRatioIndex] = React.useState(0);
  const [sizeIndex, setSizeIndex] = React.useState(1);
  const [openToolMenu, setOpenToolMenu] = React.useState<ToolMenu>(null);
  const [refImageDataUrl, setRefImageDataUrl] = React.useState("");

  const [optimizedPrompt, setOptimizedPrompt] = React.useState("");
  const [negativePrompt, setNegativePrompt] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  const dragRef = React.useRef<DragState | null>(null);
  const panRef = React.useRef<{ startX: number; startY: number; vx: number; vy: number } | null>(null);
  const resizeRef = React.useRef<ResizeState | null>(null);
  const saveTimer = React.useRef<number | null>(null);

  const selectedModel = MODEL_OPTIONS[modelIndex] ?? MODEL_OPTIONS[0];
  const selectedRatio = RATIO_OPTIONS[ratioIndex] ?? "1:1";
  const selectedSize = SIZE_OPTIONS[sizeIndex] ?? "2K";
  const modeLabel = runMode === "think" ? "思考模式" : "快速模式";
  const isPanMode = tool === "hand" || isSpaceDown;
  const isPanning = panRef.current !== null;

  const refreshBoards = React.useCallback(
    async (preferredId?: string) => {
      const res = await fetch(`${API}/api/canvas/boards`);
      if (!res.ok) return;
      const list = (await res.json()) as Board[];
      setBoards(list);

      const targetId = preferredId ?? boardId ?? list[0]?.id;
      if (!targetId) return;
      const board = list.find((b) => b.id === targetId) ?? list[0];
      if (!board) return;
      setBoardId(board.id);
      setBoardTitle(board.title || "Untitled");
      setViewport(board.viewport ?? { x: 420, y: 240, zoom: 1 });
      setElements(board.elements ?? []);
      setSelectedId(null);
    },
    [boardId],
  );

  React.useEffect(() => {
    (async () => {
      const res = await fetch(`${API}/api/canvas/boards`);
      if (!res.ok) return;
      const list = (await res.json()) as Board[];
      if (list.length > 0) {
        const b = list[0];
        setBoards(list);
        setBoardId(b.id);
        setBoardTitle(b.title || "Untitled");
        setViewport(b.viewport ?? { x: 420, y: 240, zoom: 1 });
        setElements(b.elements ?? []);
        return;
      }

      const createRes = await fetch(`${API}/api/canvas/boards`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "Untitled" }),
      });
      if (!createRes.ok) return;
      const b = (await createRes.json()) as Board;
      setBoards([b]);
      setBoardId(b.id);
      setBoardTitle(b.title || "Untitled");
      setViewport(b.viewport ?? { x: 420, y: 240, zoom: 1 });
      setElements(b.elements ?? []);
    })().catch(() => undefined);
  }, []);

  React.useEffect(() => {
    if (!boardId) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      fetch(`${API}/api/canvas/boards/${boardId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ viewport, elements }),
      }).catch(() => undefined);
    }, 700);
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, [boardId, viewport, elements]);

  React.useEffect(() => {
    function onMove(e: MouseEvent): void {
      if (dragRef.current) {
        const d = dragRef.current;
        const dx = (e.clientX - d.startClientX) / viewport.zoom;
        const dy = (e.clientY - d.startClientY) / viewport.zoom;
        setElements((prev) => prev.map((el) => (el.id === d.id ? { ...el, x: d.startX + dx, y: d.startY + dy } : el)));
      }
      if (panRef.current) {
        const p = panRef.current;
        setViewport((v) => ({ ...v, x: p.vx + (e.clientX - p.startX), y: p.vy + (e.clientY - p.startY) }));
      }
      if (resizeRef.current) {
        const r = resizeRef.current;
        const dx = (e.clientX - r.startClientX) / viewport.zoom;
        const dy = (e.clientY - r.startClientY) / viewport.zoom;
        setElements((prev) =>
          prev.map((el) => {
            if (el.id !== r.id) return el;
            let nx = r.startX;
            let ny = r.startY;
            let nw = r.startW;
            let nh = r.startH;
            if (r.corner.includes("e")) nw = r.startW + dx;
            if (r.corner.includes("s")) nh = r.startH + dy;
            if (r.corner.includes("w")) {
              nw = r.startW - dx;
              nx = r.startX + dx;
            }
            if (r.corner.includes("n")) {
              nh = r.startH - dy;
              ny = r.startY + dy;
            }
            return { ...el, x: nx, y: ny, w: Math.max(60, nw), h: Math.max(40, nh) };
          }),
        );
      }
    }
    function onUp(): void {
      dragRef.current = null;
      panRef.current = null;
      resizeRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [viewport.zoom]);

  React.useEffect(() => {
    function onPaste(e: ClipboardEvent): void {
      if (!boardId) return;
      const items = e.clipboardData?.items;
      if (!items) return;

      for (const item of items) {
        if (!item.type.startsWith("image/")) continue;
        const file = item.getAsFile();
        if (!file) continue;
        const reader = new FileReader();
        reader.onload = () => {
          const data = String(reader.result || "");
          if (!data) return;
          setElements((prev) => [...prev, { id: uid(), type: "image", x: 240, y: 180, w: 420, h: 420, text: "", image_url: data }]);
        };
        reader.readAsDataURL(file);
        e.preventDefault();
        return;
      }
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [boardId]);

  React.useEffect(() => {
    function onDocDown(event: MouseEvent): void {
      if (!composerActionsRef.current) return;
      if (!composerActionsRef.current.contains(event.target as Node)) setOpenToolMenu(null);
    }
    document.addEventListener("mousedown", onDocDown);
    return () => document.removeEventListener("mousedown", onDocDown);
  }, []);

  const zoomAt = React.useCallback(
    (clientX: number, clientY: number, nextZoom: number) => {
      const rect = wrapRef.current?.getBoundingClientRect();
      if (!rect) return;
      const canvasX = clientX - rect.left;
      const canvasY = clientY - rect.top;
      const worldX = (canvasX - viewport.x) / viewport.zoom;
      const worldY = (canvasY - viewport.y) / viewport.zoom;
      setViewport({
        zoom: nextZoom,
        x: canvasX - worldX * nextZoom,
        y: canvasY - worldY * nextZoom,
      });
    },
    [viewport],
  );

  const fitToView = React.useCallback(() => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    if (elements.length === 0) {
      setViewport({ x: rect.width / 2 - 200, y: rect.height / 2 - 120, zoom: 1 });
      return;
    }
    const minX = Math.min(...elements.map((e) => e.x));
    const minY = Math.min(...elements.map((e) => e.y));
    const maxX = Math.max(...elements.map((e) => e.x + e.w));
    const maxY = Math.max(...elements.map((e) => e.y + e.h));
    const width = Math.max(1, maxX - minX);
    const height = Math.max(1, maxY - minY);
    const padding = 120;
    const zoom = clamp(Math.min((rect.width - padding) / width, (rect.height - padding) / height), 0.2, 3);
    const cx = minX + width / 2;
    const cy = minY + height / 2;
    setViewport({
      zoom,
      x: rect.width / 2 - cx * zoom,
      y: rect.height / 2 - cy * zoom,
    });
  }, [elements]);

  React.useEffect(() => {
    function isTypingTarget(target: EventTarget | null): boolean {
      const el = target as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName?.toLowerCase();
      return tag === "input" || tag === "textarea" || el.isContentEditable;
    }

    function onKeyDown(e: KeyboardEvent): void {
      if (!isTypingTarget(e.target) && e.code === "Space") {
        if (!e.repeat) setIsSpaceDown(true);
        e.preventDefault();
      }

      if (isTypingTarget(e.target)) return;

      const cmd = e.metaKey || e.ctrlKey;
      if (cmd && (e.key === "+" || e.key === "=")) {
        e.preventDefault();
        const rect = wrapRef.current?.getBoundingClientRect();
        if (!rect) return;
        zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, clamp(viewport.zoom * 1.12, 0.2, 3));
      }
      if (cmd && e.key === "-") {
        e.preventDefault();
        const rect = wrapRef.current?.getBoundingClientRect();
        if (!rect) return;
        zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, clamp(viewport.zoom / 1.12, 0.2, 3));
      }
      if (e.key === "0") {
        e.preventDefault();
        const rect = wrapRef.current?.getBoundingClientRect();
        if (!rect) return;
        zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, 1);
      }
      if (e.key === "1" && e.shiftKey) {
        e.preventDefault();
        fitToView();
      }
    }

    function onKeyUp(e: KeyboardEvent): void {
      if (e.code === "Space") setIsSpaceDown(false);
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [fitToView, viewport.zoom, zoomAt]);

  const createBoard = React.useCallback(async () => {
    const res = await fetch(`${API}/api/canvas/boards`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Untitled" }),
    });
    if (!res.ok) return;
    const b = (await res.json()) as Board;
    setBoardId(b.id);
    setBoardTitle(b.title || "Untitled");
    setViewport(b.viewport ?? { x: 420, y: 240, zoom: 1 });
    setElements(b.elements ?? []);
    setSelectedId(null);
    await refreshBoards(b.id);
  }, [refreshBoards]);

  const deleteCurrentBoard = React.useCallback(async () => {
    if (!boardId) return;
    await fetch(`${API}/api/canvas/boards/${boardId}`, { method: "DELETE" });
    await refreshBoards();
  }, [boardId, refreshBoards]);

  const addElementAtCenter = React.useCallback((type: Exclude<ElementType, "image">) => {
    const node: CanvasElement = {
      id: uid(),
      type,
      x: 260,
      y: 180,
      w: type === "line" ? 240 : 240,
      h: type === "line" ? 6 : 140,
      text: type === "note" ? "便签" : type === "text" ? "文本" : "",
      image_url: "",
    };
    setElements((prev) => [...prev, node]);
    setSelectedId(node.id);
  }, []);

  const importImageFile = React.useCallback((file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const data = String(reader.result || "");
      if (!data) return;
      setElements((prev) => [...prev, { id: uid(), type: "image", x: 240, y: 180, w: 440, h: 300, text: "", image_url: data }]);
    };
    reader.readAsDataURL(file);
  }, []);

  const onCanvasMouseDown = (e: React.MouseEvent<HTMLElement>): void => {
    if (e.button !== 0 && e.button !== 1) return;
    if (isPanMode || e.button === 1) {
      panRef.current = { startX: e.clientX, startY: e.clientY, vx: viewport.x, vy: viewport.y };
      return;
    }
    if (tool === "note" || tool === "text" || tool === "rect" || tool === "line") {
      addElementAtCenter(tool);
      return;
    }
    setSelectedId(null);
  };

  const onWheel = (e: React.WheelEvent<HTMLElement>): void => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      const factor = Math.exp(-e.deltaY * 0.0015);
      const nextZoom = clamp(viewport.zoom * factor, 0.2, 3);
      zoomAt(e.clientX, e.clientY, nextZoom);
      return;
    }
    setViewport((v) => ({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY }));
  };

  const runGenerate = React.useCallback(async () => {
    if (!boardId || !instruction.trim()) return;
    setLoading(true);
    setError("");
    try {
      const modeHint = runMode === "think" ? "Use careful reasoning and strict requirement fidelity." : "Prioritize speed and concise prompt refinement.";
      const res = await fetch(`${API}/api/canvas/boards/${boardId}/command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction: `${instruction}\n\n[mode]\n${modeHint}`,
          reference_image_data_url: refImageDataUrl,
          aspect_ratio: selectedRatio,
          image_size: selectedSize,
          image_model: selectedModel.value,
        }),
      });
      const data = (await res.json()) as CommandResponse | { detail?: string };
      if (!res.ok) throw new Error((data as { detail?: string }).detail || "生成失败");
      const result = data as CommandResponse;
      setOptimizedPrompt(result.optimized_prompt);
      setNegativePrompt(result.negative_prompt);
      setElements((prev) => (prev.some((el) => el.id === result.added_element.id) ? prev : [...prev, result.added_element]));
      setSelectedId(result.added_element.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setLoading(false);
    }
  }, [boardId, instruction, refImageDataUrl, runMode, selectedModel.value, selectedRatio, selectedSize]);

  return (
    <div className="app-root">
      <section
        ref={wrapRef}
        className={`canvas-wrap ${isPanMode ? "pan-mode" : ""} ${isPanning ? "panning" : ""}`}
        onMouseDown={onCanvasMouseDown}
        onWheel={onWheel}
      >
        <div className="menu-anchor">
          <button type="button" className="menu-trigger" onClick={() => setMenuOpen((v) => !v)}>⦿</button>
          {menuOpen ? (
            <div className="menu-panel">
              <button type="button" onClick={() => window.location.reload()}><span>主页</span></button>
              <button type="button" onClick={() => setMenuOpen((v) => !v)}><span>项目库</span></button>
              <hr />
              <button type="button" onClick={() => void createBoard()}><span>新建项目</span></button>
              <button type="button" onClick={() => void deleteCurrentBoard()}><span>删除当前项目</span></button>
              <hr />
              <button type="button" onClick={() => fileInputRef.current?.click()}><span>导入图片</span></button>
              <hr />
              <button type="button" onClick={() => fitToView()}><span>适配画布</span><span>⇧ 1</span></button>
            </div>
          ) : null}
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importImageFile(f);
            e.currentTarget.value = "";
          }}
        />

        <div className="board-head">
          <h1>{boardTitle}</h1>
          <span>{Math.round(viewport.zoom * 100)}%</span>
        </div>

        <div className="zoom-controls">
          <button type="button" onClick={() => setViewport((v) => ({ ...v, zoom: clamp(v.zoom / 1.12, 0.2, 3) }))}>-</button>
          <button type="button" onClick={() => fitToView()}>Fit</button>
          <button type="button" onClick={() => setViewport((v) => ({ ...v, zoom: clamp(v.zoom * 1.12, 0.2, 3) }))}>+</button>
        </div>

        <div ref={canvasRef} className="canvas-surface" style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})` }}>
          {elements.map((el) => {
            const selected = selectedId === el.id;
            return (
              <article
                key={el.id}
                className={`node ${el.type}${selected ? " selected" : ""}`}
                style={{ left: el.x, top: el.y, width: el.w, height: el.h }}
                onMouseDown={(e) => {
                  e.stopPropagation();
                  setSelectedId(el.id);
                  if (tool !== "select" || isSpaceDown) return;
                  dragRef.current = { id: el.id, startClientX: e.clientX, startClientY: e.clientY, startX: el.x, startY: el.y };
                }}
                onDoubleClick={() => {
                  if (el.type === "text" || el.type === "note") {
                    const value = window.prompt("编辑文本", el.text) ?? el.text;
                    setElements((prev) => prev.map((n) => (n.id === el.id ? { ...n, text: value } : n)));
                  }
                }}
              >
                {el.type === "image" ? <img src={el.image_url} alt="generated" /> : null}
                {el.type === "line" ? <div className="line-node" /> : null}
                {el.type !== "image" && el.type !== "line" ? <pre>{el.text}</pre> : null}
                {selected && el.type !== "line" ? (
                  <>
                    {(["nw", "ne", "sw", "se"] as ResizeCorner[]).map((corner) => (
                      <span
                        key={corner}
                        className={`resize-handle ${corner}`}
                        onMouseDown={(e) => {
                          e.stopPropagation();
                          resizeRef.current = {
                            id: el.id,
                            corner,
                            startClientX: e.clientX,
                            startClientY: e.clientY,
                            startX: el.x,
                            startY: el.y,
                            startW: el.w,
                            startH: el.h,
                          };
                        }}
                      />
                    ))}
                  </>
                ) : null}
              </article>
            );
          })}
        </div>

        <div className="bottom-tools icon-mode" role="toolbar" aria-label="canvas tools">
          <button type="button" title="Select (V)" className={tool === "select" ? "active" : ""} onClick={() => setTool("select")}>▸</button>
          <button type="button" title="Hand (H / Space)" className={tool === "hand" ? "active" : ""} onClick={() => setTool("hand")}>◍</button>
          <button type="button" title="Image" onClick={() => fileInputRef.current?.click()}>▣</button>
          <span className="tool-sep" aria-hidden />
          <button type="button" title="Note" className={tool === "note" ? "active" : ""} onClick={() => setTool("note")}>⌗</button>
          <button type="button" title="Rect" className={tool === "rect" ? "active" : ""} onClick={() => setTool("rect")}>▢</button>
          <button type="button" title="Line" className={tool === "line" ? "active" : ""} onClick={() => setTool("line")}>／</button>
          <button type="button" title="Text" className={tool === "text" ? "active" : ""} onClick={() => setTool("text")}>T</button>
        </div>

        <button type="button" className="shortcut-fab" onClick={() => setShortcutOpen((v) => !v)}>?</button>
        {shortcutOpen ? (
          <div className="shortcut-overlay">
            <strong>快捷键</strong>
            <span>Space + 拖拽: 临时抓手</span>
            <span>滚轮: 平移画布</span>
            <span>Ctrl/Cmd + 滚轮: 缩放到指针</span>
            <span>Shift + 1: 适配画布</span>
            <span>Ctrl/Cmd + +/-: 缩放</span>
          </div>
        ) : null}
      </section>

      <aside className="right-panel">
        <div className="panel-topbar">
          <h3 className="panel-title">新对话</h3>
          <div className="panel-icons">
            <button type="button" title="新建" aria-label="新建">⊕</button>
            <button type="button" title="分享" aria-label="分享">⤴</button>
            <button type="button" title="历史" aria-label="历史">↦</button>
          </div>
        </div>

        <section className="skills-wrap">
          <p>试试这些 Lovart Skills</p>
          <div className="skills-grid">
            <button type="button" onClick={() => setInstruction("科技产品KV，未来感，硬朗材质，强对比灯光")}>社媒轮播图</button>
            <button type="button" onClick={() => setInstruction("社交媒体封面，品牌主视觉，冲击感构图")}>社交媒体</button>
            <button type="button" onClick={() => setInstruction("高端品牌logo设计，专业、平面、现代")}>Logo 与品牌</button>
            <button type="button" onClick={() => setInstruction("分镜故事板，电影感镜头语言")}>分镜故事板</button>
            <button type="button" onClick={() => setInstruction("营销宣传册封面，清晰主体，商业排版")}>营销宣传册</button>
            <button type="button" onClick={() => setInstruction("亚马逊产品主图，高对比，白底规范")}>亚马逊产品图</button>
          </div>
        </section>

        <div className="composer-wrap">
          <textarea
            className="composer-input"
            placeholder='Start with an idea, or type "@" to mention'
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (!loading && instruction.trim()) void runGenerate();
              }
            }}
          />

          <div className="composer-actions" ref={composerActionsRef}>
            <button type="button" className="icon-pill tip" data-tip="Upload file" onClick={() => refInputRef.current?.click()}>⌂</button>
            <button type="button" className="agent-pill">✧ Agent</button>

            <div className="tool-cluster">
              <div className="tool-anchor">
                <button type="button" className="tool-btn tip" data-tip={`模式: ${modeLabel}`} onClick={() => setOpenToolMenu((v) => (v === "mode" ? null : "mode"))}>◌</button>
                {openToolMenu === "mode" ? (
                  <div className="tool-menu">
                    <button type="button" onClick={() => { setRunMode("think"); setOpenToolMenu(null); }}>思考模式</button>
                    <button type="button" onClick={() => { setRunMode("fast"); setOpenToolMenu(null); }}>快速模式</button>
                  </div>
                ) : null}
              </div>

              <div className="tool-anchor">
                <button type="button" className="tool-btn tip" data-tip={`模型: ${selectedModel.label}`} onClick={() => setOpenToolMenu((v) => (v === "model" ? null : "model"))}>◇</button>
                {openToolMenu === "model" ? (
                  <div className="tool-menu">
                    {MODEL_OPTIONS.map((model, idx) => (
                      <button key={model.value} type="button" onClick={() => { setModelIndex(idx); setOpenToolMenu(null); }}>{model.label}</button>
                    ))}
                  </div>
                ) : null}
              </div>

              <div className="tool-anchor">
                <button type="button" className="tool-btn tip" data-tip={`比例: ${selectedRatio}`} onClick={() => setOpenToolMenu((v) => (v === "ratio" ? null : "ratio"))}>◍</button>
                {openToolMenu === "ratio" ? (
                  <div className="tool-menu">
                    {RATIO_OPTIONS.map((ratio, idx) => (
                      <button key={ratio} type="button" onClick={() => { setRatioIndex(idx); setOpenToolMenu(null); }}>{ratio}</button>
                    ))}
                  </div>
                ) : null}
              </div>

              <div className="tool-anchor">
                <button type="button" className="tool-btn tip" data-tip={`分辨率: ${selectedSize}`} onClick={() => setOpenToolMenu((v) => (v === "size" ? null : "size"))}>⌁</button>
                {openToolMenu === "size" ? (
                  <div className="tool-menu">
                    {SIZE_OPTIONS.map((size, idx) => (
                      <button key={size} type="button" onClick={() => { setSizeIndex(idx); setOpenToolMenu(null); }}>{size}</button>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          <input
            ref={refInputRef}
            type="file"
            accept="image/*"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const reader = new FileReader();
              reader.onload = () => setRefImageDataUrl(String(reader.result || ""));
              reader.readAsDataURL(file);
              e.currentTarget.value = "";
            }}
          />

          {refImageDataUrl ? <img className="ref-img" src={refImageDataUrl} alt="reference" /> : null}
          {optimizedPrompt ? (
            <div className="preview-card">
              <h3>Optimized Prompt</h3>
              <pre>{optimizedPrompt}</pre>
              <h3>Negative Prompt</h3>
              <pre>{negativePrompt || "(none)"}</pre>
            </div>
          ) : null}
          {error ? <p className="error">{error}</p> : null}
        </div>
      </aside>
    </div>
  );
}

export default App;
