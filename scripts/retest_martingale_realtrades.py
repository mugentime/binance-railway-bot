#!/usr/bin/env python3
"""What-if martingale on the REAL executed retest_trader trades (both SL 2% & SL 3% regimes).
Reconstructs each trade's return-on-notional (move%, incl. real slippage/fees) from live
userTrades, then simulates FLAT vs martingale 1.25x/1.5x/2.0x (reset on win, escalate on loss),
compounding on account equity, capped by 10x-leverage margin (can't bet >~9.5x equity)."""
import os, time, hmac, hashlib, urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import httpx
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception: pass
K=os.environ["BINANCE_API_KEY"]; S=os.environ["BINANCE_API_SECRET"]; F="https://fapi.binance.com"
CT=ZoneInfo("America/Chicago"); C=httpx.Client(timeout=40.0)
OFF=int(C.get(F+"/fapi/v1/time").json()["serverTime"])-int(time.time()*1000)
def sg(p,q=None):
    q=dict(q or {}); q["timestamp"]=int(time.time()*1000)+OFF; q["recvWindow"]=20000
    s=urllib.parse.urlencode(q); q["signature"]=hmac.new(S.encode(),s.encode(),hashlib.sha256).hexdigest()
    r=C.request("GET",F+p,params=q,headers={"X-MBX-APIKEY":K}); r.raise_for_status(); return r.json()
def ct(ms): return datetime.fromtimestamp(ms/1000,tz=timezone.utc).astimezone(CT).strftime("%m-%d %I:%M%p")

GO=int(datetime(2026,8,12,tzinfo=timezone.utc).timestamp()*1000); NOW=int(time.time()*1000)+OFF
bnb=float(C.get(F+"/fapi/v1/ticker/price",params={"symbol":"BNBUSDT"}).json()["price"])

# symbols from income
inc=[]; st=GO
while True:
    b=sg("/fapi/v1/income",{"startTime":st,"endTime":NOW,"limit":1000})
    if not b: break
    inc+=b
    if len(b)<1000: break
    st=int(b[-1]["time"])+1
symbols=sorted({x["symbol"] for x in inc if x["incomeType"]=="REALIZED_PNL" and x.get("symbol")})

# reconstruct trades per symbol from userTrades
# NOTE: Binance futures userTrades restricts startTime->endTime to <=7 days per call
# (and silently truncates to ~7d if endTime is omitted) -> must page in <=6d windows.
WIN_MS = 6*24*60*60*1000
def fetch_user_trades(sym):
    out=[]; ws=GO
    while ws<NOW:
        we=min(ws+WIN_MS, NOW)
        b=sg("/fapi/v1/userTrades",{"symbol":sym,"startTime":ws,"endTime":we,"limit":1000})
        out+=b
        ws=we
    seen=set(); dedup=[]
    for t in out:
        if t["id"] in seen: continue
        seen.add(t["id"]); dedup.append(t)
    return dedup

trades=[]
for sym in symbols:
    ut=fetch_user_trades(sym)
    ut.sort(key=lambda t:(int(t["time"]),int(t["id"])))
    pos=0.0; ent_not=0.0; real=0.0; comm=0.0; start=None; side0=None
    for t in ut:
        qty=float(t["qty"]); price=float(t["price"]); sq=qty if t["side"]=="BUY" else -qty
        cm=float(t["commission"]); ca=t["commissionAsset"]
        cm_usd=cm*(bnb if ca=="BNB" else (1.0 if ca=="USDT" else 0.0))
        if abs(pos)<1e-12: start=int(t["time"]); ent_not=0.0; real=0.0; comm=0.0; side0=t["side"]
        if (pos>=0 and sq>0) or (pos<=0 and sq<0): ent_not+=qty*price   # opening/increasing
        real+=float(t["realizedPnl"]); comm+=cm_usd; pos+=sq
        if abs(pos)<1e-9 and ent_not>0:
            trades.append({"sym":sym,"ms":start,"notional":ent_not,
                           "dir":"LONG" if side0=="BUY" else "SHORT",
                           "gross_pct":real/ent_not*100,
                           "net_pct":(real-comm)/ent_not*100,
                           "pnl":real-comm})
            pos=0.0
trades.sort(key=lambda x:x["ms"])

