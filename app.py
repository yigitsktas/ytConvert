import os
import re
import shutil
import tempfile
from urllib.parse import quote, urlparse

from flask import Flask, request, send_file, Response
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


def build_options(fmt, platform, out_dir):
    opts = {
        'outtmpl': os.path.join(out_dir, 'media.%(ext)s'),
        'noplaylist': True,          # YouTube linkinde &list= olsa bile tek video
        'playlist_items': '1',       # Instagram/X çoklu postlarda ilk video
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        # YouTube imza çözümü için JS runtime (Homebrew'daki node)
        'js_runtimes': {'node': {}},
    }

    if fmt == 'mp3':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        # En fazla 1080p, iPhone/QuickTime uyumu için H.264 + AAC tercih edilir
        opts['format'] = 'bv*+ba/b'
        opts['format_sort'] = ['res:1080', 'vcodec:h264', 'acodec:aac', 'ext:mp4:m4a']
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


@app.route('/')
def index():
    with open(os.path.join(BASE_DIR, 'index.html'), encoding='utf-8') as f:
        return f.read()


@app.route('/convert', methods=['POST'])
def convert():
    url = request.form.get('url', '').strip()
    fmt = request.form.get('format', 'mp4')

    if fmt not in ('mp3', 'mp4'):
        return 'Geçersiz format.', 400
    if url and not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    platform = detect_platform(url)
    if not platform:
        return 'Sadece YouTube, X (Twitter) ve Instagram linkleri destekleniyor.', 400

    out_dir = tempfile.mkdtemp(prefix='ytconvert-')
    try:
        with yt_dlp.YoutubeDL(build_options(fmt, platform, out_dir)) as ydl:
            info = ydl.extract_info(url, download=True)

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
                             mimetype='audio/mpeg' if fmt == 'mp3' else 'video/mp4')
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


if __name__ == '__main__':
    # Sadece localhost'ta dinler (masaüstü uygulaması buna bağlanır)
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5001)), threaded=True)
