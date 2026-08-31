#!/usr/bin/env python3
"""
config_layout.py — photo_to_figure + AUTO-LABELING / CALLOUTS.

Strategy = CONFIG-DRIVEN + BEST LAYOUT.

  * The primary path is a hand-authored ``--labels FILE.json`` — a list of
    ``{"x":0-1,"y":0-1,"text":"NAME"}`` in image-relative coordinates. Those
    callouts are drawn EXACTLY where the human put them, with careful routing.
  * When no config is given, a light AUTO fallback marks only what geometry can
    honestly find: the biggest interior bright block ("MODULE") and the board's
    connector-like edge protrusions ("CONN"). Everything else is left unlabeled
    rather than guessed — this is an auto-tracer with no part database.

The tracing stage (.edge / .detail / .fine, Zhang-Suen thinning, skeleton walk,
stroke-dashoffset draw-on) is IDENTICAL to photo_to_figure.py. Labeling is a
pure post-process layered on top:

  LAYOUT (the focus of this variant):
    - each leader is anchored at the component point, leaves it with a short
      horizontal stub, then runs to the NEARER margin (left comp -> left margin,
      right comp -> right margin) so no leader crosses the whole board;
    - within each margin, labels are sorted by anchor-y and vertically
      distributed with a minimum gap so none overlap, and because the vertical
      order is preserved the straight leaders never cross each other;
    - the SVG viewBox is WIDENED on both sides (never clipped) to give the
      IBM Plex Mono labels room, with a small grey anchor dot at the component;
    - callouts draw/fade in AFTER the traced figure has finished drawing.

Runs headless, classic-cv2 only (no ximgproc / contrib / downloads).

Usage:
    python config_layout.py <path> [-o out.html] [--title NAME]
                            [--labels labels.json] [--debug-png p.png]
"""
import argparse
import json
import sys

import numpy as np
from PIL import Image

try:
    import cv2
except ImportError:
    sys.exit("Missing dependency: pip install opencv-python-headless")

# ---- shared look (identical to base tool) ---------------------------------
BLACK, STROKE, STROKE2, ACCENT = "#000000", "#F5F5F7", "#8A8A8F", "#FF6A13"

# ---- tuning ---------------------------------------------------------------
WORK_MAX = 1500          # cap working long-edge (downscale huge photos)
WORK_MIN = 1150          # upscale small/low-res sources up to this long-edge
CANNY_SCALES = [         # (gaussian sigma, median-threshold spread) fine->coarse
    (0.8, 0.20),
    (1.6, 0.33),
    (2.6, 0.50),
]
ADAPT_BLOCK = 21         # adaptiveThreshold block size (odd)
ADAPT_C = 8              # adaptiveThreshold bias (higher = less silkscreen speckle)
CLAHE_CLIP = 2.2         # local contrast boost before edge finding (0 = off)
CLAHE_TILES = 10         # CLAHE tile grid (NxN) for that boost
RECTIFY = True           # snap near-rectangular parts to clean rectangles
RECTIFY_EXTENT = 0.86    # contour must fill >= this fraction of its min-area rect
RECTIFY_MIN_AREA_FRAC = 0.00010   # ...and be at least this fraction of the image
SMOOTH_SIGMA = 0.7       # gaussian de-jitter on each traced path
SIMPLIFY_EPS = 2.0       # Douglas-Peucker epsilon (working px)
CASE_SMOOTH_SIGMA = 2.4  # heavier de-jitter for the outer case silhouette
CASE_SIMPLIFY_EPS = 2.5  # Douglas-Peucker epsilon for the case silhouette
CHIP_RADIUS_FRAC = 0.06  # corner radius of a config 'box' chip = this * short side
MIN_LEN_FRAC = 0.020     # drop paths shorter than this * image diagonal
FINE_FRAC = 0.05         # len < this*diag -> .fine
DETAIL_FRAC = 0.17       # len < this*diag -> .detail, else .edge (structural)
RIM_ERODE = 4            # erode mask this much before keeping internal edges
MAX_PATHS = 4200         # hard cap (drop shortest) so the HTML stays sane
DRAW_WINDOW_MS = 1500    # stagger all draw-on delays across this window
USE_CURVE = True         # organic strokes wobble (Bezier); rectangles stay crisp

# ---- callout / label tuning (new) -----------------------------------------
CALLOUT_START = 3000     # ms: begin callouts only AFTER the figure has drawn in
CALLOUT_STAGGER = 150    # ms between successive callouts
CALLOUT_AFTER = 380      # ms: dot + label appear this long after their leader
LABEL_FRAC = 0.018       # label font-size = this * working diagonal (user units)
LABEL_MIN = 20.0         # never smaller than this (user units)
CHAR_W = 0.62            # IBM Plex Mono advance width as a fraction of em
GUTTER = 8.0             # gap from board edge to the leader's turn column
SHELF = 16.0             # horizontal run from the turn column into the label
STUB_FRAC = 0.02         # horizontal stub leaving the component = this * W
MARGIN_PAD = 16.0        # breathing room past the longest label in a margin
GAP_FRAC = 1.65          # min vertical gap between stacked labels = this * font


def load_image(src):
    if src.startswith(("http://", "https://")):
        import io as _io, requests
        r = requests.get(src, headers={"User-Agent": "Mozilla/5.0 (photo_to_figure)"}, timeout=30)
        r.raise_for_status()
        return Image.open(_io.BytesIO(r.content)).convert("RGB")
    return Image.open(src).convert("RGB")


