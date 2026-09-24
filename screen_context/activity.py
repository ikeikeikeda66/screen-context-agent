from datetime import datetime
from .privacy import domains


def shingles(text):
    text = "".join(text.split())[:20000]
    return {text[i:i+3] for i in range(max(1, len(text)-2))}


def blocks(records, max_gap=600):
    result = []
    previous = set()
    for r in records:
        sh = shingles(r["ocr_text"])
        similarity = len(sh & previous) / max(1, len(sh | previous))
        last = result[-1] if result else None
        day = datetime.fromtimestamp(r["ts"]).date()
        if (last is None or last["app_bundle"] != r["app_bundle"] or last["display_id"] != r["display_id"] or r["ts"] - last["end_ts"] > max_gap or similarity < .25 or day != datetime.fromtimestamp(last["start_ts"]).date()):
            last = dict(block_id=r["id"], start_ts=r["ts"], end_ts=r["ts"], app_bundle=r["app_bundle"], app=r["app_name"], title=r["window_title"], display_id=r["display_id"], frames=0, text="", domains=[], frame_ids=[])
            result.append(last)
        last["end_ts"] = r["ts"]
        last["frames"] += 1
        last["frame_ids"].append(r["id"])
        seen = set(last["text"].splitlines())
        additions = [line for line in r["ocr_text"].splitlines() if line not in seen]
        last["text"] = (last["text"] + "\n" + "\n".join(additions)).strip()
        last["domains"] = sorted(set(last["domains"]) | set(domains(r["ocr_text"])))
        previous = sh
    return result
