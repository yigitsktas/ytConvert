import base64
import os
import re
import shutil
import tempfile
import threading
import time
from urllib.parse import quote, urlparse

from flask import Flask, request, send_file, Response, jsonify
import yt_dlp
from yt_dlp.utils import DownloadError

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Desteklenen platformlar: URL host'u bu listede değilse istek reddedilir.
PLATFORMS = {
    'youtube': ('youtube.com', 'youtu.be'),
    'twitter': ('twitter.com', 'x.com'),
    'instagram': ('instagram.com',),
}

# Instagram / X login isteyen içerikler için opsiyonel cookie desteği.
# 1) Proje klasörüne cookies.txt (Netscape formatı) koyarsan o kullanılır.
# 2) Yoksa COOKIES_BROWSER=chrome (veya safari, firefox...) ile tarayıcıdan okunur.
# YouTube'a bilerek cookie gönderilmiyor: hesabın işaretlenme riski var.
COOKIES_FILE = os.path.join(BASE_DIR, 'cookies.txt')
COOKIES_BROWSER = os.environ.get('COOKIES_BROWSER')

# Önizlemede çıkarılan bilgi 10 dk saklanır; İndir'e basınca YouTube/Instagram'a
# tekrar sorulmaz, indirme anında başlar (3-6 sn kazanç).
INFO_CACHE = {}
INFO_TTL = 600
# İndirme ilerlemesi: job_id → {phase, percent, speed, eta}
PROGRESS = {}
_lock = threading.Lock()
JOB_ID = re.compile(r'^[a-zA-Z0-9-]{8,64}$')


def cache_get(url):
    with _lock:
        item = INFO_CACHE.get(url)
        if item and time.time() - item[0] < INFO_TTL:
            return item[1]
        INFO_CACHE.pop(url, None)
    return None


def cache_put(url, info):
    with _lock:
        for k in [k for k, (t, _) in INFO_CACHE.items() if time.time() - t >= INFO_TTL]:
            del INFO_CACHE[k]
        INFO_CACHE[url] = (time.time(), info)


@app.before_request
def same_origin_only():
    # Sunucu localhost'ta çalışıyor; tarayıcıda açık başka bir sitenin
    # arka planda /convert'e istek atmasını engelle (CSRF).
    if request.method == 'POST':
        origin = request.headers.get('Origin')
        if origin and urlparse(origin).netloc != request.host:
            return Response('Yetkisiz istek.', 403)
    return None


def sanitize_filename(title):
    # Remove all non-ASCII alphanumeric characters and spaces
    clean_title = re.sub(r'[^a-zA-Z0-9\s-]', '', title)
    return clean_title.strip().replace(' ', '_')


def detect_platform(url):
    host = (urlparse(url).hostname or '').lower()
    for platform, domains in PLATFORMS.items():
        if any(host == d or host.endswith('.' + d) for d in domains):
            return platform
    return None


FORMATS = {'mp4': 'video/mp4', 'mp3': 'audio/mpeg', 'm4a': 'audio/mp4'}


def progress_hooks(job_id):
    if not job_id:
        return {}

    def on_download(d):
        info = d.get('info_dict') or {}
        is_audio = info.get('vcodec') == 'none'
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        PROGRESS[job_id] = {
            'phase': 'audio' if is_audio else 'video',
            'percent': round(d['downloaded_bytes'] / total * 100, 1) if total and d.get('downloaded_bytes') else None,
            'speed': d.get('speed'),
            'eta': d.get('eta'),
        }

    def on_postprocess(d):
        if d.get('status') == 'started':
            PROGRESS[job_id] = {'phase': 'processing'}

    return {'progress_hooks': [on_download], 'postprocessor_hooks': [on_postprocess]}


