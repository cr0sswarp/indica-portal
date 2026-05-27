#!/usr/bin/env python3
"""
診断: アンカー追跡ロジックを走らせ、#6のフレーム毎座標を記録。
物理的にあり得ないジャンプ(ワープ)が、いつ・どの分岐で起きたかを特定する。
generate_video は import しない (自己完結)。
"""
import cv2, numpy as np, json
from config import VIDEO_H1, TRAJ_JSON, p2f
from config import W_LO1, W_HI1, W_LO2, W_HI2, KNL

SAMPLE = 6
MAX_TRACK_DIST = 120
MAX_DISAPP = 60
ANCHOR_WINDOW = 0.18
ANCHOR_MAX_DIST = 18.0
ANCHOR_WARP_LIMIT = 20.0
RECOVER_DIST = 5.0
WARP_THRESHOLD_M = 4.0   # 5fpsで4m/0.2s = 20m/s = 物理的に不可能

def detect_waseda(frame):
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    m=cv2.bitwise_or(cv2.inRange(hsv,W_LO1,W_HI1),cv2.inRange(hsv,W_LO2,W_HI2))
    m[:60,:]=0; m[680:,:]=0
    m=cv2.morphologyEx(m,cv2.MORPH_OPEN,KNL)
    m=cv2.morphologyEx(m,cv2.MORPH_CLOSE,KNL,iterations=2)
    cnts,_=cv2.findContours(m,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    out=[]
    for c in cnts:
        a=cv2.contourArea(c)
        if not(60<a<2800): continue
        x,y,w,h=cv2.boundingRect(c)
        if h/(w+1e-5)<0.5 or h/(w+1e-5)>9: continue
        cx,cy=x+w//2,y+h
        fx,fy=p2f(cx,cy)
        out.append({"px":cx,"py":cy-h//2,"fx":fx,"fy":fy,"bbox":(x,y,x+w,y+h),"area":a,"w":w,"h":h})
    return out

class Tracker:
    def __init__(self):
        self.nid=0; self.obj={}; self.disapp={}; self.extra={}
    def update(self,dets):
        if not dets:
            for oid in list(self.disapp):
                self.disapp[oid]+=1
                if self.disapp[oid]>MAX_DISAPP:
                    self.obj.pop(oid,None); self.disapp.pop(oid,None); self.extra.pop(oid,None)
            return []
        inp=np.array([(d["px"],d["py"]) for d in dets])
        if not self.obj:
            for d in dets:
                eid=self.nid; self.nid+=1
                self.obj[eid]=(d["px"],d["py"]); self.disapp[eid]=0; self.extra[eid]=d
        else:
            oids=list(self.obj.keys())
            oc=np.array([self.obj[o] for o in oids])
            D=np.linalg.norm(oc[:,None,:]-inp[None,:,:],axis=2)
            rows=D.min(axis=1).argsort(); cols=D.argmin(axis=1)[rows]
            ur=set(); uc=set()
            for r,c in zip(rows,cols):
                if r in ur or c in uc: continue
                if D[r,c]>MAX_TRACK_DIST: continue
                oid=oids[r]; d=dets[c]
                self.obj[oid]=(d["px"],d["py"]); self.disapp[oid]=0; self.extra[oid]=d
                ur.add(r); uc.add(c)
            for r in set(range(len(oids)))-ur:
                oid=oids[r]; self.disapp[oid]+=1
                if self.disapp[oid]>MAX_DISAPP:
                    self.obj.pop(oid,None); self.disapp.pop(oid,None); self.extra.pop(oid,None)
            for c in set(range(len(dets)))-uc:
                d=dets[c]; eid=self.nid; self.nid+=1
                self.obj[eid]=(d["px"],d["py"]); self.disapp[eid]=0; self.extra[eid]=d
        return [(oid,self.extra[oid]) for oid in self.obj if oid in self.extra]

with open(TRAJ_JSON) as f: traj=json.load(f)
anchors=[(a["time_min"],a["fx"],a["fy"]) for a in traj["confirmed_positions"] if "不明" not in a.get("note","")]
anchors.insert(0,(0.0,anchors[0][1],anchors[0][2]))
anchors.sort(key=lambda x: x[0])

def get_anchor(t):
    best=None; best_d=ANCHOR_WINDOW
    for tm,fx,fy in anchors:
        d=abs(tm-t)
        if d<best_d: best_d=d; best=(fx,fy)
    return best

def find_by_anchor(dets,fx,fy):
    best=None; best_d=ANCHOR_MAX_DIST
    for d in dets:
        dist=((d["fx"]-fx)**2+(d["fy"]-fy)**2)**0.5
        if dist<best_d: best_d=dist; best=d
    return best

cap=cv2.VideoCapture(str(VIDEO_H1))
fps=cap.get(cv2.CAP_PROP_FPS) or 30.0
tracker=Tracker(); jersey6_id=None; jersey6_pos=None; fn=0
prev_pos=None; prev_t=None

warps=[]
branch_counts={"anchor":0,"track":0,"recover":0,"lost":0}

print(f"診断開始 (前半45分, アンカー{len(anchors)}件)...")
while True:
    ret,frame=cap.read()
    if not ret: break
    fn+=1
    if fn%SAMPLE!=0: continue
    t=fn/fps/60
    if t>45: break
    dets=detect_waseda(frame); tracks=tracker.update(dets)
    anchor=get_anchor(t); is_anchor=False; player6_det=None
    branch="lost"
    prev_id=jersey6_id

    if anchor:
        candidate=find_by_anchor(dets,anchor[0],anchor[1])
        if candidate:
            if jersey6_pos is not None:
                jump=((candidate["fx"]-jersey6_pos[0])**2+(candidate["fy"]-jersey6_pos[1])**2)**0.5
                if jump>ANCHOR_WARP_LIMIT:
                    anchor=None
            if anchor:
                best_oid=None; best_px=999
                for oid,d in tracks:
                    dp=((d["px"]-candidate["px"])**2+(d["py"]-candidate["py"])**2)**0.5
                    if dp<best_px: best_px=dp; best_oid=oid
                if best_oid is not None: jersey6_id=best_oid
                player6_det=candidate; jersey6_pos=(candidate["fx"],candidate["fy"])
                is_anchor=True; branch="anchor"

    if not is_anchor and jersey6_id is not None:
        found=False
        for oid,d in tracks:
            if oid==jersey6_id:
                player6_det=d; jersey6_pos=(d["fx"],d["fy"]); branch="track"; found=True; break
        if not found and jersey6_pos is not None:
            best_oid=None; best_d=RECOVER_DIST
            for oid,d in tracks:
                dist=((d["fx"]-jersey6_pos[0])**2+(d["fy"]-jersey6_pos[1])**2)**0.5
                if dist<best_d: best_d=dist; best_oid=oid
            if best_oid is not None:
                jersey6_id=best_oid
                for oid,d in tracks:
                    if oid==jersey6_id:
                        player6_det=d; jersey6_pos=(d["fx"],d["fy"]); branch="recover"; break
            else:
                jersey6_id=None

    branch_counts[branch]+=1

    if player6_det and prev_pos is not None:
        cur=(player6_det["fx"],player6_det["fy"])
        dist=((cur[0]-prev_pos[0])**2+(cur[1]-prev_pos[1])**2)**0.5
        dt=t-prev_t
        if dist>WARP_THRESHOLD_M:
            id_changed=(prev_id!=jersey6_id)
            warps.append((t,dist,branch,prev_pos,cur,id_changed,dt))
    if player6_det:
        prev_pos=(player6_det["fx"],player6_det["fy"]); prev_t=t

cap.release()

tot=sum(branch_counts.values())
print(f"\n=== 分岐統計 (前半45分, {tot}フレーム) ===")
for k,v in branch_counts.items():
    print(f"  {k:8s}: {v:5d}  ({v/max(tot,1)*100:.1f}%)")

print(f"\n=== ワープ検出: {len(warps)}件 (>{WARP_THRESHOLD_M}m/0.2s = 物理的に不可能) ===")
by_branch={}; id_change_count=0
for t,dist,branch,fp,tp,idc,dt in warps:
    by_branch[branch]=by_branch.get(branch,0)+1
    if idc: id_change_count+=1
print(f"ワープの分岐別: {by_branch}")
print(f"ID切替を伴うワープ: {id_change_count}/{len(warps)}")
print(f"\n最初の25件:")
for t,dist,branch,fp,tp,idc,dt in warps[:25]:
    print(f"  t={t:5.2f}min  {dist:5.1f}m移動 ({dt*60:.1f}秒間)  [{branch:7s}]  "
          f"({fp[0]:.0f},{fp[1]:.0f})→({tp[0]:.0f},{tp[1]:.0f})  ID切替={idc}")