rets=[t["net_pct"]/100 for t in trades]           # net return-on-notional, chronological
wins=[t for t in trades if t["net_pct"]>0]; loss=[t for t in trades if t["net_pct"]<=0]
# longest loss streak
mx=cur=0
for t in trades:
    cur=cur+1 if t["net_pct"]<=0 else 0
    mx=max(mx,cur)

print("="*74)
print("SAMPLE = ALL REAL retest_trader TRADES (SL 2% + SL 3% regimes combined)")
print("="*74)
print(f"Trades: {len(trades)} | {ct(trades[0]['ms'])} -> {ct(trades[-1]['ms'])}")
print(f"Wins {len(wins)} / Losses {len(loss)} = {len(wins)/len(trades)*100:.0f}% win")
print(f"avg WIN move  {sum(t['net_pct'] for t in wins)/len(wins):+.2f}% (net on notional)")
print(f"avg LOSS move {sum(t['net_pct'] for t in loss)/len(loss):+.2f}% (net on notional, incl slippage)")
print(f"best {max(t['net_pct'] for t in trades):+.2f}% | worst {min(t['net_pct'] for t in trades):+.2f}%")
print(f"LONGEST LOSING STREAK: {mx} in a row  <-- drives martingale peak size")

# ---------------- EDGE DIAGNOSTICS ----------------
import math
def stats(ts):
    if not ts: return None
    r=[t["net_pct"] for t in ts]; n=len(r); mean=sum(r)/n
    w=[x for x in r if x>0]; l=[x for x in r if x<=0]
    var=sum((x-mean)**2 for x in r)/(n-1) if n>1 else 0.0
    sd=math.sqrt(var); se=sd/math.sqrt(n) if n else 0.0
    return dict(n=n, win=len(w)/n*100, mean=mean,
                aw=sum(w)/len(w) if w else 0.0, al=sum(l)/len(l) if l else 0.0,
                sd=sd, t=mean/se if se else 0.0)

print("\n"+"="*74); print("EDGE DIAGNOSTICS (net %/trade on notional)"); print("="*74)
o=stats(trades)
print(f"OVERALL: n={o['n']} | win {o['win']:.0f}% | avgW {o['aw']:+.2f}% avgL {o['al']:+.2f}%")
print(f"  expectancy = {o['mean']:+.3f}%/trade | sd {o['sd']:.2f}% | t-stat = {o['t']:.2f}"
      + ("  <-- NOT significant (|t|<2): edge indistinguishable from ZERO" if abs(o['t'])<2 else "  <-- significant"))
print(f"  breakeven win-rate needed @ this avgW/avgL: {(-o['al'])/(o['aw']-o['al'])*100:.0f}%  (you are at {o['win']:.0f}%)")

REG1=int(datetime(2026,8,17,21,7,tzinfo=timezone.utc).timestamp()*1000)   # SL 2%->3% cutover
REG2=int(datetime(2026,8,18,5,20,tzinfo=timezone.utc).timestamp()*1000)  # SL 3%->2% revert (00:20 CT 08-18)
sl2=[t for t in trades if t["ms"]<REG1 or t["ms"]>=REG2]; sl3=[t for t in trades if REG1<=t["ms"]<REG2]
print("\nBY SL REGIME:")
for name,ts in [("SL 2% (before 08-17 21:07 UTC + after 08-18 05:20 UTC)",sl2),("SL 3% (08-17 21:07 -> 08-18 05:20 UTC only)",sl3)]:
    s=stats(ts)
    if s: print(f"  {name:<30} n={s['n']:2} | win {s['win']:.0f}% | avgW {s['aw']:+.2f}% avgL {s['al']:+.2f}% | E {s['mean']:+.3f}%/trade")

print("\nBY DIRECTION:")
for d in ("LONG","SHORT"):
    s=stats([t for t in trades if t["dir"]==d])
    if s: print(f"  {d:<6} n={s['n']:2} | win {s['win']:.0f}% | avgW {s['aw']:+.2f}% avgL {s['al']:+.2f}% | E {s['mean']:+.3f}%/trade | t={s['t']:.2f}")

