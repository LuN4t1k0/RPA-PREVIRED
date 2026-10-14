import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Building2,
  Check,
  ChevronRight,
  Download,
  FileArchive,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Square,
  X
} from "lucide-react";
import "./styles.css";
import { formatRutInput, isValidRut, normalizeRut } from "./rut.mjs";

const steps = ["Acceso", "Empresa", "Seleccion", "Descarga", "Listo"];

function App() {
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Ingresa tus credenciales de Previred para comenzar.");
  const [error, setError] = useState("");
  const [credentials, setCredentials] = useState({ rut: "", password: "" });
  const [companies, setCompanies] = useState([]);
  const [companyQuery, setCompanyQuery] = useState("");
  const [company, setCompany] = useState(null);
  const [period, setPeriod] = useState({ desde: "", hasta: "" });
  const [periodGroups, setPeriodGroups] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [timeline, setTimeline] = useState([]);
  const [current, setCurrent] = useState(null);
  const [outputPath, setOutputPath] = useState("");
  const [summary, setSummary] = useState({ ok: 0, empty: 0, errors: 0, skipped: 0 });
  const [appInfo, setAppInfo] = useState(null);
  const [update, setUpdate] = useState({ type: "idle", message: "", percent: 0 });

  const filteredCompanies = useMemo(() => {
    const query = companyQuery.trim().toLowerCase();
    if (!query) return companies;
    return companies.filter((item) => `${item.nombre} ${item.rut}`.toLowerCase().includes(query));
  }, [companies, companyQuery]);

  const selectedItems = useMemo(() => periodGroups.flatMap((group) =>
    group.nominas
      .filter((nomina) => selected.has(`${group.periodo}|${nomina.slug}`))
      .map((nomina) => ({ periodo: group.periodo, slug: nomina.slug, nombre: nomina.nombre }))
  ), [periodGroups, selected]);

  useEffect(() => {
    window.desktopApi.getAppInfo().then(setAppInfo).catch(() => {});
    const removeWorker = window.desktopApi.onWorkerEvent((event) => {
      if (event.type === "status") setMessage(event.message);
      if (event.type === "login_success") {
        setCompanies(event.empresas || []);
        setCredentials((value) => ({ ...value, password: "" }));
        setBusy(false);
        setError("");
        setStep(1);
        setMessage("Selecciona la empresa y el rango de periodos.");
      }
      if (event.type === "discovery_complete") {
        const groups = event.nominas || [];
        setPeriodGroups(groups);
        setSelected(new Set(groups.flatMap((group) => group.nominas.map((item) => `${group.periodo}|${item.slug}`))));
        setBusy(false);
        setStep(2);
        setMessage(groups.length ? "Revisa las nominas encontradas antes de descargar." : "No se encontraron nominas AFP en ese rango.");
      }
      if (event.type === "plan") {
        setTimeline((event.items || []).map(([periodo, nomina]) => ({ periodo, nomina, estado: "pending" })));
      }
      if (event.type === "inicio_item") {
        setCurrent({ periodo: event.periodo, nomina: event.nomina, detail: "Buscando planillas..." });
        setTimeline((items) => items.map((item) =>
          item.periodo === event.periodo && item.nomina === event.nomina
            ? { ...item, estado: "active" }
            : item.estado === "active" ? { ...item, estado: "done" } : item
        ));
      }
      if (event.type === "planilla") {
        const item = event.planilla;
        setSummary((value) => ({
          ...value,
          ok: value.ok + (item.estado === "OK" ? 1 : 0),
          empty: value.empty + (item.estado === "SIN_DATOS" ? 1 : 0),
          errors: value.errors + (item.estado === "ERROR" ? 1 : 0),
          skipped: value.skipped + (item.estado === "OMITIDO" ? 1 : 0)
        }));
        setCurrent((value) => value ? { ...value, detail: `${item.institucion || "AFP"}: ${item.estado}` } : value);
      }
      if (event.type === "download_complete" || event.type === "download_canceled") {
        setOutputPath(event.outputPath || "");
        setBusy(false);
        setCurrent(null);
        setTimeline((items) => items.map((item) => item.estado === "active" ? { ...item, estado: "done" } : item));
        setStep(4);
        setMessage(event.type === "download_complete" ? "Descarga completada." : "Proceso detenido; se guardo lo descargado.");
      }
      if (event.type === "error" || event.type === "error_fatal") {
        setBusy(false);
        setError(event.message || "Ocurrio un error inesperado.");
      }
      if (event.type === "worker_exit" && event.code) {
        setBusy(false);
        setError("El motor Python termino inesperadamente. Puedes reintentar.");
      }
    });
    const removeUpdate = window.desktopApi.onUpdateEvent((event) => {
      setUpdate((value) => ({ ...value, ...event, percent: event.percent ?? value.percent ?? 0 }));
    });
    return () => { removeWorker(); removeUpdate(); };
  }, []);

  async function login(event) {
    event.preventDefault();
    setError("");
    const formattedRut = formatRutInput(credentials.rut);
    setCredentials((value) => ({ ...value, rut: formattedRut }));
    if (!isValidRut(formattedRut)) {
      setError("RUT inválido. Revisa el número y dígito verificador.");
      return;
    }
    setBusy(true);
    setMessage("Iniciando sesion...");
    const result = await window.desktopApi.login({
      ...credentials,
      rut: normalizeRut(formattedRut)
    });
    if (!result.ok) { setBusy(false); setError(result.message); }
  }

  async function discover() {
    setError("");
    if (!company || !period.desde || !period.hasta) {
      setError("Selecciona una empresa y completa ambos periodos.");
      return;
    }
    if (period.desde > period.hasta) {
      setError("El periodo inicial no puede ser posterior al periodo final.");
      return;
    }
    setBusy(true);
    setMessage("Buscando nominas disponibles...");
    const result = await window.desktopApi.discover({ ...company, ...period });
    if (!result.ok) { setBusy(false); setError(result.message); }
  }

  async function startDownload() {
    setError("");
    setBusy(true);
    setTimeline([]);
    setCurrent(null);
    setSummary({ ok: 0, empty: 0, errors: 0, skipped: 0 });
    setStep(3);
    setMessage("Preparando descarga...");
    const result = await window.desktopApi.download(selectedItems);
    if (!result.ok) { setBusy(false); setStep(2); setError(result.message); }
  }

  async function cancel() {
    setMessage("Deteniendo de forma segura...");
    await window.desktopApi.cancel();
  }

  async function save() {
    const result = await window.desktopApi.saveResult(outputPath);
    if (result.ok) setMessage(`ZIP guardado en ${result.filePath}`);
  }

  function toggle(periodo, slug) {
    const key = `${periodo}|${slug}`;
    setSelected((value) => {
      const next = new Set(value);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  function reset() {
    setStep(1);
    setPeriodGroups([]);
    setSelected(new Set());
    setTimeline([]);
    setCurrent(null);
    setOutputPath("");
    setError("");
    setMessage("Selecciona la empresa y el rango de periodos.");
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><FileArchive aria-hidden="true" /></div>
          <div><p>Automatizacion local</p><h1>Previred Downloader</h1></div>
        </div>
        <div className="top-actions">
          {appInfo?.packaged && <button className="quiet" onClick={() => window.desktopApi.checkForUpdates()}><RefreshCw /> Actualizar</button>}
          <span className="version">v{appInfo?.version || "..."}</span>
        </div>
      </header>

      {!["idle", "not-available"].includes(update.type) && (
        <aside className={`update-banner ${update.type}`}>
          <span>{update.message}</span>
          {update.type === "available" && <button onClick={() => window.desktopApi.downloadUpdate()}>Descargar</button>}
          {update.type === "downloaded" && <button onClick={() => window.desktopApi.installUpdate()}>Reiniciar e instalar</button>}
          {update.type === "downloading" && <strong>{Math.round(update.percent || 0)}%</strong>}
        </aside>
      )}

      <nav className="stepper" aria-label="Progreso">
        {steps.map((label, index) => (
          <React.Fragment key={label}>
            <div className={`step ${index === step ? "active" : ""} ${index < step ? "done" : ""}`}>
              <span>{index < step ? <Check /> : index + 1}</span><small>{label}</small>
            </div>
            {index < steps.length - 1 && <ChevronRight className="step-arrow" />}
          </React.Fragment>
        ))}
      </nav>

      <section className="workspace">
        {error && <div className="alert error"><X /> <span>{error}</span></div>}
        <div className="status-line">{busy && <LoaderCircle className="spin" />}<span>{message}</span></div>

        {step === 0 && (
          <form className="card access-card" onSubmit={login}>
            <div className="card-icon"><ShieldCheck /></div>
            <h2>Acceso seguro</h2>
            <p>Las credenciales se usan solo en memoria y nunca se guardan en el equipo.</p>
            <label>RUT<input value={credentials.rut} onChange={(e) => setCredentials((v) => ({ ...v, rut: formatRutInput(e.target.value) }))} placeholder="15.644.021-3" autoComplete="username" inputMode="text" maxLength={12} autoFocus /></label>
            <label>Contraseña<div className="input-icon"><KeyRound /><input type="password" value={credentials.password} onChange={(e) => setCredentials((v) => ({ ...v, password: e.target.value }))} autoComplete="current-password" /></div></label>
            <button className="primary" type="submit" disabled={busy}>{busy ? "Conectando..." : "Conectar con Previred"}</button>
          </form>
        )}

        {step === 1 && (
          <div className="grid two-columns">
            <section className="card company-card">
              <div className="section-title"><Building2 /><div><h2>Empresa</h2><p>{companies.length} disponibles</p></div></div>
              <div className="search"><Search /><input aria-label="Buscar empresa por nombre o RUT" value={companyQuery} onChange={(e) => setCompanyQuery(e.target.value)} placeholder="Buscar por nombre o RUT" /></div>
              <div className="company-list">
                {filteredCompanies.map((item) => (
                  <button key={`${item.rut}-${item.nombre}`} className={company?.rut === item.rut && company?.nombre === item.nombre ? "selected" : ""} onClick={() => setCompany(item)}>
                    <strong>{item.nombre}</strong><small>{item.rut}</small>
                  </button>
                ))}
              </div>
            </section>
            <section className="card period-card">
              <h2>Rango de periodos</h2><p>Indica los meses que quieres revisar.</p>
              <label>Desde<input type="month" value={period.desde} onChange={(e) => setPeriod((v) => ({ ...v, desde: e.target.value }))} /></label>
              <label>Hasta<input type="month" value={period.hasta} onChange={(e) => setPeriod((v) => ({ ...v, hasta: e.target.value }))} /></label>
              <button className="primary" onClick={discover} disabled={busy || !company}>Buscar nominas</button>
            </section>
          </div>
        )}

        {step === 2 && (
          <section className="card selection-card">
            <div className="selection-head"><div><h2>Nominas encontradas</h2><p>{company?.nombre} · {period.desde} a {period.hasta}</p></div><strong>{selectedItems.length} seleccionadas</strong></div>
            <div className="period-list">
              {periodGroups.map((group) => (
                <div className="period-group" key={group.periodo}>
                  <h3>{group.periodo}</h3>
                  {group.nominas.map((item) => {
                    const checked = selected.has(`${group.periodo}|${item.slug}`);
                    return <label className="check-row" key={item.slug}><input type="checkbox" checked={checked} onChange={() => toggle(group.periodo, item.slug)} /><span>{item.nombre}</span></label>;
                  })}
                </div>
              ))}
              {!periodGroups.length && <div className="empty">No se encontraron nominas AFP. Vuelve y prueba otro rango.</div>}
            </div>
            <div className="footer-actions"><button className="secondary" onClick={() => setStep(1)}>Cambiar busqueda</button><button className="primary" onClick={startDownload} disabled={!selectedItems.length}>Descargar seleccionadas</button></div>
          </section>
        )}

        {step === 3 && (
          <section className="card download-card">
            <div className="selection-head"><div><h2>Descargando planillas</h2><p>Puedes detener el proceso y conservar lo ya descargado.</p></div><button className="danger" onClick={cancel}><Square /> Detener</button></div>
            <div className="metrics"><Metric value={summary.ok} label="Descargadas" tone="green" /><Metric value={summary.empty} label="Sin datos" tone="amber" /><Metric value={summary.errors} label="Errores" tone="red" /></div>
            {current && <div className="current-item"><LoaderCircle className="spin" /><div><strong>{current.periodo} · {current.nomina}</strong><small>{current.detail}</small></div></div>}
            <div className="timeline">
              {timeline.map((item) => <div className={`timeline-row ${item.estado}`} key={`${item.periodo}-${item.nomina}`}><span></span><div><strong>{item.periodo}</strong><small>{item.nomina}</small></div></div>)}
            </div>
          </section>
        )}

        {step === 4 && (
          <section className="card done-card">
            <div className="success-mark"><Check /></div><h2>Archivo listo</h2><p>El ZIP contiene las planillas organizadas en carpetas por AFP y conserva los resultados parciales si detuviste el proceso.</p>
            <div className="metrics"><Metric value={summary.ok} label="Descargadas" tone="green" /><Metric value={summary.empty} label="Sin datos" tone="amber" /><Metric value={summary.errors} label="Errores" tone="red" /></div>
            <button className="primary large" onClick={save} disabled={!outputPath}><Download /> Guardar ZIP</button>
            <button className="quiet" onClick={reset}>Nueva ejecucion</button>
          </section>
        )}
      </section>
    </main>
  );
}

function Metric({ value, label, tone }) {
  return <div className={`metric ${tone}`}><strong>{value}</strong><span>{label}</span></div>;
}

createRoot(document.getElementById("root")).render(<App />);
