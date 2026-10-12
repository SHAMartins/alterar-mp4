#!/usr/bin/env python3
"""
Interface gráfica para o compactador de vídeos.

Use os botões para anexar vídeos ou uma pasta (ou arraste os arquivos para a lista,
se o pacote opcional `tkinterdnd2` estiver instalado). Depois ajuste as opções e
clique em "Compactar".

Executar:
    python interface_compactador.py
"""

import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from compactar_videos import FFMPEG, formatar_mb, montar_comando

try:  # arrastar e soltar é opcional
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    TkinterDnD = None

EXTENSOES = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".wmv"}
PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
           "medium", "slow", "slower", "veryslow"]
# No Windows, evita que uma janela de console pisque a cada chamada do FFmpeg.
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def duracao(video: Path) -> float:
    """Duração do vídeo em segundos (0 se não for possível descobrir)."""
    try:
        r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(video)], capture_output=True,
                           text=True, errors="replace", timeout=30, creationflags=SEM_JANELA)
        h, m, seg = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr).groups()
        return int(h) * 3600 + int(m) * 60 + float(seg)
    except Exception:
        return 0.0


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Compactador de Vídeos")
        root.geometry("860x680")
        root.minsize(720, 560)

        self.arquivos: dict[str, Path] = {}   # id da linha na lista -> caminho do vídeo
        self.fila: queue.Queue = queue.Queue()  # mensagens da thread de trabalho para a interface
        self.cancelar = threading.Event()
        self.processo = None
        self.ultima_saida = None
        self.trabalhando = False

        self._montar_ui()
        root.after(100, self._ler_fila)

    # ------------------------------------------------------------------ UI
    def _montar_ui(self):
        pad = {"padx": 10, "pady": 5}

        # Botões de ação ficam embaixo e são empacotados primeiro para nunca sumirem.
        acoes = ttk.Frame(self.root)
        acoes.pack(side="bottom", fill="x", padx=10, pady=(5, 10))
        self.btn_compactar = ttk.Button(acoes, text="▶  Compactar", command=self.iniciar)
        self.btn_compactar.pack(side="right")
        self.btn_cancelar = ttk.Button(acoes, text="Cancelar", command=self.parar, state="disabled")
        self.btn_cancelar.pack(side="right", padx=5)
        ttk.Button(acoes, text="Abrir pasta de destino", command=self.abrir_destino).pack(side="left")

        # Lista de vídeos
        frm = ttk.LabelFrame(self.root, text="Vídeos anexados")
        frm.pack(fill="both", expand=True, **pad)

        barra = ttk.Frame(frm)
        barra.pack(fill="x", padx=5, pady=5)
        self.btn_add = ttk.Button(barra, text="📎  Anexar arquivos…", command=self.add_arquivos)
        self.btn_add.pack(side="left")
        self.btn_pasta = ttk.Button(barra, text="📁  Anexar pasta…", command=self.add_pasta)
        self.btn_pasta.pack(side="left", padx=5)
        self.btn_remover = ttk.Button(barra, text="Remover selecionados", command=self.remover)
        self.btn_remover.pack(side="left")
        self.btn_limpar = ttk.Button(barra, text="Limpar lista", command=self.limpar)
        self.btn_limpar.pack(side="left", padx=5)
        self.lbl_contagem = ttk.Label(barra, text="")
        self.lbl_contagem.pack(side="right")

        lista = ttk.Frame(frm)
        lista.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        self.tree = ttk.Treeview(lista, columns=("tamanho", "status"), show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text="Arquivo")
        self.tree.heading("tamanho", text="Tamanho")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=420)
        self.tree.column("tamanho", width=100, anchor="e")
        self.tree.column("status", width=200)
        self.tree.tag_configure("ok", foreground="#1a7f37")
        self.tree.tag_configure("erro", foreground="#cf222e")
        self.tree.tag_configure("aviso", foreground="#9a6700")
        sb = ttk.Scrollbar(lista, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda e: self.remover())

        if TkinterDnD:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._soltar)
            dica = "Dica: você também pode arrastar vídeos ou pastas para esta lista."
        else:
            dica = "Dica: instale 'tkinterdnd2' para poder arrastar arquivos para a lista."
        ttk.Label(frm, text=dica, foreground="gray").pack(anchor="w", padx=5, pady=(0, 5))

        # Configurações
        cfg = ttk.LabelFrame(self.root, text="Configurações")
        cfg.pack(fill="x", **pad)
        cfg.columnconfigure(1, weight=1)

        ttk.Label(cfg, text="Pasta de destino:").grid(row=0, column=0, sticky="w", padx=5, pady=4)
        self.var_saida = tk.StringVar()
        self.ent_saida = ttk.Entry(cfg, textvariable=self.var_saida)
        self.ent_saida.grid(row=0, column=1, columnspan=6, sticky="ew", padx=5)
        self.btn_saida = ttk.Button(cfg, text="Escolher…", command=self.escolher_saida)
        self.btn_saida.grid(row=0, column=7, padx=5)
        ttk.Label(cfg, text="Vazio = cria a subpasta \"compactados\" ao lado de cada vídeo original.",
                  foreground="gray").grid(row=1, column=1, columnspan=7, sticky="w", padx=5)

        opcoes = ttk.Frame(cfg)
        opcoes.grid(row=2, column=0, columnspan=8, sticky="w", padx=5, pady=6)
        self.var_altura = tk.StringVar(value="720")
        self.var_crf = tk.StringVar(value="26")
        self.var_preset = tk.StringVar(value="medium")
        self.var_audio = tk.StringVar(value="128k")

        ttk.Label(opcoes, text="Resolução máx. (altura):").pack(side="left")
        self.cmb_altura = ttk.Combobox(opcoes, textvariable=self.var_altura, width=6,
                                       values=["1080", "720", "480", "360"])
        self.cmb_altura.pack(side="left", padx=(4, 16))
        ttk.Label(opcoes, text="Qualidade (CRF):").pack(side="left")
        self.spn_crf = ttk.Spinbox(opcoes, textvariable=self.var_crf, from_=18, to=35, width=4)
        self.spn_crf.pack(side="left", padx=(4, 16))
        ttk.Label(opcoes, text="Velocidade:").pack(side="left")
        self.cmb_preset = ttk.Combobox(opcoes, textvariable=self.var_preset, values=PRESETS,
                                       width=10, state="readonly")
        self.cmb_preset.pack(side="left", padx=(4, 16))
        ttk.Label(opcoes, text="Áudio AAC:").pack(side="left")
        self.cmb_audio = ttk.Combobox(opcoes, textvariable=self.var_audio, width=6,
                                      values=["64k", "96k", "128k", "192k"], state="readonly")
        self.cmb_audio.pack(side="left", padx=4)
        ttk.Label(cfg, text="CRF menor = mais qualidade e arquivo maior (recomendado 23 a 28).",
                  foreground="gray").grid(row=3, column=0, columnspan=8, sticky="w", padx=5, pady=(0, 5))

        # Progresso
        prog = ttk.LabelFrame(self.root, text="Progresso")
        prog.pack(fill="x", **pad)
        prog.columnconfigure(1, weight=1)
        self.lbl_status = ttk.Label(prog, text="Pronto. Anexe os vídeos para começar.")
        self.lbl_status.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=(4, 2))
        ttk.Label(prog, text="Arquivo atual:").grid(row=1, column=0, sticky="w", padx=5)
        self.pb_arquivo = ttk.Progressbar(prog, maximum=100)
        self.pb_arquivo.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        ttk.Label(prog, text="Total:").grid(row=2, column=0, sticky="w", padx=5)
        self.pb_total = ttk.Progressbar(prog, maximum=100)
        self.pb_total.grid(row=2, column=1, sticky="ew", padx=5, pady=(2, 6))

        # Log
        logf = ttk.LabelFrame(self.root, text="Log")
        logf.pack(fill="x", **pad)
        self.txt_log = tk.Text(logf, height=6, state="disabled", wrap="word", font=("Consolas", 9))
        sb_log = ttk.Scrollbar(logf, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb_log.set)
        self.txt_log.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        sb_log.pack(side="right", fill="y", pady=5)
        self.txt_log.tag_configure("ok", foreground="#1a7f37")
        self.txt_log.tag_configure("erro", foreground="#cf222e")
        self.txt_log.tag_configure("aviso", foreground="#9a6700")

        # Controles bloqueados durante a compactação
        self._controles = [self.btn_add, self.btn_pasta, self.btn_remover, self.btn_limpar,
                           self.btn_compactar, self.ent_saida, self.btn_saida, self.cmb_altura,
                           self.spn_crf, self.cmb_preset, self.cmb_audio]
        self._atualizar_contagem()

    def _log(self, texto, tag=None):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", texto + "\n", tag)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_trabalhando(self, ativo: bool):
        for w in self._controles:
            if w in (self.cmb_preset, self.cmb_audio):
                w.configure(state="disabled" if ativo else "readonly")
            else:
                w.configure(state="disabled" if ativo else "normal")
        self.btn_cancelar.configure(state="normal" if ativo else "disabled")
        self.trabalhando = ativo

    def _atualizar_contagem(self):
        total = sum(p.stat().st_size for p in self.arquivos.values() if p.exists())
        n = len(self.arquivos)
        self.lbl_contagem.configure(text=f"{n} vídeo(s) — {formatar_mb(total)}" if n else "Nenhum vídeo")

    # ------------------------------------------------------- lista de vídeos
    def add_arquivos(self):
        caminhos = filedialog.askopenfilenames(
            title="Selecione os vídeos",
            filetypes=[("Vídeos MP4", "*.mp4"),
                       ("Outros vídeos", "*.mov *.mkv *.avi *.m4v *.wmv"),
                       ("Todos os arquivos", "*.*")])
        self._adicionar(caminhos)

    def add_pasta(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta com os vídeos")
        if pasta:
            self._adicionar([pasta])

    def _soltar(self, evento):
        if not getattr(self, "trabalhando", False):
            self._adicionar(self.root.tk.splitlist(evento.data))

    def _adicionar(self, caminhos):
        ja_anexados = set(self.arquivos.values())
        for c in caminhos:
            p = Path(c)
            if p.is_dir():
                self._adicionar(sorted(p.iterdir()))
                ja_anexados = set(self.arquivos.values())
                continue
            if not p.is_file() or p.suffix.lower() not in EXTENSOES:
                continue
            p = p.resolve()
            if p in ja_anexados:
                continue
            iid = self.tree.insert("", "end", text=p.name,
                                   values=(formatar_mb(p.stat().st_size), "Aguardando"))
            self.arquivos[iid] = p
            ja_anexados.add(p)
        self._atualizar_contagem()

    def remover(self):
        if getattr(self, "trabalhando", False):
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.arquivos.pop(iid, None)
        self._atualizar_contagem()

    def limpar(self):
        self.tree.delete(*self.tree.get_children())
        self.arquivos.clear()
        self._atualizar_contagem()

    def escolher_saida(self):
        pasta = filedialog.askdirectory(title="Pasta onde salvar os vídeos compactados")
        if pasta:
            self.var_saida.set(pasta)

    def abrir_destino(self):
        if self.var_saida.get().strip():
            pasta = Path(self.var_saida.get().strip())
        elif self.ultima_saida:
            pasta = self.ultima_saida
        elif self.arquivos:
            pasta = next(iter(self.arquivos.values())).parent / "compactados"
        else:
            return
        if not pasta.exists():
            messagebox.showinfo("Pasta de destino", f"A pasta ainda não existe:\n{pasta}")
            return
        if sys.platform == "win32":
            os.startfile(pasta)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(pasta)])

    # ------------------------------------------------------------ execução
    def iniciar(self):
        if not self.arquivos:
            messagebox.showinfo("Nenhum vídeo", "Anexe pelo menos um vídeo antes de compactar.")
            return
        if FFMPEG is None:
            messagebox.showerror("FFmpeg não encontrado",
                                 "O FFmpeg não está instalado ou não está no PATH.\n\n"
                                 "No Windows, instale com:\nwinget install --id Gyan.FFmpeg -e\n\n"
                                 "Depois feche e abra este programa novamente.")
            return
        try:
            altura = int(self.var_altura.get())
            crf = int(self.var_crf.get())
            if altura < 144 or not 0 <= crf <= 51:
                raise ValueError
        except ValueError:
            messagebox.showerror("Configuração inválida",
                                 "A resolução deve ser um número (ex: 720) e o CRF deve ficar entre 0 e 51.")
            return

        cfg = {"altura": altura, "crf": crf, "preset": self.var_preset.get(),
               "audio": self.var_audio.get(), "saida": self.var_saida.get().strip()}
        itens = [(iid, self.arquivos[iid]) for iid in self.tree.get_children()]
        for iid, _ in itens:
            self.tree.set(iid, "status", "Aguardando")
            self.tree.item(iid, tags=())

        self.cancelar.clear()
        self.pb_arquivo["value"] = self.pb_total["value"] = 0
        self._set_trabalhando(True)
        self._log(f"Iniciando: {len(itens)} vídeo(s) | {altura}p | CRF {crf} | "
                  f"{cfg['preset']} | AAC {cfg['audio']}")
        threading.Thread(target=self._trabalhar, args=(itens, cfg), daemon=True).start()

    def parar(self):
        self.cancelar.set()
        self.btn_cancelar.configure(state="disabled")
        self.lbl_status.configure(text="Cancelando…")
        p = self.processo
        if p and p.poll() is None:
            p.terminate()

    @staticmethod
    def _destino(video: Path, saida: str, usados: set) -> Path:
        pasta = Path(saida) if saida else video.parent / "compactados"
        destino = pasta / f"{video.stem}.mp4"
        n = 2
        # Nunca sobrescreve o original nem outro vídeo gerado nesta mesma rodada.
        while destino.resolve() == video.resolve() or destino.resolve() in usados:
            destino = pasta / f"{video.stem}_compactado{'' if n == 2 else n - 1}.mp4"
            n += 1
        usados.add(destino.resolve())
        return destino

    def _trabalhar(self, itens, cfg):
        """Roda numa thread separada; só conversa com a interface através de self.fila."""
        ok = falhas = 0
        total_antes = total_depois = 0
        usados: set = set()
        n = len(itens)

        for i, (iid, video) in enumerate(itens):
            if self.cancelar.is_set():
                break
            self.fila.put(("inicio", iid, i, n, video.name))
            destino = self._destino(video, cfg["saida"], usados)
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                self._converter(video, destino, cfg, iid, i, n)
            except Exception as exc:
                if destino.exists():
                    destino.unlink()
                if self.cancelar.is_set():
                    self.fila.put(("status", iid, "Cancelado", "aviso"))
                    break
                falhas += 1
                self.fila.put(("status", iid, "Falha", "erro"))
                self.fila.put(("log", f"FALHA  {video.name}: {exc}", "erro"))
                continue

            antes, depois = video.stat().st_size, destino.stat().st_size
            reducao = (1 - depois / antes) * 100 if antes else 0
            ok += 1
            total_antes += antes
            total_depois += depois
            self.ultima_saida = destino.parent
            tag = "ok" if depois < antes else "aviso"
            self.fila.put(("status", iid, f"OK — {formatar_mb(depois)} (-{reducao:.0f}%)"
                           if depois < antes else f"Ficou maior: {formatar_mb(depois)}", tag))
            self.fila.put(("log", f"OK     {video.name}: {formatar_mb(antes)} -> "
                                  f"{formatar_mb(depois)} (redução de {reducao:.1f}%)", tag))
            if depois >= antes:
                self.fila.put(("log", "       O arquivo ficou maior/igual ao original; "
                                      "tente um CRF maior ou resolução menor.", "aviso"))

        self.fila.put(("fim", ok, falhas, total_antes, total_depois, self.cancelar.is_set()))

    def _converter(self, video, destino, cfg, iid, i, n):
        total = duracao(video)
        cmd = montar_comando(video, destino, cfg["altura"], cfg["crf"], cfg["preset"], cfg["audio"])
        cmd[1:1] = ["-progress", "pipe:1", "-nostats"]  # FFmpeg informa o andamento no stdout

        # stderr vai para um arquivo temporário para não travar o pipe com mensagens longas.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as erros:
            self.processo = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=erros,
                                             text=True, errors="replace", creationflags=SEM_JANELA)
            for linha in self.processo.stdout:
                chave, _, valor = linha.strip().partition("=")
                if chave in ("out_time_us", "out_time_ms") and total and valor.isdigit():
                    pct = min(100.0, int(valor) / 1_000_000 / total * 100)
                    self.fila.put(("progresso", iid, pct, i, n))
            codigo = self.processo.wait()
            self.processo = None
            erros.seek(0)
            mensagens = erros.read().strip().splitlines()

        if self.cancelar.is_set():
            raise RuntimeError("cancelado pelo usuário")
        if codigo != 0 or not destino.exists():
            raise RuntimeError(mensagens[-1] if mensagens else f"FFmpeg terminou com código {codigo}")

    def _ler_fila(self):
        try:
            while True:
                msg = self.fila.get_nowait()
                tipo = msg[0]
                if tipo == "inicio":
                    _, iid, i, n, nome = msg
                    self.tree.set(iid, "status", "Processando… 0%")
                    self.tree.see(iid)
                    self.lbl_status.configure(text=f"Compactando {i + 1} de {n}: {nome}")
                    self.pb_arquivo["value"] = 0
                    self.pb_total["value"] = i / n * 100
                elif tipo == "progresso":
                    _, iid, pct, i, n = msg
                    self.tree.set(iid, "status", f"Processando… {pct:.0f}%")
                    self.pb_arquivo["value"] = pct
                    self.pb_total["value"] = (i + pct / 100) / n * 100
                elif tipo == "status":
                    _, iid, texto, tag = msg
                    self.tree.set(iid, "status", texto)
                    self.tree.item(iid, tags=(tag,))
                elif tipo == "log":
                    self._log(msg[1], msg[2])
                elif tipo == "fim":
                    self._finalizar(*msg[1:])
        except queue.Empty:
            pass
        self.root.after(100, self._ler_fila)

    def _finalizar(self, ok, falhas, antes, depois, cancelado):
        self._set_trabalhando(False)
        if not cancelado:
            self.pb_arquivo["value"] = self.pb_total["value"] = 100
        resumo = f"{ok} sucesso(s), {falhas} falha(s)"
        if antes:
            resumo += (f"\nTotal: {formatar_mb(antes)} -> {formatar_mb(depois)} "
                       f"(redução de {(1 - depois / antes) * 100:.1f}%)")
        titulo = "Compactação cancelada" if cancelado else "Compactação concluída"
        self.lbl_status.configure(text=f"{titulo}: {resumo.splitlines()[0]}")
        self._log("=" * 50)
        self._log(f"{titulo}: {resumo}", "erro" if falhas else "ok")
        (messagebox.showwarning if falhas or cancelado else messagebox.showinfo)(titulo, resumo)


def main():
    if sys.platform == "win32":  # textos nítidos em telas com escala (125%, 150%…)
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
