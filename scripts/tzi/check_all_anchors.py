#!/usr/bin/env python3
"""
TZI: 全アンカーポイントのサムネイルを一括生成してグリッド画像を出力
使い方: python check_all_anchors.py
"""
import cv2, numpy as np, json
from pathlib import Path
from config import VIDEO_H1, VIDEO_H2, TRAJ_JSON, ANCHOR_DIR, OUTPUT_DIR, p2f, FW, FH

ANCHOR_MAX_DIST = 18.0
W_T, H_T = 640, 360
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

def make_thumb(frame, players, anchor_fx, anchor_fy, label):
    img=cv2.resize(frame,(W_T,H_T)); sx=W_T/frame.shape[1]; sy=H_T/frame.shape[0]
    best_i=-1; best_d=ANCHOR_MAX_DIST
    for i,p in enumerate(players):
        d=((p["fx"]-anchor_fx)**2+(p["fy"]-anchor_fy)**2)**0.5
        if d<best_d: best_d=d; best_i=i
    for i,p in enumerate(players):
        x1,y1,x2,y2=p["bbox"]
        x1i=int(x1*sx);y1i=int(y1*sy);x2i=int(x2*sx);y2i=int(y2*sy)
        cxi=int(p["px"]*sx);cyi=int(p["py"]*sy); n=i+1
        if i==best_i:
            cv2.circle(img,(cxi,cyi),18,(0,255,255),2)
            cv2.rectangle(img,(x1i,y1i),(x2i,y2i),(0,255,255),2)
            cv2.putText(img,f"[{n}]*",(cxi-18,y1i-5),FONT,0.7,(0,255,255),2,cv2.LINE_AA)
        else:
            cv2.rectangle(img,(x1i,y1i),(x2i,y2i),(100,220,100),1)
            cv2.putText(img,f"[{n}]",(cxi-12,y1i-4),FONT,0.65,(255,220,60),2,cv2.LINE_AA)
        cv2.putText(img,f"X{p['fx']:.0f}Y{p['fy']:.0f}",(x1i,y2i+12),FONT,0.32,(200,200,100),1,cv2.LINE_AA)
    ov=img.copy(); cv2.rectangle(ov,(0,0),(W_T,28),(0,0,0),-1)
    cv2.addWeighted(ov,0.75,img,0.25,0,img)
    cv2.putText(img,label,(6,19),FONT,0.55,(255,255,255),1,cv2.LINE_AA)
    if best_i>=0:
        cv2.putText(img,f"*=[{best_i+1}] X{anchor_fx:.0f}Y{anchor_fy:.0f}",(6,H_T-8),FONT,0.38,(0,255,255),1,cv2.LINE_AA)
    else:
        cv2.putText(img,f"*なし (X{anchor_fx:.0f}Y{anchor_fy:.0f})",(6,H_T-8),FONT,0.38,(80,80,255),1,cv2.LINE_AA)
    return img, best_i

def main():
    ANCHOR_DIR.mkdir(exist_ok=True)
    with open(TRAJ_JSON) as f: traj=json.load(f)
    anchors=traj["confirmed_positions"]
    caps={"1H":cv2.VideoCapture(str(VIDEO_H1)),"2H":cv2.VideoCapture(str(VIDEO_H2))}
    fpses={k:(caps[k].get(cv2.CAP_PROP_FPS) or 30.0) for k in caps}
    thumbs=[]

    print(f"{'#':>2} {'Half':4} {'time':6} {'*候補':6} {'dist':5}  状況")
    print("-"*55)

    for idx,anc in enumerate(anchors):
        half=anc["half"]; t_min=anc["time_min"]
        a_fx,a_fy=anc["fx"],anc["fy"]
        local_min=t_min if half=="1H" else t_min-45
        cap=caps[half]; fps=fpses[half]
        cap.set(cv2.CAP_PROP_POS_FRAMES,int(local_min*60*fps))
        ret,frame=cap.read()
        if not ret: print(f"{idx+1:2} {half} {t_min:.1f}min  失敗"); continue
        players=detect_all_players(frame)
        label=f"{half} {local_min:.1f}min (Match {t_min:.1f}min)  {len(players)}人"
        thumb,best_i=make_thumb(frame,players,a_fx,a_fy,label)
        fname=ANCHOR_DIR/f"{idx+1:02d}_{half}_{t_min:.1f}min.jpg"
        cv2.imwrite(str(fname),thumb,[cv2.IMWRITE_JPEG_QUALITY,88])
        thumbs.append(thumb)
        cand=f"[{best_i+1}]" if best_i>=0 else "---"
        best_d=((players[best_i]["fx"]-a_fx)**2+(players[best_i]["fy"]-a_fy)**2)**0.5 if best_i>=0 else 999
        status="OK" if best_d<5 else "やや離" if best_d<10 else "要確認"
        print(f"{idx+1:2} {half}  {t_min:5.1f}min  {cand:6}  {best_d:4.1f}m  {status}")

    for cap in caps.values(): cap.release()
    if thumbs:
        COLS=4; ROWS=(len(thumbs)+COLS-1)//COLS
        grid=np.zeros((ROWS*H_T+ROWS*4,COLS*W_T+COLS*4,3),dtype=np.uint8); grid[:]=30
        for i,th in enumerate(thumbs):
            r,c=i//COLS,i%COLS; y0=r*(H_T+4); x0=c*(W_T+4)
            grid[y0:y0+H_T,x0:x0+W_T]=th
            cv2.putText(grid,f"#{i+1}",(x0+4,y0+H_T-6),FONT,0.4,(160,160,160),1)
        gp=OUTPUT_DIR/"anchor_check_grid.jpg"
        cv2.imwrite(str(gp),grid,[cv2.IMWRITE_JPEG_QUALITY,80])
        print(f"\nグリッド: {gp}")
    print(f"個別画像: {ANCHOR_DIR}/")
    print("\n--- 返答フォーマット ---")
    print("#N → [M]が正しい  /  #N → 画面外、削除  /  #N → 合ってる")

if __name__=="__main__": main()
