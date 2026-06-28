"""
voice_clone.py — seed-vc v1 voice conversion for basaytts Space.

Pipeline:
  espeak WAV (機械人聲)  +  ref WAV (使用者音色)
      → seed-vc v1 DiT inference
      → loudnorm 正規化
      → 輸出 WAV

模型來源（HF Hub，首次啟動自動下載）：
  Plachta/Seed-VC          DiT checkpoint + config
  nvidia/bigvgan_v2_22khz_80band_256x  vocoder
  funasr/campplus          speaker encoder
  openai/whisper-small     content encoder
  合計約 4.7 GB — 建議在 Space settings 設定：
    HF_HOME = /data/.hf_cache  （需 persistent storage）

seed-vc 原始碼在啟動時從 GitHub 自動 clone 到 /tmp/seed-vc。
"""

from __future__ import annotations
import os
import sys
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

# ── seed-vc source setup ─────────────────────────────────────────────────────
SEEDVC_REPO = os.environ.get("SEEDVC_REPO", "https://github.com/Plachtaa/seed-vc.git")
SEEDVC_DIR  = Path(tempfile.gettempdir()) / "seed-vc"
_CLONE_LOCK = threading.Lock()
_CLONE_DONE = False


def _patch_bigvgan() -> None:
    """Make proxies / resume_download optional in BigVGAN._from_pretrained().

    huggingface_hub ≥ ~0.30 dropped these arguments from the _from_pretrained()
    call chain, but bigvgan.py still declares them as required keyword-only args.
    We patch in-place (idempotent) so the loaded module matches the Hub API.
    """
    bigvgan_path = SEEDVC_DIR / "modules" / "bigvgan" / "bigvgan.py"
    if not bigvgan_path.exists():
        return
    src = bigvgan_path.read_text(encoding="utf-8")
    patched = src
    patched = patched.replace(
        "proxies: Optional[Dict],",
        "proxies: Optional[Dict] = None,",
    )
    patched = patched.replace(
        "resume_download: bool,",
        "resume_download: bool = False,",
    )
    if patched != src:
        bigvgan_path.write_text(patched, encoding="utf-8")
        print("[voice_clone] patched bigvgan.py (proxies/resume_download defaults)", flush=True)


def _patch_hf_utils() -> None:
    """Redirect hf_utils.py cache_dir from hardcoded './checkpoints' to
    the HF Hub default cache (honours HF_HOME / HF_HUB_CACHE env vars).

    Without this, models are always written to <cwd>/checkpoints/ which is
    ephemeral on HF Spaces and causes a full re-download on every restart.
    With HF_HOME=/data/.hf_cache (persistent storage), models survive restarts.
    """
    hf_utils_path = SEEDVC_DIR / "hf_utils.py"
    if not hf_utils_path.exists():
        return
    src = hf_utils_path.read_text(encoding="utf-8")
    # Replace hardcoded cache_dir with environment-aware default
    patched = src.replace(
        'os.makedirs("./checkpoints", exist_ok=True)\n'
        '    model_path = hf_hub_download(repo_id=repo_id, filename=model_filename, cache_dir="./checkpoints")',
        'cache_dir = os.environ.get("HF_HUB_CACHE", None)\n'
        '    model_path = hf_hub_download(repo_id=repo_id, filename=model_filename, cache_dir=cache_dir)',
    ).replace(
        'config_path = hf_hub_download(repo_id=repo_id, filename=config_filename, cache_dir="./checkpoints")',
        'config_path = hf_hub_download(repo_id=repo_id, filename=config_filename, cache_dir=cache_dir)',
    )
    if patched != src:
        hf_utils_path.write_text(patched, encoding="utf-8")
        print("[voice_clone] patched hf_utils.py (cache_dir → HF_HUB_CACHE)", flush=True)


