"""Animated QPainter-only core designs for the existing Mark-LVI HUD.

No extra GPU, OpenGL, or image/video assets. Called only from the Qt paint
thread. Reuses the existing HUD audio amplitude and current state.
"""
from __future__ import annotations

import math
from PyQt6.QtCore import Qt, QRectF, QPointF, QLineF
from PyQt6.QtGui import (QColor, QBrush, QPen, QPainterPath,
                        QRadialGradient, QConicalGradient, QFont)


def color(hexcode: str, opacity: float = 1.0) -> QColor:
    c = QColor(hexcode)
    c.setAlphaF(max(0.0, min(1.0, opacity)))
    return c


def ring(p, cx, cy, radius, hue, opacity=0.5, width=1.3):
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(color(hue, opacity), width))
    p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))


def arc(p, cx, cy, radius, start_deg, span_deg, hue, opacity=0.7, width=2):
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(color(hue, opacity), width, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
              int(start_deg * 16), int(span_deg * 16))


def point(p, x, y, radius, hue, opacity=1):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color(hue, opacity))
    p.drawEllipse(QRectF(x-radius, y-radius, radius*2, radius*2))


def glow(p, cx, cy, rad, hue, power):
    grad = QRadialGradient(QPointF(cx, cy), rad)
    grad.setColorAt(0.0, color(hue, min(0.58, .18 + power * .27)))
    grad.setColorAt(.3, color(hue, .13 + .18 * power))
    grad.setColorAt(.7, color(hue, .035 + .08 * power))
    grad.setColorAt(1.0, color(hue, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(QRectF(cx-rad, cy-rad, rad*2, rad*2))


def _reactor(p, cx, cy, r, t, amp, hue, alt, particles):
    glow(p, cx, cy, r*.86, hue, amp)
    ring(p, cx, cy, r*.93, hue, .36, 1.5)
    ring(p, cx, cy, r*.79, hue, .16)
    for k in range(4):
        direction = 1 if k % 2 == 0 else -1
        rad = r * (.90 - k*.13)
        for i in range(2 + k%2):
            arc(p,cx,cy,rad,(t* (12+k*4)*direction + i*170 + k*45)%360,
                70+(k%2)*25,alt if k%2==0 else hue,.8-k*.11,3.0-k*.45)
    for j in range(60):
        a=j*math.tau/60
        spike=.02 + amp*.11*(.55+.45*math.sin(t*4+j*.65)**2)
        x=math.cos(a); y=math.sin(a)
        p.setPen(QPen(color(hue,.33+amp*.4), 1.1))
        p.drawLine(QLineF(cx+x*r*.47,cy+y*r*.47,
                          cx+x*r*(.47+spike),cy+y*r*(.47+spike)))
    inner=r*(.27+amp*.05)
    ring(p,cx,cy,inner,alt,.65,1.8)
    glow(p,cx,cy,inner*.93,alt,amp)
    if particles:
        for j in range(14):
            a=t*(.15 if j%2 else -.18)+j*math.tau/14
            rr=r*(.57+(j%4)*.075)
            point(p,cx+math.cos(a)*rr,cy+math.sin(a)*rr,1.4+(j%3)*.45,hue,.7)


def _plasma(p,cx,cy,r,t,amp,hue,alt,particles):
    glow(p,cx,cy,r*.9,hue,amp)
    for k in range(9):
        path=QPainterPath()
        for j in range(84):
            a=j*math.tau/83
            wave=math.sin(a*5+t*1.7+k*.64) * .06
            wave+=math.sin(a*9-t*1.35+k*.93)*.028
            rr=r*(.43 + k*.037 + amp*.085 + wave)
            px=cx+rr*math.cos(a);py=cy+rr*math.sin(a)
            if j==0:path.moveTo(px,py)
            else:path.lineTo(px,py)
        path.closeSubpath()
        p.setPen(QPen(color(alt if k%3==0 else hue,
                            .15+.035*k + amp*.14), .7+(k%3)*.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
    for k in range(12):
        angle=(k*math.tau/12 + math.sin(t*.85 + k)*.13)
        path=QPainterPath()
        rr=r*.16
        path.moveTo(cx+math.cos(angle)*rr,cy+math.sin(angle)*rr)
        for j in range(1,12):
            part=j/11
            a=angle+math.sin(part*12+t*2+k)*(.08+.12*part)
            rd=r*(.16+.45*part) + math.sin(part*18+t*3+k)*r*.018
            path.lineTo(cx+math.cos(a)*rd,cy+math.sin(a)*rd)
        p.setPen(QPen(color(alt if k%2 else hue,.3+amp*.42),1.1))
        p.drawPath(path)
    point(p,cx,cy,r*(.07+amp*.05),alt,.88)
    if particles:
        for i in range(26):
            a=i*2.4+t*(.1+(.015*i))
            rr=r*(.2+.68*((i*17)%27)/27)
            point(p,cx+math.cos(a)*rr,cy+math.sin(a)*rr,1.1+(i%3)*.35,hue,.28+amp*.5)


def _orbit(p,cx,cy,r,t,amp,hue,alt,particles):
    glow(p,cx,cy,r*.83,hue,amp*.75)
    for j in range(5):
        rad=r*(.30+j*.145)
        ring(p,cx,cy,rad,hue,.18+j*.045,1+(j%2)*.4)
        for n in range(2 if j<3 else 4):
            a=t*(.25+j*.1)*(1 if j%2 else -1)+n*math.tau/(2 if j<3 else 4)+j
            x=cx+math.cos(a)*rad;y=cy+math.sin(a)*rad
            point(p,x,y,2+(j%3)*.6,alt if n==0 else hue,.83)
    for j in range(9):
        angle=j*math.tau/9+t*.12
        x=cx+math.cos(angle)*r*.17;y=cy+math.sin(angle)*r*.17
        p.setPen(QPen(color(hue,.35),1))
        p.drawLine(QLineF(cx,cy,x,y))
        point(p,x,y,2.8,alt,.9)
    ring(p,cx,cy,r*.12,alt,.9,2)
    glow(p,cx,cy,r*.28,alt,.75+amp)
    if particles:
        for j in range(32):
            a=j*math.tau/32
            h=(1+amp*.2)*r*.97
            point(p,cx+math.cos(a)*h,cy+math.sin(a)*h,1,hue,.25)


def _radar(p,cx,cy,r,t,amp,hue,alt,particles):
    for i in range(1,6): ring(p,cx,cy,r*i/5,hue,.13+i*.055)
    # Sweeping triangular sector
    angle=t*.87
    sweep=QPainterPath();sweep.moveTo(cx,cy)
    sweep.arcTo(QRectF(cx-r,cy-r,r*2,r*2),-math.degrees(angle),29)
    sweep.closeSubpath()
    grad=QRadialGradient(QPointF(cx,cy),r)
    grad.setColorAt(0,color(hue,.07));grad.setColorAt(.75,color(hue,.2+amp*.1))
    grad.setColorAt(1,color(hue,0))
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QBrush(grad));p.drawPath(sweep)
    p.setPen(QPen(color(hue,.4),1))
    p.drawLine(QLineF(cx-r,cy,cx+r,cy));p.drawLine(QLineF(cx,cy-r,cx,cy+r))
    a=-angle
    p.setPen(QPen(color(alt,.9),2))
    p.drawLine(QLineF(cx,cy,cx+math.cos(a)*r,cy+math.sin(a)*r))
    for k in range(72):
        a=k*math.tau/72
        rad1=r*.94 if k%6 else r*.88
        p.setPen(QPen(color(hue,.30 if k%6 else .65),1))
        p.drawLine(QLineF(cx+math.cos(a)*rad1,cy+math.sin(a)*rad1,
                          cx+math.cos(a)*r,cy+math.sin(a)*r))
    if particles:
        for k in range(9):
            a=(k*2.39)%(math.tau);rr=r*(.25+(k%4)*.17)
            ring(p,cx+math.cos(a)*rr,cy+math.sin(a)*rr,2.5+amp*2,alt,.8,1.3)
    point(p,cx,cy,3.5,alt,.95)


def _neural(p,cx,cy,r,t,amp,hue,alt,particles):
    glow(p,cx,cy,r*.9,hue,amp)
    nodes=[]
    for layer,n in enumerate((6,10,16)):
        rr=r*(.25+.28*layer)
        for i in range(n):
            a=i*math.tau/n+t*(.05 if layer%2 else -.07)+layer*.3
            x=cx+math.cos(a)*rr;y=cy+math.sin(a)*rr
            nodes.append((x,y,layer))
    for i,(x,y,layer) in enumerate(nodes):
        for jump in (5,9):
            j=(i+jump)%len(nodes)
            xx,yy,ll=nodes[j]
            if abs(ll-layer)!=1:continue
            power=.13+.18*(.5+.5*math.sin(t*2+i*.7))+.2*amp
            p.setPen(QPen(color(hue,power),.8))
            p.drawLine(QLineF(x,y,xx,yy))
    for i,(x,y,layer) in enumerate(nodes):
        point(p,x,y,2.3 if layer!=0 else 3.2,alt if (i%7==0) else hue,.75)
    ring(p,cx,cy,r*.93,hue,.5,1.1)
    for k in range(4):arc(p,cx,cy,r*(.88-k*.12),t*(14+k*4)+k*86,44,
                          alt if k%2 else hue,.45+amp*.15,1.5)
    glow(p,cx,cy,r*.18,alt,.8+amp)


def draw(p,style,cx,cy,r,time_s,level,state,palette,settings):
    """Draw core in the caller's QPainter. No widget/signal/thread side effects."""
    accent=palette.get("accent", "#00d5ff")
    alternate=palette.get("secondary", "#a7f2ff")
    if state in ("THINKING", "PROCESSING"):
        alternate = "#ffd087"
    elif state == "SPEAKING":
        alternate = "#7bffb7"
    elif state == "MUTED":
        accent = alternate = "#f66b93"
    level = max(0., min(1., level)) * (settings.get("intensity",80)/80)
    time_s *= (.20 if settings.get("reduced_motion") else 1.0)
    particles=bool(settings.get("particles",True))
    r=max(20,min(r,1200))
    # No expensive particle/path tessellation while waiting for Groq/Gemini.
    # Keep the nucleus visible and animated, but leave the CPU for network and audio.
    fast_busy=bool(settings.get("performance_mode",True) and
                   state in ("THINKING", "PROCESSING"))
    p.save()
    if fast_busy:
        glow(p,cx,cy,r*.65,accent,level*.7)
        ring(p,cx,cy,r*.84,accent,.34,1.5)
        ring(p,cx,cy,r*.52,alternate,.23,1.2)
        for j in range(3):
            arc(p,cx,cy,r*(.78-j*.16),time_s*(18+j*5)*(1 if j%2 else -1)+j*110,
                66,alternate if j==1 else accent,.72,2)
        point(p,cx,cy,4+level*4,alternate,.85)
        p.restore()
        return
    glow(p,cx,cy,r*.94,accent,level*.8)
    if style=="plasma": _plasma(p,cx,cy,r,time_s,level,accent,alternate,particles)
    elif style=="orbit": _orbit(p,cx,cy,r,time_s,level,accent,alternate,particles)
    elif style=="radar": _radar(p,cx,cy,r,time_s,level,accent,alternate,particles)
    elif style=="neural": _neural(p,cx,cy,r,time_s,level,accent,alternate,particles)
    else: _reactor(p,cx,cy,r,time_s,level,accent,alternate,particles)
    p.restore()
