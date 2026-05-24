#!/usr/bin/env python3
"""
TZI: 指定時刻のフレームを抽出し、全選手を番号付きで表示
使い方: python extract_frame.py <秒数> <1H|2H> [anchor_fx] [anchor_fy]
例:    python extract_frame.py 45 1H 29.8 36.6
"""
import cv2, numpy as np, sys
from pathlib import Path
from config import VIDEO_H1, VIDEO_H2, OUTPUT_DIR, p2f, FW, FH

ANCHOR_MAX_DIST = 18.0
FONT = cv2.FONT_HERSHEY_SIMPLEX

def detect_all_players(frame):
    hsv   = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    grass = cv2.inRange(hsv, np.array([35,40,60]), np.array([90,255,255]))
    mask  = np.ones_like(grass); mask[:80,:]=0; mask[680:,:]=0
    fg = cv2.bitwise_and(cv2.bitwise_not(grass), mask)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN,  cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5)), iterations=2)
    cnts,_ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out=[]
    for c in cnts:
        a=cv2.contourArea(c)
        if not(80<a<5000): continue
        x,y,w,h=cv2.boundingRect(c)
        if h/(w+1e-5)<0.4 or h/(w+1e-5)>12: continue
        if w<8 or h<12: continue
        cx,cy=x+w//2,y+h
        fx,fy=p2f(cx,cy)
        out.append({"px":cx,"py":cy-h//2,"fx":fx,"fy":fy,"bbox":(x,y,x+w,y+h),"w":w,"h":h})
    return sorted(out, key=lambda d: d["px"])

def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("使い方: python extract_frame.py <秒数> <1H|2H> [anchor_fx] [anchor_fy]")
        sys.exit(1)
    target_sec = float(args[0])
    half       = args[1]
    anchor_fx  = float(args[2]) if len(args)>2 else None
    anchor_fy  = float(args[3]) if len(args)>3 else None

    video = VIDEO_H1 if half=="1H" else VIDEO_H2
    cap   = cv2.VideoCapture(str(video))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(target_sec * fps))
    ret, frame = cap.read(); cap.release()
    if not ret: print(f"フレーム読み込み失敗"); sys.exit(1)

    players = detect_all_players(frame)
    out = frame.copy()
    W_f, H_f = frame.shape[1], frame.shape[0]

    best_i=-1; best_d=ANCHOR_MAX_DIST
    if anchor_fx is not None:
        for i,p in enumerate(players):
            d=((p["fx"]-anchor_fx)**2+(p["fy"]-anchor_fy)**2)**0.5
            if d<best_d: best_d=d; best_i=i

    for i,p in enumerate(players):
        x1,y1,x2,y2=p["bbox"]; cx=(x1+x2)//2; cy=(y1+y2)//2; n=i+1
        if i==best_i:
            cv2.circle(out,(cx,cy),max(p["w"],p["h"])//2+12,(0,255,255),3)
            cv2.rectangle(out,(x1-2,y1-2),(x2+2,y2+2),(0,255,255),2)
            cv2.putText(out,f"[{n}]star",(cx-22,y1-8),FONT,0.85,(0,255,255),2,cv2.LINE_AA)
        else:
            cv2.rectangle(out,(x1,y1),(x2,y2),(100,220,100),2)
            cv2.putText(out,f"[{n}]",(cx-14,y1-6),FONT,0.8,(255,220,50),2,cv2.LINE_AA)
        cv2.putText(out,f"X{p['fx']:.0f}Y{p['fy']:.0f}",(x1,y2+14),FONT,0.38,(200,200,100),1,cv2.LINE_AA)

    ov=out.copy(); cv2.rectangle(ov,(0,0),(W_f,52),(0,0,0),-1)
    cv2.addWeighted(ov,0.7,out,0.3,0,out)
    t_min=target_sec/60
    cv2.putText(out,f"{half}  {t_min:.1f}min  | {len(players)}選手 | 正しい#6は何番?",(10,22),FONT,0.65,(255,255,255),2,cv2.LINE_AA)
    if best_i>=0:
        cv2.putText(out,f"star=[{best_i+1}] 現在候補 (X{anchor_fx:.0f}Y{anchor_fy:.0f})",(10,46),FONT,0.48,(0,255,255),1,cv2.LINE_AA)

    fname = OUTPUT_DIR / f"frame_check_{half}_{t_min:.1f}min.png"
    cv2.imwrite(str(fname), out)
    print(f"保存: {fname}")
    print(f"検出選手: {len(players)}人")
    for i,p in enumerate(players):
        mark=" [現在の候補]" if i==best_i else ""
        print(f"  [{i+1}] X={p['fx']:.1f} Y={p['fy']:.1f}{mark}")

if __name__=="__main__": main()
