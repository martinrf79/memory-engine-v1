const els = {
  authCard: document.getElementById("authCard"),
  dashboardCard: document.getElementById("dashboardCard"),
  providersCard: document.getElementById("providersCard"),
  chatCard: document.getElementById("chatCard"),
  supportCard: document.getElementById("supportCard"),
  banner: document.getElementById("banner"),
  healthChip: document.getElementById("healthChip"),
  sessionNote: document.getElementById("sessionNote"),
  connectorState: document.getElementById("connectorState"),
  projectEmpty: document.getElementById("projectEmpty"),
  loginForm: document.getElementById("loginForm"),
  registerForm: document.getElementById("registerForm"),
  projectForm: document.getElementById("projectForm"),
  chatForm: document.getElementById("chatForm"),
  logoutBtn: document.getElementById("logoutBtn"),
  pauseBtn: document.getElementById("pauseBtn"),
  resumeBtn: document.getElementById("resumeBtn"),
  disconnectBtn: document.getElementById("disconnectBtn"),
  providerList: document.getElementById("providerList"),
  chatResponse: document.getElementById("chatResponse"),
  manualMemoryForm: document.getElementById("manualMemoryForm"),
  manualMemoryInput: document.getElementById("manualMemoryInput"),
  manualMemoryResponse: document.getElementById("manualMemoryResponse"),
  manualMemorySubmit: document.getElementById("manualMemorySubmit"),
  loginUserId: document.getElementById("loginUserId"),
  loginPassword: document.getElementById("loginPassword"),
  registerUserId: document.getElementById("registerUserId"),
  registerPassword: document.getElementById("registerPassword"),
  registerProject: document.getElementById("registerProject"),
  newProjectInput: document.getElementById("newProjectInput"),
  messageInput: document.getElementById("messageInput"),
  userIdValue: document.getElementById("userIdValue"),
  projectValue: document.getElementById("projectValue"),
  memoryStatusValue: document.getElementById("memoryStatusValue"),
  providerValue: document.getElementById("providerValue"),
  projectSelect: document.getElementById("projectSelect"),
  providerTemplate: document.getElementById("providerTemplate"),
  mcpConnectorUrl: document.getElementById("mcpConnectorUrl"),
  mcpHttpUrl: document.getElementById("mcpHttpUrl"),
  toolCallingManifestUrl: document.getElementById("toolCallingManifestUrl"),
  toolCallingCallUrl: document.getElementById("toolCallingCallUrl"),
  loginSubmit: document.getElementById("loginSubmit"),
  registerSubmit: document.getElementById("registerSubmit"),
  chatSubmit: document.getElementById("chatSubmit"),
  rememberToggle: document.getElementById("rememberToggle"),
  projectSubmit: document.getElementById("projectSubmit"),
};

const state = {
  auth: null,
  providers: [],
  projects: [],
  activeProject: null,
  activeRequests: new Set(),
  requestTimeoutMs: 12000,
  sessionPollId: null,
};

function setBanner(message = "", variant = "info") {
  if (!message) {
    els.banner.textContent = "";
    els.banner.className = "banner hidden";
    return;
  }
  els.banner.textContent = message;
  els.banner.className = `banner ${variant}`;
}

function setInlineStatus(element, message = "", variant = "info") {
  if (!element) return;
  if (!message) {
    element.textContent = "";
    element.className = "banner info hidden";
    return;
  }
  element.textContent = message;
  element.className = `banner ${variant}`;
}

function setBusy(key, busy) {
  if (busy) state.activeRequests.add(key); else state.activeRequests.delete(key);
  const disabled = state.activeRequests.size > 0;
  [els.loginSubmit, els.registerSubmit, els.chatSubmit, els.manualMemorySubmit, els.projectSubmit, els.pauseBtn, els.resumeBtn, els.disconnectBtn].forEach((btn) => {
    if (btn) btn.disabled = disabled;
  });
  Array.from(document.querySelectorAll(".provider-connect")).forEach((btn) => {
    btn.disabled = disabled;
  });
}

function updateHealthChip(message, variant = "info") {
  els.healthChip.textContent = message;
  els.healthChip.dataset.variant = variant;
}

function currentHash() {
  return (window.location.hash || "#/login").toLowerCase();
}

function setRoute(hash, replace = false) {
  if (replace) {
    window.history.replaceState({}, "", hash);
  } else if (window.location.hash !== hash) {
    window.history.pushState({}, "", hash);
  }
}