# ---------------------------------------------------------------- segmentation
SEG_CANNY_LO = 18        # Canny low threshold for the rim/edge "walls"
SEG_CANNY_HI = 55        # Canny high threshold
SEG_WALL_IT = 2          # dilate edges this many times to seal faint-rim gaps
SEG_CLOSE_K = 11         # close kernel to consolidate the object region


def _otsu_mask(gray):
    """Brightness-only segmentation. Fallback for an opaque subject that is
    simply darker than its background, with no translucent parts."""
    _, m = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    border = np.concatenate([m[0], m[-1], m[:, 0], m[:, -1]])
    if border.mean() > 127:
        m = 255 - m
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), 2)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), 1)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None, None
    big = max(cnts, key=cv2.contourArea)
    frac = cv2.contourArea(big) / (gray.shape[0] * gray.shape[1])
    if not (0.06 < frac < 0.95):
        return None, None
    mask = np.zeros_like(m)
    cv2.drawContours(mask, [big], -1, 255, -1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), 2)
    return mask, big.reshape(-1, 2)


def segment(gray):
    """Object mask + silhouette contour on a flat background.

    A translucent shell (acrylic case, clear plastic) is the hard case: its body
    is nearly background-toned, so a brightness threshold drops it, while a soft
    drop-shadow is *darker* than the background, so a brightness threshold grabs
    it -- inflating the outline into the shadow while still losing the clear end.

    So segment by connectivity instead of tone. Build "walls" from the object's
    edges (Canny, dilated to seal faint-rim gaps) and flood the background inward
    from the frame corners: it fills the flat background and the soft shadow
    (which has no sharp rim to stop it) but cannot enter the case interior, which
    its own faint rim seals off. Everything the flood never reaches is the object
    -- the opaque parts, the clear rails, and the rounded translucent end alike.
    Falls back to Otsu if this misfires. Returns (mask, outline) or (full, None).
    """
    H, W = gray.shape
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
    edges = cv2.Canny(blur, SEG_CANNY_LO, SEG_CANNY_HI)
    walls = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=SEG_WALL_IT)
    free = (walls == 0).astype(np.uint8) * 255            # floodable where no wall
    ff = free.copy()
    fm = np.zeros((H + 2, W + 2), np.uint8)
    for sx, sy in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1), (W // 2, 0), (W // 2, H - 1)]:
        if free[sy, sx] == 255:
            cv2.floodFill(ff, fm, (sx, sy), 128)
    obj = (ff != 128).astype(np.uint8) * 255              # walls + everything the flood never reached
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, np.ones((SEG_CLOSE_K, SEG_CLOSE_K), np.uint8), 2)
    obj = cv2.morphologyEx(obj, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), 1)
    n, lab, st, _ = cv2.connectedComponentsWithStats(obj, 8)
    if n >= 2:
        big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        mask = (lab == big).astype(np.uint8) * 255
        # seal any internal holes so the silhouette is one solid region
        hf = mask.copy()
        hm = np.zeros((H + 2, W + 2), np.uint8)
        cv2.floodFill(hf, hm, (0, 0), 255)
        mask = mask | cv2.bitwise_not(hf)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), 2)
        frac = (mask > 0).mean()
        if 0.06 < frac < 0.95:
            c2, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            big2 = max(c2, key=cv2.contourArea)
            return mask, big2.reshape(-1, 2)
    mask, outline = _otsu_mask(gray)
    if mask is None:
        return np.full((H, W), 255, np.uint8), None
    return mask, outline


# ---------------------------------------------------------------- edge map
def auto_canny(g, spread):
    med = float(np.median(g))
    lo = int(max(0, (1.0 - spread) * med))
    hi = int(min(255, (1.0 + spread) * med))
    return cv2.Canny(g, lo, hi, L2gradient=True)


def _blank_border(m, frac=0.02):
    b = max(6, int(frac * max(m.shape)))
    m[:b, :] = 0; m[-b:, :] = 0; m[:, :b] = 0; m[:, -b:] = 0
    return m


def rectify(pts):
    """Snap a near-rectangular region contour to its exact oriented rectangle.

    Most PCB parts -- pads, SMD passives, chips, connector shells -- are truly
    rectangular; the raw region boundary is a slightly wavy version of that. When
    a contour nearly fills its own minimum-area rectangle (high 'extent') and is
    not a tiny speck, replace it with the four clean corners of that rectangle.
    Densely-packed rectangles then read as tidy parts instead of a wavy tangle,
    which is the bulk of the interior 'chaos'. Non-rectangular shapes (the antenna
    spiral, silk text, round pads) fail the extent test and pass through as-is."""
    if not RECTIFY or len(pts) < 4:
        return pts
    area = cv2.contourArea(pts.astype(np.int32))
    if area < RECTIFY_MIN_AREA_FRAC * _IMG_AREA[0]:
        return pts
    rect = cv2.minAreaRect(pts.astype(np.float32))
    (w, h) = rect[1]
    if w < 2 or h < 2:
        return pts
    extent = area / (w * h)
    if extent >= RECTIFY_EXTENT and 0.10 <= (min(w, h) / max(w, h)):
        return cv2.boxPoints(rect)
    return pts


_IMG_AREA = [1.0]   # working image area (px^2); set per-run for rectify's threshold


