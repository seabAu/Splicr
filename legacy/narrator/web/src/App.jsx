import React, { useEffect, useState } from "react";
import { getSchema, getEngines, validate, startRender, getTakes } from "./api";
import SettingsForm from "./SettingsForm";
import FileBrowser from "./FileBrowser";
import JobLog from "./JobLog";
import JobList from "./JobList";
import Library from "./Library";
import Publish from "./Publish";
import Dialogue from "./Dialogue";
import Components from "./Components";
import Pronunciation from "./Pronunciation";
import Convert from "./Convert";
import VoiceStudio from "./VoiceStudio";
import TimelineEditor from "./TimelineEditor";
import AudiogramEditor from "./AudiogramEditor";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import ErrorBoundary from "@/components/ErrorBoundary";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

// A real tabbed layout, not a page that scrolls forever -- this is what
// the desktop app already does with its own ttk.Notebook (Document /
// Voice / Output / Publish, plus separate dialogs for the rest); the web
// port had flattened everything into one linear stack of <section>s.
//
// Each tab's content mounts the FIRST time it's opened, then stays
// mounted (hidden with display:none, not unmounted) for the rest of the
// session -- switching tabs never loses whatever you were in the middle
// of typing, matching how Tk's Notebook keeps every tab's widgets alive
// under the hood. Mounting lazily (not all ten at once on page load)
// avoids every tab firing its own startup API calls before you've even
// looked at it.
const TABS = [
  { key: "narrate", label: "Narrate" },
  { key: "library", label: "Library" },
  { key: "timeline", label: "Timeline" },
  { key: "audiogram", label: "Audiogram" },
  { key: "publish", label: "Publish" },
  { key: "voices", label: "Voice studio" },
  { key: "dialogue", label: "Dialogue" },
  { key: "pronunciation", label: "Pronunciation" },
  { key: "components", label: "Components" },
  { key: "convert", label: "Convert" },
];

// Radix unmounts an inactive tab's content by default, which would throw
// away whatever was half-typed in it. forceMount keeps it in the DOM --
// but forceMount ALONE would also mount all ten on first paint, firing
// every tab's startup requests at once. Pairing it with `visited` keeps
// both properties: nothing mounts until first opened, and nothing
// unmounts after that. Radix still needs the hidden ones visually gone,
// which it does NOT do itself under forceMount, hence the explicit
// display toggle.
function TabPanel({ tabKey, activeTab, visited, children }) {
  if (!visited.has(tabKey)) return null;
  return (
    <TabsContent
      value={tabKey}
      forceMount
      className="tab-panel"
      style={{ display: activeTab === tabKey ? undefined : "none" }}
    >
      <ErrorBoundary label={TABS.find((t) => t.key === tabKey)?.label}>
        {children}
      </ErrorBoundary>
    </TabsContent>
  );
}

