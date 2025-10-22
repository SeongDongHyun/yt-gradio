import argparse
import csv
import os
import re
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional

from yt_dlp import YoutubeDL
from pydub import AudioSegment
from tqdm import tqdm

# ===== 고정 파라미터 =====
TARGET_SR = 48000
TARGET_CHANNELS = 1
DEFAULT_OUT_DIR = Path("/home/infidea/tts-data/podcast_data")

# ---------- 유틸 ----------
def _safe_title(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:200] or "audio"

# ---------- YouTube → WAV(48k/mono) ----------
def ytdlp_to_wav(
    url: str,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    final_path: Optional[str | Path] = None,
) -> Tuple[str, str, float]:
    """YouTube → 로컬폴더 WAV(48kHz/mono). return: (wav_path, title, duration_sec)"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # yt-dlp가 임시로 생성할 작업용 디렉터리 (충돌 최소화)
    tmpdir = Path(tempfile.mkdtemp(prefix="ytwav_"))
    outtmpl = str(tmpdir / "%(title).200B.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noprogress": True,
        "quiet": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav"},
            {"key": "FFmpegMetadata"},
        ],
        "postprocessor_args": ["-ar", str(TARGET_SR), "-ac", str(TARGET_CHANNELS)],
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = _safe_title(info.get("title", ""))
        upload_date = info.get("upload_date")  # YYYYMMDD
        if not upload_date:
            upload_date = "unknown"

    wavs = list(tmpdir.glob("*.wav"))
    if not wavs:
        raise FileNotFoundError("임시 폴더에 wav가 생성되지 않았습니다.")
    src_wav = max(wavs, key=lambda p: p.stat().st_mtime)

    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    # 리샘플/모노 강제 및 저장
    seg = AudioSegment.from_file(src_wav).set_frame_rate(TARGET_SR).set_channels(TARGET_CHANNELS)
    seg.export(final_path, format="wav")
    dur = len(seg) / 1000.0

    return str(final_path), title, dur

# ---------- 배치 처리 ----------
def load_urls(txt_path: Path) -> List[str]:
    urls: List[str] = []
    with txt_path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            urls.append(s)
    # 중복 제거(입력 순서 유지)
    seen = set()
    deduped = []
    for u in urls:
        if u not in seen:
            deduped.append(u)
            seen.add(u)
    return deduped

def process_batch(
    txt_file: str,
    output_dir: str | Path = DEFAULT_OUT_DIR,
    log_csv: Optional[str] = "batch_result.csv",
) -> Tuple[int, int]:
    """
    txt 파일의 링크들을 순차 처리하여 son_economy_[date].wav 형태로 저장.
    로그 CSV 헤더: index,url,status,output_path,error
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    txt_path = Path(txt_file)
    if not txt_path.exists():
        raise FileNotFoundError(f"링크 파일을 찾을 수 없습니다: {txt_file}")

    urls = load_urls(txt_path)
    total = len(urls)
    success, fail = 0, 0

    csv_path = Path(log_csv) if log_csv else None
    writer = None
    f = None
    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        f = csv_path.open("w", newline="", encoding="utf-8")
        writer = csv.writer(f)
        writer.writerow(["index", "url", "status", "output_path", "error"])

    with tqdm(total=total, desc="Batch", unit="file") as pbar:
        for i, url in enumerate(urls, 1):
            pbar.set_postfix_str(f"{i}/{total}")
            print(f"[{i}/{total}] 처리 중: {url}")
            try:
                prefix = "youtube_audio"
                final_path = Path(output_dir) / f"{prefix}_{i:04d}.wav"

                final_path_str, title, duration_sec = ytdlp_to_wav(
                    url,
                    out_dir=output_dir,
                    final_path=final_path,
                )
                final_path = Path(final_path_str)

                success += 1
                print(f"  → 완료: {final_path}")
                if writer:
                    writer.writerow([i, url, "OK", str(final_path), ""])
            except Exception as e:
                fail += 1
                print(f"  × 실패: {e}")
                if writer:
                    writer.writerow([i, url, "FAIL", "", str(e)])
            finally:
                pbar.update(1)

    if f:
        f.close()

    print(f"\n요약: 총 {total}개 | 성공 {success} | 실패 {fail}")
    if csv_path:
        print(f"로그 저장: {csv_path.resolve()}")
    return success, fail

def main():
    parser = argparse.ArgumentParser(description="YouTube 링크 일괄 오디오 추출기 (WAV 48kHz/mono, son_economy_[date].wav)")
    parser.add_argument("--urls", required=True, help="유튜브 링크가 한 줄에 하나씩 들어있는 txt 파일 경로")
    parser.add_argument("--outdir", default=str(DEFAULT_OUT_DIR), help="출력 폴더")
    parser.add_argument("--log", default="batch_result.csv", help="CSV 로그 파일 경로(비활성화하려면 빈 문자열)")
    args = parser.parse_args()

    log_csv = args.log if args.log.strip() else None
    process_batch(
        args.urls,
        output_dir=args.outdir,
        log_csv=log_csv,
    )

if __name__ == "__main__":
    main()
