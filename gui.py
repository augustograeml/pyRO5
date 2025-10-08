import tkinter as tk
from tkinter import ttk
import threading
import time

RELEASED = 0
WANTED = 1
HELD = 2
class NodeGUI:
    def __init__(self, root, node=None):
        self.root = root
        self.root.title("Sistema Distribuído - Nó Peer-to-Peer")
        self.root.geometry("600x500")
        self.root.configure(bg='#f0f0f0')

        # Variáveis
        self.node = node
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
        self.request_button.grid(row=0, column=3, padx=5)

         # Liberar acesso
        self.release_button = tk.Button(self.frame_middle, text="Liberar Acesso", command=self.release_access, bg="#F10B0B", fg='white', font=('Arial', 10), state='disabled')
        self.release_button.grid(row=1, column=3, padx=5)

        # Lista de nós ativos
        tk.Label(self.frame_middle, text="Nós Ativos:", bg='#f0f0f0', font=('Arial', 12)).grid(row=1, column=0, padx=5, pady=10)
        self.nodes_listbox = tk.Listbox(self.frame_middle, height=5, width=50, font=('Arial', 10))
        self.nodes_listbox.grid(row=1, column=1, columnspan=2, padx=5)

        # Logs
        tk.Label(self.frame_bottom, text="Logs:", bg='#f0f0f0', font=('Arial', 12)).pack(anchor='w', padx=5)
        self.log_text = tk.Text(self.frame_bottom, height=10, width=70, font=('Arial', 10))
        self.log_text.pack(padx=5, pady=5)

        if self.node is not None:
            self.name_entry.insert(0, getattr(self.node, 'nome', ''))
            self.name_entry.config(state='disabled')
            self.start_button.config(state='disabled')
            self.request_button.config(state='normal')
            self.release_button.config(state='normal')
            self.running = True
            self.node.set_logger(self.enqueue_log)
            
            threading.Thread(target=self.node.run, daemon=True).start()
            self.schedule_poll()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, message):
        self.log_text.insert(tk.END, message + '\n')
        self.log_text.see(tk.END)

    def enqueue_log(self, message: str):
        self.root.after(0, lambda: self.log(message))

    def start_node(self):
        from node import Node
        name = self.name_entry.get().strip()
        if not name:
            self.log("Erro: Nome do nó não pode ser vazio.")
            return
        
        self.node = Node(name)
        self.running = True
        self.status_label.config(text="Iniciado", fg='green')
        self.request_button.config(state='normal')
        self.name_entry.config(state='disabled')
        self.start_button.config(state='disabled')
        self.log(f"Nó {name} iniciado.")
        
        self.node.set_logger(self.enqueue_log)
        threading.Thread(target=self.node.run, daemon=True).start()

        self.update_nodes_list()
        self.schedule_poll()

    def request_access(self):
        if self.node:
            threading.Thread(target=self.node.pedir_acesso, args=(time.time(), self.node.uri), daemon=True).start()
            self.log("Pedido de acesso enviado.")
            self.update_status()

    def release_access(self):
        if self.node:
            threading.Thread(target=self.node.liberar_acesso, daemon=True).start()
            self.log("Liberando Acesso")
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
            for node in getattr(self.node, 'nodes_ativos', []):
                self.nodes_listbox.insert(tk.END, str(node))

    def schedule_poll(self):
        self.update_status()
        self.update_nodes_list()
        if self.running:
            self.root.after(500, self.schedule_poll)

    def on_close(self):
        try:
            if self.node:
                if self.node.estado == HELD:
                    self.node.liberar_acesso()
                self.node.unregister()    
            self.running = False
        finally:
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = NodeGUI(root)
    root.mainloop()