def extract_strokes(gray, mask):
    """Return a list of raw point-paths from TWO complementary sources, deduped:

      A) ADAPTIVE-THRESHOLD region contours — the local-contrast threshold turns
         the dark solder-mask into a filled sheet whose holes are every bright
         pad / trace / silk mark / the module & button; findContours traces each
         as ONE clean closed loop. Crisp rectangles, sharp corners, and (being a
         region boundary, not a pair of gradient edges) NO doubled parallel line.

      B) MULTI-SCALE CANNY linear edges — the USB shell fins, the clear case
         outline and tonal edges the filled-region pass can't see. These are
         first stripped of any pixel that lies on an already-traced region
         boundary (so A and B never draw the same edge twice), then thinned to a
         centreline and walked through junctions into long strokes."""
    H, W = gray.shape
    _IMG_AREA[0] = float(H * W)

    # Local contrast equalisation (CLAHE) BEFORE edge finding. Dark-on-dark
    # regions -- an RF-shield can and its laser-etched markings sitting on black
    # solder mask -- carry almost no global contrast, so a chip traces as an
    # empty void. CLAHE lifts that local detail (the can rim, the part number,
    # the logo) while its clip limit keeps the already-bright USB metal from
    # blowing out into noise. Both edge passes run on this equalised copy.
    gray = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=(CLAHE_TILES, CLAHE_TILES)).apply(gray)
    g = cv2.bilateralFilter(gray, 7, 60, 60)

    # ---- A) adaptive filled-region contours ----
    gb = cv2.GaussianBlur(gray, (0, 0), 1.0)
    at = cv2.adaptiveThreshold(gb, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, ADAPT_BLOCK, ADAPT_C)
    at = cv2.morphologyEx(at, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), 1)
    at = cv2.morphologyEx(at, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), 1)
    at = drop_small_cc(at, min_area=max(24, int(0.00006 * H * W)))
    at = _blank_border(at)
    region_cnts, _ = cv2.findContours(at, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    region = [rectify(c.reshape(-1, 2)) for c in region_cnts
              if cv2.arcLength(c, True) >= 0.008 * (H + W)]
    at_boundary = cv2.morphologyEx(at, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))

    # ---- B) multi-scale Canny, de-doubled against the region boundaries ----
    if mask is not None and 0.02 < (mask > 0).mean() < 0.98:
        med = float(np.median(g[mask > 0]))
    else:
        med = float(np.median(g))
    canny = np.zeros((H, W), np.uint8)
    for sigma, spread in CANNY_SCALES:
        blur = cv2.GaussianBlur(g, (0, 0), sigma) if sigma > 0 else g
        lo = int(max(0, (1.0 - spread) * med))
        hi = int(min(255, (1.0 + spread) * med))
        canny = cv2.bitwise_or(canny, cv2.Canny(blur, lo, hi, L2gradient=True))
    covered = cv2.dilate(at_boundary, np.ones((3, 3), np.uint8), 2)
    canny = cv2.bitwise_and(canny, cv2.bitwise_not(covered))
    canny = _blank_border(canny)
    # merge doubled Canny edges (close the gap) then thin to a centreline
    canny = cv2.morphologyEx(canny, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), 1)
    skel = zhang_suen(canny)
    linear = trace_skeleton(skel)

    return region + linear


def drop_small_cc(binary, min_area):
    n, lab, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)
    keep = np.zeros_like(binary)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[lab == i] = 255
    return keep


