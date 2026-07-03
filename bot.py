"""
نویسنده سورس:
	 @amir_big
	 کپی میری حداقل منبع بزن 
	 هر استفاده غیرقانونی از ربات به پای ران کننده ربات میباشد
	 amir rahmati 

"""

import os
import re
import json
import time
import shutil
import zipfile
import asyncio
import aiohttp
import aiofiles
import logging
import hashlib
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote, urldefrag, parse_qs
from collections import defaultdict
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
MAX_OMGH = 5
MAX_SAFHEH = 500
MAX_FAYL = 5000
MAX_ZIP_MB = 50
TIMEOUT = 30
CONCURRENT = 10
DL_DIR = "downloads"
MAX_REQ = 3
REQ_WINDOW = 60

ASSET_EXT = {
    ".css", ".js", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif",
    ".ico", ".bmp", ".tif", ".tiff",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav",
    ".json", ".xml", ".pdf", ".txt",
}

PAGE_EXT = {
    "", ".php", ".html", ".htm", ".asp", ".aspx",
    ".jsp", ".cfm", ".cgi", ".pl", ".shtml", ".phtml",
}

BLOCK_HOST = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"}

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

darkhast_count = defaultdict(list)


def url_amniyat(url):
    try:
        p = urlparse(url)
        host = p.hostname
        if not host or host in BLOCK_HOST:
            return False
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except Exception:
            pass
        return True
    except Exception:
        return False


def rate_limit(user_id):
    now = time.time()
    darkhast_count[user_id] = [t for t in darkhast_count[user_id] if t > now - REQ_WINDOW]
    if len(darkhast_count[user_id]) >= MAX_REQ:
        return False
    darkhast_count[user_id].append(now)
    return True