def _ensure_seedvc_cloned() -> None:
    """Clone seed-vc to /tmp (once per process, blocking)."""
    global _CLONE_DONE
    if _CLONE_DONE:
        return
    with _CLONE_LOCK:
        if _CLONE_DONE:
            return
        if not (SEEDVC_DIR / "modules").is_dir():
            print("[voice_clone] cloning seed-vc …", flush=True)
            subprocess.run(
                ["git", "clone", "--depth=1", SEEDVC_REPO, str(SEEDVC_DIR)],
                check=True, timeout=180,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            print("[voice_clone] seed-vc ready.", flush=True)
        # ── patch bigvgan.py: make proxies/resume_download optional ──────────
        # huggingface_hub ≥ 0.30 no longer passes these to _from_pretrained(),
        # but bigvgan.py declares them as required kwargs → TypeError at load.
        _patch_bigvgan()
        _patch_hf_utils()

        if str(SEEDVC_DIR) not in sys.path:
            sys.path.insert(0, str(SEEDVC_DIR))
        # Point HF cache to /data if persistent storage is available
        if Path("/data").is_dir():
            os.environ.setdefault("HF_HOME", "/data/.hf_cache")
            os.environ.setdefault("HF_HUB_CACHE", "/data/.hf_cache/hub")
        _CLONE_DONE = True


# Kick off the clone in background so it finishes before first user request
threading.Thread(target=_ensure_seedvc_cloned, daemon=True).start()

# ── constants ─────────────────────────────────────────────────────────────────
MAX_CLONE_CHARS  = int(os.environ.get("BASAY_MAX_CLONE_CHARS", "100"))
LOUDNORM_FILTER  = "loudnorm=I=-20:TP=-6.0:LRA=11:linear=true"
_DATA_VOICES     = Path("/data/voices") if Path("/data").is_dir() else None

# ── lazy model state ──────────────────────────────────────────────────────────
_MODELS: dict | None = None
_MODEL_LOCK = threading.Lock()


def _get_device():
    import torch
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _ensure_models() -> dict:
    """Load all seed-vc v1 models (once per process)."""
    global _MODELS
    if _MODELS is not None:
        return _MODELS
    with _MODEL_LOCK:
        if _MODELS is not None:
            return _MODELS
        _ensure_seedvc_cloned()

        import torch
        import yaml
        from transformers import AutoFeatureExtractor, WhisperModel
        from modules.commons import build_model, load_checkpoint, recursive_munch
        from hf_utils import load_custom_model_from_hf
        from modules.campplus.DTDNN import CAMPPlus
        from modules.bigvgan import bigvgan as bigvgan_module
        from modules.audio import mel_spectrogram

        device = _get_device()
        print(f"[voice_clone] loading models on {device} …", flush=True)

        # ── DiT model ────────────────────────────────────────────────────────
        ckpt_path, cfg_path = load_custom_model_from_hf(
            "Plachta/Seed-VC",
            "DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth",
            "config_dit_mel_seed_uvit_whisper_small_wavenet.yml",
        )
        cfg = yaml.safe_load(open(cfg_path))
        mp  = recursive_munch(cfg["model_params"])
        mp.dit_type = "DiT"
        sr  = cfg["preprocess_params"]["sr"]            # 22050
        hop = cfg["preprocess_params"]["spect_params"]["hop_length"]  # 256

        model = build_model(mp, stage="DiT")
        model, *_ = load_checkpoint(model, None, ckpt_path,
                                    load_only_params=True, ignore_modules=[],
                                    is_distributed=False)
        for k in model:
            model[k].eval().to(device)
        model.cfm.estimator.setup_caches(max_batch_size=1, max_seq_length=8192)

        sp = cfg["preprocess_params"]["spect_params"]
        mel_fn_args = dict(
            n_fft=sp["n_fft"], win_size=sp["win_length"], hop_size=hop,
            num_mels=sp["n_mels"], sampling_rate=sr,
            fmin=sp.get("fmin", 0), fmax=None, center=False,
        )
        to_mel = lambda x: mel_spectrogram(x, **mel_fn_args)

        # ── BigVGAN vocoder ───────────────────────────────────────────────────
        bgvgan = bigvgan_module.BigVGAN.from_pretrained(
            mp.vocoder.name, use_cuda_kernel=False)
        bgvgan.remove_weight_norm()
        bgvgan = bgvgan.eval().to(device)

        # ── CAMPPlus speaker encoder ─────────────────────────────────────────
        cp_ckpt = load_custom_model_from_hf(
            "funasr/campplus", "campplus_cn_common.bin", config_filename=None)
        campplus = CAMPPlus(feat_dim=80, embedding_size=192)
        campplus.load_state_dict(torch.load(cp_ckpt, map_location="cpu"))
        campplus.eval().to(device)

        # ── Whisper content encoder ──────────────────────────────────────────
        wname   = mp.speech_tokenizer.name   # openai/whisper-small
        whisper = WhisperModel.from_pretrained(
            wname, torch_dtype=torch.float16).to(device)
        del whisper.decoder
        feat_ext = AutoFeatureExtractor.from_pretrained(wname)

        _MODELS = dict(
            model=model, bigvgan=bgvgan, campplus=campplus,
            whisper=whisper, feat_ext=feat_ext, to_mel=to_mel,
            sr=sr, hop=hop, device=device,
        )
        print("[voice_clone] models ready.", flush=True)
    return _MODELS


# ── audio helpers ─────────────────────────────────────────────────────────────
def convert_to_ref_wav(audio_path: str) -> str:
    """Convert any uploaded audio (m4a/mp3/caf/aac/…) to 16 kHz mono WAV."""
    out = tempfile.NamedTemporaryFile(
        suffix="_ref.wav", delete=False, prefix="bsay_ref_")
    out.close()
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", audio_path, "-ar", "16000", "-ac", "1", out.name],
        check=True,
    )
    return out.name


