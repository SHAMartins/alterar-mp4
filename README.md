# Compactador de Vídeos

Reduz a resolução e o tamanho de vídeos MP4 para anexar em sistemas web com limite de upload. Usa FFmpeg com H.264 e AAC, e tem interface gráfica e linha de comando.

## Funcionalidades

- Anexa vários vídeos de uma vez ou uma pasta inteira (também dá para arrastar e soltar)
- Resolução máxima configurável (1080p, 720p, 480p…), mantendo a proporção do vídeo
- Compressão H.264 (`libx264`) com CRF ajustável e áudio AAC
- Barra de progresso por arquivo e geral, além da redução percentual de cada vídeo
- Não sobrescreve os arquivos originais
- Executável único para Windows, com o FFmpeg embutido (não precisa instalar nada)

## Uso

### Executável (Windows)
Baixe o `CompactadorDeVideos.exe` na página de [Releases](../../releases) e abra-o com dois cliques.

### Interface gráfica (Python)
```bash
pip install tkinterdnd2   # opcional: arrastar e soltar
python interface_compactador.py
```

### Linha de comando
```bash
python compactar_videos.py -i ./originais -o ./compactados --altura 720 --crf 26
```

| Opção | Padrão | Descrição |
|---|---|---|
| `-i`, `--entrada` | — | Pasta com os vídeos originais |
| `-o`, `--saida` | — | Pasta de destino |
| `--altura` | `720` | Altura máxima em pixels |
| `--crf` | `26` | Qualidade (menor = melhor/maior; recomendado 23–28) |
| `--preset` | `medium` | Velocidade x compressão do x264 |
| `--audio` | `128k` | Bitrate do áudio AAC |
| `-r` | — | Inclui subpastas |
| `--sobrescrever` | — | Reprocessa arquivos que já existem no destino |

Para rodar via Python é preciso ter o [FFmpeg](https://ffmpeg.org/download.html) instalado e no PATH (no Windows: `winget install --id Gyan.FFmpeg -e`).

## Gerar o executável

```bash
python -m venv .venv-build
.venv-build\Scripts\python.exe -m pip install pyinstaller imageio-ffmpeg tkinterdnd2
.venv-build\Scripts\python.exe build_exe.py
```

O arquivo é gerado em `dist\CompactadorDeVideos.exe`.

## Licença

O executável inclui o [FFmpeg](https://ffmpeg.org), distribuído sob a licença GPL.