print("\nBY DIRECTION x SL2-only (cleanest: current live rule):")
for d in ("LONG","SHORT"):
    s=stats([t for t in sl2 if t["dir"]==d])
    if s: print(f"  {d:<6} n={s['n']:2} | win {s['win']:.0f}% | avgW {s['aw']:+.2f}% avgL {s['al']:+.2f}% | E {s['mean']:+.3f}%/trade | t={s['t']:.2f}")

# symbol concentration: how much of net P/L comes from the top winners/losers
allpnl=sorted(trades,key=lambda t:t["pnl"])
tot=sum(t["pnl"] for t in trades)
top5w=sum(t["pnl"] for t in allpnl[-5:]); top5l=sum(t["pnl"] for t in allpnl[:5])
print(f"\nCONCENTRATION: total net ${tot:+.2f} | top-5 winners ${top5w:+.2f} | top-5 losers ${top5l:+.2f}")
print(f"  -> remove top-5 winners: net = ${tot-top5w:+.2f}  (edge {'SURVIVES' if tot-top5w>0 else 'VANISHES -> carried by a few outliers'})")

def sim(rets, mult, base=1.0, lev=10, cap=0.95, maxlvl=None):
    eq=1.0; lvl=0; peak=1.0; mdd=0.0; mlvl=0; capped=0; mineq=1.0; worst=0.0
    for r in rets:
        eff=lvl if maxlvl is None else min(lvl, maxlvl)
        want=base*(mult**eff); mn=lev*cap; nf=min(want,mn)
        if want>mn: capped+=1
        step=nf*r; eq*=(1+step)
        worst=min(worst,step)
        if eq<=0: eq=0.0; mineq=0.0; mdd=1.0; break
        mineq=min(mineq,eq); peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak)
        lvl=lvl+1 if r<0 else 0; mlvl=max(mlvl,eff)
    return dict(mult=mult, final=eq, ret=(eq-1)*100, mdd=mdd*100, mlvl=mlvl,
                capped=capped, mineq=mineq, worst=worst*100)

def block(title, base):
    print("\n"+title)
    print(f"{'scheme':<16}{'final x':>9}{'return%':>10}{'maxDD%':>9}{'peakBet(xEq)':>14}{'worst1%':>10}{'ret/DD':>8}")
    for m,label in [(1.0,"FLAT"),(1.25,"1.25x cap3"),(1.5,"1.5x cap3"),(2.0,"2.0x cap3")]:
        ml=None if m==1.0 else 3
        s=sim(rets,m,base=base,maxlvl=ml)
        peak=min(base*(m**(0 if m==1.0 else 3)), 9.5)
        rd=s['ret']/s['mdd'] if s['mdd']>0 else float('nan')
        print(f"{label:<16}{s['final']:>8.2f}x{s['ret']:>+9.1f}%{s['mdd']:>8.1f}%{peak:>13.2f}x{s['worst']:>+9.1f}%{rd:>8.2f}")
    print("  (uncapped, for reference:)")
    for m,label in [(1.25,"1.25x uncap"),(1.5,"1.5x uncap"),(2.0,"2.0x uncap")]:
        s=sim(rets,m,base=base,maxlvl=None)
        rd=s['ret']/s['mdd'] if s['mdd']>0 else float('nan')
        print(f"  {label:<14}{s['final']:>8.2f}x{s['ret']:>+9.1f}%{s['mdd']:>8.1f}%{'':>14}{s['worst']:>+9.1f}%{rd:>8.2f}")

print("\n"+"="*74)
print("MARTINGALE CAP=3 LEVELS (clamp size at mult^3; escalate on loss, reset on win)")
print("compounding on equity, 10x lev margin cap ~9.5x")
print("="*74)
block("base = 100% notional (1x equity):", 1.0)
block("base = 150% notional (current live setting):", 1.5)

print("\nLOSS STREAKS (consecutive losers, symbol:netmove%):")
run=[]
for t in trades:
    if t["net_pct"]<=0: run.append(t)
    else:
        if len(run)>=3: print("  x%d: "%len(run)+" ".join(f"{r['sym'][:6]}({r['net_pct']:+.1f})" for r in run))
        run=[]
if len(run)>=3: print("  x%d: "%len(run)+" ".join(f"{r['sym'][:6]}({r['net_pct']:+.1f})" for r in run))
C.close()
