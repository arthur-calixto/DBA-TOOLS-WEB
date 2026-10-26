"""Entrada Windows, fonte ou PyInstaller. Nenhum serviço HTTP local."""
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launcher import __version__
from launcher.core import (LauncherError, TOOLS, DEMO_HOST, DEMO_PORT, config_path,
                           detect_tools, launch_demo, load_config, parse_uri,
                           save_config, validate_executable)
from launcher import protocol


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if os.name != 'nt':
        print('DBA-TOOLS Launcher: execute no Windows. Testes automatizados podem rodar no Linux.')
        return 1
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f'DBA-TOOLS Launcher {__version__} — PoC')
    root.geometry('780x540')
    root.minsize(650, 480)
    root.configure(background='#F3F6F8')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 11), background='#F3F6F8', foreground='#263746')
    style.configure('TButton', padding=(12, 8))
    style.configure('Title.TLabel', font=('Segoe UI', 18, 'bold'), foreground='#08469C')
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    frame.columnconfigure(1, weight=1)
    ttk.Label(frame, text='DBA-TOOLS Launcher', style='Title.TLabel').grid(row=0, column=0, columnspan=3, sticky='w')
    ttk.Label(frame, text='Ferramentas locais · PuTTY / SSH e WinSCP / SFTP').grid(row=1, column=0, columnspan=3, sticky='w', pady=(4,16))
    paths = {kind: tk.StringVar() for kind in TOOLS}
    status = tk.StringVar(value='Configure as ferramentas instaladas neste computador.')
    config = None

    def guarded(action):
        try:
            action()
        except LauncherError as error:
            status.set(str(error))
            messagebox.showerror('DBA-TOOLS Launcher', str(error), parent=root)
        except Exception:
            status.set('Falha local inesperada. Reabra o Launcher e revise a configuração.')
            messagebox.showerror('DBA-TOOLS Launcher', status.get(), parent=root)

    # Evita que Tkinter imprima traceback/argumentos de callbacks.
    root.report_callback_exception = lambda *_: messagebox.showerror(
        'DBA-TOOLS Launcher', 'Falha na interface local. Reabra o Launcher.', parent=root)

    def browse(kind):
        result = filedialog.askopenfilename(parent=root, title=f'Selecionar {TOOLS[kind][0]}',
                                           filetypes=[('Executável Windows', '*.exe')])
        if result:
            paths[kind].set(validate_executable(kind, result))

    for row, (kind, (label, _)) in enumerate(TOOLS.items(), start=2):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0,12), pady=6)
        ttk.Entry(frame, textvariable=paths[kind]).grid(row=row, column=1, sticky='ew', pady=6)
        ttk.Button(frame, text='Selecionar…', command=lambda k=kind: guarded(lambda: browse(k))).grid(row=row, column=2, padx=(10,0), pady=6)

    def detect():
        found = detect_tools()
        for kind, path in found.items():
            if not paths[kind].get():
                paths[kind].set(path)
        status.set('Detecção concluída. Confira os caminhos antes de salvar.' if found else
                   'Ferramentas não encontradas nas pastas padrão. Use Selecionar para instalações portáteis.')

    def save():
        if config is None:
            raise LauncherError('Diretório de configuração indisponível neste usuário.')
        save_config(config, {k: v.get() for k, v in paths.items() if v.get()})
        status.set('Caminhos salvos para este usuário. Nenhuma credencial é armazenada.')

    def diagnostic():
        lines = [f'Launcher {__version__} · Windows', 'Somente testes locais; integração com backend ainda não habilitada.']
        for kind, value in paths.items():
            try:
                validate_executable(kind, value.get())
                lines.append(f'{TOOLS[kind][0]}: arquivo presente e cabeçalho executável válido (assinatura não verificada).')
            except LauncherError as error:
                lines.append(str(error))
        lines.append(protocol.status(protocol.current_command()))
        messagebox.showinfo('Diagnóstico local', '\n\n'.join(lines), parent=root)

    def test(kind):
        validate_executable(kind, paths[kind].get())
        approved = messagebox.askokcancel('Confirmar teste local',
            f'Abrir {TOOLS[kind][0]} em {DEMO_HOST}:{DEMO_PORT}?\n\n'
            'Destino fictício no próprio computador. Sem serviço nessa porta, uma recusa de conexão é esperada. '
            'Não digite credenciais reais neste teste. Nenhuma conexão a cliente será configurada.', parent=root)
        if approved:
            launch_demo(kind, paths[kind].get(), confirmed=True)
            status.set(f'{TOOLS[kind][0]} iniciado. Confira a janela da ferramenta; isso não confirma autenticação.')

    toolbar = ttk.Frame(frame)
    toolbar.grid(row=4, column=0, columnspan=3, sticky='w', pady=12)
    for label, action in [('Detectar', detect), ('Salvar caminhos', save), ('Diagnóstico', diagnostic)]:
        ttk.Button(toolbar, text=label, command=lambda a=action: guarded(a)).pack(side='left', padx=(0,8))
    tests = ttk.Frame(frame)
    tests.grid(row=5, column=0, columnspan=3, sticky='w', pady=8)
    for kind in TOOLS:
        ttk.Button(tests, text='Testar '+TOOLS[kind][0], command=lambda k=kind: guarded(lambda: test(k))).pack(side='left', padx=(0,8))

    def laboratory():
        from launcher.lab_dialog import open_dialog
        validate_executable('ssh', paths['ssh'].get())
        open_dialog(root, paths['ssh'].get())

    ttk.Button(tests, text='SSH com senha sintética…', command=lambda: guarded(laboratory)).pack(side='left')

    def registration(remove=False):
        command = protocol.current_command()
        action = 'Remover' if remove else 'Registrar'
        if messagebox.askokcancel(action+' protocolo', action+' dbatools:// somente para o seu usuário Windows?', parent=root):
            (protocol.unregister if remove else protocol.register)(command)
            status.set(protocol.status(command))

    protocols = ttk.Frame(frame)
    protocols.grid(row=6, column=0, columnspan=3, sticky='w', pady=8)
    ttk.Button(protocols, text='Registrar dbatools://', command=lambda: guarded(registration)).pack(side='left', padx=(0,8))
    ttk.Button(protocols, text='Remover registro', command=lambda: guarded(lambda: registration(True))).pack(side='left')
    ttk.Label(frame, textvariable=status, wraplength=700).grid(row=7, column=0, columnspan=3, sticky='ew', pady=16)
    ttk.Label(frame, text='PoC local: navegador aceita somente demos; senha sintética apenas no formulário de laboratório.', wraplength=700).grid(row=8, column=0, columnspan=3, sticky='ew')
    frame.bind('<Configure>', lambda event: [child.configure(wraplength=max(300, event.width-40))
        for child in frame.winfo_children() if isinstance(child, ttk.Label) and str(child.cget('wraplength')) not in ('0', '')])

    try:
        config = config_path()
        for kind, value in load_config(config).items():
            paths[kind].set(value)
    except LauncherError as error:
        status.set(str(error))
    if args:
        try:
            if len(args) != 1:
                raise LauncherError('Argumentos inválidos. Abra o aplicativo sem argumentos para configurar.')
            kind = parse_uri(args[0])
        except LauncherError as error:
            messagebox.showerror('Link recusado', str(error), parent=root)
            root.destroy()
            return 2
        root.after(200, lambda: guarded(lambda: test(kind)))
    root.mainloop()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # Nunca imprimir URI, argv, conteúdo da configuração ou traceback.
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, 'Falha ao iniciar o Launcher. Verifique a instalação.', 'DBA-TOOLS Launcher', 0x10)
        raise SystemExit(1) from None
