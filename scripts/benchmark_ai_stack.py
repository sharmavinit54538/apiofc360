#!/usr/bin/env python3
"""
Hardware benchmark script for AI Voice+Video Interview stack.
Measures real performance numbers on this CPU-only server.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any

import httpx
import numpy as np

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings


def get_cpu_info() -> dict:
    """Get CPU info using Python."""
    import platform
    import psutil
    
    return {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "cpu_freq_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else "N/A",
        "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "ram_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
    }


async def check_ollama() -> dict:
    """Check Ollama availability and models."""
    result = {"available": False, "models": [], "host": settings.OLLAMA_HOST}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.OLLAMA_HOST}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                result["available"] = True
                result["models"] = [m["name"] for m in data.get("models", [])]
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def benchmark_whisper(model_name: str, audio_path: Path, cpu_threads: int) -> dict:
    """Benchmark faster-whisper model."""
    try:
        from faster_whisper import WhisperModel
        
        # Load model
        load_start = time.perf_counter()
        model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads,
            num_workers=1,
        )
        load_time = time.perf_counter() - load_start
        
        # Transcribe
        transcribe_start = time.perf_counter()
        segments, info = model.transcribe(
            str(audio_path),
            beam_size=1,
            language=None,  # auto-detect
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=800),
        )
        # Consume segments
        text = " ".join([seg.text for seg in segments])
        transcribe_time = time.perf_counter() - transcribe_start
        
        # Get audio duration
        with wave.open(str(audio_path), 'rb') as wf:
            audio_duration = wf.getnframes() / wf.getframerate()
        
        return {
            "model": model_name,
            "load_time_sec": round(load_time, 2),
            "transcribe_time_sec": round(transcribe_time, 2),
            "audio_duration_sec": round(audio_duration, 2),
            "real_time_factor": round(transcribe_time / audio_duration, 2) if audio_duration > 0 else None,
            "text_length": len(text),
            "language": info.language,
            "cpu_threads": cpu_threads,
        }
    except Exception as e:
        return {"model": model_name, "error": str(e)}


async def benchmark_piper(voice_name: str, text: str) -> dict:
    """Benchmark Piper TTS."""
    try:
        # Check if piper is available
        piper_bin = "piper.exe" if sys.platform == "win32" else "piper"
        
        # Try to find piper
        result = subprocess.run(["where" if sys.platform == "win32" else "which", piper_bin], 
                               capture_output=True, text=True)
        if result.returncode != 0:
            return {"voice": voice_name, "error": "Piper not installed"}
        
        # Check for voice model
        # Piper voices are typically in ~/.local/share/piper/voices/ or similar
        # For now, just test if we can run it
        
        # Create temp output
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            output_path = tmp.name
        
        start = time.perf_counter()
        proc = subprocess.run(
            [piper_bin, "--model", voice_name, "--output_file", output_path],
            input=text.encode(),
            capture_output=True,
            timeout=30,
        )
        synth_time = time.perf_counter() - start
        
        if proc.returncode != 0:
            return {"voice": voice_name, "error": proc.stderr.decode()}
        
        # Get audio duration
        with wave.open(output_path, 'rb') as wf:
            audio_duration = wf.getnframes() / wf.getframerate()
        
        os.unlink(output_path)
        
        return {
            "voice": voice_name,
            "synth_time_sec": round(synth_time, 3),
            "audio_duration_sec": round(audio_duration, 3),
            "real_time_factor": round(synth_time / audio_duration, 3) if audio_duration > 0 else None,
            "text_chars": len(text),
        }
    except Exception as e:
        return {"voice": voice_name, "error": str(e)}


async def benchmark_ollama(model_name: str, prompt: str = "Hello, how are you?") -> dict:
    """Benchmark Ollama model."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Check if model exists
            resp = await client.get(f"{settings.OLLAMA_HOST}/api/tags")
            models = [m["name"] for m in resp.json().get("models", [])]
            
            if model_name not in models:
                return {"model": model_name, "error": f"Model not found. Available: {models}"}
            
            # Warm-up
            await client.post(
                f"{settings.OLLAMA_HOST}/api/generate",
                json={"model": model_name, "prompt": "Hi", "stream": False, "options": {"num_predict": 10}},
                timeout=30.0,
            )
            
            # Benchmark: first token latency + tokens/sec
            start = time.perf_counter()
            first_token_time = None
            token_count = 0
            
            async with client.stream(
                "POST",
                f"{settings.OLLAMA_HOST}/api/generate",
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "num_predict": 100,
                        "temperature": 0.2,
                        "num_thread": getattr(settings, 'OLLAMA_NUM_PARALLEL', 4),
                    },
                },
                timeout=120.0,
            ) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if first_token_time is None:
                            first_token_time = time.perf_counter() - start
                        if "response" in data and data["response"]:
                            token_count += 1
                        if data.get("done"):
                            break
            
            total_time = time.perf_counter() - start
            
            return {
                "model": model_name,
                "first_token_latency_sec": round(first_token_time, 3) if first_token_time else None,
                "total_time_sec": round(total_time, 3),
                "tokens_generated": token_count,
                "tokens_per_sec": round(token_count / total_time, 2) if total_time > 0 else None,
                "prompt": prompt[:50],
            }
    except Exception as e:
        return {"model": model_name, "error": str(e)}


