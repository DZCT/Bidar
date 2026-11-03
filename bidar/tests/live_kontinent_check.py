# Live verification of Kontinent AI integration: config auto-heal, translation, model list, vision, text
import os, sys, json, asyncio, base64, struct, zlib, tempfile
from pathlib import Path
os.environ.setdefault("API_ID", "12345"); os.environ.setdefault("API_HASH", "x"); os.environ.setdefault("PHONE", "x")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/bidar")
import bidar  # noqa: E402

bidar.KONTINENT_API_KEY = os.environ["KONTINENT_API_KEY"]
results = {}


def png_solid(w=64, h=64, rgb=(0, 0, 255)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def check_heal():
    orig = bidar.CONFIG_FILE
    with tempfile.TemporaryDirectory() as d:
        bidar.CONFIG_FILE = Path(d) / "cfg.json"
        try:
            for mid, expect in [("gemini-3-flash-preview", "gemini-3.5-flash"), ("gpt-4o-mini", "gemini-3.5-flash"),
                                ("claude-sonnet-5-5", "claude-sonnet-5-5")]:
                bidar.CONFIG_FILE.write_text(json.dumps({"ai_model": mid, "bot_lang": "fa"}))
                bidar.load_config()
                saved = json.loads(bidar.CONFIG_FILE.read_text())
                ok = bidar.config["ai_model"] == expect and bidar.config["bot_lang"] == "fa"
                results[f"heal:{mid}"] = (ok, f"config={bidar.config['ai_model']} saved={saved.get('ai_model')}")
        finally:
            bidar.CONFIG_FILE = orig
    bidar.config["ai_model"] = "gemini-3.5-flash"


async def main():
    check_heal()
    tr = await bidar._translate_text("Hello, how are you?", "fa")
    results["translate"] = (bool(tr) and any("\u0600" <= c <= "\u06FF" for c in tr), repr(tr))
    models = await bidar._fetch_kontinent_models()
    exp = ["gemini-3.5-flash", "gemini-3.1-pro-preview", "claude-opus-5-5", "claude-sonnet-5-5",
           "claude-haiku-4-5-20251001", "gpt-5.5", "gpt-6.1-sol", "gpt-5", "glm-5.3", "qwen3.8-max", "deepseek-v4.1-flash"]
    missing = [m for m in exp if m not in models]
    results["models"] = (not missing and len(models) >= 11, f"n={len(models)} missing={missing} live={models} cache={bidar._kontinent_models_cache}")
    live_not_hardcoded = [m for m in models if m not in bidar.KONTINENT_MODELS]
    results["live_vs_hardcoded"] = (True, f"live-only ids (would be reset by load_config): {live_not_hardcoded}")
    b64 = base64.b64encode(png_solid()).decode()
    v = await bidar._kontinent_chat("You describe images briefly.", "What is the dominant color?", image_b64=b64)
    results["vision"] = ("blue" in v.lower(), repr(v))
    t = await bidar._kontinent_chat("You answer in one short sentence.", "What is the capital of Kenya?", model="gemini-3.5-flash")
    results["text"] = ("nairobi" in t.lower(), repr(t))
    for k, (ok, info) in results.items():
        print(("PASS" if ok else "FAIL"), k, "->", info)


asyncio.run(main())
