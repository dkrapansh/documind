import { useCallback, useEffect, useRef, useState } from "react";
import { useScrollReveal } from "../hooks/useScrollReveal";
import { useAuth } from "../context/AuthContext";
import {
  ApiError,
  listDocuments,
  pollDocumentUntilReady,
  streamQuery,
  uploadDocument,
} from "../api/client";
import { highlightCitations } from "../lib/citationHighlight";
import "./Demo.css";

const PRESETS = {
  answerable: "How many vacation days do new full-time employees get?",
  refuse: "What was Northwind's total revenue in 2019?",
};

const BASE_STEPS = ["embed query", "dense · top 10", "bm25 · top 10", "RRF fuse", "rerank · top 4"];
const SUPPORTED_EXTENSIONS = [".txt", ".pdf", ".docx"];

const COLD_START_NOTICE =
  "Waking the demo up: this host sleeps when idle and the first request can take up to a minute.";
const UNREACHABLE_NOTICE = "Couldn't reach the demo. It may be waking up. Retry in a moment.";

function extensionOf(filename) {
  const i = filename.lastIndexOf(".");
  return i === -1 ? "" : filename.slice(i).toLowerCase();
}

export function Demo() {
  const sectionRef = useRef(null);
  useScrollReveal(sectionRef);
  const { isLoggedIn } = useAuth();

  const [doc, setDoc] = useState(null); // { id, filename, status, chunk_count }
  const [docLoading, setDocLoading] = useState(true);
  const [uploadError, setUploadError] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const [question, setQuestion] = useState(PRESETS.answerable);
  const [litSteps, setLitSteps] = useState(0); // 0..BASE_STEPS.length, then final step separately
  const [finalStep, setFinalStep] = useState(null); // { label, ok }
  const [answer, setAnswer] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sources, setSources] = useState(null); // null = not yet known
  const [refused, setRefused] = useState(false);
  const [asking, setAsking] = useState(false);
  const [notice, setNotice] = useState(null); // cold-start / error banner
  const [sessionId, setSessionId] = useState(null);

  const abortRef = useRef(null);
  const stepTimerRef = useRef(null);

  // Load whatever the current tenant already has ingested - the shared
  // seeded demo corpus for an anonymous visitor, or a logged-in user's
  // own (initially empty) documents. Re-runs on login/logout since
  // that switches which tenant the session cookie points at.
  useEffect(() => {
    let cancelled = false;
    setDocLoading(true);
    setDoc(null);
    listDocuments({ onColdStart: () => !cancelled && setNotice(COLD_START_NOTICE) })
      .then((docs) => {
        if (cancelled) return;
        setNotice(null);
        const ready = docs.find((d) => d.status === "ready");
        setDoc(ready ?? docs[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setNotice(UNREACHABLE_NOTICE);
      })
      .finally(() => {
        if (!cancelled) setDocLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn]);

  const handleFiles = useCallback((files) => {
    const file = files?.[0];
    if (!file) return;
    setUploadError(null);

    if (!SUPPORTED_EXTENSIONS.includes(extensionOf(file.name))) {
      setUploadError(`Unsupported file type. Supported: ${SUPPORTED_EXTENSIONS.join(", ")}`);
      return;
    }

    setDoc({ filename: file.name, status: "pending", chunk_count: 0 });
    setNotice(null);

    uploadDocument(file, { onColdStart: () => setNotice(COLD_START_NOTICE) })
      .then((created) => {
        setNotice(null);
        setDoc(created);
        return pollDocumentUntilReady(created.id, { onTick: (d) => setDoc(d) });
      })
      .catch((err) => {
        setNotice(null);
        setUploadError(err instanceof ApiError ? err.message : "Upload failed. Try again.");
      });
  }, []);

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const resetOutput = () => {
    setLitSteps(0);
    setFinalStep(null);
    setAnswer("");
    setSources(null);
    setRefused(false);
  };

  const runQuestion = useCallback(
    (q) => {
      if (asking) return;
      abortRef.current?.();
      clearInterval(stepTimerRef.current);

      setQuestion(q);
      resetOutput();
      setAsking(true);
      setStreaming(true);
      setNotice(null);

      let i = 0;
      stepTimerRef.current = setInterval(() => {
        i += 1;
        setLitSteps(Math.min(i, BASE_STEPS.length));
        if (i >= BASE_STEPS.length) clearInterval(stepTimerRef.current);
      }, 230);

      let gotSources = false;

      abortRef.current = streamQuery(q, {
        sessionId,
        onColdStart: () => setNotice(COLD_START_NOTICE),
        onSources: (payload) => {
          gotSources = true;
          clearInterval(stepTimerRef.current);
          setLitSteps(BASE_STEPS.length);
          setNotice(null);

          if (!payload.length) {
            setRefused(true);
            setFinalStep({ label: "below 0.70 threshold", ok: false });
          } else {
            const top = payload[0]?.confidence;
            setSources(payload);
            setFinalStep(
              top != null
                ? { label: `${top.toFixed(2)} ≥ 0.70`, ok: true }
                : { label: "reranked · top 4", ok: true }
            );
          }
        },
        onSession: (id) => setSessionId(id),
        onDelta: (text) => setAnswer((prev) => prev + text),
        onDone: () => {
          setStreaming(false);
          setAsking(false);
        },
        onError: (err) => {
          if (!gotSources) clearInterval(stepTimerRef.current);
          setStreaming(false);
          setAsking(false);
          setNotice(err instanceof ApiError && !err.coldStart ? err.message : UNREACHABLE_NOTICE);
        },
      });
    },
    [asking, sessionId]
  );

  useEffect(() => () => {
    abortRef.current?.();
    clearInterval(stepTimerRef.current);
  }, []);

  const citedSegments = !streaming && !refused && sources ? highlightCitations(answer, sources) : null;

  return (
    <section className="demo-sec" id="demo" ref={sectionRef}>
      <div className="wrap">
        <div className="sec-eyebrow reveal">Live</div>
        <h2 className="sec-h reveal">Ask the handbook something.</h2>

        <div className="demo-wrap reveal">
          <div className="demo-top">
            <DocChip doc={doc} loading={docLoading} />
            <div className="mono demo-tenant">tenant: {isLoggedIn ? "you" : "demo"}</div>
          </div>

          <div
            className={`dropzone${dragOver ? " over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
          >
            <span>Drop a .txt / .pdf / .docx to ask questions about your own document</span>
            <label className="browse">
              browse
              <input
                type="file"
                accept={SUPPORTED_EXTENSIONS.join(",")}
                onChange={(e) => handleFiles(e.target.files)}
                hidden
              />
            </label>
          </div>
          {uploadError && <div className="upload-error mono">{uploadError}</div>}

          <div className="demo-body">
            {notice && <div className="notice mono">{notice}</div>}

            <form
              className="ask"
              onSubmit={(e) => {
                e.preventDefault();
                runQuestion(question);
              }}
            >
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                aria-label="Ask a question"
              />
              <button type="submit" disabled={asking}>
                {asking ? "Asking…" : "Ask"}
              </button>
            </form>

            <div className="presets">
              <button
                type="button"
                className="preset"
                disabled={asking}
                onClick={() => runQuestion(PRESETS.answerable)}
              >
                ↳ answerable example
              </button>
              <button
                type="button"
                className="preset"
                disabled={asking}
                onClick={() => runQuestion(PRESETS.refuse)}
              >
                ↳ out-of-scope example
              </button>
            </div>

            <PipelineSteps lit={litSteps} finalStep={finalStep} />

            <div className="out">
              {refused ? (
                <div className="out-refuse">
                  <div className="r-main">
                    I can&apos;t answer that confidently from the provided documents.
                  </div>
                  <div className="r-meta">
                    best reranked score below the 0.70 threshold · refused before any model call
                  </div>
                </div>
              ) : answer ? (
                <div className="out-answer">
                  {citedSegments
                    ? citedSegments.map((seg, i) =>
                        seg.sourceId ? (
                          <span className="cited" key={i}>
                            {seg.text}
                          </span>
                        ) : (
                          <span key={i}>{seg.text}</span>
                        )
                      )
                    : answer}
                  {streaming && <span className="cursor" />}
                </div>
              ) : null}
            </div>

            {sources && (
              <div className="out-sources show">
                {sources.map((s) => (
                  <div className="chunk" key={s.id}>
                    <div className="chunk-head">
                      <span className="chunk-id mono">
                        doc {s.document_id} · chunk {s.chunk_index}
                      </span>
                      {s.confidence != null && (
                        <span className="chunk-score mono">{s.confidence.toFixed(2)}</span>
                      )}
                    </div>
                    <div className="chunk-txt">{s.text}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function DocChip({ doc, loading }) {
  if (loading) {
    return (
      <div className="doc-chip">
        <span className="doc-dot pending" /> checking for a sample document…
      </div>
    );
  }
  if (!doc) {
    return (
      <div className="doc-chip">
        <span className="doc-dot pending" /> no document yet, drop one below
      </div>
    );
  }
  const isReady = doc.status === "ready";
  return (
    <div className="doc-chip">
      <span className={`doc-dot${isReady ? "" : " pending"}`} /> {doc.filename}{" "}
      <span className="mono">
        · {doc.status}
        {isReady ? ` · ${doc.chunk_count} chunks` : "…"}
      </span>
    </div>
  );
}

function PipelineSteps({ lit, finalStep }) {
  const steps = [...BASE_STEPS, finalStep?.label ?? "score check"];
  return (
    <div className="pipe">
      {steps.map((label, i) => {
        const isFinal = i === steps.length - 1;
        const on = isFinal ? finalStep != null : i < lit;
        const failing = isFinal && finalStep && !finalStep.ok;
        return (
          <div className={`step${on ? " on" : ""}${failing ? " fail" : ""}`} key={i}>
            <span className="sdot" />
            {label}
          </div>
        );
      })}
    </div>
  );
}
