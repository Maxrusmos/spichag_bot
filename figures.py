"""Рендер схематичных GIF-анимаций упражнений (человечек-палочка)."""

from pathlib import Path

from PIL import Image, ImageDraw

from exercises import EXERCISES, POSES

MEDIA = Path(__file__).parent / "media"
SIZE = 480
BG = (250, 248, 243)
INK = (40, 44, 52)
ACCENT = (230, 110, 60)
PROP = (150, 170, 200)
BLOCK_H = .2
STEPS = 10   # кадров между ключевыми позами
HOLD = 5     # кадров удержания ключевой позы


def _apply_props(pose, props):
    pose = dict(pose)
    blocks = props.get("blocks")
    if blocks == "hands":
        feet_down = pose["ft"][1] < .05
        for k, (x, y) in pose.items():
            if k == "ft" and feet_down:
                continue
            if k == "kn" and feet_down:
                pose[k] = (x, y + BLOCK_H / 2)
                continue
            pose[k] = (x, y + BLOCK_H)
    elif blocks == "feet":
        for k, dy in (("ft", BLOCK_H), ("kn", .15), ("hip", .08)):
            x, y = pose[k]
            pose[k] = (x, y + dy)
    return pose


def _lerp(a, b, t):
    t = t * t * (3 - 2 * t)  # плавность
    return {k: (a[k][0] + (b[k][0] - a[k][0]) * t, a[k][1] + (b[k][1] - a[k][1]) * t) for k in a}


def _timeline(ex):
    keys = [_apply_props(POSES[f], ex.props) for f in ex.frames]
    seq = keys + (keys[-2:0:-1] if ex.loop == "pingpong" else [])
    if ex.loop == "cycle":
        seq = keys
    frames = []
    for i, cur in enumerate(seq):
        frames += [cur] * HOLD
        nxt = seq[(i + 1) % len(seq)]
        if ex.loop == "cycle" and i == len(seq) - 1:
            frames += [cur] * HOLD * 2  # пауза в конце, затем «прыжок» на старт
            break
        frames += [_lerp(cur, nxt, s / STEPS) for s in range(1, STEPS)]
    if len(keys) == 1:
        frames = [keys[0]]
    return keys, frames


def _transform(keys, props):
    xs = [p[0] for k in keys for p in k.values()] + [0]
    ys = [p[1] for k in keys for p in k.values()] + [0]
    if "wall" in props:
        xs.append(props["wall"] + .05)
    if "roll" in props:
        rx, ry, r = props["roll"]
        xs += [rx - r, rx + r]
    pad = .25
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - .1, max(ys) + pad
    scale = (SIZE - 40) / max(x1 - x0, y1 - y0)
    ox = SIZE / 2 - (x0 + x1) / 2 * scale
    oy = SIZE - 20 + y0 * scale
    return lambda p: (ox + p[0] * scale, oy - p[1] * scale), scale


def _draw(pose, tf, scale, props, ghost=None):
    img = Image.new("RGB", (SIZE, SIZE), BG)
    d = ImageDraw.Draw(img)
    gy = tf((0, 0))[1]
    d.line([(0, gy), (SIZE, gy)], fill=PROP, width=4)
    if "wall" in props:
        wx = tf((props["wall"] + .03, 0))[0]
        d.rectangle([wx, 0, wx + 10, gy], fill=PROP)
    if "roll" in props:
        rx, ry, r = props["roll"]
        cx, cy = tf((rx, ry))
        d.ellipse([cx - r * scale, cy - r * scale, cx + r * scale, cy + r * scale], fill=PROP)
    blocks = props.get("blocks")
    if blocks:
        bx = (ghost or pose)["ha" if blocks == "hands" else "ft"][0]
        a, b = tf((bx - .13, BLOCK_H)), tf((bx + .13, 0))
        d.rectangle([a, b], fill=PROP)
    w = max(6, int(scale * .06))
    pt = {k: tf(v) for k, v in pose.items()}
    for chain, col in (((pt["hip"], pt["kn"], pt["ft"]), INK),
                       ((pt["head"], pt["sh"], pt["hip"]), INK),
                       ((pt["sh"], pt["el"], pt["ha"]), ACCENT)):
        d.line(chain, fill=col, width=w, joint="curve")
        for p in chain:
            d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=col)
    hx, hy = pt["head"]
    r = scale * .1
    d.ellipse([hx - r, hy - r, hx + r, hy + r], fill=BG, outline=INK, width=w // 2 + 1)
    return img


def render(ex, out_dir=MEDIA):
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{ex.id}.gif"
    keys, frames = _timeline(ex)
    tf, scale = _transform(keys, ex.props)
    imgs = [_draw(f, tf, scale, ex.props, ghost=keys[0]) for f in frames]
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=60, loop=0, optimize=True)
    return path


def render_all():
    return {ex.id: render(ex) for ex in EXERCISES}


def gif_path(ex_id):
    return MEDIA / f"{ex_id}.gif"


if __name__ == "__main__":
    for k, p in render_all().items():
        print(k, p)