def build_options(fmt, platform, out_dir, quality=None, job_id=None):
    opts = {
        **progress_hooks(job_id),
        'outtmpl': os.path.join(out_dir, 'media.%(ext)s'),
        'noplaylist': True,          # YouTube linkinde &list= olsa bile tek video
        'playlist_items': '1',       # Instagram/X çoklu postlarda ilk video
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        # YouTube imza çözümü için JS runtime (Homebrew'daki node)
        'js_runtimes': {'node': {}},
    }

    if fmt in ('mp3', 'm4a'):
        opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': fmt,           # m4a: kaynak zaten AAC ise yeniden encode etmez
            'preferredquality': '192',
        }]
    else:
        # Seçilen çözünürlüğe kadar en iyisi (yoksa 1080p). 'res' kısa kenarı baz alır,
        # dikey videolarda (Shorts/Reels) da doğru çalışır. Aynı çözünürlükte H.264 + AAC tercih.
        res = int(quality) if quality and quality.isdigit() else 1080
        opts['format'] = 'bv*+ba/b'
        opts['format_sort'] = [f'res:{res}', 'vcodec:h264', 'acodec:aac', 'ext:mp4:m4a']
        opts['merge_output_format'] = 'mp4'

    if platform in ('instagram', 'twitter'):
        if os.path.exists(COOKIES_FILE):
            opts['cookiefile'] = COOKIES_FILE
        elif COOKIES_BROWSER:
            opts['cookiesfrombrowser'] = (COOKIES_BROWSER,)

    return opts


def friendly_error(platform, message):
    msg = message.lower()
    if platform == 'instagram' and any(k in msg for k in ('login', 'not available', 'rate', 'empty media', 'cookies')):
        return ('Instagram bu içerik için giriş istiyor. Proje klasörüne cookies.txt ekleyip '
                'tekrar dene.')
    if platform == 'twitter' and ('login' in msg or 'sensitive' in msg or 'protected' in msg):
        return 'X bu gönderi için giriş istiyor (hassas içerik ya da gizli hesap). cookies.txt ekle.'
    if 'audio codec' in msg:
        return 'Bu videoda ses kanalı yok, MP3 çıkarılamıyor. MP4 olarak indir.'
    if 'no video' in msg:
        return 'Bu gönderide video bulunamadı.'
    if 'sign in to confirm' in msg:
        return 'YouTube bot kontrolüne takıldı. Biraz bekleyip tekrar dene.'
    return f'İndirme başarısız: {message}'


def short_side(f):
    w, h = f.get('width'), f.get('height')
    return min(w, h) if w and h else h


def video_qualities(info):
    """Videoda gerçekten bulunan çözünürlükler + tahmini dosya boyutu."""
    formats = info.get('formats') or [info]
    size = lambda f: f.get('filesize') or f.get('filesize_approx') or 0
    audio = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') not in (None, 'none')]
    audio_size = max((size(f) for f in audio if f.get('ext') == 'm4a'), default=0) \
        or max((size(f) for f in audio), default=0)

    best = {}
    for f in formats:
        res = short_side(f)
        if not res or f.get('vcodec') in (None, 'none') or res > 2160:
            continue
        # Aynı çözünürlükte H.264 olan, yoksa en büyük boyutlu format (indirmede seçilenle uyumlu)
        rank = (str(f.get('vcodec', '')).startswith('avc1'), size(f))
        if res not in best or rank > best[res][0]:
            has_audio = f.get('acodec') not in (None, 'none')
            best[res] = (rank, size(f) + (0 if has_audio else audio_size) if size(f) else 0)

    return [{'value': str(r), 'label': f'{r}p', 'size': best[r][1] or None}
            for r in sorted(best, reverse=True)][:6]


def thumbnail_data(ydl, info):
    """Kapak görselini sunucu üzerinden data URI olarak döndür (Instagram CDN hotlink'e izin vermiyor)."""
    url = info.get('thumbnail')
    if not url:
        return None
    try:
        with ydl.urlopen(url) as r:
            data = r.read(3_000_001)
            ctype = r.headers.get('Content-Type', 'image/jpeg').split(';')[0]
        if len(data) > 3_000_000 or not ctype.startswith('image/'):
            return None
        return f'data:{ctype};base64,{base64.b64encode(data).decode()}'
    except Exception:
        return None


def normalize_url(raw):
    url = (raw or '').strip()
    if url and not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


