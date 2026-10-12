#!/usr/bin/env python3
"""
Compacta vídeos MP4 em lote usando FFmpeg (H.264 + AAC).

Exemplo:
    python compactar_videos.py -i ./originais -o ./compactados --altura 720 --crf 26
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:  # tqdm é opcional
    tqdm = None

log = logging.getLogger("compactador")


def localizar_ffmpeg():
    """Procura o FFmpeg embutido no executável, ao lado do programa ou no PATH."""
    nome = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    pastas = [Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)),
              Path(sys.executable).resolve().parent]
    for pasta in pastas:
        if (pasta / nome).is_file():
            return str(pasta / nome)
    return shutil.which("ffmpeg")


FFMPEG = localizar_ffmpeg()


def formatar_mb(n_bytes: int) -> str:
    return f"{n_bytes / (1024 * 1024):.2f} MB"


def montar_comando(entrada: Path, saida: Path, altura: int, crf: int,
                   preset: str, audio_bitrate: str) -> list:
    # Limita a altura sem ampliar vídeos menores; largura proporcional e par (exigência do libx264).
    filtro = f"scale=-2:'min({altura},ih)'"
    return [
        FFMPEG or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(entrada),
        "-vf", filtro,
        "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
        "-pix_fmt", "yuv420p",            # máxima compatibilidade com players/navegadores
        "-c:a", "aac", "-b:a", audio_bitrate,
        "-movflags", "+faststart",        # permite iniciar a reprodução web antes do download completo
        str(saida),
    ]


def processar(entrada: Path, saida: Path, args) -> bool:
    cmd = montar_comando(entrada, saida, args.altura, args.crf, args.preset, args.audio)
    try:
        resultado = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except Exception as exc:
        log.error("FALHA  %s -> %s", entrada.name, exc)
        return False

    if resultado.returncode != 0 or not saida.exists():
        erro = resultado.stderr.strip().splitlines()
        log.error("FALHA  %s -> %s", entrada.name, erro[-1] if erro else "erro desconhecido")
        saida.unlink(missing_ok=True)
        return False

    antes, depois = entrada.stat().st_size, saida.stat().st_size
    reducao = (1 - depois / antes) * 100 if antes else 0
    log.info("OK     %s: %s -> %s (redução de %.1f%%)",
             entrada.name, formatar_mb(antes), formatar_mb(depois), reducao)
    if depois >= antes:
        log.warning("       %s ficou maior/igual ao original; tente um CRF maior ou menor resolução.",
                    entrada.name)
    return True


def main():
    p = argparse.ArgumentParser(description="Compacta vídeos MP4 em lote com FFmpeg.")
    p.add_argument("-i", "--entrada", required=True, type=Path, help="Pasta com os vídeos originais")
    p.add_argument("-o", "--saida", required=True, type=Path, help="Pasta onde salvar os compactados")
    p.add_argument("--altura", type=int, default=720,
                   help="Altura máxima em pixels (ex: 1080, 720, 480). Padrão: 720")
    p.add_argument("--crf", type=int, default=26,
                   help="Qualidade H.264: menor = melhor/maior arquivo (recomendado 23-28). Padrão: 26")
    p.add_argument("--preset", default="medium",
                   choices=["ultrafast", "superfast", "veryfast", "faster", "fast",
                            "medium", "slow", "slower", "veryslow"],
                   help="Velocidade x compressão do x264. Padrão: medium")
    p.add_argument("--audio", default="128k", help="Bitrate do áudio AAC. Padrão: 128k")
    p.add_argument("-r", "--recursivo", action="store_true", help="Incluir subpastas")
    p.add_argument("--sobrescrever", action="store_true", help="Reprocessar arquivos já existentes no destino")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    if FFMPEG is None:
        log.error("FFmpeg não encontrado no PATH. Instale-o e tente novamente.")
        sys.exit(1)
    if not args.entrada.is_dir():
        log.error("Pasta de entrada inválida: %s", args.entrada)
        sys.exit(1)

    padrao = "**/*" if args.recursivo else "*"
    videos = sorted(f for f in args.entrada.glob(padrao)
                    if f.is_file() and f.suffix.lower() == ".mp4")
    if not videos:
        log.warning("Nenhum arquivo .mp4 encontrado em %s", args.entrada)
        return

    args.saida.mkdir(parents=True, exist_ok=True)
    log.info("%d vídeo(s) encontrado(s). Altura máx: %dp | CRF: %d | Preset: %s | Áudio: AAC %s",
             len(videos), args.altura, args.crf, args.preset, args.audio)

    ok = falhas = pulados = 0
    total_antes = total_depois = 0
    iteravel = tqdm(videos, desc="Compactando", unit="vídeo") if tqdm else videos

    for video in iteravel:
        destino = args.saida / video.relative_to(args.entrada)
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.exists() and not args.sobrescrever:
            log.info("PULADO %s (já existe no destino)", video.name)
            pulados += 1
            continue
        if processar(video, destino, args):
            ok += 1
            total_antes += video.stat().st_size
            total_depois += destino.stat().st_size
        else:
            falhas += 1

    log.info("=" * 60)
    log.info("Concluído: %d sucesso(s), %d falha(s), %d pulado(s).", ok, falhas, pulados)
    if total_antes:
        log.info("Total: %s -> %s (redução de %.1f%%)", formatar_mb(total_antes),
                 formatar_mb(total_depois), (1 - total_depois / total_antes) * 100)
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