function showDashboard(loggedIn) {
  els.authCard.classList.toggle("hidden", loggedIn);
  els.dashboardCard.classList.toggle("hidden", !loggedIn);
  els.providersCard.classList.toggle("hidden", !loggedIn);
  els.chatCard.classList.toggle("hidden", !loggedIn);
  els.supportCard.classList.toggle("hidden", !loggedIn);
  if (loggedIn) {
    setRoute("#/dashboard", true);
  } else if (currentHash() !== "#/login") {
    setRoute("#/login", true);
  }
}

function renderRoute() {
  const wantsDashboard = currentHash() === "#/dashboard";
  if (wantsDashboard && !state.auth) {
    showDashboard(false);
    setInlineStatus(els.sessionNote, "Necesitás iniciar sesión para ver este panel.", "warning");
    return;
  }
  showDashboard(Boolean(state.auth));
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort("timeout"), state.requestTimeoutMs);
  try {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
      signal: controller.signal,
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json().catch(() => ({})) : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload.detail : payload;
      const error = new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") {
      const timeoutError = new Error("request_timeout");
      timeoutError.status = 408;
      throw timeoutError;
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function requireProject() {
  const project = els.projectSelect.value || state.activeProject;
  if (!project) { state.activeProject = "general"; }
  state.activeProject = project;
  return project;
}

function renderProjects() {
  els.projectSelect.innerHTML = "";
  state.projects.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.project;
    option.textContent = item.project;
    els.projectSelect.appendChild(option);
  });
  const hasProjects = state.projects.length > 0;
  els.projectEmpty.classList.toggle("hidden", hasProjects);
  els.projectSelect.disabled = !hasProjects;
  if (state.activeProject && state.projects.some((item) => item.project === state.activeProject)) {
    els.projectSelect.value = state.activeProject;
  } else if (state.projects.length) {
    state.activeProject = state.projects[0].project;
    els.projectSelect.value = state.activeProject;
  } else {
    state.activeProject = null;
  }
  els.projectValue.textContent = state.activeProject || "-";
}

function renderProviders() {
  els.providerList.innerHTML = "";
  state.providers.forEach((provider) => {
    const node = els.providerTemplate.content.cloneNode(true);
    node.querySelector(".provider-title").textContent = provider.provider;
    node.querySelector(".provider-meta").textContent = `${provider.bridge_mode} · API propia: ${provider.requires_user_api_key ? "sí" : "no"}`;
    node.querySelector(".provider-connect").addEventListener("click", () => connectProvider(provider.provider));
    els.providerList.appendChild(node);
  });
}

function resetSensitiveUi() {
  els.chatResponse.textContent = "Todavía no hay respuestas.";
  if (els.manualMemoryResponse) els.manualMemoryResponse.textContent = "Todavía no guardaste memorias manuales desde este panel.";
  els.messageInput.value = "";
  if (els.manualMemoryInput) els.manualMemoryInput.value = "";
  if (els.rememberToggle) els.rememberToggle.checked = false;
  els.loginPassword.value = "";
  els.registerPassword.value = "";
}

async function refreshHealth() {
  try {
    const data = await api("/health");
    updateHealthChip(data.status === "ok" ? "Servicio listo" : "Servicio con alertas", data.status === "ok" ? "success" : "warning");
  } catch {
    updateHealthChip("Sin conexión", "error");
  }
}

async function refreshAuth() {
  const data = await api("/auth/me");
  state.auth = data.authenticated ? data : null;
  return state.auth;
}

async function loadBootstrap() {
  const data = await api("/panel/bootstrap");
  state.projects = data.projects || [];
  state.providers = data.providers || [];
  renderProjects();
  renderProviders();
  updatePanelFromMe(data.me);
}

function updatePanelFromMe(panel) {
  els.userIdValue.textContent = panel.user_id;
  els.projectValue.textContent = state.activeProject || "-";
  els.memoryStatusValue.textContent = panel.connection.status;
  els.providerValue.textContent = panel.connection.provider;
  updateConnectionState(panel.connection.status, panel.connection.provider);
  const connection = panel.connection || {};
  if (els.mcpConnectorUrl) els.mcpConnectorUrl.value = connection.mcp_connector_url || connection.mcp_sse_url || "";
  if (els.mcpHttpUrl) els.mcpHttpUrl.value = connection.mcp_http_url || "";
  if (els.toolCallingManifestUrl) els.toolCallingManifestUrl.value = connection.tool_calling_manifest_url || "";
  if (els.toolCallingCallUrl) els.toolCallingCallUrl.value = connection.tool_calling_call_url || "";
  const expiresAt = state.auth?.expires_at;
  setInlineStatus(els.sessionNote, expiresAt ? `Sesión activa. Vence: ${expiresAt}` : "Sesión activa.", "info");
}

async function refreshPanel() {
  const panel = await api("/panel/me");
  updatePanelFromMe(panel);
}