def save_voice_persistent(wav_path: str, slot: str = "user") -> str | None:
    """Copy ref WAV to /data/voices/<slot>.wav (persistent across restarts).
    Returns saved path, or None if /data is not available."""
    if _DATA_VOICES is None:
        return None
    _DATA_VOICES.mkdir(parents=True, exist_ok=True)
    dst = str(_DATA_VOICES / f"{slot}.wav")
    shutil.copy2(wav_path, dst)
    return dst


def load_voice_persistent(slot: str = "user") -> str | None:
    """Load previously saved ref WAV from /data. Returns path or None."""
    if _DATA_VOICES is None:
        return None
    p = _DATA_VOICES / f"{slot}.wav"
    return str(p) if p.exists() else None


# ── source pre-processing ─────────────────────────────────────────────────────
def _dynaudnorm_source(wav_path: str) -> str:
    """Apply per-frame dynamic normalization to espeak source.

    espeak-ng (especially bsystd/Lobanov) tends to ramp up gain across words,
    producing uneven loudness that carries into seed-vc output.
    dynaudnorm=f=200:g=15:p=0.95 smooths this out before voice conversion.
    Returns a new temp WAV path (or the original if ffmpeg is unavailable).
    """
    if not shutil.which("ffmpeg"):
        return wav_path
    out = tempfile.NamedTemporaryFile(
        suffix="_srcnorm.wav", delete=False, prefix="bsay_src_")
    out.close()
    try:
        # dynaudnorm: even out per-word amplitude ramp
        # NOTE: loudnorm removed — short espeak clips cause 2-pass distortion
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", wav_path,
             "-af", "dynaudnorm=f=200:g=15:p=0.95",
             out.name],
            check=True,
        )
        return out.name
    except Exception as e:
        print(f"[voice_clone] dynaudnorm skipped: {e}", flush=True)
        Path(out.name).unlink(missing_ok=True)
        return wav_path


