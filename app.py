import streamlit as st
import os
import tempfile
import subprocess
import srt
from datetime import timedelta

st.set_page_config(page_title="Video Subtitle Generator AI", layout="wide", page_icon="🎬")

st.title("🎬 Video Subtitle Generator App")
st.caption("Unggah video/audio dan dapatkan file subtitle (.srt) dengan timestamp presisi & transkrip akurat!")

# Sidebar Config
st.sidebar.header("🔑 API Configurations")

default_groq = st.secrets.get("GROQ_API_KEY", "")
groq_api_key = st.sidebar.text_input("Groq API Key", value=default_groq, type="password", help="Dapatkan gratis di console.groq.com")

uploaded_file = st.file_uploader(
    "Pilih file video atau audio (.mp4, .mov, .avi, .mkv, .mp3, .m4a, .wav)", 
    type=["mp4", "mov", "avi", "mkv", "mp3", "m4a", "wav"]
)

def get_video_duration(video_path):
    """Mendapatkan durasi media (dalam detik) menggunakan ffprobe"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def extract_full_audio(video_path, output_audio_path):
    """Ekstraksi seluruh audio ke MP3 Mono 96k (Kualitas Vokal Optimal & Ukuran Efisien)"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ab", "96k",
        "-ac", "1",
        "-ar", "16000",
        output_audio_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def extract_audio_chunk(video_path, output_audio_path, start_sec, duration_sec):
    """Memotong audio untuk file sangat besar dengan FFmpeg CLI"""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", video_path,
        "-t", str(duration_sec),
        "-vn",
        "-acodec", "libmp3lame",
        "-ab", "96k",
        "-ac", "1",
        "-ar", "16000",
        output_audio_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def transcribe_audio_file(client_groq, audio_file_path):
    """Mentranskripsi file audio via Groq Whisper API dengan penanganan akurasi penuh"""
    with open(audio_file_path, "rb") as audio_file:
        transcription = client_groq.audio.transcriptions.create(
            file=(audio_file_path, audio_file.read()),
            model="whisper-large-v3",
            response_format="verbose_json",
            temperature=0.0,
            prompt="Transkripsikan seluruh percakapan ucapan manusia ini secara lengkap, kata demi kata, akurat, dan sesuai dengan bahasa aslinya tanpa melewatkan kalimat apa pun."
        )
    
    if hasattr(transcription, "segments"):
        raw_segments = transcription.segments
    elif isinstance(transcription, dict):
        raw_segments = transcription.get("segments", [])
    else:
        raw_segments = getattr(transcription, "segments", [])

    segments_dict_list = []
    for s in raw_segments:
        start = getattr(s, "start", s.get("start", 0.0) if isinstance(s, dict) else 0.0)
        end = getattr(s, "end", s.get("end", 0.0) if isinstance(s, dict) else 0.0)
        text = getattr(s, "text", s.get("text", "") if isinstance(s, dict) else "").strip()

        # Ambil semua segmen yang memiliki teks asli tanpa potongan berlebih
        if text:
            segments_dict_list.append({
                "start": start,
                "end": end,
                "text": text
            })
            
    return segments_dict_list

def process_video_transcription(video_path):
    from groq import Groq
    client_groq = Groq(api_key=groq_api_key)

    st.info("🎵 1/2: Mengekstrak trek audio dari media...")
    
    # Simpan audio hasil konversi
    full_audio_path = video_path + "_extracted.mp3"
    extract_full_audio(video_path, full_audio_path)
    
    audio_size_mb = os.path.getsize(full_audio_path) / (1024 * 1024)
    all_segments = []

    st.info("🎙️ 2/2: Mentranskripsi suara ke teks (Speech-to-Text)...")

    # Jika ukuran file audio < 24 MB (Limit Groq 25 MB), proses langsung seluruhnya tanpa dipotong!
    if audio_size_mb < 24.0:
        st.text("Memproses audio utuh sekaligus untuk menjaga akurasi & presisi timestamp...")
        all_segments = transcribe_audio_file(client_groq, full_audio_path)
    else:
        # Jika > 24 MB, lakukan chunking per 15 menit
        duration_seconds = get_video_duration(video_path)
        chunk_duration = 900  # 15 menit
        st.warning(f"File audio besar ({audio_size_mb:.1f} MB). Memproses dalam beberapa bagian...")
        
        start_time = 0.0
        chunk_idx = 1
        
        while start_time < duration_seconds:
            current_duration = min(chunk_duration, duration_seconds - start_time)
            st.text(f"--- Memproses bagian {chunk_idx} ({start_time/60:.1f} m - {(start_time+current_duration)/60:.1f} m) ---")
            
            chunk_audio_path = f"{video_path}_chunk_{chunk_idx}.mp3"
            extract_audio_chunk(video_path, chunk_audio_path, start_time, current_duration)
            
            segments = transcribe_audio_file(client_groq, chunk_audio_path)
            
            for seg in segments:
                all_segments.append({
                    "start": seg["start"] + start_time,
                    "end": seg["end"] + start_time,
                    "text": seg["text"]
                })
                
            if os.path.exists(chunk_audio_path):
                os.remove(chunk_audio_path)
                
            start_time += chunk_duration
            chunk_idx += 1

    if os.path.exists(full_audio_path):
        os.remove(full_audio_path)

    # Buat File SRT Subtitle
    srt_subtitles = []
    for i, seg in enumerate(all_segments):
        start_td = timedelta(seconds=seg["start"])
        end_td = timedelta(seconds=seg["end"])
        text = seg["text"].strip()
        
        srt_subtitles.append(
            srt.Subtitle(index=i+1, start=start_td, end=end_td, content=text)
        )
    
    srt_output = srt.compose(srt_subtitles)

    return srt_output, all_segments

if uploaded_file is not None:
    original_filename = os.path.splitext(uploaded_file.name)[0]
    srt_filename = f"{original_filename}.srt"

    file_size_mb = uploaded_file.size / (1024 * 1024)
    st.success(f"📁 File **{uploaded_file.name}** ({file_size_mb:.1f} MB) berhasil diunggah!")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
        tmp_file.write(uploaded_file.read())
        temp_video_path = tmp_file.name

    if st.button("🚀 Buat Subtitle Video", type="primary"):
        if not groq_api_key:
            st.error("Silakan masukkan Groq API Key terlebih dahulu di sidebar!")
        else:
            with st.spinner("Sedang mentranskripsi percakapan... Harap tunggu sebentar."):
                try:
                    srt_content, original_segments = process_video_transcription(temp_video_path)
                    st.success("✅ Proses Transkripsi Selesai!")

                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("📥 Download Subtitle (.srt)")
                        st.download_button(
                            label=f"Download {srt_filename}",
                            data=srt_content,
                            file_name=srt_filename,
                            mime="text/plain"
                        )
                    
                    with col2:
                        st.subheader("📜 Hasil Transkrip Percakapan")
                        for seg in original_segments:
                            text_content = seg["text"].strip()
                            st.markdown(f"**[{seg['start']:.1f}s - {seg['end']:.1f}s]**")
                            st.markdown(f"🗣️ {text_content}")
                            st.divider()

                except Exception as e:
                    st.error(f"Terjadi kesalahan: {str(e)}")
            
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
