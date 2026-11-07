#!/usr/bin/env python3
"""יצירת תמונות AI בחינם — Cloudflare Workers AI (מודל FLUX.2 klein).

שימוש:
  python3 make_image.py "<תיאור באנגלית>" [--size web|post|story|square|deck] [--count 1]
                        [--name office] [--out images] [--seed 123]
  python3 make_image.py --check      # בודק שהחשבון מחובר, בלי ליצור תמונה

הפרטים נקראים מ-CF_ACCOUNT_ID ו-CF_API_TOKEN: משתני סביבה, או קובץ .env בתיקייה הנוכחית,
או ~/my-business/.env.
המכסה החינמית: 10,000 "נוירונים" ביום, בערך 60 תמונות. מתאפסת כל יום ב-00:00 UTC.
כל תמונה נרשמת ב-<out>/sources.md (קובץ, תיאור, מקור).
פייתון בלבד, בלי חבילות נוספות. עובד במק ובחלונות.
"""
import argparse, base64, json, os, re, sys, urllib.error, urllib.request, uuid
from datetime import date
from pathlib import Path

MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
# (רוחב, גובה) — כפולות של 16, ביחס של השימוש
SIZES = {
    "web": (1344, 768),     # דף נחיתה / אתר (רחב)
    "post": (832, 1040),    # פוסט אינסטגרם/פייסבוק 4:5
    "story": (768, 1344),   # סטורי / ריל (אנכי)
    "square": (1024, 1024), # פוסט מרובע
    "deck": (1344, 768),    # שקופית במצגת
}
RULES = (" Photorealistic, natural light, shot on a full-frame camera, realistic textures and imperfections."
         " Absolutely no text, letters, numbers, logos or watermarks.")


def neurons(w, h):
    return 26.05 * (-(-w // 512)) * (-(-h // 512))


def read_env():
    vals = {k: os.environ.get(k, "").strip() for k in ("CF_ACCOUNT_ID", "CF_API_TOKEN")}
    for env in (Path.cwd() / ".env", Path.home() / "my-business" / ".env"):
        if env.exists():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"\s*(CF_ACCOUNT_ID|CF_API_TOKEN)\s*=\s*['\"]?([^'\"\s]+)", line)
                if m and not vals[m.group(1)] and not m.group(2).startswith("<"):
                    vals[m.group(1)] = m.group(2)
    return vals["CF_ACCOUNT_ID"], vals["CF_API_TOKEN"]


def call(acc, tok, fields):
    b = uuid.uuid4().hex
    body = b"".join(
        f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()
    ) + f"--{b}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{MODEL}", data=body,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def explain_http(e):
    code = e.code
    txt = e.read().decode(errors="ignore")[:300]
    if code == 429 or "neuron" in txt.lower() or "limit" in txt.lower():
        return "QUOTA: נגמרה המכסה היומית (בערך 60 תמונות). היא מתאפסת כל יום ב-00:00 UTC (02:00–03:00 בלילה בישראל)."
    if code in (401, 403):
        return "AUTH: הטוקן או מספר החשבון לא נכונים, או שלטוקן אין הרשאת Workers AI."
    return f"ERROR {code}: {txt}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("--size", default="web", choices=SIZES)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--name", default="ai")
    ap.add_argument("--out", default="images")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    acc, tok = read_env()
    if not acc or not tok:
        print("NO_KEY: חסרים CF_ACCOUNT_ID ו-CF_API_TOKEN בקובץ .env")
        sys.exit(2)

    if a.check:
        req = urllib.request.Request("https://api.cloudflare.com/client/v4/user/tokens/verify",
                                     headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                ok = json.load(r).get("success")
            print("OK: הטוקן תקין" if ok else "AUTH: הטוקן לא תקין")
        except urllib.error.HTTPError as e:
            print(explain_http(e))
            sys.exit(1)
        return

    if not a.prompt:
        ap.error("חסר תיאור לתמונה")
    w, h = SIZES[a.size]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9-]+", "-", a.name.lower()).strip("-") or "ai"
    existing = len(list(out.glob(f"{slug}-ai-*.jpg")))
    made = []
    for i in range(a.count):
        fields = {"prompt": a.prompt.rstrip(". ") + "." + RULES, "width": w, "height": h}
        if a.seed is not None:
            fields["seed"] = a.seed + i
        try:
            res = call(acc, tok, fields)
        except urllib.error.HTTPError as e:
            print(explain_http(e))
            break
        except Exception as e:
            print(f"ERROR: {e}")
            break
        img = (res.get("result") or {}).get("image")
        if not img:
            print("ERROR: " + json.dumps(res, ensure_ascii=False)[:300])
            break
        path = out / f"{slug}-ai-{existing + i + 1:02d}.jpg"
        path.write_bytes(base64.b64decode(img))
        made.append(path)
        print(f"✓ {path}  ({w}×{h}, ~{neurons(w, h):.0f} נוירונים)")

    if made:
        src = out / "sources.md"
        lines = [] if src.exists() else ["# מקורות התמונות", ""]
        for p in made:
            lines.append(f"- **{p.name}** · נוצרה ב-AI (Cloudflare Workers AI, FLUX.2 klein) · {date.today():%d.%m.%Y}"
                         f" · תיאור: {a.prompt[:160]}")
        with src.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        per = neurons(w, h)
        print(f"נוצרו {len(made)} תמונות. כל תמונה בגודל הזה ~{per:.0f} נוירונים, כלומר כ-{int(10000 // per)} ביום.")


if __name__ == "__main__":
    main()