class SiteScraper:

    def __init__(self, aval_url, khorooji_dir):
        self.aval_url = aval_url.rstrip("/")
        p = urlparse(aval_url)
        self.origin = f"{p.scheme}://{p.netloc}"
        self.domain = p.netloc
        self.khorooji = Path(khorooji_dir)
        self.khorooji.mkdir(parents=True, exist_ok=True)
        self.safheh_ha = set()
        self.fayl_ha = set()
        self.lock_safheh = asyncio.Lock()
        self.lock_fayl = asyncio.Lock()
        self.session = None
        self.sem = asyncio.Semaphore(CONCURRENT)

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(ssl=True, limit=CONCURRENT, limit_per_host=10, enable_cleanup_closed=True)
        hedaer_ha = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        self.session = aiohttp.ClientSession(
            headers=hedaer_ha,
            timeout=aiohttp.ClientTimeout(total=TIMEOUT, connect=10),
            connector=connector
        )
        return self

    async def __aexit__(self, *_):
        if self.session:
            await self.session.close()

    def norm(self, url):
        url, _ = urldefrag(url)
        return url.rstrip("/") or "/"

    def hamin_domain(self, url):
        netloc = urlparse(url).netloc
        return netloc == self.domain or netloc.endswith("." + self.domain)

    def fayl_ast(self, url):
        ext = Path(urlparse(url).path).suffix.lower()
        if ext in PAGE_EXT:
            return False
        if ext in ASSET_EXT or ext:
            return True
        return False

    def url_be_path(self, url, ct=""):
        p = urlparse(url)
        raw = unquote(p.path)
        query = p.query

        if query:
            try:
                qs = parse_qs(query, keep_blank_values=True)
                qparts = []
                for k, v in list(qs.items())[:3]:
                    ks = re.sub(r"[^\w]", "", k)[:20]
                    vs = re.sub(r"[^\w]", "", v[0] if v else "")[:20]
                    qparts.append(f"{ks}_{vs}" if vs else ks)
                qsuffix = "_" + "_".join(qparts) if qparts else ""
                if not qsuffix or len(qsuffix) > 60:
                    qsuffix = "_" + hashlib.md5(query.encode()).hexdigest()[:8]
            except Exception:
                qsuffix = "_" + hashlib.md5(query.encode()).hexdigest()[:8]
        else:
            qsuffix = ""

        ghesmat_ha = [g for g in raw.split("/") if g]

        if not ghesmat_ha:
            return self.khorooji / f"index{qsuffix}.html"

        akharin = ghesmat_ha[-1]
        ext = Path(akharin).suffix.lower() if "." in akharin else ""

        if ext:
            base = self.khorooji / Path(*ghesmat_ha)
            if qsuffix:
                return base.with_name(f"{base.stem}{qsuffix}{base.suffix}")
            return base

        if "text/css" in ct:
            suffix = ".css"
        elif "javascript" in ct:
            suffix = ".js"
        elif "application/json" in ct:
            suffix = ".json"
        elif "xml" in ct:
            suffix = ".xml"
        elif raw.endswith("/"):
            return self.khorooji / Path(*ghesmat_ha) / f"index{qsuffix}.html"
        else:
            suffix = ".html"

        base = self.khorooji / Path(*ghesmat_ha)
        return base.with_name(f"{base.name}{qsuffix}{suffix}")

    def relative(self, az, be):
        try:
            return os.path.relpath(be, az.parent).replace("\\", "/")
        except ValueError:
            return str(be).replace("\\", "/")

    async def fetch(self, url, retry=3):
        async with self.sem:
            for dafe in range(retry):
                try:
                    async with self.session.get(url, allow_redirects=True, max_redirects=10) as r:
                        if r.status == 200:
                            return await r.read(), str(r.url), dict(r.headers)
                        if r.status == 429:
                            await asyncio.sleep(2 ** dafe)
                            continue
                        logger.warning(f"HTTP {r.status}: {url}")
                        return None, url, {}
                except aiohttp.ClientSSLError:
                    try:
                        conn = aiohttp.TCPConnector(ssl=False)
                        async with aiohttp.ClientSession(
                            headers=self.session._default_headers,
                            timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                            connector=conn
                        ) as fb:
                            async with fb.get(url, allow_redirects=True) as r:
                                if r.status == 200:
                                    return await r.read(), str(r.url), dict(r.headers)
                    except Exception as e:
                        logger.warning(f"SSL fallback [{url}]: {e}")
                    return None, url, {}
                except asyncio.TimeoutError:
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.warning(f"Fetch error [{url}] dafe {dafe+1}: {e}")
                    await asyncio.sleep(0.5)
        return None, url, {}

    async def zakhire(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

    def asset_ha_az_html(self, soup, safheh_url):
        list_asset = []

        def ezafe(raw):
            if not raw:
                return
            raw = raw.strip()
            if raw.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
                return
            abs_url = self.norm(urljoin(safheh_url, raw))
            if self.hamin_domain(abs_url):
                list_asset.append(abs_url)

        for tag, attr in [
            ("link", "href"), ("script", "src"), ("img", "src"),
            ("source", "src"), ("video", "src"), ("video", "poster"),
            ("audio", "src"), ("embed", "src"), ("object", "data"),
            ("input", "src"), ("track", "src"), ("use", "href"),
            ("image", "href"), ("image", "xlink:href"),
        ]:
            for el in soup.find_all(tag):
                val = el.get(attr, "")
                if val:
                    ezafe(val)

        for el in soup.find_all(attrs={"srcset": True}):
            for part in el["srcset"].split(","):
                tokens = part.strip().split()
                if tokens:
                    ezafe(tokens[0])

        for attr in ("data-src", "data-lazy", "data-original", "data-bg",
                     "data-background", "data-image", "data-img", "data-url",
                     "data-poster", "data-thumb"):
            for el in soup.find_all(attrs={attr: True}):
                ezafe(el[attr])

        for el in soup.find_all(style=True):
            for u in re.findall(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', el["style"]):
                ezafe(u)

        for el in soup.find_all("style"):
            mohtava = el.string or ""
            for u in re.findall(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', mohtava):
                ezafe(u)
            for u in re.findall(r'image-set\(([^)]+)\)', mohtava):
                for part in re.findall(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', u):
                    ezafe(part)

        for el in soup.find_all("script"):
            mohtava = el.string or ""
            if mohtava and not el.get("src"):
                list_asset.extend(self.ref_ha_az_js(mohtava, safheh_url))

        for el in soup.find_all("meta"):
            prop = el.get("property", "") or el.get("name", "")
            if "image" in prop.lower():
                mohtava = el.get("content", "")
                if mohtava:
                    ezafe(mohtava)

        for el in soup.find_all("link", rel=True):
            rel = " ".join(el.get("rel", []))
            if any(r in rel for r in ("preload", "prefetch", "modulepreload")):
                href = el.get("href", "")
                if href:
                    ezafe(href)

        return list(dict.fromkeys(list_asset))

    def link_ha_az_html(self, soup, safheh_url):
        list_link = []

        def ezafe(raw):
            raw = raw.strip()
            if not raw or raw.startswith(("mailto:", "tel:", "javascript:", "#")):
                return
            abs_url = self.norm(urljoin(safheh_url, raw))
            ext = Path(urlparse(abs_url).path).suffix.lower()
            if self.hamin_domain(abs_url) and ext in PAGE_EXT:
                list_link.append(abs_url)

        for a in soup.find_all("a", href=True):
            ezafe(a["href"])
        for el in soup.find_all("area", href=True):
            ezafe(el["href"])
        for el in soup.find_all(["frame", "iframe"], src=True):
            ezafe(el["src"])
        for el in soup.find_all("form", action=True):
            if el.get("method", "get").lower() == "get":
                ezafe(el["action"])
        for el in soup.find_all(attrs={"onclick": True}):
            for m in re.finditer(r'(?:location\.href|window\.location)\s*=\s*["\']([^"\']+)["\']', el["onclick"]):
                ezafe(m.group(1))

        return list(dict.fromkeys(list_link))

    def ref_ha_az_css(self, css_text, css_url):
        refs = []

        def ezafe(raw):
            raw = raw.strip().strip("\"'")
            if raw and not raw.startswith("data:"):
                abs_url = urljoin(css_url, raw)
                if self.hamin_domain(abs_url):
                    refs.append(abs_url)

        for m in re.finditer(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', css_text):
            ezafe(m.group(1))
        for m in re.finditer(r'@import\s+(?:url\(\s*)?["\']([^"\']+)["\']', css_text):
            ezafe(m.group(1))
        for m in re.finditer(r'image-set\(([^)]+)\)', css_text):
            for part in re.findall(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', m.group(1)):
                ezafe(part)

        return list(dict.fromkeys(refs))

    def ref_ha_az_js(self, js_text, js_url):
        refs = []
        exts = "|".join(e.lstrip(".") for e in ASSET_EXT)
        pattern = rf'["\']([^"\'<>\s]*\.(?:{exts})(?:\?[^"\']*)?)["\']'

        for m in re.finditer(pattern, js_text, re.IGNORECASE):
            raw = m.group(1)
            raw_path = raw.split("?")[0]
            if raw_path.startswith(("http://", "https://")):
                if self.hamin_domain(raw_path):
                    refs.append(self.norm(raw_path))
            elif raw_path.startswith("//"):
                full = "https:" + raw_path
                if self.hamin_domain(full):
                    refs.append(self.norm(full))
            elif raw_path.startswith("/"):
                refs.append(self.norm(urljoin(self.origin, raw)))
            elif raw_path and not raw_path.startswith(("data:", "blob:")):
                abs_url = urljoin(js_url, raw)
                if self.hamin_domain(abs_url):
                    refs.append(self.norm(abs_url))

        for m in re.finditer(r'import\s*\(\s*["\']([^"\']+)["\']', js_text):
            raw = m.group(1)
            if raw.startswith("/") and not raw.startswith("//"):
                abs_url = urljoin(self.origin, raw)
                if self.hamin_domain(abs_url):
                    refs.append(self.norm(abs_url))

        for m in re.finditer(r'(?:fetch|axios\.get|axios\.post)\s*\(\s*["\']([^"\']+)["\']', js_text):
            raw = m.group(1)
            if raw.startswith("/") and not raw.startswith("//"):
                abs_url = urljoin(self.origin, raw)
                if self.hamin_domain(abs_url):
                    refs.append(self.norm(abs_url))

        for m in re.finditer(
            r'(?:location\.href|window\.location|location\.assign|location\.replace)\s*[=(]\s*["\']([^"\']+)["\']',
            js_text
        ):
            raw = m.group(1).strip()
            if raw.startswith(("#", "javascript:")):
                continue
            abs_url = urljoin(js_url, raw)
            if self.hamin_domain(abs_url):
                refs.append(self.norm(abs_url))

        return list(dict.fromkeys(refs))

    def json_maqadir(self, obj, omgh=0):
        if omgh > 10:
            return []
        nataij = []
        if isinstance(obj, dict):
            for v in obj.values():
                nataij.extend(self.json_maqadir(v, omgh + 1))
        elif isinstance(obj, list):
            for item in obj:
                nataij.extend(self.json_maqadir(item, omgh + 1))
        elif isinstance(obj, str):
            nataij.append(obj)
        return nataij

    def baznevis_html(self, soup, safheh_url):
        safheh_fayl = self.url_be_path(safheh_url)

        def rw(raw):
            if not raw or raw.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
                return raw
            abs_url = urljoin(safheh_url, raw.strip())
            if not self.hamin_domain(abs_url):
                return raw
            return self.relative(safheh_fayl, self.url_be_path(abs_url))

        for tag, attr in [
            ("link", "href"), ("script", "src"), ("img", "src"),
            ("source", "src"), ("video", "src"), ("video", "poster"),
            ("audio", "src"), ("a", "href"), ("form", "action"),
            ("input", "src"), ("use", "href"), ("image", "href"),
        ]:
            for el in soup.find_all(tag):
                if el.get(attr):
                    el[attr] = rw(el[attr])

        for el in soup.find_all(attrs={"srcset": True}):
            parts = []
            for part in el["srcset"].split(","):
                tokens = part.strip().split()
                if tokens:
                    tokens[0] = rw(tokens[0])
                parts.append(" ".join(tokens))
            el["srcset"] = ", ".join(parts)

        for attr in ("data-src", "data-lazy", "data-original", "data-bg",
                     "data-background", "data-image", "data-img", "data-url",
                     "data-poster", "data-thumb"):
            for el in soup.find_all(attrs={attr: True}):
                el[attr] = rw(el[attr])

        for el in soup.find_all(style=True):
            def style_rw(m):
                raw = m.group(1).strip().strip("\"'")
                if raw.startswith("data:"):
                    return m.group(0)
                return f'url("{rw(raw)}")'
            el["style"] = re.sub(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', style_rw, el["style"])

        return str(soup)

    def baznevis_css(self, css_text, css_url):
        css_fayl = self.url_be_path(css_url)

        def url_rw(m):
            raw = m.group(1).strip().strip("\"'")
            if raw.startswith("data:"):
                return m.group(0)
            abs_url = urljoin(css_url, raw)
            if not self.hamin_domain(abs_url):
                return m.group(0)
            return f'url("{self.relative(css_fayl, self.url_be_path(abs_url))}")'

        def import_rw(m):
            raw = m.group(1)
            abs_url = urljoin(css_url, raw)
            if not self.hamin_domain(abs_url):
                return m.group(0)
            return f'@import "{self.relative(css_fayl, self.url_be_path(abs_url))}"'

        result = re.sub(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', url_rw, css_text)
        result = re.sub(r'@import\s+["\']([^"\']+)["\']', import_rw, result)
        return result

    async def dl_fayl(self, url):
        async with self.lock_fayl:
            if url in self.fayl_ha or len(self.fayl_ha) >= MAX_FAYL:
                return
            self.fayl_ha.add(url)

        data, _, headers = await self.fetch(url)
        if data is None:
            return

        ct = headers.get("content-type", "").lower()
        filepath = self.url_be_path(url, ct)
        ext = filepath.suffix.lower()

        if ext == ".css":
            try:
                text = data.decode("utf-8", errors="ignore")
                refs = self.ref_ha_az_css(text, url)
                await asyncio.gather(*[self.dl_fayl(r) for r in refs], return_exceptions=True)
                data = self.baznevis_css(text, url).encode("utf-8")
            except Exception as e:
                logger.warning(f"CSS error [{url}]: {e}")

        elif ext == ".js":
            try:
                text = data.decode("utf-8", errors="ignore")
                refs = self.ref_ha_az_js(text, url)
                await asyncio.gather(*[self.dl_fayl(r) for r in refs], return_exceptions=True)
            except Exception as e:
                logger.warning(f"JS error [{url}]: {e}")

        elif ext == ".json":
            try:
                obj = json.loads(data.decode("utf-8", errors="ignore"))
                refs = []
                for val in self.json_maqadir(obj):
                    val = val.strip()
                    if val.startswith("/") and not val.startswith("//"):
                        abs_url = urljoin(self.origin, val)
                        if self.hamin_domain(abs_url) and self.fayl_ast(abs_url):
                            refs.append(self.norm(abs_url))
                    elif val.startswith(("http://", "https://")):
                        if self.hamin_domain(val) and self.fayl_ast(val):
                            refs.append(self.norm(val))
                if refs:
                    await asyncio.gather(*[self.dl_fayl(r) for r in refs], return_exceptions=True)
            except Exception as e:
                logger.warning(f"JSON error [{url}]: {e}")

        await self.zakhire(filepath, data)

    async def crawl_safheh(self, url, omgh):
        async with self.lock_safheh:
            if url in self.safheh_ha or len(self.safheh_ha) >= MAX_SAFHEH:
                return
            self.safheh_ha.add(url)

        logger.info(f"[omgh={omgh}] {url}")

        data, _, headers = await self.fetch(url)
        if not data:
            return

        ct = headers.get("content-type", "").lower()
        ext = Path(urlparse(url).path).suffix.lower()
        is_html = "text/html" in ct or "application/xhtml" in ct or ext in PAGE_EXT

        if not is_html:
            await self.zakhire(self.url_be_path(url, ct), data)
            return

        try:
            html = data.decode("utf-8", errors="ignore")
        except Exception:
            return

        soup = BeautifulSoup(html, "html.parser")

        await asyncio.gather(*[self.dl_fayl(a) for a in self.asset_ha_az_html(soup, url)], return_exceptions=True)

        filepath = self.url_be_path(url, ct)
        await self.zakhire(filepath, self.baznevis_html(soup, url).encode("utf-8"))

        if omgh < MAX_OMGH:
            link_ha = self.link_ha_az_html(soup, url)
            logger.info(f"[omgh={omgh}] {len(link_ha)} link: {url}")
            await asyncio.gather(*[self.crawl_safheh(l, omgh + 1) for l in link_ha], return_exceptions=True)

    async def run(self):
        await self.crawl_safheh(self.aval_url, 0)
        return {"safheh": len(self.safheh_ha), "fayl": len(self.fayl_ha)}


def sakhte_zip(src, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src))
    return dest.stat().st_size / 1024 / 1024


def pak_kardan(*paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)


def validate_url(text):
    text = text.strip()
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    p = urlparse(text)
    if not p.netloc or not url_amniyat(text):
        return None
    return text


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! ربات دانلود سورس سایت\n\n"
        "لینک سایت رو بفرست:\n"
        "   https://example.com\n\n"
        f"حداکثر صفحات: {MAX_SAFHEH}\n"
        f"حداکثر فایل: {MAX_FAYL}\n"
        f"حداکثر ZIP: {MAX_ZIP_MB}MB\n\n"
        "/help برای راهنما"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "این ربات دانلود میکنه:\n\n"
        "تمام صفحات HTML، PHP، ASP و ...\n"
        "CSS، JS، تصاویر، فونت‌ها\n"
        "فایل‌های lazy load و srcset\n"
        "JSON manifest و asset ها\n"
        "لینک‌های ?page=x\n\n"
        "هر فایل با پسوند اصلی خودش ذخیره میشه\n"
        "مسیرها relative میشن (آفلاین کار میکنه)\n"
        "خروجی ZIP\n\n"
        "توجه: سایت‌های SPA ممکنه کامل نشن."
    )


async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not rate_limit(user_id):
        await update.message.reply_text(f"بیشتر از {MAX_REQ} درخواست در {REQ_WINDOW} ثانیه نمیشه.\nکمی صبر کن.")
        return

    url = validate_url(text)
    if not url:
        await update.message.reply_text("لینک معتبر نیست.\nمثال: https://example.com")
        return

    domain = urlparse(url).netloc
    safe_name = re.sub(r"[^\w\-]", "_", domain)
    out_dir = Path(DL_DIR) / f"{safe_name}_{user_id}"
    zip_path = Path(DL_DIR) / f"{safe_name}_{user_id}.zip"

    status = await update.message.reply_text(f"شروع دانلود...\n{url}")

    try:
        async with SiteScraper(url, str(out_dir)) as scraper:

            async def progress():
                while True:
                    await asyncio.sleep(5)
                    try:
                        await status.edit_text(
                            f"در حال دانلود...\n{url}\n\n"
                            f"صفحات: {len(scraper.safheh_ha)} / {MAX_SAFHEH}\n"
                            f"فایل‌ها: {len(scraper.fayl_ha)} / {MAX_FAYL}"
                        )
                    except Exception:
                        pass

            ptask = asyncio.create_task(progress())
            try:
                natije = await scraper.run()
            finally:
                ptask.cancel()

        if natije["safheh"] == 0:
            await status.edit_text("هیچ صفحه‌ای دانلود نشد!\nسایت در دسترس نیست یا بلاک کرده.")
            return

        await status.edit_text("در حال ساخت ZIP...")
        size_mb = sakhte_zip(out_dir, zip_path)

        if size_mb > MAX_ZIP_MB:
            await status.edit_text(f"ZIP خیلی بزرگه ({size_mb:.1f}MB)\nحد مجاز {MAX_ZIP_MB}MB هست.")
            return

        await status.edit_text("در حال ارسال...")
        with open(zip_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"{safe_name}_source.zip",
                caption=(
                    f"سورس سایت آماده!\n\n"
                    f"{url}\n"
                    f"صفحات: {natije['safheh']}\n"
                    f"فایل‌ها: {natije['fayl']}\n"
                    f"حجم: {size_mb:.2f}MB"
                )
            )
        await status.delete()

    except asyncio.TimeoutError:
        await status.edit_text("خطا: سایت پاسخ نمیده.")
    except aiohttp.ClientConnectorError:
        await status.edit_text("خطا: نمیتونم وصل بشم. آدرس رو چک کن.")
    except Exception as e:
        logger.error(f"Error user {user_id}: {type(e).__name__}", exc_info=True)
        await status.edit_text("یه خطا پیش اومد. دوباره امتحان کن.")
    finally:
        pak_kardan(out_dir, zip_path)


def main():
    Path(DL_DIR).mkdir(exist_ok=True)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    print("bot kare!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
