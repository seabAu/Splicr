import React, { useEffect, useMemo, useRef, useState } from "react";
import { listFiles } from "./api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ArrowDown,
  ArrowUp,
  File,
  Folder,
  ParentFolder,
  Search,
} from "@/components/ui/icons";
import { cn } from "@/lib/utils";

// A browser can't hand a path to the backend, so the backend browses on
// its behalf. Now a real modal: focus stays inside while a path is being
// chosen, the page behind is inert, and Escape/backdrop close it.
//
// Props are unchanged from the inline version, so no caller had to
// change: mounting it opens it, and onClose fires on every dismissal.
//
// `multiple`: clicking a file toggles its selection; "Choose N"
// confirms, and onPick receives an array. Off by default.
// `onlyDirs`: picking a FOLDER. "Use this folder" picks the one being
// viewed -- previously the only way to pick a folder was its "choose"
// button seen from its parent, so the folder you'd navigated INTO
// couldn't be chosen at all.

const SORTS = {
  name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }),
  type: (a, b) => {
    const ea = a.dir ? "" : a.name.split(".").pop() || "";
    const eb = b.dir ? "" : b.name.split(".").pop() || "";
    return ea.localeCompare(eb) || a.name.localeCompare(b.name);
  },
  modified: (a, b) => (b.mtime || 0) - (a.mtime || 0),
  size: (a, b) => (b.size || 0) - (a.size || 0),
};

const COLS = "grid grid-cols-[minmax(0,1fr)_4.5rem_6.5rem_4.5rem] gap-2";

function fmtSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDate(mtime) {
  if (!mtime) return "";
  return new Date(mtime * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function extOf(entry) {
  return entry.dir ? "folder" : entry.name.split(".").pop() || "";
}

export default function FileBrowser({
  onPick,
  onlyDirs = false,
  onClose,
  multiple = false,
}) {
  const [state, setState] = useState({ path: "", entries: [], parent: null });
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("name");
  const [sortAsc, setSortAsc] = useState(true);
  const [selected, setSelected] = useState(new Set());
  const debounceRef = useRef(null);
  const firstRun = useRef(true);

  const go = async (path, search = "") => {
    try {
      setState(await listFiles(path, onlyDirs, search));
      setError("");
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  useEffect(() => {
    go("");
  }, []);

  // Debounced: a search walks the filesystem server-side. Skipped on the
  // first render, which the effect above already covers -- otherwise the
  // opening listing was fetched twice.
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => go(state.path, query), 250);
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const navigate = (path) => {
    setQuery("");
    setSelected(new Set());
    go(path);
  };

  const sorted = useMemo(() => {
    const list = [...state.entries].sort(SORTS[sortKey] || SORTS.name);
    if (!sortAsc) list.reverse();
    // Folders first whichever way it's sorted -- applied AFTER the
    // direction, so reversing a sort never pushes folders to the bottom.
    return list.sort((a, b) => (b.dir ? 1 : 0) - (a.dir ? 1 : 0));
  }, [state.entries, sortKey, sortAsc]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortAsc((asc) => !asc);
    else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const clickEntry = (entry) => {
    if (entry.dir) return navigate(entry.path);
    if (multiple) {
      setSelected((old) => {
        const next = new Set(old);
        next.has(entry.path) ? next.delete(entry.path) : next.add(entry.path);
        return next;
      });
      return;
    }
    onPick(entry.path);
  };

  const SortHeader = ({ col, label, className }) => (
    <button
      type="button"
      onClick={() => toggleSort(col)}
      className={cn(
        "flex items-center gap-1 text-left text-[11px] text-muted-foreground",
        "hover:text-foreground",
        sortKey === col && "text-foreground",
        className
      )}
      aria-label={`Sort by ${label}`}
    >
      {label}
      {sortKey === col &&
        (sortAsc ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        ))}
    </button>
  );

  const title = onlyDirs
    ? "Choose a folder"
    : multiple
    ? "Choose files"
    : "Choose a file";

  return (
    <Dialog open onOpenChange={(open) => !open && onClose?.()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="truncate font-mono" title={state.path}>
            {state.path || "…"}
          </DialogDescription>
        </DialogHeader>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="Search this folder and below…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search files"
          />
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className={cn(COLS, "border-b border-border px-2 pb-1")}>
          <SortHeader col="name" label="Name" />
          <SortHeader col="type" label="Type" />
          <SortHeader col="modified" label="Modified" />
          <SortHeader col="size" label="Size" className="justify-end" />
        </div>

        <ul className="-mt-2 max-h-[46vh] min-h-[12rem] overflow-y-auto">
          {!query && state.parent != null && (
            <li>
              <button
                type="button"
                onClick={() => navigate(state.parent)}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-[13px] text-primary hover:bg-secondary"
              >
                <ParentFolder className="h-4 w-4" />
                Up a level
              </button>
            </li>
          )}

          {sorted.map((entry) => {
            const isSel = selected.has(entry.path);
            const Icon = entry.dir ? Folder : File;
            return (
              <li key={entry.path} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => clickEntry(entry)}
                  aria-pressed={multiple && !entry.dir ? isSel : undefined}
                  className={cn(
                    COLS,
                    "min-w-0 flex-1 items-center rounded px-2 py-1.5 text-left",
                    "text-[13px] hover:bg-secondary focus-visible:outline-none",
                    "focus-visible:ring-2 focus-visible:ring-ring",
                    isSel && "bg-accent text-accent-foreground"
                  )}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    {multiple && !entry.dir && (
                      // Visual only: the row button above is the
                      // control, and reports its state via aria-pressed.
                      <Checkbox
                        checked={isSel}
                        tabIndex={-1}
                        aria-hidden
                        className="pointer-events-none"
                      />
                    )}
                    <Icon
                      className={cn(
                        "h-4 w-4 shrink-0",
                        entry.dir ? "text-primary" : "text-muted-foreground"
                      )}
                    />
                    <span className="truncate">{entry.name}</span>
                    {entry.folder && entry.folder !== "." && (
                      <span className="truncate text-[11px] text-muted-foreground">
                        {entry.folder}
                      </span>
                    )}
                  </span>
                  <span className="truncate text-[11px] text-muted-foreground">
                    {extOf(entry)}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {fmtDate(entry.mtime)}
                  </span>
                  <span className="text-right text-[11px] text-muted-foreground">
                    {fmtSize(entry.size)}
                  </span>
                </button>
                {onlyDirs && entry.dir && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-primary"
                    onClick={() => onPick(entry.path)}
                  >
                    choose
                  </Button>
                )}
              </li>
            );
          })}

          {sorted.length === 0 && !error && (
            <li className="px-2 py-6 text-center text-xs text-muted-foreground">
              {query ? "No matches." : "Nothing here."}
            </li>
          )}
        </ul>

        {(multiple || onlyDirs) && (
          <DialogFooter className="border-t border-border pt-3">
            {multiple && (
              <>
                <span className="mr-auto text-xs text-muted-foreground">
                  {selected.size
                    ? `${selected.size} selected`
                    : "Click files to select more than one."}
                </span>
                <Button
                  variant="primary"
                  disabled={selected.size === 0}
                  onClick={() => onPick(Array.from(selected))}
                >
                  Choose {selected.size || ""}
                </Button>
              </>
            )}
            {onlyDirs && (
              <Button
                variant="primary"
                disabled={!state.path || !!query}
                onClick={() => onPick(state.path)}
              >
                Use this folder
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
