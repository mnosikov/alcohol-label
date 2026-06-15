import { ImageUp, RotateCcw, RotateCw, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type PointerEvent } from "react";

export type ImageAsset = {
  key: string;
  label: string;
  image_url: string | null;
};

type Props = {
  imageUrl: string;
  images?: ImageAsset[];
  onReplaceImage?: (imageKey: string, file: File) => Promise<void>;
  replaceDisabled?: boolean;
  scanning?: boolean;
};

const EMPTY_IMAGE_ASSETS: ImageAsset[] = [];

type PanState = {
  pointerId: number;
  startX: number;
  startY: number;
  scrollLeft: number;
  scrollTop: number;
};

export default function LabelImageViewer({
  imageUrl,
  images = EMPTY_IMAGE_ASSETS,
  onReplaceImage,
  replaceDisabled = false,
  scanning = false,
}: Props) {
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [replacingImageKey, setReplacingImageKey] = useState<string | null>(null);
  const [isPanning, setIsPanning] = useState(false);
  const viewerCanvasRef = useRef<HTMLDivElement | null>(null);
  const panStateRef = useRef<PanState | null>(null);
  const imageOptions = useMemo(
    () => imageOptionsForViewer(imageUrl, images),
    [imageUrl, images],
  );
  const [activeImageKey, setActiveImageKey] = useState(imageOptions[0]?.key ?? "front");
  const selectedImage = imageOptions.find((image) => image.key === activeImageKey) ?? imageOptions[0];
  const selectedImageLabel = labelForImage(selectedImage);
  const selectedImageMissing = !selectedImage.image_url;
  const selectedImageIsReplacing = replacingImageKey === selectedImage.key;
  const selectedImageAction = selectedImageMissing ? "Add image" : "Replace image";
  const showScanning = scanning && !selectedImageMissing;
  const stageScale = Math.max(1, zoom);
  const imageScale = zoom < 1 ? zoom : 1;

  useEffect(() => {
    setActiveImageKey((current) =>
      imageOptions.some((image) => image.key === current) ? current : "front",
    );
    setZoom(1);
    setRotation(0);
  }, [imageUrl, images]);

  useEffect(() => {
    const canvas = viewerCanvasRef.current;
    if (!canvas || selectedImageMissing) return;

    window.requestAnimationFrame(() => {
      canvas.scrollLeft = zoom > 1 ? (canvas.scrollWidth - canvas.clientWidth) / 2 : 0;
      canvas.scrollTop = zoom > 1 ? (canvas.scrollHeight - canvas.clientHeight) / 2 : 0;
    });
  }, [activeImageKey, rotation, selectedImageMissing, zoom]);

  useEffect(() => {
    if (zoom > 1 && !selectedImageMissing) return;
    panStateRef.current = null;
    setIsPanning(false);
  }, [selectedImageMissing, zoom]);

  async function handleReplacement(imageKey: string, event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file || !onReplaceImage) return;
    setReplacingImageKey(imageKey);
    try {
      await onReplaceImage(imageKey, file);
      setActiveImageKey(imageKey);
    } catch {
      // The case detail panel owns the visible error state.
    } finally {
      setReplacingImageKey(null);
    }
  }

  function startPan(event: PointerEvent<HTMLDivElement>) {
    if (zoom <= 1 || selectedImageMissing || event.button !== 0) return;

    const canvas = event.currentTarget;
    panStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: canvas.scrollLeft,
      scrollTop: canvas.scrollTop,
    };
    canvas.setPointerCapture(event.pointerId);
    setIsPanning(true);
    event.preventDefault();
  }

  function movePan(event: PointerEvent<HTMLDivElement>) {
    const panState = panStateRef.current;
    if (!panState || panState.pointerId !== event.pointerId) return;

    const canvas = event.currentTarget;
    canvas.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX);
    canvas.scrollTop = panState.scrollTop - (event.clientY - panState.startY);
    event.preventDefault();
  }

  function endPan(event: PointerEvent<HTMLDivElement>) {
    const panState = panStateRef.current;
    if (!panState || panState.pointerId !== event.pointerId) return;

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    panStateRef.current = null;
    setIsPanning(false);
  }

  return (
    <section className="image-viewer">
      <div className="viewer-toolbar">
        <div className="image-tab-row">
          <div className="image-tabs" role="tablist" aria-label="Label images">
            {imageOptions.map((image) => (
              <button
                className={image.key === activeImageKey ? "is-active" : ""}
                key={image.key}
                type="button"
                role="tab"
                aria-selected={image.key === activeImageKey}
                onClick={() => setActiveImageKey(image.key)}
              >
                {labelForImage(image)}
              </button>
            ))}
          </div>
          {onReplaceImage ? (
            <label
              className={`image-action-button ${
                replaceDisabled || selectedImageIsReplacing ? "is-disabled" : ""
              }`}
              title={`${selectedImageAction} for ${selectedImageLabel.toLowerCase()} label`}
            >
              <ImageUp size={15} />
              {selectedImageIsReplacing ? "Uploading..." : selectedImageAction}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                disabled={replaceDisabled || selectedImageIsReplacing}
                onChange={(event) => handleReplacement(selectedImage.key, event)}
              />
            </label>
          ) : null}
        </div>
        <div className="viewer-tool-buttons" aria-label="Image view controls">
          <button title="Zoom out" onClick={() => setZoom((value) => Math.max(0.6, value - 0.2))}>
            <ZoomOut size={16} />
          </button>
          <button title="Zoom in" onClick={() => setZoom((value) => Math.min(2.4, value + 0.2))}>
            <ZoomIn size={16} />
          </button>
          <button title="Rotate clockwise" onClick={() => setRotation((value) => value + 90)}>
            <RotateCw size={16} />
          </button>
          <button title="Rotate counterclockwise" onClick={() => setRotation((value) => value - 90)}>
            <RotateCcw size={16} />
          </button>
        </div>
      </div>
      <div
        className="viewer-canvas"
        data-panning={isPanning ? "true" : undefined}
        data-scanning={showScanning ? "true" : undefined}
        data-zoomed={zoom > 1 ? "true" : undefined}
        onPointerCancel={endPan}
        onPointerDown={startPan}
        onPointerMove={movePan}
        onPointerUp={endPan}
        ref={viewerCanvasRef}
      >
        {selectedImage.image_url ? (
          <div
            className="viewer-image-stage"
            style={{
              height: `${stageScale * 100}%`,
              width: `${stageScale * 100}%`,
            }}
          >
            <img
              src={selectedImage.image_url}
              alt={`${selectedImageLabel} alcohol label artwork`}
              draggable={false}
              style={{ transform: `scale(${imageScale}) rotate(${rotation}deg)` }}
            />
          </div>
        ) : (
          <div className="viewer-empty-state">
            <strong>Rear label image not provided</strong>
            {onReplaceImage ? (
              <label
                className={`image-action-button ${
                  replaceDisabled || selectedImageIsReplacing ? "is-disabled" : ""
                }`}
                >
                  <ImageUp size={15} />
                {selectedImageIsReplacing ? "Uploading..." : "Add image"}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  disabled={replaceDisabled || selectedImageIsReplacing}
                  onChange={(event) => handleReplacement("back", event)}
                />
              </label>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}

function imageOptionsForViewer(imageUrl: string, images: ImageAsset[]): ImageAsset[] {
  const front = images.find((image) => image.key === "front") ?? {
    key: "front",
    label: "Front",
    image_url: imageUrl,
  };
  const rear = images.find((image) => image.key === "back") ?? {
    key: "back",
    label: "Rear",
    image_url: null,
  };
  return [front, rear];
}

function labelForImage(image: ImageAsset): string {
  if (image.key === "front") return "Front";
  if (image.key === "back") return "Rear";
  return image.label;
}
