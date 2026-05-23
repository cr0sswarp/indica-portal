#!/usr/bin/env python3
"""
TZI: #6の全90分マークアップ動画を生成（OCR不要版）
jersey6_trajectory.json のアンカーを使って選手をトラッキング
使い方: python generate_video.py
"""
import cv2, numpy as np, subprocess, json, time
from pathlib import Path
from config import VIDEO_H1, VIDEO_H2, TRAJ_JSON, OUTPUT_DIR, p2f, FW, FH
from config import W_LO1, W_HI1, W_LO2, W_HI2, KNL

OUT = OUTPUT_DIR / "jersey6_full90.mp4"
W_OUT, H_OUT = 1280, 720
FPS_OUT      = 5
SAMPLE       = 6        # 30fps ÷ 6 = 5fps
MAX_TRACK_DIST = 80; MAX_DISAPP = 30
ANCHOR_WINDOW  = 0.18   # minutes: ±10.8秒がアンカーとしてマッチ
ANCHOR_MAX_DIST = 18.0
FONT = cv2.FONT_HERSHEY_SIMPLEX

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
anchors.sort(key=lambda x: x[0])
print(f"有効アンカー数: {len(anchors)}")

def get_anchor(t_min_total):
    best=None; best_d=ANCHOR_WINDOW
    for tm,fx,fy in anchors:
        d=abs(tm-t_min_total)
        if d<best_d: best_d=d; best=(fx,fy)
    return best

def find_by_anchor(dets,anchor_fx,anchor_fy):
    best=None; best_d=ANCHOR_MAX_DIST
    for d in dets:
        dist=((d["fx"]-anchor_fx)**2+(d["fy"]-anchor_fy)**2)**0.5
        if dist<best_d: best_d=dist; best=d
    return best

