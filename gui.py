import tkinter as tk
from tkinter import ttk
import threading
from Pyro5.api import *
import time
from queue import Queue

RELEASED = 0
WANTED = 1
HELD = 2

MAX_ACCESS_TIME = 10  # Tempo máximo de acesso ao recurso em segundos

class NodeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Sistema Distribuído - Nó Peer-to-Peer")
        self.root.geometry("600x500")
        self.root.configure(bg='#f0f0f0')

        # Variáveis
        self.node = None
        self.running = False

        # Frames
        self.frame_top = tk.Frame(root, bg='#f0f0f0')
        self.frame_top.pack(pady=10)

        self.frame_middle = tk.Frame(root, bg='#f0f0f0')
        self.frame_middle.pack(pady=10)

        self.frame_bottom = tk.Frame(root, bg='#f0f0f0')
        self.frame_bottom.pack(pady=10)

        # Nome do nó
        tk.Label(self.frame_top, text="Nome do Nó:", bg='#f0f0f0', font=('Arial', 12)).grid(row=0, column=0, padx=5)
        self.name_entry = tk.Entry(self.frame_top, font=('Arial', 12))
        self.name_entry.grid(row=0, column=1, padx=5)
        self.start_button = tk.Button(self.frame_top, text="Iniciar Nó", command=self.start_node, bg='#4CAF50', fg='white', font=('Arial', 10))
        self.start_button.grid(row=0, column=2, padx=5)

        # Status
        tk.Label(self.frame_middle, text="Status:", bg='#f0f0f0', font=('Arial', 12)).grid(row=0, column=0, padx=5)
        self.status_label = tk.Label(self.frame_middle, text="Não iniciado", bg='#f0f0f0', font=('Arial', 12, 'bold'), fg='red')
        self.status_label.grid(row=0, column=1, padx=5)

        # Pedir acesso
        self.request_button = tk.Button(self.frame_middle, text="Pedir Acesso", command=self.request_access, bg='#2196F3', fg='white', font=('Arial', 10), state='disabled')
        self.request_button.grid(row=0, column=2, padx=5)

        # Lista de nós ativos
        tk.Label(self.frame_middle, text="Nós Ativos:", bg='#f0f0f0', font=('Arial', 12)).grid(row=1, column=0, padx=5, pady=10)
        self.nodes_listbox = tk.Listbox(self.frame_middle, height=5, width=50, font=('Arial', 10))
        self.nodes_listbox.grid(row=1, column=1, columnspan=2, padx=5)

        # Logs
        tk.Label(self.frame_bottom, text="Logs:", bg='#f0f0f0', font=('Arial', 12)).pack(anchor='w', padx=5)
        self.log_text = tk.Text(self.frame_bottom, height=10, width=70, font=('Arial', 10))
        self.log_text.pack(padx=5, pady=5)

    def log(self, message):
        self.log_text.insert(tk.END, message + '\n')
        self.log_text.see(tk.END)

    def start_node(self):
        name = self.name_entry.get().strip()
        if not name:
            self.log("Erro: Nome do nó não pode ser vazio.")
            return

        self.node = Node(name)
        self.running = True
        self.status_label.config(text="Iniciado", fg='green')
        self.request_button.config(state='normal')
        self.start_button.config(state='disabled')
        self.log(f"Nó {name} iniciado.")

        # Iniciar thread para o daemon
        threading.Thread(target=self.run_daemon, daemon=True).start()

        # Atualizar lista de nós
        self.update_nodes_list()

    def run_daemon(self):
        try:
            self.node.run()
        except Exception as e:
            self.log(f"Erro no daemon: {e}")

    def request_access(self):
        if self.node:
            threading.Thread(target=self.node.pedir_acesso, args=(time.time(), self.node.uri), daemon=True).start()
            self.log("Pedido de acesso enviado.")
            self.update_status()

    def update_status(self):
        if self.node:
            status = self.node.estado
            if status == RELEASED:
                self.status_label.config(text="RELEASED", fg='green')
            elif status == WANTED:
                self.status_label.config(text="WANTED", fg='orange')
            elif status == HELD:
                self.status_label.config(text="HELD", fg='blue')

    def update_nodes_list(self):
        if self.node:
            self.nodes_listbox.delete(0, tk.END)
            for node in self.node.nodes_ativos:
                self.nodes_listbox.insert(tk.END, str(node))

class Node(object):
    def __init__(self, name):
        self.nome = name
        self.estado = RELEASED
        self.daemon = Daemon()
        self.uri = self.daemon.register(self)
        self.nodes_ativos = []
        self.fila_pedidos = Queue()
        self.timer = None

        ns = locate_ns()
        ns.register(f"{self.nome}", self.uri)

        lista = ns.list()
        for e in lista:
            if str(e) != "Pyro.NameServer" and str(e) != self.nome:
                proxy_no_ativo = Proxy(lista[e])
                self.nodes_ativos.append(proxy_no_ativo)

    def pedir_acesso(self, tempo, uri):
        self.estado = WANTED
        mensagem = (tempo, uri)
        count = 0

        while count < len(self.nodes_ativos):
            for e in self.nodes_ativos:
                try:
                    if e.ceder_acesso(mensagem):
                        count += 1
                except:
                    pass

        self.estado = HELD
        self.timer = threading.Timer(MAX_ACCESS_TIME, self.liberar_acesso)
        self.timer.start()

    @expose
    @oneway
    def ceder_acesso(self, mensagem):
        if self.estado == RELEASED:
            return True
        else:
            self.fila_pedidos.put(mensagem)
            return False

    def liberar_acesso(self):
        self.estado = RELEASED
        self.timer = None

    @expose
    @oneway
    def enviar_heartbeat(self):
        return True

    def gerencia_heartbeat(self):
        time.sleep(2)
        nodes_copia = self.nodes_ativos[:]
        for e in nodes_copia:
            try:
                e.enviar_heartbeat()
            except:
                if e in self.nodes_ativos:
                    self.nodes_ativos.remove(e)

    def run(self):
        heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat_thread.start()
        self.daemon.requestLoop()

    def heartbeat_loop(self):
        while True:
            try:
                self.gerencia_heartbeat()
            except Exception as e:
                pass
            time.sleep(1)

if __name__ == "__main__":
    root = tk.Tk()
    app = NodeGUI(root)
    root.mainloop()