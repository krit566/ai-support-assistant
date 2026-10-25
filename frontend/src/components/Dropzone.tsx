// File picker that also accepts drag and drop. The real checks (type, size, content) happen on the server;
// this only filters obvious mistakes early so the user gets an instant message.

import { useId, useRef, useState, type DragEvent } from "react";

const ACCEPT = [".pdf", ".md", ".markdown", ".txt"];

interface Props {
  maxMb: number;
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

export function Dropzone({ maxMb, onFiles, disabled }: Props) {
  const [over, setOver] = useState(false);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const id = useId();

  function take(list: FileList | null) {
    if (!list?.length) return;
    const files = Array.from(list);
    const bad = files.find((f) => !ACCEPT.some((ext) => f.name.toLowerCase().endsWith(ext)));
    const big = files.find((f) => f.size > maxMb * 1024 * 1024);
    if (bad) return setProblem(`${bad.name}: only PDF, Markdown and text files are supported.`);
    if (big) return setProblem(`${big.name}: larger than ${maxMb} MB.`);
    setProblem("");
    onFiles(files);
  }

  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (!disabled) take(e.dataTransfer.files);
  };

  return (
    <div>
      <div
        className={`dropzone${over ? " over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
      >
        <span className="drop-icon" aria-hidden="true">
          ⇪
        </span>
        <p>
          <strong>Drop files here</strong> or{" "}
          <button type="button" className="link" onClick={() => input.current?.click()} disabled={disabled}>
            choose files
          </button>
        </p>
        <p className="muted small">PDF, Markdown or text · up to {maxMb} MB · uploading a file with the same name creates a new version</p>
        <label htmlFor={id} className="sr-only">
          Upload documents
        </label>
        <input
          id={id}
          ref={input}
          type="file"
          multiple
          accept={ACCEPT.join(",")}
          className="sr-only"
          onChange={(e) => {
            take(e.target.files);
            e.target.value = "";
          }}
          disabled={disabled}
        />
      </div>
      {problem && (
        <p className="error" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}
