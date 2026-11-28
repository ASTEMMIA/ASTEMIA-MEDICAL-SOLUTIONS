import { useState } from "react";
import { api, messageFor } from "../api";
import { Button } from "./ui";

/**
 * Opens a document's original file. The bytes are fetched with the session's
 * token and offered as a download, so they never sit at a shareable URL.
 */
const EXTENSIONS: Record<string, string> = {
  "application/pdf": ".pdf",
  "image/png": ".png",
  "image/jpeg": ".jpg",
  "image/tiff": ".tif",
  "text/plain": ".txt",
};

/** A safe file name: the document's title, without path characters, with its type's extension. */
export function fileName(label: string, mediaType: string): string {
  const base = label.replace(/[\\/:*?"<>|]+/g, " ").trim() || "document";
  return base + (EXTENSIONS[mediaType.split(";")[0]?.trim() ?? ""] ?? "");
}

export function OpenDocument({ id, label }: { id: string; label: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function open() {
    setBusy(true);
    setError(null);
    try {
      const blob = await api<Blob>(`/v1/documents/${id}/content`, { as: "blob" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName(label, blob.type);
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <p>
      <Button variant="secondary" busy={busy} onClick={open}>
        Download the original<span className="visually-hidden">: {label}</span>
      </Button>
      {error && (
        <span className="error-text" role="alert">
          {" "}
          {error}
        </span>
      )}
    </p>
  );
}
