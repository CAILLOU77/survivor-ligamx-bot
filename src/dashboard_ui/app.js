(() => {
  "use strict";

  const STORAGE_KEY = "mi_survivor_api_key";
  const state = {
    key: sessionStorage.getItem(STORAGE_KEY) || "",
    mine: null,
    calendar: null,
    round: null,
    roundData: null,
    recommendation: null,
    dialogAction: null,
  };

  const $ = (id) => document.getElementById(id);
  const ui = {
    authGate: $("authGate"), app: $("app"), authForm: $("authForm"), apiKeyInput: $("apiKeyInput"),
    loginButton: $("loginButton"), authError: $("authError"), toggleKey: $("toggleKey"), logoutButton: $("logoutButton"),
    syncStatus: $("syncStatus"), seasonLabel: $("seasonLabel"), aliveIcon: $("aliveIcon"), aliveLabel: $("aliveLabel"),
    heroMessage: $("heroMessage"), streakValue: $("streakValue"), winsValue: $("winsValue"), drawsValue: $("drawsValue"),
    usedValue: $("usedValue"), nextRoundValue: $("nextRoundValue"), nextDateValue: $("nextDateValue"), roundNumber: $("roundNumber"),
    roundDate: $("roundDate"), countdownText: $("countdownText"), pickState: $("pickState"), recommendationEyebrow: $("recommendationEyebrow"), recommendedTeam: $("recommendedTeam"),
    confidenceValue: $("confidenceValue"), matchupLabel: $("matchupLabel"), recommendationNote: $("recommendationNote"),
    pickForm: $("pickForm"), teamInput: $("teamInput"), roundTeams: $("roundTeams"), confirmPickButton: $("confirmPickButton"), pickHint: $("pickHint"),
    lockPickButton: $("lockPickButton"), usedTeams: $("usedTeams"), usedCountBadge: $("usedCountBadge"),
    progressText: $("progressText"), progressTrack: $("progressTrack"), historyList: $("historyList"), emptyHistory: $("emptyHistory"),
    refreshButton: $("refreshButton"), confirmDialog: $("confirmDialog"), dialogTitle: $("dialogTitle"), dialogMessage: $("dialogMessage"),
    dialogConfirm: $("dialogConfirm"), toast: $("toast"),
  };

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  function setText(element, value) { element.textContent = value === null || value === undefined ? "—" : String(value); }
  function setSync(mode, label) { ui.syncStatus.dataset.state = mode; ui.syncStatus.lastChild.textContent = ` ${label}`; }
  function setBusy(button, busy, busyLabel, normalLabel) { button.disabled = busy; setText(button, busy ? busyLabel : normalLabel); }
  function normalizeTeam(value) {
    const base = String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[._/'-]/g, " ")
      .replace(/[^a-z0-9 ]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    const aliases = {
      "club america": "america", "cf america": "america", "club de futbol america": "america",
      chivas: "guadalajara", "cd guadalajara": "guadalajara", "chivas guadalajara": "guadalajara",
      tigres: "tigres uanl", uanl: "tigres uanl", pumas: "pumas unam", unam: "pumas unam",
      rayados: "monterrey", "cf monterrey": "monterrey", "deportivo toluca": "toluca",
      xolos: "tijuana", "club tijuana": "tijuana", "tijuana xolos de caliente": "tijuana",
      "club leon": "leon", "santos laguna": "santos", "queretaro fc": "queretaro", gallos: "queretaro",
      "atletico san luis": "atletico de san luis", "san luis": "atletico de san luis", "atl san luis": "atletico de san luis",
      juarez: "juarez", "fc juarez": "juarez", bravos: "juarez",
    };
    return aliases[base] || base;
  }

  async function api(path, options = {}, authenticated = true) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (authenticated) {
      if (!state.key) throw new ApiError(403, "Escribe tu clave privada para continuar.");
      headers.set("X-API-Key", state.key);
    }
    let response;
    try { response = await fetch(path, { ...options, headers, credentials: "omit", referrerPolicy: "no-referrer" }); }
    catch (_) { throw new ApiError(0, "No se pudo conectar con el servidor. Revisa tu conexión."); }
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) {
      const detail = payload && (payload.detail || payload.message);
      throw new ApiError(response.status, typeof detail === "string" ? detail : `Error ${response.status}`);
    }
    return payload;
  }

  function showToast(message, error = false) {
    setText(ui.toast, message);
    ui.toast.classList.toggle("error", error);
    ui.toast.classList.add("visible");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => ui.toast.classList.remove("visible"), 3800);
  }

  function showLogin(message = "") {
    ui.authGate.classList.remove("hidden");
    ui.app.classList.add("hidden");
    ui.logoutButton.classList.add("hidden");
    setText(ui.authError, message);
    setSync("idle", "Sin conectar");
    window.setTimeout(() => ui.apiKeyInput.focus(), 50);
  }

  function showApp() {
    ui.authGate.classList.add("hidden");
    ui.app.classList.remove("hidden");
    ui.logoutButton.classList.remove("hidden");
  }

  function logout(message = "Sesión cerrada.") {
    sessionStorage.removeItem(STORAGE_KEY);
    state.key = "";
    state.mine = null;
    ui.apiKeyInput.value = "";
    showLogin(message);
  }

  function formatSeason(value) { return String(value || "").replace("-", " ").toUpperCase(); }
  function formatDate(value) {
    if (!value) return "Fecha por confirmar";
    const date = new Date(`${value}T12:00:00`);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("es-MX", { weekday: "short", day: "numeric", month: "short", year: "numeric" }).format(date);
  }
  function countdownLabel(value) {
    if (!value) return "Sin fecha oficial";
    const start = new Date(`${value}T00:00:00`);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const days = Math.ceil((start.getTime() - today.getTime()) / 86400000);
    if (days > 1) return `Faltan ${days} días · hora límite no publicada`;
    if (days === 1) return "Empieza mañana · revisa el horario del primer partido";
    if (days === 0) return "Empieza hoy · confirma antes del primer partido";
    return "Jornada iniciada o finalizada";
  }

  function operationRound(mine, calendar) {
    const active = (mine.picks || []).find((pick) => ["recomendado", "confirmado", "bloqueado"].includes(pick.estado));
    if (active) return Number(active.jornada);
    const recorded = (mine.picks || []).map((pick) => Number(pick.jornada)).filter(Number.isFinite);
    const nextByHistory = recorded.length ? Math.max(...recorded) + 1 : 1;
    const nextByCalendar = Number(calendar.jornada_proxima || calendar.jornada_actual || 1);
    return Math.min(17, Math.max(nextByHistory, nextByCalendar));
  }

  function roundFromCalendar(calendar, number) {
    return (calendar.jornadas || []).find((item) => Number(item.jornada) === Number(number)) || null;
  }

  function selectionForRound(value) {
    const target = normalizeTeam(value);
    for (const match of (state.roundData && state.roundData.partidos) || []) {
      if (normalizeTeam(match.home_team) === target) {
        return { team: match.home_team, rival: match.away_team, condition: "Local", local: match.home_team, visitante: match.away_team };
      }
      if (normalizeTeam(match.away_team) === target) {
        return { team: match.away_team, rival: match.home_team, condition: "Visitante", local: match.home_team, visitante: match.away_team };
      }
    }
    return null;
  }

  function renderRoundTeams() {
    ui.roundTeams.replaceChildren();
    const teams = new Set();
    for (const match of (state.roundData && state.roundData.partidos) || []) {
      if (match.home_team) teams.add(match.home_team);
      if (match.away_team) teams.add(match.away_team);
    }
    for (const team of [...teams].sort((a, b) => a.localeCompare(b, "es-MX"))) {
      const option = document.createElement("option");
      option.value = team;
      ui.roundTeams.appendChild(option);
    }
  }

  function recommendationFromRound(payload, used, onlyTeam = "") {
    const excluded = new Set((used || []).map(normalizeTeam));
    const required = normalizeTeam(onlyTeam);
    const candidates = [];
    for (const match of payload.partidos || []) {
      const prediction = match.prediccion;
      if (!prediction) continue;
      const draw = Number(prediction.prob_empate_pct || 0);
      const sides = [
        { team: match.home_team, rival: match.away_team, condition: "Local", noLose: Number(prediction.prob_local_pct || 0) + draw, win: Number(prediction.prob_local_pct || 0) },
        { team: match.away_team, rival: match.home_team, condition: "Visitante", noLose: Number(prediction.prob_visitante_pct || 0) + draw, win: Number(prediction.prob_visitante_pct || 0) },
      ];
      for (const candidate of sides) {
        const canonical = normalizeTeam(candidate.team);
        if (!excluded.has(canonical) && (!required || canonical === required)) candidates.push(candidate);
      }
    }
    candidates.sort((a, b) => b.noLose - a.noLose || b.win - a.win);
    return candidates[0] || null;
  }

  function createChip(team) {
    const chip = document.createElement("span");
    chip.className = "team-chip";
    chip.textContent = team;
    return chip;
  }

  function renderUsed(mine) {
    ui.usedTeams.replaceChildren();
    const used = mine.usados || [];
    for (const team of used) ui.usedTeams.appendChild(createChip(team));
    if (!used.length) {
      const empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = "Ninguno todavía";
      ui.usedTeams.appendChild(empty);
    }
    setText(ui.usedCountBadge, used.length);
    setText(ui.usedValue, used.length);
    setText(ui.progressText, `${used.length} / 17`);
    ui.progressTrack.dataset.progress = String(Math.min(17, used.length));
    ui.progressTrack.setAttribute("aria-valuenow", String(used.length));
  }

  function renderHistory(mine) {
    ui.historyList.replaceChildren();
    const picks = [...(mine.picks || [])].sort((a, b) => Number(a.jornada) - Number(b.jornada));
    ui.emptyHistory.classList.toggle("hidden", picks.length > 0);
    const resultNames = { gano: "Ganó", empate: "Empató", perdio: "Perdió" };
    for (const pick of picks) {
      const item = document.createElement("li");
      item.className = "history-item";
      const round = document.createElement("span"); round.className = "round-dot"; round.textContent = `J${pick.jornada}`;
      const main = document.createElement("div"); main.className = "history-main";
      const team = document.createElement("strong"); team.textContent = pick.equipo;
      const match = document.createElement("span"); match.textContent = pick.rival ? `${pick.condicion || ""} vs ${pick.rival}`.trim() : "Partido registrado";
      main.append(team, match);
      const result = document.createElement("span");
      const resultKey = pick.resultado || (pick.estado === "resuelto" ? "pendiente" : pick.estado);
      result.className = `result ${resultKey || "pendiente"}`;
      result.textContent = resultNames[pick.resultado] || String(pick.estado || "pendiente");
      item.append(round, main, result);
      ui.historyList.appendChild(item);
    }
  }

  function currentPick(mine, round) { return (mine.picks || []).find((pick) => Number(pick.jornada) === Number(round)) || null; }

  function renderDecision(mine) {
    const roundData = state.roundData || {};
    const pick = currentPick(mine, state.round);
    renderRoundTeams();
    setText(ui.roundNumber, state.round);
    setText(ui.nextRoundValue, `J${state.round}`);
    setText(ui.roundDate, formatDate(roundData.fecha_inicio));
    setText(ui.nextDateValue, roundData.fecha_inicio ? formatDate(roundData.fecha_inicio).replace(/\s+de\s+/g, " ") : "por confirmar");
    setText(ui.countdownText, countdownLabel(roundData.fecha_inicio));

    const status = pick ? pick.estado : "sin_pick";
    ui.pickState.dataset.state = status;
    const stateNames = { recomendado: "Recomendado", confirmado: "Confirmado", bloqueado: "Bloqueado", resuelto: "Resuelto", sin_pick: "Sin confirmar" };
    setText(ui.pickState, stateNames[status] || status);

    setText(ui.recommendationEyebrow, pick ? "ANÁLISIS DE TU PICK" : "RECOMENDACIÓN DEL MODELO");
    if (state.recommendation) {
      const rec = state.recommendation;
      setText(ui.recommendedTeam, rec.team);
      setText(ui.confidenceValue, `${rec.noLose.toFixed(1)}%`);
      setText(ui.matchupLabel, `${rec.team} · ${rec.condition} vs ${rec.rival}`);
      setText(
        ui.recommendationNote,
        pick
          ? `Tu selección tiene ${rec.win.toFixed(1)}% de ganar según el modelo de la J${state.round}.`
          : `J${state.round}: ${rec.win.toFixed(1)}% de ganar. Revisa noticias y alineaciones antes de confirmar.`,
      );
      if (!pick) ui.teamInput.value = rec.team;
    } else {
      setText(ui.recommendedTeam, pick ? pick.equipo : "Sin recomendación disponible");
      setText(ui.confidenceValue, "—");
      setText(ui.matchupLabel, pick ? "Tu pick está guardado; el modelo aún no tiene probabilidades" : "El modelo aún no tiene probabilidades para esta jornada");
      setText(ui.recommendationNote, pick ? "El estado de tu selección no depende de que el modelo esté disponible." : "Puedes actualizar más tarde o registrar manualmente tu decisión.");
    }

    if (pick) ui.teamInput.value = pick.equipo;
    const immutable = pick && ["bloqueado", "resuelto"].includes(pick.estado);
    ui.teamInput.disabled = Boolean(immutable);
    ui.confirmPickButton.disabled = Boolean(immutable);
    setText(ui.confirmPickButton, pick && pick.estado === "confirmado" ? "Guardar corrección" : "Confirmar pick");
    setText(ui.pickHint, immutable ? "Esta selección ya no puede modificarse." : "Puedes corregirla hasta bloquearla.");
    ui.lockPickButton.classList.toggle("hidden", !pick || pick.estado !== "confirmado");
  }

  function render(mine) {
    setText(ui.seasonLabel, formatSeason(mine.temporada));
    setText(ui.streakValue, mine.racha || 0);
    setText(ui.winsValue, mine.victorias || 0);
    setText(ui.drawsValue, mine.empates || 0);
    setText(ui.aliveLabel, mine.sigue_vivo ? "Sigues vivo" : "Participación finalizada");
    setText(ui.aliveIcon, "●");
    ui.aliveIcon.dataset.state = mine.sigue_vivo ? "alive" : "dead";
    setText(ui.heroMessage, mine.sigue_vivo ? `${mine.racha || 0} jornadas superadas. La siguiente decisión se toma con datos, no con prisa.` : "Tu historial permanece guardado para revisar y mejorar la estrategia.");
    renderUsed(mine);
    renderHistory(mine);
    renderDecision(mine);
  }

  async function loadDashboard({ firstLogin = false } = {}) {
    setSync("loading", "Actualizando");
    setBusy(ui.refreshButton, true, "Actualizando…", "Actualizar");
    try {
      const [mine, calendar, calendarStatus] = await Promise.all([
        api("/survivor/mio"),
        api("/api/v1/calendario", {}, false),
        api("/api/v1/jornada-actual", {}, false),
      ]);
      state.mine = mine;
      state.calendar = calendar;
      state.round = operationRound(mine, calendarStatus);
      state.roundData = roundFromCalendar(calendar, state.round);
      state.recommendation = null;
      try {
        const predictionPayload = await api(`/api/v1/calendario/${state.round}?predicciones=true`, {}, false);
        const activePick = currentPick(mine, state.round);
        state.recommendation = recommendationFromRound(
          predictionPayload,
          activePick ? [] : mine.usados,
          activePick ? activePick.equipo : "",
        );
      } catch (_) {
        showToast("Tu historial está disponible, pero el modelo de la jornada tardó demasiado.", true);
      }
      render(mine);
      if (firstLogin) {
        sessionStorage.setItem(STORAGE_KEY, state.key);
        ui.apiKeyInput.value = "";
        ui.apiKeyInput.type = "password";
        setText(ui.toggleKey, "Ver");
        ui.toggleKey.setAttribute("aria-label", "Mostrar clave");
        showApp();
      }
      setSync("ok", "Al día");
    } catch (error) {
      setSync("error", "Error");
      if (error instanceof ApiError && error.status === 403) {
        logout("La clave no es válida. Verifícala en Render e intenta de nuevo.");
      } else {
        showToast(error.message || "No se pudo cargar Mi Survivor.", true);
        if (firstLogin) showLogin(error.message || "No se pudo iniciar sesión.");
      }
      throw error;
    } finally {
      setBusy(ui.refreshButton, false, "Actualizando…", "Actualizar");
    }
  }

  function askConfirmation(title, message, confirmLabel) {
    setText(ui.dialogTitle, title);
    setText(ui.dialogMessage, message);
    setText(ui.dialogConfirm, confirmLabel);
    ui.confirmDialog.showModal();
    return new Promise((resolve) => {
      ui.confirmDialog.addEventListener("close", () => resolve(ui.confirmDialog.returnValue === "confirm"), { once: true });
    });
  }

  ui.authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = ui.apiKeyInput.value.trim();
    if (!key) return;
    state.key = key;
    setText(ui.authError, "");
    setBusy(ui.loginButton, true, "Comprobando…", "Entrar a Mi Survivor");
    try { await loadDashboard({ firstLogin: true }); }
    catch (_) { state.key = ""; }
    finally { setBusy(ui.loginButton, false, "Comprobando…", "Entrar a Mi Survivor"); }
  });

  ui.toggleKey.addEventListener("click", () => {
    const reveal = ui.apiKeyInput.type === "password";
    ui.apiKeyInput.type = reveal ? "text" : "password";
    setText(ui.toggleKey, reveal ? "Ocultar" : "Ver");
    ui.toggleKey.setAttribute("aria-label", reveal ? "Ocultar clave" : "Mostrar clave");
  });
  ui.logoutButton.addEventListener("click", () => logout());
  ui.refreshButton.addEventListener("click", () => loadDashboard().catch(() => {}));

  ui.pickForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    let team = ui.teamInput.value.trim();
    if (!team || !state.round || !state.mine) return;
    const existing = currentPick(state.mine, state.round);
    const roundMatches = (state.roundData && state.roundData.partidos) || [];
    const selection = selectionForRound(team);
    if (roundMatches.length && !selection) {
      showToast(`“${team}” no participa en la Jornada ${state.round}. Elige un equipo de la lista.`, true);
      ui.teamInput.focus();
      return;
    }
    if (selection) {
      team = selection.team;
      ui.teamInput.value = team;
    }
    const alreadyUsed = (state.mine.usados || []).some((used) => normalizeTeam(used) === normalizeTeam(team));
    const isCurrentTeam = existing && normalizeTeam(existing.equipo) === normalizeTeam(team);
    if (alreadyUsed && !isCurrentTeam) {
      showToast(`${team} ya fue utilizado esta temporada. Elige otro equipo.`, true);
      return;
    }
    const confirmed = await askConfirmation(
      existing ? "¿Corregir tu selección?" : "¿Confirmar tu pick?",
      `${team} quedará registrado para la Jornada ${state.round}. Podrás corregirlo mientras no lo bloquees.`,
      existing ? "Sí, corregir" : "Sí, confirmar",
    );
    if (!confirmed) return;
    setBusy(ui.confirmPickButton, true, "Guardando…", existing ? "Guardar corrección" : "Confirmar pick");
    try {
      const params = new URLSearchParams({
        jornada: String(state.round),
        equipo: team,
        temporada: state.mine.temporada,
        rival: selection ? selection.rival : "",
        condicion: selection ? selection.condition : "",
        local: selection ? selection.local : "",
        visitante: selection ? selection.visitante : "",
        fecha: (state.roundData && state.roundData.fecha_inicio) || "",
      });
      await api(`/survivor/picks/confirmar?${params.toString()}`, { method: "POST" });
      showToast(`${team} quedó confirmado para la J${state.round}.`);
      await loadDashboard();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await loadDashboard().catch(() => {});
        showToast(`${error.message} Se cargó el estado más reciente.`, true);
      } else {
        showToast(error.message || "No se pudo confirmar el pick.", true);
      }
    } finally { setBusy(ui.confirmPickButton, false, "Guardando…", "Confirmar pick"); }
  });

  ui.lockPickButton.addEventListener("click", async () => {
    if (!state.mine || !state.round) return;
    const pick = currentPick(state.mine, state.round);
    if (!pick) return;
    const confirmed = await askConfirmation(
      "¿Bloquear definitivamente?",
      `${pick.equipo} quedará cerrado para la Jornada ${state.round}. Después no podrás corregirlo desde el dashboard.`,
      "Sí, bloquear",
    );
    if (!confirmed) return;
    setBusy(ui.lockPickButton, true, "Bloqueando…", "Bloquear selección");
    try {
      const params = new URLSearchParams({ temporada: state.mine.temporada });
      await api(`/survivor/picks/${state.round}/bloquear?${params.toString()}`, { method: "POST" });
      showToast(`${pick.equipo} quedó bloqueado para la J${state.round}.`);
      await loadDashboard();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await loadDashboard().catch(() => {});
        showToast(`${error.message} Se cargó el estado más reciente.`, true);
      } else {
        showToast(error.message || "No se pudo bloquear el pick.", true);
      }
    } finally { setBusy(ui.lockPickButton, false, "Bloqueando…", "Bloquear selección"); }
  });

  if (state.key) {
    showApp();
    loadDashboard().catch(() => {});
  } else {
    showLogin();
  }
})();