async function handleManualMemorySubmit(event) {
  event.preventDefault();
  setBusy("manualMemory", true);
  try {
    const project = requireProject();
    const content = els.manualMemoryInput.value.trim();
    if (!content) throw new Error("Escribí un dato para guardar.");
    const data = await api("/panel/memories/manual", {
      method: "POST",
      body: JSON.stringify({ project, book_id: "general", content }),
    });
    els.manualMemoryResponse.textContent = data.message || "Memoria guardada.";
    els.manualMemoryInput.value = "";
    setBanner("Memoria guardada correctamente.", "success");
  } catch (error) {
    setBanner(error.message || "No se pudo guardar la memoria.", "error");
  } finally {
    setBusy("manualMemory", false);
  }
}

function updateConnectionState(status, provider = "-") {
  const messageMap = {
    not_connected: "Sin conexión activa. Elegí un proveedor para preparar tu memoria.",
    disconnected: "La memoria quedó desconectada. Podés volver a conectarla cuando quieras.",
    connecting: `Conectando ${provider}…`,
    connected: `Conexión activa con ${provider}.`,
    paused: "La memoria está pausada. Reactivala cuando quieras continuar.",
    timeout: "La conexión tardó demasiado. Podés reintentar.",
    error: "No pudimos completar la conexión. Intentá de nuevo.",
    unavailable: "El sistema está temporalmente no disponible.",
    session_expired: "Tu sesión venció. Volvé a ingresar para continuar.",
  };
  const variant = status === "connected" ? "success" : ["error", "timeout", "unavailable"].includes(status) ? "error" : status === "session_expired" ? "warning" : "info";
  setInlineStatus(els.connectorState, messageMap[status] || `Estado actual: ${status}.`, variant);
}

async function handleUnauthorized(error) {
  if (error.status === 401) {
    stopSessionPolling();
    state.auth = null;
    state.projects = [];
    state.activeProject = null;
    renderProjects();
    resetSensitiveUi();
    showDashboard(false);
    updateConnectionState("session_expired");
    setBanner("Tu sesión venció. Volvé a iniciar sesión.", "warning");
    els.loginUserId.focus();
    return true;
  }
  return false;
}

function friendlyError(error) {
  if (["invalid_credentials", "user_exists", "project_forbidden", "auth_required"].includes(error.message)) {
    return {
      invalid_credentials: "No pudimos iniciar sesión con esas credenciales.",
      user_exists: "Ese usuario ya existe. Probá iniciar sesión.",
      project_forbidden: "No tenés acceso a ese proyecto.",
      auth_required: "Necesitás iniciar sesión para continuar.",
    }[error.message];
  }
  if (error.message === "Conexión activa no encontrada") return "No hay una conexión activa para pausar.";
  if (error.message === "Conexión pausada no encontrada") return "No hay una conexión pausada para reactivar.";
  if (error.message === "Conexión no encontrada") return "No hay una conexión para desconectar.";
  if (error.message === "Elegí un proyecto antes de continuar.") return error.message;
  if (error.message === "request_timeout") return "La operación tardó demasiado. Intentá de nuevo.";
  return navigator.onLine ? "No pudimos completar la operación. Intentá de nuevo." : "Sin conexión. Verificá tu red e intentá nuevamente.";
}

async function perform(key, action, successMessage = "", { connectorStage = null } = {}) {
  try {
    setBusy(key, true);
    if (connectorStage) updateConnectionState(connectorStage, els.providerValue.textContent || "-");
    const result = await action();
    if (successMessage) setBanner(successMessage, "success");
    return result;
  } catch (error) {
    if (!(await handleUnauthorized(error))) {
      setBanner(friendlyError(error), error.message === "project_forbidden" ? "warning" : "error");
      if (connectorStage) {
        updateConnectionState(error.message === "request_timeout" ? "timeout" : navigator.onLine ? "error" : "unavailable");
      }
    }
    throw error;
  } finally {
    setBusy(key, false);
  }
}

async function login(payload) {
  await api("/auth/login", { method: "POST", body: JSON.stringify(payload) });
  await afterAuth();
}

async function register(payload) {
  await api("/auth/register", { method: "POST", body: JSON.stringify(payload) });
  await afterAuth();
}

async function afterAuth() {
  await refreshAuth();
  await loadBootstrap();
  showDashboard(true);
  startSessionPolling();
  setBanner("Sesión iniciada correctamente.", "success");
  els.projectSelect.focus();
}

async function logout() {
  await api("/auth/logout", { method: "POST" });
  stopSessionPolling();
  state.auth = null;
  state.projects = [];
  state.activeProject = null;
  renderProjects();
  resetSensitiveUi();
  showDashboard(false);
  setInlineStatus(els.sessionNote, "", "info");
  updateConnectionState("disconnected");
  setBanner("Sesión cerrada correctamente.", "success");
  els.loginUserId.focus();
}