# ---------------------------------------------------------------- dedup / thin
def zhang_suen(binary):
    """Vectorised Zhang-Suen thinning -> 1px skeleton (classic numpy, no
    ximgproc). Collapses the doubled parallel Canny edges of a thin trace into a
    single centreline."""
    img = (binary > 0).astype(np.uint8)
    for _ in range(60):
        changed = 0
        for step in range(2):
            p = np.pad(img, 1)
            P2 = p[:-2, 1:-1]; P3 = p[:-2, 2:]; P4 = p[1:-1, 2:]; P5 = p[2:, 2:]
            P6 = p[2:, 1:-1];  P7 = p[2:, :-2]; P8 = p[1:-1, :-2]; P9 = p[:-2, :-2]
            B = P2 + P3 + P4 + P5 + P6 + P7 + P8 + P9
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]
            A = np.zeros(img.shape, np.int32)
            for i in range(8):
                A += ((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.int32)
            if step == 0:
                c1 = (P2 * P4 * P6) == 0
                c2 = (P4 * P6 * P8) == 0
            else:
                c1 = (P2 * P4 * P8) == 0
                c2 = (P2 * P6 * P8) == 0
            cond = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & c1 & c2
            c = int(cond.sum())
            if c:
                img[cond] = 0
                changed += c
        if changed == 0:
            break
    return img


NB8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
MAX_TURN_COS = -0.35     # allow continuing through a junction up to ~110 deg


def trace_skeleton(skel):
    """Walk a 1px skeleton as a graph and emit centreline polylines. Crucially it
    walks THROUGH junctions, always taking the straightest continuation, so a
    long PCB trace that crosses others stays ONE stroke instead of shattering
    into a segment per crossing. Endpoints/loops are handled too. No doubled
    out-and-back paths (each undirected edge is used once)."""
    on = set(map(tuple, np.argwhere(skel > 0).tolist()))
    if not on:
        return []

    nb = {}
    for p in on:
        y, x = p
        nb[p] = [q for q in ((y + dy, x + dx) for dy, dx in NB8) if q in on]
    deg = {p: len(v) for p, v in nb.items()}
    used = set()                      # frozenset(edge) already consumed
    paths = []

    def straightest(prev_pts, cur, prev):
        """pick the unused neighbour whose direction best continues the heading"""
        # heading over the last few points (stable through a junction)
        back = prev_pts[-4] if len(prev_pts) >= 4 else prev_pts[0]
        hy, hx = cur[0] - back[0], cur[1] - back[1]
        hn = (hy * hy + hx * hx) ** 0.5 or 1.0
        best, best_c = None, MAX_TURN_COS
        for q in nb[cur]:
            if q == prev or frozenset((cur, q)) in used:
                continue
            vy, vx = q[0] - cur[0], q[1] - cur[1]
            vn = (vy * vy + vx * vx) ** 0.5 or 1.0
            c = (hy * vy + hx * vx) / (hn * vn)
            if c > best_c:
                best_c, best = c, q
        return best

    def walk(a, b):
        path = [a, b]
        used.add(frozenset((a, b)))
        prev, cur = a, b
        while True:
            nxt = straightest(path, cur, prev)
            if nxt is None:
                break
            used.add(frozenset((cur, nxt)))
            path.append(nxt)
            prev, cur = cur, nxt
        return path

    # 1) start at real endpoints (deg 1) -> longest natural strokes
    for node in [p for p in on if deg[p] == 1]:
        for q in nb[node]:
            if frozenset((node, q)) not in used:
                paths.append(walk(node, q))
    # 2) then junctions (deg >= 3) -> remaining branches
    for node in [p for p in on if deg[p] >= 3]:
        for q in nb[node]:
            if frozenset((node, q)) not in used:
                paths.append(walk(node, q))
    # 3) leftover pure loops (all degree 2)
    for p in on:
        for q in nb[p]:
            if frozenset((p, q)) not in used:
                paths.append(walk(p, q))

    return [np.array([(x, y) for y, x in pth], float) for pth in paths]


# ---------------------------------------------------------------- path shaping
def smooth(pts, sigma, closed):
    pts = np.asarray(pts, float)
    n = len(pts)
    if n < 5 or sigma <= 0:
        return pts
    rad = max(1, int(round(sigma * 3)))
    ker = np.exp(-(np.arange(-rad, rad + 1) ** 2) / (2 * sigma * sigma))
    ker /= ker.sum()
    mode = "wrap" if closed else "edge"
    x = np.convolve(np.pad(pts[:, 0], rad, mode=mode), ker, "valid")
    y = np.convolve(np.pad(pts[:, 1], rad, mode=mode), ker, "valid")
    return np.stack([x, y], 1)


def simplify(pts, eps, closed):
    if len(pts) < 4 or eps <= 0:
        return pts
    p = cv2.approxPolyDP(pts.astype(np.float32).reshape(-1, 1, 2), eps, closed)
    return p.reshape(-1, 2)


def is_closed(pts):
    return len(pts) > 3 and np.hypot(*(pts[0] - pts[-1])) < 4


def path_len(pts):
    if len(pts) < 2:
        return 0.0
    d = np.diff(np.asarray(pts, float), axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def line_path(pts, closed):
    pts = np.asarray(pts, float)
    d = "M{:.1f} {:.1f}".format(pts[0, 0], pts[0, 1])
    for x, y in pts[1:]:
        d += " L{:.1f} {:.1f}".format(x, y)
    return d + (" Z" if closed else "")


def bezier_path(pts, closed):
    """Catmull-Rom cubic Beziers for organic subjects (--curve)."""
    pts = np.asarray(pts, float)
    n = len(pts)
    if n < 3:
        return line_path(pts, closed)
    P = (lambda i: pts[i % n]) if closed else (lambda i: pts[min(max(i, 0), n - 1)])
    d = "M{:.1f} {:.1f}".format(pts[0, 0], pts[0, 1])
    for i in range(n if closed else n - 1):
        p0, p1, p2, p3 = P(i - 1), P(i), P(i + 1), P(i + 2)
        c1 = p1 + (p2 - p0) / 6.0
        c2 = p2 - (p3 - p1) / 6.0
        d += " C{:.1f} {:.1f} {:.1f} {:.1f} {:.1f} {:.1f}".format(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])
    return d + (" Z" if closed else "")


def _poly_extent(pts):
    """Fraction of a shape's axis-aligned bounding box that it fills."""
    x, y, w, h = cv2.boundingRect(pts.astype(np.float32))
    if w * h == 0:
        return 0.0
    return abs(cv2.contourArea(pts.astype(np.float32))) / float(w * h)


def shape(pts):
    """smooth -> simplify -> polyline or Bezier; returns (d, closed, length).

    In curve mode the organic strokes get a hand-drawn wobble (Bezier), but a
    crisp rectangle -- a pad, an SMD part, a rectified chip -- is detected (few
    vertices, fills its bounding box) and kept dead-straight so it doesn't bulge
    into a blob. Straight PCB edges stay sharp; only the free-form lines wobble."""
    closed = is_closed(pts)
    sm = smooth(pts, SMOOTH_SIGMA, closed)
    sm = simplify(sm, SIMPLIFY_EPS, closed)
    if len(sm) < 2:
        return None
    rect_like = closed and len(sm) <= 6 and _poly_extent(sm) > 0.82
    emit = bezier_path if (USE_CURVE and not rect_like) else line_path
    return emit(sm, closed), closed, path_len(sm)


def shape_case(pts):
    """The outer silhouette gets heavier de-jitter and is emitted as a smooth
    Bezier so a rounded translucent end (e.g. a keyring lug) reads as a clean
    curve instead of a jagged polygon, even while interior detail stays straight.
    Returns (d, closed, length) or None."""
    sm = smooth(pts, CASE_SMOOTH_SIGMA, True)
    sm = simplify(sm, CASE_SIMPLIFY_EPS, True)
    if len(sm) < 3:
        return None
    return bezier_path(sm, True), True, path_len(sm)


# ---------------------------------------------------------------- build svg
def rounded_rect_path(x0, y0, x1, y1, r):
    """SVG path for a rounded rectangle (used to draw a config 'box' part as a
    crisp chip outline)."""
    r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    return ("M{:.1f} {:.1f} H{:.1f} A{r:.1f} {r:.1f} 0 0 1 {:.1f} {:.1f} "
            "V{:.1f} A{r:.1f} {r:.1f} 0 0 1 {:.1f} {:.1f} H{:.1f} "
            "A{r:.1f} {r:.1f} 0 0 1 {:.1f} {:.1f} V{:.1f} "
            "A{r:.1f} {r:.1f} 0 0 1 {:.1f} {:.1f} Z").format(
        x0 + r, y0, x1 - r, x1, y0 + r,
        y1 - r, x1 - r, y1, x0 + r,
        x0, y1 - r, y0 + r,
        x0 + r, y0, r=r)


def build(outline, strokes, size, boxes=None):
    """strokes: list of (pts). boxes: list of (x0,y0,x1,y1) chip rectangles.
    Returns (W,H, body, dot, count)."""
    W, H = size
    diag = float(np.hypot(W, H))
    min_len = MIN_LEN_FRAC * diag
    fine_t = FINE_FRAC * diag
    detail_t = DETAIL_FRAC * diag

    items = []   # (length, cls, d)

    if outline is not None:
        r = shape_case(outline)
        if r:
            items.append((1e9, "case", r[0]))      # object silhouette = bold case outline

    for (bx0, by0, bx1, by1) in (boxes or []):     # config 'box' parts = crisp chip outlines
        rr = CHIP_RADIUS_FRAC * min(bx1 - bx0, by1 - by0)
        items.append((5e8, "chip", rounded_rect_path(bx0, by0, bx1, by1, rr)))

    for pts in strokes:
        r = shape(pts)
        if not r:
            continue
        d, _closed, L = r
        if L < min_len:
            continue
        cls = "fine" if L < fine_t else ("detail" if L < detail_t else "edge")
        items.append((L, cls, d))

    # cap: keep the longest MAX_PATHS
    if len(items) > MAX_PATHS:
        items.sort(key=lambda t: t[0], reverse=True)
        items = items[:MAX_PATHS]

    # draw order: long -> short (structure appears first), delays spread across
    # a fixed window so the animation stays the same length regardless of count
    items.sort(key=lambda t: t[0], reverse=True)
    n = len(items)
    paths = []
    for i, (_L, cls, d) in enumerate(items):
        delay = 60 + int(DRAW_WINDOW_MS * (i / max(1, n - 1))) if n > 1 else 60
        paths.append('<path class="%s" pathLength="1" style="animation-delay:%dms" d="%s"/>'
                     % (cls, delay, d))

    body = "\n    ".join(paths)
    dot = '<circle class="dot" cx="%.0f" cy="%.0f" r="4"/>' % (W * 0.5, H * 0.52)
    return W, H, body, dot, n


# ---------------------------------------------------------------- LABELS / CALLOUTS
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def load_labels(path, W, H):
    """Read a human --labels JSON: [{"x":0-1,"y":0-1,"text":"NAME"}, ...].
    Returns component-space dicts {px, py, text}. Coords are image-relative so
    the same file works whatever the working resolution.

    A label may also carry an optional ``"box":[x0,y0,x1,y1]`` (image-relative)
    to draw that part as a crisp rounded rectangle. This is the honest way to
    give a dark-on-dark chip -- an RF-shield can whose faint rim the tracer can
    only find in fragments -- a clean square outline, positioned by a human who
    can see where the part actually is. Stored as pixel corners in ``box``."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):                 # tolerate {"labels":[...]}
        data = data.get("labels", [])
    out = []
    for d in data:
        try:
            x = float(d["x"]); y = float(d["y"]); t = str(d["text"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not t:
            continue
        # accept either 0-1 relative or already-pixel coords
        px = x * W if 0.0 <= x <= 1.0 else x
        py = y * H if 0.0 <= y <= 1.0 else y
        rec = {"px": float(np.clip(px, 0, W)),
               "py": float(np.clip(py, 0, H)), "text": t}
        b = d.get("box")
        if isinstance(b, (list, tuple)) and len(b) == 4:
            try:
                bx0, by0, bx1, by1 = (float(v) for v in b)
                to_px = lambda v, S: v * S if 0.0 <= v <= 1.0 else v
                x0, x1 = sorted((to_px(bx0, W), to_px(bx1, W)))
                y0, y1 = sorted((to_px(by0, H), to_px(by1, H)))
                rec["box"] = (x0, y0, x1, y1)
            except (TypeError, ValueError):
                pass
        out.append(rec)
    return out


def _protrusions(m, W, H):
    """Connector-like edge tips: rows/cols where the silhouette juts well past
    its own median boundary on a side. Returns up to 4 (x, y) image points."""
    tips = []
    for axis in (0, 1):                        # 0: left/right tips, 1: top/bottom
        mm = m if axis == 0 else m.T
        Hh, Ww = mm.shape
        first = np.full(Hh, -1); last = np.full(Hh, -1)
        for r in range(Hh):
            idx = np.flatnonzero(mm[r])
            if idx.size:
                first[r] = idx[0]; last[r] = idx[-1]
        v = first >= 0
        if int(v.sum()) < 8:
            continue
        medF = np.median(first[v]); medL = np.median(last[v])
        thr = 0.06 * Ww + 4
        lo = np.flatnonzero(v & (first < medF - thr))
        if lo.size:
            r = lo[int(np.argmin(first[lo]))]
            tips.append((int(first[r]), int(r)) if axis == 0 else (int(r), int(first[r])))
        hi = np.flatnonzero(v & (last > medL + thr))
        if hi.size:
            r = hi[int(np.argmax(last[hi]))]
            tips.append((int(last[r]), int(r)) if axis == 0 else (int(r), int(last[r])))
    return tips


def auto_labels(gray, mask, W, H):
    """Light, honest geometric fallback used only when no --labels file exists:
    tag the biggest interior bright block ("MODULE") and connector-like edge
    protrusions ("CONN"). Returns component-space dicts {px, py, text}."""
    labels = []
    if mask is None:
        return labels
    m = (mask > 0).astype(np.uint8)
    area = int(m.sum())
    if area < 0.02 * W * H:
        return labels

    # --- biggest interior bright block -> MODULE ---
    try:
        interior = cv2.erode(m * 255, np.ones((5, 5), np.uint8), 1)
        vals = gray[interior > 0]
        if vals.size > 50:
            thr = float(np.clip(np.mean(vals) + 0.6 * np.std(vals), 0, 255))
            bright = ((gray > thr) & (interior > 0)).astype(np.uint8)
            bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), 1)
            bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), 1)
            nlab, lab, stats, cent = cv2.connectedComponentsWithStats(bright, 8)
            best, best_a = -1, 0
            for i in range(1, nlab):
                a = stats[i, cv2.CC_STAT_AREA]
                x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
                w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
                if x <= 2 or y <= 2 or x + w >= W - 2 or y + h >= H - 2:
                    continue                    # touches frame -> probably shell
                if a > best_a and a > 0.015 * area and w > 6 and h > 6:
                    best_a, best = a, i
            if best > 0:
                cx, cy = cent[best]
                labels.append({"px": float(cx), "py": float(cy), "text": "MODULE"})
    except Exception:
        pass

    # --- connector-like protrusions -> CONN ---
    try:
        for tx, ty in _protrusions(m, W, H):
            labels.append({"px": float(tx), "py": float(ty), "text": "CONN"})
    except Exception:
        pass

    # de-dupe near-coincident tags
    out = []
    for l in labels:
        if all(abs(l["px"] - o["px"]) > 0.06 * W or abs(l["py"] - o["py"]) > 0.06 * H
               for o in out):
            out.append(l)
    return out


def _layout_side(grp, H, F):
    """Vertically distribute one margin's labels: sort by anchor-y, then enforce
    a minimum gap (order preserved -> straight leaders never cross)."""
    if not grp:
        return
    grp.sort(key=lambda l: l["py"])
    gap = F * GAP_FRAC
    top = F * 0.9
    bot = H - F * 0.5
    ys = [min(max(l["py"], top), bot) for l in grp]
    for i in range(1, len(ys)):
        if ys[i] < ys[i - 1] + gap:
            ys[i] = ys[i - 1] + gap
    if ys[-1] > bot:                            # overflowed the bottom -> push up
        ys[-1] = bot
        for i in range(len(ys) - 2, -1, -1):
            if ys[i] > ys[i + 1] - gap:
                ys[i] = ys[i + 1] - gap
    if ys[0] < top:
        ys[0] = top
        for i in range(1, len(ys)):
            if ys[i] < ys[i - 1] + gap:
                ys[i] = ys[i - 1] + gap
    for l, y in zip(grp, ys):
        l["ly"] = y


def build_callouts(labels, W, H):
    """Turn component-space label dicts into SVG. Returns
    (svg_markup, margin_left, margin_right, count). Widen the viewBox by the
    returned margins so nothing is clipped."""
    if not labels:
        return "", 0.0, 0.0, 0
    diag = float(np.hypot(W, H))
    F = max(LABEL_MIN, round(LABEL_FRAC * diag))
    stub = max(12.0, STUB_FRAC * W)

    for l in labels:
        l["side"] = "L" if l["px"] < W * 0.5 else "R"
        l["tw"] = len(l["text"]) * F * CHAR_W

    left = [l for l in labels if l["side"] == "L"]
    right = [l for l in labels if l["side"] == "R"]
    _layout_side(left, H, F)
    _layout_side(right, H, F)

    max_l = max((l["tw"] for l in left), default=0.0)
    max_r = max((l["tw"] for l in right), default=0.0)
    ML = (GUTTER + SHELF + max_l + MARGIN_PAD) if left else 0.0
    MR = (GUTTER + SHELF + max_r + MARGIN_PAD) if right else 0.0

    dot_r = max(2.2, F * 0.085)
    order = left + right                        # left column first, then right
    n = len(order)
    parts = []
    for i, l in enumerate(order):
        ax, ay, ly = l["px"], l["py"], l["ly"]
        lead_delay = CALLOUT_START + i * CALLOUT_STAGGER
        mark_delay = lead_delay + CALLOUT_AFTER
        if l["side"] == "L":
            p1x = max(ax - stub, -GUTTER + 4.0)          # horizontal stub, clamped
            gx = -GUTTER                                 # turn column, just off board
            tx = gx - SHELF                              # text end (anchor=end)
            d = ("M{:.1f} {:.1f} L{:.1f} {:.1f} L{:.1f} {:.1f} L{:.1f} {:.1f}"
                 .format(ax, ay, p1x, ay, gx, ly, tx + 3.0, ly))
            anchor, textx = "end", tx
        else:
            p1x = min(ax + stub, W + GUTTER - 4.0)
            gx = W + GUTTER
            tx = gx + SHELF                              # text start (anchor=start)
            d = ("M{:.1f} {:.1f} L{:.1f} {:.1f} L{:.1f} {:.1f} L{:.1f} {:.1f}"
                 .format(ax, ay, p1x, ay, gx, ly, tx - 3.0, ly))
            anchor, textx = "start", tx
        parts.append('<path class="callout" pathLength="1" style="animation-delay:%dms" d="%s"/>'
                     % (lead_delay, d))
        parts.append('<circle class="anchordot" cx="%.1f" cy="%.1f" r="%.1f" style="animation-delay:%dms"/>'
                     % (ax, ay, dot_r, mark_delay))
        parts.append('<text class="label" x="%.1f" y="%.1f" text-anchor="%s" font-size="%.1f" style="animation-delay:%dms">%s</text>'
                     % (textx, ly + F * 0.34, anchor, F, mark_delay, _esc(l["text"])))
    return "\n    ".join(parts), ML, MR, n


HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100svh; background:{black}; color:{stroke};
    font-family:"Archivo",system-ui,sans-serif; display:flex; flex-direction:column;
    align-items:center; justify-content:center; gap:20px; padding:40px 20px; }}
  h1 {{ margin:0; font-size:26px; font-weight:800; letter-spacing:-0.02em; }}
  .cap {{ margin:0; font-family:"IBM Plex Mono",monospace; font-size:12px;
    letter-spacing:0.06em; color:{stroke2}; }}
  .frame {{ width:100%; max-width:760px; }}
  svg {{ width:100%; height:auto; display:block; }}
  .case   {{ fill:none; stroke:{stroke};  stroke-width:2.6; stroke-linecap:round; stroke-linejoin:round; }}
  .chip   {{ fill:none; stroke:{stroke};  stroke-width:2.0; stroke-linecap:round; stroke-linejoin:round; }}
  .edge   {{ fill:none; stroke:{stroke};  stroke-width:1.5; stroke-linecap:round; stroke-linejoin:round; }}
  .detail {{ fill:none; stroke:{stroke2}; stroke-width:0.9; stroke-linecap:round; stroke-linejoin:round; }}
  .fine   {{ fill:none; stroke:{stroke2}; stroke-width:0.6; stroke-linecap:round; stroke-linejoin:round; opacity:0.85; }}
  .dot    {{ fill:{accent}; }}
  .callout {{ fill:none; stroke:{stroke2}; stroke-width:0.9; stroke-linecap:round;
    stroke-linejoin:round; opacity:0.85; }}
  .anchordot {{ fill:{stroke2}; }}
  .label {{ fill:{stroke}; font-family:"IBM Plex Mono",ui-monospace,monospace;
    font-weight:500; letter-spacing:0.06em; }}
  .case, .chip, .edge, .detail, .fine {{ stroke-dasharray:1; stroke-dashoffset:1;
    animation:draw 1.5s cubic-bezier(0.28,0.11,0.32,1) forwards; }}
  .dot {{ opacity:0; animation:pop 0.5s ease 1.7s forwards; }}
  .callout {{ stroke-dasharray:1; stroke-dashoffset:1;
    animation:draw 0.6s cubic-bezier(0.28,0.11,0.32,1) forwards; }}
  .anchordot {{ opacity:0; animation:pop 0.4s ease forwards; }}
  .label {{ opacity:0; animation:pop 0.5s ease forwards; }}
  @keyframes draw {{ to {{ stroke-dashoffset:0; }} }}
  @keyframes pop  {{ to {{ opacity:1; }} }}
  @media (prefers-reduced-motion: reduce) {{
    .case, .chip, .edge, .detail, .fine, .callout {{ animation:none; stroke-dashoffset:0; }}
    .dot, .anchordot, .label {{ animation:none; opacity:1; }}
  }}
</style></head>
<body>
  <h1>{title}</h1>
  <div class="frame">
    <svg viewBox="{vbx:.1f} {vby:.1f} {vbw:.1f} {vbh:.1f}" xmlns="http://www.w3.org/2000/svg">
    {body}
    {dot}
    {callouts}
    </svg>
  </div>
  <p class="cap">{caption}</p>
</body></html>
"""


def rasterize_debug(W, H, outline, strokes, path_out):
    """Draw the collected polylines to a PNG for visual QA (not part of output)."""
    canvas = np.zeros((H, W, 3), np.uint8)
    diag = float(np.hypot(W, H))
    fine_t, detail_t = FINE_FRAC * diag, DETAIL_FRAC * diag
    min_len = MIN_LEN_FRAC * diag
    for pts in strokes:
        r = shape(pts)
        if not r:
            continue
        _d, _c, L = r
        if L < min_len:
            continue
        sm = simplify(smooth(pts, SMOOTH_SIGMA, is_closed(pts)), SIMPLIFY_EPS, is_closed(pts))
        col = (143, 143, 143) if L < detail_t else (245, 245, 247)
        th = 1 if L < fine_t else (1 if L < detail_t else 2)
        cv2.polylines(canvas, [sm.astype(np.int32)], is_closed(pts), col, th, cv2.LINE_AA)
    if outline is not None:
        sm = simplify(smooth(outline, SMOOTH_SIGMA, True), SIMPLIFY_EPS, True)
        cv2.polylines(canvas, [sm.astype(np.int32)], True, (245, 245, 247), 2, cv2.LINE_AA)
    cv2.imwrite(path_out, canvas)


_ROTATE = {90: Image.ROTATE_90, 180: Image.ROTATE_180, 270: Image.ROTATE_270}


def run(src, out, title, labels_file=None, debug_png=None, rotate=0, curve=None):
    """Trace ``src`` into an animated line-figure HTML at ``out``.

    rotate: 0/90/180/270 -- turn the source before tracing, e.g. to stand a
            laid-down device upright (or lay an upright one down) to fit a layout.
    curve:  None keeps the module default; True forces wobble, False forces
            straight. This is the programmatic entry point the wizard-builder
            calls, so keep its signature stable."""
    if curve is not None:
        globals()["USE_CURVE"] = bool(curve)
    img = load_image(src)
    if rotate % 360 in _ROTATE:
        img = img.transpose(_ROTATE[rotate % 360])
    w0, h0 = img.size
    long_edge = max(w0, h0)
    if long_edge > WORK_MAX:
        s = WORK_MAX / long_edge
    elif long_edge < WORK_MIN:
        s = WORK_MIN / long_edge
    else:
        s = 1.0
    if s != 1.0:
        img = img.resize((max(1, round(w0 * s)), max(1, round(h0 * s))), Image.LANCZOS)
    W, H = img.size
    gray = np.asarray(img.convert("L"))

    mask, outline = segment(gray)
    strokes = extract_strokes(gray, mask)

    # --- labels: human config is the primary path; auto only as a fallback ---
    src_kind = "none"
    if labels_file:
        labels = load_labels(labels_file, W, H)
        src_kind = "config"
    else:
        labels = auto_labels(gray, mask, W, H)
        src_kind = "auto" if labels else "none"

    # draw the segmentation silhouette as a bold .case outline so the clear
    # acrylic shell reads strongly even though its own edge is a faint tone;
    # any label carrying a 'box' is drawn as a crisp chip rectangle.
    boxes = [l["box"] for l in labels if l.get("box")]
    W, H, body, dot, n = build(outline, strokes, (W, H), boxes=boxes)
    callouts, ML, MR, nl = build_callouts(labels, W, H)

    # --- bare-SVG emit (out ends .svg): a fragment for embedding in a flasher,
    #     no HTML chrome, no callouts (the host draws its own), viewBox tight to
    #     the figure. A sidecar <out>.anchors.json gives every label's anchor in
    #     user units so the host can pin interactive cues (boot highlight, LED,
    #     flash shimmer) onto the traced drawing. ---
    if out.lower().endswith(".svg"):
        import re as _re
        frag = _re.sub(r'\s*style="animation-delay:\d+ms"', '', body)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.1f %.1f" '
               'class="device-fig" role="img" aria-label="%s">\n    %s\n</svg>\n'
               % (float(W), float(H), _esc(title), frag))
        with open(out, "w", encoding="utf-8") as f:
            f.write(svg)
        anchors = {"viewBox": [0, 0, W, H],
                   "labels": {l["text"]: [round(l["px"], 1), round(l["py"], 1)] for l in labels},
                   "boxes": {l["text"]: [round(v, 1) for v in l["box"]]
                             for l in labels if l.get("box")}}
        with open(out[:-4] + ".anchors.json", "w", encoding="utf-8") as f:
            json.dump(anchors, f, indent=1)
        if debug_png:
            rasterize_debug(W, H, None, strokes, debug_png)
        texts = [l["text"] for l in labels]
        print("[figure-svg] %-36s -> %-40s  %d strokes  %d anchors  (@%dx%d)"
              % (src, out, n, nl, W, H))
        return n, nl, texts

    vbx, vby = -ML, 0.0
    vbw, vbh = W + ML + MR, float(H)
    cap = "auto-traced from a photo &middot; %d strokes" % n
    if nl:
        cap += " &middot; %d %s labels" % (nl, "config" if src_kind == "config" else "auto")

    html = HTML.format(title=title, black=BLACK, stroke=STROKE, stroke2=STROKE2,
                       accent=ACCENT, vbx=vbx, vby=vby, vbw=vbw, vbh=vbh,
                       body=body, dot=dot, callouts=callouts, caption=cap)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    if debug_png:
        rasterize_debug(W, H, None, strokes, debug_png)
    texts = [l["text"] for l in labels]
    print("[figure] %-40s -> %-45s  %d strokes  %d labels [%s] %s  (@%dx%d)"
          % (src, out, n, nl, src_kind, texts, W, H))
    return n, nl, texts