def draw_minimap(frame,player6_pos,all_dets,anchor_flag):
    MW,MH=168,112
    mp=np.zeros((MH,MW,3),dtype=np.uint8); mp[:,:,1]=50
    cv2.rectangle(mp,(0,0),(MW-1,MH-1),(180,180,180),1)
    cv2.line(mp,(MW//2,0),(MW//2,MH),(180,180,180),1)
    for xv in [21,42,63,84]:
        cv2.line(mp,(int(xv/FW*MW),0),(int(xv/FW*MW),MH),(100,100,100),1)
    for d in all_dets:
        cv2.circle(mp,(int(d["fx"]/FW*MW),int(d["fy"]/FH*MH)),3,(0,200,0),-1)
    if player6_pos:
        px6=int(player6_pos[0]/FW*MW); py6=int(player6_pos[1]/FH*MH)
        col=(0,255,255) if anchor_flag else (0,180,180)
        cv2.circle(mp,(px6,py6),5,col,-1); cv2.circle(mp,(px6,py6),7,col,2)
    cv2.putText(mp,"#6 MAP",(2,9),FONT,0.28,(255,255,255),1)
    x1m=W_OUT-MW-8; y1m=H_OUT-MH-8
    frame[y1m:y1m+MH,x1m:x1m+MW]=mp
    cv2.rectangle(frame,(x1m,y1m),(x1m+MW,y1m+MH),(160,160,160),1)

ffmpeg_cmd=['ffmpeg','-y','-f','rawvideo','-vcodec','rawvideo',
    '-s',f'{W_OUT}x{H_OUT}','-pix_fmt','bgr24','-r',str(FPS_OUT),
    '-i','pipe:0','-c:v','libx264','-preset','fast','-crf','26',
    '-pix_fmt','yuv420p','-movflags','+faststart',str(OUT)]
proc=subprocess.Popen(ffmpeg_cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def write_frame(frame):
    if frame.shape[1]!=W_OUT or frame.shape[0]!=H_OUT:
        frame=cv2.resize(frame,(W_OUT,H_OUT))
    proc.stdin.write(frame.tobytes())

total_written=0; anchor_hits=0; t_start=time.time()

for half_idx,(video_path,t_offset,half_label) in enumerate([
        (VIDEO_H1,0,"1st Half"),(VIDEO_H2,45,"2nd Half")]):
    cap=cv2.VideoCapture(str(video_path))
    fps_in=cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_f=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    tracker=Tracker(); jersey6_id=None; jersey6_pos=None; fn=0
    print(f"\n{half_label} ({total_f}f, ~{total_f/fps_in/60:.0f}min)")

    while True:
        ret,frame=cap.read()
        if not ret: break
        fn+=1
        if fn%SAMPLE!=0: continue
        local_t=fn/fps_in/60; t_min=local_t+t_offset
        dets=detect_waseda(frame); tracks=tracker.update(dets)
        anchor=get_anchor(t_min); is_anchor=False; player6_det=None
        if anchor:
            candidate=find_by_anchor(dets,anchor[0],anchor[1])
            if candidate:
                best_oid=None; best_px=999
                for oid,d in tracks:
                    dp=((d["px"]-candidate["px"])**2+(d["py"]-candidate["py"])**2)**0.5
                    if dp<best_px: best_px=dp; best_oid=oid
                if best_oid is not None: jersey6_id=best_oid
                player6_det=candidate; jersey6_pos=(candidate["fx"],candidate["fy"])
                is_anchor=True; anchor_hits+=1
        if not is_anchor and jersey6_id is not None:
            for oid,d in tracks:
                if oid==jersey6_id: player6_det=d; jersey6_pos=(d["fx"],d["fy"]); break
            if player6_det is None: jersey6_id=None

        out=frame.copy()
        for _,d in tracks:
            x1,y1,x2,y2=d["bbox"]; cv2.rectangle(out,(x1,y1),(x2,y2),(0,200,0),1)
        if player6_det:
            d=player6_det; x1,y1,x2,y2=d["bbox"]
            cx=(x1+x2)//2; cy=(y1+y2)//2; r=max(d["w"],d["h"])//2+16
            if is_anchor:
                cv2.circle(out,(cx,cy),r,(0,255,255),3); cv2.circle(out,(cx,cy),r+6,(0,140,255),2)
                cv2.rectangle(out,(x1-3,y1-3),(x2+3,y2+3),(0,255,255),2)
                cv2.putText(out,"#6 CONFIRMED",(x1,y1-10),FONT,0.75,(0,255,255),2,cv2.LINE_AA)
                cv2.arrowedLine(out,(cx,y1-50),(cx,y1-22),(0,255,0),3,cv2.LINE_AA,tipLength=0.4)
            else:
                cv2.circle(out,(cx,cy),r,(0,220,180),2)
                cv2.rectangle(out,(x1-2,y1-2),(x2+2,y2+2),(0,200,160),2)
                cv2.putText(out,"#6",(x1,y1-8),FONT,0.75,(0,220,180),2,cv2.LINE_AA)
            cv2.putText(out,f"X={d['fx']:.1f} Y={d['fy']:.1f}",(x1,y2+16),FONT,0.5,(255,255,0),1,cv2.LINE_AA)
        elif jersey6_pos:
            cv2.putText(out,"#6 tracking lost",(10,H_OUT-30),FONT,0.55,(80,80,200),1,cv2.LINE_AA)

        ov=out.copy(); cv2.rectangle(ov,(0,0),(W_OUT,46),(0,0,0),-1)
        cv2.addWeighted(ov,0.65,out,0.35,0,out)
        cv2.putText(out,f"{half_label}  {local_t:.1f}min  |  Match {t_min:.1f}min",
                   (10,20),FONT,0.65,(255,255,255),2,cv2.LINE_AA)
        cv2.putText(out,f"Anchors: {anchor_hits}",(10,40),FONT,0.5,(180,255,180),1,cv2.LINE_AA)
        if is_anchor:
            cv2.putText(out,">>> #6 POSITION CONFIRMED <<<",(W_OUT//2-190,20),FONT,0.65,(0,255,255),2,cv2.LINE_AA)
        draw_minimap(out,jersey6_pos,dets,is_anchor)
        write_frame(out); total_written+=1

        if fn%2700==0:
            e=time.time()-t_start
            print(f"  [{fn/total_f*100:.0f}%] {local_t:.0f}min  frames:{total_written}  {total_written/e:.1f}fps  {e:.0f}s")

    cap.release(); print(f"  {half_label} 完了")

proc.stdin.close(); proc.wait()
e=time.time()-t_start
sz=OUT.stat().st_size/1024/1024 if OUT.exists() else 0
print(f"\n=== 完了 ===\n出力: {OUT}\nサイズ: {sz:.0f}MB  時間: {e:.0f}s ({e/60:.1f}min)")