export default function App() {
  const [schema, setSchema] = useState(null);
  const [engines, setEngines] = useState([]);
  const [cfg, setCfg] = useState({});
  const [problems, setProblems] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [takes, setTakes] = useState([]);
  const [picking, setPicking] = useState(null); // "path" | "root" | null
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState("");
  const [jobsKey, setJobsKey] = useState(0);
  const [activeTab, setActiveTab] = useState("narrate");
  const [visited, setVisited] = useState(() => new Set(["narrate"]));

  const switchTab = (key) => {
    setActiveTab(key);
    setVisited((v) => (v.has(key) ? v : new Set(v).add(key)));
  };

  useEffect(() => {
    (async () => {
      try {
        const s = await getSchema();
        setSchema(s);
        setCfg(s.defaults);
        const e = await getEngines();
        setEngines(e.engines);
        setCfg((prev) => ({ ...prev, root: prev.root || e.output_root }));
      } catch (err) {
        setError(
          `Couldn't reach the app: ${err.message}. If you opened this page ` +
            `by hand, use the address the app printed -- it carries the token.`
        );
      }
    })();
  }, []);

  // Validate as the form changes: the same verdict a render would give,
  // so nothing is a surprise at the moment you press Generate.
  useEffect(() => {
    if (!schema || !cfg.path) return;
    let cancelled = false;
    validate(cfg)
      .then((r) => !cancelled && setProblems(r.problems))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [cfg, schema]);

  const change = (key, value) => setCfg((prev) => ({ ...prev, [key]: value }));

  const generate = async () => {
    setError("");
    try {
      const job = await startRender(cfg);
      setJobId(job.id);
    } catch (err) {
      setError(err.message);
    }
  };

  if (error && !schema) return <div className="app error">{error}</div>;
  if (!schema) return <div className="app">Loading…</div>;

  const installed = engines.filter((e) => e.installed);
  const blocking = problems.filter(
    (p) =>
      p.includes("required") ||
      p.includes("isn't one of") ||
      p.includes("no file at") ||
      p.includes("no folder at")
  );

  return (
    <div className="app">
      <h1>Narrator</h1>

      <Tabs value={activeTab} onValueChange={switchTab}>
      <TabsList>
        {TABS.map((t) => (
          <TabsTrigger key={t.key} value={t.key}>
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>

      {picking && (
        <FileBrowser
          onlyDirs={picking === "root"}
          onPick={(p) => {
            change(picking, p);
            setPicking(null);
          }}
          onClose={() => setPicking(null)}
        />
      )}

      <TabPanel tabKey="narrate" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Document</h2>
          <div className="row">
            <code>{cfg.path || "no document chosen"}</code>
            <Button onClick={() => setPicking("path")}>Choose…</Button>
          </div>
          <div className="row">
            <code>{cfg.root || "no output folder"}</code>
            <Button onClick={() => setPicking("root")}>Output folder…</Button>
          </div>
        </section>

        <section>
          <h2>Settings</h2>
          {installed.length === 0 && (
            <p className="warn">
              No engine is installed yet.{" "}
              <Button
                variant="link"
                className="h-auto p-0 text-warning underline"
                onClick={() => switchTab("components")}
              >
                Set one up in Components
              </Button>
              .
            </p>
          )}
          <div className="mb-2.5 flex items-center gap-2">
            <Checkbox
              id="show-every-setting"
              checked={advanced}
              onCheckedChange={(c) => setAdvanced(c === true)}
            />
            <Label htmlFor="show-every-setting">Show every setting</Label>
          </div>
          <SettingsForm
            fields={schema.fields}
            cfg={cfg}
            onChange={change}
            advanced={advanced}
            engines={engines}
            // Chosen in the Document section above, which is the better
            // place for them; listing them again here was a duplicate.
            hide={["path", "root"]}
          />
        </section>

        {problems.length > 0 && (
          <ul className="problems">
            {problems.map((p) => (
              <li key={p} className={blocking.includes(p) ? "error" : "note"}>
                {p}
              </li>
            ))}
          </ul>
        )}

        <Button
          variant="primary"
          size="lg"
          className="my-4"
          disabled={blocking.length > 0 || !cfg.path}
          onClick={generate}
        >
          Generate audio
        </Button>
        {error && <p className="error">{error}</p>}

        <JobLog
          jobId={jobId}
          onFinished={() => {
            getTakes().then((r) => setTakes(r.takes));
            setJobsKey((k) => k + 1);
          }}
        />
      </TabPanel>

      <TabPanel tabKey="library" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Library</h2>
          <Library
            refreshKey={jobsKey}
            onLoad={(project) => {
              // The saved cfg is the same shape the form uses, so it goes
              // straight back in -- no mapping layer to drift.
              setCfg((prev) => ({ ...prev, ...project.cfg, path: project.path }));
              switchTab("narrate");
            }}
          />
        </section>
      </TabPanel>

      <TabPanel tabKey="timeline" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Timeline</h2>
          <TimelineEditor />
        </section>
      </TabPanel>

      <TabPanel tabKey="audiogram" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Audiogram</h2>
          <AudiogramEditor />
        </section>
      </TabPanel>

      <TabPanel tabKey="publish" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Publish</h2>
          <Publish refreshKey={jobsKey} />
        </section>
      </TabPanel>

      <TabPanel tabKey="voices" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Voice studio</h2>
          <VoiceStudio />
        </section>
      </TabPanel>

      <TabPanel tabKey="dialogue" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Two-host dialogue</h2>
          <Dialogue cfg={cfg} onJob={() => setJobsKey((k) => k + 1)} />
        </section>
      </TabPanel>

      <TabPanel tabKey="pronunciation" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Pronunciation</h2>
          <Pronunciation />
        </section>
      </TabPanel>

      <TabPanel tabKey="components" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Components and add-ons</h2>
          <Components onJob={() => setJobsKey((k) => k + 1)} />
        </section>
      </TabPanel>

      <TabPanel tabKey="convert" activeTab={activeTab} visited={visited}>
        <section>
          <h2>Convert audio</h2>
          <Convert onJob={() => setJobsKey((k) => k + 1)} />
        </section>
      </TabPanel>
      </Tabs>

      {/* Cross-cutting status, visible regardless of which tab is open --
         a background job (an install, an export, a render) shouldn't
         disappear from view just because you switched tabs to look at
         something else. Deliberately OUTSIDE <Tabs>: it belongs to no
         tab and must never be unmounted with one. */}
      <JobList refreshKey={jobsKey} />

      {takes.length > 0 && (
        <section>
          <h2>Takes this session</h2>
          <ul>
            {takes.map((t) => (
              <li key={t.out_path}>
                <code>{t.name}</code> — {t.engine}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
