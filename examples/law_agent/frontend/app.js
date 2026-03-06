const { useEffect, useMemo, useRef, useState } = React;

const tabs = [
  { id: "viewer", label: "Document" },
  { id: "history", label: "History" },
  { id: "rag", label: "RAG" },
  { id: "playbook", label: "Playbook" },
  { id: "vectors", label: "Vectors" },
  { id: "auth", label: "Auth" },
];

function findingKey(finding) {
  return `${finding.clause_id || ""}|${finding.issue || ""}|${finding.excerpt || ""}`;
}

async function apiRequest(path, options = {}, token = "") {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`Network request failed for ${path}: ${reason}`);
  }

  const contentType = response.headers.get("content-type") || "";
  let data = {};
  if (contentType.includes("application/json")) {
    data = await response.json();
  } else {
    const text = await response.text();
    data = { detail: text || `Unexpected response type from ${path}.` };
  }

  if (!response.ok) {
    throw new Error(data.detail || `Request failed for ${path} with status ${response.status}.`);
  }
  return data;
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch (_error) {
    return iso;
  }
}

function renderHighlightedClauseText(clauseText, excerpt) {
  if (!excerpt || !clauseText) {
    return clauseText || "";
  }
  const index = clauseText.toLowerCase().indexOf(excerpt.toLowerCase());
  if (index < 0) {
    return clauseText;
  }
  const before = clauseText.slice(0, index);
  const hit = clauseText.slice(index, index + excerpt.length);
  const after = clauseText.slice(index + excerpt.length);
  return (
    <>
      {before}
      <mark>{hit}</mark>
      {after}
    </>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState("auth");
  const [token, setToken] = useState(localStorage.getItem("law_agent_token") || "");
  const [tenantName, setTenantName] = useState(localStorage.getItem("law_agent_tenant") || "");
  const [status, setStatus] = useState({ message: "Idle.", kind: "" });

  const [signup, setSignup] = useState({ company: "", email: "", password: "" });
  const [login, setLogin] = useState({ email: "", password: "" });
  const [authMode, setAuthMode] = useState("login");

  const [playbookText, setPlaybookText] = useState("");
  const [docs, setDocs] = useState([]);
  const [vectorRows, setVectorRows] = useState([]);
  const [vectorStats, setVectorStats] = useState({ chunk_count: 0, files: [] });

  const [reportStudioOpen, setReportStudioOpen] = useState(false);
  const [reviewInput, setReviewInput] = useState("");
  const [reviewFile, setReviewFile] = useState(null);
  const [reviewJob, setReviewJob] = useState({
    open: false,
    jobId: "",
    status: "idle",
    events: [],
    error: "",
  });

  const [historyRows, setHistoryRows] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedRunResult, setSelectedRunResult] = useState(null);
  const [editedClauses, setEditedClauses] = useState([]);
  const [commentThreads, setCommentThreads] = useState({});
  const [draftNotes, setDraftNotes] = useState({});
  const [clauseFilter, setClauseFilter] = useState("all");
  const [activeCommentKey, setActiveCommentKey] = useState("");
  const commentItemRefs = useRef({});

  const isAuthed = !!token;

  useEffect(() => {
    if (isAuthed && activeTab === "auth") {
      setActiveTab("history");
    }
    if (!isAuthed && activeTab !== "auth") {
      setActiveTab("auth");
    }
  }, [isAuthed, activeTab]);

  const statusClass = useMemo(() => {
    if (status.kind === "ok") return "status ok";
    if (status.kind === "err") return "status err";
    return "status";
  }, [status.kind]);

  function saveAuth(auth) {
    setToken(auth.token);
    setTenantName(auth.tenant_name);
    localStorage.setItem("law_agent_token", auth.token);
    localStorage.setItem("law_agent_tenant", auth.tenant_name);
  }

  function clearAuth() {
    setToken("");
    setTenantName("");
    localStorage.removeItem("law_agent_token");
    localStorage.removeItem("law_agent_tenant");
    setStatus({ message: "Signed out.", kind: "ok" });
  }

  async function loadWorkspace(tokenToUse = token) {
    await Promise.all([
      loadPlaybook(tokenToUse),
      loadDocs(tokenToUse),
      loadVectors(tokenToUse),
      loadReviewHistory(tokenToUse),
    ]);
  }

  async function handleSignup(event) {
    event.preventDefault();
    try {
      const data = await apiRequest("/api/auth/signup", {
        method: "POST",
        body: JSON.stringify(signup),
      });
      saveAuth(data);
      await loadWorkspace(data.token);
      setStatus({ message: "Account created. Workspace loaded.", kind: "ok" });
      setActiveTab("history");
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function handleLogin(event) {
    event.preventDefault();
    try {
      const data = await apiRequest("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(login),
      });
      saveAuth(data);
      await loadWorkspace(data.token);
      setStatus({ message: "Signed in. Workspace loaded.", kind: "ok" });
      setActiveTab("history");
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function loadPlaybook(authToken = token) {
    const data = await apiRequest("/api/playbook", {}, authToken);
    setPlaybookText(JSON.stringify(data.playbook, null, 2));
  }

  async function savePlaybook() {
    try {
      const parsed = JSON.parse(playbookText);
      await apiRequest(
        "/api/playbook",
        { method: "PUT", body: JSON.stringify({ playbook: parsed }) },
        token
      );
      setStatus({ message: "Playbook saved.", kind: "ok" });
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function loadDocs(authToken = token) {
    const data = await apiRequest("/api/rag/documents", {}, authToken);
    setDocs(data.documents || []);
  }

  async function uploadDocs(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    try {
      const encoded = await Promise.all(
        files.map(
          (file) =>
            new Promise((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => {
                const result = String(reader.result || "");
                const base64 = result.includes(",") ? result.split(",", 2)[1] : "";
                resolve({
                  filename: file.name,
                  content_type: file.type || "application/octet-stream",
                  base64_data: base64,
                });
              };
              reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
              reader.readAsDataURL(file);
            })
        )
      );

      await apiRequest(
        "/api/rag/documents",
        { method: "POST", body: JSON.stringify({ documents: encoded }) },
        token
      );
      await Promise.all([loadDocs(), loadVectors()]);
      setStatus({ message: "Documents uploaded.", kind: "ok" });
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function rebuildIndex() {
    try {
      const data = await apiRequest("/api/rag/reindex", { method: "POST", body: "{}" }, token);
      await loadVectors();
      if (!data.scope) {
        setStatus({ message: "RAG index rebuild finished with no chunks.", kind: "err" });
      } else {
        setStatus({ message: "RAG index rebuilt.", kind: "ok" });
      }
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function loadVectors(authToken = token) {
    const data = await apiRequest("/api/rag/index", {}, authToken);
    setVectorRows(data.chunks || []);
    setVectorStats({ chunk_count: data.chunk_count || 0, files: data.files || [] });
  }

  async function loadReviewHistory(authToken = token) {
    try {
      const data = await apiRequest("/api/review/history", {}, authToken);
      const rows = data.history || [];
      setHistoryRows(rows);
      if (!selectedRunId && rows.length) {
        setSelectedRunId(rows[0].run_id);
        await loadReviewResult(rows[0].run_id, authToken);
      }
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function loadReviewResult(runId, authToken = token) {
    try {
      const data = await apiRequest(`/api/review/history/${runId}`, {}, authToken);
      setSelectedRunResult(data);
      setEditedClauses((data.clauses || []).map((clause) => ({ ...clause })));
      setSelectedRunId(runId);

      const findings = (data.report && data.report.findings) || [];
      const persisted = JSON.parse(localStorage.getItem(`law_agent_comments_${runId}`) || "{}");
      const initialThreads = {};
      findings.forEach((finding) => {
        const key = findingKey(finding);
        const prior = persisted[key] || {};
        initialThreads[key] = {
          resolved: !!prior.resolved,
          notes: Array.isArray(prior.notes) ? prior.notes : [],
        };
      });
      setCommentThreads(initialThreads);
      setDraftNotes({});
      setClauseFilter("all");
      setActiveCommentKey("");
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  function focusComment(finding) {
    const key = findingKey(finding);
    setActiveCommentKey(key);
    setTimeout(() => {
      const node = commentItemRefs.current[key];
      if (node && typeof node.scrollIntoView === "function") {
        node.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 0);
  }

  function persistCommentThreads(runId, threads) {
    if (!runId) return;
    localStorage.setItem(`law_agent_comments_${runId}`, JSON.stringify(threads));
  }

  function toggleResolved(finding) {
    const key = findingKey(finding);
    setCommentThreads((prev) => {
      const next = {
        ...prev,
        [key]: {
          resolved: !((prev[key] && prev[key].resolved) || false),
          notes: (prev[key] && prev[key].notes) || [],
        },
      };
      persistCommentThreads(selectedRunId, next);
      return next;
    });
  }

  function addThreadNote(finding) {
    const key = findingKey(finding);
    const text = (draftNotes[key] || "").trim();
    if (!text) return;
    setCommentThreads((prev) => {
      const base = prev[key] || { resolved: false, notes: [] };
      const next = {
        ...prev,
        [key]: {
          ...base,
          notes: [...(base.notes || []), { text, at: new Date().toISOString() }],
        },
      };
      persistCommentThreads(selectedRunId, next);
      return next;
    });
    setDraftNotes((prev) => ({ ...prev, [key]: "" }));
  }

  async function runReview() {
    if (!reviewInput.trim() && !reviewFile) {
      setStatus({ message: "Paste contract text or upload a file first.", kind: "err" });
      return;
    }

    const startedAt = new Date().toLocaleTimeString();
    setReviewJob({
      open: true,
      jobId: "",
      status: "starting",
      events: [{ stage: "ui", clause_id: "", message: `Generate report clicked at ${startedAt}.` }],
      error: "",
    });

    try {
      let filePayload = {
        contract_filename: "",
        contract_content_type: "",
        contract_base64_data: "",
      };

      if (reviewFile) {
        const encoded = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => {
            const result = String(reader.result || "");
            const base64 = result.includes(",") ? result.split(",", 2)[1] : "";
            resolve({
              contract_filename: reviewFile.name,
              contract_content_type: reviewFile.type || "application/octet-stream",
              contract_base64_data: base64,
            });
          };
          reader.onerror = () => reject(new Error(`Failed to read ${reviewFile.name}`));
          reader.readAsDataURL(reviewFile);
        });
        filePayload = encoded;
      }

      const startData = await apiRequest(
        "/api/review/start",
        {
          method: "POST",
          body: JSON.stringify({ contract_text: reviewInput, trace: false, ...filePayload }),
        },
        token
      );

      setReviewJob((prev) => ({
        ...prev,
        jobId: startData.job_id,
        status: "queued",
        events: [...prev.events, { stage: "queue", clause_id: "", message: `Job: ${startData.job_id}` }],
      }));
      setStatus({ message: "Review started.", kind: "ok" });
      pollReviewStatus(startData.job_id);
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function pollReviewStatus(jobId) {
    let keepPolling = true;
    while (keepPolling) {
      try {
        const data = await apiRequest(`/api/review/status/${jobId}`, {}, token);
        setReviewJob((prev) => {
          const merged = [...(prev.events || []), ...(data.progress_events || [])];
          const seen = new Set();
          const deduped = [];
          for (const event of merged) {
            const key = `${event.stage || ""}|${event.clause_id || ""}|${event.message || ""}`;
            if (seen.has(key)) continue;
            seen.add(key);
            deduped.push(event);
          }
          return { ...prev, status: data.status, events: deduped, error: data.error || "" };
        });

        if (data.status === "completed") {
          const runId = data.result && data.result.run_id;
          if (runId) {
            await loadReviewHistory();
            await loadReviewResult(runId);
            setActiveTab("viewer");
          }
          setReviewJob((prev) => ({ ...prev, status: "completed", open: false }));
          setReportStudioOpen(false);
          setStatus({ message: "Review complete.", kind: "ok" });
          keepPolling = false;
          break;
        }

        if (data.status === "failed") {
          setStatus({ message: `Review failed: ${data.error || "Unknown error."}`, kind: "err" });
          keepPolling = false;
          break;
        }
      } catch (error) {
        setStatus({ message: String(error), kind: "err" });
        keepPolling = false;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  function updateClauseText(clauseId, text) {
    setEditedClauses((prev) => prev.map((c) => (c.id === clauseId ? { ...c, text } : c)));
  }

  function applySuggestedRedline(finding) {
    if (!finding || !finding.clause_id) return;
    setEditedClauses((prev) =>
      prev.map((clause) => {
        if (clause.id !== finding.clause_id) return clause;
        let nextText = clause.text || "";
        if (finding.excerpt && finding.suggested_redline && nextText.includes(finding.excerpt)) {
          nextText = nextText.replace(finding.excerpt, finding.suggested_redline);
        } else if (finding.suggested_redline) {
          nextText = `${nextText}\n\n${finding.suggested_redline}`;
        }
        return { ...clause, text: nextText };
      })
    );
    toggleResolved(finding);
  }

  function rejectSuggestedRedline(finding) {
    toggleResolved(finding);
  }

  function buildExportClauses() {
    const findings = (selectedRunResult && selectedRunResult.report && selectedRunResult.report.findings) || [];
    return editedClauses.map((clause) => {
      const clauseFindings = findings.filter((item) => item.clause_id === clause.id);
      const findingComments = clauseFindings.map(
        (item) => `${item.severity.toUpperCase()}: ${item.issue} - ${item.recommendation}`
      );
      const threadComments = clauseFindings.flatMap((item) => {
        const thread = commentThreads[findingKey(item)] || { notes: [] };
        return (thread.notes || []).map((note) => `Thread: ${note.text}`);
      });
      return {
        id: clause.id,
        heading: clause.heading || "",
        text: clause.text || "",
        comments: [...findingComments, ...threadComments],
      };
    });
  }

  async function exportEdited(format) {
    if (!selectedRunResult || !editedClauses.length) {
      setStatus({ message: "No reviewed document selected.", kind: "err" });
      return;
    }

    try {
      const res = await fetch("/api/review/export", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          filename: (selectedRunResult.input_name || "contract_review").replace(/\.[^.]+$/, ""),
          title: selectedRunResult.input_name || "Contract Review",
          format,
          clauses: buildExportClauses(),
        }),
      });

      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || `Export failed (${res.status})`);
      }

      const blob = await res.blob();
      const extension = format === "docx" ? "docx" : "pdf";
      const filename = `${(selectedRunResult.input_name || "contract_review").replace(/\.[^.]+$/, "")}.${extension}`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setStatus({ message: `Exported ${extension.toUpperCase()} successfully.`, kind: "ok" });
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  function renderAuthPanel() {
    return (
      <div className="workspace-block">
        <h3>Access Portal</h3>
        <div className="auth-card">
          <div className="auth-toggle">
            <button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")}>Login</button>
            <button className={authMode === "signup" ? "active" : ""} onClick={() => setAuthMode("signup")}>Sign up</button>
          </div>

          {authMode === "signup" ? (
            <form onSubmit={handleSignup}>
              <label>Company</label>
              <input value={signup.company} onChange={(e) => setSignup({ ...signup, company: e.target.value })} required />
              <label style={{ marginTop: "8px" }}>Email</label>
              <input type="email" value={signup.email} onChange={(e) => setSignup({ ...signup, email: e.target.value })} required />
              <label style={{ marginTop: "8px" }}>Password</label>
              <input type="password" value={signup.password} onChange={(e) => setSignup({ ...signup, password: e.target.value })} required />
              <div className="actions"><button className="primary" type="submit">Create account</button></div>
            </form>
          ) : (
            <form onSubmit={handleLogin}>
              <label>Email</label>
              <input type="email" value={login.email} onChange={(e) => setLogin({ ...login, email: e.target.value })} required />
              <label style={{ marginTop: "8px" }}>Password</label>
              <input type="password" value={login.password} onChange={(e) => setLogin({ ...login, password: e.target.value })} required />
              <div className="actions"><button className="primary" type="submit">Login</button></div>
            </form>
          )}
        </div>
      </div>
    );
  }

  function renderHistoryPanel() {
    return (
      <div className="workspace-block">
        <div className="history-list-pane">
          <div className="history-pane-head">
            <h3>Document History</h3>
          </div>
          <p className="small">All reviewed docs for this tenant.</p>
          <div className="history-list-main">
            {historyRows.map((row) => (
              <button
                key={row.run_id}
                className={`history-row ${selectedRunId === row.run_id ? "active" : ""}`}
                onClick={async () => {
                  await loadReviewResult(row.run_id);
                  setActiveTab("viewer");
                }}
              >
                <div className="history-row-title">{row.input_name || "Unknown document"}</div>
                <div className="small">{row.overall_risk} risk | {row.findings_count} finding(s)</div>
                <div className="small">{formatDate(row.completed_at)}</div>
                <div className="small">Docs: {(row.docs_checked || []).join(", ") || "No citations"}</div>
                <div style={{ marginTop: "6px" }}>
                  <span className="badge">Open in Document Viewer</span>
                </div>
              </button>
            ))}
            {!historyRows.length && <p className="small">No review history yet.</p>}
          </div>
        </div>
      </div>
    );
  }

  function renderViewerPanel() {
    const findings = (selectedRunResult && selectedRunResult.report && selectedRunResult.report.findings) || [];
    const displayedClauses =
      clauseFilter === "issues"
        ? editedClauses.filter((clause) =>
            findings.some((finding) => finding.clause_id === clause.id)
          )
        : editedClauses;

    return (
      <div className="workspace-block">
        <div className="good-docs-shell">
          <div className="doc-main-pane">
            <div className="doc-main-head">
              <div>
                <h3>{selectedRunResult ? selectedRunResult.input_name || "Reviewed document" : "No document selected"}</h3>
                {selectedRunResult && (
                  <p className="small">
                    Overall risk: {selectedRunResult.report ? selectedRunResult.report.overall_risk : "unknown"} | Findings: {findings.length}
                  </p>
                )}
              </div>
              <div className="actions">
                <button className="secondary" onClick={() => setActiveTab("history")}>Open History</button>
                <button className="secondary" onClick={() => exportEdited("docx")} disabled={!selectedRunResult}>Export DOCX</button>
                <button className="secondary" onClick={() => exportEdited("pdf")} disabled={!selectedRunResult}>Export PDF</button>
              </div>
            </div>
            <div className="filter-row">
              <button
                className={`secondary ${clauseFilter === "all" ? "filter-active" : ""}`}
                onClick={() => setClauseFilter("all")}
              >
                All Clauses
              </button>
              <button
                className={`secondary ${clauseFilter === "issues" ? "filter-active" : ""}`}
                onClick={() => {
                  setClauseFilter("issues");
                  if (findings.length) {
                    focusComment(findings[0]);
                  }
                }}
              >
                Clauses With Issues
              </button>
            </div>

            <div className="docs-canvas-wrap">
              {!selectedRunResult && <p className="small">Select a reviewed document from History.</p>}
              <div className="docs-page">
                <div className="docs-page-header">
                  <h4>{selectedRunResult ? selectedRunResult.input_name || "Contract" : "Contract"}</h4>
                  <p className="small">Full contract view with inline redline alerts.</p>
                </div>
                <div className="doc-view">
                  {displayedClauses.map((clause) => {
                    const clauseFindings = findings.filter((finding) => finding.clause_id === clause.id);
                    const topFinding = clauseFindings[0] || null;
                    return (
                      <div
                        key={clause.id}
                        className={`docs-clause ${clauseFindings.length ? "docs-clause-risky" : ""}`}
                        onClick={() => {
                          if (clauseFindings.length) {
                            focusComment(clauseFindings[0]);
                          }
                        }}
                      >
                        <div className="clause-head">
                          <strong>{clause.id} · {clause.heading}</strong>
                          <span className="badge">
                            {clauseFindings.length ? `${clauseFindings.length} comment(s)` : "No comments"}
                          </span>
                        </div>

                        <div className="clause-body preview-mode">
                          {renderHighlightedClauseText(clause.text, topFinding ? topFinding.excerpt : "")}
                        </div>

                        {clauseFindings.map((finding, idx) => (
                          <div className="inline-redline" key={`${clause.id}_redline_${idx}`}>
                            <div className="inline-redline-head">
                              <span className="inline-redline-label">Suggested edit: {finding.issue}</span>
                              <span className="small">{finding.severity}</span>
                            </div>
                            {finding.excerpt && <del>{finding.excerpt}</del>}
                            {finding.suggested_redline && <ins>{finding.suggested_redline}</ins>}
                            <div className="inline-redline-actions">
                              <button className="secondary" onClick={(e) => { e.stopPropagation(); applySuggestedRedline(finding); }}>Accept</button>
                              <button className="secondary" onClick={(e) => { e.stopPropagation(); rejectSuggestedRedline(finding); }}>Reject</button>
                            </div>
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          <aside className="comments-pane">
            <h4>Comments</h4>
            <p className="small">Resolve issues and apply suggested clause changes.</p>
            <div className="comments-list">
              {findings.map((finding, idx) => {
                const key = findingKey(finding);
                const thread = commentThreads[key] || { resolved: false, notes: [] };
                return (
                  <div
                    className={`comment-card ${thread.resolved ? "comment-resolved" : ""} ${activeCommentKey === key ? "comment-active" : ""}`}
                    key={`${key}_${idx}`}
                    ref={(node) => {
                      if (node) commentItemRefs.current[key] = node;
                    }}
                    onClick={() => setActiveCommentKey(key)}
                  >
                    <div className="comment-head">
                      <strong>{finding.issue}</strong>
                      <span className="badge">{finding.severity}</span>
                    </div>
                    <p className="small">Clause: {finding.clause_id}</p>
                    <p className="small">Excerpt: {finding.excerpt || "n/a"}</p>
                    <p className="small">Recommendation: {finding.recommendation}</p>
                    <p className="small">
                      Suggested clause change: {finding.suggested_redline || "Use recommendation to revise this clause."}
                    </p>
                    {!!(finding.citations || []).length && <p className="small">Sources: {finding.citations.join(", ")}</p>}

                    <div className="actions">
                      <button className="secondary" onClick={() => toggleResolved(finding)}>
                        {thread.resolved ? "Mark Open" : "Resolve"}
                      </button>
                      <button className="secondary" onClick={() => applySuggestedRedline(finding)}>
                        Apply Suggestion
                      </button>
                    </div>

                    <div className="thread-notes">
                      {(thread.notes || []).map((note, noteIdx) => (
                        <div className="thread-note" key={`${key}_note_${noteIdx}`}>
                          <div>{note.text}</div>
                          <div className="small">{formatDate(note.at)}</div>
                        </div>
                      ))}
                    </div>

                    <textarea
                      className="thread-input"
                      placeholder="Add comment"
                      value={draftNotes[key] || ""}
                      onChange={(e) => setDraftNotes((prev) => ({ ...prev, [key]: e.target.value }))}
                    />
                    <button className="secondary" onClick={() => addThreadNote(finding)}>Add Note</button>
                  </div>
                );
              })}
              {!findings.length && <p className="small">No findings available for this document.</p>}
            </div>
          </aside>
        </div>
      </div>
    );
  }

  function renderRagPanel() {
    return (
      <div className="workspace-block">
        <h3>RAG Documents</h3>
        <p className="small">Upload docs and maintain your retrieval corpus.</p>
        <input type="file" multiple onChange={uploadDocs} disabled={!isAuthed} />
        <div className="actions">
          <button className="secondary" onClick={() => loadDocs()} disabled={!isAuthed}>Refresh docs</button>
          <button className="primary" onClick={rebuildIndex} disabled={!isAuthed}>Rebuild index</button>
        </div>
        <table className="table">
          <thead><tr><th>File</th><th>Type</th><th>Added</th></tr></thead>
          <tbody>
            {docs.map((doc) => (
              <tr key={doc.id}><td>{doc.filename}</td><td>{doc.content_type}</td><td>{doc.created_at}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  function renderPlaybookPanel() {
    return (
      <div className="workspace-block">
        <h3>Playbook Rules</h3>
        <p className="small">Load and edit tenant policy JSON.</p>
        <div className="actions">
          <button className="secondary" onClick={() => loadPlaybook()} disabled={!isAuthed}>Load playbook</button>
          <button className="primary" onClick={savePlaybook} disabled={!isAuthed}>Save playbook</button>
        </div>
        <textarea
          style={{ marginTop: "10px", minHeight: "420px" }}
          value={playbookText}
          onChange={(e) => setPlaybookText(e.target.value)}
          placeholder='{"name":"My Playbook","rules":[...]}'
          disabled={!isAuthed}
        />
      </div>
    );
  }

  function renderVectorPanel() {
    return (
      <div className="workspace-block">
        <h3>Vector Store</h3>
        <p className="small">Inspect indexed chunks used by retrieval.</p>
        <div className="actions">
          <button className="primary" onClick={() => loadVectors()} disabled={!isAuthed}>Load vectors</button>
        </div>
        <p className="small">Chunks: {vectorStats.chunk_count} | Sources: {(vectorStats.files || []).join(", ") || "none"}</p>
        <table className="table">
          <thead><tr><th>Chunk ID</th><th>Source</th><th>Preview</th><th>Token count</th></tr></thead>
          <tbody>
            {vectorRows.map((row) => (
              <tr key={row.chunk_id}><td>{row.chunk_id}</td><td>{row.source}</td><td>{row.preview}</td><td>{row.token_count}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  function renderPanel() {
    if (activeTab === "auth") return renderAuthPanel();
    if (activeTab === "viewer") return renderViewerPanel();
    if (activeTab === "history") return renderHistoryPanel();
    if (activeTab === "rag") return renderRagPanel();
    if (activeTab === "playbook") return renderPlaybookPanel();
    if (activeTab === "vectors") return renderVectorPanel();
    return null;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-logo" src="/ui/emb_global_logo.png" alt="EMB Global" />
          <div>
            <h1>EMB Vakil AI</h1>
            <p className="sub">Legal review workspace</p>
          </div>
        </div>

        <div className="tenant-pill">{isAuthed ? `Tenant: ${tenantName}` : "Not signed in"}</div>

        <nav className="nav-list">
          {tabs.map((tab) => {
            const disabled = !isAuthed && tab.id !== "auth";
            return (
              <button key={tab.id} className={activeTab === tab.id ? "active" : ""} onClick={() => setActiveTab(tab.id)} disabled={disabled}>
                {tab.label}
              </button>
            );
          })}
        </nav>

        {isAuthed && (
          <button onClick={clearAuth} className="secondary signout-btn">Sign out</button>
        )}
      </aside>

      <main className="workspace">
        <div className="workspace-header">
          <h2>{tabs.find((item) => item.id === activeTab)?.label || "Workspace"}</h2>
          <div className="header-actions">
            {isAuthed && (
              <button className="primary" onClick={() => setReportStudioOpen(true)}>
                Generate Report
              </button>
            )}
            <span className={statusClass}>{status.message}</span>
          </div>
        </div>
        <div className="workspace-panel">{renderPanel()}</div>
      </main>

      {reportStudioOpen && (
        <div className="modal-overlay">
          <div className="modal-window">
            <div className="modal-head">
              <h3>Generate Report</h3>
              <button className="secondary" onClick={() => setReportStudioOpen(false)}>Close</button>
            </div>
            <label>Upload contract file (.pdf, .txt, .md, .docx) or paste text.</label>
            <input
              type="file"
              accept=".pdf,.txt,.md,.docx"
              onChange={(event) => setReviewFile((event.target.files || [])[0] || null)}
            />
            <p className="small">{reviewFile ? `Selected file: ${reviewFile.name}` : "No review file selected."}</p>
            <textarea value={reviewInput} onChange={(e) => setReviewInput(e.target.value)} placeholder="Paste NDA/MSA text here..." />
            <div className="actions"><button className="primary" onClick={runReview}>Generate Risk Report</button></div>
          </div>
        </div>
      )}

      {reviewJob.open && (
        <div className="modal-overlay">
          <div className="modal-window">
            <div className="modal-head">
              <h3>Review Work In Progress</h3>
              <button className="secondary" disabled={reviewJob.status !== "completed"} onClick={() => setReviewJob((prev) => ({ ...prev, open: false }))}>Close</button>
            </div>
            <p className="small">Job: {reviewJob.jobId || "n/a"} | Status: {reviewJob.status}</p>
            {reviewJob.error && <p className="status err">{reviewJob.error}</p>}
            <table className="table">
              <thead><tr><th>Stage</th><th>Clause</th><th>Message</th></tr></thead>
              <tbody>
                {(reviewJob.events || []).map((event, idx) => (
                  <tr key={`${idx}_${event.stage || "stage"}`}><td>{event.stage || ""}</td><td>{event.clause_id || "-"}</td><td>{event.message || ""}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
