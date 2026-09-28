import os, sys, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), HERE, os.path.dirname(HERE)]
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
D = "/tmp/wfiles"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)

os.makedirs(f"{D}/sub1/sub2", exist_ok=True)
open(f"{D}/alpha.txt", "w").write("a")
time.sleep(0.02)
open(f"{D}/beta.md", "w").write("bb")
os.makedirs(f"{D}/zeta_folder", exist_ok=True)
open(f"{D}/sub1/gamma.txt", "w").write("g")
open(f"{D}/sub1/sub2/delta_report.txt", "w").write("deltadeltadelta")
open(f"{D}/.hidden", "w").write("h")

from fastapi.testclient import TestClient
from narrator import webapi
from narrator.config import APP_DIR
c = TestClient(webapi.create_app())
H = {"X-Narrator-Token": webapi.TOKEN}

# --- default path is APP_DIR, not the OS home folder ---
r = c.get("/api/files", headers=H)
d = r.json()
assert d["path"] == os.path.abspath(APP_DIR)
print(f"D1 ok: no path given defaults to APP_DIR -- {d['path']}")

# --- basic listing: entries, mtime, hidden files excluded ---
r2 = c.get("/api/files", headers=H, params={"path": D})
d2 = r2.json()
names = {e["name"] for e in d2["entries"]}
assert names == {"alpha.txt", "beta.md", "sub1", "zeta_folder"}
assert ".hidden" not in names
print(f"L1 ok: lists real entries, hidden files excluded: {sorted(names)}")

by_name = {e["name"]: e for e in d2["entries"]}
assert all("mtime" in e and e["mtime"] > 0 for e in d2["entries"])
assert by_name["alpha.txt"]["mtime"] < by_name["beta.md"]["mtime"]
print("L2 ok: every entry has a real mtime, and creation order is "
     "reflected in it (alpha before beta)")

assert by_name["alpha.txt"]["size"] == 1
assert by_name["sub1"]["size"] is None
print("L3 ok: files report a real size, folders report none")

# --- parent navigation ---
sub_listing = c.get("/api/files", headers=H,
                    params={"path": f"{D}/sub1"}).json()
assert sub_listing["parent"] == os.path.abspath(D)
print("N1 ok: a subfolder's parent points back up correctly")

root_listing = c.get("/api/files", headers=H, params={"path": "/"}).json()
assert root_listing["parent"] is None
print("N2 ok: the filesystem root reports no parent (nowhere further up)")

# --- only_dirs filters to folders alone ---
dirs_only = c.get("/api/files", headers=H,
                  params={"path": D, "only_dirs": True}).json()
dir_names = {e["name"] for e in dirs_only["entries"]}
assert dir_names == {"sub1", "zeta_folder"}
print(f"O1 ok: only_dirs excludes files entirely: {sorted(dir_names)}")

# --- a missing folder is a clean 404 ---
missing = c.get("/api/files", headers=H, params={"path": f"{D}/nope"})
assert missing.status_code == 404
print("E1 ok: a nonexistent folder is a clean 404")

# --- recursive search ---
search = c.get("/api/files", headers=H,
              params={"path": D, "search": "delta"}).json()
assert len(search["entries"]) == 1
found = search["entries"][0]
assert found["name"] == "delta_report.txt"
assert found["folder"] == os.path.join("sub1", "sub2")
print(f"S1 ok: recursive search finds a file 2 levels down and reports "
     f"its containing subfolder: {found['folder']}")

search2 = c.get("/api/files", headers=H,
               params={"path": D, "search": "gamma"}).json()
assert len(search2["entries"]) == 1
assert search2["entries"][0]["folder"] == "sub1"
print("S2 ok: a shallower match reports its own correct subfolder")

no_match = c.get("/api/files", headers=H,
                 params={"path": D, "search": "nonexistentxyz"}).json()
assert no_match["entries"] == []
print("S3 ok: a search with no matches returns an empty list, not an error")

search_depth = c.get("/api/files", headers=H, params={
    "path": D, "search": "delta", "search_depth": 1}).json()
assert search_depth["entries"] == []
print("S4 ok: search_depth actually limits how far down the walk goes "
     "-- a depth-1 cap misses a file 2 levels down")

hidden_search = c.get("/api/files", headers=H,
                      params={"path": D, "search": "hidden"}).json()
assert hidden_search["entries"] == []
print("S5 ok: a hidden file is excluded from search results too, "
     "consistent with the plain listing")

# --- /api/schema exposes path_kind so the client knows file vs folder ---
schema = c.get("/api/schema", headers=H).json()
by_key = {f["key"]: f for f in schema["fields"]}
assert by_key["path"]["path_kind"] == "file"
assert by_key["root"]["path_kind"] == "dir"
assert by_key["video_image"]["path_kind"] == "file"
assert by_key["intro_audio"]["path_kind"] == "file"
assert by_key["outro_audio"]["path_kind"] == "file"
print("P1 ok: every path-kind schema field reports whether it wants a "
     "file or a folder -- this is what tells the browse button whether "
     "to navigate INTO a chosen folder or treat it as the pick itself")

print("\nALL WEB FILES TESTS PASSED")