async function createProject(project) {
  const data = await api("/panel/projects", { method: "POST", body: JSON.stringify({ project }) });
  state.projects = data.projects || [];
  renderProjects();
  state.activeProject = project;
  await refreshPanel();
}

async function connectProvider(provider) {
  const project = requireProject();
  updateConnectionState("connecting", provider);
  await api("/connection/connect", { method: "POST", body: JSON.stringify({ user_id: state.auth.user_id, provider, project }) });
  await refreshPanel();
}

async function pauseMemory() {
  await api("/connection/pause", { method: "POST" });
  await refreshPanel();
}

async function resumeMemory() {
  updateConnectionState("connecting", els.providerValue.textContent || "-");
  await api("/connection/resume", { method: "POST" });
  await refreshPanel();
}

async function disconnectMemory() {
  await api("/connection/disconnect", { method: "POST" });
  await refreshPanel();
}

async function sendChat(message) {
  const project = requireProject();
  const remember = !!(els.rememberToggle && els.rememberToggle.checked);
  const data = await api("/panel/chat", { method: "POST", body: JSON.stringify({ project, book_id: "general", message, remember }) });
  els.chatResponse.textContent = `${data.answer}\n\nModo: ${data.mode}`;
}

async function ensureSession() {
  try {
    const auth = await refreshAuth();
    if (!auth) {
      showDashboard(false);
      return false;
    }
    return true;
  } catch {
    showDashboard(false);
    return false;
  }
}

function startSessionPolling() {
  stopSessionPolling();
  state.sessionPollId = window.setInterval(async () => {
    if (!state.auth) return;
    try {
      await refreshAuth();
    } catch (error) {
      await handleUnauthorized(error);
    }
  }, 60000);
}

function stopSessionPolling() {
  if (state.sessionPollId) {
    window.clearInterval(state.sessionPollId);
    state.sessionPollId = null;
  }
}

els.projectSelect.addEventListener("change", async (event) => {
  state.activeProject = event.target.value;
  els.projectValue.textContent = state.activeProject;
  try {
    await refreshPanel();
  } catch (error) {
    await handleUnauthorized(error);
  }
});

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await perform("login", () => login({ user_id: els.loginUserId.value.trim(), password: els.loginPassword.value }));
});

els.registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await perform("register", () => register({ user_id: els.registerUserId.value.trim(), password: els.registerPassword.value, project: els.registerProject.value.trim() }));
});

els.projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = els.newProjectInput.value.trim();
  if (!value) {
    setBanner("Indicá un nombre de proyecto.", "warning");
    els.newProjectInput.focus();
    return;
  }
  await perform("project", () => createProject(value), "Proyecto agregado.");
  els.newProjectInput.value = "";
});

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = els.messageInput.value.trim();
  if (!message) {
    setBanner("Escribí un mensaje para probar el chat.", "warning");
    els.messageInput.focus();
    return;
  }
  await perform("chat", () => sendChat(message));
});

els.logoutBtn.addEventListener("click", () => perform("logout", logout));
els.pauseBtn.addEventListener("click", () => perform("pause", pauseMemory, "Memoria pausada."));
els.resumeBtn.addEventListener("click", () => perform("resume", resumeMemory, "Memoria reactivada.", { connectorStage: "connecting" }));
els.disconnectBtn.addEventListener("click", () => perform("disconnect", disconnectMemory, "Conexión desconectada."));

window.addEventListener("hashchange", () => renderRoute());
window.addEventListener("pageshow", async () => {
  if (!state.auth) return;
  await ensureSession();
  renderRoute();
});
window.addEventListener("online", () => updateHealthChip("Conexión recuperada", "success"));
window.addEventListener("offline", () => updateHealthChip("Sin conexión", "error"));
document.addEventListener("visibilitychange", async () => {
  if (!document.hidden && state.auth) {
    try {
      await refreshAuth();
      await refreshPanel();
    } catch (error) {
      await handleUnauthorized(error);
    }
  }
});

async function boot() {
  showDashboard(false);
  renderRoute();
  await refreshHealth();
  try {
    await refreshAuth();
  } catch {
    state.auth = null;
  }
  if (state.auth) {
    await loadBootstrap();
    showDashboard(true);
    startSessionPolling();
  } else {
    setInlineStatus(els.sessionNote, "", "info");
    updateConnectionState("disconnected");
  }
}

boot().catch(() => {
  setBanner("No pudimos iniciar el panel. Intentá nuevamente.", "error");
});


els.manualMemoryForm?.addEventListener("submit", handleManualMemorySubmit);
