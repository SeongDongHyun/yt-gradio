import tempfile, time
from pathlib import Path
from typing import Optional, Tuple

import gradio as gr
from yt_dlp import YoutubeDL
from pydub import AudioSegment

# 고정 포맷
TARGET_SR = 44100
TARGET_CHANNELS = 1
TARGET_BITRATE = "192k"

def _safe_title(t: str) -> str:
    return "".join(c for c in (t or "") if c not in '\\/:*?"<>|').strip() or f"audio_{int(time.time())}"

def ytdlp_to_mp3(url: str) -> Tuple[str, str, float]:
    """YouTube → MP3(44.1kHz/mono). return: (mp3_path, title, duration_sec)"""
    if not url or not url.strip():
        raise gr.Error("유효한 YouTube 링크를 입력하세요.")
    tmpdir = Path(tempfile.mkdtemp(prefix="ytmp3_"))
    outtmpl = str(tmpdir / "%(title).200B.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noprogress": True,
        "quiet": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            {"key": "FFmpegMetadata"},
        ],
        "postprocessor_args": ["-ar", str(TARGET_SR), "-ac", str(TARGET_CHANNELS)],
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = _safe_title(info.get("title", ""))

    mp3s = list(Path(tmpdir).glob("*.mp3"))
    if not mp3s:
        raise gr.Error("MP3 파일 생성에 실패했습니다.")
    mp3_path = max(mp3s, key=lambda p: p.stat().st_mtime)
    final = mp3_path.parent / f"{title}.mp3"
    try:
        mp3_path.rename(final)
        mp3_path = final
    except Exception:
        pass

    seg = AudioSegment.from_file(mp3_path).set_frame_rate(TARGET_SR).set_channels(TARGET_CHANNELS)
    dur = len(seg) / 1000.0
    return str(mp3_path), title, dur

def trim_export(in_path: str, start_s: float, end_s: Optional[float], name: Optional[str]) -> str:
    """구간 자르기 후 MP3(44.1kHz/mono)로 저장하고 파일 경로 반환."""
    p = Path(in_path)
    if not in_path or not p.exists():
        raise gr.Error("자를 원본 MP3를 찾을 수 없습니다.")
    audio = AudioSegment.from_file(in_path).set_frame_rate(TARGET_SR).set_channels(TARGET_CHANNELS)
    dur_ms = len(audio)
    s = max(0, int((start_s or 0) * 1000))
    e = int((end_s if end_s not in (None, "") else dur_ms / 1000) * 1000)
    e = max(s, min(e, dur_ms))

    clip = audio[s:e]
    out_dir = Path(tempfile.mkdtemp(prefix="ytmp3_clip_"))
    base = (name or Path(in_path).stem + "_clip").strip()
    out = out_dir / f"{base}.mp3"
    clip.export(str(out), format="mp3", bitrate=TARGET_BITRATE,
                parameters=["-ar", str(TARGET_SR), "-ac", str(TARGET_CHANNELS)])
    return str(out)

with gr.Blocks(title="YouTube → MP3 (44.1kHz/mono) + 자르기 & 다운로드") as demo:
    gr.Markdown(
        "### YouTube 오디오 추출 & 자르기\n"
        "- 링크에서 **오디오만** 추출해 **MP3(44.1 kHz, mono)** 로 변환\n"
        "- **미리듣기 보면서 시작/끝(초)만 지정 → 자르기 & 다운로드** 한 번에\n"
        "- 저작권과 각 플랫폼 약관을 준수하세요."
    )

    with gr.Row():
        url = gr.Textbox(label="YouTube 링크", placeholder="https://www.youtube.com/watch?v=...")
        btn_download = gr.Button("오디오 추출", variant="primary")

    with gr.Row():
        title_box = gr.Textbox(label="제목", interactive=False)
        src_file = gr.File(label="원본 MP3", file_count="single")

    # 원본 미리듣기
    audio_view = gr.Audio(label="미리듣기(원본)", type="filepath")

    with gr.Row():
        start_s = gr.Number(label="시작(초)", value=0.0, precision=3)
        end_s = gr.Number(label="끝(초, 비우면 전체 길이)", value=None, precision=3)
        out_name = gr.Textbox(label="파일명(확장자 제외, 선택)", placeholder="my_clip")

    # 자르기 + 다운로드
    btn_trim = gr.Button("자르기 & 다운로드", variant="primary")

    # 결과 섹션: 미리듣기(클립) + 다운로드 버튼을 같은 줄에 배치
    with gr.Row():
        clip_preview = gr.Audio(label="미리듣기(클립)", type="filepath")
        dl_btn = gr.DownloadButton(label="클립 다운로드", visible=False)

    # (옵션) 잘라낸 파일 자체도 파일 컴포넌트로 제공하고 싶으면 아래 주석 해제
    # clip_file = gr.File(label="잘라낸 MP3", file_count="single")

    # 1) 오디오 추출
    def on_download(u: str):
        p, t, d = ytdlp_to_mp3(u)
        # 끝 시간을 전체 길이로 기본 설정
        return t, p, p, gr.update(value=0.0), gr.update(value=round(d, 3))

    btn_download.click(
        on_download,
        inputs=url,
        outputs=[title_box, src_file, audio_view, start_s, end_s],
    )

    # 2) 자르기 & 다운로드 한 번에 (미리듣기 포함)
    def on_trim(in_file, s, e, name):
        if not in_file:
            raise gr.Error("먼저 오디오를 불러오세요.")
        out = trim_export(in_file, float(s or 0), (float(e) if e not in (None, "") else None), name)
        # 미리듣기(클립)에는 파일 경로를 그대로 넣고,
        # 다운로드 버튼에도 같은 파일을 연결(일부 Gradio 버전에선 bytes만 지원될 수 있음)
        return out, gr.update(value=out, visible=True)

    btn_trim.click(
        on_trim,
        inputs=[audio_view, start_s, end_s, out_name],
        outputs=[clip_preview, dl_btn],
    )

if __name__ == "__main__":
    demo.launch(share=True)