# ── inference helpers ─────────────────────────────────────────────────────────
def _whisper_features(waves_16k, m: dict):
    import torch
    inp = m["feat_ext"](
        [waves_16k.squeeze(0).cpu().numpy()],
        return_tensors="pt", return_attention_mask=True, sampling_rate=16000,
    )
    feats = m["whisper"]._mask_input_features(
        inp.input_features, attention_mask=inp.attention_mask
    ).to(m["device"])
    with torch.no_grad():
        out = m["whisper"].encoder(
            feats.to(m["whisper"].encoder.dtype),
            head_mask=None, output_attentions=False,
            output_hidden_states=False, return_dict=True,
        )
    S = out.last_hidden_state.to(torch.float32)
    return S[:, : waves_16k.size(-1) // 320 + 1]


def _crossfade(c1: np.ndarray, c2: np.ndarray, ov: int) -> np.ndarray:
    fo = np.cos(np.linspace(0, np.pi / 2, ov)) ** 2
    fi = np.cos(np.linspace(np.pi / 2, 0, ov)) ** 2
    if len(c2) < ov:
        c2[:ov] = c2[:ov] * fi[:len(c2)] + (c1[-ov:] * fo)[:len(c2)]
    else:
        c2[:ov] = c2[:ov] * fi + c1[-ov:] * fo
    return c2


# ── main entry point ──────────────────────────────────────────────────────────
def clone_voice(
    source_wav: str,
    ref_wav: str,
    diffusion_steps: int = 5,
    inference_cfg_rate: float = 0.7,
) -> str:
    """
    Run seed-vc v1 voice conversion.

    source_wav : espeak 合成輸出（任何取樣率，內部自動 resample）
    ref_wav    : 參考音色（已轉換為 16 kHz mono WAV）
    Returns    : 輸出 WAV 路徑（loudnorm 正規化完畢）
    """
    import torch
    import torchaudio
    import librosa
    import soundfile as sf

    m      = _ensure_models()
    device = m["device"]
    sr     = m["sr"]    # 22050
    hop    = m["hop"]   # 256
    ovfl   = 16
    ovwl   = ovfl * hop
    mcw    = sr // hop * 30   # max context window in frames

    # Even out espeak per-word volume ramp before voice conversion
    normed_source = _dynaudnorm_source(source_wav)
    try:
        src_np = librosa.load(normed_source, sr=sr)[0]
    finally:
        if normed_source != source_wav:
            Path(normed_source).unlink(missing_ok=True)
    ref_np = librosa.load(ref_wav,    sr=sr)[0]
    src = torch.tensor(src_np).unsqueeze(0).float().to(device)
    ref = torch.tensor(ref_np[:sr * 25]).unsqueeze(0).float().to(device)

    src16 = torchaudio.functional.resample(src, sr, 16000)
    ref16 = torchaudio.functional.resample(ref, sr, 16000)
    S_alt = _whisper_features(src16, m)
    S_ori = _whisper_features(ref16, m)

    mel_s = m["to_mel"](src.float())
    mel_r = m["to_mel"](ref.float())
    tl  = torch.LongTensor([mel_s.size(2)]).to(device)
    tl2 = torch.LongTensor([mel_r.size(2)]).to(device)

    feat2 = torchaudio.compliance.kaldi.fbank(
        ref16, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat2 = feat2 - feat2.mean(dim=0, keepdim=True)
    style2 = m["campplus"](feat2.unsqueeze(0))

    with torch.no_grad():
        cond,       *_ = m["model"].length_regulator(
            S_alt, ylens=tl,  n_quantizers=3, f0=None)
        prompt_cond,*_ = m["model"].length_regulator(
            S_ori, ylens=tl2, n_quantizers=3, f0=None)

    max_sw = mcw - mel_r.size(2)
    done, chunks, prev = 0, [], None
    # fp32 on MPS/CPU to avoid half-precision distortion
    dtype = torch.float16 if device.type == "cuda" else torch.float32

    with torch.no_grad():
        while done < cond.size(1):
            cc   = cond[:, done : done + max_sw]
            last = done + max_sw >= cond.size(1)
            cat  = torch.cat([prompt_cond, cc], dim=1)
            with torch.autocast(device_type=device.type, dtype=dtype):
                vct = m["model"].cfm.inference(
                    cat,
                    torch.LongTensor([cat.size(1)]).to(device),
                    mel_r, style2, None, diffusion_steps,
                    inference_cfg_rate=inference_cfg_rate,
                )
                vct = vct[:, :, mel_r.size(-1):]
            wave = m["bigvgan"](vct.float()).squeeze()[None, :]  # (1, T)

            if done == 0 and last:
                chunks.append(wave[0].cpu().numpy())
                break
            elif done == 0:
                chunks.append(wave[0, :-ovwl].cpu().numpy())
                prev  = wave[0, -ovwl:]
                done += vct.size(2) - ovfl
            elif last:
                chunks.append(_crossfade(
                    prev.cpu().numpy(), wave[0].cpu().numpy(), ovwl))
                break
            else:
                chunks.append(_crossfade(
                    prev.cpu().numpy(), wave[0, :-ovwl].cpu().numpy(), ovwl))
                prev  = wave[0, -ovwl:]
                done += vct.size(2) - ovfl

    audio = np.concatenate(chunks)
    out = tempfile.NamedTemporaryFile(
        suffix="_clone.wav", delete=False, prefix="bsay_clone_")
    out.close()
    sf.write(out.name, audio, sr)

    # loudnorm（與 basaytts-space 一致）
    if shutil.which("ffmpeg"):
        tmp = out.name + ".norm.wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-i", out.name, "-af", LOUDNORM_FILTER, tmp],
                check=True,
            )
            Path(tmp).replace(out.name)
        except Exception as e:
            print(f"[voice_clone] loudnorm skipped: {e}", flush=True)
    return out.name
