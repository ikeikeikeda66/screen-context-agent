"""Apple Vision OCR wrapper.

VNRecognizeTextRequest at the accurate level. Languages default to ja-JP + en-US;
set SCREEN_CONTEXT_OCR_LANGUAGES (comma-separated BCP 47 tags) to change them.
"""
import os
import Vision
import Quartz
from Foundation import NSDictionary

# VNRequestTextRecognitionLevel: Accurate=0, Fast=1.
# ja-JP is ONLY offered at Accurate + revision 3.
ACCURATE = 0
FAST = 1
REVISION_JA = 3


def supported_languages(level=ACCURATE, revision=REVISION_JA):
    req = Vision.VNRecognizeTextRequest.alloc().init()
    # order matters: level must be set before revision for the language list
    req.setRecognitionLevel_(level)
    if revision is not None:
        req.setRevision_(revision)
    langs, err = req.supportedRecognitionLanguagesAndReturnError_(None)
    if err:
        raise RuntimeError(str(err))
    return [str(x) for x in langs]


def default_languages():
    value = os.environ.get("SCREEN_CONTEXT_OCR_LANGUAGES", "")
    return tuple(x.strip() for x in value.split(",") if x.strip()) or ("ja-JP", "en-US")


def recognize(cg_image, languages=None, level=ACCURATE,
              language_correction=True, min_height=None, revision=REVISION_JA):
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(level)
    if revision is not None:
        req.setRevision_(revision)
    req.setRecognitionLanguages_(list(languages or default_languages()))
    req.setUsesLanguageCorrection_(language_correction)
    if min_height:
        req.setMinimumTextHeight_(min_height)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cg_image, NSDictionary.dictionary()
    )
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(str(err))

    out = []
    for obs in (req.results() or []):
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        c = cands[0]
        bb = obs.boundingBox()
        out.append({
            "text": str(c.string()),
            "confidence": round(float(c.confidence()), 4),
            # Vision bbox: normalized, origin bottom-left
            "bbox": [round(float(bb.origin.x), 4), round(float(bb.origin.y), 4),
                     round(float(bb.size.width), 4), round(float(bb.size.height), 4)],
        })
    return out


def load_cgimage(path):
    from Foundation import NSURL
    url = NSURL.fileURLWithPath_(path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        raise RuntimeError(f"cannot read image: {path}")
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def save_png(cg_image, path):
    from Foundation import NSURL
    url = NSURL.fileURLWithPath_(path)
    dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, cg_image, None)
    return bool(Quartz.CGImageDestinationFinalize(dest))


def recognize_tiled(cg_image, cols=3, rows=3, overlap=0.08, upscale=2, **kw):
    """Tile + upscale before OCR.

    Measured on a synthetic test corpus: Vision's line detector collapses on wide,
    sparsely-filled layouts (spreadsheets, forms) — a full-width frame yields
    ~7% field recall where 3x3 tiles at 2x yield ~85%. Splitting COLUMNS is what
    recovers it; full-width horizontal strips do not help at all.
    """
    import Quartz
    W = Quartz.CGImageGetWidth(cg_image)
    H = Quartz.CGImageGetHeight(cg_image)
    tw, th = W // cols, H // rows
    ox, oy = int(tw * overlap), int(th * overlap)
    seen, out = set(), []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, c * tw - ox)
            y0 = max(0, r * th - oy)
            x1 = min(W, (c + 1) * tw + ox)
            y1 = min(H, (r + 1) * th + oy)
            tile = Quartz.CGImageCreateWithImageInRect(
                cg_image, Quartz.CGRectMake(x0, y0, x1 - x0, y1 - y0))
            if upscale > 1:
                tile = _scale(tile, upscale)
            for line in recognize(tile, **kw):
                bx, by, bw, bh = line["bbox"]
                # map tile-normalized bbox back to frame-normalized
                gx = (x0 + bx * (x1 - x0)) / W
                gy = 1.0 - ((y0 + (1 - by - bh) * (y1 - y0)) / H) - bh * (y1 - y0) / H
                line["bbox"] = [round(gx, 4), round(gy, 4),
                                round(bw * (x1 - x0) / W, 4),
                                round(bh * (y1 - y0) / H, 4)]
                key = (line["text"], round(gx, 2), round(gy, 2))
                if key in seen:
                    continue
                seen.add(key)
                out.append(line)
    out.sort(key=lambda l: (-l["bbox"][1], l["bbox"][0]))
    return out


def _scale(cg_image, factor):
    import Quartz
    W = Quartz.CGImageGetWidth(cg_image) * factor
    H = Quartz.CGImageGetHeight(cg_image) * factor
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, W, H, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedFirst)
    Quartz.CGContextSetInterpolationQuality(ctx, Quartz.kCGInterpolationHigh)
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, W, H), cg_image)
    return Quartz.CGBitmapContextCreateImage(ctx)
