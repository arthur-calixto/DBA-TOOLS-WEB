"""Explicit local lab input, never persisted or accepted from protocol links."""
def open_dialog(root, executable):
    import queue
    import threading
    import tkinter as tk
    from tkinter import ttk
    from launcher.core import LauncherError
    from launcher.putty_lab import launch_lab

    dialog = tk.Toplevel(root)
    dialog.title('SSH de laboratório — somente credenciais sintéticas')
    dialog.transient(root)
    panel = ttk.Frame(dialog, padding=18)
    panel.pack(fill='both', expand=True)
    panel.columnconfigure(1, weight=1)
    values = {}
    for row, (name, label, default) in enumerate([
            ('host', 'Host de laboratório', '127.0.0.1'), ('port', 'Porta', '65022'),
            ('username', 'Usuário sintético', 'launcher_lab'),
            ('fingerprint', 'Fingerprint SHA256 confiável', ''),
            ('password', 'Senha sintética (somente memória)', '')]):
        ttk.Label(panel, text=label).grid(row=row, column=0, sticky='w', padx=(0,12), pady=6)
        values[name] = tk.StringVar(value=default)
        ttk.Entry(panel, textvariable=values[name], width=52,
                  show='*' if name == 'password' else '').grid(row=row, column=1, sticky='ew', pady=6)
    notice = tk.StringVar(value='Não use senhas reais. Obtenha o fingerprint pelo console do laboratório.')
    ttk.Label(panel, textvariable=notice, wraplength=620).grid(row=5, column=0, columnspan=2, pady=12)
    results = queue.Queue()
    running = False

    def poll():
        nonlocal running
        try:
            message = results.get_nowait()
        except queue.Empty:
            dialog.after(100, poll)
            return
        running = False
        submit.configure(state='normal')
        notice.set(message)

    def start():
        nonlocal running
        if running:
            return
        try:
            port = int(values['port'].get())
        except ValueError:
            notice.set('Porta inválida.')
            return
        fields = [values[k].get() for k in ('host', 'username', 'fingerprint', 'password')]
        values['password'].set('')
        running = True
        submit.configure(state='disabled')
        notice.set('Abrindo PuTTY e entregando a senha pelo canal local…')

        def worker():
            try:
                launch_lab(executable, fields[0], port, fields[1], fields[2], fields[3])
                results.put('Senha entregue ao PuTTY; confirme o shell no laboratório. '
                            'Access denied: autenticação recusada. Erro de rede: servidor indisponível. '
                            'Não redigite a senha; encerre a tentativa e revise os dados.')
            except LauncherError as error:
                results.put(str(error))
            except Exception:
                results.put('Falha local no teste; verifique a instalação do Launcher.')
            finally:
                fields.clear()
        threading.Thread(target=worker, daemon=True).start()
        dialog.after(100, poll)

    submit = ttk.Button(panel, text='Abrir SSH com senha sintética', command=start)
    submit.grid(row=6, column=0, columnspan=2, sticky='e')
    dialog.protocol('WM_DELETE_WINDOW', lambda: None if running else dialog.destroy())