def main():
    ap = argparse.ArgumentParser(description="Photo -> maximum-detail line figure with callouts.")
    ap.add_argument("src", help="image URL or local path")
    ap.add_argument("-o", "--out", default="figure.html")
    ap.add_argument("--title", default="Traced figure")
    ap.add_argument("--labels", default=None, help="JSON [{x,y,text}] of callouts (image-relative 0-1). Primary path; drawn exactly. Omit for a light auto fallback.")
    ap.add_argument("--min-len", type=float, default=None, help="drop paths shorter than FRAC*diagonal (higher = less noise). Default 0.013")
    ap.add_argument("--simplify", type=float, default=None, help="Douglas-Peucker epsilon (higher = straighter). Default 2.0")
    ap.add_argument("--max", type=int, default=None, help="downscale long edge above this. Default 1500")
    ap.add_argument("--upscale", type=int, default=None, help="upscale low-res long edge up to this. Default 1150")
    ap.add_argument("--adapt-c", type=int, default=None, help="silkscreen threshold bias (higher = less fine detail). Default 6")
    ap.add_argument("--curve", dest="curve", action="store_true", default=None, help="organic strokes wobble (default)")
    ap.add_argument("--straight", dest="curve", action="store_false", help="force dead-straight polylines everywhere")
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270], help="turn the source before tracing (stand a device upright, etc.)")
    ap.add_argument("--debug-png", default=None)
    a = ap.parse_args()
    g = globals()
    if a.min_len is not None:  g["MIN_LEN_FRAC"] = a.min_len
    if a.simplify is not None: g["SIMPLIFY_EPS"] = a.simplify
    if a.max is not None:      g["WORK_MAX"] = a.max
    if a.upscale is not None:  g["WORK_MIN"] = a.upscale
    if a.adapt_c is not None:  g["ADAPT_C"] = a.adapt_c
    run(a.src, a.out, a.title, a.labels, a.debug_png, rotate=a.rotate, curve=a.curve)


if __name__ == "__main__":
    main()
