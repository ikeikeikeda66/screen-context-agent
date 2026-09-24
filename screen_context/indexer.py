import io
import json
import time
from PIL import Image
from . import store
from .crypto import atomic_write, get_key, seal, unseal
from .privacy import denied, domains


def merge_lines(lines):
    output = []
    for line in sorted(lines, key=lambda x: (-x["bbox"][1], x["bbox"][0])):
        if any(line["text"].strip() == old["text"].strip() and abs(line["bbox"][0]-old["bbox"][0]) < .03 and abs(line["bbox"][1]-old["bbox"][1]) < .02 for old in output): continue
        output.append(line)
    return output


def native_ocr(image):
    import sys
    if sys.platform == "darwin":
        from .platforms import vision
        import Quartz
        from Foundation import NSData
        buf = io.BytesIO(); image.save(buf, "PNG"); data = buf.getvalue()
        src = Quartz.CGImageSourceCreateWithData(NSData.dataWithBytes_length_(data, len(data)), None)
        cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
        return merge_lines(vision.recognize(cg) + vision.recognize_tiled(cg))
    if sys.platform == "win32":
        from .platforms.windows import recognize
        return recognize(image)
    raise RuntimeError("Native OCR requires macOS or Windows")


def drain(settings, recognize=native_ocr):
    key = None if settings.plaintext else get_key(settings)
    stats = {"indexed": 0, "excluded": 0, "failed": 0}
    for path in sorted((settings.root / "spool").glob("*.frame")):
        try:
            raw = path.read_bytes()
            if key: raw = unseal(raw, key)
            header, png = raw.split(b"\n", 1)
            record = json.loads(header)
            if record["id"] != path.stem: raise ValueError("Spool ID mismatch")
            with store.connect(settings, readonly=True) as con:
                exists = con.execute("SELECT 1 FROM frames WHERE id=?", (record["id"],)).fetchone()
            if exists:
                path.unlink(); continue
            if denied(settings.policy(), record):
                path.unlink(); stats["excluded"] += 1; continue
            image = Image.open(io.BytesIO(png)).convert("RGB")
            started = time.monotonic()
            lines = recognize(image)
            record.update(ocr_text="\n".join(x["text"] for x in lines), ocr_json=json.dumps(lines, ensure_ascii=False), ocr_ms=int((time.monotonic()-started)*1000), src_w=image.width, src_h=image.height)
            if denied(settings.policy(), record):
                path.unlink(); stats["excluded"] += 1; continue
            record["domains"] = json.dumps(domains(record["ocr_text"]))
            image.thumbnail((1600, 1600), Image.Resampling.BILINEAR)
            buf = io.BytesIO(); image.save(buf, "WEBP", quality=60)
            record["image_path"] = record["id"] + ".webp" + (".enc" if key else "")
            data = seal(buf.getvalue(), key) if key else buf.getvalue()
            atomic_write(settings.root / "images" / record["image_path"], data)
            with store.connect(settings) as con: store.insert(con, record)
            path.unlink()
            stats["indexed"] += 1
        except Exception as error:
            # Retain for retry, do not log sensitive metadata or OCR contents.
            stats["failed"] += 1
            stats["last_error_type"] = type(error).__name__
    atomic_write(settings.root / "index-status.json", json.dumps({"ts": time.time(), **stats}).encode())
    return stats


def maintain(settings, now=None):
    from .service import Service
    from datetime import datetime
    now = now or time.time()
    cutoff = now - settings.retention_days*86400
    for path in (settings.root / "spool").glob("*.frame"):
        if path.stat().st_mtime < now - 86400: path.unlink(missing_ok=True)
    service = Service(settings, "full", "maintenance")
    with store.connect(settings, readonly=True) as con:
        dates = {datetime.fromtimestamp(r[0]).strftime("%Y-%m-%d") for r in con.execute("SELECT ts FROM frames")}
    rollups = {d: service.get_daily_rollup(d) for d in dates}
    with store.connect(settings) as con:
        for day, payload in rollups.items():
            con.execute("INSERT OR REPLACE INTO rollups VALUES (?,?)", (day, json.dumps(payload, ensure_ascii=False)))
        old = con.execute("SELECT image_path FROM frames WHERE ts < ? AND image_path IS NOT NULL", (cutoff,)).fetchall()
        for r in old:
            path = (settings.root / "images" / r[0]).resolve()
            if path.parent == (settings.root / "images").resolve(): path.unlink(missing_ok=True)
        # §8: retain searchable OCR; delete raw detail + preview after 90 days.
        con.execute("UPDATE frames SET image_path=NULL, ocr_json=NULL WHERE ts < ?", (cutoff,))
    return {"expired_images": len(old), "rollups": len(rollups)}
