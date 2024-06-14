import os
from flask import Flask, request, send_file, redirect, url_for
from pytube import YouTube
from moviepy.editor import VideoFileClip

app = Flask(__name__)

# Ensure the directories exist
os.makedirs('downloads/mp3', exist_ok=True)
os.makedirs('downloads/mp4', exist_ok=True)

@app.route('/')
def index():
    return open('index.html').read()

@app.route('/convert', methods=['POST'])
def convert():
    url = request.form['url']
    fmt = request.form['format']
    
    yt = YouTube(url)
    video_title = yt.title
    sanitized_title = video_title.replace(" ", "_").replace("/", "_").replace("\\", "_")  # Sanitize the video title

    if fmt == 'mp4':
        video = yt.streams.filter(progressive=True, file_extension='mp4').first()
        file_path = f'downloads/mp4/{sanitized_title}.mp4'
        video.download(filename=file_path)
        return send_file(file_path, as_attachment=True, download_name=f'{sanitized_title}.mp4')

    elif fmt == 'mp3':
        video = yt.streams.filter(progressive=True, file_extension='mp4').first()
        temp_file_path = f'downloads/mp4/{sanitized_title}.mp4'
        video.download(filename=temp_file_path)
        
        audio_file_path = f'downloads/mp3/{sanitized_title}.mp3'
        video_clip = VideoFileClip(temp_file_path)
        audio_clip = video_clip.audio
        audio_clip.write_audiofile(audio_file_path)
        
        # Remove the temporary mp4 file after extracting audio
        os.remove(temp_file_path)

        return send_file(audio_file_path, as_attachment=True, download_name=f'{sanitized_title}.mp3')

    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