@app.route('/info', methods=['POST'])
def info():
    url = normalize_url(request.form.get('url'))
    platform = detect_platform(url)
    if not platform:
        return 'Sadece YouTube, X (Twitter) ve Instagram linkleri destekleniyor.', 400

    try:
        with yt_dlp.YoutubeDL(build_options('mp4', platform, tempfile.gettempdir())) as ydl:
            data = ydl.extract_info(url, download=False)
            if data.get('_type') == 'playlist':  # Instagram/X çoklu gönderi → ilk video
                entries = [e for e in (data.get('entries') or []) if e]
                if not entries:
                    raise DownloadError('No video could be found in this post')
                data = entries[0]
            thumb = thumbnail_data(ydl, data)
            cache_put(url, ydl.sanitize_info(data))
    except DownloadError as e:
        print(f"Info error ({platform}): {e}")
        return Response(friendly_error(platform, str(e)), status=422)

    formats = data.get('formats') or []
    has_audio = any(f.get('acodec') not in (None, 'none') for f in formats) or not formats
    return jsonify({
        'platform': platform,
        'title': data.get('title') or data.get('description') or 'Başlıksız',
        'uploader': data.get('uploader') or data.get('channel') or data.get('uploader_id'),
        'duration': data.get('duration'),
        'thumbnail': thumb,
        'video': video_qualities(data) or [{'value': 'best', 'label': 'En iyi', 'size': None}],
        'audio': has_audio,
    })


@app.route('/')
def index():
    with open(os.path.join(BASE_DIR, 'index.html'), encoding='utf-8') as f:
        return f.read()


@app.route('/convert', methods=['POST'])
def convert():
    url = normalize_url(request.form.get('url'))
    fmt = request.form.get('format', 'mp4')
    quality = request.form.get('quality')
    job_id = request.form.get('job')
    job_id = job_id if job_id and JOB_ID.match(job_id) else None

    if fmt not in FORMATS:
        return 'Geçersiz format.', 400

    platform = detect_platform(url)
    if not platform:
        return 'Sadece YouTube, X (Twitter) ve Instagram linkleri destekleniyor.', 400

    out_dir = tempfile.mkdtemp(prefix='ytconvert-')
    try:
        # YouTube bazı stream linklerini rastgele 403 ile reddediyor; taze bilgiyle tekrar dene
        for attempt in range(3):
            if job_id:
                PROGRESS[job_id] = {'phase': 'starting'}
            try:
                with yt_dlp.YoutubeDL(build_options(fmt, platform, out_dir, quality, job_id)) as ydl:
                    cached = cache_get(url) if attempt == 0 else None
                    if cached:
                        # Önizlemedeki bilgiyle direkt indir (yt-dlp --load-info-json ile aynı yol)
                        info = ydl.process_ie_result(ydl.sanitize_info(cached), download=True)
                    else:
                        info = ydl.extract_info(url, download=True)
                break
            except DownloadError as e:
                if 'HTTP Error 403' not in str(e) or attempt == 2:
                    raise
                print(f"403, tekrar deneniyor ({attempt + 1}/2): {url}")
                with _lock:
                    INFO_CACHE.pop(url, None)
                shutil.rmtree(out_dir, ignore_errors=True)
                os.makedirs(out_dir)

        files = [f for f in os.listdir(out_dir) if f.endswith('.' + fmt)]
        if not files:
            raise DownloadError('No video could be found in this post')
        file_path = os.path.join(out_dir, files[0])

        title = info.get('title') or info.get('id') or 'download'
        download_name = f"{sanitize_filename(title)[:80] or 'download'}.{fmt}"

        # Dosyayı açıp geçici klasörü hemen sil: açık dosya gönderim bitene kadar
        # okunabilir kalır, diskte de hiçbir şey birikmez.
        media = open(file_path, 'rb')
        shutil.rmtree(out_dir, ignore_errors=True)
        response = send_file(media, as_attachment=True, download_name=download_name,
                             mimetype=FORMATS[fmt])
        response.headers['X-Filename'] = quote(download_name)
        return response

    except DownloadError as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        print(f"Download error ({platform}): {e}")
        return Response(friendly_error(platform, str(e)), status=422)
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        print(f"Error during conversion: {e}")
        return Response(f'Beklenmeyen hata: {e}', status=500)
    finally:
        if job_id:
            PROGRESS.pop(job_id, None)


@app.route('/progress/<job_id>')
def progress(job_id):
    return jsonify(PROGRESS.get(job_id) or {})


if __name__ == '__main__':
    # Sadece localhost'ta dinler (masaüstü uygulaması buna bağlanır)
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5001)), threaded=True)
