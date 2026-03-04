const { useMemo, useState } = React;

const tabs = [
  "auth",
  "playbook",
  "rag",
  "review",
  "vectors",
];

async function apiRequest(path, options = {}, token = "") {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(path, { ...options, headers });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Request failed.");
  }
  return data;
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

  const [reviewInput, setReviewInput] = useState("");
  const [reviewFile, setReviewFile] = useState(null);
  const [reviewResult, setReviewResult] = useState(null);
  const [reviewJob, setReviewJob] = useState({
    open: false,
    jobId: "",
    status: "idle",
    events: [],
    error: "",
  });

  const isAuthed = !!token;

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
  }

  async function handleSignup(event) {
    event.preventDefault();
    try {
      const data = await apiRequest("/api/auth/signup", {
        method: "POST",
        body: JSON.stringify(signup),
      });
      saveAuth(data);
      setStatus({ message: "Account created.", kind: "ok" });
      setActiveTab("playbook");
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
      await loadPlaybook(data.token);
      await loadDocs(data.token);
      await loadVectors(data.token);
      setStatus({ message: "Signed in. Playbook, docs, and vectors loaded.", kind: "ok" });
      setActiveTab("rag");
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function loadPlaybook(authToken = token) {
    try {
      const data = await apiRequest("/api/playbook", {}, authToken);
      setPlaybookText(JSON.stringify(data.playbook, null, 2));
      if (authToken === token) {
        setStatus({ message: "Playbook loaded.", kind: "ok" });
      }
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function savePlaybook() {
    try {
      const parsed = JSON.parse(playbookText);
      await apiRequest(
        "/api/playbook",
        {
          method: "PUT",
          body: JSON.stringify({ playbook: parsed }),
        },
        token
      );
      setStatus({ message: "Playbook saved.", kind: "ok" });
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function loadDocs(authToken = token) {
    try {
      const data = await apiRequest("/api/rag/documents", {}, authToken);
      setDocs(data.documents);
      if (authToken === token) {
        setStatus({ message: "Documents loaded.", kind: "ok" });
      }
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
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
        {
          method: "POST",
          body: JSON.stringify({ documents: encoded }),
        },
        token
      );
      setStatus({ message: "Documents uploaded.", kind: "ok" });
      await loadDocs();
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function rebuildIndex() {
    try {
      const data = await apiRequest("/api/rag/reindex", { method: "POST", body: "{}" }, token);
      if (!data.scope) {
        const warningText = (data.warnings || []).join(" | ") || "No chunks were indexed.";
        setStatus({ message: `RAG index empty: ${warningText}`, kind: "err" });
      } else if ((data.warnings || []).length > 0) {
        setStatus({
          message: `RAG index rebuilt with warnings: ${(data.warnings || []).join(" | ")}`,
          kind: "err",
        });
      } else {
        setStatus({ message: "RAG index rebuilt.", kind: "ok" });
      }
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
  }

  async function loadVectors(authToken = token) {
    try {
      const data = await apiRequest("/api/rag/index", {}, authToken);
      setVectorRows(data.chunks);
      setVectorStats({ chunk_count: data.chunk_count, files: data.files });
      if (authToken === token) {
        setStatus({ message: "Vector index loaded.", kind: "ok" });
      }
    } catch (error) {
      setStatus({ message: String(error), kind: "err" });
    }
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
      events: [
        {
          stage: "ui",
          clause_id: "",
          message: `Generate Risk Report clicked at ${startedAt}. Initializing review...`,
        },
      ],
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
          body: JSON.stringify({
            contract_text: reviewInput,
            trace: false,
            ...filePayload,
          }),
        },
        token
      );
      setReviewJob((prev) => ({
        ...prev,
        jobId: startData.job_id,
        status: "queued",
        events: [
          ...prev.events,
          {
            stage: "queue",
            clause_id: "",
            message: `Review job created: ${startData.job_id}`,
          },
        ],
      }));
      setStatus({ message: "Review started.", kind: "ok" });
      pollReviewStatus(startData.job_id);
    } catch (error) {
      const errorMessage = String(error);
      setStatus({ message: errorMessage, kind: "err" });
      setReviewJob((prev) => ({
        ...prev,
        open: false,
        status: "failed",
        error: errorMessage,
        events: [
          ...prev.events,
          {
            stage: "error",
            clause_id: "",
            message: errorMessage,
          },
        ],
      }));
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
          return {
            ...prev,
            status: data.status,
            events: deduped,
            error: data.error || "",
          };
        });

        if (data.status === "completed") {
          setReviewResult(data.result);
          setStatus({ message: "Review complete.", kind: "ok" });
          keepPolling = false;
          break;
        }
        if (data.status === "failed") {
          const backendError = data.error || "Review failed with unknown error.";
          setStatus({ message: `Review failed: ${backendError}`, kind: "err" });
          setReviewJob((prev) => ({
            ...prev,
            open: false,
            status: "failed",
            error: backendError,
            events: [
              ...(prev.events || []),
              {
                stage: "error",
                clause_id: "",
                message: backendError,
              },
            ],
          }));
          keepPolling = false;
          break;
        }
      } catch (error) {
        const errorMessage = String(error);
        setStatus({ message: errorMessage, kind: "err" });
        setReviewJob((prev) => ({
          ...prev,
          open: false,
          status: "failed",
          error: errorMessage,
          events: [
            ...(prev.events || []),
            {
              stage: "error",
              clause_id: "",
              message: errorMessage,
            },
          ],
        }));
        keepPolling = false;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  return (
    <div className="container">
      <div className="header">
        <div className="brand">
          <img className="brand-logo" src="/ui/emb_global_logo.png" alt="EMB Global" />
          <div>
            <h1>EMB Vakil AI</h1>
            <p className="sub">Multi-tenant contract review with local RAG and custom rule playbooks.</p>
          </div>
        </div>
        <div className="badge">{isAuthed ? `Tenant: ${tenantName}` : "Not signed in"}</div>
      </div>

      <div className="grid">
        <div className="panel nav">
          {tabs.map((tab) => (
            <button
              key={tab}
              className={activeTab === tab ? "active" : ""}
              onClick={() => setActiveTab(tab)}
            >
              {tab.toUpperCase()}
            </button>
          ))}
          {isAuthed && (
            <button onClick={clearAuth} className="secondary" style={{ margin: "10px" }}>
              Sign out
            </button>
          )}
        </div>

        <div className="panel section">
          {activeTab === "auth" && (
            <>
              <h3>Access Portal</h3>
              <div className="auth-card">
                <div className="auth-toggle">
                  <button
                    className={authMode === "login" ? "active" : ""}
                    onClick={() => setAuthMode("login")}
                  >
                    Login
                  </button>
                  <button
                    className={authMode === "signup" ? "active" : ""}
                    onClick={() => setAuthMode("signup")}
                  >
                    Sign up
                  </button>
                </div>

                {authMode === "signup" ? (
                  <form onSubmit={handleSignup}>
                    <label>Company</label>
                    <input
                      value={signup.company}
                      onChange={(e) => setSignup({ ...signup, company: e.target.value })}
                      required
                    />
                    <label style={{ marginTop: "8px" }}>Email</label>
                    <input
                      type="email"
                      value={signup.email}
                      onChange={(e) => setSignup({ ...signup, email: e.target.value })}
                      required
                    />
                    <label style={{ marginTop: "8px" }}>Password</label>
                    <input
                      type="password"
                      value={signup.password}
                      onChange={(e) => setSignup({ ...signup, password: e.target.value })}
                      required
                    />
                    <div className="actions">
                      <button className="primary" type="submit">
                        Create account
                      </button>
                    </div>
                  </form>
                ) : (
                  <form onSubmit={handleLogin}>
                    <label>Email</label>
                    <input
                      type="email"
                      value={login.email}
                      onChange={(e) => setLogin({ ...login, email: e.target.value })}
                      required
                    />
                    <label style={{ marginTop: "8px" }}>Password</label>
                    <input
                      type="password"
                      value={login.password}
                      onChange={(e) => setLogin({ ...login, password: e.target.value })}
                      required
                    />
                    <div className="actions">
                      <button className="primary" type="submit">
                        Login
                      </button>
                    </div>
                  </form>
                )}
              </div>
            </>
          )}

          {activeTab === "playbook" && (
            <>
              <h3>Tenant playbook rules</h3>
              <p className="small">Load/edit JSON playbook for your tenant.</p>
              <div className="actions">
                <button className="secondary" onClick={loadPlaybook} disabled={!isAuthed}>
                  Load playbook
                </button>
                <button className="primary" onClick={savePlaybook} disabled={!isAuthed}>
                  Save playbook
                </button>
              </div>
              <textarea
                style={{ marginTop: "10px", minHeight: "360px" }}
                value={playbookText}
                onChange={(e) => setPlaybookText(e.target.value)}
                placeholder='{"name":"My Playbook","rules":[...]}'
              />
            </>
          )}

          {activeTab === "rag" && (
            <>
              <h3>RAG documents</h3>
              <p className="small">Upload PDFs/text docs. They are indexed locally per tenant.</p>
              <input type="file" multiple onChange={uploadDocs} disabled={!isAuthed} />
              <div className="actions">
                <button className="secondary" onClick={loadDocs} disabled={!isAuthed}>
                  Refresh docs
                </button>
                <button className="primary" onClick={rebuildIndex} disabled={!isAuthed}>
                  Rebuild index
                </button>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Type</th>
                    <th>Added</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.map((doc) => (
                    <tr key={doc.id}>
                      <td>{doc.filename}</td>
                      <td>{doc.content_type}</td>
                      <td>{doc.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {activeTab === "review" && (
            <>
              <div className="review-head">
                <h3>Contract review</h3>
                <button className="primary" onClick={runReview} disabled={!isAuthed}>
                  Generate Risk Report
                </button>
              </div>
              <label>Upload contract file (.pdf, .txt, .md, .docx) or paste text</label>
              <input
                type="file"
                accept=".pdf,.txt,.md,.docx"
                onChange={(event) => setReviewFile((event.target.files || [])[0] || null)}
              />
              <p className="small">
                {reviewFile ? `Selected file: ${reviewFile.name}` : "No review file selected."}
              </p>
              <textarea
                value={reviewInput}
                onChange={(e) => setReviewInput(e.target.value)}
                placeholder="Paste NDA/MSA text here..."
              />
              {reviewResult && (
                <>
                  <p className="small">
                    Overall risk: {reviewResult.report.overall_risk} | Findings: {reviewResult.report.findings.length}
                  </p>
                  <div className="markdown">{reviewResult.markdown}</div>
                  <h4 style={{ marginTop: "14px" }}>Document View With Redlines</h4>
                  <div className="doc-view">
                    {(reviewResult.clauses || []).map((clause) => {
                      const clauseFindings = (reviewResult.report.findings || []).filter(
                        (finding) => finding.clause_id === clause.id
                      );
                      const topFinding = clauseFindings[0] || null;
                      return (
                        <div
                          key={clause.id}
                          className={`clause-card ${clauseFindings.length ? "clause-risky" : ""}`}
                        >
                          <div className="clause-head">
                            <strong>
                              {clause.id} · {clause.heading}
                            </strong>
                            <span className="badge">
                              {clauseFindings.length
                                ? `${clauseFindings.length} issue(s)`
                                : "No issues"}
                            </span>
                          </div>
                          <div className="clause-body">
                            {renderHighlightedClauseText(
                              clause.text,
                              topFinding ? topFinding.excerpt : ""
                            )}
                          </div>
                          {clauseFindings.map((finding, idx) => (
                            <div className="redline-block" key={`${clause.id}_${idx}`}>
                              <div>
                                <strong>{finding.issue}</strong> ({finding.severity})
                              </div>
                              <div className="small">Why: {finding.why}</div>
                              <div className="small">Recommendation: {finding.recommendation}</div>
                              {finding.suggested_redline && (
                                <div className="redline-text">{finding.suggested_redline}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </>
          )}

          {activeTab === "vectors" && (
            <>
              <h3>Vector database view</h3>
              <p className="small">Inspect local chunk index used by RAG retrieval.</p>
              <div className="actions">
                <button className="primary" onClick={loadVectors} disabled={!isAuthed}>
                  Load vectors
                </button>
              </div>
              <p className="small">
                Chunks: {vectorStats.chunk_count} | Sources: {(vectorStats.files || []).join(", ") || "none"}
              </p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Chunk ID</th>
                    <th>Source</th>
                    <th>Preview</th>
                    <th>Token count</th>
                  </tr>
                </thead>
                <tbody>
                  {vectorRows.map((row) => (
                    <tr key={row.chunk_id}>
                      <td>{row.chunk_id}</td>
                      <td>{row.source}</td>
                      <td>{row.preview}</td>
                      <td>{row.token_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <div className={statusClass}>{status.message}</div>
        </div>
      </div>

      {reviewJob.open && (
        <div className="modal-overlay">
          <div className="modal-window">
            <div className="modal-head">
              <h3>Review Work In Progress</h3>
              <button
                className="secondary"
                disabled={reviewJob.status !== "completed"}
                onClick={() => setReviewJob((prev) => ({ ...prev, open: false }))}
              >
                Close
              </button>
            </div>
            {reviewJob.status !== "completed" && (
              <p className="small">This window stays open until the final report is generated.</p>
            )}
            <p className="small">
              Job: {reviewJob.jobId || "n/a"} | Status: {reviewJob.status}
            </p>
            {reviewJob.error && <p className="status err">{reviewJob.error}</p>}
            <table className="table">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Clause</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {(reviewJob.events || []).map((event, idx) => (
                  <tr key={`${idx}_${event.stage || "stage"}`}>
                    <td>{event.stage || ""}</td>
                    <td>{event.clause_id || "-"}</td>
                    <td>{event.message || ""}</td>
                  </tr>
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
