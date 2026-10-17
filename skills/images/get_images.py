#!/usr/bin/env python3
"""הורדת תמונות חינמיות לפרויקט — Pexels (עם מפתח חינמי) או Openverse (בלי מפתח).

שימוש:
  python3 get_images.py "<נושא באנגלית>" [--count 10] [--size web|post|story|square|deck]
                        [--orientation landscape|portrait|square] [--out images] [--source pexels|openverse]

המפתח של Pexels נקרא מ-PEXELS_API_KEY: משתנה סביבה, או קובץ .env בתיקייה הנוכחית,
או ~/my-business/.env. בלי מפתח — עוברים אוטומטית ל-Openverse.
כל הורדה נרשמת ב-<out>/sources.md (קובץ, צלם, עמוד מקור, רישיון).
פייתון בלבד, בלי חבילות נוספות. עובד במק ובחלונות.
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path

# גדלים מוכנים: (רוחב, גובה). גובה None = שומרים על היחס המקורי.
SIZES = {
    "web": (1600, None),      # תמונה לדף נחיתה או לאתר
    "post": (1080, 1350),     # פוסט לאינסטגרם/פייסבוק (4:5)
    "story": (1080, 1920),    # סטורי / ריל (9:16)
    "square": (1080, 1080),   # פוסט מרובע
    "deck": (1920, 1080),     # שקופית במצגת (16:9)
}
DEFAULT_ORIENTATION = {"web": "landscape", "post": "portrait", "story": "portrait", "square": "square", "deck": "landscape"}
UA = {"User-Agent": "machine-starter-images/1.0"}


def find_key():
    if os.environ.get("PEXELS_API_KEY"):
        return os.environ["PEXELS_API_KEY"].strip()
    for env in (Path.cwd() / ".env", Path.home() / "my-business" / ".env"):
        if env.exists():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"\s*PEXELS_API_KEY\s*=\s*['\"]?([^'\"\s]+)", line)
                if m and not m.group(1).startswith("<"):
                    return m.group(1)
    return None


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def download(url, path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "image"


def from_pexels(key, query, count, size, orientation):
    w, h = SIZES[size]
    params = {"query": query, "per_page": min(count, 80), "orientation": orientation}
    data = get_json("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(params), {"Authorization": key})
    out = []
    for p in data.get("photos", [])[:count]:
        # ה-CDN של Pexels חותך ומקטין לפי הפרמטרים, אז לא צריך תוכנה לעיבוד תמונה
        extra = f"&w={w}&h={h}&fit=crop" if h else f"&w={w}"
        out.append({
            "url": p["src"]["original"] + "?auto=compress&cs=tinysrgb" + extra,
            "author": p.get("photographer", ""),
            "page": p.get("url", ""),
            "license": "Pexels License (חינם לשימוש מסחרי, בלי חובת קרדיט)",
            "ext": "jpg",
        })
    return out


def from_openverse(query, count):
    params = {"q": query, "page_size": min(count, 20), "license_type": "commercial", "mature": "false"}
    data = get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(params))
    out = []
    for p in data.get("results", [])[:count]:
        lic = (p.get("license") or "").upper()
        ver = p.get("license_version") or ""
        needs_credit = lic not in ("CC0", "PDM")
        ext = (p.get("filetype") or "jpg").lower().replace("jpeg", "jpg")
        out.append({
            "url": p["url"],
            "author": p.get("creator") or "",
            "page": p.get("foreign_landing_url") or "",
            "license": f"{'CC ' if lic not in ('CC0', 'PDM') else ''}{lic} {ver}".strip()
                       + (" — חובה לתת קרדיט לצלם" if needs_credit else " — בלי חובת קרדיט"),
            "ext": ext if ext in ("jpg", "png", "webp") else "jpg",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--size", choices=SIZES, default="web")
    ap.add_argument("--orientation", choices=["landscape", "portrait", "square"])
    ap.add_argument("--out", default="images")
    ap.add_argument("--source", choices=["pexels", "openverse"])
    a = ap.parse_args()

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = find_key()
    source = a.source or ("pexels" if key else "openverse")
    if source == "pexels" and not key:
        sys.exit("NO_KEY: לא נמצא PEXELS_API_KEY. אפשר להמשיך עם --source openverse.")

    try:
        if source == "pexels":
            items = from_pexels(key, a.query, a.count, a.size, a.orientation or DEFAULT_ORIENTATION[a.size])
        else:
            items = from_openverse(a.query, a.count)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: " + ("המפתח של Pexels לא תקין." if e.code in (401, 403) else "השירות לא ענה. לנסות שוב בעוד דקה."))

    if not items:
        sys.exit("NO_RESULTS: לא נמצאו תמונות. לנסות מילים אחרות באנגלית.")

    src_md = out_dir / "sources.md"
    new_file = not src_md.exists()
    saved = []
    with open(src_md, "a", encoding="utf-8") as log:
        if new_file:
            log.write("# מקורות התמונות\n\n| קובץ | צלם | עמוד מקור | רישיון |\n|---|---|---|---|\n")
        base = slug(a.query)
        n = len(list(out_dir.glob(base + "-*")))
        for i, it in enumerate(items, start=n + 1):
            name = f"{base}-{i:02d}.{it['ext']}"
            try:
                download(it["url"], out_dir / name)
            except Exception as e:  # תמונה אחת שנכשלה לא עוצרת את השאר
                print(f"✗ {name}: {e}")
                continue
            log.write(f"| {name} | {it['author']} | {it['page']} | {it['license']} |\n")
            saved.append(name)
            print(f"✓ {name}")
    print(f"\nנשמרו {len(saved)} תמונות ב-{out_dir} (מקור: {source}). רשימת מקורות: {src_md}")


if __name__ == "__main__":
    main()