async def benchmark_insightface(model_name: str = "buffalo_s") -> dict:
    """Benchmark InsightFace model."""
    try:
        import insightface
        import cv2
        import numpy as np
        
        # Create test image
        test_img = np.random.randint(0, 255, (640, 480, 3), dtype=np.uint8)
        
        # Initialize model
        load_start = time.perf_counter()
        app = insightface.app.FaceAnalysis(name=model_name, providers=['CPUExecutionProvider'])
        app.prepare(ctx_id=0, det_size=(640, 640))
        load_time = time.perf_counter() - load_start
        
        # Run inference
        infer_start = time.perf_counter()
        faces = app.get(test_img)
        infer_time = time.perf_counter() - infer_start
        
        return {
            "model": model_name,
            "load_time_sec": round(load_time, 2),
            "inference_time_sec": round(infer_time, 4),
            "faces_detected": len(faces),
            "embedding_dim": faces[0].embedding.shape[0] if faces else None,
        }
    except Exception as e:
        return {"model": model_name, "error": str(e)}


def create_test_audio(duration_sec: float = 10.0, sample_rate: int = 16000) -> Path:
    """Create a test audio file with sine wave."""
    import tempfile
    
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec))
    # Mix of frequencies to simulate speech-like signal
    signal = (
        0.3 * np.sin(2 * np.pi * 200 * t) +
        0.2 * np.sin(2 * np.pi * 400 * t) +
        0.1 * np.sin(2 * np.pi * 800 * t)
    )
    # Add some noise
    signal += 0.05 * np.random.randn(len(signal))
    signal = np.clip(signal, -1, 1)
    signal_int16 = (signal * 32767).astype(np.int16)
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        output_path = Path(tmp.name)
    
    with wave.open(str(output_path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(signal_int16.tobytes())
    
    return output_path


async def main():
    print("=" * 70)
    print("HARDWARE BENCHMARK - AI Voice+Video Interview Stack")
    print("=" * 70)
    
    # CPU Info
    cpu_info = get_cpu_info()
    print("\n[CPU / SYSTEM INFO]")
    print("-" * 40)
    for k, v in cpu_info.items():
        print(f"  {k}: {v}")
    
    cpu_threads = cpu_info["cpu_count_logical"]
    print(f"\n  Using cpu_threads={cpu_threads} for benchmarks")
    
    # Ollama check
    print("\n[OLLAMA CHECK]")
    print("-" * 40)
    ollama_info = await check_ollama()
    print(f"  Host: {ollama_info['host']}")
    print(f"  Available: {ollama_info['available']}")
    if ollama_info["available"]:
        print(f"  Models: {ollama_info['models']}")
    else:
        print(f"  Error: {ollama_info.get('error', 'Unknown')}")
    
    # Create test audio
    print("\n[Creating test audio (10s, 16kHz mono)...]")
    audio_path = create_test_audio(10.0, 16000)
    print(f"  Created: {audio_path}")
    
    # Benchmark Whisper
    print("\n[WHISPER BENCHMARK (faster-whisper int8)]")
    print("-" * 40)
    whisper_models = ["tiny", "base", "small"]
    whisper_results = []
    
    for model_name in whisper_models:
        print(f"  Testing {model_name}...", end=" ", flush=True)
        result = await benchmark_whisper(model_name, audio_path, cpu_threads)
        whisper_results.append(result)
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"OK {result['transcribe_time_sec']}s (RTF: {result['real_time_factor']}x)")
    
    # Cleanup test audio
    audio_path.unlink(missing_ok=True)
    
    # Benchmark Piper TTS
    print("\n[PIPER TTS BENCHMARK]")
    print("-" * 40)
    test_text = "This is a test sentence for the interview system."
    # Note: Piper voices need to be downloaded separately
    print("  Note: Piper voices need to be installed separately.")
    print("  Available voices can be found at: https://github.com/rhasspy/piper/releases")
    piper_result = {"note": "Piper benchmark requires voice models to be installed"}
    
    # Benchmark Ollama
    print("\n[OLLAMA BENCHMARK]")
    print("-" * 40)
    # Use available models that are CPU-friendly (avoid 30B+ models)
    test_models = ["gemma:2b", "llama3:latest"]
    ollama_results = []
    
    if ollama_info["available"]:
        for model_name in test_models:
            if model_name in ollama_info["models"]:
                print(f"  Testing {model_name}...", end=" ", flush=True)
                result = await benchmark_ollama(model_name)
                ollama_results.append(result)
                if "error" in result:
                    print(f"ERROR: {result['error']}")
                else:
                    print(f"OK First token: {result['first_token_latency_sec']}s, {result['tokens_per_sec']} tok/s")
            else:
                print(f"  Skipping {model_name} (not installed)")
                ollama_results.append({"model": model_name, "error": "Not installed"})
    else:
        print("  Ollama not available, skipping")
    
    # Benchmark InsightFace
    print("\n[INSIGHTFACE BENCHMARK]")
    print("-" * 40)
    insightface_models = ["buffalo_s", "buffalo_sc"]
    insightface_results = []
    
    for model_name in insightface_models:
        print(f"  Testing {model_name}...", end=" ", flush=True)
        result = await benchmark_insightface(model_name)
        insightface_results.append(result)
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"OK Inference: {result['inference_time_sec']*1000:.1f}ms")
    
    # Summary Table
    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    
    print("\n[Whisper (10s audio, int8, beam_size=1):]")
    print(f"  {'Model':<10} {'Load(s)':<8} {'Transcribe(s)':<14} {'RTF':<6} {'Lang':<6}")
    for r in whisper_results:
        if "error" not in r:
            print(f"  {r['model']:<10} {r['load_time_sec']:<8} {r['transcribe_time_sec']:<14} {r['real_time_factor']:<6} {r['language']:<6}")
        else:
            print(f"  {r['model']:<10} ERROR: {r['error']}")
    
    print("\n[Ollama (100 tokens, temp=0.2):]")
    print(f"  {'Model':<15} {'First Token(s)':<15} {'Tokens/sec':<12} {'Total(s)':<10}")
    for r in ollama_results:
        if "error" not in r:
            print(f"  {r['model']:<15} {r['first_token_latency_sec']:<15} {r['tokens_per_sec']:<12} {r['total_time_sec']:<10}")
        else:
            print(f"  {r['model']:<15} ERROR: {r['error']}")
    
    print("\n[InsightFace (640x480 image):]")
    print(f"  {'Model':<12} {'Load(s)':<8} {'Infer(ms)':<12} {'Dim':<6}")
    for r in insightface_results:
        if "error" not in r:
            print(f"  {r['model']:<12} {r['load_time_sec']:<8} {r['inference_time_sec']*1000:<12.1f} {r['embedding_dim']:<6}")
        else:
            print(f"  {r['model']:<12} ERROR: {r['error']}")
    
    # Recommendations
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    
    # Whisper recommendation
    whisper_ok = [r for r in whisper_results if "error" not in r and r.get("real_time_factor", 99) < 0.5]
    if whisper_ok:
        best_whisper = min(whisper_ok, key=lambda x: x["transcribe_time_sec"])
        print(f"OK Whisper: Use '{best_whisper['model']}' (RTF: {best_whisper['real_time_factor']}x, {best_whisper['transcribe_time_sec']}s for 10s audio)")
    else:
        print("WARNING Whisper: No model meets RTF < 0.5x. Consider 'tiny' for speed.")
    
    # Ollama recommendation
    ollama_ok = [r for r in ollama_results if "error" not in r]
    if ollama_ok:
        best_ollama = max(ollama_ok, key=lambda x: x.get("tokens_per_sec", 0))
        print(f"OK Ollama: Use '{best_ollama['model']}' ({best_ollama['tokens_per_sec']} tok/s, first token: {best_ollama['first_token_latency_sec']}s)")
        print(f"   Set OLLAMA_NUM_PARALLEL=1, OLLAMA_MAX_LOADED_MODELS=1, OLLAMA_KEEP_ALIVE=30m")
    else:
        print("WARNING Ollama: No models available. Pull qwen2.5:3b or llama3.2:3b")
    
    # InsightFace recommendation
    insightface_ok = [r for r in insightface_results if "error" not in r]
    if insightface_ok:
        best_if = min(insightface_ok, key=lambda x: x["inference_time_sec"])
        print(f"OK InsightFace: Use '{best_if['model']}' ({best_if['inference_time_sec']*1000:.1f}ms per image)")
    else:
        print("WARNING InsightFace: Not available. Install insightface and download models.")
    
    print("\nNext Steps:")
    print("  1. Review benchmark results above")
    print("  2. Confirm model choices and disk/RAM requirements")
    print("  3. Approve to proceed with Step 1 (migrations + models)")
    
    # Save results
    results = {
        "cpu_info": cpu_info,
        "ollama": ollama_info,
        "whisper": whisper_results,
        "piper": piper_result,
        "ollama_bench": ollama_results,
        "insightface": insightface_results,
    }
    
    with open("benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to benchmark_results.json")


if __name__ == "__main__":
    asyncio.run(main())