"""
Durable harvester for the Railway `ob-logger` C2 order-book signals.

WHY THIS EXISTS
    The Railway service `ob-logger` only prints `SIGNAL <json>` lines to stdout.
    Railway keeps a short rolling buffer (~200 lines), so signals are lost within
    hours. This tool tails `railway logs`, deduplicates, and appends every signal
    to an append-only JSONL store so the dataset is realistic, complete going
    forward, and reusable for backtests.

STORE
    research/ob_data/signals.jsonl   -- append-only, one JSON object per line.
    Deduplicated on key = f"{symbol}:{breakout_bar_ms}" (a unique breakout event).
    Each stored record is the raw signal plus two meta fields:
        _src          "ingest" | "railway"   (where we captured it)
        _harvested_at UTC ISO of when the harvester saw it (null for old backfill)
    Raw fields (ts_utc, symbol, dir, rvol5, range6h_pct, breakout_*, book{...})
    are preserved untouched, so the file is self-describing and future-proof.

USAGE
    python harvest.py ingest <file>...   seed/merge SIGNAL or bare-json lines from files
    python harvest.py once                pull the current railway buffer, merge, exit
    python harvest.py watch               stream railway logs forever, append live
    python harvest.py stats               summarize the store (counts, range, splits)

`once` and `ingest` are idempotent; run them as often as you like without dupes.
`watch` re-spawns `railway logs` if the connection drops, so it survives outages.
"""
import os, sys, json, time, threading, queue, subprocess, shutil, collections
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "signals.jsonl")
SERVICE = os.environ.get("OB_SERVICE", "ob-logger")
RAILWAY = shutil.which("railway") or "railway"
DECODER = json.JSONDecoder()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_ts(ts):
    """Normalize any ts_utc form to 'YYYY-MM-DDTHH:MM:SSZ'."""
    if not ts:
        return ts
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ts


def key_of(rec):
    return f"{rec.get('symbol')}:{rec.get('breakout_bar_ms')}"


def extract_signal(line):
    """Return the signal dict from a log/jsonl line, or None.

    Handles three shapes: a raw `SIGNAL {json}` log line, a railway --json
    wrapper whose message contains one, and a bare `{json}` line (old store).
    """
    line = line.strip()
    if not line:
        return None
    i = line.find("SIGNAL ")
    if i >= 0:
        frag = line[i + 7:].lstrip()
    elif line[0] == "{":
        frag = line
    else:
        return None
    try:
        rec, _ = DECODER.raw_decode(frag)
    except Exception:
        return None
    if not isinstance(rec, dict):
        return None
    # railway --json wrapper: signal is inside the "message" field
    if "breakout_bar_ms" not in rec and isinstance(rec.get("message"), str):
        return extract_signal(rec["message"])
    if "symbol" not in rec or "breakout_bar_ms" not in rec:
        return None
    return rec


def load_seen():
    seen = set()
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    seen.add(key_of(json.loads(ln)))
                except Exception:
                    pass
    return seen


class Store:
    def __init__(self):
        self.seen = load_seen()
        self._fh = open(STORE, "a", encoding="utf-8")

    def add(self, rec, src):
        rec["ts_utc"] = norm_ts(rec.get("ts_utc"))
        k = key_of(rec)
        if k in self.seen:
            return False
        rec["_src"] = src
        rec["_harvested_at"] = now_iso() if src == "railway" else rec.get("_harvested_at")
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()
        self.seen.add(k)
        return True

    def close(self):
        self._fh.close()


def cmd_ingest(paths):
    if not paths:
        print("usage: harvest.py ingest <file>...")
        return
    st = Store()
    added = 0
    for p in paths:
        if not os.path.exists(p):
            print(f"skip (missing): {p}")
            continue
        n = 0
        with open(p, encoding="utf-8", errors="replace") as f:
            for ln in f:
                rec = extract_signal(ln)
                if rec and st.add(rec, "ingest"):
                    n += 1
        added += n
        print(f"ingested {n:>4} new from {p}")
    st.close()
    print(f"total new: {added}  |  store now: {len(load_seen())} signals")


def _spawn_logs():
    cmd = [RAILWAY, "logs", "-s", SERVICE]
    if os.name == "nt" and RAILWAY.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c"] + cmd  # .cmd shims need the interpreter on Windows
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )


def _reader(proc, q):
    for ln in proc.stdout:
        q.put(ln)
    q.put(None)  # sentinel: stream ended


def cmd_once(idle=10, cap=150):
    """Drain the current railway buffer: read until idle seconds pass or cap hit."""
    st = Store()
    proc = _spawn_logs()
    q = queue.Queue()
    threading.Thread(target=_reader, args=(proc, q), daemon=True).start()
    added = 0
    start = time.time()
    while time.time() - start < cap:
        try:
            ln = q.get(timeout=idle)
        except queue.Empty:
            break  # buffer drained, no new lines for `idle`s
        if ln is None:
            break
        rec = extract_signal(ln)
        if rec and st.add(rec, "railway"):
            added += 1
    try:
        proc.terminate()
    except Exception:
        pass
    st.close()
    print(f"once: +{added} new  |  store now: {len(load_seen())} signals")


def cmd_watch():
    st = Store()
    print(f"watching railway logs for '{SERVICE}' -> {STORE}  (Ctrl+C to stop)")
    added = 0
    try:
        while True:
            proc = _spawn_logs()
            q = queue.Queue()
            threading.Thread(target=_reader, args=(proc, q), daemon=True).start()
            while True:
                ln = q.get()
                if ln is None:
                    break  # stream dropped -> re-spawn
                rec = extract_signal(ln)
                if rec and st.add(rec, "railway"):
                    added += 1
                    print(f"[{now_iso()}] +{rec['symbol']} {rec.get('dir')} "
                          f"rvol={rec.get('rvol5')} (total {len(st.seen)})", flush=True)
            print(f"[{now_iso()}] stream dropped, reconnecting in 5s...", flush=True)
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        st.close()
        print(f"stopped. session added {added}, store now {len(load_seen())}.")


def cmd_stats():
    if not os.path.exists(STORE):
        print("no store yet."); return
    recs = []
    with open(STORE, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    recs.append(json.loads(ln))
                except Exception:
                    pass
    if not recs:
        print("store empty."); return
    recs.sort(key=lambda r: r.get("ts_utc") or "")
    d = collections.Counter(r.get("dir") for r in recs)
    sym = collections.Counter(r.get("symbol") for r in recs)
    src = collections.Counter(r.get("_src") for r in recs)
    rv = sorted(r["rvol5"] for r in recs if isinstance(r.get("rvol5"), (int, float)))
    print(f"signals: {len(recs)}")
    print(f"range:   {recs[0]['ts_utc']}  ->  {recs[-1]['ts_utc']}  (UTC)")
    print(f"dir:     {dict(d)}")
    print(f"source:  {dict(src)}")
    print(f"symbols: {len(sym)} unique | top: {sym.most_common(8)}")
    if rv:
        print(f"rvol5:   min {rv[0]} / med {rv[len(rv)//2]} / max {rv[-1]}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "ingest":
        cmd_ingest(sys.argv[2:])
    elif cmd == "once":
        cmd_once()
    elif cmd == "watch":
        cmd_watch()
    elif cmd == "stats":
        cmd_stats()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
