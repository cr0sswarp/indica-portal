#!/usr/bin/env python3
"""
TZI: jersey6_trajectory.json からヒートマップを生成
使い方: python generate_heatmap.py
"""
import json, numpy as np, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from scipy.ndimage import gaussian_filter
from config import TRAJ_JSON, OUTPUT_DIR, FW, FH

OUT = OUTPUT_DIR / "heatmap_jersey6_latest.png"

with open(TRAJ_JSON) as f:
    traj = json.load(f)
valid = [a for a in traj["confirmed_positions"] if "不明" not in a.get("note","")]
print(f"使用アンカー: {len(valid)} / {len(traj['confirmed_positions'])} 点")

xs = [a["fx"] for a in valid]; ys = [a["fy"] for a in valid]
halves = [a["half"] for a in valid]; times = [a["time_min"] for a in valid]

fig = plt.figure(figsize=(16,8), facecolor='#1a1a2e')
gs  = fig.add_gridspec(1,2, width_ratios=[3,1])
ax  = fig.add_subplot(gs[0], facecolor='#2d5a1b')
ax2 = fig.add_subplot(gs[1], facecolor='#1a1a2e')

ax.set_xlim(0,FW); ax.set_ylim(0,FH); ax.set_aspect('equal')
ax.tick_params(colors='white')
for spine in ax.spines.values(): spine.set_color('#555')
for x in [21,42,63,84]: ax.axvline(x,color='white',alpha=0.25,lw=0.8)
ax.axhline(34,color='white',alpha=0.25,lw=0.8)
ax.axvline(FW/2,color='white',alpha=0.5,lw=1.2)
for px,pw in [(0,16.5),(FW-16.5,16.5)]:
    ax.add_patch(patches.Rectangle((px,13.84),pw,40.32,fill=False,ec='white',alpha=0.4,lw=0.8))

H,W=340,520; grid=np.zeros((H,W))
for x,y in zip(xs,ys):
    gx=int(x/FW*(W-1)); gy=int(y/FH*(H-1))
    if 0<=gx<W and 0<=gy<H: grid[gy,gx]+=1
grid=gaussian_filter(grid,sigma=12)
if grid.max()>0: grid/=grid.max()
ax.imshow(grid,extent=[0,FW,0,FH],origin='lower',cmap='YlOrRd',alpha=0.55,aspect='auto',vmin=0,vmax=1)

c1h=plt.cm.Blues(np.linspace(0.4,1,max(1,sum(h=="1H" for h in halves))))
c2h=plt.cm.Oranges(np.linspace(0.4,1,max(1,sum(h=="2H" for h in halves))))
i1=i2=0
for x,y,h,t in zip(xs,ys,halves,times):
    c=c1h[i1] if h=="1H" else c2h[i2]
    if h=="1H": i1+=1
    else: i2+=1
    ax.scatter(x,y,c=[c],s=100,zorder=5,edgecolors='white',linewidths=0.8)
    ax.annotate(f"{t:.0f}m",xy=(x,y),xytext=(3,3),textcoords='offset points',fontsize=6.5,color='white',fontweight='bold')

ax.set_title("Jersey #6 Position Heatmap", color='white', fontsize=14, pad=10)
ax.set_xlabel("Field Length (m)", color='white'); ax.set_ylabel("Field Width (m)", color='white')
for xi,xl in enumerate(['D1','D2','D3','A1','A2']):
    cx=[0,21,42,63,84][xi]+10.5
    ax.text(cx,FH+1.5,xl,ha='center',va='bottom',color='white',fontsize=8,alpha=0.7)

t1=[t for t,h in zip(times,halves) if h=="1H"]; y1=[y for y,h in zip(ys,halves) if h=="1H"]
t2=[t for t,h in zip(times,halves) if h=="2H"]; y2=[y for y,h in zip(ys,halves) if h=="2H"]
if t1: ax2.plot(t1,y1,'o-',color='#6eb5ff',label='1H',lw=1.5,ms=5)
if t2: ax2.plot(t2,y2,'s-',color='#ffaa55',label='2H',lw=1.5,ms=5)
ax2.axhline(34,color='white',alpha=0.3,lw=0.8,ls='--')
ax2.set_xlim(0,90); ax2.set_ylim(0,FH)
ax2.set_xlabel("Match Time (min)", color='white', fontsize=9)
ax2.set_ylabel("Y position (m)", color='white', fontsize=9)
ax2.set_title("Y-axis Timeline", color='white', fontsize=10)
ax2.tick_params(colors='white')
for sp in ax2.spines.values(): sp.set_color('#444')
ax2.legend(fontsize=8,facecolor='#2a2a4a',labelcolor='white')

n_fix=sum(1 for a in traj["confirmed_positions"] if "手動修正" in a.get("note",""))
fig.text(0.01,0.01,f"Manual corrections: {n_fix}  |  Uncertain: {len(traj['confirmed_positions'])-len(valid)}  |  Used: {len(valid)}",
    color='#aaa',fontsize=9)
plt.tight_layout()
plt.savefig(str(OUT),dpi=150,bbox_inches='tight',facecolor='#1a1a2e')
plt.close()
print(f"保存: {OUT}")
